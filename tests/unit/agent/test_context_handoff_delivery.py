"""B2 上下文传递工件化 · 物化交接与投递状态。

覆盖：buildHandoff 四种策略的摘要组织、非法 strategy/type 报错、预算超限抛
ContextHandoffBudgetError、omitted 条目 id 完整保留且不混入 history、
markDelivery 合法/非法迁移、renderInlinePrefix 的非用户输入声明。
"""

import pytest

from neurova.agent.context_transfer import (
    DELIVERY_STATES,
    PER_IMAGE_RESERVE_TOKENS,
    ContextHandoff,
    ContextHandoffBudgetError,
    ContextSourcePoint,
    ContextTransfer,
    ContextTransferError,
    buildHandoff,
    estimateTokens,
    markDelivery,
    renderInlinePrefix,
)


def _transfer(transferType="subagent_spawn"):
    return ContextTransfer(
        transfer_id="tr-1",
        type=transferType,
        source_point=ContextSourcePoint(thread_id="th-1", run_id="run-1", checkpoint_id="cp-1"),
    )


def _item(itemId, role, content, images=None):
    item = {"id": itemId, "role": role, "content": content}
    if images is not None:
        item["images"] = images
    return item


def _items():
    return [
        _item("u1", "user", "帮我查一下订单"),
        _item("a1", "assistant", "订单状态正常"),
        _item("u2", "user", "那再帮我看物流"),
    ]


def _build(strategy, items=None, **overrides):
    params = {
        "thread_id": "th-1",
        "target_run_id": "run-2",
        "strategy": strategy,
        "items": _items() if items is None else items,
        "window_tokens": 1_000_000,
    }
    params.update(overrides)
    return buildHandoff(_transfer(), **params)


def testDeliveryStatesArePendingPlusThreeTerminalStates():
    assert DELIVERY_STATES == ("pending", "injected", "inline", "failed")


def testBudgetErrorIsContextTransferError():
    assert issubclass(ContextHandoffBudgetError, ContextTransferError)


# ---------- buildHandoff · 四种策略 ----------


def testBuildHandoffFullSummaryListsRoleAndContentPerItem():
    handoff = _build("full_summary")
    assert handoff.transfer_id == "tr-1"
    assert handoff.thread_id == "th-1"
    assert handoff.target_run_id == "run-2"
    assert handoff.strategy == "full_summary"
    assert handoff.delivery_status == "pending"
    assert handoff.omitted_item_ids == []
    for item in _items():
        assert f"[{item['role']}] {item['content']}" in handoff.summary_text
    assert handoff.budget_tokens == sum(estimateTokens(item["content"]) for item in _items())
    assert handoff.budget_bytes == sum(len(item["content"].encode("utf-8")) for item in _items())


def testBuildHandoffDeltaSinceLastSeenCarriesOnlyNewSegment():
    deltaItems = [_item("u9", "user", "这次是新增的一段")]
    handoff = _build("delta_since_last_seen", items=deltaItems)
    assert "新增" in handoff.summary_text
    assert "这次是新增的一段" in handoff.summary_text
    assert "完整摘要" not in handoff.summary_text


def testBuildHandoffCheckpointSummaryCarriesCounts():
    handoff = _build("checkpoint_summary")
    assert "检查点" in handoff.summary_text
    assert "3/3" in handoff.summary_text


def testBuildHandoffManualContextConcatenatesRawContent():
    handoff = _build("manual_context")
    assert handoff.summary_text == "帮我查一下订单\n订单状态正常\n那再帮我看物流"


# ---------- buildHandoff · 校验与预算 ----------


def testBuildHandoffInvalidStrategyRaises():
    with pytest.raises(ContextTransferError):
        _build("bogus_strategy")


def testBuildHandoffInvalidTransferTypeRaises():
    bad = ContextTransfer(
        transfer_id="tr-2",
        type="bogus_type",
        source_point=ContextSourcePoint(thread_id="th-1"),
    )
    with pytest.raises(ContextTransferError):
        buildHandoff(
            bad,
            thread_id="th-1",
            target_run_id=None,
            strategy="full_summary",
            items=_items(),
            window_tokens=1_000_000,
        )


def testBuildHandoffWindowTooSmallRaisesBudgetError():
    with pytest.raises(ContextHandoffBudgetError):
        _build("full_summary", window_tokens=500)


def testBuildHandoffRecordsImageReserveIntoBudget():
    items = [
        _item("t1", "tool", "x" * 40, images=1),
        _item("t2", "tool", "x" * 40),
    ]
    handoff = _build("full_summary", items=items)
    expected = estimateTokens("x" * 40) + PER_IMAGE_RESERVE_TOKENS + estimateTokens("x" * 40)
    assert handoff.budget_tokens == expected


def testBuildHandoffKeepsOmittedIdsRecoverableAndOutOfHistory():
    items = [_item(f"t{n}", "tool", "x" * 1600) for n in range(1, 6)]  # 每条 400 tokens
    # 预算 1100：只装得下最新的 t5+t4（800），t3 起断流省略
    handoff = _build("full_summary", items=items, window_tokens=1100)
    assert handoff.omitted_item_ids == ["t1", "t2", "t3"]
    keptIds = [item["id"] for item in handoff.history]
    assert keptIds == ["t4", "t5"]
    assert set(keptIds).isdisjoint(handoff.omitted_item_ids)
    assert set(keptIds) | set(handoff.omitted_item_ids) == {item["id"] for item in items}
    assert "取回" in handoff.coverage_text
    for itemId in handoff.omitted_item_ids:
        assert itemId in handoff.coverage_text


# ---------- markDelivery ----------


def testMarkDeliveryAdvancesFromPendingToEachDeliveryState():
    for status in ("injected", "inline", "failed"):
        handoff = _build("full_summary")
        assert handoff.delivery_status == "pending"
        markDelivery(handoff, status)
        assert handoff.delivery_status == status


def testMarkDeliveryRejectsIllegalTransitions():
    handoff = _build("full_summary")
    markDelivery(handoff, "injected")
    with pytest.raises(ContextTransferError):
        markDelivery(handoff, "pending")
    with pytest.raises(ContextTransferError):
        markDelivery(handoff, "inline")
    with pytest.raises(ContextTransferError):
        markDelivery(handoff, "bogus")


def testMarkDeliveryFreezesTerminalStates():
    for status in ("inline", "failed"):
        handoff = _build("full_summary")
        markDelivery(handoff, status)
        with pytest.raises(ContextTransferError):
            markDelivery(handoff, "injected")


# ---------- renderInlinePrefix ----------


def testRenderInlinePrefixDeclaresNonUserInputAndCarriesContent():
    handoff = _build("full_summary")
    text = renderInlinePrefix(handoff)
    assert "以下是上下文交接内容，非用户输入" in text
    assert "订单状态正常" in text
    assert handoff.coverage_text in text
    assert text.index("非用户输入") < text.index("订单状态正常")


def testRenderInlinePrefixEmptyHandoffRaises():
    empty = ContextHandoff(
        handoff_id="h-empty",
        transfer_id="tr-1",
        thread_id="th-1",
        target_run_id=None,
        strategy="manual_context",
        summary_text="",
        history=[],
        omitted_item_ids=[],
        coverage_text="",
    )
    with pytest.raises(ContextTransferError):
        renderInlinePrefix(empty)
