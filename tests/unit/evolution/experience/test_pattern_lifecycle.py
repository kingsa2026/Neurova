"""017 · "通过门控"不等于"永久固化"（红绿灯 TDD）。

审计里最隐蔽的一条级联：门越好 ⇒ 越固化。结晶器把自述成功率直接写成温度
（`temperature = rate * 100`），而温度策略里「`>= 80` 不衰减」把高温当固化——
于是**一次好读数换来永久豁免**，且 `MemoryType.PATTERN` 没有任何淘汰分支。

落定契约：
1. 自述成功率不得跨进豁免区：温度上限落在 80 之下（本轮取 75），
   PATTERN 节点与其他记忆一样参与衰减——淘汰路径即衰减本身；
2. 豁免只可来自**人工升格**（`is_crystallized`，管理页/API 已在用这条通道），
   不得来自单次自述。本票同时锁住这条通道仍然有效（防止有人"顺手删掉固化"）；
3. 反向锁：被持续取用/采纳的高价值经验，一个衰减周期内不得被清零——
   006 的检索记账（每次命中 +10）必须能跑赢一次衰减。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine


@pytest.fixture(autouse=True)
def _direct_write_store(monkeypatch):
    """关掉 LLM 裁决闸 ⇒ 规则预筛通过即入库，本票测的是入库后的温度语义。"""
    monkeypatch.setenv("NEUROVA_CRYSTALLIZATION_LLM_GATE", "0")


def _crystallize(make_crystallizer, successes):
    cryst, engine = make_crystallizer()
    for ok in successes:
        cryst.observe(tool_name="pdf_export", context="导出季度报表", success=ok)
    return cryst, engine


class TestSelfReportCannotGrantExemption:
    def test_perfect_rate_lands_below_the_no_decay_line(self, make_crystallizer):
        _cryst, engine = _crystallize(make_crystallizer, [True, True, True])
        assert engine.stored, "对照：模式确实结晶入库了"
        node = engine.stored[-1]
        assert node.temperature < 80.0, (
            f"自述成功率 {node.metadata['success_rate']} 换来的是免衰减豁免区：{node.temperature}"
        )

    def test_crystallized_pattern_still_decays(self, make_crystallizer):
        _cryst, engine = _crystallize(make_crystallizer, [True, True, True])
        node = engine.stored[-1]
        verdict = TemperatureEngine().on_decay(node.temperature, days_idle=30.0)
        assert verdict["decay_amount"] > 0.0, "闲置一个月的结晶模式必须可降权（当前必红：不衰减）"

    def test_rate_still_orders_patterns(self, make_crystallizer):
        """温度不再通向豁免，但排序信息不得丢：高成功率仍应更热。"""
        _c1, strong = _crystallize(make_crystallizer, [True, True, True])
        _c2, weak = _crystallize(make_crystallizer, [True, True, False])
        assert strong.stored[-1].temperature > weak.stored[-1].temperature


class TestManualPromotionStillExempts:
    def test_is_crystallized_channel_remains_exempt(self):
        """人工升格是唯一正当的豁免来源，本票不得顺手把它删掉。"""
        verdict = TemperatureEngine().on_decay(60.0, days_idle=90.0, is_crystallized=True)
        assert verdict["decay_amount"] == 0.0
        assert verdict["lifecycle_stage"] == "crystallized"

    def test_self_report_alone_does_not_set_the_flag(self, make_crystallizer):
        _cryst, engine = _crystallize(make_crystallizer, [True, True, True])
        node = engine.stored[-1]
        assert not (node.metadata or {}).get("is_crystallized"), (
            "结晶入库不得自带人工升格标志"
        )


class TestPersistentUseIsNotZeroed:
    def test_retrieval_credit_outpaces_one_decay_cycle(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine,
            UnifiedMemoryNode,
        )

        engine = CognitiveStorageEngine(agent_id="cse-017", data_dir=str(tmp_path / "cse"))
        try:
            nid = engine.store(UnifiedMemoryNode(content="pattern_hot_export_flow", temperature=75.0))
            engine._flush_l0_to_l1()
            after_decay = TemperatureEngine().on_decay(75.0, days_idle=30.0)["new_temp"]
            engine.retrieve("pattern_hot_export_flow", limit=5)
            row = engine._db.execute(
                "SELECT temperature FROM memories WHERE id = ?", (nid,)
            ).fetchone()
            assert row[0] > after_decay, "被持续取用的模式应能跑赢一个衰减周期（反向锁）"
        finally:
            engine._db.close()
