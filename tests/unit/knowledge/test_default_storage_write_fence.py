"""生产知识库写入围栏（工单 001 立，工单 019b-4b 随默认后端翻向而加固）。

真实 `data/knowledge/knowledge.json` 已证实被历史非隔离运行写入过（38 行纯冗余，见
docs/specs/2026-09-20-knowledge-foundation-design.md §1.2）。围栏把"测试写生产目录"从
静默污染变成显式失败。

019b-4b 之后围栏必须守在**构造**而不是只守 `_save`：默认权威已在底座库，
`KnowledgeRepository(...)` 一建就带着迁移建表和一次性搬家。本批真实踩过一次——
某个摘掉围栏标记的用例指向真生产目录，把生产的 `knowledge.json` 搬进库并改了名。
所以本文件的铁律：**清掉围栏标记的用例只准指向 tmp_path 下的假生产目录**，
落盘默认后端另用 `narrativeSpy` 拦掉，真落盘只发生在隔离目录里。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List

import pytest

from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME, NarrativeStore
from neurova.knowledge.repository import (
    DEFAULT_STORAGE_DIR,
    NARRATIVE_STORE_ENV,
    KnowledgeRepository,
)


@pytest.fixture
def writeSpy(monkeypatch) -> List[Any]:
    """拦截落盘：记录 (path, text) 而不写文件。

    repository._save 是函数内惰性 import，故替身打在源模块属性上即可生效。
    """
    calls: List[Any] = []

    def _stub(path, text, *args, **kwargs):
        calls.append((str(path), text))
        return None

    monkeypatch.setattr("neurova.core.atomic_io.atomic_write_text", _stub)
    return calls


def _repo(storage_dir: str) -> KnowledgeRepository:
    return KnowledgeRepository(storage_dir)


@pytest.fixture
def narrativeSpy(monkeypatch) -> List[str]:
    """拦截底座库三条写路径：记录调用而不落文件（默认后端就是它）。"""
    calls: List[str] = []
    from neurova.knowledge.foundation.narratives import NarrativeStore

    monkeypatch.setattr(NarrativeStore, "replaceAll",
                        lambda self, items: calls.append("items") or sum(len(v) for v in items.values()))
    monkeypatch.setattr(NarrativeStore, "replaceAllTombstones",
                        lambda self, recs: calls.append("tombstones") or len(recs))
    monkeypatch.setattr(NarrativeStore, "replaceAllConflicts",
                        lambda self, recs: calls.append("conflicts") or len(recs))
    monkeypatch.setattr(NarrativeStore, "tombstoneCount", lambda self: 1)
    monkeypatch.setattr(NarrativeStore, "conflictCount", lambda self: 1)
    monkeypatch.setattr(NarrativeStore, "loadTombstones", lambda self: {})
    monkeypatch.setattr(NarrativeStore, "loadConflicts", lambda self: {})
    monkeypatch.setattr(NarrativeStore, "loadAll", lambda self: {})
    return calls


def _withItem(repo: KnowledgeRepository) -> KnowledgeRepository:
    repo._items["guard-probe"] = [{"knowledge_id": "k1", "title": "t", "content": "c"}]
    return repo


class TestProductionWriteFence:
    def test_defaultStorageConstructionRaises(self, monkeypatch, writeSpy, narrativeSpy):
        """围栏从 _save 提到构造：默认权威在底座库，构造本身就会建库落文件。

        只守 _save 等于守不住——测试会话会在 data/knowledge/ 里造出真底座库。
        """
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")

        with pytest.raises(RuntimeError, match="生产知识库"):
            _repo(DEFAULT_STORAGE_DIR)

        assert writeSpy == [] and narrativeSpy == [], "围栏生效时不得有任何落盘调用"

    def test_saveBoundaryIsFencedToo(self, monkeypatch, tmp_path, writeSpy, narrativeSpy):
        """构造放行之后（隔离目录），写边界仍必须挡住被改指到生产目录的实例。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _withItem(_repo(str(tmp_path / "kb")))
        repo._dir = Path(DEFAULT_STORAGE_DIR)  # 故意伪造：绕过构造围栏，直接改指向

        with pytest.raises(RuntimeError, match="生产知识库"):
            repo._save()

        assert writeSpy == [] and narrativeSpy == []

    def test_fenceIsWhatStopsTheWrite(self, monkeypatch, tmp_path, writeSpy, narrativeSpy):
        """摘掉围栏标记后同一调用必须真的走到落盘——证明围栏是唯一拦阻者，不是空守卫。

        刻意**不**指向真生产目录：这条用例要把围栏标记清掉才能证明没有别的东西在拦，
        而清掉标记之后指向真目录就等于放行真写。默认权威已在底座库，
        构造本身会跑一次性搬家（导入 + 把旧主文件改名）——那正是本批留档事故的原样，
        所以拿假生产目录证明同一件事，零生产暴露。
        """
        fakeProd = tmp_path / "data" / "knowledge"
        fakeProd.mkdir(parents=True)
        monkeypatch.setattr("neurova.knowledge.foundation.storage_fence.PRODUCTION_STORAGE_DIR",
                            str(fakeProd))
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        repo = _withItem(_repo(str(fakeProd)))

        repo._save()

        # 默认后端是底座库，所以这次落盘走 replaceAll 而不是 atomic_write_text
        assert narrativeSpy == ["items"], "没有围栏时写入必须真的落到后端"
        assert writeSpy == [], "JSON 分支只在显式 off 时才被走到"

    def test_tombstoneAndConflictLedgersAreFenced(self, monkeypatch, tmp_path, narrativeSpy):
        """两本旁账的写边界同样在围栏之后——它们在 019b-2c/019b-4a 才收进底座，
        围栏若只覆盖条目主账，墓碑与冲突就会从侧门漏出去。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _repo(str(tmp_path / "kb"))
        repo._dir = Path(DEFAULT_STORAGE_DIR)  # 故意伪造：绕过构造围栏，直接改指向
        repo._tombstones["k1"] = {"item": {}}
        repo._conflicts["c1"] = {"status": "pending"}

        with pytest.raises(RuntimeError, match="生产知识库"):
            repo._save_tombstones()
        with pytest.raises(RuntimeError, match="生产知识库"):
            repo._save_conflicts()

        assert narrativeSpy == []

    def test_isolatedStorageStillWritable(self, monkeypatch, tmp_path):
        """隔离目录必须照常可写——围栏不能变成"测试里谁也存不了"。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _withItem(_repo(str(tmp_path / "kb")))

        repo._save()

        assert (tmp_path / "kb" / FOUNDATION_DB_NAME).exists()

    def test_jsonBackendStillWritableWhenExplicitlyOff(self, monkeypatch, tmp_path):
        """显式 off 的回退分支必须还是那条能落 JSON 的老路，否则开关是单向门。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        monkeypatch.setenv(NARRATIVE_STORE_ENV, "off")
        repo = _withItem(_repo(str(tmp_path / "kb-json")))

        repo._save()

        assert (tmp_path / "kb-json" / "knowledge.json").exists()
        assert not (tmp_path / "kb-json" / FOUNDATION_DB_NAME).exists()

    def test_readPathCutoverIsRealAndUnfencedOutsidePytest(self, monkeypatch, tmp_path):
        """围栏只管测试会话：非测试会话里构造即读，且默认后端的读会真的搬家。

        这条用例把 019b-4b 的事故作用点钉在假生产目录上——一次性搬家挂在读路径上，
        搬完把旧主文件改名归档。真被测试会话碰上就是事故，所以本用例自己造目录、
        自己清标记，只证明"机制存在且只此一次"。
        """
        fakeProd = tmp_path / "data" / "knowledge"
        fakeProd.mkdir(parents=True)
        (fakeProd / "knowledge.json").write_text(
            json.dumps({"ag": [{"knowledge_id": "k1", "title": "t", "content": "c"}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr("neurova.knowledge.foundation.storage_fence.PRODUCTION_STORAGE_DIR",
                            str(fakeProd))
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)

        repo = _repo(str(fakeProd))

        assert [i["knowledge_id"] for i in repo._items["ag"]] == ["k1"]
        assert (fakeProd / FOUNDATION_DB_NAME).exists()
        assert not (fakeProd / "knowledge.json").exists(), "搬家后旧主文件必须让位，不能双写"
        assert list(fakeProd.glob("knowledge.json.pre-narrative-store-*"))
        # 重启第二次不得再搬——已删条目被归档快照复活就是这个形状
        assert _repo(str(fakeProd))._items["ag"][0]["knowledge_id"] == "k1"


class TestFenceCoversEveryProductionWritingSurface:
    """围栏守的是"生产目录"，不是某一个类。

    019b-4b 实测漏口的样子：条目仓库被守住之后，`get_knowledge_fact_store()` 的默认路径
    照样在 `data/knowledge/` 里建出真底座库——四个写入面各抄过一份路径，就各漏一次。
    """

    def test_factStoreNarrativeStoreAndBenchmarkAreFenced(self, monkeypatch):
        from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        prodDb = str(Path(DEFAULT_STORAGE_DIR) / FOUNDATION_DB_NAME)
        evalDb = Path(DEFAULT_STORAGE_DIR) / "knowledge_evaluation.db"
        # 评测账本在生产里是真件（冻结基线住在那儿），所以判据是"没被碰过"而不是"不存在"
        evalStamp = (evalDb.stat().st_size, evalDb.stat().st_mtime_ns) if evalDb.exists() else None

        with pytest.raises(RuntimeError, match="生产知识库"):
            KnowledgeFactStore(prodDb)
        with pytest.raises(RuntimeError, match="生产知识库"):
            NarrativeStore(prodDb)
        with pytest.raises(RuntimeError, match="生产知识库"):
            RetrievalBenchmark(str(evalDb))

        assert ((evalDb.stat().st_size, evalDb.stat().st_mtime_ns)
                if evalDb.exists() else None) == evalStamp

    def test_factStoreSingletonDefaultPathIsFenced(self, monkeypatch):
        """真正的漏口是工厂：无参取单例时路径由 DEFAULT_FACT_DB 兜底，绕过仓库的围栏。"""
        from neurova.knowledge.foundation import knowledge_facts
        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        monkeypatch.setattr(knowledge_facts, "_store_singleton", None)
        prodDir = Path(knowledge_facts.DEFAULT_FACT_DB).parent
        before = sorted(p.name for p in prodDir.iterdir())

        with pytest.raises(RuntimeError, match="生产知识库"):
            get_knowledge_fact_store()

        assert sorted(p.name for p in prodDir.iterdir()) == before, \
            "被挡住的那次构造不得在磁盘上留下任何东西"

    def test_productionPathIsSingleSourced(self):
        """路径只准有一份：抄第二份就等于给下一个入口留漏口的位置。"""
        from neurova.knowledge import vector_index
        from neurova.knowledge.evaluation import retrieval_benchmark
        from neurova.knowledge.foundation import knowledge_facts
        from neurova.knowledge.foundation.storage_fence import PRODUCTION_STORAGE_DIR

        assert Path(DEFAULT_STORAGE_DIR) == Path(PRODUCTION_STORAGE_DIR)
        assert Path(knowledge_facts.DEFAULT_FACT_DB) == Path(PRODUCTION_STORAGE_DIR) / FOUNDATION_DB_NAME
        assert Path(retrieval_benchmark.DEFAULT_EVAL_DB).parent == Path(PRODUCTION_STORAGE_DIR)
        assert Path(vector_index.DEFAULT_STORAGE_DIR) == Path(PRODUCTION_STORAGE_DIR)

    def test_isolatedSurfacesStayUsable(self, monkeypatch, tmp_path):
        """围栏不能变成"测试里谁也建不了库"——三个面在隔离路径上都得照常工作。"""
        from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")

        assert KnowledgeFactStore(str(tmp_path / "f.db")).factCount() == 0
        assert NarrativeStore(str(tmp_path / "n.db")).count() == 0
        assert RetrievalBenchmark(str(tmp_path / "e.db")).caseCount() == 0
