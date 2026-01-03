"""
认证插件

负责在路由转发前检查用户认证状态

功能：
1. 检查路由的 auth_config 配置
2. 判断当前路径是否为公开路径
3. 检查 Authorization 头或 Cookie 中的令牌
4. 未认证时重定向到登录页或返回 401
5. 支持认证服务不可用时的降级策略
"""

import fnmatch
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from fastapi import Response
from fastapi.responses import JSONResponse, RedirectResponse

from hermes.core.config import settings
from hermes.core.logging import get_logger
from hermes.plugins.base import GatewayContext, GatewayPlugin
from hermes.schemas.route import AuthConfig

logger = get_logger("hermes.plugins.authentication")


class AuthenticationPlugin(GatewayPlugin):
    """
    认证插件

    优先级 50（在限流之前执行）

    工作流程：
    1. 检查路由是否配置了 auth_config
    2. 如果 require_auth=False，直接放行
    3. 检查当前路径是否在 public_paths 中
    4. 检查请求头或 Cookie 中的认证信息
    5. 未认证时根据配置决定重定向或返回 401
    """

    name = "authentication"
    priority = 50  # 在限流(100)之前执行

    def __init__(self):
        self.enabled = settings.auth_plugin_enabled
        # 用于检查认证服务可用性的超时时间
        self._auth_service_timeout = 5.0

    async def before_request(self, ctx: GatewayContext) -> GatewayContext:
        """
        请求前检查认证

        如果认证失败，设置 short_circuit_response
        """
        if not self.enabled:
            return ctx

        route = ctx.route
        if not route:
            return ctx

        # 获取认证配置
        auth_config = route.auth_config
        if not auth_config:
            return ctx

        # 如果不需要认证，直接放行
        if not auth_config.require_auth:
            return ctx

        # 检查是否是公开路径
        if self._is_public_path(ctx.path, auth_config):
            logger.debug(
                f"路径 {ctx.path} 在公开路径列表中，跳过认证",
                extra={"extra_fields": {"path": ctx.path}},
            )
            return ctx

        # 检查认证信息
        token = self._extract_token(ctx)
        if token:
            # 验证令牌（可选：调用认证服务验证）
            is_valid = await self._validate_token(ctx, token, auth_config)
            if is_valid:
                # 令牌有效，在 metadata 中标记已认证
                ctx.metadata["authenticated"] = True
                ctx.metadata["auth_token"] = token
                return ctx
            else:
                # 令牌无效
                logger.debug(
                    f"令牌验证失败: {ctx.path}",
                    extra={"extra_fields": {"path": ctx.path}},
                )

        # 未认证或令牌无效
        logger.debug(
            f"请求未认证: {ctx.path}",
            extra={
                "extra_fields": {
                    "path": ctx.path,
                    "client_ip": ctx.client_ip,
                }
            },
        )

        # 根据配置决定响应方式
        ctx.short_circuit_response = self._create_auth_response(ctx, auth_config)
        return ctx

    def _is_public_path(self, path: str, auth_config: AuthConfig) -> bool:
        """
        检查路径是否在公开路径列表中

        Args:
            path: 请求路径
            auth_config: 认证配置

        Returns:
            是否是公开路径
        """
        if not auth_config.public_paths:
            return False

        for pattern in auth_config.public_paths:
            # 支持通配符匹配
            # /api/docs/* 匹配 /api/docs/xxx
            # /api/docs/** 匹配 /api/docs/xxx/yyy
            if pattern.endswith("/**"):
                # 多级匹配
                prefix = pattern[:-3]
                if path == prefix or path.startswith(prefix + "/"):
                    return True
            elif pattern.endswith("/*"):
                # 单级匹配
                prefix = pattern[:-2]
                if path.startswith(prefix + "/"):
                    remaining = path[len(prefix) + 1 :]
                    if "/" not in remaining:
                        return True
            elif "*" in pattern:
                # 通用通配符匹配
                if fnmatch.fnmatch(path, pattern):
                    return True
            else:
                # 精确匹配
                if path == pattern:
                    return True

        return False

    def _extract_token(self, ctx: GatewayContext) -> Optional[str]:
        """
        从请求中提取认证令牌

        支持：
        1. Authorization: Bearer <token>
        2. Cookie: access_token=<token>
        3. X-Auth-Token: <token>

        Args:
            ctx: 网关上下文

        Returns:
            令牌字符串，如果没有则返回 None
        """
        request = ctx.request

        # 1. 检查 Authorization 头
        auth_header = request.headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
            # 也支持直接传递令牌
            return auth_header

        # 2. 检查 Cookie
        token_from_cookie = request.cookies.get("access_token")
        if token_from_cookie:
            return token_from_cookie

        # 3. 检查自定义头
        token_from_header = request.headers.get("X-Auth-Token")
        if token_from_header:
            return token_from_header

        return None

    async def _validate_token(
        self,
        ctx: GatewayContext,
        token: str,
        auth_config: AuthConfig,
    ) -> bool:
        """
        验证令牌有效性

        目前采用简单验证：只要令牌存在且不为空就认为有效
        未来可以扩展为调用认证服务验证

        Args:
            ctx: 网关上下文
            token: 令牌
            auth_config: 认证配置

        Returns:
            令牌是否有效
        """
        # 简单验证：令牌非空
        if not token or len(token) < 10:
            return False

        # 如果配置了认证服务，可以调用认证服务验证
        route = ctx.route
        if route and route.auth_service:
            auth_service = route.auth_service
            # 尝试调用认证服务的验证端点
            try:
                validate_url = f"{auth_service.base_url}/api/v1/auth/validate"
                async with httpx.AsyncClient(timeout=self._auth_service_timeout) as client:
                    response = await client.post(
                        validate_url,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if response.status_code == 200:
                        return True
                    elif response.status_code == 401:
                        return False
                    # 其他状态码视为认证服务异常
            except Exception as e:
                logger.warning(
                    f"调用认证服务失败: {e}",
                    extra={
                        "extra_fields": {
                            "auth_service_id": auth_service.id,
                            "error": str(e),
                        }
                    },
                )
                # 认证服务不可用时的降级策略
                if settings.auth_degrade_allow:
                    logger.warning(
                        "认证服务不可用，降级放行请求",
                        extra={
                            "extra_fields": {
                                "path": ctx.path,
                                "client_ip": ctx.client_ip,
                            }
                        },
                    )
                    return True
                else:
                    return False

        # 没有配置认证服务时，只要令牌存在就放行（透传模式）
        return True

    def _create_auth_response(
        self,
        ctx: GatewayContext,
        auth_config: AuthConfig,
    ) -> Response:
        """
        创建认证失败响应

        Args:
            ctx: 网关上下文
            auth_config: 认证配置

        Returns:
            认证失败响应
        """
        request = ctx.request

        # 判断是否是 API 请求（Accept: application/json 或 XHR）
        accept = request.headers.get("Accept", "")
        is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        is_api_request = "application/json" in accept or is_xhr

        if is_api_request:
            # API 请求返回 JSON 401
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "认证失败，请先登录",
                    "code": "AUTH_REQUIRED",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 网页请求重定向到登录页（必须由 ServiceAtlas 路由规则配置）
        login_redirect = auth_config.login_redirect
        if login_redirect:
            # 构造回调 URL，正确处理 login_redirect 本身带 query 的情况
            original_url = str(request.url)
            redirect_url = self._build_redirect_url(login_redirect, original_url)
            return RedirectResponse(
                url=redirect_url,
                status_code=302,
            )

        # 路由规则未配置 login_redirect 时返回 401
        return Response(
            status_code=401,
            content="Unauthorized - Please login. Route auth_config.login_redirect not configured.",
            headers={
                "WWW-Authenticate": "Bearer",
                "Content-Type": "text/plain; charset=utf-8",
            },
        )

    def _build_redirect_url(self, login_url: str, original_url: str) -> str:
        """
        构建登录重定向 URL

        正确处理 login_url 本身带 query 参数的情况

        Args:
            login_url: 登录页面 URL
            original_url: 原始请求 URL

        Returns:
            完整的重定向 URL
        """
        parsed = urlparse(login_url)

        # 解析现有的 query 参数
        existing_params = parse_qs(parsed.query, keep_blank_values=True)

        # 添加 redirect 参数（将列表转为单值）
        existing_params["redirect"] = [original_url]

        # 重新编码 query 参数
        new_query = urlencode(
            {k: v[0] if len(v) == 1 else v for k, v in existing_params.items()},
            doseq=True,
        )

        # 重新构建 URL
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
