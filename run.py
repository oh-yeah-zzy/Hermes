#!/usr/bin/env python3
"""
Hermes API Gateway 启动脚本

用法:
    python run.py                     使用默认配置启动
    python run.py -p 8080             使用 8080 端口启动
    python run.py --debug --reload    开发模式
"""

import argparse
import os
import sys

# 将项目目录添加到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Hermes API Gateway 启动脚本",
    )
    parser.add_argument(
        "-H",
        "--host",
        type=str,
        default="127.0.0.1",
        help="监听地址 (默认: 127.0.0.1，仅本地访问)",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8880,
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
        help="ServiceAtlas 地址",
    )
    parser.add_argument(
        "--no-registry",
        action="store_true",
        help="禁用服务注册",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    args = parser.parse_args()

    # 设置环境变量
    os.environ["HERMES_HOST"] = args.host
    os.environ["HERMES_PORT"] = str(args.port)
    os.environ["HERMES_LOG_LEVEL"] = args.log_level

    if args.debug:
        os.environ["HERMES_DEBUG"] = "true"
    if args.registry_url:
        os.environ["HERMES_REGISTRY_URL"] = args.registry_url
    if args.no_registry:
        os.environ["HERMES_REGISTRY_ENABLED"] = "false"

    # 启动服务器
    import uvicorn

    print(f"启动 Hermes API Gateway...")
    print(f"  地址: http://{args.host}:{args.port}")
    print(f"  调试模式: {'是' if args.debug else '否'}")
    print(f"  热重载: {'是' if args.reload else '否'}")
    print()

    uvicorn.run(
        "hermes.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
