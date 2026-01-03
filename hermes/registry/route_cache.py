"""
路由规则缓存模块

从 ServiceAtlas 获取路由规则并缓存，支持定期刷新
同时支持本地路由配置文件加载
"""

import asyncio
import time
from pathlib import Path
from typing import List, Optional

import httpx

from hermes.core.config import settings
from hermes.core.logging import get_logger
from hermes.schemas.route import RouteInfo, ServiceInfo

logger = get_logger("hermes.registry.route_cache")


class RouteCache:
    """
    路由规则缓存

    功能：
    - 从 ServiceAtlas 拉取路由规则
    - 加载本地 routes.yaml 配置
    - 合并远程和本地规则（本地优先）
    - 定期刷新路由规则
    - 缓存失效时使用旧数据或本地配置
    - 缓存服务列表（用于服务卡片显示）
    """

    def __init__(
        self,
        registry_url: str,
        gateway_id: str,
        refresh_interval: int = 30,
        timeout: float = 10.0,
    ):
        """
        初始化路由缓存

        Args:
            registry_url: ServiceAtlas 地址
            gateway_id: 网关服务 ID
            refresh_interval: 刷新间隔（秒）
            timeout: 请求超时时间（秒）
        """
        self.registry_url = registry_url.rstrip("/")
        self.gateway_id = gateway_id
        self.refresh_interval = refresh_interval
        self.timeout = timeout

        # 缓存的远程路由规则
        self._remote_routes: List[RouteInfo] = []
        # 本地路由规则
        self._local_routes: List[RouteInfo] = []
        # 服务列表
        self._services: List[ServiceInfo] = []
        # 上次更新时间
        self._last_update: float = 0
        # 异步锁
        self._lock = asyncio.Lock()
        # 刷新任务
        self._refresh_task: Optional[asyncio.Task] = None
        # 运行状态
        self._running = False
        # ServiceAtlas 是否可用
        self._registry_available = False

    async def start(self) -> None:
        """启动缓存刷新任务"""
        if self._running:
            return

        self._running = True

        # 加载本地路由
        self._load_local_routes()

        # 如果启用了 ServiceAtlas，则尝试获取远程路由
        if settings.registry_enabled:
            # 初始加载远程路由
            success = await self.refresh()
            self._registry_available = success

            if success:
                logger.info(
                    f"路由缓存已启动，远程: {len(self._remote_routes)} 条，本地: {len(self._local_routes)} 条",
                    extra={
                        "extra_fields": {
                            "remote_routes": len(self._remote_routes),
                            "local_routes": len(self._local_routes),
                        }
                    },
                )
            else:
                if settings.fallback_to_local and self._local_routes:
                    logger.warning(
                        f"ServiceAtlas 不可用，使用本地路由配置 ({len(self._local_routes)} 条)"
                    )
                else:
                    logger.warning("路由缓存启动时加载失败，将使用空路由表")

            # 启动定期刷新任务
            self._refresh_task = asyncio.create_task(self._refresh_loop())
            logger.info(
                f"路由刷新任务已启动，刷新间隔: {self.refresh_interval}秒",
                extra={"extra_fields": {"refresh_interval": self.refresh_interval}},
            )
        else:
            # 非注册模式，只使用本地路由
            logger.info(
                f"路由缓存已启动（仅本地模式），共 {len(self._local_routes)} 条本地规则",
                extra={"extra_fields": {"local_routes": len(self._local_routes)}},
            )

    async def stop(self) -> None:
        """停止缓存刷新任务"""
        if not self._running:
            return

        self._running = False

        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        logger.info("路由缓存已停止")

    def _load_local_routes(self) -> None:
        """加载本地路由配置"""
        if not settings.local_routes_enabled:
            logger.debug("本地路由已禁用")
            return

        local_routes_file = Path(settings.local_routes_file)

        # 如果不是绝对路径，则相对于工作目录
        if not local_routes_file.is_absolute():
            # 尝试项目根目录
            from hermes.main import BASE_DIR
            local_routes_file = BASE_DIR / settings.local_routes_file

        if not local_routes_file.exists():
            logger.debug(f"本地路由配置文件不存在: {local_routes_file}")
            return

        try:
            import yaml

            with open(local_routes_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if not config:
                logger.debug("本地路由配置文件为空")
                return

            routes = []
            for i, route_data in enumerate(config.get("routes", [])):
                # 本地路由使用负数 ID
                route_id = -(i + 1)
                # 本地路由优先级提升
                route_data["priority"] = (
                    route_data.get("priority", 0) + settings.local_routes_priority_boost
                )

                try:
                    route = RouteInfo.from_local_config(route_data, route_id)
                    routes.append(route)
                except Exception as e:
                    logger.warning(f"解析本地路由配置失败: {e}", exc_info=True)

            self._local_routes = routes
            logger.info(
                f"已加载 {len(routes)} 条本地路由规则",
                extra={"extra_fields": {"local_routes": len(routes)}},
            )

        except ImportError:
            logger.warning("yaml 模块未安装，无法加载本地路由配置")
        except Exception as e:
            logger.error(f"加载本地路由配置失败: {e}", exc_info=True)

    def reload_local_routes(self) -> None:
        """重新加载本地路由配置"""
        self._load_local_routes()

    async def refresh(self) -> bool:
        """
        从 ServiceAtlas 刷新路由规则

        Returns:
            是否刷新成功
        """
        url = f"{self.registry_url}/api/v1/gateway/routes"
        headers = {"X-Gateway-ID": self.gateway_id}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    routes_data = response.json()
                    routes = [RouteInfo.from_dict(r) for r in routes_data]

                    async with self._lock:
                        self._remote_routes = routes
                        self._last_update = time.time()
                        self._registry_available = True

                    logger.debug(
                        f"路由规则已刷新，共 {len(routes)} 条",
                        extra={"extra_fields": {"route_count": len(routes)}},
                    )

                    # 同时刷新服务列表
                    await self._refresh_services()

                    return True

                elif response.status_code == 403:
                    logger.warning(
                        "无权限获取路由（服务未标记为网关）",
                        extra={"extra_fields": {"gateway_id": self.gateway_id}},
                    )
                elif response.status_code == 404:
                    logger.warning(
                        "网关服务不存在",
                        extra={"extra_fields": {"gateway_id": self.gateway_id}},
                    )
                else:
                    logger.warning(
                        f"刷新路由失败: HTTP {response.status_code}",
                        extra={
                            "extra_fields": {
                                "status_code": response.status_code,
                                "response": response.text[:200],
                            }
                        },
                    )

        except httpx.TimeoutException:
            logger.warning(
                "刷新路由超时",
                extra={"extra_fields": {"url": url, "timeout": self.timeout}},
            )
        except httpx.RequestError as e:
            logger.warning(
                f"刷新路由请求错误: {type(e).__name__}: {e}",
                extra={"extra_fields": {"url": url, "error": str(e)}},
            )
        except Exception as e:
            logger.error(
                f"刷新路由异常: {type(e).__name__}: {e}",
                extra={"extra_fields": {"url": url, "error": str(e)}},
                exc_info=True,
            )

        self._registry_available = False
        return False

    async def _refresh_services(self) -> None:
        """刷新服务列表（用于服务卡片）"""
        url = f"{self.registry_url}/api/v1/services"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    response_data = response.json()
                    # ServiceAtlas 返回 {"total": n, "services": [...]}
                    services_data = response_data.get("services", response_data)
                    if not isinstance(services_data, list):
                        services_data = []
                    services = []

                    for s in services_data:
                        # 过滤掉网关和注册中心
                        if s.get("is_gateway"):
                            continue
                        service_meta = s.get("service_meta") or {}
                        service_type = service_meta.get("service_type", "application")
                        if service_type in ("gateway", "registry"):
                            continue

                        # 根据 service_type 或服务名称自动选择图标
                        icon = service_meta.get("icon")
                        if not icon:
                            # 根据 service_type 映射图标
                            icon_map = {
                                "authentication": "shield",
                                "auth": "shield",
                                "iam": "shield",
                                "document": "file",
                                "file": "file",
                                "storage": "database",
                                "database": "database",
                                "registry": "map",
                                "gateway": "cloud",
                            }
                            icon = icon_map.get(service_type)

                            # 如果没匹配到，根据服务名称或 ID 推断
                            if not icon:
                                service_id = s.get("id", "").lower()
                                service_name = s.get("name", "").lower()
                                if "aegis" in service_id or "auth" in service_id or "权限" in service_name:
                                    icon = "shield"
                                elif "deck" in service_id or "view" in service_id or "文档" in service_name or "预览" in service_name:
                                    icon = "file"
                                elif "atlas" in service_id or "registry" in service_id or "注册" in service_name:
                                    icon = "map"
                                else:
                                    icon = "cube"

                        services.append(
                            ServiceInfo(
                                id=s["id"],
                                name=s["name"],
                                status=s["status"],
                                description=service_meta.get("description", ""),
                                icon=icon,
                                base_url=s.get("base_url", ""),
                                service_type=service_type,
                            )
                        )

                    async with self._lock:
                        self._services = services

                    logger.debug(
                        f"服务列表已刷新，共 {len(services)} 个服务",
                        extra={"extra_fields": {"service_count": len(services)}},
                    )

        except Exception as e:
            logger.debug(f"刷新服务列表失败: {e}")

    async def _refresh_loop(self) -> None:
        """定期刷新循环"""
        while self._running:
            await asyncio.sleep(self.refresh_interval)
            if self._running:
                await self.refresh()

    def get_routes(self) -> List[RouteInfo]:
        """
        获取合并后的路由规则

        Returns:
            路由规则列表（按优先级降序排列）
        """
        # 合并远程和本地路由
        all_routes = self._remote_routes + self._local_routes
        # 按优先级排序
        return sorted(all_routes, key=lambda r: r.priority, reverse=True)

    def get_services(self) -> List[ServiceInfo]:
        """获取服务列表"""
        return self._services.copy()

    @property
    def route_count(self) -> int:
        """获取路由规则总数"""
        return len(self._remote_routes) + len(self._local_routes)

    @property
    def remote_route_count(self) -> int:
        """获取远程路由规则数量"""
        return len(self._remote_routes)

    @property
    def local_route_count(self) -> int:
        """获取本地路由规则数量"""
        return len(self._local_routes)

    @property
    def last_update(self) -> float:
        """获取上次更新时间戳"""
        return self._last_update

    @property
    def is_stale(self) -> bool:
        """检查缓存是否过期（超过 2 倍刷新间隔）"""
        if self._last_update == 0:
            return True
        return time.time() - self._last_update > self.refresh_interval * 2

    @property
    def is_empty(self) -> bool:
        """检查路由缓存是否为空"""
        return self.route_count == 0

    @property
    def registry_available(self) -> bool:
        """检查 ServiceAtlas 是否可用"""
        return self._registry_available
