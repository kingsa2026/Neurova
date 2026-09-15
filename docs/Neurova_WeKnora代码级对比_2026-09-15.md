# Neurova × Tencent/WeKnora 代码级对比与实施记录（2026-09-15）

> 研究对象：https://github.com/Tencent/WeKnora （v0.8.0，Go 主服务 + Python docreader gRPC sidecar，MIT 协议）
> 对比基线：Neurova 知识库（`neurova/knowledge/` 3957 行 + 认知层 KG + chat 检索链，JSON 存储，单进程桌面优先）
> 方法：WeKnora 全仓浅克隆三路深读（摄取/检索治理/数据源）+ Neurova KB 穷尽摸底；P0×5 + P1×7 + 待拍板×4 全部落地，TDD 先红后绿。
> ⚠️ 本文件为未跟踪文档，**已被共享工作区的并行 git 清理操作删除两次**——请尽快随代码一并提交。

## 1. 定位差异（对比第一前提）

WeKnora = 企业自托管 RAG 框架：固定 10 段事件管线 quick-QA、ReAct Agent、Wiki Mode（agent 蒸馏互链 Markdown+反链图+修订回滚）、8+ 数据源连接器、4 档 RBAC、capability API Key、9 种向量库、Langfuse 观测。部署最低形态 PG+Redis 六容器。

Neurova = 单进程桌面个人智能体。结论：**只抄机制、不抄架构**。

| 维度 | WeKnora | Neurova |
|---|---|---|
| 形态 | Go 集群 + Python sidecar | FastAPI 单进程全本地 |
| KB 模型 | KB→Knowledge→Chunk(13 型) SQL 行级 | repo→entry→chunks[]/parents[] JSON |
| 检索 | 事件管线 query 理解→多库扇出→RRF→rerank→注入 | MemoryRetrievalChain 优先级链，知识=补充源（记忆优先知识必查） |
| 引用 | modelcontext 句柄编解码+资格分离+流式解码 | `<memory_citation/>`（本会话升级为句柄+资格+流式缓冲） |
| 治理 | RBAC×组织共享×路由表 Key | 条目级 visibility+审核+Fernet 托管+SSRF 逐 IP |

## 2. 关键机制差距 → 已移植项（详单见 §7/§8）

- **切分**：WeKnora 三层自适应策略链+validator 回退+语义 overlap+表头零宽注入+ContextHeader 持久化+父子分块（parent 不入向量）。Neurova 原单层固定窗口。
- **索引**：per-chunk 增量重索引（O(1)/编辑）vs Neurova 原库级脏标记全量重建。
- **融合**：加权 RRF+跨引擎分数归一+「RRF 分数域 [0,~0.033] 禁止阈值再过滤」。
- **Rerank**：12 阶段清洗（代码/公式拆壳使其可被判相关）、阈值 0.7× 降级（floor 0.3）、复合分 0.6model+0.3base+0.1source、MMR λ=0.7。
- **引用**：长 ID→短句柄（cN/dN/wN）编解码、引用资格分离（仅本轮检索证据可引用）、流式后缀缓冲。
- **数据源**：游标=完整快照、失败不推进、partial 抑制删除、多副本去重（Neurova 单进程简化为线程互斥）。
- **记忆信任**：pending-until-confirm、遗忘墓碑 ErrPreviouslyForgotten、NormalizedKey 无 LLM 覆盖（Neurova 按保守折叠键实现）。
- **观测**：knowledge_processing_spans 阶段树+三段式 stop-parse+DLQ 重放。

## 3. WeKnora 亮点机制速记（未抄但值得知道）

`ReadStream` 逐帧传图防爆 gRPC 上限；PDF 逐页图像面积占比判扫描页+隐藏文本抗注入+跨页重复 MD5 判水印；队列拓扑单源注册表（服务器/仪表盘/取消共用）；ZSET 租约信号量 fail-open；resource:// 句柄目录+owner 引用计数 GC；wiki map/reduce+debounce finalize 收敛+pg_trgm 预筛防幻觉合并；registry self-healing（singleflight+generation counter+冷却）；prompt cache 指纹跨 provider 策略表。

## 4. 评分（实施后口径）

解析摄取 9/5（不抄）；切分 9/4.5→**7**；索引 8/6→**8**；检索融合 9/6→**8**；引用上下文 9.5/5→**7**；治理 9/7；数据源 9/4→**6.5**；记忆 8/8→**8.5**；观测 9/4→**6**；桌面适配 3/9。WeKnora 总评 8.7 对 Neurova 6.0→**7.2**。

## 5. Neurova 领先项（勿对齐回去）

记忆-知识分层仲裁、索引层物理分片隔离、条目级 tombstone/冲突/revisions 三账本、unpublish-vs-purge 语义、Fernet+has_api_key 不回显+SSRF 收紧、知识进睡眠/情绪/元认知回路的认知整合度。

## 6. 顺带根治的预存 bug（本会话）

1. `knowledge_integration.py` HTTPException 未 import（501 崩 500）——已修+诚实 501 钉死。
2. `UnifiedVectorStore.index_memories` 非增量重建用清空前 existing_ids → 未变更文档静默丢出索引（KB 全量重建必踩）——已修。
3. 增量分支 `_update_idf(new_docs)` 整体重置 IDF 至"仅新文档"统计 → 老词项清零、存量向量不可达（记忆侧同踩）——`_extend_idf` 累积修复。
4. `_rebuild_indexes` 只重建传入 agent 分组 → 其他 agent 条目被清出索引——改全库遍历。
5. TF-IDF 对字母数字混合词（BatchTerm2/2024）失明+score floor 交互——索引零命中回 substring 兜底。
6. 内容更新不重切 chunks → 旧块污染索引与块命中——update 时同步重切（父子模式用 build_entry_chunks）。
7. graph_bridge 回写 graph_node_ids 触发全库重建——索引操作只认 title/content 变更。

## 7. 实施清单（P0×5 + P1×7）

| 项 | 落点 | 测试 |
|---|---|---|
| #2 切分精修（英文句界/围栏原子/表头注入/build_index_content 单源） | `knowledge/splitter.py` | test_splitter_v2_weknora (12) |
| #1 索引增量（操作队列+分片级 remove/add+阈值回退） | `knowledge/repository.py`、`unified_vector_store.py` | test_knowledge_index_incremental (13) |
| #4 双索引器合一（hybrid 四路 RRF，chat 路语义首入；API bm25/rrf 委托单源） | 新 `knowledge/hybrid.py`、`knowledge_retriever_adapter.py`、`semantic_search_api.py` | test_hybrid_service (14) |
| #3 rerank 四连（清洗/阈值降级/复合分/MMR，端点 opt-in 默认关） | 新 `knowledge/rerank/refine.py` | test_rerank_refine_weknora (24) |
| #5 引用句柄+资格分离（CitationRegistry/decode_citation_handles） | `memory/citation.py`、chat_pipeline、orchestrator | test_citation_registry_weknora (11) |
| #6 父子分块（子进索引父回传 context_passages，build_entry_chunks 单源） | splitter/repository/adapter/knowledge.py | test_parent_child_chunking (7) |
| #7 切分 live-preview 端点（只读+护栏+单源） | `POST /knowledge/preview-chunking` | test_knowledge_preview_chunking (5) |
| #8 块编辑乐观锁（expected_revision/追加账本/自动重索引/PUT+GET chunks） | repository.update_chunk + 3 端点 | test_chunk_editing (8) |
| #9 飞书正文同步（raw_content 修只回标题；游标三契约；`POST /configs/{id}/sync`） | adapters、新 `knowledge/datasource_sync.py` | test_feishu_sync (13) |
| #10 同步并发互斥（config_sync_lock 非阻塞→409） | datasource_sync | 同上 |
| #11 记忆信任（confirm 门钉测；content_tombstones 双道拦截+forget 端点登记；normalized_key 确定性覆盖） | `memory/pending_memory.py`、endpoints/memory/pending.py | test_pending_forget_tombstone (8) |
| #12 摄取 span+cancel（spans 表/ack-nack-dead 守卫/`POST /ingress-tasks/{id}/cancel`） | `ingest_queue.py`、`ingest_worker.py`、knowledge.py | test_ingest_spans_cancel (10) |

## 8. 待拍板四项接续轮（同日完成）

- **① integration 收口**：sync/* 落 `KnowledgeStorage.memory_links`（持久，缺 id 不合成假关联）；`/rag/retrieve`、`/rag/batch` 接真实两路（记忆 recall+知识 repo，单源故障只降级该源）；`/gaps/analyze`、`/learn` 维持诚实 501；`/evolution/progress` 读真计数；sync 端点 adapter 装配 api_key→app_secret 映射。测试 wired(6)+honesty(2)。
- **② NormalizedKey**：`normalized_key/find_supersede_ids/supersede_same_key`（NFKC+小写+去说话人前缀+剔标点，全等才覆盖；无 LLM/embedding）；confirm 落库前同键旧活跃记忆软遗忘，漏覆盖不阻断入库。并入 test_pending_forget_tombstone(+3)。
- **③ 前端+定时器**：配置弹窗飞书行"立即同步"（409 如实透出）+ 创建表单同步间隔字段；条目"分块"弹窗（编辑/乐观锁 409 自动重载/修订历史）；knowledge.ts +5 API；后端 `compute_due_configs/tick_feishu_sync/run_feishu_sync_loop`（单配置故障隔离）+ app.py 装配（`NEUROVA_KB_SYNC=off` 停用；未配间隔=空转）；i18n 11 语×11 键。守卫：locale 35 绿、页面挂载 21 绿、vue-tsc 0 错。
- **④ 流式缓冲**：`StreamCitationBuffer`（feed/flush：完整标记按 registry 解码、半截挂起、流结束前缀不丢字）；接 `_call_loop_stream`/`_call_legacy_stream`，**门控本轮有句柄才启用**（无句柄轮次逐字节旧行为）；流式族 62 测零回归。

## 9. 验证与登记

回归：knowledge 259 / agent+context 1595 / memory 1097 / api 附加 57 / 前端 35+21+tscheck——全绿。
**非本会话失败归属**（mtime 实据，并行会话在途）：sleep 阶段 6、graph_llm_bridge 3、public_library_wave_h3 7、skill_pool 2、growth wave H0 红测 1——本会话未触碰其文件，不代修。
**遗留观察**：块编辑对父子模式的 parent 叠加重建（WeKnora rebuildParentContent）未做——子块 content 已是权威副本，父上下文暂为原文；如需编辑可见于父回传，另立需求。`/knowledge-integration/*` 前端旧模块路径与后端仍不一致（零消费者死码），删除或重写待拍板。
**纪律**：新测试文件与本报告均须 `git add -f`（tests 目录 gitignore），随本轮改动提交以免共享区 clean 事故三度吞档。

## 10.1 提交与核验记录（同日，commit `4448c54a`，54 文件 +5349/-458）

- **共享区安全**：提交前 `git diff --cached` 发现并行会话暂存 46 文件（docs 比对批删除）——用 `git commit --only <paths>` 精确提交，对方暂存原样保留；提交范围复核零并行域文件（前端死模块 `knowledge-integration.ts` 已删除并摘 index.ts 导出）。
- **HTTP 层闭环冒烟**：真实 `create_app()` + TestClient，11 个新/改端点（preview-chunking / chunks GET·PUT·revisions / configs sync / ingress-tasks cancel / integration rag·sync·501 / semantic hybrid）全部 401 鉴权生效、**零 404 零装配异常**。
- **前端闭环**：`npm run build`（vue-tsc 全量 + vite 产物）通过；i18n 守卫+页面挂载 56 测绿（修复 fr/it 撇号转义、previewResult 类型收紧 2 处提交前 TS 错）。
- **提交自洽核验**：从 HEAD 建干净 worktree 跑本轮全部核心套件 → **310 passed**（提交不含任何未提交依赖）。唯一收集错为**历史遗留断链**：HEAD 旧测试 `test_pending_memory.py` → `neurova.web_reach.credentials`——web_reach 为早前 Agent-Reach 会话的未跟踪目录（[[neurova-agent-reach-integration]] 记录「须一起提交」），主工作区有该目录故全绿，与本轮提交无关，登记待其会话入库。
- **全量归属复核**：unit 主跑 governance 一次顺序 flake（单跑/复跑均绿）；api 目录 4-5 失败集中在 `test_my_skills_wave_v`/`test_transfers_wave_h4`（并行会话本会话内新建的在途测试）——零涉及本轮文件。**待拍板登记**：块编辑→父块叠加重建、ingress span 的前端可视化（当前 API 就绪）为下批候选。
