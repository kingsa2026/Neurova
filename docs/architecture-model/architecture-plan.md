# Neurova 架构分析 — 范围与路由计划

生成日期：2026-09-19
产出技能：`explore`（路由）→ `system-modeler`（主）+ `flow-visualizer` / `dependency-impact-analyzer` /
`deployment-topology-analyzer` / `risk-quality-reviewer`（辅）；基础层 `c4model` + `graphviz`。

## 架构问题（本次要回答什么）

| # | 决策问题 | 视图层 | 负责技能 |
|---|----------|--------|----------|
| Q1 | Neurova 整体是什么结构，边界在哪里，谁负责什么 | L1 / L2 | system-modeler |
| Q2 | Agent 内部如何组织，深度模块与 `agent_ref` 注入是否真的成立 | L3 / L4 | system-modeler |
| Q3 | 一次对话请求穿过系统的完整路径是什么，有无断点 | 运行时流 | flow-visualizer |
| Q4 | 模块依赖方向如何，改动会波及哪些消费方 | 依赖图 | dependency-impact-analyzer |
| Q5 | 系统实际运行在哪里，进程/端口/存储/发布路径 | 运行时拓扑 | deployment-topology-analyzer |
| Q6 | 存在哪些结构性风险，哪些会阻断 AI agent 安全修改代码 | 风险图 | risk-quality-reviewer |
| Q7 | 架构文档与代码是否已漂移，图能否回溯到证据 | 元校验 | architecture-health |

## 受众与用途

主受众是**需要修改本仓库代码的工程 agent 与开发者**，因此视图按"能否安全改代码"组织，
而非按汇报美观度组织。每个节点与边必须可回溯到 `文件:行号`。

## 视图状态声明

本目录下的图默认全部为 **current（现状）**。例外须显式标注：

- `target` / `proposed`：`agent_core.py` 拆分 Phase 2–7（`docs/CONTEXT.md` 记录在案，尚未实施）
- `unknown`：证据不足、需后续验证的区域，保留为 unknown 节点，不补画成完整通路

## 范围边界

纳入：`neurova/`（58 个子目录）、`NeurUI/`、`tests/`、`config/`、`deploy/` `helm/` `Dockerfile`
`docker-compose.yml`、`.github/`、`docs/01-architecture/adr/`。

不纳入：`node_modules/` `dist/` `__pycache__/` `models/`（本地权重）`logs/` `backups/`
`MagicMock/`（测试副产物）及根目录一次性分析产物。

## 证据计划

| 类别 | 来源 | 状态 |
|------|------|------|
| code | 模块导入、`agent_ref` 注入点、装饰器、handler、dataclass | 采集中 |
| contract | FastAPI 路由注册、Pydantic 模型、前端 `src/api/*` 调用路径 | 采集中 |
| config | `.env.example`、`config/`、`pyproject.toml`、`vite.config.*`、`docker-compose.yml` | 采集中 |
| data | SQLite 文件与路径常量、`neurova/db/`、零停机迁移、内存 dataclass | 采集中 |
| document | `docs/CONTEXT.md`、`docs/01-architecture/adr/0001-0015`、`README.md`、`AGENTS.md` | 已读 |
| runtime | 无生产遥测；端口与进程关系仅来自脚本与配置 | 缺口，标注 unknown |
| assumption | 用户未提供额外口头约束 | 无 |

## 已独立确认的证据（不依赖分区采集）

1. **规模漂移**：`docs/CONTEXT.md:13` 与 `AGENTS.md` 记 "550+ Python 文件"；`git ls-files "*.py"` 实测 **2573**，
   `neurova/` 约 171,148 行。
2. **热点错判**：`docs/CONTEXT.md:26-33` 把行数棘轮压在 `agent_core.py`（2159 行），但
   `neurova/tool_executor.py` **5159 行**、`cognitive_layers/memory_layer/manager.py` 3266 行、
   `post_chat_pipeline.py` 3068 行、`agent/chat_pipeline.py` 2626 行均无守卫（`wc -l` 实测）。
3. **可视化无源**：全仓 `find -name "*.dot|*.dsl|*.puml|*.mmd"` 零命中，`docs/*.html` 有 **25** 张手写图，
   同一依赖图存在 `-v2/-v3/-v4/-v5` 四个文件名副本 → 历史可视化不可重生成、不可 diff。
4. **文档目录分叉**：`docs/01-architecture/`（99 跟踪文件）与 `docs/architecture/`（44）同名文件内容
   md5 不同（`01-core-architecture.md`、`08-project-structure.md` 已分叉；`11-database-architecture.md` 仍相同）。
   `docs/adr/` 与 `docs/01-architecture/adr/` 曾并存——
   2026-09-21 已按 Issue #68 收口为 `docs/01-architecture/adr/` 一份（19 份 ADR 全在此）。
5. **测试面漂移**：`README.md:1413` 记"846 个后端测试文件（unit 703）"，实测 `tests/` 下 `test_*.py` **1535**
   （unit 1378 / integration 56 / e2e 5 / performance 2 / benchmarks 1）。
6. **断链命令**：`README.md:1428` 写 `python tests/run_all_tests.py`，实际文件在 `tests/runners/run_all_tests.py`；
   `AGENTS.md` 的路径是对的，README 是错的。
7. **根目录残留**：`AGENTS.md` 称 `tests/` 根目录 ad-hoc 文件已于 2026-09-16 归位，但仓库根仍有 **5 个**
   未跟踪 `test_*.py`（`test_api_server.py` 等），裸跑 `pytest` 会被 rootdir 收集。

## 交付物清单

| 文件 | 回答 | 格式 |
|------|------|------|
| `neurova.architecture.structurizr.dsl` | Q1 Q2 Q5 逻辑结构 | Structurizr DSL |
| `neurova.flows.dot` | Q3 对话/协作端到端流 | Graphviz DOT |
| `neurova.dependencies.dot` | Q4 模块依赖与改动波及面 | Graphviz DOT |
| `neurova.deployment.dot` | Q5 运行时拓扑 | Graphviz DOT |
| `neurova.risks.dot` | Q6 风险网络 | Graphviz DOT |
| `architecture-findings.md` | Q1–Q6 结论正文 + 证据 | Markdown |
| `evidence-model.json` | 节点/边/sourceRefs/置信度结构化模型 | JSON |
| `README.md` | 如何预览与重生成 | Markdown |

## 已知限制

- 本机无 `dot` / `java` CLI（已实测 `dot -V`、`java -version` 均 command not found），因此**不产出 SVG/PNG**。
  文本源以 Qoder 的 DSL / DOT 格式预览器为消费入口，保持源与模型同构、可 diff。
- 无运行时遥测，Q5 的进程与网络关系全部来自脚本与配置静态推导，运行时行为标注为推导而非观测。
- 仓库有 60 项未提交变更，其中大量为未跟踪的新子系统；本模型区分"已提交基线"与"工作区在途"。
