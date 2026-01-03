"""
熔断插件

实现熔断器模式，保护上游服务
"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from fastapi import Response

from hermes.core.config import settings
from hermes.core.logging import get_logger
from hermes.plugins.base import GatewayPlugin, GatewayContext

logger = get_logger("hermes.plugins.circuit_breaker")


class CircuitState(str, Enum):
    """熔断器状态"""

    CLOSED = "closed"  # 正常状态，允许请求通过
    OPEN = "open"  # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，允许少量请求探测


@dataclass
class CircuitBreaker:
    """
    熔断器

    状态机：
    CLOSED -> (失败超阈值) -> OPEN -> (冷却超时) -> HALF_OPEN -> (成功达标) -> CLOSED
                                                         |
                                                    (失败) -> OPEN
    """

    # 失败阈值
    failure_threshold: int = 5
    # 半开状态成功阈值
    success_threshold: int = 2
    # 熔断超时时间（秒）
    timeout: float = 30.0

    # 当前状态
    state: CircuitState = CircuitState.CLOSED
    # 失败计数
    failure_count: int = 0
    # 成功计数（半开状态使用）
    success_count: int = 0
    # 上次失败时间
    last_failure_time: float = 0

    def record_success(self) -> None:
        """记录成功"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._reset()
        elif self.state == CircuitState.CLOSED:
            # 成功时重置失败计数
            self.failure_count = 0

    def record_failure(self) -> None:
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # 半开状态下失败，立即熔断
            self._trip()
        elif self.failure_count >= self.failure_threshold:
            # 达到失败阈值，熔断
            self._trip()

    def allow_request(self) -> bool:
        """
        是否允许请求通过

        Returns:
            True 允许通过，False 拒绝
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # 检查是否超时，可以进入半开状态
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False

        # 半开状态：允许请求通过（用于探测）
        return True

    def _trip(self) -> None:
        """触发熔断"""
        self.state = CircuitState.OPEN
        self.failure_count = 0
        logger.warning(
            "熔断器已打开",
            extra={"extra_fields": {"state": self.state.value}},
        )

    def _reset(self) -> None:
        """重置熔断器"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        logger.info(
            "熔断器已恢复",
            extra={"extra_fields": {"state": self.state.value}},
        )


class CircuitBreakerPlugin(GatewayPlugin):
    """
    熔断插件

    按目标服务维度进行熔断
    """

    name = "circuit_breaker"
    priority = 200  # 在限流之后执行

    def __init__(
        self,
        failure_threshold: int = None,
        success_threshold: int = None,
        timeout: float = None,
    ):
        """
        初始化熔断插件

        Args:
            failure_threshold: 失败阈值
            success_threshold: 成功阈值
            timeout: 熔断超时时间
        """
        self.failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self.success_threshold = success_threshold or settings.circuit_breaker_success_threshold
        self.timeout = timeout or settings.circuit_breaker_timeout

        # 是否启用
        self.enabled = settings.circuit_breaker_enabled

        # 按服务 ID 的熔断器
        self._breakers: Dict[str, CircuitBreaker] = {}

        # 异步锁
        self._lock = asyncio.Lock()

    def _get_breaker(self, service_id: str) -> CircuitBreaker:
        """获取或创建熔断器"""
        if service_id not in self._breakers:
            self._breakers[service_id] = CircuitBreaker(
                failure_threshold=self.failure_threshold,
                success_threshold=self.success_threshold,
                timeout=self.timeout,
            )
        return self._breakers[service_id]

    async def before_request(self, ctx: GatewayContext) -> GatewayContext:
        """检查熔断状态"""
        if not self.enabled or not ctx.route:
            return ctx

        service_id = ctx.route.target_service_id

        async with self._lock:
            breaker = self._get_breaker(service_id)

            if not breaker.allow_request():
                logger.warning(
                    f"熔断器拒绝请求: {service_id}",
                    extra={
                        "extra_fields": {
                            "service_id": service_id,
                            "path": ctx.path,
                            "state": breaker.state.value,
                        }
                    },
                )
                ctx.metadata["circuit_rejected"] = True
                ctx.short_circuit_response = self._create_circuit_open_response(
                    service_id, breaker.state.value
                )

        return ctx

    async def after_response(
        self,
        ctx: GatewayContext,
        response: Response,
    ) -> Response:
        """根据响应更新熔断状态"""
        if not self.enabled or not ctx.route:
            return response

        # 如果请求被熔断拒绝，不需要更新状态
        if ctx.metadata.get("circuit_rejected"):
            return response

        service_id = ctx.route.target_service_id

        async with self._lock:
            breaker = self._get_breaker(service_id)

            # 5xx 错误视为失败
            if response.status_code >= 500:
                breaker.record_failure()
            else:
                breaker.record_success()

            # 添加熔断状态响应头
            response.headers["X-Circuit-State"] = breaker.state.value

        return response

    async def on_error(
        self,
        ctx: GatewayContext,
        error: Exception,
    ) -> Optional[Response]:
        """网络错误也视为失败"""
        if not self.enabled or not ctx.route:
            return None

        service_id = ctx.route.target_service_id

        async with self._lock:
            breaker = self._get_breaker(service_id)
            breaker.record_failure()

        return None

    def _create_circuit_open_response(self, service_id: str, state: str) -> Response:
        """创建熔断响应"""
        return Response(
            content=f'{{"error": "Service Unavailable", "reason": "circuit_open", "service": "{service_id}"}}',
            status_code=503,
            headers={
                "Content-Type": "application/json",
                "Retry-After": str(int(self.timeout)),
                "X-Circuit-State": state,
            },
        )

    def get_breaker_status(self, service_id: str) -> Optional[Dict]:
        """
        获取熔断器状态

        Args:
            service_id: 服务 ID

        Returns:
            熔断器状态信息
        """
        if service_id not in self._breakers:
            return None

        breaker = self._breakers[service_id]
        return {
            "service_id": service_id,
            "state": breaker.state.value,
            "failure_count": breaker.failure_count,
            "success_count": breaker.success_count,
            "last_failure_time": breaker.last_failure_time,
        }

    def get_all_breaker_status(self) -> Dict[str, Dict]:
        """获取所有熔断器状态"""
        return {
            service_id: self.get_breaker_status(service_id)
            for service_id in self._breakers
        }
