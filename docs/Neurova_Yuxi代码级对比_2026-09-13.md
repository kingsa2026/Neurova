# Neurova × Yuxi 代码级对比（2026-09-13）

> 对比对象：`github.com/xerrors/Yuxi`（本地浅克隆 `%TEMP%/yuxi-research`，commit `9820648`，2026-09-11 推送）× `E:/项目/Neurova`
> 方法：五路并行代码探索（Yuxi 智能体编排层 / 知识域 / 服务层与基础设施 / 前端与测试体系 + Neurova 侧对位核实），所有结论带 文件:行号 锚点。
> Yuxi：可私有部署的多租户知识智能体平台（FastAPI + LangGraph/DeepAgents + ARQ worker + PostgreSQL/Redis/MinIO/Milvus/Neo4j），6,941★ / 1,088 fork / MIT，2024-07 创建，至今高频活跃。

---

## 0. 元数据与体量

| 项 | Yuxi | Neurova |
|---|---|---|
| 定位 | 团队/企业私有部署的知识智能体平台（RAG+图谱+多智能体+治理） | 多用户 AI 助手平台（记忆/认知/知识库/工作流/技能/14渠道/桌面/语音） |
| 语言/栈 | Python 3 + LangGraph(DeepAgents 0.7) + ARQ；Vue3 全 JS 前端 | Python 3 FastAPI + SQLite/JSON；Vue3 + TS 前端 |
| 外部依赖 | PG/Redis/MinIO/Milvus/Neo4j + MinerU/PaddleX + sandbox-provisioner 全家桶（Docker Compose 强制） | **零外部服务依赖**，单 pip 环境可跑（桌面版单文件安装器） |
| 后端体量 | 550 py 文件 / **124k 行**（yuxi 包：agents 11.9k、services 14.5k、repositories 8k、knowledge 15.5k） | 550+ py 文件 / **225k 行**（90 子目录） |
| 前端体量 | web/src **≈93k 行**（JS，无 TS） | NeurUI/src **≈75k 行**（TS + vue-tsc 严格检查） |
| 测试 | backend **259 文件 / 2,034 test / 77.7k 行**（unit/integration/e2e 真 PG 栈）+ web 69 文件 node --test | 全仓 test 函数 4k+ 定义；台账绿基线 ≈ backend unit/api 1,471 + deep 1,197 + channels 391，前端 vitest 1,260 |
| Schema 治理 | **storage-migrator 唯一改表进程** + business/knowledge 版本域 + 精确匹配拒绝启动 | db_migration（PRAGMA user_version）只接入记忆库 1 个，其余 CREATE TABLE IF NOT EXISTS |
| 部署 | Docker Compose（7+ 服务） | 单进程 + 安装器（桌面/服务器两形态） |

**一句话画像**：Yuxi 是"平台工程纵深"的教科书——把**运行租约（lease）、线程级 FIFO、Durable Task、schema 版本域、openat 文件安全**这类分布式正确性做成了开源同类罕见的水准，测试体系（2,034 个真库并发竞态测试）是其最硬的资产；但在**记忆/认知/情感、可视化工作流、消息渠道、语音、桌面化**上完全空白。Neurova 是"产品广度 + 认知纵深"对"运行时工程纪律"的镜像：单进程零依赖部署是刻意的产品选择，代价是执行持久性与并发正确性落后 Yuxi 一个量级。

---

## 1. 逐项评分表

> 10 分制，对"该维度绝对完成度+工程质量"打分，不做相对扭曲。Yuxi 没有的维度按 0-1 记（对齐 OpenClaw 报告口径）。
>
> **⚠️ 本表为首评快照（2026-09-13 上午）。当日 P0/P2 两轮实施改变了 8 个维度的 NV 侧事实，修订评分与勘误见 §5；引用本表数字时请注明口径。**

| # | 维度 | Yuxi | Neurova | 一句话裁决 |
|---|---|---:|---:|---|
| 1 | 架构分层与边界纪律 | **8.5** | 7.0 | 薄路由/services 用例/repositories 持久三层铁律 + ARCHITECTURE.md 写死不变量；NV 大文件巨石残留 |
| 2 | Agent 运行时与会话编排 | **8.5** | 6.5 | middleware 洋葱组合 + Postgres checkpoint + HITL interrupt 闭环；NV 六步管线功能面全但 run 不持久 |
| 3 | 执行持久性与并发正确性 | **9.5** | 5.5 | 差距最大维度：lease/attempt/FIFO 部分唯一索引/取消三层/失联收敛全有真库竞态测试 |
| 4 | 上下文与 token 管理 | **8.0** | 7.5 | 四级压缩+工具结果落盘存根+30 字段用量快照 vs NV 活水池+compaction 四件套，接近持平 |
| 5 | 技能体系与扩展门控 | **8.5** | 7.0 | 三层依赖工具门控+advisory lock 投影同步；NV 独有能力进化但安装/门控弱 |
| 6 | MCP 整合 | **7.5** | 6.5 | 配置表+stdio 仅内置+缓存代次失效；NV 改造进行中（tool_layers 治理轮） |
| 7 | 知识库与 RAG | **8.5** | 7.0 | Milvus BM25 hybrid+rerank+Graph RAG+外部 KB 适配器；NV 零依赖方案完成度不低但 rerank 模型通道断链 |
| 8 | 知识图谱 | 7.5 | 6.5 | Neo4j+PPR 真联动 vs NV JSON 文件图谱+TKG 时效独有面 |
| 9 | 多租户与权限治理 | **8.0** | 6.5 | 部门+share v2+OIDC+API key 派生/哈希/tombstone；NV 5 角色 RBAC 无组织概念（产品范围所限） |
| 10 | 后台任务与调度 | **8.5** | 6.0 | Durable Task registry/lease/同事务失败钩子；NV 三套 APScheduler 并存且 TaskScheduler 台账重启即丢 |
| 11 | 存储与 schema 治理 | **8.5** | 5.5 | 见第 0 节；NV 多 SQLite+JSON 混存无全局迁移策略 |
| 12 | 沙箱与文件安全 | **8.5** | 5.5 | provisioner 容器 + dir_fd/O_NOFOLLOW 逐段 openat 链；NV 工作区目录级隔离（relpath 事故刚修） |
| 13 | 评测体系 | **7.0** | 4.5 | RAG eval P/R/F1@K+自动出题+Langfuse 实验回灌；NV benchmark 执行器 simulated 占位（诚实但未接线） |
| 14 | 测试与工程纪律 | **9.0** | 7.5 | 并发正确性真库竞态测试是标杆；NV TDD 红绿灯纪律+i18n 守卫但无 CI、竞态测试缺 |
| 15 | 可观测与审计 | **8.0** | 6.5 | model_audit/tool_audit 分离+阶段时间派生+Langfuse；NV OTel bridge+轨迹+错误上报链 |
| 16 | 前端工程 | 6.5 | **7.5** | NV TS+vitest+组件拆分占优；Yuxi 全 JS、5,655 行巨型 SFC，但 SSE 断线补偿设计强 |
| 17 | 记忆与认知体系 | 1.0 | **8.5** | NV 独占：温度生命周期/7 类 4 信任源/L0-L3/MoE/进化闭环 9.9k 行真接线；Yuxi 仅一个 147 行 memory middleware |
| 18 | 渠道/桌面/语音/工作流画布 | 1.0 | **8.0** | NV 独占：14 IM 渠道+入站持久队列、NeurFlow DAG 引擎、TTS/ASR、桌面安装器、CUA |
| | **平均（18 维）** | **7.3** | **6.8** | |
| | 仅平台工程 1-16 | **8.1** | 6.5 | Yuxi 领先 |
| | 仅产品广度 17-18 | 1.0 | **8.3** | Neurova 压倒性 |

---

## 2. 分维度代码级对比

### 2.1 执行持久性与并发正确性（Yuxi 9.5 / NV 5.5）——差距最大的维度

**Yuxi 的做法**（`services/run_worker.py`、`agent_request_queue_service.py`、`agent_run_repository.py`）：
- **先落库再投递**：请求在单事务内建消息+`AgentRunRequest`，只有 PG 提交成功才投 ARQ（`agent_request_queue_service.py:436-446`），队列消息永不先于数据库事实可见——ARCHITECTURE.md 把它列为架构不变量。
- **线程级单活 + FIFO**：`(uid, agent_slug, thread_id)` 的部分唯一索引 `WHERE status NOT IN (终态)` 由数据库强制互斥（`models_business.py:1257-1265`），冲突捕获 IntegrityError 保持 queued（`:986-992`）；FIFO 排序 `ORDER BY (policy!='steer'), created_at, id`（`agent_run_request_repository.py:70-91`），队头读取 `SELECT … FOR UPDATE`。
- **租约三件套**：进程 identity + 每 attempt 全新 owner token（`run_worker.py:627-629`）；lease 120s / heartbeat 30s，续租失败即停止执行且不写终态（`:213-229,1275-1277`）；所有业务写路径统一 `_require_lease_owner` 栅栏（`agent_run_repository.py:1056-1064`）；失联由 `FOR UPDATE SKIP LOCKED` 扫描收敛为 `worker_lease_expired`（`:530-589`），attempt 表做不可变审计。
- **取消三层**：PG `cancel_requested` 是唯一意图事实 → Redis key 0.2s 轮询加速 → PG 1s watcher 兜底，**读库失败 fail-closed 直接停执行**（`run_worker.py:184-211`）。
- **Durable Task**：claim 行锁 + 容量 advisory lock（`task_repository.py:181-228`）；`finish_owned` 在同一锁行事务里先跑领域 failure hook 再写终态、写完二次校验 owner 否则 rollback（`:307-351`）——文件中间态收敛与任务终态原子，杜绝跨 attempt 误伤。

**NV 现状**：
- 聊天 run 是 API 进程内的 `asyncio.create_task`（`api/endpoints/console.py:644`），断线靠进程内内存缓冲（每 session 500 事件 / TTL 600s，`:169-217`）做 `replay_from` 重放——**服务重启即丢全部在途**（代码注释自认 `:493`）；`/chat/stream` 旧链路断线直接 `task.cancel()`（`chat.py:374-383`）。无后端队列（前端本地 messageQueue）、无租约/心跳概念。
- **但模式对位物已存在**：`channels/channel_ingress_queue.py:1-16` 已经实现了 SQLite 持久化 FIFO + claim 租约 120s + max_attempts + dead-letter——即 Neurova 在渠道入站侧已经懂这套，只是从未推广到 AgentRun 与知识解析。
- Web Locks 跨标签页协调（sendlock 事故已修）解决的是浏览器侧并发，不是服务端。

**差距本质**：Yuxi 把"崩溃后世界会怎样"当作第一设计变量并用真 PG 并发测试锁死（`test_agent_run_lease.py` 19 个竞态用例：过期 owner 拒写、并发 reconcile 只失败一次、根终态原子取消子 run）；Neurova 的容错语义目前止步"进程活着时不丢"。

### 2.2 Agent 运行时与会话编排（Yuxi 8.5 / NV 6.5）

**Yuxi**：不造图节点，全押 LangGraph `create_agent` + DeepAgents middleware 洋葱（`buildin/chatbot/graph.py:34-66` 装配顺序 12 层）：Steer（插话在安全边界让位，`steer.py` 仅 37 行但 after_model 兜底防漏检）→ Filesystem 工具结果预算 → Skills → Memory → SubAgent → Summary → TodoList → PatchToolCalls → ModelRetry → 图片兼容 → TokenUsage → HumanInTheLoop。HITL 与持久化闭环：`interrupt()` 挂起 → checkpoint 落 PG → Run 终态 `interrupted` → resume 创建新 run 不重新进 FIFO。**SubAgent 共享 runtime_scope_id 命中同一沙箱与 Workdir**（`subagent_run_service.py:255-258`）、禁子生孙、父 `task` 工具超时时显式返回"仍在运行"而非假结果。弱点：每次构图全量重做（MCP 拉取+投影刷目录+DB 解析），graph 缓存实际不生效；DeepAgents 私有 API 强耦合（import 下划线函数）。
**NV**：ChatPipeline Step0~5（检索→Evocate→LLM 自动续写→后处理→广播 SessionSync）+ swarm 真工具接线（`builtin_tools.py:538` spawn_subagent）+ Team/ACP + workflow_agent 编译发布——功能面比 Yuxi 宽（Yuxi 无渠道无记忆温度），但缺 checkpoint/HITL/steer：无人在环路（无审批 middleware 对位物）、无运行中断恢复。步骤时间轴/产物卡片前端面 NV 反而先行。

### 2.3 上下文与 token 管理（Yuxi 8.0 / NV 7.5）——最接近的一维

Yuxi 四级递进压缩（`summary.py:163-298`）：历史工具参数截 2000 字符 → **超预算 ToolMessage 全文落盘 `outputs/large_tool_results/<tool>-<sha16>.txt`，上下文替换为含 SHA-256+路径+预览的存根** → LLM 五段式摘要（TAG_NOSTREAM 防回流前端）→ ContextOverflowError 兜底再摘；全程发 `context_compression` 事件给 UI。用量观测 30+ 字段快照、cache 命中/未命中分桶、Provider 黑名单。
NV 的活水池+compaction 四件套（09-09）+窗口统一入口已同水位，且**落盘存根这一级 NV 已有同位架构**（本次复核更正初稿口径）：写入侧 TOOL_CALL 归档（`context/orchestrator.py:837`）→ 驱逐台账 SQLite WAL+FTS5 持久（`context_pool.py:298-324`）→ 模型侧 `recall_history` 工具双源召回带循环防护（`tool_executor.py:2623-2642`）→ microcompact 老工具结果占位清除（`orchestrator.py:881-910`，保留最近 3 条原文）。真差距收窄为两点：
- **offload 时机在归档之前**：executor 各工具 `max_chars` 硬截断（如 `text[:8000]`、file 读 `[:50000]`，`tool_executor.py:2367,2785`）丢弃的尾部**从未进过池**——microcompact 注释"原文已由归档无损"只对"残文入池"成立，对工具原始输出不成立；Yuxi 是返回时全文落盘+存根，一条不丢。
- **占位不具寻址性**：NV 占位是固定字符串（无 turn_id/预览/hash），`recall_history` 只能靠模型猜子串查询；Yuxi 存根自带工具名+路径+SHA256+预览，模型所见即所寻。

### 2.4 技能体系（Yuxi 8.5 / NV 7.0）

Yuxi Skill=SKILL.md(frontmatter)+脚本/资源，索引在 PG；核心是**三层依赖工具门控**：构建期全量注册保可执行、每轮 `request.override(tools=)` 剔除未激活 skill 的依赖工具、**模型 read_file 命中 SKILL.md 即激活**（且 slug 必须在授权面内，防越权自激活，`middlewares/skills.py:215-217,254-269`）。用户 skill 投影同步用 进程锁+fcntl+PG advisory 三档锁 + no-follow SHA-256 树哈希 diff + 原子 rename + fail-closed 删除（`skills/service.py:341-432`）；远程 skill 在一次性无凭据沙箱安装。弱点：`skills/service.py` 1,823 行上帝模块。
NV 技能有进化闭环（skill_improver 731 行 + review gate C10 审批 + 肌肉记忆）——生态纵深独有；但 SKILL.md 门控/投影/版本哈希这些"装载工程学"没有对位物。

### 2.5 知识库与 RAG（Yuxi 8.5 / NV 7.0）

Yuxi Milvus 单 collection 内 BM25 sparse 向量（Milvus 内置 Function）+ dense IVF_FLAT/COSINE，三模式召回→WeightedRanker(0.7/0.3)→可选图 PPR 结果 RRF(k=60) 融合→rerank 重排→截断（`milvus.py:853-1052`）；外部 KB 抽象极干净：`ReadOnlyConnectors` 基类把约 20 个文档方法统一拒绝，新接入只需实现 `aquery`（Dify 167 行、Notion 763 行即全部成本）；解析 7 引擎能力注册表懒加载、PG+Milvus 双写带补偿回滚、文件状态机全走 CAS+owner。
NV 零依赖路线（JSON 条目+每用户 ONNX bge 向量文件+jieba/BM25/FTS5+0.4/0.4/0.2 加权融合+联邦多库 LLM 路由）在单机场景完成度不低，但 **rerank 的 model 通道"框架在、生产无装配点"**（`model_rerank_runner.py:3-6` 自述+全仓 grep 无接线）——恰是台账惯犯的"声明未接线"模式；且知识导入是请求内同步（`knowledge.py:881-943`），大会计文件阻塞 HTTP。
**Yuxi 的前车之鉴**：`aquery` 顶层 `except → return []`（`milvus.py:1050-1052`）、rerank 失败静默回退——零结果与后端故障不可分；embedding 模型换名直接 **drop collection 重建丢数据**（`:369-380`）。这两条都违反 Neurova 修复教义第 1/3 条，NV 接线时反着做：错误显式分型、模型漂移走 reindex 任务而非毁库。

### 2.6 知识图谱（Yuxi 7.5 / NV 6.5）

Yuxi 抽取→Neo4j MERGE + 实体/三元组向量入 Milvus 双栈，流水线三阶段 worker（抽取/写入/向量）+断点续跑+分段进度；Graph RAG 是真联动：实体召回构 PPR 种子→networkx personalized PageRank→chunk 打分→与向量 RRF。消解仅 lowercase+空白归一、MERGE 属性整体覆盖（`graph_utils.py:119-121`），中文场景弱点明显。
NV TKG（时效知识图谱 772 行，双时态）是 Yuxi 没有的维度，检索链也有 tkg_retriever 适配器（优先级 26）；弱点在 JSON 文件存储无并发防护、无图增强检索（PPR 类联动缺）。

### 2.7 多租户与权限（Yuxi 8.0 / NV 6.5）

Yuxi `share_config` v2：read/manage 两级 scope × global/department/user 三档 + manage⊆read 校验 + 按资源类型封顶（知识库普通用户≤READ）；三密钥（JWT/API-key 派生/沙箱 token）≥32 字符互不复用、启动前强制校验；API key HMAC 确定性派生+只存 SHA-256+request_id 幂等+撤销 tombstone 防重放；OIDC+CLI 设备码授权完整。弱点：可见性全部 Python 后过滤未下推 SQL（`agent_repository.py:313-331`）、**模型供应商 API key 明文进 PG+Redis**（`providers/cache.py:34,153-158`，与自家 API key 标准不一致）、JWT 无吊销通道。
NV 无部门/租户（产品定位单实例，5 角色组），但**凭据加密反而更强**：providers AES-256-GCM secret_store、外部 KB key Fernet、开放平台 key 哈希+scope+revoke——Yuxi 明文落盘那条 NV 已经做对了；NV 可补的是 API key 幂等创建+tombstone。

### 2.8 存储与 schema / 后台任务 / 沙箱（Yuxi 8.5/8.5/8.5 对 NV 5.5/6.0/5.5）

见 §0 与 §2.1。补充三个 NV 可低成本移植的点：
- **版本域 + 精确匹配拒绝启动**（`storage/postgres/manager.py:26-27,500-514`）：NV 的 db_migration 已有 PRAGMA user_version 骨架，缺"每库登记版本域+启动校验+防降级"闭环；
- **定时任务防重三唯一约束**（`(job_id,occurrence_key)`/request_id/thread_id，`models_business.py:995-1043`）+ `SKIP LOCKED` 领取 + stuck 恢复扫描——NV TaskScheduler 台账内存 dict 重启丢（本次实测确认）是同类问题的反面教材；
- **文件安全 openat 链**（`utils/paths.py` 逐组件 `O_DIRECTORY|O_NOFOLLOW` + fstat 复核 + temp `O_EXCL` + fd-rename + fsync）：NV 的 relpath 乱放事故（09-08）修的是语义层，Yuxi 这套原语是更底层的根治，SQLite 工作区目录可直接抄 `open_directory_fd/open_regular_file_fd` 两个函数。

### 2.9 评测（Yuxi 7.0 / NV 4.5）

Yuxi RAG eval：JSONL 数据集（query/gold_chunk_ids/gold_answer）→ P/R/F1@{1,3,5,10} + LLM Judge 二值 → 逐题评估、每 5 题 lease 事务内 checkpoint 可断点续跑；自动出题两模式（向量邻居 / graph_enhanced PPR 扩散选上下文）。弱点：无 MRR/nDCG、gold_chunk_ids 与分块命名强耦合（重分块即废数据集）。
NV benchmark 执行器 simulated 占位（`benchmark/__init__.py:415-418`）+API 层如实标注——诚实性合规，但评测能力=0。Yuxi 这套指标+数据集格式+自动出题是 NV benchmark 执行器接线的现成蓝本（纯 Python 可移植，不需要 Milvus）。

### 2.10 测试与工程纪律（Yuxi 9.0 / NV 7.5）

Yuxi 2,034 测试的含金量在"围绕并发正确性写"：lease fencing、过期 owner 拒写、terminal 事件与 DB 提交原子性竞态、幂等 schema 演进，全在真 PG 上跑（集成层直连 compose 栈），unit 层 sqlite 内存库+FakeRedis 分层纪律清晰。弱点：credentials 缺失即静默 skip、run_worker 测试重 monkeypatch 脆性高。
NV 的红绿灯 TDD+i18n 11 语守卫+防复活钉（channel 死壳）文化同类中罕见，但竞态测试与 CI 是空白。sendlock 事故的教训（"mock 须规范忠实否则假绿"）与 Yuxi 真库并发测试philosophy完全同向——值得把该原则从浏览器锁推广到全部锁/租约类代码。

### 2.11 前端（Yuxi 6.5 / NV 7.5）

Yuxi 值得抄的只有 SSE 工程：手写帧解析、**45s 无事件看门狗主动查 run 收口**（防 loading 永转）、`id:` seq 去重回退、localStorage active_run 快照（1h TTL）页面恢复续流、interrupted 态保留审批现场、grapheme 边界打字机平滑+prefers-reduced-motion 直通。其余全面落后：零 TS、零组件渲染测试、10 个 1,100+ 行巨型 SFC（AgentChatComponent 5,655 行）。NV 的 TS+vitest+三区导航+i18n 体系更工程化，dock 产物预览/步骤时间轴也是 Yuxi 没有的。

### 2.12 Neurova 独占资产（Yuxi 无对位物）

记忆温度生命周期（556 行真实衰减/结晶/遗忘）、7 类×3 型×4 信任源分类、L0-L3 渐进检索+MoE 门控、睡眠巩固、情绪四层 17 情感、进化闭环 9.9k 行（pattern mining/基因引擎/skill 改进/肌肉记忆/RSI）、NeurFlow DAG 引擎（层内并发/子流/检查点/NL 设计器/工作流转工具）、14 IM 渠道+入站持久队列、TTS/ASR 全链、桌面版+安装器、CUA 桌面自动化、11 语言 i18n。**注意**：本次实测更正 AGENTS.md 口径——"17 维分类"实为情感体系的 17 种情绪，MemoryCategory 是 7 个值（`memory_layer/models.py:26-34`）；`memory_layer/manager.py` 的 50+ 委托方法有自认 stub（独立子模块本体真实）。

---

## 3. 启发点清单（按性价比排序，遵守"只提升不下降"约束）

| # | 优先级 | 启发点 | Yuxi 证据 | Neurova 落点 |
|---|---|---|---|---|
| 1 | **P0** ✅ | **AgentRun 持久化状态机**：run/attempt 表+owner token+heartbeat+启动时 reconcile 收敛死 run——把 `channel_ingress_queue.py` 已有模式推广到聊天主链路，根治"重启丢在途+stream 断线 cancel+内存缓冲 replay"三连 | `agent_run_repository.py:390-589` | console.py 管线外壳（重放缓冲保持内存有界——Yuxi 事件流非持久是其弱点#5，列入不抄） |
| 2 | **P0** ✅ | **线程级单活+FIFO**：SQLite 同样支持部分唯一索引（`CREATE UNIQUE INDEX … WHERE status NOT IN (…)`），同 session 活跃 run 互斥由库强制，前端 messageQueue 语义后移到服务端 | `models_business.py:1257-1265` | chat/console 入站 |
| 3 | **P0** ✅ | **rerank 模型通道接线**：工厂/runner 都在，补一个 provider 装配点（llm_router 已有 rerank capability 映射）；同时按 Yuxi 反面教材保证检索/重排错误**显式分型**不吞成空结果 | 反面：`milvus.py:1050-1052` | `knowledge/rerank/model_rerank_runner.py` |
| 4 | **P0** ✅ | **schema 版本闭环**：db_migration 从只挂记忆库推广到全部 SQLite 库——每库版本域登记+启动精确校验+防降级拒绝打开 | `postgres/manager.py:26-27,500-514` | `core/db_migration.py` 接入面 |
| 5 | **P1** | **RAG 评估执行器**：P/R/F1@K+JSONL 数据集+自动出题（邻居采样），纯 Python 无依赖，直接让 benchmark 摘掉 simulated | `knowledge/eval/metrics.py`、`benchmark_generation.py` | `benchmark/` 执行器 |
| 6 | **P1** | **Offload 前移 + 存根寻址化**：NV 已有"池归档→FTS 台账→recall_history→microcompact 占位"闭环（初稿误判为缺，已复核更正），真缺口两处——① executor `max_chars` 硬截断改"全文入池/落台账、消息体留存根"（被截尾部现状永久丢失，违背归档无损语义）；② 占位串补 turn_id+预览，recall_history 从猜子串变按指针直取 | `summary.py:591-626` | `tool_executor.py` 截断点 + `orchestrator._clear_old_tool_results` |
| 7 | **P1** | **Skill 依赖工具三层门控**：构建期全注册、每轮按激活集剔可见、read SKILL.md=激活（带授权面校验防自激活） | `middlewares/skills.py:103-141,215-269` | skills 体系/tool 装配面 |
| 8 | **P1** | **取消语义升级**：stop 先落 DB durable 意图，执行侧轮询消费；**读状态失败 fail-closed 停执行** | `run_worker.py:184-211,567-574` | task_tracker + stop 端点 |
| 9 | **P1** | **知识解析 Durable Task 化**：上传即入队（claim+heartbeat+failure hook 同事务收敛文件错误态），导入不再阻塞请求；文件状态迁移全走 CAS | `task_service.py:414-533`、`knowledge_file_repository.py:807-826` | `knowledge.py:881-943` 同步链 |
| 10 | **P2** ✅ | **openat 文件原语移植**：逐组件 `dir_fd+O_NOFOLLOW+fstat` 两函数直接可用于 agent_workspaces 防符号链逃逸 | `utils/paths.py:8-78` | workspace_files/沙箱层 |
| 11 | **P2** ✅ | **定时任务防重**：三唯一约束+到期领取+stuck 恢复扫描；TaskScheduler 台账落库（现状重启丢） | `models_business.py:995-1043` | `agent/scheduler.py` |
| 12 | **P2** ✅ | **API key 幂等+tombstone**：request_id advisory（SQLite 用 BEGIN IMMEDIATE 即可）+撤销保留行拒重放 | `api_key_repository.py:114-188` | openplatform_keys |
| 13 | **P2** ✅ | **竞态正确性测试层**：为 #1/#2/#9 新表写真库并发用例（过期 owner 拒写/单赢家/原子收敛）；"mock 须忠实"原则推广到锁类代码 | `test_agent_run_lease.py` | tests/integration |
| 14 | **P2** ✅ | **model/tool 审计与历史分离**：`model_audit/tool_audit` 类型消息不进普通历史与计数，调试面板走受控独立有界读接口 | `run_worker.py` 事件映射 | 步骤时间轴/DebugPanel |
| 15 | **P2** ✅ | **配置表单单源生成**：dataclass/pydantic metadata 反射出查询参数与配置面板契约（NV 睡眠设置/负一屏多次键位契约漂移的根治法） | `milvus.py:84-282` | SettingPage 系 |

**不抄清单**（Yuxi 自身弱点，Neurova 现状或策略更优）：全量 PG/Redis/Milvus 栈（违背零依赖桌面产品定位）；可见性 Python 后过滤（NV 规模小暂不痛，但新表设计时预留 SQL 谓词位）；模型 key 明文落盘（NV 的 AES-GCM 更强）；事件流只存 Redis 非持久；`run_worker` 640 行巨函数、`skills/service` 1,823 行上帝模块、死代码不删（context.py/dynamic_tool.py）；图谱 MERGE 属性覆盖；JWT 无吊销。

---

## 4. 结论

1. **总体**：Yuxi 7.3 / Neurova 6.8。拆开看是两个物种——平台工程 16 维 Yuxi **8.1 对 6.5** 显著领先，产品广度 Neurova **8.3 对 1.0** 压倒性领先。与 OpenClaw 报告结论同构：又一面"镜像"，这面镜子照的不是认知系统（那块 NV 无对手），而是**执行持久性/并发正确性/schema 治理**这条 NV 最薄的板。
2. **NV 最值钱的三条**按序是 #1 AgentRun 持久化（顺带 #2 线程 FIFO、#8 取消三层——同一张表族一次解决）、#4 schema 版本闭环（骨架已有、只差接入面）、#5 RAG 评估执行器（benchmark 摘 simulated 的第一条真路）。全部可在 SQLite+单进程内移植 Yuxi 语义而不引入任何新依赖——Yuxi 的实现证明这套状态机不依赖 PG 特性里的独家货（部分唯一索引、CAS、SKIP LOCKED 在 SQLite 均有等价物，仅并发上限不同）。
3. **对 NV 现有文化的验证**：Yuxi 的"失败钩子同事务收敛""错误不静默""先落库再投递"与 Neurova 修复教义逐条同构；它的教训面（吞错返回空列表、drop 重建、明文 key、死代码）恰是教义禁止的反例——说明这套教义方向正确，缺的是把锁/租约类代码纳入强制竞态测试的范围。

---

## 5. 复核修订纪实（2026-09-13 评审轮）

> 触发：当日 P0（四条）/P2（六条）实施改变了 NV 侧多项事实；评审对 Yuxi 侧关键论断做源码抽查、对 NV 侧逐条重新核实。**原 §0-§4 保留为首评快照不回改**，勘误与本节为准。

### 5.1 Yuxi 侧抽查复核（8/8 属实）

| 关键论断 | 锚点 | 复核 |
|---|---|---|
| 线程级单活=部分唯一索引（库层强制） | models_business.py:1257-1265 | ✅ 属实（`postgresql_where`+`sqlite_where` 双形态，NV 移植的正是后者语义） |
| 每 attempt 全新 owner token | run_worker.py `_run_owner_token` | ✅ worker identity + uuid4 |
| rerank 失败静默回退 + aquery 顶层吞错 return [] | milvus.py:1044-1052 | ✅ **不抄清单**该条成立 |
| embedding 换名/缺 BM25 → drop collection 重建 | milvus.py:366-380 | ✅ 且匹配靠 description 字符串包含，原文"脆弱且危险"成立 |
| 模型供应商 api_key 明文进 ModelInfo/Redis | providers/cache.py:33-35 | ✅ `api_key: str` 原样序列化 |
| 后端测试规模 2,034 | `def test_` 计数 | ✅ 实测 2,033（差 1 忽略） |
| chatbot middleware 洋葱装配顺序 | buildin/chatbot/graph.py:34-66 | ✅ Steer→Filesystem→Skills→Memory→SubAgent→… |
| Durable Task `finish_owned` 领域 hook 同事务 | task_repository.py:307+（before_finish/before_cancel 参数） | ✅ |

### 5.2 NV 侧失效表述 → 实施后现状

| 位置 | 首评表述 | 现状（09-13 实施轮后） |
|---|---|---|
| §0 Schema 治理行 | "db_migration 只接入记忆库 1 个" | 已按域注册（memory/agent_runs/channel_ingress 三域）+ SchemaVersionError 防降级；**剩余**：大量 JSON 配置文件（providers/keys/scheduler 台账）不在版本域体系内 |
| §2.1 NV 现状 | "无后端队列、无租约/心跳、重启丢全部在途" | `agent_run_store.py`+console `_AgentRunLedger`：先落库再执行、部分唯一索引单活、FIFO queued 事件、owner 栅栏心跳、启动收敛（process_died/server_restart）、6 真并发竞态测试；**剩余**：run 执行仍随进程死（无独立 worker，重启语义=收敛而非续跑）、`/v1/chat/stream` 次链路未接、重放缓冲仍内存 |
| §2.5 | "rerank model 通道框架在生产无装配点" | `llm/rerank_client.py`（/rerank 协议+RerankConfigError/BackendError 分型）+ `rerank_note` 响应透出 + to_thread；**剩余**：知识导入仍请求内同步 |
| §2.7 | "NV 可补的是 API key 幂等创建+tombstone" | openplatform_keys 已补（落盘+request_id 幂等+撤销/删除 tombstone 防重放）；**评审新发现**：`nrv_` 密钥全仓**无验证消费方**（签发吊销链完整、用键认证未接线）；`api/api_key_manager.py` 为零消费孤岛库 |
| §2.8 三点 | 缺版本域/台账落库/openat | 三点全落地（safe_paths.py 跨平台组件级 symlink/junction 拒绝 + workspace_files 单源接线；TaskScheduler 台账 JSON 原子落盘六写点）；**剩余**：定时任务防重三唯一约束/SKIP LOCKED 式领取未做（单进程下优先级低） |
| §2.10 | "NV 竞态测试空白" | store 层 6 真线程竞态用例在位；CI 仍空白 |
| §0/§2.10 测试基线 | "1,471+deep 1,197+channels 391" | 09-13 实测：unit/core 1753、unit/api 1494、channels 387、knowledge 146 全绿（新增 85 用例后） |

### 5.3 修订评分（NV 侧；Yuxi 列不变）

| # | 维度 | Yuxi | NV 首评 → 修订 | 依据 |
|---|---|---:|---|---|
| 3 | 执行持久性与并发正确性 | 9.5 | 5.5 → **7.0** | 状态机+库层单活+竞态测试到位；无执行续跑/checkpoint，封顶 7 |
| 7 | 知识库与 RAG | 8.5 | 7.0 → **7.5** | rerank 接线+分型；同步解析、无模型 rerank 内置权重 |
| 9 | 权限治理 | 8.0 | 6.5 → **6.5** | keys 幂等/tombstone 补上，但认证消费断链暴露抵销加分 |
| 10 | 后台任务与调度 | 8.5 | 6.0 → **6.5** | scheduler 台账落库；防重约束未做 |
| 11 | 存储与 schema 治理 | 8.5 | 5.5 → **7.0** | 域化+防降级；JSON 文件群未纳管、无统一迁移进程位 |
| 12 | 沙箱与文件安全 | 8.5 | 5.5 → **6.5** | openat 原语+接线；执行沙箱仍缺 |
| 14 | 测试与工程纪律 | 9.0 | 7.5 → **7.8** | 竞态层+防复活钉改行为级断言；无 CI |
| | 平台工程 1-16 均值 | 8.1 | 6.5 → **6.8** | |
| | 18 维总评 | 7.3 | 6.8 → **7.0** | 产品广度两维不变 |

差距从 0.5 收敛到 0.3。**"差距最大维度"表述仍成立**（3 维 2.5 分差为全表之最），但性质变了：从"机制缺失"变为"裁剪深度"——NV 缺的续跑执行/独立 worker/HITL checkpoint 是形态约束（单进程零依赖），不是工程纪律欠账。

### 5.4 锚点勘误

console.py 因 ledger 插入行号平移：`create_task(run_chat())` 644→**771**；重放缓冲 `:169-217`→**`:171-218`**；`_AgentRunLedger` 新类 `:224`；`get_recent_context` 角色白名单 `session_manager.py:747`。附录"对位锚点"以本勘误为准。

### 5.5 评审总结论

1. 首评的 Yuxi 侧全部关键论断经抽源码复核成立，锚点可信；"不抄清单"维持。
2. NV 侧首评判断被当日实施验证为**可移植且已移植**（部分唯一索引/CAS/租约/防降级/openat 语义在 SQLite+Windows 全部有等价物），首评"落后一个量级"的表述对当前状态应修正为"最薄板块已从机制缺失降为形态约束"。
3. 真正剩余的真差距只有三块，全部需要**形态决策**而非代码移植：独立 worker 的执行续跑（P1 #9 的 Durable Task 化可解知识解析一块）、HITL/checkpoint 人在环路、CI/CD 纪律；外加两个本评审新登记的断链——nrv_ 密钥认证消费、api_key_manager 孤岛库。
4. 启发清单执行进度：**P0 4/4、P2 6/6 已实施；P1 0/5**（#5 RAG 评估执行器、#6 offload 前移+存根寻址、#7 skill 门控、#8 取消三层完整体、#9 知识解析 Durable 化），#5 是下一性价比之王。

---

## 附：主要证据文件索引

**Yuxi**（根 `backend/package/yuxi/`）：
- 运行时：`services/run_worker.py`（1,616 行，lease/取消/reconcile）、`services/agent_request_queue_service.py`（998 行）、`repositories/agent_run_repository.py`、`storage/postgres/models_business.py:1133-1402`（Run/Attempt/Request 表+索引）
- 编排：`agents/middlewares/`（summary.py 864、token_usage.py 591、subagent_task.py 543、skills.py 342）、`agents/buildin/chatbot/graph.py:34-66`、`services/subagent_run_service.py`
- 知识：`knowledge/implementations/milvus.py`（1,355 行）、`knowledge/graphs/milvus_graph_service.py`、`knowledge/eval/`、`knowledge/chunking/ragflow_like/`
- 治理：`permissions/resource_permission.py`、`utils/auth_utils.py`、`services/task_registry.py`、`storage_migration.py`
- 安全：`utils/paths.py`（openat 链）、`workspace/filesystem.py`、`agents/backends/sandbox/backend.py`（1,261 行）
- 测试：`backend/test/integration/services/test_agent_run_lease.py`、`test_durable_task_repository.py`、`test_agent_request_queue_concurrency.py`

**Neurova**（对位锚点）：`neurova/api/endpoints/console.py:169-217,491-520,644,715-730`、`neurova/channels/channel_ingress_queue.py`、`neurova/agent/chat_pipeline.py`、`neurova/knowledge/rerank/`、`neurova/core/db_migration.py`、`neurova/agent/scheduler.py:662-717`、`neurova/benchmark/__init__.py:415-418`、`neurova/cognitive_layers/memory_layer/`
