# NeurFlow 定义 × 无限画布打通 与 工作流归属模型设计

日期：2026-09-14 ｜ 状态：**已实施（B0–B5 全落地，前后端全绿）** ｜ 前置结论来源：两轮代码核查（文件行号均为核查时点实据）

---

## 1. 背景：现状与断点

「工作流」页（`NeurUI/src/workflow/WorkflowPage.vue`，路由 `/collaboration/workflows`）下两个 tab：
- **画布**：无限画布编辑形态。文件存储 `data/collaboration/canvases/<id>.json`（`neurova/collaboration/canvas_store.py`），快照含 nodes/edges/position，带 `version` 乐观锁。
- **定义**：NeurFlow 执行内核 `WorkflowDefinition`。SQLite `neurflow.db` 的 `workflows` 表（`neurova/collaboration/neurflow/storage.py`），已有 `user_id` 属主 + `public` 全局可见。

设计意图是"画布是可编辑形态，定义是执行内核"（`WorkflowPage.vue:12` 注释），但实际是**单向、临时编译式**关系，断点清单：

| # | 断点 | 证据 |
|---|------|------|
| 1 | 「定义」tab 点"打开"只弹详情 Modal，不进画布编辑器 | `WorkflowPage.vue:84,445-448,98-114` |
| 2 | 编辑器只有一条加载路径，查画布文件库，查不到 404，不回退到定义 | `CanvasDesignerPage.vue:2187-2208`、`useCollaboration.ts:128`、`collaboration_api.py:505-512` |
| 3 | 保存一律写画布文件，永不回写定义；`PUT /neurflow/workflows/{id}/definition`（`neurflow_api.py:1000-1027`）在画布链路零调用 | `CanvasDesignerPage.vue:1976-2009` |
| 4 | `definition_to_canvas()`（`canvas_bridge.py:167-243`）仅被 ComfyUI 导入与 NL 生成消费，无"打开已有定义"入口；且转换丢 `variables/status/version/tags`，metadata 里的 `workflow_id` 溯源标记在导入路径被 pop（`collaboration_api.py:711`） | `collaboration_api.py:698,710`、`nl_designer.py:164,220` |
| 5 | 运行走临时编译 `wf_canvas_<uuid>` 不落库，执行记录与持久化定义 id 对不上 | `collaboration_api.py:723-779`、`canvas_bridge.py:150` |
| 6 | 布局槽位"后端有、前端无接线"：`WorkflowNode.position`（`models.py:134`）随 nodes_json 可落库；`PUT /workflows/{id}/viewport`（`neurflow_api.py:1030-1047`）存在但前端不调，刷新视口复位 | `CanvasDesignerPage.vue:626` |
| 7 | 自定义节点类型未打通：`CustomNodeService.create_node/update_node/delete_node`（`custom_nodes.py:111,146,202`）已实现但无 HTTP 端点、无前端入口 | `neurflow_api.py:840-920` 仅 GET/search/sync/stats |
| 8 | **安全缺口（顺带根治）**：画布文件无任何用户隔离，快照无 `user_id`，canvas CRUD 端点不校验属主——任意登录用户可读写/删除他人画布 | `canvas_store.py:79-91`、`collaboration_api.py:478-540` |

已具备、无需重做的能力：双向转换器都在；节点参数级编辑已打通（属性面板按 `NodeDefinition.sub_blocks` 渲染表单，工具/Skill/MCP 参数自动映射，`neurflow/adapters.py:41-203`、`CanvasDesignerPage.vue:1533-1588,1669-1691`）；定义侧属主隔离与 404 同构语义已在 storage 单点落地。

---

## 2. 归属模型设计

### 2.1 对用户三分类方案的评估

原方案：公共工作流（按用户隔离，=用户下无项目、无 agent 归属）／项目工作流（按项目隔离）／agent 工作流（按 agent 隔离，=agent 对话自动产生）。

方向正确，与项目顶层模型（项目→协作/团队/工作流，2026-09-02 归属修复）和既有先例（KB 可见性模型、记忆 agent_wide 口径、渠道 session_scope）一致。但有三处需要修正：

1. **"agent 产生"是来源（origin），不是归属（ownership），两者正交**。agent 在项目上下文里对话生成的工作流，按三互斥分类无法归置——它既有项目归属又有 agent 来源。若把"来源"编码进"归属"，这个场景一出现模型就破。
2. **agent 不是安全主体**。权限判定最终都落在 user_id（JWT 实名）；agent_id 的真实作用是**资产池归属与运行时可见集**（该 agent 能在对话/subflow/调度器里引用哪些工作流），不承担访问控制。三类"隔离"中只有用户隔离与项目成员可见是权限语义，agent 维度是引用语义。
3. **三分类应实现为过滤视图，而不是三套存储或三个互斥标记**。互斥标记（`type` 枚举列）会在每处 CRUD 强制仲裁优先级；可空双列（project_id/agent_id）+ 视图组合天然允许一个工作流同时出现在项目视图与 agent 资产池。

### 2.2 推荐模型（单安全属主 + 双可空归属列 + 来源列）

```
user_id    : str   必填，安全属主（判定/迁移回填 'default'，沿用 6238766c 语义）
project_id : str?  可空，协作归属上下文（非空=项目工作流，成员共享）
agent_id   : str?  可空，agent 资产池归属（决定运行时可引用集）
origin     : str   来源：manual | nl_chat | template | comfyui | evolution
public     : bool  沿用现状：跨用户全局可读（已发布）
```

画布与定义**共用同一组归属列**——这是第 3 节打通的硬前提（否则回写后两份记录归属劈叉）。canvas 快照新增 `user_id`，存量文件迁移回填 `default`（同 `_backfill_workflow_user_ids()` 幂等模式）。

### 2.3 三类 tab 视图 = 查询过滤

| 视图 | 过滤条件 | 读权限 | 写权限 |
|------|---------|--------|--------|
| 个人（原"公共"） | `user_id=self AND project_id IS NULL AND agent_id IS NULL` | 属主 | 属主 |
| 项目 | `project_id ∈ 我的项目` | 项目成员 fail-closed（先例：`_user_can_access_agent` 式成员判定，KB 可见性模型） | 成员可编辑，或收紧为属主编辑——实施时按项目 RBAC 现状定，默认属主写、成员读 |
| Agent | `agent_id = 该 agent`（agent 运行时可引用集） | agent 属主 + 该 agent 的运行身份 | agent 属主 |

- 命名建议：用户口中的"公共工作流"改叫**个人工作流**，避免与 `public` 标志（全局公共）撞名。
- 对话内 agent 生成时**上下文继承**：会话带项目 → 同时写 `project_id + agent_id, origin=nl_chat`，条目同时出现在项目视图与 agent 视图；无项目 → `agent_id` only。这就是不做互斥 type 列的收益——无需仲裁规则。
- 判定下沉 storage 单点（`get_canvas/save_workflow` 的 `requester_id/is_admin` 模式），deny 与不存在同构 404 防枚举，18 端点挂载清单直接复用 6238766c 的先例；非 HTTP 入口（cron/webhook/chat 桥/`WorkflowTaskExecutor`）接属主方式同样复用。

---

## 3. 打通方案（画布 ⇄ 定义双向编辑）

### 3.1 加载侧
- 定义 tab"打开"改为跳编辑器：路由带来源标记（`/collaboration/canvas/:id?source=definition` 或独立段 `/collaboration/definition/:id`，实施时择一）。
- 后端提供"按来源解析快照"：source=definition 时读 `WorkflowDefinition` → `definition_to_canvas()` 返回快照，`metadata.workflow_id` 作为溯源标记**保留不再 pop**。
- 补往返映射：`variables/tags/status` 双向携带（改 `canvas_bridge.py` 两函数，互逆）。

### 3.2 保存侧
- 编辑器检测到来源为定义时，保存走 `PUT /neurflow/workflows/{id}/definition`：节点坐标写 `WorkflowNode.position`（storage 已持久化，零 schema 改动），视口写 `PUT /viewport`，前端补 `neurflow.ts` 封装与加载/保存接线。
- 乐观锁：定义侧补 `version` 递增比对（对齐画布 `base_version` 语义），防双端互踩（多端同开时的丢更新与 09-02 排序事故同级预防）。

### 3.3 运行侧统一
- 来自定义的画布：保存后直接 `POST /neurflow/execute`（持久化 id），执行记录 `agent_id/user_id` 归位，发布/版本/trigger/subflow 引用链路自然对齐。
- 纯个人画布维持"编译临时定义"执行不变（增量原则：不下调现有画布行为）。

### 3.4 画布归属收编（前置安全批）
- canvas 快照补 `user_id`，CRUD/list/run 挂属主判定（fail-closed），存量回填。此批**先于**双向编辑实施：归属劈叉与越权是打通后的放大故障。

### 3.5 自定义节点类型（独立批，可选）
- `CustomNodeService` CRUD 暴露为 `POST/PUT/DELETE /neurflow/nodes`（登录+属主判定，内置类型禁删），前端节点面板加"新建节点类型"入口；`inert-but-ready` 不适用——此功能有真实消费方。

---

## 4. TDD 实施批次（每批先红后绿 + 受影响套件回归）

| 批次 | 内容 | 关键红色用例 |
|------|------|-------------|
| B0 | 画布 user_id 属主隔离（§3.4） | bob 读/改/删/运行 alice 画布 → 404 同构；list 不含；存量回填幂等 |
| B1 | 归属列统一（§2.2）：定义+画布补 project_id/agent_id/origin + 三视图过滤 | 三视图过滤矩阵；项目成员读 fail-closed；deny/不存在同构 |
| B2 | 双向编辑接线（§3.1/3.2）：加载回退、definition 保存回写、position/viewport 持久化、往返不丢字段 | 打开定义→画布快照字段全等回环；保存后 PUT definition 载荷含 position；刷新视口恢复 |
| B3 | 运行统一（§3.3） | 来自定义的画布执行记录 workflow_id == 持久化 id |
| B4 | agent 对话生成归位（§2.3 上下文继承） | 项目会话生成 → 双列齐 + origin=nl_chat；无项目 → agent only |
| B5（可选） | 自定义节点类型 CRUD + UI | 注册→出现在节点面板→画布可用→delete 守卫内置类型 |

兼容硬约束（用户既定原则）：只提升不下降——`variables` 语义、画布 run 临时编译路径、`public` 过滤、core/agent 框架零改动；所有存量行为回归（tests/unit/neurflow 667+、api/neurflow 47、integration 34、前端 vue-tsc + vitest）为每批 DoD。

## 5. 风险与对策

- **双存储劈叉**（文件画布 vs SQLite 定义）：B0/B1 强制两组列同构，打通后新增列必须同步进 canvas_bridge 往返映射，防回归测试锁定（快照→定义→快照字段全等）。
- **画布历史越权面**：B0 独立先行的理由；不做则任何"打通"都在放大它。
- **并发编辑**：定义侧乐观锁（§3.2）+ 画布 `base_version` 已具备，编辑器加载时携带版本、保存冲突提示刷新。
- **subflow 悬空**：agent/项目视图改变可引用集后，删除工作流前需反查 subflow 引用（`neurflow/subflow.py` 运行期已只认 PUBLISHED，属主维度补删除守卫）。

---

## 6. 实施终态（2026-09-14，B0–B5 全落地）

> 全部按 TDD 先红后绿。设计口径有 2 处相对本文前文的收敛修正，见文末「实现偏差」。

### 落地清单
- **B0 画布属主隔离**：`CanvasStore` 补 `user_id`/`origin` 列（缺省 `default` 懒归一，不重写旧文件）+ `_can_read`/`_can_write` 单点判定（owner/admin 全通、项目成员只读、deny 与不存在同构）；`create` 属主以 JWT 为准防快照伪造、`update`/`mutate`/`delete`/`list` 加 `requester_id`/`is_admin`/`project_ids`；`collaboration_api` 画布 CRUD/run/ops/import 全挂 `get_current_user_or_default` 并透传身份；新增单源 `neurova/api/project_access.py`（`requester_project_ids`/`is_project_member`）。
- **B1 归属列统一**：`WorkflowDefinition` + `workflows` 表补 `project_id`/`agent_id`/`origin`（幂等 ALTER + `idx_workflows_project`）；`get_workflow`/`list_workflows`/`search_workflows` 加项目成员可读面 + `view=personal|project|agent` 三视图；`find_subflow_references` 删除守卫；`duplicate`/`instantiate` 落 `origin=template`；`PUT /workflows` 全量更新时 payload 缺失归属列以存量为准（旧前端不抹除）。
- **B2 双向编辑**：`GET /collaboration/canvas/{id}?source=definition` 把定义编译为可编辑快照（携带 `version`/`viewport`/溯源 `metadata.workflow_id`）；`PUT /workflows/{id}/definition` 扩展 `base_version` 乐观锁 + `name`/`description`/`viewport` 回写，局部语义保 `variables`/`status`；编辑器 `editorSource` 双源加载/保存分流。
- **B3 运行统一**：`POST /collaboration/canvas/{id}/run` 支持 `source=definition`——直跑持久化定义、执行记录挂真实 workflow id 并落 `executions` 表；`runs/{run_id}?source=definition` 轮询走定义读取校验。
- **B4 对话生成归位**：`canvas/from-nl` 响应带 `origin=nl_chat`+`agent_id`，NL 设计器透传至编辑器保存归属列。
- **B5 自定义节点**：`CustomNodeService` 首曝 HTTP（`POST/GET/PUT/DELETE /neurflow/nodes/custom`，builtin 守卫 400、非属主 404 同构、type 冲突 409），注册表单入口在 `WorkflowPage`。
- **前端**：`WorkflowPage` 三视图下拉 + 归属/来源 tag + 定义「打开」跳编辑器（`?source=definition`）；`collaboration.ts`/`neurflow.ts` API 与类型对齐；i18n 17 新键 ×11 语言。

### 测试
- 新增后端 5 文件 62 用例：`test_canvas_store_ownership`(17)、`test_canvas_ownership_api`(11)、`test_workflow_ownership_v2`(16)、`test_canvas_definition_bridge_api`(10)、`test_custom_nodes_and_nl_origin`(8)。
- 回归：后端 `unit/api + unit/collaboration + unit/neurflow` = **2702 passed**；integration 34 绿；前端 **1435 passed**；vue-tsc **0 错**；i18n 一致性 22 绿。
- **预存失败台账**（与本次无关，A/B 确认相关文件相对 HEAD 零改动）：`test_cron_trigger::test_fire_calls_dispatch`（P2 trigger_source 注入后断言过期）、`test_neurloop_integration_fixes`（3，evolution 签名漂移）、`test_channel_qrcode_*`（收集期 `segno` 缺失，环境项）。

### 实现偏差（相对本文前文）
1. **乐观锁基线**：定义侧用 `workflow_versions` 表真实版本号（`get_workflow_version_number`），非新造列。
2. **归属保持**：定义回写复用 `PUT /definition` 局部语义 + `save_workflow` 属主保留，`project_id`/`agent_id`/`origin` 随 loaded 对象原样写回，未在 `canvas_bridge` 往返里搬运（快照回写不重建定义，天然零丢失）。
