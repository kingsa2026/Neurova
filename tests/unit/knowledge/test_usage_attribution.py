"""token 归因策略：显式引用 → 权重 → 均分 → 未归因。"""
from neurova.knowledge.usage_attribution import allocateGenerationTokens


def _sum(alloc, idx):
    return sum(pair[idx] for pair in alloc.values())


def test_explicit_citation_allocates_only_cited():
    alloc, unattributed, method = allocateGenerationTokens(
        ["f1", "f2", "f3"], 100, 50, citationIds=["f1", "f2"]
    )

    assert method == "explicit_citation"
    assert set(alloc) == {"f1", "f2"}
    assert _sum(alloc, 0) == 100
    assert _sum(alloc, 1) == 50
    assert unattributed == (0, 0)


def test_weighted_estimate_uses_scores():
    alloc, unattributed, method = allocateGenerationTokens(
        ["f1", "f2"], 100, 50, weights={"f1": 3.0, "f2": 1.0}
    )

    assert method == "weighted_estimate"
    assert alloc["f1"] == (75, 38)
    assert alloc["f2"] == (25, 12)
    assert _sum(alloc, 0) == 100
    assert _sum(alloc, 1) == 50
    assert unattributed == (0, 0)


def test_even_split_when_no_signal():
    alloc, unattributed, method = allocateGenerationTokens(["f1", "f2", "f3"], 10, 5)

    assert method == "even_split"
    assert _sum(alloc, 0) == 10
    assert _sum(alloc, 1) == 5
    assert unattributed == (0, 0)


def test_no_facts_goes_to_unattributed():
    alloc, unattributed, method = allocateGenerationTokens([], 10, 5)

    assert alloc == {}
    assert unattributed == (10, 5)
    assert method == "unattributed"
