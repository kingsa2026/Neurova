# -*- coding: utf-8 -*-
"""P2-1 hooks 引擎：配置加载/匹配/wire 决策/开关。"""
import json
import subprocess
import sys

import pytest

from neurova.core.hooks_engine import HookEngine, reset_hook_engine


def _py(code: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", code])


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_HOOKS_CONFIG", str(tmp_path / "hooks.json"))
    monkeypatch.delenv("NEUROVA_HOOKS", raising=False)
    reset_hook_engine()
    yield
    reset_hook_engine()


def _write_config(tmp_path, hooks):
    cfg = tmp_path / "hooks.json"
    cfg.write_text(json.dumps({"hooks": hooks}), encoding="utf-8")
    return cfg


class TestHookEngine:
    def test_missing_config_no_outcomes(self, tmp_path):
        engine = HookEngine(str(tmp_path / "nope.json"))
        assert engine.run("PreToolUse", {"tool_name": "x"}) == []

    def test_pre_tool_use_block(self, tmp_path):
        cmd = _py(
            "import sys,json;d=json.load(sys.stdin);"
            "print(json.dumps({'decision':'block','reason':'denied:'+d['tool_name']}))"
        )
        _write_config(tmp_path, {"PreToolUse": [{"command": cmd}]})
        engine = HookEngine()
        out = engine.run("PreToolUse", {"tool_name": "computer_shell", "params": {}})
        assert out[0]["blocked"] is True
        assert "computer_shell" in out[0]["reason"]

    def test_matcher_filters_tools(self, tmp_path):
        cmd = _py("import sys,json;print(json.dumps({'decision':'block','reason':'x'}))")
        _write_config(tmp_path, {"PreToolUse": [{"command": cmd, "matcher": "^computer_"}]})
        engine = HookEngine()
        out = engine.run("PreToolUse", {"tool_name": "memory_search"})
        assert out == []
        out2 = engine.run("PreToolUse", {"tool_name": "computer_shell"})
        assert out2 and out2[0]["blocked"] is True

    def test_post_tool_use_additional_context(self, tmp_path):
        cmd = _py("import sys,json;print(json.dumps({'additionalContext':'提示：已执行'}))")
        _write_config(tmp_path, {"PostToolUse": [{"command": cmd}]})
        engine = HookEngine()
        out = engine.run("PostToolUse", {"tool_name": "t", "result": "ok"})
        assert out[0]["additional_context"] == "提示：已执行"
        assert out[0]["blocked"] is False

    def test_stop_event_fires(self, tmp_path):
        cmd = _py("import sys,json;json.load(sys.stdin);print(json.dumps({}))")
        _write_config(tmp_path, {"Stop": [{"command": cmd}]})
        engine = HookEngine()
        assert len(engine.run("Stop", {"session_id": "s"})) == 1

    def test_non_block_decision_on_pretooluse_not_blocking(self, tmp_path):
        cmd = _py("import sys,json;print(json.dumps({'decision':'approve'}))")
        _write_config(tmp_path, {"PreToolUse": [{"command": cmd}]})
        out = HookEngine().run("PreToolUse", {"tool_name": "t"})
        assert out[0]["blocked"] is False

    def test_hook_failure_fail_open(self, tmp_path):
        _write_config(tmp_path, {"PreToolUse": [{"command": "definitely-not-a-command-xyz"}]})
        out = HookEngine().run("PreToolUse", {"tool_name": "t"})
        # fail-open：hook 挂了不拦截（error 或非零退出码均可，绝不 blocked）
        assert out[0]["blocked"] is False
        assert out[0].get("error") or out[0].get("exit_code") not in (0, None)

    def test_env_kill_switch(self, tmp_path, monkeypatch):
        cmd = _py("import sys,json;print(json.dumps({'decision':'block','reason':'x'}))")
        _write_config(tmp_path, {"PreToolUse": [{"command": cmd}]})
        monkeypatch.setenv("NEUROVA_HOOKS", "0")
        engine = HookEngine()
        assert engine.run("PreToolUse", {"tool_name": "t"}) == []

    def test_corrupt_config_fail_open(self, tmp_path):
        cfg = tmp_path / "hooks.json"
        cfg.write_text("{broken", encoding="utf-8")
        engine = HookEngine(str(cfg))
        assert engine.run("PreToolUse", {"tool_name": "t"}) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestExtendedEvents:
    """P2-10：新增四类事件（各自独立灰度，默认关）。"""

    def test_known_events_extended(self):
        from neurova.core.hooks_engine import KNOWN_EVENTS

        for event in ("SessionStart", "UserPromptSubmit", "PermissionRequest", "PostToolUseFailure"):
            assert event in KNOWN_EVENTS

    @pytest.mark.parametrize("event,helperName", [
        ("SessionStart", "runSessionStartHooks"),
        ("UserPromptSubmit", "runUserPromptSubmitHooks"),
        ("PermissionRequest", "runPermissionRequestHooks"),
        ("PostToolUseFailure", "runPostToolUseFailureHooks"),
    ])
    def test_default_off(self, tmp_path, monkeypatch, event, helperName):
        _write_config(tmp_path, {event: [{"command": _py("print(json.dumps({'decision':'block','reason':'x'}))")}]})
        import neurova.core.hooks_engine as he
        helper = getattr(he, helperName)
        assert helper({"tool_name": "t"}) == []

    @pytest.mark.parametrize("event,helperName,envName", [
        ("SessionStart", "runSessionStartHooks", "NEUROVA_SESSION_START_HOOKS"),
        ("UserPromptSubmit", "runUserPromptSubmitHooks", "NEUROVA_USER_PROMPT_HOOKS"),
        ("PermissionRequest", "runPermissionRequestHooks", "NEUROVA_PERMISSION_REQUEST_HOOKS"),
        ("PostToolUseFailure", "runPostToolUseFailureHooks", "NEUROVA_TOOL_FAILURE_HOOKS"),
    ])
    def test_enabled_runs(self, tmp_path, monkeypatch, event, helperName, envName):
        cmd = _py("import sys,json;print(json.dumps({'additionalContext':'ctx-t','reason':'r'}))")
        _write_config(tmp_path, {event: [{"command": cmd}]})
        monkeypatch.setenv(envName, "1")
        import neurova.core.hooks_engine as he
        helper = getattr(he, helperName)
        out = helper({"tool_name": "t"})
        assert len(out) == 1
        assert out[0]["additional_context"] == "ctx-t"

    def test_block_semantics_for_new_events(self, tmp_path, monkeypatch):
        cmd = _py("import sys,json;print(json.dumps({'decision':'block','reason':'拒'}))")
        _write_config(tmp_path, {
            "UserPromptSubmit": [{"command": cmd}],
            "PermissionRequest": [{"command": cmd}],
            "PostToolUseFailure": [{"command": cmd}],
            "SessionStart": [{"command": cmd}],
        })
        monkeypatch.setenv("NEUROVA_USER_PROMPT_HOOKS", "1")
        monkeypatch.setenv("NEUROVA_PERMISSION_REQUEST_HOOKS", "1")
        monkeypatch.setenv("NEUROVA_TOOL_FAILURE_HOOKS", "1")
        monkeypatch.setenv("NEUROVA_SESSION_START_HOOKS", "1")
        engine = HookEngine()
        # 可 block：UserPromptSubmit / PermissionRequest
        assert engine.run("UserPromptSubmit", {"tool_name": "t"})[0]["blocked"] is True
        assert engine.run("PermissionRequest", {"tool_name": "t"})[0]["blocked"] is True
        # 只读面：SessionStart / PostToolUseFailure 永不 block
        assert engine.run("PostToolUseFailure", {"tool_name": "t"})[0]["blocked"] is False
        assert engine.run("SessionStart", {"tool_name": "t"})[0]["blocked"] is False
