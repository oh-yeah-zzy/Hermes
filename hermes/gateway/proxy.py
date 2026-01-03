"""
HTTP 代理转发模块

将请求转发到上游服务
"""

import asyncio
import time
from typing import Dict, Optional

import httpx
from fastapi import Request, Response

from hermes.core.config import settings
from hermes.core.logging import get_logger
from hermes.gateway.matcher import build_upstream_url
from hermes.schemas.route import RouteInfo, ServiceInstance

logger = get_logger("hermes.gateway.proxy")


# hop-by-hop 头（不应转发）
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


async def proxy_request(
    request: Request,
    route: RouteInfo,
    instance: ServiceInstance,
    forward_headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> Response:
    """
    代理转发请求到上游服务

    Args:
        request: FastAPI 请求对象
        route: 匹配的路由规则
        instance: 目标服务实例
        forward_headers: 要转发的请求头（如果为 None 则使用原始请求头）
        timeout: 超时时间（秒），默认使用配置
        max_retries: 最大重试次数，默认使用配置

    Returns:
        响应对象
    """
    start_time = time.time()

    # 使用配置的默认值
    if timeout is None:
        timeout = settings.proxy_timeout
    if max_retries is None:
        max_retries = settings.proxy_max_retries

    # 构建上游 URL
    upstream_url = build_upstream_url(
        route,
        request.url.path,
        request.url.query or "",
    )

    # 准备请求头
    if forward_headers is None:
        # 复制原始请求头
        headers = dict(request.headers)
        # 移除 hop-by-hop 头
        for header in HOP_BY_HOP_HEADERS:
            headers.pop(header, None)
        # 移除 host 头，让 httpx 自动设置
        headers.pop("host", None)
    else:
        headers = forward_headers.copy()

    # 读取请求体
    body = await request.body()

    # 发送请求
    status_code = 502
    response_headers: Dict[str, str] = {}
    response_body = b""
    error_message = None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout)
        ) as client:
            last_error = None

            # 支持重试
            for attempt in range(max_retries + 1):
                try:
                    upstream_response = await client.request(
                        method=request.method,
                        url=upstream_url,
                        headers=headers,
                        content=body,
                        follow_redirects=False,
                    )

                    status_code = upstream_response.status_code
                    response_headers = dict(upstream_response.headers)
                    response_body = upstream_response.content
                    break

                except httpx.RequestError as e:
                    last_error = e
                    if attempt < max_retries:
                        # 等待后重试
                        await asyncio.sleep(settings.proxy_retry_delay)
                        continue
                    raise

            # 如果所有重试都失败
            if last_error and status_code == 502:
                raise last_error

    except httpx.TimeoutException:
        status_code = 504
        error_message = "上游服务响应超时"
        response_body = b'{"error": "Gateway Timeout", "message": "Upstream service timed out"}'
        response_headers = {"content-type": "application/json"}

    except httpx.RequestError as e:
        status_code = 502
        error_message = f"上游服务连接失败: {str(e)}"
        response_body = b'{"error": "Bad Gateway", "message": "Upstream service connection failed"}'
        response_headers = {"content-type": "application/json"}

    # 计算延迟
    latency_ms = (time.time() - start_time) * 1000

    # 记录日志
    log_extra = {
        "method": request.method,
        "path": request.url.path,
        "upstream_url": upstream_url,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "target_service": instance.id,
    }

    if error_message:
        logger.warning(
            f"代理请求失败: {error_message}",
            extra={"extra_fields": log_extra},
        )
    else:
        logger.debug(
            f"代理请求完成: {request.method} {request.url.path} -> {status_code}",
            extra={"extra_fields": log_extra},
        )

    # 构建响应
    # 移除一些不需要转发的响应头
    for header in ["content-encoding", "content-length", "transfer-encoding"]:
        response_headers.pop(header, None)

    return Response(
        content=response_body,
        status_code=status_code,
        headers=response_headers,
    )
