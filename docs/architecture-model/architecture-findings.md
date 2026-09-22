# Neurova 全面架构分析

生成日期：2026-09-19　|　视图状态：**current（现状）**
产出技能：`system-modeler`（主）+ `flow-visualizer` / `dependency-impact-analyzer` /
`deployment-topology-analyzer` / `risk-quality-reviewer`，基础层 `c4model` + `graphviz`
证据模型：[`evidence-model.json`](evidence-model.json)（67 节点 / 34 边，全部带可解析 `sourceRefs`）
配套图：[`neurova-c4.dsl`](neurova-c4.dsl) · [`neurova-flows.dot`](neurova-flows.dot) ·
[`neurova-dependencies.dot`](neurova-dependencies.dot) · [`neurova-deployment.dot`](neurova-deployment.dot) ·
[`neurova-risks.dot`](neurova-risks.dot)

---

## 0. 一句话结论

Neurova 是一个**真实运转、深度模块化的单体 Agent 平台**，其骨架（Agent → SubSystemContainer →
Pipeline → 深度模块 + `agent_ref`）成立且有 ADR 与守卫支撑；但它同时表现出一个大型演进单体在
缺乏**单一事实源纪律**时的全部症状：同域概念并生 129 个重名类、门面躲在包外、规范实现被同名目录遮蔽、
路由注册静默降级、预算只记账不拦截、前后端前缀契约断裂、以及一整个未纳入版本控制的新子系统层。

**最值得先修的不是最大文件，而是三处"静默失效"**：它们不崩溃、不报错，只是持续给出错误答案。

---

## 1. L0 业务能力 → 实现落点

`README.md` 以 18 个编号特性陈述能力主张。下表把它们锚回代码，并标注真实成熟度。
（`README.md:37` 之后缺失 `### 3.` 标题，编号断档 —— 文档本身的完整性问题。）

| 能力 | 实现落点 | 状态 |
|------|----------|------|
| 独特 Agent 人格 | `agent_core.py:1071` `_load_identity()` | 已实现 |
| NeRF 六通道记忆检索 | `cognitive_layers/memory_layer/moe_router` + 检索责任链 `chat_pipeline.py:201-229` | 已实现 |
| 情感中枢引擎 | `emotion_context_layer`（memory_layer 中唯一急切装配项 `manager.py:217`） | 已实现 |
| CogArch 认知架构 | `cognitive_layers/` 138 文件，其中 memory_layer 占 118（86%） | 已实现但重心失衡 |
| 持续进化 / RSI | `evolution/`（eval / rsi / skill_\*）；事件+启动触发，**无调度器** | 已实现 |
| **多 Agent 团队协作** | `turn_coordinator.py` 已写好 yield/outbox 规则，但 `get_turn_coordinator()` **零调用方**，未接入 `chat_pipeline` | **能力主张与运行时之间存在缺口** |
| ToolMemory 肌肉记忆 | `tool_layers/` + `chat_pipeline.py:671` Step0.5 工具记忆检查 | 已实现 |
| 工具系统 / Computer Use | `tool_executor.py`（5159 行）+ `computer_use/` + `skills/` | 已实现 |
| 贝叶斯 EKI 优化器 | `cognitive_layers/` 内 | 已实现 |
| 活水上下文池 | `context/` + ADR 0015 回收契约 | 已实现（契约已显式化） |
| NeurFlow 工作流引擎 | `collaboration/neurflow/`（48 文件） | 已实现 |
| 知识库隔离与 RAG | `knowledge/` | 已实现 |
| LLM 服务商管理 | `llm/provider_manager.py` + `llm_router` | 已实现 |
| MCP 治理 | `tool_layers/mcp_server.py` | 已实现 |
| **成本控制** | `models/cost_tracking.py` 记账 + `cost_budget.py:276,282` 判定 | **判定只进报表路径，主路径未闭环** |

> 结论：18 项能力中 15 项可锚到实现，2 项（多 Agent 协调、成本拦截）**代码已写但没接进运行时**，
> 这正是"实现新功能容易、闭合链路难"的典型形态。

---

## 2. L1 系统上下文

```
                  ┌──────────────┐        ┌──────────────────┐
   开发者/运维 ──▶ │              │  ────▶ │ LLM 服务商 ×8     │
                  │   Neurova    │        ├──────────────────┤
 渠道终端用户 ──▶ │  (单体内聚)  │  ────▶ │ 消息平台 ×18 对端 │
                  │              │        ├──────────────────┤
                  │              │  ────▶ │ MCP Servers       │
                  └──────────────┘        ├──────────────────┤
                                          │ 电商/社媒 ×11     │
                                          └──────────────────┘
```

系统边界内是一个**协同单体**：不存在服务拆分，所有"子系统"都是同一 Python 进程内的包。
唯一的跨进程边界是 前端 SPA ↔ 后端 HTTP/WS，以及 后端 ↔ 外部服务商。

`agent_ref` 需澄清一个常见误解：**它不是 API 层的依赖注入**。
`agent_ref` 是进程内深度模块持有的宿主 Agent 自引用（10 个文件、51 处，例
`chat_pipeline.py:181-182`、`tool_executor.py:321`）；HTTP 侧真正的 DI 入口是
`api/deps.py:108 get_agent_instance`，查 `_app_state["agents"]`（`api/app.py:533-549` 注入）。

---

## 3. L2 容器视图

| 容器 | 端口 | 证据 | 备注 |
|------|------|------|------|
| NeurUI (Vue3 SPA) | :8100 | `vite.config.ts:17-42` | strictPort，proxy `/api`→:9527 |
| FastAPI 后端 | :9527 | `api/app.py:1160`、`start_server.py:102-111` | 双检锁单例 app |
| SQLite 数据族 | — | 128 个 `.db`，`data/` 1.2GB | 路径常量三处各自为政 |
| 文件态存储 | — | sessions 2408 文件 / agent_workspaces 610 / trajectories 2780 | 非结构化落盘 |
| CI 守卫 | — | `ci.yml` 9 job | 见 §7 |

关键结构性事实：**容器维度上没有拆分**。57 个后端子包、17 万行代码全部部署为 1 个进程 +
1 个 SQLite。这不是缺陷（单体自洽），但它意味着任何"子系统"都**没有运行时隔离**，
一次 import 期副作用就会污染全进程 —— 这解释了 `tests/conftest.py` 为什么需要
**14 个 autouse 单例隔离 fixture**（`_isolate_session_manager_singletons:16`、
`_isolate_execution_engine_singleton:45`、`_isolate_skill_service_storage:69` …）。
测试需要隔离 14 类全局态，本身就是进程内共享总线过强的度量。

---

## 4. L3 Agent 核心组件

装配链（已证实）：

```
Agent.__init__ [agent_core.py:1061]
  └─ 仅两行：_load_identity() + SubSystemContainer(self).init_all() [:1071-1075]
       └─ SubSystemContainer [:452]
            ├─ 12 个 init_* 分组 [:483-496]
            ├─ _build_dependency_graph 声明拓扑序 [:503]
            └─ InitializationManager 循环检测 [core/initialization_manager.py:83,154,252]
                 └─ 约 40 个属性挂回 agent [:559-1012]  ← 隐式共享总线
```

这套设计是**真实的优点**，值得保留：`Agent.__init__` 从 427 行降到 14 行（ADR 记录），
装配顺序显式化且有循环检测。

但代价是：`agent` 上 40 个属性构成一条**没有类型的共享总线**。
深度模块之间不通过接口通信，而是通过 `agent_ref.某个属性` 互相可达。
后果有两个，都已在本仓库观察到：

1. **读写矩阵不可枚举**。谁写了哪个属性，静态分析不出来（登记为 `u3`）。
2. **反向回手成为惯用法**。`tool_layers/tool_router.py:643-645` 在被
   `agent_core.py:979-980` 注入 executor 之后，回手调用 executor 的**私有方法**
   `_execute_builtin_tool`；`tool_layers/mcp_server.py:205` 直接 import `tool_executor`。
   "无循环依赖"是靠约定与延迟导入维持的，不是靠结构维持的。

### ChatPipeline 的真实形状

`AGENTS.md:44` 与 `docs/CONTEXT.md:49-58` 均记为 **6 步**。实测为 **8 个编号步**
（`chat_pipeline.py:421-445`）：

| 步 | 方法 | 行号 |
|----|------|------|
| Step0 | `_step_activity_tracking` | `:584` |
| Step0.5 | `_step_pre_llm_checks` | `:671` |
| **Step0.7** | `_step_inject_attachments` | `:1165` |
| Step1 | `_step_retrieve_and_build_context` | `:1390` |
| **Step2** | `_step_evocate_injection` | `:1815` |
| Step3 | `_step_llm_call` | `:1869` |
| Step4 | `_step_post_processing` | `:2491` |
| **Step5** | `_sync_final_reply` | `:449` |

步骤间唯一载体是 `ChatContext` dataclass（`:126`）—— 这是一个**好的设计**：
显式、可测、无隐藏状态。

`PostChatPipeline`（3068 行）在 Step4 分叉为「响应路径 asyncio.gather 两波」+「后台旁路」
（`post_chat_pipeline.py:648-680`），含 Step 8.5 / 9 / 9.05 / 9.06 / 9.1 / 9.9 / 9.95 /
9.96 / 10 / 10.5 / 11 等 20+ 步。**编号已到小数点后两位**，说明主干步骤序号已耗尽，
扩展只能插缝 —— 这是管线需要重构为声明式阶段表的信号。

另：`Agent.chat_stream`（`agent_core.py:1855-1864`）是**伪流式**（全量生成后按句切块），
而 `_step_llm_call`（`chat_pipeline.py:2032`）是真流式。两条并存路径对外表现不一致。

---

## 5. 依赖方向与并行实现（本次最硬的量化发现）

### 5.1 同域概念并生定义

`grep -oP '^class \K\w+' neurova/**/*.py | uniq -c`：**129 个顶层类名被定义 2 次以上**，
且多数是核心域类型，不是巧合重名：

| 类名 | 次数 | 分布 |
|------|------|------|
| `SkillInfo` | 6 | `api/endpoints/{skill,skills_market,skill_pool_api}.py`、`skills/market_adapters.py:22`、`skill_system/__init__.py:267`、`skill_system.py:43` |
| `MemoryType` | 4 | `cognitive/orchestrator.py:35`、`cognitive_layers/memory_layer/models.py:15`、`cognitive_layers/.../cognitive_storage_engine.py:34`、`core/cognition_orchestrator.py:43` |
| `MemoryManager` | 3 | 同上三处**平行命名空间各一个**（`:112` / `:136` / `:193`） |
| `Message` | 3 | `context_compressor.py:50`、`llm/interfaces/provider_interface.py:40`、`router.py:67` |
| `WorkflowDefinition`/`NodeType` | 4 | — |
| `Message`、`MessageType`、`CognitiveState`、`AgentStatus`、`MemoryManager` | 各 3 | — |

注意 `MemoryType` 的四处分属**三个平行认知命名空间**：`neurova/cognitive/`、
`neurova/cognitive_layers/`、`neurova/core/cognition_orchestrator.py`。这是三次 fork 的残留。

### 5.2 这不是历史遗留，是持续生成的

`docs/01-architecture/adr/` 的 ADR 中，**6 份的决策主题完全同构**——"N 套收敛为 1 套"：

| ADR | 主题 | 收敛前套数 |
|-----|------|-----------|
| 0001 | 统一 Memory dataclass | 3+1 |
| 0008 | SessionRepository | 5 套会话存储 |
| 0009 | ExecutionStatus | 4 个不兼容枚举 |
| 0010 | ToolExecutionContext | 2 个不兼容 dataclass |
| 0011 | SkillRegistry | A 规范 / B re-export |
| 0013 | 技能市场端点 | 4 套→1 套 |

5 个月内同类决策出现 6 次 ⇒ **仓库缺少阻止并生定义的机制**（无域类型单一模块、
无 import 别名 lint、无契约快照守卫覆盖这些类型）。ADR 只处理了 129 中的 6 例。
根因不在"当初不该分叉"，而在"没有任何东西阻止下一次分叉"。

### 5.3 LLM 层：门面在包外

```
neurova/llm_client.py            ← 真正的门面（顶层，975 行）
neurova/llm/client.py            ← 8 行占位，docstring 自陈"实际代码在 neurova.llm_client" [:2-5]
neurova/llm/multi_model_client.py:38  ← 包内反向 import 顶层模块
neurova/llm/{adapters,registry,interfaces,sandbox}  ← 自引闭环孤岛，外部消费 1–4 处
neurova/llm/cost_tracking_middleware.py  ← 362 行，全仓零消费者
```

`AGENTS.md` 声称后端架构含 `neurova/llm/ — Multi-model LLM client, router, provider manager`，
暗示 `llm/` 是家。实际上包名是空的壳，门面在顶层，且包反向依赖顶层。
`llm/{adapters,registry,interfaces,sandbox}` 是"多提供商适配器架构"的**未完成迁移**还是
**废弃残留**，无 ADR 指明终态（登记为 `u2`）。

---

## 6. 三处静默失效（优先级最高的修复目标）

判据（依 `AGENTS.md` 修复教义第 1 条）：把报错恢复原状后，根因处不修则故障必然复现。

### 6.1 路由注册静默降级

```python
# neurova/api/endpoints/__init__.py:182-301  字符串白名单 + importlib 动态导入
#                                        :296-297  except ImportError: logger.debug(...)
```

88 项 endpoint 白名单靠**运行时字符串**导入，失败只 `logger.debug`。后果：

- 漏注册 / 导入炸了在启动期**完全不可见**；
- 实测 4 个端点模块（`cost_api.py` / `computer_api.py` / `phase3_api.py` / `migration_api.py`）
  **零注册、零引用**；
- `budget_api` / `cost_rollup_api` 走 `app.py` **旁路**注册，
  与白名单机制并存 = 两套注册事实源；
- `neuron` 既在白名单（prefix `""`）又在 `app.py` **重复挂载**；
- `coordination_api` 自带 `prefix="/coordination"` 又被挂到 `/api/coordination`
  → 实际路径 `/api/coordination/coordination/*`，前端零引用；
- 动态字符串注册**不可静态分析**：IDE、类型检查、依赖图、以及本目录所有架构图，
  都看不到这张表。这是自动化治理的结构性障碍。

**2026-09-22 收口状态**：旁路注册组与三个模块级空 `APIRouter`
（`router` / `evolution_router` / `rag_router`）已删除，挂载事实收口到
`endpoint_modules` 注册表一处；`neuron` / `coordination_api` 的重复前缀段消失。
常驻守卫 `tests/unit/api/test_route_mount_contract_guard.py` 钉住
「零路由挂载 / 前缀重复 / 挂载层错位」三类形态，并保留
`unmountedEndpointModules()` 名单（`cost_api` / `computer_api` / `phase3_api` /
`migration_api` / `skill_market` / `skills_market` 仍定义了路由但未挂载，
名单进 `docs/09-dev-progress/api_inventory.md` 供人排期）。
「导入失败只 `logger.debug`」这条仍成立，属同域的下一个缺口，未在本轮处置。

### 6.2 成本链路：是只读报表，不是拦截器

```
LLM 调用 (12 处 chat.completions.create)
   ├─ 仅 2 处有 @track_llm_call  [llm_client.py:315,671]
   ├─ 装饰器 ImportError 时降级为 no-op  [llm_client.py:22-30]   ← 静默失效点 1
   └─ 10 处完全不经装饰器  [llm_client.py:354,445,576,695 + llm/providers/capability_detector.py ×8]

_record_budget_and_check_alerts  [cost_tracking.py:510]
   └─ 只 record_llm_call_cost，无抛错、无拦截

预算判定函数的真实调用面（实测 grep 逐条核对）：
   is_over_budget      [cost_budget.py:276]
     ← budget_api.py:171        把该布尔值作为「响应字段」返回前端
     ← cost_budget.py:362,380   get_budget_status 报表
     ← tests/unit/models/test_cost_budget.py ×5
     ⇒ 只在「读报表」路径上被调用；LLM 调用主路径上零调用
   throttle_if_needed  [cost_budget.py:282]
     ← 仅 tests/unit/models/test_cost_budget.py:132,136
     ⇒ 生产代码零调用方
   grep 'check_budget|budget_exceeded' 在 neurova/ 下 = 0 命中

CI: package.json:9-11 + cost-guards.yml
   └─ guard:llm-tracked 标 continue-on-error: true  → 名义守卫，不阻断
      且 workflow 与 package.json / scripts/guard-*.cjs 均未跟踪 → 当前 CI 是纸面存在
```

准确结论不是"预算函数没人调用"，而是：**这套预算系统在架构上是只读报表，不是拦截器。**
它能告诉前端"已超支"，但超支之后没有任何一处代码据此放慢或拒绝下一次 LLM 调用。
`throttle_if_needed` 已实现限流逻辑却只被测试调用，是最直接的证据。

三套并行装饰器（`models/cost_tracking.py:445` 真身 / `llm/cost_tracking_middleware.py:279` 零消费
/ `collaboration/cost_ledger_integration.py:29` 仅孤岛引用）进一步说明
这条链路是**分头写了三遍，一次都没接通**。

### 6.3 前后端前缀契约断裂

```
前端 baseURL = /api/v1                    [NeurUI/src/api/index.ts ← config/index.ts]
后端 budget/cost_rollup 挂在 /api/...      [app.py 旁路注册]  ← 缺 /v1
   ⇒ CostDashboard 全部请求 404
   ⇒ 被 .catch(() => null) 静默吞掉        [CostDashboardPage.vue]

api/computer.ts 更用裸 axios 绕开唯一实例  [api/computer.ts]
   ⇒ 无 token、无信封解包，且指向未注册路由 → 必 404
```

**2026-09-22 收口状态**：`budget_api` / `cost_rollup_api` 已并入注册表挂 `/v1`，
`/api/v1/budgets/*`、`/api/v1/cost-rollup/*` 实测可达（真应用探活）。`api/computer.ts`
仍用裸 axios 且指向未挂载的 `/api/computers`——它属 `unmountedEndpointModules()`
名单里的 `computer_api`，是同一张清单的下一层，未在本轮处置（清单里逐条在册）。

这一条把 §6.1（未注册）与 §6.3（前缀不一致）耦合成同一个可观测故障：
**前端界面会正常渲染，只是所有数据都是空的**。这是最难从外部发现的一类 bug。

---

## 7. 一处正确性缺陷（根因级，已实测复现）

### `neurova/skill_system.py` 被同名目录永久遮蔽

Python 的包优先于同名模块。本次实测（`python -c "import neurova.skill_system as m; print(m.__file__)"`）
确认解析到 `neurova/skill_system/__init__.py`，**32KB 的 `neurova/skill_system.py` 经正常 import
路径不可达**。而该文件是 git 跟踪的规范实现，最后一次提交是
`2026-09-18 01:03:50 fix(evolution): P1/P2 收口…`（即两天前还在改）。

为了用那个不可达文件里的规范类，`skill_system/__init__.py` 叠了四层兜底：

1. `__getattr__` 分支（`:190-223`，为 6 个名字各写一遍）用
   `importlib.util.spec_from_file_location` **按文件路径**载入 `../skill_system.py`；
2. 载入时以假名 `neurova.skill_system_module_standalone` 注入 `sys.modules`
   （`:194-196`、`:215-217`）—— 该模块名**在磁盘上不存在**（`find` 已确证）；
3. `:245` 备一个只有 `name`/`description` 两个属性的**占位 `Skill` 类**，
   供 `:242` 的 `except ImportError` 降级；
4. `:264` 模块顶层直接 `from neurova.skill_system_module_standalone import Skill`。

第 4 步之所以目前不炸，**仅仅因为**同一文件 `:239` 的
`from neurova.skill_system import Skill` 先触发了 `__getattr__`，把别名塞进了 `sys.modules`。
这是一条**加载顺序耦合**：任何一次 import 重排、或删掉 `:238-241` 那个 try 块，
`:264` 立刻在导入期抛 ImportError。

代码注释自陈了此前症状（`:204-207`）：缺 `"Skill"` 分支时占位类导致
`SkillRegistry.register()` 抛 `AttributeError`。**修法是往 `__getattr__` 再加一个分支**，
而不是消除同名遮蔽 —— 这正是 `AGENTS.md` 修复教义第 1 条禁止的 consumer-only guard。

> 判据自检：恢复"报错信息不消失"的原状 —— 若把 `skill_system.py` 改名或把规范实现上提到包内，
> 这四层兜底全部可删；反之只要包与模块同名，就必须永远维持这条顺序耦合。故根因在**命名冲突**，不在 `__getattr__`。

### 同型地雷：大小写

`api/endpoints/migration_api.py:11` 导入小写 `neurova.storage.*`，
git 记录为 `neurova/Storage/`（大写）。Windows 文件系统大小写不敏感所以本地可跑，
**Linux / Docker 镜像内必然 ImportError**。本机无法复现（已在 `u` 项登记）。

---

## 8. 部署拓扑

| 形态 | 真实进程/服务数 | 证据 | 说明 |
|------|----------------|------|------|
| 本机开发 | 2（后端 :9527 + Vite :8100） | `start.py:7-8`、`scripts/config.py:23-24` | `--prod` 退化为 1（前端产物拷进 `neurova/static`，`start.py:281-291`） |
| docker-compose | **默认 1** | `docker-compose.yml:67-85` frontend 挂 `profiles: development` | 无 redis / worker / db service |
| Helm | 2 + hpa + ingress + pvc | `helm/neurova/templates`（12 模板） | 唯一真实多服务拓扑，但 `replicaCount` 均为 1（`values.yaml:31,112`）；副本 >1 且缺 jwtSecret 会渲染期失败（`:150`） |
| 桌面 | Tauri | `NeurUI/src-tauri` | `desktop/` 仅剩一张 pfx |
| 旁支 | — | `NeurovaHarmony/`(ArkTS)、`web/`+`deploy/`(PHP+nginx+xray) | **不应计入架构基线** |

结论：**不要按微服务理解 Neurova**。它是一进程单体，Docker 默认单容器，
Helm 有两个 Deployment 但零副本冗余。任何"某子系统独立伸缩"的假设都不成立。

另外两个入口层面的问题：
- `check_and_start.py` 是**第二套同端口启动器**（`:23-24,137,193`），未接入 `start.py`；
- `bootstrap_evolution_persistence` 在 `start_server.py:67` 与 `api/app.py:774` **各调一次**，
  启动装配存在双事实源；
- `.cnb.yml`（19KB）镜像 `ci.yml` 同一管线 → CI 也是双事实源。

### 零停机迁移：文档描述的机制在代码里是 `pass`

`neurova/Storage/zero_downtime_migration.py`（未跟踪）有完整的 7 阶段状态机
（`:22-31`）、四阶段执行（`:163-182`）、batch=1000/延迟 0.1s（`:89-91`）、
短事务 `timeout=1.0` + `LIMIT/OFFSET` + sleep 避锁 —— 这部分是真的。

但表切换的实质步骤全为空：

| 方法 | 行号 | 实现 |
|------|------|------|
| `_enable_dual_write` | `:195-199` | `pass` |
| `_insert_into_new_schema` | `:292-301` | `pass` |
| `_switch_readers` | `:303-307` | `pass` |
| `_schedule_cleanup` | `:309-313` | `pass` |
| `_should_stop_migration` | `:326-329` | `pass` |
| `rollback` | `:367-375` | 恒 `False` |
| `verify` | `:377-382` | 恒 `True` |

`verify` 恒 True + `rollback` 恒 False 的组合最危险：**任何迁移都会被报告为验证通过且不可回滚**。
`MIGRATION_SYSTEM_GUIDE.md` 描述的表切换策略与代码不符（登记 `u`，需问作者是否有仓外实现）。

---

## 9. 测试与版本控制面

| 事实 | 数值 | 证据 |
|------|------|------|
| git 跟踪 `.py` | **2573**（文档称 550+） | `git ls-files "*.py"` |
| `tests/` 下 `test_*.py` | **1535**（README 称 846） | 实测 |
| `pytest --collect-only` | 17194 tests / 61.6s / **1 收集错误** | 该错误在 `tests/benchmarks/test_multi_agent_coordination.py`（未跟踪） |
| autouse 隔离 fixture | 14 个 | `tests/conftest.py:16-493` |
| 前端 `*.test.ts` | 210 | `NeurUI/src/**/__tests__/` |
| 仓库根游离 `test_*.py` | 5，均未跟踪 | 与 `AGENTS.md` 声称 2026-09-16 已归位矛盾 |

**未纳入版本控制的核心代码**（这是当前最大的可复现性风险）：
`neurova/db/`、`neurova/models/`（成本账本领域层）、`neurova/crdt/`、
`neurova/llm/{adapters,registry,sandbox,interfaces}/`、`neurova/experiments/`、
`neurova/collaboration/` 7 个新文件、`neurova/api/endpoints/` 7 个新端点、
`neurova/Storage/zero_downtime_migration.py`、`.github/CODEOWNERS`、
`.github/workflows/cost-guards.yml`、根 `package.json`、`scripts/guard-*.cjs`。

即：**主线架构有一大块既不在 HEAD 里，也不在 CI 覆盖里**。
`CODEOWNERS` 未跟踪 ⇒ 七团队模块路由从未生效。

反向问题：711 个 `.md` 被跟踪，其中 40+ 份是 `PINIA_*` / `IMPLEMENTATION_SUMMARY_PHASE*` /
`COST_CONTROL_*` 一次性报告，提交于 `.gitignore:218` 的 `/*.md` 规则之前（ignore 对已跟踪无效）；
`audit-reports/` 完全未被覆盖；`data/backups/`(>1GB) 与 `uploads/`(1.5GB) 在盘上。

---

## 10. 关于"可视化"本身的结论

`find . -name "*.dot" -o -name "*.dsl" -o -name "*.puml" -o -name "*.mmd"` → **零命中**。
而 `docs/` 下有 **25 张手写 HTML 图**，同一张依赖图存在 `-v2 / -v3 / -v4 / -v5` 四个文件名副本
（`docs/neurova-dependency-diagram*.html`）。

这意味着此前每一次"做架构图"都产出了**不可重生成、不可 diff、无法验证是否过期**的产物，
只能靠再画一张新版本来更新，于是累积成 5 份并存。本目录采用
**文本源（Structurizr DSL + Graphviz DOT）为唯一权威**，
导出图只是衍生物，正是为了终结这个循环。

---

## 11. 建议修复次序

按**依赖**排序，不按严重度排序（F1 不做，F2/F3 的验证手段就没有）：

| # | 动作 | 消除 | 净 LOC 预估 |
|---|------|------|------------|
| F1 | 路由注册 `ImportError` 改为启动期 fail-fast（或显式降级清单），并把 `test_route_registration.py` 纳入 `protected_tests.txt` 路由快照断言 | R2 | ≤0（换掉 debug 分支 + 加一条快照测试） |
| F2 | 消除 `skill_system` 同名遮蔽：`skill_system.py` 改名上提为包内规范模块，删 `__getattr__` 六分支 + 幽灵模块别名 + 占位 `Skill` 类 | R1, R1b | **显著为负**（删 ~120 行兜底） |
| F3 | 让预算成为拦截器而非报表：在 `cost_tracking.py:510` 记账后调用 `throttle_if_needed`（`cost_budget.py:282`）并据结果拦停；装饰器 `ImportError` 改快速失败；补齐 10 处未覆盖调用点 | R3, R3b | +少量（含防回归用例） |
| F4 | 前后端前缀统一到 `/api/v1`，去掉 `.catch(()=>null)`，`api/computer.ts` 回归唯一 axios 实例 | R7 | ≈0 |
| F5 | 把 §9 列出的未跟踪核心纳入版本控制，`CODEOWNERS` 与 `cost-guards.yml` 一并入库 | R11, R11b, R8 可验证性 | 0（仅 `git add`） |
| F6 | 行数棘轮从 `agent_core.py` 1 个文件扩到 top-10；为 129 个重名类建收敛台账，每收一个开 ADR | R5, R4 | 守卫为配置，台账为文档 |
| F7 | `migration_api.py:11` 大小写对齐；零停机迁移要么实现 `_switch_readers`，要么把 `verify` 改为 `NotImplementedError` 并同步 `MIGRATION_SYSTEM_GUIDE.md` | R10, R12 | ≤0 |
| F8 | 文档单一入口：合并 `docs/architecture/` 与 `docs/01-architecture/`（已 md5 分叉），修正 `CONTEXT.md`/`AGENTS.md`/`README.md` 的 6 项实测数字，本目录取代 25 张 HTML | R6, R9, R9b | 文档 |

F7 的后半句是本仓库最需要的纪律：**未实现的机制必须显式抛错，不能让 `verify()` 恒真**。

---

## 12. 未确认事项（勿当作已知）

| id | 内容 | 为何重要 |
|----|------|----------|
| u1 | ~~「17 维记忆分类」代码中无该常量；实测为 `auto_classifier.py:27-56` 三枚举并集 7+6+4~~ **已裁决（Issue #68 / ADR 0018）**：「17 维」不存在于代码，已废止；分类值域唯一事实源 = `models.py` 的 MemoryCategory(7)/MemoryType(7)/MemoryPerspective(4)，三份私有枚举已删除，`remember(auto_classify=True)` 真落分类 | 文档口径已按 ADR 0018 逐个修正 |
| u2 | `llm/{adapters,registry,interfaces,sandbox}` 是未完成的对齐目标态还是废弃残留 | 决定 F3 该往哪套实现收口 |
| u3 | `agent` 上约 40 个属性的实际读写矩阵 | 精确耦合图与 F6 的拆分边界都依赖它 |
| u4 | 无运行时遥测；进程与网络关系全部静态推导 | 部署图不能声称"观测所得" |
| u5 | `NeurUI/src/views/*.tsx` 是待迁移 React 原型还是误提交外部代码（`package.json` 无 react 依赖） | 决定是否可直接删 |
| u6 | 零停机迁移是否有仓外调用方使 `pass` 步骤被替代 | 决定 F7 是"实现"还是"删除" |
| u7 | `cumora/`、`flow-kb-sdk/`、`.zcode*/`、`other/` 等归属 | 影响"哪些算交付架构" |

---

## 13. 验证状态声明（勿过度解读）

- ✅ 四个图源 + JSON 证据模型通过**词法/结构自检**（`python lint-architecture-sources.py` → 全 OK）
- ✅ 关键断言均带 `文件:行号`，可逐条 grep 复核
- ✅ §7 遮蔽结论经**实际执行 Python import 验证**（非阅读推断）
- ❌ **未渲染 SVG/PNG**：本机 `dot -V`、`java -version`、`mmdc` 均 command not found（已实测）
- ❌ **未启动服务验证 404**：§6.3 的前缀断裂来自静态前缀推导，未查 `openapi.json` 实际路由表
- ❌ **未跑全量测试套件**：仅 `pytest --collect-only`（17194 tests，1 收集错误）
- ⚠️ 工作树含 60 项未提交变更，图区分了 committed 基线与 working-tree 在途，但 F5 完成前
  任何重新 checkout 都会改变现状
