"""
日志配置模块

提供结构化 JSON 格式日志和标准格式日志
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """
    JSON 格式日志格式器

    输出格式:
    {
        "timestamp": "2024-01-01T12:00:00.000Z",
        "level": "INFO",
        "logger": "hermes.gateway",
        "message": "Request processed",
        "request_id": "abc-123",
        ...
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 添加额外字段（通过 extra 参数传入）
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "method"):
            log_data["method"] = record.method
        if hasattr(record, "path"):
            log_data["path"] = record.path
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = record.latency_ms
        if hasattr(record, "client_ip"):
            log_data["client_ip"] = record.client_ip
        if hasattr(record, "target_service"):
            log_data["target_service"] = record.target_service

        # 添加其他自定义字段
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        # 异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class RequestContextAdapter(logging.LoggerAdapter):
    """
    请求上下文日志适配器

    自动在日志中添加请求上下文信息（如 request_id）
    """

    def process(
        self, msg: str, kwargs: Dict[str, Any]
    ) -> tuple[str, Dict[str, Any]]:
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    logger_name: Optional[str] = None,
) -> logging.Logger:
    """
    配置日志系统

    Args:
        level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        json_format: 是否使用 JSON 格式
        logger_name: 日志器名称，None 表示配置根日志器

    Returns:
        配置好的日志器
    """
    # 获取日志器
    if logger_name:
        logger = logging.getLogger(logger_name)
    else:
        logger = logging.getLogger()

    # 设置日志级别
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # 移除现有的处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 创建控制台处理器
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # 设置格式器
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    logger.addHandler(handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志器

    Args:
        name: 日志器名称（建议使用模块名，如 hermes.gateway）

    Returns:
        日志器实例
    """
    return logging.getLogger(name)
