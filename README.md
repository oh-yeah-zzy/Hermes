# Hermes API Gateway

<p align="center">
  <strong>轻量级 API 网关</strong><br>
  路由转发 · 负载均衡 · 限流熔断 · 认证集成 · 可观测性
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.104+-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="License">
</p>

---

## 概述

Hermes 是一个轻量级 API 网关，作为微服务生态的流量入口。它支持从 ServiceAtlas 获取动态路由规则，也支持本地路由配置，具备请求转发、负载均衡、限流熔断、认证集成等核心网关功能。

### 核心特性

| 特性 | 说明 |
|------|------|
| **动态路由** | 从 ServiceAtlas 获取路由规则，支持本地配置回退 |
| **本地路由** | 通过 `routes.yaml` 配置本地路由，Web 界面可编辑 |
| **负载均衡** | 轮询、随机、最少连接三种策略 |
| **限流** | 令牌桶算法，支持全局/路由/IP 多维度限流 |
| **熔断** | 熔断器模式，保护上游服务 |
| **认证集成** | 可选认证插件，支持跳转登录、服务降级 |
| **服务卡片** | 仪表盘展示已注册服务状态 |
| **插件系统** | 可扩展的过滤器链架构 |
| **可观测性** | Prometheus 格式指标、请求追踪、健康检查 |
| **Web 界面** | 仪表盘、路由管理、指标监控（支持 Basic Auth） |

### 技术栈

- **后端**: Python 3.9+ / FastAPI / httpx
- **配置**: Pydantic Settings / YAML
- **日志**: 结构化 JSON 日志

---

## 快速开始

### 1. 安装依赖

```bash
cd Hermes
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 生产模式（连接 ServiceAtlas）
python run.py --registry-url http://localhost:9000

# 仅使用本地路由
python run.py --no-registry

# 开发模式（热重载）
python run.py --debug --reload
```

### 3. 访问

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8080 | Web 管理界面（仪表盘） |
| http://127.0.0.1:8080/routes | 路由规则列表 |
| http://127.0.0.1:8080/routes/edit | 本地路由配置编辑器 |
| http://127.0.0.1:8080/metrics-view | 指标监控页面 |
| http://127.0.0.1:8080/health | 健康检查 |
| http://127.0.0.1:8080/metrics | Prometheus 指标 |
| http://127.0.0.1:8080/docs | API 文档（调试模式） |

**默认登录凭据**: `admin` / `hermes123`

---

## 本地路由配置

编辑 `routes.yaml` 或通过 Web 界面 `/routes/edit` 配置：

```yaml
# 路由规则列表
routes:
  # 直接代理到指定 URL
  - path_pattern: "/auth/**"
    target_url: "http://localhost:8000"
    strip_prefix: true
    strip_path: "/auth"
    priority: 100
    methods: "*"
    auth_config:
      require_auth: false

  # 使用 ServiceAtlas 中的服务
  - path_pattern: "/api/docs/**"
    target_service_id: "deckview"
    priority: 50
    auth_config:
      require_auth: true
      auth_service_id: "aegis"
      public_paths:
        - "/api/docs/public/**"

# 全局认证配置
default_auth_config:
  require_auth: false
  public_paths:
    - "/health"
    - "/docs"
```

### 路由优先级

- 本地路由优先级自动提升 1000（可配置）
- 数值越大优先级越高
- 本地路由优先于 ServiceAtlas 远程路由

---

## 命令行参数

```bash
python run.py [选项]
```

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--host` | `-H` | 监听地址 | 0.0.0.0 |
| `--port` | `-p` | 监听端口 | 8080 |
| `--debug` | | 启用调试模式 | false |
| `--reload` | | 启用热重载 | false |
| `--registry-url` | | ServiceAtlas 地址 | http://localhost:9000 |
| `--no-registry` | | 禁用服务注册 | false |
| `--log-level` | | 日志级别 | INFO |

---

## 环境变量配置

创建 `.env` 文件或设置环境变量（前缀 `HERMES_`）：

```bash
# === 服务配置 ===
HERMES_HOST=0.0.0.0
HERMES_PORT=8080
HERMES_DEBUG=false

# === ServiceAtlas 配置 ===
HERMES_REGISTRY_ENABLED=true
HERMES_REGISTRY_URL=http://localhost:9000
HERMES_SERVICE_ID=hermes
HERMES_SERVICE_NAME=Hermes API Gateway

# === 代理配置 ===
HERMES_PROXY_TIMEOUT=30.0
HERMES_PROXY_MAX_RETRIES=3

# === 负载均衡 ===
HERMES_LOAD_BALANCE_STRATEGY=round_robin  # round_robin, random, least_conn

# === 限流配置 ===
HERMES_RATE_LIMIT_ENABLED=true
HERMES_RATE_LIMIT_GLOBAL_QPS=10000
HERMES_RATE_LIMIT_PER_ROUTE_QPS=1000
HERMES_RATE_LIMIT_PER_IP_QPS=100

# === 熔断配置 ===
HERMES_CIRCUIT_BREAKER_ENABLED=true
HERMES_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
HERMES_CIRCUIT_BREAKER_TIMEOUT=30.0

# === Web 界面安全 ===
HERMES_WEB_AUTH_ENABLED=true
HERMES_WEB_AUTH_USERNAME=admin
HERMES_WEB_AUTH_PASSWORD=hermes123

# === 本地路由配置 ===
HERMES_LOCAL_ROUTES_ENABLED=true
HERMES_LOCAL_ROUTES_FILE=routes.yaml
HERMES_LOCAL_ROUTES_PRIORITY_BOOST=1000
HERMES_FALLBACK_TO_LOCAL=true

# === 认证插件 ===
HERMES_AUTH_PLUGIN_ENABLED=true
HERMES_AUTH_DEGRADE_ALLOW=false
```

---

## 认证插件

认证插件默认启用，Hermes 会根据 **ServiceAtlas 下发的路由规则** 中的 `auth_config` 检查认证状态：

```bash
# 禁用认证插件（默认启用）
export HERMES_AUTH_PLUGIN_ENABLED=false

# 认证服务不可用时是否放行（降级策略）
export HERMES_AUTH_DEGRADE_ALLOW=false
```

> **注意**：`login_redirect` 由 ServiceAtlas 自动生成，使用网关代理路径（如 `/aegis/admin/login`）。
> 服务注册时在 `service_meta.auth_config` 中声明认证需求，路由规则会自动继承。

### 服务注册时声明认证需求（推荐）

服务注册时在 `service_meta` 中声明 `auth_config`，ServiceAtlas 会自动应用到路由规则：

```python
# 服务注册时声明认证需求
metadata={
    "auth_config": {
        "require_auth": True,
        "auth_service_id": "aegis",
        "public_paths": ["/health", "/api/docs"],
    }
}
```

`login_redirect` 会自动生成为网关代理路径（如 `/aegis/admin/login`），无需手动配置。

### 认证流程

```
请求 → 路由匹配 → AuthPlugin
                    ├─ 不需认证 (require_auth=false) → 转发
                    ├─ 公开路径 (public_paths) → 转发
                    ├─ 已认证 (有有效 Token) → 转发
                    └─ 未认证 → 重定向登录（如配置）/ 返回 401
```

---

## 与 ServiceAtlas 集成

Hermes 从 ServiceAtlas 获取路由规则。启动顺序：

```bash
# 1. 启动 ServiceAtlas
cd ../ServiceAtlas
python run.py

# 2. 启动 Hermes
cd ../Hermes
python run.py --registry-url http://localhost:9000
```

### 路由规则来源

1. **远程路由**: 从 ServiceAtlas 的 `/api/v1/gateway/routes` 获取
2. **本地路由**: 从 `routes.yaml` 加载（优先级更高）

当 ServiceAtlas 不可用时，自动回退到本地路由配置。

---

## 架构设计

### 请求处理流程

```
Client
   ↓
Middleware (RequestID, WebAuth)
   ↓
PluginChain.before()
   ├─ AuthenticationPlugin (认证检查, 优先级 50)
   ├─ RateLimitPlugin (限流检查, 优先级 100)
   ├─ CircuitBreakerPlugin (熔断检查, 优先级 200)
   └─ HeaderTransformPlugin (头部处理, 优先级 300)
   ↓
RouteMatcher (路由匹配)
   ↓
LoadBalancer (负载均衡)
   ↓
Proxy (代理转发)
   ↓
PluginChain.after()
   ↓
Response
```

### 插件系统

插件按优先级顺序执行（数字越小越先执行）：

| 优先级 | 插件 | 功能 |
|-------|------|------|
| 50 | AuthenticationPlugin | 认证（可选） |
| 100 | RateLimitPlugin | 限流 |
| 200 | CircuitBreakerPlugin | 熔断 |
| 300 | HeaderTransformPlugin | 头部透传 |

---

## 项目结构

```
Hermes/
├── hermes/
│   ├── core/                   # 核心配置
│   │   ├── config.py           # Pydantic Settings
│   │   ├── logging.py          # 日志配置
│   │   └── exceptions.py       # 异常定义
│   ├── gateway/                # 网关核心
│   │   ├── router.py           # 网关端点
│   │   ├── matcher.py          # 路由匹配
│   │   ├── proxy.py            # 代理转发
│   │   └── balancer.py         # 负载均衡
│   ├── plugins/                # 插件系统
│   │   ├── base.py             # 插件基类
│   │   ├── authentication.py   # 认证插件
│   │   ├── headers.py          # 头部透传
│   │   ├── rate_limit.py       # 限流
│   │   └── circuit_breaker.py  # 熔断
│   ├── registry/               # ServiceAtlas 集成
│   │   ├── client.py           # 服务注册
│   │   └── route_cache.py      # 路由缓存
│   ├── middleware/             # 中间件
│   │   ├── request_id.py       # 请求 ID
│   │   └── web_auth.py         # Web 界面认证
│   ├── observability/          # 可观测性
│   │   ├── health.py           # 健康检查
│   │   └── metrics.py          # 指标收集
│   ├── schemas/                # 数据模型
│   │   └── route.py            # 路由模型
│   ├── web/                    # Web 界面
│   │   └── routes.py           # Web 路由
│   └── main.py                 # 应用入口
├── templates/                  # HTML 模板
│   ├── base.html
│   ├── dashboard.html
│   ├── routes.html
│   ├── routes_edit.html
│   └── metrics.html
├── static/                     # 静态资源
│   ├── css/style.css
│   └── js/main.js
├── routes.yaml                 # 本地路由配置
├── run.py                      # 启动脚本
└── requirements.txt
```

---

## 许可证

MIT License
