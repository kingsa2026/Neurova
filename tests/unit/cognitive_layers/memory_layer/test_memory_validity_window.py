# -*- coding: utf-8 -*-
"""C6（graphiti 对照批）：记忆行 fact 级有效期（valid_from/valid_until）。

语义与 knowledge_facts/temporal_facts 的判活口径同源：生效窗口外不进
检索召回；两字段缺省 NULL＝永远有效，旧行为零变化。判活谓词单点在
`Memory.isVisibleAt`——recall 与 searchMemoriesFulltext 共用，不各写一份
时间谓词（防两处口径漂移）。
"""

import datetime

import pytest

from neurova.cognitive_layers.memory_layer.models import Memory

NOW = datetime.datetime(2026, 11, 14, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _mgr(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agt_v")


class TestMemoryVisibility:
    def test_defaultAlwaysVisible(self):
        """未设窗口（NULL）＝永远有效——旧行为零变化。"""
        assert Memory(id="m1", content="x").isVisibleAt(NOW) is True

    def test_expiredNotVisible(self):
        m = Memory(id="m2", content="x",
                   valid_until=NOW - datetime.timedelta(days=1))
        assert m.isVisibleAt(NOW) is False

    def test_futureNotVisible(self):
        m = Memory(id="m3", content="x",
                   valid_from=NOW + datetime.timedelta(days=1))
        assert m.isVisibleAt(NOW) is False

    def test_activeWindowVisible(self):
        m = Memory(id="m4", content="x",
                   valid_from=NOW - datetime.timedelta(days=1),
                   valid_until=NOW + datetime.timedelta(days=1))
        assert m.isVisibleAt(NOW) is True

    def test_naiveTimestampsTreatedAsUtc(self):
        """naive 时间戳按 UTC 判（与库内 ISO 串回填口径一致）。"""
        m = Memory(id="m5", content="x",
                   valid_until=(NOW - datetime.timedelta(days=1)).replace(tzinfo=None))
        assert m.isVisibleAt(NOW) is False

    def test_roundTripCarriesWindow(self):
        m = Memory(id="m6", content="x",
                   valid_from=NOW - datetime.timedelta(days=2),
                   valid_until=NOW + datetime.timedelta(days=2))
        d = m.to_dict()
        assert d["valid_from"] is not None and d["valid_until"] is not None
        back = Memory.from_dict(d)
        assert back.valid_from == m.valid_from
        assert back.valid_until == m.valid_until

    def test_roundTripNoneStaysNone(self):
        d = Memory(id="m7", content="x").to_dict()
        assert d["valid_from"] is None and d["valid_until"] is None
        back = Memory.from_dict(d)
        assert back.valid_from is None and back.valid_until is None


class TestManagerValidity:
    def test_expiredNotRecalled(self, tmp_path):
        mgr = _mgr(tmp_path)
        try:
            mgr.remember("过期事实", valid_until=NOW - datetime.timedelta(days=1))
            mgr.remember("有效事实")
            hits = mgr.recall(query="事实", use_semantic=False)
            contents = [h["content"] for h in hits]
            assert "过期事实" not in contents, "已失效记忆不得再被召回"
            assert "有效事实" in contents
        finally:
            mgr.close()

    def test_futureNotRecalled(self, tmp_path):
        mgr = _mgr(tmp_path)
        try:
            mgr.remember("未来事实", valid_from=NOW + datetime.timedelta(days=1))
            mgr.remember("现在事实")
            hits = mgr.recall(query="事实", use_semantic=False)
            contents = [h["content"] for h in hits]
            assert "未来事实" not in contents, "未生效记忆不得被召回"
            assert "现在事实" in contents
        finally:
            mgr.close()

    def test_fulltextSkipsExpired(self, tmp_path):
        mgr = _mgr(tmp_path)
        try:
            mgr.remember("齿轮箱维护手册", valid_until=NOW - datetime.timedelta(days=1))
            mgr.remember("齿轮箱安装手册")
            hits = mgr.searchMemoriesFulltext("齿轮箱")
            contents = [m.content for m in hits]
            assert "齿轮箱维护手册" not in contents
            assert "齿轮箱安装手册" in contents
        finally:
            mgr.close()

    def test_windowSurvivesReload(self, tmp_path):
        """窗口字段随持久化 round-trip：重启装载后过期记忆仍不可见。"""
        mgr = _mgr(tmp_path)
        try:
            mgr.remember("会过期的记忆", valid_until=NOW - datetime.timedelta(days=1))
        finally:
            mgr.close()
        mgr2 = _mgr(tmp_path)
        try:
            assert mgr2.recall(query="会过期", use_semantic=False) == []
        finally:
            mgr2.close()

    def test_migration7AddsColumns(self, tmp_path):
        """v7 迁移落列：memories 增 valid_from/valid_until 两个可空列。"""
        mgr = _mgr(tmp_path)
        try:
            cols = {r[1] for r in mgr._persist_conn.execute(
                "PRAGMA table_info(memories)").fetchall()}
            assert "valid_from" in cols and "valid_until" in cols
        finally:
            mgr.close()
