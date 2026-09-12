# -*- coding: utf-8 -*-
"""B-9（台账 2026-09-11 第五节）防回归：会话摘要/反馈统计的 mtime 缓存。

- 摘要缓存：同一文件未变时重复 list_sessions 不再重复 json.load；
- mtime 失效：写入消息后列表立即反映更新；
- get_feedback_counts 与 get_history 手工聚合一致（跨日期文件聚合、
  content 截断 100、明细最小字段）；
- 缓存条目有界（LRU 超限逐出最旧）+ 读写线程安全。

隔离纪律：NEUROVA_SESSIONS_DIR → tmp_path，无真实网络/用户文件/SQLite。
SessionManager 为进程级单例，fixture 直接清空缓存隔离跨测试残留。
"""

import json
import threading
from pathlib import Path

import pytest

from neurova.session_manager import SessionManager


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # CWD 隔离 + 相对 sessions 目录：与 test_session_round_ops 的单例共存
    # 姿势一致。重指派单例 _sessions_dir 为绝对路径会毒化依赖
    # chdir + 相对 sessions/ 的其他测试（预存干扰，session_count 文件同款），
    # 故此处用相对路径 + 退出时恢复原指向。
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sessions").mkdir(exist_ok=True)
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", "sessions")
    mgr = SessionManager()
    original_dir = mgr._sessions_dir
    mgr._sessions_dir = Path("sessions")  # 已初始化单例不再读 env，显式对齐
    # 单例跨测试复用：清掉上一测试残留的缓存条目
    mgr._summary_cache.clear()
    mgr._feedback_cache.clear()
    yield mgr
    mgr._sessions_dir = original_dir


class TestSummaryCache:
    def test_second_list_sessions_does_not_reparse(self, repo, tmp_path, monkeypatch):
        """①冷启动（无索引的外部存量数据）首次列表必须解析建索引；
        之后同一文件未变的重复 list_sessions 不再 json.load。

        （B-9 v2 sidecar 索引后锚点调整：写路径同步建索引，经 repo 方法
        创建的会话列表从首次起就零解析——该 O(索引) 主锚移至
        test_session_summary_sidecar.py；本用例保留"冷启动解析一次、
        之后零解析"的缓存复用不变量。）
        """
        agent_dir = tmp_path / "sessions" / "a1"
        agent_dir.mkdir(parents=True)
        (agent_dir / "session_s1_2026-01-01.json").write_text(
            json.dumps({
                "agent_id": "a1", "session_id": "s1", "session_date": "2026-01-01",
                "messages": [], "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00", "total_messages": 0,
                "title": "存量", "user_id": "u1",
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        calls = {"n": 0}
        real_read = repo._read_session_file

        def counting_read(file_path):
            calls["n"] += 1
            return real_read(file_path)

        monkeypatch.setattr(repo, "_read_session_file", counting_read)

        first = repo.list_sessions(agent_id="a1", user_id="u1")
        assert len(first) == 1
        after_first = calls["n"]
        assert after_first >= 1, "冷启动（无索引）首次列表必须解析文件重建索引"

        second = repo.list_sessions(agent_id="a1", user_id="u1")
        assert calls["n"] == after_first, "文件未变时第二次 list_sessions 不得重新 json.load"
        assert second == first, "缓存复用不得改变列表结果"

    def test_second_list_archived_sessions_does_not_reparse(self, repo, tmp_path, monkeypatch):
        """存档列表共用 _collect_summaries，同样享受缓存。"""
        (tmp_path / "sessions" / "a1").mkdir(parents=True)
        repo.create_session("a1", user_id="u1")
        repo.archive_session("a1", repo.list_sessions(agent_id="a1")[0]["session_id"])

        calls = {"n": 0}
        real_read = repo._read_session_file

        def counting_read(file_path):
            calls["n"] += 1
            return real_read(file_path)

        monkeypatch.setattr(repo, "_read_session_file", counting_read)

        assert len(repo.list_archived_sessions(agent_id="a1")) == 1
        after_first = calls["n"]
        assert len(repo.list_archived_sessions(agent_id="a1")) == 1
        assert calls["n"] == after_first, "文件未变时第二次存档列表不得重新 json.load"

    def test_write_invalidates_summary_cache(self, repo):
        """②写入消息后列表必须立即反映更新（mtime/size 失效正确）。"""
        repo.create_session("a2", user_id="u1")
        before = repo.list_sessions(agent_id="a2")[0]
        assert before["total_messages"] == 0

        repo.add_message("a2", before["session_id"], "hello", "hi there", user_id="u1")

        after = repo.list_sessions(agent_id="a2")[0]
        assert after["total_messages"] == 2, "写入后列表必须反映更新（mtime 失效）"

        repo.rename_session("a2", before["session_id"], "改名了")
        assert repo.list_sessions(agent_id="a2")[0]["title"] == "改名了"

    def test_cache_hit_returns_independent_copies(self, repo, tmp_path):
        """缓存复用返回副本：调用方改写返回摘要不得污染缓存。"""
        (tmp_path / "sessions" / "a1").mkdir(parents=True)
        repo.create_session("a1", user_id="u1")
        s1 = repo.list_sessions(agent_id="a1")[0]
        s1["title"] = "调用方污染"
        s2 = repo.list_sessions(agent_id="a1")[0]
        assert s2["title"] != "调用方污染"


class TestFeedbackCounts:
    def test_counts_match_manual_aggregation_from_history(self, repo):
        """③get_feedback_counts 与 get_history 手工数出的 like/dislike 一致。"""
        agent, sid = "a3", "s3"
        rows = [
            ("user", "q1", None),
            ("assistant", "a1", {"feedback": "like"}),
            ("user", "q2", None),
            ("assistant", "a2", {"feedback": "dislike"}),
            ("assistant", "a3", {"feedback": "like"}),
            ("assistant", "a4", None),
        ]
        for role, content, meta in rows:
            repo.save_message(agent, sid, role, content, metadata=meta)

        msgs = repo.get_history(agent, sid)
        manual_like = sum(
            1 for m in msgs
            if m.get("role") == "assistant" and (m.get("metadata") or {}).get("feedback") == "like"
        )
        manual_dislike = sum(
            1 for m in msgs
            if m.get("role") == "assistant" and (m.get("metadata") or {}).get("feedback") == "dislike"
        )

        counts = repo.get_feedback_counts(agent, sid)
        assert (manual_like, manual_dislike) == (2, 1)
        assert counts["like"] == manual_like
        assert counts["dislike"] == manual_dislike
        assert len(counts["items"]) == 3
        for it in counts["items"]:
            assert set(it) == {"session_id", "timestamp", "content", "feedback"}
            assert it["session_id"] == sid

    def test_aggregates_across_date_files(self, repo):
        """跨日期文件聚合（旧→新），计数与明细都合并。"""
        agent, sid = "a4", "s4"
        for date, fb, ts in (
            ("2026-01-01", "like", "2026-01-01T00:00:00"),
            ("2026-01-02", "dislike", "2026-01-02T00:00:00"),
        ):
            fp = repo._get_session_file(agent, sid, date)
            repo._write_session_file(fp, {
                "agent_id": agent, "session_id": sid, "session_date": date,
                "messages": [{
                    "role": "assistant", "content": "r", "timestamp": ts,
                    "metadata": {"feedback": fb},
                }],
                "total_messages": 1, "user_id": "",
            })

        counts = repo.get_feedback_counts(agent, sid)
        assert counts["like"] == 1 and counts["dislike"] == 1
        assert [it["timestamp"] for it in counts["items"]] == [
            "2026-01-01T00:00:00", "2026-01-02T00:00:00",
        ]

    def test_items_truncate_content_to_100(self, repo):
        agent, sid = "a5", "s5"
        repo.save_message(agent, sid, "assistant", "x" * 300, metadata={"feedback": "like"})

        counts = repo.get_feedback_counts(agent, sid)
        assert counts["items"][0]["content"] == "x" * 100

    def test_feedback_cache_reflects_metadata_update(self, repo):
        """反馈聚合缓存同样按 mtime 失效：like 改 dislike 后计数翻转。"""
        agent, sid = "a6", "s6"
        repo.save_message(agent, sid, "assistant", "r", metadata={"feedback": "like"})
        ts = repo.get_history(agent, sid)[0]["timestamp"]
        assert repo.get_feedback_counts(agent, sid)["like"] == 1

        assert repo.update_message_metadata(agent, sid, ts, {"feedback": "dislike"}) is True
        counts = repo.get_feedback_counts(agent, sid)
        assert counts["like"] == 0 and counts["dislike"] == 1

    def test_missing_session_returns_zero(self, repo):
        counts = repo.get_feedback_counts("ghost-agent", "ghost-sid")
        assert counts == {"like": 0, "dislike": 0, "items": []}


class TestCacheBoundedAndThreadSafe:
    def test_lru_eviction_bounded(self, repo, monkeypatch):
        """④缓存有界：超限逐出最旧，命中刷新 LRU 顺序。"""
        monkeypatch.setattr(repo, "_SUMMARY_CACHE_MAX", 5)
        for i in range(8):
            repo._cache_put(repo._summary_cache, ("k", i), {"v": i}, repo._SUMMARY_CACHE_MAX)
        assert len(repo._summary_cache) <= 5
        assert ("k", 7) in repo._summary_cache
        assert ("k", 0) not in repo._summary_cache, "超限应逐出最旧"

        repo._cache_get(repo._summary_cache, ("k", 3))
        for i in range(8, 10):
            repo._cache_put(repo._summary_cache, ("k", i), {"v": i}, repo._SUMMARY_CACHE_MAX)
        assert ("k", 3) in repo._summary_cache, "最近命中的键不得被逐出"
        assert ("k", 4) not in repo._summary_cache

    def test_feedback_cache_bounded(self, repo, monkeypatch):
        monkeypatch.setattr(repo, "_FEEDBACK_CACHE_MAX", 3)
        for i in range(5):
            repo._cache_put(repo._feedback_cache, ("f", i), {"like": i}, repo._FEEDBACK_CACHE_MAX)
        assert len(repo._feedback_cache) <= 3

    def test_cache_thread_safe_smoke(self, repo):
        """读写并发 smoke：RLock 保护下无异常、条目数不超上限。"""
        errors = []

        def worker(n):
            try:
                for i in range(300):
                    key = ("t", n, i % 50)
                    repo._cache_put(repo._summary_cache, key, {"v": i}, repo._SUMMARY_CACHE_MAX)
                    repo._cache_get(repo._summary_cache, key)
            except Exception as e:  # pragma: no cover - 仅失败时收集
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(repo._summary_cache) <= repo._SUMMARY_CACHE_MAX
