# -*- coding: utf-8 -*-
"""P2-12 元认知事件游标 2000 截断静默越权红测（全库断点审计 2026-11-12）。

缺陷：reflect() 只取最近 2000 条事件（list_events limit=2000），游标写
max(截断集 id)——积压超过 2000 条时，更早的未编译事件被游标静默标记为
"已编译"，从此从未被任何算子看过。

修复口径（审计开方：分页取尽）：reflect 向前翻页取尽全部未编译事件
（台账有 _max_events 剪枝上界，翻页必然终止）。
"""
import pytest


@pytest.fixture
def engine(tmp_path):
    from neurova.cognitive_layers.meta_cognition_layer.ledger import MetaLedger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import SelfModelEngine

    ledger = MetaLedger(db_path=str(tmp_path / "meta.db"), max_events_per_agent=5000)
    return SelfModelEngine(agent_id="agent_cur", ledger=ledger)


def test_reflect_covers_all_events_beyond_2000(engine, monkeypatch):
    for i in range(2500):
        engine.ledger.write_event(
            agent_id="agent_cur", process_type="tool",
            description=f"tool_{i}", success=True,
        )

    seen: list = []
    original = engine._op_drift

    def _capture(ev, ob):
        seen.extend(int(e["id"]) for e in ev)
        return original(ev, ob)

    monkeypatch.setattr(engine, "_op_drift", _capture)
    engine.reflect()

    assert len(set(seen)) == 2500, (
        f"反思只看到 {len(set(seen))}/2500 条事件——游标截断把更早的未编译"
        "事件静默标记为已编译，永不补课"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
