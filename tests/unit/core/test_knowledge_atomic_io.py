# -*- coding: utf-8 -*-
"""DATA-P1-2（审计 2026-09-11）回归：知识库原子写 + 损坏隔离。

- atomic_write_text：tmp→replace，中途崩溃不留半截文件；
- 损坏文件 _load 时隔离改名，绝不被下次 _save 用空态覆盖。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.core.atomic_io import atomic_write_text, quarantine_corrupt_file
from neurova.knowledge.repository import KnowledgeRepository


def test_atomic_write_no_partial_file(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_text(target, json.dumps({"a": 1}))
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "data.json.tmp").exists()


def test_corrupt_file_is_quarantined_not_overwritten(tmp_path, monkeypatch, caplog):
    """主文件半截 JSON → 隔离保留现场，内存态为空但原文件不留在原地。"""
    repo_dir = tmp_path / "kb"
    repo_dir.mkdir()
    corrupt = repo_dir / "knowledge.json"
    corrupt.write_text('{"agent-1": [{"knowledge_id": "k1", "ti', encoding="utf-8")

    repo = KnowledgeRepository(storage_dir=str(repo_dir))
    # 数据不可恢复地丢失于内存视图……
    assert repo._items == {}
    # ……但真数据文件被改名保留，未被清空覆盖
    leftovers = [p.name for p in repo_dir.iterdir()]
    assert not corrupt.exists()
    assert any(".corrupt-" in n for n in leftovers), leftovers


def test_roundtrip_after_atomic_save(tmp_path):
    repo_dir = tmp_path / "kb2"
    repo_dir.mkdir()
    repo = KnowledgeRepository(storage_dir=str(repo_dir))
    item = repo.create_knowledge(agent_id="a1", title="T", content="C", source="user")
    repo2 = KnowledgeRepository(storage_dir=str(repo_dir))
    found = repo2.get_item(agent_id="a1", knowledge_id=item["knowledge_id"])
    assert found is not None and found["title"] == "T"
