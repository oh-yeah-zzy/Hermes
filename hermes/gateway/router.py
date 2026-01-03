"""
网关路由端点

处理所有需要代理转发的请求
"""

import time

from fastapi import APIRouter, Request, Response, HTTPException

from hermes.core.config import settings
from hermes.core.exceptions import RouteNotFoundError, NoAvailableInstanceError
from hermes.core.logging import get_logger
from hermes.gateway.matcher import route_matcher
from hermes.gateway.proxy import proxy_request
from hermes.gateway.balancer import LoadBalancerFactory, connection_tracker
from hermes.plugins.base import GatewayContext
from hermes.observability.metrics import metrics_collector

logger = get_logger("hermes.gateway.router")

router = APIRouter(tags=["网关"])


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,  # 不在 OpenAPI 文档中显示
)
async def gateway_proxy_handler(
    request: Request,
    path: str,
) -> Response:
    """
    网关代理端点

    处理所有需要代理转发的请求：
    1. 匹配路由规则
    2. 执行插件前置处理（限流、熔断等）
    3. 负载均衡选择实例
    4. 代理转发到上游服务
    5. 执行插件后置处理
    6. 记录指标

    注意：此路由必须在所有其他路由之后注册，作为兜底路由
    """
    start_time = time.time()

    # 获取请求 ID
    request_id = getattr(request.state, "request_id", "")
    full_path = f"/{path}"

    # 获取路由缓存和插件链
    route_cache = request.app.state.route_cache
    plugin_chain = request.app.state.plugin_chain

    # 匹配路由
    routes = route_cache.get_routes()
    route = route_matcher.match(routes, request.method, full_path)

    if route is None:
        logger.debug(
            f"路由不存在: {full_path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": full_path,
            },
        )
        raise HTTPException(status_code=404, detail="路由不存在")

    # 创建网关上下文
    ctx = GatewayContext(
        request=request,
        route=route,
        start_time=start_time,
        request_id=request_id,
    )

    try:
        # 执行插件前置处理
        ctx = await plugin_chain.execute_before(ctx)

        # 检查短路响应（限流、熔断等）
        if ctx.short_circuit_response is not None:
            return ctx.short_circuit_response

        # 负载均衡选择实例
        balancer = LoadBalancerFactory.create(settings.load_balance_strategy)
        instance = balancer.select([route.target_service])

        if instance is None:
            logger.warning(
                f"无可用服务实例: {route.target_service_id}",
                extra={
                    "request_id": request_id,
                    "target_service": route.target_service_id,
                },
            )
            raise HTTPException(status_code=503, detail="无可用服务实例")

        ctx.upstream_instance = instance

        # 追踪连接（用于 least_conn）
        await connection_tracker.acquire(instance)

        try:
            # 代理转发
            response = await proxy_request(
                request=request,
                route=route,
                instance=instance,
                forward_headers=ctx.metadata.get("forward_headers"),
            )

            # 执行插件后置处理
            response = await plugin_chain.execute_after(ctx, response)

            # 记录指标
            latency_ms = (time.time() - start_time) * 1000
            await metrics_collector.record(
                route_pattern=route.path_pattern,
                target_service=route.target_service_id,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )

            return response

        finally:
            # 释放连接
            await connection_tracker.release(instance)

    except HTTPException:
        raise
    except Exception as e:
        # 尝试让插件处理错误
        error_response = await plugin_chain.handle_error(ctx, e)
        if error_response:
            return error_response

        logger.error(
            f"网关处理错误: {type(e).__name__}: {e}",
            extra={
                "request_id": request_id,
                "path": full_path,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=502, detail="网关错误")
