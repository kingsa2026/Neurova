"""P2-3 质量罚分等价核对（OpenSpace quality/types.py:83-116）

核对结论：Neurova AdaptiveToolWeights 已具备滑动窗口/乘数夹紧/惰性衰减/
连续成败累进奖惩（update_weight），**缺小样本免疫**——OpenSpace 规定调用
<3 次不受罚（一次网络抖动不得把工具权重打到 0），Neurova 原实现 1 条失败
观测 → 窗口成功率 0 → 有效权重 0，误伤方向与"声明未接线"病灶同类。

增量语义：免疫只作用于成功率基座（rate），乘数（bonus/penalty 几何累进）
照常记录方向——阈值齿轮（get_effective_multiplier 消费）行为不变。
"""

from neurova.evolution.closed_loop import AdaptiveToolWeights


def test_single_failure_small_sample_immune():
    """1 次失败：rate 不罚（=1.0），有效权重仅乘数小幅回落（0.95），不得归零。"""
    w = AdaptiveToolWeights()
    w.register_tool("t")
    w.update_weight("t", False)
    eff = w.get_effective_weight("t")
    assert eff > 0.9, f"小样本免疫失守：单次失败有效权重 {eff}"
    assert eff < 1.0, "方向性保留：乘数仍须反映失败（阈值齿轮不失明）"


def test_second_failure_still_immune_until_three():
    w = AdaptiveToolWeights()
    w.register_tool("t")
    w.update_weight("t", False)
    w.update_weight("t", False)
    eff = w.get_effective_weight("t")
    # rate 免疫 1.0 × 乘数(0.95²)≈0.9025 → 仍 >0.85
    assert eff > 0.85


def test_full_penalty_after_enough_observations():
    """≥3 条观测起，窗口成功率语义全面生效（全失败 → 近零）。"""
    w = AdaptiveToolWeights()
    w.register_tool("t")
    for _ in range(3):
        w.update_weight("t", False)
    eff = w.get_effective_weight("t")
    assert eff < 0.1


def test_windowed_semantics_preserved_beyond_threshold():
    """免疫只对小样本：4 观测 3 成 1 败 → rate 0.75 参与乘算（非 1.0）。"""
    w = AdaptiveToolWeights()
    w.register_tool("t")
    for ok in (True, True, True, False):
        w.update_weight("t", ok)
    rate = w._windowed_success_rate(w.get_weight("t"))
    assert abs(rate - 0.75) < 1e-9


def test_legacy_lifetime_counts_also_immune_small():
    """旧持久化（window 空、终身计数 <3）同样免疫。"""
    w = AdaptiveToolWeights()
    w.register_tool("t")
    entry = w.get_weight("t")
    entry.window = []
    entry.success_count = 0
    entry.failure_count = 2
    assert w._windowed_success_rate(entry) == 1.0
    entry.failure_count = 5
    assert w._windowed_success_rate(entry) == 0.0
