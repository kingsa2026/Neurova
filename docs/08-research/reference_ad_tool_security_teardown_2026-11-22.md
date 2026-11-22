# reference_ad 专项：工具与执行安全十轴细拆（Neurova vs LobeHub）

- 日期：2026-11-22
- 性质：总报告《reference_ad_vs_neurova_fullstack_evaluation_2026-11-21.md》D4 维（工具生态与执行安全）的**专项细拆**（竞品/外部对标，研究参考，不作产品事实源）
- 对象与证据：lobehub/lobehub（canary@2026-11-21 快照）vs 本仓主干。证据来自只读深读：对方 `builtin-tools`/`tool-runtime`/`mecha`/`device-mcp`/`device-sandbox`/`ssrf-safe-fetch`/`secret-channel`/`builtin-tool-creds`/`InterventionChecker`/`agent-signal` vs 本仓 `tool_executor.py`（9,580 行）/`builtin_tools.py`/`sandbox/`（code_sandbox/exec_sandbox/restricted_token/appcontainer）/`security/`（governance/command_segments/approval_manager/skill_scanner/secret_store）/`http_fetch.py`/`muscle_memory.py`。全部结论带 file:line。
- 评分口径：本专项 10 轴 ×10 分 = 100 分（与总报告 D4 的 14 分维互相独立，粒度更细；轴等权）。

## 0. 结论摘要

**专项总分：Neurova 82.0/100 vs LobeHub 78.0/100**——十轴等权下本仓小胜 4 分，画像互补。

- LobeHub 最强：**执行安全基建**——三档沙箱（云沙箱/SRT 本地沙箱/Pyodide WASM）、专用 SSRF 防护包+自研 lint 强制走安全通道、凭据全程脱敏不进模型上下文、三层审批（声明式 humanIntervention+动态审计+auto-run 也不可绕过的安全黑名单）、44 个工具全部带完整运行元数据（超时 clamp/双执行面/干预策略）。
- Neurova 最强：**139 个内置工具单源注册表+并行能力声明**（readOnly/concurrentSafe/writeScopes）、**MCP client+server 双端**（对方仅 client）、**肌肉记忆程序性闭环**（调用成败→参数模板→相似任务自动执行/建议，对方为零）、**命令分段治理**（防白名单搭便车）与**渠道验签/审计/技能扫描**族。
- 双方共同缺口：工具大结果都无统一"落盘+句柄"卸载层（本仓 microcompact 只覆盖 >8000 token 的工具结果；对方靠修剪+重调）；都无工具级 ABAC/字段级权限。
- 一句话：对方是"**执行安全基建 + 分布式执行面**"，本仓是"**工具智能（肌肉记忆）+ 双端 MCP + 治理纵深**"——总报告 D4 粗评（L 12.5/N 10）低估了本仓工具面（实测 139 工具 vs 44）与肌肉记忆权重，v7 据实回写后 D4 = L 12.0 / N 11.5（L 险胜 0.5）。

## 1. 十轴评分表

| # | 轴 | 满分 | LobeHub | Neurova | 判定 |
|---|----|-----:|--------:|--------:|------|
| 1 | 工具声明与 Schema 治理 | 10 | 9.0 | 8.5 | L 胜 |
| 2 | 生态规模与领域覆盖 | 10 | 8.5 | **9.0** | **N 胜** |
| 3 | 执行面架构 | 10 | 9.0 | 7.5 | L 胜 |
| 4 | MCP 能力 | 10 | 7.0 | **9.0** | **N 胜** |
| 5 | 工具调用学习（程序性记忆） | 10 | 1.0 | **9.5** | **N 大胜** |
| 6 | 沙箱与代码执行隔离 | 10 | 9.0 | 7.0 | L 胜 |
| 7 | 网络出站安全（SSRF） | 10 | 9.0 | 7.0 | L 胜 |
| 8 | 凭据管理与脱敏 | 10 | 8.5 | 7.5 | L 胜 |
| 9 | 审批与人机协同 | 10 | 9.0 | 8.5 | L 胜 |
| 10 | 入站验签/审计/工具供应链 | 10 | 8.0 | **8.5** | **N 小胜** |
| | **合计** | **100** | **78.0** | **82.0** | |

## 2. 逐轴详拆

### 轴1 工具声明与 Schema 治理（L 9 / N 8.5）

**LobeHub**：每工具一个 `BuiltinToolManifest`：identifier + api[]（JSON Schema parameters/description/`defaultTimeoutMs`（clamp 到 [1000,800000]，`packages/types/src/tool/builtin.ts:144-151`）/`humanIntervention`/`ordered`/`serializeBy`）+ systemRole + `executors: ['client'|'server']` + deviceClients，Zod 校验（builtin.ts:211-289）；`builtin-tools/src/index.ts` 汇总 44 manifest 带 `defaultToolIds`/`alwaysOnToolIds` 与 feature gates；进模型前 `normalizeToolSchema.ts`+`validateToolLimits.ts` 归一限长。
**Neurova**：`builtin_tools.py` 的 `_BUILTIN_SCHEMAS` 单源注册 **139 个工具**（每条含 description/parameters，且带**并行能力声明** `capability: {readOnly, concurrentSafe, writeScopes}`——如 recall_history 声明 `readOnly: True, writeScopes: ("none",)`，这是对方没有的维度）；`api/endpoints/tool_schema.py` 提供 OpenAI/Anthropic 双格式转换端点（_to_openai/_to_anthropic :67-73）；工具可见性治理=curated 名册+MAIN_AGENT_ONLY_TOOLS 并集+成员工具面收窄。
**判定**：对方运行元数据更厚（超时 clamp/双执行面标注/干预策略进 manifest）；本仓能力声明（读写作用域）与双格式转换端点是差异点，工具可见性治理（主 agent 专属/成员收窄）更成体系。L 9 / N 8.5。

### 轴2 生态规模与领域覆盖（L 8.5 / N 9）——本仓反超

**LobeHub**：44 个 builtin-tool 全部真实现（45 包含聚合包；最小包也有 manifest+serverRuntime，无空壳），类别：浏览器/网页、代码执行（cloud-sandbox/calculator/claude-code 桥）、文件/系统、知识/记忆、任务/协作/产物（task/goal/work/verify/acceptance-evidence/brief/dashboard/notebook/message/channel）、多 agent/技能（agent-builder/group-*/self-iteration/skill-store/activator）、媒体（image/video/canvas/artboard）、凭据/事件/设备/交互。
**Neurova**：`_BUILTIN_SCHEMAS` 实测 **139 个**（`grep -c '^    "[a-z0-9_]+": {'` = 139），领域：上下文池召回族（recall_history/recall_context_span/recall_query/context_compress/context_status/pool_search）、记忆与图谱（memory_search/graph_search）、文件族（file_read/file_parse/file_write/file_create/file_delete/file_edit/file_list/file_search/query_database/write_pdf）、**computer use 族 15+**（screenshot/click/type/scroll/dom_snapshot/som_snapshot/click_mark/list_windows/key/paste/drag/ssh_exec/shell…）、**浏览器原语族 30+**（navigate/click/type/extract_text/dom_snapshot/click_role/fill_ref/tab_*/eval/cookies/storage/console/pdf/download/upload…）、社交抓取（youtube_transcript/bilibili_search/rss_read/v2ex_hot/social_search/agent_reach）、语音（asr_transcribe/tts_synthesize/voice_memory_search）、**蜂群编排族**（spawn_subagent/list_teams/dispatch_team/propose_team/room_post/subagent_status/cancel_subagent/continue_subagent/rollback_subagent/request_approval/decide_subagent_approval/escalate/submit_result/ask_user）、技能（discover_skills/create_skill）、**工作流引擎族**（custom_node_*/workflow_*/run_scripted_workflow/schedule_task/sync_nodes/node_env_preflight/workflow_repair/build_batch_compensate）、canvas 族 13、规划/情绪/工具编排（planning/emotion_analyze/orchestrate_tools）、企业数据（enterprise_data_query）、deep_research/web_search/web_fetch/git/run_code/exec_command/write_stdin。
**判定**：数量 139 vs 44；本仓把蜂群编排/工作流引擎/canvas/computer use 整个子系统工具化，覆盖面更宽；对方单工具元数据更厚但清单窄。N 9 / L 8.5。

### 轴3 执行面架构（L 9 / N 7.5）

**LobeHub**：双执行面——client 面经 device-gateway WebSocket 派发到用户设备、Redis 阻塞等结果、服务端超时 clamp（`apps/server/src/modules/AgentRuntime/dispatchClientTool.ts:44-50,83`）；server 面 `services/toolExecution/`（serverRuntimes 73 文件）；结果以 tool_result/tools_batch_result 回灌（`agent-runtime/src/agents/pendingToolMessages.ts`），过期 pending 不劫持后续轮次（:37-50）；`tool-view-model` 把工具事件投影为 UI 视图模型；mecha manifestPool 按环境/开关/禁用态装配。
**Neurova**：`tool_executor.py`（9,580 行）**单管道零旁路**——所有工具（含 MCP、Skill、肌肉记忆自动执行）经同一 execute 咽喉，带 span 工具事件（S6 批接入）、治理预检内联、有界投影；REST `/tools/execute` 同层；`on_tool_executed`（:9354-9470）同时是肌肉记忆记账单源。
**判定**：对方的 client/server 双面+设备网关是分布式生产架构（浏览器/本地系统工具在用户设备执行），本仓单进程单管道换来的是审计简单与一致性，但远程执行面弱（仅 computer_ssh_exec）。L 9 / N 7.5。

### 轴4 MCP 能力（L 7 / N 9）——本仓反超

**LobeHub**：纯 MCP Client（`packages/device-mcp` 依赖 @modelcontextprotocol/client ~2.4.0，stdio+StreamableHTTP；服务端 `services/mcp/index.ts` 亦以 client 连 HTTP server）；加分：MCP Apps（SEP-1865）交互 UI+严格 iframe CSP、`builtin-tool-mcp-events` 事件订阅、per-tool 权限映射审批、进程树回收/会话守卫。**全仓无 @modelcontextprotocol/server、无对外 tools/list 服务端点**。
**Neurova**：client 侧 `tool_layers/mcp_client.py`+mcp_bootstrap/mcp_config/mcp_oauth/mcp_resilience/mcp_catalog；**server 侧** `mcp_agent_tools_server.py`（/v1/mcp/agent-tools 只读工具组 team_list/knowledge_search/memory_search，双鉴权 401）+`mcp_ontology_server.py`+`tool_layers/mcp_server.py`+`security/mcp_grants.py` 鉴权+`endpoints/mcp_server_api.py`+知识 MCP 源（`knowledge/mcp_source.py`、`ontology/mcp_surface.py`）。
**判定**：对方 client 深度（MCP Apps UI/事件订阅）略优，但本仓双端齐备且 server 面带鉴权——对外可被其他 agent 平台当工具源消费。N 9 / L 7。

### 轴5 工具调用学习（程序性记忆）（L 1 / N 9.5）——本仓大胜

**Neurova**：肌肉记忆完整闭环（默认开）——`muscle_memory.py`（861 行）+`tool_memory_integration.py`（536 行）：`ToolExecutor.on_tool_executed`（tool_executor.py:9354-9470）单源记账（治理拦截不记账防误伤）→ `MuscleMemoryItem`（工具名+查询指纹+语义向量+**上次成功参数模板**+L1/L2/L3+成败计数，JSON 原子落盘按 agent 隔离）→ 每轮 pre-LLM `match_by_query`（n-gram F1×0.6+语义余弦×0.3+成功率×0.1，层内阈值 L1>0.7/L2>0.5/L3>0.3）→ 三档：高置信**自动执行**（免 LLM 现想参数，仍过治理/审批，chat_pipeline.py:1324-1394）/ 中置信 `[工具记忆]` 建议块注入（context/orchestrator.py:1911-1931）/ 低置信不动作；连击升级/30-90 天衰减/失败重置/防回声室（hit_only 不计成功率）/参数形状不可执行封顶 suggest/工具退役联动 do_not_execute；阈值 RSI 可调（evolution/rsi/eval_harness.py:111-119）；测试 79 文件。
**LobeHub**：无程序性工具记忆。最近似三者均在文档/观测层：Agent Signal 弱信号回路（同工具连败≥2/纠正≥2→反思→create/refine_skill 提案，沉淀物是 SKILL.md 说明书进 system prompt）；Expertise(SCLPT) 教训编译为 verify_criteria（交付物验收判定器，不进工具链）；UsageCounter.accumulateTool 计量无反哺。无参数模板、无调用序列固化重放、无 tool stats 表。
**判定**：对方为零，本仓完整闭环。N 9.5 / L 1。

### 轴6 沙箱与代码执行隔离（L 9 / N 7）

**LobeHub**：三档——①云沙箱（market 托管/onlyboxes 自托管，executeCode 支持 python/js/ts，文件/shell 走 ComputerRuntime→ISandboxService）；②SRT 本地沙箱（基于 @anthropic-ai/sandbox-runtime：文件系统 allowRead/Write+denyRead/Write realpath 归一、网络 strictAllowlist 域名白名单且**排除模型/API 提供商防数据外带**、禁 PTY/Apple events、有活动命令时拒绝切策略，`device-sandbox/src/policy.ts`/`presets.ts:19-24`）；③Pyodide WASM Web Worker 进程内隔离。超时每 API clamp。
**Neurova**：`neurova/sandbox/` 四件——code_sandbox/exec_sandbox/restricted_token（受限令牌）/appcontainer（应用容器），run_code/exec_command 工具走此族；`security/command_segments.py` 把 shell 命令按 &&/||/;/| 分段逐段过白名单，堵"白名单命令+注入段搭便车"（`ls && evil` 不再命中前缀 ls 直接放行，governance 全段命中才放行）。
**判定**：对方三档分层+网络白名单排除模型提供商（防提示注入后外带密钥）更深；本仓有进程级隔离与分段治理但无云沙箱/WASM 档，隔离强度依赖平台机制。L 9 / N 7。

### 轴7 网络出站安全（SSRF）（L 9 / N 7）

**LobeHub**：专用包 `ssrf-safe-fetch`——request-filtering-agent 在连接时与**每一跳 redirect** 过滤私网/环回/链路本地/meta IP（index.ts:182-213），SSRFBlockedError 可识别，错误日志 URL 脱敏到 origin（:66-74），maxContentLength 流式软截断；自研 alint 规则 `no-unsafe-user-url-fetch` **强制**新代码走安全 transport（lint 层兜底）；消费方：web-crawler、model-runtime 媒体下载、文件上传。
**Neurova**：`http_fetch.py`（208 行）禁自动跟随重定向、3xx 交还上层逐跳处理（每跳可复核 SSRF 守卫，:133,181）；SSRF/协议守卫归调用方咽喉点先行校验（web_reach._http_get_text/rss_read 等），knowledge_ingestion/webhooks 等端点有 ipaddress 校验。**无统一专用包、无 lint 强制**，覆盖依赖各出站路径自觉走咽喉。
**判定**：对方"专用包+逐跳+lint 强制"成体系；本仓有逐跳复核意识但分散在咽喉点，漏接风险高。L 9 / N 7。

### 轴8 凭据管理与脱敏（L 8.5 / N 7.5）

**LobeHub**：`builtin-tool-creds`：OAuth（Composio+自有 providers）、`injectCredsToSandbox` 结果只含 env 变量名、值统一 `******`（连 Market 的首尾 2 字符掩码也不入模型上下文，`injectResult.ts:34-58`）、`__proto__` 原型链防护、用户手填凭据走权限门控表单；`secret-channel` HPKE（RFC 9180）端到端加密通道（aad/hpke/identity/redact，fail-closed 测试）但主链路未见消费方（待核实）；桌面 keytar/safeStorage。
**Neurova**：`security/secret_store.py`（keyring OS 级存储）；凭据"后缀掩码+显式展开"（qwenpaw 借鉴 B5 批：结果默认只显示后缀，展开需显式动作）；`audit_logger.py` 脱敏；8 个渠道 webhook 独立 secret 验签。无 HPKE 级端到端信道。
**判定**：对方的"凭据值永不进模型上下文"纪律与 HPKE 协议储备更深（尽管未接线）；本仓 keyring+后缀掩码+显式展开实用但层级少。L 8.5 / N 7.5。

### 轴9 审批与人机协同（L 9 / N 8.5）

**LobeHub**：三层——声明式 `humanIntervention: never/required/always`+参数级规则+动态审计注册表（pathScopeAudit 越出工作区即问/deleteFilesAudit 永久删除必问/dashboard dry-run/activateTools/agentAccount outbound，`dynamicInterventionAudits.ts:13-20`）；强制层 `InterventionChecker.shouldIntervene` 先查安全黑名单（rm -rf ~/、/etc/passwd 等），**auto-run 也不可跳过**（InterventionChecker.ts:60-77）；流程 `request_human_approve` 暂停→human_approval 事件→pending tool message→批准恢复，过期 pending 不劫持。
**Neurova**：审批链 L0/L1/L2 分级（NEUROVA_SWARM_MERGE_APPROVAL_LEVEL）+ToolExecutor 内联 `_governance_precheck`+`security/command_segments.py` 分段防搭便车+`governance.match_whitelist`+`approval_manager.py`+MAIN_AGENT_ONLY_TOOLS 并集+子代理工具面按成员收窄+工具面 ask_user/escalate/request_approval/decide_subagent_approval；肌肉记忆自动执行也过治理/审批。
**判定**：对方的参数级规则+动态审计+黑名单优先级更细；本仓分段解析与分级审批链更广（覆盖 swarm 裁决/房间治理）。L 9 / N 8.5。

### 轴10 入站验签/审计/工具供应链（L 8 / N 8.5）——本仓小胜

**LobeHub**：webhook HMAC 多处（logto SHA256/video timingSafeEqual/artboard 文件 HMAC+timingSafeEqual/inbound 每钩子独立 secret/LLM relay 信令 HMAC）；`workspace_audit_logs` 40+ 动作枚举+channel_audit；alint 安全规则（no-shell-command-injection/no-unsafe-raw-sql/no-secret-exposure/no-untrusted-code-execution）；MCP iframe 严格 CSP。缺口：主站 CSP 弱、业务 API 无通用限流、Electron IPC 裸 socket（计入 D9，不重复扣）。
**Neurova**：8 渠道 webhook 验签（dingtalk/feishu/wechat_kf_crypto/wechat_auth/telegram/qq/qclaw/xiaoyi，含 HMAC/签名解密）；`security/audit_logger.py`+`desktop_audit.py`+`endpoints/audit.py`+ontology audit；`skill_scanner.py` 技能内容扫描+`governance.py`+`eu_token_manager.py`；工具执行全量 span 事件入轨迹。
**判定**：双方都成体系；本仓渠道验签覆盖面（8 渠道）与技能内容扫描是差异点，对方 alint 模型背书 lint 是差异点。N 8.5 / L 8。

## 3. 对主报告的回写（v7）

- 二级专项：《reference_ad_remote_execution_teardown_2026-11-22.md》把轴3/轴6 中"跨主机/跨设备执行"部分再细拆（十轴 L 84.5 / N 78.0），结论方向一致，D4 不再因此调整。

- 首版 D4 粗评时本仓工具清单未实测（按"规模小"给工具框架 3.0/5，v4 肌肉记忆专项后调至 3.5）。本次实测 `_BUILTIN_SCHEMAS` 单源 **139 个工具**（vs 对方 44），且带对方没有的并行能力声明（readOnly/concurrentSafe/writeScopes）——工具框架与生态规模子项据实重评：**L 5.0→4.5 / N 3.5→4.0**。
- D4 合计：L 12.5/10.5 → **L 12.0 / N 11.5**（L 险胜 0.5）；总报告总分 98.0/95.0 → **97.5/96.0**。
- 口径说明：十轴等权下本仓 82.0 vs 78.0 反超；总报告 D4 因"执行安全"占 5.5/14 权重且对方在沙箱/SSRF/凭据三轴领先，判 L 险胜 0.5——两个口径并存，实质是"工具智能 vs 执行安全基建"的画像差，差距已收敛到 0.5 分。

## 4. 可借鉴点

D4 全域可借鉴点清单（21 项：P0×4/P1×8/P2×9）统一收口在《reference_ad_remote_execution_teardown_2026-11-22.md》§4——本节不另立第二份清单（教义第 6 条）。原轴级指向（SSRF 专用包收敛=轴7/沙箱补档位=轴6/动态干预审计注册表=轴9/manifest 运行元数据=轴1/HPKE 凭据信道=轴8/MCP Apps UI=轴4）均已并入该汇总。落地实施计划见《2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md》。

## 5. 本仓守卫提示（对方没有、勿被"对齐"掉）

1. **肌肉记忆程序性闭环**（轴5）：对方为零；引入其工具面形态时不得退化为"每次现想参数"。
2. **MCP server 面**（轴4）：对方仅 client；本仓双端是差异点。
3. **命令分段治理**（轴6）：防白名单搭便车的分段解析是本仓独有；对方靠黑名单+审批。
4. **工具并行能力声明**（轴1）：readOnly/concurrentSafe/writeScopes 进 schema 单源，对方 manifest 无此维度。
5. **139 工具单源注册表**（轴2）：规模与领域覆盖（蜂群/工作流/canvas/computer use 工具化）是本仓宽护城河。

## 6. 复评（2026-11-22 升级计划实施后）

三批十九卡+U20 全部实施完毕（提交链：91969ed0a U2 / 10b9cf7b2 U1+U3 / df23d131c 治理簇 / 79a15e220 通道认证 / 45c54da78 U10+killpg 收敛 / b1f3feb6c U5 容器档 / ead9c31e5 U19 lint / 6fd2f600e 收尾簇 U8+U17+U5 接线+U10 接线+write_pdf 属主 / 372e12c95 U20 浏览器隔离+能力路由 / ad567aee5+b92e69ece 收口补遗 / bf5bd9368 schema 补声明撤豁免）。逐轴复评：

| # | 轴 | 实施前 | 复评 | 依据（本仓新增能力） |
|---|----|-------:|-----:|------|
| 1 | 声明治理 | 8.5 | 9.0 | runtime 元数据+isolation/timeout 进 _BUILTIN_SCHEMAS 单源，READ_EXEMPT 收缩至 tz 别名 |
| 2 | 生态规模 | 9.0 | 9.0 | 持平 |
| 3 | 执行面 | 7.5 | 8.0 | park+迟交回灌、失败分级重试、结构化 UNSUPPORTED、进程树清算接线 |
| 4 | MCP | 9.0 | 9.0 | 持平 |
| 5 | 学习 | 9.5 | 9.5 | 持平 |
| 6 | 沙箱 | 7.0 | 8.0 | Docker 容器强隔离档+isolation 分派（不可用诚实拒绝） |
| 7 | SSRF | 7.0 | 8.5 | safe_fetch 收敛+全量迁移+静态扫描严格零违规 |
| 8 | 凭据 | 7.5 | 7.5 | 持平（write_pdf 属主登记计入轴10） |
| 9 | 审批 | 8.5 | 9.0 | 动态干预注册表+最后一刻复验+write_pdf 属主登记 |
| 10 | 测试/供应链 | 8.5 | 9.0 | 出站扫描严格模式+shell 分段扫描+新增 34 测试文件 |
| | 合计 | 82.0 | **86.5** | |

复评说明：总目标 90.0 **未达**（86.5），差距诚实记档——轴3（8.0）对方分布式设备网关仍深、轴6（8.0）对方云沙箱/SRT/Pyodide 三档仍全、轴7（8.5）对方 lint 强制成熟度更高；这三轴的剩余差距需另立卡（分布式执行面/云沙箱 provider/lint 升 error）而非在本轮注水。D4 维（总报告，安全加权口径）据实重评：L 12.0 / N 12.5——本仓反超 0.5。

## 7. 批四复评（2026-11-22 二次立卡实施后）

批四四卡全部实施完毕（提交链：c37697a31 remote_exec 核心包——端点注册表 SQLite+分派漏斗+离线 hold / 8ec41fcb4 SSH 形态接入漏斗+端点登记+守卫（真后端 9573+真 socket SSH 桩三跑：直连登记→漏斗执行→不可达 hold「未执行、可安全重试」）/ 3b74367ae guest/tunnel/neuacp/mcp 四形态登记（真 guest FastAPI+真 SQLite live-verify，跨租户隔离成立）/ 51276d9f8 shell 分段 lint 升 error+双扫描器挂双 CI static-gate——并补上 U2 交付时实际未挂载 outbound_fetch 的缺口）。受影响轴据实复评：

| # | 轴 | 批三后 | 批四复评 | 依据（本仓新增能力） |
|---|----|-------:|-----:|------|
| 3 | 执行面 | 8.0 | 9.0 | 统一远程执行面落地：五形态端点注册表（SQLite、自然键 upsert、租户段、稳定 endpointId、健康度台账）+dispatchRemoteCall 统一分派漏斗（准入能力复验→执行体注入→离线 hold 指数退避「未执行、可安全重试」→统一结果信封→生命周期事件）+注册制增量接入守卫（绕漏斗即红）——对齐对方设备网关的注册表/hold 语义且可审计 |
| 10 | 测试/供应链 | 9.0 | 9.5 | shell 分段 lint 默认 strict（违规退出 1，--warn 降档）+check_shell_segments/check_outbound_fetch 双扫描器显性挂进 .cnb.yml 与 GitHub ci.yml static-gate（真实仓 0 违规由测试钉住，引入违规即双红） |
| | 合计 | 86.5 | **88.0** | |

批四复评说明：轴3 8.0→9.0、轴10 9.0→9.5，合计 86.5→**88.0**。立卡时验收线写「轴7 8.5→9.0、86.5→89.0+」系轴归属标注误差（lint 属轴10 测试/供应链，轴7 为 SSRF 且已在批三复评至 8.5）——按「只经据实复评回写、不许预支」纪律落档 88.0。总目标 90.0 仍未达（差 2.0），剩余差距=轴6 云沙箱三档（U15 评估结论：待真实消费场景另卡）+ 对方设备网关的设备 attestation 与多版本兼容深度。D4 维（总报告，安全加权口径）据实重评：L 12.0 / N **13.0**——本仓反超扩大至 1.0。
