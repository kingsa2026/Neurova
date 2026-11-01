# dsh-superagent 原型与 Neurova 的「注意力预算 / 授权门 / 工单模型」代码级对比（2026-10-31）

> **性质声明**：本文属 `docs/INDEX.md` §2.4「竞品/外部对标」——**研究参考，仅作背景，不可作为本仓设计的事实源或对齐依据**（`AGENTS.md` 协作红线 §2：外部项目只作功能依赖或背景登记，严禁在代码、注释、文档中引用/模仿/对齐第三方实现，不搬运其命名、结构与措辞）。文中候选若要落地，一律按本仓修复教义独立立项（先红后绿 + live-verify），本文不构成对齐承诺，**也不授权搬运其代码、提示词或词汇**。每条候选的立项理由均写成本仓自身可核实的断点；「对方有 X」只出现在提问语境，不出现在理由列。
>
> **对比对象**：`github.com/deepseek-ai/dsh-superagent-prototype`（浅克隆 @ commit `6337fc823ce20251c8de8085948165c81aaa701e`；抓取日 2026-10-31；仓内随附 `LICENSE` 文件，本未逐字核）。README 自述：**研究原型、非官方产品、非生产级**，且"与设计文章描述的若干方向不一致，部分未实现"——本条按硬约束使用：**它写了但代码里没有的东西，不进候选**。规模：216 个跟踪文件，`src/` 15,587 行 TypeScript/TSX（147 `.ts` + 30 `.tsx`），另有 `docs/000–008` 九篇编号文档、`prompts/` 16 份提示文、`skills/` 两份 SKILL.md、`locale/` 中英两份。定位：面向**单个 GitHub 仓库**的主动式编码代理，监听 GitHub（可选飞书），按"工单"开活、在自己的会话与目录里干活、回到原对话答复，另有一个"需要人"的网页面板。
>
> **方法**：外部侧为**纯代码读，未实跑**——其依赖是整套私有 `@deepseek-ai/*` 包（`package.json:62-100`），浅克隆无 `node_modules`，`pnpm check` 无法复现，因此它 59 个 spec 的实际绿灯**未经验证**。三路并行精读（内核与授权执行 / 提示与技能装配 / 面板评测与质量门）后，本文作者另对其 6 条关键断言**亲自抽验原文**并确认属实：fail-open 默认监听（`sources/registry.ts:128`）、工单目录不清理（全仓 `rmdir` 仅 `executor/dsh.ts:257` 一处且只删空目录）、托管会话 `danger-full-access`（`app/sessions.ts:152`）、`attention` 为单值非数组（`core/model.ts:286`）、投递逐字比对（`core/replies.ts:77`）、提示面 BANNED/LEGACY 禁用词表（`tests/model-surface.spec.ts:52-57`）。其余未抽验处在本文明确标注。Neurova 侧行号绑定 2026-10-31 工作树，后续会漂。
>
> **前作指针**：本域前作八篇（`zcode`／`rsiagent`／`skillglow`／`dramaclaw`／`semantica`／`modularrsi`／`harness2`／`tmem`）**均未覆盖**「对人开口的注意力预算」「授权门同源性与 fail-closed」「工单阶段是否可计算」这三题；`harness2` 谈 harness 递归优化、`zcode` 谈工具循环，不重复。候选编号另起 `D-1..D-6`，不占前作号位。本篇不做十维加权评分（前作有，但此处领域不同，给分易被读成事实）。

---

## 0. 结论摘要

**一句话画像**：它是一套**以"人的注意力"为稀缺资源来设计的单仓常驻代理**——收单有三事实判据、干活有独立会话与工作树、说话有硬预算（合并、排队、一次只容一个问题、人在等就 hold），代价是治理面很薄（无批准/驳回/接管动作、面板即权限、OS 边界自认不存在、CI 缺失、依赖私有包）。Neurova 是**治理面厚、出口预算薄**的反形：我们有身份单通道、权限门、脱敏单源、审计与静态门禁、CI 多腿，但"什么时候对人开口"这件事**在代码里几乎不存在**——全仓节流词汇都指向上游限流，不指向出口。

最重要的四个判断：

1. **它最有价值的不是架构而是"注意力预算被写成了代码"**。可核的机制有四条：notice 以 `name` 为 coalesce 键、未发出的同名被新值覆盖（`core/notices.ts:11-14`）；同单同会话严格排队、前一条连败三次才放行（`app/store.ts:259-261`、`app/outbox.ts:45`）；`attention` 在数据结构上**只能有一个未决问题**（`core/model.ts:286`，单值非数组）；人在等的时候自动产生的 Input 被 hold（`core/tickets.ts:238`、`model.ts:349-353`）。这四条各自都能被一句断言钉住，而我们同位置目前是"发出去就完了"。
2. **它的"阶段"不是状态字段，而是从最新事实反推的四条布尔**（`core/stage.ts:9-21` 判 `person`：投递失败／有未决提问／report=ready 待评审／blocked|failed 且无人追问）。这正对本仓一条老病：运行台账的 `status` 是被写出来的字段，会与真相漂移——本仓 §6-421 活体抓到过"任务 164s 仍在跑而 run 被扫成 `failed/process_died`"的同形故障。**可计算阶段**这条思路的借鉴价值高于它的实现细节。
3. **它的 fail-closed 不彻底，且失败方向与文档相反**：allowlist 默认空、未列出即 ignore（`src/policy.ts:77,84`）确实 fail-closed，但 Source 无 stored 实例时 `scope()` 返回 `listened:true`（`registry.ts:128`）是**默认放行**；`WORK_TOOLS` 用取交集实现（`app/sessions.ts:61/288`），profile 多装插件就给 worker 放行 `send_message`/`interrupt_agent`，与 `docs/007:532` 相反。⇒ **反面教材，不是候选**：与本仓批 P-4（权限门在场、门后 `if self._event_bus:` 恒空）是同一条"门与真相相反"的根。
4. **它的收单判据把"不接单也不回话"写成了规定**（`prompts/admission.md:23/52/65` 的 no-ACK；只有 accept 必填一句 acknowledgement，`app/tools/main.ts:53`）。这一条与直觉相反，但对"少占人注意力"是关键取舍；本仓若立项必须先裁"静默拒单会不会让提需求的人以为没人接"——这是产品语义题，不是工程题。

## 1. 它的实状（三块，均按代码读）

**领域与授权**：工单聚合无状态字段（`model.ts:277-308` 有 `ended?/attention?/mandate/assignments[]/inputs[]/undelivered[]`，阶段全靠 `stage.ts` 反推）；写者唯一（`core/engine.ts:24-58`，一命令一事务）；幂等键四处（triggerId 内容哈希 `intake.ts:23`、`ticket=key('ticket',evalId)`、`input=key(...)`、effect 主键 `(kind,key)`、outbox `INSERT OR IGNORE`）；持久化是**单个 SQLite 里把整个聚合塞进一个 JSON 列**＋generated 列与部分索引扫活跃行（`app/store.ts:30-44,71-82`）。授权唯一落点 `settingsPolicy().gate()`（`policy.ts:191-211`），allowlist 按 Source 分片、不跨源映射身份（`:119-121`）。范围收窄只做一半：Mandate 不可变、inferred 单硬加"仅限单模块内小改"（`executor/dsh.ts:91-95`），但**没有每单工具/预算级收窄**，`blockedCommands` 默认空（`policy.ts:96`）。

**执行隔离**：每单一个 `worker-<ticketId>` 会话＋`<root>/<worktreeName>-<ticketId前12位>` 目录（`dsh.ts:24,57,110`）；并发 `maxWorkers` 默认 3、人的消息多用一槽且 wake 优先于新 launch（`dsh.ts:182-196,305-310`）；投递前后重读并校验 `latestAssignment().id===assignmentId`（`dsh.ts:272-274,331-336`）——并发正确性靠"每处 await 后重读再校验"的约定，**不是不变量**。失败后 Session 与目录保留供人接管（`app/sessions.ts:289-297`），但**清理时机全仓不存在**；`inputs[]` 只 push 无裁剪（`tickets.ts:236`）⇒ 两处无界增长。

**提示与技能**：注入顺序在 `app/prompts.ts:102-118` 一处定死（shared→角色稿→团队三段→subscriptions/replies→dispatch|work→admission→handoff→environment→policy，policy 置末使改动不动前文）；角色可见性由 `roles: MAIN/WORKER/BOTH` 声明（`:49-69`）。**没有 include 机制**：复用靠 15 个 part key 表＋字符串相加，团队三段被内置稿**按标题字符串引用**（`:17`）⇒ 团队清空一段即整段消失、引用变悬空，且无校验（`:105-115`，`tests/prompts.spec.ts:36` 反把它当期望）。交接不只有提示：回传字段有工具 schema 硬清单（`orchestrator_report{state,summary,human_action?,question_for_trigger_id?,pr_number?,reply_to_trigger_id?}`，`executor.ts:80-88`），投递侧 `attention.question !== request.question` 即抛 `notAttention`（`replies.ts:75-77`），result 只放行 ready/completed/merged/dropped（`:69-73`）。措辞硬顶：100 词、中文按 `Intl.Segmenter('zh')` 分词计数、禁拆多条（`prompts/replies.md:27-30`、`src/infra/text.ts:3-15`）。技能＝**frontmatter 只有 `name`+`description` 的可命名提示插槽，正文纯散文、无可执行脚本**（`skill-files.ts:19-23`），不扫盘、按 prompt 版本注册进会话作用域（`sessions.ts:319-325`）。

**面板、评测与质量门**：待办源＝`ticketStage().stage==='person'`（`app/views/overview.ts:73`）；动作只有外链去源站回答／retry／stop／跳会话（`client/rows.tsx:31-41`），**无批准、无驳回、无接管**（全仓无此代码）；无人等待计时只有小时粒度相对时间（`client/text.ts:51-54`）。评测**不打分**（全仓无 `score`/`confidence`），阈值是布尔门＋模式：三项事实不合即降 ignore、无 enabled 命中→`noRuleMatched`、缺 `intent_evidence` 抛错、超时重排两次转 `unavailable` 并点亮 `evals` 健康 error（`policy.ts:26-29,51-58`、`evals.ts:19,60-69`）；判定结果**有读者**（面板 rules/direction/wouldAccept、主会话回读 `decisionDetails`、命中规则进 worker assignment 文本、dismissed 过滤 Overview，`records.ts:185-208`、`cards.ts:85-87`、`dsh.ts:102-108`）。测试以装配为主（`runtime.spec.ts` 91 例；9 个 `panel-*.spec.tsx` 挂真实 App＋类型化假 API），并有四道"判据自证"类守卫：未声明的 query/body 记进 misuse、每例后断言清空（`fixtures/panel-server.ts:416,450`）；src 文件与测试文件**双向钉进 007 文档表**（`tests/docs.spec.ts:58,63`）；每个 class 须带 JSDoc（`class-docs.spec.ts:9`）；反查死 CSS 类（`styles.spec.ts:9`）；prompt＋工具字符预算棘轮 59000/40500（`model-surface.spec.ts:40,396`）。质量门 `pnpm check` = typecheck && vitest && tsdown（`package.json:51`）——**没有跑不起来的空门**（它既无 lint 脚本也无 lint 配置，与我们 §4 里那道"挂着但跑不起来"的 lint 门形成对照）；但**仓内无 CI**，全靠人手跑。HTTP 面无 token，只有 loopback 硬门＋Host/Origin 校验且允许 Origin 缺失（`app/http.ts:231,75-79`），API 保存即面板权限（`:195,201`）。仅 POSIX（tmux＋fcntl＋`#!/bin/sh` shim，`scripts/dsh-superagent:166-181`、`infra/environment.ts:89`、`deployment.ts:13`）。

## 2. 本仓自有断点（候选的立项理由都在这里，与它无关）

| 编号 | 断点（本仓可核实） | 现状证据 |
|---|---|---|
| N-1 | **"对人开口"没有出口预算**：全仓 `throttle/cooldown/rate_limit` 命中都指向上游限流与模型退避，没有任何一处是"同一件事不重复说／多条合并／静默期／人在等就压住自动输入" | `neurova/agent/swarm.py:299-304`（429 退避）、`neurova/channels/models.py:181`（`rate_limit: 60` 是渠道侧入站口径）；出口侧无同族落点 |
| N-2 | **运行台账 `status` 是被写出来的字段**，与"任务是否还在跑"可以不一致（本仓 §6-421 活体实测：任务 `chat@164s` 仍跑而 run 被扫成 `failed/process_died`；断连后时间线停在断连那一秒、`buf["done"]` 永不置位） | `neurova/core/agent_run_ledger`＋`neurova/api/endpoints/console.py`；台账格与写点见 §6-421／§6-423 正文 |
| N-3 | **"需要人"只有逐次工具运行的台账筛选，不是待处理队列**：`needs_human` 由 refusal/effect 算出、可按 `只看需人工行` 过滤，但没有"当前有几个问题等人、各自等了多久"的面 | `neurova/security/desktop_audit.py:45/66/108`、`neurova/api/endpoints/governance.py:865/876` |
| N-4 | **审批可堆叠、等待预算写死在数据里、且没有"同时只容一个未决问题"的约束**（本仓 §6-408 其二的实测：`exec_approval` 会等满 `config["timeout"]`，处理器在它返回之后才被调 ⇒ 60 就是 60 秒空等；同根第三条链在批 O-2c 收口） | `neurova/collaboration/neurflow/builtin.py:2099 exec_approval`、`tests/unit/neurflow/test_approval_reply_mechanism.py` |
| N-5 | **授权面分两处、口径不同源**：渠道级 `open/closed/whitelist` 与治理级工具白名单＋管理员 CRUD 是两道独立门，"这一轮谁能指挥 agent"没有一处统一判据 | `neurova/channels/discord.py:62-63`、`neurova/security/governance.py:60/79`、`neurova/api/endpoints/governance.py:119-146` |

## 3. 候选清单（D-1..D-6；每条只写"本仓要解决什么"，不写"照它做"）

- **D-1 出口注意力预算（挂 N-1）**：在同一条"要对人说话"的出口上立一处单源，实现①同键覆盖（后一条未发出即被新值取代）②同会话同工作项严格排队③人未答复时压住自动产生的后续输入。判据打在**发出去几条**而非"有没有发"。代价：需要新增"消息可合并性"的键口径，与 `channels/` 各条渠道的长度限制交叉（本仓需现查各渠道上限，不能像它那样只对一条渠道校验）。建议按本仓节奏拆两格先做①②。
- **D-2 阶段可计算化（挂 N-2）**：把"是否需要人／是否还在跑"从**存储字段**改成**由最新事实反推的纯函数**，字段只留人写入的意图。判据＝同一时刻两个读面（台账行与阶段函数）必须同读同写；反向钉一格"写出来的 status 与事实相反时，读面取哪个"。这一格能顺带收掉 §6-421 留在"仍开"里的"状态位不轮询"。
- **D-3 待人队列与一次一问（挂 N-3＋N-4）**：给"等人"一个可枚举的队列面（当前有几个未决问题、各自等了多久），并在数据结构上限制同一工作项同时只容一个未决问题。与 N-4 的等待预算口径同批做（已有先例：预算收成具名常量、父墙由它导出）。
- **D-4 出口措辞的硬预算（挂 N-1）**：答复长度上限与"不拆多条"从提示措辞升级为**代码侧可断言的约束**；中文按词计数的口径若采用必须一处具名（本仓已有 11 语言文案纪律，落点需先现查 `src/i18n/` 与渠道出口，避免造第二份尺度）。
- **D-5 加一条渠道的最小契约（挂 N-5）**：以**清单**形式规定新增事件源/渠道必须实现哪些面、缺省时走哪个方向（本仓原则：缺省必须 fail-closed）。注意它的实现本身没做到（通用层仍硬编码两源，见 §4），所以只借"契约清单＋默认拒绝方向"，不借其抽象。
- **D-6 提示/技能文本的防漂移守卫**：本仓提示面是否存在"同一契约多处重写"目前**未核**（属立项前置调查）。若存在，可考虑用"禁用旧词汇表＋字符预算棘轮"兜住——它与本仓已有的静态门禁、台账守卫、在册子集棘轮是同族工具，不新增体系。

## 4. 不照搬清单（每条写"照了会退步在哪"）

- **整个聚合塞一个 JSON 列＋generated 列扫活跃行**：本仓 SQLite 纪律是连接池＋WAL＋`db_migration` 注册表（`AGENTS.md` §3），双份可读面（JSON 内容与列）正是 §6-411/§6-416 反复收口的"多表漂移"形态，照了等于新增第二处事实源。
- **YAML 配置里执行 JS（`!!js` 标签）**：`cordis.patch.yml` 的补丁机制依赖它；本仓配置系统（ConfigManager＋环境变量）不允许配置面携带可执行代码，这是安全底线的退步。
- **托管会话一律 `danger-full-access`、面板保存即权限、无 token、Origin 缺失放行**：四条都是把"权限"与"能力"合一的实现，本仓身份与权限是分层的（§3 身份单通道＋治理门），照了等于拆掉自己的门。
- **工单目录与 `inputs[]` 无界增长、无清理时机**：这是 §2 断点纪律要修的形状，不是设计。
- **并发正确性靠"每处 await 后重读再校验"的约定**：无不变量、无判据，本仓同一问题走 DCL＋RLock 与状态机（§3 单例规约），改成约定即放弃可验证性。
- **`WORK_TOOLS` 取交集导致扩权、Source 缺 stored 实例时默认监听**：两处失败方向都朝"放行"，与本仓 fail-closed 口径相反（同族教训见批 P-4：门在场而门后恒空）。
- **提示无 include 机制、按标题字符串跨文引用**：一段清空即悬空且无校验，还把这种悬空写进测试当期望；本仓若做提示分层必须显式装配点＋存在性检查。
- **迁移里用正则改写历史 prompt 文本**（`app/migration.ts:271-281`）：与"已入库正文不可改写"同值，属数据史实破坏。
- **只有中英双语、`locale/*.json` 无键对齐守卫、缺键静默回落原码**：本仓 11 语言严格对齐已有守卫（`src/i18n/__tests__/locale-consistency.test.ts`），它的口径比我们的弱，只"占位符集合相等"这一维是否已被我方覆盖属未验证（见 §5）。
- **无 CI、依赖整套私有包、绿灯不可复现**：不可复现的质量门等于没有门；本仓 §4"规则以实际存在的命令为准"正是这条的反面。

## 5. 未验证项（不冒充已核）

1. **外部仓未实跑**：私有 `@deepseek-ai/*` 依赖与缺失的 `node_modules` 使 `pnpm check` 无法复现；本文外部结论全部为代码读。它"59 个 spec／809 个 `it`／3091 个 `expect`"是子代理现场计数，我**只抽验了 §前言列出的 6 条断言**，计数本身未复算。
2. **许可与出处口径**：仓内有 `LICENSE` 文件但本文未逐字读其条款；README 自称非官方产品，其与公开文章的一致性未核对（文章本身未获取）。
3. **D-6 的本仓前置未做**：本仓提示/技能文本是否存在同一契约多处重写、`locale-consistency.test.ts` 是否已覆盖占位符集合维度——两项都要现查才能立项。
4. **N-2/N-3 的行号会漂**：`agent_run_ledger`、`console.py`、`desktop_audit.py` 均在他会话在途改动面上（本批工作树另有并发在途件），引用前需复算。
5. **未做量化对比**：不给出"谁的架构更好"的分数；本文只给可核事实与本仓断点。
