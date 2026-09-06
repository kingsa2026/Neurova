"""认知三链路巡检 P1-5/P2 防回归：台账读取的 kind 过滤必须在 SQL 层。

P1-5：reflection_history 先取最新 limit 条再在 Python 过滤 kind——
thought/lesson 占满窗口时更早的 reflection 永远翻不到（前端反思
时间线"看起来从没反思过"）。
P2：check_tool_advisory 同款漏斗——无 kind 过滤，thought 记录把活跃
avoid_tool 教训挤出最新 50 条窗口，调控门静默失效。
"""
import pytest

from neurova.cognitive_layers.meta_cognition_layer.ledger import MetaLedger


@pytest.fixture
def ledger():
    return MetaLedger(db_path=":memory:")


def test_reflection_history_survives_thought_flood(ledger):
    """先灌 30 条 thought，再灌 3 条 reflection——时间线必须能取到 reflection。"""
    for i in range(30):
        ledger.create_record(agent_id="a", kind="thought", type="monitoring", content=f"t{i}")
    for i in range(3):
        ledger.create_record(
            agent_id="a", kind="reflection", type="monitoring", content=f"反思报告 {i}"
        )

    history = ledger.reflection_history(agent_id="a", limit=10)
    assert len(history) == 3, (
        "reflection_history 必须在 SQL 层按 kind='reflection' 过滤；"
        "Python 侧后过滤会让 thought 挤占窗口导致时间线漏报"
    )


def test_check_tool_advisory_survives_thought_flood(ledger):
    """avoid_tool 教训被 50 条 thought 压在窗口外时仍必须可查到。"""
    for i in range(50):
        ledger.create_record(agent_id="a", kind="thought", type="monitoring", content=f"t{i}")
    ledger.create_record(
        agent_id="a",
        kind="lesson",
        type="monitoring",
        content="避免用 tool_z",
        metadata={"subject": "tool_z", "recommendation": "avoid_tool"},
    )

    from neurova.cognitive_layers.meta_cognition_layer.self_model import SelfModelEngine

    engine = SelfModelEngine(agent_id="a", ledger=ledger)
    advisory = engine.check_tool_advisory("tool_z")
    assert advisory is not None, "SQL 层 kind 过滤缺失时教训被挤出窗口，调控门静默失效"
    assert advisory.get("recommendation") == "avoid_tool"
