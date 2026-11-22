# 小脑分诊门接线与自研微型判定模型实施方案

> 日期：2026-11-22 · 状态：**已实施并开机（2026-11-22，十一笔提交，本地已推双远端）：SB-1..SB-5 + 收官修复 + SB-6/SB-7 + D-SB1/D-SB3；判定数 ≥500 已达标；开关已切 enforce（2026-11-22 用户拍板，回滚=同一设置键热改回 shadow/off）；D-SB1/D-SB3/D-SB4 全部裁决实施**
> 来源：[多 Agent 协作实现路径分析报告](../05-reports/2026-11-21-multi-agent-collaboration-implementation-analysis.md) §8/§11 + 2026-11-21/22「双心智通路」专项剖析（会话内完成，证据链见 §1）
> 关联计划：[2026-11-21-multi-agent-collaboration-repair-plan.md](2026-11-21-multi-agent-collaboration-repair-plan.md)（M1–M14 协作域断点修复，与本计划**文件域无交集**，可并行）
> 纪律：每卡先红后绿（红灯实证缺陷）→ 最小实现转绿 → A/B 零新增失败 → live-verify 真链路 → `--only` 逐文件提交；净新增 LOC 尽量为负或逐条列明去向（测试不计）。

---

## 1. 背景与问题定义

### 1.1 双心智架构现状

本仓「双心智」在推理面的落点是 **Small-Brain 分诊门**（`neurova/llm/triage.py:51` `SmallBrainTriageGate`，廉价小模型按原则判定"本轮是否值得响应"）与 **SmallBrainRouter**（`neurova/collaboration/small_brain_router.py`，模型路由/分类）。分诊门是七层多 agent 防御体系（`collaboration/glance_yield_rules.py`）的 **Layer 6**；其判定原则为：人在场/人在等→必响应；纯 agent 互聊且无未竟工作→不响应；拿不准→保守放行（triage.py:79-115）。

### 1.2 问题：「未进自动路径」证据链（逐环核实）

1. **活路径经过 Layer 6**：聊天回合 → `AgentRunLedger.acquire`（core/agent_run_ledger.py:258）→ `requestYieldGate`（agent/turn_coordinator.py:143）→ `check_yield_rules`（glance_yield_rules.py:172）→ Layers 1-4 → Layer 6 `_check_triage_gate`（:415）。`agent_run_ledger.py:30-34` 实名 import，每个普通回合必经。
2. **Layer 6 是空壳**：`_check_triage_gate`（:415-434）只读进程内 `_triage_cache` 字典，未命中即默认放行（:433-434），从不调用真分诊门。
3. **缓存永无写入**：唯一写入入口 `cache_triage_result`（:505）全仓零调用方（生产与测试均无）——Layer 6 运行时恒放行。
4. **真门只在 REST 手动面**：`triage_message` 唯一消费点是 `coordination_api.py:207` `POST /triage/check`；`chat_pipeline`/`channel_router`/`room_turn_router`/`loops` 零调用。
5. **进料口已通、出料口未接**：`_fetch_conversation_history`（triage.py:332-343）已按 P1-10 从 `SessionSyncManager`（会话事件单一事实源）取最近 50 条消息事件——门有料可吃，无人把门装进流水线。
6. **伴生空转层**：Layer 5 新鲜度预检为自认简化版（:393-413，恒放行）；Layer 3c 唤醒去抖无实现（coordination_api.py:250-256 注记「仅在 glance_yield_rules.py 里有设计注记，无实现」）。
7. **另一半心智同样未接**：SmallBrainRouter 仅 `phase3_api` 端点可达，且分类是关键词规则；真实模型选择走 `effort_inference`+provider 链，从不咨询它。

### 1.3 成因

机制先行、消费滞后（本仓四域审计已点名的系统性通病）；Layers 1-4 因守护真实资源被生产化加固，Layers 5-6 需要跨模块闭环被搁置；P1-10 修复只接通了门的进料与诚实性，未接消费者；接不接自动路径的成本/延迟/误杀权衡长期悬置，门以 REST 手动面栖息。

### 1.4 影响面（不接留下什么）

| 影响点 | 后果 |
|---|---|
| 成本 | 房间/群聊 agent 互聊每条触发成员 agent 完整主模型管线（room_turn_router 逐成员 chat）；无廉价拦截（渠道群领导租约默认关 fail-open，room_post 限频是另一维度） |
| 风暴与记忆污染 | 回声对话写进 `room:<id>` 作用域记忆与房间转录，经 `build_room_history` 持续污染后续召回与生成 |
| 防御语义失真 | 七层宣称七层，实际 L5/L6 恒放行、L3c 缺失；`/triage/stats` 的 `triage_cache_size` 恒 0 |
| 小脑无生产验证 | 误杀率等关键参数从未在真实流量跑过，将来想接也没有 shadow 数据支撑 |
| 心智模型混乱 | `YieldReason.TRIAGE_GATE`、`cache_triage_result` 等接线预留让后来者误以为已生效 |

---

## 2. 目标与非目标

**目标**：Layer 6 在自动路径真实生效；**运行时零 LLM、零网络、零新增依赖**；单次判定亚毫秒；误杀可控（保守弃权+灰度晋升）、可观测（stats+样本留痕）、可回退（三档开关）。

**非目标**：不接 SmallBrainRouter 选模型半边（§10 D-SB4）；不动 Layers 1-4；不建第二套事件源/缓存/编排；不做任何安全/权限判定（那是审批链的事）。

---

## 3. 方案总览：规则守高置信区 + 自研微型模型守灰色区

关键洞察：分诊门 docstring 的判定依据**全是可计算信号**（人类距离、20 条独走环、复读、等待时长），模型只是这些信号的模糊分类器。把模型换成按同一规格实现的**确定性裁决器 + 微型学习模型级联**，即"按规格蒸馏"——判定边界不变，成本延迟故障面归零。

```
回合入口（既有活路径，不动）
  AgentRunLedger.acquire → requestYieldGate（turn_coordinator.py:143）
    → check_yield_rules Layers 1-4（现状不动）
    → Layer 6 _check_triage_gate（改造点 glance_yield_rules.py:415）
         │
         ▼
  TriageRuleEngine.evaluate(events)          ← SB-1 纯函数规则（无歧义区）
    events = SessionSyncManager.get_messages(conv_id, limit=50)  ← 复用 P1-10 进料口（triage.py:332，同步内存快照）
    ├─ R0/R1 人类在场 → 放行（零计算快路径）
    ├─ R2/R3 独走环/复读环 → 拦截（机器可证）
    └─ 灰色区 → NeuJudge.score(features)   ← SB-2 自研微型判定模型（<1ms）
         ├─ P <低阈值 → 拦截
         ├─ P >高阈值 → 放行
         └─ 弃权带 → 放行（保守默认，与原门"拿不准→响应"同构）
```

**为什么零 LLM 反而更科学**：判定依据即规格（原门 SIGNALS/EXAMPLES 全部可机械判定）；无网络调用即无 P1-10 类故障面（凭据/超时/解析）；同步完成（异步闸难题结构性消失）；无持久判定状态（每轮对窗口现算，人类消息一进窗口结论自动翻转——缓存陈化/永久静音风险被结构性消灭）；可回放可穷举测试；成本严格为零。

---

## 4. 确定性规则层（SB-1）

| 序 | 规则 | 判定 | 依据（原门规格出处 triage.py） |
|---|---|---|---|
| R0 | 窗口为空，或最后一条是人类消息 | 放行（跳过后续计算） | 原则 1"人在场→必响应" |
| R1 | 近 10 条事件存在人类消息，或近 5 分钟有人类活动 | 放行 | SIGNALS"Human message/reaction/read in last 10 messages"、"waiting >5 min" |
| R2 | agent 独走环：自最近人类事件起连续 agent 消息 ≥20 | 拦截 `agent_loop_no_human` | SIGNALS"Agent loop (>20 messages since human attention)" |
| R3 | 复读环：最近 6 条 agent 消息归一化（casefold+去标点空白，长度≥8）后重复 ≥3 次，或与本回合输入相似度 ≥0.9（stdlib difflib） | 拦截 `verbatim_loop` | SIGNALS"Repetitive coordination without progress" |
| R4 | 以上皆不命中 | 放行（保守弃权） | 原则 3"When unsure → actionable=true" |

设计要点：**无状态纯函数**（不维护跨轮计数、不需要 TTL）；R2 从最近人类消息起算；R3 设最小长度门槛防"好的/收到"误判；阈值（20/10/5min/6/3/0.9）= 原门自述值，模块常量 + env 可覆盖，不发明新口径。已知边界：reaction/read 信号事件源暂不提供，v1 不覆盖（R0/R1 已覆盖其绝大多数场景），如实登记。

---

## 5. 自研微型判定模型（SB-2/SB-3）

### 5.1 选型

| 候选 | 运行成本 | 依赖 | 结论 |
|---|---|---|---|
| 本地小 LLM（llama.cpp/0.5B） | 几十 ms+数百 MB+常驻进程 | 重 | 否：违反可选依赖纪律 |
| sklearn/torch | 中 | 新增重依赖 | 否 |
| 云端小模型（原设计） | 网络往返+token 费 | 无 | 否：被替换对象 |
| **hash 特征 + 逻辑回归（自研）** | **<1ms，权重几十 KB** | **零新增**（NumPy 已在仓内；无 NumPy 走纯 Python 退化路径） | **采用** |

### 5.2 特征

- **结构特征（主）**：距最近人类消息的事件/时间距离、agent 独走长度、复读率、消息速率、参与者 agent 数、长度统计（均值/方差/最长）、疑问句比例（确定性词表）、本回合输入与最近 agent 输出最大相似度——即 R1-R3 的连续化，模型学到的边界是规则边界的平滑推广（覆盖区一致、灰区有据内插）。
- **文本特征（辅）**：最近 10 条 agent 消息的词级 1-2gram + 字符 3gram，hashing trick 投 4096 维（不存词表、无 OOV）；每条截断 200 字符、参与消息封顶 10 条——特征提取哈希次数有硬上界，纯 Python 亦在 1ms 量级。

### 5.3 训练数据与标签（三级来源，全程离线）

1. **规则强标签自举（主力，零人工零 LLM）**：规则在无歧义区即完美标注器——人类在场窗口→正样本；≥20 独走/复读环窗口→负样本。
2. **人工标注回流**：enforce 期每次 skip 落特征快照，admin 经管理端点复核改标，进入下一轮训练集（SB-5）。
3. **离线 LLM 蒸馏（可选，明确不在运行路径）**：用现有 `SmallBrainTriageGate` 离线跑抽样窗口生成弱标签，成本封顶、人工触发——**已实施（D-SB1，`70d844735`：训练脚本 `--distill N` 配额制，默认 0 不启用；经 realGateTriageFn 复用同一份运行时分诊门）**。

数据源现成：会话 JSON、房间转录（RoomStore→SessionRepository）、请求归档 JSONL。训练/验证按**会话切分**（防同会话泄漏）；固定种子；产物带 `model_version/feature_version/data_fingerprint/eval_metrics`。

### 5.4 运行时形态

权重 JSON（偏置+稀疏非零权重，约 50–200KB）随仓带默认模型（v1 建议仅结构特征、文本权重留空——即规则的平滑版），部署可在数据根放重训版覆盖；懒加载单例（DCL+RLock，§3 规约）；权重常驻内存，推理无网络无磁盘读。加载失败（缺字段/版本不匹配/损坏）→ 诚实失败并**降级为仅规则模式**（规则层本身仍是闸，不 fail-open 到放行一切）。

### 5.5 评测与棘轮

复用 `neurova/benchmark/suite_eval.py` EvalCase 体系（case-first 红绿，案例标注来源与成本口径）；**不回退棘轮**：新模型产物仅在冻结验证集上指标（skip 精确率/误杀率/弃权率）不劣于现任才许替换默认权重；漂移监控：弃权率/跳过率/误救率持续输出，误救率超阈值自动告警回 shadow。

---

## 6. 被拦截回合的命运：skip，不是 park

`TRIAGE_GATE` 现为可重试让位原因，会让回合白等 200s——但"会话空转"不随等待自愈。因此新增**跳过语义**：Layer 6 拦截时返回 `YieldGateOutcome(proceeded=False, parkReason="triage_gate_skip")`，`AgentRunLedger.acquire` 据此**不执行该回合**——不建 run、不产生回复、落 DEBUG 日志 + `triage_skipped` 计数；与 `MODEL_PIN_VIOLATION` 的"挂起等人工"区分（空转跳过不值得人工续跑，也不占 park 槽位）。房间内可选发**低频系统提示**（复用 room_post 滑动窗口限频口径，每会话每小时至多一条）。跳过事实进 stats 面；H-4 账本不加新事件类型（高频细节不进账本，与 `member_chunk` 同纪律）。

---

## 7. 治理开关与灰度

沿 `swarm_acceptance_enabled`/`sleep_induction_enabled` 先例：设置键 `advanced.triage_gate_enabled` + env 覆盖，三档：

- `off`（默认）：行为与现状逐字节一致；
- `shadow`：恒放行，记录规则结论与模型概率（`triage_shadow_would_skip` 计数）；
- `enforce`：真拦截（仅"规则命中 或 模型 P<低阈值"才拦；模型只增拦不增放，误杀面只从规则侧评估）。

**晋升判据**：shadow 期累计 ≥500 次判定且误救率达标（误救率 = 被 skip 会话中 5 分钟内出现人类新消息的比例；高=静音了人类关心的内容）。stats 复用 `/coordination/triage/stats` 扩展字段。

---

## 8. 拆卡

### SB-1 确定性规则裁决器
- 内容：新模块 `neurova/collaboration/triage_rules.py`（`evaluate(events) -> Verdict{action, reason, features}` 纯函数）+ 全量单测。
- 红灯：构造 25 条纯 agent 消息无人类的会话 → 现状 `check_yield_rules` 恒放行，断言 `should_yield=True, reason=TRIAGE_GATE` 失败。
- 绿灯：同场景拦截；R0/R1/R2/R3 边界用例全过（19→20 条、长度<8 复读反例、人类第 8 条回归放行）。

### SB-2 微型判定模型推理器 + 默认产物
- 内容：`neurova/collaboration/neu_judge.py`（LR 推理 + 权重加载/校验/降级）+ 默认权重 `neu_judge_default.json`（仅结构特征）。命名：Neu 前缀沿 neuacp 系，Judge 指判定职能。
- 红灯：灰区窗口（如 12 条独走、低复读）规则放行、模型低 P → 断言拦截（纯规则下必失败）；权重损坏 → 断言降级为仅规则且不抛出。
- 绿灯：同输入两次推理概率逐位一致（无采样）；特征边界（空窗口/50 条封顶/200 字符截断）单测过。

### SB-3 离线训练脚本
- 内容：`scripts/training/train_neu_judge.py`（数据抽取→规则弱标注→训练→冻结集评测→产物生成）；固定种子可复现（同数据同种子权重逐字节一致）。
- 验收：对默认数据根跑通一次，产出带指纹与指标的产物；训练不引入任何运行时依赖。

### SB-4 Layer 6 接线 + skip 语义 + 三档开关
- 内容：`_check_triage_gate` 改造（规则+模型级联）；`turn_coordinator` 增 skip 语义、`agent_run_ledger.acquire` 映射不建 run；`app_settings.py` 增 `advanced.triage_gate_enabled`（off/shadow/enforce，默认 off）+ env 覆盖；退役旧 `_triage_cache` 字典（单一事实源=窗口现算）。
- 红灯：off 档同输入与现状逐字节同结论（防误伤）；enforce 档 R2 场景 `agent.chat` 不被调用、台账无新 run。
- 绿灯：shadow 档行为与 main 基线一致且 `triage_shadow_would_skip` 递增；skip 语义下不进 park 队列。

### SB-5 EvalCase 案例集 + 人工复核端点 + stats 透出
- 内容：分诊 EvalCase 案例集（构造窗口+期望结论，标注来源/成本口径，先 case 后修）；admin 复核改标端点（skip 样本特征快照回流训练集）；`/coordination/triage/stats` 扩展字段（checks/allows/skips{by_rule}/shadow_would_skip/误救率）。
- 验收：vitest/pytest 契约测试 + 治理页展示（前端最小改动可另批）。

### live-verify（合并验收）
真后端起房间：脚本驱动两 agent 互发 25 轮空转 → enforce 档第 20 轮起不再触发 `agent.chat`（台账无新 run、`triage_skips` 递增）；人类发一条消息 → 下一轮 agent 正常响应（复活验证）；shadow 档行为与基线一致。

---

## 9. 建议顺序

SB-1（规则，同时是模型训练数据来源，先落地当地基）→ SB-4（接线+开关，先 off/shadow）→ SB-2/SB-3（模型与训练）→ SB-5（案例集与回流）。SB-1/SB-2 理论可并行，但 SB-2 依赖 SB-1 的特征与标注口径，建议串行。

---

## 10. 待拍板

| 编号 | 问题 | 选项与推荐 |
|---|---|---|
| D-SB1 | 离线 LLM 蒸馏是否立项为可选项 | **已裁决并实施（2026-11-22 用户拍板，`70d844735`）**：立项为可选项、默认不启用——训练脚本 `--distill N` 配额制离线蒸馏，复用同一份运行时分诊门，失败诚实弃权 |
| D-SB2 | 模型弃权带初始宽度 | 0.25–0.75（推荐）/ 更窄 |
| D-SB3 | 默认模型是否随 v1 发布 | **已裁决并实施（2026-11-22 用户拍板）**：种子模型随仓发布（`neu_judge_default.json`，仅结构特征）；D-SB3 真实数据源同批落地——训练脚本 `--source real` 从数据根会话文件收割窗口（本仓实测 100 窗口训练通过） |
| D-SB4 | SmallBrainRouter（选模型半边）处置 | **已裁决并实施（2026-11-22 用户拍板）：先比后合退役（`365cb3916`）**——`neurova/llm/llm_router.py` 为选模型单源（能力驱动、已进主聊天链路），SmallBrainRouter 为关键词规则弱重复且零生产消费方（仅 phase3_api 三端点自展，前端零引用），整体退役并修正两处失实注释 |
| D-SB5 | shadow 晋升判据 | ≥500 次判定且误救率<1%（推荐）/ 固定 7 天 |

## 11. 明确不做

- 不建第二套编排/事件源/缓存（旧 `_triage_cache` 随 SB-4 退役）；
- 不引入任何运行时模型调用或新依赖（训练亦纯离线脚本）；
- 不动 Layers 1-4 与既有让位语义（仅新增 skip 分支）；
- 不做安全/权限判定（审批链领域）；
- 不为"看似有推进的空转"强行扩规则（保守弃权，靠 shadow 数据再议）。

## 12. 风险与诚实声明

- **灰区初期是"有依据的内插"而非"有标签的学习"**：靠宽弃权带 + 单调结构特征 + 人工审计回流逐步夯实；
- **标签偏差**：规则弱标签只覆盖无歧义区，灰区边界靠人工回流校准，模型永远不做安全判定；
- **reaction/read 信号缺失**：事件源暂只含 USER_MESSAGE/AGENT_REPLY，v1 不覆盖，已登记为已知边界；
- **单副本约束**：裁决器无状态，多副本下各副本现算结论一致，比原缓存设计更利得多副本（编排面单副本口径沿用）；
- **误杀的代价不对称性**是本方案保守取向的根据：漏放一轮空转（多烧一次调用）≪ 误杀一轮真工作。

## 13. 执行记录

**已实施（2026-11-22，本地 main 六笔提交，未推远端）：**

| 卡 | 提交 | 内容 |
|---|---|---|
| SB-1 | `2075c1ea0` | 确定性规则裁决器 `triage_rules.py`（R0-R4 + 11 特征单源），18 例绿 |
| SB-2 | `2d7c13480` | `NeuJudge` 微型判定模型 + 种子权重（命名经用户拍板），22 例绿 |
| SB-3 | `da9f5b707` | `train_neu_judge.py` 离线训练脚本 + model_version 加载策略修正，47 例绿，冻结集指标 accuracy/skipPrecision/skipRecall=1.0 |
| SB-4 | `52b2ebd99` | Layer 6 真实现（三档开关）+ skip 语义（不 park、终态 failed/triage_gate_skip）+ 五入口分支，27 例绿 |
| SB-5 | `e1202a3f2` | skip 样本回流存储 + admin 复核端点 + triage-v1 EvalCase 案例集 7 条，28 例绿 |
| 收官修复 | `9ae2f9b05` | /triage/stats 双源合并（live-verify 实测发现 Layer 6 计数器无端点透出的可观测性断点） |
| SB-6/D-SB4 | `365cb3916` | SmallBrainRouter 先比后合退役（净 −634 行）：选模型单源归 `llm/llm_router.py`，phase3_api 三端点/失实注释/集成测试用例同批清偿，13 例绿 |
| SB-7 | `ea81fd0ac` | 误杀率统计 `falseRescueStats`（skip 后 5 分钟人类救援窗口）接入 /triage/stats 第三源；开关切 shadow，33 例绿 |
| D-SB1/D-SB3 | `70d844735` | `triage_dataset.py`（真实会话窗口收割 + 规则/离线蒸馏弱标注）+ 训练脚本 `--source real/--distill` + 旧门异常契约修正；真实数据冒烟 100 窗口训练通过，17 例绿 |

- **A/B 回归**：受影响域全量串行（collaboration/evals/channels/benchmark + 五入口套件）**1762 passed / 3 failed**——失败均为预存 `test_swarm_room_integration.py::TestEscalationResolve` 顺序性失败，逐卡前后失败集合逐行一致，净增失败 0。
- **live-verify（9777 真后端，13/13 PASS）**：off 档真实回合计数冻结（零副作用）→ 运行时 PUT 切 enforce → 真实回合 `triage_checks` 0→1（**闸在自动路径真跑**）→ 人类在场回合零拦截 → `/triage/skip-samples` admin 端点在线。skip 拦截路径由 26 例接线测试以真实 SessionSyncManager 事件覆盖（人类触发型入口无法经 HTTP 构造纯 agent 环，如实登记）。
- **开关已开（shadow，2026-11-22）**：`data/app_settings.json` 的 `triage_gate_enabled=shadow`（运行时配置不入库），复启后端活体确认三链：`GET /settings` 回读 shadow、真实回合 `triage_checks` 0→1（闸在 shadow 档真跑）、`false_rescue` 读数与 `/triage/skip-samples` 端点在线——误杀率数据自此随流量积累，达标（≥500 次判定且误救率<1%）后可切 enforce。
- **误杀率真实数据已采集（shadow，2026-11-22，多 agent 剧本协作流量）**：moss nex-n2.6 蜂群接龙填窗 → 真实 `/v1/chat` 人类探针（进闸判定落 would-skip 样本）→ 分组救援对照。**13 样本 / falseKills=3 / 误杀率 0.2308**：A 组（+45s 人类回归）3/3 计误杀；B 组（+334.8s 回归，窗外）不计——5 分钟窗口边界判别力成立；C 组（无回归）与 legacy 0 误杀。规则分布 R3 verbatim_loop×11、R2 agent_loop_no_human×2。过程发现：① 闸窗口=SessionSyncManager（仅 USER_MESSAGE/AGENT_REPLY），房间仓库端点不可作资格依据；② moss 上游并发上限=1，共享限流器默认 8 并发致蜂群内部调用互撞 429→指数退避锁死，以 `max_concurrent=1` 启动配置串行化解决（构造参数正常配置，未改产品代码）。
- **判定数补齐 ≥500（shadow，2026-11-22）**：同进程 `triage_checks` 503（≥500，lv17b 端点驱动 4.8 分钟：`/coordination/yield-checker/check` 走生产闸全链路；真实回合驱动因 moss 延迟劣化 56s→100s+/回合中止于 42 次，如实登记）。误救率 3/22=13.6% 为**受控对照口径**——3 条误杀均系 +45s 注入回归；自然回归样本 0/19（含 3 条 legacy R2）。切 enforce 仍以自然流量积累的误救率为准，本批不作为达标依据。
- **开关切 enforce（2026-11-22 用户拍板：「大体上应该没有什么问题，如果有问题，后期再补救，再切回去」）**：`advanced.triage_gate_enabled=enforce`，经 `PUT /v1/settings` 热改（整段提交，无重启）。live-verify 双向（lv18b）：qualified 房（agent 独走窗）真回合 **0.0s 秒拦**，响应含 `triage_skipped=true`+`skip_reason`+`run_id`；人类在场新会话正常放行（R0 快路径，`triage_skipped=None`）。**回滚路径**：同一设置键热改回 `shadow`/`off` 即可（秒级生效）；enforce 期间以真实误杀反馈为准，出现误杀即回 shadow 复核阈值。
- **蒸馏增强与 0.4.0-neurova 晋升（2026-11-22）**：首轮真实蒸馏暴露三类瓶颈并修复——教师调用 429 连锁（节流 6s 修复）、skip 类稀缺致模型塌缩（triage_skips.jsonl 直训+类平衡权重+分层切分）、超长窗口顶爆教师 prompt（400 字符截断）。**0.4.0-neurova**（答案先行结果采矿+教师质量门+边界扫描）在真实评估集（83 行）对比 0.1.0-seed 全面占优（0.952/0.82/1.00 vs 0.795/0.60/0.17；seed 漏拦 15/18），已晋升默认权重。语义发现：moss 教师对深独走环持"active_work→actionable"异议，与 R2 拦截策略相悖且结果数据支持规则——训练管线已改为**规则 skip 窗不送教师审计**（教师只裁灰区与放行窗）。
- **阈值标定与软标签（2026-11-22，MiniMind 白盒蒸馏启发）**：新增 `calibrate_neu_judge.py`（真实评估集上扫 skip_p 网格，推荐零误拦下最激进阈值，--apply 写回产物并试载）；NeuJudge 产物支持 `thresholds` 字段（越界/倒置拒载）；教师置信度转软标签参与训练（类平衡权重仍按硬标签）。对 0.4.0-neurova 实测：skip_p=0.10 评估集**零误拦**、召回 0.7222；0.25 召回 1.0 但误拦 3（均为人为注入的 +45s 回归对照）。
- **外部数据集与合成灰区数据接入（2026-11-22，`b0c05033e` + 转换器头部窗口修正）**：按用户拍板「第一梯队三数据集全拿来做训练 + moss 合成灰区数据」——tau-bench/TheAgentCompany/ToolTalk 浅克隆经 `convert_external_datasets.py` 转换 360 会话（收割器兼容落盘，任务成败留元数据）；训练器新增 `external_labels.jsonl` 标签注入（同会话覆盖旧标签 + 灰区弃权窗补入 category=external 训练行，real/sweep 两源接线并透出 externalLabels/externalApplied 指标）；moss 合成两轮共 36 条教师标签（第二轮并发 6——上游并发上限经用户确认实为 **10**，修正前记「=1」，串行化是当时 429 风暴的止血方案）。**实验结论（同评估集 86 行=21 skip/65 allow，两产物同集对比）**：v7（外部尾窗+合成）任意阈值误拦 ≥4；v7b（转换器改头部窗口后重训）仍**无零误拦点**（0.05 档误拦 1/漏拦 6，0.25 档误拦 4/漏拦 0）；v6 现行产物保持零误拦（skip_p=0.25，召回 0.7143）——**v6 保留，v7/v7b 均不晋升**。两项数据面发现：① 长工具轨迹取尾部窗口会被规则判 skip，与「人类发起=放行」语义相反，教模型过度拦截（转换器已改头部 40 条窗口，人类任务消息留窗内，无人类消息的组合跳过）；② moss 写不出「无实质内容」的纯 agent 对话（20/24 生成失败，输出拒绝或非 JSON），合成数据定格全 allow 类——灰区 skip 类样本只能靠真实流量与边界扫描积累。
- **v8 隔离实验定论（2026-11-22，用户问「是否 v7 训练方法不对」）**：训练器与 `buildOutcomeSweepDataset` 增 `--exclude-agents`（按 agentDir 前缀整目录剔除窗口，数据源消融用）。v8 = V6 办法（sweep+distill 60）× 现在数据、**排除外部/合成目录**：冻结集 skipPrecision 0.50（v7b）→ **0.90**（v8）；86 行评估集上 v8 与 v6 现行产物**全部阈值下混淆矩阵逐格一致**（0.25 档均零误拦/漏拦 6，0.45 档均误拦 3/漏拦 3）——两产物权重不同（11 维全异、bias 0.2646 vs −0.3662）但对本评估集判定完全一致，说明判定由主导结构特征决定、**训练方法稳定可复现，v6 的零误拦不是运气**。**最终定论：v7/v7b 回归根因 = 外部轨迹窗口与合成窗口混入训练集（稀释真实灰区分布 + 挤占 60 条教师蒸馏配额，v7b distillUsed 仅 9/错误 5），非管线方法问题**；v8 与 v6 打平、不晋升，v6 继续担任线上权重。外部数据的正确用法留待后续：不进收割窗、只作特征语义升级的素材或独立域阈值档案。
- **标定目标显式化（2026-11-22，用户质疑「为什么只考评误杀率，不考评正确拦截率」）**：拦截精确率（skipP）/召回率（skipR）本就在评估表内，但推荐策略把「零误拦」设成唯一准则——这隐含「误杀代价>>漏拦代价」的业务假设，不应是默认真理。标定器新增 `--objective`：zero-fp（保守，默认）/ max-f1（正确拦截率与覆盖并重）/ cost（`--fp-cost`/`--fn-cost` 代价比可配）。86 行评估集复算：**max-f1 目标下 v7b（skip_p=0.25，误拦 4/漏拦 0，F1=0.913）反超 v6/v8（skip_p=0.45，误拦 3/漏拦 3，F1=0.857）**——「哪个产物更好」取决于误杀/漏拦代价比，属业务拍板项；默认仍 zero-fp（enforce 下误杀=静默终止工作回合，代价不对称的保守选择）。
- **偏离与修正**：① SB-2 任务书契约矛盾（权重方向 vs decide 映射）按计划 §3 裁决 p=「值得响应」概率；② SB-3 修正 model_version 精确比对缺陷（重训产物永不可加载）+ 合成数据零方差特征根因修复（亚型多样化+零方差权重置 0+指标透出）；③ SB-4 增 `triage_gate_errors` 计数器、`settleResult` skipped 守卫（防完成回调竞速洗掉 skip 终态）、SSE `skipped` 具名事件；④ live-verify 发现并修复 /triage/stats 双源未合流断点（`9ae2f9b05`）。
- **待拍板遗留**：D-SB1/D-SB3/D-SB4 已全部裁决实施（`70d844735`/`365cb3916`）。当前开关=**enforce**（2026-11-22 用户拍板，回滚路径见上）；种子模型仅结构特征、弃权带 0.25–0.75，按计划推荐值先行；D-SB1 蒸馏默认配额 0（人工触发才消费 LLM），真实数据 skip 类正样本待渠道流量积累。
