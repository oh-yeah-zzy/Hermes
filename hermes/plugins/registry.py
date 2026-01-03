"""
插件注册表

管理和配置所有插件
"""

from hermes.core.config import settings
from hermes.plugins.base import PluginChain
from hermes.plugins.authentication import AuthenticationPlugin
from hermes.plugins.headers import HeaderTransformPlugin
from hermes.plugins.rate_limit import RateLimitPlugin
from hermes.plugins.circuit_breaker import CircuitBreakerPlugin


def create_default_plugin_chain() -> PluginChain:
    """
    创建默认的插件链

    包含以下插件（按优先级排序）：
    1. AuthenticationPlugin (50) - 认证
    2. RateLimitPlugin (100) - 限流
    3. CircuitBreakerPlugin (200) - 熔断
    4. HeaderTransformPlugin (300) - 头部处理

    Returns:
        配置好的插件链
    """
    chain = PluginChain()

    # 认证插件（优先级最高，在限流之前执行）
    if settings.auth_plugin_enabled:
        chain.register(AuthenticationPlugin())

    # 限流插件
    if settings.rate_limit_enabled:
        chain.register(RateLimitPlugin())

    # 熔断插件
    if settings.circuit_breaker_enabled:
        chain.register(CircuitBreakerPlugin())

    # 头部处理插件（始终启用）
    chain.register(HeaderTransformPlugin())

    return chain


# 全局插件链实例
plugin_chain = create_default_plugin_chain()
