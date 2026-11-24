# -*- coding: utf-8 -*-
"""D7：召回质量三态温度对照基准（证据，不是门禁；手动跑，零模型费用）。

问题：D5 让记忆温度重新有区分度后，融合召回的排序质量是升是降？温度
通道权重是否需要调整？

三态对照（同一语料、同一查询集，只变温度分布）：
- 态 A 旧世界：全库 100°（D5 前的均匀态，温度通道无区分度）
- 态 B 现状：全库 60°（R6 重置后的当下）
- 态 C 使用塑形：热点 90+ / 常用 70-85 / 闲置 30-50 / 长尾 <30（D5 设计终态）

语料 64 条（SQL 直插，词法通道打分——温度问题是受控变量，文本相关性
三态恒定）：近期热点 8 / 老而重要 8 / 冷门强相关 8 / 易混淆对 12 / 干扰 28。
查询 22 条分四类，各有明确预期。

指标：Hit@5 / MRR（整体 + 分四类）+ 温度通道贡献度（C 态去温度通道对照）。
判定（事先钉死）：态 C 整体 MRR ≥ 态 A；冷门强相关类 MRR(C) ≥ 90%×MRR(A)；
温度通道不得拖累召回（D8 判据：含温度通道 MRR ≥ 去温度通道）。

评测核心在 neurova/benchmark/recall_quality.py（与自动调参工具共用）。
"""
from __future__ import annotations

import pytest

from neurova.benchmark.recall_quality import (
    build_seeded_manager,
    evaluate_state,
    make_engine,
    run_recall_queries,
)

pytestmark = [pytest.mark.timeout(300)]


def _print_table(results: dict, extra: dict | None = None) -> None:
    print("\n===== D7 三态召回质量对照 =====")
    print(f"{'状态':<16}{'Hit@5':>8}{'MRR':>8}  {'热点':>7}{'老重要':>7}{'冷门':>7}{'混淆':>7}")
    for state, m in results.items():
        print(f"{state:<16}{m['hit5']:>8.3f}{m['mrr']:>8.3f}  "
              f"{m['recent_hot']['mrr']:>7.3f}{m['old_important']['mrr']:>7.3f}"
              f"{m['cold_relevant']['mrr']:>7.3f}{m['confusable']['mrr']:>7.3f}")
    if extra:
        print(f"\n温度通道贡献度（C 态）: 含温度通道 MRR {extra['with_temp_mrr']:.3f}"
              f" / 去温度通道 MRR {extra['mrr']:.3f}")


def test_recall_quality_three_temperature_states(tmp_path):
    results: dict = {}
    for state in ("A", "B", "C"):
        label = {"A": "A_uniform100", "B": "B_uniform60", "C": "C_shaped"}[state]
        results[label] = evaluate_state(str(tmp_path / f"recall_{state}.db"), state)

    # 温度通道贡献度：同一个 C 态 manager 上跑两遍（含/去温度通道）——
    # 同一快照同一时间戳，逐位可比
    manager_c, role_to_id, queries = build_seeded_manager(
        str(tmp_path / "recall_C_paired.db"), "C"
    )
    engine_c = make_engine(manager_c)
    from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

    without_channels = [c for c in RecallChannel if c != RecallChannel.TEMPERATURE]
    with_temp = run_recall_queries(engine_c, queries, role_to_id)[0]
    without_temp = run_recall_queries(
        engine_c, queries, role_to_id, channels=without_channels
    )[0]
    extra = {"with_temp_mrr": with_temp["mrr"], "mrr": without_temp["mrr"]}
    _print_table(results, extra)

    # 事先钉死的判定（方案 §D7）
    assert results["C_shaped"]["mrr"] >= results["A_uniform100"]["mrr"], (
        f"使用塑形态整体 MRR 不得低于旧均匀态："
        f"C={results['C_shaped']['mrr']:.3f} vs A={results['A_uniform100']['mrr']:.3f}"
    )
    cold_c = results["C_shaped"]["cold_relevant"]["mrr"]
    cold_a = results["A_uniform100"]["cold_relevant"]["mrr"]
    assert cold_c >= cold_a * 0.9, (
        f"冷门强相关类退化超限：C={cold_c:.3f} vs A={cold_a:.3f}"
    )
    # D8 判定：温度通道不得拖累召回（实测它曾把 MRR 0.751 拖到 0.459）
    assert extra["with_temp_mrr"] >= extra["mrr"], (
        f"温度通道拖累召回：含温度通道 {extra['with_temp_mrr']:.3f}"
        f" < 去温度通道 {extra['mrr']:.3f}"
    )
