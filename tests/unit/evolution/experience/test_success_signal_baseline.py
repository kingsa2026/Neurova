"""成败信号基线（工单 001 落点，工单 002 已转绿）。

本文件的基线用例断言的是修复后的目标态，期望值由
`agent/loops/base.py` 的记录形态手工推得（独立真相源），不由被测代码反算。
001 交付时它们**刻意为红**（那是当时唯一的证据）；002 把 `success` 位接上
`resolve_tool_outcome` 后逐条转绿。

审计实测（2026-09-19，生产库 91 条）：`success` 全为 1、`confidence_score` 0/91 非空。
原因链见 `docs/specs/2026-09-19-experience-quality-gate-audit.md` L1：
`post_chat_pipeline.py:1612` 的 `any(tm.get("success", True) ...)` —— `tool_call`
记录根本没有 `success` 键，于是"任一工具失败"与"从未调用工具"都被读成成功。
"""

def test_failed_tool_result_must_not_record_a_successful_experience(experience_probe,
        tool_records):
    """任一工具结果失败 ⇒ 这轮经验不得记为成功。

    修复前必红（002 已转绿）：`any()` + `tool_call` 缺 `success` 键 ⇒ 同一条 `tool_call` 投的
    `True` 票足以让整轮"成功"，落库 `success` 恒 1。
    """
    outcome = experience_probe.run_turn(tool_messages=[
        tool_records.call("pdf_export"),
        tool_records.result("pdf_export", success=False, result="磁盘写入失败"),
    ])

    assert outcome["facade_success"] is False, (
        "含失败工具结果的轮次仍被当成成功送进进化链："
        f" {outcome['facade_success']!r}")
    assert outcome["rows"], "经验未落库，本用例无法判据落库侧"
    assert outcome["rows"][-1]["success"] == 0, (
        f"落库 success 位没有携带信息：{outcome['rows'][-1]}")


def test_turn_without_tools_is_no_evidence_not_success(experience_probe):
    """没有任何工具结果 = 无证据，不得记成成功。

    判据要能区分"确实没有改善空间"与"这轮压根没有客观回执"——
    后者冒充前者，正是恒真信号让门槛退化成盖章机的机制。
    """
    outcome = experience_probe.run_turn(tool_messages=[])

    assert outcome["facade_success"] is None, (
        "无工具轮被写成成功票（应落无证据）："
        f" {outcome['facade_success']!r}")


def test_all_success_turn_still_records_success(experience_probe, tool_records):
    """反向锁：不得靠"一律记失败"把上面两条蒙绿。"""
    outcome = experience_probe.run_turn(tool_messages=[
        tool_records.call("web_search"),
        tool_records.result("web_search", success=True, result="已找到 5 条"),
        tool_records.call("summarizer"),
        tool_records.result("summarizer", success=True, result="摘要完成"),
    ])

    assert outcome["facade_success"] is True
    assert outcome["rows"][-1]["success"] == 1


def test_experience_rows_carry_agent_ownership(experience_probe, tool_records):
    """落库必须带得上归属：审计实测生产 91 行里仅 25 行有 agent_id，
    而检索按 agent 精确匹配（`experience_knowledge_base.py:400-402`）
    ⇒ 其余条目对任何 agent 永不可见。本批不改归属口径，先把它钉成可见的断言。
    """
    experience_probe.run_turn(tool_messages=[
        tool_records.call("pdf_export"),
        tool_records.result("pdf_export", success=True),
    ])

    row = experience_probe.experience_rows()[-1]
    assert row["agent_id"] == "agent-probe-01", (
        f"经验条目归属丢失，检索侧将永远看不见它：{row}")


def test_no_evidence_turn_is_tagged_not_recorded_as_failure(experience_probe):
    """无证据轮既不得记成功、也不得伪装成失败 —— 必须被标成"无证据"。

    D1 的取舍是"保留量 + 标证据"：库里要能把"确证失败"与"这轮没有客观回执"分开，
    否则 007 的检索降权与 008 的指标都会把两者混成一锅。
    002 交付时这格挤在 `tags` 字符串里；工单 008 把它升成一等列 `evidence_state`
    （本用例随之改写：列上有值、tags 里不再有那个字符串 hack）。
    """
    experience_probe.run_turn(tool_messages=[])

    row = experience_probe.experience_rows()[-1]
    assert row["success"] == 0, f"无证据轮被写成成功票：{row}"
    assert row["evidence_state"] == "unevidenced", (
        f"无证据轮没有可区分的证据列，将与确证失败同等降权：{row}")
    assert "unevidenced" not in (row["tags"] or ""), "字符串 hack 已退役，不得两处各写一份"
