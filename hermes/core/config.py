"""
应用配置模块

使用 pydantic-settings 管理配置，支持环境变量和 .env 文件
"""

from enum import Enum
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoadBalanceStrategy(str, Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_CONN = "least_conn"


class Settings(BaseSettings):
    """Hermes 配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="HERMES_",
    )

    # ========== 应用基础配置 ==========
    app_name: str = "Hermes"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8880

    # ========== ServiceAtlas 配置 ==========
    # 是否启用服务注册
    registry_enabled: bool = True
    # ServiceAtlas 地址
    registry_url: str = "http://localhost:8888"
    # 本服务 ID（在 ServiceAtlas 中的唯一标识）
    service_id: str = "hermes"
    # 本服务名称
    service_name: str = "Hermes API Gateway"
    # 本服务对外暴露的地址（用于服务注册）
    service_host: str = "127.0.0.1"
    # 心跳间隔（秒）
    heartbeat_interval: int = 30
    # 路由规则刷新间隔（秒）
    route_refresh_interval: int = 30

    # ========== 代理配置 ==========
    # 代理请求超时时间（秒）
    proxy_timeout: float = 30.0
    # 代理请求最大重试次数
    proxy_max_retries: int = 3
    # 重试间隔（秒）
    proxy_retry_delay: float = 0.5

    # ========== 负载均衡配置 ==========
    # 负载均衡策略
    load_balance_strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN

    # ========== 限流配置 ==========
    # 是否启用限流
    rate_limit_enabled: bool = True
    # 全局 QPS 限制
    rate_limit_global_qps: float = 10000
    # 每路由 QPS 限制
    rate_limit_per_route_qps: float = 1000
    # 每 IP QPS 限制
    rate_limit_per_ip_qps: float = 100
    # 突发流量倍数
    rate_limit_burst_multiplier: float = 1.5

    # ========== 熔断配置 ==========
    # 是否启用熔断
    circuit_breaker_enabled: bool = True
    # 触发熔断的连续失败次数
    circuit_breaker_failure_threshold: int = 5
    # 半开状态恢复的成功次数
    circuit_breaker_success_threshold: int = 2
    # 熔断冷却时间（秒）
    circuit_breaker_timeout: float = 30.0

    # ========== 日志配置 ==========
    # 日志级别
    log_level: str = "INFO"
    # 是否使用 JSON 格式日志
    log_json_format: bool = True

    # ========== CORS 配置 ==========
    cors_origins: List[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]

    # ========== 指标配置 ==========
    # 是否启用指标收集
    metrics_enabled: bool = True
    # 指标导出路径
    metrics_path: str = "/metrics"

    # ========== Web 界面安全配置 ==========
    # 是否启用 Web 界面认证
    web_auth_enabled: bool = True
    # Web 界面用户名
    web_auth_username: str = "admin"
    # Web 界面密码
    web_auth_password: str = "hermes123"
    # 可选的 API Key 认证（优先级高于 Basic Auth）
    web_api_key: str = ""

    # ========== 本地路由配置 ==========
    # 本地路由配置文件路径
    local_routes_file: str = "routes.yaml"
    # 是否启用本地路由
    local_routes_enabled: bool = True
    # 本地路由优先级提升值（使本地路由优先于远程路由）
    local_routes_priority_boost: int = 1000

    # ========== 回退配置 ==========
    # ServiceAtlas 不可用时是否回退到本地配置
    fallback_to_local: bool = True

    # ========== 认证配置 ==========
    # 是否启用认证插件（网关代理路由的认证检查）
    auth_plugin_enabled: bool = True
    # 认证服务不可用时是否放行请求
    auth_degrade_allow: bool = False


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 全局配置实例
settings = get_settings()
