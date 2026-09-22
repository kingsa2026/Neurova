# 工具↔经验↔再调用三环路修复 · 规格说明书

- 日期：2026-09-21
- 来源：Issue #80（用户派发 11 张工单：001–011）
- 范围：`neurova/agent/`、`neurova/tool_executor.py`、`neurova/skills/`、
  `neurova/evolution/`、`neurova/cognitive_layers/memory_layer/`
- 票集与依赖：[`docs/specs/2026-09-21-tool-experience-loop/tickets/`](./2026-09-21-tool-experience-loop/tickets/000-索引.md)

---

## 1. 问题陈述

「工具调用 → 经验记忆 → 再次调用」这条环路在**三处同时断开**，且断裂点互相咬合：

1. **不产票**：写票口唯一在 `tool_executor.py` 的 finally，原生 function-calling 链
   （`agent/loops/base.py` 的两条出口）不经它 ⇒ 原生链执行的工具在服务端证据账本上
   查无票据，`resolve_ticket_evidence` 恒 `absent`。
2. **形状分叉**：`chat_pipeline._call_loop_stream` 把 `{type, data}` 包装事件与原生的
   扁平记录写进**同一个**取证列表 ⇒ `turn_state.resolve_tool_outcome` 读不到 `success`
   （成功轮被判 False）、`post_chat_pipeline` 读出 `unknown` 工具名（真实库已有
   `skill_name='unknown,weather'` 的行）。
3. **三态折叠**：`success` 由不同位置的 `bool()` / truthiness 各自折叠 ⇒「未测量」显示成
   「失败」、「被策略拦截」计成「工具故障」，且拦截会永久粘在结构身份上。
4. **再调用不可用**：肌肉记忆的中文指纹用 `\w\s` + `split()`，中文整句成**一个** token，
   「指纹相等」≈「整串相等」，近似问法恒不命中；且写侧存的是降级后的 `{"_raw": …}`，
   命中后必然被参数校验拒 ⇒ 每次自动执行都往证据库续一张永久失败票。

## 2. 方案概述

按票据依赖顺序分两批落地，**先立可测量的探针，再改生产代码**：

- **第一批（探针与形状）** 001 三链路探针基座 → 002 工具记录形状单源；
- **第二批（收编与三态）** 003 原生链收编进执行咽喉 → 004 成败三态收口；
- **并行支线** 005 其余入口迁移 / 006 视图键域收口 / 007 肌肉记忆止血 /
  009 经验度量落库 / 010 采集可观测；
- **终态** 008 肌肉记忆指纹与参数复用（解 007 的临时收紧）。

三条贯穿原则：
1. **成败判据单源**：`tool_executor._result_is_success` 是唯一内容判据；
2. **形状单源**：取证源只有扁平记录一种形状，传输壳（SSE/蜂群流）不进取证源；
3. **三态不许折叠**：`True` / `False` / `None`（未测量）各归各位，落库 `NULL`。

## 3. 已定决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 原生链执行一律经 `ToolExecutor` 咽喉 | 同一次执行一次收齐票据 / `on_tool_executed` / 治理 / hooks / 超时 |
| D2 | 取证源只收扁平记录 | 包装事件是传输壳，语义与扁平记录重复且缺关键字段 |
| D3 | `success` 列放开为可空 | 「没测到」与「失败」在检索降权、指标、展示三面必须分得开 |
| D4 | 肌肉记忆**彻底修**（不砍臂） | 先止血（007）再换指纹与写侧参数（008） |

## 4. 测试决策

- 探针必须经**生产构造点**驱动（真 `Agent` / 真 `ToolExecutor` / 真 `ChatPipeline`），
  替身只放在模型边界（`ScriptedModel` 只实现 `chat_stream` / `chat`）；
- 反向锁各一条：证明拦阻者确实是根因，不是探针写错；
- 写验证一律落 `tmp` 库（`NEUROVA_EKB_DB` + `SkillService` 目录隔离），
  **严禁**对 `data/` 生产库写验证。

## 5. 明确不做（登记）

- **D5 失败粘性解冻**（绑工具契约版本）：依赖本批落地后才有新数据校准，另批；
- `injector.py` 的 `context`/`content` 键错位：只在非池路径可达，本批不定级；
- `estimate_confidence` 序列分虚高、`voice_memory_bridge` 硬编码 success、
  `neurflow/builtin.py` 吃模型自报：前两批已登记项，本批不重复计入。

## 6. 执行结果（逐票）

见各票「执行结果」节与 PR 描述。关键读数：

- 001 探针三条：改前全红（形状 2 条违规 / 票据 `absent` / EKB `unknown,get_datetime`），
  003 后全绿；
- 003 起原生链执行产票：`lookup == "evidenced"`；
- 006 停用生效判据改为「发给 LLM 的工具清单少一项」；
- 008 换实体近似句 confidence 由 0.400 升到 0.85（门槛 0.8 可达）。

## 7. 第二轮补做（006 / 005 残留 + 011）

前一轮只完成主干，三条收口各有未尽的断点，第二轮逐条补齐（明细见
[`000-索引.md`](./2026-09-21-tool-experience-loop/tickets/000-索引.md)）：

- **006**：`VisibleSkill.enabled` 的三条判停落点此前只有 manifest `enabled` 一条真生效；
  补 registry 运行时 `status` 与生命周期 `usage.state=archived`，三闸同读一份 entry。
  同名冲突计数改为可重跑（`scripts/diagnostics/skill_name_collisions.py`）。
- **005**：`neurflow` 两处 `get_tool_engine` 是**不存在的导入**（静默零同步）；
  `/tool-layers/tools/execute` 把 `ToolEngine` 当入口用（绕过咽喉）。两处各自改道 + 守卫。
- **011**：整票交付——回滚判据单源（`should_rollback`）、留痕落 `revisions`、
  治理面端点（未装配 503 / 空归档 409）、`AgentSkillPage.vue` 归档与回滚入口、
  11 份 locale。

live-verify（真 Agent + 真 ToolExecutor + 真 SkillService）：端点经咽喉执行产票、
停用/归档后工具面各少一项、重建→归档→回滚留痕带操作者、`improvements` 键未复活、
空归档回滚返回 False。


---

## 8. 第三轮补做：9 条尾巴（逐条先红后绿）

第二轮把主干补齐后仍有 9 处未兑现的尾巴，逐条按「先红后绿」修掉。每条先落一条
必红用例并实证它红，再改实现转绿；红→绿实测输出见 PR 描述与各测试文件的模块说明。

### 8.1 003 残留：`ToolRouter` 复判（假成功票的第二处生产点）

票面点名「`tool_router.py` 的 `ToolResult(success=True, result={...})` **必须复判**」。
前一轮只把咽喉内层改对了，路由器仍对任何不抛异常的结果报成功，于是同一次失败在两条
消费链上分叉：经咽喉的调用判失败（正确），经 `ToolSequenceSkill.execute` 的自动技能
恒真 ⇒ 自动技能产出假成功票（审计 L-02）。

- 收口：`ToolRouter` 的成败判据改为委托咽喉的 `ToolExecutor._result_is_success`
  （**单源**，路由器内不写第二份内容判据），失败时把 `error` 一并带出。
- 红灯：`tests/unit/tools/test_tool_router_success_verdict.py` 改前 3 failed
  （error 载荷判成功 / `route()` 不抛 / 自动技能产成功票），改后 5 passed。

### 8.2 004 残留：三态在四个面各自可分辨

票面要求「三种输入在**四个面**（EKB 行、权重表、结晶器、API 展示）各自独立可分辨；
用一张对照表贴进票末，缺一格不算完」，并要求「把 `success=NULL` 手工写成 0 ⇒
至少一条用例必须红」。前一轮只有 EKB 列与权重表两格，结晶器面与 API 展示面零用例。

| 输入 | EKB `success` | 权重表 | 结晶器 | API `outcome` |
|---|---|---|---|---|
| 真成功 | `1` | `success_count+1` | 进分子分母 | `success` |
| 真失败 | `0` | `failure_count+1` | 进分子分母 | `failure` |
| 无票无回执 | `NULL` | 不投票 | 不进分子分母 | `unevidenced` |

- 落点：`tests/unit/evolution/experience/test_three_state_four_faces.py`（8 条）。
  写入走 `ExperienceKnowledgeBase.add_experience_record`，读数走 `/ranking` 契约的
  唯一产出点 `_outcome_word`；反向锁把 `NULL` 手工 UPDATE 成 `0` 后断言 API 面
  必然转成 `failure`（证明断言真的在区分，而不是复述一遍 NULL）。

### 8.3 009 残留：结构身份 = 工具序列 + 参数

票面定义「结构身份（工具序列 + **参数形状指纹**）」。前一轮把指纹接到了 EKB
`context`，但**同一份"结构"算法有两个实现**：`fingerprint`（结构 + 意图）与
`structure_key`（结构）各自复写归一与序列化。

- 收口：抽 `structural_identity()`（归一）+ `_hash_identity()`（序列化哈希），
  两个键都经它们出哈希，差异只在有没有把意图并进载荷。AST 守卫钉住单源。
- 覆盖：`tests/unit/evolution/experience/test_structure_identity_param_shape.py`（9 条），
  含端到端负向（换参数的两次调用必须落两个 `structure_key`）与隐私锁（不落明文）。
- 实测澄清：复核发现 `structure_key` 在 `1e1341b0` 上**已**吃参数（`{"city":"x"}` 与
  `{"city":"y"}` 本就不同哈希），上一轮"参数塌成同一身份"的读数有误。本条的净改动是
  **消除第二份实现**，不是"补上参数"——报告原文与订正一并留在 PR 描述里。

### 8.4 007 的连带代价（票面明令「必须写进票末」）

`tool_memory.muscle_memory_threshold` 是 ADR 0016 判死方向后 RSI 参数寻优臂唯一还有
位移的旋钮（起点 0.85 / 目标 0.8）。007 收紧裁定档位会让那条臂**近乎空转**：

- 这是**有意**的临时状态，由 008 终态解；
- **不得**为"让 RSI 有活干"而回退 007 的收紧；
- 008 必须重验 ADR 0016 的梯度账，不得默认它仍成立。

守卫：`tests/unit/evolution/experience/test_rsi_idle_cost_recorded.py`。

### 8.5 008 三项附带要求

- **身份显式化**：`MuscleMemory.__init__` 原用 `**kwargs` 静默吞掉 `agent_id`
  （实测 `hasattr(m, "_agent_id") == False`）⇒ 收口为显式参数并落成可读属性
  `memory.agent_id`，未知 kwarg 直接 `TypeError`，不再静默吞。
- **现网脏条目作废重攒**：`agent_workspaces/kai/.../muscle_l2.json` 的 2 条 `_raw`
  条目已归档重攒。**归档落点同时修正**：原实现把副本写在源文件旁边，而
  `agent_workspaces/` 被 `.gitignore` 整目录忽略——一次 `git clean -xfd` 或换机器，
  "可回退"就没了。现落 `docs/05-reports/muscle-memory-ledger/`（仓内、随提交入库）。
- **阈值可达性重算 + ADR 0016 梯度账重验**：新增可复算入口
  `scripts/diagnostics/muscle_memory_threshold_attainability.py`。实测 8 条相关配对里，
  阈值 0.85 与 0.8 的裁定**完全相同**，落在开区间 `(0.8, 0.85)` 的真输入为 **0 条**。
  ⇒ "唯一还有真实梯度的参数"须订正为"**可动参数一颗、梯度带为空**"，ADR 0016 已回写。

### 8.6 010 / 006 残留：只写不读的计数接线

`missing_context_count()` 在 `neurova/` 内**零生产消费方**，`_name_collision_count`
只见于日志——"写出了读数、没人读"正是协作红线点名的断点形态。

- 收口：`core/metrics.py` 新增两个 gauge（`neurova_ticket_context_missing` /
  `neurova_skill_name_collisions`）与抓取时快照 `observe_chain_integrity()`，
  接进既有 `/metrics` 端点（**不新开端点**）。
- 数值取自计数器本体（单一事实源）；取注册表读数经
  `skill_system.registered_collision_count()` 只读口，**抓指标绝不懒建注册表**。
- 守卫：`tests/unit/core/test_chain_integrity_observability.py`（5 条）。

### 8.7 001 残留：只读取证脚本落库

票面点名的 `scripts/diagnostics/_tool_experience_loop_probe.py` 已落库：一条命令输出
三读数 + `ticket_lookup` / `ticket_reason` 的 JSON，库落临时目录（**不指向 `data/`**），
模型边界只放一个回预置 tool_call 的替身，不触网。守卫
`tests/unit/agent/test_tool_experience_loop_offline_probe.py` 钉住"可独立重跑"与
"绝不打开生产库"两条。

### 8.8 005 残留：迁移清单逐条有结论

票面要求「清单逐条有结论：**迁移 / 不迁移（写明风险与不修理由，回审计文档 §2 新开登记项）**，
无一条含糊」。守卫
`tests/unit/skills/test_skill_entry_choke_migration.py::TestMigratedEntriesCallTheChoke`
原来用一个 `allowed` 文件集整体放行，等于"清单上其余入口一律不写理由"。现改为
**行号级清单**：每个保留点必须携带理由，新增的未登记命中点直接判红
（人类可读副本见 [`入口迁移台账.md`](./2026-09-21-tool-experience-loop/入口迁移台账.md)）。

### 8.9 杂项

- `scripts/ci/protected_tests.txt` 里 `test_rsi_rollback_evidence.py` 重复登记两行 ⇒ 去重。
- 两个诊断脚本（`skill_name_collisions.py` / `muscle_memory_rearchive.py`）未登记
  `scripts/diagnostics/INDEX.md` ⇒ 补登记。
- 006 的同名冲突"预期计数 = 8"改为可复算：新增 `tests/unit/evolution/experience/`
  与 `tests/unit/skills/` 下的复算用例（按审计记载的存量形状重建 manifest，
  断言计数口径 = 不同身份的额外条目数），并注明本检出环境**没有** `data/` 下的
  真 manifest 文件，故该数字的生产态仍待在有生产库的机器上复跑（见 §8.13）。


### 8.10 第三轮后的 CI 红：改指面漏了「代码里的路径拼接」

第二轮之后 `docs/adr/` 整目录被删净（改为编号分层 `docs/01-architecture/adr/`），
本批新增用例里仍按旧路径拼 ADR 0016 的位置 ⇒ `unit-tests-py311` / `unit-tests-py12`
双跑同时红在 `FileNotFoundError`。已修并补判据：

- `tests/unit/evolution/experience/test_muscle_memory_rearchive_safety.py` 改指
  `docs/01-architecture/adr/0016-rsi-parameter-source-of-truth.md`（唯一解，仓库里就一份）；
- 退役目录守卫补两条口径：**规则 1c** 管源码里的路径拼接形态
  （`REPO_ROOT / "docs" / "adr" / "…"`），**规则 1b′** 管通配形态
  （旧目录下的通配 ADR 引用在唯一可解时必须改指）。此前两条只看得见 Markdown，
  这类引用因此从门禁下溜过去；
- 同批扫荡另有三处通配引用指向已退役目录，一并改指。

### 8.11 CI 上的墙钟上界断言：从"登记为既有时序脆弱"改判为"根因处修复"

第三轮推送后 `unit-tests-py312` 红在
`tests/unit/agent/test_post_chat_p0_latency_observability.py::TestResponsePathLatencyImprovement::test_background_response_path_does_not_scale_with_bypass_steps`
（`assert 0.42625 < (0.15 + 0.1)`）。当时按"既有时序脆弱族"登记，并写明根治方向是把判据
从墙钟阈值改为步骤数不变量——但**留在本批未做**。本轮按该方向补齐，因为"登记为脆弱"
并没有让 CI 变绿，偶发红仍会持续。

**根因（不是"阈值太小"）：结构性契约被编码成墙钟阈值。**
"响应路径不付旁路代价"、"响应无关步骤并发跑"、"RSI 不进响应路径"这三条契约**与机器
速度无关**，是步骤集合与调度结构的事；写成 `elapsed < 0.25` 之后判据与机器强相关，
同一份代码在 py3.11 绿、py3.12 红。更坏的是它的**误判方向**：负载越高越红，
于是"让 CI 变绿"的捷径就变成放宽阈值——那会把真实的尾延迟回归一并放行，
属教义第 2 条禁止的降级断言。

**实测（本机注入 GIL 争抢，复刻 CI 负载）**：旧判据 `elapsed=0.437s vs 阈值 0.25` 必红，
且无负载时也已是 `0.437s`（阈值本身就没有裕量不代表契约）。详见下表。

**改动点（4 处，全部先红后绿）**

1. `test_background_response_path_does_not_scale_with_bypass_steps`：
   把 11 个旁路步骤全部闸在 `asyncio.Event` 上，`gate` 只在 `process()` 返回之后放开
   ⇒ "响应路径仍在等旁路步骤"表现为 `process()` 返回不了（`wait_for` 超时判红），
   而不是"耗时看起来偏大"。
2. `test_concurrent_background_actually_parallel`：
   每个步骤进门把在飞计数 +1 后停在闸上，断言**同轮在飞高水位 = 并发步数 5**
   （串行 await 时恒为 1）。
3. `test_summary_never_awaits_rsi_on_response_path`：
   RSI 步骤闸住不放（永不自行结束），若仍挂在响应路径上则 `process()` 超时；
   再断言返回时 `rsi_iteration` 未出现在 `_step_results` 里。
4. `test_snapshot_cost_is_negligible` → `test_snapshot_cost_does_not_scale_with_row_count`：
   原判据 `duration_ms < 250` 测不出"成本是否与数据量相关"（那才是"拖慢启动"的成因），
   却能在负载下误判。改为两条结构不变量：**语句骨架随数据量不变** +
   **只允许读元数据**（`sqlite_master` / `PRAGMA`，一条都不许碰表数据）。
   第 4 处最初只写"语句序列相同"，反向注入"每表多发一条 `SELECT COUNT(*)`"时
   **判绿（空转）**——语句条数不变、成本却随行数线性增长。补上"只读元数据"这条后，
   同一注入立即判红。

**新增门禁（防复发，单一事实源）**
`tests/unit/test_ci_wallclock_assertion_ledger.py`：受保护子集里每一个**墙钟上界断言**
都必须逐条登记结论（当前台账为空 = 此处不允许留墙钟）；外加 `CONVERTED_TO_INVARIANT`
登记本轮改为结构不变量的 4 处，**改回墙钟即判红**。检出口径覆盖三种写法：由时钟算出的
变量、名字含耗时词的量、以及**断言里就地算时钟**的表达式（漏了第三类，改一处写法就能
从门禁下溜过——本守卫的红灯用例锁住这点）。

**放大视角（教义第 5 条）：子集外的 22 处一并登记**
同一契约（结构性契约被编码成墙钟阈值）在受保护子集**之外**还有 22 处、分布在 17 个文件里。
它们不在 CI 跑，故不阻塞本批，但不得静默遗留——已逐文件登记数量进守卫
（`OUTSIDE_SUBSET_LEDGER`），分布一变即判红。是否改判属另一票范围：其中一部分本意就是
量真实机时（性能/超时类基准），一部分被测对象就是墙上时钟本身。

**门禁自身的稳定性**：新的分布核对用例最初要 parse 整仓 1694 个测试文件（实测约 4s），
注入负载后直接撞 `pytest-timeout`（>30s）——门禁自己都不稳就会被人绕过。加文本预筛
（候选词是判据的超集，不漏判，并有专门用例锁住"预筛不得滤掉真命中"）后降到约 1.2s，
负载下整组 `72 passed / 29.89s`。

**红→绿实测**
- 守卫自身：`2 failed, 5 passed`（判红 4 处未登记墙钟断言 + 守卫未登记受保护子集）
  → 登记后 `13 passed`。
- 反向验证（把实现回退成"旁路步骤仍在响应路径上"，位置：`process()` 的
  `if self.background_enabled():` → `if False and ...`）：3 处结构不变量全部判红；
  快照处的注入（每表多扫一条数据查询）同样判红。
- 反向验证（守卫本身）：① 往受保护子集塞一处未登记墙钟上界 → 判红；
  ② 把已改结构不变量的用例改回 `assert elapsed < 0.25` → 判红。
- 受保护子集（CI 同款 pytest 9.0.3）：`1925 passed, 6 skipped`。
- 负载自证：注入 16 个 GIL 争抢进程后，被改的 4 个文件 `72 passed`；
  A/B 对照（同一份负载）旧判据必红、新判据必绿（`0.437s` vs 阈值 `0.25`）。
- `ruff check neurova tests` 全过；`ci_static_gate.py --skip-import` 全过。

**净 LOC**：生产代码 `neurova/` **0 行**——改动全在测试判据（结构性判据替换墙钟判据）。

### 8.12 墙钟守卫与 A2 判据口径：合入 main 后的 CI 红

合入 main（上下文持久化批次 #108/#113/#115）后，`unit-tests-py311` / `unit-tests-py312`
双跑红在同一处：`test_ci_wallclock_assertion_ledger.py::test_no_unledgered_wallclock_upper_bound`
点名 `tests/unit/context/test_ledger_write_batching.py::test_batch_round_is_far_below_per_row_shape`。
该文件在 main 侧进受保护子集、在本分支侧还没有，合并才把它们凑到一起。

**根因（不是"阈值太小"）：A2 的比值读数把一次性冷加载算进了分子。**
被点名的用例其实**本机必红**（`227.6 ms > 194.0/3 ms`），与 CI 负载无关：
批量形状的首次归档会懒加载 token 估算器（tiktoken `o200k_base`，实测 227–331 ms），
而现状形状那一侧不带这项成本 ⇒ 分子恒为分母的 1.2 倍。也就是说，
"批量提交让写侧快 200 倍"的契约读数，被一次性的进程级冷加载盖住了。

**改动点**

1. `TestWriteAmplification`：两侧各预热一轮，再取 3 轮中位。实测现状 194–253 ms/轮 vs
   批量 0.42–1.57 ms/轮，倍数 **135–427×**（阈值只要 3×，裕量 45× 以上）。断言逐字未放宽。
2. 同契约补**结构面**判据 `TestRoundHasOneTransactionBoundary`：一轮归档内
   **新建连接 0 次 / `BEGIN` 1 次 / `COMMIT` 1 次**（用 `set_trace_callback` 数真语句）。
   与机器速度无关；反向验证（实现退回逐条提交）当场判红 `一轮归档开了 24 个事务（应共用一个）`。
3. 守卫台账逐条登记这 1 处（`WALLCLOCK_LEDGER`）：A2 的倍数本身是机时契约，墙钟不可替代，
   但**同一契约的结构面必须另有用例钉住**——只留比值等于把契约交给机器速度。
4. **守卫检出器的两个洞一并补上**（教义第 5 条：同一根因全命中点扫荡）：
   - 「用时经容器收集后取中位」（`samples.append(perf_counter() - t0)` → `median(samples) < 0.2`）
     与「用时派生量」（`budget = elapsed * 3`）此前**整片漏检**；
   - 同时把**时刻**（`before = time.time()`、`expires_at = time.time() + 3600`）
     从耗时量里摘出去——否则区间/过期断言会被误判（假阳性会训练人忽略门禁）。

**红→绿实测**

- 红灯（修复前，本机）：守卫 `1 failed / 12 passed`，点名上述 1 处；
  该用例**单独跑也红**：`批量形状 252.7 ms/轮 > 现状形状 221.8 ms/轮 的 1/3`。
- 绿灯：`test_ledger_write_batching.py` 13 passed；守卫 15 passed。
- 检出器新增的红灯（先红后绿）：`test_detector_follows_clock_through_collected_samples`、
  `test_detector_follows_clock_through_derived_variable` —— 补口径前两条均 `assert []` 判红，
  补后转绿。
- 反向验证：① 实现退回逐条提交 → 结构面用例判红（24 个事务）；
  ② 用例退回"不预热 + 单轮读数" → 原样判红（227.56 vs 194.00/3）。
- 子集外台账同步复核（检出器收紧的后果）：`test_phase4_integration.py` 1→2、
  `test_b7_worker_occupancy.py` 1→2、`test_camofox_supervisor.py` 1→0（时刻区间断言不算墙钟上界）。
- `ruff check neurova tests --no-cache` 全过。

**净 LOC**：生产代码 `neurova/` **0 行**——改动全在测试判据与文档。

### 8.13 第四轮：票面正文入库与「判据可复核」的收口

前三轮把生产代码修完并逐条登记，但**「收工判据」本身在仓库内不可达**：001–011
的票面正文只存在于 Issue #80 的附件里，仓内只有 `000-索引.md`。后果不是"文档不齐"，
而是复核者拿不到判据原文，只能反推——索引表 11 行的「主要落点」把人指向 11 份
**并不存在**的票面。

本轮把它收口成可机器校验的三条判据，落在 `tests/unit/test_tool_loop_ticket_set_guard.py`：

1. **票面齐备**：`000-索引.md` 表格里声明的每个票号都必须有同名唯一的票面正文，
   且正文不得是占位（≥200 字、至少一个小节）。索引表是唯一事实源，票号清单不另写一份。
2. **执行结果不留白**：票面进仓后「执行结果」格必须填上读数或诚实的「未做到 + 原因」，
   不许停在 `待填`。写出了字段却没人读，正是协作红线点名的断点形态。
3. **文档里的落点与人读的入口必须可达**：本批文档内以行内码写出的**仓库路径**
   （`docs/...`、`neurova/...`、`tests/...` 等）不得零命中或多候选；规格文档与票集索引里的
   **章节号**（`§8.10`）必须指向真实存在的章节。判据复用仓库既有的引用判定
   （`scripts/scan_docs_refs.py`），不另写一套解析。

**红→绿实测**

- 判据 1 红灯（入库前）：`1 failed`，点名 `001 → 缺 001-*.md` 至 `011 → 缺 011-*.md` 共 11 条；
  11 份正文入库后 `4 passed`。
- 判据 2 红灯（正文入库后）：`1 failed`，点名 11 处 `待填`；
  逐票填入实测读数后转绿（读数取自 §8.1–§8.12 与本轮复跑：`test_tool_router_success_verdict`
  `5 passed`、`test_three_state_four_faces` `8 passed`、`test_structure_identity_param_shape`
  `9 passed`、`test_rsi_idle_cost_recorded` `4 passed`、`test_chain_integrity_observability`
  `5 passed`、`test_skill_view_key_domain` `13 passed`、`test_skill_entry_choke_migration`
  `15 passed`、`test_skill_rollback_governance` `7 passed`、`test_tool_loop_funnel_probes`
  `8 passed`、离线探针 `4 passed`）。
- 判据 3 红灯（覆盖面只含索引时）：把票面正文纳入覆盖面后当场点名
  `006-…:38 docs/adr/0018-skill-view-key-domain.md → 源已删除`；
  改指 `docs/01-architecture/adr/0019-skill-view-key-domain.md` 后 `10 passed`。
  同批还把「描述旧落点」的正文改成占位形态（`docs/adr/0018-<slug>.md`）——
  描述性文字里写具体旧路径同样会被退役目录守卫判红，假阳性与真断链必须分清。
  另两处同类死指针一并改指：`入口迁移台账.md` 里的审计文档路径（那份审计**从未入库**，
  改成显式文本交代去处，不再写成仓库内路径形态）、规格文档里两处指向**第九节**的悬空
  章节号（本规格实际只有第一节至第八节，改为指向台账与本轮这一节）。
- 三条反向控制各自独立：缺号判据喂合成输入判出 `099`；占位判据认得出 `待填`
  且不误报已填读数；章节号判据认得出 `§8.2` 悬空、`§8.1` 存在；路径判据认得出
  零命中为「源已删除」，同时不得把**唯一可解**的旧路径（`agent/chat_pipeline.py`）
  误判成断链（假阳性会训练人忽略这道门禁）。

**净 LOC**：生产代码 `neurova/` **0 行**；改动全在文档（票面正文入库 + 若干处改指）
与一份新守卫（`tests/unit/test_tool_loop_ticket_set_guard.py`，测试不计入教义第 2 条的账）。

**仍未闭环（诚实登记，不静默遗留）**

- **006 生产库读数**：本检出环境 `data/` 下没有 `data/agents/*/skills/manifest.json`，
  「同名冲突 = 8」的生产态真值仍待在有生产库的机器上跑
  `python scripts/diagnostics/skill_name_collisions.py` 复核；计数**口径**已可复算（= 7）。
- **008 浏览器级 live** 与 **011 三件套**：沿用第二轮登记，均属需人配合或本仓无既有落点的动作。
  两项已在第六轮由用户裁定「按现状承接」，退出未闭环清单，见 §10 与票集索引的「用户裁定」节。
- **来源审计文档**（工具↔经验环路的深度审计）：其正文只存在于 Issue #80 附件，
  仓内从未有过；005 票面要求的「回审计文档 §2 新开登记项」因此无法就地兑现，
  已改由 `入口迁移台账.md` 承接并在该文件「登记」节写明。
- **本票集正文的 L-xx 断点编号**（如 003 的「审计 L-02」）引自上述未入库的审计文档；
  本轮未改写这些引用（它们不构成仓库内死链），待审计文档入库后即可回填。

---

## 9. 第五轮：批次级判据入库与断点编号出处

第四轮把 001–011 的**票面正文**入了库，判据在「每张票」这一层可读了。但这一批
还有**更高一层的判据**仍然只存在于 Issue #80 的附件里，仓内不可读：

- **全局约束**（每张票都必须遵守，违反任一条该票视为未完成）；
- **硬次序**（`002` 早于 `003`、`007` 早于 `008`，不可调换）；
- **整批完成判据**（`001` 三条探针全绿 + 经验质量门禁两格读数不变差）；
- **票面里的 `L-xx` 断点编号**：其出处（工具↔经验环路的深度审计）从未入库。

前两者的后果是**同一批的 11 张票在两套口径下被裁**：索引里只有「全局约束**遵守情况**」，
那是实现方的自陈报告，不是约束本体；复核者读不到「约束写了哪几条」，也就无法判断
各票是否在同一契约下完成——与第四轮那个「有索引、无判据」的断点是同一形态，
只是断在更高一层。

第三项更硬：票面正文大量出现 `审计 L-02`、`L-04 / L-05 / L-10` 这类编号，
读者在仓内**查不到它指什么**。出处文档的正文无法凭空复原（它从未入库，见 §5 的「明确不做」登记与本文档 §9.3），
但「编号 → 承载它的票」这件事可以从票面自陈回填，让「同一断点在哪几张票被处理」
在仓内可读——「查不到」与「没人写」必须分得开。

### 9.1 收口

- 票集索引新增 `## 批次级判据`：硬次序、全局约束 11 条、完成判据（各自点名取证入口）、
  以及 `L-xx` 编号出处表。正文按附件原文录入，遵守情况仍在各票「执行结果」与
  §8 各节——**不新造第二份遵守情况**。
- 守卫 `tests/unit/test_tool_loop_ticket_set_guard.py` 增第 4、5 组判据（6 条 + 2 条反向控制）：
  批次级节必须存在、约束条目数不得退化、完成判据必须点名可重跑的取证入口、
  票面里每个 `L-xx` 编号必须在本表登记。

### 9.2 红→绿实测

- 红灯（实现前，6 failed）：
  `test_batchConstraintsBlockExists` / `test_everyBatchHeadingIsPresent` /
  `test_globalConstraintsAreEnumerated` / `test_completionCriteriaNameTheirEvidenceSources` /
  `test_everyTicketDefectNumberIsIndexed`（点名 `L-02 … L-11` 共 10 个未登记编号）/
  `test_provenanceFormIsStated`。
- 绿灯（收口后）：`tests/unit/test_tool_loop_ticket_set_guard.py` **21 passed**
  （原 13 条 + 本轮 6 条 + 2 条反向控制）。
- 反向控制各自独立，均喂合成输入、不拿仓库现状当输入：约束条目检出器认得出
  `1. **粗体标题**` 形态且不把普通编号列表算进来；编号完备性判据能判出「票面有、索引无」
  的 `L-99`。

### 9.3 本批不做项在哪

附件索引里的「不排本批（登记，勿顺手做）」与 §5「明确不做（登记）」是同一批内容
（`D5` 失败粘性解冻、`injector.py` 的 `context`/`content` 键错位、`estimate_confidence`
序列分虚高、`voice_memory_bridge` 硬编码 success、`neurflow/builtin.py` 吃模型自报），
以 §5 为准，不在本轮回填第二份。


## 10. 第六轮：用户裁定入库（008 / 011 两项「按现状承接」）

第五轮末本批剩四项「实现方无法单方面闭环」的事项。其中两项需要用户裁决：**008 的
浏览器级 live** 与 **011 的设计契约三件套**。用户在 Issue #80 裁定：

> 第 2、3 项「按现状承接」。

### 10.1 本轮断点：裁定落在评论里，读者在仓内看不到

裁定之前，这两项在各处都写作「未闭环（诚实登记）」。裁定之后若不同步，读者在票面
看到的仍是这四个字——**「已裁定、不必再做」与「没人做、待办挂着」在仓内分不开**。
与第四轮（有索引、无判据）、第五轮（有票面、无批次判据）是同一形态：写入→读取的环
断在**读者**这一环，只是这次断的是「裁决结果」这一类事实。

裁定本体无法从代码反推，也无既有落点可承载（它既不是票面判据，也不是规格正文），
故按「单一事实源」在票集索引新开一节；不另建裁定文书、不在规格里复写第二份。

### 10.2 收口

- 票集索引新增 `## 用户裁定（按现状承接）`：裁定原文引用、两项的覆盖范围与等价覆盖方式、
  以及**未闭环清单里哪两项不适用本裁定**（006 生产库真值、来源审计文档入库，属「缺输入」
  而非「按现状收」）。
- 008 与 011 两份票面的「未闭环」段末尾各补一句回指：写明已裁定、退出未闭环清单，
  并指向索引那一节——票面是读者的第一站，环必须在那里闭上。
- 守卫 `tests/unit/test_tool_loop_ticket_set_guard.py` 增第 6 组判据
  `TestUserRulingIsReadableInRepo`（4 条判据 + 1 条反向控制）：裁定节必须存在、
  必须点名结论与覆盖项、必须交代「退出未闭环清单」并指向本节、被覆盖票面必须回指。

### 10.3 红→绿实测

- 红灯（收口前，4 failed）：
  `test_rulingSectionExists` / `test_rulingNamesTheCoveredItems` /
  `test_rulingSaysTheseAreNoLongerOpenItems` / `test_coveredTicketsPointAtTheRuling`
  （点名 `008-…md` 与 `011-…md` 两份票面未回指）。
- 绿灯（收口后）：`tests/unit/test_tool_loop_ticket_set_guard.py` **26 passed**。
- 反向控制 `test_rulingCriterionIsNotVacuous` 喂合成输入，不拿仓库现状当输入：
  节缺失、结论写错、覆盖项说不全三种形态各判一次。
- 过程读数（既有判据当场生效）：索引里写下 `§10` 而规格尚无该节时，
  `test_crossDocRefsIntoTheSpecResolve` 立即报红点名 `000-索引.md:315 §10`
  ——本轮新增的跨文档引用被既有的章节号判据接住了。

### 10.4 与本轮同批的 CI 红：受保护子集的 `sh` 依赖

本 PR 首次推送时 `unit-tests-py311/py312` 双跑红，唯一失败项与文档改动无关：

```
FAILED tests/unit/test_dev_path_and_runtime_dep_guards.py::TestProtectedGuardsUseNoExternalBinaries::test_no_bare_external_command_in_subprocess
  tests/unit/ci/test_npc_script_interpreter_reachability.py:362: 直接执行外部命令 'sh'
1 failed, 2368 passed, 12 skipped
```

红点在上一提交（`7b2c9c84`，PR #155）新入受保护子集的
`test_node_call_form_reaches_the_same_reading`：它为复现平台调用形态写下字面量
`subprocess.run(["sh", "-c", ...])`，而 `sh` 不在白名单里。`sh` 缺席时不是断言失败
而是 `FileNotFoundError`，整个文件（含同文件其余 9 条判据）**静默不跑** —— 正是该
守卫存在的理由。

根因两层，已由同一分支上的后续提交一次修掉（`e8d62417`）：

1. 直接原因：`sh` 在使用点先证后用（`shutil.which("sh")` 缺席即显式 skip 并点名原因），
   再把 `sh` / `-c` / 桥命令原样交给 `subprocess`——调用形态与平台一致，判据未降级。
2. 更高一层：白名单的**语义没有判据守着**。原注释写着「仅当前环境断言存在的外部命令
   （用 `shutil.which` 跳过）」，但 `git` 的四个使用点从不自证可达，白名单于是成了
   「把已知坏味道挪进去」的通道，换基础镜像即复发。故补
   `test_allowed_binaries_are_proven_reachable_at_every_call_site`：白名单里的每个命令
   都必须在每个使用点自证可达（AST 口径）+ 一条反向控制，同批补齐 `git` 的四个使用点。

处置依据与该提交的红→绿实测以其提交说明为准，本节不复制第二份。此处记录它的理由只有一个：
它与本轮的文档改动同处一条 PR、同一个 `unit-tests-*` 门禁，读者复核「这一批为什么红过」
时必须能在一个地方看到因与果——不因分属「CI」与「文档」而拆到两处。

### 10.5 与本轮同批的第二处 CI 红：台账生成物与扫描器脱节

同一条 PR 的第二次推送上，`unit-tests-py311/py312` 又红在同一处，仍与任务内容无关：

```
FAILED tests/unit/test_archive_nav_impact_guard.py
  ::TestPointerEntriesAreProjectInitiated::test_summary_block_matches_scanner
  ::TestMachineBlocksHaveAGenerator::test_writer_is_idempotent_on_the_shipped_ledger
2 failed, 21 passed, 1 skipped
```

两处指向同一件事：台账 `docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md` 第 8.2 节
（`<!-- NAV-IMPACT:SUMMARY:BEGIN -->` 区块）写着归档层悬空引用 **1778** 条，而扫描器
当时的真实读数是 **1781**（其中「无当下读者」豁免 830 → 833）。

**根因**：本轮给 `docs/05-reports/dependency-cve-ledger.md` 追加的修复台账一节里，
有 3 处引用写成了**裸文件名**（`test_tracked_run_residue_guard.py` 等）——同节相邻引用
都写了全路径，这 3 处是漏写。归档层正文改动会让扫描器的悬空引用计数变化，而第 8.2 节
是**生成物**，本轮改完源文档没有同批重生成，生成物与唯一事实源（扫描器）就此脱节。

这正是「写入 → 读取」的环断在**生成物**这一环：源文档改了，生成物没跟上，守卫比对的
两侧读数不再相等。

**处置**：按守卫明示的唯一动作重生成，不手改生成区、不就地改写归档层正文
（该层政策是「陈述当时形态，不就地改写」；裸文件名在扫描器口径里属**已枚举的合法
形态**，落在「描述性行内码」与「无当下读者」两个豁免桶里，不是非法状态）：

```
$ python scripts/scan_docs_refs.py --update-ledger
台账机器区已重生成：docs/06-bugfix/历史悬空引用登记台账_2026-09-21.md（5 个区块）
```

**红 → 绿实测（本环境 py3.11）**：

```
# 红（重生成前）
$ pytest tests/unit/test_archive_nav_impact_guard.py -q
2 failed, 21 passed, 1 skipped

# 绿（重生成后）
$ pytest tests/unit/test_archive_nav_impact_guard.py -q
23 passed, 1 skipped
```

幂等自证（生成器不空转重写）：把生成结果写回后逐字节不变——守卫
`test_writer_is_idempotent_on_the_shipped_ledger` 即此判据，第二次重跑无差异。
