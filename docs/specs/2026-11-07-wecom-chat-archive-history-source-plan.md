# 企微聊天历史消息（会话内容存档）摄取方案 —— 2026-11-07 立项，批 C7 候选

> **状态：方案，未开工。本文件不附带任何代码改动，也不改动任何生产模块。**
> 关联：连接器立项方案 [`2026-11-07-enterprise-source-connectors-plan.md`](2026-11-07-enterprise-source-connectors-plan.md) §2.4-3/§3-C6（本方案是 C6 留下的「历史消息拉取」那一格的兑现路径）；
> 台账 [`../audit-reports/simplification-audit-2026-10-05.md`](../../audit-reports/simplification-audit-2026-10-05.md) §6-576/§6-577 留裁定项。

---

## §0 一页结论

1. **缺口是真实的，且今天已被诚实登记在册**：`sourceType=chat` 读的是既有入站捕获面
   `channel_ingress_events`（[connectors_chat.py:135](../../neurova/knowledge/enterprise/connectors_chat.py)），
   覆盖面＝「机器人被拉进群之后、回调推得到的那些消息」。**开通存档前的历史、机器人不在群里的
   群内对话，这条路永远拿不到**——不是节流问题，是通道性质问题。
2. **合规的唯一历史通道是企微「会话内容存档」（msgaudit）**，其读取面是腾讯官方 C 库的
   Python 包装（本仓探测名已在册：[connectors_chat.py:41](../../neurova/knowledge/enterprise/connectors_chat.py)，
   三态 degraded 判定在 [connectors_chat.py:207](../../neurova/knowledge/enterprise/connectors_chat.py)）。
   **槽留好了，缺的只是读取面本身。**
3. **推荐的架构（甲案）：读取面落通道层，企业源侧仍是纯只读消费者**。存档凭据（存档专用 secret
   ＋RSA 私钥）是**平台凭据**，而 C6 落格时对 `connectors_chat` 的契约写得很清楚——「不接任何平台
   凭据、不建长连接、只读旁库」（该模块 docstring「数据源」条目）。把私钥塞进企业源适配器就是自毁
   契约并造出第二个凭据面；放在通道层则与 corpid/app_secret 同源同处，且天然解决
   「SDK 句柄是进程级、企业源是租户级」的错配（句柄形态属 SDK 细节，C7a 核查项，见 §15）。**代价：多一张 append-only 存档投影表。**
4. **四件事需要拍板**（各带影响面见 §14）：A 是否现在开工；B RSA 私钥落点；
   C 聊天正文落 facts 还是条目链；D 附件（`sdkfileid`）摄取触发归属。
5. **本方案不承诺「装了 SDK 就全量可达」**：前置动作全在客户企业微信后台（席位、密钥、成员同意），
   代码只能如实读数、不能代劳；无真席位时活体验证按 §12 的「双态登记」走，不冒充跑通。

---

## §1 实状复算：两条通道与各自上限

| | ① 入站捕获面（现役） | ② 会话内容存档面（本方案） |
|---|---|---|
| 数据从哪来 | 回调事件经队列落 `channel_ingress_events`（[channel_ingress_queue.py:44](../../neurova/channels/channel_ingress_queue.py) DDL，`:145` enqueue，`dedupe_key` 幂等） | 官方 SDK 按 `seq` 增量拉全企业存档 |
| 覆盖范围 | 机器人所在会话、回调可达、开通后 | **已购席位且已同意成员**的全部会话（含机器人不在场的） |
| 时间跨度 | 落库起，无回溯 | 存档开通日起，可回溯 |
| 消息形态 | 六列行集已归一（[connectors_chat.py:35](../../neurova/knowledge/enterprise/connectors_chat.py)） | 密文 → 需 RSA＋AES 双层解密 → 按 `msgtype` 归一 |
| 凭据面 | **零凭据**（只读旁库，`mode=ro` 短连接） | 存档专用 secret ＋ RSA 公私钥对 ＋ 出口 IP 白名单 |
| 今天的读数 | 正常 | `health()` 显式 `degraded`，reason 点名「会话存档 SDK 未接入，仅既有捕获面可达」 |

**已经顺带闭合的一条旧裁定**：§6-576 留裁定项③（`NEUROVA_CHANNEL_INGRESS_DB` env 名从
`manager.py` 内联字面量提为模块常量）——现查该常量已在
[channel_ingress_queue.py:41](../../neurova/channels/channel_ingress_queue.py)，代码取用处两处
（`manager.py:635` 与 `connectors_chat._resolveIngressDb`:116 内的惰性 import）共用同一常量，
单点已成立——`connectors_chat.py:118` 剩下的那次出现是 docstring 里的说明文字，不是第二份字面量取用。
**本方案只需在台账销号，不再立项。**

---

## §2 为什么只剩这一条（含明确不成立项）

- **自建应用回调面**只能事件驱动，不推的事件永远补不到——这是①的上限根因，不是实现缺陷。
- **`get_groupmsg` 系**是「应用群发任务」的记录面（谁收到了这条群发），**不是成员历史消息**，
  拿来充当历史拉取属于口径错误。本方案不把它列为候选。
- **HTTP 形态的存档拉取接口是否存在**：**待核**。仓内没有任何证据，本文不臆造端点名。
  开工批的第一件事是拿官方文档与一次真实调用把「只有 SDK」这件事证实或证伪——若 HTTP 面成立，
  §4 甲案的凭据面与依赖面都要改写（少一个第三方二进制）。
- **微信侧（个人号/微信客服/小微）无官方历史拉取通道**，本方案只覆盖企微；
  微信 vendor 的 degraded 措辞（[connectors_chat.py:209](../../neurova/knowledge/enterprise/connectors_chat.py)）原样保留。

---

## §3 客户侧前置（代码不可代劳，health 面须逐条可判）

| 前置 | 落在哪 | 未做时本方案怎么读数 |
|---|---|---|
| 后台开通「会话内容存档」并给**被存档成员**买席位 | 客户后台 | 拉取返回空 seq 区间 → `degraded: 存档无授权成员/无席位` |
| 生成 RSA 密钥对，公钥上传后台、私钥留服务端；记录 `publickey_ver` | 客户后台＋我方凭据面 | 私钥文件缺失/不可读 → `error`（点名路径，不打印内容） |
| 密钥版本轮换（公钥可多版本） | 私钥侧需版本→私钥映射 | 消息带未知 `publickey_ver` → 该条**跳过并计数**，不猜 |
| 出口 IP 进白名单；如需代理则 SDK 侧带 proxy 参数 | 部署环境 | 连接失败 → `error: 存档接口不可达（检查出口 IP 白名单）` |
| 成员与外部联系人同意被存档 | 企微客户端 | 未同意方的会话**不在存档里**——这是覆盖率缺口，须在 health reason 里如实点名「按同意状态过滤，非全量」 |

**这一表是方案的一部分，不是可选项。** C6 的纪律是「不静默冒充全量」；存档面最容易犯的错误，
就是把「按席位与同意状态过滤后的子集」报成「企业全部群聊」。

---

## §4 架构落点：读取面归通道层（甲案，推荐）

### 甲案（推荐）

```
官方 SDK(C 库句柄) ──┐
                     ├─ channels/wecom_archive.py  ← 新模块：Init / 按 seq 增量拉 / 解密 / 归一
存档凭据面（通道层）─┘         │
                              ▼ 写（唯一写路径）
                   channel_archive_messages（新表，append-only，seq 主键）
                              │ 只读 mode=ro 短连接
                              ▼
              enterprise/connectors_chat.py  ← 只把「源表」参数化，行集形状与游标风格不变
                              ▼
              registry.runOnceAsync → applyMapping → admission 唯一咽喉 → facts/条目
```

- **凭据单点不动**：存档 secret 与私钥路径进通道层的 `ChannelConfig`（`base.py:70` 现成
  `app_id/app_secret/extra` 面，`extra` 即可承载 `corpId`/`publickeyVer→私钥路径`），
  与 corpid/app_secret 同一个配置入口、同一个渠道配置页，不新造第二套凭据存储。
- **`connectors_chat` 的契约不破**：仍然「不接凭据、不建长连接、只读旁库」，
  改动面是 `_resolveIngressDb`/`_readRows` 的来源选择（捕获面 or 存档投影面）＋游标 token 的
  `since=` 语义换成 `seq`（`_parseSince` 按 `since=` 解析，形状兼容，[connectors_chat.py:196](../../neurova/knowledge/enterprise/connectors_chat.py)）。
- **SDK 进程级句柄 vs 租户级源的错配**由通道层单例消化（一个 corpid 一个句柄），
  企业源侧不需要知道 SDK 存在。
- **代价（照登）**：多一张投影表、多一个「明文消息落盘」的驻留面（见 §13 风险 2）、
  以及两段式延迟（拉取批与摄取批不同节拍）。

### 乙案（不推荐）：适配器直接接 SDK 拉取

少一张表、游标直接落 `enterprise_source_configs.cursor`（[registry.py:271](../../neurova/knowledge/enterprise/registry.py)）。
但：① 企业源适配器开始持 RSA 私钥与存档 secret——正面违背 C6 在册承诺与「凭据面单点在通道层」；
② SDK 句柄进程级、描述符租户级，多企业场景要在适配器里再造一层句柄注册表，那是第二条凭据生命周期线；
③ 捕获面与存档面在同一个适配器里各写一套读取分支，`health()` 三态判定要翻倍。
**判：甲案。**（教义第 6 条——凭据面只允许一处；第 7 条——比较后才选，不是顺手挑简单的那个。）

---

## §5 数据面：拉取 → 解密 → 归一

- **拉取**：按 `seq` 单调增量，`limit` 分批（官方建议批次上限具体值**待核**，实施时以一次真实调用定形）；
  成功后才推进水位——与 [registry.py:311-321](../../neurova/knowledge/enterprise/registry.py) 现有
  「批成功后 `saveCursor`、批失败不推进」的语义完全一致，投影表侧同规矩（拉取失败不落半行）。
- **解密链（结构性描述，细节以官方 SDK demo 为准）**：
  `encrypt_random_key` →（RSA 私钥，按 `publickey_ver` 选版本）→ AES 密钥 →
  （AES-CBC，iv 取该密钥前 16 字节）解 `encrypt_chat_msg` → 明文 JSON。
  **AES-CBC 半边必须扩展既有加解密单源** [wechat_kf_crypto.py:65](../../neurova/channels/wechat_kf_crypto.py)
  所在模块，不在存档模块里再抄一遍 AES/pkcs7/iv 取法（教义第 6/7 条）；RSA 半边是该模块今天没有的形状，
  新增函数、两个面共用一份模块。
- **归一到在册六列**（`msg_id/chat_id/chat_type/sender/sent_at/text`，[connectors_chat.py:35](../../neurova/knowledge/enterprise/connectors_chat.py)）：
  - `chat_type`：有 `roomid` → `group`（subject 语义＝群 id，模板由映射层拼，沿用 C6 口径）；无 → `p2p`；
  - `sent_at`：存档消息毫秒时间戳 → ISO8601（带时区，与捕获面 `timestamp.isoformat()` 同形）；
  - `text`：仅 `text` 类消息有正文；非文本类该列留空，靠附件列承载；
  - `media_ref`：附件透传列语义不变（[connectors_chat.py:182](../../neurova/knowledge/enterprise/connectors_chat.py)），
    但**存档侧的值形态是 `sdkfileid`，与捕获面的 `media_id` 不是同一种引用**——取字节的路径也不同
    （存档侧走 SDK 的分片媒体读取，捕获面走 `wecom.py:58 fetchWecomMediaBytes`）。
    这一点必须在 `describeSchema`/health 里点名，否则「media_ref 有值」会被读成「同一条媒体管线可达」。
- **消息类型处置（原则先定，清单待核）**：`text` 入账；`image/voice/video/file` 入行＋`media_ref`；
  `revoke`（撤回）**不回改已摄取事实**——本仓 admission 侧没有按源消息撤销的通道（见 §13 风险 3），
  如实登记为已知缺口而不是静默丢弃；`mixed`/未知类型不猜，计数并在 health 点名。

---

## §6 凭据与私钥落点（拍板项 B）

三选一，影响面：

1. **私钥文件路径进配置 ＋ 文件权限位（推荐）**：`extra.archivePrivateKeyPath` 指向磁盘私钥。
   代价：部署侧要管文件权限；好处：私钥尺寸大、不进环境变量、不进库、不进描述符，
   日志脱敏面天然简单。与 §2.4-1「凭据仍只从 env/密文面取」的口径**不冲突**——那条讲的是企业源描述符，
   本方案凭据在通道层。
2. **私钥内容进 `NEUROVA_KB_SECRET` 密文**：复用仓内唯一解密设施（`storage.decryptSecret`，
   先例 [connectors_sql.py:424](../../neurova/knowledge/enterprise/connectors_sql.py)）。
   代价：把平台凭据塞进知识库密钥面，跨域；且 RSA PEM 多行走密文面要在描述符里放行形状。
3. **私钥路径进 env 变量**：与 SQL 批 `credentialEnv` 同构，代价：通道配置页看不到、运维面分裂。

**推荐 1，并补一条硬判据（照抄 SQL 批的既有纪律）**：明文密钥出现在配置字段里即构造期拒绝
（先例 [connectors_sql.py:151](../../neurova/knowledge/enterprise/connectors_sql.py) 的「给了 password/secret 明文就拒」），
日志与 health reason 一律不落密钥与消息正文（`_redact` 先例 :443）。

---

## §7 依赖与 CI 声明面

- **SDK 是第三方二进制＋其 Python 包装**：按可选依赖纪律**不进 `requirements.txt`**，
  惰性 import 探测＋fail-soft（探测名在册，[connectors_chat.py:41](../../neurova/knowledge/enterprise/connectors_chat.py)、
  探测在 :214），未装即 degraded，**不改成崩进程**。这与 §2.4-1 的驱动豁免不同类：
  驱动是 PyPI 包、可进可选段；C 库 `.so/.dll` 不是 pip 依赖清单能表达的东西，只能作为部署前置声明。
- **解密依赖**：`cryptography>=41.0` 已在生产依赖（[requirements.txt:120](../../requirements.txt)），
  CI 锁内有 `cryptography==50.0.1`（requirements-ci.lock:62），但**是传递而来**——
  `requirements-ci.txt` 未显式声明。若本方案的解密判据要进受保护子集，按 §0 纪律应显式声明而非靠传递
  （登记为开工批的一个小动作，不在本文代做决定）。

---

## §8 量、节流与触发面

- **首轮回溯是最大风险点**：`runOnceAsync` 单轮上限＝`_RUN_ONCE_MAX_BATCHES`(20) ×
  `_FETCH_BATCH_LIMIT`(200)＝**4000 行/轮**（[registry.py:28-30](../../neurova/knowledge/enterprise/registry.py)）。
  一个中型企业几年的群聊历史远超此数——**首轮会 `truncated=True` 连续多轮**，这不是 bug，是限流在起作用；
  必须在页面/文档里把「首轮是分多轮收敛的过程」讲清，否则会被读成「同步坏了」。
- **新增一个描述符开关：`archive.backfill`（待裁）**——关＝只拉水位之后（增量），
  开＝允许从 `seq=0` 起回溯。推荐**默认关**，回溯由显式一次性触发，避免「配了个连接器就吞了三年聊天记录」。
- **常驻增量拉取**：通道层定时任务（默认关、env 门控），形态对齐既有 worker 线程先例
  （[ingest_bridge.py:343 runIngestWorker](../../neurova/knowledge/ingest_bridge.py)、
  `datasource_sync.py:257` 轮询环）；企业源侧触发面仍走现有
  `POST /enterprise/sources/{id}/ingest`（[knowledge_enterprise.py:138](../../neurova/api/endpoints/knowledge_enterprise.py)），
  不新造端点。批 C2 的「目录轮询常驻」今天**未开工**（§6-577 在册）——本方案的常驻面应与它同一节拍设计，
  避免长出两个互不知晓的常驻线程池。
- **配额**：存档接口有速率与并发限制（具体数值**待核**），实施时按具名常量＋退避重试，先例见
  ERP 批的 429 退避（`connectors_erp.py`）；不硬编码魔法数。

---

## §9 消费面：映射、facts 与「正文去哪」

- **源钟已经就位**：facts 层 `sourceCreatedAt/sourceModifiedAt` 描述符键与透传已落格
  （[schema_mapping.py:160-163](../../neurova/knowledge/enterprise/schema_mapping.py)、
  [registry.py:165-166](../../neurova/knowledge/enterprise/registry.py)）。
  **聊天记录要「按业务时间查」，这里已经不用等**——描述符把 `sent_at` 声明为源钟列即可。
  （W6/K-09 时间面四项里仍开的是检索/导出侧的读法，与本批不互为阻塞。）
- **契约面零新增**：描述符提交走编译期校验 `validateDescriptor`（变体闭集 `chat.vendor` ∈
  wecom/wechat，[schema_mapping.py:21-26](../../neurova/knowledge/enterprise/schema_mapping.py)），
  存档面的新字段（`archive.*`）沿用同一校验面；**映射里不写 SQL 的形状守卫照旧生效**（:112）。
- **拍板项 C：聊天正文落点。** C6 的在册承诺是「聊天原文不整段进 facts，正文归 narrative/条目链」
  （`connectors_chat.py` docstring 末段），但今天的通用映射把 `object.kind=column` 的列值直接写进
  `AdmissionRequest.objectTerm/content`——**即：把 `text` 列配成 object，就把整句聊天记录灌进了 facts**。
  - 甲：正文进**条目链**（复用 `ingest_bridge` 的消息→条目通道），facts 只承结构化断言
    （谁-在哪个群-何时-说了什么的**索引**，或根本只承「成员活跃度/话题归属」类聚合）。
    代价：需要一条「chat 行 → 条目」的受控路径，而这条路径今天对**历史行**不存在（bridge 服务的是入站消息）。
  - 乙：正文进 facts 的 object（描述符照现状配）。
    代价：**facts 表被历史聊天淹没**，本体层的术语/谓词面被自然语言脏化，检索召回质量与
    双时态裁决都会退化；与 C6 在册承诺相悖。
  - 丙：**两条并存但按消息长度/类型分档**（结构化字段进 facts，正文进条目）。
    代价：分档规则是新口径，需判据钉住，且「同一句话在两处各有一份」要由幂等键统一。
  **推荐丙的最小版**：文本消息 → 条目链承正文；`media_ref`/群/成员/时间 → facts 结构化断言。
  这不是「更省事的乙」，理由在量级：历史回溯是**十万到百万行**，facts 是本体层资产，两者混灌不可逆。

---

## §10 附件（`sdkfileid`）与触发归属（拍板项 D，承 §6-576②）

- 今天的行为：`media_ref` 只如实放进行里，适配器**刻意不主动触发**媒体下载/解析/OCR
  （[connectors_chat.py:73-77](../../neurova/knowledge/enterprise/connectors_chat.py) describeSchema 已点名）。
- 历史消息一进来，附件量远大于入站实时消息（一年群聊里的图片/文件），「谁触发」从理论问题变成容量问题：
  - 甲：**企业源侧独立触发端点**（`POST /enterprise/sources/{id}/media`）——范围可控、可逐源限流，
    但会新造一条媒体触发线。
  - 乙：**ingest 时顺带触发**（复用 `ingest_bridge` 的 `_ingestPayload`，:205）——一条线、无新端点，
    但单轮摄取耗时被媒体下载/OCR 主导，`truncated` 读数会失真。
  - 丙：**先只落 `sdkfileid` 引用，媒体面另批**（现状延续）——最小开工面，代价是「附件已采集」这句
    话只能停在 health 文案里，页面「数据量」列与实际可检索附件不一致。
  **推荐丙→甲分两步**：C7 开工批只做引用与诚实读数；媒体触发面单独一批（因为它还要裁「存档侧
  分片取字节」这条与 `fetchWecomMediaBytes` 不同的路径）。

---

## §11 判据与测试计划（红→绿落点，开工批照此执行）

| 判据档 | 落点 | 咬什么 |
|---|---|---|
| 通道层读取面 | `tests/unit/channels/test_wecomChatArchiveReader.py` | 假 SDK 夹具（按 `seq` 返回密文行）：水位只在拉取成功后推进；未同意成员的会话不出现在行集；`publickey_ver` 未知即跳过并计数；SDK 缺席时 `health` 三态各判其对 |
| 解密单源扩展 | `tests/unit/channels/test_wecomCryptoSingleSource.py` | 存档侧 AES-CBC 走 `wechat_kf_crypto` 同一函数（AST/调用面反证：存档模块内**不得**再出现 AES Cipher 构造）；RSA 半边失败即显式抛，不静默返回密文 |
| 投影表只读契约 | `tests/unit/knowledge/enterprise/test_chatArchiveSource.py` | 存档面与捕获面**同一六列行形状**（同体判据，避免两套列名）；`media_ref` 值形态点名是 `sdkfileid`；游标 `since=` 承载 `seq` |
| 凭据面 | 同企业源档 | 明文私钥进配置字段即构造期拒（照抄 SQL 批判据形状）；日志与 reason 无密钥、无消息正文 |
| 量与幂等 | 同企业源档 | 首轮 `truncated=True` 多轮收敛；重放同一 `seq` 区间 `admitted=0`（咽喉内容键，`tests/unit/knowledge/enterprise/test_enterpriseIngestAdmission.py` 先例） |
| 反向守卫 | `tests/unit/test_repair_discipline_guard.py` 同族 | 不新造第二套凭据存储/第二个写口/第二条媒体触发线（凡甲案落点偏离即红） |

夹具纪律沿用 C6：**按真实 schema 自建自插**（不 import 队列类，避免真连接与迁移副作用，
见 `tests/unit/knowledge/enterprise/test_chatConnector.py:30-48` 注释）；红灯必须红在行为断言上，
不得红在 import/collection——装配噪声先排掉，且红必须证明被测分支真被走到。

---

## §12 活体验证路径（不做即不算完成）

1. **有真企微测试企业＋存档席位**：提交 `chat.vendor=wecom` 描述符（存档面）→ 触发 ingest →
   读回 facts/条目，逐条核对 `sent_at` 落进 facts 源钟、群聊 subject＝群 id；
   再拉一段含图片的时间窗，核对 `media_ref` 引用形态与 health 点名一致。
2. **无席位（大概率是开工当场的状态）**：按 §6-577 的**双态登记**口径——假夹具全链绿＋
   「真租户凭据待配」进台账，**不得**用假夹具冒充活体跑通。
3. `python start.py --check` 与前后端两道门（`npm run test`／`npx vue-tsc --noEmit`）随批执行；
   受保护子集在册数现场复算，不手抄。

---

## §13 风险与回退

1. **隐私与合规是第一位风险，不是技术风险**：存档面的可见范围由**席位＋成员同意**决定，
   与「机器人所在群」无关——一次误配就可能把大量非本业务所需的员工对话灌进知识库。
   缓解（必须落进开工批）：`archive.backfill` 默认关；按 `roomid`/成员白名单在**通道层落库前**过滤
   （不是摄取后再删）；文档与页面文案写明「存档范围由企微后台决定，本系统只读能读到的」。
2. **明文消息落盘的驻留**：甲案引入投影表，表里是解密后的聊天正文。
   开工批须裁其保留策略（摄取成功后是否清理正文、清理是否走既有存档/擦除设施）。
   今天的擦除闭集**不含 `source:` 前缀**（[registry.py:238-246](../../neurova/knowledge/enterprise/registry.py)
   `deleteConfig` 注释已点名：删连接器只删配置，不碰已摄取事实）——**级联清除是另一个立项**，
   本方案不冒充它有。
3. **撤回（revoke）不回改**：历史里被撤回的消息已进 facts/条目的部分无法撤回。如实登记缺口。
4. **回退动作两挡且不相冒充**（沿用立项方案 §4-1 的在册口径）：
   `enabled=False` 关闸（零拉取零网络）／通道层不启动存档 worker（投影表不再增长）；
   两者读数不同，页面须分开显示（§6-561 两态纪律）。
5. **与在途改动撞车**：并发会话正在重写 `channels/wecom.py`（协议合规＋token 单源，
   工作树里有未跟踪的 `neurova/channels/wecom_token.py` 与 `tests/unit/channels/test_wecomProtocolCompliance.py`）。
   本方案的通道层新模块与那批同域——**开工前须等那批合流**，否则同文件双写。

---

## §14 待拍板四项（各带影响面）

| | 选项 | 选了会导致 | 不可逆点 | 推荐 |
|---|---|---|---|---|
| **A 开工时机** | 现在开工 C7a（前置核查＋凭据面＋投影表，不含拉取）／整批 C7 一起做／只做 HTTP 面可行性核查 | 整批做要先解决 SDK 二进制分发（`.so/.dll` 不是 pip 件），部署面未定即写读取面＝纸上代码 | 无（方案阶段） | **先 C7a＋HTTP 面核查**，读取面待部署口径定 |
| **B 私钥落点** | 私钥文件路径＋权限位／`NEUROVA_KB_SECRET` 密文／env | 后两者把平台凭据搬进知识库密钥面或运维面分裂 | 私钥一旦进过库/日志，泄露面永久存在 | **文件路径＋权限位**，明文进配置即拒（照抄 SQL 批判据） |
| **C 聊天正文落点** | 条目链承正文／正文进 facts object／分档并存 | 纯 facts 档：历史回溯十万级行淹掉本体层资产，术语/谓词退化，**且不可逆（删不净，见风险 2）** | facts 一旦灌入自然语言正文 | **分档最小版**（§9 推荐） |
| **D 附件触发归属** | 独立触发端点／ingest 内联／先只落引用 | 内联让单轮耗时被 OCR 主导、`truncated` 读数失真；独立端点＝新造一条媒体触发线 | 无（引用列已就位） | **先只落引用**，媒体触发面另批（含存档侧分片取字节） |

---

## §15 分批与顺序（供拍板后执行，本文不开工）

- **C7a 前置核查与凭据面**：官方文档核实「HTTP 存档拉取是否存在」＋SDK 分发形态与部署口径；
  通道配置面加存档字段；私钥落点与权限位判据；health 三态文案定稿。**不含任何拉取逻辑。**
- **C7b 读取面与投影表**：`channels/wecom_archive.py`（Init/seq/解密/归一/过滤），
  加解密单源扩展，`connectors_chat` 来源参数化，游标换 seq；判据见 §11 前三行。
- **C7c 消费面与量控**：`archive.backfill` 默认关、roomid/成员白名单落库前过滤、
  常驻增量 worker（与 C2 轮询同节拍）、正文分档落点（承 §14-C 裁定）、页面读数（连接器列表的
  「数据量」列与存档范围对齐，见 `NeurUI/src/pages/EnterpriseSourcesPage.vue:201/609` 的 chat 向导段）。
- **依赖关系**：C7b/C7c 依赖 C7a 的两项核查结论；§14-C 的裁定决定 C7c 的映射判据形状。
  三批各自可独立验证，任一批出问题按 §13-4 两挡回退。
