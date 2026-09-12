# -*- coding: utf-8 -*-
"""B-9 v2（台账 2026-09-11，用户拍板 sidecar 索引方案）防回归测试。

替代 v1 的 (路径, mtime, size) 进程内 LRU 读缓存（tests/unit/api/
test_session_summary_cache.py 保留其仍有效的行为锚），升级为落盘
摘要 sidecar 索引 `_summary_index.json`（每 agent 目录一份）：

- 写路径同步接线：create/add/save/rename/pin/sort/delete_round/
  update_message_metadata/delete/archive/unarchive 改摘要字段时
  在既有锁内同步更新索引；
- 读路径：list_sessions/list_archived_sessions 优先读索引（零会话
  文件解析）；索引缺失/损坏/版本不符/指纹失配 → 回退全量扫描并
  顺手重建（自愈）；
- feedback 计数/明细走索引，console stats 端点不再 get_history 全量；
- 一致性红线：任何操作后索引视图与全量扫描视图逐字段一致。

隔离纪律：NEUROVA_SESSIONS_DIR → tmp_path（chdir + 相对 sessions/，
不毒化单例 _sessions_dir），无真实网络/真实 SQLite。
"""

import asyncio
import json
import threading
import types
from pathlib import Path

import pytest

from neurova.session_manager import SessionManager


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """隔离姿势与 test_session_count_and_console_bound 一致：
    chdir + 相对 sessions/ 目录（单例 _sessions_dir 天然跟随 CWD）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_sessions_dir", Path("sessions"), raising=False)
    # 单例跨测试复用：清掉上一测试残留的缓存条目
    mgr._summary_cache.clear()
    mgr._feedback_cache.clear()
    if hasattr(mgr, "_sidecar_cache"):
        mgr._sidecar_cache.clear()
    yield mgr


def _sidecar_path(agent_id: str) -> Path:
    return Path("sessions") / (agent_id or "default") / "_summary_index.json"


def _count_session_parses(repo, monkeypatch):
    """统计会话文件 JSON 解析次数（sidecar 自身的小文件直读不计入）。"""
    calls = {"n": 0}
    real_read = repo._read_session_file

    def counting_read(file_path):
        calls["n"] += 1
        return real_read(file_path)

    monkeypatch.setattr(repo, "_read_session_file", counting_read)
    return calls


def _forced_scan_list(repo, **kw):
    """绕过 sidecar 快路径（快路径桩返回 None）取全量扫描对照基准。"""
    orig = repo._summaries_via_sidecar
    repo._summaries_via_sidecar = lambda dirs, uid: None
    try:
        return repo.list_sessions(**kw)
    finally:
        repo._summaries_via_sidecar = orig


def _assert_index_scan_parity(repo, **kw):
    """一致性质检：sidecar 视图与全量扫描视图逐字段一致。"""
    fast = repo.list_sessions(**kw)
    forced = _forced_scan_list(repo, **kw)
    key = lambda s: s.get("session_id", "")
    assert sorted(fast, key=key) == sorted(forced, key=key), (
        f"sidecar 视图与全量扫描不一致: fast={fast} forced={forced}"
    )


def _write_external_session(agent_id: str, sid: str, title: str = "外来",
                            date: str = "2026-01-01", user_id: str = "",
                            messages=None) -> Path:
    d = Path("sessions") / agent_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"session_{sid}_{date}.json"
    p.write_text(json.dumps({
        "agent_id": agent_id, "session_id": sid, "session_date": date,
        "messages": messages or [], "created_at": f"{date}T00:00:00",
        "updated_at": f"{date}T00:00:00", "total_messages": len(messages or []),
        "title": title, "user_id": user_id,
    }, ensure_ascii=False), encoding="utf-8")
    return p


class TestSidecarIndexLifecycle:
    def test_sidecar_created_by_wired_writes_and_list_zero_parse(self, repo, monkeypatch):
        """写路径已同步索引：列表零会话文件解析（O(索引) 主锚）。"""
        sid = repo.create_session("zf", user_id="u1")
        repo.add_message("zf", sid, "q", "a", user_id="u1")

        assert _sidecar_path("zf").exists(), "create_session 必须落盘 sidecar 索引"
        calls = _count_session_parses(repo, monkeypatch)
        first = repo.list_sessions(agent_id="zf")
        assert calls["n"] == 0, "索引新鲜时 list_sessions 不得解析任何会话文件"
        assert [s["session_id"] for s in first] == [sid]
        assert first[0]["total_messages"] == 2

        second = repo.list_sessions(agent_id="zf")
        assert calls["n"] == 0, "第二次列表同样零解析"
        assert second == first

    def test_cold_rebuild_then_zero_parse(self, repo, monkeypatch):
        """外部存量数据（无索引）→ 首次列表全量扫描重建，之后零解析。"""
        _write_external_session("cold", "old1", title="存量会话",
                                messages=[{"role": "user", "content": "hi",
                                           "timestamp": "2026-01-01T00:00:00"}])
        calls = _count_session_parses(repo, monkeypatch)
        out = repo.list_sessions(agent_id="cold")
        assert calls["n"] >= 1, "冷启动（无索引）必须解析会话文件重建索引"
        assert [s["session_id"] for s in out] == ["old1"]
        assert out[0]["total_messages"] == 1
        assert _sidecar_path("cold").exists(), "回退扫描必须顺手重建索引"

        n_after_first = calls["n"]
        out2 = repo.list_sessions(agent_id="cold")
        assert out2 == out
        assert calls["n"] == n_after_first, "索引建成后列表不得再解析"

    def test_sidecar_matches_full_scan_after_each_mutation(self, repo):
        """一致性质检：每个变更操作后索引视图 == 全量扫描视图。"""
        a = repo.create_session("cx", user_id="u1")
        _assert_index_scan_parity(repo, agent_id="cx")

        repo.add_message("cx", a, "q1", "a1", user_id="u1")
        _assert_index_scan_parity(repo, agent_id="cx")

        repo.rename_session("cx", a, "改名了")
        repo.set_session_pinned("cx", a, True)
        _assert_index_scan_parity(repo, agent_id="cx")

        b = repo.create_session("cx", user_id="u2")
        repo.add_message("cx", b, "q2", "a2", user_id="u2")
        repo.set_sessions_sort_order("cx", [b, a])
        _assert_index_scan_parity(repo, agent_id="cx")

        ts = repo.get_history("cx", a)[0]["timestamp"]
        assert repo.update_message_metadata("cx", a, ts, {"feedback": "like"},
                                            role="assistant") is True
        _assert_index_scan_parity(repo, agent_id="cx")

        deleted = repo.delete_round("cx", a, ts)
        assert len(deleted) == 2
        _assert_index_scan_parity(repo, agent_id="cx")

        repo.delete_session("cx", b)
        repo.set_session_pinned("cx", a, False)
        _assert_index_scan_parity(repo, agent_id="cx")
        _assert_index_scan_parity(repo)  # 全局（跨 agent 目录）视图

    def test_user_filter_resolved_on_index(self, repo, monkeypatch):
        """user_id 过滤在索引上完成（零会话文件解析）。"""
        repo.create_session("uf", user_id="u1")
        repo.create_session("uf", user_id="u2")
        repo.list_sessions(agent_id="uf")  # 预热（实际写路径已建索引）

        calls = _count_session_parses(repo, monkeypatch)
        out = repo.list_sessions(agent_id="uf", user_id="u1")
        assert calls["n"] == 0, "user 过滤必须走索引，不得解析会话文件"
        assert [s["user_id"] for s in out] == ["u1"]

        out_all = repo.list_sessions(agent_id="uf")
        assert calls["n"] == 0
        assert {s["user_id"] for s in out_all} == {"u1", "u2"}

    def test_archived_list_uses_sidecar(self, repo):
        """存档列表同样走索引，与全量扫描一致。"""
        sid = repo.create_session("ar", user_id="")
        repo.add_message("ar", sid, "q", "a")
        repo.archive_session("ar", sid)

        fast_arch = repo.list_archived_sessions(agent_id="ar")
        assert [s["session_id"] for s in fast_arch] == [sid]
        assert _sidecar_path("ar/archived").exists(), "存档目录必须建独立索引"
        assert repo.list_sessions(agent_id="ar") == []

        _assert_index_scan_parity(repo, agent_id="ar")

        repo.unarchive_session("ar", sid)
        assert [s["session_id"] for s in repo.list_sessions(agent_id="ar")] == [sid]
        assert repo.list_archived_sessions(agent_id="ar") == []
        _assert_index_scan_parity(repo, agent_id="ar")

    def test_delete_session_removes_index_entry(self, repo):
        sid = repo.create_session("del", user_id="")
        repo.list_sessions(agent_id="del")
        data = json.loads(_sidecar_path("del").read_text(encoding="utf-8"))
        assert sid in data["sessions"]

        assert repo.delete_session("del", sid) is True
        data = json.loads(_sidecar_path("del").read_text(encoding="utf-8"))
        assert sid not in data["sessions"], "删除后索引条目必须清理"
        assert repo.list_sessions(agent_id="del") == []


class TestSidecarSelfHealing:
    def test_corrupt_sidecar_rebuilt(self, repo):
        """索引损坏 → 回退扫描重建，结果仍正确且索引恢复合法。"""
        sid = repo.create_session("sh", user_id="u1")
        assert [s["session_id"] for s in repo.list_sessions(agent_id="sh")] == [sid]

        _sidecar_path("sh").write_text("{corrupt!!", encoding="utf-8")
        out = repo.list_sessions(agent_id="sh")
        assert [s["session_id"] for s in out] == [sid]

        data = json.loads(_sidecar_path("sh").read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert sid in data["sessions"]

    def test_version_mismatch_rebuilt(self, repo):
        sid = repo.create_session("vm", user_id="")
        repo.list_sessions(agent_id="vm")
        p = _sidecar_path("vm")
        data = json.loads(p.read_text(encoding="utf-8"))
        data["schema_version"] = 9999
        p.write_text(json.dumps(data), encoding="utf-8")

        out = repo.list_sessions(agent_id="vm")
        assert [s["session_id"] for s in out] == [sid]
        rebuilt = json.loads(p.read_text(encoding="utf-8"))
        assert rebuilt["schema_version"] != 9999

    def test_external_file_add_and_remove_self_heal(self, repo):
        """外部绕过 manager 增删会话文件 → 指纹/文件集校验触发重建。"""
        sid = repo.create_session("ea", user_id="u1")
        assert {s["session_id"] for s in repo.list_sessions(agent_id="ea")} == {sid}

        _write_external_session("ea", "extx", title="外来会话", user_id="u1")
        assert {s["session_id"] for s in repo.list_sessions(agent_id="ea")} == {sid, "extx"}

        (Path("sessions") / "ea" / "session_extx_2026-01-01.json").unlink()
        assert {s["session_id"] for s in repo.list_sessions(agent_id="ea")} == {sid}

    def test_external_modification_detected_by_fingerprint(self, repo):
        """外部改写会话内容（mtime/size 变化）→ 指纹失配 → 重建反映新内容。"""
        sid = repo.create_session("fp", user_id="u1")
        assert repo.list_sessions(agent_id="fp")[0]["title"] == "新对话"

        f = next((Path("sessions") / "fp").glob(f"session_{sid}_*.json"))
        data = json.loads(f.read_text(encoding="utf-8"))
        data["title"] = "外部改名"
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        out = repo.list_sessions(agent_id="fp")
        assert out[0]["title"] == "外部改名", "指纹失配必须触发重建，不得吃掉外部修改"


class TestFeedbackSidecar:
    def test_counts_via_index_zero_parse(self, repo, monkeypatch):
        """反馈计数走索引：save/update 接线后计数零会话文件解析。"""
        sid = repo.create_session("fb1", user_id="")
        repo.save_message("fb1", sid, "assistant", "r1", metadata={"feedback": "like"})
        repo.save_message("fb1", sid, "assistant", "r2", metadata={"feedback": "dislike"})
        ts = repo.get_history("fb1", sid)[0]["timestamp"]
        # like 改 dislike：增量必须正确（+1 dislike / -1 like）
        assert repo.update_message_metadata("fb1", sid, ts, {"feedback": "dislike"},
                                            role="assistant") is True

        calls = _count_session_parses(repo, monkeypatch)
        counts = repo.get_feedback_counts("fb1", sid)
        assert counts["like"] == 0 and counts["dislike"] == 2
        assert calls["n"] == 0, "反馈计数必须走 sidecar 索引"
        assert len(counts["items"]) == 2
        for it in counts["items"]:
            assert set(it) == {"session_id", "timestamp", "content", "feedback"}
            assert it["session_id"] == sid

    def test_feedback_cancel_via_none_patch(self, repo):
        """feedback=None（取消反馈）→ 计数与明细同步回落。"""
        sid = repo.create_session("fb2", user_id="")
        repo.save_message("fb2", sid, "assistant", "r", metadata={"feedback": "like"})
        ts = repo.get_history("fb2", sid)[0]["timestamp"]
        assert repo.update_message_metadata("fb2", sid, ts, {"feedback": None},
                                            role="assistant") is True
        assert repo.get_feedback_counts("fb2", sid) == {"like": 0, "dislike": 0, "items": []}

    def test_non_feedback_patch_keeps_counts(self, repo):
        """checkpoint 等非反馈补丁：计数不变，仅 updated_at 随索引更新。"""
        sid = repo.create_session("fb3", user_id="")
        repo.save_message("fb3", sid, "assistant", "r", metadata={"feedback": "like"})
        ts = repo.get_history("fb3", sid)[0]["timestamp"]
        assert repo.update_message_metadata("fb3", sid, ts, {"checkpoint": True}) is True
        assert repo.get_feedback_counts("fb3", sid)["like"] == 1
        _assert_index_scan_parity(repo, agent_id="fb3")

    def test_delete_round_decrements_feedback(self, repo):
        """删除带反馈的轮次：索引计数/明细同步递减。"""
        sid = repo.create_session("fb4", user_id="")
        repo.add_message("fb4", sid, "q", "a")
        hist = repo.get_history("fb4", sid)
        asst_ts = next(m["timestamp"] for m in hist if m["role"] == "assistant")
        repo.update_message_metadata("fb4", sid, asst_ts, {"feedback": "like"},
                                     role="assistant")
        assert repo.get_feedback_counts("fb4", sid)["like"] == 1

        deleted = repo.delete_round("fb4", sid, hist[0]["timestamp"])
        assert len(deleted) == 2
        assert repo.get_feedback_counts("fb4", sid) == {"like": 0, "dislike": 0, "items": []}
        assert repo.list_sessions(agent_id="fb4")[0]["total_messages"] == 0
        _assert_index_scan_parity(repo, agent_id="fb4")

    def test_fork_copied_feedback_counted(self, repo):
        """fork 链路（save_message 复制含 feedback 的 metadata）计数正确。"""
        src = repo.create_session("forksrc", user_id="")
        repo.save_message("forksrc", src, "assistant", "r", metadata={"feedback": "like"})
        msgs = repo.get_history("forksrc", src)
        dst = repo.create_session("forksrc", user_id="")
        for m in msgs:
            repo.save_message("forksrc", dst, m["role"], m["content"],
                              metadata=(m.get("metadata") or None))
        assert repo.get_feedback_counts("forksrc", dst)["like"] == 1

    def test_counts_fallback_when_index_absent(self, repo):
        """索引缺失（外部直写文件）→ 回退逐文件聚合，结果一致。"""
        _write_external_session("fbs", "x1", messages=[
            {"role": "assistant", "content": "r", "timestamp": "2026-01-01T00:00:00",
             "metadata": {"feedback": "like"}},
        ])
        counts = repo.get_feedback_counts("fbs", "x1")
        assert counts["like"] == 1 and counts["dislike"] == 0

    def test_recent_feedback_capped_at_20(self, repo):
        sid = repo.create_session("cap", user_id="")
        for i in range(25):
            repo.save_message("cap", sid, "assistant", f"r{i}", metadata={"feedback": "like"})
        counts = repo.get_feedback_counts("cap", sid)
        assert counts["like"] == 25, "计数必须精确"
        assert len(counts["items"]) == 20, "明细按最近 20 条封顶"


class TestFeedbackStatsEndpoint:
    def _call(self, agent_id="", limit=50):
        from neurova.api.endpoints.console import get_feedback_stats

        return asyncio.run(get_feedback_stats(
            request=types.SimpleNamespace(),
            current_user={"user_id": "u1"},
            agent_id=agent_id,
            limit=limit,
        ))

    def test_response_contract_unchanged(self, repo):
        """响应契约字段与 v1 完全一致。"""
        sid = repo.create_session("ep", user_id="")
        repo.save_message("ep", sid, "assistant", "回答甲", metadata={"feedback": "like"})
        repo.save_message("ep", sid, "assistant", "回答乙", metadata={"feedback": "dislike"})

        body = self._call(agent_id="ep")
        assert body["code"] == 0
        data = body["data"]
        assert set(data) == {"agent_id", "sessions_scanned", "total_feedback",
                             "like", "dislike", "recent"}
        assert data["like"] == 1 and data["dislike"] == 1
        assert data["total_feedback"] == 2
        assert data["sessions_scanned"] == 1
        assert len(data["recent"]) == 2
        for it in data["recent"]:
            assert set(it) == {"session_id", "timestamp", "content", "feedback"}
            assert it["session_id"] == sid

    def test_endpoint_never_pulls_full_history(self, repo, monkeypatch):
        """stats 端点不得触发 get_history 全量（B-9 核心诉求）。"""
        sid = repo.create_session("ep2", user_id="")
        repo.save_message("ep2", sid, "assistant", "r", metadata={"feedback": "like"})

        def _boom(*a, **k):
            raise AssertionError("stats 端点不得 get_history 全量拉取")

        monkeypatch.setattr(type(repo), "get_history", _boom)
        data = self._call(agent_id="ep2")["data"]
        assert data["like"] == 1 and data["sessions_scanned"] == 1

    def test_endpoint_second_call_zero_session_parse(self, repo, monkeypatch):
        """端点幂等调用零会话文件解析（O(索引)）。"""
        sid = repo.create_session("ep3", user_id="")
        repo.save_message("ep3", sid, "assistant", "r", metadata={"feedback": "dislike"})

        calls = _count_session_parses(repo, monkeypatch)
        self._call(agent_id="ep3")
        first = calls["n"]
        self._call(agent_id="ep3")
        assert calls["n"] == first, "第二次端点调用不得新增会话文件解析"
        assert first == 0, "写路径已建索引时端点调用应全程零解析"

    def test_endpoint_limit_respected(self, repo):
        for i in range(3):
            sid = repo.create_session("epl", user_id="")
            repo.save_message("epl", sid, "assistant", f"r{i}", metadata={"feedback": "like"})
        data = self._call(agent_id="epl", limit=2)["data"]
        assert data["sessions_scanned"] == 2
        assert data["like"] == 2


class TestConcurrencyAndContract:
    def test_concurrent_add_message_smoke(self, repo):
        """多线程 add_message 并发冒烟：锁序（会话锁→sidecar 锁）不炸、数据一致。"""
        sid = repo.create_session("cc", user_id="u1")
        errors = []

        def worker(n):
            try:
                for i in range(5):
                    repo.add_message("cc", sid, f"q{n}-{i}", f"a{n}-{i}", user_id="u1")
            except Exception as e:  # pragma: no cover - 仅失败时收集
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发写入异常: {errors}"
        fast = repo.list_sessions(agent_id="cc")
        assert fast[0]["total_messages"] == 80
        _assert_index_scan_parity(repo, agent_id="cc")

    def test_session_manager_implements_repository(self):
        from neurova.session_repository import SessionRepository

        assert isinstance(SessionManager(), SessionRepository)

    def test_summary_view_fields_unchanged(self, repo):
        """摘要对外字段与 v1 完全一致（不含 sidecar 内部字段泄漏）。"""
        sid = repo.create_session("fields", user_id="u1")
        repo.add_message("fields", sid, "q", "a", user_id="u1")
        summary = repo.list_sessions(agent_id="fields")[0]
        assert set(summary) == {"id", "session_id", "agent_id", "title", "user_id",
                                "created_at", "updated_at", "total_messages",
                                "pinned", "sort_order"}
