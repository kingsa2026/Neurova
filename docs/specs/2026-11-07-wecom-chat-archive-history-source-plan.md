# 企微聊天历史消息（会话内容存档）摄取方案 —— 2026-11-07 立项，批 C7

> **状态：四项待拍板已全部裁定（2026-11-08，用户「选择甲案 其余的需要拍板的按推荐走」）——
> 架构取甲案，A/B/C/D 各按本文推荐项。**C7a（前置核查＋凭据面＋health 文案）已落格**
> （台账 §6-584：`channels/wecom_archive.py`＋写入口 400＋health 改接单点，判据 31 格、
> 六发变异探针各只红该红、live-verify 四判据 exit 0）；**C7b（读取面＋投影表＋RSA 半边）
> 已落格**（台账 §6-585：ctypes 薄包装＋`pullArchiveBatch` 按 seq 增量拉＋归一＋
> `channel_archive_messages` 投影表＋`wechat_kf_crypto` RSA 半边＋`connectors_chat`
> `chatSource` 两态与存档只读面，新增判据 28 格；实测 cryptography 错钥 PKCS1v15
> 可能不抛返垃圾，已补 AES 合法钥长判据挡在半边）；**C7c 未开工**（backfill 默认开、
> 白名单落库前过滤、常驻 worker、水位落后读数、正文分档、页面读数）；媒体触发面另批。
> C7a 的官方文档核查结论见 §16，它推翻了本文初稿的**四条**前提，
> 相关各节已就地更正并标注「C7a 核查更正」。**
> 关联：连接器立项方案 [`2026-11-07-enterprise-source-connectors-plan.md`](2026-11-07-enterprise-source-connectors-plan.md) §2.4-3/§3-C6（本方案是 C6 留下的「历史消息拉取」那一格的兑现路径）；
> 台账 [`../audit-reports/simplification-audit-2026-10-05.md`](../../audit-reports/simplification-audit-2026-10-05.md) §6-576/§6-577 留裁定项。

---

## §0 一页结论

1. **缺口是真实的，且今天已被诚实登记在册**：`sourceType=chat` 读的是既有入站捕获面
   `channel_ingress_events`（[connectors_chat.py:135](../../neurova/knowledge/enterprise/connectors_chat.py)），
   覆盖面＝「机器人被拉进群之后、回调推得到的那些消息」。**开通存档前的历史、机器人不在群里的
   群内对话，这条路永远拿不到**——不是节流问题，是通道性质问题。
2. **合规的唯一历史通道是企微「会话内容存档」（msgaudit），且只有经典 C SDK 那一面能把正文带回本仓**
   （C7a 核查更正，实证见 §16）。官方只分发 **C 动态库**（linux x86/arm、windows），
   **没有官方 Python 包**——仓内在册的探测名 `WeWorkFinanceSdk`
   （[connectors_chat.py:41](../../neurova/knowledge/enterprise/connectors_chat.py)）**不对应任何可安装件**，
   那次 `importlib.import_module` 恒 ImportError，三态判定（:207）因此永远停在第一档。
   C7a 把它退役，换成原生库可达性探测。
3. **「历史」有硬上限：官方只允许拉 ≤5 天的会话记录**（C7a 核查更正）。
   所谓「全量历史」＝**开通存档那天起定期拉取＋本地累积**，不是「某天补拉三年前」。
   这条改变了 §8 的回溯语义：投影表不是可选优化，而是**唯一能让历史超过 5 天的设施**。
4. **架构取甲案（已裁）：读取面落通道层，企业源侧仍是纯只读消费者**。存档凭据（存档专用 secret
   ＋RSA 私钥）是**平台凭据**，而 C6 落格时对 `connectors_chat` 的契约写得很清楚——「不接任何平台
   凭据、不建长连接、只读旁库」（该模块 docstring「数据源」条目）。把私钥塞进企业源适配器就是自毁
   契约并造出第二个凭据面；放在通道层则与 corpid/app_secret 同源同处，且天然解决
   「SDK 句柄是进程级、企业源是租户级」的错配。**代价：多一张 append-only 存档投影表。**
5. **本方案不承诺「装了 SDK 就全量可达」**：前置动作全在客户企业微信后台（席位、密钥、成员同意、
   2026-06-15 起的 90 天定期授权），代码只能如实读数、不能代劳；无真席位时活体验证按 §12 的
   「双态登记」走，不冒充跑通。

---

## §1 实状复算：两条通道与各自上限

| | ① 入站捕获面（现役） | ② 会话内容存档面（本方案） |
|---|---|---|
| 数据从哪来 | 回调事件经队列落 `channel_ingress_events`（[channel_ingress_queue.py:44](../../neurova/channels/channel_ingress_queue.py) DDL，`:145` enqueue，`dedupe_key` 幂等） | 官方 SDK 按 `seq` 增量拉全企业存档 |
| 覆盖范围 | 机器人所在会话、回调可达、开通后 | **已购席位且已同意成员**的全部会话（含机器人不在场的） |
| 时间跨度 | 落库起，无回溯 | **官方只给 ≤5 天**（C7a 核查更正）；更早的历史只能靠定期拉取＋本地累积 |
| 消息形态 | 六列行集已归一（[connectors_chat.py:35](../../neurova/knowledge/enterprise/connectors_chat.py)） | 密文 → RSA 私钥解出密钥 → **官方 SDK `DecryptData` 出明文**（AES 半边在 SDK 内，不在本仓）→ 按 `msgtype` 归一 |
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
- **HTTP 形态的存档拉取接口**：**C7a 已核，结论是「存在但对自建应用不可用，且不带正文」**（实证见 §16-2/§16-3）。
  - ISV 面 `POST /cgi-bin/chatdata/sync_msg`：官方文档对**自建应用、代开发、第三方**三种应用类型
    一律标注「暂不支持」——本仓的企微通道是自建应用（corpid/agentid），这条路今天走不通。
  - 数据与智能专区 `sync_msg`：请求方法官方写明「通过 SDK 调用」，返回的是**元数据＋
    `service_encrypt_info`（加密密钥）**，**不返回消息正文**；那把密钥是给专区内其它接口
    （模型分析等）用的，即数据留在专区里。它能回答「谁在哪个群何时说了哪种类型的消息」，
    不能回答「说了什么」。
  - **判：只有经典会话内容存档 C SDK 那一面能把正文带回本仓**，§4 甲案的凭据面与依赖面照此定形。
- **微信侧（个人号/微信客服/小微）无官方历史拉取通道**，本方案只覆盖企微；
  微信 vendor 的 degraded 措辞（[connectors_chat.py:209](../../neurova/knowledge/enterprise/connectors_chat.py)）原样保留。

---

## §3 客户侧前置（代码不可代劳，health 面须逐条可判）

| 前置 | 落在哪 | 未做时本方案怎么读数 |
|---|---|---|
| 后台开通「会话内容存档」并给**被存档成员**买席位 | 客户后台 | 拉取返回空 seq 区间 → `degraded: 存档无授权成员/无席位` |
| 取**聊天内容存档专用 Secret**（管理端→管理工具→聊天内容存档，**不是应用 Secret**） | 客户后台＋我方凭据面 | 未配置 → `degraded`，reason 点名去哪取 |
| 生成 **RSA 2048 位**密钥对，公钥上传后台、私钥留服务端；记录 `publickey_ver` | 客户后台＋我方凭据面 | 私钥文件缺失/不可读/位数不对 → `error`（点名路径与原因，不打印内容） |
| 密钥版本轮换（公钥可多版本） | 私钥侧需版本→私钥映射 | 消息带未知 `publickey_ver` → 该条**跳过并计数**，不猜 |
| 出口 IP 进白名单；如需代理则 SDK 侧带 proxy 参数 | 部署环境 | 连接失败 → `error: 存档接口不可达（检查出口 IP 白名单）` |
| 成员与外部联系人同意被存档 | 企微客户端 | 未同意方的会话**不在存档里**——这是覆盖率缺口，须在 health reason 里如实点名「按同意状态过滤，非全量」 |
| **定期拉取（≤5 天窗口）**：官方明写「获取会话记录内容不能超过 5 天，如果企业需要全量数据，则企业需要定期拉取聊天消息」 | 部署侧常驻节拍（C7c） | 停拉超过 5 天 → 那段历史**永久取不回**，health 须点名水位落后天数 |
| **数据与智能专区定期授权**（2026-06-15 起，90 天有效） | 客户后台 | 授权过期 → errcode **48002**；本方案走经典存档面，此项只在客户改用专区时相关 |

**这一表是方案的一部分，不是可选项。** C6 的纪律是「不静默冒充全量」；存档面最容易犯的错误，
就是把「按席位与同意状态过滤后的子集」报成「企业全部群聊」。

---

## §4 架构落点：读取面归通道层（甲案，推荐）

### 甲案（推荐）

```
官方 C 动态库(ctypes 薄包装) ──┐
                              ├─ channels/wecom_archive.py  ← C7a 只落凭据面＋就绪读数；
存档凭据面（通道层）──────────┘                              C7b 再加 Init/按 seq 增量拉/解密/归一
                                         │
                                         ▼ 写（唯一写路径）
                              channel_archive_messages（新表，append-only，seq 主键）
                                         │ 只读 mode=ro 短连接
                                         ▼
                         enterprise/connectors_chat.py  ← 只把「源表」参数化，行集形状与游标风格不变
                                         ▼
                         registry.runOnceAsync → applyMapping → admission 唯一咽喉 → facts/条目
```

- **凭据单点不动**：存档凭据的**指针**进通道层 `ChannelConfig.extra`（`base.py:70` 现成面），
  与 corpid/app_secret 同一个配置入口、同一个渠道配置页，不新造第二套凭据存储。
  **指针不是值**（C7a 定形，理由见 §6）：`archiveSecretEnv`＝环境变量名、
  `archivePrivateKeys`＝`{publickey_ver: 私钥文件路径}`、`archiveSdkPath`＝原生库路径。
  企业源适配器只向通道层要一个**就绪读数（reason 字符串）**，凭据值与路径都不过它的手。
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

## §5 数据面：拉取 → 解密 → 归一（C7a 核查更正后定形，实证见 §16-1）

- **拉取**：`GetChatData(sdk, seq, limit, proxy, passwd, timeout, chatDatas)`——
  **从 `seq+1` 开始返回**，首轮 `seq=0`，任意 seq 可重入；`limit ≤ 1000`；
  官方速率上限 **≤4000 次/分钟**。成功后才推进水位——与
  [registry.py:311-321](../../neurova/knowledge/enterprise/registry.py) 现有
  「批成功后 `saveCursor`、批失败不推进」的语义完全一致，投影表侧同规矩（拉取失败不落半行）。
  返回行＝`seq / msgid / publickey_ver / encrypt_random_key / encrypt_chat_msg`；
  `msgid` 带 `_external`（外部联系人）/`_updown_stream`（上下游）后缀。
- **解密链（更正：AES 半边不在本仓）**：
  `encrypt_random_key` → base64 解码 → **RSA PKCS1（2048 位模数，按 `publickey_ver` 选私钥）**
  → 得到 `encrypt_key` → 连同 `encrypt_chat_msg` 交给官方 **`DecryptData(encrypt_key, encrypt_msg, msg)`**
  → 明文 JSON。**AES-CBC 由 SDK 内部完成，本仓不实现、也不该实现。**
  初稿「AES-CBC 半边必须扩展 `wechat_kf_crypto`」一句**作废**：那条纪律的前提是本仓自己解 AES，
  而官方接口把明文直接给出来了。本仓只新增 **RSA 半边**，落
  [wechat_kf_crypto.py](../../neurova/channels/wechat_kf_crypto.py) 同一模块（该模块今天只有 AES，
  RSA 是新形状），两个面共用一份模块、不在存档模块里另起加解密炉灶（教义第 6/7 条）。
  RSA 失败即显式抛，不静默返回密文。
- **明文消息形状**：`{"msgid","action":"send|recall|switch","from","tolist":[],"roomid",
  "msgtime":<UTC 毫秒>,"msgtype":"text","text":{"content"}}`。
  - `from`＝同企业 userid 或外部 external_userid（机器人 `wb` 开头、外部联系人 `wo`/`wm` 开头）；
  - `roomid` 空＝私聊；群聊 subject 语义＝群 id（沿用 C6 口径，模板由映射层拼）；
  - 引用/回复消息官方会**在正文前加前缀**「这是一条引用/回复消息：」（英文环境
    "This is a quote/reply:"）——归一时**原样保留**，不猜着剥（剥错就是改原文）。
- **归一到在册六列**（`msg_id/chat_id/chat_type/sender/sent_at/text`，[connectors_chat.py:35](../../neurova/knowledge/enterprise/connectors_chat.py)）：
  - `msg_id` ← `msgid`（保留后缀，它是区分内外部会话的一部分）；
  - `chat_type`：有 `roomid` → `group`；无 → `p2p`；
  - `sent_at`：`msgtime` **毫秒** → ISO8601（带时区，与捕获面 `timestamp.isoformat()` 同形）。
    ⚠ 专区面 `send_time` 是**秒**，两面单位不同，归一函数必须按面分开，不共用一个除数；
  - `text`：仅 `msgtype=text` 有正文；非文本类该列留空，靠附件列承载；
  - `media_ref`：附件透传列语义不变（[connectors_chat.py:182](../../neurova/knowledge/enterprise/connectors_chat.py)），
    但**存档侧的值形态是 `sdkfileid`，与捕获面的 `media_id` 不是同一种引用**——取字节的路径也不同
    （存档侧走 `GetMediaData` 的 `index_buf` 分片续传，捕获面走 `wecom.py:58 fetchWecomMediaBytes`）。
    这一点必须在 `describeSchema`/health 里点名，否则「media_ref 有值」会被读成「同一条媒体管线可达」。
- **消息类型处置（更正：`action` 与 `msgtype` 是两个维度）**：
  - `action=send` 入账；`action=recall`（撤回）**不回改已摄取事实**——本仓 admission 侧没有
    按源消息撤销的通道（见 §13 风险 3），如实登记为已知缺口而不是静默丢弃；
    `action=switch`（会话切换/员工离职继承）不是消息正文，计数不入账；
  - `msgtype`：经典存档面是**字符串**（`text`/`image`/`voice`/`video`/`file`/`mixed`…），
    专区面是 **0–28 的数字**——两面枚举不同源，**不合并成一张表**（合并即造出假单源）；
    本方案只走经典面，故只认字符串枚举；未知类型不猜，计数并在 health 点名。

---

## §6 凭据与私钥落点（拍板项 B —— **已裁：文件路径＋权限位**）

三个候选的影响面（裁定前的比较，留档）：

1. **私钥文件路径进配置 ＋ 文件权限位（✅ 已裁）**：`extra.archivePrivateKeys` 是
   `{publickey_ver: 磁盘私钥路径}`。代价：部署侧要管文件权限；好处：私钥尺寸大、不进环境变量、
   不进库、不进描述符，日志脱敏面天然简单。与 §2.4-1「凭据仍只从 env/密文面取」的口径**不冲突**——
   那条讲的是企业源描述符，本方案凭据在通道层。
2. **私钥内容进 `NEUROVA_KB_SECRET` 密文**：复用仓内唯一解密设施（`storage.decryptSecret`，
   先例 [connectors_sql.py:424](../../neurova/knowledge/enterprise/connectors_sql.py)）。
   代价：把平台凭据塞进知识库密钥面，跨域；且 RSA PEM 多行走密文面要在描述符里放行形状。
3. **私钥路径进 env 变量**：与 SQL 批 `credentialEnv` 同构，代价：通道配置页看不到、运维面分裂。

**硬判据（照抄 SQL 批的既有纪律）**：明文密钥出现在配置字段里即构造期拒绝
（先例 [connectors_sql.py:151](../../neurova/knowledge/enterprise/connectors_sql.py) 的「给了 password/secret 明文就拒」），
日志与 health reason 一律不落密钥与消息正文（`_redact` 先例 :443）。

### §6.1 C7a 定形：配置面只放**指针**，值一律不进 `extra`

存档专用 Secret 的落点在 C7a 实施时收口为 **`extra.archiveSecretEnv`＝环境变量名**，
而不是把 Secret 明文写进 `extra.archive_secret`。理由是实测出来的两条，不是偏好：

- **回显面**：`GET /v1/channel-config/{channel_type}` 把 `extra` **原样回读**
  （[channel_config.py:624](../../neurova/api/endpoints/channel_config.py)，`_load_store` 已 unseal）。
  `app_secret` 之所以安全是因为它是**顶层字段**、响应里只给 `app_id_masked`；
  往 `extra` 里新塞一个明文 Secret 等于把它吐给每一个有读权限的客户端。
- **封存面双源纪律**：新增凭据键名必须同步
  [secret_store.py:111 `CREDENTIAL_KEY_NAMES`](../../neurova/security/secret_store.py)
  与前端 `NeurUI/src/config/channelFields.ts` 的密码字段表（守卫
  `tests/unit/api/test_channel_credential_sealing_290.py` 逐名比对），并牵动 11 语言文案——
  而并发会话正在改 i18n。用指针则**零新增凭据键、零回显面、零文案面**。

于是 C7a 的三个配置字段全是**身份/路径/变量名类**（正是上述守卫反向控制不许混进封存集合的那一类）：

| `extra` 键 | 值形态 | 缺省时读数 |
|---|---|---|
| `archiveSdkPath` | 官方 C 动态库的磁盘路径（也可由 `NEUROVA_WECOM_ARCHIVE_SDK` 注入） | `degraded`：点名去哪配 |
| `archiveSecretEnv` | 环境变量**名**（值＝管理工具→聊天内容存档的专用 Secret） | `degraded`：点名字段名 |
| `archivePrivateKeys` | `{publickey_ver(str): 私钥文件路径}` | `degraded`：点名字段名 |

corpid 复用既有 `extra.corpid`/`app_id`，**不新造第二个 corpid 字段**。
私钥文件判据：存在且可读 → 解析为 **RSA 2048 位**（官方口径）→ POSIX 下权限位须 owner-only
（`mode & 0o077 == 0`）；**Windows 无 POSIX 权限位**，如实点名「访问控制须由部署侧 NTFS ACL 保证」，
不假装校验通过（假装通过就是教义第 2 条禁的表面抹除）。

**明文判据咬两个边界，共用一份实装**（`channels/wecom_archive.validateArchiveExtra`）：
写入口 `POST /v1/channel-configs` 命中即 **400**（在 `_save_store` 之前，拒绝理由只点名字段名、
不回显值）；读边界 `archiveReadiness` 再判一次，命中即 **`error`**——盘上存量可能是 C7a 之前落的
或手工改的，写入口拒得住不代表存量干净。不在 `WeComAdapter.__init__` 抛：那会让整条通道
装配失败，而存档面坏不该拖垮机器人收消息。

---

## §7 依赖与 CI 声明面（C7a 核查更正）

- **官方只分发 C 动态库，没有官方 Python 包**（实证见 §16-1）：linux x86 v2.0/v3.0、
  linux arm v3.0、windows v2.0/v3.0（v3.0 依赖 openssl 3.0）。因此：
  - **不进 `requirements.txt`**——`.so/.dll` 不是 pip 依赖清单能表达的东西，只能作为**部署前置声明**；
  - 本仓自写 **`ctypes` 薄包装**（标准库，零新增 pip 件）。仓内今天 `ctypes`/`find_library`/`CDLL`
    **零先例**（现查 `neurova/` 无命中），C7a 是第一处，故探测面收在通道层单点、不散落；
  - **不引入任何第三方 Python 包装**——AGENTS.md §2 原创性红线：外部依赖只作为功能依赖登记
    （版本、许可、用途），不搬运其命名/结构/措辞。官方 C 库是**功能依赖**（腾讯分发、按其许可使用），
    包装层是本仓独立实现；
  - 库路径由部署侧显式给（`extra.archiveSdkPath` 或 `NEUROVA_WECOM_ARCHIVE_SDK`），
    **本仓不猜文件名**——官方下载包内的文件名未经一次真实部署核实前不写进代码当默认值。
    未配置即 degraded 并点名去哪配，**不改成崩进程**。
  - 退役项：[connectors_chat.py:41](../../neurova/knowledge/enterprise/connectors_chat.py)
    的 `_WECOM_ARCHIVE_SDK_MODULE = "WeWorkFinanceSdk"` 与 :214 的 `importlib` 探测——
    该模块名不对应任何可安装件，探测恒 ImportError，属**假判据**（教义第 2 条：不得以恒真/恒假断言充数）。
- **解密依赖**：本仓只做 RSA 半边（§5 更正），`cryptography>=41.0` 已在生产依赖
  （[requirements.txt:120](../../requirements.txt)），CI 锁内有 `cryptography==50.0.1`
  （requirements-ci.lock:62）但**是传递而来**——`requirements-ci.txt` 未显式声明。
  C7a 的私钥解析判据若进受保护子集，按 §0 纪律应显式声明而非靠传递（登记为 C7b 的一个小动作）。

---

## §8 量、节流与触发面（C7a 核查更正：5 天窗口改变回溯语义）

- **「首轮吞掉三年历史」这个风险不存在**——官方只给 ≤5 天（§16-1）。真正的风险反过来了：
  **停拉超过 5 天，那段历史永久取不回**。于是：
  - `runOnceAsync` 单轮上限＝`_RUN_ONCE_MAX_BATCHES`(20) × `_FETCH_BATCH_LIMIT`(200)＝**4000 行/轮**
    （[registry.py:28-30](../../neurova/knowledge/enterprise/registry.py)）。5 天窗口内的消息量
    仍可能远超此数 ⇒ **首轮会 `truncated=True` 连续多轮**，这不是 bug，是限流在起作用；
    必须在页面/文档里把「首轮是分多轮收敛的过程」讲清，否则会被读成「同步坏了」。
  - **`archive.backfill` 开关的语义须重写**：`seq=0` 起回溯拿到的也只是**最近 5 天**，
    不是「全量历史」。初稿「默认关，避免吞了三年聊天记录」的理由作废；
    改成**默认开**（首次装配即从 `seq=0` 拉到当前水位），因为不拉就永久丢。此项 C7c 落判据。
  - **投影表从「可选优化」升为「必需设施」**：超过 5 天的历史只存在于本地累积里。
    §13 风险 2（明文驻留）因此不是可以靠「不建表」回避的，只能靠保留策略管理。
- **常驻增量拉取**：通道层定时任务（默认关、env 门控），形态对齐既有 worker 线程先例
  （[ingest_bridge.py:343 runIngestWorker](../../neurova/knowledge/ingest_bridge.py)、
  `datasource_sync.py:257` 轮询环）；企业源侧触发面仍走现有
  `POST /enterprise/sources/{id}/ingest`（[knowledge_enterprise.py:138](../../neurova/api/endpoints/knowledge_enterprise.py)），
  不新造端点。批 C2 的「目录轮询常驻」今天**未开工**（§6-577 在册）——本方案的常驻面应与它同一节拍设计，
  避免长出两个互不知晓的常驻线程池。**节拍上限由 5 天窗口定**：常驻周期必须远小于 5 天，
  且 health 须能报「水位落后多久」，否则静默丢历史。
- **配额（已核，不再是待核项）**：`GetChatData` **≤4000 次/分钟**、`limit ≤ 1000`；
  专区面另有每企业并发 10 的限制（本方案不走专区面）。按具名常量＋退避重试，先例见
  ERP 批的 429 退避（`connectors_erp.py`）；不硬编码魔法数。
  注意 4000 次/分钟 × 1000 行 = 理论上 400 万行/分钟，**本仓单轮 4000 行的上限是自我节流**，
  两者不是一回事，文案不许混。

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
- **拍板项 C：聊天正文落点（✅ 已裁：分档最小版）。** C6 的在册承诺是「聊天原文不整段进 facts，正文归 narrative/条目链」
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
  **✅ 已裁：丙的最小版**——文本消息 → 条目链承正文；`media_ref`/群/成员/时间 → facts 结构化断言。
  这不是「更省事的乙」，理由在量级：5 天窗口 × 常驻累积同样是**十万到百万行**，
  facts 是本体层资产，两者混灌不可逆。落判据在 C7c。

---

## §10 附件（`sdkfileid`）与触发归属（拍板项 D，承 §6-576② —— **✅ 已裁：先只落引用**）

- 今天的行为：`media_ref` 只如实放进行里，适配器**刻意不主动触发**媒体下载/解析/OCR
  （[connectors_chat.py:73-77](../../neurova/knowledge/enterprise/connectors_chat.py) describeSchema 已点名）。
- 存档面一进来，附件量远大于入站实时消息（5 天窗口里的图片/文件，加上常驻累积），
  「谁触发」从理论问题变成容量问题：
  - 甲：**企业源侧独立触发端点**（`POST /enterprise/sources/{id}/media`）——范围可控、可逐源限流，
    但会新造一条媒体触发线。
  - 乙：**ingest 时顺带触发**（复用 `ingest_bridge` 的 `_ingestPayload`，:205）——一条线、无新端点，
    但单轮摄取耗时被媒体下载/OCR 主导，`truncated` 读数会失真。
  - 丙：**先只落 `sdkfileid` 引用，媒体面另批**（现状延续）——最小开工面，代价是「附件已采集」这句
    话只能停在 health 文案里，页面「数据量」列与实际可检索附件不一致。
  **✅ 已裁：丙→甲分两步，两步均已落格**——引用与诚实读数＝C7b/C7c（台账 §6-585..587）；
  媒体触发面＝台账 §6-588：`GetMediaData` 分片续传（官方文档 91774 实证：indexbuf 在
  sdkfileid 之前、MediaData_t 句柄＋工具五件）＋`POST /enterprise/sources/{id}/media`
  独立触发端点＋`media_staged_path`「已采集」机器可判＋`ArchiveMediaUnavailable`
  引用过期独立读数；live-verify 必核：GetData char* 二进制截断风险待真库验证（双态登记）。
  **附带约束（C7a 核查得出）**：`sdkfileid` 的有效期与存档窗口同族，引用落库不等于字节永久可取——
  媒体批必须裁「引用过期后怎么读数」，不许把「有引用」报成「附件可检索」。

---

## §11 判据与测试计划（红→绿落点，开工批照此执行）

| 判据档 | 落点 | 咬什么 | 批 |
|---|---|---|---|
| 凭据面与就绪读数 | `tests/unit/channels/test_wecomArchiveReadiness.py` | 原生库路径未配置/不可加载/可加载三态各判其对；`archiveSecretEnv` 指向的 env 未设即点名；私钥版本→路径映射缺版本不猜；明文 Secret/PEM 进配置在写入口 400、在读边界 error（同一份判据，理由不回显值）；POSIX 权限位 owner-only，Windows 如实点名不假通过；reason 不含密钥值与消息正文 | **C7a** |
| 探测单源退役 | `tests/unit/knowledge/enterprise/test_chatConnector.py` 追加格 | `_historyGapReason` 消费通道层同一读数（AST/调用面反证：适配器内**不得**再出现 `importlib.import_module("WeWorkFinanceSdk")` 那份恒假探测）；三态文案与通道层逐字一致 | **C7a** |
| 通道层读取面 | `tests/unit/channels/test_wecomChatArchiveReader.py` | 假 SDK 夹具（按 `seq` 返回密文行，**从 seq+1 起**）：水位只在拉取成功后推进；未同意成员的会话不出现在行集；`publickey_ver` 未知即跳过并计数；`action=recall/switch` 分别处置；`msgtime` 毫秒→ISO8601 | C7b |
| 解密单源扩展 | `tests/unit/channels/test_wecomCryptoSingleSource.py` | **只有 RSA 半边在本仓**（§5 更正）：RSA PKCS1 解出 `encrypt_key` 后交 SDK `DecryptData`，存档模块内**不得**出现 AES Cipher 构造（AES 在 SDK 内，本仓再写一份即第二套实装）；RSA 失败即显式抛，不静默返回密文 | C7b |
| 投影表只读契约 | `tests/unit/knowledge/enterprise/test_chatArchiveSource.py` | 存档面与捕获面**同一六列行形状**（同体判据，避免两套列名）；`media_ref` 值形态点名是 `sdkfileid`；游标 `since=` 承载 `seq` | C7b |
| 量与幂等 | 同企业源档 | 首轮 `truncated=True` 多轮收敛；重放同一 `seq` 区间 `admitted=0`（咽喉内容键，`tests/unit/knowledge/enterprise/test_enterpriseIngestAdmission.py` 先例）；水位落后超 5 天即 health 点名「那段历史已不可取」 | C7c |
| 正文分档 | 同企业源档 | 文本正文进条目链、**不进** facts object（承 §14-C 裁定）；结构化字段进 facts；同一句话两处不重复（幂等键统一） | C7c |
| 反向守卫 | `tests/unit/test_repair_discipline_guard.py` 同族 | 不新造第二套凭据存储/第二个写口/第二条媒体触发线（凡甲案落点偏离即红） | 各批 |

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
   缓解（必须落进 C7b/C7c）：按 `roomid`/成员白名单在**通道层落库前**过滤
   （不是摄取后再删）；文档与页面文案写明「存档范围由企微后台决定，本系统只读能读到的」。
   ⚠ 初稿把「`archive.backfill` 默认关」列为缓解手段，**C7a 核查后作废**：5 天窗口下
   默认关等于永久丢历史（§8），隐私缓解只能靠落库前过滤，不能靠不拉。
2. **明文消息落盘的驻留**：甲案引入投影表，表里是解密后的聊天正文。
   开工批须裁其保留策略（摄取成功后是否清理正文、清理是否走既有存档/擦除设施）。
   今天的擦除闭集**不含 `source:` 前缀**（[registry.py:238-246](../../neurova/knowledge/enterprise/registry.py)
   `deleteConfig` 注释已点名：删连接器只删配置，不碰已摄取事实）——**级联清除是另一个立项**，
   本方案不冒充它有。
3. **撤回（revoke）不回改**：历史里被撤回的消息已进 facts/条目的部分无法撤回。如实登记缺口。
4. **回退动作两挡且不相冒充**（沿用立项方案 §4-1 的在册口径）：
   `enabled=False` 关闸（零拉取零网络）／通道层不启动存档 worker（投影表不再增长）；
   两者读数不同，页面须分开显示（§6-561 两态纪律）。
5. **与在途改动撞车：已解除**。初稿登记的前置（并发会话正在重写 `channels/wecom.py`，
   协议合规＋token 单源）已合流——该批落在 `612caf931`，台账销号在 `eb97f4db0`（§6-583，
   四项不符合＋缺口全修，channels 769 passed）。C7a 开工时工作树里那两个未跟踪件已不在，
   通道层新模块不再与它同文件双写。

---

## §14 四项裁定（2026-11-08 用户「选择甲案 其余的需要拍板的按推荐走」——**全部已裁**）

| | 选项 | 选了会导致 | 不可逆点 | **裁定** |
|---|---|---|---|---|
| **A 开工时机** | 现在开工 C7a（前置核查＋凭据面，不含拉取）／整批 C7 一起做／只做 HTTP 面可行性核查 | 整批做要先解决 SDK 二进制分发（`.so/.dll` 不是 pip 件），部署面未定即写读取面＝纸上代码 | 无（方案阶段） | ✅ **先 C7a＋HTTP 面核查**，读取面待部署口径定。核查已完成（§16）；投影表归 C7b（初稿 A 选项里把它写进 C7a 属笔误，与 §15 冲突，就此更正） |
| **B 私钥落点** | 私钥文件路径＋权限位／`NEUROVA_KB_SECRET` 密文／env | 后两者把平台凭据搬进知识库密钥面或运维面分裂 | 私钥一旦进过库/日志，泄露面永久存在 | ✅ **文件路径＋权限位**，明文进配置即拒（照抄 SQL 批判据）。Secret 落点另按 §6.1 收口为 env 名指针 |
| **C 聊天正文落点** | 条目链承正文／正文进 facts object／分档并存 | 纯 facts 档：十万级行淹掉本体层资产，术语/谓词退化，**且不可逆（删不净，见风险 2）** | facts 一旦灌入自然语言正文 | ✅ **分档最小版**（§9） |
| **D 附件触发归属** | 独立触发端点／ingest 内联／先只落引用 | 内联让单轮耗时被 OCR 主导、`truncated` 读数失真；独立端点＝新造一条媒体触发线 | 无（引用列已就位） | ✅ **先只落引用**，媒体触发面另批（含存档侧 `GetMediaData` 分片取字节） |

---

## §15 分批与顺序（裁定后执行口径）

- **C7a 前置核查与凭据面（已落格，台账 §6-584）**：
  - 官方文档核查「HTTP 存档拉取是否存在」＋SDK 分发形态与部署口径 → **已完成，结论见 §16**；
  - 新建 `channels/wecom_archive.py`，**本批只落凭据面与就绪读数**（字段名单点、原生库可达性探测、
    私钥版本→路径映射＋权限位、明文进配置即拒、reason 脱敏）；
  - `connectors_chat._historyGapReason` 改接同一单点，退役恒假的 `WeWorkFinanceSdk` 模块探测；
  - health 三态文案定稿。**不含任何拉取逻辑，不建投影表。**
- **C7b 读取面与投影表（已落格，台账 §6-585）**：在同一个 `channels/wecom_archive.py` 里加 ctypes 薄包装
  （`NewSdk`/`Init`/`GetChatData`/`DecryptData`＋资源半边 `FreeChatData`/`DestroySdk`）、按 seq 增量拉、归一；
  `wechat_kf_crypto` 加 RSA 半边（含错钥垃圾挡判据）；建 `channel_archive_messages` 投影表＋`channel_archive_state`
  水印表（迁移域 `channel_archive` v1）；`connectors_chat` 来源参数化（`chatSource` 两态）、游标换 seq；
  判据 §11 C7b 三行 28 格全绿（本批改动：白名单落库前过滤移 C7c，与 §14-C 的裁定归属一致）。
- **C7c 消费面与量控（两块已落格，台账 §6-586/§6-587：白名单落库前过滤＋常驻 worker env 门控默认关＋水位落后读数＋backfill 默认开＝水位 0 起；正文分档最小版＝编译期拒 text 进 facts object＋writeArchiveEntries 条目链；页面读数缓办——i18n 与并发会话撞车，解除后小批补）**：首次装配即从 `seq=0` 拉（§8 更正后的 backfill 语义）、
  roomid/成员白名单落库前过滤、常驻增量 worker（与 C2 轮询同节拍，周期远小于 5 天）、
  水位落后超窗即 health 点名、正文分档落点（承 §14-C）、页面读数（连接器列表的
  「数据量」列与存档范围对齐，见 `NeurUI/src/pages/EnterpriseSourcesPage.vue:201/609` 的 chat 向导段）。
- **依赖关系**：C7b/C7c 依赖 §16 的核查结论（已就位）；§14-C 的裁定决定 C7c 的映射判据形状。
  三批各自可独立验证，任一批出问题按 §13-4 两挡回退。

---

## §16 C7a 核查结论（官方文档实证，2026-11-08）

取证方式：官方文档站是 JS 渲染，`WebFetch` 只拿到 CSS；改用浏览器渲染后取 `document.body.innerText`
拿到全文。以下每条都点名文档路径与更新时间，**不凭记忆补全**。

### §16-1 经典「会话内容存档」（文档路径 91774，更新 2026/01/19）

- **分发形态：只有 C 动态库**。linux x86 v2.0（2024-6-6）/v3.0（2025-2-13，依赖 openssl 3.0）、
  linux arm v3.0、windows v2.0/v3.0。**没有官方 Python 包**——故仓内 `WeWorkFinanceSdk`
  这个模块探测名不对应任何可安装件（§7 退役项）。
- **接口面**：`NewSdk()` → `Init(sdk, corpid, secret)`（secret＝**聊天内容存档专用 Secret**，
  管理端→管理工具→聊天内容存档，不是应用 Secret）→
  `GetChatData(sdk, seq, limit, proxy, passwd, timeout, chatDatas)` → `DecryptData(encrypt_key, encrypt_msg, msg)`；
  媒体另有 `GetMediaData`（`sdkfileid` ＋ `index_buf` 分片续传）。
- **`GetChatData` 语义**：**从 `seq+1` 开始返回**，首轮 `seq=0`，任意 seq 可重入；`limit ≤ 1000`；
  **≤4000 次/分钟**。
- **硬窗口（推翻初稿前提）**：官方原文「获取会话记录内容不能超过 5 天，如果企业需要全量数据，
  则企业需要定期拉取聊天消息」。⇒ **「历史」＝≤5 天＋本地累积**，不存在深度回溯（§0-3/§8 已更正）。
- **返回行**：`chatdata[]`＝`seq / msgid / publickey_ver / encrypt_random_key / encrypt_chat_msg`；
  `msgid` 带 `_external` / `_updown_stream` 后缀。
- **解密**：`encrypt_random_key` base64 解码 → **RSA PKCS1，2048 位模数**，按 `publickey_ver` 选私钥
  → 结果连同 `encrypt_chat_msg` 交 `DecryptData` → 明文 JSON。**AES 半边在 SDK 内**（§5 已更正）。
- **明文形状**：`{"msgid","action":"send|recall|switch","from","tolist":[],"roomid",
  "msgtime":<UTC 毫秒>,"msgtype":"text","text":{"content"}}`；`from`＝userid 或 external_userid
  （机器人 `wb` 开头、外部联系人 `wo`/`wm` 开头）；`roomid` 空＝私聊；
  引用/回复消息正文前官方加前缀「这是一条引用/回复消息：」（英文 "This is a quote/reply:"）。

### §16-2 数据与智能专区 `sync_msg`（文档路径 99968，更新 2026/09/10，自建应用）

- **请求方法官方写明「通过 SDK 调用」**，不是裸 HTTP。入参 `{cursor, token, limit, mode}`（＋`begin_time`）；
  cursor 缺省＝**5 天内最早**；`token` 来自回调事件（10 分钟有效，否则受严格频控）；
  `limit` 默认 200、上限 1000；`mode` 0/1/2（默认/预分页/自适应）。
- 返回 `has_more` / `next_cursor` / `msg_list[]`（`msgid`、`sender{type:1员工/2外部联系人/3机器人, id}`、
  `receiver_list`、`chatid`、`send_time`（**unix 秒**）、**数字 `msgtype` 0–28**、
  `service_encrypt_info{encrypted_secret_key, public_key_ver}`、`extra_info.call_duration`）＋`page_id_list`。
- **不返回消息正文**：那把 `encrypted_secret_key` 是给专区内其它接口（模型分析等）用的，
  数据留在专区里。⇒ 它能回答「谁在哪个群何时说了哪种类型」，不能回答「说了什么」（§2 已更正）。
- 前置：数据与智能专区权限＋后台设公钥；`get_msg_list_by_page_id` 需 SDK ≥ c++1.3.0/java1.3.0/python1.2.2，
  每企业并发上限 10。

### §16-3 ISV HTTP 面（文档路径 97240 / 99670）

- `POST https://qyapi.weixin.qq.com/cgi-bin/chatdata/sync_msg?access_token=...`，体 `{cursor, token, limit}`
  （cursor 缺省＝3 天内最早）；需会话存档接口权限＋企业版/服务版。
- **自建应用、代开发、第三方三种类型一律标注「暂不支持」**。本仓企微通道是自建应用
  （corpid/agentid，见 `wecom.py:545 create_wecom_adapter`）⇒ **这条路今天走不通**（§2 已更正）。

### §16-4 定期授权（文档路径 101545）

- **2026-06-15 起**，数据与智能专区数据改用定期授权，**90 天**有效，过期 → errcode **48002**。
  本方案走经典存档面，此项只在客户改用专区时相关，但前置表（§3）照登，免得日后混面。

### §16-5 核查对方案的净影响（三条前提被推翻，均已就地更正）

| 初稿前提 | 核查结论 | 更正落点 |
|---|---|---|
| 「HTTP 面若成立则少一个第三方二进制」 | HTTP 面对自建应用不可用；专区面不带正文 | §2、§16-2/§16-3 |
| 「存档开通日起可回溯」 | **只给 ≤5 天**，全量靠定期拉＋本地累积 | §0-3、§1 表、§3、§8、§13-1 |
| 「AES-CBC 半边扩展 `wechat_kf_crypto`」 | AES 在官方 `DecryptData` 内，本仓只做 RSA | §1 表、§5、§7、§11 |
| 「探测名 `WeWorkFinanceSdk` 是可用槽」 | 官方无 Python 包，该探测恒 ImportError＝假判据 | §0-2、§7、§11、§15 |
