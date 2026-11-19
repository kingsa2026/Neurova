# -*- coding: utf-8 -*-
"""AD-5（agent-desktop 对照工单后置项拍板立项）· CUA 独立 CLI。

`python -m neurova.computer_use <command>`：进程内直调 manager（人工代理形态，
不走 agent 治理面），统一 JSON 信封 {"ok", "command", "data"/"error"}。
README 里 `neurova computer ...` 的记载此前无实现（文档漂移），本模块补齐真入口。
"""

import json

import pytest

import neurova.computer_use.__main__ as cli


class _FakeUia:
    def __init__(self):
        self.calls = []

    def snapshot(self, *args, **kwargs):
        self.calls.append(("snapshot", args, kwargs))
        return {"success": True, "elements": [{"index": 0, "name": "确定", "depth": 1}]}

    def list_windows(self, limit=50):
        self.calls.append(("list_windows", limit))
        return {"windows": [{"title": "记事本", "class_name": "Notepad"}]}

    def click_element(self, *args, **kwargs):
        self.calls.append(("click_element", args, kwargs))
        return {"success": True, "action_result": {"effect": "confirmed"}}

    def set_value(self, *args, **kwargs):
        self.calls.append(("set_value", args, kwargs))
        return {"success": True}


class _FakeCu:
    def screenshot(self, region=None):
        return b"png-bytes"

    def click(self, x, y, button="left"):
        return True

    def type_text(self, text, interval=0.05):
        return True

    def press_key(self, keys):
        return True

    def scroll(self, x, y, vertical, horizontal=0):
        return True


@pytest.fixture()
def patched(monkeypatch):
    uia, cu = _FakeUia(), _FakeCu()
    monkeypatch.setattr(cli, "_uia_manager", lambda: uia)
    monkeypatch.setattr(cli, "_cu_manager", lambda: cu)
    return uia, cu


def _run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out.splitlines()[-1])


class TestCliEnvelope:
    def test_status_reports_capability(self, patched, capsys):
        code, env = _run(capsys, "status")
        assert code == 0 and env["ok"] is True and env["command"] == "status"
        assert "uia" in env["data"] and "platform" in env["data"]

    def test_dom_snapshot_passes_flags(self, patched, capsys):
        uia, _ = patched
        code, env = _run(capsys, "dom-snapshot", "--window-title", "记事本",
                         "--max-depth", "4", "--skeleton")
        assert code == 0 and env["ok"] is True
        assert env["data"]["elements"][0]["name"] == "确定"
        _, args, kwargs = uia.calls[0]
        assert args == ("记事本", None, 4, None, None, True)

    def test_click_element_by_runtime_id(self, patched, capsys):
        uia, _ = patched
        code, env = _run(capsys, "click-element", "--runtime-id", "42.1.7")
        assert code == 0 and env["ok"] is True
        _, args, kwargs = uia.calls[0]
        assert args == (None, "42.1.7", None, "left", None)

    def test_click_pixel_uses_cu_manager(self, patched, capsys):
        _, cu = patched
        code, env = _run(capsys, "click", "--x", "10", "--y", "20")
        assert code == 0 and env["ok"] is True and env["data"]["clicked"] is True

    def test_missing_target_refused(self, patched, capsys):
        code, env = _run(capsys, "click-element")
        assert code == 2 and env["ok"] is False and "index" in env["error"]

    def test_unknown_command_exit_code(self, patched, capsys):
        code, env = _run(capsys, "no-such-command")
        assert code == 2 and env["ok"] is False

    def test_type_and_key(self, patched, capsys):
        _, cu = patched
        code, env = _run(capsys, "type", "--text", "你好")
        assert code == 0 and env["ok"] is True
        code, env = _run(capsys, "key", "--keys", "esc")
        assert code == 0 and env["ok"] is True
