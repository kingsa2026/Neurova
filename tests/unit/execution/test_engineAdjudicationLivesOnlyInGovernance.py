# -*- coding: utf-8 -*-
r"""§6-295 乙案：引擎不假装裁决，回落支接回治理单源。

复核实状（运行时探针八腿，台账 §6-295 逐条读数）：真装配下两把 `ToolEngine`
（`shared_core/execution_engine.py:123` 与 `api/endpoints/tool_layers.py:44`）附的都是
`tool_engine.py:177-191` 那个恒 `safe=True` 的 `DefaultGuard`，`neurova/` 内无一处传
`tool_guard=`；同一输入喂真 `ToolGuardEngine` 是 `should_block=True`。于是
`api/endpoints/tool_layers.py` 那条"无 agent ⇒ 引擎直调"的回落支——**唯一一条不经治理的执行路**——
它的守卫是个装饰品：`{"file_path": "/etc/shadow"}` 经真 HTTP 把工具跑了起来。

本批按用户裁乙落两刀（两刀是同一根因的两半：**裁决只该有一个口，而那条路没接上它**）：
① 退役引擎自带的门面（`_create_default_guard`／`tool_guard` 形参／`execute` 里那段检查与
   "C3 修复: 执行前安全检查"那句不实注释）；
② 回落支改经治理单源 `get_governance().evaluate_tool_call(...)`——动态来源那一侧按既有
   P0-2／M4 规则用 `scan_all=True`，否则动态工具换个参数名就绕过去。

**刻意收窄的那一格写在码里而不是藏在测试里**：这一支没有会话可以问人，所以 ASK 与 SANDBOX
都按拒绝处理。它只朝保守方向偏（多拒不漏拒），且不改主路——主路有 agent／审批链，仍由咽喉解释。

**刻意不做的两件**：① 不把两把 `ToolEngine` 合一（§6-295 末格另记的独立缺陷，另一张票）；
② 不在端点里复刻 `_governance_precheck` 那条链（沙箱路由、审批、审计都留在咽喉）——这里只
取"裁决是什么"，取数一律经那个单源函数。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tests import ast_scan
from tests.ast_scan import parseSource


REPO = Path(__file__).resolve().parents[3]
TOOL_ENGINE = REPO / "neurova" / "execution_engine" / "tool_engine.py"
TOOL_LAYERS = REPO / "neurova" / "api" / "endpoints" / "tool_layers.py"

SHADOW = "/etc/shadow"
CHOKE_FILE = REPO / "tests" / "unit" / "tools" / "test_tool_layer_breakpoints_zoom_out.py"


def _nameUseForm(node: ast.AST, name: str) -> str:
    """这个节点是不是在**取用** `name`？是则返回取法名，否则空串。三种取法都认。

    `ClassDef`＝还在定义；`Name`＝裸名（`DefaultGuard()`）；`Attribute`＝
    `tool_engine.DefaultGuard` 这种经模块对象取的形。拆成纯函数是为了可证伪——
    合成样本直接喂进来就能逐形验证，不必往生产里种临时文件。
    """
    if isinstance(node, ast.ClassDef) and node.name == name:
        return "定义"
    if isinstance(node, ast.Name) and node.id == name:
        return "裸名引用"
    if isinstance(node, ast.Attribute) and node.attr == name:
        return "属性访问"
    return ""


def _callEndpoint(tool_name: str, arguments: dict):
    """走真端点函数，引擎与 agent 用替身——本批要判的是**端点这一层的次序**，不是引擎内部。"""
    from neurova.api.endpoints import tool_layers
    from neurova.api.endpoints.tool_layers import ToolExecuteRequest, execute_tool

    engine = MagicMock()
    engine.execute_with_safeguards = AsyncMock(return_value={"ok": "ran"})
    with patch.object(tool_layers, "get_tool_engine", return_value=engine), \
         patch("neurova.api.endpoints.get_agent_instance", return_value=None):
        response = asyncio.run(execute_tool(
            ToolExecuteRequest(tool_name=tool_name, arguments=arguments, timeout=5)
        ))
    return response, engine


class TestFallbackEngineCallIsGoverned:
    def testAdjudicablePathIsRefusedWithoutRunningTheTool(self):
        """主红：那条回落支今天把危险调用真跑了（探针读数⑤）。"""
        response, engine = _callEndpoint("file_read", {"file_path": SHADOW})
        assert engine.execute_with_safeguards.await_count == 0, (
            "无 agent 的引擎直调没经治理就跑了工具——§6-295 探针读数⑤的现场")
        assert response.get("code") == 1, f"这一支应诚实拒绝，实得 {response}"
        assert "治理" in str(response.get("error") or ""), (
            f"拒绝得点名理由（不许只回'执行失败'），实得 {response.get('error')}")

    def testKeyRenamedDynamicToolIsStillAdjudicated(self):
        """动态来源那一侧的既有规则不许在这条支路上丢掉：scan_all=True。

        取一个**不在任何键名清单里**的键（`target`）。只按键名取数的写法会放过去，
        而这条支路注册的正是 MCP／动态工具（P0-2／M4 那条规则的原始场合）。
        """
        response, engine = _callEndpoint("mcp.demo.peek", {"target": SHADOW})
        assert engine.execute_with_safeguards.await_count == 0, (
            "动态工具换个参数名就绕过了预检——scan_all 那一刀没接上")
        assert response.get("code") == 1

    def testNonAdjudicableCallStillRuns(self):
        """对照格：不许把"接治理"做成一律拒（形态 251：归零那一腿要有合成样本续钉）。

        `evaluate_tool_call` 对无可裁决内容回 None，这一支该照旧放行——既有那条
        "无 agent 的评测/脚本路径仍可用引擎（不是一刀切禁掉）"的反向锁依赖它。
        """
        response, engine = _callEndpoint("calculator", {})
        assert engine.execute_with_safeguards.await_count == 1, (
            f"无可裁决内容也被拒了＝把降级支拆了，实得 {response}")
        assert response.get("code") == 0

    def testEndpointTakesVerdictFromTheSingleSource(self):
        """形状格：端点只许经那个单源函数取裁决，不许另起一份实装。

        钉的是**代码形态**（调的是谁、有没有就地 new 一个引擎自己扫），不钉词。
        """
        tree = parseSource(TOOL_LAYERS.read_text(encoding="utf-8"), filename=str(TOOL_LAYERS))
        endpoint = next(n for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n.name == "execute_tool")
        calledAttrs = {n.func.attr for n in ast.walk(endpoint)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "evaluate_tool_call" in calledAttrs, (
            f"端点没经治理单源取裁决（实得调用面 {sorted(calledAttrs)}）")
        constructed = {n.func.id for n in ast.walk(endpoint)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "ToolGuardEngine" not in constructed, (
            "端点里就地 new 了一个守卫自己扫——那是第二个裁决口（教义第 6 条）")


class TestEngineNoLongerPretendsToAdjudicate:
    def testToolEngineHasNoGuardSeam(self):
        """门面退役：形参、属性、那段检查与那个恒 safe 的兜底类，一处不剩。"""
        tree = parseSource(TOOL_ENGINE.read_text(encoding="utf-8"), filename=str(TOOL_ENGINE))
        init = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "__init__"
                    and any(getattr(a, "arg", "") == "self" for a in n.args.args)
                    and any(getattr(a, "arg", "") == "config" for a in n.args.args))
        argNames = {a.arg for a in init.args.args}
        assert "tool_guard" not in argNames, (
            f"ToolEngine 还留着 tool_guard 这个形参（一个没人传的裁决口）：{sorted(argNames)}")

        funcNames = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert "_create_default_guard" not in funcNames, "那个恒 safe 的兜底工厂还在"

        execute = next(n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name == "execute")
        guarded = [n.lineno for n in ast.walk(execute)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "guard"]
        assert not guarded, f"execute() 里还在自己裁决（{guarded}）——裁决只该有一个口"

    def testDefaultGuardNameGoneFromProductionSurface(self):
        """全仓 `neurova/` 不再出现这个类名：留着就是"还有一道门"的假象。

        取数走 `tests/ast_scan` 的共享预算（`nodeScan` ＋文本预筛——判据认的是这个**名字**，
        连这串字样都没出现的文件不可能命中）；不私有 `glob + ast.parse`（D22）。

        取法认三种（定义／裸名／`tool_engine.DefaultGuard` 属性形）：旧口径只认前两种，
        属性访问那条形即使留着也报"零引用"——取法窄于意图。
        """
        offenders = [
            f"{ast_scan.relativeToRepo(path)}:{node.lineno} [{form}]"
            for path, node in ast_scan.nodeScan(ast_scan.PRODUCTION_ROOT, ".py",
                                                ast_scan.textHints("DefaultGuard"))
            if (form := _nameUseForm(node, "DefaultGuard"))
        ]
        assert not offenders, f"恒 safe 的门还在被定义或被引用：{sorted(set(offenders))}"

    def testDetectorFlagsAllThreeFormsAndIgnoresNeighbours(self):
        """探测函数自己可证伪：三种取法逐个给出，两个邻居形状不得误报。

        没有这格，"补上属性访问形"这句话只能靠往生产里种文件来验——那会污染别的常驻判据。
        仍**不覆盖** `getattr(x, "DefaultGuard")` 这种字符串形：把 `ast.Constant` 也算进去会
        连docstring/日志文案一起咬，边界写在台账里而不是偷偷放宽。
        """
        forms = {
            "定义": "class DefaultGuard:\n    pass\n",
            "裸名引用": "g = DefaultGuard()\n",
            "属性访问": "g = tool_engine.DefaultGuard\n",
        }
        for expected, source in forms.items():
            tree = parseSource(source)
            found = {f for n in ast.walk(tree) if (f := _nameUseForm(n, "DefaultGuard"))}
            assert found == {expected}, f"{expected} 那形的取法判不出来：{found}"

        neighbours = {
            "同前缀不同名": "class DefaultGuardX:\n    pass\ng = tool_engine.DefaultGuardX\n",
            "被取的其它属性": "g = tool_engine.guard\n",
        }
        for label, source in neighbours.items():
            found = [f for n in ast.walk(parseSource(source)) if (f := _nameUseForm(n, "DefaultGuard"))]
            assert not found, f"{label} 被误判成取用 DefaultGuard：{found}"

    def testOldEngineGuardCellsRetiredNotLeftZombie(self):
        """旧契约的格子必须跟着退役：留着就断言"引擎该自己裁决"这条被推翻的规矩。"""
        source = CHOKE_FILE.read_text(encoding="utf-8")
        tree = parseSource(source, filename=str(CHOKE_FILE))
        zombie = [n.name for n in ast.walk(tree)
                  if isinstance(n, ast.ClassDef) and n.name == "TestToolGuardWired"]
        assert not zombie, (
            "`TestToolGuardWired` 还在钉引擎自带守卫这个旧契约——本批改判成"
            "『裁决只在治理单源』，旧格要么删要么改指新形状")
