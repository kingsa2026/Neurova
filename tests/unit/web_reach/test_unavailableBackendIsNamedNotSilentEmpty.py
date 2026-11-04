"""agent-reach 后端不可得时必须点名原因，不许咽成空读数骗过引导（⑥ 乙案）。

现量根据（动手前实测，两处外部源一致）：
- 生产代码要的是 `agent_reach.core.AgentReach` 与 `agent_reach.config.Config`
  （`neurova/web_reach/reach.py:359-360`）。
- PyPI `agent-reach` 0.1.0（MIT，Author Jean Galea，依赖 feedparser）实际模块是
  `__init__/__main__/budget/cache/cli/doctor/envelope/installer/manifest/paths/registry/runner/skillgen`；
  上游仓 `jgalea/agent-reach`（main，最后推送 2026-09-23）是 src 布局，
  `src/agent_reach/` 下同一组模块——**两边都没有 core.py / config.py**。
- 本机未装、仓内也无同名包 ⇒ 那条 `except` 今天必然命中，而它交回的是 `{}`：
  调用方 `social_search()`（`:390`）只看 `channels.<平台>.active_backend`，空字典与
  "后端在但没配登录态"长得一模一样，于是给用户念的是"去配置登录态、跑 agent-reach doctor --json 验证"——
  一个既装不上、也没有那两个模块的命令。

故本批不删能力也不进清单（用户裁乙），只做一件事：把"不可得"与"未配置"分成两种读数，
让不可得时点名不可得。测试里注入假 `agent_reach.*` 只为覆盖成功路径——
它顶替的是取不到的第三方包，不是本仓业务对象（教义第 3 条禁的是后者）。
"""

import ast
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from neurova.web_reach import reach
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
REACH_FILE = REPO_ROOT / "neurova" / "web_reach" / "reach.py"


def _installFakeAgentReach(monkeypatch, doctorResult):
    """造一个"包与两个入口模块都在"的第三方环境，只用于走成功路径。"""
    class _Config:
        def __init__(self, read_only=False):
            self.read_only = read_only

    class _AgentReach:
        def __init__(self, config):
            self.config = config

        def doctor(self):
            return doctorResult

    pkg = ModuleType("agent_reach")
    core = ModuleType("agent_reach.core")
    config = ModuleType("agent_reach.config")
    core.AgentReach = _AgentReach
    config.Config = _Config
    pkg.core = core
    monkeypatch.setitem(__import__("sys").modules, "agent_reach", pkg)
    monkeypatch.setitem(__import__("sys").modules, "agent_reach.core", core)
    monkeypatch.setitem(__import__("sys").modules, "agent_reach.config", config)


def test_后端不可得时点名原因而不是交空字典():
    """真态（本机未装、上游无那两个模块）：空字典就是把失败读成"没配"。"""
    report = reach.run_doctor()

    assert report != {}, "后端不可得却交回空字典——调用方无从分辨「未装」与「没配」"
    assert report.get("success") is False, report
    assert "agent_reach" in str(report.get("error") or report.get("reason") or ""), report


def test_引导不得让用户去配一个根本不存在的后端():
    outcome = reach.social_search("twitter", "关键词")

    assert outcome.get("success") is False, outcome
    guide = str(outcome.get("guide") or outcome.get("error") or "")
    assert "agent-reach doctor --json" not in guide, (
        "后端本身不可得，却让用户去跑上游命令验证——把不可得说成未配置：%s" % guide[:160])
    assert ("不可得" in guide or "未安装" in guide or "不匹配" in guide), guide[:160]


def test_后端在但该渠道未配登录态仍按未配置引导(monkeypatch):
    """反向格（今天就该绿）：不得把"没配"也说成"不可得"——两种读数都要各自正确。"""
    _installFakeAgentReach(monkeypatch, {"channels": {"twitter": {"active_backend": None}}})
    outcome = reach.social_search("twitter", "关键词")

    assert outcome.get("needs_setup") is True, outcome
    assert "登录态" in str(outcome.get("guide") or ""), outcome


def test_后端可用时原样交回上游体检读数(monkeypatch):
    """反向格（今天就该绿）：成功路径不得被新增字段污染——上游给什么交回什么。"""
    upstream = {"channels": {"twitter": {"active_backend": "opencli"}}}
    _installFakeAgentReach(monkeypatch, upstream)

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
