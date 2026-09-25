"""使用与采纳回流（工单 010，G07、灭 B06）。

判据是反向的：`neurova/knowledge/` 此前对这些列零命中，说明"知识被用到还是被无视"
根本无人记录。本票补写回面与度量面；**触发点**（检索命中即计数）在工单 011 切读路径时接，
本票不提前造一个没有调用方的计数器。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADOPTION_OUTCOMES = ("success", "failure", "unevidenced")


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def facts(store):
    key = store.upsertSubject("a", "神经瓦")
    return [store.upsertFact("a", key, "version", str(i), "正文 %d" % i) for i in range(5)]


class TestInjectionCounting:
    def test_count_increments_on_each_injection(self, store, facts):
        store.recordInjection([facts[0]])
        store.recordInjection([facts[0], facts[1]])

        assert store.fact(facts[0])["injected_count"] == 2
        assert store.fact(facts[1])["injected_count"] == 1
        assert store.fact(facts[2])["injected_count"] == 0

    def test_last_injected_at_is_stamped(self, store, facts):
        assert store.fact(facts[0])["last_injected_at"] is None

        store.recordInjection([facts[0]])

        assert store.fact(facts[0])["last_injected_at"]

    def test_unknown_fact_id_is_reported_not_silently_skipped(self, store, facts):
        with pytest.raises(LookupError):
            store.recordInjection([facts[0], "fact_ghost"])

    def test_concurrent_injections_do_not_lose_counts(self, store, facts):
        """计数丢一次就是"这条知识没人用"的假证据——并发下必须不丢。"""
        import threading

        errors = []

        def worker():
            try:
                for _ in range(20):
                    store.recordInjection([facts[0]])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert store.fact(facts[0])["injected_count"] == 80


class TestAdoptionWriteback:
    def test_never_written_is_null_not_unevidenced(self, store, facts):
        """NULL=从未发生过回写；unevidenced=回写过但没依据。混起来就把"没测"读成"测了没通过"。"""
        row = store.fact(facts[0])
        assert row["adoption_outcome"] is None
        assert row["latest_adoption_outcome"] is None

    @pytest.mark.parametrize("outcome", ADOPTION_OUTCOMES)
    def test_three_valued_outcome_is_accepted(self, store, facts, outcome):
        store.recordAdoption(facts[0], outcome)

        assert store.fact(facts[0])["adoption_outcome"] == outcome

    def test_unknown_outcome_is_rejected(self, store, facts):
        with pytest.raises(ValueError, match="adoption_outcome"):
            store.recordAdoption(facts[0], "probably_fine")

    def test_last_write_wins_and_history_count_is_kept(self, store, facts):
        store.recordAdoption(facts[0], "success")
        store.recordAdoption(facts[0], "failure")

        row = store.fact(facts[0])
        assert row["adoption_outcome"] == "failure"
        assert row["latest_adoption_outcome"] == "failure"


class TestUsageMetrics:
    def test_zero_usage_share_and_blind_spots_are_readable(self, store, facts):
        store.recordInjection([facts[0], facts[1]])
        store.recordAdoption(facts[0], "success")
        store.recordAdoption(facts[1], "unevidenced")

        metrics = store.usageMetrics()

        assert metrics["fact_count"] == 5
        assert metrics["never_injected_count"] == 3
        assert metrics["never_injected_share"] == pytest.approx(0.6)
        assert metrics["outcome_written"] == 2
        assert metrics["outcome_never_written"] == 3
        # unevidenced 必须单独成数，不能并进"成功/失败"任一桶
        assert metrics["outcome_unevidenced"] == 1

    def test_metrics_on_empty_store_are_unevidenced_not_perfect(self, store):
        metrics = store.usageMetrics()

        assert metrics["measure_state"] == "unevidenced"
        assert metrics["never_injected_share"] is None, "空库不能报 0% 无视，那是无据不是满分"
        assert metrics["missing_reason"]


class TestNoLongerBlindToUsage:
    def test_usage_columns_are_referenced_in_the_knowledge_package(self):
        """B06 的反向判据：此前 neurova/knowledge/ 对这些列零命中，即无人记录用没用。"""
        from pathlib import Path

        root = Path('neurova/knowledge')
        hits = {name: 0 for name in ('injected_count', 'last_injected_at', 'adoption_outcome')}
        for path in list(root.rglob('*.py')):
            text = path.read_text(encoding='utf-8', errors='ignore')
            for name in hits:
                hits[name] += text.count(name)

        assert all(hits.values()), '使用回流列仍无人引用，B06 未灭：%s' % hits
