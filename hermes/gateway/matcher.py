"""
路由匹配器模块

根据请求路径匹配路由规则，支持通配符模式
"""

import fnmatch
import re
from typing import List, Optional

from hermes.schemas.route import RouteInfo


class RouteMatcher:
    """
    路由匹配器

    支持的路径模式：
    - /api/v1/users - 精确匹配
    - /api/v1/users/* - 匹配一级子路径
    - /api/v1/** - 匹配所有子路径
    - /api/v1/users/{id} - 路径参数
    """

    @staticmethod
    def match_path(pattern: str, path: str) -> bool:
        """
        匹配路径

        Args:
            pattern: 路径模式
            path: 请求路径

        Returns:
            是否匹配
        """
        # 处理 ** 通配符（匹配任意深度的子路径）
        if "**" in pattern:
            # 使用临时占位符保护 ** 的转换，避免被后续的 * 替换影响
            regex_pattern = pattern.replace("**", "\x00DOUBLESTAR\x00")
            regex_pattern = regex_pattern.replace("*", "[^/]*")
            regex_pattern = regex_pattern.replace("\x00DOUBLESTAR\x00", ".*")
            regex_pattern = f"^{regex_pattern}$"
            return bool(re.match(regex_pattern, path))

        # 处理 * 通配符（匹配单级路径）
        if "*" in pattern:
            return fnmatch.fnmatch(path, pattern)

        # 处理路径参数 {id}
        if "{" in pattern:
            regex_pattern = re.sub(r"\{[^}]+\}", r"[^/]+", pattern)
            regex_pattern = f"^{regex_pattern}$"
            return bool(re.match(regex_pattern, path))

        # 精确匹配
        return pattern == path

    @staticmethod
    def match_method(allowed_methods: str, method: str) -> bool:
        """
        匹配 HTTP 方法

        Args:
            allowed_methods: 允许的方法（逗号分隔或 *）
            method: 请求方法

        Returns:
            是否匹配
        """
        if allowed_methods == "*":
            return True

        methods = [m.strip().upper() for m in allowed_methods.split(",")]
        return method.upper() in methods

    def match(
        self,
        routes: List[RouteInfo],
        method: str,
        path: str,
    ) -> Optional[RouteInfo]:
        """
        从路由列表中查找匹配的路由

        Args:
            routes: 路由规则列表（应按优先级降序排列）
            method: HTTP 方法
            path: 请求路径

        Returns:
            匹配的路由，如果没有匹配则返回 None
        """
        for route in routes:
            # 跳过未启用的路由
            if not route.enabled:
                continue

            # 检查路径匹配
            if not self.match_path(route.path_pattern, path):
                continue

            # 检查 HTTP 方法匹配（如果路由定义了 methods 字段）
            if hasattr(route, 'methods') and route.methods:
                if not self.match_method(route.methods, method):
                    continue

            # 路由匹配成功
            return route

        return None


def build_upstream_path(route: RouteInfo, request_path: str) -> str:
    """
    构建上游服务路径

    Args:
        route: 匹配的路由
        request_path: 原始请求路径

    Returns:
        上游服务路径
    """
    upstream_path = request_path

    # 处理路径前缀剥离
    if route.strip_prefix and route.strip_path:
        prefix = route.strip_path.rstrip("/")
        if request_path.startswith(prefix):
            upstream_path = request_path[len(prefix):] or "/"

    # 确保路径以 / 开头
    if not upstream_path.startswith("/"):
        upstream_path = "/" + upstream_path

    return upstream_path


def build_upstream_url(route: RouteInfo, request_path: str, query_string: str = "") -> str:
    """
    构建完整的上游服务 URL

    Args:
        route: 匹配的路由
        request_path: 原始请求路径
        query_string: 查询字符串

    Returns:
        完整的上游服务 URL
    """
    base_url = route.target_service.base_url.rstrip("/")
    upstream_path = build_upstream_path(route, request_path)

    url = f"{base_url}{upstream_path}"

    if query_string:
        url = f"{url}?{query_string}"

    return url


# 全局路由匹配器实例
route_matcher = RouteMatcher()
