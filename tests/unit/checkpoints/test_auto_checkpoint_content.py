# -*- coding: utf-8 -*-
"""K1 快照内容补全红测：`_auto_checkpoint` 的 session_data 必须含完整会话历史。

缺陷（P1-5 断链①）：`chat_pipeline._auto_checkpoint` 只写
{user_input, reply, trace_id, turn} 四字段——"快照"里没有会话历史，
恢复面无从谈起。本测钉住：快照内容必须能还原会话消息序列
（与 `session_manager.get_history` 同源），且原四字段保留不缩水。
"""
import asyncio
import json

import pytest

from neurova.agent.chat_pipeline import ChatContext


class _Cfg:
    def __init__(self, agent_id: str):
        self.agent_id = agent_id


class _Agent:
    """最小 agent 替身：`_auto_checkpoint` 只经 agent_ref 碰
    config / session_manager / turn_count / checkpoints_enabled。"""

    def __init__(self, agent_id: str, session_manager):
        self.config = _Cfg(agent_id)
        self.session_manager = session_manager
        self.memory_agent = None
        self.context_orchestrator = None
        self.turn_count = 2
        self.checkpoints_enabled = True


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from neurova.session_manager import SessionManager

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    # tmp_path 下的裸仓库不继承本仓 git config；CI/宿主未配全局身份时
    # commit-tree 会因 "Author identity unknown" 失败——用 env 隔离，
    # 让断言落在快照内容本身，而不是环境缺身份。
    monkeypatch.setenv("GIT_AUTHOR_NAME", "neurova-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "neurova-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "neurova-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "neurova-test@example.com")
    SessionManager._instance = None
    sm = SessionManager()
    yield {"sm": sm, "tmp": tmp_path}
    SessionManager._instance = None


def _run_auto_checkpoint(agent, session_id: str, user_input: str, reply: str) -> None:
    from neurova.agent.chat_pipeline import ChatPipeline

    pipeline = ChatPipeline(agent)
    ctx = ChatContext(
        user_input=user_input, session_id=session_id, reply=reply, trace_id="tr-k1"
    )
    asyncio.run(pipeline._auto_checkpoint(ctx))


def test_auto_checkpoint_snapshot_contains_full_history(env):
    sm = env["sm"]
    agent = _Agent("cp-agent-1", sm)

    # 两轮对话落盘（与生产同源：回合末经 add_message 成对写入）
    sm.add_message("cp-agent-1", "sess-k1", "第一问", "第一答")
    sm.add_message("cp-agent-1", "sess-k1", "第二问", "第二答")

    _run_auto_checkpoint(agent, "sess-k1", "第二问", "第二答")

    svc = agent._checkpoint_service
    snaps = svc.list_snapshots(session_key="sess-k1", kind="auto")
    assert len(snaps) >= 1, "自动快照必须存在"

    payload = svc.restore_snapshot(snaps[0]["ref"])
    data = json.loads(payload["session_json"])
    msgs = data.get("messages")
    assert isinstance(msgs, list) and len(msgs) == 4, (
        f"快照必须含完整会话历史（4 条消息），实际字段={sorted(data.keys())}、"
        f"messages={msgs!r}"
    )
    assert [m["content"] for m in msgs] == ["第一问", "第一答", "第二问", "第二答"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # 原四字段保留（向后兼容，不因补历史而缩水掉既有键）
    assert data["user_input"] == "第二问"
    assert data["reply"] == "第二答"
    assert data["trace_id"] == "tr-k1"
    assert data["turn"] == 2


def test_auto_checkpoint_skips_when_disabled(env):
    """checkpoints_enabled=False 时不产生快照（既有开关语义不变）。"""
    sm = env["sm"]
    agent = _Agent("cp-agent-2", sm)
    agent.checkpoints_enabled = False
    sm.add_message("cp-agent-2", "sess-off", "问", "答")

    _run_auto_checkpoint(agent, "sess-off", "问", "答")

    assert not hasattr(agent, "_checkpoint_service") or not agent._checkpoint_service.list_snapshots()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
