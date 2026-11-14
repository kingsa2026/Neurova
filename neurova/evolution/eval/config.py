"""文本级进化配置与开关。

字符 / 参数描述 200 字符 / 提示增长 ≤20%),这样两边对"膨胀"的判据同源。

开关语义(NEUROVA_TEXT_EVOLUTION):
  - 默认关(opt-in)—— 对齐项目 C10 评审闸"改行为的进化产物默认待审"的哲学,
  - 显式设 "1"/"true" 才开启;其余值(含未设置)均视为关闭。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EvolutionConfig:
    """一次文本进化运行的配置。"""

    # ── LLM 配置 ──
    # 空串表示用 llm_router 的默认模型(judge 用小模型省成本)
    judge_model: str = ""
    optimizer_model: str = ""

    # ── 优化参数 ──
    iterations: int = 10
    # 每轮并行的变异候选数（P1-7a，RRSI 对齐）：>1 时各候选拿不同的失败
    # 子集分片，过闸后并行评测、tune 分 argmax（平分保持先到）。
    # 默认 1 = 单线 lineage，行为与旧版逐字节一致。
    variants_per_round: int = 1
    # 主 runner 近平分盲选 tie-break（N7 决策）：top 两候选分差在噪声带内时，
    # 用匿名 A/B 选择器替代先到 argmax；无选择器时诚实回退。
    blind_tiebreak_enabled: bool = True
    # 留出集提升低于该值视为"无真实增益",保留基线。
    # P0 堵漏（2026-09-17）：原默认 0.0 + 判据 `after <= before + min + eps`，
    # judge 不可用时前后同为中性 0.5 → 浮点相等使 `<=` 为假 → **零增益被放行**。
    # 现在默认 0.01（要求可测量的真实提升），且"判分不可用"单独判拒绝
    # （judge_unavailable），不再依赖 0.0/0.5 这种边界相等。
    min_improvement: float = 0.01

    # 判分不可用时的回退判据：deterministic = 只用确定性可用性检查（非空/无异常），
    # 产出的提案强制人工复核；off = 保持 judge_unavailable 整轮拒绝。
    judge_fallback: str = "deterministic"

    # ── 例级不退化门（§8 前置 1，对照 Designer-RSI 的 matched replay gate）──
    # 留出集均值涨了不算过关：一条用例被改坏，可以被另一条的涨幅抵掉。
    # 撞坏的既有单例数超过该容忍度即拒（拒绝理由 `case_regression`）。
    # 默认 1 —— 留出集小时单例判分抖动会直接转成拒绝（noise_repeats 默认 0，
    # 未自动校准），故留一条缓冲；收紧到 0 即等价"一条都不许丢"。
    # 判分失败的单例不计入退化（落 unevidencedCases），也不因此放行。
    case_regression_allowance: int = 1

    # ── 锚定地板（P2-4，SkillGLoW 对比 2026-10-07）──
    # A = max(历史最优留出, 无技能基线)：候选只赢过**正在退化的现役基线**不算
    # 真增益，必须达到 A − accept_threshold 才可部署（信用不归因于退化）。
    # 无技能留出只在候选过基线门后评测（成本有界）。关 = 沿用旧语义
    # （只对比当前基线，不花无技能臂预算）。
    anchor_floor_enabled: bool = True

    # ── 约束闸──
    max_skill_size: int = 15_000
    max_tool_desc_size: int = 500
    max_param_desc_size: int = 200
    max_prompt_growth: float = 0.2
    # 语义保持阈值:余弦相似度(Jaccard 回退)低于此值判漂移
    semantic_similarity_threshold: float = 0.75

    # ── benchmark 回归门 ──
    # bench gain 低于 -tolerance 即拒绝变体(无论技能分多高)
    bench_tolerance: float = 0.02

    # ── 成本规则（P1-5，RRSI 对齐）──
    # ΔC ≤ β0 + β1·ΔS：候选文本相对基线的长度变化率（成本代理）不得超过
    # 免费额度 β0 加上"每单位实测增益可购买的预算 β1·ΔS"——微增益配大膨胀
    # 的候选被拒。判据位于留出集判定之后（先证明有真增益，再谈值不值）。
    cost_rule_enabled: bool = True
    cost_beta0: float = 0.10
    cost_beta1: float = 44.5

    # ── 泄漏审查（P0-3，评测前 critic）──
    # 确定性预检（背题标记/退化 no-op）恒开；LLM 六类审查默认关——
    # 打开后每次候选审查多一次 LLM 调用，故障时诚实降级不误杀。
    leak_llm_review: bool = False

    # ── 评测噪声地板（RRSI 对齐：接受阈值 = max(min_improvement, δ)）──
    # δ>0 表示已校准（历史校准产物回填或注入 NoiseBand 时的兜底来源）。
    # 0 = 未校准，判据回退 min_improvement——默认行为与旧版逐字节一致。
    noise_band_delta: float = 0.0
    # service 侧自动校准：对同一基线重复评测的次数。B3（survey §10.2）默认
    # 0→3：校准算式早已在（δ=z·sd），只差默认开——接受判据从此读
    # max(min_improvement, δ) 而非点值，单点噪声不再触发接受/拒绝。
    # 真臂预算已按 repeats×判据集计上（planRealArmTurns.noiseCalibration）。
    noise_repeats: int = 3
    # 校准置信系数：δ = noise_z × sd(重复评测得分)，z=2 ≈ 97.5% 单侧置信。
    noise_z: float = 2.0

    # ── 评测集 ──
    eval_dataset_size: int = 20
    train_ratio: float = 0.5
    val_ratio: float = 0.25
    holdout_ratio: float = 0.25
    # 真留出报告集占比（P0-2 holdout 防污染）：>0 且数据集无 heldout 时，
    # service 从 holdout 尾部按此比例划出 heldout——只做验收证据，永不参与
    # 接受/拒绝判定。D1（survey §10.2）默认 0.15 生产启用：机制与"永不参与判定"
    # 纪律早已在（carve_heldout + 决策后只读附带），默认 0 等于密封证据从不划出。
    # 判据侧守卫（holdout 至少留 1）由 carve_heldout 既有逻辑承担。
    # 本旋钮与 anchor_floor_enabled/noise_repeats 同族：单一出处即本 dataclass
    # 默认值，不走 evolution_settings（每条 EvolutionConfig 构造点各传一份设置值
    # 会让 API 路径与后台路径读到两个来源——教义第 6 条的双源形态）。
    heldout_ratio: float = 0.15
    seed: int = 42

    # ── 优化期间快速打分(省钱):judge 只对 val 集跑,训练集用重叠代理 ──
    fast_proxy: bool = True

    # ── 每任务成本账 + CoP + 成本软门（HN1/HC1，HarnessPro 对照 2026-11-13）──
    # CoP（Cost-of-Pass）的"通过"判分线：单例 composite ≥ cop_pass_score 记
    # 通过（judge 0..1 分制）。零通过 ⇒ CoP=None（无定义），不是 0。
    cop_pass_score: float = 0.5
    # 成本软门：候选臂执行成本（usage 快照差分，见 eval/cost_ledger.py）相对
    # 基线臂涨幅 > cost_soft_gate_ratio ⇒ 提案 requires_manual_review=True
    #（不自动应用、也不拒绝——钱的事人说了算）。enabled=False 为逃生门。
    cost_soft_gate_enabled: bool = True
    cost_soft_gate_ratio: float = 0.2

    # ── 可执行测试判据层（HN2/HC2，HarnessPro 对照 2026-11-13）──
    # 对 skill 类工件在 judge 之外建一层确定性断言判据（eval/exec_suite.py）：
    # 合成一次、全程冻结，基线与胜者各跑一遍；候选断言通过率低于基线 ⇒
    # exec_suite_regression 拒绝。size 是套件用例数（真臂预算按 2×size 计上）。
    exec_suite_enabled: bool = True
    exec_suite_size: int = 4

    # ── 评测集核选（HN6/HC6，HarnessPro 对照 2026-11-13）──
    # 评测集超过该容量时，按「难度加权多样性」贪心（eval/coreset.py）收缩到
    # K 个再走既有 split——判据集变小、评测成本不随语料线性走。0 = 不核选
    #（逐字旧行为）。
    eval_coreset_k: int = 0

    # ── R1 成本升选择键（2026-11-13，§10.2）──
    # 近平分成本 tiebreak：多变体轮里，增益达线且彼此近平分的候选集中，选文本
    # 长度最小者（文本臂成本代理，与 P1-5 同源）。盲选（judge 偏好）优先级
    # 更高；等长保持先到（确定性）。False = 纯 argmax。
    cost_tiebreak_enabled: bool = True
    # 成本硬门（默认关）：开启后，候选臂执行成本（usage 差分）相对基线臂
    # 涨幅 > cost_hard_gate_ratio ⇒ 直接拒绝（cost_gate_failed）。
    # 软门（人工复核）不受影响，两者可并存。
    cost_hard_gate_enabled: bool = False
    cost_hard_gate_ratio: float = 0.5

    # ── N1/N2/N3（§11.3 残差清偿，2026-11-13）──
    # N1 Pareto 多档交付：多变体轮幸存候选按 lite/standard/heavy 轮转指派执行
    # 档位并串行评测（turn 级档位真实生效、成本按档位归账），产出 (分数, 成本)
    # 非劣集随结果交付。默认关＝既有并行评测行为逐字节不变。
    profile_variants_enabled: bool = False
    # N2 候选集并行递归：多变体轮把非劣幸存者透出到结果，递归演化
    # （evolveRecursive pool_size>1）的下轮对池内每个基各跑一次进化。
    lineage_pareto_enabled: bool = False
    # N3 G-rollout 联合诊断：失败采集时每用例采样 G 次（>1 才启用），诊断按
    # 「全挂=stable / 部分挂=flaky」归因——区分稳定缺陷与偶发噪声。1 = 旧形态。
    diagnosis_rollouts: int = 1

    # ── V1 near-miss 有界修复通道（VideoEvolve 对照 2026-11-14）──
    # 被验证侧门（holdout_regression/coreset_recheck_failed/case_regression/
    # exec_suite_regression）拒绝、但开发增益为正的候选，带门别诊断进入修复轮
    # 的次数上限。0 = 关闭（拒绝即弃置，逐字旧行为）。生效值 = max(本配置,
    # 治理设置项)——治理抬底线，与 N3 同纪律。
    repair_rounds: int = 0


def text_evolution_enabled() -> bool:
    """文本级进化总开关,默认关。

    优先级:env(显式设置时赢过文件,开发/测试即时生效)>
    evolution_settings 文件(管理员 UI 高级选项)> 默认关。

    默认关的理由:进化会改技能/提示词正文,属"改行为"的产物——与
    skill_review_gate 的 C10 哲学一致,必须显式 opt-in。
    """
    env = os.environ.get("NEUROVA_TEXT_EVOLUTION", "").strip().lower()
    if env:
        return env in ("1", "true", "yes", "on")
    try:
        from neurova.evolution.evolution_settings import load_settings

        return load_settings().text_evolution
    except Exception:  # noqa: BLE001 - 设置层故障退回关闭(保守)
        return False
