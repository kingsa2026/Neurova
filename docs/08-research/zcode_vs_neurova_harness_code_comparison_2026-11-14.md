# ZCode（zai-org/ZCode）vs Neurova 代码级对照评测

- 日期：2026-11-14
- 对象：zai-org/ZCode v3.18.2（commit `fec975905a2abd4c07e35c40d51fa097a2258ec9`，2026-11-13，Apache-2.0，8.7k star）
- 方法：浅克隆源码至仓外 `E:/项目/_external_repos/zai-org-ZCode`；**只读代码、不采信 README/文档宣传**。6 路并行代码侦察（核心循环／工具与沙箱／模型层与服务端／扩展机制／桌面与前端／工程质量与发布），关键结论逐条人工抽查核实（文件:行号见文）。
- 定位澄清：ZCode 是**单用户 coding agent harness**（CLI＋Electron＋远程控制）；Neurova 是**多用户通用 Agent 平台**（FastAPI＋Vue3＋多渠道＋知识/记忆/本体）。本评测在"各自定位下的实现质量"上打分，并列明相互可借鉴处；总分不等于"谁该取代谁"。

---

## 1. 规模与技术栈实测

| 维度 | ZCode v3.18.2 | Neurova（本仓） |
|---|---|---|
| 主代码 | ~120 万行 TS；22 个顶层 package + CLI 内 34 个子包 | ~40.1 万行 Python（1145 文件、60+ 顶层模块）+ 677 个前端 TS/Vue 文件 |
| 核心包 | core 11.7 万行 / desktop 15.1 万行 / services 14.3 万行 / ui 46.4 万行 / shared 6.6 万行 | agent_core 2089 行（尺寸棘轮钉住）+ agent/ 57 模块 + context/ 29 模块 |
| 测试 | 1974 个测试文件（含 757 个桌面 e2e spec、169 个工程测试） | 2626 个 pytest 文件 + 前端 vitest（2462 通过） |
| CI | **无**（无 `.github/`，门禁全在本地 pre-push 钩子） | ci.yml + codeql.yml + cost-guards.yml + .cnb.yml |
| 形态 | CLI(OpenTUI)+Electron+Web+remote server（Hono，单用户） | FastAPI+Vue3+Tauri 桌面+多渠道（企微/控制台/移动配对） |

## 2. 评分卡（10 分制，加权总分）

| # | 维度 | 权重 | ZCode | Neurova | 判定依据（摘要） |
|---|---|---|---|---|---|
| A | Agent 核心循环与编排 | 15% | **9.2** | 8.3 | ZCode：10 相位显式状态机＋非法迁移即抛错、工具拓扑分层并行、子代理权限只收窄、dynamic-workflow 编译期检查＋vm 沙箱＋journal 可恢复；弱：无硬步数上限、runtime/methods 100+ 文件。Neurova：checkpoint/恢复/环检测/协作编排成熟，循环显式化与调度并行度稍逊 |
| B | 工具系统与执行治理 | 15% | **8.8** | 8.1 | ZCode：47 工具双 schema、元数据契约（readOnly/destructive/riskLevel/sideEffectScope/needsApproval）、每工具 100KB 结果预算→artifact+预览、语法级危险命令匹配＋3300 行 argv 只读白名单、审批 fail-closed；弱：OS 沙箱已撤除且 `dangerouslyDisableSandbox` 由模型入参控制、路径无硬边界。Neurova：真沙箱模块（exec_sandbox/restricted_token 等）＋command_authority，但工具元数据契约与结果预算缺位 |
| C | 上下文工程与记忆 | 15% | 8.6 | **8.8** | ZCode：三级压缩（microcompact→auto 双熔断→reactive）、九段结构化摘要逐字保留安全约束、15M token 预算倒数注入、write-ahead 账本恢复字节一致；弱：token 启发式估算、无长期语义记忆。Neurova：fold 全家族（trigger/integrity/resolution/rollup）＋压缩经济学＋语义去重防漂移＋R(t) 保留率基准＋记忆巩固/睡眠洞察，更深且有度量 |
| D | 模型接入与弹性 | 10% | **8.5** | 8.2 | ZCode：AI SDK v6 统一三协议、35 个数据驱动 provider 模板＋远程同步、重试预算＋准入票据＋off-peak 排队；弱：无成本核算、无 Bedrock/Vertex。Neurova：llm/ 路由/限流/错误策略/能力缓存齐备＋按用户/组配额与用量账本，但 provider 模板仍代码注册、准入/off-peak 缺位 |
| E | 扩展机制 | 10% | **9.0** | 7.5 | ZCode：声明式零代码插件 manifest（skills/命令/hooks/MCP/agents/ui.surfaces）＋桌面代码扩展（能力表×授权档位×consentRevision）、7 事件 hooks 可改写入参/阻断/续跑、MCP Apps UI 标准、dynamic-workflow；弱：skills-lock 无校验消费者、扩展同进程。Neurova：plugins/（manifest/生命周期/权限/路由挂载）＋skill_system，事件点与能力表粒度较粗 |
| F | 安全与权限 | 10% | 7.6 | **8.0** | ZCode：六权限模式、fail-closed 审批、keyring 凭据、日志脱敏、更新验签；弱：无 OS 级沙箱、无路径硬边界、WebFetch 无 DNS 级 SSRF 防护、yolo 判定先于硬禁用检查、server 单共享 token。Neurova：多用户 JWT/角色/部门/配额/审计/宪法/认知安全门＋真沙箱模块；历史鉴权 P1 已全部收口 |
| G | 产品形态与前端 | 10% | **8.8** | 8.0 | ZCode：三端同核、648 键类型化 IPC、瘦 main＋host 进程、extension-host 熔断、更新链多平台验签、922 个桌面 e2e；弱：ui 包 46 万行"组件库+应用"不分、巨石文件靠 lint 豁免、i18n 仅 5 语言。Neurova：Vue3 工作台＋管理台＋11 语言严格对齐＋主题令牌棘轮＋Tauri 安装包，桌面自动化测试与更新链较薄 |
| H | 工程质量与治理 | 10% | **8.6** | 8.2 | ZCode：架构即代码（800 行/300 契约/12 方法/禁循环，baseline 零违规）、pre-push 8 道门、受影响测试选择、169 个"测基建"测试、许可合规证据链、SEA+bytecode 供应链加固；弱：无 CI、无覆盖率门禁、40+ 豁免、knip 盲区。Neurova：修复教义（先红后绿/live-verify/禁 consumer-only guard）＋尺寸棘轮＋CI/CodeQL，但边界治理靠守卫测试而非机器可查 policy |
| I | 企业化与多租户 | 5% | 3.5 | **8.8** | ZCode：单用户、server 单共享 token、有飞书/TG bot 渠道。Neurova：多用户/组/部门、按用户与组配额、用量账本、知识库部门隔离、管理台、多渠道、备份与分析 |
| | **加权总分** | 100% | **8.4** | **8.2** | 核心域（A+B+C）均分：ZCode 8.87 vs Neurova 8.40；工程/产品域（D–I）均分：ZCode 7.67 vs Neurova 8.12 |

**一句话结论**：ZCode 是"单品冠军"——coding harness 核心域（循环/工具/扩展/治理）目前业内第一梯队，值得逐项拆解借鉴；Neurova 在上下文工程、企业化多租户、渠道面上反超，且是唯一有 CI 与安全扫描的一方。总分 ZCode 8.4 : Neurova 8.2，差距主要在核心域的"机制显式化与机器可查治理"，而这恰是最可迁移的部分。

## 3. ZCode 各维度证据要点（代码级）

### A. 核心循环（9.2）
- `apps/zcode-cli/packages/core/src/agent/turn-state.ts:35-45`：10 个 TurnPhase；`turn-machine.ts:92-104` 非法迁移抛错；驱动循环 `runtime/methods/turn-loop.ts:67` 保持极薄。
- 工具调度：`tool/scheduler.ts:50` 按依赖拓扑分层并行（maxConcurrency=10）；流式期间只读工具提前执行（`streaming-tool-coordinator.ts:52-53`）。
- 结果治理：每工具 resultBudget 默认 100KB，超限落 artifact 只回 2000 字符预览（`result-serialization.ts:25-30`、`result-persistence-format.ts:46-59`）。
- 子代理：Task 工具派生 AgentRuntime，`inheritPermissionMode`（contracts/…/session.port.ts:38-40）保证 guarded 父会话把子代理 yolo 压回 guarded——权限只收窄不升级。
- dynamic-workflow：模型写 TypeScript 脚本，编译器做 facade 类型检查＋污点分析，执行在子进程 vm 沙箱＋NDJSON host 桥＋journal 可恢复。
- 弱点：无硬最大步数（仅软警告与两处熔断）；`runtime/methods/` 100+ 文件、steering.ts 1663 行；状态机记录与真实转移双轨易漂移。

### B. 工具与执行治理（8.8）
- 47 个内置工具集中注册（core/tool/handlers/index.ts:87-162）；zod runtime schema＋JSON Schema 双schema（types.ts:444-446）；元数据 readOnly/destructive/riskLevel/sideEffectScope/needsApproval/timeoutMs（types.ts:75-111）。
- 权限六模式 plan/build/edit/yolo/guarded/auto（session.port.ts:33；auto 未实现直接 deny，permission/service.ts:152）。
- guarded 危险命令用 bash/cmd 语法解析识别（rm -r、dd、mkfs、git 危险子命令…），命中走"单次确认"；只读命令靠约 3300 行 argv 级白名单免审批。
- `resolveInput` 入参归一化单点：hook、权限规则、审批预览、handler 共享同一份执行入参——杜绝"批准 A 跑 B"。
- 已核实的沙箱缺位：Node 执行适配器注释自认"sandbox 撤除后"（adapters/src/exec/node-execution-adapter-run.ts:399-400）；`dangerouslyDisableSandbox` 是模型可见入参（contracts/src/tools/bash.ts:70）；路径策略明示不硬拦 workspace 外路径。

### C. 上下文工程（8.6）
- 三级压缩：microcompact 清旧工具结果（阈值=autoCompact×0.9）→ auto compact（200K 窗口−21K 输出预留−13K buffer，连续失败 3 次熔断）→ 超限 reactive compact（compact/policy.ts:6-14,90-157）。
- 压缩摘要强制九段结构并逐字保留安全约束（compact/prompt.ts:24-80）。
- token 预算 15M，按 runtime 倒数注入 `<total_tokens>` 附件（context/total-tokens.ts、helpers/total-tokens-budget.ts:41-70）。
- 会话 SQLite＋write-ahead 输入账本，admission/promotion 同事务杜绝孤儿输入；恢复前缀字节一致。
- 记忆：project memory 索引＋Dream 巩固（24h 锁，memory/dream.ts:12-14）＋turn 后台抽取。
- 弱点：token 估算为"中文字符×2"启发式（context/utils.ts:12-18），无真实 tokenizer；无长期语义记忆层。

### D. 模型接入与弹性（8.5）
- 35 个 provider 模板数据驱动（config/provider/zcode-builtin.json，revision 44）＋远程同步（provider-node/zcode-builtin-remote-synchronizer.ts）——新增供应商不改代码。
- 执行层 Vercel AI SDK v6，三协议归一（anthropic-messages / openai-responses / openai-chat-completions，adapters model-execution.ts:401-423）。
- 弹性：默认 10 次重试、2s×2 退避 60s 封顶＋jitter＋重试预算（retry-policy.ts:11-26）；进程级在飞请求准入票据（request-admission.ts:38）；429/业务码 off-peak 排队（offpeak-retry.ts:32-56）；fallback 带显式 reason/providerErrorCode。
- preflight 上下文预算钳制：每步输出上限 = contextWindow − 估算已用 − 1000（runtime/methods/model-token-limits.ts:26-44）。
- 弱点：无按 token 成本核算；无 Bedrock/Vertex/Ollama。

### E. 扩展机制（9.0）
- CLI 插件＝一个 manifest（contracts/src/plugins/index.ts:149-171），目录约定贡献 skills/commands/hooks/mcpServers/agents/lspServers/outputStyles/ui.surfaces，纯内容插件可零代码。
- 桌面代码扩展跑独立 UtilityProcess，能力表×授权档位链（fullAccess⊇write⊇read）＋consentRevision 语义变宽强制重新确认（extension-host/grants.ts:12-52）。
- hooks 7 事件（SessionStart/UserPromptSubmit/PreToolUse/PermissionRequest/PostToolUse/PostToolUseFailure/Stop），可 deny＋改写入参＋注入上下文＋Stop 续跑；工作区 hook 每次分发前重验信任（core/src/hooks/runner.ts:51-114）。
- MCP 纯 client，stdio/http/sse＋OAuth，工具并入 `mcp__<server>__<tool>`，默认 needsApproval=true；UI 面板走 MCP Apps 开放标准。
- 弱点：skills-lock.json 无任何校验消费者（供应链锁形同虚设）；桌面扩展自述"授权不是安全边界：所有扩展同进程"（grants.ts:4-5）。

### F. 安全与权限（7.6）
- 审批 fail-closed：审批钩子异常仍保持 ask；未知拒绝错误一律按 PermissionDenied（executor/impl.ts:219-224）。
- WebFetch 出口护栏拒 localhost/私网字面量（含 NAT64/IPv4-mapped 还原），但自认不做 DNS 解析校验（webfetch-egress-guard.ts:24,40-99）——DNS 重绑定可绕过。
- 凭据：OS keyring（@napi-rs/keyring）＋`enc:` 加密文件兼容＋请求期动态鉴权头注入；日志按 key/token/cookie/password/secret 正则脱敏。
- yolo 放行先于 disallowedTools 硬禁用检查（permission/service.ts:148 与 161，注释自认此序）——顺序瑕疵。

### G. 桌面与前端（8.8）
- main 进程瘦壳；Agent 与业务 services 跑独立 host utilityProcess；extension-host/scheduler/CUA helper 各自进程，崩溃预算＋熔断退避。
- IPC 通道常量单一事实源（shared/src/channels.ts，三组约 648 键）；main 侧 127 处 handle；全程 contextIsolation:true。
- 自研 `@zcode/rpc` 一套抽象吃通桌面 MessagePort／Web WebSocket／远程遥控三传输。
- 打包分发：mac 签名+公证、win NSIS+下载包 Authenticode 再验签（autoUpdater.ts:494-501）、linux 四格式；CLI 走 Node SEA＋V8 bytecode。
- 弱点：packages/ui 46.4 万行实为"组件库+整个应用"；autoUpdater.ts 2178 行等巨石靠 lint 豁免；web-share/share-ui 与 web/ui 双份并存。

### H. 工程质量与发布（8.6）
- 架构即代码：architecture-policy.yaml 登记模块 roots/requires/publicEntrypoints/layers/owner，全局 maxFileLines:800 / maxContractLines:300 / maxPublicMethods:12 / forbidCycles（:1838-1841），baseline 零违规；治理脚本自身有 node:test 守卫。
- pre-push 8 道门：worktree→e2e 目标→lint→陈旧文档短语→SQLite schema 契约→架构治理测试→增量架构检查→受影响工程测试（依赖闭包选测试）。
- 169 个工程测试覆盖打包/e2e 基建/许可/schema；第三方许可"数据+证据+生成器"门禁化（inventory.json 全量 sha256）。
- 弱点：无 CI 工作流（已核实无 `.github/`）；无覆盖率门禁；40+ unmanaged 例外；knip 忽略 ui 组件目录；e2e 默认回放 mock。

## 4. 对 Neurova 的提升清单（按影响面与优先级，待点单）

### P1（核心机制，建议优先）
1. **工具结果预算治理**：为每工具设 bytes 预算，超限落 artifact、只回固定长度预览。影响：tool_executor（7789 行，需先拆）、artifact 面（document_artifact 已有）、context 编排。收益：防巨结果撑爆上下文，与 B7 巨结果封顶形成互补的"逐工具"细粒度。
2. **工具元数据契约统一**：readOnly/destructive/riskLevel/sideEffectScope/needsApproval/timeout 进 ToolEntry，权限判定、调度并行、前端审批 UI 消费同一份；执行入参归一化单点（批准对象=执行对象）。影响：tool_executor、security/approval_manager、security/command_authority、前端审批组件。
3. **guarded 式危险命令治理**：语法级危险命令匹配（替代/叠加字符串黑名单）＋argv 级只读命令白名单免审批＋"单次确认"档位。影响：security/command_segments、command_authority、approval_*；直接扩大无人值守安全面。
4. **权限模式语义化**：引入 plan/build/edit/yolo/guarded（+auto 预留）会话级模式；子代理/工具权限"只收窄不升级"作为不变式进守卫。影响：agent、security、channels、前端模式开关。
5. **Provider 模板数据驱动化**：provider 注册从代码收口为 JSON 模板＋schema 校验（＋可选远程同步），新增供应商不改代码。影响：neurova/llm/providers、provider_manager、模型管理页、provider 设置 API。
6. **上下文注入 write-ahead**：凡注入模型的内容先落盘再进历史，恢复/重放字节一致；输入账本记录排队/消费/废弃。影响：context/orchestrator、checkpoints、session_repository。与既有 fold 完整性机制同链。
7. **架构即代码**：把模块边界/依赖方向/文件尺寸写成 policy 文件＋增量（只查变更）检查器，并导出"给 AI 的架构上下文"。影响：scripts/ci、新增守卫；与现有人工守卫测试互补。

### P2
8. **ToolSearch/延迟工具加载**：工具目录按需注入，控制 system prompt 体积。影响：builtin_tools、tool_executor、context builder。
9. **弹性包补齐**：进程级准入票据、失败分类驱动的重试预算、off-peak 排队。影响：llm/model_rate_limiter、model_error_policy、llm_client。
10. **hooks 事件点扩展**：PreToolUse（可改参/deny）、PostToolUse、Stop（可续跑）进 plugin_lifecycle，配信任审批与失败策略。影响：plugins/、skill_system、security。
11. **桌面更新验签链**：安装包下载后验签＋helper 证书一致性校验（若继续 Tauri 线则对齐 Tauri updater 校验）。影响：打包脚本、桌面端。
12. **e2e 真进程矩阵**：Playwright 现有 CI 基础上加分片、按时长加权、容器化。影响：tests/e2e、CI 配置。
13. **遥测 OTLP 化**：标准 OTLP 上报＋错误脱敏（只留 type/code/message）＋显式开关＋端点构建期注入。影响：analytics、新增 telemetry 模块。

### P3
14. **dynamic-workflow 型编排**：模型写受限脚本＋静态检查＋子进程沙箱＋journal 可恢复，替代自由 agent 循环跑长任务。影响：新增模块，接 workflow/execution_engine。
15. **记忆巩固后台化**：周期性"沉淀"任务（24h 锁防重）把会话经验折叠进长期记忆。影响：memory/、memory_ingest。
16. **MCP Apps UI 面板**：agent 生成 UI 的资源化托管（HTML 资源＋manifest 声明面板位）。影响：aigc_studio、前端。

### 不建议照搬的 ZCode 做法
- 无 CI／无覆盖率门禁（Neurova 的 ci.yml＋codeql.yml 是优势，别丢）。
- token"中文×2"启发式（Neurova 已收口 o200k 唯一尺子）。
- 沙箱撤除＋模型可控 `dangerouslyDisableSandbox`、路径不设硬边界——Neurova 的 sandbox/ 与多租户边界不应放松。
- ui 包 46 万行"组件库+应用"不分、巨石文件靠 lint 豁免——与 Neurova 尺寸棘轮方向相悖。

## 5. 结论

ZCode 代表"coding harness 单品"的当前最高工程水位：**机制显式化**（状态机、能力表、policy 文件）与**治理机器可查**（架构零违规、许可证据链、受影响测试）是它领先的两个根因，也正好是 Neurova 下一步投入产出比最高的两个方向。Neurova 在上下文工程深度、企业多租户、渠道与安全扫描面上保持领先。建议按 P1 清单逐项点单实施；每项都可独立走先红后绿流程落地。
