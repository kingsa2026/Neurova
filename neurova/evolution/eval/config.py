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
    # 留出集提升低于该值视为"无真实增益",保留基线
    min_improvement: float = 0.0

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

    # ── 评测集 ──
    eval_dataset_size: int = 20
    train_ratio: float = 0.5
    val_ratio: float = 0.25
    holdout_ratio: float = 0.25
    seed: int = 42

    # ── 优化期间快速打分(省钱):judge 只对 val 集跑,训练集用重叠代理 ──
    fast_proxy: bool = True


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
