# 四域可靠性修复方案：自我进化引擎 / 检查点回滚 / 肌肉记忆 / 活水上下文池

> **来源**：2026-11-18 四域代码级审计（四路并行只读审计 + 关键强断言现场复核，审计证据附录见 §5）。
> **性质**：修复方案（任务卡制），非准则文档。行号均为 2026-11-18 现场读数，**每张卡开工前须按当时代码现场复核行号与接线状态**；执行一律遵循 AGENTS.md 修复教义：先红后绿、A/B 零新增失败、live-verify 真链路自证、`git commit --only` 逐文件点名。
> **命名约定**：E=进化域（Evolution），K=检查点域（che**K**point/rollback），M=肌肉记忆域（Muscle），SC=活水池增强（沿用 [selfcompact 对照批](../08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md) §9.4 既有编号，避免双套编号）。

---

## 0. 审计结论速查

| 域 | 真实状态 | 核心病灶 | 与仓库自述矩阵（docs/0-index/README.md）的出入 |
|---|---|---|---|
| 自我进化引擎（人格/动机/宪法/反思） | 进化闭环与反思回路**已闭环运转**；宪法/人格/动机三条轨**展示与行为脱钩** | 双轨脱钩（文本轨进 prompt 生效，结构化轨只存不用）+ 死端点谎报成功 | 矩阵 🟡「遗传引擎部分」偏保守，进化/反思本体实为活的 |
| 检查点/回滚 | 五条局部链闭环（工作流检查点重试/批次补偿/工作流版本回滚/会话 fork/parked 续跑）；**会话级与蜂群 run 级恢复机制已写好但恢复侧零接线** | 写入侧先行、恢复侧欠账（无 API/无启动钩子/无前端入口） | 矩阵 ⬜「无实现」偏严——P1-5 CheckpointService 组件与测试齐备，缺的是消费面 |
| 肌肉记忆（ToolMemory 三层） | **已实现闭环**（写 3 真实写点→三层存取落盘→读取裁定→auto_execute→反馈/固化/遗忘/RSI 调参全链贯通，真实数据文件在库） | 审计修复后的收尾瑕疵（双重记账/Skill 失败不记/死读取面/集成 mock） | 矩阵 🟡「L1/L2/L3 部分」**滞后**，应更新 ✅ |
| 活水上下文池 | 完成度约八成：可逆降权+四路召回+压缩纪律全链成立 | SC 系"时机智能"增强已设计待拍板未排产；增长门基线不跨重启；池→记忆蒸馏无通路 | 矩阵 🟡「P1-1 已补齐」基本准确 |

**共性根因**：四域均为"机制先行、消费滞后"——数据模型与写入链路按架构愿景建齐，"读 → 影响行为 / 用户可达"的最后一公里（API 端点、启动钩子、prompt 注入点、默认开关）未同步闭环。修复以**接通消费面或诚实退役**为主，不新造大件。

---

## 1. 批次总览与依赖

| 批次 | 内容 | 优先级 | 依赖 | 需拍板 |
|---|---|---|---|---|
| E1 | 宪法死端点修复（谎报成功） | P0 | 无 | 否 |
| M1–M4 | 肌肉记忆收尾四件（记账单源/Skill 失败入账/死面退役/集成去 mock） | P1 | 无 | 否 |
| K2 | 启动接线：swarm 账本收敛 + ShutdownGuard 装配 | P1 | 无 | 否 |
| K1 | CheckpointService 恢复面（列表/恢复 API + 快照内容补全） | P1 | K2 优先但非硬依赖 | 快照内容范围 |
| K3 | 记忆版本回滚：接线或退役 | P1 | 无 | 接线还是退役 |
| SC-3 → SC-7 → SC-5 | 活水池时机智能第一波（读数/反思对齐/回执指引） | P1 | 无 | 否 |
| SC-1/SC-2/SC-8 | 活水池软抑制三件 | P2 | SC-3 | 否 |
| E5 | 反思 lessons 注入补池分支 + avoid_tool 门灰度 | P2 | 无 | 翻默认灰度 |
| SC-6/SC-4 | 折叠后召回率读数 + 四臂基准 | P2 | SC-1/SC-2 | 否 |
| S6' | 增长门折叠基线跨重启持久化 | P2 | 无 | 否 |
| E2/E3/E4 | 宪法规则接行为 / 动机最小闭环 / 人格特质诚实化 | P2 | E1 | **是**（影响 agent 行为，须先拍板影响面） |
| K4 | 会话"就地回滚"是否建设 | — | — | **是**（纯决策卡） |
| K5 | 蜂群中断 run 续跑（事件账本重建执行上下文） | P3 另立项 | K2 | 是 |
| M5 | 功能矩阵状态更新（肌肉记忆 🟡→✅） | P2 | M1–M4 | 否 |
| S8 | 池→记忆蒸馏 | P3 另立项 | — | 是（按 memory-distillation-plan） |

执行建议：E1、M1–M4、K2 三组互不碰文件域，可并行先行；SC 三件套依次序串行（同一折叠触发面）。

---

## 2. 任务卡

### E1 · 宪法死端点修复（P0，谎报成功必须清零）

- **现状**：`neurova/api/endpoints/agent.py:944-992` 的 `GET/PUT /api/v1/agents/{id}/constitution` 依赖 `agent.get_constitution()/update_constitution()`，Agent 类全仓**无此二方法**（`hasattr` 防御后 GET 恒 `{}`、PUT 静默 no-op 返回成功）。真正生效的宪法注入走 `config.constitution` 字符串轨（`agent_core.py:243,366` → `session_snapshot.py:69-74` 冻结 → `orchestrator.py:1295-1308`）；规则 JSON 轨的读写走 `constitution_router.py:77-148`（挂载于 `/v1/growth`），其唯一后端读方是 `growth.py:324` 展示。
- **改动**：删除 `agent.py:944-992` 旧端点；前端 `NeurUI/src/api/modules/growth.ts` 若有对应旧调用改指 `/v1/growth` rules 通道（先 grep 前端确认调用面）。
- **红灯**：断言 `GET /api/v1/agents/{id}/constitution` 返回 404/410（旧路由退役），且 `/v1/growth` 宪法规则 CRUD 契约测试仍绿；补充"Agent 类不存在 get_constitution 属性"的退役守卫（防复活）。
- **验收**：A/B 零新增；前端宪法编辑页功能不回退（rules 通道读写正常）。

### E2 · 宪法规则接行为注入（P2，**需拍板**：规则生效形态）

- **现状**：rules JSON（`constitution_persistence.py:21-66`）只存不用。
- **方案（二选一，拍板后执行）**：①在 `orchestrator.py:1295-1308` 组装 system_instructions 时，将该 agent 的 enabled 规则编译进宪法段（与 `config.constitution` 同源合流，不造第二注入点）；②判定"规则仅作治理台账"，页面明示不生效。
- **红灯（若选①）**：写规则后，下一轮上下文信封的 system_instructions 含该规则文本；禁用规则不出现。
- **影响面**：prompt 组装面；须评估 token 预算（规则条数×长度设具名上限）。

### E3 · 动机最小闭环（P2，**需拍板**：动机是否驱动行为）

- **现状**：四驱动记录+展示闭环真实（`post_chat_pipeline.py:3023-3083` observe 三路 + `console.py:2364-2375` 点赞 purpose + `growth.py:602-613` 回答回流）；但 `intrinsic_motivation.py:157,338,480,662` 的 `generate_actions()/calculate_intensity()` 全仓零消费方——动机不改行为；主动提问由 QuestionQueue 驱动（`post_chat_pipeline.py:1897-1920` 入队、`:2949-3021` 出队）。
- **方案（拍板后执行）**：**最小闭环**——不新造行为通道，把 purpose/autonomy 强度接进 QuestionQueue 出队调制（强度低→提问频率上限收紧；具名常量）。`generate_actions` 若无消费场景**退役删净**（教义第 6 条），不保留"看起来能驱动行为"的死码。
- **红灯**：强度低时出队间隔≥高强度时的间隔（具名常量可测）；退役面无 import 残留。

### E4 · 人格特质诚实化或接线（P2，**需拍板**）

- **现状**：`personality.md` 文本轨注入生效（`agent_core.py:1336-1341` → `orchestrator.py:1298,1305-1306`）；`personality.json` 特质轨（`personality_persistence.py`）零行为影响；`POST /personality/evolve` 诚实 501（`personality_router.py:101-104`）。
- **方案（二选一）**：①把 communication_style/decision_style 编译进人格段 prompt（同 E2 形态）；②页面与文档明示"特质仅作记录，暂不影响行为"。501 保持诚实形态不动。

### E5 · 反思 lessons 注入补池分支 + avoid_tool 门灰度（P2）

- **现状**：meta lessons 注入只走非池分支（`orchestrator.py:1964` → `builder.py:51`），**默认池分支（use_pool=True，`orchestrator.py:141,1429`）不注 lessons**；avoid_tool 硬门默认关（`tool_executor.py:781-815`，env `NEUROVA_METACOG_GATE`）。
- **改动**：①池分支同样经 `injector._build_metacog_lessons`（`injector.py:340-341,515-540`）注入 lessons 块（预算仍 ≤3 条，`orchestrator.py` 既有口径）；②avoid_tool 门先在测试环境灰度开，收集拦截读数后再拍板翻默认。
- **红灯**：池分支会话的信封含活跃 lesson 文本；lesson 过期后不再出现。
- **注意**：不把元认知信息变成常驻噪声——注入走既有 lessons 块预算，不新增恒定注入面（对照文档 §9.5 第 3 条）。
- **灰度指引 · 开启与观察**：灰度环境经治理设置 `metacog_gate_enabled: true`（或 env `NEUROVA_METACOG_GATE=1`）开门；观察读数＝执行日志「🚦 元认知调控门命中」行 + 工具回执 `metacog_advisory` 字段（命中工具名、教训 finding/recommendation），按日统计拦截次数与误拦率作为翻默认拍板依据。
- **灰度指引 · 回退**：env `NEUROVA_METACOG_GATE=0` 强制关（优先级最高、即时生效），或移除治理设置 `metacog_gate_enabled` 项恢复内置默认关；灰度读数出来前生产默认保持关。

### K1 · CheckpointService 恢复面接通（P1）

- **现状**：`neurova/checkpoints/service.py:26` `CheckpointService`（git 裸仓库 plumbing `repository.py:60`；restore_snapshot `:120`、restore_with_rollback `:181`、diff `:239`、gc `:262`）组件与测试齐备（`tests/unit/checkpoints/test_checkpoints.py`），但**只有写入半条链**：`chat_pipeline.py:3645-3671` `_auto_checkpoint` 每轮防抖写，快照内容缩水（仅 user_input/reply/trace_id/turn 四字段，`kb_files={}` 空置）；恢复侧生产调用为零、无 API。
- **改动**：
  1. 新增 `GET /api/v1/agents/{agent_id}/checkpoints`（列 refs，读 `refs/{auto,snap,pre-restore}/…`）与 `POST /api/v1/agents/{agent_id}/checkpoints/{ref}/restore`（调 `restore_with_rollback`，admin/owner 门）；
  2. 快照内容补全：session_data 纳入会话 messages 历史（从 session_manager 读）；`kb_files` 与知识库子系统接线，或显式删除该参数并在注释写明（二选一，不许悬空）；
  3. 前端 Agent 详情页增"检查点"折叠面板（列表+恢复按钮+确认弹窗）。
- **红灯**：先造两轮对话→列检查点≥1→恢复到旧 ref→会话状态回到旧点（messages 断言）；恢复后再造新消息，pre-restore 快照存在。
- **风险**：恢复语义=整体替换会话状态，须在响应中明示；恢复前 pre-restore 自动留档已有（service.py:120）。

### K2 · 启动接线：swarm 账本收敛 + ShutdownGuard 装配（P1，小改高收益）

- **现状**：①`swarm.py:196-211 replayRunTailStatus` / `swarm.py:1096-1122 reconcileRunFromEvents` 已实现有测试，但生产启动流程零调用（台账级 `agent_run_store.py:219 reconcile_at_startup` 已接线，但它只收敛 SQLite 台账，不重放事件账本校正内存 run）；②`recovery/shutdown_guard.py` 已实现有测试，`app.py:68` 仅 `self.shutdown_guard = None` 槽位，生产启动未 import `neurova.recovery`。
- **改动**：①app 启动钩子（`_on_startup` 链）调用 swarm 收敛入口：对台账中仍 running 的 run 逐个 `reconcileRunFromEvents`，把账本末态写回台账（running→failed(process_died) 口径与 `reconcile_at_startup` 一致，避免双源打架——以台账 reconcile 为主、账本只作校正证据）；②`app.py:68` 槽位装配真 `ShutdownGuard`（按其现有 prepare_startup/recover_from_sessions 契约）。
- **红灯**：伪造"台账 running + 账本末态 failed"的 run → 启动后台账判 failed(process_died)；伪造未落盘会话 → ShutdownGuard 恢复路径被调用。
- **注意**：只做**状态收敛**（与 CoworkOS"恢复只重驱 queued 项"边界一致），不做 run 复活续跑（那是 K5）。

### K3 · 记忆版本回滚：接线或退役（P1，**需拍板**）

- **现状**：`cognitive_layers/memory_layer/version_control.py:409-445 rollback_to_version` 全仓零生产调用、零暴露；`post_chat_pipeline.py:2872-2939 _step_version_snapshot` 每轮为 recall 到的 ≤3 条记忆写"可回滚保障"快照——**快照在积累，回滚永不发生**（只写不读，违反教义第 5 条的断点判定）。
- **方案（拍板二选一）**：①接线——新增 `POST /v1/memory/{memory_id}/rollback?version=` 端点（owner 门），或接进记忆管理页"历史版本"面板；②退役——删 `_step_version_snapshot` 写入步与 version_control 的 rollback/history/compare 面（含测试）。不许维持只写不读。

### K4 · 会话"就地回滚"决策卡（**纯拍板，不实施**）

- **现状**：会话级面向用户的"回退"只有 fork-by-copy（`console.py:2415-2470` 按 until_timestamp 截取复制到新会话）+ 消息 checkpoint 锚点（`console.py:2480-2504`，metadata 布尔标记，配合前端 forkFromMessage）。
- **决策点**：是否需要"原会话就地回滚到历史点"。**建议不建**：fork 已覆盖"回到某点重来"场景，且不破坏消息不可变性与审计链；就地回滚会引入"历史被改写"的审计/同步问题（多端 WS、蜂群引用会话）。若拍板要建，走 K1 的 CheckpointService restore 通道而不是新造机制。

### K5 · 蜂群中断 run 续跑（P3，另立项，**需拍板**）

- **现状**：事件账本（`swarm_event_log.py:35-75`）只有状态与摘要、无任务载荷；`agent_run_store.py:24` 明示"不自动跨重启续跑"；cancelRun（`swarm.py:1526-1602`）落终态不回滚副作用；`updateSubagent mode=restart` 是重派不是回滚。
- **立项边界**：从 TaskUnit 声明 + 台账行 + 事件账本重建执行上下文，**只重驱 queued/blocked 项**（CoworkOS 同款边界），已完成项不重跑；副作用补偿不在本期（依赖 build_mode 批次补偿既有通道）。开工前先出独立方案。

### M1 · 肌肉记忆记账单源（P1）

- **现状**：自动执行成功对同一指纹**双重记账**——`on_tool_executed`（`tool_executor.py:9107-9227`）与 `chat_pipeline._record_tool_outcome → _record_muscle_memory_outcome`（`chat_pipeline.py:1419-1450`）各记一次 `record_usage`，`consecutive_successes` 一次成功 +2；配合 `_PROMOTE_THRESHOLD=2`（`muscle_memory.py:178`），L3 新条目**一次成功即升 L2**，固化阈值被稀释。
- **改动**：保留 `on_tool_executed` 统一咽喉为唯一记账点；`_record_muscle_memory_outcome` 降级为仅记 RSI 反馈面（`get_feedback()`），不再调 `muscle_memory.record_usage`（或整段删除，以现场双写证据为准）。
- **红灯**：同一次 auto_execute 后，`consecutive_successes` 恰 +1；新 L3 条目需**两次**独立成功才升 L2。

### M2 · Skill 失败入账（P1）

- **现状**：`agent_core.py:1572-1627 _on_skill_post_execute` 在 `:1589` 对失败结果提前返回——Skill 失败不进肌肉记忆/降级链（常规工具失败经 finally 统一进）。
- **改动**：失败也调 `on_tool_executed(..., success=False)`（走既有失败降级与权重反馈链）。
- **红灯**：Skill 失败后，对应工具的 muscle 记录 failure_count+1、自适应乘数下降（`tool_executor.py:9144-9155` 链路可测）。

### M3 · 肌肉记忆死面退役（P1）

- **现状**：①`mem_core.py:567-573` `muscle_memory` 属性是从未被生产代码赋值的死读取面（真实句柄是 `tool_memory.muscle_memory`）；②`chat_pipeline` 侧 `builder.py:475-492 _merge_tool_memory` 消费 `check_tool_memory` 返回中**不存在的 `memories` 键**——空转支路；③`tool_executor.py:1220-1281 execute_from_memory_async` 无生产调用方。
- **改动**：按教义第 6/7 条逐一退役（属性、空转合并支路、死方法），清理测试引用；先比后合——若 `execute_from_memory_async` 有规划中消费场景，登记另议，不在本批硬删。
- **红灯**：退役守卫测试（find_spec 断言/属性不存在断言），参照 `test_neuhebb_retired.py` 形态。

### M4 · 集成层去 mock（P2）

- **现状**：`tests/integration/test_main_system_loop.py:72` 把 `check_tool_memory` mock 掉——端到端"真实输入→自动执行→回流"未在 CI 级全真验证。
- **改动**：补一条全真集成用例（真实 ToolMemoryIntegration + 真实 muscle_memory 临时目录）：录入→命中→auto_execute→回流固化。
- **验收**：集成套件零新增失败；用例含固化层级断言。

### M5 · 功能矩阵状态更新（P2，依赖 M1–M4 合并）

- **改动**：`docs/0-index/README.md` 功能矩阵"肌肉记忆（ToolMemory 三层）"🟡→✅，备注三层闭环证据（本方案 §5 审计锚点）。

### SC-3 · 折叠时机判读暴露（P1，零风险读数）

- **现状**：`context_status` 工具（`builtin_tools.py:88-94`）只有盘点读数，模型不知道"当前该不该折"。
- **改动**：`context_status` 回执增"折叠时机判读"块：增长门当前判定（`fold_trigger.decideFoldTrigger` 的四判据读数：占用/增量/增量消息数/可折质量）+ 元认知状态（未编译事件数、距上次反思轮数、活跃 lesson 计数——读 MetaLedger 现成面）。
- **红灯**：判读块字段齐备且与触发器判据同源（不造第二套判定）；超预算时有界截断。
- **注意**：只走模型主动查询面（工具回执），不进信封恒定注入（对照文档 §9.5 第 3 条）。

### SC-7 · 反思节律对齐折叠（P1，本仓独有结构感知触发）

- **现状**：折叠触发只有 token 维度（`fold_trigger.py:103-158`）；反思编译完成（`self_model.reflect`，`post_chat_pipeline.py:3492-3514` 每轮 `reflect_due`）这一"段落完成"信号未接入。
- **改动**：反思编译完成后，将"已编译事件对应的更早消息"纳入下一轮折叠候选（仍过增长门与池归档，不越硬水位；边界锚点保留规则同 SC-1 软抑制形态）。
- **红灯**：反思触发后的下一轮折叠候选集含反思覆盖区间的消息；未反思时不含（防误折）；严格变小守卫照常生效。
- **注意**：折叠/召回统计与 MetaLedger 反思证据必须是两条账——折叠状态不进反思输入（对照文档 §9.5 第 2 条）。

### SC-5 · 折叠回执带召回指引（P1）

- **现状**：`context_compress` 回执（`tool_executor.py:5799-5815`）未附被折区间的池引用与找回路径——折叠后模型不知道"去哪找回"，池回读面利用率上不去。
- **改动**：回执附结构化提示：被折区间的池引用（covers_ref/消息 hash 段）+ 三条找回路径（`recall_history` 精确直取 / `pool_search` 语义检索 / `recall_context_span` 下钻）。
- **红灯**：执行 context_compress 后回执含 covers_ref 且用 recall_context_span(covers_ref) 能取回被折区间内容（往返闭环）。

### SC-1/SC-2/SC-8 · 软抑制三件（P2，依赖 SC-3）

- **SC-1 任务相位抑制**：`fold_trigger.py` 增相位判据——run 生命周期读 `agent_run_ledger`（权威源），"子任务进行中"时折叠只取区间尾部、保留推导边界锚点（最后一条消息/当前工具调用对）在视图，其余照常入池。
- **SC-2 卡住抑制**：命中条件 = 活跃 avoid_tool 教训（`self_model.check_tool_advisory`）∨ 工具滑动失败率超阈（`MetaLedger.tool_success_rates`）——接现成元认知读数，不新造卡住检测器。
- **SC-8 活跃教训保护**：compression_doctrine 的 KEEP 面增加——活跃 lesson（未过期、PENDING/VALIDATED）引用的原文消息折叠时豁免或降档。
- **红灯**：相位命中时边界锚点仍在视图；卡住命中时该轮不触发自动折叠；活跃 lesson 引用消息在 KEEP 面命中。
- **注意**：三者都是"优先级建议"不是"替代门"——增长门 token 判据仍是安全底线（对照文档 §9.5 第 1 条）。

### SC-6/SC-4 · 召回率读数与四臂基准（P2，依赖 SC-1/SC-2）

- **SC-6**：把 CompressionEvent（折叠时点、区间 hash 集）与抽屉命中账本（B13 八计数）关联，产出"折叠后 N 轮内区间被召回比率"——折叠时机质量量化指标。影响面：`fold_trigger.py`/`orchestrator.py` 折叠事件、`semantic_drawer.py` 命中埋点、`budget_report.py` 聚合。
- **SC-4**：四臂基准（固定间隔 / 增长门 / 增长门+相位抑制 / 增长门+前移触发），读数新增"折叠后 N 轮召回率"与"中途截断次数"；激进臂只做实验臂不转默认（无数据不转正）。

### S6' · 增长门折叠基线跨重启持久化（P2）

- **现状**：折叠基线（`last_fold_tokens/msgs`、covered 集、冻结头缓存）存编排器内存折叠槽（`orchestrator.py:2840-2887`），进程重启后归零重算（层索引因 SUMMARY 落台账仍可跨重启寻址，`context_pool.py:1456-1498`；冷却状态机已随时间线持久，`context_pool.py:214-235`）。
- **改动**：把折叠基线并入 CompressionEvent 时间线（复用冷却重建模式 `rebuildCompactionCooldown`），重启后重放恢复。
- **红灯**：折叠→重启（重建）→增长门不因基线丢失而立即重复折叠。

### S8 · 池→记忆蒸馏（P3 另立项，**需拍板**）

- **现状**：池折叠内容与长期记忆写入无机制化通路（长期记忆写原始 user_input/reply，`post_chat_pipeline.py:1482-1561`；memory_admission/memory_ingest 无 pool 引用）。
- **去向**：按 `docs/04-plans/2026-11-18-memory-distillation-plan.md` 推进；**注意** MEMORY.md 共编通道已退役（c132f7d64，蒸馏回写改道温度体系），不得复活。

---

## 3. 明确不做 / 防扩 scope

0. **与 QwenPaw 批不立项清单的关系**：QwenPaw 批"已对齐不立项清单"含"检查点"，指的是**不照搬 QwenPaw 的检查点形态**；本方案 K1/K2/K3 不引入任何新机制，只接通本仓**既有** P1-5 CheckpointService / ShutdownGuard / MemoryVersionControl 的消费面（修的是"只写不读"断链，不是新建平行体系）。
1. **不建第二套检查点机制**：会话恢复一律走 P1-5 CheckpointService 既有 git-plumbing 通道；K4 若拍板建就地回滚也复用它。
2. **不自动跨重启续跑 run**（K5 立项边界之外不做）：与 `agent_run_store.py:24` 既有声明一致。
3. **不做动机→自主行为的直接驱动**（E3 只做提问频率调制）：动机不改工具选择/回复内容，防不可控自主性。
4. **不为压缩扩教训注入预算**：lessons 仍 ≤3 条（对照文档 §9.5 第 3 条）。
5. **不复活已退役面**：NeuHebb、MEMORY.md 蒸馏通道、破坏性 drain 均有退役守卫，不得回退。
6. **SC 激进触发臂不转默认**：前移触发以 SC-4/SC-6 数据为准，无数据不转正。

---

## 4. 交付定义（每张卡相同）

①红灯测试先行并实证真红 → 最小实现转绿；②目标套件全绿 + 相关域 A/B 零新增失败（失败集合与基线逐行比对）；③live-verify 真链路证据（命令+输出原文）写入提交说明；④`git commit --only` 逐文件点名（新文件先 `git add`），中文 Conventional Commits，正文含动机/根因/去向与 `净 LOC：生产池 +N/−M`；⑤本方案文档执行记录段补一行（commit 号+一句话结果+偏差）。

---

## 5. 审计证据附录（file:line 快查，2026-11-18 读数）

**进化域**：装配 `start_server.py:108-141`、`agent_core.py:757-781,1467-1505`；经验链 `post_chat_pipeline.py:944-988,2108-2131` → `evolution_facade.py:191-227` → `closed_loop.py:570-650`；遗传消费 `post_chat_pipeline.py:2468-2618`；工具选择过滤 `orchestrator.py:1141-1155` → `closed_loop.py:453-514`；默认关 `evolution_settings.py:68-71`、`closed_loop.py:936-972`。宪法死端点 `agent.py:944-992`（已复核 Agent 类无 get/update_constitution）；规则读方仅 `growth.py:324`。人格 501 `personality_router.py:101-104`。动机零消费 `intrinsic_motivation.py:157,338,480,662`；QuestionQueue `post_chat_pipeline.py:1897-1920,2949-3021`。反思回路 A `post_chat_pipeline.py:1818-1852,1955-1978` + `growth_log.py`；回路 B `self_model.py:63-70,56` → `ledger.py:81-106` → 注入 `injector.py:340-341,515-540`（仅非池分支 `orchestrator.py:1964`）；avoid_tool 门 `tool_executor.py:781-815`。

**检查点域**：P1-5 组件 `checkpoints/service.py:26,120,181,239,262` + `repository.py:60`；写入半条链 `chat_pipeline.py:3645-3671`（内容缩水 4 字段、kb_files 空）；恢复零调用。记忆版本控制 `version_control.py:409-445`（rollback 零调用）+ 每轮写快照 `post_chat_pipeline.py:2872-2939`。swarm 账本 `swarm_event_log.py:35-75`；重放/校正 `swarm.py:196-211,1096-1122`（生产零调用，已复核）；台账启动收敛 `agent_run_store.py:219,533`（在）。ShutdownGuard 槽位 `app.py:68`（未装配，已复核）。已闭环五链：neurflow 检查点 `execution_engine.py:364-377` + `neurflow_api.py:1791,1809`；批次补偿 `batch_compensate.py:18`；工作流回滚 `collaboration/neurflow/storage.py:672-702`；fork `console.py:2415-2470`；checkpoint 锚点 `console.py:2480-2504`；parked 续跑 `console.py:1399` + `agent_run_store.py:393-411`。

**肌肉记忆域**：三层定义 `muscle_memory.py:108-167`；存储落盘 `:789-850` + `agent_core.py:577-580`（真实数据 `data/default/memory/muscle_memory/`）；写点 `tool_executor.py:1861-1895,9107-9227`、`agent_core.py:1572-1627`（失败提前返回 `:1589`）、`chat_pipeline.py:1324-1384,1419-1450`；读取裁定 `chat_pipeline.py:956,1297-1322` → `tool_memory_integration.py:313-393,446-480`；prompt 注入 `orchestrator.py:1731-1751`；固化/遗忘 `muscle_memory.py:178,543-587,589-642` + 维护触发 `tool_memory_integration.py:236-248`；RSI 参数面 `rsi/integration_manager.py:51,292`；双重记账 `chat_pipeline.py:1419-1450`；死读取面 `mem_core.py:567-573`；空转 `builder.py:475-492`；NeuHebb 已退役（`agent_core.py:1434-1436` 注释 + 守卫 `tests/unit/memory/test_neuhebb_retired.py`）。

**活水池域**：注入咽喉 `context_pool.py:538,865-885`；折叠触发 `fold_trigger.py:62-158`；S6 触发 `context_pool.py:48` + `chat_pipeline.py:3126-3168`；软目标 `swarm.py:104-108`；冷却 `context_pool.py:169-235` + `chat_pipeline.py:3274-3328`；四路召回 `tool_executor.py:5593-6026` + `context_pool.py:1303-1387,1555-1668,2014-2038`；被动抽屉 `context_pool.py:1967-2012` + `orchestrator.py:3010-3049`；有界投影 `chat_pipeline.py:2993-3038` + `tool_executor.py:158-213`；持久台账 `eviction_ledger_db.py:4,428,458-467`；基线内存槽 `orchestrator.py:2840-2887`；context_compress 回执 `tool_executor.py:5799-5815`；context_status `builtin_tools.py:88-94`。

**测试基线参考**：`tests/unit/checkpoints/test_checkpoints.py`、`tests/unit/agent/test_run_status_transitions.py`、`tests/unit/memory/test_shutdown_guard.py`、`tests/execution_engine/test_tool_closed_loop.py`、`tests/unit/memory/test_muscle_memory_closed_loop.py`、`tests/unit/agent/test_context_compact_discipline.py`、`tests/unit/agent/test_compaction_cooldown_soft_target.py`、`tests/unit/context/`（折叠族 14 文件）。

---

## 执行记录（按卡补记）

| 卡 | commit | 结果 | 偏差/移交 |
|---|---|---|---|
| E1 宪法死端点 | `74fcfc0ff` | 退役 `agents/{id}/constitution` 谎报成功端点（生产池 +0/−58）+ 退役守卫 3 用例；live-verify 旧路由 404、/v1/growth 规则 CRUD 闭环 | 前端 grep 证实零旧调用，未动 |
| M1 记账单源 | `09f1e6139` | 删 `_record_muscle_memory_outcome` 双重记账，`on_tool_executed` 唯一记账点；一次自动执行连击恰 +1、两次独立成功才升 L2（+10/−27） | — |
| M2 Skill 失败入账 | `a5945f3b8` | `_on_skill_post_execute` 失败分支补调 `on_tool_executed(success=False)` 接通降级/权重链（+21/−0） | — |
| M3 死面退役 | `d7bf606f8` | 删 `mem_core.muscle_memory` 死属性、`builder._merge_tool_memory` 空转支路、`execute_from_memory_async`（grep 证零生产调用）+ 守卫（+11/−101） | — |
| M4 集成去 mock | `3e3bbd423` | 新增肌肉记忆三层全真链路集成用例（写入→命中→auto_execute→回流→固化→重载） | 既有 mock 用例保留 |
| M5 矩阵更新 | `87f640b9d` | 功能矩阵肌肉记忆 🟡→✅，落点修正为实际实现文件 | — |
| K2 启动接线 | `bd86bd992` | `reconcileSwarmRunsAtStartup` 接启动链（账本末态校正、只收敛不复活）+ ShutdownGuard 真装配 + 优雅关停刷缓冲（+131/−6）；live-verify 强杀→二次启动识别异常关停并恢复 | — |
| K1 检查点恢复面 | `27c2145c4` | `GET .../checkpoints` + `POST .../checkpoints/{ref}/restore`（事务化恢复+确认门+属主门+审计）+ 快照内容补全（messages 全量，kb_files 悬空参数删除）（+298/−6）；live-verify 16/16 | 前端检查点面板移交（挂点/鉴权就绪） |
| K3 记忆回滚接线 | `ddd4d86bc` | `GET /v1/memory/{id}/versions` + `POST .../rollback`（沿用 rollback_to_version 语义+审计单源）；附带修 version_id 毫秒撞号（+220/−2）；live-verify 14 项 | 前端版本时间轴移交；拍板=接线 |
| K4 就地回滚 | — | 决策卡：**不建**——fork-by-copy 与检查点恢复已覆盖，避免历史改写破坏审计链 | 如需再议，走 CheckpointService 通道 |
| K5 蜂群 run 续跑 | — | 另立项（本方案不含）：从 TaskUnit+台账+事件账本重建执行上下文，只重驱 queued/blocked | 开工前须独立方案 |
| SC-3 时机判读 | `731186598` | `context_status` 回执增 `fold_timing` 判读块（内部直调 `decideFoldTrigger` 零第二套判据）+ 元认知六字段（+259/−16）；live-verify 9787 | — |
| SC-7 反思对齐折叠 | `1ae111871` | MetaLedger 只读游标 + 反思水印 + 对齐预算帽（只加深不放宽）（+183/−2）；live-verify 真管线水印咬合 | — |
| SC-5 回执召回指引 | `7341b1bd6` | `context_compress` 回执附 covers_ref 三路径指引，live-verify 往返逐字取回（+75/−2） | 甄别出 P3-9 去重×T-11b 索引交互（既有，另记） |
| SC-1/2/8 软抑制 | `232d95b0c` | 相位锚点软抑制（run 生命周期只读信号）/卡住抑制（活跃教训∨失败率，阈值具名可调）/活跃教训 KEEP 保护（doctrine 1.0.0→1.1.0）（+365/−2）；live-verify 卡住命中不折、对照立即折 | — |
| S6' 基线跨重启 | `ad567c654` | 折叠基线随 `fold_baseline` 时间线事件持久化、建槽即重放、手动 /compact 同批落盘、fail-open（+131/−0）；live-verify 重启后不重复折叠、挪走时间线对照立即折叠 | — |
| SC-6 召回率读数 | `89c6f2967` | 折叠事件×召回命中单源关联账本 + `/metrics` `fold_recall` 只读面 + 跨重启时间线重放恢复分母（+375/−1）；live-verify 比率 0→0.1429 | 直取类召回不经抽屉，比率为下界（已注明） |
| SC-4 四臂基准 | `f52ce3eaf` | 四臂对照框架+读数（臂3 相位抑制召回率 0.38 最高、臂4 前移峰值最低 5142；+106/−35）；**激进臂仅实验臂，转正须另行拍板** | — |
| E3 动机最小闭环 | `939822481` + `51f47bcbc` | 强度调制接出队点（具名间隔表，读 MotivationLedger.snapshot 单源）+ `generate_actions` 等行为生成死码退役 −496 行+守卫；live-verify 高/低强度出队频率差 | 收割点接线由 E5 件2 清偿 |
| E5 反思/动机/门三件 | `082399ffa` + `e6a0a2f67` + `557d3f4c2` | lessons 补池分支（复用唯一选取入口）+ 动机调制补接收割点（import 复用纯函数）+ avoid_tool 门两态验证与本卡灰度指引（生产默认保持关） | — |
| E2 宪法规则接行为 | `e6edef924` | `compileConstitutionRulesSection()` 编译口（上界 20 条/500 字符诚实截断）经 session_snapshot 与三件套同点冻结、组装点与字符串轨合流（+102/−2）；live-verify budget 读数字节级吻合 | 期间分支被 rebase，哈希随之更新、内容已核验 |
| E4 人格特质接行为 | `07c3e751b` | `compilePersonalityTraitsSection()` 同形态进人格段（上界 12 条/2000 字符）（+91/−3）；live-verify 同法实证 | `/personality/evolve` 501 诚实桩保留 |
| S8 池→记忆蒸馏 | — | 另立项：按 [2026-11-18-memory-distillation-plan.md](2026-11-18-memory-distillation-plan.md) 推进；红线=不复活已退役的 MEMORY.md 通道 | — |

**总收口**：四域方案可执行卡全部完成，共 23 笔提交落地本地 main（未 push）；每笔先红后绿、相关套件 A/B 零新增失败、live-verify 真链路自证；共享工作树多会话并行以文件域互斥 + `--only` 点名 + 必要时过滤 patch 精确暂存共处，全程零撞车事故。
