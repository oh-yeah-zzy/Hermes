"""
插件系统基础模块

定义插件基类、网关上下文和过滤器链
"""

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import Request, Response

from hermes.schemas.route import RouteInfo, ServiceInstance


@dataclass
class GatewayContext:
    """
    网关上下文

    在整个请求生命周期中传递，包含请求信息和中间状态
    """

    # 原始请求
    request: Request

    # 匹配的路由规则
    route: Optional[RouteInfo] = None

    # 选中的上游服务实例
    upstream_instance: Optional[ServiceInstance] = None

    # 请求开始时间（时间戳）
    start_time: float = 0

    # 请求 ID
    request_id: str = ""

    # 元数据（用于插件间传递数据）
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 短路响应（如果设置，将跳过后续处理直接返回）
    short_circuit_response: Optional[Response] = None

    @property
    def client_ip(self) -> str:
        """获取客户端 IP"""
        if self.request.client:
            return self.request.client.host
        return "unknown"

    @property
    def method(self) -> str:
        """获取请求方法"""
        return self.request.method

    @property
    def path(self) -> str:
        """获取请求路径"""
        return self.request.url.path


class GatewayPlugin(ABC):
    """
    网关插件基类

    插件通过实现 before_request、after_response、on_error 方法来介入请求处理流程

    优先级说明：
    - 数字越小越先执行
    - 建议范围 0-1000
    - 100: 限流插件
    - 200: 熔断插件
    - 300: 头部处理插件
    - 500: 默认优先级
    - 900: 日志插件
    """

    # 插件名称（用于日志和配置）
    name: str = "base_plugin"

    # 优先级（数字越小越先执行）
    priority: int = 500

    # 是否启用
    enabled: bool = True

    async def before_request(self, ctx: GatewayContext) -> GatewayContext:
        """
        请求前处理

        可以：
        - 修改请求头（通过 ctx.metadata["forward_headers"]）
        - 记录日志
        - 执行限流检查
        - 设置 ctx.short_circuit_response 短路请求

        Args:
            ctx: 网关上下文

        Returns:
            修改后的上下文
        """
        return ctx

    async def after_response(
        self,
        ctx: GatewayContext,
        response: Response,
    ) -> Response:
        """
        响应后处理

        可以：
        - 修改响应头
        - 记录指标
        - 更新熔断状态

        Args:
            ctx: 网关上下文
            response: 上游响应

        Returns:
            修改后的响应
        """
        return response

    async def on_error(
        self,
        ctx: GatewayContext,
        error: Exception,
    ) -> Optional[Response]:
        """
        错误处理

        Args:
            ctx: 网关上下文
            error: 异常对象

        Returns:
            自定义错误响应，返回 None 则继续传播错误
        """
        return None


class PluginChain:
    """
    插件链管理器

    负责注册插件和按优先级执行插件链
    """

    def __init__(self):
        self._plugins: List[GatewayPlugin] = []

    def register(self, plugin: GatewayPlugin) -> None:
        """
        注册插件

        Args:
            plugin: 插件实例
        """
        self._plugins.append(plugin)
        # 按优先级排序（优先级数字小的在前）
        self._plugins.sort(key=lambda p: p.priority)

    def unregister(self, plugin_name: str) -> None:
        """
        注销插件

        Args:
            plugin_name: 插件名称
        """
        self._plugins = [p for p in self._plugins if p.name != plugin_name]

    def get_plugin(self, plugin_name: str) -> Optional[GatewayPlugin]:
        """
        获取插件

        Args:
            plugin_name: 插件名称

        Returns:
            插件实例，如果不存在则返回 None
        """
        for plugin in self._plugins:
            if plugin.name == plugin_name:
                return plugin
        return None

    @property
    def plugins(self) -> List[GatewayPlugin]:
        """获取所有插件"""
        return self._plugins.copy()

    async def execute_before(self, ctx: GatewayContext) -> GatewayContext:
        """
        执行所有插件的 before_request

        如果某个插件设置了 short_circuit_response，则跳过后续插件

        Args:
            ctx: 网关上下文

        Returns:
            处理后的上下文
        """
        for plugin in self._plugins:
            if not plugin.enabled:
                continue

            ctx = await plugin.before_request(ctx)

            # 如果设置了短路响应，立即返回
            if ctx.short_circuit_response is not None:
                break

        return ctx

    async def execute_after(
        self,
        ctx: GatewayContext,
        response: Response,
    ) -> Response:
        """
        执行所有插件的 after_response

        按优先级逆序执行（后注册的先执行）

        Args:
            ctx: 网关上下文
            response: 上游响应

        Returns:
            处理后的响应
        """
        for plugin in reversed(self._plugins):
            if not plugin.enabled:
                continue

            response = await plugin.after_response(ctx, response)

        return response

    async def handle_error(
        self,
        ctx: GatewayContext,
        error: Exception,
    ) -> Optional[Response]:
        """
        处理错误

        按优先级顺序尝试处理，第一个返回非 None 响应的插件生效

        Args:
            ctx: 网关上下文
            error: 异常对象

        Returns:
            错误响应，如果没有插件处理则返回 None
        """
        for plugin in self._plugins:
            if not plugin.enabled:
                continue

            response = await plugin.on_error(ctx, error)
            if response is not None:
                return response

        return None
