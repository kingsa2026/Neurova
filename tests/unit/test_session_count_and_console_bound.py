"""RES-P1-4 / RES-P2-13 回归测试。

- count_sessions 零解析快路径：home 统计不再为取个数全量 json.load
  全部会话消息（判据：文件内容为非法 JSON 时计数依然正确）。
- console ConnectionManager._messages 每用户有界（旧 list 只增不清）。
"""

import pytest
from pathlib import Path

from neurova.session_manager import SessionManager


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """隔离姿势与 test_session_round_ops 一致：chdir + 相对 sessions/ 目录。

    严禁把单例 _sessions_dir 重指派为绝对路径——本文件结束后它仍驻留
    单例，会毒化后续依赖"相对 sessions/ 跟随 CWD"的测试（round_ops 同跑
    曾因此必现 7 失败）。相对路径让 _sessions_dir 天然跟随 monkeypatch.chdir。
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    mgr = SessionManager()
    # 显式归位相对路径：全量顺序下先前测试可能把单例指到绝对路径；
    # monkeypatch 结束后自动恢复原值——双向都不毒化
    monkeypatch.setattr(mgr, "_sessions_dir", Path("sessions"), raising=False)
    return mgr


def _mk_agent_dir(root, name):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestCountSessions:
    def test_counts_by_filename_without_parsing(self, repo, tmp_path):
        agent = _mk_agent_dir(Path("sessions"), "agentA")
        # 内容全部非法 JSON——若实现尝试解析会抛错/漏计，计数必须照常正确
        (agent / "session_s1_2026-01-01.json").write_text("{broken", encoding="utf-8")
        (agent / "session_s1_2026-01-02.json").write_text("{broken", encoding="utf-8")
        (agent / "session_s2_2026-01-03.json").write_text("{broken", encoding="utf-8")
        (agent / "not_a_session.json").write_text("{}", encoding="utf-8")

        assert repo.count_sessions() == 2, "同 session 多日期应去重、非 session 文件不计"

    def test_zero_count_when_no_dir(self, repo, tmp_path):
        assert repo.count_sessions() == 0

    def test_specific_agent_dir(self, repo, tmp_path):
        a = _mk_agent_dir(Path("sessions"), "agentA")
        b = _mk_agent_dir(Path("sessions"), "agentB")
        (a / "session_x_2026-01-01.json").write_text("{broken", encoding="utf-8")
        (b / "session_y_2026-01-01.json").write_text("{broken", encoding="utf-8")

        assert repo.count_sessions(agent_id="agentA") == 1
        assert repo.count_sessions(agent_id="agentB") == 1

    def test_user_id_filter_falls_back_to_summaries(self, repo, tmp_path):
        agent = _mk_agent_dir(Path("sessions"), "agentA")
        (agent / "session_s1_2026-01-01.json").write_text(
            '{"session_id":"s1","user_id":"u1","messages":[]}', encoding="utf-8"
        )
        # 回退路径走真实解析：合法 JSON + user_id 命中 → 计 1
        assert repo.count_sessions(user_id="u1") == 1
        assert repo.count_sessions(user_id="nobody") == 0


class TestConsoleMessageBuffer:
    def test_per_user_buffer_bounded(self):
        from neurova.api.endpoints.console import ConnectionManager

        cm = ConnectionManager()
        for i in range(150):
            cm.store_message("u1", {"i": i})

        buf = cm._messages["u1"]
        assert len(buf) <= cm.MAX_USER_MESSAGES, "每用户消息缓冲必须封顶"
        msgs = cm.get_messages("u1")
        assert msgs[0]["i"] == 150 - cm.MAX_USER_MESSAGES, "超限应丢最旧"
        assert msgs[-1]["i"] == 149

    def test_users_isolated(self):
        from neurova.api.endpoints.console import ConnectionManager

        cm = ConnectionManager()
        cm.store_message("u1", {"i": 1})
        cm.store_message("u2", {"i": 2})
        assert [m["i"] for m in cm.get_messages("u1")] == [1]
        assert [m["i"] for m in cm.get_messages("u2")] == [2]
