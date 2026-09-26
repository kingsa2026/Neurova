# B6 立项：清死线与谎报面（Issue #90 · 审计 §10 B6）

- 日期：2026-09-22
- 状态：**已实施**（B6-1…B6-11 全部交付：B6-10 批次 A–F 见台账 §17 / §31，B6-11 见 §3.1）
- 实施记录：`docs/05-reports/上下文三链路修复台账_2026-09-21.md` §16
- 上游：`docs/05-reports/上下文三链路审计_2026-09-21.md` §4（P2-1…P2-10）、§5（死线登记）、§10 B6 行、决策项 **D5**
- 前置批次：B1–B5 已交付；B5 收口与两条尾巴见 `docs/05-reports/上下文三链路修复台账_2026-09-21.md` §15
- 工单拆分：[`2026-09-22-b6-deadline-and-fake-surfaces/tickets/000-索引.md`](2026-09-22-b6-deadline-and-fake-surfaces/tickets/000-索引.md)

---

## 1. 为什么必须独立立项

审计 §10 对 B6 的批注是「面广且多为"删或接线"的独立判定，**每个孤儿需单独论证可达性**」。
这不是一句谨慎话，而是本批的根本约束：

- 一条死线只是"没人调用"，但如果它**同时是某个谎报面的载体**（例如 `token-budget`
  GET/PUT 挂在从不存在的属性上），那么"接线"与"删除"的代价完全不同；
- 而"删除"也不能凭 grep 命中数下刀：测试、脚本、文档引用都不算生产调用方，
  但**测试本身可能就是该契约的唯一守卫**——删代码前必须先把契约搬到真面上去。

所以 B6 的每张工单都必须先回答两个问题：**这条面今天可达吗？它被删掉以后，
它原本承诺的东西由谁承担？** 两个问题都答不出，就不许动。

## 2. main 现状逐条复核（2026-09-22 实测，不是照抄审计）

审计写于 2026-09-21。B4/B5 两批改过上下文装配链与持久层，因此本节**逐条重测**，
给出「仍成立 / 已变化」的判定与实测命令。全部读数取自 `main`（`00d60679`）。

### 2.1 谎报面（P2-1…P2-10）

| 编号 | 复核结论 | 实测证据（本仓） |
|---|---|---|
| P2-1 | **仍成立** | `python3 -c "from neurova.context_pool import get_context_pool"` → `ImportError: cannot import name 'get_context_pool' from 'neurova.context_pool'`；`builtin._get_context_pool()` → `None`（`except ImportError` 静默，只打 DEBUG「ContextPool 未可用」）。故 `exec_context` 在无注入时恒 `failed` |
| P2-2 | **仍成立** | `git grep -n "\.unified_injector =" -- neurova/` → **0 命中**。而 `api/endpoints/context.py:263/522/554` 三处 `hasattr(agent, "unified_injector")` 恒假 → GET `/token-budget` 恒返回硬编码 `16000/0/16000`，PUT 恒返回成功且零效果 |
| P2-3 | **仍成立** | `api/endpoints/context.py:114` `return ContextPool(user_id=..., agent_id=..., session_id=...)`——每次请求新建池，与 Agent 池完全隔离（写入即丢） |
| P2-4 | **仍成立** | `orchestrator.py:654` 视图重建注释自陈「只保留 role+content」；`_tool_placeholder`（`:1075-1085`）依赖 `tool_call_id` 才能产出硬地址指针，字段被剥后指针降级为空 |
| P2-5 | **仍成立** | `orchestrator.py:157-160` 台账初始化失败只 `logger.warning`（回退内存台账，无重试）；摘要器失败路径同理（`:165-170`），此后 `pool._summarizer=None` |
| P2-6 | **仍成立（形态已变）** | 就地改写点 `orchestrator.py:746` 仍在（`drawer.max_tokens = self._retrievalBudget(...)`）。B5 已把**额度公式**收成单源，但「构造期值每轮被覆盖」这一形态未变 |
| P2-7 | **仍成立** | 分支门 `orchestrator.py:99/104/140`（`use_pool` 默认 `True`）由 `agent_core.py:553` 传入 `c.enable_context_pool`（默认 `True`）→ 非 pool 分支默认不可达；`injector.py:163` 实例化 `SmartContextCompressor` 后 `self._compressor` 全仓**无读取点**（仅 `:167/169` 赋 `None`） |
| P2-9 | **仍成立** | `orchestrator.py:539` 选中反思 → `:551` `await mark_injected_logs(...)`，即「选中即 applied」；此时尚未经过池调取的相关性门槛，效力裁决输入含幻影注入 |
| P2-10 | **仍未复核** | 审计列的是 `recovery.compact_messages_for_overflow` 的条数折叠与 `ensure_future` 发后不管。本立项不把它并入 B6（它与「删死线/清谎报」不同源），登记为**另票议题**，见 §5 |

### 2.2 死线登记（审计 §5）逐条重测

审计 §5 列 13 项。用「定义处以外的引用」为判据重测（`git grep` 全仓，排除 `tests/` 与
`__pycache__`），结论如下：

| 项 | 现状 | 说明 |
|---|---|---|
| `EnhancedContextBuilder` / `enhanced_context_builder.py` | ✅ 已删 | 文件不存在、`git grep` 全仓 0 命中；但 `docs/01-architecture/COMPLETE_MODULES.md` **两处**（`:476`、`:708`）仍列着它 → **新留悬空引用** |
| `ContextFacade` / `context_facade.py` | 仍需处置 | 生产侧只有自身文件内的定义与单例工厂；`orchestrator.py:1842` 仅是注释提及。零生产消费方 |
| `ContextPoolRegistry` / `context_pool_registry.py` | 仍需处置 | 全仓仅本文件内定义；它是 `pool.query` 的唯一调用方（`:103`、`:131`）→ **池的 session 分区读路径在对话主链从未被走** |
| `ContextCompressor`（`context/compressor.py`） | 仍需处置 | 仅被 `context_pool.py:146`（`self._compressor = ContextCompressor(max_tokens)`）实例化；`compress_context` 消费者为零 |
| `SmartContextCompressor`（`context_compressor.py`） | 仍需处置 | 仅 `injector.py:163` 实例化即弃（`_compressor` 无读取点）；另有 `get_context_compressor()` 工厂零调用 |
| 池方法 `mark_turn_seen` | 仍零调用 | 全仓仅定义行 |
| 池方法 `select_fold_candidates` | 仍零调用 | 全仓仅定义行 |
| 池方法 `convert_context_for_model` | 仍零调用 | 全仓仅定义行 |
| 池方法 `merge_with` | 仍零调用 | 全仓仅定义行（同名 `merge_with_user_emotion` 是另一件事，不混算） |
| 池方法 `cleanup_expired` | 仍零调用 | 定义在 `context_pool.py:1057`；同名命中全为其他模块的 `_cleanup_expired*`，不混算 |
| 池方法 `dedup` | **已变化** | `context_pool.py:1201/1217` 走 `self._deduplicator.dedup(...)`——**是另一份实现**（`context/dedup.py`），池自身的方法仍零调用。需按「第二份定义」口径收口，不是简单删除 |
| 池方法 `clear` | 需收窄判据 | `clear` 是通用名（全仓 300+ 命中），必须按「`ContextPool.clear` 的调用点」逐点判，不能按名字计数 |
| 池方法 `compress_context`（`context_pool.py:1173`） | 仍零调用 | 与 `ContextCompressor` 同源，一并处置 |
| 编排器 `set_session_id` | 仍零调用 | `orchestrator.py:197` 定义；`:227` 注释自陈「旧实现的唯一出口是已退役的 `set_session_id` 裁剪」 |
| 编排器 `build_system_prompt` | 需分域判 | `orchestrator.build_system_prompt` 被 `context_facade` 两处调用（`:104/156`），而 `context_facade` 自身零生产消费方 → **两级同时死**，只删一级无效 |
| 只写不读 `cache["covered"]` | 仍成立 | `orchestrator.py:232` 初始化、`:1388`/`:1470` 写入；无任何读取点。注：审计把它写成 `[:1170/1211/1268/1295]`，B4/B5 改动后行号已漂移，故按符号检索 |
| 只写不读 `_last_archived_window_hashes` | 仍成立 | `:128` 初始化、`:1069` 赋值；无读取点。审计原文称它是「折叠前必须已归档」零丢失判据的唯一物证——**留下却没人校验** |
| `semantic_drawer.preload_vector_store` | 仍零调用 | 全仓仅定义行 |
| `ContextPoolUtils` 两份同名实现 | 需复核 | 审计称 `context/utils.py` 与 `token_estimator.py` 两份同名；本票实施前须以 AST 复核，不照抄 |

### 2.3 D5（反思记账语义）

D5 的裁决是「反思改'进视图才记账'并配降档兜底」。main 现状：`mark_injected_logs` 在
**选中**时即调用（§2.1 P2-9），账目与视图无因果。该项涉及**效力裁决输入**，
改动会波及 RSI 侧的裁决数据，故单独成票、单独取证。

**已交付（2026-09-25）**：记账收在**装配出口** `_finishContext`（三条装配分支共用，
逐分支各写判定就是三份判据）；"进视图"的客观判据是**视图注入面里有没有这条的文本**
（新模块 `context/reflection_view.py` 经 `parse_envelope` 解析信封块）——"被 draw
取出"不算，因为之后还有一步 `compress_envelope` 确定性淘汰。降档兜底走**既有**
`register_negative_feedback`（只降不删，跌破 0.3 转 rejected），连续
`VIEW_MISS_LIMIT = 3` 轮未进视图触发。读数
`get_context_health()["reflection_injection"]`（生产读者 = /metrics 既有抓取面）。
详见[台账 §28](../05-reports/上下文三链路修复台账_2026-09-21.md)。

## 3. 工单拆分（垂直切片）

每张工单独立成立、独立验证。判据口径一律「先把契约搬到真面上，再删旧面」——
不许先删再修（那会留下无守卫的窗口）。

| # | 标题 | Blocked by | 完成后可验证 |
|---|---|---|---|
| B6-1 | 死线分域判据与台账（先立判据，不动代码） | 无 | 每项给出「可达 / 不可达 / 第二份实现」三态与判据命令，可复算 |
| B6-2 | `token-budget` GET/PUT 接真读写对象 | B6-1 | 读数不再是硬编码；PUT 后 GET 反映新值；属性不存在时点名而非静默 |
| B6-3 | 池作用域收口：`get_context_pool` 符号缺失的根因处置 | B6-1 | `exec_context` 在无注入时不再静默 `failed`；或该节点按显式契约退役 |
| B6-4 | `/context/build` 池身份收口（写入即丢） | B6-1、B6-3 | 两次端点取到同一池；写入后可见 |
| B6-5 | 视图归一化保留工具寻址字段（P2-4 的根因侧） | B6-1 | `_tool_placeholder` 的硬地址指针真能产出；折叠防召回对工具归档同样生效 |
| B6-6 | 向量层：批量编码入口 + tfidf 路径进缓存（B5 尾巴一） | B6-1 | `UnifiedVectorStore` 有批量入口；同批文本跨轮真编码次数下降（取证前后读数） |
| B6-7 | `created_at` 读侧排序/打分策略（B5 尾巴三） | B6-1 | 策略有单源落点；召回顺序/打分随归档时刻可解释且可测 |
| B6-8 | P2-5 静默降级收敛（两处能力永久关闭不再重试） | B6-1 | 降级有可观测读数与重试/恢复路径，不以 warning 代替 |
| B6-9 | P2-6 抽屉额度形态收口 | B6-1 | 构造期值与每轮值的关系有单一解释，不再"每轮就地改写" |
| B6-10 | 死线处置执行（删或接线，逐项论证） | B6-1…B6-5 | 审计 §5 每一项在三态台账上有终局；悬空文档引用归零 |
| B6-11 | D5 反思记账改「进视图才记账」+ 降档兜底 | B6-1 | 未进视图的反思不再计入 applied；裁决输入不含幻影注入 |

## 3.1 实施进度（2026-09-23）

| # | 状态 | 交付要点 |
|---|---|---|
| B6-1 | ✅ | 死线分域判据与台账（判据类机器算，台账照抄不一致即红） |
| B6-2 | ✅ | `/token-budget` 接真预算对象，取不到即 503 点名 |
| B6-3 | ✅ | 补 `get_context_pool` 真面 + `ContextPoolRegistry.adopt/get_pool` |
| B6-4 | ✅ | `/context/build` 与编排器取同一个池（构造期就地登记） |
| B6-5 | ✅ | 视图归一保留工具寻址字段（归一入口收成一处） |
| B6-6 | ✅ | 向量层批量入口（`encode` 由它派生）+ tfidf 稳定形态进缓存 |
| B6-7 | ✅ | 归档时刻是读侧排序/打分的唯一时间事实源，第二份定义删净 |
| B6-8 | ✅ | 降级读数 `attempts/enabled/last_error` + 每轮重试恢复 |
| B6-9 | ✅ | 每轮额度经入参透传，构造期字段不再被就地改写；硬顶口径单源 |
| B6-10 | ✅ | 处置轴判据 + 六项终局 + 折叠零丢失判据接线（`fold_integrity`）+ 压缩/去重面收口 + TTL 回收接线 + 门面层与池注册表多池机制退场（见台账 §17 / §31） |
| B6-11 | ✅ | D5 反思记账改「进视图才记账」+ 未进视图降档兜底（判据 `tests/unit/context/test_reflection_view_accounting_b6_11.py`） |

## 4. 非目标

- 不改 `keep_count` / `keep_days` 等容量默认值（属 B5 容量议题，已收口）。
- 不动 P2-10（`recovery.compact_messages_for_overflow`）——它与「删死线」不同源，
  见 §5。
- 不做"顺手重构"：每张工单只碰它点名的那个断链。

## 5. 未决与登记（不静默遗留）

- **U1**：`cleanup_expired` / `clear` 这类通用名方法的"零调用"判定，是按名字计数还是按
  AST 解析出「目标类型的方法调用」？后者成本高但不会误判。**建议 AST**，理由是
  按名字计数已在本批实测出假阴性/假阳性两面（`dedup`、`clear` 即例）。
- **U2**：`ContextPoolUtils` 两份同名实现是否真存在——实施前以 AST 复核，不照抄审计。
- **P2-10 另票**：`recovery.compact_messages_for_overflow` 的条数折叠 + `ensure_future`
  发后不管，登记为独立议题（涉及恢复路径，与 B6 无共享判据）。
- **本批未走查**：审计 §9「未证实事项」中的部分项仍未取证，本立项不把它们当结论。
