"""
Web 管理界面路由

提供 Hermes 网关的 Web 管理界面
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from hermes.core.config import settings
from hermes.core.logging import get_logger

logger = get_logger("hermes.web.routes")

# 项目根目录
BASE_DIR = Path(__file__).parent.parent.parent

# 模板引擎
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Web 路由器
router = APIRouter(tags=["Web 管理界面"])

# 启动时间（用于计算运行时间）
START_TIME = time.time()


def get_template_context(request: Request, title: str, **kwargs) -> Dict[str, Any]:
    """
    生成模板上下文

    Args:
        request: FastAPI 请求对象
        title: 页面标题
        **kwargs: 额外的上下文数据

    Returns:
        模板上下文字典
    """
    return {
        "request": request,
        "title": title,
        "version": settings.app_version,
        "debug": settings.debug,
        **kwargs,
    }


def get_uptime() -> str:
    """获取运行时间（格式化）"""
    seconds = int(time.time() - START_TIME)

    if seconds < 60:
        return f"{seconds} 秒"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes} 分 {secs} 秒"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} 小时 {minutes} 分"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days} 天 {hours} 小时"


@router.get("/", include_in_schema=False)
async def dashboard(request: Request):
    """
    仪表盘首页

    显示网关概览信息：
    - 运行状态
    - 路由统计
    - 请求指标
    - 插件状态
    """
    # 获取路由缓存和插件链
    route_cache = request.app.state.route_cache
    plugin_chain = request.app.state.plugin_chain

    # 从 metrics_collector 获取指标
    from hermes.observability.metrics import metrics_collector
    metrics_data = metrics_collector.get_stats()

    # 构建统计数据
    routes = route_cache.get_routes()
    stats = {
        "uptime": get_uptime(),
        "route_count": len(routes),
        "route_enabled": sum(1 for r in routes if r.enabled),
        "plugin_count": len(plugin_chain.plugins),
        "plugins": [
            {
                "name": p.name,
                "priority": p.priority,
                "enabled": p.enabled,
            }
            for p in plugin_chain.plugins
        ],
        "registry_enabled": settings.registry_enabled,
        "registry_url": settings.registry_url if settings.registry_enabled else None,
        "registry_available": route_cache.registry_available,
        "last_route_update": datetime.fromtimestamp(route_cache.last_update).strftime("%Y-%m-%d %H:%M:%S") if route_cache.last_update > 0 else "从未更新",
    }

    # 合并指标数据
    stats.update(metrics_data)

    return templates.TemplateResponse(
        "dashboard.html",
        get_template_context(request, "Hermes - 仪表盘", stats=stats)
    )


@router.get("/services", include_in_schema=False)
async def services_page(request: Request):
    """
    服务目录页面

    显示已注册的服务列表，点击可跳转到对应服务
    """
    route_cache = request.app.state.route_cache
    services = route_cache.get_services()

    # 构建服务列表数据
    services_data = [
        {
            "id": s.id,
            "name": s.name,
            "status": s.status,
            "description": s.description,
            "icon": s.icon,
            # 使用 Hermes 代理路径
            "base_url": f"/{s.id}/",
            "service_type": s.service_type,
        }
        for s in services
    ]

    return templates.TemplateResponse(
        "services.html",
        get_template_context(request, "Hermes - 服务目录", services=services_data)
    )


@router.get("/routes", include_in_schema=False)
async def routes_page(request: Request):
    """
    路由规则页面

    显示当前加载的所有路由规则
    """
    route_cache = request.app.state.route_cache
    routes = route_cache.get_routes()

    # 构建路由列表数据
    route_list = []
    for route in routes:
        route_list.append({
            "id": route.id,
            "path_pattern": route.path_pattern,
            "methods": getattr(route, "methods", "*"),
            "target_service_id": route.target_service_id,
            "target_service_name": route.target_service.name,
            "target_service_url": route.target_service.base_url,
            "target_service_status": route.target_service.status,
            "target_service_healthy": route.target_service.healthy,
            "strip_prefix": route.strip_prefix,
            "strip_path": route.strip_path,
            "priority": route.priority,
            "enabled": route.enabled,
            "is_local": getattr(route, "is_local", False),
            "require_auth": route.auth_config.require_auth if route.auth_config else False,
        })

    context_data = {
        "routes": route_list,
        "route_count": len(route_list),
        "last_update": datetime.fromtimestamp(route_cache.last_update).strftime("%Y-%m-%d %H:%M:%S") if route_cache.last_update > 0 else "从未更新",
        "is_stale": route_cache.is_stale,
        "refresh_interval": settings.route_refresh_interval,
    }

    return templates.TemplateResponse(
        "routes.html",
        get_template_context(request, "Hermes - 路由规则", **context_data)
    )


@router.get("/metrics-view", include_in_schema=False)
async def metrics_page(request: Request):
    """
    指标监控页面

    显示请求统计和性能指标
    """
    from hermes.observability.metrics import metrics_collector

    # 获取详细指标
    stats = metrics_collector.get_stats()
    route_stats = metrics_collector.get_route_stats()

    context_data = {
        "stats": stats,
        "route_stats": route_stats,
    }

    return templates.TemplateResponse(
        "metrics.html",
        get_template_context(request, "Hermes - 指标监控", **context_data)
    )


@router.get("/api/stats", include_in_schema=False)
async def api_stats(request: Request):
    """
    获取实时统计数据（JSON API）

    供前端 AJAX 调用
    """
    from hermes.observability.metrics import metrics_collector

    route_cache = request.app.state.route_cache
    plugin_chain = request.app.state.plugin_chain

    stats = metrics_collector.get_stats()
    stats["uptime"] = get_uptime()
    stats["route_count"] = route_cache.route_count
    stats["plugin_count"] = len(plugin_chain.plugins)

    return stats


# === 本地路由配置 API ===


class LocalRoutesContent(BaseModel):
    """本地路由配置内容"""
    content: str


def get_local_routes_file() -> Path:
    """获取本地路由配置文件路径"""
    local_routes_file = Path(settings.local_routes_file)
    if not local_routes_file.is_absolute():
        local_routes_file = BASE_DIR / settings.local_routes_file
    return local_routes_file


@router.get("/routes/edit", include_in_schema=False)
async def routes_edit_page(request: Request):
    """
    本地路由配置编辑页面

    提供 YAML 编辑器，允许编辑本地路由配置文件
    """
    route_cache = request.app.state.route_cache
    local_routes_file = get_local_routes_file()

    # 读取当前配置内容
    yaml_content = ""
    if local_routes_file.exists():
        try:
            yaml_content = local_routes_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取本地路由配置失败: {e}")

    # 如果文件不存在，提供默认模板
    if not yaml_content:
        yaml_content = """# Hermes 本地路由配置
#
# 本地路由优先级高于 ServiceAtlas 规则
# 当 ServiceAtlas 不可用时，将使用此配置

# 路由规则列表
routes:
  # 示例：直接代理到指定服务
  # - path_pattern: "/auth/**"
  #   target_url: "http://localhost:8000"
  #   strip_prefix: true
  #   strip_path: "/auth"
  #   priority: 100
  #   methods: "*"
  #   auth_config:
  #     require_auth: false

# 默认认证服务 ID（未指定时使用）
default_auth_service_id: "aegis"

# 全局认证配置（可被路由级别覆盖）
default_auth_config:
  require_auth: false
  public_paths:
    - "/health"
    - "/ready"
    - "/docs"
"""

    context_data = {
        "yaml_content": yaml_content,
        "local_routes_file": str(local_routes_file),
        "local_priority_boost": settings.local_routes_priority_boost,
        "remote_routes": route_cache.remote_route_count,
        "local_routes": route_cache.local_route_count,
        "total_routes": route_cache.route_count,
        "registry_available": route_cache.registry_available,
    }

    return templates.TemplateResponse(
        "routes_edit.html",
        get_template_context(request, "Hermes - 本地路由配置", **context_data)
    )


@router.get("/api/routes/local", include_in_schema=False)
async def get_local_routes_content():
    """获取本地路由配置文件内容"""
    local_routes_file = get_local_routes_file()

    if not local_routes_file.exists():
        return JSONResponse({"content": "", "exists": False})

    try:
        content = local_routes_file.read_text(encoding="utf-8")
        return JSONResponse({"content": content, "exists": True})
    except Exception as e:
        logger.error(f"读取本地路由配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置失败: {e}")


@router.put("/api/routes/local", include_in_schema=False)
async def save_local_routes_content(request: Request, data: LocalRoutesContent):
    """
    保存本地路由配置文件

    保存后自动重新加载路由规则
    """
    local_routes_file = get_local_routes_file()

    # 先验证 YAML 语法
    try:
        import yaml
        config = yaml.safe_load(data.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 语法错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解析失败: {e}")

    # 验证配置结构
    if config and not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="配置必须是 YAML 字典格式")

    # 保存文件
    try:
        # 确保目录存在
        local_routes_file.parent.mkdir(parents=True, exist_ok=True)
        local_routes_file.write_text(data.content, encoding="utf-8")
        logger.info(f"本地路由配置已保存: {local_routes_file}")
    except Exception as e:
        logger.error(f"保存本地路由配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    # 重新加载路由
    route_cache = request.app.state.route_cache
    route_cache.reload_local_routes()

    return JSONResponse({
        "success": True,
        "message": "配置已保存并重新加载",
        "local_routes": route_cache.local_route_count,
        "total_routes": route_cache.route_count,
    })


@router.post("/api/routes/local/validate", include_in_schema=False)
async def validate_local_routes_content(data: LocalRoutesContent):
    """验证本地路由配置语法"""
    try:
        import yaml
        config = yaml.safe_load(data.content)
    except yaml.YAMLError as e:
        return JSONResponse({
            "valid": False,
            "error": f"YAML 语法错误: {e}",
        }, status_code=400)
    except Exception as e:
        return JSONResponse({
            "valid": False,
            "error": f"解析失败: {e}",
        }, status_code=400)

    # 检查配置结构
    if config is None:
        return JSONResponse({
            "valid": True,
            "route_count": 0,
            "message": "配置为空",
        })

    if not isinstance(config, dict):
        return JSONResponse({
            "valid": False,
            "error": "配置必须是 YAML 字典格式",
        }, status_code=400)

    routes = config.get("routes", [])
    if not isinstance(routes, list):
        return JSONResponse({
            "valid": False,
            "error": "'routes' 必须是列表",
        }, status_code=400)

    # 验证每条路由
    errors = []
    for i, route in enumerate(routes):
        if not isinstance(route, dict):
            errors.append(f"路由 #{i+1}: 必须是字典格式")
            continue
        if not route.get("path_pattern"):
            errors.append(f"路由 #{i+1}: 缺少 path_pattern")
        if not route.get("target_url") and not route.get("target_service_id"):
            errors.append(f"路由 #{i+1}: 必须指定 target_url 或 target_service_id")

    if errors:
        return JSONResponse({
            "valid": False,
            "error": "; ".join(errors),
        }, status_code=400)

    return JSONResponse({
        "valid": True,
        "route_count": len(routes),
        "message": f"验证通过，共 {len(routes)} 条规则",
    })
