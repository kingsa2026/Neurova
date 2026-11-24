# 启动规模化实施方案：agent 并行装载 + 记忆温度分层

> 日期: 2026-11-24 · 状态: 备稿待拍板（批一用户已拍板"要做"，批二待确认 C1 路线）
> 源起: 同日用户问答——"agent 数量增加后启动会不会越来越慢？有没有方案？"以及
> "记忆既然有温度，能否只优先加载近期温度高的记忆？"

## 0. 背景与实测

启动耗时轨迹（本机 9527 真后端）：25min（全库迁移）→ 216s（数据收口）→ 43s →
22s（ASR 惰性，59f063c11）→ **14~15.5s**（providers 包惰性 + 编码器进程级共享，
20d299f27）。

现余构成：固定成本 ~4-5s（import/路由注册/核心组件）+ **agent 装载段 ~9s**
（10 agent 串行构造，单个 0.08~1.1s）。连续构造实测边际成本：首个 1.53s
（含进程级一次性初始化）、1658 条记忆的 kai 0.60s、小记忆 agent 0.08~0.10s。

**增长模型**：随 agent 数 × 各自记忆量线性增长；100 agent 外推 50~80s。
单 agent 装载 = `SELECT * FROM memories WHERE agent_id=?` 全量行 × sqlite 读取
+ 逐行 AES 解密 + 内存对象/索引构建（manager.py `_load`，约 985 行起）。

## 1. 目标与非目标

- G1 装载段从 Σ(单 agent) 变为 ≈ max(单 agent)（并行）。
- G2 单 agent 装载成本与**冷记忆数量**解耦（温度分层）。
- G3 召回语义不变：冷记忆最终可被召回，无静默失忆。
- 非目标：不做 agent 全量惰性构造（~40 处读取点扫荡，风险>收益，另案）；
  不改召回融合算法本身。

## 2. 已核实的事实基础（写方案前逐条读过）

| 事实 | 出处 |
|------|------|
| 装载入口串行逐个构造 | `neurova/api/app.py:268 _load_saved_agents` |
| 记忆全量快照 SQL | `manager.py` `_load`：`SELECT * FROM memories WHERE agent_id=? ORDER BY created_at DESC`，逐行 `_row_to_memory` 解密 |
| `memories.temperature` 列已存在 | storage.py:603（REAL DEFAULT 100.0） |
| 温度索引已存在 | storage.py:632 `idx_mem_temperature` |
| SQL 直查温度 Top-N 已是既有模式 | manager.py:3101 `get_top_memories_by_temperature`；manager.py:788 召回降级路径 `ORDER BY temperature DESC LIMIT ?` |
| MoE 向量索引是 **DB 驱动**，不依赖内存快照 | mem_core `init_moe_router` 经 `_PersistDbStore` 查库建索引 → 温度分层不影响向量召回覆盖面 |
| 温度是活信号 | 访问 +10（manager.py:849，DB 与内存同步）；睡眠/衰减引擎按 last_accessed 周期衰减 |
| 共享资源构造期均有锁且幂等 | 编码器 `initialize_sync` 自锁+短路；provider_manager/LLMRouter DCL；import 模块锁 |
| sqlite 每 agent 独立文件且 WAL | v3 布局 `data/agent/<bucket>/<id>/memory/` |

## 3. 批一（P0）：agent 并行装载

### A1 worker 数解析
- `_agent_load_workers() -> int`：env `NEUROVA_AGENT_LOAD_WORKERS`，默认 4，
  钳制 [1,16]；非法值回退 4；`"1"` = 串行（A/B 对照与逃生口）。纯函数。

### A2 单 agent 工作单元
- `_construct_saved_agent(agent_id) -> tuple[str, Agent|None]`：从
  `_load_saved_agents` 抽出逐 agent 主体（读配置 → 缺失但有数据则自动重建配置 →
  `_agent_config_from_saved` → `Agent(config)`）。返回 None = 无可装载（保持现
  "静默跳过"语义）；异常就地 `logger.warning(..., exc_info=True)` 并返回 None
  （失败隔离，与现逐个 try/except 等价）。

### A3 并行化与确定性注册
- `ThreadPoolExecutor(max_workers=min(w, len(ids)), thread_name_prefix="agent-load")`，
  `as_completed` 收集；**按发现顺序**回插 `app_state.add_agent`（注册顺序稳定，
  UI/测试不扰动）。
- 汇总日志：`Loaded N saved agents in X.XXs (workers=W, failures=F)`。
- `workers==1` 或仅 1 个 agent 时走原串行路径。
- 配置自动重建在 worker 内并行执行（写的是各自 agent 目录，无竞争）。

### 测试与验收（先红后绿）
- 红灯已备：`tests/unit/api/test_agent_load_parallel.py`——4×0.4s 桩 Agent：
  串行 ≥1.6s（红）/ 并行 <1.2s（绿）+ 多线程参与断言；坏配置 agent 不拖累其余；
  env 解析四例。当前实测红（`_agent_load_workers` 不存在，收集期 ImportError）。
- 回归：api 套件净 HEAD 工作树 A/B，零新增失败。
- live-verify：9527 重启计时，装载段 9s → 预期 ≤4s。

### 回退
env 置 `NEUROVA_AGENT_LOAD_WORKERS=1` 即回串行，不改代码。

## 4. 批二（P1）：记忆温度分层装载（C1 冷层后台补载）

### 4.0 前置卡（D5，2026-11-24 排查新增）：记忆温度语义修复

**排查结论（kai 真库实测 + 代码链）**：温度对绝大多数记忆永久失效——kai 1658 条中
1531 条恒为 100°、1222 条从未被访问（access_count=0）。根因是三件套互相抵消：

1. 记忆出生温度 = 100（storage.py:603 `DEFAULT 100.0`）；
2. 衰减引擎对 ≥80° 硬门直接跳过（temperature.py:280，"高温记忆视为固化"）；
3. 全系统不存在任何把记忆从 ≥80 降到 <80 的路径（访问只 +10 且封顶 100，合并取平均）。

衰减触发面本身在正常跑（每轮聊天后管线 post_chat_pipeline.py:905 →
agent_core.py:1828 `run_decay_cycle`，5 分钟节流 + 单轮 500 条游标；关停整理
agent_shutdown.py:83；管理端点 crud.py:305），但全部被第 2 条挡住——"跑了也白跑"。
次要缺陷：关停整理调 `on_decay` 时把 `created_at` 误当 `last_accessed` 传参
（sleep.py:472），即使降到 <80，闲置天数也按创建时间算而非真实最后访问时间。

**修复内容（五件，同批落地）**：

- **D5-R1** 出生温度 100 → 60（列默认值与模型侧默认单源修改；此后新记忆一律 60° 生效）。
- **D5-R2** 命中回温改比例式 `T += (100 − T) × k`，k 默认 0.25（env
  `NEUROVA_MEMORY_HIT_GAIN`）；模拟召回 k=0.1。判据：20° 首命中 → 40；95° 命中 →
  96.25；连续命中序列单调、有界、不越 100；高频/每周/每月/从不访问的记忆平衡点自然分层。
- **D5-R3 冻结门 80 → 95（用户拍板 2026-11-24）**：保留"高温视为固化"机制，阈值从
  80 提到 95（建议 env `NEUROVA_MEMORY_FREEZE_TEMP`，默认 95）。配合出生 60° +
  比例回温 k=0.25：连续命中约 8 次才跨 95 固化——固化成为"持续使用挣来的"状态，
  而非出生即得；80~95 区间保留幂律慢衰减（饱和因子下高温衰减本就偏快），温度在
  热区内部仍有区分度；crystallized 行任意温度豁免衰减的既有规则不变。
- **D5-R4** sleep.py 传参修正：`last_accessed` 传真实 `last_accessed_at`，NULL 回退
  `created_at`。
- **D5-R5 同轮去重（用户拍板）**：同一轮会话内，同一条记忆无论被多少个通道/多少次命中，
  只记**一次**命中——轮级聚合，轮末统一 `creditRecallHits` 一次；跨轮各记各的。
- **D5-R6 存量全量初始化 60°（用户拍板 2026-11-24）**：所有 agent 的全部记忆行温度
  一次性重置为 60（含 crystallized/forgotten 行，按"全部"字面执行）。实施形态：离线
  一次性脚本（后端停止后执行，同 v3 切换纪律——运行中后端持 sqlite 句柄且内存快照
  会失真），只 UPDATE temperature 一列，`updated_at`/`last_accessed_at`/`access_count`
  一概不动；--dry-run 支持。重置后温度同票由 B1 复合排序（last_accessed_at/access_count）
  兜底区分度，随使用与衰减重新拉开梯度。

**红绿判据**：六件各一条单测（R6 另验：重置后全表 temperature=60 且其余列逐列不变、
dry-run 零改动）；另做 kai 真库抽样回放——修后跑一轮衰减，非结晶行必须开始下降、
60° 新记忆闲置 30 天落到约 30~40 区间、同轮重复命中只 +1 次。

**排序关系**：本卡落地前温度无区分度，批二热层 `ORDER BY temperature DESC` 会从
100° 平票里随机切——**批二排在 D5 之后实施**。

### B1 热层同步装载
- `_load` 拆为 `_load_rows(where_sql, params)` 复用主体；热层：
  `SELECT * FROM memories WHERE agent_id=? AND lifecycle_stage != 'forgotten'
  ORDER BY temperature DESC LIMIT ?`（排除 forgotten：它们本就不进召回，不占
  热层名额；冷层补载仍会含它们，管理面最终一致）。
- 热层 N：env `NEUROVA_MEMORY_HOT_LIMIT`，默认 500，**0 = 关闭分层**（全量同步，
  行为同今日，兼容开关）。N 按每 agent 生效。排序用复合键
  `temperature DESC, last_accessed_at DESC NULLS LAST, access_count DESC`——
  同温平票时按新近度/访问次数决出，避免任意切分。
- 行数 ≤ N 时退化为全量同步（无后台线程，行为同今日）。
- 可选优化：补复合索引 `idx_mem_agent_temperature(agent_id, temperature)`。

### B2 冷层后台补载
- `_load` 返回后起 daemon 线程：按 `ORDER BY temperature ASC` 分批（500/批）
  扫库，**跳过已在内存的 id**（merge 幂等），逐批 `_row_to_memory` +
  `_merge_loaded_memory`，直至补齐；置 `_cold_load_done: threading.Event` 与
  `_cold_load_ok: bool`。
- **sqlite 线程约束**：冷层线程不得复用构造线程的常驻连接
  （`check_same_thread` 默认拒跨线程），每批借 `get_short_connection` 用完即还
  （ADR 0014 纪律）。
- 失败处理：ERROR 日志点名 + 一次退避重试；仍失败则 stats 标记 `cold_ok=False`，
  管理员可经既有 `reload_memories()` 手动补齐——不许静默残留半量快照（教义第 2 条）。

### B3 锁与一致性
- 实现期审计 `_memories` 既有并发防护（uvicorn 线程池下写路径本就并发）；
  冷层 merge 复用同一把锁；无锁遍历的读侧改为浅拷贝快照迭代（代价 O(N) 浅拷贝，
  可接受则做）。

### B4 可观测
- manager stats 增 `memory_load: {hot, cold, cold_done, cold_ok, hot_limit}`；
- 启动日志：`Memory snapshot: hot=X cold=Y (background Z.ZZs)`。

### 测试与验收（先红后绿）
- 红灯 1 热层判定：seed 800 条已知温度分布，`NEUROVA_MEMORY_HOT_LIMIT=500` →
  同步装载后 `len(_memories)==500` 且恰为温度 Top-500。
- 红灯 2 冷层补齐：等 `cold_load_done` 后 `len==800`；补载期间 recall 不抛异常。
- 红灯 3 关闭分层：`HOT_LIMIT=0` → 全量同步、无后台线程（旧行为锁定）。
- 回归：tests/test_memory/ + cognitive_layers 净 HEAD A/B 零新增失败。
- live-verify：kai（1658 条）重启装载段显著缩短；新建记忆 → 重启 → 立即召回
  成功（新记忆 temperature=100 必在热层）；将某记忆温度调低 → 重启 → 立即召回
  验证冷层窗口行为，补载完成后再次召回成功。

## 5. 风险登记

| 风险 | 对策 |
|------|------|
| R1 sqlite check_same_thread 拒跨线程 | 冷层每批借短连接（B2） |
| R2 `_memories` 并发变异 | 复用/补齐写锁（B3），冷层 merge 持锁 |
| R3 冷层窗口内多通道召回暂漏冷记忆 | 窗口仅数秒；MoE 向量召回 DB 驱动仍覆盖；文档写明 |
| R4 管理页窗口期只见热层 | 数秒后一致；若不可接受 → D3 拍板改阻塞就绪 |
| R5 sleep_writeback 若只扫内存态 | 实现期核验；冷层在盘上由衰减周期正常处理 |
| R6 并行构造踩到未核出的共享单例 | worker 数=1 逃生口 + A/B 对照 |

## 6. 待拍板

- D1 热层 N 默认值：建议 500（约覆盖当前最大 agent 的三成，观测后调）。
- D2 env 名确认：`NEUROVA_AGENT_LOAD_WORKERS` / `NEUROVA_MEMORY_HOT_LIMIT`。
- D3 管理页"数秒后一致"窗口是否可接受：建议可接受。
- D4 C2（召回时按温度下探 DB）本批不做：先 C1 验证，留作冷层失败的加固选项。
- D5 温度语义修复（2026-11-24 排查后新增，见 §4.0）：六件修复已按用户意见纳入
  （同轮命中去重、存量全量初始化 60°、冻结门 80→95 均已拍板）；k=0.25 / 出生 60°
  为建议默认值，随批实施、env 可后续调整。

## 7. 提交拆分

1. `perf(agents): 启动期 agent 并行装载`——app.py + test_agent_load_parallel.py。
2. `perf(memory): 记忆温度分层装载——热层同步+冷层后台补载`——manager.py/storage.py + 新测试。
3. `docs: 启动规模化方案入库`——本文件 + 0-index 登记。

每笔附红灯/绿灯实测输出与净 LOC 去向；批间可独立回退（env 开关）。

## 8. 执行记录

（待实施后回填：逐卡 commit、实测数据、偏离点。）
