# 接口梳理：记忆系统（`/api/v1/memory*` 全域）

> 生成日期 2026-10-05，处置记录更新至 2026-10-07。范围：6 个 router / 现存 **104 条路由**（原 109，本域已退役 5 条无人消费且无实现的路由，见 §十一）。
> 仓内既有文档 `docs/01-architecture/02-memory-system.md`（v1.0.0-beta1，最后更新 2026-06-07，末次改动为分类闭环批）只讲模块架构，**不含 HTTP 面**，故本篇无平行源。

## 证据口径（三类，逐条标注）

| 标记 | 含义 |
|---|---|
| `[实测]` | 打到本机 9527 运行实例的真实 HTTP 响应，或直接读磁盘/SQLite/在进程内调用函数得到的输出 |
| `[静态]` | 读代码/配置得出，附 `文件:行号`，未跑运行时 |
| `[未复核]` | 子代理取证后我未逐条复算，按原始出处引用，风险自负 |

**一条必须先讲的前提**：9527 实例加载的是**提交态代码**，而工作树有 7 个记忆域文件未提交改动（`git status --porcelain`：`memory/base.py`、`crud.py`、`metacognition.py`、`profile.py`、`tkg.py`、`working_memory.py`、`memory_enhancement.py`）。所以 `[实测]` 与 `[静态]` 在 §十-1 上给出了**互相矛盾的答案**，两边都对——分别对应两个代码状态。

---

## 一、接口概览

### 1.1 挂载链

- 注册表：`neurova/api/endpoints/__init__.py:215-323`（`ENDPOINT_MODULES`，挂载事实唯一落点）
- 拼接：`neurova/api/endpoints/__init__.py:340` `app.include_router(module.router, prefix="/api" + prefix, ...)` `[静态]`
- 调用者：`neurova/api/app.py:566` `register_endpoint_routers(app)`，旁路 `include_router` 已删（`app.py:560-565` 注释）`[静态]`
- 结论：所有记忆路由的完整前缀是 `/api/v1/...`。`/api` 来自 `:340` 字面量，`/v1` 来自注册表每行。

| router 模块 | 注册行 | 对外前缀 | router 级鉴权 | 路由数 `[静态]` |
|---|---|---|---|---|
| `endpoints/memory/`（包） | `__init__.py:223` | `/api/v1/memory` | **无**（`base.py:22`） | 70 |
| `enhanced_memory_search_api.py` | `:283` | `/api/v1/enhanced-memory-search` | **无**（`:18`） | 11 |
| `memory_timeline_api.py` | `:287` | `/api/v1/memory-timeline` | `Depends(get_current_user)`（`:11`） | 4 |
| `memory_enhancement.py` | `:293` | `/api/v1/memory-enhancement` | `Depends(get_current_user)`（`:38`） | 6 |
| `memory_share_groups.py` | `:296` | `/api/v1/memory-share-groups` | `Depends(get_current_user)`（`:23`） | 11 |
| `memory_settings_api.py` | `:301` | `/api/v1/memory-settings` | 无，逐端点声明（`:22`） | 7 |

路由数按文件（取证时口径）：`crud 11 / eki 11 / metacognition 16 / emotion 6 / working_memory 8 / pending 4 / profile 4 / tkg 4 / questions 3 / markdown 2 / visibility 1`（主包 70）+ 卫星 39 = **109**。
2026-10-07 退役批后（§十一）：`questions 0（整模块删）/ eki 10 / metacognition 15`，主包 **65** + 卫星 39 = **104**。`[静态]`

主包路由遮蔽纪律：`memory/__init__.py:12-25` 规定 **`crud` 必须最后导入**，因其 `/{memory_id}` 会吞掉后注册的字面路由；当前导入序 markdown→eki→emotion→metacognition→profile→questions→tkg→working_memory→pending→visibility→crud，按此序无遮蔽 `[静态]`。

### 1.2 唯一装配点

所有记忆读写都经 `neurova/api/endpoints/memory/base.py:174-210 get_memory_manager(agent_id, user)` `[静态]`：

| 步骤 | 行为 | 失败形态 |
|---|---|---|
| 1 | `get_app_state()` 取应用状态 | 无 state → `APIError(AGENT_NOT_INITIALIZED=6001)` → **HTTP 500** |
| 2 | 传 `agent_id` → `_state.agents.get()`；不传 → `_state.get_agent()`（`app.py:70-80` → `endpoints.get_agent_instance`） | agent 不存在 → 404；默认 agent 未初始化 → 6001 → 500 |
| 3 | `agent.memory_manager` 缺席 | `MEMORY_OPERATION_FAILED=7001` → **500**（未列映射表） |
| 4 | `set_request_scope(neuser_id, user_id)`（`manager.py:852-860`，ContextVar，不改共享单例） | 不支持时仅 `logger.debug`（`base.py:208`）——**静默降级** |

身份缺省值：`(user or {}).get("neuser_id") or "default"`，`user_id` 同理（`base.py:203-204`）`[静态]`。

---

## 二、主要功能

记忆系统对外提供：写入（`remember`）、检索（`recall`）、单条读改删、统计与温度运维（`/stats` `/hot` `/crystallized` `/decay` `/compress`）、跨进程对账（`/reload`）、以及七个扩展面（EKI 认知优化、情绪、元认知、待确认队列、用户/自我画像、时序事实、工作记忆），外加 5 个卫星面（增强检索、时间轴、增强操作、分享组、参数配置）。

**分支划分主线只有一条**：`agent_wide` 参数。默认三层隔离（`agent_id`+`neuser_id`+`user_id`）；`agent_wide=True` 把基集换成 agent 全量，**显式关掉第 2、3 层**（`manager.py:1346-1356`、`903-911`）`[静态]`。

---

## 三、业务逻辑

### 3.1 读写模型：内存快照 + 写穿，REST 读的不是 SQL

这是整个域最要紧的一条，所有接口的行为都由它派生 `[静态]`：

1. **构造期读一次盘**：`manager._load_from_db()`（`manager.py:470-529`）执行 `SELECT * FROM memories WHERE agent_id = ? ORDER BY created_at DESC`（`:495-497`），灌进进程内字典 `self._memories`（`:189`）。
2. **此后所有读**都在内存字典上做过滤（`_scoped_memories` `:894-901`、`_agent_memories` `:903-911`）——**没有按 neuser/user 的 SQL**，三元组过滤是 Python 对象比较。
3. **所有写**先改内存对象，再写穿到持久库：`_persist_memory` → `_persist_upsert`（`:692-704`）→ `_PERSIST_UPSERT_SQL`（`:667-685`，完整 19 列，`ON CONFLICT(id) DO UPDATE ... WHERE agent_id/neuser_id/user_id` 三列相等才允许覆盖；跨作用域同 id 冲突时 `rowcount=0`，改写为 `\x1f` 作用域前缀行 id，`:688-690`、`:700-704`）。
4. **另一进程写的行看不见**，直到重启或显式 `POST /api/v1/memory/reload`（`visibility.py:22`）——该端点做**双向**对账：并入盘上新行、回收盘上已消失行（`manager.py:531-545` 注释与实现）`[静态]`。

> 直接后果：**"这条记忆在库里"与"这条接口能返回它"是两件事**——快照只在构造期读盘，外进程写入既非拒绝也非申报地不可见，§十 的"恒空"类缺陷有一半的根在这里。
>
> **一条未坐实的观察（如实标未确认）**：实测 `GET /api/v1/memory?limit=2` 返回 `count:0`、`GET /memory/stats` 返回 `total_memories:0`，而同一时刻磁盘 `neurova_memories_persist.db` 里 `agent_id='default'` 有 5 行（见 §四 附注）。**冲突原因未确认**——候选有三条：运行实例绑定的 agent 非 `default`、`NEUROVA_AGENT_WORKSPACES_DIR`（`agent_workspaces.py:14`）把工作区根指向别处、或快照装载早于这些行落盘且从未 `reload`。本轮未逐条排除，故不用它作"跨进程不可见"的例证。

### 3.2 recall（`GET /api/v1/memory`，`crud.py:30`）

主流程 `[静态]`：

1. `memory_type` 逗号多值逐段校验，任一非法 → **422 `HTTPException`**（`crud.py:43-48`；校验刻意放在 `try` 之前，注释说明防被下面 `except Exception` 收编成 `APIError`）。
2. `manager.recall(query, category, limit, agent_wide=True, memory_type)`（`crud.py:51-54`）——**搜索端点固定扩权**，同 agent 内跨用户可见。
3. 锁内构造基集 → 排除 `FORGOTTEN`（`manager.py:1352-1363`）→ 类型过滤（全非法则确定性空集，不静默回退全量，`:1369-1382`）→ 分类过滤 → 温度过滤。
4. 有 `query` 且 `use_semantic`（默认 True）→ `_semantic_recall`（`:1402-1404`，透传 `agent_wide` 防管理页"列表可见、搜索不可见"割裂）；否则关键词子串匹配（`:1406-1408`）。
5. 命中前 `limit` 条 `touch()` 后**批量落盘**（单条走 `_persist_memory`，多条走 `persist_memory_batch`，`:1416-1425`，注释点名替代"top-10 即 10 次 fsync"）。
6. 每条发 `MemoryEvent.MEMORY_ACCESSED` 到 `self._bus`（`:1426-1433`）——进程内总线，非 MQ。

异常：`AGENT_NOT_INITIALIZED` 被**降级成 200 + 空列表**（`crud.py:65-71`）；其余 → `MEMORY_SEARCH_FAILED=7003` → **HTTP 500**（7003 不在映射表，见 §八）。

### 3.3 remember（`POST /api/v1/memory`，`crud.py:78`）

入参 `AddMemoryRequest`（`base.py:47-60`）：`content` 1-50000、`auto_classify` **默认 True**、`auto_analyze_emotion` 默认 True、`emotion_score` -1..1。

`manager.remember`（`manager.py:1013-`）主流程 `[静态]`：

1. 未显式传 `temperature`/`importance` 时读配置：`manager.new_memory_temperature` 默认 **65.0**、`manager.new_memory_importance` 默认 **50.0**（`:1062-1071`）。注释记录原默认 100 ≥ 高温不衰减阈值 80，导致新记忆从不参与衰减（温度死锁修复）。
2. **内容门**：同作用域归一化相同表述只保首条，后到者返回既有 id 并刷 `updated_at`，不新增行（`:1044-1047` 语义说明）。
3. `auto_classify=True` → `_infer_and_apply_classification`（`:1089-1100`），**只补未声明的** `category`/`memory_type`/`perspective`，推断证据落 `metadata["_auto_classified"] = {..., "inferred":[...], "confidence":float}`。
4. 非法 `memory_type` → warning + 回落 `SEMANTIC`，原始值进 metadata 留痕 + `_stats` 计数（`:1105-1112`）；非法 `category` 同理回落 `GENERAL`，原值进 `_original_category`（`:1119-1129`）。
5. `mem_id = kwargs.get("id", f"mem_{counter:06d}")`（`:1076`）。

**死开关**：`auto_analyze_emotion` 不是 `remember` 的形参，落进 `**kwargs`（`manager.py:1039` 自陈"其余控制参数(留 kwargs)"），全仓零消费方 → API 上这个开关什么都不做 `[静态]`。

### 3.4 主包其余分组（逐条）

行号取自 `@router.*` 装饰器行 `[静态]`，除标注外均为我本轮 grep/读取直接核到。

| 组 | 路由 | 下游与要点 |
|---|---|---|
| crud | `GET /stats:120`、`/hot:141`、`/crystallized:170` | 全部 `agent_wide=True`（`:127/152/181`）。`/hot` 文档写 ">=50" 而实现取配置 `manager.hot_memories_threshold` 默认 **80.0** `[未复核→已复核 manager 默认值]` |
| crud | `POST /decay:199` | `run_decay_cycle(max_memories=5000, min_interval_seconds=300)`（`crud.py:211-213`）；**节流窗口内直接 `return 0`**（`manager.py:2610-2618`），故回执 `updated_count=0` 无法区分"无改动"与"被跳过" `[静态]` |
| crud | `POST /compress:263` | `dry_run` 默认 **True**（只出计划），`limit≤5000` → `compress_low_value_memories`（`manager.py:3689-`） |
| crud | `GET /{memory_id}:228` | 改走 `manager.get_memory()`（`crud.py:246`），归属校验在 `manager.py:1778-1793`（P1-6）。**兜底 except 的错误码写成 `MEMORY_NOT_FOUND`**（`crud.py:260`）→ 内部异常也报 404，语义错位 |
| crud | `GET /relations/{id}/traverse:286` | `traverse_relations`，`method∈{bfs,dfs}`、`max_depth 1..10` |
| crud | `PUT /{memory_id}:310` | `model_dump(exclude_none=True)`，空 payload → 422（`:326-327`）；`manager.update_memory` 现带归属校验（`manager.py:1806-1832`，越权 warning + False） |
| crud | `DELETE /{memory_id}:347` | `manager.forget(memory_id)` **不再传 `agent_wide`**（`crud.py:361`，`:358-360` 注释点名越权原因）；默认 `soft=True` 置 `FORGOTTEN`，而回执文案是"记忆已删除"（`:369`） |
| visibility | `POST /reload:22` | 见 §3.1；`hasattr` 不支持则 7001；返回 `reloaded`/`reaped` 两个真实读数 |
| pending | `GET /pending:46`、`/pending/decisions:67`、`POST /pending/{id}/confirm:90`、`/reject:177` | 权限用本地 `_is_admin(user["role"])`（`:42-43`），**非 `require_admin`**；非 admin 读裁决历史 → 403（`:74-75`）；confirm 由**端点闭包**在 store 锁内写主库（`:139/:164`）；`proposed_action=="forget"` 分支读侧 `agent_wide=True`（`:124`）而写侧 `forget` 不扩权（`:127`）→ 匿名/default 作用域删他人记忆得 404；reject 记内容指纹防重提。落库 `pending_memories`+`content_tombstones`（实测 `data/memory_pending/pending_memories.db`）**同一张表用 status 位区分**，裁决历史不是独立表 |
| questions | ~~`GET /questions/pending`、`POST /questions/ask`、`GET /questions/stats`~~ | **已退役**（2026-10-07）：`MemoryManager` 上三个方法一个都不存在（运行时 `hasattr` 逐条探明），同功能现役面在 `/api/v1/growth/questions`（`agent.question_queue_manager`）。见 §十一 |
| emotion | 6 条（`:46/:86/:119/:147/:185/:216`） | `/emotion/types`（`:147`）**零鉴权依赖** `[实测+静态]`；`/emotion/summary`、`/distribution` 用 `hasattr` 探测后兜空骨架，except 吞成 **200 "获取成功(降级)"** `[未复核]`；`GET /emotion/{type}` 的 `min_score` 形参**未透传下游**（`emotion.py:232` 只传 emotion/limit）→ 过滤条件失效 `[静态，本轮亲验]` |
| eki | 10 条（原 11，`/eki/reinforce` 已退役） | `POST /classify` 纯透传；`POST /classify-and-remember`（`:146`）在 `classify_and_remember` 之后**再调一次 `classify_memory`** 做回显（`:160-165`）→ 每次写做两遍分类 `[静态，本轮亲验]`；`GET /eki/reinforce` **已退役**：`manager.eki_get_reinforcement_recommendations` 全仓零定义，而语义相邻的 `manager.eki_recommend_reinforcement`（`:3108`）是"给传入的 id 打分"，与"推荐哪些记忆要强化"不是同一件事——改名接通会造出一个假实现，故随批删除（§十一） |
| metacognition | 15 条（原 16，`/meta/skills/generate` 已退役） | 12 条 `meta/*`（`:45/:68/:91/:115/:144/:168/:197/:221/:245/:269/:298/:328/:379`）走 `manager.meta_*`；`POST /meta/skills/generate` **已退役**（`manager.meta_generate_skill` 零定义，且整个 `/meta/skills*` 面在 manager 侧只是"最近元认知事件"的别名视图，不含技能生成，§十一）；`GET /{agent_id}/metacognition`（`:413`）与 `.../stats`（`:469`）**零鉴权依赖**且走 `get_meta_ledger`（非 memory_manager），except 吞成 200 空数据 `[静态+实测匿名 200]` |
| working_memory | 8 条（`:63/:89/:116/:142/:168/:194/:220/:245`） | 走 `manager.wm_*`；`DELETE /wm` 无归属也无确认参数（在 §十-1 回归修完后会成为一个匿名清空面）`[未复核]` |
| profile | 4 条（`:45/:69/:108/:133`） | `GET/PUT /users/{user_id}/profile` 的 `user_id` 是路径参且**无越权校验** `[未复核]`；画像缺失时返回 `{"message":"用户画像不存在"}` 冒充 data `[未复核]` |
| tkg | 4 条（`:59/:101/:139/:175`） | `POST /tkg/facts` 把前端契约 `entity/attribute/value` **显式映射**到权威 `subject/predicate/obj`（`tkg.py:75-81`，`:29-31` 注释记录曾静默写空三元组）；下游 `manager.tkg_*` → `TKGModule`（`manager.py:3199-3208`），`factStore` 缺省时回落**知识库底座单例** `get_knowledge_fact_store()`（`modules/tkg_module.py:57-63`）→ 落 `knowledge_facts` 表（实测 `data/knowledge/knowledge_facts.db`，208 KB，含 `knowledge_facts`/`knowledge_subjects`/`knowledge_conflicts` 等 8 表）`[静态+实测]`。`memory_layer/temporal_knowledge_graph.py:167` 的 `temporal_facts` 表**不在这条路径上**，且其构造默认 `db_path=":memory:"`（`:194`） |
| markdown | 2 条（`:43/:64`） | `MemoryExporter` 导出/写回文本层；两函数**无 try/except**，下游异常穿透为未处理 500 `[未复核]` |

### 3.5 五个卫星 router（逐条要点）

- **`memory_timeline_api.py`（4 条，全部需登录）= 零实现占位面** `[静态，本轮复核装饰器与实现]`：`/recent` 只算时间窗后返 `memories:[] total:0`（`:19-23`）；`/range` 透传 echo 恒空；`/grouped` 循环生成 ≤30 个 key、count 恒 0；`/stats` 全零硬编码。无 404、无 501，**前端在调**（`memory.ts:958`）→ 时间轴页面恒空。
- **`memory_enhancement.py`（6 条，router 级登录门）**：`_require_memory_manager`（`:99-125`）传 `getattr(request.state,"user",None)`，而 **`request.state.user` 全仓零写入点**（我本轮 `grep -rn "state.user =" neurova/` 唯一命中是该注释自身）→ user 恒 None → 作用域恒回落 `default`；`APIError`→**503**（`:118-124`）。importance 双向量纲换算：存储 0-100 对 API 0-1，`IMPORTANCE_SCALE=100.0`（`:44`）、`_toApiImportance:133`、`_toStoreImportance:142`。forget/strengthen 走 `agent_wide=True`（`:171/175/213`），**越权与不存在都报同一个 404**（`:175-178`、`:213-215`）。`/export` 的 `format` 未校验，非法值静默按 JSON（`:323-367`）。`/import` 的 overwrite/merge 分支把 `memory_type`/`origin` 传给 `update_memory`，而该键不在其受理字段内 → 静默丢弃（`:421-437` 对 `manager.py:1841-1880`）`[未复核]`。
- **`memory_share_groups.py`（11 条，仅登录门，无 admin 无属主校验）**：存储是 **JSON 文件不是 DB**——`_STORE_PATH = dataPath("memory_share_groups.json")`（`:28`）；落盘实现 `share_group.py:101-115`，格式 `{"groups":[...],"updated_at":iso}`，异常仅 `logger.error`（写失败静默）。**隐患（本轮亲验）**：`get_share_group_manager(storage_path=None)` 是"首访定终身"的单例（`share_group.py:300-307`），而 `storage.py:666` 以**无参**方式取同一单例 → 若记忆可见性判定先触发，单例 `storage_path=None`，`_save_to_file` 直接 return，分享组改动不落盘。首访顺序未确认。
- **`enhanced_memory_search_api.py`（11 条）**：`POST /search`（`:73`）**无鉴权**，引擎集合来自 `get_app_state()["agents"]` 逐 agent 取 `memory_agent.recall_engine`（`:21-44`），异常吞成 `agents={}`；只取 `engines[0]`（`:97`）；无引擎 → `code:0` 空 results（**假成功形态**）；异常 → `code:-1` 但 HTTP 仍 200（`:130-136`）`[未复核]`。`GET /stats`（`:139`）全零硬编码；`POST /decay`（`:515`）只回时间戳与 `affected_count:0`；`POST /analyze`（`:522`）按词数分支的假分析（confidence 硬编码 0.75）；`GET /activation/{id}`（`:541`）读 `_activations`（`:70` 声明，**全仓零写入**）→ 恒默认零值。**三条 `/settings` `/nerf-settings` `/channel-weights` 的真实落点各不相同**：`/settings` 写 `data/memory_settings.json`（经 `cfg.update_and_save`）+ 另一份 UI JSON `data/memory_search_ui_settings.json`（`:169`，实测**该文件不存在**）；NeRF 设置存**进程内** `_nerf_config` 与各引擎 `VolumeRenderer`（`:55-66`），**重启即丢**；`/channel-weights` 是函数内硬编码 5 组权重表（`:483-511`）`[未复核，本轮亲验 401/200 状态码]`。
- **`memory_settings_api.py`（7 条）**：读需登录、写/重置/导入需 `require_admin()`（`:111/:133/:163`）。参数唯一事实源 `settings_config.py`，10 个 section：`temperature`(decay_rate 0.1)、`auto_context`、`compression`(0.7/10/24/0.3/`enable_llm_compression=True`)、`activation`、`threshold.default 0.3`、`graph`、`vector_search`、`manager`(65/50/80/3/1.0/1.0)、`llm.temperature 0.7`，其中标【预留】的项无运行时消费者 `[未复核]`。**路由遮蔽（本轮亲验）**：`GET /settings/{section}`（`:83`）声明在 `GET /settings/export`（`:146`）之前，而 `:94-99` 对未知 section 抛 404 → `/settings/export` 恒 404。`PUT /settings` 对未知键/类型不符/越界一律 warning + 跳过、不抛异常，`updated` 为空时返 `code:1 "No valid settings were updated"` 但 HTTP 200（`:118-122`）。

### 3.6 分层惯例说明

主包**无独立业务编排层**：入口函数直接调 `MemoryManager` 门面方法（`memory/` 全包 grep 无 service/biz 层）`[静态]`。这与本仓其它域（`knowledge_core`/`agent` 等）一致，不属偏离。偏离点在**持久化层**：记忆域不用 ORM、不用 `core/connection_pool.py`，而是 manager 自持 `sqlite3.connect` + 自设 WAL（见 §四）。

---

## 四、涉及存储

| 库/文件（真实路径） | 表 | 访问点 | 用途 | 生产状态 |
|---|---|---|---|---|
| `agent_workspaces/<agent_id>/memory/neurova_memories_persist.db` | `memories`（19 列：`id,content,memory_type,category,lifecycle_stage,perspective,origin,emotion,temperature,importance,access_count,metadata,agent_id,neuser_id,user_id,shared,created_at,updated_at,last_accessed_at`） | 建表 `manager.py:349-370`；写 `:667-685`；读 `:495`、`:575`；索引 `idx_mem_3tier` `:381` | **记忆唯一真源** | **生效** `[实测]`：`agent_workspaces/default/...` 实测 5 行（见下附注） |
| `agent_workspaces/<agent_id>/memory/memory.db` | `memory_emotions`、`attachments`、`memory_attachments` | `manager.py:254 EmotionModule(db_path)`；`emotion_module.py:159/169/191/205` | 情绪态、附件 | 生效（实测各 0 行）；**该库无 `memories` 表** `[实测]` |
| `data/memory_pending/pending_memories.db` | `pending_memories`、`content_tombstones`、`extraction_leases` | `pending_memory.py:31/185/324` | 待确认提议、判重墓碑、抽取租约 | 生效（实测 0/0 行）；**无 WAL**（`:200` 裸 connect） |
| `data/knowledge/knowledge_facts.db` | `knowledge_facts` 等 8 表 | `/memory/tkg/*` → `tkg_module.py:57-63` → `get_knowledge_fact_store()`（`knowledge_facts.py:1092-1097`，`DEFAULT_FACT_DB` = `PRODUCTION_STORAGE_DIR/FOUNDATION_DB_NAME` `:30`） | 时序事实 | 生效 `[实测]` 208 KB |
| `data/memory_settings.json` | — | `settings_config.py:186-189/285-294` | 记忆参数覆盖值 | 生效（实测文件存在） |
| `data/embedding_cache.json` | — | `unified_vector_store.py:68-72/134-142` | embedding 写穿缓存 | 生效 `[实测]` 369 KB |
| `data/memory_search_ui_settings.json` | — | `enhanced_memory_search_api.py:169/198` | 检索 UI 设置 | 端点在读写，实测**文件不存在**（从未成功落盘或未触发） `[实测]` |
| `data/memory_share_groups.json` | — | `memory_share_groups.py:28` + `share_group.py:101-115` | 分享组 | 同上，实测**不存在** `[实测]` |

**附注：default 记忆库里躺着审计探针的残留（已部分清理，2026-10-07）** `[实测]`。本轮取证时 `agent_workspaces/default/memory/neurova_memories_persist.db` 有 5 行，内容直引为 `TAMPERED-…`、`TAMPERED-by-bob`、`TAMPERED-by-anon`、`ALICE-…`，与 `audit-reports/memory-isolation-2026-10-05.md` §二 图证 [2]/[3]/[6] 的植入语句逐字对应；**处置时复测已增至 12 行**——期间另有 7 行探针（`ALIVE-私密记忆`×3、`IMP-探针`、`DB-探针`×2、`SOCK-私密记忆`）落进同一库，形似并发会话正在使用的取证数据。
按授权范围只删除签名匹配的那 5 行（`mem_000001`–`mem_000005`），**其余 7 行原样未动**；删除前把全部 12 行整行导出为 JSON 备份（`%TEMP%\neurova-probe-residue-backup.json`，含库绝对路径与备份时刻），可按行原样回写。
报告 §二 声称"探针即用即删、`NEUROVA_DATA_DIR` 指到临时目录不触碰真实数据"，但这些行确实在真实工作区里——**残留未清是既有事实**，会污染任何按 default agent 的统计/演示读数。

**建成但生产零使用 / 落不了盘**（均 `[静态]`，除标注）：

- `memory.db` 之外还有一层 JSON 存储 `MemoryStorage`（`storage.py:270-282`，`memories.json`），目录 = `dirname(_db_path)/memory_storage`；**实测 `agent_workspaces/{default,kai}/memory/memory_storage/` 均为空目录**，全仓 `memories.json` 只出现在 `tests/` → 死层。
- `memory_record_store.py`：`MemoryStorage` 薄壳，**全仓无实例化点** `[未复核]`。
- `cognitive_storage_engine.py`：独立 LSM+FTS5 引擎（`memories`+`memories_fts`+3 触发器，`:169-216`，库 `data/<agent>/memory.db` `:243`），**不在 `MemoryManager` 路径**，仅 `agent_core.py:1423`、`neurflow_api.py:448` 自建 `[未复核]`。
- `temporal_facts`（`temporal_knowledge_graph.py:167-189`）：构造默认 `":memory:"`（`:194`），REST 面已改走知识库底座 → 该表在记忆域实际不落盘。
- `entities`/`edges`（`dependency_graph.py:114/124`）：`_save` 无 `db_path` 时直接 return（`:186-188`），而 `agent_core.py:425 get_dependency_graph()` 不传路径 → **零落盘** `[未复核]`。
- `memory_versions`（`version_control.py:154-176`）：`storage=None` 时 `:146-147` 提前 return，而 `agent_core.py:418/596` 正是不传 storage → **生产零读写** `[未复核]`。
- `neurova/memory/scripts/init_db.py` 的 19 表注册表落 `data/yi_ling_memory.db`：实测**该库文件不存在**，且其中 16 张表在 `neurova/` 内零引用 `[实测+未复核]`。

连接方式（本轮亲验 + `[未复核]` 细节）：记忆域**不走** `core/connection_pool.py`；`manager.py:341-346` 自持 `sqlite3.connect(..., check_same_thread=False)` + `PRAGMA journal_mode=WAL / synchronous=NORMAL / busy_timeout=4000`，写锁 `_persist_db_lock = RLock`（`:340`），读路径另有 `_load_from_db` 的常驻连接/短连接池双分支（`:485-491`，ADR 0014）。实测落盘产物：`agent_workspaces/default/memory/` 下 persist 库存在且伴随 `-wal`。

路径解析链（本轮亲验）：`base.py:174` → `agent.memory_manager`；`MemoryManager.__init__`（`manager.py:165-180`）的 `db_path` 哨兵 → `_default_db_path_for`（`:4228-4238`）= `get_agent_workspace_dir(agent_id)/memory/memory.db` → `agent_workspaces.py:20-28`，可被 env `AGENT_WORKSPACES_ENV` 注入；持久库由 `persist_landing.py:23-28` 固定同目录名 `neurova_memories_persist.db`。数据根 `data_root.py:28/37-48`：`NEUROVA_DATA_DIR` 未注入则回落 `<repo>/data`；**该 env 在 `.env.example`、`docker-compose.yml`、`pyproject.toml` 均未声明** `[未复核]`。

---

## 五、远程调用接口

**结论：记忆读写路径上没有跨进程 HTTP 调用。** `[静态]`

| 类型 | 标识 | 地址 | 说明 |
|---|---|---|---|
| 本地推理 | ONNX Runtime embedding | 无网络 | `semantic_search.py:304-306` → `embedding/__init__.py:26-48` 工厂 → `onnx_embedding.py:62` 默认 `BAAI/bge-small-zh-v1.5`，本地目录 `models/embedding/bge-small-zh-v1.5/`（本轮实测**存在**）；引擎为 None 时降级为 256 维哈希词频向量（`semantic_search.py:170-191`） |
| 一次性外网 | 模型下载 | `https://hf-mirror.com/{repo}/resolve/main/`（`model_downloader.py:391`）、`HF_ENDPOINT`（`:398`）、ModelScope 优先（`:372`） | **仅首次拉模型**，不属请求链路 |
| LLM | `llm_client` | 无 | 压缩器接受注入式 client，但 `manager.py:3735-3737` 显式传 **`None`** → `compression.py:423/885/956` 早退，`_llm_compression` 生产不可达 `[未复核]` |
| MQ | — | — | 无。`MemoryEvent` 走进程内 `self._bus` / `memory_stream.py:183` 自有回调流 |

依据：`memory_layer/` 全目录 grep `httpx|aiohttp|requests\.|AsyncOpenAI|OpenAI(|urlopen` **零命中** `[未复核]`；`config/` 无 embedding base URL 配置键。向量后端探测链 `unified_vector_store.py:261-288`（faiss→fastembed→onnx→tfidf），而 `requirements.txt` 有 `onnxruntime>=1.16.0`（`:46`）与 `sentence-transformers`（`:55`）、**无 faiss/fastembed**（本轮实测 grep 计数 0）→ 实际落 **onnx**，向量驻留内存（`:220-221`），只有 embedding 文本缓存持久化 `[实测+静态]`。

---

## 六、缓存与异步消息

| 类型 | Key/落点 | 用途/失效 | 状态 |
|---|---|---|---|
| 进程内快照 | `manager._memories`（`manager.py:189`）+ `_content_index`（`:191`） | **实质上是唯一缓存层**；失效时机只有构造期、`reload_memories()` 与重启（`:474-478`） | 生效 |
| embedding 缓存 | `data/embedding_cache.json`（`unified_vector_store.py:68-72`，写穿 `:134-142`） | 省重复编码 | 生效 `[实测]` |
| `neurova/core/cache.py` | `MemoryCache(capacity, default_ttl)` + 清理线程 + 缓存注册表（全仓唯一实现；曾经的 `memory/core/cache.py` 实装与 `memory_layer/cache.py` 薄壳已按 §6-204 后批退役） | **不在记忆读写路径**：消费者只有 `api/endpoints/settings.py`（清缓存，走 `clearRegisteredCaches()`）与 `core/metrics.py`（命中率） | 挂了但没人用 `[实测]` |
| 事件 | `MemoryEvent.MEMORY_ACCESSED`/`TEMPERATURE_UPDATED`（`bus_event.py:67`） | 进程内 pub/sub，无 MQ | 生效 |

后台触发（**均为进程内直调，不经 HTTP 端点**）`[静态/未复核]`：

- 温度衰减：`post_chat_pipeline.py:745` → `:901-909` → `agent_core.py:1892-1893` `run_decay_cycle(hours=1.0, rate=1.0, max_memories=500, min_interval_seconds=300.0)`。所以 `POST /api/v1/memory/decay` 是**手工补跑入口**，与自动路径共用同一节流窗口——刚聊完天再点必得 0。
- 固化/睡眠：`agent_core.py:650` 建 `IdleTimeTracker`，`:1383-1385`/`:1407` 注入回调；`idle_tracker.py:101` 轮询 60 s → `:243-245 run_promotion_cycle(max_memories=500, min_interval_seconds=1800)`（注释 `:241` 明示"无 LLM"）→ `:273-275 run_sleep_cycle`；`deep_sleep/hibernate` 受 `memory_consolidation_enabled` 门控（`:255-263`）。关停期 `agent_shutdown.py:72`。
- 压缩：**无自动调度**，仅 `POST /api/v1/memory/compress` 手工（前端按钮）。
- pending：无定时归档，状态机靠 REST 判决推进。

---

## 七、上游调用方

- **前端**（Vue，`NeurUI/`）：`src/config/index.ts:32` `apiBaseUrl = VITE_API_BASE_URL || '/api/v1'`；`src/api/index.ts:77` axios 实例 + `:88-91` 附 Bearer。封装集中在 `src/api/modules/memory.ts`（`BASE='/memory'`）：CRUD/stats/hot/crystallized/decay/reload/markdown（`:486-571`）、self-model 与用户画像（`:746-761`）、pending（`:1093-1108`）、emotion/eki/meta/questions/tkg/wm（`:581/:617/:668/:768/:789/:815`）；卫星面在 `:861/:897/:958/:984/:1045`；`memory-settings.ts:31-65` `[静态]`
- **后端有、前端零调用**（本轮 `grep NeurUI/src` 复算，命中数为 0）：`POST /memory/classify-and-remember`、`GET /memory/relations/{id}/traverse`；`/memory/classify` 仅 2 处 i18n 文案命中，无 API 调用 → **三条写得出/读得见但没人驱动** `[实测]`。
- **CLI**：`cli.py:694/701/705/709` 经 **HTTP** 打 `/api/v1/memory`（`GET`、`POST`、`DELETE /{id}`、`/stats`），`:749` hybrid_search `[未复核]`。
- **进程内**（同对象，非 HTTP）：`skills/builtin/memory_executor.py:105/135/242`（forget/recall/remember）、`agent/chat_pipeline.py:257` + `:467`（ContextVar 注入 user_id）、`voice_memory_bridge.py:233/342/432/444`、`agent/crystallized_experience_manager.py:325` `[未复核]`。
- **MCP 对外面**：`api/endpoints/mcp_server_api.py` 无 memory 命中 → **MCP 未直接暴露记忆工具** `[未复核]`。

---

## 八、异常处理

统一信封 `[实测]`：成功 `{code:0,message,timestamp,data[,request_id]}`；失败由 `neurova/api/error_handlers.py:31-45` 的 `APIError` 处理器产出 `{code,message,timestamp}`。实测 `GET /api/v1/memory/meta/skills/stats` 返回带 `request_id`（由 `middleware.py:33` 写入 `state.request_id`），而 `crud.py` 多数端点传 `_get_request_id(None)` 恒丢 request_id `[静态]`。

错误码 → HTTP（`error_handlers.py:17-27`，本轮亲验）：

| 码 | 值 | HTTP | 记忆域用它的地方 |
|---|---|---|---|
| `MEMORY_INVALID_CONTENT` | 7004 | 400 | — |
| `PERMISSION_DENIED` | 2002 | 403 | `pending.py:74-75`（非 admin 读裁决历史） |
| `NOT_FOUND`/`AGENT_NOT_FOUND`/`MEMORY_NOT_FOUND` | 3000/6002/7002 | 404 | `crud.py:248/329/364`、`base.py:191` |
| `RATE_LIMITED` | 4290 | 429 | — |
| `MEMORY_OPERATION_FAILED` | **7001** | **500** | `base.py:198`（"记忆系统未启用"）、`crud.py:117/376` |
| `MEMORY_SEARCH_FAILED` | **7003** | **500** | `crud.py:75` |
| `AGENT_NOT_INITIALIZED` | **6001** | **500** | `base.py:186/195` |
| `INTERNAL_ERROR` | 5001 | 500 | 各文件 `APIError.internal` |

即：**"记忆系统未启用""Agent 未初始化"这类本应 4xx/503 的状态全按 500 呈现**，未列映射表就是 500（`error_handlers.py:16` 注释自陈"未列出的错误码保持 500"）`[静态]`。

静默/降级形态清单（只登记不修）：`crud.py:65-71`（未初始化 → 200 空列表）、`emotion.py` summary/distribution（except → 200 "获取成功(降级)"）、`metacognition.py:461-466/489-494`（except → 200 空数据）、`enhanced_memory_search_api.py:81-91/130-136`（无引擎 code:0、异常 code:-1 但 200）、`share_group.py:114-115`（写盘失败仅 error 日志）、`manager.py:3199` 系列 `logger.debug` 吞索引失败（`:660-661`）、`base.py:208`（不支持 set_request_scope 仅 debug）。

---

## 九、鉴权矩阵

代码口径（本轮亲验行号）：

- 全局中间件 `GlobalAuthMiddleware`（`global_auth.py:81-136`）三态由 env `NEUROVA_GLOBAL_AUTH` 决定，**默认 `off`**（`:62-63`），off 时直接放行（`:93-95`）；白名单 `PUBLIC_EXACT_PATHS`（`:32-49`）**不含任何 memory 路径** `[静态]`。
- 主包 **68 处** `Depends(get_current_user_or_default)`（本轮 `grep -rn ... neurova/api/endpoints/memory/*.py | wc -l` 实测计数；分布于 `eki 12 / crud 12 / metacognition 15 / emotion 6 / working_memory 9 / tkg 5 / profile 5 / pending 5 / questions 4 / markdown 3 / visibility 2`）。
- `get_current_user_or_default`（`auth.py:533-559`）：**无凭证 → `_DEFAULT_USER` 放行**（`:546-547`）；有凭证但无效 → 401（`:552-557`，S-10 修复）。`neuser_id = payload.neuser_id or sub`（`:517-530`）。
- 主包内 **3 条零鉴权依赖**（本轮 AST 复核，唯一命中）：`emotion.py:148 get_emotion_types`、`metacognition.py:414 get_agent_metacognition`、`metacognition.py:470 get_agent_metacognition_stats`。
- 卫星：timeline/enhancement/share_groups 走 router 级**严格** `get_current_user`（`auth.py:415`，无凭证即 401）；`memory-settings` 写类与 `enhanced-memory-search` 写类走 `require_admin()`（`memory_settings_api.py:111/133/163`、`enhanced_memory_search_api.py:246/361/426`）；`enhanced-memory-search` 的 `/search /stats /decay /analyze /activation/{id}` **无鉴权**。

实测矩阵（`[实测]`，匿名无凭证 GET，打 9527 提交态实例）：

| HTTP | 路由 |
|---|---|
| 200 | `/api/v1/memory?limit=2`、`/memory/stats`、`/memory/hot`、`/memory/crystallized`、`/memory/eki/status`、`/memory/emotion/types`、`/memory/emotion/summary`、`/memory/markdown`、`/memory/tkg/stats`、`/memory/wm/stats`、`/memory/pending`、`/memory/self-model`、`/memory/meta/health`、`/memory/meta/skills/stats`、`/memory/relations/mem_000001/traverse`、`/enhanced-memory-search/stats`、`/enhanced-memory-search/activation/mem_1` |
| 401 | `/memory-enhancement/categories`、`/memory-settings/settings`、`/memory-timeline/recent`、`/memory-share-groups`、`/enhanced-memory-search/channel-weights` |
| 403 | `/memory/pending/decisions`（非 admin） |
| 404 | `/memory/nonexistent-id`、`/knowledge-integration/links` |
| 500 | `/memory/questions/stats`（`'MemoryManager' object has no attribute 'get_question_stats'`）、`/memory/eki/reinforce`（同类悬空）**——这两条所在路由组已于 2026-10-07 退役，现应 404；本行保留的是"实测当时打在旧实例上"的原始读数** |

另：该实例 `/openapi.json`、`/docs`、`/redoc` **全 404** `[实测]` → 无法用 OpenAPI 自证路由清单，本篇路由清点全部来自代码 AST 统计。

---

## 十、缺陷登记与处置状态（取证时全部为只读登记；处置见 §十一）

按"能不能现在复现"排序。

1. **P0（工作树，未提交改动引入）：16 条路由必 500。** —— **【已闭】** 该形态由内存隔离接线批（"身份解析收成单源，三条 by-id 路由回到归属校验"）在同批后续提交中修掉；本轮 2026-10-07 用 AST 复扫当前树，命中数 **0**（原文保留作取证与判据依据，因为它示范了"守卫测不到装配断裂"这一类盲区）。 `working_memory.py`(8)、`profile.py`(4)、`tkg.py`(4) 的函数签名把依赖参数命名为 `current_user`，函数体却写 `get_memory_manager(agent_id, user)` → `NameError`，被外层 `except Exception` 折成 `APIError.internal`（5001）。
   `[实测]` 本轮在进程内直接调用 `working_memory.get_wm_stats(...)` 得到：
   `NameError: name 'user' is not defined` → `APIError | ErrorCodes.INTERNAL_ERROR | 获取工作记忆统计失败: name 'user' is not defined`。
   `[静态]` AST 全量核出恰好 16 个函数（`working_memory.py:64/90/117/143/169/195/221/246`、`profile.py:46/70/109/134`、`tkg.py:60/102/140/176`）；`crud/metacognition/pending/questions/visibility` 均 0 命中。
   与 `[实测]` 的矛盾：9527 实例跑提交态代码，这些路由仍返 200。**这是同一次隔离修复（删 `_get_user_ids_from_token` 旁路）改参数名时漏改函数体所致**，属教义第 5 条"同一根因全命中点扫荡"未扫完。
   现成守卫 `tests/integration/test_memory_route_authorization.py` 只断言"依赖挂上了"，**测不出这个 NameError**（绕过了真实调用路径）。
2. **P1（实测恒 500）：三条调用不存在 manager 方法的路由。** —— **【已闭·退役】** 2026-10-07 按维护者裁决退役这 5 条路由（三条 questions + `eki/reinforce` + `meta/skills/generate`），含前端零消费封装与守卫测试同批，判据见 §十一。 `GET /memory/questions/stats` → `get_question_stats`（`questions.py:137`）、`GET /memory/eki/reinforce` → `eki_get_reinforcement_recommendations`（`eki.py:267` 路由）、`POST /memory/meta/skills/generate` → `meta_generate_skill`（`metacognition.py:365`）。前两条 `[实测]` 500 原文已贴；第三条 `[静态]`（全仓仅端点自身同名函数有定义，未跑 POST 以免写数据）。判据：我把端点里所有 `manager.<x>(` 调用与 `memory_layer/` + `neurova/memory/` 的 `def` 全集比对，缺失即这三条。
3. **P1（静态）：`pending.py:64` 与 `:87` 用 `ErrorCodes.INTERNAL`，而枚举只有 `INTERNAL_ERROR`（`api_standard.py:42`）** —— **【已闭·2026-10-07】** 改为 `ErrorCodes.INTERNAL_ERROR`，红灯见 `tests/integration/test_memory_pending_failure_envelope.py`（红态原文：`AttributeError: type object 'ErrorCodes' has no attribute 'INTERNAL'`；绿态断言 HTTP 500 + `code:5001` 且响应点名原始故障）。 → store 故障时 except 块内再抛 `AttributeError`，原始故障彻底丢失。
4. **P1（口径）：匿名写读落到 `default` 租户 + 读侧固定扩权。** 默认 `global_auth=off` 下，`GET /memory`(search)、`/stats`、`/hot`、`/crystallized` 全部 `agent_wide=True`（`crud.py:52/127/152/181`）→ 同一 agent 内**任意请求（含无凭证）**可读他人记忆；`DELETE /wm`、`GET/PUT /users/{user_id}/profile`、`GET /{agent_id}/metacognition[/stats]` 无角色门。注：`audit-reports/memory-isolation-2026-10-05.md` §三.1/2/3（PUT 无校验 / DELETE 扩权 / GET 读无人写的 `_storage` 恒 404）与 §三.4/5（`_get_user_ids_from_token` 双源旁路、`resolve_user` 死码）**在当前工作树均已修**——`base.py:33-39` 注释记录旁路删除、`crud.py:246/361` 改走带归属校验的 `manager.get_memory`/`forget`、`manager.py:1806-1832` 补齐 `update_memory` 校验。残留面即本条所列读侧。
5. **P2（实测 404 恒失败）：`GET /api/v1/memory-settings/settings/export`** —— **【已闭·2026-10-07】** 把字面路由移到参数化路由之前（不给 `{section}` 抄第二份 section 白名单，否则顶教义第 6 条），并在删除处留顺序纪律注释。守卫 `tests/integration/test_memory_settings_export_route_order.py` 双向钉：导出必须 200、未知 section 仍须 404。 被 `:83` 的 `/settings/{section}` 抢先匹配 → `:96-99` 抛 `404 Unknown section: export`。
6. **P2（前端在调、后端恒空）：`memory-timeline` 4 条全为空实现**；`enhanced-memory-search` 的 `/stats` 硬编码全零、`/decay` `affected_count:0`、`/activation/{id}` 读零写入的 `_activations`、`/analyze` 假启发式（confidence 常量 0.75）→ 四张仪表盘读数不可信。
7. **P2（数据丢失风险）：分享组单例首访顺序决定能否落盘**——`storage.py:666` 无参取单例 vs 端点 `memory_share_groups.py:34` 传路径，而 `share_group.py:300-307` 忽略后到的 `storage_path`；写失败仅 `logger.error`（`:114-115`）。实测 `data/memory_share_groups.json` 不存在（与"从未成功落盘"一致，但不能排除只是没人建过组）。
8. **P2（过滤条件静默失效）** —— **【部分已闭·2026-10-07】**
   已闭：`GET /emotion/{type}` 的 `min_score`（端点透传 + manager 侧新增 `min_intensity` 形参，默认 0.3 保持既有口径；守卫 `tests/integration/test_memory_emotion_min_score.py` 含"阈值降到写死值之下两条都必须在"的反向对照，防修法退化成恒空）；`AddMemoryRequest.auto_analyze_emotion`（提为 `remember` 显式形参并真的判定，默认 True 不改历史行为；守卫 `tests/integration/test_memory_auto_analyze_emotion_switch.py` 含默认口径对照）。
   **同批连带修掉一处自相矛盾的测试装配**：`tests/unit/memory/test_emotion_semantic_tagging.py::_remember` 一边传 `auto_analyze_emotion=False` 一边断言"内容情感明确应写入 emotion 行"——它一直靠这个 bug 才绿；修法取删掉自相矛盾的参数，不动断言强度。
   仍开放：`/memory-enhancement/export` 的 `format` 未校验；`/import` overwrite/merge 传入的 `memory_type`/`origin` 被 `update_memory` 静默丢弃。
9. **P2（假成功/文案不符）**：`POST /decay` 节流跳过与无改动都报 `updated_count=0`（`manager.py:2610-2618`）；`DELETE /memory/{id}` 软删却回"记忆已删除"（`crud.py:361/369`）；`PUT /memory/{id}` 回显可能 `data:null` 仍报"更新成功"（`crud.py:331-337`）；`memory-enhancement` 的 forget/strengthen 把越权与不存在压成同一个 404（`:175-178`、`:213-215`）；`memory_enhancement.py:106` 自陈的 `request.state.user` 恒 None（本轮亲验全仓零写入点）→ 该面作用域实际固定在 `default`。
10. **P2（死层/未接线，删除需人裁）**：`MemoryStorage` JSON 层（`storage.py:270-282`，实测目录空）、`memory_record_store.py` 无实例化点、`memory_versions`/`entities`/`edges`/`temporal_facts` 生产不落盘、`init_db.py` 的 19 表与 `yi_ling_memory.db`（实测文件不存在）、`vector_index_manager.py` 未接线、`memory/core/cache.py` 不在读写路径、`memory_layer/cache.py` 已废弃、`search/enhancement/decay.enabled` 等配置项无消费者。按本仓纪律，这些**不能按冗余直接删**——`docs`/审计报告记载过 `7835c367`、`33b71a25` 两刀把活链路摘掉造成"今天没人用"的历史。

---

## 十一、处置记录（2026-10-07）

维护者点单：修 §十 登记的缺陷 + 清理探针残留；三条"能力缺位"端点按**退役**处置。

### 11.1 已闭项与落点

| 项 | 生产码落点 | 守卫测试（先红后绿） |
|---|---|---|
| pending 错误码不存在 | `memory/pending.py:64/87` | `tests/integration/test_memory_pending_failure_envelope.py`（2 例，参数化两条路由） |
| `/settings/export` 被遮蔽 | `memory_settings_api.py`（字面路由移到参数化之前） | `tests/integration/test_memory_settings_export_route_order.py`（2 例，含反向对照） |
| `min_score` 未透传 | `memory/emotion.py` + `manager.get_memories_by_emotion`（新增 `min_intensity` 形参，默认 0.3） | `tests/integration/test_memory_emotion_min_score.py`（2 例，含"不得退化成恒空"对照） |
| `auto_analyze_emotion` 无人读取 | `manager.remember`（提为显式形参并真的判定，默认 True） | `tests/integration/test_memory_auto_analyze_emotion_switch.py`（2 例）+ 修 `tests/unit/memory/test_emotion_semantic_tagging.py` 自相矛盾的装配 |
| 三条恒 500 端点（实为 5 条路由） | 删 `memory/questions.py` 与其在 `memory/__init__.py` 的导入、`eki.py` 的 `/eki/reinforce`、`metacognition.py` 的 `/meta/skills/generate` 及孤儿模型 `AutoGenerateSkillRequest`；前端 `NeurUI/src/api/modules/memory.ts` 退役零消费封装 −55 行（`getPendingQuestions`/`askQuestion`/`getQuestionStats`/`getEKIReinforcement`/`generateMetaSkill` + `PendingQuestion`/`QuestionQueueStats`/`EKIReinforcement` 三类型，全部经复算确认仅在本文件出现、组件侧零消费） | `tests/integration/test_memory_retired_routes_guard.py`（7 例：五条路径 404、路由表无悬空登记、questions 模块与聚合器导入同批消失） |

退役判据（为何不选"接线"或"改 501"）：三条的 `MemoryManager` 侧**没有任何实现可接**——运行时 `hasattr` 逐条探明 `get_pending_questions` / `mark_question_asked` / `get_question_stats` / `eki_get_reinforcement_recommendations` / `meta_generate_skill` 全为 MISSING；`eki_recommend_reinforcement` 虽存在但语义是"给传入 id 打分"，改名接通等于造一个假实现；questions 的同功能现役面在 `/api/v1/growth/questions`（走 `agent.question_queue_manager`），本组是第二份从未接通的实现。既然前端也只有封装、组件侧零消费，按 AGENTS.md §2"断点必须接线或删除"取删除。

### 11.2 验证口径与归属

- 提交分三批（`fix(memory)` × 2 + `fix(api)` × 1），`git commit --only -- <显式路径>`，未用 `git add -A`，未触碰并发会话的在途文件。
  **commit 号在本仓不是稳定标识**（并发会话会 rebase/merge 重写历史），需要引用时用 `git merge-base --is-ancestor <h> HEAD` 复核可达性，别只凭 `git cat-file -e`。
- 退役批因 `manager.py` 同文件承载两处接线，无法无痕拆分，故与情绪接线合为一批提交，提交说明内逐条列根因。
- 前端：`npx vue-tsc --noEmit` **0 错**；`npm run test` 1932 passed / 1 failed test（2 个红文件：`duplicate-function-inventory.guard.test.ts` 载入期 SyntaxError、`collaboration/canvasEdgesStyle.test.ts` 悬浮层位置断言）。**两条经 A/B 复算为预存**——把 `memory.ts` 恢复到 HEAD 后单独重跑这两个文件，红态逐条一致。
- 后端：`tests/unit/api` + `tests/test_api` 全量 2178 passed / 17 failed / 8 errors。
  17 条按文件计数为 `test_memory_route_shadowing`×2、`test_files_store_persistence`×4、
  `test_transfers_wave_h4`×7、`test_skill_pool_api_rlock_protection`×2、
  `test_my_skills_wave_v`×1、`test_public_library_wave_h3`×1（分母由 `grep -c ^FAILED` 现算）。
  归属用 A/B 复算而非按目录猜：把这批改动临时移出后重跑同一组用例，失败集合**逐行一致**，
  全部为预存红，不折进本批成绩；那 8 条 ERROR（`test_generation_batch3`）随大合批执行顺序
  出现、定向重跑不复现，属本仓已知的"全量批红"泄漏族，仅登记不在此修。
  另 `tests/test_memory/test_base.py::TestRouter::test_router_prefix` 不在本次全量口径内
  （属 `tests/test_memory` 目录），它在聚焦 A/B 中同样基线即红，见 §11.4。

### 11.3 数字勘误（提交说明里的净 LOC 两处写错）

按 `git show --numstat` 逐提交重算（生产码，测试不计入）：

| 提交 | 生产码 | 净 |
|---|---|---|
| `bc9f8993` pending 错误码 | +2/−2 | 0 |
| `1e4cc835` settings 路由序 | +17/−14 | +3 |
| `0c305b0b` 情绪阈值 + 开关 | emotion +3/−1、manager +13/−5 | **+10** |
| `2f670878` 五端点退役 | memory.ts −55、questions.py −149、metacognition −33、eki −29、`__init__` −1 | **−267** |

**勘误**：`0c305b0b` 提交说明写"+21/-9"、`2f670878` 写"净减约 92 行"，均与 numstat 不符
（前者的 21/9 含已拆分掉的合并态测试文件，后者是我按"删除文件行数≈端点体量"估的，
没走 numstat 复核）。提交说明不可改写，**以本表为准**；教训同 §11.2 的 commit 号一条：
凡是写进交付物的数字，落笔前先按同口径重算一遍。



### 11.4 本批新开出、刻意不在本批处理的登记项

- `neurova/cognitive_layers/memory_layer/proactive_question.py`：随 `/memory/questions` 退役，它成为**零生产实例化、零 REST 消费**的孤儿（仅 `neurova/memory/__init__.py` 的懒加载映射表还挂着名字）。它与现役 `cognitive_layers/meta_cognition_layer/question_queue.py` 是同一功能的第二份实现，按教义第 7 条须先"对比优劣→取长补短→接通→退役"，比选要跨两个包并牵动 growth 面，**独立成批**，不与端点退役捆在同一次改动里。
- `neurova/skills/skill_generator.py`：本轮它唯一的天然消费方（`/meta/skills/generate`）已退役，"唯一实现零生产消费"的状态**原样保留**。它身上那条"不得删"的反向守卫来历存疑（见 `audit-reports/simplification-audit-2026-10-05.md` 与本仓判例 `TestDeadCodeReallyRemoved` 的相反判例），处置属人裁项。
- 3 条预存红测试：`tests/test_memory/test_base.py::TestRouter::test_router_prefix`、`tests/test_api/test_memory_route_shadowing.py::test_get_memory_detail_returns_200` 与 `::test_get_unknown_memory_returns_structured_404`（后两条的根是其测试替身 `_FakeMemoryManager` 未随"by-id 路由回到 `manager.get_memory()`"的接线批同步）。
- §十 第 4/6/7/9/10 条（fail-open 身份、空实现卫星面、假读数端点、单例首访顺序、死层清单）**状态不变**，仍为登记。

---

**小结**

- **链路长度**：一次 `POST /api/v1/memory` 平均触发 1 次内存写 + 1 次 SQLite upsert + 1 次 embedding 编码（本地 ONNX）+ 若干分类/索引；**零远程调用**，所以记忆接口的延迟不由网络决定，而由 `_lock` 争用与 fsync 批量策略决定（`manager.py:1414-1425` 的批量落盘正是为削这个）。
- **最反直觉的一点**：REST 读到的是**进程内快照**，不是数据库。库里有一行 ≠ 接口能返回它，跨进程写入要靠重启或 `POST /reload` 才可见（`manager.py:474-478`、`531-545` 注释自陈这是可见性仅有的两处兑现手段）。排查"页面空但库里有"的反馈时，先问快照时机，再怀疑查询条件。
- **与仓内分层惯例的差异**：主包无编排层（入口直调 manager 门面）——与本仓其它域一致；但持久化**绕开了 `core/connection_pool.py` 自持连接**，且并存 4 套互不相干的记忆存储（persist SQLite / 主库 SQLite / JSON `MemoryStorage` / LSM+FTS5 `CognitiveStorageEngine`），其中只有一套是真源——属教义第 6 条"单一事实源"未收口的现场。
- **鉴权是这个域的主要风险面**：`global_auth` 默认 `off` + 68 处 fail-open 依赖 + 3 条零依赖 + 4 条读侧固定扩权，构成"匿名即 default 租户"的现行口径。是否把 `/api/v1/memory` 纳入 `enforce` 属运维决策，`audit-reports/memory-isolation-2026-10-05.md` §五 明确未裁定，本篇同样不裁定。
- **交付纪律**：取证轮全程只读；处置轮（§十一）按先红后绿落地，每条改动都有对应的真装配路径守卫，预存红经 A/B 逐条归属、不折进本批成绩。遗留的 §十-4（fail-open 身份面）是本域**当前风险最高且仍未闭**的一条——它不是端点缺陷，而是"默认 off 的全局闸 + 匿名回落 default 租户"这一产品/运维裁决项。
