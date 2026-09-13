# -*- coding: utf-8 -*-
"""会话历史的审计/模型上下文分离（Yuxi 对比 P2 #14）。

甄别结论（本次实测）：Neurova 会话持久化天然只写 user+assistant 成对行
（add_message S1 契约），Yuxi 的 model_audit/tool_audit 双型问题在此不存在；
但 `save_message(role=任意)` 写侧不设防（当前唯一调用方是 session fork），
且读侧 `get_recent_context`（模型上下文唯一重建入口，/compact 同源）不过滤
role——若未来任何链路把工具/审计行写进会话，将直接进模型上下文诱发幻觉。
本契约把"审计不进模型上下文"钉成读侧不变量；展示路径 get_history 不动
（历史 UI 可见性语义不变，只提升不下降）。
"""
import pytest

from neurova import session_manager as sm_mod
from neurova.session_manager import SessionManager


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    # 单例 __new__：构造参数只首次生效，测试隔离走 NEUROVA_SESSIONS_DIR env
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    inst = SessionManager()
    yield inst
    SessionManager._instance = None


def _seed(sm):
    sid = sm.create_session(agent_id="a1", user_id="u1", title="t")
    sm.save_message(agent_id="a1", session_id=sid, role="user", content="q1")
    sm.save_message(agent_id="a1", session_id=sid, role="assistant", content="a1")
    # 模拟未来误写：审计/工具型行进入会话存储
    sm.save_message(agent_id="a1", session_id=sid, role="tool", content="RAW-TOOL-AUDIT")
    sm.save_message(agent_id="a1", session_id=sid, role="model_audit", content="RAW-MODEL-AUDIT")
    return sid


def test_recent_context_only_user_assistant(sm):
    sid = _seed(sm)
    ctx = sm.get_recent_context("a1", sid, max_messages=None)
    roles = {m["role"] for m in ctx}
    assert roles <= {"user", "assistant"}, f"审计/工具行泄入模型上下文: {roles}"
    contents = " ".join(m["content"] for m in ctx)
    assert "RAW-TOOL-AUDIT" not in contents and "RAW-MODEL-AUDIT" not in contents


def test_display_history_untouched(sm):
    """展示路径不筛（只提升不下降）：原始行仍完整可查。"""
    sid = _seed(sm)
    hist = sm.get_history(agent_id="a1", session_id=sid)
    assert any(m.get("role") == "tool" for m in hist)
