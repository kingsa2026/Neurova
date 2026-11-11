"""agent-reach 集成面「不可得」与「未接入」两种读数互不同形（⑥ 乙案延续）。

裁定沿革：用户裁乙——不删能力，把"不可得"与"未配置"分成两种读数，
不可得时点名不可得，不引导用户去配一个装不上的东西。
2026-11-12 起，该裁定的实现面从「幽灵库 import（agent_reach.core／
agent_reach.config，PyPI 与源码仓都不存在，死门）」收口为「CLI 面」
（``agent_reach_cli`` 桥接，argv 直传 + JSON envelope 归一）：
- 不可得 = CLI 未安装/执行失败 → 点名 + 安装指引
- 未接入 = doctor 渠道 status not_added/needs_setup → 引导 agent-reach add …
- 未登录态 = 渠道就绪但执行回 NEED_LOGIN → 引导 agent-reach login …
本文件钉这三种读数各自正确、成功路径原样透传。
"""

import ast
from pathlib import Path

import pytest

from neurova.web_reach import agent_reach_cli as cli
from neurova.web_reach import reach
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
REACH_FILE = REPO_ROOT / "neurova" / "web_reach" / "reach.py"


def _forceCliMissing(monkeypatch):
    """钉死"CLI 不可得"态（真机上装了 CLI 会翻转读数，测试须显式定态）。"""
    monkeypatch.setattr(cli, "resolveExecutable", lambda: None)


def test_后端不可得时点名原因而不是交空字典(monkeypatch):
    """CLI 未装态：不可得必须点名并带安装指引，不许咽成空读数。"""
    _forceCliMissing(monkeypatch)
    report = reach.run_doctor()

    assert report != {}, "后端不可得却交回空字典——调用方无从分辨「未装」与「没配」"
    assert report.get("success") is False, report
    assert "agent-reach" in str(report.get("error") or ""), report


def test_引导不得让用户去配一个根本不存在的后端(monkeypatch):
    _forceCliMissing(monkeypatch)
    outcome = reach.social_search("twitter", "关键词")

    assert outcome.get("success") is False, outcome
    guide = str(outcome.get("guide") or outcome.get("error") or "")
    assert "doctor --json" not in guide, (
        "后端本身不可得，却让用户去跑上游命令验证——把不可得说成未配置：%s" % guide[:160])
    assert ("不可得" in guide or "未安装" in guide or "不匹配" in guide), guide[:160]


def test_渠道就绪但未登录态按登录引导(monkeypatch):
    """反向格：不得把"没登录"也说成"不可得"——NEED_LOGIN 是独立读数。"""
    monkeypatch.setattr(
        cli,
        "runDoctor",
        lambda: {
            "success": True,
            "version": "1.6.0",
            "data": {"channels": [{"channel": "twitter", "status": "unverified"}]},
        },
    )
    monkeypatch.setattr(
        cli,
        "runChannelAction",
        lambda *a, **kw: {
            "success": False,
            "code": "NEED_LOGIN",
            "error": "login required",
            "hint": "Run `agent-reach login twitter`",
        },
    )
    outcome = reach.social_search("twitter", "关键词")

    assert outcome.get("needs_login") is True, outcome
    assert "登录态" in str(outcome.get("guide") or ""), outcome


def test_渠道未接入按接入引导而不是报不可得(monkeypatch):
    """反向格：不得把"没接入"也说成"不可得"——两种读数都要各自正确。"""
    monkeypatch.setattr(
        cli,
        "runDoctor",
        lambda: {
            "success": True,
            "version": "1.6.0",
            "data": {"channels": [{"channel": "twitter", "status": "not_added"}]},
        },
    )
    outcome = reach.social_search("twitter", "关键词")

    assert outcome.get("needs_setup") is True, outcome
    assert outcome.get("backend_unavailable") is not True, outcome


def test_后端可用时原样交回上游体检读数(monkeypatch):
    """成功路径不得被新增字段污染——上游给什么交回什么。"""
    upstream = {"version": "1.6.0", "channels": [{"channel": "twitter", "status": "unverified"}]}
    monkeypatch.setattr(cli, "runDoctor", lambda: {"success": True, "data": upstream, "version": "1.6.0"})

    assert reach.run_doctor() == upstream


def test_except分支不得把异常咽成空字典字面量():
    """结构格：钉代码形态——`run_doctor` 的 except 里 return {} 就是本批修掉的那件事。"""
    tree = parseSource(REACH_FILE.read_text(encoding="utf-8"), "reach.py")
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_doctor")
    emptied = []
    for handler in [h for blk in ast.walk(fn) if isinstance(blk, ast.Try) for h in blk.handlers]:
        for node in ast.walk(handler):
            if (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                    and not node.value.keys):
                emptied.append(node.lineno)
    assert emptied == [], (
        "run_doctor 的 except 又把失败咽成空字典（行 %s）：不可得与未配置将再次同形" % emptied)
