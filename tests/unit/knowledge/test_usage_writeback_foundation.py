"""使用与采纳回流（工单 010，G07、灭 B06）。

判据是反向的：`neurova/knowledge/` 此前对这些列零命中，说明"知识被用到还是被无视"
根本无人记录。本票补写回面与度量面；**触发点**（检索命中即计数）在工单 011 切读路径时接，
本票不提前造一个没有调用方的计数器。
"""

from __future__ import annotations

import pathlib

import pytest

from tests import ast_scan

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
        # 文件枚举与读盘走 tests/ast_scan.py 的共享预算（Issue #148：受保护子集里
        # 不得再出现自带 rglob 的第二份实现）。
        for ref in ast_scan.sourceRefsUnder(root):
            for name in hits:
                hits[name] += ref.code.count(name)

        assert all(hits.values()), '使用回流列仍无人引用，B06 未灭：%s' % hits


def _adoptionCallSites(root):
    """AST 数 `recordAdoption` 的**调用点**（定义、docstring 里的名字都不算）。

    按文本数会把"这个 API 被提过"数成"有人在写"，那是本卷反复出现的同一处失真
    （判"零调用"须按节点形态判；台账 §6-75 与判据形态清单第 13 条）。
    """
    import ast as _ast

    root = pathlib.Path(root)
    sites = []
    # 枚举与解析走 tests/ast_scan.py 的共享预算（Issue #148：受保护子集里不得
    # 再出现自带 rglob + ast.parse 的第二份实现）。
    for path, tree in ast_scan.parsedModules(root):
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)                     and node.func.attr == 'recordAdoption':
                sites.append('%s:%d' % (path.relative_to(root).as_posix(), node.lineno))
    return sites


class TestAdoptionWriteSurfaceIsStillUnwired:
    """采纳回执这一维：**写面全仓零调用点**，所以 `usageMetrics.outcome_written` 恒 0。

    与注入账不同——注入的接缝活在 `graph_retriever_adapter:47`（另有两条在默认关的
    `NEUROVA_KB_FACT_SURFACE` 闸后），2026-10-10 已在真库拷贝上活体证过（§6-124）。
    本格守的是"这件事没人悄悄改掉"：要么接线（得先定"拿哪个用户信号当采纳"，属新能力），
    要么把这一维读数如实标成未接线。**两条都要先改这一格**，不许留着一个恒 0 的读数
    让治理面把它当成"没人采纳"来读（AGENTS.md §2 断点条款、§7 影响面条款）。
    """

    def testNoProductionCallerWritesAdoptionOutcome(self):
        from pathlib import Path

        repoRoot = Path(__file__).resolve().parents[3]
        sites = _adoptionCallSites(repoRoot / 'neurova')
        assert sites == [], (
            'recordAdoption 出现了生产调用点 %s —— 那本格的前提就结束了：'
            '把本类改成"回执必须落账"的正向判据，并在台账 §6-124 记下是谁、按哪个信号接的'
            % sites)

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
    """采纳回执为零时，读数必须自己说清成因（用户 2026-10-10 裁定：如实标「写面未接线」）。

    `outcome_written=0` 有两种成因：底座刚建（还没人用）与**写面从未接线**——
    后者是实况（AST 复算 `recordAdoption` 生产调用点 = 0，台账 §6-124）。
    只把 0 摆出来，读的人就会把它当产品结论（"没人采纳这些知识"），
    而那是拿账面缺失冒充测量结果，与 §6-109 那族"算完不告诉人哪里没成"同形。
    """

    def test_zeroAdoptionOutcomeNamesTheUnwiredWriter(self, store, facts):
        metrics = store.usageMetrics()

        assert metrics["outcome_written"] == 0
        reason = str(metrics.get("missing_reason") or "")
        assert '未接线' in reason, (
            '一条回执都没有，读数却没点名成因——只剩一个 0 会被读成「没人采纳」：%r' % metrics)
        assert 'recordAdoption' in reason, (
            '要点名到写面本体（哪个方法没有调用点），只写「暂无数据」等于没说：%r' % reason)

    def test_aSingleWrittenOutcomeRetiresTheReason(self, store, facts):
        """反向对照：一旦真有人写了回执，就不该再挂「未接线」的说明。

        少了这一格，"未接线"会被写成永久文案——那正是把一次性诊断变成假陈述的路。
        """
        store.recordInjection([facts[0]])
        store.recordAdoption(facts[0], 'success')

        metrics = store.usageMetrics()
        assert metrics["outcome_written"] == 1
        assert '未接线' not in str(metrics.get("missing_reason") or ''), (
            '已经有回执了还标未接线：读数会把人引向错误方向：%r' % metrics)
