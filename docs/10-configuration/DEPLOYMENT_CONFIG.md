# 部署配置（Dockerfile / docker-compose / Helm）

> 更新时间: 2026-09-18 · 关联 Issue: #61 · 守卫: `scripts/ci/deploy_config_consistency_check.py`

Neurova 同一套后端服务有三种交付形态，它们必须共享同一份接线契约：

| 形态 | 文件 | 用途 |
|------|------|------|
| 容器镜像 | `Dockerfile` | 生产镜像（Helm/compose 的底座） |
| 单机编排 | `docker-compose.yml` | 本地/单机部署 |
| Kubernetes | `helm/neurova/` | 生产集群部署 |

## 统一契约（改动前先读）

- **端口**：后端 `9527`，前端 `8100`
- **健康检查**：`GET /health`，周期 30s、超时 5s、启动宽限 30s、失败阈值 3
  （Dockerfile `HEALTHCHECK` / compose `healthcheck` / Helm `backend.healthCheck` 三处同源）
- **后端资源**：requests `500m` / `1Gi`，limits `2000m` / `4Gi`
- **运行时**：Python 3.12（必须落在 CI 实测矩阵 3.11/3.12 内）、Node 20（与 CI 一致）
- **版本**：`Chart.appVersion` == `neurova/__init__.py::__version__`；
  镜像 `tag` 留空跟随 appVersion（不要写死 `latest`）
- **持久化**：`database.persistence.enabled=true` 时数据卷必须是 PVC
  （`<fullname>-data`，`subPath` 分出 `agent_workspaces/` 与 `sessions/`）
- **鉴权**：生产多副本必须提供 `auth.jwtSecret`（≥32 字节）；
  `values-production.yaml` 已开 `auth.requireJwtSecret`，缺失时 helm 渲染期直接失败

## 环境变量命名

应用侧读取的键名是唯一事实来源，配置里写错的名字**不会报错**，只会静默失效：

| 配置里该写的键 | 读取方 | 常见错误写法（零读取方） |
|----------------|--------|--------------------------|
| `NEUROVA_LOG_LEVEL` | `start_server.py` | ~~`LOG_LEVEL`~~ |
| `NEUROVA_LOG_FILE` | `neurova/api/endpoints/console_system.py` | ~~`LOG_FILE`~~ |
| `NEUROVA_LOG_JSON` | `neurova/core/logger.py` | ~~`LOG_FORMAT`~~ |
| `NEUROVA_DB_PATH` | `neurova/core/db_indexes.py` | ~~`DATABASE_PATH`~~ |
| `NEUROVA_CORS_ORIGINS` | `neurova/api/middleware.py` | ~~`CORS_ORIGINS`~~ |
| `NEUROVA_JWT_SECRET` | `neurova/api/auth.py` | — |
| `NEUROVA_PORT` / `NEUROVA_HOST` | `start_server.py` | — |

模型/服务商默认值**不通过环境变量配置**：运行时以
`~/.neurova/config/providers.json` 与 `agent_workspaces/<agent_id>/agent_config.json`
为准（配置页写入）。

## 门禁

```bash
python scripts/ci/deploy_config_consistency_check.py        # 人读报告
python scripts/ci/deploy_config_consistency_check.py --json # 机器可读
```

R1~R11 覆盖端口 / 健康检查 / 资源 / 镜像与版本 / 环境变量可读性 / 持久化 /
鉴权密钥 / 硬依赖声明 / 门禁接线 / 镜像内配置资产 / Helm values 引用完整性。

接线：

- push / PR：`.cnb.yml` 的 `deploy-config` 流水线与 `.github/workflows/ci.yml`
  的 `deploy-config` job 双侧阻断；
- 周级巡检：`.cnb.yml` 的 `"crontab: 30 3 * * 1"`（每周一 03:30，Asia/Shanghai），
  抓的是"没人提交、但上游变了"的时间维度漂移（基础镜像发版、依赖 CVE）。

> 平台定时任务说明：CNB 的 `crontab:` 只接受标准 5 段 POSIX cron 表达式，
> 最小调度间隔 5 分钟；周级 cadence 用第 5 段（星期）表达即可，不存在
> "间隔单位"写法，也没有任务存活时长上限。

契约守卫：`tests/unit/test_deploy_config_guard.py`（已进
`scripts/ci/protected_tests.txt`），含负向控制用例——门禁退化成"永远绿"会被抓到。

## 配置 CORS

`config/cors.json` 是运行时读取的资产，**必须**在 `.dockerignore` 里显式放行
（`!config/cors.json`）：被排除时构建与启动都正常，只是 CORS 来源静默回落到
内置默认值（生产浏览器请求被拒且日志无线索）。门禁 R10 会拦住这种形态。
