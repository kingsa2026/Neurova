# -*- coding: utf-8 -*-
"""C3：data/generations 产物保留清理（台账 AIGC 遗留项台账_细化 C3）。

契约：
- NEUROVA_GENERATION_RETENTION_DAYS 默认 0=关闭（保守；用户拍板不激进）；
- 仅删「账本终态 + 超期 + 路径在产物目录内」的文件；**账本行永不删**
  （历史面板据此显示已过期态）；
- 引用完整性：Studio 库（storyboards/characters/assets/episodes/merges）
  在引用的路径一律保护；Studio 库读取失败 → 本轮整体放弃（宁可不清，
  不冒删用在产物之险）；
- 产物目录之外的路径拒删（安全守卫）；
- 无账本记录的文件不扫描不删除（纯账本驱动）。
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from neurova.llm.generators import retention as rt
from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord

pytestmark = pytest.mark.timeout(60)

DAY = 86400.0


@pytest.fixture()
def ledger(tmp_path):
    return GenerationTaskLedger(path=str(tmp_path / "led.json"))


@pytest.fixture()
def out_dir(tmp_path):
    d = tmp_path / "generations"
    d.mkdir()
    return d


def _rec(led, task_id, path, status="done", age_days=10):
    return led.add(TaskRecord(
        kind="image", task_id=task_id, status=status, local_path=path,
        submitted_at=rt_time(age_days), updated_at=rt_time(age_days)))


def rt_time(age_days):
    import time
    return time.time() - age_days * DAY


class TestPurge:
    def test_expired_terminal_no_ref_deleted_ledger_row_kept(self, ledger, out_dir):
        f = out_dir / "old.png"
        f.write_bytes(b"X")
        _rec(ledger, "t1", str(f))
        stats = rt.purge_expired_files(ledger, referenced=set(), days=7, out_dir=out_dir)
        assert stats["deleted"] == 1
        assert not f.exists()
        # 账本行永不删：仍可查到，文件已失
        assert ledger.get("t1") is not None

    def test_referenced_path_protected(self, ledger, out_dir):
        f = out_dir / "in_use.png"
        f.write_bytes(b"X")
        _rec(ledger, "t2", str(f))
        stats = rt.purge_expired_files(ledger, referenced={str(f)}, days=7, out_dir=out_dir)
        assert stats["skipped_protected"] == 1
        assert f.exists()

    def test_no_ledger_file_untouched(self, ledger, out_dir):
        f = out_dir / "orphan.png"
        f.write_bytes(b"X")
        stats = rt.purge_expired_files(ledger, referenced=set(), days=7, out_dir=out_dir)
        assert stats["deleted"] == 0 and f.exists()

    def test_unexpired_terminal_not_deleted(self, ledger, out_dir):
        f = out_dir / "fresh.png"
        f.write_bytes(b"X")
        _rec(ledger, "t3", str(f), age_days=2)
        stats = rt.purge_expired_files(ledger, referenced=set(), days=7, out_dir=out_dir)
        assert stats["deleted"] == 0 and f.exists()

    def test_non_terminal_status_not_deleted(self, ledger, out_dir):
        f = out_dir / "running.png"
        f.write_bytes(b"X")
        _rec(ledger, "t4", str(f), status="running")
        stats = rt.purge_expired_files(ledger, referenced=set(), days=7, out_dir=out_dir)
        assert stats["deleted"] == 0 and f.exists()

    def test_path_outside_output_dir_refused(self, ledger, out_dir, tmp_path):
        outside = tmp_path / "secret"
        outside.mkdir()
        f = outside / "keep.png"
        f.write_bytes(b"X")
        _rec(ledger, "t5", str(f))
        stats = rt.purge_expired_files(ledger, referenced=set(), days=7, out_dir=out_dir)
        assert stats["deleted"] == 0
        assert stats["skipped_outside"] == 1
        assert f.exists()

    def test_days_zero_disables(self, ledger, out_dir):
        f = out_dir / "old2.png"
        f.write_bytes(b"X")
        _rec(ledger, "t6", str(f))
        stats = rt.purge_expired_files(ledger, referenced=set(), days=0, out_dir=out_dir)
        assert stats.get("disabled") is True
        assert f.exists()

    def test_referenced_none_aborts_conservatively(self, ledger, out_dir):
        """Studio 库读失败（referenced=None）→ 整轮放弃，一文件不删。"""
        f = out_dir / "old3.png"
        f.write_bytes(b"X")
        _rec(ledger, "t7", str(f))
        stats = rt.purge_expired_files(ledger, referenced=None, days=7, out_dir=out_dir)
        assert stats.get("aborted") is True
        assert f.exists()


class TestReferenceCollector:
    def test_reads_studio_tables(self, tmp_path):
        from neurova.aigc_studio.store import StudioStore

        db = tmp_path / "studio.db"
        store = StudioStore(db_path=str(db))
        p = store.create_project("u1", title="T")
        ep = store.add_episode(p["id"], {"number": 1, "title": "e"})
        store.update_episode(ep["id"], {"video_path": str(db.parent / "ep.mp4")})
        store.add_character(p["id"], {"name": "c", "image_path": str(db.parent / "c.png")})
        store.add_asset({"project_id": p["id"], "kind": "character", "name": "c",
                         "ref_path": str(db.parent / "a.png")})
        store.close()
        refs = rt.collect_referenced_paths(db_path=str(db))
        assert refs is not None
        assert str(db.parent / "ep.mp4") in refs
        assert str(db.parent / "c.png") in refs
        assert str(db.parent / "a.png") in refs

    def test_missing_db_is_safe_empty(self, tmp_path):
        # 从未建库 = Studio 无产物可引用，set() 安全
        assert rt.collect_referenced_paths(db_path=str(tmp_path / "nope.db")) == set()

    def test_corrupt_db_returns_none_conservative(self, tmp_path):
        # 损坏库 ≠ 空引用：必须 None 触发整轮放弃（宁可不清）
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"NOT A SQLITE FILE AT ALL" * 100)
        assert rt.collect_referenced_paths(db_path=str(bad)) is None


class TestBootstrap:
    def test_env_off_returns_none(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_GENERATION_RETENTION_DAYS", "0")
        assert rt.start_retention_bootstrap() is None

    def test_env_on_creates_task(self, monkeypatch):
        import asyncio

        monkeypatch.setenv("NEUROVA_GENERATION_RETENTION_DAYS", "30")
        monkeypatch.setattr(rt, "_purge_once", lambda: {})

        async def scenario():
            task = rt.start_retention_bootstrap()
            assert task is not None
            await task

        asyncio.run(scenario())
