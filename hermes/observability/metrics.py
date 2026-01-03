"""
指标收集模块

收集和导出网关指标（Prometheus 格式）
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from fastapi import APIRouter

from hermes.core.config import settings

router = APIRouter(tags=["指标"])


@dataclass
class MetricsBucket:
    """指标存储桶"""

    # 请求计数
    request_count: int = 0
    # 错误计数
    error_count: int = 0
    # 总延迟（毫秒）
    total_latency_ms: float = 0

    # 状态码分布
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    # 延迟样本（用于计算分位数）
    latencies: List[float] = field(default_factory=list)


class MetricsCollector:
    """
    指标收集器

    收集请求指标，支持按维度聚合
    """

    def __init__(self, window_size: int = 1000):
        """
        初始化指标收集器

        Args:
            window_size: 延迟样本窗口大小
        """
        self.window_size = window_size

        # 全局指标
        self._global = MetricsBucket()

        # 按路由指标
        self._by_route: Dict[str, MetricsBucket] = defaultdict(MetricsBucket)

        # 按目标服务指标
        self._by_service: Dict[str, MetricsBucket] = defaultdict(MetricsBucket)

        # 异步锁
        self._lock = asyncio.Lock()

    async def record(
        self,
        route_pattern: str,
        target_service: str,
        status_code: int,
        latency_ms: float,
    ) -> None:
        """
        记录请求指标

        Args:
            route_pattern: 路由模式
            target_service: 目标服务 ID
            status_code: 响应状态码
            latency_ms: 延迟（毫秒）
        """
        async with self._lock:
            for bucket in [
                self._global,
                self._by_route[route_pattern],
                self._by_service[target_service],
            ]:
                bucket.request_count += 1
                bucket.total_latency_ms += latency_ms
                bucket.status_codes[status_code] += 1

                if status_code >= 400:
                    bucket.error_count += 1

                # 维护延迟窗口
                bucket.latencies.append(latency_ms)
                if len(bucket.latencies) > self.window_size:
                    bucket.latencies.pop(0)

    def _get_percentile(self, latencies: List[float], p: float) -> float:
        """计算分位数"""
        if not latencies:
            return 0

        sorted_latencies = sorted(latencies)
        index = int(len(sorted_latencies) * p / 100)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]

    def export_prometheus(self) -> str:
        """
        导出 Prometheus 格式指标

        Returns:
            Prometheus 格式的指标文本
        """
        lines = []

        # 添加帮助信息
        lines.append("# HELP hermes_requests_total Total number of requests")
        lines.append("# TYPE hermes_requests_total counter")
        lines.append(f"hermes_requests_total {self._global.request_count}")

        lines.append("# HELP hermes_errors_total Total number of errors")
        lines.append("# TYPE hermes_errors_total counter")
        lines.append(f"hermes_errors_total {self._global.error_count}")

        # 平均延迟
        if self._global.request_count > 0:
            avg_latency = self._global.total_latency_ms / self._global.request_count
            lines.append("# HELP hermes_latency_avg_ms Average latency in milliseconds")
            lines.append("# TYPE hermes_latency_avg_ms gauge")
            lines.append(f"hermes_latency_avg_ms {avg_latency:.2f}")

        # 延迟分位数
        p50 = self._get_percentile(self._global.latencies, 50)
        p95 = self._get_percentile(self._global.latencies, 95)
        p99 = self._get_percentile(self._global.latencies, 99)

        lines.append("# HELP hermes_latency_p50_ms 50th percentile latency")
        lines.append("# TYPE hermes_latency_p50_ms gauge")
        lines.append(f"hermes_latency_p50_ms {p50:.2f}")

        lines.append("# HELP hermes_latency_p95_ms 95th percentile latency")
        lines.append("# TYPE hermes_latency_p95_ms gauge")
        lines.append(f"hermes_latency_p95_ms {p95:.2f}")

        lines.append("# HELP hermes_latency_p99_ms 99th percentile latency")
        lines.append("# TYPE hermes_latency_p99_ms gauge")
        lines.append(f"hermes_latency_p99_ms {p99:.2f}")

        # 按路由指标
        lines.append("# HELP hermes_route_requests_total Requests by route")
        lines.append("# TYPE hermes_route_requests_total counter")
        for route, bucket in self._by_route.items():
            safe_route = route.replace('"', '\\"')
            lines.append(
                f'hermes_route_requests_total{{route="{safe_route}"}} {bucket.request_count}'
            )

        lines.append("# HELP hermes_route_errors_total Errors by route")
        lines.append("# TYPE hermes_route_errors_total counter")
        for route, bucket in self._by_route.items():
            safe_route = route.replace('"', '\\"')
            lines.append(
                f'hermes_route_errors_total{{route="{safe_route}"}} {bucket.error_count}'
            )

        # 按服务指标
        lines.append("# HELP hermes_service_requests_total Requests by service")
        lines.append("# TYPE hermes_service_requests_total counter")
        for service, bucket in self._by_service.items():
            lines.append(
                f'hermes_service_requests_total{{service="{service}"}} {bucket.request_count}'
            )

        lines.append("# HELP hermes_service_errors_total Errors by service")
        lines.append("# TYPE hermes_service_errors_total counter")
        for service, bucket in self._by_service.items():
            lines.append(
                f'hermes_service_errors_total{{service="{service}"}} {bucket.error_count}'
            )

        return "\n".join(lines)

    def get_summary(self) -> Dict:
        """
        获取指标摘要

        Returns:
            指标摘要字典
        """
        avg_latency = 0
        if self._global.request_count > 0:
            avg_latency = self._global.total_latency_ms / self._global.request_count

        return {
            "total_requests": self._global.request_count,
            "total_errors": self._global.error_count,
            "error_rate": (
                self._global.error_count / self._global.request_count
                if self._global.request_count > 0
                else 0
            ),
            "avg_latency_ms": round(avg_latency, 2),
            "p50_latency_ms": round(self._get_percentile(self._global.latencies, 50), 2),
            "p95_latency_ms": round(self._get_percentile(self._global.latencies, 95), 2),
            "p99_latency_ms": round(self._get_percentile(self._global.latencies, 99), 2),
            "routes": len(self._by_route),
            "services": len(self._by_service),
        }

    def get_stats(self) -> Dict:
        """
        获取统计数据（供 Web 界面使用）

        Returns:
            统计数据字典
        """
        total_requests = self._global.request_count
        total_errors = self._global.error_count
        success_count = total_requests - total_errors

        avg_latency = 0
        if total_requests > 0:
            avg_latency = self._global.total_latency_ms / total_requests

        success_rate = (success_count / total_requests * 100) if total_requests > 0 else 100

        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "success_count": success_count,
            "success_rate": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "p50_latency_ms": round(self._get_percentile(self._global.latencies, 50), 2),
            "p95_latency_ms": round(self._get_percentile(self._global.latencies, 95), 2),
            "p99_latency_ms": round(self._get_percentile(self._global.latencies, 99), 2),
            "status_codes": dict(self._global.status_codes),
        }

    def get_route_stats(self) -> List[Dict]:
        """
        获取按路由的统计数据

        Returns:
            路由统计列表
        """
        result = []
        for route, bucket in self._by_route.items():
            avg_latency = 0
            if bucket.request_count > 0:
                avg_latency = bucket.total_latency_ms / bucket.request_count

            success_rate = 0
            if bucket.request_count > 0:
                success_rate = (bucket.request_count - bucket.error_count) / bucket.request_count * 100

            result.append({
                "route": route,
                "requests": bucket.request_count,
                "errors": bucket.error_count,
                "success_rate": round(success_rate, 2),
                "avg_latency_ms": round(avg_latency, 2),
            })

        # 按请求数降序排序
        result.sort(key=lambda x: x["requests"], reverse=True)
        return result


# 全局指标收集器
metrics_collector = MetricsCollector()


@router.get(settings.metrics_path)
async def get_metrics():
    """
    获取 Prometheus 格式指标

    Returns:
        Prometheus 格式的指标文本
    """
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(
        content=metrics_collector.export_prometheus(),
        media_type="text/plain",
    )


@router.get("/metrics/summary")
async def get_metrics_summary():
    """
    获取指标摘要

    Returns:
        指标摘要 JSON
    """
    return metrics_collector.get_summary()
