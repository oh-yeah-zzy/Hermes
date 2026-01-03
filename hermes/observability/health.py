"""
健康检查模块

提供网关健康状态检查端点
"""

from fastapi import APIRouter

from hermes.core.config import settings

router = APIRouter(tags=["健康检查"])


@router.get("/health")
async def health_check():
    """
    健康检查端点

    Returns:
        健康状态信息
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
async def readiness_check():
    """
    就绪检查端点

    检查服务是否准备好接收流量
    """
    # TODO: 可以添加更多检查，如路由缓存是否加载完成
    return {
        "status": "ready",
        "service": settings.app_name,
    }
