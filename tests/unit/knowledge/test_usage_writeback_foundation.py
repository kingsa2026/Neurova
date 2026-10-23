"""使用与采纳回流（工单 010，G07、灭 B06）。

判据是反向的：`neurova/knowledge/` 此前对这些列零命中，说明"知识被用到还是被无视"
根本无人记录。本票补写回面与度量面；**触发点**（检索命中即计数）在工单 011 切读路径时接，
本票不提前造一个没有调用方的计数器。
"""

from __future__ import annotations

import pathlib

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


def _adoptionCallSites(root):
    """AST 数 `recordAdoption` 的**调用点**（定义、docstring 里的名字都不算）。

    按文本数会把"这个 API 被提过"数成"有人在写"，那是本卷反复出现的同一处失真
    （判"零调用"须按节点形态判；台账 §6-75 与判据形态清单第 13 条）。
    """
    import ast as _ast

    from tests import ast_scan

    root = pathlib.Path(root)
    sites = []
    # 枚举与解析走 tests/ast_scan 的共享预算（不私有 rglob + ast.parse——后者把
    # 判据成本绑在代码总量上，见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    # 预筛词 `recordAdoption` 是判据的**充分条件**：谓词只认这一处属性调用。
    for ref in ast_scan.sourceRefsUnder(root, '.py', ast_scan.textHints('recordAdoption')):
        try:
            tree = _ast.parse(ref.code, filename=str(ref.path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)                     and node.func.attr == 'recordAdoption':
                sites.append('%s:%d' % (ref.path.relative_to(root).as_posix(), node.lineno))
    return sites


class TestAdoptionWriteSurfaceIsWired:
    """采纳回执写面：只允许两条已声明喉——聊天反馈与服务端血缘、显式管理端。

    2026-10-23 新能力落地，原先的"零调用点"前提结束；这里改成正向判据，
    防止随手长出的第三条写路绕过"服务端血缘"或"显式 fact_id"的语义。
    """

    def testProductionCallersAreTheTwoDocumentedThroats(self):
        from pathlib import Path

        repoRoot = Path(__file__).resolve().parents[3]
        sites = _adoptionCallSites(repoRoot / 'neurova')
        files = {site.split(':', 1)[0] for site in sites}
        assert files == {
            'api/endpoints/console.py',
            'api/endpoints/knowledge_core.py',
        }, '采纳写面出现未声明的调用点: %s' % sites

    def testDetectorReallyCountsCallSites(self):
        """反空转：探测器必须抓得住一处人造调用点，也不把定义与 docstring 数成调用。"""
        lines = [
            'class StoreLike:',
            '    def recordAdoption(self, factId, outcome):',
            '        """recordAdoption 这个名字出现在 docstring 里也不算调用点"""',
            '        return None',
            '',
            'def _fire(store):',
            '    store.recordAdoption("f1", "success")',
            '',
        ]
        sample = chr(10).join(lines)
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmpPath = pathlib.Path(tmp)
            (tmpPath / 'writer.py').write_text(sample, encoding='utf-8')
            sites = _adoptionCallSites(tmpPath)
        assert sites == ['writer.py:7'], (
            '探测器没数到那一跳调用（或把定义/docstring 误数成调用）：%s' % sites)


class TestAdoptionZeroIsNamedNotSilent:
    """采纳回执为零时，读数必须自己说清成因。

    `outcome_written=0` 的当前含义是“尚未发生回写”；写面已接两条喉，
    不能把 0 读成“写面未接线”，更不能读成“没人采纳”。
    """

    def test_zeroAdoptionOutcomeNamesTheWriteThroats(self, store, facts):
        metrics = store.usageMetrics()

        assert metrics["outcome_written"] == 0
        reason = str(metrics.get("missing_reason") or "")
        assert '尚未发生回写' in reason, (
            '一条回执都没有，读数却没点名成因——只剩一个 0 会被读成「没人采纳」：%r' % metrics)
        assert '/chat/feedback' in reason and '/knowledge/facts/' in reason, (
            '要写明已接的两条写入喉，否则读者无法判断 0 是“没发生”还是“没接线”：%r' % reason)
        assert '未接线' not in reason

    def test_aSingleWrittenOutcomeRetiresTheReason(self, store, facts):
        """反向对照：一旦真有人写了回执，就不该再挂缺失说明。"""
        store.recordInjection([facts[0]])
        store.recordAdoption(facts[0], 'success')

        metrics = store.usageMetrics()
        assert metrics["outcome_written"] == 1
        assert '尚未发生回写' not in str(metrics.get("missing_reason") or ''), (
            '已经有回执了还挂缺失说明：读数会把人引向错误方向：%r' % metrics)
