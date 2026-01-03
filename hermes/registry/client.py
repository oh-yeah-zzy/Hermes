"""
ServiceAtlas 注册客户端

负责将 Hermes 注册到 ServiceAtlas 并维护心跳
"""

import asyncio
from typing import Optional, Dict, Any

import httpx

from hermes.core.logging import get_logger

logger = get_logger("hermes.registry.client")


class RegistryClient:
    """
    ServiceAtlas 注册客户端

    功能：
    - 服务注册（标记为网关）
    - 心跳维护
    - 优雅注销
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
        self.protocol = protocol
        self.health_check_path = health_check_path
        self.metadata = metadata or {}
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout

        # 运行状态
        self._running = False
        # 心跳任务
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start(self) -> bool:
        """
        启动注册客户端

        Returns:
            注册是否成功
        """
        if self._running:
            return True

        # 注册服务
        success = await self._register()
        if not success:
            logger.warning(
                "注册失败，Hermes 将以离线模式运行",
                extra={"extra_fields": {"registry_url": self.registry_url}},
            )
            return False

        self._running = True

        # 启动心跳任务
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info(
            f"已注册到 ServiceAtlas: {self.registry_url}",
            extra={
                "extra_fields": {
                    "service_id": self.service_id,
                    "service_name": self.service_name,
                    "heartbeat_interval": self.heartbeat_interval,
                }
            },
        )
        return True

    async def stop(self) -> None:
        """停止注册客户端并注销服务"""
        if not self._running:
            return

        self._running = False

        # 取消心跳任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # 注销服务
        await self._unregister()

        logger.info(
            f"已从 ServiceAtlas 注销: {self.registry_url}",
            extra={"extra_fields": {"service_id": self.service_id}},
        )

    async def _register(self) -> bool:
        """
        注册到 ServiceAtlas

        Returns:
            注册是否成功
        """
        register_data = {
            "id": self.service_id,
            "name": self.service_name,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "health_check_path": self.health_check_path,
            "is_gateway": True,  # 关键：标记为网关，以便获取路由规则
            "service_meta": {
                **self.metadata,
                "type": "api_gateway",
                "features": [
                    "routing",
                    "load_balancing",
                    "rate_limiting",
                    "circuit_breaker",
                ],
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.registry_url}/api/v1/services",
                    json=register_data,
                )

                if response.status_code in (200, 201):
                    logger.debug(
                        "服务注册成功",
                        extra={"extra_fields": {"service_id": self.service_id}},
                    )
                    return True

                elif response.status_code == 409:
                    # 服务已存在，尝试更新
                    logger.debug("服务已存在，尝试更新")
                    update_response = await client.put(
                        f"{self.registry_url}/api/v1/services/{self.service_id}",
                        json=register_data,
                    )
                    return update_response.status_code == 200

                else:
                    logger.warning(
                        f"注册失败: HTTP {response.status_code}",
                        extra={
                            "extra_fields": {
                                "status_code": response.status_code,
                                "response": response.text[:200],
                            }
                        },
                    )

        except httpx.TimeoutException:
            logger.warning(
                "注册超时",
                extra={"extra_fields": {"registry_url": self.registry_url}},
            )
        except httpx.RequestError as e:
            logger.warning(
                f"注册请求错误: {type(e).__name__}: {e}",
                extra={"extra_fields": {"error": str(e)}},
            )
        except Exception as e:
            logger.error(
                f"注册异常: {type(e).__name__}: {e}",
                exc_info=True,
            )

        return False

    async def _unregister(self) -> None:
        """从 ServiceAtlas 注销"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.delete(
                    f"{self.registry_url}/api/v1/services/{self.service_id}"
                )
                logger.debug(
                    "服务注销成功",
                    extra={"extra_fields": {"service_id": self.service_id}},
                )
        except Exception as e:
            logger.debug(
                f"服务注销失败（可忽略）: {type(e).__name__}: {e}",
                extra={"extra_fields": {"error": str(e)}},
            )

    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            if self._running:
                await self._send_heartbeat()

    async def _send_heartbeat(self) -> None:
        """发送心跳"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.registry_url}/api/v1/services/{self.service_id}/heartbeat"
                )
                if response.status_code == 200:
                    logger.debug(
                        "心跳发送成功",
                        extra={"extra_fields": {"service_id": self.service_id}},
                    )
                else:
                    logger.warning(
                        f"心跳响应异常: HTTP {response.status_code}",
                        extra={"extra_fields": {"status_code": response.status_code}},
                    )
        except Exception as e:
            logger.debug(
                f"心跳发送失败: {type(e).__name__}: {e}",
                extra={"extra_fields": {"error": str(e)}},
            )
