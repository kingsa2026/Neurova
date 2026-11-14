# -*- coding: utf-8 -*-
"""P2-10：UserPromptSubmit 钩子在聊天管线的接线。

- block → metadata.user_prompt_blocked（交 _step_llm_call 早退拒答）；
- additionalContext → metadata["hook_additional_context"]，并经
  _mergeHookGuidance 并入受控指引通道（挂最前）；
- 默认关；钩子故障放行。
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.core import hooks_engine as he
from neurova.core.hooks_engine import reset_hook_engine


def _setupHooks(monkeypatch, tmp_path, request, enabled=True, mode="block"):
    cfg = tmp_path / "hooks.json"
    import subprocess
    import sys as _sys

    hookCmd = subprocess.list2cmdline([
        _sys.executable,
        "-c",
        "import sys,json;print(json.dumps({'decision':'block','reason':'策略拒绝'}))" if mode == "block" else "import sys,json;print(json.dumps({'additionalContext':'合规提醒：本轮只读'}))",
    ])
    cfg.write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [{"command": hookCmd}]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_HOOKS_CONFIG", str(cfg))
    monkeypatch.setenv("NEUROVA_USER_PROMPT_HOOKS", "1" if enabled else "0")
    reset_hook_engine()
    request.addfinalizer(reset_hook_engine)


def _pipeline():
    from neurova.agent.chat_pipeline import ChatPipeline
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator.__new__(ContextOrchestrator)
    orch._context_health = orch._emptyContextHealth()
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(
        conversation_history=[],
        context_orchestrator=orch,
        config=SimpleNamespace(agent_id="a-hooks"),
    )
    return pipeline


def _ctx(userInput):
    return SimpleNamespace(session_id="s-hooks", user_input=userInput, metadata=None)


class TestUserPromptHooks:
    def test_block_sets_metadata(self, monkeypatch, tmp_path, request):
        _setupHooks(monkeypatch, tmp_path, request, enabled=True)
        pipeline = _pipeline()
        ctx = _ctx("任意输入")
        asyncio.run(pipeline._check_user_prompt_hooks(ctx))
        assert ctx.metadata["user_prompt_blocked"] is True
        assert "策略拒绝" in ctx.metadata["user_prompt_blocked_reason"]

    def test_additional_context_captured(self, monkeypatch, tmp_path, request):
        _setupHooks(monkeypatch, tmp_path, request, enabled=True, mode="context")
        pipeline = _pipeline()
        ctx = _ctx("任意输入")
        asyncio.run(pipeline._check_user_prompt_hooks(ctx))
        assert ctx.metadata.get("user_prompt_blocked") is None
        assert "合规提醒" in ctx.metadata["hook_additional_context"]

    def test_default_off_noop(self, monkeypatch, tmp_path, request):
        _setupHooks(monkeypatch, tmp_path, request, enabled=False)
        pipeline = _pipeline()
        ctx = _ctx("任意输入")
        asyncio.run(pipeline._check_user_prompt_hooks(ctx))
        assert ctx.metadata is None


class TestMergeHookGuidance:
    def test_hook_context_prepended(self):
        pipeline = _pipeline()
        ctx = _ctx("x")
        ctx.metadata = {"hook_additional_context": "合规提醒"}
        assert pipeline._mergeHookGuidance(ctx, "歧义指引") == "合规提醒\n歧义指引"

    def test_no_hook_context_passthrough(self):
        pipeline = _pipeline()
        ctx = _ctx("x")
        ctx.metadata = {}
        assert pipeline._mergeHookGuidance(ctx, "歧义指引") == "歧义指引"
        assert pipeline._mergeHookGuidance(ctx, "") == ""

    def test_hook_context_only(self):
        pipeline = _pipeline()
        ctx = _ctx("x")
        ctx.metadata = {"hook_additional_context": "合规提醒"}
        assert pipeline._mergeHookGuidance(ctx, "") == "合规提醒"
