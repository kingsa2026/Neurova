# -*- coding: utf-8 -*-
r"""§6-299 丙案：工具归属由注册方带来的声明派生，列表面不再替它猜。

复核实状（现读，不是沿用票面描述）：造 `ToolInfo` 的地方在这个文件里有**四处**——
`:383`（`/mcp-servers/{id}/tools`，`source="mcp"`＋`server_id=server_id`，本来就是对的）、
`:419`（`list_all_tools` 源 1）、`:440`（源 2 真内置）、`:568`（`/tools/public`）。
缺陷集中在源 1 与 public 那两处：`tool_source = "builtin"` 是**写死的字面量**
（只有 `is_public`／`owner` 才改写），`server_id=None` 是**硬塞**——而注册方把答案带来了：
`mcp_client._sync_tools_to_engine` 注册时打的是 `tags=["mcp", server_id]`
（`neurova/tool_layers/mcp_client.py:609`）。于是 MCP 工具在对外契约里被标成内置、所属 server 被抹掉。

**取值口径**（丙的必然结果，不是本批新裁）：带 `mcp` tag → `("mcp", server_id)`；
否则 `is_public` → `("public", None)`；否则有 `owner` → `("user", None)`；
都不带 → `("dynamic", None)`——**中性值，不再顶替成"builtin"**。
"builtin" 这一值此后只属于源 2（`agent._builtin_tools` 的真内置注册器）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
TOOL_LAYERS = REPO / "neurova" / "api" / "endpoints" / "tool_layers.py"

MCP_TAG = "mcp"
SERVER_ID = "srv-b72"
DERIVE = "_ownershipFromRegistration"


def _engineWith(tools: list):
    """真 `ToolEngine` ＋真 `register_tool`（不走替身：本批要判的就是注册面带来了什么）。"""
    from neurova.execution_engine.tool_engine import ToolEngine, ToolStatus

    engine = ToolEngine()
    for spec in tools:
        engine.register_tool(
            tool_name=spec["name"],
            tool_func=lambda **kw: {"ran": True},
            description=spec.get("description", "取证用"),
            tags=spec.get("tags"),
            status=ToolStatus.AVAILABLE,
            owner=spec.get("owner", ""),
            is_public=spec.get("is_public", False),
        )
    return engine


def _callListAllTools(engine, source: str = None):
    from neurova.api.endpoints import tool_layers
    from neurova.api.endpoints.tool_layers import list_all_tools

    with _patchedEngine(engine), _patchedAgent():
        return asyncio.run(list_all_tools(source=source))


def _callPublicTools(engine):
    from neurova.api.endpoints import tool_layers
    from neurova.api.endpoints.tool_layers import discover_public_tools

    with _patchedEngine(engine):
        return asyncio.run(discover_public_tools())


class _patchedEngine:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        from neurova.api.endpoints import tool_layers
        self._orig = tool_layers.get_tool_engine
        tool_layers.get_tool_engine = lambda: self.engine
        return self

    def __exit__(self, *exc):
        from neurova.api.endpoints import tool_layers
        tool_layers.get_tool_engine = self._orig
        return False


class _patchedAgent:
    """源 2 用**真**内置注册器（`BuiltinToolRegistry`），不用 Mock 冒充业务对象。"""

    def __enter__(self):
        import neurova.api.endpoints as EP
        from neurova.builtin_tools import BuiltinToolRegistry

        self._orig = EP.get_agent_instance
        EP.get_agent_instance = lambda agent_id="": SimpleNamespace(_builtin_tools=BuiltinToolRegistry())
        return self

    def __exit__(self, *exc):
        import neurova.api.endpoints as EP
        EP.get_agent_instance = self._orig
        return False


def _entry(entries, tool_id: str):
    return next((t for t in entries if t.tool_id == tool_id), None)


class TestOwnershipComesFromRegistration:
    def testMcpToolIsNotLabelledBuiltinAnymore(self):
        """主红：MCP 工具在列表面里被写死的字面量标成了内置。"""
        entries = _callListAllTools(_engineWith([
            {"name": f"mcp.{SERVER_ID}.peek", "tags": [MCP_TAG, SERVER_ID]},
        ]))
        entry = _entry(entries, f"mcp.{SERVER_ID}.peek")
        assert entry is not None, f"列表面没有这条：{[t.tool_id for t in entries][:6]}"
        assert entry.source == MCP_TAG, (
            f"来源被标成 {entry.source!r}——注册方带的是 tags=['mcp', {SERVER_ID!r}]，"
            "列表面不该替它猜成 builtin")
        assert entry.server_id == SERVER_ID, (
            f"所属 server 被抹成 {entry.server_id!r}（就在同一份 tags 里）")

    def testUnownedDynamicRegistrationIsNotBuiltin(self):
        """没有 mcp tag、没有 owner、也不是 public 的动态注册：中性值，不许顶替成 builtin。"""
        entries = _callListAllTools(_engineWith([{"name": "bare_dynamic"}]))
        entry = _entry(entries, "bare_dynamic")
        assert entry is not None and entry.source == "dynamic", (
            f"今天它读回 {entry.source if entry else None!r}——写死的字面量把动态注册说成内置")

    def testPublicEndpointAlsoCarriesTheServerId(self):
        """同根因的第二处命中点：`/tools/public` 硬塞 `server_id=None`。"""
        entries = _callPublicTools(_engineWith([
            {"name": f"mcp.{SERVER_ID}.shared", "tags": [MCP_TAG, SERVER_ID], "is_public": True},
        ]))
        entry = _entry(entries, f"mcp.{SERVER_ID}.shared")
        assert entry is not None and entry.server_id == SERVER_ID, (
            f"公开工具库这一面丢了 server 归属：{entry}")

    def testOwnerAndBuiltinSourcesStillHold(self):
        """对照格：owner 那一支仍是 "user"，真内置（源 2）仍是 "builtin"。

        设计成改前改后都绿，钉的是"不许把派生做成一律改写"（形态集 251：归零那一腿要有对照续钉）。
        """
        entries = _callListAllTools(_engineWith([
            {"name": "user_owned", "owner": "alice"},
        ]))
        owned = _entry(entries, "user_owned")
        assert owned is not None and owned.source == "user", f"owner 那一支被改坏了：{owned}"

        builtin = _entry(entries, "file_read")
        assert builtin is not None and builtin.source == "builtin", (
            f"真内置（源 2 的 BuiltinToolRegistry）不该被这一刀动到：{builtin}")

    def testSourceFilterSplitsMcpFromBuiltin(self):
        """`?source=` 的行为后果：改前 MCP 工具混在 builtin 里，过滤按注册声明分得开。"""
        engine = _engineWith([
            {"name": f"mcp.{SERVER_ID}.peek", "tags": [MCP_TAG, SERVER_ID]},
            {"name": "bare_dynamic"},
        ])
        mcpOnly = [t.tool_id for t in _callListAllTools(engine, source=MCP_TAG)]
        builtinOnly = [t.tool_id for t in _callListAllTools(engine, source="builtin")]
        assert f"mcp.{SERVER_ID}.peek" in mcpOnly, f"按 mcp 过滤漏了它：{mcpOnly}"
        assert f"mcp.{SERVER_ID}.peek" not in builtinOnly, (
            f"按 builtin 过滤仍混进 MCP 工具：{builtinOnly}")


class TestDerivationIsTheOnlyInterpreter:
    def _tree(self):
        return ast.parse(TOOL_LAYERS.read_text(encoding="utf-8"), filename=str(TOOL_LAYERS))

    def _functions(self):
        return {n.name: n for n in ast.walk(self._tree())
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def testListSiteNoLongerAssignsTheBuiltinLiteral(self):
        """形状格：源 1 里"把来源赋成 builtin 字面量"那一形必须消失（按 AST 判，不扫词）。"""
        listing = self._functions()["list_all_tools"]
        offenders = []
        for node in ast.walk(listing):
            if not isinstance(node, ast.Assign):
                continue
            names = [ast.unparse(t) for t in node.targets]
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for value in values:
                if isinstance(value, ast.Constant) and value.value == "builtin" \
                        and any("source" in n for n in names):
                    offenders.append(f"{node.lineno}:{names}")
        assert offenders == [], (
            f"列表面还在把来源写成字面量 builtin：{offenders}——归属只能从注册面派生")

    def testDerivationDefinedOnceAndUsedByBothFaces(self):
        """一处定义、两处消费（`list_all_tools` 与 `/tools/public`）——同一根因的命中面都在内。"""
        funcs = self._functions()
        assert DERIVE in funcs, f"派生口不存在（现读函数名 {sorted(funcs)[:8]}…）"
        for caller in ("list_all_tools", "discover_public_tools"):
            called = {n.func.id for n in ast.walk(funcs[caller]) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name)}
            assert DERIVE in called, f"{caller} 没经那个派生口——第二份解释又长出来了"

    def testNoSecondInterpreterOfTheMcpTagAnywhere(self):
        """全仓 `neurova/` 只许这一处**解释** mcp tag（写侧 `tags=["mcp", sid]` 不算解释）。

        三件都要成立：① 派生口自己那一处被认下来（**正控**——没有它，"零命中"可能只是探测器坏了，
        形态集 266）；② 除它以外 0 处；③ 探测器对合成的一段"在别处解释 tags"的代码必须点名，
        且对派生函数自己的形态不误报（按 AST 认函数身份，不按行号也不按文件名——形态集 223／268）。
        """
        exempt = (TOOL_LAYERS.relative_to(REPO).as_posix(), DERIVE)
        hits = []
        for path in (REPO / "neurova").rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            hits.extend(_tagInterpretations(
                path.read_text(encoding="utf-8", errors="ignore"), rel))

        mine = [h for h in hits if (h[0], h[1]) == exempt]
        assert mine, f"派生口自己都没被探测器认下来（现读命中 {hits}）——探测器坏了，别拿'零命中'当结论"
        others = [f"{rel}:{fn}:{line}" for rel, fn, line in hits if (rel, fn) != exempt]
        assert others == [], f"tags→归属 的解释出现了第二份：{others}"

    def testToolInfoSourceHasNoGuessedDefault(self):
        """模型层的同一形也必须消失：`source` 不许再有默认值。

        漏传该炸，不该静默自称内置——那是"列表面替工具猜归属"的另一种写法。
        """
        cls = next(n for n in ast.walk(self._tree())
                   if isinstance(n, ast.ClassDef) and n.name == "ToolInfo")
        withDefault = [ast.unparse(node.target) for node in cls.body
                       if isinstance(node, ast.AnnAssign) and node.value is not None
                       and getattr(node.target, "id", "") == "source"]
        assert withDefault == [], f"ToolInfo.source 还带默认值（漏传即静默 builtin）：{withDefault}"

    def testDetectorBitesAnInlinedCopyOfTheQuestion(self):
        """探测器反空转自证：别处内联解释要点名，派生函数自己那形不许报。"""
        withInline = (
            "def _ownershipFromRegistration(tool_def):\n"
            '    tags = list(tool_def.tags or [])\n'
            '    if "mcp" in tags:\n'
            "        return 'mcp'\n"
            "    return 'dynamic'\n"
            "def otherFace(tool_def):\n"
            "    return 'x' if 'mcp' in (tool_def.tags or []) else 'y'\n")
        onlyDerivation = (
            "def _ownershipFromRegistration(tool_def):\n"
            '    tags = list(tool_def.tags or [])\n'
            '    if "mcp" in tags:\n'
            "        return 'mcp'\n"
            "    return 'dynamic'\n")
        exempt = ("synthetic.py", DERIVE)

        hits = [(rel, fn, line) for rel, fn, line in _tagInterpretations(withInline, "synthetic.py")
                if (rel, fn) != exempt]
        assert len(hits) == 1 and hits[0][1] != DERIVE, (
            f"调用点上内联重述归属解释的那一处没被点名：{hits}")
        assert [h for h in _tagInterpretations(onlyDerivation, "synthetic.py")
                if (h[0], h[1]) != exempt] == [], "干净形态被误报，说明豁免没按 AST 认函数身份"


def _tagInterpretations(source: str, rel: str):
    """找出"读 `.tags` 并与 `mcp` 这个**值**比较"的落点（解释形态），带所属函数名。

    值要按 AST 解析，不按子串：`mcp` 字面量，或模块级绑成 `"mcp"` 的常量名（生产里就是
    `MCP_SOURCE`）都算；写侧 `tags=["mcp", sid]` 是 Assign 不是 Compare，不会命中；
    通用标签过滤（`tag in t.tags`）里没有那个值，也不会命中。
    """
    tree = ast.parse(source, filename=rel)
    mcpNames = set()
    for node in tree.body:
        value = getattr(node, "value", None)
        if not (isinstance(value, ast.Constant) and value.value == MCP_TAG):
            continue
        # Assign 的 target 是 targets 列表，AnnAssign 才是单个——两种写法都要认（形态集 258 同族）
        names = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                 if isinstance(node, ast.Assign) else
                 ([node.target.id] if isinstance(getattr(node, "target", None), ast.Name) else []))
        mcpNames.update(names)
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left] + list(node.comparators)
            readsTags = any("tags" in ast.unparse(o) for o in operands)
            usesMcp = any(
                (isinstance(o, ast.Constant) and o.value == MCP_TAG)
                or (isinstance(o, ast.Name) and o.id in mcpNames)
                for o in operands)
            if readsTags and usesMcp:
                out.append((rel, fn.name, node.lineno))
    return out
