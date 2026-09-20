# 外部 Agent 记忆与会话导入（Ingest Bundle）设计

日期：2026-09-20　状态：待评审
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
- 漂移守卫：无 schema 版本的两族（Claude/Codex）必需列缺失即整 store 拒绝，绝不半导。
- 允许 `--source <converter>` 人工指定，跳过猜测（仍走同一校验器）。

### 5.1 平台落地名册（每加一家就更新这里，交叉误认由 `test_five_families_never_cross_match` 钉住）

| 指纹名 | 源形态 | 状态 | 证据来源 |
|--------|--------|------|----------|
| `qwenpaw_history` | SQLite `conversation_history` | 已实现 + 真库往返 | 本机源库 242 行实测 |
| `dialog_daily` | 每日一个 JSONL（一文件一场会话） | 已实现 + 真库往返 | 本机 40 个文件实测 |
| `legacy_session` | 1.x 工作区 JSONL（带表头记录） | 已实现 + 真库往返 | 本机 31 个文件实测 |
| `opencode_session` | SQLite `message` + `part`（JSON data 列） | 已实现 + 真库往返 | 本机 4 会话 / 845 消息 / 4423 块实测 |
| `codex_rollout` | `rollout-<ts>-<id>.jsonl`，线形 `{type, payload}` | 已实现（合成夹具）；**无本机真库可跑** | 该平台上游写入侧源码 |
| `dsh_session` | per-session JSONL，首行带 `version` | **只有指纹、暂无转换器**：detect 会认出并明确报"有指纹无转换器"，不写一个字节 | 本机无会话数据可取证字段 |
| （未命名） | 按项目目录分片的 JSONL（无版本字段） | 不做：既无本机样本也无在盘源码，凭记忆写字段就是猜 | — |

## 6. 失败与撤销

- 默认 `detect` 只出报告；写库必须显式 `--apply`（与既有 backup/restore 的显式确认口径一致）。
- 每次 `--apply` 生成 `ingest_run_id`，落进每条记录 metadata。
- 单 store 一个事务，整支成功或整支不落；跨 store 不做分布式事务，失败者进报告。
- `--undo <ingest_run_id>` 按标签精确删除该批记忆行与会话消息。
- 条目数/体积上限，超限拒绝。
- 安全：SQLite 一律只读 URI 打开；包内路径过 `safe_paths.resolve_within`（zip-slip 已有先例测试）；
  导入内容不进 system prompt，工具参数只当数据存。

## 7. 测试与验收

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
  （content+category+importance+origin）不同构，需要先定映射规则，再谈第二家真实来源。
- 私有方言的记忆导入：本机 `qwenpaw_memory*` 一族无公开格式可依；包契约里 `memories.jsonl`
  与 `MemoryManager.import_memories` 已就位，但**还没有任何转换器产出记忆**——三源转换器
  只产会话。私有来源（记忆库、session_contexts 快照、reme 笔记、身份文件）由
  `scripts/import_kai_to_neurova.py` 继续管：它已从"本地不入库"改为随仓入库并标注
  **不再是产品入口**（回归在 `tests/unit/migration/`，15 条）。新格式一律进
  `scripts/ingest_memory.py`，不往那个脚本加方言。
- 身份/人格文件导入（`import_identity`）：归人格装配面，已定不并入。
- 记忆图边落图（`relations.jsonl`）：v1 只登记。
- 运行期记忆写入无统一事件总线：`refresh_moe_index` 至今零调用方，本设计不依赖它。
- 导入媒体在**运行中的服务**里看不见：intake 把字节落进 `agent_workspaces/<agent>/media/`
  并按注册处同一算法给出 `metadata.artifacts` 条目，但产物注册表是 API 进程内的字典
  （`artifacts_api._artifacts_store`），跨进程不共享。要让导入的图片在 UI 里打开，需要的是
  注册表持久化（预存缺口，见 `tests/unit/api/test_files_store_persistence.py` 的红），
  不是再往导入侧加一遍写入。
- 通道侧会话号仍带冒号（`discord:{channel}:{user}` 等）：路径装配处已统一归一并在读侧保留
  源名兜底，POSIX 老库不受影响；但**新写入**会落在归一名下，若老库里同日已有源名文件则
  续写老文件——彻底收敛需要一次带备份的重命名，另开批次做。
