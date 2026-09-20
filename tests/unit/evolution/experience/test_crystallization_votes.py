"""无证据观察不得投票（工单 003 对结晶门的直接后果）。

`success` 三态贯通后，结晶缓冲里会出现 `None` 观察。旧实现用
`sum(1 for e in entries if e["success"])` 算成功率 —— `None` 与 `False` 同为假，
于是"这轮没有客观回执"被算成一张失败票：`test_experience_recorded_crystallizer.py`
断言的"纯对话轮也要进结晶缓冲"就会反向失效（三次闲聊被判成失败模式）。

判据看的是候选有没有越过统计预筛（工单 005 之后入库还要再过 LLM 裁决，
所以"没入库"不再等价于"被门槛拦住"）。
"""


def _passed_prescreen(cryst, engine) -> bool:
    return bool(cryst.list_pending()) or bool(engine.stored)


def _observe(cryst, outcomes):
    for success in outcomes:
        cryst.observe(tool_name="pdf_export", context="导出季度报表", success=success)


def test_unevidenced_observations_vote_neither_way(make_crystallizer):
    """三次无证据观察：既不结晶成"成功模式"，也不被算成失败模式。"""
    cryst, engine = make_crystallizer()

    _observe(cryst, [None, None, None])

    assert not _passed_prescreen(cryst, engine), "无证据观察被判成了可入库模式"
    assert cryst._buffer, "无证据观察不应被丢弃（后续可能被确证）"


def test_evidence_rate_ignores_unevidenced_observations(make_crystallizer):
    """无证据轮不得稀释确证成功：1 次确证成功 + 2 次无回执 ⇒ 确证口径成功率 1.0。"""
    cryst, engine = make_crystallizer()

    _observe(cryst, [None, True, None])

    assert _passed_prescreen(cryst, engine), (
        f"无证据观察被当成失败票稀释了成功率：缓冲={cryst._buffer}")


def test_confirmed_failures_still_block_crystallization(make_crystallizer):
    """反向锁：确证失败必须仍然拦得住 —— 不得把 None 的处理做成"一律放行"。"""
    cryst, engine = make_crystallizer()

    _observe(cryst, [False, False, None])

    assert not _passed_prescreen(cryst, engine), "确证失败的模式仍越过了门槛"
