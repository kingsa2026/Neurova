# 多 Agent 协作断点修复计划

> 日期：2026-11-21 · 状态：**已拍板并实施完毕（2026-11-21，十四卡全绿）**
> 来源：[多 Agent 协作实现路径分析报告](../05-reports/2026-11-21-multi-agent-collaboration-implementation-analysis.md) §11 断点与风险清单（六路并行代码级核读产出）
> 纪律：每卡按修复教义执行——先红后绿（红灯测试实证缺陷）→ 最小实现转绿 → A/B 零新增失败 → live-verify 真链路 → `--only` 逐文件提交；净新增 LOC 默认 ≤0（测试不计）。

---

## 0. 与既有计划的关系（防重复立项）

| 本计划卡 | 既有计划重叠 | 处理 |
|---|---|---|
| M5 事件库读面消费与周期清理 | `2026-11-21-reference-ac-catchup-implementation-plan.md` A2 卡（**已实施**：全局 seq/重放/快照降级/pruned-through/双写镜像） | **不重做 A2**。本卡只补两件 A2 未含的事：生产读面消费接线 + 周期 prune 任务接线 |
| 候选板重启可查 | `2026-11-21-reference-ab-borrowable-mechanisms-plan.md` P2-3（**已实施**：H-4 重放投影） | 不立项。仅存「投影不含正文」的已知边界，随 M7 多副本拍板一并考虑 |
| 蜂群图投影/契约钉子 | reference-ab P1-1/P2-4（**已实施**） | 不立项 |
| 外部成员验收判定通道 | reference-ab P1-2（**已实施**） | 不立项 |

---

## 1. 现状锚点（问题证据，均经代码核实）

| # | 问题 | 证据（file:line） |
|---|---|---|
| P0-1 | 房间自由文本批准不回灌治理 | `neurova/agent/approval_chain.py:1187-1205`（handleRoomSwarmReply 只调 decideSwarmApproval）vs `neurova/api/endpoints/collaboration_room_api.py:229-251`（显式端点双回灌）、`neurova/tool_executor.py:2793-2814`（工具路径双回灌） |
| P0-2 | MCP 身份缺省回落 admin | `neurova/api/endpoints/mcp_ontology_server.py:110-120`（_currentUserFromContext state 读取失败→role=admin） |
| P0-3 | API-key 租户硬编码 default | `neurova/api/endpoints/mcp_ontology_server.py:78`；`neurova/core/api_key_manager.py:31-59`（APIKey 无 tenant_id 字段） |
| P0-4 | L2 审批通道故障即放行 | `neurova/agent/swarm.py:1674-1677`（_approveMerge 返回 `True, "approval_channel_unavailable"`） |
| P1-5 | 进程内状态多副本会裂 | candidate_merge.py（内存板）、approval_chain.py:922-924（pending 索引）、tool_executor.py:3573-3590（room_post 限频字典）、teams_api.py:239（待批登记） |
| P1-6 | swarm_events 读面无生产消费 + 无周期清理 | `neurova/agent/swarm_event_store.py:193-306`（replayThrough/pruneCovered 仅测试消费）；`neurova/agent/swarm.py:1240-1243`（仅写侧镜像） |
| P1-7 | /external-agents/status 空壳 | `neurova/api/endpoints/external_agents_api.py:130-140`（找 poolStatus、池只有 stats()，process_pool.py:320-332） |
| P1-8 | lineage tenant/room 维度只写不读；member_chunk 纯留痕 | `neurova/agent/swarm.py:3637`、`swarm_support.py:73-113`；读侧仅消费 parent/depth |
| P2-9 | 泵线程同步等审批阻塞帧派发 | `neurova/agent/neuacp/acp_member.py:188-231`（future.result 同步等） |
| P2-10 | 池满 acquire 无超时 | `neurova/agent/neuacp/acp_executor.py:256`（未传 waitTimeout） |
| P2-11 | 成员声明侧未过滤；TEAM 可见性占位 | `neurova/context/orchestrator.py:4159`；`neurova/collaboration/collaboration_isolation.py:1271-1274` |
| P2-12 | 前端四小项 | `NeurUI/src/pages/CollaborationRoomPage.vue`（升级只读/审批后仅 toast）、`api/modules/collaborationRoom.ts:225-229`（getRoomSwarmPending 零消费）、`collaborationRoom.ts:259-264`（去重过宽） |
| P2-13 | 文档/心智债 | `neurova/tool_executor.py:1439`（docstring 含已拆 ToolEngine 档）；team.py 与 SwarmManager 双抽象并存 |

---

## 2. 拆卡

### 批一 · P0 语义一致性与权限面（建议即办）

#### M1 房间自由文本批准补齐治理回灌

- **问题**：群主在房间聊天里回「同意」，审批单变 approved，但团队沉淀/项目治理数据不落地；同一裁决在显式端点/工具路径有回灌、在自由文本路径没有——同一裁决两种效力。
- **根因处修复**：`handleRoomSwarmReply` 批准分支补调 `applyTeamProposalDecision` 与 `applyProjectGovernanceDecision`（带 `decidedByChannel="room"`），与 `decide_room_approval` 端点行为对齐；回灌函数经惰性 import 防循环依赖（approval_chain 已有同款先例）。
- **影响面**：`neurova/agent/approval_chain.py`；房间聊天批准语义变化——批准即生效（此前只改状态）；团队/项目治理面新增一条 room 渠道来源。
- **红灯**：构造 swarm 审批单（metadata.source="swarm"、kind=team_consolidation/project_governance）+ 房间群主身份文本「同意」→ 断言 `applyTeamProposalDecision`/`applyProjectGovernanceDecision` 未被调用（现状红）。
- **绿灯**：同一场景两回灌均发生且 `decidedByChannel="room"` 落审计；驳回路径不回灌（与端点口径一致）。
- **验收**：单测转绿 + 全量 A/B 零新增 + live-verify（真后端建单→房间文本批准→查团队/项目数据落地与审计事件）。

#### M2 MCP 身份缺省改 fail-closed

- **问题**：MCP 两个面的身份解析在 state 读取失败时回落 `role=admin` 的 service 视角——身份通道断裂时以最高权限执行，与全仓 fail-closed 纪律相悖。
- **根因处修复**：`_currentUserFromContext` 缺省分支改为返回身份缺失并让调用方 401/结构化拒绝；service-token 面保留显式 token 校验路径（token 在即有身份，无需缺省）。
- **影响面**：`mcp_ontology_server.py`（本体面四工具壳 + agent-tools 只读面共用解析）；管理面探测脚本如依赖「无身份也可读」需同步调整。
- **红灯**：无任何凭据调用 `/v1/mcp` 工具 → 现状以 admin 身份执行（红）；改后断言 401/identity_missing。
- **绿灯**：三种显式凭据（service token / API-key / JWT）行为不变；无凭据一律拒。
- **验收**：单测 + live-verify（无凭据 curl 得 401；JWT 正常）。

#### M3 API-key 租户策略收口（**含待拍板**）

- **问题**：API-key 身份恒 default 租户、恒 role=user。当前 MCP 面用它查 default 租户数据——等价于把 default 租户数据面开放给任意 API-key 持有者；且无法支撑多租户。
- **选项与影响面**：
  - **甲（最小收口，推荐）**：API-key 身份在 team/project/memory 等租户敏感工具面明确限定 default 租户自身数据（现行为成文）+ 文档标注「API-key 仅适用单租户部署」；多租户场景必须用 JWT。改动小、不破兼容。
  - **乙（schema 扩展）**：APIKey 增 tenant_id 字段 + 签发面选项 + 校验点接入。能力完整但动表、动签发、动校验，涉及迁移。
- **推荐**：甲先落（把隐式行为变显式契约 + 守卫钉住），乙按多租户商业化节奏另批。
- **红灯**：API-key 调 `team_list` 时构造非 default 租户团队 → 断言不可见（若现状已不可见则本卡降级为「契约成文+守卫」）。
- **待拍板**：D-M3 甲/乙。

#### M4 L2 审批通道故障改 fail-closed

- **问题**：`_approveMerge` 在审批基础设施抖动时返回 `approval_channel_unavailable` 并放行合入——L2「强制人工」语义被基础设施故障豁免。
- **根因处修复**：通道不可用时对需要人审的分级（L2，及 interactive 模式下的 L1）**不放行**：候选保持 submitted、run 转 `failed(merge_approval_unavailable)` 或维持等待态（取等待态，避免误杀可重试场景——审批链 waiter 本有 300s 预算，超时另有处置），只有确认审批单**被拒绝**才否决。L0 自动放行路径不受影响。
- **影响面**：`neurova/agent/swarm.py` `_approveMerge`；相关测试桩。
- **红灯**：mock 审批链抛「通道不可用」+ L2 单 → 现状合入成功（红）。
- **绿灯**：同场景候选保持待批/run 不判 completed；审批恢复后可继续裁决；L0 行为不变。
- **验收**：单测 + A/B + live-verify（停审批依赖→L2 合入被阻→恢复后裁决生效）。

### 批二 · P1 可观测与多副本韧性

#### M5 swarm_events 生产消费与周期清理接线

- **问题**：A2 卡已落地全局事件库能力（seq/重放/快照降级/pruned-through），但生产无读面消费、无周期 prune——事件库无限增长，重放能力空转。
- **修法**：① 读面消费：swarm 会话断线重连链路接 `replayThrough`（对齐 mobile 侧 `resolveResumeMode` 的 pruned/ahead/budget→snapshot 决策语义，游标过旧诚实下发快照）；② 清理：`addSystemJob` 周期调 `pruneCovered`（保留窗沿用 A2 拍板值 1 天），先发布 pruned-through 再删。
- **影响面**：`neurova/agent/swarm.py`（_logRunEvent 镜像处不动）、`neurova/api/app.py`（job 注册）、会话同步重连路径。
- **红灯**：构造超窗事件 + 触发 prune job → 断言库大小受控且 pruned-through 边界已发布；重连用例中断言走 replay 而非全量快照。
- **待拍板**：D-M5 保留窗天数（默认沿 A2 的 1 天）。

#### M6 /external-agents/status 接真实池水位

- **问题**：端点找 `poolStatus`，池只有 `stats()`，恒返回占位 note——管理面看不到真实池水位（进程数/排队/空闲/崩溃踢出）。
- **修法**：端点改调 `pool.stats()` 并透出真实字段（pool_key 维度计数 + 全局上限）；无池时诚实返回 disabled。
- **红灯**：池内放 2 个假活动件 + 上限 4 → status 断言出现真实计数（现状恒占位，红）。
- **影响面**：`external_agents_api.py`、前端 TeamPage 状态卡读数字段（字段名保持兼容则前端零改）。

#### M7 多副本约束显性化（**含待拍板**）

- **问题**：候选板/审批 pending/room_post 限频/团队待批均为进程内存，多 worker/多副本下会裂；当前无任何部署约束声明。
- **选项**：
  - **甲（推荐，短期）**：部署文档明示「编排面单副本约束」+ 启动时检测多实例同数据根并 WARNING 留痕；限频窗口迁 SQLite（与 tool_call_journal 同款轻量表）消除最实际的绕过面。
  - **乙（长期）**：候选板/审批 pending 迁 SQLite 单源（判定权随库），或引入共享存储。改动大，按多副本刚需另批。
- **推荐**：甲。乙在无多副本部署需求前不立项（不为假设需求加复杂度）。
- **待拍板**：D-M7 甲/乙。

#### M8 台账只写不读项处置

- **问题**：`lineage.tenant_id/room_id` 无读面聚合；`member_chunk` 纯留痕；`NEUROVA_REQUEST_ARCHIVE_FULL` 钩子无消费。
- **修法**：member_chunk 保留（低成本、账本完整性有用）但补一个读面消费者（subagent 事件读面增加 chunk 统计摘要）或明确登记「留痕不消费」；lineage 聚合做 admin 审计读面（按租户/房间过滤 run/事件）——**待拍板是否立项**（有审计需求才做）；REQUEST_ARCHIVE_FULL 钩子删除或接线（按 §2 断点条款，无人读的开关应删）。
- **红灯/绿灯**：按最终拍板形态补。

### 批三 · P2 健壮性与体验

#### M9 neuacp 泵线程审批等待去阻塞

- **问题**：权限请求在泵线程同步等审批，等待期间同进程帧（含流式 chunk）无法派发，人工审批慢时外部代理「卡住」。
- **修法**：把「等裁决」挪出泵线程——泵线程只投递权限请求到执行体队列即返回（先回 ACP 一个 pending/deferred 形态或按协议允许稍后应答），裁决到达后在事件循环侧补发应答；保留 fail-closed（裁决前不 allow）。
- **影响面**：`acp_client.py` 泵循环 + `acp_executor.py` 权限处理器 + `codec_v2` 应答映射；需核对 ACP 协议对延迟应答的约束（v1/v2 分别验证）。
- **红灯**：权限请求挂起期间持续泵入流式 chunk → 现状 chunk 停滞（红）；改后 chunk 继续转发。
- **待拍板**：D-M9 是否本期做（涉及协议时序，需真 CLI 握手验证）。

#### M10 池 acquire 有界等待

- **问题**：池满时 `acquire` 无超时，新派活最坏等近 10 分钟。
- **修法**：`_ensureClient` 传有界 `waitTimeout`（如 30s，env 可调），超时诚实报 `executor_pool_busy` 结构化失败（不改静默重试）。
- **红灯**：占满池 + 新 spawn → 断言快速失败且错误码为池忙（现状挂起，红）。

#### M11 成员声明侧过滤对齐

- **问题**：`build_tools_for_llm` 不读成员白名单，子代理工具声明面仍列主代理专属工具——浪费 token 且诱导撞门（执行期有兜底，安全性无损）。
- **修法**：成员回合构建工具清单时按已绑定的 `run.tool_allowlist` 过滤声明面（与执行门同源）；Tool Search 压缩路径同步。
- **影响面**：`neurova/context/orchestrator.py`；子代理可见工具数下降。
- **红灯**：成员上下文构建工具清单 → 断言不含 MAIN_AGENT_ONLY_TOOLS（现状含，红）。

#### M12 TEAM 可见性补真实现

- **问题**：`_can_view_project` 对 TEAM 直接 return False——`visibility=team` 审批通过后非成员仍不可见，审批语义与可见性语义脱节。
- **修法**：TEAM 分支按项目元数据的目标团队/成员清单判定（审批通过时登记的 memberUserIds 即共享对象），非成员仍拒。
- **红灯**：visibility=team 项目 + 已审批共享的目标用户（非项目成员）→ 现状不可见（红）；改后可见；无关用户仍不可见。

#### M13 前端协作四小项

- 升级卡：拍板「保留只读」或接提交口（若接，后端本有 escalation 裁决面可挂）——**待拍板 D-M13a**；
- 待审批角标：房间页接 `getRoomSwarmPending`（端点已在），显示「N 条待裁决」；
- 审批后本地态：`decideApproval/actCandidate` 成功后本地更新卡片状态（不空等 WS 回声），支持 note 输入位；
- user_message 去重收紧：去重键加 messageId/时间戳，避免连续同文被吞。
- **验收**：vitest 组件用例 + vue-tsc 0 错 + i18n 新增键 ×11 语言。

#### M14 文档/心智债小修

- `tool_executor.py:1439` execute() docstring 修正为现行回退链（纯注释，零逻辑）；
- `team.py` 模块头标注「协议层预留、生产主链在 SwarmManager」边界说明（已在分析报告 §4.1，落一行代码注释防误用）；
- `04-multi-agent-collaboration.md` 头部状态标注已存在，保持。

---

## 3. 待拍板清单（**已全部拍板，2026-11-21 交互拍板**）

| 编号 | 问题 | 拍板结果 |
|---|---|---|
| D-M3 | API-key 租户策略 | **乙：APIKey 增 tenant_id 字段**（动表+签发+校验，随 M3 实施） |
| D-M5 | 事件库保留窗 | **1 天，env 可调**（沿 A2 拍板值） |
| D-M7 | 多副本路线 | **乙：候选板与审批 pending 迁 SQLite 单源** |
| D-M8 | lineage 审计聚合读面 | **立项：admin 审计聚合读面** |
| D-M9 | 泵线程审批去阻塞 | **本期连 M9 一起做**（与 M10 同批，真 CLI 验证时序） |
| D-M13a | 升级前端闭环 | **接提交口**（后端升级裁决面 + 前端按钮与 i18n） |

## 4. 明确不做

- 不建第二套编排引擎/事实源（team.py 不升级为第二编排，只作协议层标注）；
- 不为多副本引入新中间件（消息队列/分布式锁），除非 D-M7 拍板乙；
- 候选板不落新表（沿用 H-4 重放投影纪律）；
- 不动 reference-ac/ab 已实施卡的既有语义（A2 双写镜像、P2-3 投影）。

## 5. 建议执行顺序

批一 M1→M4（P0，一至两天量级，互相独立可并行）→ 批二 M6→M5→M7→M8 → 批三 M10→M11→M12→M13→M14→M9。每卡独立提交、独立红绿证据；批一完成后回填本节执行记录。

## 6. 执行记录

**2026-11-21 实施：十三卡全部落地，双门（红→绿 + A/B 零新增）逐卡通过。**

| 卡 | 提交 | 摘要 |
|---|---|---|
| M1 | `b4d952208` | 房间文本批准补治理回灌（与显式端点同效力，decidedByChannel=room） |
| M2 | `9f162dbab` | MCP 身份缺省改 fail-closed（McpIdentityMissingError） |
| M4 | `052cb6243` | merge 审批通道故障改 fail-closed（候选保留待人工） |
| M3 | `649cadc4e` | APIKey 增 tenant_id（拍板乙）：签发者租户进身份（REST/MCP 两面） |
| M6+M10 | `5e88d0b1a` | /external-agents/status 接真实池水位 + acquire 有界等待（池裁决不绕过） |
| M5 | `877ad512a` | 事件库镜像周期清理（保留窗 1 天 env 可调）+ console after_seq 游标重放 |
| M12 | `f1bb32eaf` | TEAM 可见性补真（治理批准共享清单 teamSharedUserIds） |
| M11 | `095b9a218` | 成员工具声明面按派生白名单收窄 |
| M8 | `2ca518b8c` | lineage 租户/房间审计聚合读面（admin） |
| M9 | `81cf837ac` | 权限裁决去泵线程（handler(params, respond) 契约，人审期间帧派发不停） |
| M7 | `60ad6ce7d` | 候选板/房间 pending 索引 SQLite 单源（env 门控，缺省内存不变） |
| M13 | `73627f28c` | 待裁决角标/审批后本地态+备注/去重按 event_id/升级提交口（steer/cancel） |
| M14 | 本笔 | execute() 文档回退链修正、team.py 定位边界注记、本执行记录 |

**偏离说明**：
- M4：计划倾向「run 维持等待态」，实施取「候选保留 submitted 待人工处置」——候选板即等待态载体，run 判 failed 与 merge_blocked 既有语义一致，避免为终态挂起新造机制。
- M5：读面消费落在 console 子任务事件端点的 after_seq 游标重放（replayThrough 的生产消费点，degraded 诚实降级）；会话级 WS 断线重连接入需「全局 seq ↔ 会话 seq」映射设计，超出本卡，另批登记。
- M9：契约由 handler(params)→dict 改为 handler(params, respond)；replay harness 与 fake agent 同步适配。
- M12：TEAM 语义锚定治理批准清单（metadata.teamSharedUserIds，两处批准路径写入），非清单外非成员仍拒。
- M3：REST 消费点（auth.py）原已是 getattr 兼容形态，本卡补齐数据模型、MCP 消费点与两处签发面透传。

**实施中发现的预存问题（归属其他工作线，本计划不越界修）**：
1. 架构守卫 `test_architecture_policy_guard` 未分类 `neurova/contracts` 模块（commit 31055a619 引入）——2 例预存红。
2. 鉴权面文档机器段与路由表脱节（RSI 批次新增路由未跑 `scripts/generate_api_auth_surface.py --write`）——2 例预存红。
3. 身份通道守卫台账缺 4 个新读方（asr/minutes、dreaming、lane_mutex、tool_call_journal，RSI 批次引入）——1 例预存红。
4. `test_replay_contract[codex/prompt_end_of_turn]` 一次偶发失败，复跑 10/10 全绿（环境竞争，非稳定失败）。
