"""017 收缩判据：SPO 分歧判定只剩咽喉一处实现。

三条轴分清楚才谈"合一"：
- **事实级（同主体同谓词取值相异）** —— 只准有 `KnowledgeConflictJudge` 一处。
  TKG 与 `TKGModule` 原本各扫各的内存/私有表（无分类、无严重度依据、无账本），已删。
- **条目级（同标题正文相像）** —— `repository._detect_conflicts` 一处，账本在
  `knowledge_entry_conflicts`。它与事实级是两个对象，硬并会丢相似度（理由见 016/019b-4a）。
- **时序关系级（A 先于 B 又后于 B、传递成环）** —— `temporal_reasoner` 一处，
  与上面两条不是同一语义轴；它的环检测由 021 的分层规则引擎收编，不在本票删。
"""

from __future__ import annotations

import pathlib

import pytest

from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

MEMORY_LAYER = pathlib.Path("neurova/cognitive_layers/memory_layer")


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


class TestTheSecondAndThirdImplementationAreGone:
    def test_privateTkgStoreIsRetiredEntirely(self):
        """旧私有 TKG 存储（temporal_knowledge_graph.py）已按教义第 7 条整体退役
        （2026-11-14）：时序事实唯一权威在底座 knowledge_facts，读面是
        foundation.temporal_facts.TemporalFactReader。模块名再可导入即复活。"""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(
                "neurova.cognitive_layers.memory_layer.temporal_knowledge_graph")

    def test_noMemoryLayerFileJudgesSpoContradictionsExceptByDelegation(self):
        """memory_layer 里可以有人*问*冲突，不许有人自己*判*冲突。"""
        offenders = []
        for path in sorted(MEMORY_LAYER.rglob("*.py")):
            if path.name in ("temporal_reasoner.py",):
                continue  # 时序关系轴，另一条语义，收编在 021
            text = path.read_text(encoding="utf-8")
            if "def detect_conflicts" in text and "KnowledgeConflictJudge" not in text:
                offenders.append(path.name)
        assert offenders == [], "这些文件还在自己判 SPO 分歧: %s" % offenders


class TestDetectionNowAnswersFromTheFoundation:
    def _seed(self, store):
        from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge

        same = "2026-09-20T00:00:00+00:00"
        key = store.upsertSubject("default", "神经瓦")
        older = store.upsertFact("default", key, "version", "1.0", "1.0 的说法",
                                 recordedAt=same)
        newer = store.upsertFact("default", key, "version", "2.0", "2.0 的说法",
                                 recordedAt=same)
        for fid in (older, newer):
            store.setEvidenceState(fid, "evidenced")
        KnowledgeConflictJudge(store).record("神经瓦", "version")
        return older, newer

    def test_moduleLevelDetectionUsesTheJudgeVerdict(self, store, monkeypatch):
        older, newer = self._seed(store)
        monkeypatch.setattr("neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
                            lambda *a, **k: store)

        conflicts = TKGModule().detect_conflicts("神经瓦", "version", "1.0")

        assert [c["object_term"] for c in conflicts] == ["2.0"], "问的是谁和 1.0 打架"
        assert conflicts[0]["fact_id"] == newer
        assert "confidence" in conflicts[0], "回的是底座事实行，不是模块自己那份字段"

    def test_undelegatedFactsAreNotInvented(self, store, monkeypatch):
        self._seed(store)
        monkeypatch.setattr("neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
                            lambda *a, **k: store)

        assert TKGModule().detect_conflicts("没这个人", "version", "x") == []
