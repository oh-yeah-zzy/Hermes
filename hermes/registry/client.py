"""
ServiceAtlas 注册客户端

负责将 Hermes 注册到 ServiceAtlas 并维护心跳

优先使用 ServiceAtlas SDK，若未安装则使用内置实现
"""

import asyncio
from typing import Optional, Dict, Any

import httpx

from hermes.core.logging import get_logger

logger = get_logger("hermes.registry.client")


# ================== 尝试导入 SDK ==================
try:
    from serviceatlas_client import AsyncServiceAtlasClient
    SDK_AVAILABLE = True
    logger.debug("使用 ServiceAtlas SDK")
except ImportError:
    SDK_AVAILABLE = False
    logger.debug("SDK 未安装，使用内置实现")


# ================== 内置实现（SDK 不可用时使用）==================
if not SDK_AVAILABLE:
    class AsyncServiceAtlasClient:
        """
        内置的 ServiceAtlas 异步注册客户端
        仅在 SDK 未安装时使用，接口与 SDK 保持一致
        """

        def __init__(
            self,
            registry_url: str,
            service_id: str,
            service_name: str,
            host: str,
            port: int,
            protocol: str = "http",
            health_check_path: str = "/health",
            is_gateway: bool = False,
            base_path: str = "",
            metadata: Optional[Dict[str, Any]] = None,
            heartbeat_interval: int = 30,
            trust_env: bool = True,
        ):
            self.registry_url = registry_url.rstrip("/")
            self.service_id = service_id
            self.service_name = service_name
            self.host = host
            self.port = port
            self.protocol = protocol
            self.health_check_path = health_check_path
            self.is_gateway = is_gateway
            self.base_path = base_path
            self.metadata = metadata or {}
            self.heartbeat_interval = heartbeat_interval
            self.trust_env = trust_env

            self._running = False
            self._heartbeat_task: Optional[asyncio.Task] = None

        async def start(self) -> bool:
            """启动客户端：注册服务并开始心跳"""
            if self._running:
                return True

            if not await self._register():
                return False

            self._running = True
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            return True

        async def stop(self):
            """停止客户端：停止心跳并注销服务"""
            if not self._running:
                return

            self._running = False

            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

            await self._unregister()

        async def _register(self) -> bool:
            """注册服务到 ServiceAtlas"""
            try:
                register_data = {
                    "id": self.service_id,
                    "name": self.service_name,
                    "host": self.host,
                    "port": self.port,
                    "protocol": self.protocol,
                    "health_check_path": self.health_check_path,
                    "is_gateway": self.is_gateway,
                    "service_meta": self.metadata,
                }
                if self.base_path:
                    register_data["base_path"] = self.base_path

                async with httpx.AsyncClient(timeout=10, trust_env=self.trust_env) as client:
                    response = await client.post(
                        f"{self.registry_url}/api/v1/services",
                        json=register_data
                    )
                    if response.status_code in (200, 201):
                        return True
                    elif response.status_code == 409:
                        # 服务已存在，尝试更新
                        update_response = await client.put(
                            f"{self.registry_url}/api/v1/services/{self.service_id}",
                            json=register_data,
                        )
                        return update_response.status_code == 200
                    else:
                        return False
            except Exception:
                return False

        async def _unregister(self):
            """从 ServiceAtlas 注销服务"""
            try:
                async with httpx.AsyncClient(timeout=5, trust_env=self.trust_env) as client:
                    await client.delete(
                        f"{self.registry_url}/api/v1/services/{self.service_id}"
                    )
            except Exception:
                pass

        async def _heartbeat_loop(self):
            """心跳循环"""
            while self._running:
                await asyncio.sleep(self.heartbeat_interval)
                if self._running:
                    await self._send_heartbeat()

        async def _send_heartbeat(self):
            """发送心跳"""
            try:
                async with httpx.AsyncClient(timeout=5, trust_env=self.trust_env) as client:
                    await client.post(
                        f"{self.registry_url}/api/v1/services/{self.service_id}/heartbeat"
                    )
            except Exception:
                pass


# ================== RegistryClient 封装类 ==================
class RegistryClient:
    """
    ServiceAtlas 注册客户端

    功能：
    - 服务注册（标记为网关）
    - 心跳维护
    - 优雅注销

    内部优先使用 ServiceAtlas SDK，未安装时使用内置实现
    """

    def __init__(
        self,
        registry_url: str,
        service_id: str,
        service_name: str,
        host: str,
        port: int,
        protocol: str = "http",
        health_check_path: str = "/health",
        metadata: Optional[Dict[str, Any]] = None,
        heartbeat_interval: int = 30,
        timeout: float = 10.0,
    ):
        """
        初始化注册客户端

        Args:
            registry_url: ServiceAtlas 地址
            service_id: 服务 ID
            service_name: 服务名称
            host: 服务地址
            port: 服务端口
            protocol: 协议（http/https）
            health_check_path: 健康检查路径
            metadata: 服务元数据
            heartbeat_interval: 心跳间隔（秒）
            timeout: 请求超时时间（秒）
        """
        self.registry_url = registry_url.rstrip("/")
        self.service_id = service_id
        self.service_name = service_name
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval

        # 构建网关特有的元数据
        gateway_metadata = {
            **(metadata or {}),
            "type": "api_gateway",
            "features": [
                "routing",
                "load_balancing",
                "rate_limiting",
                "circuit_breaker",
            ],
        }

        # 创建内部客户端（SDK 或内置实现）
        self._sdk_client = AsyncServiceAtlasClient(
            registry_url=registry_url,
            service_id=service_id,
            service_name=service_name,
            host=host,
            port=port,
            protocol=protocol,
            health_check_path=health_check_path,
            is_gateway=True,  # Hermes 作为网关
            base_path="",
            metadata=gateway_metadata,
            heartbeat_interval=heartbeat_interval,
            trust_env=False,  # 禁用代理，避免环境变量干扰
        )

        self._running = False

    async def start(self) -> bool:
        """
        启动注册客户端

        Returns:
            注册是否成功
        """
        if self._running:
            return True

        # 使用 SDK 客户端启动
        success = await self._sdk_client.start()

        if not success:
            logger.warning(
                "注册失败，Hermes 将以离线模式运行",
                extra={"extra_fields": {"registry_url": self.registry_url}},
            )
            return False

        self._running = True

        logger.info(
            f"已注册到 ServiceAtlas: {self.registry_url}",
            extra={
                "extra_fields": {
                    "service_id": self.service_id,
                    "service_name": self.service_name,
                    "heartbeat_interval": self.heartbeat_interval,
                    "sdk_available": SDK_AVAILABLE,
                }
            },
        )
        return True

    async def stop(self) -> None:
        """停止注册客户端并注销服务"""
        if not self._running:
            return

        self._running = False

        # 使用 SDK 客户端停止
        await self._sdk_client.stop()

        logger.info(
            f"已从 ServiceAtlas 注销: {self.registry_url}",
            extra={"extra_fields": {"service_id": self.service_id}},
        )
