"""P1-2（ZCode 电脑操控对照评测）：动作错误三元组 action_sent / retry。

对齐 ZCode CUA 的错误契约：错误除精确拒绝码外，还要回答两个模型最需要的
问题——"这个动作是否可能已经下发"（action_sent，防非幂等动作盲重放）与
"下一步该怎么走"（retry: reobserve|retry|never）。本文件钉契约与推导规则。
"""

import pytest

from neurova.computer_use import action_result as ar
from neurova.tool_executor import ToolExecutor


class TestRetryVocabulary:
    def test_retry_modes_closed(self):
        assert ar.RETRY_MODES == frozenset({"reobserve", "retry", "never"})

    def test_every_refusal_code_has_retry_advice(self):
        """每个拒绝码都必须有重试建议——新增码漏登建议即红（防词表扩张不带语义）。"""
        missing = [c for c in ar.REFUSAL_CODES if c not in ar.REFUSAL_RETRY_ADVICE]
        assert not missing, f"拒绝码缺重试建议：{missing}"

    def test_retry_advice_values_in_vocabulary(self):
        for code, advice in ar.REFUSAL_RETRY_ADVICE.items():
            assert advice in ar.RETRY_MODES, f"{code} 的建议 {advice!r} 越界"


class TestBuildDerivesFields:
    def test_confirmed_implies_action_sent(self):
        out = ar.build("uia", "confirmed", delivery="background", evidence=["value_readback"])
        assert out["action_sent"] is True

    def test_refused_implies_not_sent(self):
        out = ar.refused("global_input", "permission_required")
        assert out["action_sent"] is False

    def test_refused_auto_retry_advice(self):
        assert ar.refused("uia", "stale_generation")["retry"] == "reobserve"
        assert ar.refused("global_input", "permission_required")["retry"] == "never"
        assert ar.refused("shell", "backend_error")["retry"] == "retry"

    def test_explicit_retry_overrides(self):
        out = ar.build("uia", "refused", refusal_code="backend_error", retry="never")
        assert out["retry"] == "never"

    def test_invalid_retry_rejected(self):
        with pytest.raises(ar.ActionResultError):
            ar.build("uia", "refused", refusal_code="backend_error", retry="maybe")

    def test_refused_with_action_sent_true_rejected(self):
        """refused ⇒ delivery=not_applicable（未投递）；声明已下发即契约矛盾。"""
        with pytest.raises(ar.ActionResultError):
            ar.build("uia", "refused", refusal_code="backend_error", action_sent=True)

    def test_unverifiable_carries_action_sent(self):
        out = ar.build("global_input", "unverifiable", delivery="foreground", retry="reobserve")
        assert out["action_sent"] is True
        assert out["retry"] == "reobserve"


class TestExecutorWiring:
    def test_pixel_action_result_advises_reobserve(self):
        """pyautogui 无投递回执 → unverifiable；建议=重新观察（补拍截图已承担）。"""
        out = ToolExecutor._pixel_action_result()
        assert out["effect"] == "unverifiable"
        assert out["action_sent"] is True
        assert out["retry"] == "reobserve"

    @pytest.mark.asyncio
    async def test_sandbox_refusal_carries_contract(self, monkeypatch):
        """沙箱档无会话拒绝：拒绝码 + 永不盲重试的建议随结果回灌模型。"""
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "sandbox")
        monkeypatch.setattr("neurova.computer_use.get_active_remote_desktop", lambda: None)
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = pytest_import_magicmock()
        out = await inst._execute_builtin_tool("computer_click", {"x": 1, "y": 2})
        assert out["success"] is False
        contract = out.get("action_result") or {}
        assert contract.get("refusal_code") == "sandbox_session_required"
        assert contract.get("retry") == "never"
        assert contract.get("action_sent") is False

    @pytest.mark.asyncio
    async def test_review_refusal_carries_never_retry(self, monkeypatch):
        """审核档铸审批：模型应等待批准而非重试——retry=never。"""
        from neurova.computer_use import runtime_policy as rp

        monkeypatch.setattr(rp, "get_runtime_mode", lambda: "review")

        class _Req:
            request_id = "appr-1"

        class _Mgr:
            def create_approval_request(self, **kwargs):
                return _Req()

        import sys

        from unittest.mock import MagicMock

        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager", lambda: _Mgr()
        )
        inst = ToolExecutor.__new__(ToolExecutor)
        inst._agent = MagicMock()
        inst._agent.current_session_id = None
        inst._agent._current_user_id = "u1"
        out = inst._desktop_runtime_gate("computer_click", {"x": 1, "y": 2})
        contract = out.get("action_result") or {}
        assert contract.get("refusal_code") == "permission_required"
        assert contract.get("retry") == "never"


def pytest_import_magicmock():
    from unittest.mock import MagicMock

    m = MagicMock()
    m.current_session_id = None
    m._current_user_id = "u1"
    return m
