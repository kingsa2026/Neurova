"""B2 上下文传递工件化 · 预算与历史挑选。

覆盖：clampTokenCap 边界（None / 低于下限 / 高于上限）、estimateTokens 多语言
字节成本（中文 / emoji）、computeHandoffBudget 窗口扣减与负余量抛错、
selectHistory 新到旧整条填充、强制保留项、图片预留计费、省略条目的恢复指引。
诚实失败纪律：预算放不下必须抛 ContextHandoffBudgetError，禁止静默截断。
"""

import pytest

from neurova.agent.context_transfer import (
    DEFAULT_BYTE_CAP,
    DEFAULT_TOKEN_CAP,
    MAX_TOKEN_CAP,
    MIN_TOKEN_CAP,
    PER_IMAGE_RESERVE_TOKENS,
    ContextHandoffBudgetError,
    clampTokenCap,
    computeHandoffBudget,
    estimateTokens,
    selectHistory,
)


def _item(itemId, role, content, images=None):
    item = {"id": itemId, "role": role, "content": content}
    if images is not None:
        item["images"] = images
    return item


def _fiveAssistantItems():
    # 每条 400 字节 ASCII -> 100 tokens；全 assistant 角色（无 user 强制保留项干扰）
    return [_item(f"a{n}", "assistant", "x" * 400) for n in range(1, 6)]


# ---------- clampTokenCap ----------


def testClampTokenCapNoneFallsBackToDefault():
    assert clampTokenCap(None) == DEFAULT_TOKEN_CAP == 16000


def testClampTokenCapClampsBothSides():
    assert clampTokenCap(MIN_TOKEN_CAP - 1) == MIN_TOKEN_CAP
    assert clampTokenCap(0) == MIN_TOKEN_CAP
    assert clampTokenCap(5000) == 5000
    assert clampTokenCap(MAX_TOKEN_CAP) == MAX_TOKEN_CAP
    assert clampTokenCap(MAX_TOKEN_CAP + 1) == MAX_TOKEN_CAP


# ---------- estimateTokens ----------


def testEstimateTokensEmptyTextIsZero():
    assert estimateTokens("") == 0


def testEstimateTokensAsciiCeilsUpByUtf8Bytes():
    assert estimateTokens("abcd") == 1  # 4 字节
    assert estimateTokens("abc") == 1  # 3 字节向上取整
    assert estimateTokens("abcde") == 2  # 5 字节向上取整


def testEstimateTokensChineseAndEmojiCostByUtf8Bytes():
    assert estimateTokens("你好") == 2  # 6 字节
    assert estimateTokens("你好，世界") == 4  # 15 字节
    assert estimateTokens("😀") == 1  # 4 字节
    assert estimateTokens("a😀") == 2  # 5 字节


# ---------- computeHandoffBudget ----------


def testComputeHandoffBudgetDefaultsUseTokenCapAndByteCap():
    budgetTokens, budgetBytes = computeHandoffBudget(window_tokens=1_000_000)
    assert budgetTokens == DEFAULT_TOKEN_CAP
    assert budgetBytes == DEFAULT_BYTE_CAP == 64 * 1024


def testComputeHandoffBudgetDeductsWindowUsage():
    budgetTokens, _ = computeHandoffBudget(
        window_tokens=20000, native_usage_tokens=3000, input_tokens=2000, reserve_tokens=1000
    )
    assert budgetTokens == 14000  # min(16000, 20000 - 3000 - 2000 - 1000)


def testComputeHandoffBudgetTakesMinOfClampedCapAndWindow():
    assert computeHandoffBudget(token_cap=8000, window_tokens=1_000_000)[0] == 8000
    # 低于下限的 cap 被抬到 MIN_TOKEN_CAP
    assert computeHandoffBudget(token_cap=100, window_tokens=1_000_000)[0] == MIN_TOKEN_CAP


def testComputeHandoffBudgetByteCapClampedToDefaultCeiling():
    assert computeHandoffBudget(window_tokens=1_000_000, byte_cap=1024)[1] == 1024
    assert computeHandoffBudget(window_tokens=1_000_000, byte_cap=10**9)[1] == DEFAULT_BYTE_CAP


def testComputeHandoffBudgetWindowTooSmallOrNegativeRaises():
    with pytest.raises(ContextHandoffBudgetError):
        computeHandoffBudget(window_tokens=MIN_TOKEN_CAP - 1)
    with pytest.raises(ContextHandoffBudgetError):
        # 窗口 10000，扣掉 9000 + 5000 后余量为负：宁可失败不静默截断
        computeHandoffBudget(window_tokens=10000, native_usage_tokens=9000, input_tokens=5000)


def testComputeHandoffBudgetExactMinBoundaryStillPasses():
    assert computeHandoffBudget(window_tokens=MIN_TOKEN_CAP)[0] == MIN_TOKEN_CAP


# ---------- selectHistory ----------


def testSelectHistoryFillsNewestFirstAndStopsAtFirstNonFit():
    items = _fiveAssistantItems()
    kept, omitted, coverage = selectHistory(items, budget_tokens=350, budget_bytes=10_000)
    assert [item["id"] for item in kept] == ["a3", "a4", "a5"]
    assert omitted == ["a1", "a2"]
    assert "3/5" in coverage


def testSelectHistoryForcesNewestTurnAndOldestUserEvenOverBudget():
    items = [
        _item("u1", "user", "x" * 400),  # 最早 user：强制保留
        _item("a1", "assistant", "x" * 400),
        _item("t1", "tool", "x" * 400),  # 最新条目是 tool，不属于强制保留
        _item("u2", "user", "x" * 400),  # 最新 user/assistant：强制保留
    ]
    kept, omitted, coverage = selectHistory(items, budget_tokens=10, budget_bytes=10)
    assert [item["id"] for item in kept] == ["u1", "u2"]
    assert omitted == ["a1", "t1"]
    assert "2/4" in coverage
    assert "未注入" in coverage
    assert "取回" in coverage


def testSelectHistoryChargesImageReservePerImage():
    items = [
        _item("t1", "tool", "x" * 40),  # 10 tokens
        _item("t2", "tool", "x" * 40, images=2),  # 10 + 2*8192 tokens
        _item("t3", "tool", "x" * 40),  # 10 tokens
    ]
    kept, omitted, _ = selectHistory(items, budget_tokens=100, budget_bytes=10_000)
    assert [item["id"] for item in kept] == ["t3"]
    assert omitted == ["t1", "t2"]

    kept, omitted, _ = selectHistory(
        items, budget_tokens=2 * PER_IMAGE_RESERVE_TOKENS + 100, budget_bytes=10_000
    )
    assert [item["id"] for item in kept] == ["t1", "t2", "t3"]
    assert omitted == []


def testSelectHistoryRespectsByteBudgetForMultibyteContent():
    items = [
        _item("t1", "tool", "汉" * 100),  # 300 字节 / 75 tokens
        _item("t2", "tool", "汉" * 100),  # 300 字节 / 75 tokens
    ]
    # token 预算充足、字节预算紧张：多字节内容按字节预算被省略
    kept, omitted, _ = selectHistory(items, budget_tokens=1000, budget_bytes=100)
    assert kept == []
    assert omitted == ["t1", "t2"]

    kept, omitted, _ = selectHistory(items, budget_tokens=1000, budget_bytes=1000)
    assert [item["id"] for item in kept] == ["t1", "t2"]
    assert omitted == []


def testSelectHistoryCoverageListsOmittedIdsWithRecoveryGuidance():
    items = [_item(f"t{n}", "tool", "x" * 400) for n in range(1, 6)]
    kept, omitted, coverage = selectHistory(items, budget_tokens=250, budget_bytes=10_000)
    assert omitted == ["t1", "t2", "t3"]
    assert [item["id"] for item in kept] == ["t4", "t5"]
    for itemId in omitted:
        assert itemId in coverage
    assert "未注入" in coverage
    assert "取回" in coverage


def testSelectHistoryAllFitReportsNoOmission():
    items = _fiveAssistantItems()
    kept, omitted, coverage = selectHistory(items, budget_tokens=1000, budget_bytes=100_000)
    assert omitted == []
    assert len(kept) == 5
    assert "无省略" in coverage


def testSelectHistoryEmptyItemsKeepsEmptyArtifact():
    kept, omitted, coverage = selectHistory([], budget_tokens=1000, budget_bytes=1000)
    assert kept == []
    assert omitted == []
    assert coverage
