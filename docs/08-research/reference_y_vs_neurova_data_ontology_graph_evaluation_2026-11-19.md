# reference_y vs Neurova：数据本体图谱平台对照评测（2026-11-19）

> **性质**：外部参照项目代码级对照评测（研究参考，仅作背景，不可作事实源）。
> **参照项目**：代号 `reference_y`——一个开源（Apache-2.0）的「企业数据→本体→知识图谱」平台：把数据库、SaaS 工具与文档同步进来，由本体 agent 起草本体，加载进同团队出品的 Rust 图数据库（图+向量+BM25 同引擎），提供图浏览器与带引用的问答。Go 后端 + Next.js 16 站点，克隆时点约 19.9 万行（ts/tsx/go），2,154 星、312 fork，创建于 2026-10-07、推送活跃。
> **本文纪律**：全文不出现参照项目及其作者、所集成第三方产品的实名；一律以「参照项目」「本体 agent」「图库」等中性表述指代。文中 `file:line` 均为**对方仓库内路径**（克隆件当前工作区读数）。
> **被评方**：Neurova 本仓**当前代码态**，分数沿用 2026-11-18 独立终评（[reference_a_vs_neurova_final_evaluation_2026-11-18.md](reference_a_vs_neurova_final_evaluation_2026-11-18.md)）的 101/110 逐项证据；本轮已现场抽查锚点文件全部在位（`neurova/agent/swarm.py`、`neurova/agent/candidate_merge.py`、`neurova/memory_discipline.py`、`neurova/context_pool.py`、`neurova/core/request_archive.py` 等），期间提交均为移动端/前端适配与 MCP 外部注册（后者巩固已满分的 G2），不触及七维锚点。

---

## 1. 结论摘要

1. **总分：Neurova 101/110（91.8%）vs 参照系Y 80/110（72.7%），Neurova 领先 21 分。** 七维对照：A 协作形成 16 vs 13、B 执行协调 24 vs 18、C 通信 14 vs 10、D 记忆共享 14 vs 10、E 治理安全 14 vs 13、F 观测评测 10 vs 6、**G 异构互操作 9 vs 10（参照系Y 唯一领先维）**。
2. 形态差异必须先讲清：参照系Y 是**垂直数据工具**（单 agent 链路：连接器→本体起草→人审→图加载→问答），不是多 agent 协作平台也不是通用个人助理。其低分集中在协作/编排/评测等「多 agent harness」维度，属**形态使然**；而在它的主航道上（契约工程、工具面收窄、人审状态机、数据血缘、多源接入）它是教科书级实现。
3. **对本仓最有价值的五条启发**：①「规则即测试」——每条工程约定都对应一个会红的测试，完工标准与 CI 门完全同构；②**mock 服务器按契约出形状 + 故障注入**，成为契约的第三个实现，三方互相牵制；③**最小权限代理**——agent 拿到的是一次性临时 token 的环回代理，见不到真实租户凭据；④**人审决策对象带证据哈希**（ClaimKey/ClaimSpan/StatementHash），决策后自动重放生效；⑤**agent-host 模式**——把对话 agent 跑在用户自己的外部 coding CLI 订阅上，空工具集+只读沙箱+审批一律拒绝的隔离范式。
4. 参照系Y 的 **G 维（多模型/互操作）反超本仓 1 分**：7 类模型 provider + 本地模型探测 + MCP/llms.txt/.well-known 全套 agent 接入面 + 15 类连接器生态 + 借外部 CLI 当执行体。本仓 G2 已满分，差距在 G1 的 provider 广度与本地模型运行时。

---

## 2. 参照项目画像

### 2.1 定位与总体架构

```
浏览器 SPA（React 19 + react-router 7 + TanStack Query，客户端挂载）
   │  同源 BFF /papi（Next.js server：WorkOS 会话 + 单飞刷新 + HMAC CSRF + 零通配白名单）
   ▼
Go 后端（单二进制：API + 7 类 worker）── MySQL 元数据/任务队列 ── S3 兼容对象存储（不可变快照）
   │                        │
   │  环回 gRPC（vendored JSON 契约 4.26.0，启动比对版本）      │  graphproxy 环回代理（临时 token）
   ▼                        ▼
本体 agent sidecar（独立镜像，源码不在仓库）              图库（Rust，图+向量+BM25）
   │
agent-host（宿主机 helper：把 Assistant 跑在用户自己的 Claude Code/Codex 订阅上）
```

- **入口与装配**：`cmd/foundry/main.go:27-54` 解析配置；`run.go:102-162` 依序打开 MySQL（连接池 25/5、30 次 ping 重试）→ 迁移 → 种子 owner/workspace → 建数据桶 → AI 探测器（探测环境变量 key、捆绑 Ollama、本机 LM Studio）→ `dig` 依赖注入装配 worker 列表（foundry-read + sync/document/ontology/graph/ask 五 worker，可选 heal/agent/automation）→ `errgroup` 并发服务 + 30s 优雅停机（run.go:390-430）。
- **任务队列**：无外部队列，**MySQL 表即队列**——`store.go:617-655` `claimLease[T]` 泛型，事务内 `FOR UPDATE SKIP LOCKED` 领取到期行、置 `status='running'`、`attempts+1`、记 `lease_owner/lease_until`；worker 侧 15s 续租，丢租约即 cancel（围栏语义，「一个 hang 住的库等同失败」）。
- **数据→图链路**：连接器同步 → 快照与变更批写 S3（`ws/{ws}/connectors/{c}/{table}/{objectID}.jsonl.gz`）→ 表变化标记本体待刷新 → graph job 领取 → Ingest（同步表灌入新 load）+ Extract（文档交 agent 抽取，不确定的 claim 进人审队列）→ 经 graphproxy 写图库；读路径经只读代理，回答带引用。

### 2.2 连接器与同步（数据面核心）

- **15 类数据源**统一成一个目录（`connector/connector.go:313-334`）：Stripe、WorkOS、PostHog、GitHub、Linear、Cal.com、Granola、Slack、Notion、Google Workspace、Databuddy、PostgreSQL、MySQL、S3 文件源、事件推送源。
- **抽象接口**（connector.go:46-165）：`Kind`（Prepare/Discover/Sync）、`Targeted`（设置决定凭据发往哪台服务器，防改设置把凭据发去别处）、`SnapshotKind`（单快照多表一致）、`ChangeReader`（full/cursor/events/log 四种捕获）+ `VersionedWriter`（按版本列防旧覆盖新）。
- **CDC**：PostgreSQL 复制槽 + pglogrepl 消费 WAL（`postgres_cdc.go:77-250`），MySQL binlog + GTID 自动定位（`mysql_cdc.go:34-63`）；游标过期/位置丢失 → 该表自动转全量重读并保留上次重置原因（changes.go:29-61）。
- **错误语义三分类**：`InvalidError`（设置错，未拨号）/`RefusedError`（连接被拒，客户可读）/`AuthError`（凭据被拒，触发换 token 重试）。
- **SSRF 防护**：`connector.Guard` 拒绝私网地址，客户自选 host 走 `guard.HTTPClient()`。

### 2.3 本体 agent 与人审闭环

- 本体 agent 是**独立 sidecar**（源码不在仓库），Go 侧仅存 vendored JSON 契约（turn/ingest/extract/ask/audit/compare/revise/probe/check 等 11 个 Schema + VERSION，当前 4.26.0），启动时 `GetInfo` 比对版本，不符即永久失败（`ontologyagent/generator.go:237-240`）。
- **起草即多轮对话**：`Generator.Run` 把各表最新快照与文档集（每集最多 5 篇）暂存后发 Turn；agent 回 `needs_input` 时存 Questions+TurnState 等人答，回答进入下一轮 feedback turn；`done` 时产出 `agent_bundle`（OntologyTOML+MappingsTOML+Draft+Questions+Rules+Usage，≤3MiB）。
- **load 硬门**：手写本体定义永不加载；只有 agent 产出、状态 done、规则全部评估过的版本才能 load（`generator.go:168-188`）。
- **人审状态机**（`store/model/foundry_review_decisions.go`）：抽取中不确定的结论以 `held` 状态进审阅队列，人工五类决策——`resolve`（名字→实体）、`prop`（属性值，仅标量）、`release`（放行 claim）、`reject`（判错）、`withdraw`（撤回已生效决策）；同一 claim 只能 release 或 reject 之一。**每个决策带证据三元组**：`ClaimKey`（sha256）+ `ClaimSpan`（文档内字节区间）+ `StatementHash`（绑定用户当时读到的内容）。
- **决策即生效**：人审通过后排队 resend graph job 把相关文档重发引擎，使批准立即生效；resolve 结果作为 alias 带入后续 load。

### 2.4 血缘与可信问答

- **表级血缘**：S3 对象 key 自带 workspace/connector/table 路径，可回放任意批次。
- **claim 级血缘**：每条抽取结论绑定文档字节区间与内容哈希，回答引用时给出 `marker→CitationTarget`，target 恰好一型：实体/属性/文档引文（section+字节区间），解码时强制「每个引用必须有 marker 与证据、不得重复」（`ontologyagent/ask.go:398-445,560-566`）。
- **值冲突等人审**：多个文档对同一属性值不一致时，该值不直接生效，等待人工裁决。

### 2.5 安全模型

- **密钥密封**：`pkg/secretbox` AES-256-GCM 轮换 keyring，`Seal/Open` 以存储位置为 context（如 `connector:<id>`、`foundry-ai:<configID>`），key id 参与 AD 防换列/换行重放（`secretbox.go:61-90`）；连接器凭据、模型 key、Assistant 动作参数全部走此机制；`Hint` 只显示类型前缀+尾 4 位。
- **最小权限代理**（`graphproxy/graphproxy.go`）：每次图写入 job 由 Go 侧在 `127.0.0.1:0` 起一个一次性代理 + 32 字节随机 token，agent 拿到的 `HelixTarget{url,token}` **见不到也选不了真实租户与 provisioner key**；仅转发 `POST /v2/query`，header 白名单仅两项，body ≤2MiB；每 30s 重绑复核（库被删/暂停即永久拒）；429/503 准入拒绝按指数退避+jitter 重试。
- **BFF 硬门**（`src/server/`）：`__Host-` cookie 前缀强制、CSRF secret ≥32 字节、HMAC token 绑定 sessionId + timingSafeEqual + 双提交 + 同源校验；**refresh token 单次使用竞态用 per-cookie 单飞（single-flight）解决**（`single-flight.ts:10-46`，同 key 并发共享在飞 promise，宽限期内复用已旋转结果）；`/papi` 白名单 **865 行零通配**——「一条一个 method+path，照 swagger 抄，不许通配不许前缀，没列的 404，永不加登录/SSO/角色变更/成员移除」；配置不完整直接 503 拒绝「半配置」运行。
- **source grants**（`access/`）：被授权者即被「限制」在授权内，撤权不解除限制；API 层逐方法执行授权规则，grantee 仅可见其授权覆盖的 load。
- **agent-host 隔离**（`agent-host/src/run.ts` + README）：把 Assistant 跑在用户自己的 Claude Code/Codex 上（用户订阅付模型费）。对 Claude Code：`tools: []` 空工具集、只挂 Foundry 的 MCP、`settingSources: []` 屏蔽用户设置/CLAUDE.md/hooks、`canUseTool` 双保险拒绝一切其他工具、摘掉环境里的 API key 强制走订阅、每线程一个空目录。对 Codex：`sandbox: read-only`、`approvalPolicy: untrusted`、helper 对每个审批请求**一律拒绝**、开模型前**回读实际生效配置**（managed config 优先级高于 `-c`，任一覆盖不成立就让 turn 失败）、版本低于阈值不跑。配对用一次性 10 分钟码换长效 token，Foundry 侧只存 SHA-256。

### 2.6 工程体系

- **测试四层**：Go 单测+集成 342 文件/约 1,500 个测试函数（`compose.test.yaml` 起真实 MySQL 3307、GTID MySQL 3309、逻辑解码 PostgreSQL 5433）；前端 Vitest 149 文件；Playwright e2e 52 spec（生产构建对 mock + 本地构建对自有 mock 双跑，CI 4 分片）；**stack 真实栈测试**——`tests/stack/run.sh` 从头 compose 起真实依赖（含样例 PostgreSQL 灌种子数据），默认 `AI_PROVIDER=none`（不花钱、不误抓本机 key），trap 清场，在 Playwright 官方镜像里现场装依赖跑真机断言。
- **mock 即契约第三实现**：62 文件的假 WFE，严格按 swagger 出形状；`/__mock/config` 可注入几十种故障/节奏场景（token TTL、上传失败、读错误、目录异常、自动化时钟……）；`tests/unit/agent-contract.test.ts` 用 ajv 校验 mock 的每个回答、每个 fixture 与 SPA 发出的每个请求都符合 schema——**契约、mock、SPA 类型三方互相牵制，漂移即红**。
- **CI**：typecheck → eslint(0 warning) → prettier → vitest → 4 分片 e2e（汇总门 `needs: e2e-shard, if: always()` 全绿才算过）+ 后端独立检查流（build/vet/gofmt/golangci-lint/go test + 真实测试库）。
- **AGENTS.md（285KB/194 行，行超长）**：「仓库即 agent 说明书」——命令表逐条给端口/账号/三种 AI 模式；规则节全是**有测试兜底的硬约束**（白名单纪律、agent JSON 不信任解析、颜色只许 token、cookie 一律 `__Host-`…）；「Review decisions」节把审阅状态机等复杂业务语义写成散文级规格；完工标准一句话：「四项检查全跑完再收工，CI 跑的是同一套」。
- **agent 接入面**：`/llms.txt`、`/llms-full.txt`、`/.well-known/mcp.json`（streamable-http + OAuth2 + RFC 9728）、`ai-catalog.json`；内容实时从 docs 站抓取过滤；**工具清单与后端实际注册的一致性由单测保证**；robots 对应用本体（SPA/API）全站禁止索引，只开放门面与说明书。

---

## 3. 评分方法与锚点

- **维度体系**：与历轮完全同框——七维 A–G、廿二子项，每子项 0–5 分，满分 110。
- **锚点**：0=无实现；1=骨架/占位无消费方；2=部分实现仅靠自觉；3=机制化覆盖主链路有明显边界；4=机制化+测试守卫+治理完备；5=机制化+测试+治理+实证闭环。
- **形态校准声明**：七维框架为多 agent 协作 harness 而设。参照系Y 是单 agent 垂直数据工具，评其 A1（团队/角色）、C1（邮箱寻址）等子项时按「该形态下该机制的需要与实现」校准：它没有 swarm 概念，但其 worker 分工/角色模型目录/契约化任务对象若达到同档机制水平则给同档分，不因「形态不同」机械给 0；反之也不因其工程精致而虚高。此校准方式与 [reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md](reference_d_vs_neurova_standard_harness_framework_evaluation_2026-11-18.md) 的中立化处理一致。
- **证据纪律**：参照系Y 侧证据来自本轮两个并行代码分析（后端全量 + 前端/工程体系全量），引证到对方仓库 file:line；Neurova 侧沿用 2026-11-18 终评现场读数（本轮已抽查锚点在位性）。

---

## 4. 逐维逐子项评分表（参照系Y，22 项全表）

### A. 协作形成（13/20）

| 子项 | 分数 | 机制落点（对方仓库读数） | 边界 |
|---|---|---|---|
| A1 团队组成与角色分配 | 2 | 无多 agent 团队/名册；有模型四角色目录（Draft/Ask/Extract/Verify，`backend/ai/catalog.go:131-157`）与 worker 分工；agent-host 借外部 CLI 当执行体是独特的「协作形态」 | 无角色分配/职责拼装机制，角色是静态目录 |
| A2 任务单元结构化 | 4 | 本体草稿即高度结构化任务对象：agent_bundle（TOML+mappings+Draft+Questions+Rules+Usage，≤3MiB，`store/model/ontology_generation.go:52-60`）；11 个 JSON Schema + 版本号 4.26.0，ajv 三方校验 | 不是跨 agent 的 TaskUnit，仅此一条链路 |
| A3 验收条件 | 4 | load 硬门：仅 agent 产出、状态 done、规则全评估的版本可加载，手写定义永不加载（`generator.go:168-188`）；probe/check 契约；contracttest 回放 | 验收是门禁型而非评分型，无缺失项回炉机制 |
| A4 依赖与评审关系 | 3 | 同步→本体刷新→load 链式依赖由 store 事务内交接下一步 job id（graph-worker `finish`，`task.go:308-345`）；人审队列 ranked/random 出卡 | 无 DAG 依赖声明/校验/结算，无评审相位占槽 |

### B. 执行协调（18/25）

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| B1 共享执行状态 | 3 | MySQL 状态字段 + `claimLease` 租约（status/lease_owner/lease_until/attempts，`store.go:617-655`）+ goose 迁移 | 无显式状态迁移表，非法迁移不拦截（靠枚举纪律） |
| B2 单元生命周期 | 4 | 领租约→15s 续期→丢租约即 cancel 围栏；outcome 五分类（成功/预算耗尽/永久失败/Uncounted/InternalAttempts=2）；停机 Requeue 不计次；persist 三次重试保结局落库（`foundry-sync-worker/task.go:311-430`） | 无启动对账/事件重放收敛；状态语义散在 worker 而非单源 |
| B3 依赖门控与前沿并行 | 3 | 变化表→刷新→graph job 自动接续；budget 内 Extract，超预算等下次 | 无依赖门控 DAG、无并行前沿管理 |
| B4 事件驱动交互与阻塞升级 | 4 | `needs_input` 人答状态机（Questions/Answers/TurnState 进下一轮）；held claim 人审队列；automation 触发器五类（schedule/sync_finished/load_ready/document_arrived/generation_finished，`automation/trigger.go:24-93`） | 阻塞升级限于人审/问答，无卡死看门狗/升级建议动作 |
| B5 结果集成 | 4 | load 版本化 + `SetCurrentOntologyVersion` 原子切 current（`store.go:342`）+ 两 load compare + resend 使决策即生效 + alias 带入后续 load | 单写者模型，无候选制/CAS 合并/冲突双保留（形态不需要） |

### C. 通信基础设施（10/15)

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| C1 寻址/路由/邮箱 | 3 | gRPC+gateway+bufconn 环回路由（`server/endpoint/endpoint.go:148-173`）；BFF `/papi` 零通配白名单精确匹配（`papi-allowlist.ts:853-865`） | 无 agent 邮箱/优先级队列/死信语义（形态不需要） |
| C2 实时性 | 3 | NDJSON 事件流（tool_call/tool_result/draft/verdict/progress）；agent-host 250ms 增量回传（`run.ts:35`）；前端轮询 Ask 事件流 | 无 SSE/WS 广播通道 |
| C3 可靠性语义 | 4 | 幂等 request_id；准入重试（429/503 指数退避+jitter，`graphproxy.go:288-348`）；游标过期转全量宁全不丢；单飞刷新防 refresh token 竞态；resend 宁重不丢 | 无两阶段确认+死主回收的邮箱级语义 |

### D. 记忆与上下文共享（10/15）

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| D1 跨 agent 上下文共享 | 3 | worker 间经 store/S3 共享（快照缓存、agent_bundle、generation 状态）；Go↔sidecar 经 TurnState 传递 | 共享限于管道上下文，无跨会话记忆共享 |
| D2 共享黑板/工作记忆 | 4 | 图库（图+向量+BM25 同引擎）即持久共享知识库；表级+claim 级双血缘；值冲突不生效等人审 | 无记忆准入纪律/世代失效/确定性冲突判据 |
| D3 历史压缩与成本 | 3 | 成本治理强：vendored 价格目录（模型不在目录即拒，`ai/catalog.go:27-29`）、月度预算、BudgetExhausted、ProbeMaxUSD=0.5、boost 租约限速、快照 sweep 清理 | 无上下文压缩纪律（形态不需要）；预算是闸门型非优化型 |

### E. 治理与安全（13/15）

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| E1 权限/审批（人在环） | 4 | 人审五类决策状态机 + 本体草稿人审 + needs_input 问答 + source grants（授权即限制）+ workspace 隔离 + audit 契约 | 无审批分级（L0/L1/L2）/成对审计查询端点；本地模式无鉴权（产品定位为单人本机） |
| E2 工具面收窄 | 5 | **教科书级**：graphproxy 一次性临时 token（agent 见不到真实凭据）+ header 白名单 + 仅 /v2/query + 2MiB + 30s 重绑复核；agent-host 空工具集+只读沙箱+审批一律拒绝+配置回读验证；BFF 零通配白名单 | — |
| E3 资源治理 | 4 | 月度预算闸门 + MaxAttempts 判死 + IntervalFloor 同步间隔下限 + boost 并发租约 + ask 并发配置 | 无广度/深度/错峰等 spawn 级治理（无 spawn） |

### F. 可观测与评测（6/10）

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| F1 台账/trace/事件 | 4 | Prometheus 指标遍布（syncLag/jobs/jobSeconds/admission_retries/enrichment 全套）；health/ready/metrics 三件套；slog 结构化日志；Ask 事件落库；x-request-id 贯穿 | 无 run 级因果链账本/请求级归档/前端时间线 |
| F2 基准评测 harness | 2 | 无内建能力基准（无轨迹判据/基线归档/回归评分）；测试体系是正确性门非能力评测 | — |

### G. 异构与互操作（10/10）

| 子项 | 分数 | 机制落点 | 边界 |
|---|---|---|---|
| G1 多模型/多 provider | 5 | 7 类 provider（anthropic/openai/azure_openai/bedrock/cohere/ollama/openai_compatible，`ai/settings.go:22-33`）+ 四角色模型目录 + 本地模型自动探测（Ollama/LM Studio/环境变量，`ai/detect`）+ 价格目录强校验 + agent-host 借用户订阅 | — |
| G2 互操作协议 | 5 | MCP（/mcp + .well-known/mcp.json + RFC 9728）+ gRPC + swagger/OpenAPI 双契约 + llms.txt/llms-full.txt/ai-catalog.json + 15 类连接器生态 + agent-host 外部 CLI 互操作 + 配套技能仓 | — |

**维度小计**：A 13、B 18、C 10、D 10、E 13、F 6、G 10——**合计 80/110（72.7%）**。

### 十维中立框架附注（不同框架，不进座次）

按 reference_d 的十维口径快评参照系Y：P1 规划 5、P2 工具执行 8、P3 上下文 6、P4 记忆 7.5、P5 自我改进 4、P6 编排 5.5、P7 HITL 8、P8 安全治理 8.5、P9 工程可靠性 8、P10 生态部署 9——**约 69.5/100**。强在安全治理/生态部署/工程可靠性，弱在规划/自我改进/编排（垂直工具形态使然）。

---

## 5. 与 Neurova 对照

| 维 | Neurova（终评） | 参照系Y | 对照结论 |
|---|---|---|---|
| A 协作形成 | **16** | 13 | TaskUnit/验收门/依赖门控 vs 契约化草稿+load 硬门；Y 无多 agent 协作 |
| B 执行协调 | **24** | 18 | 迁移表+候选制+机械完成闸门 vs 租约围栏+outcome 分类；Y 缺启动对账与依赖门控 |
| C 通信基础设施 | **14** | 10 | 邮箱两阶段确认/优先级队列 vs 环回代理+白名单路由；Y 无 agent 邮箱语义 |
| D 记忆与上下文共享 | **14** | 10 | 类脑多层级+记忆准入纪律 vs 图谱即记忆+双血缘；Y 无准入/失效/压缩 |
| E 治理与安全 | **14** | 13 | 最接近的一维：Y 的 E2（工具面收窄）满分，本仓 4 分；本仓胜在审批分级+审计成对查询+治理三明治 |
| F 可观测与评测 | **10** | 6 | 本仓事件账本因果链+真模型基线 vs Y 的指标/日志/健康三件套；Y 无评测 harness |
| G 异构与互操作 | 9 | **10** | **Y 唯一领先维**：provider 广度（7 类+本地探测）与 agent 接入面（MCP/llms.txt/agent-host）略胜 |
| **合计** | **101（91.8%）** | **80（72.7%）** | **Neurova 领先 21 分** |

座次更新（同一七维框）：**Neurova 101 > 参照系A 95 > 参照系B 84 > 参照系C 81 > 参照系Y 80**。（参照系D 81.5 为十维框，不可比，仍作附注。）

一句话结论：参照系Y 把「单条数据链路的契约化、收窄、血缘、人审」做到了极高水准，但作为垂直工具，其协作/编排/记忆/评测纵深与通用 harness 不可同日而语；本仓在其主航道之外全面领先，唯一失分点在 provider/接入面广度。

---

## 6. 对本仓的启发与借鉴清单（按性价比排序）

> 每条给出：借鉴点 → 本仓现状 → 建议落点。是否立项由拍板定，本清单只列「值得学什么」。

1. **「规则即测试」+ 完工标准=CI 门**（性价比最高）。对方每条工程约定都对应一个会红的测试（颜色 token 三处一致、白名单⊆契约∩mock、agent JSON 不信任解析、cookie `__Host-`），AGENTS.md 明写「四项检查全跑完再收工，CI 跑同一套」。本仓已有守卫族（修复教义三落点、命名清洗、pytest 收集卫生），可把「i18n 键对齐、主题 token 禁硬编码、路由表与文档一致」等仍靠人工核对的约定继续钉成测试。落点：`tests/unit/` 守卫族、`.github/workflows/ci.yml`。
2. **mock 按契约出形状 + 故障注入**。对方 62 文件 mock 严格按 swagger 出形状，`/__mock/config` 可注入几十种故障/节奏场景，mock 成为契约的「第三个实现」，与 SPA 类型、ajv 校验三方互相牵制。本仓前端测试可借鉴：给 NeurUI 建「按后端契约出形状 + 可注入失败/慢速/边界」的 mock 层，让 vitest/e2e 能确定性演练失败路径。落点：`NeurUI/` 测试基建。
3. **最小权限代理（graphproxy 范式）**。agent 拿到的是一次性临时 token 的环回代理，见不到真实租户凭据；header 白名单、body 上限、30s 重绑复核、准入重试。本仓工具执行/MCP 面已有单管道，可借鉴「agent 不持有下游根凭据，只拿短时效、窄白名单的代理凭证」的纵深思路，尤其在外部 MCP server 注册面（f6dd5c6dc 刚落地）上适用。落点：`neurova/tool_layers/mcp*`、外部工具注册链。
4. **人审决策对象带证据哈希 + 决策后自动重放生效**。对方的 resolve/release/reject/withdraw 每条都带 ClaimKey+ClaimSpan+StatementHash（绑定「用户当时读到的内容」），且批准后自动排队 resend 使决策立即生效。本仓审批链/记忆人工审阅可借鉴：审批对象绑定证据摘要（防批准内容与执行内容不一致），决策通过后自动触发后续动作而非停留记录。落点：`neurova/agent/approval_chain.py`、`neurova/memory_admission.py`。
5. **agent-host 模式：借用户自己的外部 coding CLI 当执行体**。把对话 agent 的模型调用外包给用户已登录的 Claude Code/Codex 订阅，隔离手段拉满（空工具集、屏蔽用户设置、审批一律拒绝、开跑前回读实际生效配置、版本门槛）。本仓已有 ACP/外部 agent 握手与 MCP 客户端，这是互补方向：让本仓 Assistant 能「挂载」外部成熟 agent CLI 作为执行臂。落点：`neurova/agent/` 外部 agent 握手、渠道域。
6. **单飞刷新（single-flight）防 token 竞态**。refresh token 单次使用的场景下，并发 401 用 per-key 单飞共享同一次刷新并短暂复用旋转结果。本仓多渠道 token 刷新存在同类竞态面。落点：渠道 token 刷新链路。
7. **llms.txt/.well-known/mcp.json + 工具清单一致性测试**。把「如何接入本系统」写成 agent 可消费的说明书（是什么/何时用/如何接/全部工具清单），并用单测保证清单与后端实际注册一致。本仓 MCP server 面可补一份机器可读接入说明 + 一致性守卫。落点：`neurova/api/`、`neurova/mcp*`。
8. **stack 真实栈自动化冒烟**。对方用 compose 从零起真实依赖+样例数据，`AI_PROVIDER=none` 防花钱防误抓 key，trap 清场，Playwright 容器里跑真断言。本仓 live-verify 目前靠人工执行，可借鉴做成「一键真实栈冒烟脚本」（不起真模型，用桩 provider），把第 4 条教义的执行成本降下来。落点：`scripts/` 或 `tests/stack/`。
9. **BFF「配置即门卫」**。密钥长度、cookie 前缀、回调 URI 精确匹配任一不满足即拒绝启动相关面（503），绝不「半配置」运行。本仓启动校验可借鉴这种 fail-fast 姿态。落点：`neurova/api/` 启动链。
10. **AGENTS.md 的「领域语义规格化」写法**。对方把审阅状态机、撤销窗口、分页语义等复杂业务规则写成散文级规格供 agent 遵守，配合 mock 场景注入使 agent 可自证。本仓 AGENTS.md 是纪律总纲，可为高频协作域（swarm 状态机、审批链、记忆纪律）补「领域语义小节」，降低新会话/新 agent 的理解成本。落点：`AGENTS.md` 或 `docs/`。

**不值得学/不适配本仓**：MySQL 表即队列（本仓 SQLite/内存队列已够用且更轻）；闭源 sidecar 依赖（与本仓可选依赖惰性加载纪律相反）；本地单用户无鉴权定位（本仓是多用户服务端平台）。

---

## 7. 反向借鉴（本仓强项，参照系Y 可学）

简要列出，供完整性：状态迁移表+启动对账收敛（对方 worker 状态散置无单源）；候选制 CAS 合并与冲突双保留；run 级 JSONL 事件账本与因果链；记忆准入纪律（3-Task 转正/世代失效/敏感拦截）；上下文压缩纪律（触发比/严格变小/冷却）；基准评测 harness（轨迹判据+真模型基线归档）；RSI 闭环（阶段晋升门+快照回滚+确定性评测）；多渠道接入（IM/邮件/移动端）与移动原生端。

---

## 8. 局限性

- 参照系Y 的本体 agent sidecar **源码不在仓库内**（仅 vendored 契约），其提示词质量、工具调用细节、抽取准确率无法代码级核验；相关子项评分基于 Go 侧契约与驱动代码 + 契约 Schema 的完备性推断，可能存在 ±1 分的观察误差。
- 本评分为**静态代码级对照**，未实机运行对方栈（stack 测试需 Docker 环境与真实模型 key，本轮未执行）；对方「实证闭环」维度（F2）的低分部分源于无法观测其运行时表现，已按「仓内无内建评测 harness」这一代码事实评分。
- 七维框架的形态校准（§3）含主观判断；已在校准声明中写明规则，同一项目由不同评者复评可能产生 ±3 分内的总分歧，不改变「Neurova 领先一个身位」的量级结论。
- 对方创建仅六周、迭代极快，本读数仅代表克隆时点（2026-11-19）。
