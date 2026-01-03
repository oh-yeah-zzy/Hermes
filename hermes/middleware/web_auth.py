"""
Web 界面认证中间件

通过 Aegis 进行统一认证：
1. 检查 JWT token（cookie 或 Authorization header）
2. 如果未认证，重定向到 Aegis 登录页面
3. 登录成功后带 token 返回
"""

from typing import Optional
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from hermes.core.config import settings
from hermes.core.logging import get_logger

logger = get_logger("hermes.middleware.web_auth")

# JWT token 的 cookie 名称（与 Aegis 保持一致）
TOKEN_COOKIE_NAME = "access_token"


class WebAuthMiddleware(BaseHTTPMiddleware):
    """
    Web 界面认证中间件

    通过 Aegis 进行统一认证，未登录时重定向到 Aegis 登录页面
    """

    # 需要认证的路径前缀
    PROTECTED_PATHS = [
        "/",
        "/routes",
        "/routes/edit",
        "/metrics-view",
        "/api/stats",
        "/api/routes",
    ]

    # 不需要认证的路径（例外）
    EXCLUDED_PATHS = [
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/static",
        # Aegis 认证相关路径（通过 Hermes 代理访问）
        "/aegis",
    ]

    async def dispatch(self, request: Request, call_next):
        # 如果 Web 认证未启用，直接放行
        if not settings.web_auth_enabled:
            return await call_next(request)

        path = request.url.path

        # 检查是否是例外路径
        for excluded in self.EXCLUDED_PATHS:
            if path == excluded or path.startswith(excluded + "/"):
                return await call_next(request)

        # 检查是否是受保护路径（精确匹配或前缀匹配）
        is_protected = False
        for protected in self.PROTECTED_PATHS:
            if path == protected or (protected != "/" and path.startswith(protected)):
                is_protected = True
                break

        # 对于根路径，只有精确匹配才保护
        if path == "/":
            is_protected = True

        if not is_protected:
            return await call_next(request)

        # 检查 JWT token
        token = self._get_token(request)
        if token and self._validate_token(token):
            # token 有效，放行
            return await call_next(request)

        # 未认证，重定向到 Aegis 登录页面
        login_url = self._get_login_url(request)
        if login_url:
            logger.info(
                f"未认证，重定向到登录页面: {login_url}",
                extra={"extra_fields": {"path": path}}
            )
            return RedirectResponse(url=login_url, status_code=302)

        # 没有配置认证服务，返回 503
        logger.warning(
            "未配置认证服务，无法进行认证",
            extra={"extra_fields": {"path": path}}
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"detail": "认证服务不可用"}
        )

    def _get_token(self, request: Request) -> Optional[str]:
        """
        从请求中获取 JWT token

        优先级：
        1. Authorization header (Bearer token)
        2. Cookie
        """
        # 从 Authorization header 获取
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]

        # 从 Cookie 获取
        token = request.cookies.get(TOKEN_COOKIE_NAME)
        if token:
            return token

        return None

    def _validate_token(self, token: str) -> bool:
        """
        验证 JWT token 是否有效

        简单验证：检查 token 格式和过期时间
        完整验证应该调用 Aegis 的验证接口
        """
        try:
            import jwt
            # 只解码不验证签名（签名验证由 Aegis 负责）
            # 这里只做基本的格式和过期检查
            payload = jwt.decode(token, options={"verify_signature": False})

            # 检查是否过期
            import time
            exp = payload.get("exp")
            if exp and exp < time.time():
                logger.debug("Token 已过期")
                return False

            return True
        except jwt.InvalidTokenError as e:
            logger.debug(f"Token 无效: {e}")
            return False
        except Exception as e:
            logger.debug(f"Token 验证异常: {e}")
            return False

    def _get_login_url(self, request: Request) -> Optional[str]:
        """
        获取登录页面 URL

        通过 Hermes 代理访问 Aegis 登录页面（/aegis/admin/login），
        这样登录后设置的 cookie 在 Hermes 域下，避免跨域问题。
        """
        try:
            # 当前请求路径，登录成功后跳回
            current_path = request.url.path
            if current_path == "/":
                current_path = ""  # 避免重复的 /

            # 通过 Hermes 代理访问 Aegis 登录页面
            # 登录成功后 Aegis 设置的 cookie 将在 Hermes 域下生效
            login_path = f"/aegis/admin/login?redirect={quote(current_path or '/')}"

            return login_path

        except Exception as e:
            logger.error(f"获取登录 URL 失败: {e}", exc_info=True)
            return None
