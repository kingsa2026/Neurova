# reference_ad 资源治理专项 teardown：运行时 CPU/内存/时间/并发/配额/背压/成本

- 日期：2026-11-22
- 对象：[lobehub/lobehub](https://github.com/lobehub/lobehub)（代号 reference_ad，canary 快照，克隆留 `~/.zcode/tmp/lobehub-src`）
- 方法：专项只读深读（沙箱/超时/并发/配额/存储/部署/观测八面，104 次工具调用）；本仓对照锚点当日复核（container_sandbox/model_rate_limiter/connection_pool/TokenBudgetGate）
- 性质：**竞品/外部对标，研究参考**；主报告（v14）未回写，§4 评分建议供主控拍板参考

## §1 七类机制地图（LobeHub）

**1. CPU —— 无硬限**：沙箱 onlyboxes/market provider 无 CPU/进程数/容器规格配置，仅超时与租约 TTL（`apps/server/src/services/sandbox/providers/onlyboxes.ts:21-24,693-695`）；device-sandbox(SRT) 策略只含文件系统读写根+网络域名白名单，不含 CPU/内存（`packages/device-sandbox/src/policy.ts:29-50`）；python-interpreter(Pyodide Worker) 无内存/时间上限（`packages/python-interpreter/src/worker.ts` 全文无 limit/timeout/abort）；local-system runCommand 仅超时 30s–600s（`builtin-tool-local-system/src/manifest.ts:19,49,241,294`）。file-parse worker 有**结构化预算**（输入体积/条目数/解压后体积/单元格面积，超限抛 `FileParseBudgetError` 快速失败，`packages/file-loaders/src/fileParseBudget.ts:14-39`）——属内存型预算而非 CPU 配额。

**2. 内存 —— 弱~中（应用层字节预算，无 cgroup 级硬限）**：Docker 运行时堆顶 `NODE_OPTIONS=--max-old-space-size=8192`（`Dockerfile:60`，全仓唯一进程级内存硬顶）；ssrf-safe-fetch `maxContentLength` 流式截断（到量即毁流断连，`packages/ssrf-safe-fetch/index.ts:112-135,220`；消费点：下载图片/存消息图片/图片转 base64/爬虫 `MAX_HTML_SIZE=1MB`）；上传 2GB-1、解析 64MB（`packages/const/src/file.ts:22,26`）；访客单文件 32MB/每回合 10 个/总量 512MB（`packages/const/src/agentShare.ts:59-89`）；附件预览 4000 字符+按 token 预算规划（`planAttachmentPreviews`，`attachmentBudget.ts`）；陈旧工具结果 100k 字符裁剪（`StaleToolResultTrim.ts:364,630`）；路由 body 限宽 2MB/16KB/256KB/10MB；无日志轮转。

**3. 时间 —— 有（较成体系的软限，全部是超时而非 CPU 时片）**：工具超时三层同源 clamp——manifest 契约 `defaultTimeoutMs` 夹 `[1s, 800s]`、全局默认 120s（`packages/types/src/tool/builtin.ts:144-151`）→ `resolveToolTimeoutMs` 仲裁（`resolveToolTimeout.ts:16-24`）→ 服务端 `dispatchClientTool` 二次 clamp 兜底（`dispatchClientTool.ts:49-50`）；LLM：Anthropic 显式 295s（env 可调，`anthropicCompatible/index.ts:52,59-61`），OpenAI 兼容层未见显式 timeout（待核实）；爬虫 10s+AbortSignal（`withTimeout.ts:3-30`）；异步任务 298s（`ASYNC_TASK_TIMEOUT`，对齐上游）；沙箱命令 120s+lease TTL 900s+JIT TTL 1800s；Agent 状态 Redis TTL 2h+不活跃回收（`AgentStateManager.ts:224,651-677`）；workflow 对齐 Cloudflare 100s origin 预算（`nightlyReview.ts:186-200`）。

**4. 并发 —— 有（锁+槽+信号量+队列，但用户级并发默认不限）**：step 级分布式锁 `SET NX EX`+Lua claim/refresh/release 带属主校验（`AgentStateManager.ts:19-47,416-443`）；run 并发槽 `agentRunSlots` Redis Lua 租约+60s 续租（`agentRunSlots.ts:10-33`）——**但业务默认实现"从不限制"**（`business-server/src/agent-run/runConcurrency.ts:18-26`）；工具结果等待 `ToolResultWaiter` 多键 BLPOP 共享 deadline（`ToolResultWaiter.ts:61-93`）；embedding 批 50/并发 10（env 可调）+超时停在飞批次（`routers/async/file.ts:145-229`）；文件解析进程内信号量 `PARSE_CONCURRENCY=2`+等待队列、worker `maxConcurrent=1`（`fileParse/runner.ts:45`）；pMap 批量 fan-out；pg 池仅 `connectionTimeoutMillis=30s`（防池耗尽全挂，`database/src/core/web-server.ts:12-31`），`max` 未配置走 pg 默认 10。

**5. 配额/预算 —— 弱（骨架齐全，开源默认多直通）**：nightly-review 每用户每晚 topic 配额 50（Redis 原子领取，`topicQuota.ts:27-40`）；feedback-classifier 每用户每日 200 且 **Redis 不可用即 fail-closed 宁可不跑**（`budget.ts:19-70`）；手动触发限频 10 次/时/用户（`triggerRateLimit.ts:11`）；分享访客 `monthlySpendLimit` 默认 $10 强制存在+每访客 100 条（`const/src/agentShare.ts:18-24`）——**但 spendGate 默认恒放行 no-op**（`business-server/src/agent-share/spendGate.ts:47-51`）；embedding 用量中间件空壳直通（`trpc-middlewares/async.ts:3-5`）；ModelRuntime 留有 `beforeChat` 预算中断钩子（"Throw to abort (budget exceeded)"，`ModelRuntime.ts:118-120,387-421`）——**apps/server 无任何消费者（未接线）**；上下文压缩阈值 50% 窗口（`tokenCounter.ts:29-37`）。

**6. 背压 —— 弱（点状队列，无全局入口限流）**：有 QStash 队列削峰、解析信号量排队、BLPOP 阻塞等待、pg 池 30s 等待上限；无全站 HTTP rate-limit 中间件（仅 GitHub 上游 429 识别与 Redis key 模板，无全局消费）。

**7. 成本 —— 弱~中（观测完备，执法靠可覆盖钩子）**：`UsageCounter` 纯累计（tokens/cost/工具耗时，`UsageCounter.ts:9-50`）；`onChatFinal` 成本回调位+ServerLLMTransport usage 归因（`ServerLLMTransport.ts:250-254,728`）；背景任务降本靠配额面（topic/日预算双层），未见强制 mini 模型绑定（待核实）。

**8. 进程/部署/观测 —— 弱**：docker-compose 无 `deploy.resources` cpu/memory（仅 ES JVM 堆建议与 `nofile` ulimits，`docker-compose/deploy/docker-compose.yml:184-222`）；file-parse 为 worker_threads 每任务一线程与请求线程隔离；Electron 仅 `getAppMetrics` 观测无约束；存储治理有实战痕迹——autovacuum 针对高频表调优（`migrations/0026_add_autovacuum_tuning.sql`）、回收站定时 purge（`trash/handlers/purge.ts:20-34`）、FTS outbox claim/死信（`ftsSearchSync/service.ts:207-234`）；`/health` 静态 `{ok:true}` 不探依赖；全仓无 circuit breaker。

## §2 四项判定

1. **硬 CPU/内存上限**：CPU 全链路无硬限（沙箱/worker/LLM 均无 cpu 配额）；内存仅两道——Docker 镜像级堆顶 8192MB 与应用层字节预算（流截断/64MB 解析/访客 32MB·512MB）；无 cgroup/k8s resources 声明。
2. **超时覆盖**：较成体系（工具三层同源 clamp、异步 298s、沙箱 120s+TTL、爬虫 10s、workflow 100s、Agent 状态 2h）。裸奔面：Pyodide 解释器无时限、OpenAI 兼容 LLM 调用未见显式超时（待核实）、pg 无 statement_timeout、device-sandbox 命令执行。
3. **并发/背压**：Redis 分布式锁（step 串行）+租约槽（run 并发**默认不限**）+进程内信号量/pMap+QStash 队列+pg 池 30s 等待上限；无 HTTP 层全局限流/排队中间件。
4. **成本/配额粒度**：设计粒度细（per-user：topic 50/晚、classifier 200/日、trigger 10/时；per-share：$10/月、100 条、512MB；per-run：并发槽）；但**开源默认实现多为 no-op 直通钩子**（spendGate/runConcurrency/checkEmbeddingUsage 恒放行、beforeChat 预算钩子未接线），真实执法依赖部署方覆盖 `packages/business-server`。

## §3 与本仓对照（七类）

| 类 | LobeHub | Neurova（当日锚点复核） | 判定 |
|---|---|---|---|
| CPU | 全链无硬限 | 容器沙箱硬限 `--cpus 1`+`--pids-limit 64`+断网只读根+超时停容器（`neurova/sandbox/container_sandbox.py:68-71,283-284`） | **N 胜（执行面硬限）** |
| 内存 | 堆顶 8192MB+应用层字节预算 | 容器 `--memory 512m`+池预算（窗口×0.6）+microcompact 占位指针 | **N 胜（执行面硬限）** |
| 时间 | 三层同源 clamp [1s,800s] 成体系，覆盖较全 | 容器超时到点停容器+门控体系；未见统一"声明→仲裁→执行端"超时契约（待逐项核对） | **L 胜（契约化程度）** |
| 并发 | 分布式锁+租约槽+信号量+QStash（槽默认不限） | 单进程 asyncio+连接池获取 30s 上限（`core/connection_pool.py:59-80`）+渠道子进程隔离 | **L 胜（分布式面）** |
| 配额 | 粒度细但 OSS 默认直通 | TokenBudgetGate 在环真实执法（`agent/gates.py:128-134`，缺省取配置单源）+ModelRateLimiter（`llm/model_rate_limiter.py:26-30`）+swarm 软目标 | **N 胜（执法真实性）** |
| 背压 | QStash 削峰+信号量排队 | asyncio 队列/信号量（未做对等全量盘点） | 平（待核） |
| 成本 | 观测完备+钩子未接线 | usage 记账+TokenBudgetGate 在环 | **N 略胜** |

**总判定**：LobeHub 强在**超时契约化**（三层同源 clamp 值得学）与**分布式并发骨架**（锁/槽/队列）；Neurova 强在**执行面硬资源上限**（容器级 CPU/内存/进程数）与**配额在环执法**（门控真实拦截而非直通钩子）。共同短板：全局入口限流、熔断、依赖探活（/health 探依赖）双方都弱。

## §4 评分建议（供主控拍板，本笔未回写主报告）

- 资源治理证据主要落在 D9（运行安全）与 D4（执行安全）。若据实微调：D4/D9 中"资源执法"面本仓凭容器硬限与在环门控占优，对方凭超时契约与并发骨架占优——与 v14 后 D9 追平（9.0/9.0）、D4 反超（12.5/12.0）的现有格局**方向一致，不需改分**；本 teardown 作为证据留档。
- 若后续做"资源治理"独立轴（建议 10 分：CPU/内存/时间/并发/配额/背压/成本/观测/部署/恢复），当前快照可给 L 5.5 / N 6.0——是否立轴由主控拍板。

## §5 借鉴清单

P1（高价值、改动面可控）：
1. **工具超时三层同源 clamp 契约**：manifest 声明 → 集中仲裁 → 执行端二次 clamp，区间 [1s, 800s] 全局默认 120s。本仓超时散点各处自定，可收口为单一契约（影响面：tool_executor/沙箱/渠道）。
2. **后台任务 Redis 原子配额 + fail-closed**：nightly topic 50/晚、classifier 200/日的"Redis 原子领取、不可用宁可不跑"模式——适配本仓后台整理/RSI 跑批的频次治理。
3. **文件解析四维结构化预算**：输入体积/条目数/解压后体积/单元格面积任一超限即抛专用异常快速失败（`fileParseBudget.ts:14-39`）——可挂本仓知识库摄取链，防恶意/畸形文件拖垮解析。

P2：
4. **run 并发槽租约模式**（Redis Lua+60s 续租+属主校验）：为未来多实例部署预研；单进程现状下不急。
5. **存储自治理计划化**：SQLite 侧对应 incremental_vacuum/analyze 周期任务（对方 autovacuum 调优+回收站 purge+FTS outbox 死信的同构物）。

不照搬：
- "配额骨架默认直通"的 OSS 姿态——这正是本仓四域审计点名过的"机制先行消费滞后"同形病，对方靠闭源云版覆盖，本仓不学；
- 无 CPU 硬限的沙箱 posture——本仓容器硬限是优势，保持；
- 静态 /health 不探依赖——本仓健康面若扩展应做依赖探活。

## §6 证据与局限

- 静态只读、canary 单日快照、104 次工具调用抽样走读；关键结论均带 file:line。
- 两处待核实：OpenAI 兼容 LLM 调用是否依赖 SDK 默认超时；后台任务是否强制 mini 模型绑定。
- 本仓侧为锚点级复核（container_sandbox/model_rate_limiter/connection_pool/TokenBudgetGate），未做对等全量盘点；对照判定中"待核"项已标注。

## §7 实施记录（2026-11-22，P1×3+P2×2 全部落地）

- **P1-1 工具超时三层同源 clamp**=dce23f1b2：新增 core/timeout_policy.py 单源（[1,800]s，缺省 60s，非法/NaN/bool 回落缺省）；解析层 get_tool_timeout 表值/缺省过闸（单点收口，保留打桩接缝）；执行层 _execute_run_code 用户参 timeout 过闸（封堵 10**9 直通运行时的旁路）。红=ModuleNotFoundError+二段 4 failed（表值/用户参直通实证）；绿=46 passed 含既有 wiring/table-honesty 零回归。live：真后端 /v1/tool-layers/tools/execute run_code timeout=10**9 正常执行（60ms）。
- **P1-2 后台任务每日原子配额**=c29bd50da：新增 core/background_quota.py（BEGIN IMMEDIATE 原子领取、(name, UTC 日) 计数、fail-closed、DDL 走 db_migration domain=background_quota）；接线 RSI run_iteration 与 Sleep run_sleep_cycle（拒绝返回 quota_denied 信封，消费方零改动）。上限 NEUROVA_RSI_DAILY_QUOTA=500 / NEUROVA_SLEEP_CYCLE_DAILY_QUOTA=200。红=ModuleNotFoundError×3；绿=44 passed（20 线程抢 5 恰放行 5/fail-closed 双形态/跨日跨名隔离）。live：真数据根 first=True/second=False。
- **P1-3 文件解析四维预算**=55df7e5e4：新增 knowledge/parse_budget.py（输入体积 64MB/页数 2000/表格行数 10 万/单元格面积 500 万，env 注入）；parse_document 三处接线（入口体积闸含旧管线、pdf 页数闸、xls 表格闸），预算异常保形穿透（不被宽 except 重包成 parse_failed）。红=ModuleNotFoundError×3；绿=44 passed。live：真解析函数超限 fast-fail input_too_large。
- **P2-4 run 槽租约**=8f35c6780：新增 core/run_lease.py 租约板（acquire/renew/release 属主校验、过期回收、单调钟注入）；swarm 三处接线（spawn 锁内回收僵死槽+挂租约、_release_slot 属主释放、_reapStaleRunSlots 只修记账不杀任务）。NEUROVA_RUN_LEASE_TTL_S 缺省 0=关闭逐位一致。红=2 collection error；绿=31 passed。多实例启用位。
- **P2-5 存储自治理**=407beeab2：新增 core/db_maintenance.py（wal_checkpoint(TRUNCATE)+optimize，gauge neurova_db_maintenance_last_run_unixtime），app 启动注册每日系统 job（jobId=db_maintenance，同 prune 范式 fail-soft）。红=2 collection error；绿=31 passed。live：对运行中后端数据根真 checkpoint。
- **坑（复用教训）**：①数据根注入变量名是 **NEUROVA_DATA_DIR**（不是 NEUROVA_DATA_ROOT——后者被忽略静默回退仓库 data/，首轮回退污染真实库，已清 live_probe 行）；②共享索引里他会话已 add 的件会被普通 commit 扫走（c29bd50da 卷入 test_phase_suppression_sc1.py）——提交前必须核对 `git diff --cached --numstat` 只含本笔文件；③净 LOC 必须按 add 后实测 numstat 写（本批三笔写错：P1-1/P1-3 当场 amend 修正；P1-2/P2-4 两笔因并行会话高速推进放弃改写、留待推送窗口守卫兜底——c29bd50da 声明 +122 实际 +161、8f35c6780 声明 +121/−2 实际 +143/−0）。
