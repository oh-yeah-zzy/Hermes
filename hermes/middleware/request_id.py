"""
请求 ID 中间件

为每个请求生成唯一 ID，用于链路追踪
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    请求 ID 中间件

    功能：
    - 从请求头获取或生成 Request-ID
    - 将 Request-ID 存储到 request.state
    - 将 Request-ID 添加到响应头
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 从请求头获取或生成 Request-ID
        request_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Trace-ID")
            or str(uuid4())
        )

        # 存储到 request.state
        request.state.request_id = request_id

        # 处理请求
        response = await call_next(request)

        # 添加到响应头
        response.headers["X-Request-ID"] = request_id

        return response
