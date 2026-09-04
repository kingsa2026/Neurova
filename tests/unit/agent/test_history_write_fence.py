"""P1-10 会话历史写入围栏（writer claim fencing，OpenClaw 启发）— TDD 测试

参照 OpenClaw `expectedWriterRunId` 事务内双重断言：
- 并行会话/旧 run 恢复后可能写脏历史（本项目历史上发生过 stash/并行覆盖事故三例）。
- 围栏语义：新 run 接管会话（claim 夺权）后，旧 run 的历史写入被拒绝——
  「被夺权的 run 永远写不进陈旧数据」。
- 等价性约束：不传 writer_claim 的调用方行为完全不变（显式参与式围栏）。
"""
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.agent.history_fence import FenceClaim, HistoryWriteFence, get_history_write_fence


class TestFenceBasics:
    """围栏基础语义"""

    def test_claim_returns_claim_with_generation(self, tmp_path):
        fence = HistoryWriteFence()
        c = fence.claim("agt", "sess1", "run:A")
        assert isinstance(c, FenceClaim)
        assert c.writer_id == "run:A"
        assert c.generation == 1

    def test_same_writer_reclaim_keeps_generation(self):
        fence = HistoryWriteFence()
        c1 = fence.claim("agt", "sess1", "run:A")
        c2 = fence.claim("agt", "sess1", "run:A")
        assert c2.generation == c1.generation
        assert fence.check("agt", "sess1", c1) is True

    def test_takeover_bumps_generation(self):
        fence = HistoryWriteFence()
        c_a = fence.claim("agt", "sess1", "run:A")
        c_b = fence.claim("agt", "sess1", "run:B")
        assert c_b.generation == c_a.generation + 1
        # 旧 writer 的 claim 失效
        assert fence.check("agt", "sess1", c_a) is False
        assert fence.check("agt", "sess1", c_b) is True

    def test_check_scoped_by_session(self):
        fence = HistoryWriteFence()
        c = fence.claim("agt", "sess1", "run:A")
        # 不同会话互不干扰
        assert fence.check("agt", "sess2", c) is False

    def test_check_rejects_none_claim(self):
        fence = HistoryWriteFence()
        assert fence.check("agt", "sess1", None) is False

    def test_singleton_returns_same_instance(self):
        assert get_history_write_fence() is get_history_write_fence()

    def test_fenced_writes_counter(self):
        fence = HistoryWriteFence()
        c_a = fence.claim("agt", "s", "run:A")
        fence.claim("agt", "s", "run:B")
        fence.record_fenced_write()
        assert fence.fenced_writes == 1


class TestSessionManagerFencing:
    """层2 落盘咽喉：SessionManager.add_message 围栏（经共享单例）"""

    @pytest.fixture(autouse=True)
    def _reset_fence(self):
        from neurova.agent.history_fence import reset_history_write_fence

        reset_history_write_fence()
        yield
        reset_history_write_fence()

    @pytest.fixture
    def sm(self, tmp_path):
        from neurova.session_manager import SessionManager

        sm = SessionManager()
        sm._sessions_dir = Path(tmp_path) / "sessions"
        sm._sessions_dir.mkdir(parents=True, exist_ok=True)
        return sm

    def test_valid_claim_writes_normally(self, sm, tmp_path):
        fence = get_history_write_fence()
        claim = fence.claim("agt", "s1", "run:A")
        sid = sm.add_message("agt", "s1", "你好", "你好！", writer_claim=claim)
        assert sid == "agt_s1"
        rec = sm.get_session("agt", "s1")
        assert len(rec.messages) == 2

    def test_stale_claim_rejected_no_file_write(self, sm, tmp_path):
        fence = get_history_write_fence()
        claim_a = fence.claim("agt", "s2", "run:A")
        fence.claim("agt", "s2", "run:B")  # 夺权
        before = fence.fenced_writes
        sid = sm.add_message("agt", "s2", "旧run的消息", "旧run的回复", writer_claim=claim_a)
        # 被围栏：返回空标识，文件不落盘
        assert sid == ""
        files = list((Path(tmp_path) / "sessions" / "agt").glob("session_s2_*.json"))
        assert files == []
        assert fence.fenced_writes == before + 1

    def test_no_claim_unchanged_behavior(self, sm):
        """等价性：不传 writer_claim 行为与历史完全一致"""
        sid = sm.add_message("agt", "s3", "u", "a")
        assert sid == "agt_s3"
        rec = sm.get_session("agt", "s3")
        assert len(rec.messages) == 2

    def test_stale_claim_exception_never_propagates(self, sm):
        """围栏拒绝只跳过写盘，绝不炸调用链"""
        fence = get_history_write_fence()
        claim_a = fence.claim("agt", "s4", "run:A")
        fence.claim("agt", "s4", "run:B")
        # 不应抛异常
        result = sm.add_message("agt", "s4", "u", "a", writer_claim=claim_a)
        assert result == ""


class TestMemCoreFencing:
    """层1 内存历史：MemCore.update_history 围栏（经共享单例）"""

    @pytest.fixture(autouse=True)
    def _reset_fence(self):
        from neurova.agent.history_fence import reset_history_write_fence

        reset_history_write_fence()
        yield
        reset_history_write_fence()

    @pytest.fixture
    def core(self):
        from neurova.conversation_context import ConversationContext
        from neurova.mem_core import MemCore

        c = MemCore.__new__(MemCore)
        c._agent = SimpleNamespace(
            config=SimpleNamespace(agent_id="agt"),
            _conversation_context=ConversationContext(),
            conversation_history=[],
        )
        c._history_lock = threading.RLock()
        return c

    def test_update_history_with_valid_claim(self, core):
        fence = get_history_write_fence()
        claim = fence.claim("agt", "s1", "run:A")
        core.update_history("u", "a", writer_claim=claim, session_id="s1")
        assert len(core._agent.conversation_history) == 2

    def test_update_history_stale_claim_skipped(self, core):
        fence = get_history_write_fence()
        claim_a = fence.claim("agt", "s1", "run:A")
        fence.claim("agt", "s1", "run:B")  # 夺权
        core.update_history("旧消息", "旧回复", writer_claim=claim_a, session_id="s1")
        # 被围栏：历史不追加
        assert core._agent.conversation_history == []

    def test_update_history_no_claim_unchanged(self, core):
        """等价性：不传 writer_claim 行为不变"""
        core.update_history("u", "a")
        assert len(core._agent.conversation_history) == 2


class TestChatPipelineWiring:
    """ChatPipeline 接线：turn 开始 claim、post_chat 透传 claim"""

    def test_chat_context_has_writer_claim_field(self):
        from neurova.agent.chat_pipeline import ChatContext

        ctx = ChatContext(user_input="hi")
        assert ctx.writer_claim is None

    def test_pipeline_request_has_writer_claim_field(self):
        from neurova.pipeline_executor import PipelineRequest

        req = PipelineRequest(user_input="hi", reply="ok")
        assert req.writer_claim is None

    def test_save_to_session_accepts_writer_claim(self, tmp_path):
        """Agent._save_to_session 透传 writer_claim 到 SessionManager（经共享单例）"""
        from neurova.session_manager import SessionManager

        fence = get_history_write_fence()
        sm = SessionManager()
        sm._sessions_dir = Path(tmp_path) / "sessions2"
        sm._sessions_dir.mkdir(parents=True, exist_ok=True)

        from neurova.mem_core import MemCore

        core = MemCore.__new__(MemCore)
        config = SimpleNamespace(agent_id="agt")
        core._agent = SimpleNamespace(
            config=config,
            session_manager=sm,
        )
        claim_a = fence.claim("agt", "s9", "run:A")
        core.save_to_session("u", "a", "s9", writer_claim=claim_a)
        rec = sm.get_session("agt", "s9")
        assert len(rec.messages) == 2

        # 夺权后再存 → 被拒
        fence.claim("agt", "s9", "run:B")
        core.save_to_session("旧", "旧", "s9", writer_claim=claim_a)
        rec = sm.get_session("agt", "s9")
        assert len(rec.messages) == 2  # 未增加
