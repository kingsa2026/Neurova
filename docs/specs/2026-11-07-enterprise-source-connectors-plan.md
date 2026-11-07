# 企业源真连接器立项方案（2026-11-07）

> 定位：兑现台账 §6-561/§6-564「企业源真连接器另立项」的立项草稿——B14 已把接入面固定为
> 可测试契约（适配器 Protocol、映射描述符、admission 接线），本文回答三个问题：
> 真连接器插在哪、零第三方依赖约束下先做哪几类、分几批怎么验收。
> 事实源：`neurova/knowledge/enterprise/`（protocols/schema_mapping/registry/fake_adapter）、
> `neurova/api/endpoints/knowledge_enterprise.py`、`neurova/knowledge/foundation/admission.py`、
> `requirements.txt`（依赖现值）、`specs/2026-09-20-knowledge-foundation-design.md` §0（六决策）、
> `specs/2026-11-05-ontology-capability-upgrade-plan.md` §14（B14 详设）、
> `specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md`、
> `audit-reports/simplification-audit-2026-10-05.md` §6-561/§6-564/§6-567。
> 硬约束：`specs/2026-09-20-knowledge-foundation-design.md` §0 六决策全程有效——
> 零新增第三方依赖（`requirements.txt` 不新增包）、不引外部服务（SQLite＋本地 ONNX）。

---

## §0 一页结论

**B14 落完后，企业源到 facts 的「管道」每一节都在位且互相咬合，缺的是两段：**
把外部世界行集送进 `fetchBatch` 的真实适配器（今天只有测试桩），以及把适配器跑起来的生产触发面（今天零调用）。

- 链路上游（REST 描述符提交→编译期校验→v34 配置表）、中游（映射→`AdmissionRequest`）、
  下游（admission 唯一写咽喉→facts→查询面）全部已接线、有判据、有守卫；
- 断点不在「死码」，在「差最后一公里」：`EnterpriseIngestor.ingestBatch` 生产调用面为零，
  适配器注册表生产恒空，REST 无任何触发摄取端点——今天唯一喂行方式是测试桩直调（§1.2 给影响面）；
- ~~选型按依赖现值裁定~~ → **2026-11-07 用户裁定改判（见 §2.4）**：数据库直连
  **直接做**（四驱动按可选依赖纪律引入，六决策第 4 项豁免登记）；ERP **先做金蝶与用友**
  （httpx REST 对接，不引 SDK）；新增 **企微＋微信（小微）聊天信息源**批（聊天/群聊
  ＋聊天记录中的图片与文档）；§2.3 两项均按推荐（1A 单类型＋变体字段、2A 先手动触发
  端点后轮询）；
- 全部新连接器走同一 Protocol、输出同一 `ChangeBatch`、经同一 admission 写口——
  不新造第二套摄取路径（教义第 6 条）；全部默认 `enabled=False` 关闸，配置存了≠源连上了。

---

## §1 现状走查：协议入口 → schema mapping → admission

### §1.1 链路全景（数据从哪来、经谁处理、到哪去、谁消费）

**写入链（B14 已落部分，全部现场核实）：**

1. **REST 入口**：`neurova/api/endpoints/knowledge_enterprise.py` 三端点，经
   `knowledge.py:109-110` 聚合挂载、前缀 `/api/v1/knowledge`（`knowledge.py:17`）：
   - `GET /api/v1/knowledge/enterprise/sources`（登录可读，列表）；
   - `GET /api/v1/knowledge/enterprise/sources/{source_id}`（登录可读，未提交 404）；
   - `POST /api/v1/knowledge/enterprise/sources`（仅管理员，`knowledge_enterprise.py:96`）。
2. **编译期校验**：POST 先过 `schema_mapping.validateDescriptor()`（`schema_mapping.py:39`）——
   `sourceType` 必须在白名单 `SOURCE_TYPES = ("sql", "erp_api", "event_stream")`
   （`protocols.py:15`）；`columns` 非空；subject 模板占位符必须是已声明列；predicate `termId`
   必须已在 `OntologyTermRegistry` 登记；object.kind 闭集（`column/template/term/literal`，
   `schema_mapping.py:16`）；qualifier 与 validFrom/validUntil 列必须已声明；描述符全文禁 SQL
   形状片段。非法整条拒（`MappingError`，带定位），零落库。
3. **配置落库**：`EnterpriseIngestor.saveConfig()`（`registry.py:121`）写 v34 表
   `enterprise_source_configs`（`schema_mapping.py:21-32`；迁移经
   `foundation_schema.py:115-116` 注册表挂入，PRIMARY KEY (tenant_id, source_id)）。
   `enabled` 默认 False——**提交描述符 ≠ 开始摄取**。
4. **读面两态**：GET 回显 `enabled`（配置开关）与 `adapter_registered`（读进程内唯一适配器
   注册表 `getSourceRegistry()`，DCL 单例 `registry.py:46-58`）。两态不相冒充：
   **配置存下来了 ≠ 源能连上了**。
5. **摄取链**：`EnterpriseIngestor.ingestBatch(descriptor, rows, cursorToken)`
   （`registry.py:73`）→ 每行 `applyMapping()`（`schema_mapping.py:95`，R2RML 风格 JSON
   子集的运行期半边）→ 每行一条 `AdmissionRequest`（`activityKind="import"`、
   `actorType="importer"`、`mediumRef="source:<id>:<cursor>"`，`registry.py:101-107`）→
   `productionAdmissionGate(store).admitBatch()`（`admission.py:565` / `:409`）→ facts。
6. **咽喉语义**（`admission.py:284` `admit()`）：内容身份归一 → 内容键去重（重放折回旧行，
   幂等由咽喉承担）→ 溯源断言必填（匿名知识写入前即拒）→ 按租户分区。坏一行只退它自己，
   逐条 finding 留名（`ingestBatch` 把 `admitBatch` 的拒因按 index 原样带回）。
7. **消费面**：facts 落库后进既有读取面——`searchableFacts()`、`/access/*` 查询门面、
   质量报告；时间面读法如 `temporal_facts.py:104`（生效时间取 `valid_from`，缺列回退
   `recorded_at`）。

**对照文档/条目链**：文档链的源时间透传在 `ingest_bridge.py:245-246`
（`source_created_at=srcCreated` / `source_modified_at=srcModified`），属条目三时间戳契约
（2026-11-04 spec）。企业源行链今天**不携带**行级源时间进 `AdmissionRequest`——映射面只有
`validFrom/validUntil`（事实生效窗口列）；facts 层源钟（按源 `modified_at` 排新者）是
在册尾巴（§6-567①：`conflict_judge.py:117` 仍按 `recorded_at` 选 most_recent）。
本方案不抢跑（§2.3 拍板项三）。

### §1.2 今天靠什么喂（断点影响面）

grep 复算（2026-11-07 现场）：`ingestBatch` / `ingestIfEnabled` 的调用面**只有测试档**
（`tests/unit/knowledge/enterprise/test_enterpriseIngestAdmission.py`），生产代码零调用；
`getSourceRegistry().register()` 生产零调用——注册表在生产进程里**恒空**，
`adapter_registered` 恒 False；REST 三端点里没有任何一个触发摄取。

**影响面（不许只给「缺真连接器」一句的定性）**：

- **现在能实现什么**：企业源描述符的提交/校验/落库/两态回显全链真通；`fake_adapter.py`
  （进程内行集、游标按偏移、health 可注入故障）在测试里证明「行→映射→咽喉→facts→查询读回」
  全段咬合（`test_enterpriseIngestAdmission.py` 五格：落库/坏行不拖批/重放幂等/跨租户不可见/注册表白名单默认空表）。
- **数据从哪来到哪去（缺的那段）**：外部源行集 → `adapter.fetchBatch` 这一步没有真实实现；
  也没有任何生产入口能把行喂进 `ingestBatch`——数据进不来，中下游（映射、咽喉、facts、
  查询面）处于「管道通、无水」状态。
- **不接线留下什么**：企业数据进知识库只有两条现役替代路径——人工整理成文档走
  `ingest_bridge` 文档链（叙述行，丢结构化 SPO 形状），或逐条手工走本体流水线
  `pipeline/run`（无批量增量语义）。结构化企业数据（订单/工单/主档）的批量、增量、
  幂等摄取今天为零。

---

## §2 连接器候选清单与取舍

### §2.1 依赖约束的证据基线

- 依赖单一事实源 = `requirements.txt`（`pyproject.toml` 头注：**刻意不设**
  `[project].dependencies`，两处声明必然漂移；锁文件与守卫
  `tests/unit/test_lock_integrity_guard.py` 兜底）。
- `requirements.txt` 现值（2026-11-07 复算）：`httpx>=0.25.0`（:8）、`aiohttp>=3.14.5`（:12）、
  `requests>=2.31.0`（:143，`channels/feishu_auth.py:12` 模块级 import）。CI 薄环境
  `requirements-ci.txt:31` 同收 httpx。httpx 的生产消费方已在位：
  `llm_client.py:354`、`api/endpoints/webhooks.py:181`、`channels/qrcode_auth.py`（多处）。
- `watchdog`、`paho-mqtt` **不在** `requirements.txt`（`ingest_mqtt.py` 对 paho 是可选惰性
  import，未装即保持进程内路径）。
- 六决策（`specs/2026-09-20-knowledge-foundation-design.md` §0）：零新增第三方依赖
  （`requirements.txt` 不新增包）＋零新增外部服务（全部落 SQLite＋本地 ONNX）。
  **判据：下表每一行的依赖结论都以 `requirements.txt` 现值为准，不以「应该有」为据。**

### §2.2 候选清单

| # | 候选 | 对接什么 | 取舍 | 理由与依赖风险 |
|---|------|----------|------|----------------|
| 1 | 文件行源（CSV/TSV/JSON/JSONL） | 本地/挂载路径上的结构化行文件 | **进，批 C1** | stdlib `csv`/`json`，零依赖；一行源行＝描述符 `columns` 的一行，与 `applyMapping` 的输入形状天然同构；可测性最好（临时文件即夹具）。风险：编码与 CSV 方言（§4 有对策，先只承诺 utf-8/utf-8-sig） |
| 2 | 目录轮询监听 | 热目录里新增/变更的行文件 | **进，批 C2** | 标准库 `os.scandir`/`os.stat` 轮询 mtime，零依赖。事件式监听（inotify/watchdog 类）需要第三方包且平台行为不一——不进；轮询间隔具名常量可配、**默认关**（env 门控）。仓内先例齐：`datasource_sync.py` 的游标持久化/失败不推进游标/互斥（第二路立即 `SyncBusyError`）三件套照搬语义 |
| 3 | SQLite 旁库只读挂接 | 企业侧自落地的 `.db` 文件 | **进，批 C2** | stdlib `sqlite3` 只读 URI（`mode=ro`）开**独立连接**；不 ATTACH 进主库连接池（旁库 schema 不可控，混进主库连接是写坏主库的门）。`cursorColumn` 取旁库行的 `updated_at` 列即天然增量。风险：锁竞争——只读连接＋短事务，不碰旁库写面 |
| 4 | HTTP 拉取（JSON API） | 企业内网 JSON 端点（分页列表/导出接口） | **进，批 C3** | `httpx>=0.25.0` **已在依赖清单且生产在用**（§2.1 证据）——零新增即合规；`fetchBatch` 是 async，与 httpx 异步客户端直接对齐。不新写 requests/aiohttp 第二套 HTTP 面（同功能不并存，教义第 7 条）。风险：超时/重试面（具名常量上限）、凭据只从 `NEUROVA_KB_SECRET` 解密、日志不落凭据与原始行全文（B14 §14.3 安全面原文有效） |
| 5 | Oracle/MSSQL/PostgreSQL/MySQL 直连 | 企业数据库 | **缓** | 驱动（oracledb/pymssql/pyodbc/psycopg 类）全是第三方包——**每引一个即破六决策第 4 项**；且企业库直连引入网络可达性、凭据、防火墙审批一整面。**未来若放开约束的接法**：实现 `EnterpriseSourceAdapter` 四动词（describeSchema/fetchBatch/health/close）→ 经 `getSourceRegistry().register()` 进白名单 → 输出同一 `ChangeBatch` → 经同一咽喉——协议已在位，核心零改动。**过渡路径（今天就能到）**：企业侧 ETL 把库表落成 CSV/SQLite 旁库，走候选 1/3 |
| 6 | ERP API（SAP/金蝶/用友类 SDK）与事件流（Kafka/CDC/MQTT） | ERP 厂商 SDK / 消息中间件 / 变更数据捕获 | **缓** | SDK 与消费端框架均第三方依赖；CDC 需外部进程/服务，违反「不引外部服务」。仓内 `ingest_mqtt.py` 已有的 MQTT 属**入站消息传输**（企微/飞书入站队列的可选跨进程通道），与「结构化行摄取连接器」功能不同——不并（教义第 7 条比较后不合并），也不是本方案的搭车口 |

### §2.3 待拍板项（2026-11-07 已全部拍板，均按推荐）

1. **`SOURCE_TYPES` 扩展粒度**——**拍 1A**：单类型＋变体字段。
   - `SOURCE_TYPES` 扩为 `("sql", "erp_api", "event_stream", "file", "http_pull", "chat")`；
   - 变体细分走描述符字段：`file.format`（csv/tsv/json/jsonl）、`sql.driver`
     （postgresql/mysql/mssql/oracle/sqlite）、`erp_api.vendor`（kingdee/yongyou）、
     `chat.vendor`（wecom/wechat）——白名单与变体闭集都在 `validateDescriptor`
     单点校验，注册面不翻倍；
   - 适配器类按 (sourceType, 变体) 分派，一份族一份读取器。
2. **生产触发面形态**——**拍 2A**：批 C1 先做 REST 手动触发端点
   （管理员，`POST /api/v1/knowledge/enterprise/sources/{source_id}/ingest`），
   批 C2 补目录轮询常驻线程（默认关，env 门控）。手动触发语义＝「现在跑一轮」，
   与后续轮询并存不冲突。
3. **行级源时间落 facts 源钟**——已随 K-09 源钟批落定（见上）。

### §2.4 2026-11-07 用户裁定（对本方案原取舍的改判，逐条登记）

1. **数据库直连（Oracle/MSSQL/PostgreSQL/MySQL）直接做**——推翻原「缓」判。
   - 代价照登：四个驱动（oracledb / pymssql / PyMySQL / psycopg2-binary）全是
     第三方包，**六决策第 4 项（零新增第三方依赖）就此开豁免口**——豁免登记见
     `specs/2026-09-20-knowledge-foundation-design.md` §0 补记（2026-11-07）。
   - 补偿措施（不可省）：① 驱动只进 `requirements.txt` 可选段，**不进 CI 薄环境**
     （`requirements-ci.txt` 不加）；② 适配器惰性 import＋fail-soft——驱动未安装时
     `health()` 显式 `error: driver not installed`，`adapter_registered=False`，
     进程不崩、注册表不半死；③ 测试全走假 cursor/连接夹具，CI 零驱动依赖；
     ④ 凭据仍只从 `NEUROVA_KB_SECRET` 解密，日志不落凭据与原始行全文。
2. **ERP API 先做金蝶与用友**——推翻原「SDK 类全缓」判的一半：金蝶云星空 WebAPI
   与用友（U8C/YonSuite）开放 API 均为 HTTP REST，**经已在依赖清单的 httpx 对接
   （候选 4 同款），不引厂商 SDK**——依赖面零新增，原判 SDK 的理由对 REST 化
   对接不成立。
3. **新增聊天信息源批（企微＋微信/小微）**——采集聊天、群聊信息，含聊天记录中的
   图片与各种文档。
   - 仓内现状（现场核实）：企微/微信通道层已厚（`channels/wecom.py`、`wechat*.py`
     七个 mixin、`mediaIngress.py`），**消息入站→知识条目的桥已在**
     （`ingest_bridge.py` category="wecom"，语音转写/媒体下载/OCR 元数据字段在位）；
   - 缺口＝①B14 协议化接入（chat 源与行源同走 admission 咽喉）；②**历史消息拉取**：
     企微侧官方通道是「会话存档」SDK（腾讯原生 C 库，第三方二进制）——按第 2 条
     同一原则先走 REST/既有通道可达面，会话存档 SDK 留适配槽：凭据未配时
     `adapter_registered=False`＋finding 点名，不静默空转；③附件（图片/文档）复用
     既有媒体下载＋解析＋OCR 管线，不重写第二套。
   - 「微信小微」按微信端助手通道（既有 WeChatAdapter/微信客服面）接入解释；
     若指腾讯小微独立产品，`chat.vendor` 字段留扩展位，接入面不变。
3. **行级源时间（`source_modified_at`）落 facts 源钟**。
   - **（2026-11-07 更新：本项已随 K-09 源钟批落定，不再是待拍板项。）** facts 源钟已按
     台账 §6-570 三裁定落格（v36 迁移：`knowledge_facts.source_created_at/source_modified_at`；
     `conflict_judge.most_recent` 改读 `COALESCE(source_modified_at, recorded_at)`），
     且 B14 映射 DSL 已同批补 `sourceCreatedAt/sourceModifiedAt` 两个描述符键（同
     `validFrom` 模式）＋`registry` 透传。本方案三批的连接器只需在描述符里声明源时间列，
     行级源时间即沿唯一咽喉落列——原 A 案「不抢跑」的前提（咽喉先有钟）已成立。
   - 影响面：增量语义仍由**游标水位＋咽喉内容键**承担；facts 源钟在此基础上让
     「新者胜」裁决与检索 tie-break 读到真实源文档时间。

---

## §3 实施路线（三批，每批独立可验证）

> 每批纪律：先红后绿（红灯文件转绿前不进 `scripts/ci/protected_tests.txt`）、
> live-verify 证据（命令＋输出原文）进提交说明、台账下一空号落格（现查）。
> 测试落点统一 `tests/unit/knowledge/enterprise/`（现役目录，命名对齐 `test_enterprise*`）。

### 批 C1 · 文件行源连接器（CSV/TSV/JSON/JSONL 同构一组）＋ 生产触发面

- **改动点**：`neurova/knowledge/enterprise/connectors_file.py`（新模块，单一适配器类按
  `format` 分派读取器——四格式不写四套类）；`protocols.py:15` 白名单扩 `"file"`（拍板项 1A）；
  `knowledge_enterprise.py` 增 `POST /api/v1/knowledge/enterprise/sources/{source_id}/ingest`
  （管理员；`loadConfig` → 构造适配器 → `register` 进注册表 → `fetchBatch` 循环 →
  `ingestBatch`；`enabled=False` 时回 skipped，零读取）。不碰 `agent_core.py`（尺寸棘轮）。
- **红绿测试落点**：`tests/unit/knowledge/enterprise/test_fileConnector.py`。
  红灯先证：`sourceType="file"` 注册被 ValueError 拒（白名单现状）、无连接器类。
  绿灯判据：`describeSchema` 从文件头推 `columns`；`fetchBatch` 游标＝（文件指纹＋行偏移）
  推进、空批显式 `hasMore=False`；全量重入幂等（同一文件重放，facts 行数不增）；
  坏行逐条 finding 不拖批；`enabled=False` 零读取零落库；`adapter_registered` 翻 True。
- **活体验证路径**：真后端 9527（`start_server.py:80`，缺省 `NEUROVA_PORT=9527`）——
  登录取管理员 token → `POST …/enterprise/sources` 提交 CSV 描述符（`enabled=true`）→
  `GET …/enterprise/sources/{id}` 复读 `enabled=true`＋`adapter_registered=true` →
  `POST …/{id}/ingest` → 事实查询面读回 SPO；再重放 ingest 一次复算 facts 行数不变（幂等）。

### 批 C2 · SQLite 旁库只读挂接 ＋ 目录轮询

- **改动点**：`connectors_sqlite.py`（只读 URI 独立连接；旁库写面显式拒绝）；`connectors_dir.py`
  ＋常驻轮询线程（env 门控默认关；单源单飞互斥；游标持久化复用
  `enterprise_source_configs.cursor` 列——表结构零改动）。白名单按拍板项 1 的裁定扩。
- **红绿测试落点**：`test_sqliteRoConnector.py`、`test_dirPollConnector.py`。
  绿灯判据：对旁库的写意图显式 error 不静默；轮询一轮一个 source 同时只允许一路
  （第二路立即让路，`SyncBusyError` 同款语义）；源文件拉取失败→游标不推进→下轮重试；
  清单残缺时抑制「游标有、本轮无→删」的收敛（`datasource_sync.py` 三纪律照搬）。
- **活体验证路径**：9527 上挂真 SQLite 旁库与真目录（临时数据根，不动 `data/` 主库指纹），
  端到端：改旁库一行 → 触发 → 查询面见新值；目录轮询开闸后落新文件 → 一轮内被摄取。

### 批 C3 · HTTP 拉取

- **改动点**：`connectors_http.py`（httpx 异步客户端；超时/重试上限/单批行数上限具名常量；
  凭据从 `NEUROVA_KB_SECRET` 解密；响应分页 token → `SourceCursor`）。白名单扩 `"http_pull"`
  （拍板项 1A）。
- **红绿测试落点**：`test_httpPullConnector.py`。夹具用标准库 `http.server` 起本机回环端口
  （不外网、不引新依赖）。绿灯判据：分页游标按响应 next-token 推进；超时→`health()` 显式
  error→游标不推进；重试上限到达后显式失败（不吞成空批）。
- **活体验证路径**：9527 对本机回环夹具端点拉真批 → facts 读回；日志面复算不含凭据与原始行全文。

### 批 C4 · 数据库直连（2026-11-07 裁定：直接做，依赖豁免见 §2.4-1）

- **改动点**：`connectors_sql.py`——`sql.driver` ∈ (postgresql/mysql/mssql/oracle/sqlite)
  分派驱动模块（全部惰性 import＋fail-soft）；`describeSchema` 走 information_schema
  等价查询（每驱动一小段、假 cursor 可测）；`fetchBatch` 按 `cursorColumn` 水位增量；
  sqlite 驱动复用 C2 旁库的只读 URI 纪律（同一份代码两个入口时不并两套——教义第 7 条
  比较：sqlite 作 sql.driver 的实现即 C2 connectors_sqlite 的收编方向，落地时对比后合）。
- **红绿测试落点**：`test_sqlDirectConnector.py`——全部假 connection/cursor 夹具，
  CI 零驱动依赖；判据：驱动缺失→`health()` 显式 error 点名（不半死）、游标水位推进、
  写意图（任何非 SELECT 形状）显式拒绝、凭据不落日志。
- **活体验证路径**：sqlite 驱动用真实旁库文件端到端（零网络）；四网络驱动按
  「假连接全格＋真凭据待配」双态如实登记（无内网库时 live-verify 到注册与
  health 面）。

### 批 C5 · ERP REST 连接器（2026-11-07 裁定：先做金蝶与用友）

- **改动点**：`connectors_erp.py`——`erp_api.vendor` ∈ (kingdee/yongyou) 分派两族
  REST 客户端（httpx；金蝶云星空 WebAPI：登录态＋ExecuteBillQuery 分页；用友
  U8C/YonSuite：token 换取＋单据列表分页；凭据 `NEUROVA_KB_SECRET`）。
  **不引厂商 SDK**（裁定依据 §2.4-2：REST 化对接经 httpx 零新增依赖）。
- **红绿测试落点**：`test_erpConnectors.py`——httpx MockTransport 夹具（登录/过期
  重登/分页推进/限频 429 退避）；判据：会话过期自动重登一次再失败才报错、
  游标按单据号/时间戳推进、凭据与原始报文不落日志。
- **活体验证路径**：真租户凭据待配——live-verify 到「注册成功＋health 显式
  auth_required」双态；真账套拉数留凭据到位后补记。

### 批 C6 · 聊天信息源（2026-11-07 裁定：企微＋微信/小微）

- **改动点**：`connectors_chat.py`——`chat.vendor` ∈ (wecom/wechat)；桥接既有通道层
  （`channels/wecom.py`、`wechat*.py`、`mediaIngress.py`）而非另起凭据面：
  消息/群聊经既有入站捕获 → 本适配器把会话流按 B14 协议送 admission
  （谁/哪个群/何时/说了什么 → SPO＋narrative）；**附件（图片与文档）复用既有
  媒体下载＋解析＋OCR 管线**；历史消息拉取：企微侧官方通道为「会话存档」原生
  SDK（腾讯 C 库，第三方二进制）——适配槽留出，凭据未配时
  `adapter_registered=False`＋finding 点名「会话存档 SDK 未接入」，不静默空转；
  REST 可达面（回调补拉）先落。
- **红绿测试落点**：`test_chatConnector.py`——假通道事件夹具；判据：私聊/群聊
  都成账（群聊 subject＝群 id＋消息 id）、附件消息产条目且源钟＝消息时间、
  历史拉取未配凭据显式 finding、聊天原文不整段进 facts（narrative 承正文，
  facts 承结构化字段）。
- **活体验证路径**：9527 真后端＋企微测试应用凭据（既有通道凭据面）——
  发一条群消息 → 触发 → facts/条目读回；附件消息走媒体下载→条目→OCR 元数据。
  微信侧按既有凭据面同法。
- **历史消息拉取（本批留槽，未开工）**：路径与前置已另出方案
  `specs/2026-11-07-wecom-chat-archive-history-source-plan.md`（批 C7 候选）——会话内容存档是唯一合规
  历史通道，读取面与存档凭据归通道层、企业源侧仍零凭据只读；该方案的四项待拍板（开工时机/
  私钥落点/正文落点/附件触发归属）中，**附件触发归属一项正是本批 docstring 里挂着的裁定项**。

---

## §4 风险与回退

1. **连接器故障不影响主库（fail-soft 让路）**：写面只有 admission 一个咽喉，连接器侧
   无任何直插 SQL 的通道（描述符编译期就禁 SQL 形状）。故障三态显式（`SourceHealth`
   ok/degraded/error，不静默空批）；fetch 失败 → 游标不推进 → 下轮必然重试；坏行只退
   它自己；单源互斥防重入拖库。**回退动作两挡且不相冒充**：`enabled` 置 False（关闸，
   零调用零网络）/ 注册表不 `register`（`adapter_registered` 如实回 False）——
   两态分开正是 B14 留下的回退抓手。
2. **大文件限流**：`fetchBatch(limit)` 分页是协议义务（fake adapter 已按偏移分页示范）；
   单批行数上限与轮询间隔均为具名常量、默认温和；文件源逐行流式读（`csv.reader` 迭代器），
   不整文件载入内存；批量写走 `admitBatch` 单事务面。作业化（超长文件挂 `ingest_jobs`
   队列）留作 C2 可选增强，C1 不做。
3. **编码与 CSV 方言**：沿用本仓「缺失不猜」哲学（2026-11-04 spec：元数据缺失留空，
   不回退猜测值）——编码不可判定 → 显式拒因 finding，**不做静默字节替换**；描述符可显式
   声明 `encoding`（首版只承诺 `utf-8`/`utf-8-sig`，BOM 不炸）与 CSV 方言参数
   （delimiter/quotechar，stdlib `csv` 原生面）；方言探测判不准即显式拒，不猜。
   GBK/GB18030 的实际命中面**待核**（企业侧样例数据进来后按实况扩，扩即加测试格）。
4. **增量与全量重入**：首轮空游标＝全量快照；此后按 `cursorColumn`（源侧 `updated_at`
   类列）增量；幂等由 (sourceId, idempotencyKey) → 咽喉内容键去重承担，重放不产生
   重复事实（`test_enterpriseIngestAdmission.py` 已钉）。游标只在 source batch 完成后推进，
   逐行拒因不阻塞水位——语义 B14 §14.3 已定，连接器只遵守不改造。
5. **与知识库三时间戳的对齐**：条目级三时间戳（源创建/源修改/入库）已在文档链落地
   （`ingest_bridge.py:245-246` 透传）；facts 层源钟是在册尾巴（§6-567①，按
   `recorded_at` 选 most_recent 的读法未被源时间取代）。本方案按拍板项 3A 处理：
   增量正确性由游标水位＋内容键幂等保证，不依赖 facts 源钟；源钟尾巴落地后，
   连接器把行级 `modified_at` 接进 `AdmissionRequest` 即完成对齐——契约只增，连接器
   侧改动预计仅一行映射面。
6. **回退总闸**：三批全部默认关闸上线；任何一批出问题，停用对应 env 门控/置 False 即回到
   B14 现状（管道在、无水、零网络调用），无数据回滚需求——坏行在咽喉外就已被拒。

---

## §5 不做什么

- 不做 Oracle/MSSQL/PostgreSQL/MySQL 直连驱动、ERP SDK、Kafka/CDC 消费端（§2.2 依赖裁定，缓办）；
- 不做事件式文件监听（watchdog 类不在依赖清单，轮询够用且可判）；
- 不做跨表 join、聚合、子查询与全量 R2RML 引擎（B14 §14.2 边界延续，映射里不写 SQL）；
- 不做写回源（适配器只读边界不动）；
- 不新造第二套凭据存储（复用 `NEUROVA_KB_SECRET`）、不新造第二个写口（admission 唯一咽喉）、
  不碰 `agent_core.py`（尺寸棘轮）、不新增任何 `requirements.txt` 包；
- 不在前端提供任何「假已连接」态（两态回显纪律延续，§6-561 已立）。

---

## §6 与已有工作的关系

- **B14（`specs/2026-11-05-ontology-capability-upgrade-plan.md` §14）**：本方案是 §14.5
  「真实连接器另立项」的立项兑现。Protocol、描述符、v34 配置表、admission 接线全部原样
  复用，本方案只补「最后一公里」（真适配器＋触发面）——不新造平行体系（教义第 6 条）。
- **台账 §6-561/§6-564/§6-567**：企业源真连接器作为「仍开」项在册；本方案立项后，
  实施批次逐格销号，销号时在台账引用本文件批次号。
- **`neurova/knowledge/datasource_sync.py`**：连接器的运行纪律先例（游标持久化、失败不推进、
  互斥、残缺抑制删除）。模式对齐、实现不合并——它服务飞书文档落库（叙述条目链），
  本方案服务结构化行摄取（facts 链），功能不同不并（教义第 7 条比较后裁定）。
- **`specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md`**：源时间语义对齐的出处；
  facts 源钟尾巴（§6-567①）是本方案拍板项 3A 的依赖声明，非阻塞项。
- **`specs/2026-09-20-knowledge-foundation-design.md` §0 六决策**：全程硬约束；
  本方案每一步的依赖结论以 `requirements.txt` 现值为准（§2.1）。
