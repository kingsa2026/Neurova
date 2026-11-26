# -*- coding: utf-8 -*-
"""U-conn 扩展批：Git 仓库连接器——本地 file:// 仓库真 clone（零网络），
文件清单切页、health 探测、缺 repo_url 显式拒绝。
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from neurova.knowledge.enterprise.connectors_git import GitAdapter
from neurova.knowledge.enterprise.registry import buildAdapter


def _run(coro):
    return asyncio.run(coro)


def _makeSourceRepo(tmp_path):
    """本地源仓库：两个文件 + 一次提交（file:// 形态即可 clone，零网络）。"""
    repo = tmp_path / "source-repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "src").mkdir()
    (repo / "src" / "customers.py").write_text("print('customers')", encoding="utf-8")
    (repo / "src" / "orders.py").write_text("print('orders')", encoding="utf-8")
    (repo / "README.md").write_text("demo repo", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                    "-c", "user.email=t@example", "commit", "-m", "init"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"],
                   check=True, capture_output=True)
    return repo


@pytest.fixture
def adapter(tmp_path):
    repo = _makeSourceRepo(tmp_path)
    return GitAdapter({"sourceType": "git", "repo_url": str(repo),
                       "branch": "main", "file_glob": "**/*.py"},
                      "git1", "default")


class TestGitAdapter:
    def test_dispatchesFromRegistry(self, adapter):
        from neurova.knowledge.enterprise.registry import buildAdapter

        built = buildAdapter({"sourceType": "git", "repo_url": "/tmp/x"},
                             "git2", "default")
        assert isinstance(built, GitAdapter)

    def test_fetchBatchListsGlobbedFiles(self, adapter):
        batch = _run(adapter.fetchBatch(None, 10))
        paths = [row["path"] for row in batch.rows]
        assert paths == ["src/customers.py", "src/orders.py"], "file_glob=**/*.py 只收 Python 文件"
        assert batch.rows[0]["size_bytes"] > 0
        assert batch.hasMore is False

    def test_offsetCursorSlicesPages(self, adapter):
        first = _run(adapter.fetchBatch(None, 1))
        assert [row["path"] for row in first.rows] == ["src/customers.py"]
        assert first.hasMore is True
        second = _run(adapter.fetchBatch(first.nextCursor, 1))
        assert [row["path"] for row in second.rows] == ["src/orders.py"]
        assert second.hasMore is False

    def test_healthProbesLocalRepo(self, adapter):
        health = _run(adapter.health())
        assert health.status == "ok"

    def test_fetchFailureRaisesInsteadOfEmptySuccess(self, adapter, monkeypatch):
        def boom():
            raise RuntimeError("git unavailable")

        monkeypatch.setattr(adapter, "_files", boom)
        with pytest.raises(RuntimeError, match="git unavailable"):
            _run(adapter.fetchBatch(None, 10))

    def test_missingRepoUrlRaisesInsteadOfEmptySuccess(self):
        adapter = GitAdapter({"sourceType": "git"}, "git3", "default")
        with pytest.raises(ValueError, match="repo_url"):
            _run(adapter.fetchBatch(None, 10))
        health = _run(adapter.health())
        assert health.status == "error" and "repo_url" in health.reason
