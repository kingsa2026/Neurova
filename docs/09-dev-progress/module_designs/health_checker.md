# Neurova 系统健康检查和错误恢复模块

> 版本: 1.0.0
> 日期: 2025-05-14
> 状态: 已完成

---

## 1. 概述

### 1.1 模块目标

为 Neurova 提供完整的系统健康监控和自动错误恢复能力：

1. **健康检查**：监控各系统组件的运行状态
2. **自动恢复**：检测到故障时自动执行恢复策略
3. **告警机制**：问题发生时及时通知管理员
4. **运维支持**：提供 K8s 探针和监控接口

### 1.2 设计原则

| 原则 | 描述 |
|------|------|
| **非侵入** | 不影响主业务流程，轻量级检查 |
| **可扩展** | 支持注册自定义检查和恢复策略 |
| **容错** | 检查失败不影响系统运行 |
| **异步** | 后台监控不阻塞主线程 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    系统健康检查和恢复架构                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                   HealthChecker (健康检查器)                 │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │ │
│  │  │ 健康检查注册  │  │ 检查执行器   │  │ 恢复策略管理  │   │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐      │
│  │ 组件检查器  │     │ 组件检查器  │     │ 组件检查器  │      │
│  │ Database    │     │   Memory    │     │    LLM      │      │
│  └─────────────┘     └─────────────┘     └─────────────┘      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                     API 层 (FastAPI)                         │ │
│  │  GET /v1/health         - 快速状态检查                       │ │
│  │  GET /v1/health/report - 详细健康报告                       │ │
│  │  POST /v1/health/recover - 触发恢复                         │ │
│  │  GET /v1/health/live   - K8s Liveness                       │ │
│  │  GET /v1/health/ready  - K8s Readiness                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| `HealthChecker` | `core/health_checker.py` | 健康检查核心引擎 |
| `HealthCheck` | `core/health_checker.py` | 健康检查定义 |
| `RecoveryStrategy` | `core/health_checker.py` | 恢复策略定义 |
| `health.py` | `api/endpoints/` | API 路由 |

---

## 3. 健康状态

### 3.1 状态枚举

| 状态 | 值 | 说明 |
|------|-----|------|
| `HEALTHY` | healthy | 所有检查通过 |
| `DEGRADED` | degraded | 降级运行，有警告 |
| `UNHEALTHY` | unhealthy | 不健康，有错误 |
| `UNKNOWN` | unknown | 状态未知 |

### 3.2 检查类型

| 类型 | 说明 | 默认检查项 |
|------|------|-----------|
| `DATABASE` | 数据库检查 | 连接、查询 |
| `MEMORY` | 记忆系统检查 | 存储、索引 |
| `LLM` | LLM 服务检查 | 服务可用性 |
| `API` | API 服务检查 | 路由加载 |
| `STORAGE` | 存储空间检查 | 磁盘空间 |
| `SERVICE` | 通用服务检查 | 组件健康 |

---

## 4. 健康检查 API

### 4.1 端点列表

| 方法 | 端点 | 描述 |
|------|------|------|
| GET | `/v1/health` | 获取系统健康状态 |
| GET | `/v1/health/checks` | 获取所有检查项及结果 |
| GET | `/v1/health/checks/{name}` | 获取单个检查结果 |
| POST | `/v1/health/checks/{name}/run` | 手动执行检查 |
| GET | `/v1/health/report` | 获取详细健康报告 |
| POST | `/v1/health/recover` | 触发错误恢复 |
| POST | `/v1/health/monitoring/start` | 启动后台监控 |
| POST | `/v1/health/monitoring/stop` | 停止后台监控 |
| GET | `/v1/health/live` | K8s Liveness 探针 |
| GET | `/v1/health/ready` | K8s Readiness 探针 |

### 4.2 响应示例

**GET /v1/health**

```json
{
  "status": "healthy",
  "healthy": true,
  "timestamp": "2025-05-14T14:30:00",
  "uptime": "2h 30m"
}
```

**GET /v1/health/report**

```json
{
  "overall_status": "healthy",
  "components": {
    "database": {
      "name": "database",
      "status": "healthy",
      "message": "数据库正常，当前 152 条记忆",
      "duration_ms": 12.5
    },
    "memory": {
      "name": "memory",
      "status": "healthy",
      "message": "记忆系统正常，5 个向量索引"
    }
  },
  "summary": {
    "total_checks": 5,
    "healthy": 5,
    "degraded": 0,
    "unhealthy": 0
  },
  "recommendations": ["✅ 系统运行正常"]
}
```

---

## 5. 恢复策略

### 5.1 恢复动作

| 动作 | 说明 |
|------|------|
| `RESTART` | 重启服务 |
| `RECONNECT` | 重新连接 |
| `RELOAD` | 重新加载 |
| `FALLBACK` | 降级使用备用方案 |
| `ALERT` | 发送告警 |
| `IGNORE` | 忽略 |

### 5.2 默认策略

```
┌─────────────────────────────────────────────────────────────┐
│                    默认恢复策略                               │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  策略 1: critical_service_restart                            │
│  条件: 关键组件不健康                                        │
│  动作: 重启 -> 告警                                          │
│                                                              │
│  策略 2: non_critical_degrade                                │
│  条件: 非关键组件不健康                                      │
│  动作: 降级 -> 告警                                          │
│                                                              │
│  策略 3: timeout_retry                                      │
│  条件: 超时错误                                              │
│  动作: 重新连接                                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 恢复流程

```
检测到故障
    │
    ▼
检查冷却时间
    │
    ├── 未过冷却 ──► 跳过
    │
    ▼
检查最大尝试次数
    │
    ├── 达到上限 ──► 跳过（需要人工干预）
    │
    ▼
执行恢复动作
    │
    ├── RESTART ──► 发布重启事件
    ├── RECONNECT ──► 发布重连事件
    ├── FALLBACK ──► 启用备用方案
    └── ALERT ──► 发送告警
    │
    ▼
更新恢复记录
    │
    ▼
进入冷却期
```

---

## 6. 使用示例

### 6.1 注册自定义检查

```python
from neurova.core.health_checker import (
    get_health_checker,
    create_service_check,
)

checker = get_health_checker()

# 注册自定义检查
checker.register_check(create_service_check(
    name="my_component",
    checker=lambda: {"status": "healthy", "message": "组件正常"},
    critical=True,
    interval=30.0
))
```

### 6.2 执行检查并获取报告

```python
# 执行所有检查
results = await checker.run_all_checks()

# 获取健康报告
report = await checker.get_health_report()

print(f"整体状态: {report.overall_status}")
print(f"健康检查: {report.summary}")
for rec in report.recommendations:
    print(rec)
```

### 6.3 手动触发恢复

```python
# 触发恢复流程
result = await checker.check_and_recover()

for action in result["actions_taken"]:
    print(f"执行: {action['strategy']}")
    print(f"动作: {action['actions_taken']}")
```

### 6.4 Kubernetes 探针配置

```yaml
# deployment.yaml
livenessProbe:
  httpGet:
    path: /api/v1/health/live
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 15

readinessProbe:
  httpGet:
    path: /api/v1/health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

---

## 7. 默认检查项

| 检查项 | 类型 | 关键 | 间隔 | 说明 |
|--------|------|------|------|------|
| database | DATABASE | ✅ | 30s | SQLite 数据库连接和查询 |
| memory | MEMORY | ✅ | 60s | 记忆存储目录和向量索引 |
| llm | LLM | ✅ | 120s | LLM 服务可用性 |
| api | API | ✅ | 60s | API 端点模块加载 |
| storage | STORAGE | ❌ | 300s | 磁盘空间检查 |

---

## 8. 目录结构

```
neurova/
├── core/
│   └── health_checker.py          # 健康检查核心 ⭐
└── api/
    └── endpoints/
        └── health.py              # 健康检查 API ⭐
```

---

## 9. 后续扩展

### 9.1 计划功能

1. **告警系统集成**
   - 接入钉钉/飞书/Slack 通知
   - 支持邮件告警
   - 告警升级策略

2. **历史记录**
   - 健康状态历史存储
   - 趋势分析
   - 报告导出

3. **性能监控**
   - 响应时间统计
   - 资源使用监控
   - 性能告警

4. **分布式支持**
   - 多实例健康协调
   - 主从选举
   - 健康状态同步

### 9.2 告警配置示例

```python
# 未来版本：配置告警规则
checker.configure_alert(
    channel="dingtalk",
    webhook_url="https://oapi.dingtalk.com/...",
    trigger_on=["critical", "repeated_failure"]
)
```

---

## 10. 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2025-05-14 | 1.0.0 | 初始版本，实现健康检查核心、API、恢复机制 |
