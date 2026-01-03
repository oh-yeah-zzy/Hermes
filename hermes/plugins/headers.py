"""
请求头处理插件

负责透传请求头和添加追踪头
"""

from typing import Dict, Set

from hermes.plugins.base import GatewayPlugin, GatewayContext


class HeaderTransformPlugin(GatewayPlugin):
    """
    请求头处理插件

    功能：
    - 透传 Authorization 等认证头
    - 添加追踪头（X-Request-ID, X-Forwarded-*）
    - 移除 hop-by-hop 头
    """

    name = "header_transform"
    priority = 300

    # hop-by-hop 头（不应转发）
    HOP_BY_HOP_HEADERS: Set[str] = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }

    async def before_request(self, ctx: GatewayContext) -> GatewayContext:
        """处理请求头，构建转发头"""
        request = ctx.request
        client_ip = ctx.client_ip

        # 构建转发头
        forward_headers: Dict[str, str] = {}

        # 透传所有非 hop-by-hop 头
        for header_name, header_value in request.headers.items():
            header_lower = header_name.lower()

            # 跳过 hop-by-hop 头
            if header_lower in self.HOP_BY_HOP_HEADERS:
                continue

            # 跳过 host 头（让 httpx 自动设置）
            if header_lower == "host":
                continue

            forward_headers[header_name] = header_value

        # 添加追踪头
        forward_headers["X-Request-ID"] = ctx.request_id
        forward_headers["X-Forwarded-For"] = client_ip
        forward_headers["X-Forwarded-Proto"] = request.url.scheme
        forward_headers["X-Forwarded-Host"] = request.url.netloc
        forward_headers["X-Real-IP"] = client_ip

        # 添加路径前缀（供后端服务设置 base path）
        if ctx.route and ctx.route.strip_path:
            forward_headers["X-Forwarded-Prefix"] = ctx.route.strip_path

        # 存储处理后的头到上下文
        ctx.metadata["forward_headers"] = forward_headers

        return ctx
