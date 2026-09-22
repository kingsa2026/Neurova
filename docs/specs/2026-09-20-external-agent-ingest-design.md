# 外部 Agent 记忆与会话导入（Ingest Bundle）设计

日期：2026-09-20　状态：已落地（2026-09-21 兼容性修复批次已并入，见 §6 硬规则与 §9）
范围：把一次性本地脚本 `scripts/import_kai_to_neurova.py`（被 .gitignore 排除）的导入逻辑并入受控模块，
并升级为"识别来源 → 路由转换器 → 显式确认写库"的通用外部 agent 数据导入能力。

## 1. 目标与非目标

目标
- 一个中立交换格式（Ingest Bundle）作为唯一契约：Neurova 只认它，写库只有一处。
- 来源自动识别（结构指纹）与逐 store 路由；识别不了就明确报未识别，不猜。
- 导入过程无损优先：凡是降级的字段必须在包与报告里显式申报。
- 可撤销：按导入批次精确回滚。

非目标（本设计明确不做）
- 不做 HTTP 端点与前端页面（先只包内模块 + CLI；有第二类使用者再提接口）。
- 不导入人格/身份文件（SOUL.md/PROFILE.md 等），那属于人格装配面，另单。
- 不支持私有方言：`qwenpaw_memory*`、`humanthinking_insights/dream_logs`、`memory_working_cache`、
  `session_relationships/emotional_continuity` 在公开 QwenPaw 全仓与 qwenpaw/copaw/reme 各 wheel 中零命中，
  属本机私有工程产物，不进指纹表、不进支持清单；碰到即"未识别 + 结构摘要"。
- v1 不消费记忆图边（`relations.jsonl` 允许存在、只登记不导入）。

## 2. 取证：各家实际怎么落盘（结论的根据）

| 维度 | QwenPaw(原 copaw) | OpenClaw | Hermes | DeepSeek harness(dsh) | Claude Code | Codex CLI |
|---|---|---|---|---|---|---|
| 载体 | `history.db` 表 `conversation_history`（含 `seq`/`dedup_key`/`headline`/`tool_state`/`metadata`） | per-agent SQLite `transcript_events(session_id,seq,event_json,created_at)` + `session_windows`，遗留 JSONL | 单库 `state.db`：`sessions`/`messages`(25 列) | per-session JSONL，首行 header 带 `version`，SQLite 仅可丢弃派生索引 | per-session JSONL，按项目目录分片 | `sessions/YYYY/MM/DD/rollout-<ts>-<id>.jsonl` |
| 排序 | `seq` | `(session_id,seq)` + id/parentId 树 | 插入 id（文档写明时钟会倒退，不按 timestamp） | `seq` | 行序 + uuid/parentUuid | 行序 + 可选 `ordinal` |
| 工具结果 | 独立行 + `tool_call_id` | 独立行 `role:"toolResult"` + `toolCallId` | 独立 `role='tool'` 行 | 独立 `tool/result` 事件 | 下一个 user 行的 `tool_result` 块 | 独立 `function_call_output` 行 |
| 推理 | `blocks` 内 thinking | content block `thinking` | 独立列 `reasoning`/`reasoning_content`/`reasoning_details` | `reasoning-chunks`（逐 delta，无损） | content block | 独立 `reasoning` 行，正文常为密文 |
| schema 版本 | 无 | 无 | 有（`schema_version` 表=23） | 有（header `version=3` + v0→v3 迁移链） | **无**，官方称内部格式跨版本会变 | **无** |
| 时间戳 | TEXT | 信封 ISO + 体内 epoch ms | REAL epoch | epoch ms | 行级 ISO | 行级 ISO，事件体内混用 ms |

三条决定设计的取证事实：
1. **工具调用与结果在所有族里都是跨行关联**，没有一家把结果内嵌进调用行 → 传输层必须保持扁平事件行。
2. **市面上的"互相导入"等于静默丢数据**：Hermes 从 claude/codex 导入把工具调用压成 `[ran tool: name]`、
   丢弃 tool 结果与 reasoning、强制合并相邻同角色；Codex 导 Claude 同样降级为文本注释。降级必须显式申报。
3. **OpenClaw 的信任级 `origin_class(owner|agent|untrusted|system)` 与 Neurova 的 `MemoryOrigin` 闭集同词**，
   因此不扩枚举；信任级逐条由转换器声明。

## 3. 契约：Ingest Bundle v1

`schema_version = 1`。包 = 一个目录（或 zip）：`manifest.json` + `transcripts.jsonl` + `memories.jsonl`
（+ 可选 `relations.jsonl`，v1 只登记）。

`manifest.json`
- `schema_version`：整数，不等于 1 直接拒绝。
- `generated_at`、`agent_name`、`source`：`{converter, converter_version}`。
- `counts`：每类记录条数（校验器据此核对实际行数，缺一即拒）。
- `dropped[]`：`{store, field|block, reason, count}` —— 转换器必须申报丢了什么；空数组表示自认无损。
- `stores[]`：每个来源 store 的识别结论（指纹名、版本判定、置信、条目数）。

`transcripts.jsonl`（一行一个事件，扁平，不按轮分组）
- 必填：`session_id`、`seq`（int，会话内单调）、`kind`（`user_message|assistant_message|tool_call|tool_result|system|compact_summary`）、`ts`（ISO-8601 带时区，转换器负责从 epoch/REAL 换算）、`identity_key`。
- `content_blocks[]`：`{type: text|image|file, ...}`，图片/文件走 `media/<digest>.<ext>` 内容寻址引用。
- `tool_call_id` / `tool_name`：跨行关联用；`tool_result` 必须能回指 `tool_call`。
- `reasoning`：`{state: text|opaque|absent, text?}` —— 密文或不可得时是 `opaque`，**不许悄悄变成空**。
- `parent_seq`：分叉/回溯时的树边（Claude/Pi/OpenClaw 都有 parent 概念）。
- 角色为 `user` 的记录 `origin` 隐含 OWNER；`assistant/tool` 侧为 AGENT；由校验器复核而非信任声明。

`memories.jsonl`
- 必填：`identity_key`、`content`、`memory_type`、`category`、`origin`（闭集四值，越界即拒）、`importance`、`ts`。
- 可选：`tags[]`、`source_ref`（来源文件/表/行，供追溯）、`supersedes`（为既有裁决链留位）。

`identity_key` 由各源不变量派生（源行主键或 hash(内容+时间+作用域)），是幂等与撤销的唯一依据。
Neurova 自身的库不在识别范围内：本机 `data/*.db` 无 `conversation_history`/`messages`/`sessions` 表，
与上述指纹不冲突（已核）。

## 4. 组件

```
neurova/memory_ingest/
  bundle/    manifest.py（版本与计数核对）· records.py（记录类型）· validate.py（负例即拒）
  probe.py   结构断言 DSL：列集合断言 / JSONL 首行与前 N 行断言 / 目录形态断言
  converters/  每家一个模块，各自 handprint() + convert()，只产 bundle、不写库
  intake.py  唯一写入口：bundle → MemoryManager.import_memories / SessionManager.import_messages
  report.py  IngestPlan（识别报告）与 IngestReport（写入结果）
scripts/ingest_memory.py   薄 CLI：detect / convert / apply / undo
```

写入侧新增两个入口（不改运行期写入口语义）
- `MemoryManager.import_memories(rows, *, ingest_run_id)`：单事务、复用同一连接与同一份 schema
  （DDL 不再由转换器抄写）、原样保留历史时间戳/温度/来源；**不触发**内容门、关键词倒排、
  MoE 向量同步等运行期副作用（由启动扫描与后续召回自然覆盖）。
- `SessionManager.import_messages(turns, *, ingest_run_id)`：能表达"一条 assistant 轮含多个工具调用与
  多个结果"的原始序列，不复用 `add_message` 的 user+assistant 成对语义。

## 5. 识别与路由

- 单位是 **store 不是目录**：一个源目录可同时含多族多个 store，`detect` 输出逐 store 清单。
- 三态：唯一高置信 / 多命中冲突 / 零命中。后两态一律不写库；零命中打印结构摘要
  （表名与列集、JSONL 首行键集）供新增转换器。
- 漂移守卫：必需列缺失即整 store 拒绝，绝不半导。只有带版本号的族额外申报"版本比已知的新"，
  无版本号的族（Claude/Codex/OpenClaw）只能靠列面与指纹兜底。
- 允许 `--source <converter>` 人工指定，跳过猜测（仍走同一校验器）。

### 5.1 平台落地名册（每加一家就更新这里，交叉误认由 `test_every_family_matches_only_its_own_store` 钉住）

| 指纹名 | 源形态 | 状态 | 证据来源 |
|--------|--------|------|----------|
| `qwenpaw_history` | SQLite `conversation_history` | 已实现 + 真库往返 | 本机源库 242 行实测；公开源码建表列集逐列相符 |
| `dialog_daily` | 每日一个 JSONL（一文件一场会话） | 已实现 + 真库往返 | 本机 40 个文件实测 |
| `legacy_session` | 1.x 工作区 JSONL（带表头记录） | 已实现 + 真库往返 | 本机 31 个文件实测 |
| `opencode_session` | SQLite `message` + `part`（JSON data 列） | 已实现 + 真库往返 | 本机 4 会话 / 845 消息 / 4423 块实测 |
| `codex_rollout` | `rollout-<ts>-<id>.jsonl`，线形 `{type, payload}` | 已实现（合成夹具）；**无本机真库可跑** | 该平台上游写入侧源码 |
| `openclaw_transcript` | per-agent SQLite `transcript_events` + `session_windows` | 已实现 + 上游整份 schema 建库往返 | 在盘上游源码：建表 SQL + 事件信封读取侧 |
| `hermes_state` | 单库 `messages`(26 列) + `sessions` + `schema_version` | 已实现 + 上游 SCHEMA_SQL 原文建库往返 | 该平台上游建表语句与写入侧行构造（其版本 30） |
| `dsh_session` | per-session JSONL，首行带 `version` | **只有指纹、暂无转换器**：detect 会认出并明确报"有指纹无转换器"，不写一个字节 | 本机无会话数据可取证字段 |
| （未命名） | 按项目目录分片的 JSONL（无版本字段） | 不做：既无本机样本也无在盘源码，凭记忆写字段就是猜 | — |

真库缺位的两家（`codex_rollout`/`hermes_state`）只算"可转换"，不算"经真库验证"；两者都按上游
建表语句原文建库跑过一遍往返（列面不是手抄的），落笔处逐列标了落点，未知列按条数申报。
`hermes_state` 还额外读它的 `schema_version`：版本比已知上限新时照常转，但报告里必须看得见。
产出记忆面的目前只有 `openclaw_transcript`（映射规则与理由见 §9 第一条），其余族只导会话。

## 6. 失败与撤销

三条硬规则（2026-09-21 兼容性修复批次确立，各由用例钉住）：

1. **取值域归校验层**：`kind` / `reasoning_state` / `importance` / `temperature` 的合法域只在
   `bundle/validate.py` 判一次，越界即整包拒绝。咽喉侧不做二次校验——到那里才炸就已经写了一半；
   `import_memories` 的 `origin` fail-safe 降档保留，但权威判据是校验器（守卫：`test_bundle_validate.py`
   的 `test_unknown_kind_rejected_by_validator` 等 4 条 + `test_intake.py` 的"零写入"一条）。
2. **时间戳定不出就申报，不造时刻**：`ensure_offset` 定不出来返回空串，五族在入口申报 `timestamp`
   并跳过该行/该块（openclaw 记忆条记 `memory:无时间`）。造一个 `now()` 会把半年回填的历史按今天
   分桶写进会话文件，且包内看不出区别（守卫：`test_bundle_writer.py::test_ensure_offset_never_invents_now`
   与五族的 `*_without_readable_time_*` 用例；`grep "datetime.now(" neurova/memory_ingest/` 只允许
   `writer.generated_at` 一处）。
3. **包内媒体引用强制 `media/<digest>.<ext>`**：子目录会被落盘拍平（同名不同目录只落一份、第二条引用
   指向错字节），摘要必须声明（否则引用与字节的对应无从证明）。撤销的"是否仍被引用"只看
   `metadata.artifacts` 的结构化登记，不靠拼接全文取子串（守卫：`test_bundle_media.py` 三条命名闸 +
   `test_intake.py::test_undo_prunes_even_when_name_appears_in_body`）。

- 默认 `detect` 只出报告；写库必须显式 `--apply`（与既有 backup/restore 的显式确认口径一致）。
- 每次 `--apply` 生成 `ingest_run_id`，落进每条记录 metadata。
- 单 store 一个事务，整支成功或整支不落；跨 store 不做分布式事务，失败者进报告。
- `--undo <ingest_run_id>` 按标签精确删除该批记忆行与会话消息。
- `apply` 两种输入都收：源目录（先识别再转换）与**已转好的包**（有 `manifest.json` 的目录直接写库，
  不再经临时目录重转）。「先 convert 看包、再 apply 同一支包」因此是全通路（守卫：
  `test_cli.py::test_apply_accepts_a_previously_converted_bundle`）。
- 一个可探查 store 都没探到（或部分 store 认不出）时以非零码收尾，认不出的那一支一个字节都不写；
  退出码 `0 成功 / 2 未识别或冲突 / 3 校验失败 / 4 报告态`。
- 条目数/体积上限，超限拒绝。
- 安全：SQLite 一律只读 URI 打开（`probe.read_only_connect` 是唯一打开点，路径走 `Path.as_uri()`
  转义——字面的 `%` 不转义会被 SQLite 当转义序列解掉，把"打不开"报成"未识别"）；包内路径过
  `safe_paths.resolve_within`（zip-slip 已有先例测试）；导入内容不进 system prompt，工具参数只当数据存。

## 7. 测试与验收

### 7.1 2026-09-21 兼容性修复批次（逐条处置）

计划与取证：`docs/04-plans/2026-09-20-external-agent-ingest-plan.md`（同批次工单 Task 1-12）。
审计报告 `docs/05-reports/外部agent导入兼容性审计_2026-09-21.md` 未在本次可见分支内（见下"回写"）。

| Finding | 处置 | 提交 |
|---|---|---|
| F-01 未知 kind 抛 ValueError 穿到写入口 | 已修（取值域进校验层 + intake 兜 ValueError） | 519030d4 |
| F-02 importance/temperature 无域校验 | 已修（同上） | 519030d4 |
| F-03a opencode 只有思考块即 IndexError | 已修（思考作用域收到消息内） | 8a076a2c |
| F-03b OpenClaw 缺记忆附表整支转不出 | 已修（NULL 列带别名） | 6c26172d |
| F-06 五处静默 now() | 已修（定不出→申报跳过） | a202e456 |
| F-07 空正文轮整条消失且不申报 | 已修（轮内记 reasoning_state；qwenpaw 补空行申报） | 83ecdfd9 / f48e14d7 |
| F-08 extra 不进落盘形状 | 已修（extra 随行落盘） | 83ecdfd9 |
| F-09 只有 redacted_thinking 的行不留痕 | 已修（产事件；hermes 照数申报） | 435c7f4b |
| F-12 只读 URI 未转义 | 已修（Path.as_uri） | 5b22942a |
| F-13 apply 不接受 convert 的产物 | 已修（_is_bundle 分岔） | 619f8f0b |
| F-14 空目录假成功 | 已修（零 store 退非零码） | 619f8f0b |
| F-15 第二份"记录→消息"映射 | 已删（只留 turns.py） | 620644e4 |
| F-19a 六份 _dropped_entries 各写一份 | 已修（上收 writer.dropped_entries） | 31d38bef |
| F-19b 角色不认报成"空正文" | 已修（本批核对：role 前缀在各族信封已申报，补防回归锁） | 31d38bef / fac2b1d3 |
| F-19c 死条件 `if rows or True` | 已修（去掉包裹） | 31d38bef |
| F-19d relations.jsonl 无从登记 | 已修（writer 按实计数 + validate 登记闸） | 31d38bef |
| F-20 origin 权威归一处 | 已修（校验器权威；咽喉 fail-safe 降档保留并写明） | 519030d4 |
| F-21 包内同名不同目录被拍平 | 已修（强制内容寻址命名 + 摘要必声明） | b74fa9ef |
| F-22 撤销拼全文取子串判引用 | 已修（改结构化引用集合） | b74fa9ef |
| F-04 导入会话用户归属 | 已修：CLI `--owner-user-id` + 会话级归属不变量（既有属主只读、共享批次不得放宽已有属主） | 见 §7.4 |
| F-05 导入结果对运行中服务不可见 | 已修：`MemoryManager.reload_memories()` 增量并入 + `POST /v1/memory/reload` 端点 + 管理页入口；CLI 出口改指该通道（重启降为兜底）。见 §7.6 | 见 §7.6 |
| F-10 撤销作用域口径 | 已修：按**行自带**三元组删盘 + 索引摘除收口（授权凭据是批次标签，不是调用现场作用域） | 578536b4 |
| F-11 回填历史的温度语义 | 已修：导入侧定标获知时刻（created_at 记事件、last_accessed_at 记获知），温度照原样落库 | b52eac01 |
| F-16 OpenClaw 同 event id 多行 | 已修：幂等键改立行主键 (session_id, seq)，event id 降级为 extra 标识；**真样本已取证**（npm openclaw@2026.9.5 上游 schema） | c35b3458 |
| F-17 memory-enhancement/import 端点 | 仍待拍板 DEC-5（退役/接线/声明仅演示，三选一；本轮不动） | — |
| F-18 私有方言双路幂等域 | 已修：打通（老脚本会话导入改走产品链，会话号与行幂等键只在转换器定义一处）；见 §7.4 | 见 §7.4 |

回写状态：本批次开工时审计报告 `docs/05-reports/外部agent导入兼容性审计_2026-09-21.md` 不在仓库
可见分支内（grep 全仓与全历史零命中），无法逐条追加处置结果；故把上表落到规格 §7.1，
待报告入库后按此表回写即可，不另建第二份口径。

### 7.3 2026-09-21 闸门批（F-04 / F-05 / F-10 / F-11 / F-16 / F-17 / F-18）

前批把七条留成闸门，理由是"要动运行期咽喉或需真实上游样本"。本轮把样本拉下来逐条核对，
凡是**可由事实判定、且修在上游产生非法状态那一侧**的都收了；只留真正的产品决定：

- **F-16 真样本取证（npm `openclaw@2026.9.5`）**：上游建表语句里 `transcript_events` 主键是
  `(session_id, seq)`；event id 的唯一性由第三张表 `transcript_event_identities` 承担
  （主键 `(session_id, event_id)`），而本转换器的指纹只要求两张会话表。上游自己的
  `copyRetainedTranscriptPayload` 会把同一条事件按**新 seq** 再插一份（只 `json_set` 修
  parentId），`readTranscriptEventIdentity` 对缺 id 的事件返回 undefined（只跳过 identity 行）。
  结论：event id 在源侧不是不变量，把它当包内幂等键，重复即整包被校验器判死、缺 id 又整行丢——
  两个方向的错，同一个根因。今改立行主键，真样本实测通过。
- **F-11 判定性**：不是产品二选一。`days_idle` 取 `last_accessed_at or created_at` 的语义
  （距今多久没被访问）本就正确，错的是导入侧只写了事件时刻、没写获知时刻。修在导入侧，
  created_at 照原样保留历史时刻、last_accessed_at 定标为导入时刻，温度一个字节不改。
- **F-10 授权口径**：批次标签 `ingest_run_id` 本身就是撤销的授权凭据（§6"回滚靠标签"），
  行的归属与调用现场的归属是两个语义；按现场三元组删盘是这两者混用。今按行自带三元组删，
  P1-6 越权守卫默认口径不变（只有显式传行归属才放宽）。同根因的第二个命中点——撤销不摘
  关键词倒排与运行期向量库——同步收口到 `_drop_from_recall_indexes` 一处，`forget` 共用。
- **F-05 只做诚实暴露**：开 HTTP 端点（推翻"本轮不开端点"）与加 `reload_memories` 入口
  （改运行期咽喉）都需拍板；但报告写"记忆 +N"而界面一条看不见，是第三种假成功。CLI 现报出
  "会话读盘即见；记忆需后端重启后才可见"，仅在有记忆写入时出现。
- **F-04 / F-18 已由拍板收口**（2026-09-21 第二批）：用户拍板"F-04 要给 CLI 加属主参数""F-18 打通"，
  落地见 §7.4。此前把它们记成产品决定的判断仍成立——正因是决定，才需要拍板后才动。
- **F-17 仍闸门**：退役 / 接线 / 声明"仅演示"三选一，属产品决定；本轮只做逐条说明（§7.5）。
  另修正前批一处过期前提：计划写"UI 层无调用者"，实测 `MemoryPage.vue:863` **确实在调**。

### 7.4 2026-09-21 拍板批（F-04 属主 / F-18 打通）

用户拍板后落地两条，都按"在产生非法状态的一侧修"落地：

**F-04 导入会话的用户归属**

- 读侧规则不动：`list_sessions` / `delete` / `rename` 的过滤是"空属主=共享"，这条正确。
  错的是导入侧生产了"没有属主"这份状态——多用户/多渠道下导入的他人历史对任意 `user_id`
  可见，且可被任意用户改名或删除。
- 修在 `SessionManager.import_session_messages(..., owner_user_id="")`（唯一导入写入口）：
  缺省仍为空=共享（单用户桌面下的合法语义，与 `add_message` 缺省口径一致）；显式给属主时
  写进会话文件 `user_id`，并随行落 `metadata.ingest.owner_user_id`。
- **归属是只读事实**：`_reconcile_owner` 是唯一判定处。既有属主与本批不符、或用"共享"批次
  去碰已有属主的会话（等价放宽可见范围）→ 抛 `SessionOwnerConflict` 整批拒绝；存量共享会话
  被指定属主导入时回填（与 `add_message` 的 DATA-P1-1 同口径）。
- **判定在任何写入之前**：`check_ingest_owners` 由 `apply_bundle` 在写第一字节前调用，
  避免"前几支会话已落盘、后一支才抛"的半程导入；咽喉异常在 intake 收口成 `BundleError`。
- 写入 → 读取 → 反馈闭环：`ingested_run_owners` 回读 + CLI `--owner-user-id` +
  undo 报告印出"属主 u_alice，记忆 N 条、消息 M 条"，撤销不再是无名删除。

**F-18 两条导入路收口到同一幂等域**

- 实测的分裂是两套身份：同一支 dialog 源，老脚本落 `session_kai-dialog-20260501`（行键
  `(kai_import.source, ts, 内容哈希)`），ingest 落 `session_dialog-2026-05-01`（行键
  `metadata.ingest.identity_key`）——两套会话号 + 两套行键，互不认对方。
- **修法不是给私有方言侧再补一份派生规则**（那是第二份事实源），而是让老脚本的会话导入
  走产品链：删掉自造的 `SRC_PREFIX`/`_dedup_key`/`_derive_title`/`_SessionWriter`/三族
  各自的抽取函数/`MAX_TOOL_RESULT` 截断（均无仓内第二消费方），`import_chats` 改为
  逐 store `probe_store` 认指纹 → 转换器 → `apply_bundle`。会话号与行幂等键只在
  `converters/` 定义一处，两条路的幂等域因此天然是同一个。
- 分族计数从产出的包按 `session_id` 去重数出（一支会话表库里住着多场会话，按 store 计数
  会把"几场会话"报成"几支库"）。
- `intake.session_manager_for()` 收口会话库装配口径（CLI 与老脚本共用）。
- 同批顺带修：`import_session_messages` 零新增批次不再落盘（原来即使 `added == 0` 也写回
  一个 `updated_at`，给文件盖"这次动过"的章，幂等重跑就证明不了"空操作"——反方向 interop
  用例抓到）；`apply_bundle` 包里有记忆却无人接时响亮拒绝，不静默丢那批记忆。

判据（`tests/unit/memory_ingest/test_import_interop.py` 五个用例，双向都咬合）：
老脚本先导 → 产品链零增量且文件字节不变；产品链先导 → 老脚本零增量且文件字节不变；
会话号与产品链一致；落盘行带 `metadata.ingest.identity_key`。

### 7.5 F-17 `POST /memory-enhancement/import` 的现状（待拍板 DEC-5）

真后端实测（登录后打真端点，非读码推断）：

- 端点写的是 `memory_enhancement.py` 的**进程内 dict** `_memories_store`：既不入 SQLite、
  也不进 `MemoryManager`。实测导入返回 `Imported 1 memories`，但同一进程的 `GET /memory`
  （管理页列表用）`count = 0`，而 `GET /memory-enhancement/categories` 报 1 条——说明写的是
  另一个面，且那份 dict 重启即空。
- `MemoryPage.vue:863` 的调用链是：导入弹窗确认 → `memoryApi.importMemories(...)`（打
  `/memory-enhancement/import`）→ 提示"导入 N 条" → `fetchMemories()`（打 `GET /memory`）+
  `fetchStats()`。两端点读写两个不同的面，所以这段代码实际实现的是"**点了确认、提示成功、
  列表里什么都没有**"——报告说成功、用户看不到，属假成功。
- 同文件的 `forget` / `strengthen` 端点实测落 `_memories_store`：`MemoryManager` 没有
  `forget_memory`/`strengthen_memory` 两个方法（实测 `hasattr` 均为 False），那两个分支永不命中。
  所以**删 UI 调用点解决不了问题**——得先定端点去留。
- 去留三选一（退役并删前端 API / 接进 `MemoryManager.import_memories` / 保留但响应声明
  "仅演示不落库"）仍是产品决定，本轮一行不改。

### 7.6 2026-09-22 可见性批（F-05 后半：reload 通道）

用户拍板"开 HTTP 端点 / 加 reload_memories 入口"后落地。**根因**：记忆快照只在进程
构造时 `_load_from_db` 读一次盘，另一个进程（CLI 导入、备份恢复、多实例）写下的行对
运行中的服务不可见——报告写"已写入"而界面一条看不见，是既非拒绝也非申报的假成功。
可见性条件只有两条：**服务重启** 或 **显式 reload**；本轮兑现后者。

- **`MemoryManager.reload_memories() -> int`**：口径与 `_load_from_db` 同源（agent 全量，
  视图层再按调用语义过滤），差别只在"只并入缺失的行"（判据 = 业务 id + 行自带三元组）。
  行构造收口到 `_row_to_memory`、并入去重收口到 `_merge_loaded_memory`，装载与 reload
  共用同一处——两处各写一份就是下一轮漂移的起点。
- **召回面同步并入**：关键词倒排逐条 `upsert_memory_index`（**禁用** `build_keyword_index`
  ——它先 `clear()`，只喂缺失行会抹掉既有倒排）；内容门索引缺键才登记
  （`_merge_content_index`，用 `setdefault` 不抢已有键归属），否则 reload 之后同键写入
  会另起一行。
- **不写盘**：这是读侧可见性通道，不新增也不改写任何持久行。
- **`POST /v1/memory/reload`**（`neurova/api/endpoints/memory/visibility.py`）：返回真实
  并入条数（幂等，无缺失行时为 0）。**注册顺序**与 `/stats`/`/hot` 同一条纪律——字面路由
  必须先于 crud 的 `/{memory_id}`，否则被吞成"获取 memory_id='reload' 的记忆"→ 404。
- **闭环**：CLI 出口由"需重启后才可见"改为指向该端点（重启降为端点不可达时的兜底）；
  管理页 `MemoryPage` 加"重新读盘"入口（`reloadMemories()` + 11 份 locale 的
  `memory.reload` / `memory.reloadHint`），写入 → 读取 → 反馈形成闭环。

判据（`tests/unit/cognitive_layers/memory_layer/test_reload_memories_visibility.py`、
`tests/unit/api/test_memory_reload_endpoint.py`、`tests/unit/memory_ingest/test_cli.py`）：
增量与幂等（2/0）、本进程运行期记忆不被抹掉、盘上行一个字节不改、关键词倒排既有词条不被清空、
门索引咬合（同键写入不另起行）、快照口径不因 reload 收窄、`/reload` 不被 `/{memory_id}` 吞掉。

### 7.2 常驻判据

- 转换器：每族一个合成 fixture 正例 + 一个"像但不是"的负例；黄金 bundle 摘要进 CI。
- 校验器负例：未知 schema_version、origin 越界、`seq` 断裂、计数不符、路径越界。
- 写入：重复 `--apply` 幂等；`--undo` 精确回到前态；不触发运行期副作用（断言关键词/向量索引未被写）。
- 真实对照：`Kai/history.db` 会话族与现脚本输出逐条比对（基线：7 会话 / 61 条消息），
  差异只允许出现在有意补回的 `headline`/`tool_state`/`agent_id`/`metadata`。
- CI 安全：全部合成夹具，不依赖任何外部工程目录存在。

## 8. 落地顺序

1. `memory_ingest/` 骨架 + bundle 校验 + 两个咽喉入口。
2. `probe` DSL + **会话族**转换器（公开 QwenPaw `conversation_history` 优先）+ CLI 三态与 `--apply`/`--undo`。
3. 仓库处置：`tests/unit/migration/` 解忽略并入常规套件；`.gitignore` 删除
   `/scripts/import_kai_to_neurova.py` 一行，本地脚本在等价验收通过后退役；
   `agent_workspaces/kai/` 与 `docs/05-reports/kai-import-render-verify-*.png` 维持忽略。
4. 后续每家一单：OpenClaw / Hermes / dsh / Claude Code / Codex。无 fixture 不写进支持清单。

v1 的记录类型边界（避免接口悬空）
- 第 1-3 步是第一轮工单：**真实来源只有会话族**。`memories.jsonl` 与 `MemoryManager.import_memories()`
  在同一轮把契约、校验与写入实现补齐（用合成 fixture 与幂等/撤销测试钉住），但不假装"已支持某家的记忆导入"。
- 第一个真实产出记忆记录的转换器，取决于下面这条映射规则先定下来：各家记忆面普遍是
  有界策展 markdown（Hermes `MEMORY.md`/`USER.md`、OpenClaw 工作区 Markdown + chunk 索引）
  或文件分片（ReMe `files_*/chunks_*`）——**它们该落 Neurova 的 memories 表还是 knowledge 面**，
  是语义决策，不是转换器细节。定在 §9，另单。

## 9. 已知缺口（登记，不在本设计内解决）

- 分片/策展型记忆条目的归属：chunk（path+start_line+end_line+text+embedding）与"一条记忆"
  （content+category+importance+origin）**不同构**，映射规则已在 `openclaw_transcript` 定下并被测试
  钉住：正文取 chunk 文本、`source` 列两值映射 memory_type/category（memory→semantic/knowledge、
  sessions→episodic/conversation）、`origin_class` 逐字透传（与本系统 `MemoryOrigin` 同词）、
  importance 按 1-10→0-100 定标且缺档用本系统默认 50、path+行号成 `source_ref`、
  `supersedes_key` 成 `supersedes`；向量/内容哈希/嵌入模型属源侧派生索引一律不搬（申报条数）。
  **没记出处的条目按 `untrusted` 最低信任导入并申报条数**（源侧自己的回填也是 untrusted）：整条丢掉
  是丢内容、悄悄抬信任是投毒，落最低档 + 报数两头都保住；时间用该条自己的 `updated_at`，不用导入时刻。
- 私有方言的记忆导入：本机 `qwenpaw_memory*` 一族无公开格式可依；`memories.jsonl` 与
  `MemoryManager.import_memories` 已就位，产出记忆的第一家是公开族 `openclaw_transcript`
  （会话+记忆同属一支 store，一支包两样都装）；其余各族目前仍只导会话。私有来源（记忆库、
  session_contexts 快照、reme 笔记、身份文件）由 `scripts/import_kai_to_neurova.py` 继续管：它已从
  "本地不入库"改为随仓入库并标注**不再是产品入口**（回归在 `tests/unit/migration/`，15 条）。
  新格式一律进 `scripts/ingest_memory.py`，不往那个脚本加方言。
- 只有记忆索引、没有会话事件表的库导不了：detect 认不出（指纹按会话表立），这种库要导记忆得先
  给它一条独立指纹——目前没有样本，暂不立。
- 身份/人格文件导入（`import_identity`）：归人格装配面，已定不并入。
- 记忆图边落图（`relations.jsonl`）：v1 只登记。
- 运行期记忆写入无统一事件总线：`refresh_moe_index` 至今零调用方，本设计不依赖它。
- 已核不是问题（勿重修，2026-09-21 批次反证）：源的 WAL sidecar 不由识别与转换读取（只读 URI 打开
  主库即可，`-wal`/`-shm` 缺席也不影响）；非 UTF-8 行由各读点的 `errors="replace"` 承接，
  识别与包产出都不会因此崩；`probe._structure` 对打不开的库回 `{"error": ...}` 而非空结构。
- 导入媒体在**运行中的服务**里看不见：intake 把字节落进 `agent_workspaces/<agent>/media/`
  并按注册处同一算法给出 `metadata.artifacts` 条目，但产物注册表是 API 进程内的字典
  （`artifacts_api._artifacts_store`），跨进程不共享。要让导入的图片在 UI 里打开，需要的是
  注册表持久化（预存缺口，见 `tests/unit/api/test_files_store_persistence.py` 的红），
  不是再往导入侧加一遍写入。
- 通道侧会话号仍带冒号（`discord:{channel}:{user}` 等）：路径装配处已统一归一并在读侧保留
  源名兜底，POSIX 老库不受影响；但**新写入**会落在归一名下，若老库里同日已有源名文件则
  续写老文件——彻底收敛需要一次带备份的重命名，另开批次做。
