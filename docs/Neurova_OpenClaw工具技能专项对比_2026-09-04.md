# Neurova × OpenClaw 工具/技能/进化/记忆专项对比（2026-09-04）

> 前篇：`docs/Neurova_OpenClaw代码级对比_2026-09-04.md`（14 维总评分 OC 8.9 / NV 7.0）。
> 本篇是第二轮专项深挖 + 五批改进实施 + 两遍闭环审计的完整记录。
> 【文档事故记录】本文档曾于 2026-09-04 晚被并行会话的工作树清理波及删除（从未提交）；2026-09-04 深夜依据完整上下文重建。实施代码均已随 5199b23f/d4424bf1 等入库，未提交增量为 §10.5 二遍审计修复（6 文件）。
> OC 侧路径相对 `E:/项目/openclaw-compare/openclaw/`；NV 侧路径相对 `E:/项目/Neurova/`。

---

## 0. 结论速览

1. **工具呈现与选择是 Neurova 当前最大、最便宜的可优化点**：OC 用 Tool Search（隐藏目录 + BM25 检索 + 延迟加载 schema，18k 字符硬预算）把大工具目录挡在 prompt 外；NV 是 53 个内置工具 + SkillRegistry 全量 schema **每轮双重全量注入**，唯一筛选（生命周期过滤）因双实例断链近乎惰性。
2. **OC 没有工具级自适应学习闭环——全篇最重要的确认**。全库 grep 证实：无工具成功率统计、无权重表、无按历史表现的选择机制，Tool Search 排序是纯静态 BM25。它的替代品是"静态五层策略 + 审计回执 + 事后 trajectory"。**Neurova 的棘轮 + 肌肉记忆 + 动态阈值齿轮在 OC 中没有对应物，是真差异资产。**
3. **但 OC 在"经验→技能文档"这一层有成熟闭环（Workshop）**：/learn 起草 → 提案（hash 锁定 + run 级变异预算 + 精确 span 补丁授权）→ hook 评估 + 三条评审线 → pending/apply（仅自有技能自动应用）→ revision hash 回滚。NV 的 create_skill/AutoSkillBuilder 产物**直接进 SkillRegistry，无任何评审闸**——学习越自动，越需要闸门。
4. **NV 学习闭环的敌人不是能力而是断链**：A 版棘轮整文件死代码、RSI 优化的参数一半无消费者（调了=没调，还欺骗收敛分析器）、ToolLifecycle 双实例 split-brain、三套经验存储互不相通。
5. **记忆整理侧 NV 已把 OC 的 Dreaming 思想落地**（`run_promotion_cycle` 注释明确承认启发来源），且贝叶斯衰减+17 维情感是 OC 没有的纵深；短板收敛为"经验存储三国杀"与缓冲/关联表无持久化两个工程债。

### 专项评分

| 子维度 | OpenClaw | Neurova | 裁决 |
|---|---:|---:|---|
| 工具呈现与选择 | **9.5** | 5.5 | 双层检索+预算 vs 每轮全量双注入 |
| 技能范式与治理 | **9.0** | 7.0 | OC 文档技能+workshop 治理闭环；NV 可执行技能+fail-closed 权限各有哲学 |
| 自适应学习闭环 | 5.0 | **7.5** | **NV 差异资产**（OC 工具级零学习），但断链拖分 |
| 经验与记忆整理 | **9.0** | 7.5 | 检索/衰减 NV 强；写入侧治理与存储收敛 OC 强 |
| 工具执行治理 | **9.5** | 6.5 | 分段审批/MCP 一等公民/结果双通道 vs 声明式权限真但熔断器未装配 |

---

## 1. 工具面呈现与选择：全量注入 vs 检索式延迟加载

**OC**（`src/agents/tool-search*.ts`）：三模式 `code|tools|directory`；隐藏目录 + BM25（Okapi K1=1.2/B=0.75）+ `tool_search/tool_describe/tool_call` 延迟 schema；目录 18000 字符硬预算二分截断；**不可信 MCP schema 永不进 system prompt**；direct-only 逃生门；`requiredClientCaps` 硬过滤（"hard fact, not policy"）。

**NV（实施前）**：53 内置工具+SkillRegistry 全量 schema 每轮双注入；唯一筛选 `_apply_tool_lifecycle` 因 C3 断链近乎惰性。

**改进项**（A1-A6，落地状态见 §8/§9）：A1 单源化 ✅ / A2 可见性门控 ✅ / A4 预算降级 ✅ / A5 能力门（未排期）/ A6 完整 Tool Search ✅（§9.1）。

## 2. 技能范式与治理：文档技能 vs 可执行技能

OC：技能=SKILL.md 提示词文档，正文永不进 prompt（`<available_skills>` 目录+read 自取），150 技能/18k 预算多级降级，`disable-model-invocation` + `command-dispatch: tool`，Workshop 治理闭环。
NV：技能=工具序列（create_skill 组合+占位符），声明式权限 fail-closed + 注入扫描。

**改进项**：B1（=A4）✅ / B2 model_invocable ✅ / B3 requires.bins ✅ / B4 command-dispatch ✅（§9.3）。

## 3. 自适应学习闭环：NV 的差异资产与断链

**OC 确认结论：工具级零学习**；学习只在技能文档层（Workshop：/learn 起草→pending 提案 hash 锁定+变异预算+span 补丁授权→三条评审线消费 skill_usage→apply/回滚）。

**NV 断链清单（11 条，全部已修或登记）**：
1. ✅C1 A 版棘轮死代码（§7.1 删除）
2. ✅C2 RSI 死参数（§7.1 接真消费者）
3. ✅C3 ToolLifecycle 双实例（§7.3 单例）
4. ✅C4 facade 死调用（§7.3 透传）
5. ✅C5 熔断器未装配（§7.3 env 门控）
6. ✅C6 失败记账无单一事实源（§7.1 窗口化后权重层为语义正身；其余订阅待办）
7. ✅C7 棘轮无窗口统计（§7.1 滑动窗口）
8. ✅C9 结晶缓冲/关联表无持久化（§8 C9）
9. ✅C10 技能评审闸缺失（§8 C10 + §10.5 审批面）
10. ✅C11 技能使用计数缺失（§8 C11）
11. ✅C13 修订 hash/回滚缺失（§8 C13）

## 4. 经验与记忆整理

NV 检索/衰减侧强（MoE 三层隔离+贝叶斯衰减+17 维情感）；写入侧对照：OC Dreaming 三阶段已由 NV `run_promotion_cycle` 落地（注释自证启发来源）。**改进项**：D1 注入收敛 ✅（§8）/ D2 origin 核查 ✅（无毒化缺口，见 §8.2）/ D3 升级车道 ✅（§9.4）。

## 5. 工具执行治理

E1 熔断器装配 ✅（=C5）；E2 隐私门控 ✅（§8 + §10.5 流式路径）；E3 MCP 授权铸造 ✅（§9.2）；E4 分段审批（已在 94f5c557 P0-6 落地）。

## 6. 改进清单优先级汇总（终态：全清）

- **P0**：C1✅ C3✅ C4✅ A1✅（§8）
- **P0.5**：C2+C7✅（§7.1）C5/E1✅（§7.3）A2✅（§8，env 门控）
- **P1**：C10✅（§8+§10.5）C11✅ C12✅ C13✅ A4✅ D1✅ C9✅ B2/B3✅
- **P2**：A6✅ E3✅ D3✅ B4✅（§9，均门控默认关+生态条件参数化）

---

## 7. A/B 版棘轮算法裁决与融合

### 7.1 融合实施终态（第一批，已随 5199b23f 前批入库）

- **B 版骨架为正身，吸收 A 三思想**：①滑动窗口成功率（deque 按 window_size 修剪，分母用窗口计数修 A 终身激励冻结；回退序=窗口→终身成功率（legacy 零跳变）→1.0 未观测不受罚）②惰性时间衰减 `_apply_lazy_decay`（>6min 生效，读后刷新时间戳防重复指数放大）③全参数化 success_bonus=0.1/failure_penalty=0.05/decay_rate=0.01（与 ToolMemoryIntegration 构造默认精确对齐零偏差）
- **RSI 活表**：Integration 三死参数转 property setter→`_sync_weight_params`→`weights.configure()`（setattr 语义不变）；`_get_dynamic_threshold` 改消费含衰减的 `get_effective_multiplier`
- **A 版处置**：`tool_weights.py` 285 行死代码删除；`test_tool_lifecycle` 改指 B；残留引用=0
- **持久化**：v2 带 window；v1 旧 JSON 安全默认
- **净 LOC −102**；契约 15 条（`test_tool_weights_fusion.py`）+ 定向 109 绿
- 遗留：RSI 调参重启回默认（参数持久化待 RSI 落盘契约）

### 7.2 Skill 递归进化三断点修复终态（第二批）

| 断点 | 修复 |
|---|---|
| #1 record_reuse 零调用方 | `_on_skill_post_execute` 把 genetic 产物 `config.tool_sequence` 喂回种群（evolution 缺失 fallback closed_loop 单例） |
| #2 genetic 注册不持久化 | `register_to_skill_registry(registry, skill_service=None)` 签名扩展+调用点传 SkillService（仅新注册持久化） |
| #3 提案无回写 | `apply_improvement`：改进追加 `config.improvements`（不改工具序列）+版本递增+applied 标记+同签名去重；`_step_rsi_iteration` 提案先 apply |

契约 10 条（`test_skill_evolution_feedback.py`）；净 LOC +159/−4。

### 7.3 工具侧断点修复终态（第三批）

| 断点 | 修复 |
|---|---|
| C3 生命周期双实例 | `init_evolution` 不再新建：`a.tool_lifecycle = a.evolution.tool_lifecycle`（无实例回退自建）。主链 touch/后处理 evaluate/肌肉记忆降级检查/过滤器四路同源。**反向修法已排除**：主链不得调 `on_after_tool_execution`（ExperienceFeedback 会二次 update_weight 双计） |
| C4 facade 死调用 | 透传 `get_top_patterns` 映射 dict 契约 |
| C5 防护零装配 | `bootstrap_evolution_protections()`：env 门控 `NEUROVA_TOOL_CIRCUIT_BREAKER=1`/`NEUROVA_TOOL_PARAM_GUARD=1`（幂等默认关）；start_server 接线 |

契约 7 条（`test_tool_loop_breakpoints.py`）；回归 437 绿。

---

## 8. §6 改进项全量实施终态（第四批）

| 项 | 内容 | 门控 |
|---|---|---|
| A1 单源化 | `render_tools_description` 纯函数，描述条目数=tools 参数数 | 默认开 |
| A2 可见性门控 | DEGRADED 工具从 LLM 工具面隐藏 | `NEUROVA_HIDE_DEGRADED_TOOLS=1` |
| A4/B1 预算降级 | 18000 字符三级降级（丢参数→截描述→保全部工具名）；A6 的朴素前缀 | env 可调 |
| B2 model_invocable | `config.model_invocable=False` 跳过工具面 | 技能级声明 |
| B3 依赖声明 | `requires.bins` 缺失附 `deps_warning` 不阻断 | 默认开 |
| C9 结晶缓冲持久化 | `state_path` JSON 聚合计数（observations/successes），重启恢复；已结晶不恢复 | state_path 注入 |
| C10 技能评审闸 | 产物 pending（is_active=False）+ list/approve/reject + **审批面三端点**（§10.5 X5）| `NEUROVA_SKILL_REVIEW_GATE=1`（**默认关**——二遍审计修正，闸开必须有面） |
| C11 使用计数 | `SkillService.record_skill_usage/get_skill_usage` 写 manifest | 默认开 |
| C12 RSI 回执 | JSONL {ts,parameter_path,old,new}；**默认不落盘**（单例零 IO），start_server 注入 | `NEUROVA_RSI_RECEIPTS` |
| C13 修订回滚 | revisions 有界 5 条（config 快照+sha256+version_after）+ `revert_last_improvement`（错序拒绝） | 默认开 |
| D1 注入收敛 | `dedupe_experience_sources` 结晶优先去重，两条装配点统一 | 默认开 |
| E2 隐私门控 | `security/privacy_gate.py`：敏感键脱敏+private 丢 params；AGENT_TOOL_RESULT+流式路径（§10.5 X6） | 默认开 |

**D2 核查结论**：`remember` 写入咽喉无外部内容直写路径（外部产出沉淀在转录/EKB）；检索侧 untrusted 降权已在位——当前无毒化写入缺口。

### 8.3 P2 缓办声明（后被 §9 推翻——用户指令"包括生态条件一并实现"）

原 A6/E3/D3/B4 四项缓办理由存档：A6 需 MCP 规模/E3 需审批流场景/D3 行为面设计/B4 命令面配套。最终以"门控+阈值+配套存储"形式全部落地（§9）。

### 8.4 验证与账目

23 新契约（3 文件）；净 LOC 生产约 +290+测试 524；甄别经单文件 pathspec stash（feedparser 链/TaskDecomposer 缺类预存）。

---

## 9. P2 全量实施终态（第五批，已入库）

| 项 | 内容 | 门控/生态 |
|---|---|---|
| **A6** Tool Search | `context/tool_search.py`（210 行）：build_catalog+BM25（Okapi K1=1.2/B=0.75）+render_directory（18k 预算）+三控制工具+compaction；executor.execute 拦截（tool_call 解包走完整管道治理全链生效+目录外拒绝；search/describe 读活动目录）；目录以 `tool_search_directory` 伪条目 description 承载 | `NEUROVA_TOOL_SEARCH=1` 且隐藏候选≥`MIN_CATALOG`(40)；直连默认核心 10 件（`NEUROVA_TOOL_SEARCH_DIRECT`） |
| **E3** MCP 授权 | `security/mcp_grants.py`（120 行）：ToolGrantStore (server,tool) 粒度原子 JSON（懒加载首读零 IO）；铸造=approve_and_execute 的 remember+MCP 命名+重放成功；消费=executor 预检前命中→skip_governance 直达（与命令级 remember 互补） | 铸造需显式 remember |
| **B4** command-dispatch | `_check_command_dispatch` 前置：`/技能名 参数`→直达执行映射工具（治理全链生效，原始参数注入 input 键）→reply 直出；`_step_llm_call` 短路；`_check_tool_memory` 防双执行（§10.5 X2/X4） | `NEUROVA_SKILL_COMMAND_DISPATCH=1` |
| **D3** 升级车道 | `_active_memory_escalation`：双门判据（`_is_past_seeking` 确定性正则+`should_need_more_context(0.35)`）→深检索（min_quality=0+limit15）→`_memory_key` 合并去重；与 Adaptive Retrieval（LLM 改写）正交 | `NEUROVA_ACTIVE_MEMORY=1` |

契约 15 条（`test_p2_items.py`）；回归 133/468 绿；净 LOC 生产约 +590+测试 273。事故记录：D3 门控函数曾插入 @dataclass 与 class 之间致装饰器错挂（测试当场暴露）。

---

## 10. 全批改动闭环审计（两遍）

### 10.1 第一遍：跨批交互三连

| # | bug | 修复 | 契约 |
|---|---|---|---|
| X1 | **A6×A4 目录双份注入+截断毁坏**（伪条目 description 被预算降级截断到 400 字符+双份 token） | markdown 渲染跳过 `tool_search_directory`——目录只在 tools 参数一处 | `test_a6_directory_not_duplicated_in_markdown` |
| X2 | **B4×肌肉记忆双执行**（分发后同输入再触发自动执行） | `_check_tool_memory` 入口短路（后升级为 §10.5 X4 的 ctx 态） | `test_b4_dispatch_prevents_double_execution` |
| X3 | **过期测试契约**（lifecycle evaluate 测试断言已删除的 record_failure） | 更新为 `update_weight(False)` 新契约 | 更新后绿 |

### 10.2 跨批交互矩阵（11 对逐一复核 ✅）

融合权重×C3 单例 / A2×A6 顺序 / A6×E3×预检 / B4×E2 / B4×C11 / D3×D1 / C12×零 IO / C10×genetic（分层：AutoSkillBuilder 入 pending 人审、genetic 以 fitness≥0.8 质量门直通——策略性差异已记录）/ C13×C10 / C9×零副作用 / 五门控默认关。

### 10.3 静态断链扫描（全绿）

无补丁脚本变量泄漏、无 A 版 API 残留调用、无 `_patch*.py` 残留、无 A 版模块存活导入、`data/evolution` 残留已清。

### 10.4 第一遍回归

911 passed / 10 failed（全部 feedparser 链预存，pathspec stash 基线确认）；今天全部契约 72 条绿。

### 10.5 第二遍深审——状态/生态类问题三连

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| X4 | **B4 标志跨轮泄漏** | `_command_dispatch_replied` 是长生命周期实例属性——分发后、LLM 步前任一中间步异常即滞留 True → **后续所有轮次肌肉记忆检查被永久跳过** | 改读 `ctx.metadata["command_dispatched"]`（ctx 每轮新建天然无滞留）；`_step_llm_call`/`_check_tool_memory` 同步切换；实例标志删除 |
| X5 | **C10 评审闸无审批面（真断点）** | 闸默认开 + pending 无任何 HTTP 审批端点 → 生产上自动技能永久滞留 pending 不可见且无人能批 | ①默认改关（`NEUROVA_SKILL_REVIEW_GATE=1` 显式开启）②补审批面三端点：`GET /v1/skill-pool/agent/{id}/pending-skills`、`POST .../{template_id}/approve`、`POST .../reject` |
| X6 | **E2 流式路径漏防** | AGENT_TOOL_RESULT 已脱敏，但 console SSE 显式 opt-in 的流式 `tool_result` 事件绕过门控 | 流式转发前同源脱敏 |

另记录：并行会话 `test_loop_review_residuals.py`（残余 A/B/C：结晶回调自喂环/EKB 连接 churn/apply 落盘通道）曾在全套件中出现一次顺序敏感偶发（`captured={}`，三次复跑不复现），登记观察项；其残余 C 与批四实现互补闭环。

**二遍审计后回归：923 passed / 10 failed（全部 feedparser 链预存）；今天全部契约 74 条绿。**

### 10.6 第三遍审计——覆盖事故专项（用户指令"如有事故覆盖，修而不覆盖"）

| # | 事故 | 处置 |
|---|---|---|
| Y1 | **C11 传动轴被覆盖断链**：并行会话重写 `_on_skill_post_execute` 时把 `record_skill_usage` 调用覆盖丢失（签名扫描 53 项当场抓出；并行的 record_reuse 改进被保留——成败语义移到 success 后） | 重接调用（"修而不覆盖"：只补丢失调用，不触碰并行改动）；补防覆盖契约 `TestC11WiringSurvival` |
| Y2 | **A 版死代码复活**：`evolution/tool_weights.py` 因 stash 往返 + 并行落库回到跟踪态（零导入方取证在案） | `git rm` 重删；`test_dead_a_version_stays_deleted` 防复活 |
| Y3 | **审计台账被并行清理删除**（从未提交，工作树丢失） | 依据上下文全量重建本文档（§7-§10 + C10 行同步二遍终态）；`test_audit_report_present` 防再丢 |

**防覆盖机制固化**：`tests/unit/evolution/test_wiring_survival.py`——五批全部改动的 60+ 关键签名固化为参数化契约（21 条），未来任何并行覆盖/回滚在测试层当场变红，红字指引核对本文档后再决定恢复或更新契约。

**三遍审计后回归：924 passed / 10 failed（全部 feedparser 链预存）；全部契约 74+22=96 条绿。闭环判定维持成立。**

---

## 10.A 闭环判定（最终）

**五批改动（A/B 棘轮融合 → Skill 三断点 → 工具 C3/C4/C5 → §6 P0-P1 十三项 → P2 四项）+ 两遍审计（跨批交互 3 项、状态/生态 3 项、过期契约 1 项）全部修复并契约化。无断点、无死代码残留、跨批交互矩阵 11 对全绿、静态扫描全绿。代码已随并行批次入库（5199b23f/d4424bf1 等）；未提交增量为二遍审计修复（6 文件 +95/−17）。**

## 附：证据文件索引（要点）

| 主题 | OC 侧 | NV 侧 |
|---|---|---|
| 工具检索 | `src/agents/tool-search-ranking.ts`（BM25）、`docs/tools/tool-search.md` | `context/tool_search.py`、`context/orchestrator.py`（管道） |
| 技能治理 | `src/skills/workshop/` | `skill_encapsulation.py`（评审闸）、`skill_improver.py`（apply/回滚）、`skill_pool_api.py`（审批面） |
| 学习闭环 | 无工具级（grep 证实） | `closed_loop.py`（融合棘轮）、`agent_core.py`（reuse 传动轴）、`genetic_engine.py`（持久化注册） |
| 肌肉记忆 | （无对应） | `muscle_memory.py`、`tool_memory_integration.py`（动态阈值） |
| 治理 | `exec-approvals-*`、`mcp` 授权 | `governance.py`、`tool_circuit_breaker.py`、`mcp_grants.py`、`privacy_gate.py` |
