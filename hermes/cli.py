"""
命令行入口

提供 CLI 参数解析
"""

import argparse
import sys


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Hermes API Gateway - 轻量级 API 网关",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  hermes                           使用默认配置启动
  hermes -p 8080                   使用 8080 端口启动
  hermes -H 0.0.0.0 -p 80          监听所有地址的 80 端口（内网可访问）
  hermes --debug --reload          开发模式
  hermes --registry-url http://localhost:8888  指定注册中心
  hermes --no-registry             不连接注册中心（离线模式）
        """,
    )

    parser.add_argument(
        "-H",
        "--host",
        type=str,
        default=None,
        help="监听地址 (默认: 127.0.0.1，仅本地访问)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help="监听端口 (默认: 8880)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用调试模式",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用热重载（开发模式）",
    )
    parser.add_argument(
        "--registry-url",
        type=str,
        default=None,
        help="ServiceAtlas 地址 (默认: http://localhost:8888)",
    )
    parser.add_argument(
        "--no-registry",
        action="store_true",
        help="禁用服务注册（离线模式）",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别 (默认: INFO)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Hermes API Gateway v0.1.0",
    )

    return parser.parse_args()


def main():
    """CLI 主入口"""
    args = parse_args()

    # 设置环境变量（覆盖配置）
    import os

    if args.host is not None:
        os.environ["HERMES_HOST"] = args.host
    if args.port is not None:
        os.environ["HERMES_PORT"] = str(args.port)
    if args.debug:
        os.environ["HERMES_DEBUG"] = "true"
    if args.registry_url is not None:
        os.environ["HERMES_REGISTRY_URL"] = args.registry_url
    if args.no_registry:
        os.environ["HERMES_REGISTRY_ENABLED"] = "false"
    if args.log_level is not None:
        os.environ["HERMES_LOG_LEVEL"] = args.log_level

    # 重新加载配置
    from hermes.core.config import Settings

    settings = Settings()

    # 启动服务器
    import uvicorn

    uvicorn.run(
        "hermes.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
