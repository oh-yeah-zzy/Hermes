"""
限流插件

使用令牌桶算法实现限流，支持多种限流维度
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Response

from hermes.core.config import settings
from hermes.core.logging import get_logger
from hermes.plugins.base import GatewayPlugin, GatewayContext

logger = get_logger("hermes.plugins.rate_limit")


@dataclass
class TokenBucket:
    """
    令牌桶

    令牌按固定速率补充，请求消耗令牌，令牌不足则拒绝请求
    """

    # 桶容量
    capacity: float
    # 当前令牌数
    tokens: float
    # 每秒补充令牌数
    refill_rate: float
    # 上次补充时间
    last_refill: float

    def try_acquire(self, tokens: int = 1) -> bool:
        """
        尝试获取令牌

        Args:
            tokens: 需要的令牌数

        Returns:
            是否成功获取
        """
        now = time.time()

        # 补充令牌
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        # 尝试消费
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False


class RateLimitPlugin(GatewayPlugin):
    """
    限流插件

    支持多种限流维度：
    - 全局限流：保护网关自身
    - 按路由限流：保护特定 API
    - 按客户端 IP 限流：防止单个客户端滥用
    """

    name = "rate_limit"
    priority = 100  # 最先执行

    def __init__(
        self,
        global_rate: float = None,
        per_route_rate: float = None,
        per_ip_rate: float = None,
        burst_multiplier: float = None,
        cleanup_interval: float = 300,
    ):
        """
        初始化限流插件

        Args:
            global_rate: 全局 QPS 限制
            per_route_rate: 每路由 QPS 限制
            per_ip_rate: 每 IP QPS 限制
            burst_multiplier: 突发流量倍数
            cleanup_interval: 清理过期令牌桶的间隔（秒）
        """
        self.global_rate = global_rate or settings.rate_limit_global_qps
        self.per_route_rate = per_route_rate or settings.rate_limit_per_route_qps
        self.per_ip_rate = per_ip_rate or settings.rate_limit_per_ip_qps
        self.burst_multiplier = burst_multiplier or settings.rate_limit_burst_multiplier
        self.cleanup_interval = cleanup_interval

        # 是否启用
        self.enabled = settings.rate_limit_enabled

        # 全局令牌桶
        self._global_bucket = TokenBucket(
            capacity=self.global_rate * self.burst_multiplier,
            tokens=self.global_rate * self.burst_multiplier,
            refill_rate=self.global_rate,
            last_refill=time.time(),
        )

        # 按路由的令牌桶
        self._route_buckets: Dict[str, TokenBucket] = {}

        # 按 IP 的令牌桶
        self._ip_buckets: Dict[str, TokenBucket] = {}

        # 异步锁
        self._lock = asyncio.Lock()

        # 清理任务
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self) -> None:
        """启动定期清理任务"""
        if self._cleanup_task is not None:
            return

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            f"限流插件清理任务已启动，间隔 {self.cleanup_interval} 秒",
            extra={"extra_fields": {"cleanup_interval": self.cleanup_interval}},
        )

    async def stop_cleanup_task(self) -> None:
        """停止定期清理任务"""
        if self._cleanup_task is None:
            return

        self._cleanup_task.cancel()
        try:
            await self._cleanup_task
        except asyncio.CancelledError:
            pass
        self._cleanup_task = None
        logger.info("限流插件清理任务已停止")

    async def _cleanup_loop(self) -> None:
        """清理循环"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                async with self._lock:
                    cleaned = self.cleanup_stale_buckets()
                    if cleaned > 0:
                        logger.info(
                            f"清理了 {cleaned} 个过期令牌桶",
                            extra={"extra_fields": {"cleaned_count": cleaned}},
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理令牌桶时出错: {e}")

    def _get_route_bucket(self, route_key: str) -> TokenBucket:
        """获取或创建路由令牌桶"""
        if route_key not in self._route_buckets:
            self._route_buckets[route_key] = TokenBucket(
                capacity=self.per_route_rate * self.burst_multiplier,
                tokens=self.per_route_rate * self.burst_multiplier,
                refill_rate=self.per_route_rate,
                last_refill=time.time(),
            )
        return self._route_buckets[route_key]

    def _get_ip_bucket(self, client_ip: str) -> TokenBucket:
        """获取或创建 IP 令牌桶"""
        if client_ip not in self._ip_buckets:
            self._ip_buckets[client_ip] = TokenBucket(
                capacity=self.per_ip_rate * self.burst_multiplier,
                tokens=self.per_ip_rate * self.burst_multiplier,
                refill_rate=self.per_ip_rate,
                last_refill=time.time(),
            )
        return self._ip_buckets[client_ip]

    async def before_request(self, ctx: GatewayContext) -> GatewayContext:
        """检查限流"""
        if not self.enabled:
            return ctx

        client_ip = ctx.client_ip
        route_key = ctx.route.path_pattern if ctx.route else ctx.path

        async with self._lock:
            # 检查全局限流
            if not self._global_bucket.try_acquire():
                logger.warning(
                    "全局限流触发",
                    extra={
                        "extra_fields": {
                            "client_ip": client_ip,
                            "path": ctx.path,
                            "limit_type": "global",
                        }
                    },
                )
                ctx.short_circuit_response = self._create_rate_limit_response("global")
                return ctx

            # 检查路由限流
            route_bucket = self._get_route_bucket(route_key)
            if not route_bucket.try_acquire():
                logger.warning(
                    f"路由限流触发: {route_key}",
                    extra={
                        "extra_fields": {
                            "client_ip": client_ip,
                            "path": ctx.path,
                            "route": route_key,
                            "limit_type": "route",
                        }
                    },
                )
                ctx.short_circuit_response = self._create_rate_limit_response("route")
                return ctx

            # 检查 IP 限流
            ip_bucket = self._get_ip_bucket(client_ip)
            if not ip_bucket.try_acquire():
                logger.warning(
                    f"IP 限流触发: {client_ip}",
                    extra={
                        "extra_fields": {
                            "client_ip": client_ip,
                            "path": ctx.path,
                            "limit_type": "ip",
                        }
                    },
                )
                ctx.short_circuit_response = self._create_rate_limit_response("ip")
                return ctx

        return ctx

    def _create_rate_limit_response(self, limit_type: str) -> Response:
        """创建限流响应"""
        return Response(
            content=f'{{"error": "Too Many Requests", "type": "{limit_type}"}}',
            status_code=429,
            headers={
                "Content-Type": "application/json",
                "Retry-After": "1",
                "X-RateLimit-Type": limit_type,
            },
        )

    def cleanup_stale_buckets(self, max_idle_seconds: float = 300) -> int:
        """
        清理过期的令牌桶

        Args:
            max_idle_seconds: 最大空闲时间（秒）

        Returns:
            清理的桶数量
        """
        now = time.time()
        cleaned = 0

        # 清理路由桶
        stale_routes = [
            key
            for key, bucket in self._route_buckets.items()
            if now - bucket.last_refill > max_idle_seconds
        ]
        for key in stale_routes:
            del self._route_buckets[key]
            cleaned += 1

        # 清理 IP 桶
        stale_ips = [
            key
            for key, bucket in self._ip_buckets.items()
            if now - bucket.last_refill > max_idle_seconds
        ]
        for key in stale_ips:
            del self._ip_buckets[key]
            cleaned += 1

        if cleaned > 0:
            logger.debug(
                f"清理了 {cleaned} 个过期的令牌桶",
                extra={"extra_fields": {"cleaned_count": cleaned}},
            )

        return cleaned
