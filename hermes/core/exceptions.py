"""
自定义异常模块
"""


class HermesError(Exception):
    """Hermes 基础异常"""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RouteNotFoundError(HermesError):
    """路由未找到"""

    def __init__(self, path: str):
        super().__init__(
            message=f"路由不存在: {path}",
            status_code=404,
        )


class NoAvailableInstanceError(HermesError):
    """无可用服务实例"""

    def __init__(self, service_id: str):
        super().__init__(
            message=f"服务 {service_id} 无可用实例",
            status_code=503,
        )


class ProxyError(HermesError):
    """代理转发错误"""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message=message, status_code=status_code)


class RateLimitExceededError(HermesError):
    """超出速率限制"""

    def __init__(self, limit_type: str = "global"):
        super().__init__(
            message=f"请求过于频繁 (限制类型: {limit_type})",
            status_code=429,
        )


class CircuitOpenError(HermesError):
    """熔断器开启"""

    def __init__(self, service_id: str):
        super().__init__(
            message=f"服务 {service_id} 熔断中，请稍后重试",
            status_code=503,
        )


class RegistryError(HermesError):
    """服务注册中心错误"""

    def __init__(self, message: str):
        super().__init__(
            message=f"注册中心错误: {message}",
            status_code=503,
        )
