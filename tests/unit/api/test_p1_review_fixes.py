# -*- coding: utf-8 -*-
"""P1 落地复审修复 — 防回归测试

锁定复审发现的六处修复：
1. memory_to_dict origin 枚举序列化（str(MemoryOrigin.X) 破坏契约）；
2. approve_request 过期分支必须同步 SQLite（否则重启后过期请求复活）；
3. /stats/provider-usage 端点要求登录（账单数据匿名可读=泄露）；
4. _step_save_session 围栏拒绝后回退原 session_id（"" 不下传）；
5. ChatPipeline claim 时序在 trace 之后（writer 关联 trace_id）。
6. provider_usage_adapters 无死代码（openrouter fetch 干净）。
"""
import asyncio
import datetime
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))


class TestMemoryToDictOrigin:
    """修③: origin 枚举序列化"""

    def test_memory_object_enum_serialized_to_value(self):
        from neurova.api.endpoints.memory.base import memory_to_dict
        from neurova.cognitive_layers.memory_layer.models import Memory

        d = memory_to_dict(Memory(id="m1", content="x"))
        assert d["origin"] == "agent"

    def test_dict_branch_valid_and_invalid(self):
        from neurova.api.endpoints.memory.base import memory_to_dict

        assert memory_to_dict({"id": "m", "content": "c", "origin": "owner"})["origin"] == "owner"
        assert memory_to_dict({"id": "m", "content": "c", "origin": "GOD"})["origin"] == "agent"
        assert memory_to_dict({"id": "m", "content": "c"})["origin"] == "agent"

    def test_untrusted_object_not_mangled(self):
        from neurova.api.endpoints.memory.base import memory_to_dict
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryOrigin

        d = memory_to_dict(Memory(id="m2", content="x", origin=MemoryOrigin.UNTRUSTED))
        assert d["origin"] == "untrusted"


class TestApprovalExpirySqlite:
    """修④: approve 过期分支落 SQLite"""

    def test_expired_status_survives_restart(self, tmp_path):
        from neurova.security.approval_manager import ApprovalManager, ApprovalStatus

        am = ApprovalManager(str(tmp_path))
        r = am.create_approval_request("a1", "u1", "cmd", metadata={})
        req = am.get_request(r.request_id)
        req.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        assert am.approve_request(r.request_id, "u") is False

        am2 = ApprovalManager(str(tmp_path))
        assert am2.get_request(r.request_id).status == ApprovalStatus.EXPIRED


class TestProviderUsageEndpointAuth:
    """修①: /stats/provider-usage 要求登录"""

    def test_anonymous_rejected(self):
        """账单端点匿名（无 Bearer）必须 401/403 —— 走真实 get_current_user 依赖链"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import stats as stats_mod

        app = FastAPI()
        app.include_router(stats_mod.router, prefix="/stats")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/stats/provider-usage")
        assert resp.status_code in (401, 403), f"匿名应被拒，实际 {resp.status_code}"


class TestSaveSessionFenceFallback:
    """修⑥: 围栏拒绝后 session_id 回退"""

    @pytest.mark.asyncio
    async def test_fenced_save_returns_original_session_id(self, tmp_path):
        from neurova.agent.history_fence import get_history_write_fence, reset_history_write_fence
        from neurova.post_chat_pipeline import PostChatPipeline, StepStatus

        reset_history_write_fence()
        try:
            from neurova.session_manager import SessionManager

            sm = SessionManager()
            sm._sessions_dir = Path(tmp_path) / "sessions"
            sm._sessions_dir.mkdir(parents=True, exist_ok=True)

            agt = SimpleNamespace(
                _collect_tool_messages=lambda: [],
                current_reasoning=None,
                _save_to_session=lambda *a, **kw: sm.add_message(
                    agent_id="agt", session_id=a[2], user_content=a[0], assistant_content=a[1],
                    metadata=a[3], assistant_metadata=a[4], writer_claim=kw.get("writer_claim"),
                ),
            )
            pipe = PostChatPipeline.__new__(PostChatPipeline)
            pipe._agent = agt  # _agt property 读 self._agent
            pipe._step_results = []
            pipe._PROGRAMMING_ERRORS = (TypeError, AttributeError, NameError, ImportError, SyntaxError)

            fence = get_history_write_fence()
            claim_a = fence.claim("agt", "s1", "run:A")
            fence.claim("agt", "s1", "run:B")  # 夺权

            sid = await pipe._step_save_session("u", "a", "s1", True, {}, writer_claim=claim_a)
            assert sid == "s1"  # 回退原始 session_id，不是 ""
            assert pipe._step_results[-1].status == StepStatus.SKIPPED
        finally:
            reset_history_write_fence()


class TestClaimOrderAfterTrace:
    """修⑤: claim 在 trace 之后（writer_id 含 trace_id）"""

    @pytest.mark.asyncio
    async def test_writer_claim_carries_trace_id(self):
        from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
        from neurova.agent.history_fence import get_history_write_fence, reset_history_write_fence

        reset_history_write_fence()
        try:
            agent = SimpleNamespace(
                increment_turn_count=lambda: None,
                _frozen_identity_snapshot=None,
                session_manager=SimpleNamespace(
                    get_session=lambda **kw: None,
                    get_recent_context=lambda **kw: [],
                ),
                idle_tracker=None,
                _trajectory_recorder=SimpleNamespace(
                    start_trace=lambda **kw: "trace-xyz",
                    record_event=lambda **kw: None,
                ),
            )

            class _Cfg:
                agent_id = "agt"

            agent.config = _Cfg()

            pipe = ChatPipeline.__new__(ChatPipeline)
            pipe._agent = agent

            ctx = ChatContext(user_input="hi", session_id="sess9", metadata={})

            from unittest.mock import patch as _patch

            with _patch("neurova.agent.session_snapshot.get_session_snapshot_cache") as snap_mock:
                snap_mock.return_value.get.return_value = None
                await pipe._step_activity_tracking(ctx)

            assert ctx.trace_id == "trace-xyz"
            assert ctx.writer_claim is not None
            assert ctx.writer_claim.writer_id == "run:trace-xyz"
        finally:
            reset_history_write_fence()


class TestAdaptersClean:
    """修②: provider_usage_adapters 无死代码"""

    def test_openrouter_fetch_shape(self):
        from unittest.mock import MagicMock, patch

        from neurova.llm.provider_usage_adapters import _fetch_openrouter

        pc = SimpleNamespace(api_key="sk-or")
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"data": {"limit_remaining": 5.0, "usage": 1.2}}
        with patch("httpx.get", return_value=fake_resp):
            snap = _fetch_openrouter(pc)
        assert snap["plan"] == "credits"
        assert snap["quota_remaining"] == 5.0
        assert "balance" not in snap or snap.get("balance") is None
