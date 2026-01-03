"""
路由规则模型

定义从 ServiceAtlas 获取的路由规则数据结构
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class ServiceInstance:
    """服务实例信息"""

    # 实例 ID
    id: str
    # 服务名称
    name: str
    # 主机地址
    host: str
    # 端口
    port: int
    # 协议（http/https）
    protocol: str = "http"
    # 状态（healthy/unhealthy）
    status: str = "unknown"
    # 权重（用于负载均衡）
    weight: int = 1
    # 是否健康
    healthy: bool = True
    # 活跃连接数（用于 least_conn 策略）
    active_connections: int = 0
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        """获取服务基础 URL"""
        return f"{self.protocol}://{self.host}:{self.port}"

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class AuthConfig:
    """认证配置"""

    # 是否需要认证
    require_auth: bool = False
    # 认证服务 ID
    auth_service_id: Optional[str] = None
    # 公开路径（不需要认证）
    public_paths: List[str] = field(default_factory=list)
    # 登录重定向路径
    login_redirect: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["AuthConfig"]:
        """从字典创建认证配置"""
        if not data:
            return None

        return cls(
            require_auth=data.get("require_auth", False),
            auth_service_id=data.get("auth_service_id"),
            public_paths=data.get("public_paths", []),
            login_redirect=data.get("login_redirect"),
        )


@dataclass
class AuthServiceInfo:
    """认证服务信息"""

    # 服务 ID
    id: str
    # 服务名称
    name: str
    # 服务基础 URL
    base_url: str
    # 认证端点路径
    auth_endpoint: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["AuthServiceInfo"]:
        """从字典创建认证服务信息"""
        if not data:
            return None

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            base_url=data.get("base_url", ""),
            auth_endpoint=data.get("auth_endpoint"),
        )


@dataclass
class RouteInfo:
    """
    路由规则信息

    从 ServiceAtlas 的 /api/v1/gateway/routes 接口获取
    也可以从本地 routes.yaml 配置文件加载
    """

    # 路由 ID（本地路由使用负数 ID）
    id: int
    # 路径匹配模式（支持 *, **, {id} 通配符）
    path_pattern: str
    # 目标服务 ID
    target_service_id: str
    # 目标服务实例
    target_service: ServiceInstance
    # HTTP 方法限制（逗号分隔，如 "GET,POST" 或 "*"）
    methods: str = "*"
    # 是否剥离路径前缀
    strip_prefix: bool = False
    # 要剥离的路径
    strip_path: Optional[str] = None
    # 优先级（数值越大优先级越高）
    priority: int = 0
    # 是否启用
    enabled: bool = True
    # 认证配置
    auth_config: Optional[AuthConfig] = None
    # 认证服务信息
    auth_service: Optional[AuthServiceInfo] = None
    # 是否是本地路由（从 routes.yaml 加载）
    is_local: bool = False
    # 直接指定目标 URL（本地路由可用，无需通过 ServiceAtlas）
    target_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteInfo":
        """从字典创建路由信息（ServiceAtlas 响应）"""
        target = data.get("target_service", {})

        return cls(
            id=data["id"],
            path_pattern=data["path_pattern"],
            target_service_id=data["target_service_id"],
            target_service=ServiceInstance(
                id=target.get("id", ""),
                name=target.get("name", ""),
                host=target.get("host", ""),
                port=target.get("port", 0),
                protocol=target.get("protocol", "http"),
                status=target.get("status", "unknown"),
                healthy=target.get("status") == "healthy",
            ),
            methods=data.get("methods", "*"),
            strip_prefix=data.get("strip_prefix", False),
            strip_path=data.get("strip_path"),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            auth_config=AuthConfig.from_dict(data.get("auth_config")),
            auth_service=AuthServiceInfo.from_dict(data.get("auth_service")),
            is_local=False,
        )

    @classmethod
    def from_local_config(cls, data: Dict[str, Any], route_id: int) -> "RouteInfo":
        """
        从本地配置创建路由信息

        Args:
            data: 本地配置字典
            route_id: 路由 ID（通常为负数，表示本地路由）
        """
        # 如果指定了 target_url，解析主机和端口
        target_url = data.get("target_url")
        if target_url:
            from urllib.parse import urlparse
            parsed = urlparse(target_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            protocol = parsed.scheme or "http"
            target_service_id = f"local-{host}-{port}"
            target_service = ServiceInstance(
                id=target_service_id,
                name=f"Local: {target_url}",
                host=host,
                port=port,
                protocol=protocol,
                status="healthy",
                healthy=True,
            )
        else:
            # 需要通过 ServiceAtlas 获取目标服务信息
            target_service_id = data.get("target_service_id", "")
            target_service = ServiceInstance(
                id=target_service_id,
                name=target_service_id,
                host="",
                port=0,
                protocol="http",
                status="unknown",
                healthy=False,  # 暂时标记为不健康，后续刷新时更新
            )

        return cls(
            id=route_id,
            path_pattern=data["path_pattern"],
            target_service_id=target_service_id,
            target_service=target_service,
            methods=data.get("methods", "*"),
            strip_prefix=data.get("strip_prefix", False),
            strip_path=data.get("strip_path"),
            priority=data.get("priority", 0),
            enabled=data.get("enabled", True),
            auth_config=AuthConfig.from_dict(data.get("auth_config")),
            is_local=True,
            target_url=target_url,
        )

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class ServiceInfo:
    """服务信息（用于服务卡片显示）"""

    # 服务 ID
    id: str
    # 服务名称
    name: str
    # 服务状态
    status: str
    # 服务描述
    description: str = ""
    # 图标名称
    icon: str = "cube"
    # 服务基础 URL
    base_url: str = ""
    # 服务类型
    service_type: str = "application"
