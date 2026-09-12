"""RSI 端到端评测集 — gain 的统一度量（Auto Harness 思想）。

对比启发（jiuwenswarm Auto Harness：评测驱动优化 harness 本身）：

现状缺口：RSI 棘轮的 gain 来自 setpoint 梯度的"信号估算"——参数贴近度
满分不代表行为正确，棘轮缺少"整个 agent 是否变好"的端到端标尺。

设计：确定性评测集（零 LLM、纯内存、毫秒级），用例驱动四族可优化参数
的真实子系统行为（AdaptiveToolWeights / SleepConsolidation /
TemperatureEngine / ExperienceFeedback 的真实代码路径，隔离 fixture，
不触碰真实用户数据）。

真值契约：参数处于 setpoint（SYSTEM_SETPOINTS，即 RSI 的优化目标）时
全部用例满分。setpoint 表已对齐真实消费方的设计默认（2026-09-12 治理：
原表从 Agent 镜像属性抄写与文档/类默认冲突；merge_threshold 别名幻影移除；
pattern_min_support 经属性桥激活）。棘轮的候选都是朝 setpoint 的步进——
- 步进保持行为 → gain ≥ 0 → 保留；
- 漂移跨入有害区间（饱和/失活/过合并/过结晶）→ 对应用例失分 →
  gain < 0 → 棘轮自动回滚（run_iteration 既有机制）。
评测集因此是棘轮的"行为安全地板"，而非参数贴贴度复读机。
"""

import datetime
from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger
from neurova.evolution.experience_feedback import ExperienceFeedback

logger = get_logger(__name__)


def _param(live_params: Dict[str, Dict[str, Any]], system: str, name: str) -> Tuple[Any, bool]:
    """读活参数值；系统未暴露（None）时回退 setpoint（返回值, 是否回退）。"""
    from .system_performance import get_setpoint

    value = (live_params or {}).get(system, {}).get(name)
    if value is None:
        return get_setpoint(system, name), True
    return value, False


# ────── tool_memory 族 ──────


def _case_tm_multiplier_differentiation(live_params) -> Tuple[float, str]:
    """奖惩分化：近期同为 50% 成功率的两个工具，最近回暖者必须权重更高。

    敏感性：success_bonus→0（好工具不涨）或 failure_penalty→0（坏工具不跌）
    → 乘数并列 → 扣分。这是"工具权重仍是真实决策变量"的行为底线。
    """
    from neurova.evolution.closed_loop import AdaptiveToolWeights

    bonus, fb1 = _param(live_params, "tool_memory", "success_bonus")
    penalty, fb2 = _param(live_params, "tool_memory", "failure_penalty")
    decay, _ = _param(live_params, "tool_memory", "decay_rate")
    weights = AdaptiveToolWeights(
        success_bonus=float(bonus), failure_penalty=float(penalty), decay_rate=float(decay)
    )
    for ok in (False, False, False, False, True, True, True, True):
        weights.update_weight("tool_good", ok)
    for ok in (True, True, True, True, False, False, False, False):
        weights.update_weight("tool_bad", ok)
    margin = weights.get_effective_multiplier("tool_good") - weights.get_effective_multiplier(
        "tool_bad"
    )
    # 满分线 0.05：与设计默认 failure_penalty=0.05 对齐（该默认下
    # 好坏分化 margin≈0.06 应得满分；margin→0 的失活漂移仍被捕获）
    score = 1.0 if margin >= 0.05 else (0.5 if margin > 0 else 0.0)
    fallback = "（含 setpoint 回退）" if fb1 or fb2 else ""
    return score, f"乘数差 {margin:.3f}{fallback}"


def _case_tm_decay_forgetting_band(live_params) -> Tuple[float, str]:
    """遗忘带宽：闲置 2 小时的工具乘数必须下降但不许击穿下限。

    敏感性：decay_rate→0（永不遗忘，乘数原样）或 →1.0（瞬间清零击穿下限）
    → 扣分。
    """
    import datetime as _dt

    from neurova.evolution.closed_loop import AdaptiveToolWeights

    bonus, _ = _param(live_params, "tool_memory", "success_bonus")
    penalty, _ = _param(live_params, "tool_memory", "failure_penalty")
    decay, fb = _param(live_params, "tool_memory", "decay_rate")
    weights = AdaptiveToolWeights(
        success_bonus=float(bonus), failure_penalty=float(penalty), decay_rate=float(decay)
    )
    for _ in range(5):
        weights.update_weight("tool_x", True)
    weight = weights.get_weight("tool_x")
    pre = weight.adaptive_multiplier
    # last_used 是 datetime（update_weight 写 datetime.now(UTC)）
    weight.last_used = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=2)
    decayed = weights.get_effective_multiplier("tool_x")
    score = 1.0 if weights.min_multiplier < decayed < pre else 0.0
    return score, f"乘数 {pre:.3f} → 闲置后 {decayed:.3f}（下限 {weights.min_multiplier}）{ '（setpoint 回退）' if fb else ''}"


def _case_tm_threshold_band(live_params) -> Tuple[float, str]:
    """肌肉记忆阈值语义域：置信度类阈值必须落在 (0, 1]（越界即行为死亡）。"""
    value, fb = _param(live_params, "tool_memory", "muscle_memory_threshold")
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return 0.0, f"阈值非法: {value!r}"
    score = 1.0 if 0.0 < value_f <= 1.0 else 0.0
    return score, f"muscle_memory_threshold={value_f}{ '（setpoint 回退）' if fb else ''}"


# ────── sleep 族 ──────


def _sleep_fixture(live_params):
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    sim_thr, _ = _param(live_params, "sleep", "similarity_threshold")
    decay, _ = _param(live_params, "sleep", "base_decay_rate")
    return SleepConsolidation(similarity_threshold=float(sim_thr), decay_rate=float(decay))


def _case_sl_dedup_band(live_params) -> Tuple[float, str]:
    """相似合并带宽：近似重复对必须合并，不相关记忆必须幸存。

    敏感性：merge_threshold→1.0（欠合并：0.99 相似对也不再合并）或
    →0.05（过合并：0.2 相似的无关记忆被吞并）→ 扣分。
    """
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

    sleep = _sleep_fixture(live_params)
    dup_a = MemoryRecord(id="dup_a", content="dup a", embedding=[1.0, 0.0])
    dup_b = MemoryRecord(id="dup_b", content="dup b", embedding=[0.99, 0.141])  # cos≈0.99
    other = MemoryRecord(id="other", content="other", embedding=[0.2, 0.98])  # cos≈0.2
    merged_memories, _merge_results = sleep.consolidate([dup_a, dup_b, other])

    # 3 条 → 2 条（重复对合并、无关记忆幸存）。阈值 1.0 → 欠合并（3 条）；
    # 阈值 0.05 → 过合并（1 条）。
    did_merge = len(merged_memories) == 2
    other_survived = any(
        m.id == "other" and not m.merged_from for m in merged_memories
    )
    score = 1.0 if (did_merge and other_survived) else 0.0
    return score, f"3 条记忆整合后 {len(merged_memories)} 条（期望 2）, 无关记忆幸存={other_survived}"


def _case_sl_decay_band(live_params) -> Tuple[float, str]:
    """睡眠衰减带宽：闲置记忆温度必须下降但不许击穿归档线。

    敏感性：base_decay_rate→0（温度原样）或 →1.0（直接归档）→ 扣分。
    """
    import time as _time

    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

    sleep = _sleep_fixture(live_params)
    # 温度必须 <80：高温记忆被引擎视为固化不衰减（守卫分支）
    memory = MemoryRecord(
        id="m1",
        content="old memory",
        temperature=60.0,
        importance=0.5,
        emotion_score=0.0,
        created_at=datetime.datetime.now() - datetime.timedelta(days=5),
    )
    sleep.apply_sleep_decay([memory])
    score = 1.0 if sleep.archive_threshold < memory.temperature < 60.0 else 0.0
    return score, f"温度 60.0 → {memory.temperature:.1f}（归档线 {sleep.archive_threshold}）"


# ────── emotion 族 ──────
# 语义约定：情感保护参数按 TemperatureEngine 衰减语义解释（记忆衰减中
# 情感保护的实际消费方）；factor ≤1 = 保护，>1 = 惩罚（方向性违反）。


def _emotion_fixture(live_params):
    from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

    threshold, _ = _param(live_params, "emotion", "emotional_protection_threshold")
    factor, _ = _param(live_params, "emotion", "emotional_protection_factor")
    return TemperatureEngine(
        base_decay_rate=0.1,
        emotional_protection_threshold=float(threshold),
        emotional_protection_factor=float(factor),
    )


def _case_em_protection_direction(live_params) -> Tuple[float, str]:
    """保护方向（严格）：情感记忆（0.9）必须比中性记忆（0.1）衰减得更慢。

    setpoint factor=0.3（保护开启）下严格成立；factor→1.0（保护失活，
    两者同速）或 >1.0（情感记忆被加速遗忘）均失分——保护特性必须可观测。
    threshold 漂移出 [0,1] 语义域使 0.9 分记忆失去保护 → 同样失分。
    """
    engine = _emotion_fixture(live_params)
    last3 = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat()
    # 温度 60：高温(≥80)记忆被引擎视为固化不衰减
    r_emotional = engine.on_decay(60.0, last_accessed=last3, importance=0.5, emotion_score=0.9)
    r_neutral = engine.on_decay(60.0, last_accessed=last3, importance=0.5, emotion_score=0.1)
    t_e = float(r_emotional["new_temp"])
    t_n = float(r_neutral["new_temp"])
    score = 1.0 if t_e > t_n else 0.0
    return score, f"情感记忆 {t_e:.1f} vs 中性 {t_n:.1f}（须严格更慢）"


def _case_em_threshold_band(live_params) -> Tuple[float, str]:
    """保护阈值语义域：情感分数归一于 [0,1]，阈值越界即保护永久失活。"""
    value, fb = _param(live_params, "emotion", "emotional_protection_threshold")
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return 0.0, f"阈值非法: {value!r}"
    score = 1.0 if 0.0 < value_f <= 1.0 else 0.0
    return score, f"emotional_protection_threshold={value_f}{ '（setpoint 回退）' if fb else ''}"


# ────── experience 族 ──────


def _experience_fixture(live_params) -> Any:
    from neurova.evolution.experience_feedback import ExperienceFeedback

    min_obs, _ = _param(live_params, "experience", "crystallize_min_observations")
    min_rate, _ = _param(live_params, "experience", "crystallize_min_success_rate")
    fb = ExperienceFeedback()
    fb.crystallize_min_observations = int(min_obs)
    fb.crystallize_min_success_rate = float(min_rate)
    return fb


def _crystallized_count(min_obs, min_rate, successes: int, failures: int) -> int:
    fb = _experience_fixture({"experience": {
        "crystallize_min_observations": min_obs,
        "crystallize_min_success_rate": min_rate,
    }})
    tool = "tool_probe"
    for _ in range(successes):
        fb.process_experience(f"使用 {tool} 成功完成", task_type="probe")
    for _ in range(failures):
        fb.process_experience(f"{tool} 失败", task_type="probe")
    return int(fb.get_feedback()["crystallized_patterns"])


def _case_ex_crystallization_band(live_params) -> Tuple[float, str]:
    """结晶门槛带宽（三个子断言）：
    4 观察 75% 必须结晶（欠严查）/ 2 观察 90% 不得结晶（门槛过松）/
    6 观察 33% 不得结晶（成功率门槛失守）。
    """
    min_obs, _ = _param(live_params, "experience", "crystallize_min_observations")
    min_rate, _ = _param(live_params, "experience", "crystallize_min_success_rate")
    sub_qualified = (
        _crystallized_count(min_obs, min_rate, successes=3, failures=1) == 1
    )
    sub_under_qualified = (
        _crystallized_count(min_obs, min_rate, successes=2, failures=0) == 0
    )
    sub_low_quality = (
        _crystallized_count(min_obs, min_rate, successes=2, failures=4) == 0
    )
    score = (sub_qualified + sub_under_qualified + sub_low_quality) / 3.0
    return score, f"合格结晶={sub_qualified}, 欠观察不结晶={sub_under_qualified}, 低质不结晶={sub_low_quality}"


def _case_ex_pattern_support_band(live_params) -> Tuple[float, str]:
    """模式支持度带宽（桥接链路实测：属性 setter → PatternMiner.min_support）：
    3 次出现的序列必须被挖掘（过严查）/ 1 次出现的不得被挖掘（过松查）。
    """
    from neurova.evolution.closed_loop import PatternMiner

    support, _ = _param(live_params, "experience", "pattern_min_support")
    fb = ExperienceFeedback()
    miner = PatternMiner()
    fb.attach_pattern_miner(miner)
    fb.pattern_min_support = support

    for _ in range(3):
        miner.add_sequence(["tool_alpha", "tool_beta"])
    miner.add_sequence(["tool_gamma", "tool_delta"])
    patterns = {tuple(p.tools) for p in miner.mine()}

    frequent_mined = ("tool_alpha", "tool_beta") in patterns
    rare_excluded = ("tool_gamma", "tool_delta") not in patterns
    score = (frequent_mined + rare_excluded) / 2.0
    return score, f"min_support={miner.min_support}, 高频挖掘={frequent_mined}, 低频排除={rare_excluded}"


# ────── 主类 ──────

EVAL_CASES = [
    ("tm_multiplier_differentiation", "tool_memory", _case_tm_multiplier_differentiation),
    ("tm_decay_forgetting_band", "tool_memory", _case_tm_decay_forgetting_band),
    ("tm_threshold_band", "tool_memory", _case_tm_threshold_band),
    ("sl_dedup_band", "sleep", _case_sl_dedup_band),
    ("sl_decay_band", "sleep", _case_sl_decay_band),
    ("em_protection_direction", "emotion", _case_em_protection_direction),
    ("em_threshold_band", "emotion", _case_em_threshold_band),
    ("ex_crystallization_band", "experience", _case_ex_crystallization_band),
    ("ex_pattern_support_band", "experience", _case_ex_pattern_support_band),
]


class RSIEvalHarness:
    """端到端评测集：四族参数 × 8 用例，输出 0..1 统一分数。

    run() 完全确定性、零 LLM、零磁盘 IO、毫秒级——可在每次棘轮
    应用前后各跑一次作为 gain 度量。
    """

    def run(self, live_params: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        cases: List[Dict[str, Any]] = []
        for case_id, family, fn in EVAL_CASES:
            try:
                score, detail = fn(live_params)
            except Exception as e:  # noqa: BLE001 - 坏参数可致子系统抛异常：该用例 0 分，评测不炸
                score, detail = 0.0, f"case error: {e}"
            cases.append(
                {"id": case_id, "family": family, "score": round(float(score), 4), "detail": detail}
            )
        overall = sum(c["score"] for c in cases) / len(cases) if cases else 0.0
        return {"score": round(overall, 6), "cases": cases}
