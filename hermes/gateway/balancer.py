"""
负载均衡器模块

支持多种负载均衡策略：轮询、随机、最少连接
"""

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from hermes.core.config import LoadBalanceStrategy
from hermes.schemas.route import ServiceInstance


class LoadBalancer(ABC):
    """负载均衡器基类"""

    @abstractmethod
    def select(self, instances: List[ServiceInstance]) -> Optional[ServiceInstance]:
        """
        从实例列表中选择一个实例

        Args:
            instances: 服务实例列表

        Returns:
            选中的实例，如果没有可用实例则返回 None
        """
        pass


class RoundRobinBalancer(LoadBalancer):
    """
    轮询负载均衡

    按顺序依次选择每个实例
    """

    def __init__(self):
        # 按服务 ID 分组的计数器
        self._counters: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    def select(self, instances: List[ServiceInstance]) -> Optional[ServiceInstance]:
        """
        同步选择实例（非线程安全，仅用于单线程场景）

        Args:
            instances: 服务实例列表

        Returns:
            选中的实例，如果没有可用实例则返回 None
        """
        # 过滤健康的实例
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return None

        # 获取服务 ID（使用第一个实例的 ID 前缀）
        service_id = healthy[0].id.rsplit("-", 1)[0] if "-" in healthy[0].id else healthy[0].id

        # 获取当前计数并选择实例
        counter = self._counters.get(service_id, 0)
        selected = healthy[counter % len(healthy)]

        # 更新计数器
        self._counters[service_id] = counter + 1

        return selected

    async def select_async(self, instances: List[ServiceInstance]) -> Optional[ServiceInstance]:
        """
        异步选择实例（线程安全）

        Args:
            instances: 服务实例列表

        Returns:
            选中的实例，如果没有可用实例则返回 None
        """
        # 过滤健康的实例
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return None

        # 获取服务 ID（使用第一个实例的 ID 前缀）
        service_id = healthy[0].id.rsplit("-", 1)[0] if "-" in healthy[0].id else healthy[0].id

        async with self._lock:
            # 获取当前计数并选择实例
            counter = self._counters.get(service_id, 0)
            selected = healthy[counter % len(healthy)]

            # 更新计数器
            self._counters[service_id] = counter + 1

        return selected


class RandomBalancer(LoadBalancer):
    """
    随机负载均衡

    随机选择一个实例
    """

    def select(self, instances: List[ServiceInstance]) -> Optional[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return None

        return random.choice(healthy)


class LeastConnBalancer(LoadBalancer):
    """
    最少连接负载均衡

    选择当前活跃连接数最少的实例
    """

    def select(self, instances: List[ServiceInstance]) -> Optional[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return None

        # 选择连接数最少的实例
        # 考虑权重：有效连接数 = 实际连接数 / 权重
        return min(
            healthy,
            key=lambda i: i.active_connections / max(i.weight, 1)
        )


class ConnectionTracker:
    """
    连接追踪器

    用于 least_conn 策略，追踪每个实例的活跃连接数
    """

    def __init__(self):
        self._lock = asyncio.Lock()

    async def acquire(self, instance: ServiceInstance) -> None:
        """请求开始时调用，增加连接计数"""
        async with self._lock:
            instance.active_connections += 1

    async def release(self, instance: ServiceInstance) -> None:
        """请求结束时调用，减少连接计数"""
        async with self._lock:
            instance.active_connections = max(0, instance.active_connections - 1)


class LoadBalancerFactory:
    """负载均衡器工厂"""

    # 缓存已创建的负载均衡器
    _balancers: Dict[LoadBalanceStrategy, LoadBalancer] = {}

    @classmethod
    def create(cls, strategy: LoadBalanceStrategy) -> LoadBalancer:
        """
        创建或获取负载均衡器

        Args:
            strategy: 负载均衡策略

        Returns:
            负载均衡器实例
        """
        if strategy not in cls._balancers:
            if strategy == LoadBalanceStrategy.ROUND_ROBIN:
                cls._balancers[strategy] = RoundRobinBalancer()
            elif strategy == LoadBalanceStrategy.RANDOM:
                cls._balancers[strategy] = RandomBalancer()
            elif strategy == LoadBalanceStrategy.LEAST_CONN:
                cls._balancers[strategy] = LeastConnBalancer()
            else:
                # 默认使用轮询
                cls._balancers[strategy] = RoundRobinBalancer()

        return cls._balancers[strategy]


# 全局连接追踪器
connection_tracker = ConnectionTracker()
