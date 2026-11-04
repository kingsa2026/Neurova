# Agent 自主节点编排与工作流修改能力设计

- **状态**：设计已拍板（2026-11-04 六项裁定）+ 交互门要求；**N0/N1/N2/N3/N4/N5 已实施（2026-11-04）**
- **基线日期**：2026-11-04（`main` 工作树，含未提交的广告自动调优批）
- **裁定摘要**：custom 节点默认 `draft`；已发布工作流可直接改但必须先有安全版本可回滚；
  环境需求随 `NodeDefinition`；修复由 Agent 轮次编排；审批按任务批次一次；
  复用 RSI 提案/回滚/评测基础设施与 EKB（详见 §9）。**新增产品要求**：
  一句话需求先过 BuildSession 就绪门，不明确/缺凭据走面板，满足条件才动手；
  构建中的疑问/选择同样走面板（§5.0、N0）
- **输入依据**：
  - `neurova/collaboration/canvas_ops.py`、`canvas_store.py`、`canvas_bridge.py`
  - `neurova/collaboration/neurflow/{node_registry,custom_nodes,adapters,execution_engine}.py`
  - `neurova/builtin_tools.py`、`neurova/tool_executor.py`
  - `neurova/api/endpoints/{collaboration_api,neurflow_api}.py`
  - `NeurUI/src/modules/collaboration/CanvasDesignerPage.vue`、`NeurUI/src/api/modules/collaboration.ts`
  - 2026-11-04 关于「Agent 能否按需求与运行参数自主增减/修改节点」的只读复盘结论

> 本文严格区分三件事：**现在已具备**、**现在不具备**、**拟新增**。
> 拟新增的接口均标注「拟」，不把设计意图写成现状。

---

## 0. 一句话结论

**能改「节点实例」，不能造「节点类型」；能改「画布」，不能直接改「已发布工作流定义」；能看运行报错再改参数，但没有自动发现/配置环境与凭据。**

如果目标是「用户说一句需求，Agent 自己补节点、补参数、补环境并持续收敛」，
当前还差五段接线：**交互就绪门**（先问清再动手，§5.0/N0）、节点参数自描述、
节点类型 CRUD 工具、注册表同步入口、以及带闸门的自愈闭环。

---

## 1. 术语与边界

| 概念 | 代码落点 | 写入面 | Agent 现状 |
|---|---|---|---|
| 节点类型（NodeDefinition） | `neurflow/models.py:105` | 节点注册表 + `custom_nodes` 表 | 只能查，不能增/改/删 |
| 节点实例（画布节点） | 画布快照 `nodes[]` | `CanvasStore`（JSON 文件） | 能增/删/连/改配置/移动 |
| 画布（Canvas） | `canvas_store.py` | `data/canvases/*.json` | 能创建、读取、运行 |
| 工作流定义（WorkflowDefinition） | `neurflow/storage.py` | SQLite 工作流库 | 只能执行，不能改/发布 |
| 节点注册表（NodeRegistry） | `neurflow/node_registry.py` | 进程内单例 | 无同步工具 |
| 自定义节点（custom:*） | `neurflow/custom_nodes.py` | SQLite + 注册表双写 | 仅 HTTP API，无 Agent 工具 |

**关键区分**：

- 「画布」与「工作流定义」是两套持久化面。Agent 的 `canvas_*` 工具写画布库；
  前端编辑器保存「来自定义的快照」时走
  `PUT /neurflow/workflows/{id}/definition`（`NeurUI/src/api/modules/collaboration.ts:415`）。
- `canvas_run` 把**当前画布快照**编译成工作流再执行
  （`canvas_bridge.py:71`、`tool_executor.py:2746`），不会回写工作流定义。

---

## 2. 现状锚点（只读证据）

### 2.1 Agent 已有的画布工具面

`_BUILTIN_SCHEMAS` 当前 74 个工具，画布相关 10 个：

| 工具 | 作用 | 行号 |
|---|---|---|
| `canvas_create` | 新建空白画布 | `builtin_tools.py:1137` |
| `canvas_read` | 读快照（含 version、节点 config、端口） | `builtin_tools.py:1150` |
| `canvas_list_nodes` | 查节点库（仅摘要） | `builtin_tools.py:1267` |
| `canvas_add_node` | 加已注册类型的节点 | `builtin_tools.py:1162` |
| `canvas_connect` | 连边（port 校验、重复边拒绝） | `builtin_tools.py:1179` |
| `canvas_set_config` | 浅合并节点配置 | `builtin_tools.py:1196` |
| `canvas_move_node` | 移动节点 | `builtin_tools.py:1211` |
| `canvas_remove_node` | 删节点及其边 | `builtin_tools.py:1227` |
| `canvas_layout` | 自动布局 | `builtin_tools.py:1241` |
| `canvas_run` | 编译快照并执行，返回节点级结果 | `builtin_tools.py:1254` |

写操作带 `base_version` 乐观锁；冲突返回 `version_conflict`，重读可重试
（`canvas_ops.py:154` 及后续 mutate 路径）。

### 2.2 节点库查询只给摘要，不给参数契约

`CanvasOpService.list_nodes` 只返回：

```text
type / label / icon / category / description / source
```

（`canvas_ops.py:219-252`）

**不返回** `sub_blocks`、`inputs`、`outputs`、默认值、必填项、所需环境变量。
后果：

- Agent 只知道「有这个节点」，不知道「要填哪些参数、哪些必填」；
- 只能先 `canvas_add_node`（默认配置会被合并进来），再 `canvas_read`
  看 `config`/`inputs`/`outputs`，属于「先试后看」；
- 参数名写错时 `canvas_set_config` 不校验，会静默留在 config 里
  （`canvas_set_config` 描述是浅合并）。

### 2.3 注册表可见性依赖一次 `sync_all`

`CanvasOpService._registry()` 只做 `ensure_builtin()`：

```python
# canvas_ops.py:147-153
registry = get_node_registry()
registry.ensure_builtin()
return registry
```

启动时预注册的是内置 + ComfyUI + 电商 + 短剧：

```python
# api/app.py:1323-1325
register_comfyui_nodes(_reg)
register_commerce_nodes(_reg)
register_drama_nodes(_reg)
```

`tool:*` / `skill:*` / `mcp:*` / `custom:*` 依赖
`adapters.sync_all(registry)`（`adapters.py:364`），而它只在：

- `GET /neurflow/nodes`（`neurflow_api.py:686`）
- `POST /neurflow/nodes/sync`（`neurflow_api.py:859`）
- 画布编译/执行 `canvas_to_workflow` 的 `_known_node_types()`（`canvas_bridge.py:51`）

被触发。Agent 的 `canvas_list_nodes` / `canvas_add_node` 不会触发它。

**实际后果**：Agent 刚 `create_skill` 或用户刚通过 API 建了自定义节点，
`canvas_add_node("skill:xxx")` / `canvas_add_node("custom:xxx")`
可能直接报「未注册的节点类型」，直到 UI 拉过一次节点库或执行过一次画布。
这不是节点不存在，是注册表进程内快照没刷新。

### 2.4 自定义节点：服务已存在，工具面未接

`CustomNodeService`（`custom_nodes.py`）支持：

- **L1 declarative**：表单 `sub_blocks` + prompt 模板，`{{key}}` 占位符；
- **L2 composite**：顺序执行已有节点/工具，前一步输出经 `{{prev}}` 注入后一步配置；
- **L3 code**：明确不在本阶段范围（需要审批门 + 沙箱）。

服务含：

- SQLite + 内存注册表双写；
- 更新前旧版本快照 `custom_node_versions`；
- `create_node` / `update_node` / `delete_node` / `build_executor`。

**但它只有 HTTP 面**：

```text
POST   /neurflow/nodes/custom
PUT    /neurflow/nodes/custom/{node_type}
DELETE /neurflow/nodes/custom/{node_type}
```

（`neurflow_api.py:781-826`）

当前落库即 `status="active"`（`custom_nodes.py:135`），没有 draft/审批态；
`delete_node` 只删库与注册表，不检查工作流/画布引用（`custom_nodes.py:203-209`）。
这两点都是本文 5.3 建议补的闸门。

Agent 的 74 个内置工具里没有任何 `custom_node_*` / `node_*` 工具。
`canvas_list_nodes` 的描述本身写着「搜索无果说明节点库缺少该能力，可考虑建议用户创建自定义节点」
（`builtin_tools.py:1270`）——这句话是当前边界的直接证据。

`custom_nodes.py` 顶部注释说「让用户（经节点工坊 UI）与 agent（经工具）按需创建新节点类型」，
其中「agent（经工具）」是**未接线的设计意图**，不是现状。

### 2.5 工作流定义：Agent 只能执行，不能改/发布

- 工作流定义存储与版本：`neurflow/storage.py`；
- 发布后可作为工具 `workflow:<id>` 执行（`tool_executor.py` 的 workflow 工具族）；
- 前端编辑器回写定义：`PUT /neurflow/workflows/{id}/definition`
  （`collaboration.ts:415` 的 `writebackDefinition`）；
- Agent 无 `workflow_definition_get/update/publish` 工具；
- `canvas_*` 写的是 CanvasStore，不是工作流库。

因此：

- Agent 可以「建一张画布 → 运行 → 定时跑这张画布」（上一批已加
  `schedule_task(canvas_id=...)`，`scheduler.py:450` 的 `run_canvas`）；
- Agent 不能「把一张已发布工作流的节点改掉再发布」。

### 2.6 运行与自愈：没有热改，也没有失败回灌

`canvas_run` 流程：

1. `canvas_read` 当前快照；
2. `canvas_to_workflow` 编译；
3. `WorkflowExecutor.execute`；
4. 返回 `node_results`（status/output/error）。

（`tool_executor.py:2746`、`canvas_bridge.py:71`）

约束：

- **快照在运行前编译**：运行中改画布不影响本轮；
- `canvas_run` 在 `TOOL_TIMEOUTS_S` 里没有专属条目，走默认 60s
  （`agent/tool_coordinator.py:62`），长画布可能被转后台；
- 工具面没有 `canvas_run_status` 查询工具（REST 有
  `GET /canvas/runs/{run_id}` 类端点，但 Agent 工具面没有接）；
- 定时画布失败只把任务标 failed，不会自动生成「检查错误 → 改节点 → 重跑」的
  Agent 轮次。

### 2.7 环境与凭据：没有声明，也没有代配

- `NodeDefinition` 有 `sub_blocks`/`inputs`/`outputs`/`idempotent`/`tier`，
  **没有**「所需环境变量 / 凭据槽位」字段（`neurflow/models.py:105-128`）；
- `canvas_list_nodes` 不暴露环境需求；
- Agent 没有 SecretStore 写工具（电商节点只读 `NEUROVA_AMAZON_ADS_*` 等环境变量/
  StoreConnection；MCP 凭据走 UI/API）；
- `canvas_set_config` 不校验字段类型/必填；
- 因此 Agent 能「知道某节点要 `profile_id`」通常来自描述文字或报错，而不是契约。

---

## 3. 能力矩阵

| 用户需求 | 现在 | 结论 | 阻塞点 |
|---|---|---|---|
| 在画布上加/删/连节点 | ✅ | 可以 | 无 |
| 改节点配置参数 | ✅ | 可以（浅合并） | 无 schema 校验 |
| 先查节点需要哪些参数 | 🟡 | 只能看摘要；需先加节点再读 config | `list_nodes` 缺 sub_blocks/ports/defaults |
| 按运行报错改参数再跑 | ✅ | Agent 在环时可做 | 无自动回灌；长跑需状态查询 |
| 新建节点类型（L1/L2） | ⬜ | 不可以（仅 HTTP API） | 无 Agent 工具 |
| 新建 L3 代码节点 | ⬜ | 不可以（能力本身未实现） | 审批门 + 沙箱 |
| 让新技能/自定义节点立即可用 | 🟡 | 需先 `sync_all` | 无 `sync_nodes` 工具 |
| 改已发布工作流定义并发布 | ⬜ | 不可以（仅 REST/UI） | 无 workflow 定义工具 |
| 自动发现并配置环境/凭据 | ⬜ | 不可以 | 无环境元数据/凭据工具 |
| 定时持续执行画布 | ✅ | 可以（上一批） | 失败不自愈 |
| 运行中热改当前执行 | ⬜ | 不可以 | 快照先编译 |

状态：✅ 已具备；🟡 部分/有条件；⬜ 不具备。

---

## 4. 差距分级

### P0（不补则「自主」名不副实）

1. **参数契约不可见**：`list_nodes` 缺 `sub_blocks`/`inputs`/`outputs`/默认值/必填。
2. **注册表不刷新**：没有 Agent 可调的 `sync_nodes`，技能/工具/MCP/自定义节点
   时有时无。
3. **自定义节点 CRUD 无 Agent 工具**：服务已具备 L1/L2，只差暴露面。

### P1（决定「改完能不能持续收敛」）

4. **工作流定义修改/发布无 Agent 工具**：只能改画布，不能改已发布定义。
5. **运行结果无回灌**：`canvas_run` 失败后没有工具面状态查询/重试编排。
6. **环境/凭据无声明**：节点不知道自己需要什么，Agent 无法预检。

### P2（安全与规模化）

7. **`set_config` 无 schema 校验**：错键静默留存。
8. **自定义节点写共享注册表缺审批/归属/引用检查**：现在只有 HTTP 层的最小校验。
9. **L3 代码节点**：需要沙箱 + 审批门 + 资源上限，明确不在本批。

---

## 5. 目标设计

> 以下均为**拟新增**；接口名、字段名是建议稿，落地前按 `AGENTS.md` 先红后绿。

### 5.0 交互面板与构建就绪门（P0，N0）

**产品要求（2026-11-04）**：用户说一句需求后，Agent **不得直接动手**。
先检查是否具备构建完整工作流的条件；遇到不明确、不理解、缺少补充说明或凭据，
先通过**交互面板**问清楚，直到满足条件才允许创建/修改节点。搭建过程中出现疑问、
需要用户选择时，同样弹面板。

#### 5.0.1 复用现有交互基础设施，不新造第二套

| 现有能力 | 落点 | 复用方式 |
|---|---|---|
| 多轮问答状态机 | `plan_mode/plan_session.py`（`asking → awaiting_approval`，`MAX_QUESTION_ROUNDS=12`，`submit_answers` :177，`_ask_questions` :215） | 抽出通用「问答轮」引擎；BuildSession 复用同一问题结构（id/question/options/multi/allow_custom） |
| 问答面板渲染 | `NeurUI/src/components/chat/PlanPanel.vue`（选项/多选/自由补充/预览/审批） | 抽 `QuestionRoundView` 通用组件；BuildPanel 复用，PlanPanel 保留计划模式入口 |
| 审批弹窗 | `GovernanceApprovalModal.vue` + `useGovernanceApproval`，SSE `approval_required`（`ChatPage.vue:1745`） | 批次审批、发布审批、draft 激活审批共用 |
| 渠道审批节点 | `builtin:approval`（`builtin.py:2277`） | 仅用于无人值守渠道/跨渠道场景；不是画布内的主面板 |

**不直接复用 `PlanSession` 对象本身**：它产出计划文档与 `execute_prompt`，
BuildSession 产出「构建就绪清单 + 构建计划 + 批次审批」。复用的是问答轮协议、
面板渲染和审批状态机，不是把计划模式硬改成构建模式。

#### 5.0.2 BuildSession 状态机

```text
received
  → clarifying（面板问答中）
  → ready（就绪清单全绿）
  → awaiting_approval（构建计划 + 批次审批）
  → approved / building
  → blocked(question)（构建中提问，暂停）
  → building（回答后恢复）
  → verifying（运行/检查）
  → converged | failed
```

- `build_session_id` 绑定当前任务/Agent 轮次；服务端保存状态，可跨断线恢复；
- `ready` 是**服务端判据**，不是模型自述；
- `blocked` 是暂停，不是失败；超时保留会话，等用户回答后继续；
- 每次状态迁移写审计（谁、何时、缺什么、答了什么，敏感值除外）。

#### 5.0.3 就绪清单（缺一项就出问题面板）

| # | 条件 | 检查方式 | 缺失时的面板 |
|---|---|---|---|
| 1 | 目标、范围、验收标准明确 | 意图解析 + 模型自检；歧义则提问 | 单选/多选/自由补充 |
| 2 | 目标是新建还是修改既有画布/工作流 | 明确目标 id 与归属 | 单选 |
| 3 | 所需节点类型存在 | `canvas_list_nodes` + 注册表 | 选替代节点 / 建 draft 自定义节点（批次审批） |
| 4 | 必填参数齐全 | 节点 `sub_blocks.required` + 端口 | 逐个字段提问；未知值不猜 |
| 5 | 环境/凭据可用 | `env_requirements` + StoreConnection/MCP 配置 | **secret 输入面板**；只写 SecretStore |
| 6 | 权限/归属合法 | 用户、Agent、画布/工作流属主 | 说明并请用户选择授权对象 |
| 7 | 预算/轮次/时间可接受 | 用户确认或默认上限 | 确认单 |
| 8 | 已发布修改有安全版本 | §5.4 `safe_version` 检查 | 先建基线；修复走工作流定义草稿版本 |

> 条件 1–4 依赖 N1（参数自描述）；条件 5 依赖 N1 的 `env_requirements`。
> N0 可以先落「面板 + 状态机 + 服务端拒绝未就绪写入」，清单随 N1 逐步补齐。

#### 5.0.4 面板请求/应答契约（拟）

```json
{
  "interaction_id": "int_...",
  "build_session_id": "build_...",
  "kind": "choice | multi | text | secret | confirm | approval",
  "title": "这条广告链用哪个亚马逊店铺？",
  "why": "节点需要 profileId 才能拉取真实报表",
  "impact": "选择后只影响本次构建；可随时更换",
  "options": [
    {"label": "店铺 A", "description": "US 站", "recommended": true},
    {"label": "店铺 B", "description": "JP 站"}
  ],
  "multi": false,
  "allow_custom": true,
  "required": true,
  "secret_key": "NEUROVA_AMAZON_ADS_CLIENT_SECRET",
  "timeout_seconds": 600
}
```

规则：

- 每轮最多 3 个问题；总轮数上限沿用 12（防出题死循环），可提前收口；
- 问题必须带 `why` 与 `impact`，不只给一个空问题；
- `secret` 类型只允许单值输入；提交后后端写 SecretStore，**返回值只含
  `configured: true` 与 key 名**；值不进 SSE、日志、审计、画布 config、EKB；
- 用户回答「暂不提供」时，BuildSession 进入 `blocked`，不把缺失值填成默认值；
- 同一问题不得重复问；已回答的写入会话记录，后续引用。

#### 5.0.5 构建过程中提问

- Agent 遇到「两个节点都能做、选哪个」「参数含义不明确」「外部账号选哪个」
  「是否覆盖/回滚」「是否激活 draft 节点」→ 调 `ask_user`（拟新增工具），
  创建 interaction，暂停当前步，等面板回答；
- 回答若改变节点集合/范围/已发布定义 → 更新构建计划并**重新批次审批**；
  只改参数值且在原批次范围内 → 记录后继续；
- 运行失败后的修复提问同样走面板；失败原因与候选修复必须在面板里列清楚，
  不允许“我猜了一个值就重跑”。

#### 5.0.6 服务端强制（不能只靠提示词）

- 构建任务内的 `canvas_create` / `canvas_add_node` / `canvas_set_config` /
  `custom_node_create` / `workflow_definition_update` 先查 `build_session.ready`
  与 `batch.approved`；未满足 → 返回 `clarification_required` + 缺失清单 +
  interaction_id，**不产生任何写入**；
- `ask_user` 是唯一提问入口；返回 `paused` 时模型不得自答/重试同一问题；
- 手动编辑画布（无 build_session）不受此门限制，保持现有体验；
- 凭据只能经 `secret` 面板写入；任何工具都不接受明文凭据作为参数。

#### 5.0.7 验收判据

1. 一句模糊需求 → 未创建任何画布/节点前，面板先问；`ready` 前 `canvas_*`
   写入被服务端拒绝并返回缺失清单。
2. 缺 `profileId`/client secret → secret 面板；值不进 SSE/日志/画布 config/EKB；
   SecretStore 可读到；补齐后 BuildSession 恢复。
3. 构建中遇到二选一 → 面板出现；回答后继续；材料性变更触发重新批次审批。
4. 面板超时 → 状态 `blocked`（暂停），不是 failed；稍后回答可恢复。
5. 模型试图跳过提问直接建节点 → 服务端拒绝，返回 `clarification_required`。
6. 一次批次审批覆盖多节点变更；每个变更逐条审计，凭据只记 key 名。

### 5.1 节点参数自描述（P0）

**目标**：Agent 在添加节点前就知道要填什么。

**方案 A（推荐）**：扩展 `canvas_list_nodes` 返回结构，只增字段：

```json
{
  "type": "builtin:ad-streaming",
  "label": "广告流投放",
  "category": "commerce",
  "source": "commerce",
  "version": "1.0.0",
  "sub_blocks": [
    {"id": "platform", "type": "select", "required": true, "default_value": "amazon"},
    {"id": "campaign_id", "type": "input", "required": false}
  ],
  "inputs": [{"id": "input", "label": "输入", "required": false}],
  "outputs": [{"id": "output", "label": "输出"}],
  "default_config": {"platform": "amazon", "apply": "false"},
  "env_requirements": ["NEUROVA_AMAZON_ADS_CLIENT_ID", "NEUROVA_AMAZON_ADS_CLIENT_SECRET"],
  "idempotent": false
}
```

- `env_requirements` 需要 `NodeDefinition` 新增字段（默认空列表），先由
  commerce/MCP 节点声明；找不到声明的节点如实为空，不猜。
- 保持旧字段不变，前端与既有消费方无需同步改。
- 可选新增 `node_schema(type)` 单节点查询，避免列表过大。

**验收**：对 `builtin:ad-streaming` 查询能拿到 sub_blocks 与 required；
未声明环境的节点返回空数组；旧字段逐字不变。

### 5.2 注册表同步工具（P0）

拟新增 Agent 工具 `sync_nodes`：

```json
{
  "action": "sync",
  "scope": "all | tools | skills | mcp | custom | commerce | drama"
}
```

- 调用 `adapters.sync_all(registry)` 或其分项；
- 返回每类注册数（与 `sync_all` 现有返回一致）；
- 幂等；写进程内共享注册表，声明为非并发安全；
- 不写任何持久化数据，不需要审批，但必须审计。

**验收**：`create_skill` → `sync_nodes(scope=skills)` →
`canvas_add_node("skill:<name>")` 成功；不调用 `sync_nodes` 时失败并给出
「先同步」的明确提示，而不是只报未知类型。

### 5.3 自定义节点 CRUD 工具（P0）

拟新增三个 Agent 工具，复用 `CustomNodeService`，**只开放 L1/L2**：

```text
custom_node_create(spec, status="draft")
custom_node_update(node_type, spec)
custom_node_delete(node_type, force=false)
```

`spec` 字段与现有服务一致：

```json
{
  "type": "custom:campaign_audit",
  "label": "广告复盘",
  "description": "按 ACOS 复盘并输出建议",
  "category": "commerce",
  "tier": "composite",
  "form_schema": [{"id": "campaign_id", "type": "input", "required": true}],
  "inputs": [{"id": "input", "label": "输入"}],
  "outputs": [{"id": "output", "label": "输出"}],
  "executor_body": {
    "steps": [
      {"node_type": "builtin:ad-monitor", "config": {"ad_ids": "{{config.campaign_id}}"}},
      {"node_type": "builtin:llm", "config": {"prompt": "{{prev}}"}}
    ]
  }
}
```

**安全约束**：

- 类型必须带 `custom:` 前缀；禁止覆盖 `builtin:`/`tool:`/`skill:`/`mcp:` 命名空间；
- **创建默认 `draft`（2026-11-04 第 1 条裁定）**：
  - `draft` 不进 active 节点库，不能被 `canvas_add_node`/工作流引用；
  - 一次任务批次可连续创建多个 draft；**批次审批一次（第 5 条）**后统一 `active`；
  - 审批卡列出本批全部 draft 的类型、tier、步骤与目标命名空间；
- `delete` 前检查引用：被已发布工作流/画布引用时拒绝，列明引用方；
- 更新自动快照旧版本（服务已有 `custom_node_versions`）；
- 归属记录 `created_by`；非属主/非 admin 不得改删；
- L3 `tier=code` 明确拒绝，返回 `not_supported`，不静默降级。

**验收**：L1 模板节点可创建并执行；L2 步骤链能引用 `{{prev}}`；
非法 tier/空 template/空 steps/覆盖内置命名空间均拒绝；
draft 不可被画布引用；一次批次审批后全部 draft 转 active；
删除被引用的节点返回引用清单。

### 5.4 工作流定义读取/修改/发布（P1）

**裁定（2026-11-04 第 2 条）**：允许 Agent **直接修改已发布版本**——不需要先另建
一份草稿工作流；候选可在内存/临时快照上验证，通过后原子写入已发布定义。
但每次修改前必须先确定一个可回滚的**安全版本**；整个任务批次只审批一次（第 5 条）。

拟新增工具（或者在 `canvas_*` 增加 `source="definition"`，二选一）：

```text
workflow_definition_get(workflow_id)
  → {definition, version, status, safe_version, safe_reason}

workflow_definition_update(workflow_id, nodes, edges, base_version, batch_id)
  → {version, safe_version, validation}

workflow_rollback(workflow_id, target_version)   // 默认 rollback 到 safe_version
  → {version, restored_from}

workflow_publish(workflow_id, note)              // draft → published（仍保留）
```

**安全版本定义**：

- 最后一次「已发布/人工批准」的版本，**或**最近一次执行校验通过的版本；
  发布动作本身使该版本成为安全基线（人工批准就是一次显式确认）；
- 与 `workflow_versions` 区分：后者是**每次内容变更的快照**（现有
  `_record_version_if_changed`，`storage.py:559`），前者是**可退的底线**；
- **落点已定（§9.1）**：`workflows` 表新增 `safe_version` 列，记录版本号、
  原因、时间、校验凭据；迁移走 `storage.py` 既有幂等补列路径，不另建表；
- **没有安全版本 ⇒ 先为当前已发布版本建立安全基线快照**；快照失败则拒绝直接改，
  不拿“内存里的当前内容”冒充安全版本。

**批次 ID（已定，§9.1）**：`batch_id` 由 **Agent 轮次创建**，生命周期覆盖
本任务轮次内的「澄清 → 批次审批 → 写入 → 校验 → 提交/回滚 → 审计」；
跨轮次不沿用，避免把两次任务的动作混成一批。

**修改流程**：

```text
1. get：确认 status=PUBLISHED；safe_version 缺失时先为当前版本建立安全基线快照，
   快照失败才拒绝（并说明原因）
2. 任务批次审批（一次覆盖本批所有节点变更，第 5 条）
3. update：
   - base_version 乐观锁；
   - 写前确保当前版本已有 workflow_versions 快照（现有机制）；
   - 写后跑定义校验（DAG/端口/节点类型/子流程环）
4. 校验失败或后续执行失败：
   - 自动 rollback_workflow(safe_version)（storage.py:624 已具备）
   - 回滚本身产生新版本，undo-friendly
5. 成功后不自动提升 safe_version：
   - 需一次真实执行校验通过，或人工批准后才提升
```

**审批粒度**：一次任务批次一次审批，审批卡列出本批全部节点/边/配置变更；
每个变更仍逐条写审计（谁、批次、原版本、新版本、变更摘要）。

**验收**：

- 已发布且有安全版本：允许 update，新版本可执行，失败能回滚到 safe_version；
- 已发布但无安全版本：先为当前版本建立安全基线快照；快照失败才拒绝；
- 校验失败：自动回滚，safe_version 不变，审计记录回滚原因；
- 一次批次审批覆盖多个节点修改，但仍逐条审计；
- 回滚后 `workflow:<id>` 执行的是安全版本内容。

### 5.5 自愈闭环（P1）

**裁定（2026-11-04 第 4 条）**：由 **Agent 轮次编排**，不做引擎级自动重试。
引擎级重试只保留给 `idempotent=True` 节点的既有语义；节点修复必须有可解释的
观察、候选、评估与回滚。

目标形态：

```text
定时/手动触发
  → canvas_run
  → 读取 node_results 中 failed 节点
  → 查 EKB 修复经验（5.8.3）
  → 判定：参数错 / 缺节点 / 环境缺失 / 数据问题
  → 只做允许的修复（改 config、加已注册节点、调 sync_nodes、建 draft 节点）
  → 草稿副本统一落到**工作流定义草稿版本**（duplicate 为 DRAFT，`neurflow_api.py:898-922`）
  → 再 run 草稿版本（最多 5 轮）
  → 通过才提交；失败回滚并如实上报，不伪造成功
```

约束（与 2026-11-04 裁定对齐）：

- **一次任务批次一次审批（第 5 条）**：批次内可改多个节点、建多个 draft，
  审批卡汇总；每个变更仍逐条审计；
- **修改已发布定义**必须满足 5.4 的安全版本前置，并纳入同一批次审批；
- `batch_id` 由 Agent 轮次创建（§9.1），贯穿本任务轮次；
- 每轮修改写审计；draft 节点激活在批次审批时统一发生；
- **最多 5 轮**（已定，§9.1）、总预算上限；环境缺失发起 secret/补充面板，
  Agent 不代写、不读取凭据值；
- 复用 5.8 的 RSI 提案/回滚/评测基础设施与 EKB，不另造第二套经验库。

**验收**：

- 构造「配置键写错」的画布：自愈轮能读出错误、生成 patch、在草稿跑通、
  批次审批后提交；线上旧版本未被中途污染；
- 构造「缺凭据」的画布：停在上报缺哪些变量，不反复重试烧预算；
- 构造「需要新节点类型」的失败：draft 节点随批次审批激活，激活前不可被引用；
- 修复失败：回滚到安全版本/草稿快照，EKB 记录失败，不写成成功。

### 5.6 环境/凭据预检（P1）

**裁定（2026-11-04 第 3 条）**：环境需求随 `NodeDefinition` 走。

- `NodeDefinition` 新增 `env_requirements: List[str]`（只存名字，不存值），
  随节点版本快照一起持久化；
- `canvas_list_nodes` / `node_schema` 返回；
- 新增 `node_env_preflight(types)`：返回 `missing` 名单与「由哪个 StoreConnection /
  MCP 配置提供」的提示；不读取、不回显凭据值；
- 真正写凭据仍走既有 UI/SecretStore/MCP OAuth，不新开 Agent 写口。

### 5.7 安全与治理（贯穿）

| 面 | 规则 |
|---|---|
| 命名空间 | `custom:` 独占；禁止覆盖 builtin/tool/skill/mcp |
| 写共享注册表 | 按任务批次一次审批（第 5 条）：批次内建多个 draft，批准后统一 active；`NEUROVA_NODE_AUTHORING=1` 仅用于沙箱/CI，不替代审批 |
| 归属 | `created_by` + owner/admin 校验；跨用户不可改删 |
| 版本 | 更新前快照；发布不可覆盖历史 |
| 引用 | 删除前检查工作流/画布引用 |
| L3 代码 | 不开放；需沙箱、资源上限、审批门 |
| 审计 | 每次创建/更新/删除/发布写审计（谁、类型、版本、变更摘要） |
| 失败语义 | 不支持的 tier / 缺依赖 / 缺环境一律显式失败，不返回假成功 |

### 5.8 与现有 RSI 机制的复用边界

**已拍板（2026-11-04 第 6 条）：复用 RSI 的提案/回滚/评测基础设施与 EKB，
不把 `RSIOrchestrator` 直接接到节点失败上。** 节点修复的编排落一个新模块
`WorkflowRepairSupervisor`（或 `NodeRepairLoop`），RSI 作为库被调用，
不作为循环的所有者。

#### 5.8.1 RSI 现在是什么

- `RSIOrchestrator.run_iteration`（`rsi/orchestrator.py:439`）的固定流程是：
  收集四闭环反馈 → 收敛分析 → 生成参数优化 → 应用 → 全局性能实测 → 棘轮保留/回滚。
- 可优化参数是**硬编码参数表**：sleep / emotion / experience / tool_memory /
  context 五族（`rsi/integration_manager.py:33`），宿主是各闭环对象；
  `apply_optimization` 只改宿主属性。
- 候选生成是参数步进（5%/10%/15%/20% 朝 setpoint，`orchestrator.py:963` 附近），
  不是「改节点配置 / 换节点 / 补节点」这类离散修复。
- 自动执行受 `RSIDeploymentController` 阶段 gate 约束（`deployment_controller.py:67`），
  评测与棘轮依赖 `RSIEvalHarness`（`eval_harness.py:341`）与
  `RecursiveRatchetPruner`（`recursive_ratchet_pruner.py:76`）。

**关键事实**：RSI 的反馈信号里没有工作流/画布节点；参数表里没有节点配置；
`run_iteration` 的 gain/回滚是**整轮、全局**的。把它直接套到单节点失败上，
会把节点局部修复计入 RSI 的全局收敛与回滚账本，粒度与语义都不一致。

#### 5.8.2 可直接复用的三件

| 基础设施 | 现状能力 | 在节点修复中的用法 |
|---|---|---|
| 提案生命周期 | `PENDING → APPLIED → ROLLED_BACK` / `PENDING → REJECTED`；`require_approver` 人类审批（`evolution/proposal_lifecycle.py`） | 节点修复提案：目标 = `canvas_id`/`workflow_id` + `base_version` + patch；同一状态机与审批人规则 |
| 回滚快照 | `RSIRollbackManager.create_snapshot(system_state)` 接受任意 dict（`rollback_manager.py:100`） | 修复前对画布快照/工作流定义做快照，失败或指标退化时回滚；画布版本号仍是主锁 |
| 评测骨架 | `RSIEvalHarness` / `RecursiveRatchetPruner` 的「候选 → 评估 → 只保留改进」结构 | 节点修复的评估换成 `canvas_run` 的 `node_results`：失败→通过、耗时、成本、错误码；候选少时不必三筛 |

**不直接复用**：

| 组件 | 为什么 |
|---|---|
| `RSIOrchestrator.run_iteration` | 固定四闭环信号 + 全局参数表 + 整轮回滚；节点修复是局部、事件驱动、即时多轮，混用会污染 RSI 的收敛/棘轮账 |
| `RSIOPTIMIZABLE_PARAMETERS` | 没有节点配置族；硬塞会制造第二份参数口径 |
| `RSIDeploymentController` phase gate | 它是 RSI 自动执行档，不是节点修复授权；节点修复有自己的审批/预算/次数上限 |
| `PatternMiner` | 它挖的是**工具调用序列**（`evolution/pattern_miner.py:40`），不是节点失败→修复模式；不适用 |

#### 5.8.3 经验沉淀：用现有 EKB，不新造第二套

- `ExperienceKnowledgeBase.add_experience_record`（`skills/experience_knowledge_base.py:344`）
  已有 `skill_name / context / result / success / evidence / tags / agent_id`；
  `find_similar_experiences`（`:668`）可按上下文相似检索。
- 节点修复记录建议：
  - `skill_name`：统一用 `workflow_node_repair`（已定，§9.1），节点类型放 tags；
  - `context`：`{node_type, error_code, config_before, upstream_shape, env_missing}`；
  - `result`：`{patch, attempt, outcome}`；
  - `success`：仅在有服务端票据（节点从 failed → success）时给 True；
  - `tags`：`["workflow_node_repair", "node:<type>"]`。
- 检索时按 `(node_type, error_code)` 先精确、再 `find_similar_experiences` 模糊；
  无历史经验时返回空，不编造「最佳实践」。
- 不把节点修复写进 RSI 的 `experience` 参数族；RSI 那边的
  `crystallize_min_observations` 等只是经验系统的阈值参数，不是经验存储。

#### 5.8.4 已拍板循环（WorkflowRepairSupervisor）

```text
canvas_run 失败 / 定时任务失败
  → 读取 node_results（failed 节点 + error + 上游输出形状）
  → 检索 EKB 修复经验（精确 error_code / 相似 context）
  → 生成候选修复（按优先级）：
      1) 补/改 config（值来自节点 schema / 运行时报错）
      2) 换已注册节点（同语义替代）
      3) 建议或创建自定义节点（L1/L2，需审批）
  → 统一应用到**工作流定义草稿版本**（duplicate 为 DRAFT）
  → 执行草稿版本（canvas 入口先编译为 workflow draft）
  → 评估：失败→通过 / 错误码变化 / 成本与耗时
  → 棘轮：通过才提交（新 version）；不通过回滚到修复前快照
  → 写 EKB 记录（成功/失败都写，success 三态如实）
  → 最多 N 轮；仍失败则如实上报，不伪造成功
```

**为什么用草稿版本**：节点修复会改共享画布/工作流；直接在线上改，
一次坏补丁就把正在跑的流程打断。统一用工作流定义的 DRAFT 副本
（现有 `POST /workflows/{id}/duplicate` 即产出 `status=DRAFT` 的副本，
`neurflow_api.py:898-922`），再配合 `base_version` + 快照回滚，
与现有画布乐观锁、工作流版本快照同口径。

#### 5.8.5 安全闸门（节点修复专用，不借 RSI 的阶段 gate）

- 改 config / 换已注册节点：可在 `NEUROVA_NODE_REPAIR=1` 武装下自动执行，
  但每轮写审计、最多 5 轮、总成本上限；
- 新建自定义节点 / 改已发布工作流：必须审批（复用 5.3/5.4 的闸门）；
- 缺凭据 / 缺环境：发起 §5.0.4 的 secret/补充面板；Agent 不代写、不读取凭据值，
  用户不提供则 `blocked`，不拿默认值继续；
- 评估不得用「没有报错」代替「目标达成」：必须有 node_results 的前后对比；
- 失败记录也要写 EKB，success 不得默认 True。

#### 5.8.6 验收判据

1. 一个「config 键写错」的画布：supervisor 能读到错误、生成 patch、
   在草稿上跑通、提交新版本；线上旧版本未被中途污染。
2. 一个「缺凭据」的画布：停在「缺 `NEUROVA_...`」上报，不重复烧轮次。
3. 一个「换节点才能修」的失败：候选包含同语义替代节点；替换后评估通过才提交。
4. 修复失败：回滚到快照，EKB 记录 `success=False`，不把失败写成成功。
5. 同一 `(node_type, error_code)` 第二次出现：EKB 能检索到上次修复并作为候选，
   但不得跳过评估直接应用。

---

## 6. 关键流程

### 6.1 Agent 组装一条新流程

```text
用户一句话需求
  → BuildSession(received → clarifying)
  → 面板问答：意图/范围/验收标准/目标类型（5.0.3 条件 1–2）
  → canvas_list_nodes + 注册表检查（扩后：参数/端口/默认值/环境）
  → 缺参数/缺凭据 → 面板（secret 输入只写 SecretStore）
  → 缺节点类型 → 选替代节点 / 建 draft（批次审批）
  → ready：就绪清单全绿
  → 展示构建计划 + 批次审批
  → canvas_create
  → canvas_add_node ×N（必要时先 sync_nodes）
  → canvas_set_config（按 sub_blocks 契约）
  → canvas_connect
  → canvas_run
  → 构建中疑问/选择 → 面板；回答后继续
  → 读 node_results；失败节点按 5.5 修复
  → 成功后可 schedule_task(canvas_id=...)
```

### 6.2 自定义节点

```text
用户：把这条三步链固化成可复用节点
  → custom_node_create(tier=composite, steps=[...], status=draft)
  → （同一任务批次内可继续建多个 draft）
  → 批次审批一次（第 5 条）
  → 批准后统一 active
  → sync_nodes(custom)
  → canvas_add_node("custom:...")
```

### 6.3 已发布工作流

```text
workflow_definition_get
  → 确认 status=PUBLISHED；safe_version 缺失则先建基线快照（失败才拒绝）
  → 批次审批一次（覆盖本批全部节点变更）
  → 校验/修改节点（内存/临时快照候选，不另建草稿工作流）
  → workflow_definition_update(base_version, batch_id) 原子写入已发布定义
  → 校验；失败则 workflow_rollback(safe_version)
  → 执行校验通过后提升 safe_version
  → workflow:<id> 执行新版本
```

---

## 7. 分期与验收

| 批次 | 内容 | 红灯判据（先红后绿） |
|---|---|---|
| N0 | BuildSession 就绪门 + 通用问答面板 + `secret` 输入 + `ask_user` + 服务端拒绝未就绪写入 | 未 ready 前 `canvas_*` 写入被拒；缺凭据走 secret 面板且值不进 SSE/日志/画布/EKB；构建中提问可暂停/恢复；超时 `blocked` 非 failed；一次批次审批覆盖多节点 |
| N1 | `canvas_list_nodes` 扩展 + `node_schema`（只读） | 查询 ad-streaming 含 sub_blocks/required；旧字段不变；未声明环境为空 |
| N2 | `sync_nodes` | 不调用时 skill 节点不可加且报明确码；调用后可加 |
| N3 | `custom_node_create/update/delete`（L1/L2，默认 draft） | 越权/命名空间/非法 tier 拒绝；draft 不可被引用；批次审批后统一 active；更新快照；引用检查 |
| N4 | `workflow_definition_get/update/rollback/publish` | 已发布且有安全版本可改；无安全版本先建基线（快照失败才拒绝）；校验失败自动回滚；批次审批一次覆盖多节点；回滚后执行安全版本 |
| N5 | `node_env_preflight` + `WorkflowRepairSupervisor`（Agent 轮次 + 工作流定义草稿版本 + EKB + 复用 RSI 提案/回滚/评测骨架） | 缺环境只上报；配置错可自愈；线上版本不被中途污染；批次审批；最多 5 轮/预算上限 |

> **实施进度（2026-11-04）**：N0/N1/N2/N3/N4/N5 已实施（见 §12）。

每批按 `AGENTS.md`：

1. 先写行为红（不得是 import/collection error）；
2. 最小实现转绿；
3. 红自证（stash 本批生产改动复跑，红的恰是本批判据）；
4. live-verify（`create_app` + `TestClient`，隔离数据根，真 HTTP 栈）；
5. 单任务单提交，正文写根因、红绿输出、净 LOC 去向。

---

## 8. 明确不做（本设计范围外）

- L3 代码节点（需要沙箱 + 审批门 + 资源上限，另立设计）；
- Agent 自行代写 SecretStore / 代管 MCP OAuth 凭据（用户经 §5.0.4 的 `secret`
  面板主动输入、由后端写入 SecretStore 不在此列；Agent 不得读取或回显值）；
- 运行中热改当前执行（快照编译模型不变，只做「改完重跑」）；
- 自动发布到生产/外部系统（只做画布运行与受控发布）；
- 以「节点存在」代替「节点可用」：所有新增能力必须有执行判据。

---

## 9. 已拍板（2026-11-04）

六项裁定 + 本次交互门要求均已确定，不再作为待拍板；实施中若出现新分叉另立票。

| # | 裁定 | 设计落点 | 关键约束 |
|---|---|---|---|
| 1 | 自定义节点默认 `draft` | §5.3、§5.7、N3 | draft 不进 active 节点库、不可被引用；批次审批后统一 active |
| 2 | 允许直接改已发布版本，但必须先有**安全版本**可回滚 | §5.4、N4 | 无安全版本先为当前版本建基线快照（失败才拒绝）；校验/执行失败自动回滚；回滚本身产生新版本 |
| 3 | 环境需求落在 `NodeDefinition.env_requirements`（随节点版本走） | §5.6、N1 | 只存变量名不存值；未声明节点如实返回空，不猜 |
| 4 | 自愈由 **Agent 轮次编排**（非引擎级自动重试） | §5.5、§5.8、N5 | 引擎重试仍只给 `idempotent=True` 节点；修复循环可解释、可回滚 |
| 5 | 审批按「一次任务内的节点批次」一次 | §5.3、§5.4、§5.5、§5.7 | 批次内多节点/多 draft 汇总审批；每个变更仍逐条审计 |
| 6 | 复用 RSI 提案/回滚/评测基础设施与 EKB | §5.8、N5 | 不复用 `RSIOrchestrator.run_iteration` 与全局参数表；不污染 RSI 收敛账 |
| 7 | **先问清再动手**：一句话需求先过 BuildSession 就绪门；构建中疑问/选择走面板 | §5.0、§6.1、N0 | 服务端强制未 ready 不写画布；凭据只走 secret 面板且只写 SecretStore；超时 `blocked` 非 failed；不得静默假设 |

**裁定 2 的额外约束**（安全版本）：

- 安全版本 = 已发布/人工批准的版本，或最近一次执行校验通过的版本；
- 若工作流从未有过安全版本，先为当前已发布版本建立安全基线快照；
  快照失败则不能直接改；
- 修改已发布版本必须走 §5.4 的 `safe_version` 前置 + 批次审批；
- 回滚目标只能是安全版本或本次修改前的快照，不能回滚到未校验的中间态；
- `safe_version` 的提升必须有一次执行校验或人工批准，不随“保存成功”自动提升。

**裁定 4/6 的额外约束**（修复循环）：

- `WorkflowRepairSupervisor` 作为 Agent 轮次的一部分运行，不常驻后台自动改线上；
- 复用 `proposal_lifecycle` 的状态机与 `require_approver`、`RSIRollbackManager`
  的快照能力、`RSIEvalHarness`/棘轮的“候选→评估→只留改进”结构；
- 经验写入 `ExperienceKnowledgeBase`，不把节点修复塞进 RSI 的 `experience` 参数族。

---

## 9.1 实现细节（已定，2026-11-04）

以下不改变六条裁定与 N0 交互门，均已确定：

| # | 实现细节 | 裁定 |
|---|---|---|
| 1 | `safe_version` 存储 | `workflows` 表加列（`safe_version`），走 `storage.py` 既有幂等补列迁移，不另建表 |
| 2 | 批次 ID 生成与生命周期 | 由 **Agent 轮次**创建；覆盖本任务轮次的「澄清 → 审批 → 写入 → 校验 → 提交/回滚 → 审计」，跨轮次不沿用 |
| 3 | 草稿副本落点 | **工作流定义草稿版本**：用现有 `POST /workflows/{id}/duplicate` 产出 `status=DRAFT` 副本（`neurflow_api.py:898-922`）；画布入口先编译为 workflow draft |
| 4 | 自愈轮次预算 | **最多 5 轮**；另设 token/执行时间上限作为附加闸门 |
| 5 | EKB `skill_name` 语义 | 统一用 `workflow_node_repair`；节点类型/错误码放 `tags`，避免污染技能经验统计 |

**实现顺序**：N0 先落交互门与面板；N1/N2 补参数/环境与同步；N3/N4 补节点
CRUD 与安全版本；N5 接草稿版本修复循环与 5 轮预算。

---

## 9.2 实施前阻塞点（决定「能不能一口气做完」）

以下不是产品裁定，是落地前必须验证/选型的工程问题；不解决会在中途返工。

| # | 问题 | 现状证据 | 影响 | 建议处理 |
|---|---|---|---|---|
| B1 | 如何触发 BuildSession | 文档只写「用户一句话」，未定义入口 | 自动意图识别会误触发普通聊天；显式入口又不够「一句话」 | v1 先显式入口（按钮/斜杠命令）+ 意图识别只做提示，不自动建会话；后续再放开 |
| B2 | 面板长等待 vs 工具超时 | 工具默认超时 60s（`tool_coordinator.py:62`）；审批已有 pending/续跑模式（`tool_executor.py:1716`）；PlanSession 是独立 REST 会话 | `ask_user` 若阻塞等待，会被 60s 超时掐断或转后台 | 采用 pending/resume：`ask_user` 返回 `paused + interaction_id`，回答后由 BuildSession 恢复，不在工具调用里死等 |
| B3 | 画布工具写 CanvasStore，草稿却定为工作流 DRAFT | `canvas_*` 写 `CanvasStore`；工作流 DRAFT 有独立存储/duplicate（`neurflow_api.py:898-922`） | 两者不是同一写入面，直接混用会出现「草稿在画布、提交在工作流」两套状态 | **N4 已结**：选「新增 workflow 定义编辑工具」——`workflow_definition_update` 直接改定义，`workflow_definition_duplicate` 产 DRAFT 副本；画布工具继续只写 CanvasStore，两类写入面不混用 |
| B4 | 草稿工作流没有 Agent 执行工具 | REST `POST /workflows/{id}/execute` 不校验 PUBLISHED（`neurflow_api.py:358`）；`workflow:<id>` 工具只暴露已发布（`workflow_as_tool.py` 文档） | 修复循环无法用现有 Agent 工具执行 DRAFT 版本做评估 | **N4 已结**：新增 `workflow_execute(workflow_id, allow_draft=true)`；默认仍只允许已发布 |
| B5 | 批次审批与写入原子性 | 当前 canvas 工具逐次立即写；批次审批未来才加 | 审批前就落盘 = 先斩后奏；审批后逐条写失败会留下半批 | 先落 staging（草稿画布/DRAFT），审批后一次提交；失败整体回滚 |
| B6 | `safe_version` 迁移与回填 | `workflows` 表无该列；历史版本表有快照但无安全标记 | 存量已发布工作流无安全版本，首次修改会被门挡住 | **N4 已结**：幂等补 4 列 + 启动时为已发布存量补基线（无快照先补当前内容快照） |
| B7 | 前端面板抽离与 secret 输入 | `PlanPanel` 是计划模式 modal；无 secret 字段；11 语言词条需补齐 | 直接复用会耦合计划文档；secret 输入涉及安全渲染 | 抽 `QuestionRoundView` + 新 `BuildPanel`；secret 字段只提交不回显；补齐 11 语言 |
| B8 | 权限/归属/凭据边界 | BuildSession、批次、草稿、interaction 都新增对象 | 跨用户/跨 Agent 可能越权；secret 可能落错库 | 所有对象带 `user_id/agent_id/build_session_id`；secret 只写 SecretStore，审计只记 key 名 |
| B9 | N5 的 RSI/EKB 接线细节 | RSI 参数表无节点族；EKB 的 `skill_name` 已定统一名 | 评估、经验检索、5 轮预算需要新适配层 | **N5 已结**：EKB 统一 `workflow_node_repair`；只复用提案状态机与回滚快照，不接 `RSIOrchestrator` |
| B10 | 真实账号/外部服务验证 | 本机无真实 Amazon Ads 等凭据；现有测试用替身 | 无法证明真实投放/接口兼容 | 代码级 live-verify 用替身 + 真实 UI/DB；外部账号验证单独列验收项，不冒充完成 |
| B11 | 一次提交 vs 仓规 | `AGENTS.md` 要求单任务单提交、先红后绿、live-verify | 把 N0–N5 塞进一个未验证提交会违反纪律，也难回滚 | 按 N0/N1+N2/N3+N4/N5 四段提交；每段独立红绿与回滚点 |

**结论**：**不能承诺「一口气全部做完且一次全绿」**。可以在一段连续工作里完成，
但必须按上面的 B1–B11 先做小验证/选型，并按 N0 → N1+N2 → N3+N4 → N5 分段交付；
每段都要红灯、绿灯、红自证、live-verify。任何声称「全做完」但没有分段证据的交付，
按本仓纪律都不算完成。

---

## 10. 附录：现状证据命令

```bash
# 1. 画布工具清单
python - <<'PY'
import ast
src = open('neurova/builtin_tools.py', encoding='utf-8').read()
tree = ast.parse(src)
for node in tree.body:
    if isinstance(node, ast.AnnAssign) and getattr(node.target, 'id', '') == '_BUILTIN_SCHEMAS':
        keys = [ast.literal_eval(k) for k in node.value.keys if isinstance(k, ast.Constant)]
        print([k for k in keys if k.startswith('canvas_')])
PY

# 2. 注册表同步入口
rg -n "sync_all\(" neurova

# 3. 自定义节点 HTTP 面
rg -n "nodes/custom" neurova/api/endpoints/neurflow_api.py

# 4. 画布工具写的是 CanvasStore
rg -n "get_canvas_store|CanvasStore|canvas_to_workflow" \
  neurova/collaboration/canvas_store.py \
  neurova/collaboration/canvas_bridge.py \
  neurova/tool_executor.py

# 5. 工作流定义回写面
rg -n "workflows/.*/definition|writebackDefinition" \
  neurova/api NeurUI/src/api/modules/collaboration.ts
```

---

## 11. 与既有文档的关系

- NeurFlow 引擎总体说明：`docs/01-architecture/22-neurflow-workflow-engine.md`
- NeurFlow 开发规格：`docs/01-architecture/neurflow-dev-spec.md`
- 外部 API 设计：`docs/01-architecture/neurflow-external-api-design.md`
- 本文只讨论「Agent 对节点/工作流定义的写权限与参数/环境发现」，不重复引擎内部机制。


---

## 12. N0 实施记录（2026-11-04）

### 12.1 阶段 0 探针结论

| 探针 | 结果 |
|---|---|
| 草稿工作流能否执行 | 能：`save_workflow(status=draft)` → `WorkflowExecutor` 执行 `completed` |
| 草稿版本 | `workflow_versions` 可记录；`rollback_workflow` 可回滚 |
| 画布 staging | 画布工具写 `CanvasStore`；工作流 DRAFT 有独立存储，二者仍需在 N3/N4 接「私有草稿画布 → workflow DRAFT」 |
| SecretStore | 读写正常，可承载 secret 面板 |

### 12.2 已落代码

| 层 | 文件 | 内容 |
|---|---|---|
| 会话状态 | `neurova/build_mode/build_session.py` | BuildSession 状态机、问答轮、就绪清单、secret 不落会话、5 轮/12 轮上限、batch_id |
| API | `neurova/api/endpoints/build_mode.py` | `/v1/build/sessions` 创建/读取/回答/批准/交互回答/取消；鉴权与属主校验 |
| 工具 | `neurova/tool_executor.py` + `builtin_tools.py` | `ask_user` 返回 `paused`；画布写工具构建门（未 ready/approved 拒绝） |
| 上下文 | `neurova/core/build_context.py` | 请求级 `build_session_id` ContextVar |
| SSE | `neurova/api/endpoints/console.py` | `build_interaction_required` 事件 |
| 前端 | `NeurUI/src/components/chat/BuildPanel.vue`、`BuildQuestionInput.vue`、`api/modules/build.ts` | `/build` 面板、问答/secret/批准 |
| 入口 | `useSlashCommands` + `ChatComposerArea` + `ChatPage` | `/build` 显式入口；批准后带 `build_session_id` 继续聊天 |
| i18n | 11 个 locale | `build.*` 与 `chat.slashBuild` |

### 12.3 验证

- 后端 N0 判据：14 passed（BuildSession 5 + ask_user/门禁 6 + API 3）；
- 工具契约/可重现性/扩展面：178 passed；
- 前端：`vue-tsc --noEmit` exit 0；全量 vitest `2313 passed`；
- 活体：真实前端 `/chat` 输入 `/build …` 成功拉起「构建工作流」面板；
- 安全专项：secret 回答只写 SecretStore，会话 JSON 与磁盘均不含明文（测试断言）。

### 12.4 N0 边界（仍未做）

> 本段记录 N0 当时的边界；其中 B3/B4 与 `custom_node_*` / `workflow_definition_*`
> 已在 N3/N4 实施（见 §12.6/§12.7），保留原文仅作历史对照。

- **B3/B4 仍在**：画布工具目前直接写 CanvasStore；把草稿提交为 workflow DRAFT、以及草稿执行工具（`workflow_execute(draft=true)`）属于 N3/N4；
- 门禁只覆盖画布写工具与 `schedule_task`；`custom_node_*` / `workflow_definition_*` 尚未实现，因而未纳入；
- 构建中的 `ask_user` 需要用户回答后由前端发一条续跑消息；尚未做服务端自动拉起 Agent 回合；
- N0 没有实现 RSI/EKB 修复循环（N5）。


### 12.5 N1/N2 实施记录（2026-11-04）

**N1 参数自描述**

- `NodeDefinition` 新增 `env_requirements: List[str]`（只存名字）；
- `node_definitions` 表新增 `env_requirements_json`，建表与旧库幂等补列；
- `custom_nodes` 的 L1/L2 spec 支持 `env_requirements`，创建/更新持久化；
- `CanvasOpService.list_nodes` 返回 `sub_blocks / inputs / outputs /
  default_config / required / env_requirements / idempotent / version / tier /
  status`，旧字段保持；
- 新增 `node_schema(node_type)` 工具，精确拿单节点契约；
- 广告三节点声明 `NEUROVA_AMAZON_ADS_CLIENT_ID/SECRET`。

**N2 注册表同步**

- 新增 `sync_nodes(scope)` 工具，调用既有 `adapters.sync_all` 或分项同步；
- 技能/自定义/MCP 节点注册后，`canvas_add_node` 可见；
- 工具声明为非只读、非并发安全；失败如实返回。

**验证**

- N1/N2 判据 + 工具契约：`174 passed`；
- 自定义节点/注册表/存储回归：`95 passed`；
- 节点 API/电商/画布工具回归：`106 passed`（含新增广告 env 声明格）；
- 前端无改动，沿用 N0 的 `vue-tsc 0 / vitest 2313 passed`。

**仍在**

- N3 custom 节点 draft/批次激活工具；
- N4 工作流定义工具 + `safe_version` + DRAFT 草稿提交；
- N5 修复循环/RSI/EKB；
- N0 的 B3/B4（画布 staging 到 workflow DRAFT、草稿执行工具）仍按 N3/N4 接。


### 12.6 N3 实施记录（2026-11-04）

**自定义节点草稿与批次激活**

- `NodeDefinition` 新增 `batch_id`，`node_definitions` 表新增 `batch_id` 列（建表 + 旧库补列）；
- `CustomNodeService.create_node` 支持 `status=draft|active` 与 `batch_id`；
- 新增 `activate_node`：仅 draft → active；active 幂等；
- 新增 Agent 工具：
  - `custom_node_create(spec)`：固定 draft，`batch_id` 取当前 BuildSession；
  - `custom_node_update(node_type, spec)`：只允许本批次 draft；
  - `custom_node_activate(node_type)`：校验 `node.batch_id == session.batch_id`；
  - `custom_node_delete(node_type)`：只允许本批次 draft；
- 四个工具纳入构建写门：BuildSession approved/building 之前服务端拒绝；
- 工具声明为非只读、非并发安全、非可重现。

**验证**

- N3 判据 + 自定义节点/工具契约：`206 passed`；
- 覆盖：未批准拒绝、draft 创建、批次激活、active 更新/删除拒绝、draft 更新/删除；
- `NodeDefinition` 的 `batch_id`/`env_requirements` 持久化通过存储回归。

**仍在**

- N4：`workflow_definition_get/update/rollback/publish`、`safe_version` 列、
  已发布直接改 + 安全回滚、DRAFT 草稿提交与草稿执行工具（B3/B4）；
- N5：修复循环/RSI/EKB/5 轮。


### 12.7 N4 实施记录（2026-11-04）

**安全版本存储（§5.4、B6）**

- `workflows` 表新增 4 列：`safe_version / safe_reason / safe_at / safe_evidence_json`；
  建表带列 + 旧库幂等补列；
- `save_workflow` 的 `INSERT OR REPLACE` 显式继承安全列——否则每次保存都会抹掉回滚底线；
- `getSafeVersion / setSafeVersion / ensureSafeVersion`：
  - `setSafeVersion` 只接受已存在的版本快照，不伪造基线；
  - `ensureSafeVersion` 无有效基线时先为**当前内容**补快照（快照失败抛异常，不拿内存内容冒充）；
  - 版本容量裁剪（20 条）永不裁剪 `safe_version` 指向的快照；
- 启动迁移 `_backfill_workflow_safe_versions`：为已发布且无基线的存量工作流补基线
  （`safe_reason=migration_baseline`），单行失败不阻塞建库。

**定义编辑模块 `neurova/collaboration/neurflow/workflow_definition_editor.py`**

- `validateWorkflowDefinition`：DAG（环/起止/悬挂边）+ 节点类型 + 自定义节点必须 active +
  端口声明（兼容 NodePort 与注册表 dict 两种形态）；
- `getWorkflowDefinition`：返回定义/版本/状态/安全版本；已发布无有效基线时先建基线；
- `updateWorkflowDefinition`：`base_version` 乐观锁；已发布先确保安全版本；
  校验失败**不落盘**（比“写后回滚”少一个瞬态非法窗口，审计记 `update_refused`）；
- `rollbackWorkflowDefinition`：缺省回安全版本；回滚自身产生新版本；安全标记不变；
- `publishWorkflowDefinition`：校验 + 编译工作流 Agent；发布动作把当前版本设为安全基线；
- `duplicateWorkflowDefinition`：复制为 DRAFT 草稿副本，元数据记录
  `source_workflow_id/source_version/batch_id`（N5 修复循环的暂存落点）；
- `executeWorkflowDefinition`：默认只允许已发布，`allow_draft=true` 才试跑草稿；
  已发布执行成功才把当前版本提升为安全版本（`execution_verified`）；
- 所有变更逐条写 `workflow_definition_audit.jsonl`（actor/batch/old_version/new_version/
  拒绝原因/执行凭据），落数据根，可用 `NEUROVA_WORKFLOW_DEFINITION_AUDIT` 覆盖。

**Agent 工具与门禁**

- 新增 6 工具：`workflow_definition_get/update/duplicate`、`workflow_rollback`、
  `workflow_publish`、`workflow_execute`；
- 除 `get` 外全部纳入构建写门（BuildSession approved/building）并声明非可重现；
  构建会话内 `batch_id` 必须与会话批次一致；
- REST 同口径：`POST /workflows/{id}/publish` 成功后提升安全版本；
  已发布工作流的 `PUT /workflows/{id}` 与 `PUT /workflows/{id}/definition`
  在写入前确保安全基线，建基线失败则拒绝改写。

**N3 更正**

- `CustomNodeService.create_node/update_node` 不再把 draft 注册进 active 节点库；
  只有 `activate_node` 后才对画布/工作流可见——与 §5.3「draft 不进 active 节点库」对齐。

**验证**

- N4 判据：`26 passed`（安全版本存储 5、定义校验 4、工具/门禁/回滚/发布/草稿/执行 17）；
- 全量 `tests/unit/neurflow`：`799 passed`；
- `tests/unit/collaboration`：`588 passed`；
- 工具/上下文/build_mode 相邻回归：`116 passed`；
- 活体（真 `create_app` + 真 JWT + 隔离数据根，10 个断言全 PASS）：
  发布 → `safe_version=1` → 工具改定义 `v2`（安全版本仍 1）→ 回滚 `v3`（内容恢复）→
  执行成功提升安全版本到 `v3`（`execution_verified`）→ 复制 DRAFT 副本 →
  审计 4 条落隔离根 → 仓内 `data/` 指纹未变。

**仍在 / 已知边界**

- N5：已实施（见 §12.8）；
- B5 的“整批原子提交”未做：定义更新本身是单次原子保存，但一次任务里的
  多工具变更仍是逐条落盘 + 逐条审计，没有跨工具事务；N5 必须以草稿副本隔离生产；
- 校验器实测发现 3 个**存量**模板含未注册节点类型（`data_analysis` / `document` /
  `web_maintenance`：`builtin:web-scrape`、`builtin:data-analyze`、
  `builtin:data-visualize`、`builtin:doc-read`、`builtin:doc-write`、
  `builtin:seo-optimize`、`builtin:broken-link-check`）。这是模板自身的旧缺口，
  不是 N4 引入；此类模板在补齐注册前会被 `workflow_publish` / `workflow_execute`
  如实拒绝，不会假执行。


### 12.8 N5 实施记录（2026-11-04）

**环境预检 `neurova/collaboration/neurflow/env_preflight.py`**

- `preflightNodeEnv(types)` 返回 `declared / sources / missing / providers /
  unknown_types / inactive_types / ready`；
- 只读环境变量名与 `SecretStore.list_keys()`，不读取、不回显任何凭据值；
- 缺环境时按变量名给出配置来源提示（SecretStore / StoreConnection / MCP）；
- 工具 `node_env_preflight(types)`：只读、可并行。

**修复监督器 `neurova/collaboration/neurflow/workflow_repair.py`**

- 目标二选一：`workflow_id` → `duplicateWorkflowDefinition` 产 DRAFT 副本；
  `canvas_id` → `canvas_to_workflow` 先编译为 DRAFT。**提交前原目标零写入**；
- 预检缺环境 / 未知节点 / 未激活自定义节点 → `blocked`，0 轮、0 执行；
- `NEUROVA_NODE_REPAIR=1` 才允许自动修复；提交需要已批准构建会话，
  或显式 `NEUROVA_NODE_REPAIR_COMMIT=1`；
- 候选生成：
  - schema 配置键 typo → 近似必填键重命名；
  - 必填键缺失且有 `default_value` → 填默认值；
  - 无配置候选时 → 同类别 + 标签近似的已注册节点 `replace_node` 候选（需人确认语义）；
  - EKB `workflow_node_repair` 历史 patch → 作为候选，**仍必须重新评估**；
- 每轮：DRAFT 执行 → 读 failed 节点/错误 → 生成候选 → RSI 快照
  （`RSIRollbackManager.create_snapshot`）→ 提案 `PENDING→APPLIED`
  （`require_approver` / `assert_can_decide`）→ 改 DRAFT → 再跑；
  失败则回滚快照并把提案转 `ROLLED_BACK`；
- 停止条件：无候选 → `needs_agent`；缺必填无默认 → `needs_input`；
  建节点等非自动候选 → `needs_approval`；最多 **5 轮**（请求值夹到 1–5）；
  默认时间预算 300 秒（`NEUROVA_NODE_REPAIR_TIME_BUDGET_S`）；
- 通过后提交：工作流走 `workflow_definition_update` 乐观锁；
  已发布目标提交成功后 `safe_version = repair_verified`；
  画布只提交配置差异（`CanvasOpService.set_config(replace=True)`），
  结构化差异进 `deferred_changes`，不静默改画布；
- EKB：成功/失败/阻断/回滚/提交失败都写；`success=True` 只在真实
  `node_results` 给出成功回执时落；`skill_name=workflow_node_repair`，
  tags 带 `node:<type>` 与 `outcome:<...>`；
- 审计：`repair_blocked / repair_round / repair_rollback / repair_success /
  repair_failed` 逐条写 `workflow_definition_audit.jsonl`。

**引擎根修：节点内层 `failed` 不再假成功**

- `execution_engine._execute_single_node` 改前只把 `timeout/pending` 外显，
  其余内层状态一律记 `success`；64 处内置执行器的 `status=failed` 与
  custom/subflow 的 `status=error` 因此全被读成「流程跑通」；
- 现在 `failed/error` 走与异常同一条失败路径：节点结果记 `failed`、
  下游停止、工作流状态 `failed`、错误原因保留；
- 连带更正一条旧判据：`test_resolution_context_injection_in_workflow_execution`
  原依赖 `builtin:llm` 无模型时的假成功；改为在注册表边界注入成功替身，
  并断言 `memory_manager/context_pool` 真被注入。

**画布提交**

- `CanvasOpService.set_config` 新增 `replace=False`（默认仍为浅合并）；
  N5 配置提交用 `replace=True` 原子替换整份 config；
- 前端 `canvas_op` 的 `set_config` 支持 `data.replace`，按替换应用；
- 增删节点/边等结构化差异不在本轮自动写画布，返回 `deferred_changes`。

**工具**

- `node_env_preflight`：只读、可并行；
- `workflow_repair`：构建写门 + 非可复现；支持 `workflow_id` / `canvas_id`
  二选一，`max_rounds` 1–5，`commit` 默认 true。

**验证**

- N5 判据：`17 passed`（预检 5 + 修复/画布/限额/授权 12）；
- 全量 `tests/unit/neurflow`：`815 passed`；
- `tests/unit/collaboration`：`588 passed`；
- 工作流相关相邻回归（agent/api/tools/workflow/cognitive）：`136 passed`；
- 工具/上下文/build_mode：`116 passed`；
- 前端：`vitest 2313 passed`、`vue-tsc --noEmit` exit 0；
- 活体（真 `create_app` + 真 JWT + 隔离数据根，15 个断言全 PASS）：
  自定义组合节点配置键写错 → DRAFT 内真实失败 → 改名补丁 → 重跑成功 →
  提交 `v2`、`safe_version=2`（`repair_verified`）、EKB 成功记录；
  `builtin:ad-streaming` 缺凭据 → 预检 `blocked`、0 轮、目标停在 `v1`；
  预检只返回变量名与来源标签；仓内 `data/` 指纹未变。

**仍在 / 已知边界**

- B5 跨工具原子提交未做：修复循环以 DRAFT 隔离生产，提交是单次定义更新；
- `create_node` 候选仍不自动执行（需审批）；画布结构化差异只返回清单；
- 「换节点」候选按同类别 + 标签近似生成，不保证语义等价，交给审批确认；
- 真实 Amazon Ads 账号/凭据仍未验证（与 B10 一致）。
