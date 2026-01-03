"""
FastAPI 应用入口

配置和创建 FastAPI 应用
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from hermes.core.config import settings
from hermes.core.logging import setup_logging, get_logger
from hermes.middleware.request_id import RequestIDMiddleware
from hermes.middleware.web_auth import WebAuthMiddleware
from hermes.registry.client import RegistryClient
from hermes.registry.route_cache import RouteCache
from hermes.plugins.registry import create_default_plugin_chain
from hermes.plugins.rate_limit import RateLimitPlugin
from hermes.observability.health import router as health_router
from hermes.observability.metrics import router as metrics_router
from hermes.gateway.router import router as gateway_router
from hermes.web.routes import router as web_router

logger = get_logger("hermes.main")

# 项目根目录
BASE_DIR = Path(__file__).parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时：
    1. 配置日志
    2. 初始化路由缓存
    3. 初始化插件链
    4. 注册到 ServiceAtlas

    关闭时：
    1. 停止路由缓存刷新
    2. 从 ServiceAtlas 注销
    """
    # 配置日志
    setup_logging(settings.log_level, settings.log_json_format)
    logger.info(
        f"启动 {settings.app_name} v{settings.app_version}",
        extra={
            "extra_fields": {
                "host": settings.host,
                "port": settings.port,
                "debug": settings.debug,
            }
        },
    )

    # 初始化路由缓存（不立即启动）
    route_cache = RouteCache(
        registry_url=settings.registry_url,
        gateway_id=settings.service_id,
        refresh_interval=settings.route_refresh_interval,
    )
    app.state.route_cache = route_cache

    # 初始化插件链
    plugin_chain = create_default_plugin_chain()
    app.state.plugin_chain = plugin_chain
    logger.info(
        f"已加载 {len(plugin_chain.plugins)} 个插件",
        extra={
            "extra_fields": {
                "plugins": [p.name for p in plugin_chain.plugins],
            }
        },
    )

    # 启动限流插件的清理任务
    rate_limit_plugin = None
    for plugin in plugin_chain.plugins:
        if isinstance(plugin, RateLimitPlugin):
            rate_limit_plugin = plugin
            await plugin.start_cleanup_task()
            break

    # 先注册到 ServiceAtlas（标记为网关）
    registry_client = None
    if settings.registry_enabled:
        registry_client = RegistryClient(
            registry_url=settings.registry_url,
            service_id=settings.service_id,
            service_name=settings.service_name,
            host=settings.service_host,
            port=settings.port,
            heartbeat_interval=settings.heartbeat_interval,
            metadata={
                "version": settings.app_version,
            },
        )
        await registry_client.start()
        app.state.registry_client = registry_client

    # 然后启动路由缓存（加载本地路由，如果启用了 ServiceAtlas 则获取远程路由）
    await route_cache.start()

    logger.info(
        f"{settings.app_name} 启动完成",
        extra={
            "extra_fields": {
                "registry_enabled": settings.registry_enabled,
                "route_count": route_cache.route_count,
            }
        },
    )

    yield

    # 清理
    logger.info(f"正在关闭 {settings.app_name}...")

    # 停止限流插件的清理任务
    if rate_limit_plugin:
        await rate_limit_plugin.stop_cleanup_task()

    await route_cache.stop()

    if registry_client:
        await registry_client.stop()

    logger.info(f"{settings.app_name} 已关闭")


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用

    Returns:
        配置好的 FastAPI 应用
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="轻量级 API 网关，支持路由转发、负载均衡、限流熔断",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # 添加中间件（注意顺序：后添加的先执行）
    # 1. CORS 中间件（最外层）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    # 2. Web 认证中间件
    app.add_middleware(WebAuthMiddleware)
    # 3. 请求 ID 中间件（最内层）
    app.add_middleware(RequestIDMiddleware)

    # 挂载静态文件
    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 注册路由（顺序重要：Web 路由必须在 gateway_router 之前）
    app.include_router(health_router)

    if settings.metrics_enabled:
        app.include_router(metrics_router)

    # Web 管理界面路由
    app.include_router(web_router)

    # 网关路由（catch-all，必须最后注册）
    app.include_router(gateway_router)

    return app


# 创建应用实例
app = create_app()
