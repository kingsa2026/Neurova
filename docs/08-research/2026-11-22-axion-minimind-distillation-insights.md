# Axion 1.0 与 MiniMind 方法学对照：NeuJudge 微型判定模型的蒸馏改进实录

> 日期：2026-11-22 · 状态：**已实施并完成真跑对比；0.4.0-axion 已晋升默认权重**
> 来源：[Axion 1.0 论文](https://arxiv.org/abs/2611.03233) · [项目页](https://axion1-0.github.io) · [bytedance/axion1_0](https://github.com/bytedance/axion1_0) · [jingyaogong/minimind](https://github.com/jingyaogong/minimind)
> 关联：[小脑分诊门接线与自研微型判定模型实施方案](../04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md)（NeuJudge、误杀率、enforce 晋升判据均在该计划）
> 纪律：本报告为研究笔记+实测记录；外部项目仅作方法学参考，不构成事实源。

## 1. 两个参照系是什么

**Axion 1.0**（字节跳动联合 Duke/UMD/Buffalo，Apache 2.0）：开源 agent 基础模型，
MoE 35B/122B（Qwen 底座），配方刻意极简——两段 SFT + 一段 RL，不用 mid-training/
DPO/在线蒸馏。18K 条轨迹训出在 HLE（59.0）等基准上与 Gemini 3.1 Pro 互有胜负的
模型，且**单模型赢了一个 "Agent Team" 多智能体基线**。

**MiniMind**（jingyaogong/minimind，Apache 2.0）：从零训练 64M/198M 超小语言模型
的教学级开源项目——纯原生 PyTorch（不依赖 transformers/trl/peft 封装），单卡
3090 约 3 元跑完 预训练→SFT→DPO→RLAIF→Agentic RL 全流程，另含白盒蒸馏
（CE+KL+温度缩放）。

两者与 NeuJudge 不在同一量级（基础模型 vs 亚毫秒逻辑回归），可迁移的是**方法学**：
答案先行的可验证标注、边界密集采样、小数据高密度、结果驱动的标签来源、诚实评测。

## 2. 方法映射（Axion → NeuJudge）

| Axion 1.0 的做法 | 在 NeuJudge 上的落地 |
|---|---|
| Stage II「先定答案、后出题」：参考答案由确定性程序先行算出，剔除"不用工具也能解"的题 | **结果采矿 `mineOutcomeLabels`**：skip 样本的标签由可观测结果决定——skip 后 5 分钟内会话出现人类消息=误杀(1)；否则真跳过(0)。规则高置信窗不占教师配额（规则直标免费） |
| Stage I「模型感知的边界增强」：组合/参数化/范围偏移/分类讨论，在基座已成功的策略附近加难 | **边界扫描 `boundarySweepWindows`**：真实种子窗口沿独走长度(5/10/20/30)、人类距离(0/3/6/10/15)、复读×3、人类疑问四轴参数化扰动；特征向量 sha256 去重——同特征变体共享一次教师标注 |
| 参考答案程序化核验 | **教师质量门 `teacherAgreement`**：先在结果已知的窗口上测教师（moss nex-n2.6）与结果的一致率，<0.7 即中止蒸馏——教师不可信时不浪费配额 |
| 小数据高密度（18K 轨迹训基础模型） | 教师配额只花在**边界附近的唯一特征向量**上（去重后 ≤60 个） |
| 评测棘轮 | 每轮重训必须在冻结集上不回退；真实误杀/确认正确的跳过沉淀为冻结案例 |

MiniMind 的补充启发：**白盒蒸馏→软标签**（教师置信度转软目标，逻辑回归损失天然
支持浮点标签）、**课程式训练**（规则自举→教师蒸馏→结果反馈三段递进）、**强模型
合成数据**（真实灰区流量稀缺时由 moss 合成对照窗口）、**诚实评测文化**（敢公布
接近随机的成绩并注明口径）。

## 3. 实施内容（均已提交）

- `neurova/collaboration/triage_axion.py`（新模块）：
  - `mineOutcomeLabels`：结果采矿。naive 时间戳按 CST/UTC 双解释兜底
    （房仓与旧库两种落盘口径并存）；
  - `boundarySweepWindows`：四轴扰动 + 特征向量 sha256 去重 + 每种子/全局封顶；
  - `teacherAgreement`：教师质量门；
  - `buildAxionDataset`：收割→规则直标→结果采矿→质量门→边界扫描→配额内
    教师标注（已知特征键免费继承）。
- `triage_dataset.py`：`labelWindows` 增 `distillScope="audit"`（教师复核规则已决
  窗口，裁决覆盖规则标签）；`realGateTriageFn` 种子内容按 400 字符截断
  （防教师 prompt 超 token：实测 11932>8192）；教师调用节流（最小间隔 6s，
  env `NEUROVA_DISTILL_TEACHER_MIN_INTERVAL` 可调）。
- `scripts/training/train_neu_judge.py`：`--source axion`（0.4.0-axion）、
  `--distill-scope`、`_ingestSkipFeedback`（triage_skips.jsonl 直训）、
  `_trainLogisticRegression` 类平衡权重（n/(2·类数)）、`_stratifiedSplit`
  （冻结集分层补救）。
- 测试：`test_triage_axion.py` 8 例 + `test_triage_dataset.py`/`test_train_neu_judge.py`
  增 10 例，全部先红后绿。

## 4. 实测结果

### 4.1 训练轮次演进（冻结集 = 真实窗口留出 split）

| 轮次 | 配置 | accuracy | skipPrecision | skipRecall | 问题 |
|---|---|---|---|---|---|
| 首轮 real | 无类平衡/无回流/无分层 | 1.0000 | 0 | 0 | 塌缩成全放行（skip 类全在训练侧） |
| v3 real | +skip 回流+类平衡+分层 | 0.7857 | 0.70 | 0.54 | 教师调用 101 次仅 12 成（moss 429） |
| **v5 axion** | +结果采矿+质量门+边界扫描 | **0.9762** | **0.75** | **1.00** | 教师成功 19 次（节流后 429 显著下降） |

### 4.2 同一真实评估集四方对比（83 行 = 18 条结果标注 would-skip + 65 条规则放行窗）

| 模型 | accuracy | skipPrecision | skipRecall | 漏拦(fn) | 误拦(fp) |
|---|---|---|---|---|---|
| 0.1.0-seed（晋升前默认） | 0.7952 | 0.6000 | 0.1667 | **15** | 2 |
| 0.3.0-real（v3） | 0.9277 | 0.7500 | 1.0000 | 0 | 6 |
| 0.4.0-axion（v5） | 0.9518 | 0.8182 | 1.0000 | 0 | 4 |
| **0.4.0-axion（v6，修正管线，已晋升）** | **0.9639** | **0.8571** | **1.0000** | **0** | **3** |

关键发现：**0.1.0-seed 在真实窗口上漏拦 15/18**——合成训练与真实分布的偏差实证；
v6 全召回且误拦最少（3 条均为人为注入的 +45s 回归对照被正确放行）。

**教师语义分歧的发现与处置（重要）**：moss 教师对深独走环给出
"active_work→actionable"式异议（审计标注会把 R2 拦截翻成放行），而结果数据
（真实 skip 样本几乎全部真跳过）支持规则。处置：训练管线改为**规则 skip 窗不送
教师审计、规则 skip 变体保持规则标签**——教师只裁灰区与放行窗。修复后 v6 的
skip 精确率 0.82→0.86、误拦 4→3。教训：**教师只在"结果不可知"处有发言权，
结果数据与既定策略优先**。

**阈值标定（calibrate_neu_judge.py 对 v6 实测）**：skip_p=0.25 时精确率 1.0
（零误拦）、召回 0.8333——15 条真跳过全召回、3 条人为注入误杀正确放行；
skip_p=0.10 召回 0.61 但同样零误拦。现值即最优工作点，阈值已显式写入产物
thresholds 字段。

**口径声明**：评估集的 allow 侧与训练集同源（规则标注），skip 侧的 23 条回流样本
也参与了 v3/v5/v6 训练——对比对蒸馏模型略有利；seed 侧为完全未见数据。晋升决策
同时参考了方向试打分（25 独走无人类 → p=0.0；人类在场 → p=0.43，该场景在级联中
由 R0/R1 规则先裁）。

### 4.3 过程事故与修复（如实登记）

- moss 对连续调用以 429 `concurrency_limit_exceeded` 应答：首轮蒸馏 101 次教师
  调用仅 12 次成功；端点驱动判定补齐时亦触发内部通道 120/min 限流（/health 被答
  429，看门狗误判失联）。修复：教师调用最小间隔 6s（env 可调）、驱动脚本降频。
- moss 延迟随持续调用劣化（~12s → ~100s/次）：真实回合判定驱动（lv16）因此中止；
  蒸馏配额从 100 降到 30/60 以控时。
- 后端进程一次无痕死亡（14:08，内存检索链中途，无 traceback）：重启恢复，
  限流器为进程内存态随之清零（判定计数重新积累）。
- `buildAxionDataset` 首跑漏返回 `grayUnlabeled` 致训练步 KeyError：补齐后重跑通过。

## 5. 对 harness 的额外启发（未实施，登记备查）

1. **单模型 vs Agent Team 的内置 A/B**：Axion 用单模型赢多智能体基线——蜂群编排
   可增加"单强模型 vs 团队"的对照评测模式，按验证结果与成本自动选边。
2. **答案先行的可验证任务生成**：任务书自带确定性判分器（对接 S4 验收门/候选制），
   为后续 RL 式自我改进铺路。
3. **TITO/R3 纪律**：训练数据逐字等于运行时所见（本仓 skip 样本已存特征快照，保持）。
4. **压缩段→训练窗**：S6/S15 压缩段可桥接为判定模型训练窗口。
5. **MiniMind 的成本透明**：每轮蒸馏报告教师调用数/耗时/token，让"换多少精度"
   可决策（本轮：约 220 次教师调用，成功 32 次）。

## 6. 同型参照：Jeff（firelex/jeff）决策函数库

Jeff 是一个 0.8B 的"System 1"决策模型产品化框架：把判断类问题封装成普通函数
调用（如 `jeff.safety.guard.attempt` 检测 prompt injection），毫秒级返回**带校准
置信度的类型化 Decision**，置信度不足即弃权。与 NeuJudge 高度同型——都是
"小模型 + 窄问题 + 弃权带"——它的产品化做法有四点可直接借鉴：

1. **校准置信度作为一等公民**：Decision 携带校准过的概率，而非裸分数。本仓
   的 `calibrate_neu_judge.py` 已迈出第一步（评估集上反推阈值），下一步可把
   校准曲线本身存进产物（如 isotonic/Platt 分段），让 p 值可直接当概率用。
2. **底座 + 领域 LoRA 适配器的目录（catalogue）**：同一底座按领域切换适配器。
   对应本仓：NeuJudge 可支持"按会话域加载不同权重/阈值档"（讨论型房间 vs
   写操作密集房间用不同配置），manifest 化管理。
3. **golden cases 即契约**：`contract/` 里放全仓 golden cases 作一致性测试。
   本仓 triage-v1 案例集同思路，应对齐到"每次误杀/每条确认跳过都进案例集"。
4. **窄问题单一职责**：一个决策函数只回答一个问题。NeuJudge 之外，本仓的
   升级判定、候选验收、升级到人等 judgment 点都可复用"微型模型 + 校准 +
   弃权"的同构做法。

差异：Jeff 面向"选项已知的分类决策"，NeuJudge 还承担窗口特征提取与规则级联
（R0-R4 前置），复杂度更高；Jeff 的本地引擎（Unix socket + INT4 底座）形态
对 NeuJudge 无直接需求（逻辑回归本就亚毫秒）。

## 7. 当前状态与后续

- **0.4.0-axion（v6，修正管线）已晋升为 `neu_judge_default.json`**
  （`d840607ea`），并写入标定阈值 `thresholds={skip_p:0.25, allow_p:0.75}`
  （v6 在评估集上该点精确率 1.0/召回 0.8333，为最优工作点）；enforce 档
  后端下次重启加载新权重与阈值（当前进程仍持旧模型，属预期）。
- 后续可选：教师置信度→软标签已落地（本轮）；moss 合成灰区窗口 datagen；
  影子分歧主动学习面板。
- 误救率晋升判据（≥500 判定且 <1%）中判定数已达标（503），误救率待自然流量积累。
