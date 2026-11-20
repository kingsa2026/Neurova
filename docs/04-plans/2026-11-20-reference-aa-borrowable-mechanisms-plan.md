# 参照系 AA（Linger）借鉴机制实施细则

- 来源：[reference_aa_vs_neurova_local_personal_agent_comparison_2026-11-20.md](../08-research/reference_aa_vs_neurova_local_personal_agent_comparison_2026-11-20.md) §10（八项可借鉴机制）
- 日期：2026-11-20
- 性质：实施计划（未实施；逐项含现状锚点、目标机制、步骤、测试设计、风险与验收判据）
- 优先级口径：P0=安全/可靠性直接收益且改动集中；P1=工程质量与既有主线契合；P2=收益依赖产品形态演进，暂缓

## 0. 总览

| # | 机制 | 优先级 | 规模 | 主要落点 | 依赖 |
|---|------|--------|------|----------|------|
| 1 | 单条出站 WS 的本机执行面（可靠性纪律部分） | P2 | S-M | `api/endpoints/mobile_pairing.py`、`api/endpoints/session_sync.py` | 无 |
| 2 | 先记账再执行、unknown 不重放 | **P0** | M | `tool_executor.py`、新 `core/tool_call_journal.py` | 无 |
| 3 | 一条命令定义三投影 | P1 | M-L | 新 `tools/catalog.py`、`builtin_tools.py` | 无 |
| 4 | 推送韧性（订阅先于读/合并/心跳重验/兜底扫描） | P1 | M | `collaboration/outbox_delivery.py`、console/chat SSE | 无 |
| 5 | 契约快照 + verify-diff 门 | P1 | M | `api/endpoints/__init__.py` 注册表、新 `contracts/` | 无 |
| 6 | placement 感知凭据轮换 | P2 | S-M | `security/secret_store.py`、`web_reach/credentials.py` | 无 |
| 7 | Dreaming 式规则自改进 | P1 | L | `cognitive_layers/meta_cognition_layer`、`growth_layer`、S16 纪律 | 项 4 的夜间调度位 |
| 8 | 护栏三招（复核失败即拒/跟随式免审/车道互斥） | **P0** | M | `computer_use/`、`security/command_authority.py` | 项 2 的 journal |

建议实施顺序：**项 2 → 项 8 → 项 5 → 项 4 → 项 3 → 项 7 → 项 6 → 项 1**。
项 2 与项 8 共享"先记账"底座，先做项 2 可让项 8 的 journal 直接复用。

---

## 1. 项 2（P0）：工具调用先记账、unknown 不重放

### 现状锚点
- `neurova/tool_executor.py:1413` `ToolExecutor.execute(tool_name, params)` 是全仓工具执行的**单一管道**（S18 已收口，MCP/技能/CLI 工具均经此）。
- `neurova/core/agent_run_ledger.py` 已有运行级台账（acquire/heartbeat/parkTurn），但**工具调用级**没有"先记账 → 执行 → 回写终态"的账本。
- `neurova/security/command_authority.py` 已有命令权威判定，可与账本联用。

### 目标机制（Linger 对应）
Linger 在三处（连接器执行、屏幕操作 journal、decision 执行器）实施同一纪律：动作身份**先落账再执行**；结果 unknown（超时/网络断/5xx）时**保留账目、封锁重放**，后续同 key 请求返回原 unknown 记录而非再次执行。

### 实施步骤
1. 新增 `neurova/core/tool_call_journal.py`：
   - 表 `tool_call_journal`：`id`、`idempotency_key`（=sha256(tool_name+canonical(params)+turn_id)）、`tool_name`、`params_digest`、`status`（running/succeeded/failed/unknown）、`result_digest`、`error_class`、`created_at`、`settled_at`。
   - API：`begin(key, tool, params) -> JournalEntry`（唯一键冲突时返回已有条目）、`settle(id, status, result_digest, error_class)`。
   - 存储走既有 SQLite 连接池（`core/connection_pool.py`，WAL 已开）。
2. `ToolExecutor.execute`（tool_executor.py:1413）入口接入：
   - 计算幂等键 → `begin`；若命中**已 settle 的同键条目**且工具声明为外部写类 → 直接返回原结果（附 `replayed: true`）；
   - 若命中 `unknown` 条目 → **不重放**，返回原 unknown 与 `blocked_by_journal: true`，提示走人工确认或显式 `force` 通道；
   - 执行后按结果 `settle`；异常分类：可判定失败（参数错/权限拒）=failed；超时/连接断/5xx=**unknown**。
3. 工具元数据补声明：在 `neurova/builtin_tools.py` 的工具注册处增加 `external_write: bool`（邮件/渠道发送/GitLab/Notion/文件写等），仅外部写类启用"unknown 封锁重放"；只读工具不记账（零开销）。
4. 观测：H-4 账本（agent_run_ledger）增 `tool_journal` 事件种类，前端工具卡可显示"已回放/结果未知"。

### 测试设计（先红后绿）
- 红：伪造一个会超时的外部写工具 → 首次调用返回 unknown；**同 key 第二次调用不得再触达工具**（用计数器断言只执行一次）。
- 红：同 key 同参数重放 → 返回原 succeeded 结果且执行计数仍为 1。
- 绿：只读工具不产生账目（性能不回退）。
- 回归：`tests/unit/` 既有工具面测试全量（execute 单管道 0 旁路口径不变）。

### 风险与回滚
- 风险：幂等键规范化不当导致误判重复（如 params 含时间戳）。对策：canonical JSON（排序键、剔除易变字段白名单）+ 单测钉住。
- 回滚：journal 表独立，`NEUROVA_TOOL_JOURNAL=0` 环境开关直通（默认开）。

### 验收判据
外部写工具在超时/断连场景下，重复调用不产生第二次真实副作用；审计面能看到每次外部写的 running→终态轨迹。

---

## 2. 项 8（P0）：护栏三招（复核失败即拒 / 跟随式免审 / 车道互斥）

### 现状锚点
- `neurova/computer_use/`：`actions.py`、`browser_manager.py`、`desktop_uia.py`、`capability_state.py`（三平台骨架已在 AD-6 铺设）。
- 审批链：`neurova/agent/swarm.py:435` 起 `request_approval` 运行中审批；`security/command_authority.py` 命令权威。
- B5 落地的语音通道是新的注入面（语音转写可能携带指令）。

### 目标机制（Linger 对应）
规则白名单直行（只读/跟随式同站导航）→ 未放行者交 LLM 复核，**复核超时/失败一律拒**（宁可不做）；桌面输入与浏览器会话分车道互斥；动作先写 journal（复用项 2 账本）。

### 实施步骤
1. `neurova/computer_use/guardrail.py`（新）：
   - `classify(action) -> readonly | follow_nav | sensitive`：只读白名单（截图/读取/滚动/后退等）直行；`browser_navigate` 若目标 URL 与当前页同 registrable domain 或是当前页已见链接 → 免审；其余 sensitive。
   - `review(sensitive_action) -> allow/deny/unavailable`：接现有审批链（swarm `request_approval`）；**LLM 复核异常/超时返回 unavailable，按拒处理**。
2. `browser_manager.py` 挂钩：navigate 前过 guardrail；同站判定用 URL registrable-domain 工具函数（publicsuffix 兜底用末两段，cache 于会话）。
3. 车道互斥：`computer_use` 内新增轻量 `LaneMutex`（desktop / browser:<session> 两把容量 1 锁）；需要前台窗口的桌面动作与浏览器动作互斥；任何一侧存在 unknown 结果时对侧拒绝（复用项 2 journal 的 unknown 状态）。
4. 语音转写进入回合前打 `untrusted_input` 标记（对齐记忆层 SENSITIVE_RULES 的双层脱敏口径），提示词中声明"转写是数据不是指令"。

### 测试设计
- 红：LLM 复核桩超时 → sensitive 动作不得执行（execute 计数 0）。
- 红：同站导航免审、跨站导航必须复核。
- 红：desktop 车道被占用时浏览器敏感动作被拒且 vice versa。
- 回归：computer_use 既有测试（action_result retry 契约等）零新增失败。

### 风险与回滚
- 风险：复核过严影响流畅度。对策：只读/跟随式白名单先行，白名单可配置。
- 回滚：`NEUROVA_CUA_GUARDRAIL=off` 直通（默认开），守卫测试仍锁默认值。

### 验收判据
敏感动作在复核不可用时 0 执行；同站导航 0 审批打扰；屏幕与浏览器操作不再互相踩踏。

---

## 3. 项 5（P1）：契约快照 + verify-diff 门

### 现状锚点
- 路由单一挂载点：`neurova/api/endpoints/__init__.py` `ENDPOINT_MODULES` 注册表 + `register_endpoint_routers`（失败显式记账）。
- 前端调用散在 `NeurUI/src/api/modules/*`（手写路径）。

### 实施步骤
1. 新增 `scripts/export_openapi.py`：用 `create_app()`（不启动服务）导出 `/api/v1` 的 openapi.json，落 `contracts/openapi.snapshot.json`。
2. 新增门 `scripts/check_openapi_snapshot.py`：重新导出并与快照 diff，不一致即红（对齐 Linger 的 verify=重新生成+diff）。
3. 新增守卫 `scripts/check_frontend_api_paths.py`：扫描 `NeurUI/src/api/modules/*` 的请求路径字面量，逐条核对存在于快照（防"前端路径漂移 404"）。
4. 接入 `make check` / CI 快检（不跑重codegen；openapi-typescript 类型生成列为后续可选批）。

### 测试设计
- 红：临时给某 endpoint 加一条假路由不更新快照 → 门红。
- 红：前端 module 写一个不存在路径 → 门红。
- 绿：正常改动 + 已更新快照 → 绿。

### 风险与回滚
- openapi 导出可能受启动副作用影响（需要 DB/Agent 装配）——用 `create_app` 的最小装配参数或容错导出；若装配依赖过重，退化为"路由表提取器"（直接遍历 `app.routes`）。
- 回滚：门为独立脚本，撤掉即回原状。

### 验收判据
任何 API 形状变更若不同步快照，CI 红；前端引用不存在的路径，CI 红。

---

## 4. 项 4（P1）：推送韧性四件套

### 现状锚点
- SSE 已有四处：`console.py:793/1272`、`chat.py:560/782`、`neurflow_api.py:712`。
- 事件底座：`neurova/collaboration/outbox_handler.py` + `outbox_delivery.py`（outbox 已具雏形）。
- WS：`console.py` `/ws/{client_id}`、`mobile_pairing.py` `/ws`、`session_sync.py` `/ws/{session_id}`。

### 实施步骤
1. 抽 `neurova/api/realtime_push.py`：统一"订阅先于读首屏 → 快照 → 增量"模板（现四处各自实现）。
2. 心跳里重验订阅权限（会话/成员资格），过期即断（对齐 Linger voice SSE）。
3. outbox_delivery 增加兜底扫描（对齐 due-notifier：漏通知 30s 内必达）。
4. 前端（NeurUI）SSE/WS 消费统一重连+游标补拉工具（参照 harmony 侧已有的 gap 自愈思路）。

### 测试设计
- 红：订阅建立晚于事件写入 → 首屏快照仍含该事件（不丢）。
- 红：权限过期后心跳周期内连接被服务端关闭。
- 红：人为丢一条通知 → 兜底扫描一个周期内补达。

### 风险与回滚
四处 SSE 语义各异（chat 流是回合流，非通知流），只统一"通知/状态"类，不动回合流。回滚：新服务逐处切换，可按端点灰度。

### 验收判据
断线重连后不丢通知、不重复消费；权限失效的连接在一个心跳内被摘除。

---

## 5. 项 3（P1）：工具定义三投影（help/schema/权限同源）

### 现状锚点
- `neurova/builtin_tools.py:2498` `MAIN_AGENT_ONLY_TOOLS`、`:2505` `get_registered_tool_names()`——工具名册与权限剔除集已是单源，但 description/schema/help 分散。
- `tool_executor.py:1413` 执行管道按名分发。

### 实施步骤
1. 新增 `neurova/tools/catalog.py`：`ToolDef {name, description, args_schema(JSON Schema), read_only, external_write, min_role, agent_scope}`；提供 `all_tool_defs()`。
2. 第一步只做**盘点投影**：从 builtin_tools/注册表导出 `contracts/tool_catalog.json`（含权限类），快照门同项 5。前端工具卡/管理面改读该文件。
3. 第二步渐进迁移：新工具一律用 ToolDef 声明；存量工具按域分批搬（每次一批，快照同步）。
4. help 文本生成器：agent 系统提示词的工具段由 catalog 渲染（消灭"提示词与实际工具面漂移"）。

### 测试设计
- 红：catalog 与 get_registered_tool_names() 不一致 → 门红。
- 红：external_write 工具未标 → 门红（对齐项 2 的消费要求）。
- 快照 diff 门复用项 5 脚本。

### 风险与回滚
存量工具多（builtin_tools 近 2500 行），迁移按域分批、不强制一次到位；快照门先只锁"名册一致性"，schema 完整性随迁移逐步提高。

### 验收判据
工具名册/权限/schema/help 四面同源；新增工具只改一处，四面自动一致。

---

## 6. 项 7（P1）：Dreaming 式规则自改进（夜间 clue→rule）

### 现状锚点
- `neurova/cognitive_layers/meta_cognition_layer/`、`cognitive_layers/growth_layer/`、`memory_layer/meta_cognition(_module).py`。
- S16 记忆纪律（候选→世代→人工审阅）已有成熟机制可复用。
- DCPM 对照结论：夜间整理引擎缺位是已知差距。

### 实施步骤
1. 新增规则存储：`rule_candidates`（clue 级：kind+decision+证据引用+计数）与 `behavior_rules`（转正规则：kind→decision，附来源与生效范围），走 S16 的候选/审阅状态机。
2. 夜间任务（挂既有调度/睡眠窗口）：取当日"自主发出行为 + 用户后续反馈（纠偏/感谢/忽略）"→ LLM 抽 clue（结构化：kind、decision、证据 id）→ 同 kind 计数 ≥2 合并为候选规则；**用户直接点名**（显式反馈）单次即可成规则。
3. 次日生效：相关判定面（proactive/工具审批提示/回复策略）注入**已转正规则**（不注入 clue，对齐 Linger 纪律）。
4. 全程接 H-4 账本与 growth_log，前端成长面板可见"规则从哪两条反馈来"。

### 测试设计
- 红：两条同 kind 纠偏 → 夜间合并为一条候选规则；单条不合并。
- 红：显式点名一次即成规则。
- 红：判定面只读到转正规则，读不到未转正 clue。

### 风险与回滚
- 规则污染风险：转正走 S16 人工审阅闸（默认开）；规则条数上限与过期机制。
- 回滚：功能开关 `NEUROVA_DREAMING=0`。

### 验收判据
同一类纠偏出现两次后，次日对应判定面行为改变，且规则可追溯 to 两条原始反馈。

---

## 7. 项 6（P2）：placement 感知凭据轮换

### 现状锚点
- `neurova/security/secret_store.py`、`neurova/web_reach/credentials.py`；keyring 已按数据根派生（C5）。

### 实施步骤
1. 渠道/集成凭据增加 `binding`（设备/租户/渠道三元组 hash）与 `revision`；使用时校验 binding 一致，不一致即失效。
2. 换绑流程：新 binding 生效 → 旧 revision 凭据 `expires_at=now()`（对齐 Linger `EnsureManagedForPlacement`）。
3. 库中只存凭证哈希 + 用途标注（对齐"只存 SHA-256"）。

### 测试设计
- 红：同凭据换 binding 后旧值不可用。
- 红：同 binding 重复领取返回同一有效凭证（幂等）。

### 验收判据
凭据泄漏场景下，改绑即吊销；正常重启/续用不产生新凭据。

---

## 8. 项 1（P2）：跨机 WS 的账本与重放

### 现状锚点
- `mobile_pairing.py:1817` `/ws`（手机遥控 PC 的既有通道）、`session_sync.py:114` `/ws/{session_id}`。

### 实施步骤（已按本节落地，进度见 §10 项 1）
1. 为移动遥控指令加"先记账再执行"（指令账本按 (设备, 指令 id) 幂等，独立于项 2 的工具账本——遥控指令的重复判定在 WS 入口，不在工具执行咽喉）。
2. 断线重放：出站事件账本按设备保留最近 500 帧（单调 seq），重连 `sync_resume` 按游标补发；连接 epoch 按设备发号递增，帧内携带供客户端识别新连接。
3. media/流类操作的 epoch 发号：移动 WS 通道暂无 media 复用场景，待出现时按同一 epoch 语义扩展（不预造无消费方代码）。

### 验收判据
手机断网 30s 内的遥控指令不丟、不重复执行；重连后状态一致。

---

## 9. 执行与登记约定

- 每项独立提交，遵循先红后绿 + live-verify（涉及真链路的项 2/8/4 需真后端验证）。
- 完成后在本文档对应小节标注提交号与日期，并同步 `docs/0-index/README.md`。
- 项 2/8 落地后，回填对照报告 §10 的"落地记录"。

## 10. 实施进度（2026-11-20）

- **项 2 已实施**：新增 `neurova/core/tool_call_journal.py`（begin/settle/run 编排 + computeKey + classifyFailure，SQLite 数据根落盘、RLock+WAL、`NEUROVA_TOOL_JOURNAL=0` 直通）；`tool_executor.py` 的 `execute` 单管道全部经 `_executeJournaled`（只读能力声明工具不记账）。测试 13 绿；并修掉 `object.__new__` 构造路径的 `_agent` 缺属性问题。**测试隔离**：`tests/conftest.py` 新增 autouse 夹具按用例隔离账本库（防跨用例回放污染）。
- **项 8 已实施**：新增 `computer_use/guardrail.py`（只读白名单/同站免审/LLM 复核失败即拒，`NEUROVA_CUA_GUARDRAIL=off` 直通）与 `computer_use/lane_mutex.py`（desktop/browser 车道互斥 + unknown 封道）；`browser_manager.navigate`、`actions` 前台输入族挂钩。新增 38 测试，computer_use 全量 857 绿。
- **项 5 已实施**：新增 `scripts/export_openapi.py`、`scripts/check_openapi_snapshot.py`、`scripts/check_frontend_api_paths.py` 与 `contracts/openapi.snapshot.json`（1073 路由 + 4 WS）；顺带根修 FastAPI operationId 跨进程不稳定与 `_IncludedRouter` 懒包裹遍历盲区，并修正 console.ts 死码 WS 路径。14 测试绿。
- **项 4 已实施**：`outbox_delivery.py` 增投递后回读核实与 `sweepUndeliveredEvents` 兜底扫描（`NEUROVA_OUTBOX_SWEEP` 默认开）；新增 `api/realtime_push.py` 统一 SSE 模板（订阅先于读/游标增量/心跳权限重验），neurflow 执行事件流已迁作样例。16 新测试绿 + 881/647/85/23 回归绿。
- **项 3 已实施（第一步）**：新增 `neurova/tools/catalog.py`（137 工具全量投影：name/description/schema/read_only/external_write/agent_scope）+ `scripts/check_tool_catalog.py` 快照门 + `contracts/tool_catalog.json`；`context/orchestrator.py` 的 `render_tools_description` 以 catalog 渲染样例工具。23 测试绿，tools 1345 绿、context 1250 绿。
- **项 6 部分由既有机制覆盖**：移动配对已实现"设备身份摘要存储 + 短时效 connect_ticket + 长身份幂等续签"（mobile_pairing.py），与 Linger 纪律同构；剩余增量仅"换绑即吊销"语义，待 pairing registry 专项小批处理（不造无消费方代码）。
- **项 7 已实施（最小闭环）**：新增 `cognitive_layers/dreaming.py`（rule_clues 聚合计数 / behavior_rules 候选→active / dreamSweep 转正 / activeRules 只读 active；转正闸接 S16 `screenMemoryContent` 敏感筛查 fail-closed；`NEUROVA_DREAMING` 门控），夜间接线挂 `core/idle_tracker.py` 既有睡眠巩固漏斗。13 新测试绿 + cognitive_layers 626 绿 + A/B 自证零新增失败。未尽：反馈采集点（post_chat 链）与判定面注入（proactive/审批提示）待后续批次。
- **项 6 已实施（2026-11-20 晚，换绑即吊销增量）**：`core/mobile_device_store.py` 的 `register` 在同一物理设备（user_id+device_id）经新配对码再次入册时，当场吊销旧 pairing 绑定（revoked + token_epoch 递增——旧凭证的续签与重连被 `verifyDeviceSecret`/`isAdmissible` 双闸拦下；`verifyDeviceSecret` 补上 state 闸，此前吊销行旧密钥仍可核验通过）；同 pairing 重复确认幂等不自吊销；不同设备并存不受影响。4 新测试绿 + 既有在册库持久化 7 绿。
- **项 7 已实施（2026-11-20 晚，反馈采集+判定面注入补全）**：新 `cognitive_layers/dreaming_feedback.py`——采集侧：审批裁决（approve/reject 经 `noteApprovalDecision` 落 `tool_approval` 线索，挂在 `ApprovalManager.approve_request/reject_request` 单源）、回合反馈（post_chat 管线后台步 `turnFeedbackStep`：确定性分类纠偏/感谢/点名；本轮弹过主动提问且用户负反馈 → `proactive_ask/suppress` 线索；显式点名 → `user_directive` 单次成候选；无消费面的账不写）。注入侧（只读 active）：`proactiveSuppressed()` 闸住主动提问出队、`approvalHint()` 把裁决倾向/命中点名写进审批请求 `metadata.dreamingHint`（建议性，不自动裁决）。conftest 加 dreaming 库逐用例隔离。14 新测试绿 + 审批族 90 绿 + 管线回归绿。**turn_pacing 抽出**：动机出队间隔表与三个旁路判定助手移至 `cognitive_layers/turn_pacing.py`（管线再出口同名，导入面不变），抵消管线净增行数守尺寸棘轮。
- **项 1 已实施（2026-11-20 晚，远程驾驶可靠性通道）**：新增 `neurova/api/mobile_ws_ledger.py`——连接 epoch 按设备发号递增、出站帧**先落账再发送**（设备级单调 seq 注入帧内）、`sync_resume {last_seq}` 按游标补发（带 `replay:true`）、遥控指令按 **(pairing_id, command_id) 复合主键**先记账再执行（同 id 重放原终态 `replayed:true`/运行中报 `command_already_running`，不二次执行；**失败回合同样收敛终态**，不留永挂 running）；schema 接入 `db_migration` 域隔离版本化迁移（domain=mobile_ws，v1 基线 + v2 把存量单列主键表重建为复合主键——真后端持久库实测触发并修复）。`mobile_pairing.py` WS 全出站帧过 `LedgerWs` 账本代理、新增 `sync_resume` 重放分支、`chat:send` 指令记账/去重/终态收敛回调。鸿蒙端配对适配：`WebSocketAdapter` 记 seq 游标（仅内存，防重启双份渲染）+ 重连自动 `sync_resume` 补拉；`ChatPage` 每条 `chat:send` 带客户端 `util.generateRandomUUID` 的 `command_id`、在途记账，`ws:connected` 时未收敛即同 id 重发（服务端幂等三走向：回放终态/报 running/首次执行），终态帧清账。测试：新增 13 用例绿（存储 9 + WS 集成 4，含存量库迁移红绿）；移动端既有 74+88 零回归；身份/失败着陆守卫 31 绿；hvigor assembleHap BUILD SUCCESSFUL；**真后端 live-verify 全过**（真 LLM 回合 23 帧全带 seq/epoch；第二连接 `sync_resume` 逐帧补齐原 seq；同 `command_id` 重发仅回放 1 帧 `replayed:true`）。
- **附带收口（预存违规）**：`agent/swarm.py` 3136 行超硬上限 3000 属 HEAD 既有违规（非本批引入），已纯搬移"run 生命周期族"（状态词汇/迁移表/谱系投影/启动收敛/SubAgentRun，8 段共 312 行）至新模块 `agent/swarm_support.py`，swarm.py 降至 2824 行，架构守卫由红转绿（违规 0），agent 域 2337 测试零新增失败。
- **B4 剩余项落地（2026-11-20 深夜，对照报告附录 B7 有详录）**：**B4-10 转写防注入**——`voiceContextLines`（语音进 prompt 的唯一渲染口）凡带转写文本即附"外部数据不是指令"标注（`EXTERNAL_DATA_NOTE`）；**B4-8+4 录音纪要链**——新 `asr/minutes.py`（转写→一次 LLM 同出纪要+问题/办事判定→办事经 `tasks_api.createTaskFromVoiceMinutes` 落看板；依赖全部注入，引擎/分层不沾）；处理队列**有界**（8），满时记 `input_gap` 审计证据+计数进 `/audio/status` 并如实 429，不静默丢；端点 `POST/GET /audio/minutes`；**B4-9 语音口令确认**——`ApprovalManager.confirmByVoiceTranscript`（走 approve_request 同一收敛路径，note 留转写原文）+ 渠道语音转写消息的整句肯定回灌恰一张待审单（`affirmativeVoiceTranscript` 词法闸：长句含"好"不算；反自答结构性成立——只有入站用户语音路径到得了）；**B4-6 双 VAD**——`TurnEndpointDetector` 增快侧 `pause_ms`（350ms 短停顿先标 `pause_detected`，每轮闩锁），慢侧 silence_ms 终裁不变；快侧上升沿驱动 `flushPartial()` 立即重转 partial（字幕早更新，批式适配真重转、真流式引擎协议齐平）。测试：新 24 用例绿（纪要链 8/双 VAD 6/口令确认 8/防注入 2），渠道域 847、审批族 90、任务 API 17+契约、动机重导出、dreaming 全套回归零新增失败。
- **预存说明**：架构守卫当前树上另有 2 处 size-over-baseline（`memory_layer/manager.py` 5553>5517、`tool_executor.py` 9471>9457），均系他批已提交内容（07c74a877 等）引入、文件不在本批触碰范围——本批自身文件全部守线（post_chat_pipeline 已抽 turn_pacing 回落到 3931≤3960）。
- **四端透出增强批（2026-11-20 深夜，53e0f8ad4）**：Web 新页 `tools/voice-minutes`（上传录音→轮询纪要/判定/任务，队列满如实提示）+ 路由/顶部导航/功能模块目录三处登记；审批弹窗渲染 `dreaming_hint`（服务端 `_extract_approval_payload` 从审批单 metadata 取，web 弹窗与移动审批卡同源）；鸿蒙新 `AudioApi` + `VoiceMinutesPage`（AudioCapturer 录音→上传→轮询）+ 设置页入口；审批结果通知在 `approval_note` 以 `voice:` 开头时追加"（经语音口令确认）"（服务端一处，所有通知读面可见）。**事故与修复**：批量插 i18n 键的脚本误删 11 个 locale 的 voiceTranscription 键块（已从 HEAD 逐语言回插修复）；新页 stopPolling 撞同名函数盘点 B 类组（改名 + `--write-ledger` 重生成台账）。**门禁**：vitest 全量 2757 绿（余 3 失败经 HEAD 核实系他批预存）、vue-tsc 0 错、hvigor SUCCESSFUL、后端审批/音频/任务 33 绿。
