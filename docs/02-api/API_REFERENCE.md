# Neurova API 接口文档

> **版本**: v1.0.0-beta1 | **基础路径**: `/api/v1` | **协议**: HTTP/HTTPS | **数据格式**: JSON  
> **最后更新**: 2026-11-19（核对基准 2026-11-19：端点模块数取 `neurova/api/endpoints/__init__.py` 的 `ENDPOINT_MODULES` 注册表行数；端点总数按各端点文件 `@router` 装饰器实测计数） | **端点模块**: 96 个 | **端点总数**: 1250

## 通用说明

**响应格式**: `{"code": 0, "data": {}, "message": "success", "request_id": "uuid"}`

**认证**: `Authorization: Bearer <token>` (JWT Token, 部分端点支持 API Key)

**分页**: `limit` (默认50), `offset` (默认0)

---

## 一、核心功能 (15模块)

### 1. `/api/v1/health` — `health.py` | 多数公开（`POST /checks/{name}/run` 需认证）
- `GET` 系统健康检查 | `GET /checks` 检查项列表 | `GET /checks/{name}` 单项状态 | `POST /checks/{name}/run` 手动执行检查（需认证，`health.py:135`） | `GET /report` 健康报告 | `POST /recover` 恢复

### 2. `/api/v1` — `home.py` | 需认证（路由级 `get_current_user`）
- `GET /home/data` 首页概览 | `GET /home/trends` 趋势 | `GET /stats/system` 系统统计

### 3. `/api/v1/chat` — `chat.py` | 需认证（逐路由 `get_current_user`）
- `POST` 发送消息 | `POST /stream` 流式SSE | `GET /history` 对话历史 | `DELETE /history` 清空历史 | `POST /attachment` 上传附件 | `GET /tts-audio/{agent_id}/{filename}` 获取TTS音频

### 4. `/api/v1/agents` — `agent.py` | 需认证
- CRUD: `GET` 列表 | `GET /{agent_id}` 详情 | `POST` 创建 | `PUT /{agent_id}` 更新 | `DELETE /{agent_id}` 删除
- 扩展: `GET /{agent_id}/stats` 统计 | `POST /{agent_id}/switch` 切换默认 | `POST /{agent_id}/decision` 决策 | `POST /{agent_id}/rebuild-loop` 重建循环
- 同前缀注册模块（`ENDPOINT_MODULES` 同挂 `/v1/agents`）：`agent_package.py`（`GET /{agent_id}/export-package` 导出包 | `POST /import-package` 导入包）、`agent_migration.py`（`GET /{agent_id}/export-migration` | `POST /import-migration`）、`agent_checkpoints_api.py`（`GET /{agent_id}/checkpoints` 检查点列表 | `POST /{agent_id}/checkpoints/{ref}/restore` 事务化恢复）
- 宪法/性格**不在本面**：constitution_router / personality_router 由 `growth.py:42-43` 并入 `/api/v1/growth`（`GET/PUT /growth/constitution`、`/growth/constitution/rules*`、`GET/PUT /growth/personality` 等，见 §20）（2026-11-19 核对）

### 5. `/api/v1/auth` — `auth.py` | 公开（`GET /me` 需认证）
- `POST /login` 登录 | `POST /refresh` 刷新Token | `POST /logout` 登出 | `GET /me` 当前用户(需认证) | `GET /setup-status` 初始化状态 | `POST /recover-password` 找回密码 | `POST /register` 注册 | `POST /register/send-code` 发验证码 | `POST /register/verify-code` 验证 | `POST /register/invite` 邀请注册

### 6. `/api/v1/memory` — `memory/`（包；共享 router 见 `memory/base.py`） | 需身份（`requireIdentityForMemoryFace`）
- **主CRUD**（`crud.py`）: `GET` 搜索/列表 | `POST` 添加 | `GET /{memory_id}` 详情 | `PUT /{memory_id}` 更新 | `DELETE /{memory_id}` 删除 | `GET /stats` 统计 | `GET /hot` 高温记忆 | `GET /crystallized` 固化记忆 | `POST /decay` 温度衰减 | `POST /compress` 压缩 | `GET /relations/{memory_id}/traverse` 关系遍历 | `GET/PUT/DELETE /management/{memory_id}` 管理通道
- **子模块** (均挂 `/api/v1/memory` 下):
  - `working_memory.py` -> `POST /wm/turns` | `GET /wm/context` | `POST /wm/compress` | `POST /wm/plans` | `POST /wm/plans/retrieve` | `POST /wm/plans/result` | `GET /wm/stats` | `DELETE /wm` 清空
  - `emotion.py` -> `GET /emotion/summary` | `GET /emotion/distribution` | `POST /emotion/analyze` | `GET /emotion/types` | `GET /emotion/timeline` | `GET /emotion/{emotion_type}`
  - `profile.py` -> `GET/PUT /self-model` 自我模型 | `GET/PUT /users/{user_id}/profile` 用户画像
  - `metacognition.py` -> `POST /meta/monitor|reflect|optimize|evolve-skills` | `GET /meta/health` | `GET /meta/reflection` | `GET /meta/should-monitor|reflect|optimize|evolve` | `GET /meta/skills` | `GET /meta/skills/stats` | `POST /meta/skills/match` | `GET /{agent_id}/metacognition` | `GET /{agent_id}/metacognition/stats`
  - `tkg.py` -> `POST /tkg/facts` | `POST /tkg/query` | `GET /tkg/history/{entity}/{relation}` | `GET /tkg/stats`
  - `eki.py` -> `POST /classify` | `POST /classify-and-remember` | `GET /eki/status` | `POST /eki/process` | `GET /eki/decay/{memory_id}` | `GET /eki/strength/{memory_id}` | `GET /eki/statistics` | `POST /eki/batch-update` | `PUT /eki/config` | `PUT /eki/enable`
  - `markdown.py` -> `GET /markdown` 导出 | `POST /markdown` 写回
  - `pending.py` -> `GET /pending` | `GET /pending/decisions` | `POST /pending/{pending_id}/confirm` | `POST /pending/{pending_id}/reject`
  - `visibility.py` -> `POST /reload` 跨进程对账
  - `lineage.py` -> `GET /{memory_id}/lineage` 世代链
  - `versions.py` -> `GET /{memory_id}/versions` | `POST /{memory_id}/rollback`
- `questions.py` 已退役删除，questions 现役面在 `/api/v1/growth/questions`（`growth.py:449-557`）；`reflection.py` 不在代码中（2026-11-19 核对）

### 7. `/api/v1/models` — `model.py` | 需认证
- `GET` 列表 | `PUT/DELETE /{model_id}` 更新/删除 | `POST /detect-capabilities` 能力探测 | `GET /by-capability` 按能力筛选 | `GET /active` 当前激活 | `POST /switch` 切换 | `POST /probe-multimodal` 多模态探测 | `POST /probe-output-limit` 输出上限探测 | `POST /check-connection` 连通性检查 | `GET /pending-downloads` 待完成下载 | `GET/POST /download-source` 下载源 | `POST /download` 下载 | `GET /download-progress` 下载进度

### 8. `/api/v1/providers` — `provider.py` | 需认证
- CRUD: `GET` 列表 | `POST` 创建 | `GET/PUT/DELETE /{provider_id}`
- 模型操作: `POST /activate-model` 激活模型 | `GET /active-model` 当前激活 | `GET /scopes` 作用域 | `GET /{provider_id}/models/discover` 发现模型 | `GET /{provider_id}/models/series` 系列 | `POST /{provider_id}/models/filter` 过滤 | `POST /{provider_id}/models/discover/merge` 合并发现结果 | `POST /{provider_id}/check-connection` 连通性检查

### 9. `/api/v1/skills` — `skill.py` | 需认证（路由级）
- `GET` 列表 | `GET /{skill_id}` 详情 | `POST /{skill_id}/execute` 执行 | `PUT /{skill_id}/enable` 启用 | `PUT /{skill_id}/disable` 停用 | `GET /stats` 统计 | `POST /learn` 学习 | `GET /tips` 提示

### 10. `/api/v1/settings` — `settings.py` | 需认证（写面另加管理员门）
- `GET/PUT` 系统设置 | `GET/PUT /{key}` 单键读写 | `GET/POST /ssh-credentials`、`DELETE /ssh-credentials/{host}` SSH凭据 | `GET/POST /rdp-credentials`、`DELETE /rdp-credentials` RDP凭据 | `GET/PUT /cors` CORS配置 | `POST /clear-cache` 清缓存
- 「某个用户默认看什么语言」**不在这一面**（§6-167 退役）：`general.language` 与平铺 `language` 两个键都已摘掉，写它们回 **400 并给出去处**，读它们回 **404**；起点改由 `/api/v1/language/preferences/default`（写面仅管理员）承载
- 实测（活体 `tests/manual/languageFace_outOfBox_batch167.py` 第 [31]/[32]/[33] 项）：无凭证 `GET /settings` 与 `GET /settings/{key}` 都是 **401**，带凭证读一个不存在的键是 **404**——本行原先写的是「无认证」，与本批动过的那个面不符，按读数改；**附录里其余模块的「无需认证」整表仍未逐模块复核**（§6-158 留的那笔账一寸没变）

### 11. `/api/v1/logs` — `logs.py` | 需认证（路由级）
- `GET` 系统日志 (level, limit, start_time, end_time) | `POST /search` 搜索 | `GET /levels` 日志级别 | `DELETE` 清空（管理员）

### 12. `/api/v1/stats` — `stats.py` | 需认证
- `GET` 总览 | `GET /system` 系统统计 | `GET /agents` Agent统计 | `GET /token-usage` Token用量 | `GET /usage-overview` 用量总览 | `GET /provider-usage` 供应商用量 | `GET /usage` 用量 | `GET /performance` 性能 | `GET /export` 导出

### 13. `/api/v1/monitor` — `monitor.py` | 需管理员（`require_admin`）
- `GET /status` 系统状态 | `GET /resources` 资源占用 | `GET /connections` 连接 | `GET /alerts` 告警 | `POST /alerts/{alert_id}/resolve` 处理告警

### 14. `/api/v1/scheduler` — `scheduler.py` | 需认证
- `GET /status` 调度器状态 | `GET/POST /tasks` | `GET/PUT/DELETE /tasks/{task_id}` | `POST /tasks/{task_id}/run|pause|resume` 执行/暂停/恢复

### 15. `/api/v1/trace` — `trace.py` | 需认证（路由级）
- `GET` 轨迹列表 | `GET /stats` 统计 | `GET /{trace_id}` 详情 | `GET /{trace_id}/events` 事件 | `GET /{trace_id}/export` 导出

---

## 二、生成与知识 (8模块)

### 16. `/api/v1/generation` — `generation.py` | 需认证（路由级）
- `POST /text` 文本 | `POST /image` 图像 | `POST /audio` 音频 | `POST /video` 视频 | `GET /voices` 音色列表 | `GET /resolve` 解析引用 | `GET /video/status/{task_id}` 视频任务状态 | `GET /usage` 用量 | `GET /tasks` 任务列表 | `GET /files/{name}` 产物文件

### 17. `/api/v1/image` — `image.py` | 需认证（路由级）
- `GET /templates` 模板列表 | `GET /templates/{name}` 模板详情 | `POST /build` 生成 | `GET /builds` 生成记录 | `GET /builds/{build_id}` 记录详情

### 18. `/api/v1/media` — `media.py`
- 写：`POST /save`（表单字段 `media_type` 必填；无 `POST /upload`）｜ `POST /batch-delete`（body `{media_ids, mode}`）｜ `PUT /config` ｜ `POST /cache/clear`
- 读：`GET /list`（`agent_id`/`media_type`/`search`/`offset`/`limit`）｜ `GET /config` ｜ `GET /{media_id}`（内容）｜ `GET /{media_id}/metadata` ｜ `GET /download/{media_id}` ｜ `GET /stats/{agent_id}` ｜ `GET /memory/{memory_id}` ｜ `GET /storage-path/{media_type}`
- 回收站（§6-158）：`DELETE /{media_id}?mode=trash` 软删 ｜ `GET /trash` 读面 ｜ `POST /{media_id}/restore` 恢复 ｜ `DELETE /{media_id}?mode=permanent` 彻底删除。**缺省档是 `permanent`**——列表里那个删除按钮至今仍是硬删
- 认证：路由级 `Depends(get_current_user)`，**无凭证即 401**（实测于 §6-158 的活体第 [8] 项，附录那张表的旧值见其脚注）
- 字面段（`/trash`、`/list`、`/config`、`/batch-delete`…）必须注册在 `GET /{media_id}` 之前，守卫见 `tests/unit/api/test_media_route_order_guard.py`

### 19. `/api/v1/knowledge` — `knowledge.py`（聚合器；实现拆 knowledge_common/core/sharing/remote/ingestion）
- CRUD: `GET` | `POST` | `GET/PUT/DELETE /{id}` | `POST /search`
- `POST /search`（2026-11-04）：请求体可选 `source_modified_after`/`source_modified_before`（源文档修改时间范围；设置后无源时间条目如实排除）；条目含 `source_created_at`/`source_modified_at`（缺失空串），`created_at`＝入库时间
- `POST /search` / `POST /access/query` 双时态（2026-11-06，B11 L3）：请求体可选 `asOf`/`knownAt`；任一给出时走事实层 `factsBitemporal`（`asOf` 裁 valid time，`knownAt` 裁 transaction time），返回事实项（`knowledge_id`＝fact_id，`metadata` 带 confidence/qualifier/valid/transaction）；两轴都空保持条目检索旧行为。**W0-1（2026-11-13）**：`/access/query` 增显式查询参数 `?asOf=`/`?knownAt=`（与 body 同义、显式优先）；不可解析时间由存储层 `parseBitemporalStamp` 单点判，显式 **400**（REST）/结构化 `rejected`（MCP `ontology_query` 的 `as_of`/`known_at` 同款），不静默当空轴
- 本体 dry-run 与流水线（2026-11-05，升级计划 B2/B6，实现 `knowledge_ontology.py`＋`knowledge/ontology/pipeline.py`）：
  - `POST /ontology/validate`（只读）：入参 `{tenantId?, agentId?, triples:[{subjectLabel, subjectKey?, predicateTermId, objectTerm, qualifier?}]}`；逐条回 `{index, subjectKey, findings, violations, verdict}`＋`summary`。violation 不抛异常进 verdict；不落库、不建主体。校验路径与流水线共用一份
  - `POST /ontology/pipeline/run`（管理员）：入参 `{agentId?, tenantId?, termUpserts[], ruleRegistrations[], factCandidates[], reason?}`；候选先全部 dry-run，任一 violation 整批拒绝（400 带 `rejections`，零落盘）；应用术语/规则（只登记不触发求值）后写 `knowledge_baselines` 快照（scope=`ontology_pipeline`）；返回 `{baselineId, applied, summary}`
  - `GET /ontology/pipeline/diff?fromBaseline=..&toBaseline=..`（只读）：两基线（`toBaseline` 缺省对比当前实况）间 terms/rules 差异 `{added, removed, changed}`
  - `POST /ontology/pipeline/rollback`（管理员）：入参 `{toBaselineId, reason?}`；按基线快照逐字恢复 terms/rules/shapes，追加变更审计并按推导账本撤销受影响推导；返回 `{restored, audit, activity_id}`
  - `GET /ontology/export.ttl?agent_id=`（只读，**仅管理员**）：本租户全库 Turtle 导出，`text/turtle; charset=utf-8`，文本出自 `ontology/turtle.py::serializeAll`（端点不另拼第二份序列化）。**语法子集边界**：固定 `@prefix kbg: <https://neurova.local/knowledge/>`；主语＝`kbg:<subject_key>`（不用中文标签，避免 IRI 收字形时不同主体互相吞并）；谓词＝`kbg:<数据里的术语名>`；客体一律字符串字面量——不出 IRI 客体、不出集合/匿名节点、不出 xsd 数据类型标记、不出 owl/rdf 模式词汇；事实段只收 `status='active' AND record_kind='triple'`；排序只来自固定 ORDER BY ⇒ 同一库内容两次导出逐字节一致。rdflib 互操作对拍是可选测试（产品零第三方依赖）。**B8 扩展（2026-11-05）**：文档头增 `rdf:`/`rdfs:`/`owl:` 三个固定前缀；新增"标准槽位语义行"——概念父类 `rdfs:subClassOf`、关系父属性 `rdfs:subPropertyOf`、逆关系 `owl:inverseOf`（全 IRI 独立三元组行）；`is_a` 事实导出为 `rdf:type`（客体＝概念术语 IRI）；术语 IRI 有 `external_iris_json.skos_exactMatch` 外部映射时用外部 IRI，否则 `kbg:`；读侧前缀名从只认 `kbg:` 放宽到任意 `prefix:local`
  - `GET /ontology/export.jsonld?agent_id=`（管理员）：`application/ld+json; charset=utf-8`，`@context` + `@graph`，逐字节确定
  - `GET /ontology/export.owl?version=`（管理员）：OWL 2 RL 可规则化公理（subClass/subProperty/inverse/symmetric/transitive/functional），`text/turtle`
  - `GET /ontology/export.shacl`（管理员）：形状注册表 → `sh:` 形状，`text/turtle`
  - `GET /ontology/export.prov`（管理员）：activities/derivations → PROV-O，`text/turtle`
- **函数层（2026-11-13，specs/2026-11-12 §4 W2，v43）**：可计算业务语义登记——受限 AST 表达式
  （算术/比较/布尔＋聚合 `sum/count/avg/min/max(facts(谓词, qualifierFilter?, asOf?))`），
  登记即编译（白名单外节点/未知符号/越界谓词 400）；结论经咽喉入账，推导账本
  `source_kind=function`（rule_id 位写 `function:<id>`），物化档 observe/enforce 复用 v35 语义。
  - `GET /ontology/functions`（登录可读）｜`POST /ontology/functions`（管理员，登记即编译）｜
    `DELETE /ontology/functions/{function_id}`（管理员，按源撤回其全部结论）
  - MCP 新工具 `ontology_compute`（只读 dry 求值：值＋输入快照＋表达式回显，零落库；
    selector 超行上限显式拒）——与 `ontology_derive`（函数结论带溯源）同源
  - W1 配套：术语 qualifier_schema 声明 `type: number` 的键，写入时在咽喉单点归一成
    canonical 量值（`quantity.py` 单源）；`POST /graph/instances` 可带 `qualifier`；
    抽取 prompt 对数值谓词输出「数字＋单位」引导段（`graph_bridge`）


- **状态机（W3，v44）**：`GET|POST|DELETE /ontology/state-machines`（admin 写/登录读）＋`GET /ontology/domain-packs`（导入即补缺 has_state cardinality=1）；MCP `ontology_state`
- **动作语义（W4，v45）**：ontology_actions 三列 precondition_json/impact_json/state_change_json；`POST /ontology/actions` 透传三段；MCP `ontology_act` 门面转交 ToolExecutor.execute 单管道
- **推演（W5，v46）**：`POST|GET /ontology/simulations`（admin）——backup 副本→假设注入→规则/函数推演→diff；生产零写；MCP `ontology_simulate`
- **决策台账（W7，v47）**：`POST|GET /ontology/decisions`＋`POST /ontology/decisions/{id}/links`＋`GET /ontology/decisions/{id}/trace`＋`GET /ontology/decisions/precedents`；MCP 四工具 ontology_decision_record/link/trace/precedents
- **GraphRAG（W8，v48）**：`GET|POST|DELETE /ontology/chunk-strategies`＋`GET /ontology/communities`＋`POST /ontology/community-search`（global/drift）；MCP `ontology_community_search`
- **推理广度（W9）**：`POST /ontology/sparql`（501 not_supported）＋`POST /ontology/abduce`；MCP `ontology_sparql`/`ontology_abduce`
- **摄取广度（W10）**：`POST /enterprise/webhook/{source_id}`（HMAC 非登录态；缺省 off）；SOURCE_TYPES 扩 unity_catalog/snowflake/sap_odata/http_pull
- **追责审计（W12）**：`GET /ontology/accountability`（admin 只读跨五账聚合）；digest_chain verify 经 `/foundation/integrity` 共存
- **C2 工件溯源**：`GET /ontology/domain-packs/{id}/attribution`＋`GET /ontology/domain-packs/{id}/integrity`。**收尾批（2026-11-13，v50）**：工件级内容地址不可变存储 `ontology_artifacts`（主键＝SHA-256(content)，write-once 只插不改不删）——领域包导入即登记工件；`GET /ontology/artifacts?kind=&limit=`（清单：元数据＋哈希引用，不含字节）｜`GET /ontology/artifacts/{sha256}/content`（按哈希读原始字节，读时校验，损坏显式 500 不静默换字）｜`GET /ontology/artifacts/{sha256}/verify`（ok/drift/missing——核验是读数不是修复）
- **C1 字节级往返（收尾批 2026-11-13）**：`POST /ontology/import-rdf`（管理员，inert 姿态）导入即把原始字节登记为 `rdf_import` 工件，回执带 `sha256`/`artifact_sha256`/`artifact_created`（同字节重导 `artifact_created=false` 零二次写）；`GET /ontology/import-artifact/latest`（登录可读）按字节原样回最近一次导入＋`X-Original-Import-Sha256` 头；`GET /ontology/export.ttl` 响应头 `X-Original-Import-Sha256` 单源引用该工件（原 env 占位退役）
- **U3/U5 读数面（收尾批 2026-11-13）**：`GET /ontology/blocking-stats?agent_id=&nodeLimit=`（消解队列 blocking 预读数：全对/候选对比＋剪枝百分比；节点源与消解队列同源 KnowledgeGraphManager）｜`GET /ontology/conflict-policy/{term_id}`（术语级 conflict_policy 声明读数，未声明回 default）｜webhook 接收面：`GET /ontology/webhook/config`（enabled（env 门控缺省 off）＋签名密钥 SHA-256 前 12 位指纹——零明文回传）｜`POST /ontology/webhook/rotate`（admin：进程内 env 指针写新随机密钥，回新指纹；部署面持久化仍走环境变量）｜`POST /ontology/webhook/simulate`（`mode=ok|duplicate|bad_signature`，回执为接收器原话——含诚实拒绝）｜`GET /ontology/webhook/dedup-stats`（幂等去重台账行数/源数）
- 本体关系映射（2026-11-05，升级计划 B8，实现 `term_registry.py`＋`rule_engine.py`＋`relation_candidates.py`）：
  - 术语写面（`POST|PUT /ontology/terms`）新增字段：`inverse_of`/`symmetric`/`transitive`/`aliases`/`external_iris`/`deprecated`/`replaced_by`（None＝PUT 保留现值）；relation 可挂 relation 父属性（`rdfs:subPropertyOf`，父子 kind 必须一致、登记处判环）；`inverse_of` 登记时双向补齐；别名按租户唯一；`cardinality=1` 即函数属性（不新增列）
  - 规则写面（`POST|PUT /ontology/rules`）新增字段：`shape`（relay/conjunction/inverse；缺省按 `head_object_const` 推断）；inverse 要求 head 主语变元＝正原子客体变元
  - **物化档位（2026-11-06，v35，§12.6 设计 3）**：规则新增 `materialization` ∈ `observe`/`enforce`（缺省 `observe`，未知值写入处拒 400）。语义：全局灰度 `NEUROVA_CONDITION_CLASSES_ROUTE` 仍为 off 时，`observe` 规则的推导结论只作解释链/审计可见，`enforce` 规则的结论**进检索主路**并带 `via_derived`；一行结论留在主路的条件是它的每条推导边都来自 enforce 规则（口径单点在 `derivation_ledger.derivedExclusionClause`，读面 `hiddenDerivedFactIds` 与图谱走查共用同一段 SQL 片段）。PUT 省略即保留现值；`pipeline/run` 的 `ruleRegistrations[].materialization` 同步支持，基线 diff 的规则投影含该栏
  - **条件类规则经 REST 登记现在会真推导**：端点装配此前裸造引擎（未接咽喉），登记一条能匹配到存量事实的条件类规则会当场 400「推理未接咽喉写入口」；现 `_ontologyParts()` 与生产装配同形态注入 `productionAdmissionGate`，推导结论统一走 `admit` 唯一写口
  - 关系特征由 `ForwardChainingEngine.ensureAutoRules` 幂等对齐为 `auto_subproperty:*`/`auto_transitive:*`/`auto_inverse:*`/`auto_symmetric:*` 规则行（术语写面与批准动作后自动触发）；`is_a` 的传递规则沿用历史 id `is_a_transitive`（同 id 单行，旧手工种子退役）
  - 未知关系候选（抽取侧 `graph_bridge` 落候选，不再两层静默消失）：
    - `GET /ontology/relation-candidates?status=pending|approved|rejected&limit=`（登录可读）
    - `POST /ontology/relation-candidates/{candidate_id}/approve`（**仅管理员**）：登记术语（term_id＝规范化词形）并回填 `promoted_term_id`
    - `POST /ontology/relation-candidates/{candidate_id}/reject`（**仅管理员**）：保留审计行不删除
    - 去重口径 `(tenant_id, normalized_surface, source_entry_id)`；批准/拒绝二态互斥（重复审批 409）
- 形状注册表（2026-11-06，B10 L4，实现 `knowledge/ontology/shapes.py`）：
  - `GET /ontology/shapes?enabled_only=`（登录可读）：本租户形状列表
  - `POST /ontology/shapes`（管理员）：`{shape_id, target_kind, target_term_id?, path?, constraint_kind, constraint, severity?, message?, enabled?, version?}`；与内置 6 项校验撞车 400
  - `PUT /ontology/shapes/{shape_id}`（管理员）：更新；不存在 404，不静默新建
  - `DELETE /ontology/shapes/{shape_id}`（管理员）：删除；不存在 404
  - 形状与内置 6 项校验共用同一求值器（写入前/dry-run 同 findings 流）
- 事件/时间受控词汇（2026-11-06，B11 L3，§12.4 设计 3；实现 `ontology/upper_lite.py` 种子）：
  - `hasParticipant`/`hasTime` 与 Allen 四条 `before`/`after`/`overlaps`/`during` 随上层术语播种，定义域统一 `Event`，四条区间关系挂既有 `temporal` 父属性（`rdfs:subPropertyOf`）
  - OWL-Time 仅走 `external_iris.skos_exactMatch` 导出槽（Turtle/JSON-LD 里术语 IRI 直接换成 `<https://www.w3.org/2006/time#before>` 之类）；**不做运行时时间推理**，这四条不生成传递/组合规则（反面判据 `test_eventTimePattern.py`）
  - 读面可见：`GET /ontology/terms` 逐行带出 `domain_terms`/`parent_term_id`/`external_iris`，`GET /ontology/impact?term=before` 给引用面
- 术语声明字段写面（2026-11-06，B10 L2／B11 L3，实现 `term_registry.py`＋`knowledge_ontology.py`）：
  - `POST|PUT /ontology/terms` 新增 `labels`（lang→文本）/`alt_labels`（lang→文本数组）/`module`（`core`|`domain`|空）/`identity_keys`（类型级身份判据键名）/`qualifier_schema`（限定关系三判：键/类型/必填）；口径与既有字段一致——None＝PUT 保留现值，显式空容器才是清空声明
  - **「保留现值」只有一个属主**：合并逻辑住在 `OntologyTermRegistry.declarePartial()`（字段表 `_DECLARE_COLUMNS` 单点），REST PUT 与 `POST /ontology/pipeline/run` 的 `termUpserts[]` 都走它；端点里不留第二份清单（反向判据 `test_pipelineTermUpsertPartial.TestMergeSingleSource` 按 AST 咬）。`PipelineTermUpsert` 随之补齐 B8 关系特征（`inverseOf/symmetric/transitive/aliases/externalIris/deprecated/replacedBy`）与 `version: null`（不带 version 的批次不重置现版本）
  - 写入处即判：语言标记必须 BCP47 形状（否则 400）；`module` 闭集且 core↔domain 不许翻转；`identity_keys` 由 `SubjectResolver` 按类型读取（缺省回退 canonical label＋aliases）；`qualifier_schema` 由 admission/validate 侧 `qualifierSchemaOf` 读取
  - 流水线基线 diff 的术语投影覆盖全部声明字段（B8/B10/B11 一视同仁），批次改 labels 不再对 diff 隐身
- 本体质量报告（2026-11-06，B13 L9，实现 `knowledge/ontology/quality.py`）：
  - `GET /ontology/quality`（登录可读）：`{tenant_id, term_count, findings:[{kind,severity,target,message}], metrics:{consistency,conciseness}}`
  - 只覆盖**可计算**子集：`missingLabel`/`orphanClass`/`inverseOneSided`/`duplicateLabel`；同一库两次读数逐字一致
  - 完整 OOPS!/OntoClean/OQuaRE 认证与检索 NDCG/A-B 不在本端点承诺面（前者 §6 不纳入项，后者走 `/evaluation/*` 与 `/audit/*`）
- 企业源描述符提交（2026-11-06，B14 §14.3，实现 `knowledge_enterprise.py`＋`knowledge/enterprise/registry.py`）：
  - `GET /enterprise/sources`（登录可读）：本租户已提交源 `{items:[{source_id, descriptor, cursor, enabled, adapter_registered}], total}`
  - `GET /enterprise/sources/{source_id}`（登录可读）：单源回显；未提交过 404
  - `POST /enterprise/sources`（**仅管理员**）：入参 `{source_id, descriptor, enabled?}`；`validateDescriptor` 编译期先判（sourceType 白名单 sql/erp_api/event_stream、模板占位符须是已声明列、predicate/object.term 须已登记、object.kind 闭集、qualifier/validFrom/validUntil 列须已声明、描述符任何字段含 SQL 形状片段即拒），非法整条拒 400 带定位且**零落库**
  - 两态分开：`enabled` 默认 False（关闸＝摄取路径零调用零网络）；`adapter_registered` 读进程内唯一适配器注册表 `getSourceRegistry()`，默认 False——真实 DB/ERP API/事件流连接器另立项，本端点不提供任何「已连接」调用
- 四动词统一门面（2026-11-05，升级计划 B3，实现 `knowledge_access_facade.py`，纯转发零新逻辑）：
  - `POST /access/query` → 同 `POST /search`（入参与响应形状一致；支持 `asOf`/`knownAt` 双时态——body 内 `as_of`/`known_at` 或显式查询参数 `?asOf=`/`?knownAt=`（W0-1，显式优先），任一给出时返回事实视图；非法时间 400）
  - `POST /access/analyze` → 同 `POST /v1/semantic-search/analyze`
  - `POST /access/validate` → 同 `POST /ontology/validate`
  - `POST /access/use/{fact_id}` → 同 `POST /facts/{fact_id}/adoption`（治理门同源：仅管理员）
  - 未声明动词无处理面，天然 404；旧路由保持直接入口

### 20. `/api/v1/growth` — `growth.py`（含并入的 constitution_router / personality_router，`growth.py:42-43`） | 需认证（路由级）
- `GET` 成长概览 | `GET /capabilities` 能力面
- 反思: `GET/POST /reflection` | `GET /reflection/stats`
- 提问队列: `GET /questions` | `POST /questions` | `GET /questions/next` | `PUT /questions/{question_id}/answer`（memory/questions 退役后的现役面，`growth.py:449-557`）
- 主动行为: `GET/POST /proactive` | `GET/PUT /motivation`
- 宪法（constitution_router）: `GET/PUT /constitution` | `GET/POST /constitution/rules` | `PUT/DELETE /constitution/rules/{rule_id}`
- 性格（personality_router）: `GET/PUT /personality` | `GET /personality/traits` | `POST /personality/evolve`

### 21. `/api/v1/sleep` — `sleep.py` | 需认证（路由级）
- 均按 agent：`GET /{agent_id}/status` 睡眠状态 | `GET/PUT /{agent_id}/settings` 睡眠设置 | `GET /{agent_id}/dreams`、`GET /{agent_id}/dreams/{dream_id}` 梦境 | `GET /{agent_id}/insights`、`GET /{agent_id}/insights/{insight_id}` 洞察 | `GET /{agent_id}/merges`、`GET /{agent_id}/merges/{merge_id}` 记忆合并 | `GET /{agent_id}/conflicts`、`GET /{agent_id}/conflicts/{resolution_id}`、`POST /{agent_id}/conflicts/{resolution_id}/resolve` 冲突与裁决 | `GET /{agent_id}/inductions` 诱导记录 | `POST /{agent_id}/wake` 唤醒 | `POST /{agent_id}/sleep` 入睡

### 22. `/api/v1/runtime` — `runtime.py` | 需认证（路由级）
- `GET /status` 运行时状态 | `GET /resources` 资源占用 | `GET /performance` 性能指标 | `POST /gc` 触发垃圾回收

### 23. `/api/v1/marketplace` — `marketplace.py` | 需认证
- `GET /skills` 技能市场列表 | `GET /skills/{skill_id}` 详情 | `POST /skills/{skill_id}/install` 安装 | `DELETE /skills/{skill_id}/install` 卸载 | `GET /installed` 已安装 | `POST /skills` 发布 | `POST /skills/submit` 提交审核 | `GET /skill-submissions` 审核列表 | `POST /skill-submissions/{submission_id}/review` 审核 | `PUT /skills/{skill_id}` 更新 | `DELETE /skills/{skill_id}` 下架 | `POST /sync` 同步

---

## 三、渠道与通知 (7模块)

### 24. `/api/v1/channel-adapters` — `channels.py` | 多数需认证（`POST /{channel_type}/webhook` 回调入口公开）
> 原 §24 写的 `/api/v1/channels`（`channel.py`）不存在于代码与 `ENDPOINT_MODULES` 注册表；渠道真实面即本节 channels.py（2026-11-19 核对改写）。
- `GET` 渠道状态列表 | `GET /{channel_type}` 指定渠道状态
- 连接与消息: `POST /{channel_type}/connect` 连接 | `POST /{channel_type}/disconnect` 断开 | `POST /{channel_type}/send` 发送消息 | `POST /{channel_type}/restart` 重启渠道 | `POST /{channel_type}/clear-queue` 清空待处理队列
- Webhook: `POST /{channel_type}/webhook` 回调入口（公开） | `POST /{channel_type}/webhook/set` 设置（Telegram setWebhook） | `DELETE /{channel_type}/webhook` 删除 | `GET /{channel_type}/webhook/info` 查询状态
- 运维读数: `GET /health/all` 渠道健康检查 | `GET /ingress/bypass-stats` 入站旁路直发读数 | `GET /conflicts/check` 机器人身份冲突检测

### 25. `/api/v1/channel-adapters` — `channels.py`
- 与 §24 同指一个模块（同挂 `/v1/channel-adapters`），路由清单见 §24，不重复列。

### 26. `/api/v1/channel-configs` — `channel_config.py` | 需认证（路由级）
- `GET` 列表 | `POST` 创建/更新 | `GET/DELETE /{channel_type}` | `POST /{channel_type}/test` 测试连接 | `GET /{channel_type}/qrcode` 登录/授权二维码 | `GET /{channel_type}/qrcode/status` 轮询扫码状态
- 运维与迁移: `GET /ingress/stats` 入站队列状态 | `GET /migration-sources` 迁移候选源 | `POST /migrate-agent` 迁移归属 agent | `GET /schemas` 动态表单 schema
- 渠道身份绑定: `GET /identity/bindings` | `GET /identity/bindings/mine` | `GET /identity/observed` | `POST /identity/bindings/code` 发绑定码 | `DELETE /identity/bindings` 解绑

### 27. `/api/v1/channel-sharing` — `channel_sharing.py` | 需认证（路由级）
- `GET` 分享配置列表 | `POST /enable` 启用 | `POST /disable` 停用 | `POST /channels` 配置渠道 | `GET /available-channels` 可用渠道 | `POST /test` 测试 | `GET /status` 状态

### 28. `/api/v1/notifications` — `notifications.py` | 需认证
- `GET` 通知列表 | `GET /unread-count` 未读数 | `GET /stream` SSE 订阅 | `POST/PUT /{notification_id}/read` 标记已读 | `POST /mark-all-read`、`PUT /read-all` 全部已读 | `DELETE /{notification_id}` 删除 | `GET /push-statistics` 推送统计

### 29. `/api/v1/audit` — `audit.py` | 需认证
- `GET` 审计日志 | `GET /stats` 统计 | `GET /export` 导出 | `POST /search` 搜索 | `GET /approvals` 审批记录

### 30. `/api/v1/firewall` — `firewall.py` | 需管理员（路由级 `require_admin`）
- `GET/POST /rules` | `PUT/DELETE /rules/{rule_id}` | `GET /blocked` 封禁列表 | `GET /stats` 统计

---

## 四、协作与团队 (7模块)

### 31. `/api/v1/analytics` — `analytics.py` | 需认证
- `GET /usage` 用量 | `GET /performance` 性能 | `GET /behavior` 行为 | `GET /errors` 错误 | `GET /cost-readout` 成本读数

### 32. `/api/v1/collaboration` — `collaboration_api.py` + `collaboration_room_api.py`（同挂 `/v1/collaboration`） | 需认证（room 面逐路由）
- 模板: `GET/POST /templates` | `GET/PUT/DELETE /templates/{template_id}`
- 会话: `POST /start` 发起 | `GET /history` 历史 | `GET /sessions` 列表 | `GET /stats` 统计
- 画布: `POST /canvas` 创建 | `GET /canvas` 列表 | `GET/PUT/DELETE /canvas/{canvas_id}` | `POST /canvas/from-nl` 自然语言建画布 | `POST /canvas/{canvas_id}/ops` 操作 | `POST /canvas/{canvas_id}/run` 运行 | `GET /canvas/{canvas_id}/runs/{run_id}` 运行详情 | `POST /comfyui/import-canvas` 导入
- 房间（collaboration_room_api.py）: `GET /rooms/{room_id}` | `PUT /rooms/{room_id}` | `GET/POST /rooms/{room_id}/messages` | `POST /rooms/{room_id}/collaboration` | `GET /rooms/{room_id}/swarm/pending` | `POST /rooms/{room_id}/approvals/{request_id}/decide` | `POST /rooms/{room_id}/candidates/{candidate_id}/{action}`

### 33. `/api/v1/groups` — `groups_api.py` | 需认证
- `GET/POST` | `GET/PUT/DELETE /{group_id}` | `GET/POST /{group_id}/members` | `DELETE /{group_id}/members/{username}`

### 34. `/api/v1/teams` — `teams_api.py` | 需认证（路由级）
- `POST/GET` | `GET/PUT/DELETE /{team_id}` | `POST /{team_id}/members` 添加成员 | `DELETE /{team_id}/members/{member_id}` 移除成员 | `PUT/GET /{team_id}/members/{member_id}/prompt` 成员提示词 | `GET /{team_id}/prompt-context` 提示词上下文

### 35. `/api/v1/neurflow` — `neurflow_api.py` | 需认证（路由级）
> 原 §35 写的 `/api/v1/workflows`（`workflows_api.py`）不存在；工作流真实面是 neurflow_api.py 挂 `/v1/neurflow`（2026-11-19 核对改写）。
- 工作流: `GET/POST /workflows` | `GET/PUT/DELETE /workflows/{workflow_id}` | `GET /workflows/search/{query}` | `POST /workflows/{workflow_id}/validate|execute|duplicate|publish|step-run` | `GET/PUT /workflows/{workflow_id}/definition` | `PUT /workflows/{workflow_id}/viewport` | `GET /workflows/{workflow_id}/versions` | `POST /workflows/{workflow_id}/versions/{version}/rollback`
- 执行: `GET /executions` | `GET /executions/{execution_id}` | `GET /executions/{execution_id}/events|variables|checkpoint` | `POST /executions/{execution_id}/cancel|resume|retry|breakpoint|debug/resume`
- 节点: `GET /nodes` | `GET /nodes/{node_type}` | `GET /nodes/search/{query}` | `GET /nodes/stats` | `POST /nodes/sync` | `GET/POST /nodes/custom` | `PUT/DELETE /nodes/custom/{node_type}` | `PUT /nodes/{node_id}/mock`
- Agent/模板: `GET/POST /agents` | `POST /agents/{agent_id}/archive|restore` | `GET/POST /templates` | `POST /templates/{template_id}/instantiate`
- 其他: `GET /stats` | `GET /comfyui/status` | `POST /comfyui/execute` | `GET /otel/status`

### 36. `/api/v1/tasks` — `tasks_api.py` | 需认证（路由级）
- 看板: `POST/GET /boards` | `GET /boards/{board_id}` | `GET /boards/{board_id}/stats`
- 任务: `GET/POST /boards/{board_id}/tasks` | `PUT /tasks/{task_id}` 更新 | `PUT /tasks/{task_id}/move` 移动

### 37. `/api/v1/projects` — `projects_api.py` | 需认证（路由级）
- CRUD: `POST/GET` | `GET/PUT/DELETE /{project_id}` | `GET /{project_id}/stats`
- 关联面: `GET /{project_id}/workflows` | `GET /{project_id}/collaboration` | `POST/GET /{project_id}/teams` | `POST /{project_id}/teams/{team_id}/members` | `GET /{project_id}/teams/{team_id}/agents` | `GET/POST /{project_id}/tasks` | `POST /{project_id}/tasks/{task_id}/pause|resume`

---

## 五、工具与技能 (12模块)

### 38. `/api/v1/rules` — `rules_api.py` | 需认证（路由级）
- `POST/GET` | `GET/PUT/DELETE /{rule_id}` | `PUT /{rule_id}/toggle` 启停 | `POST /{rule_id}/test` 测试 | `GET /{rule_id}/logs` 执行日志

### 39. `/api/v1/webhooks` — `webhooks.py` | 需认证（路由级）
- `GET/POST` | `GET/PUT/DELETE /{webhook_id}` | `POST /{webhook_id}/test` 测试 | `GET /{webhook_id}/deliveries` 投递记录

### 40. `/api/v1/enhanced-users` — `enhanced_users_api.py` | 需管理员（路由级 `require_admin`）
- `GET` 列表 | `POST` 创建 | `PUT /{user_id}` 更新 | `PUT /{user_id}/password` 改密 | `DELETE /{user_id}` 删除 | `GET /backup` 备份

### 41. `/api/v1/user-groups` — 已移除
- 该模块未实现，已从本文档移除（2026-11-19 核对：无 `user_group_api.py`，`ENDPOINT_MODULES` 无此注册项）。

### 42. `/api/v1/files` — `files_api.py` | 需认证
- `POST /upload` 上传 | `GET` 列表 | `GET /storage/info` 存储信息 | `GET /{file_id}` 详情 | `GET /{file_id}/preview` 预览 | `GET /{file_id}/content` 内容 | `GET /{file_id}/download` 下载 | `PUT /{file_id}` 更新 | `DELETE /{file_id}` 删除 | `GET /{file_id}/versions` 版本 | `POST /{file_id}/approve`、`POST /{file_id}/reject` 审批

### 43. `/api/v1/file-flows` — 已移除
- 该模块未实现，已从本文档移除（2026-11-19 核对：无 `file_flows_api.py`，`ENDPOINT_MODULES` 无此注册项）。

### 44. `/api/v1/tools` — `tool_schema.py` | 需认证（路由级）
- `GET /formats` 支持格式 | `POST /schema` 生成 schema | `POST /convert` 格式转换 | `POST /validate` 校验 | `POST /parse` 解析 | `POST /batch-convert` 批量转换 | `GET /examples` 示例

### 45. `/api/v1/tool-layers` — `tool_layers.py` | 需认证（路由级）
- MCP 服务器: `GET/POST /mcp-servers` | `DELETE /mcp-servers/{server_id}` | `POST /mcp-servers/{server_id}/test` 测试 | `GET /mcp-servers/{server_id}/tools` 服务器工具 | `POST /mcp-servers/{server_id}/oauth/authorize` OAuth授权
- 目录与工具: `GET /mcp-catalog` 目录 | `POST /mcp-catalog/{entry_id}/install` 安装目录项 | `GET /tools` 工具列表 | `POST /tools/execute` 执行 | `GET /tools/public` 公开工具

### 46. `/api/v1/skill-pool` — `skill_pool_api.py` | 需认证（路由级）
- 公共库: `GET /public` | `GET /public/{skill_id}` | `POST /public/{skill_id}/install`
- 私有库: `GET/POST /private` | `PUT/DELETE /private/{skill_id}` | `POST /private/{skill_id}/share` 分享 | `POST/DELETE /private/{skill_id}/push` 推送 | `POST /private/{skill_id}/execute` 执行
- 我的技能: `GET/POST /me/skills` | `PUT/DELETE /me/skills/{skill_id}` | `POST /me/skills/{skill_id}/from-public` 从公共库导入
- Agent 侧: `GET /agent/{agent_id}/pending-skills`、`POST /agent/{agent_id}/pending-skills/{template_id}/approve|reject` | `GET /agent/{agent_id}/pending-experiences`、`POST /agent/{agent_id}/pending-experiences/{record_id}/approve|reject` | `GET /agent/{agent_id}/consolidation/plans`、`POST /agent/{agent_id}/consolidation/{umbrella}/approve|reject` | `GET /agent/{agent_id}/skills` | `GET /agent/{agent_id}/domain-harnesses`
- 安装与审核: `POST /install-from-url` | `POST /install-from-zip` | `POST /skills/submit` 提交 | `GET /skill-submissions` | `POST /skill-submissions/{submission_id}/review` 审核
- 转移: `POST/GET /transfers` | `POST /transfers/{transfer_id}/accept|reject`

### 47. `/api/v1/marketplace` — `marketplace.py`（技能市场面，与 §23 同模块） | 需认证
- `GET /skills` | `GET /skills/{id}` | `POST /skills/{id}/install` | `DELETE /skills/{id}/install` | `GET /installed`

### 48. `/api/v1/skill-versions` — `skill_version_api.py` | 需认证（路由级）
- `POST /check` 检查更新 | `POST /check-all` 全量检查 | `GET /notifications` 更新通知 | `PUT /notifications/{notification_id}/read` 通知已读 | `POST /auto-update` 自动更新 | `POST /sync-from-public` 从公共库同步 | `POST /update` 更新 | `GET /startup-check` 启动检查

### 49. `/api/v1/mobile` — `mobile_pairing.py` | 需认证
- `POST /pairing/generate` | `GET /pairing/qrcode/{code}` | `POST /pairing/confirm` | `GET /pairing/status/{code}` | `GET /pairing/list` | `DELETE /pairing/{id}` | `WS /ws`
- 配对辅助（2026-11-19 补录）：`POST /pairing/resolve` | `POST /pairing/cancel` | `POST /pairing/refresh` | `GET /pairing/tunnel/status` 隧道状态 | `GET/PUT /pairing/connection-config` 连接配置 | `POST /pairing/connection-config/preflight` 预检 | `POST /pairing/connection-config/remote-deploy`、`GET /pairing/connection-config/remote-deploy/{taskId}`、`POST /pairing/connection-config/remote-undeploy` 远程部署
- `WS /ws?code=…`（或 `?token=…`）的消息面：入站 `ping` / `chat:send` / `chat:cancel` / `agent:switch` / `session:list` / `session:create`；出站 `pong`、`chat:chunk`→`chat:done`、`agent:switched`、`session:*`，失败一律回 `type=error` 带 `code`。
- §6-154（批 17）改到实况的两点：**`chat:send` 此前从未真的跑起来**——调用点按 `content=`/`user_id=` 传参，与 `Agent.chat_stream`/`Agent.chat` 的真签名（`user_input=`/`metadata=`）对不上 ⇒ 必 `TypeError`，又被一条不记日志的 catch-all 转成 `chat_failed`，服务端零痕迹。现在形状接对、回合内建立请求级属主（usage 入账、按日配额、会话归属同 §6-153 的边界口径），并把"取不到 Agent"的两种因由分开回：`agent_not_found`（确实没有）与 `agent_lookup_failed`（查询自己抛了，日志留服务端）。
- `/api/v1/mobile/push`（`mobile_push.py`）：`PUT /push-tokens`（上报设备推送令牌，platform=android|harmony，绑定真实登录身份）｜`DELETE /push-tokens/{device_id}`｜`GET /push-credentials/status`（FCM/Push Kit 凭据配置状态，不回显值）。离线推送只发信令（notificationId/type），正文由 App 拉取通知接口获取。

---

## 六、记忆增强 (7模块)

### 50. `/api/v1/experience` — `experience_knowledge_api.py` | 需认证（路由级）
- `POST /records` 写入经验 | `GET /ranking` 排名 | `GET /stats` 统计 | `POST /similar` 相似检索 | `GET /{record_id}` 详情 | `PUT /{record_id}/disposition` 处置 | `DELETE /{record_id}` 删除

### 51. `/api/v1/knowledge-graph` — `knowledge_graph_api.py` | 需认证
- 均按 agent：`GET /{agent_id}/knowledge-graph` 图谱 | `GET /{agent_id}/spatial-nodes` 空间节点 | `GET /{agent_id}/knowledge-graph/search` 搜索 | `GET /{agent_id}/knowledge-graph/nodes/{node_id}` 节点详情 | `GET /{agent_id}/knowledge-graph/resolution/reviews` 消解评审 | `POST /{agent_id}/knowledge-graph/resolution/reviews/{review_id}/resolve` 裁决 | `POST /{agent_id}/knowledge-graph/resolution/run` 执行消解 | `POST /{agent_id}/knowledge-graph/backfill` 回填 | `GET /{agent_id}/knowledge-graph/authority-drift` 权威漂移 | `POST /{agent_id}/knowledge-graph/projection/rebuild` 重建投影 | `GET /{agent_id}/studio` 工作台视图 | `GET /{agent_id}/subgraph` 子图

### 52. `/api/v1/knowledge-integration` — `knowledge_integration.py` | 需认证（登录或服务身份）
- 同步: `POST /sync/knowledge-to-memory` 知识→记忆 | `POST /sync/memory-to-kb` 记忆→知识库 | `GET /sync/links` 同步链路
- RAG: `POST /rag/retrieve` | `POST /rag/batch`
- 学习与缺口: `POST /gaps/analyze` 缺口分析 | `POST /learn` 学习 | `GET /evolution/progress` 演进进度 | `GET /gaps` 缺口 | `GET /learning-records` 学习记录

### 53. `/api/v1/semantic-search` — `semantic_search_api.py` | 需认证
- `POST /hybrid` 混合检索 | `POST /bm25` BM25 检索 | `POST /vector` 向量检索 | `POST /compare` 检索对比 | `POST /analyze` 查询分析

### 54. `/api/v1/enhanced-memory-search` — `enhanced_memory_search_api.py` | 需认证（路由级）
- `POST /search` 检索 | `GET /stats` 统计 | `GET/PUT /settings` 检索设置 | `GET/PUT /nerf-settings` NeRF设置 | `POST /nerf-settings/reset` 重置 | `GET /channel-weights` 通道权重 | `POST /decay` 衰减 | `POST /analyze` 分析 | `GET /activation/{memory_id}` 激活读数

### 55. `/api/v1/memory-timeline` — `memory_timeline_api.py` | 需认证（路由级）
- `GET /recent` 最近 | `GET /range` 时间范围 | `GET /grouped` 分组 | `GET /stats` 统计

### 56. `/api/v1/synonyms` — `synonym_api.py` | 需认证（路由级）
- `GET` 列表 | `GET /{word}` 查询 | `POST` 添加 | `PUT` 更新 | `DELETE /{word}` 删除 | `DELETE /{word}/synonyms/{synonym}` 删同义词 | `GET /stats` 统计 | `POST /load` 载入 | `POST /save` 保存 | `GET/PUT /config/llm` LLM配置 | `POST /test-search` 检索测试

---

## 七、扩展功能 (12模块)

### 57. `/api/v1/benchmark` — `benchmark.py` | 需认证（路由级）
- `GET /suites` 套件列表 | `POST /run` 运行 | `GET /runs` 运行列表 | `GET /runs/{run_id}` 运行详情 | `GET /results` 结果 | `GET /agents/{agent_id}` 按Agent | `POST /compare` 对比 | `GET /baseline-reports`、`GET /baseline-reports/{report_id}` 基线报告 | `GET/POST /rag-datasets`、`PUT/DELETE /rag-datasets/{dataset_id}`、`POST /rag-datasets/generate` RAG数据集 | `POST /rag-evaluate` RAG评测 | `GET /health-rag` RAG健康

### 58. `/api/v1/console` — `console.py` | 需认证
- 会话: `POST /chat/new` 新建 | `GET /chat/sessions` 列表 | `PUT/DELETE /chat/sessions/{session_id}` | `POST /chat/sessions/reorder` 排序 | `POST /chat/sessions/{session_id}/auto-title|pin|archive|unarchive|fork` | `GET /chat/sessions/archived` 归档 | `GET /chat/sessions/{session_id}/timeline` 时间线
- 对话: `POST /chat` 发送 | `POST /chat/review|steer|stop|resume` | `POST /chat/checkpoint` 检查点 | `GET /chat/runs` | `GET /chat/history` | `DELETE /chat/rounds` | `GET /chat/tools/{task_id}/result` 工具结果 | `GET /chat/subagents/{subagent_id}/events` 子Agent事件 | `POST /chat/feedback` 反馈 | `GET /chat/feedback/stats`
- 其他: `WS /ws/{client_id}` | `GET /push/messages` | `POST /push/message` | `GET /tasks` 任务

### 59. `/api/v1/plugins` — `plugin.py` | 需认证（安装/卸载/加载等写面另加管理员门）
- `GET /` 插件列表 | `GET /{plugin_id}` 详情 | `GET /{plugin_id}/modules` 模块 | `POST /discover` 发现
- 市场与源: `GET /market` | `GET /market/{market_plugin_id}` | `POST /market/submit` | `POST /market/install` | `GET /remote-sources` | `PUT/DELETE /remote-sources/{host}`
- 生命周期: `POST /{plugin_id}/install` 安装（管理员） | `DELETE /{plugin_id}/uninstall` 卸载（管理员） | `POST /{plugin_id}/load|unload` 加载/卸下（管理员） | `POST /{plugin_id}/enable|disable` 启停（管理员） | `GET /status` 状态
- 权限与路由: `GET /permissions/model` | `GET /{plugin_id}/permissions` | `POST /{plugin_id}/permissions/{permission}/grant|revoke` | `POST /{plugin_id}/routes/mount|unmount`（管理员）

### 60. `/api/v1/sandbox` — `sandbox.py` | 需认证（路由级）
- `GET` 列表 | `GET /agent/{agent_id}` 按Agent | `POST /start` 启动（原写 `POST /create`，实况是 `/start`） | `GET /{sandbox_id}` 详情 | `POST /{sandbox_id}/execute` 执行 | `POST /{sandbox_id}/step` 单步 | `POST /{sandbox_id}/commit` 提交 | `DELETE /{sandbox_id}` 删除

### 61. `/api/v1/builder` — `builder.py` | 需认证（路由级）
- `GET /templates` 模板列表 | `GET /templates/{template_id}` 模板详情 | `POST /validate` 校验 | `POST /build` 构建 | `GET /agents` 可构建Agent

### 62. `/api/v1/computer` — `computer.py` | 需认证（shell/file 读写另加管理员门）
- 桌面操作: `POST /screenshot` 截图 | `POST /click` 点击 | `POST /type` 输入 | `POST /scroll` 滚动 | `POST /smart-click`、`POST /smart-type` 智能操作 | `POST /shell`（管理员） | `POST /file/read`、`POST /file/write`（管理员） | `GET /status` 状态 | `GET /doctor` 诊断
- 浏览器: `POST /browser/navigate` 导航 | `POST /browser/screenshot` | `POST /browser/click` | `POST /browser/type` | `POST /browser/extract-text|extract|extract-links` 抽取 | `POST /browser/execute-js|execute` 执行 | `POST /browser/snapshot` 快照 | `POST /browser/click-role|fill-role` 角色定位 | `POST /browser/capabilities` 能力 | `POST /browser/scrape` 抓取

### 63. `/api/v1/shared-config` — `shared_config.py` | 需认证（写面另加管理员门）
- `GET /` 读取 | `PUT /` 更新（管理员） | `GET/POST /llm-providers`、`GET/PUT/DELETE /llm-providers/{name}` LLM供应商 | `GET/POST /mcp-servers`、`GET/PUT/DELETE /mcp-servers/{name}` MCP服务器 | `GET /export` 导出 | `POST /import` 导入（管理员）

### 64. `/api/v1/openplatform` — `openplatform_keys.py` | 需认证（路由级）
- `GET /` 密钥列表 | `POST /` 创建 | `GET/PUT/DELETE /{key_id}` | `POST /{key_id}/revoke` 吊销 | `GET /{key_id}/usage` 用量 | `GET /scopes` 可用作用域

### 65. `/api/v1/model-adapter` — 已移除
- 该模块未实现，已从本文档移除（2026-11-19 核对：无 `model_adapter.py`，`ENDPOINT_MODULES` 无此注册项）。

### 66. `/api/v1/context` — `context.py` | 需认证
- `POST /build` 构建上下文 | `POST /build/v2` 构建上下文 v2 | `GET /stats` 统计 | `GET /composition` 组成 | `GET /budget` 预算 | `GET /{context_id}/preview` 预览 | `POST /{context_id}/compress` 压缩 | `GET /inject/reflection`、`GET /inject/memories`、`GET /inject/hot` 注入面

### 67. `/api/v1/context-pool` — 已移除
- 该模块未实现，已从本文档移除（2026-11-19 核对：无 `context_pool_settings.py`，`ENDPOINT_MODULES` 无此注册项）。

### 68. `/api/v1/metacognition` — `metacognition_api.py` | 需认证
- 均按 agent：`GET /{agent_id}/metacognition` 记录 | `POST /{agent_id}/metacognition` 写入 | `GET /{agent_id}/metacognition/stats` 统计 | `GET /{agent_id}/metacognition/state` 状态 | `GET /{agent_id}/metacognition/lessons` 教训 | `GET /{agent_id}/metacognition/history` 历史 | `POST /{agent_id}/metacognition/reflect` 反思

---

## 八、其他模块 (8模块)

### 69. `/api/v1/agent-enhancement` — `agent_enhancement.py` | 需认证（路由级）
- 均按 agent：`GET /{agent_id}/status` 状态 | `GET /{agent_id}/capabilities` 能力 | `GET /{agent_id}/health` 健康 | `POST /{agent_id}/restart` 重启

### 70. `/api/v1/agent-communication` — `agent_communication_api.py` | API Key 或登录（`get_current_user_or_api_key`，路由级）
- API 密钥: `POST /api-keys` 签发 | `GET /api-keys` 列表 | `PUT /api-keys/{key_id}` 更新 | `POST /api-keys/{key_id}/revoke` 吊销 | `DELETE /api-keys/{key_id}` 删除
- 消息: `POST /handshake` 握手 | `POST /messages/send` 发送 | `GET /messages` 收取
- 外部 Agent: `GET/POST /external-agents` | `GET /external-agents/{agent_id}/status` 状态 | `GET /routing/stats` 路由统计

### 71. `/api/v1/logs-api` — `logs_api.py` | 需认证（路由级）
- `POST` 写入 | `GET` 查询 | `GET /daily-summary` 日报 | `GET /weekly-report` 周报 | `GET /stats` 统计 | `GET /export` 导出

### 72. `/api/v1/memory-enhancement` — `memory_enhancement.py` | 需认证（路由级）
- `POST /{memory_id}/forget` 遗忘 | `POST /{memory_id}/strengthen` 强化 | `GET /categories` 分类 | `POST /batch` 批量操作 | `GET /export` 导出 | `POST /import` 导入

### 73. `/api/v1/audio` — `audio.py` | 需认证
- `POST /synthesize` 合成 | `POST /synthesize-stream` 流式合成 | `POST /transcribe` 转写 | `GET /status` 状态 | `GET /engines` 引擎列表 | `GET /asr/local-whisper/status` 本地Whisper状态 | `POST /asr/local-whisper/consent` 本地Whisper同意

### 74. `/api/v1/sync` — `session_sync.py` | 需认证
> 原 §74 标题写 `/api/v1/session-sync`，前缀有误：注册表挂 `/v1/sync`（`__init__.py:304`），实际前缀即 `/api/v1/sync`（2026-11-19 核对改写）。
- `POST /sessions` 创建会话 | `GET /sessions` 会话列表 | `GET /sessions/{session_id}` 会话详情 | `GET /sessions/{session_id}/history` 历史 | `POST /sessions/{session_id}/messages` 追加消息 | `DELETE /sessions/{session_id}` 删除 | `GET /statistics` 统计 | `GET /connections` 连接 | `WS /ws/{session_id}` 会话同步

### 75. `/api/v1/memory-share-groups` — `memory_share_groups.py` | 需认证（路由级）
- `GET/POST` 分享组 | `GET/PUT/DELETE /{group_id}` | `POST /{group_id}/agents` 加入Agent | `DELETE /{group_id}/agents/{agent_id}` 移除Agent | `GET /{group_id}/agents` 成员列表 | `GET /agent/{agent_id}` 按Agent查组 | `GET /agent/{agent_id}/shared-agents` 可共享Agent | `GET /check/{agent_id_1}/{agent_id_2}` 两两共享判定

### 76. `/api/v1/language` — `language_api.py` | 需认证（写面另加管理员门）
- 本人语言偏好：`GET /preferences/mine`（只读，没设过如实回 `configured:false`，不替用户建一条）｜
  `PUT /preferences/mine`（属主**只从登录态取**，请求体 `extra="forbid"`，多写 `user_id` 直接 422）
- 开箱默认（§6-167 取进来的那一格）：`GET /preferences/default`（登录即可读）｜`PUT /preferences/default`（**仅管理员**）
  它只作用于**还没自己选过语言的人**，本人一旦选过就以其本人偏好为准；落盘是 `language_preferences.json` 顶层的**可选 `default` 键**——不占 `preferences` 里的用户行（占了就会被读成「这个人做过决定」），也**不抬存储版本**（抬了会让已落盘的按人偏好被自己的版本隔离逻辑改名隔离，那是凭空丢真数据）
- 读数把两件事分开给：`configured`＝这个人自己做过决定没；`source` ∈ `user`/`out_of_box`/`builtin`＝这条读数是哪个来源给的。来源词汇只在 `LanguageManager.EFFECTIVE_SOURCES` 定义一处（UI 侧那份常量只在 `NeurUI/src/api/modules/language.ts`，判据按文件面钉住）
- 译文覆盖层：`GET /overlay?language=&namespace=`（含**未审**条目，逐条带 `approved`/`translator`）｜
  `PUT /overlay/{namespace}`（**仅管理员**；`{key: {语言码: 文案}}`，坏语言码整批 400 并点名）
- 语言码归一只走 `Language.normalizeTag`（本面不写第二刀）；`auto` 不许当首选/回退语言，
  那一层语义由 `auto_detect` 承载（台账 §6-140/§6-145 的同一根因，别在新字段上重建）
- 偏好落盘：数据根下 `language_preferences.json`（**刻意不放进 `language/` 译文目录**——
  那里每个 `*.json` 都会被当成一个命名空间读进来）；写盘失败回 500 且内存回滚，不谎报已保存
- 实测：无凭证各读面均 401、普通用户写面 403（活体 `tests/manual/languageFace_batch14.py`
  第 [22]/[13] 项，台账 §6-160）；`/preferences/default` 那两面同样实测——非管理员写 403、无凭证读 401（活体 `tests/manual/languageFace_outOfBox_batch167.py` 第 [4]/[19] 项，台账 §6-167）

---

## 附录

### 认证需求总结

> **本表已停用（2026-10-22，§6-399）**：原先按"模块"给出「无需认证」名单，实测**系统性错误**。
> 复算口径：真 `create_app()`，按 `include_context` 展开（顶层 `_IncludedRouter.path` 为空，
> 直接读它会得到"零路由"的假读数），逐路由读依赖图里的身份/角色门；**不请求任何端点**。
> 读数：附录列的 60 个模块中 56 个能在 `/api/v1/<module>` 找到路由，其中**只有 `health` 是
> 全公开**、**55 个至少有一条路由需认证**；这些前缀共 972 条路由，**542 条需认证、45 条公开**。
> 同一份文件里 `settings` 仍留在「无需认证」行，而它的模块节已写「需认证」并抄了实测 401——
> 手写汇总与模块节自相矛盾，这就是停用的原因。
>
> **以各模块节的标题为准。**「哪些端点公开」将由生成器按路由依赖图产出（下一批，含
> freshness 守卫），不再手写；生成器落地前，要确认某个面就看该模块节，或无凭证打一条
> **已存在**的路由（401/403＝有门；404/405 不算门，别把"路径写错"读成"没门"）。

仍有据可查的两条归类（来自模块节，不由本表推导）：

| 认证类型 | 模块 |
|----------|------|
| **API Key** | `agent-communication` |
| **HTTPBearer** | `mobile` |

### 公开面清单（机器段）

<!-- auth-surface:begin -->
> 本段由 `scripts/generate_api_auth_surface.py`（`--write`）生成，**不要手改**：
> 守卫 `tests/unit/api/test_authSurfaceFreshness.py` 逐字比对，漂移即红。
> 口径：只认**路由依赖图**里的身份/角色门；在 handler 体内自验 token 的那一类**未覆盖**，要确认它只能真打请求。404/405 不算门。

**汇总**：路由 1036 条（含方法展开）——需认证 **1016**、公开 **20**。

| 模块前缀 | 路由 | 需认证 | 公开 |
|----------|------|--------|------|
| `agent-communication` | 12 | 12 | 0 |
| `agent-enhancement` | 4 | 4 | 0 |
| `agents` | 15 | 15 | 0 |
| `analytics` | 5 | 5 | 0 |
| `api` | 37 | 37 | 0 |
| `artifacts` | 2 | 2 | 0 |
| `audio` | 9 | 9 | 0 |
| `audit` | 5 | 5 | 0 |
| `auth` | 10 | 0 | 10 |
| `backups` | 3 | 3 | 0 |
| `benchmark` | 16 | 16 | 0 |
| `budgets` | 7 | 7 | 0 |
| `build` | 6 | 6 | 0 |
| `builder` | 5 | 5 | 0 |
| `channel-adapters` | 14 | 13 | 1 |
| `channel-configs` | 16 | 16 | 0 |
| `channel-sharing` | 7 | 7 | 0 |
| `chat` | 6 | 6 | 0 |
| `collaboration` | 27 | 27 | 0 |
| `computer` | 25 | 25 | 0 |
| `computers` | 11 | 10 | 1 |
| `console` | 30 | 30 | 0 |
| `context` | 10 | 10 | 0 |
| `cost-rollup` | 8 | 8 | 0 |
| `diagnostics` | 1 | 1 | 0 |
| `enhanced-memory-search` | 11 | 11 | 0 |
| `enhanced-users` | 6 | 6 | 0 |
| `evolution` | 19 | 19 | 0 |
| `experience` | 7 | 7 | 0 |
| `external-agents` | 4 | 4 | 0 |
| `files` | 12 | 12 | 0 |
| `firewall` | 6 | 6 | 0 |
| `generation` | 10 | 10 | 0 |
| `governance` | 38 | 38 | 0 |
| `groups` | 8 | 8 | 0 |
| `growth` | 13 | 13 | 0 |
| `health` | 6 | 1 | 5 |
| `home` | 2 | 2 | 0 |
| `image` | 5 | 5 | 0 |
| `knowledge` | 10 | 10 | 0 |
| `knowledge-graph` | 12 | 12 | 0 |
| `knowledge-integration` | 10 | 10 | 0 |
| `language` | 6 | 6 | 0 |
| `logs` | 4 | 4 | 0 |
| `logs-api` | 6 | 6 | 0 |
| `marketplace` | 12 | 12 | 0 |
| `media` | 15 | 15 | 0 |
| `memory` | 71 | 71 | 0 |
| `memory-enhancement` | 6 | 6 | 0 |
| `memory-settings` | 7 | 7 | 0 |
| `memory-share-groups` | 11 | 11 | 0 |
| `memory-timeline` | 4 | 4 | 0 |
| `metacognition` | 7 | 7 | 0 |
| `mobile` | 19 | 16 | 3 |
| `models` | 15 | 15 | 0 |
| `monitor` | 5 | 5 | 0 |
| `negative-screen` | 4 | 4 | 0 |
| `neurflow` | 47 | 47 | 0 |
| `notifications` | 9 | 9 | 0 |
| `openplatform` | 8 | 8 | 0 |
| `phase3` | 15 | 15 | 0 |
| `plans` | 6 | 6 | 0 |
| `plugins` | 24 | 24 | 0 |
| `projects` | 16 | 16 | 0 |
| `providers` | 13 | 13 | 0 |
| `quality` | 4 | 4 | 0 |
| `rules` | 8 | 8 | 0 |
| `runtime` | 4 | 4 | 0 |
| `sandbox` | 8 | 8 | 0 |
| `scheduler` | 9 | 9 | 0 |
| `semantic-search` | 5 | 5 | 0 |
| `settings` | 13 | 13 | 0 |
| `shared-config` | 14 | 14 | 0 |
| `skill-pool` | 37 | 37 | 0 |
| `skill-versions` | 8 | 8 | 0 |
| `skills` | 8 | 8 | 0 |
| `sleep` | 15 | 15 | 0 |
| `stats` | 9 | 9 | 0 |
| `studio` | 21 | 21 | 0 |
| `sync` | 8 | 8 | 0 |
| `synonyms` | 12 | 12 | 0 |
| `tasks` | 8 | 8 | 0 |
| `teams` | 10 | 10 | 0 |
| `tool-layers` | 11 | 11 | 0 |
| `tools` | 7 | 7 | 0 |
| `trace` | 5 | 5 | 0 |
| `webhooks` | 7 | 7 | 0 |
| `workspace` | 5 | 5 | 0 |

**依赖图里未见身份门的路由（候选集，不等于「无凭证可打」）**：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/recover-password`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/register/invite`
- `POST /api/v1/auth/register/send-code`
- `POST /api/v1/auth/register/verify-code`
- `GET /api/v1/auth/setup-status`
- `POST /api/v1/channel-adapters/{channel_type}/webhook`
- `POST /api/v1/computers/{computer_id}/heartbeat`
- `GET /api/v1/health`
- `GET /api/v1/health/checks`
- `GET /api/v1/health/checks/{name}`
- `POST /api/v1/health/recover`
- `GET /api/v1/health/report`
- `POST /api/v1/mobile/pairing/confirm`
- `POST /api/v1/mobile/pairing/refresh`
- `POST /api/v1/mobile/pairing/resolve`
<!-- auth-surface:end -->

> **抽样复核（裁定 C，2026-10-22）**：对机器段里 49 条安全的 GET 逐条以无凭证真打（隔离数据根）
> ——校准格 `GET /api/v1/settings` 回 401；49 条中 **2 条回 401**：`GET /api/v1/auth/me`、
> `GET /api/v1/computers/cloud`。它们正是「handler 体内自验」那一类（依赖图里看不到门），
> 所以上面的清单是**候选集**、不是「无凭证可打」的证明；判定某个面请以真打为准。
> 复跑：`tests/manual/authSurfacePublicProbe_batch.py`。

> 脚注（§6-158）：`media` 原先挂在"无需认证"那一行，与实况不符——`media.py:40` 是
> `APIRouter(dependencies=[Depends(get_current_user)])`，无凭证请求实测回 **401**
> （活体第 [8] 项）。这张表**没有逐模块复核过**，其余条目同样可能是旧的：本批只按实测改了
> 自己动过的那一格，不做整表顺手清扫（那需要一次自己的复算与裁定，登记在台账）。
>
> 追加（§6-160）：`language` 这一行是**按实测新加的**，不是照旧表抄的——两个读面无凭证 401、
> 覆盖层写面对普通用户 403（活体第 [22]/[13] 项）。旧表那张"无需认证"名单至今仍未逐模块复核。

### 项目统计

| 指标 | 数值 |
|------|------|
| 后端API模块 | 96（`ENDPOINT_MODULES` 注册表行数，2026-11-19 实测） |
| 端点总数 | 1250（按各端点文件 `@router` 装饰器计数，2026-11-19 实测） |
| GET端点 | 571 |
| POST端点 | 502 |
| PUT端点 | 98 |
| DELETE端点 | 76 |
| 需认证端点 | 未复核（旧读数「~100」已不可采信，见上方停用说明；机器段口径见「公开面清单」汇总） |
| 公开端点 | 未复核（旧读数「~525」与实测相反：同口径下公开仅 45） |
| 前端覆盖 | 94.7% (71/75)（2026-09 旧读数，本批未复核） |

> 模块数与端点四类计数为 2026-11-19 按代码实测复核（grep `@router` 装饰器，含 `memory/` 子包与 websocket）；
> 认证两行已停用（§6-399）；前端覆盖行沿用 2026-09 旧统计。

---

> **文档结束** — Neurova API Reference v1.0.0-beta1