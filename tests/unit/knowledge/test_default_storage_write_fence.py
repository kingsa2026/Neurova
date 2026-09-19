"""生产知识库写入围栏（工单 001）。

真实 `data/knowledge/knowledge.json` 已证实被历史非隔离运行写入过（38 行纯冗余，见
docs/specs/2026-09-20-knowledge-foundation-design.md §1.2）。围栏把"测试写生产目录"从
静默污染变成显式失败。

本文件自身绝不触碰生产磁盘：落盘一律换成 `atomic_write_text` 的替身，
所以即使围栏被摘掉也不会写真文件（这一点是 001 期间真实踩过的坑）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from neurova.knowledge.repository import DEFAULT_STORAGE_DIR, KnowledgeRepository


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


def _withItem(repo: KnowledgeRepository) -> KnowledgeRepository:
    repo._items["guard-probe"] = [{"knowledge_id": "k1", "title": "t", "content": "c"}]
    return repo


class TestProductionWriteFence:
    def test_defaultStorageSaveRaises(self, monkeypatch, writeSpy):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _withItem(_repo(DEFAULT_STORAGE_DIR))

        with pytest.raises(RuntimeError, match="生产知识库"):
            repo._save()

        assert writeSpy == [], "围栏生效时不得有任何落盘调用"

    def test_fenceIsWhatStopsTheWrite(self, monkeypatch, writeSpy):
        """摘掉围栏标记后同一调用必须真的走到落盘——证明围栏是唯一拦阻者，不是空守卫。"""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)
        repo = _withItem(_repo(DEFAULT_STORAGE_DIR))

        repo._save()

        assert len(writeSpy) == 1
        assert str(repo._path) == writeSpy[0][0]

    def test_tombstoneAndConflictLedgersAreFenced(self, monkeypatch):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        # 旁账走 Path.write_text 而非 atomic_write_text，故单独拦截，
        # 保证"围栏若回归"时这个用例也不会真在生产目录落下文件。
        monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: None)
        prod = _repo(DEFAULT_STORAGE_DIR)
        prod._tombstones["k1"] = {"item": {}}
        prod._conflicts["c1"] = {"status": "pending"}

        with pytest.raises(RuntimeError, match="生产知识库"):
            prod._save_tombstones()
        with pytest.raises(RuntimeError, match="生产知识库"):
            prod._save_conflicts()

    def test_temporaryStorageStillWritable(self, monkeypatch, tmp_path):
        """隔离目录必须照常可写——围栏不能变成"测试里谁也存不了"。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _withItem(_repo(str(tmp_path / "kb")))

        repo._save()

        assert (tmp_path / "kb" / "knowledge.json").exists()

    def test_readPathUnaffected(self, monkeypatch):
        """围栏只管写：指向生产目录的只读加载必须照常可用，否则启动即炸。"""
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        repo = _repo(DEFAULT_STORAGE_DIR)

        assert repo._path.parent.resolve() == Path(DEFAULT_STORAGE_DIR).resolve()
        assert isinstance(repo._items, dict)
