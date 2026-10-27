# -*- coding: utf-8 -*-
r"""§6-297 乙案：咽喉里那一档"优先使用 ToolEngine"恒不命中，本批把它拆掉。

取证读数（台账 §6-297 六腿）：`ToolExecutor` 内层那把 `ToolEngine` 取自
`ExecutionEngine._tool_engine`，而**全仓唯一能往它注册面写入的入口**是
`shared_core/execution_engine.py:410` 的 `ExecutionEngine.register_tool()`——后者零消费者
（运行时计数 0；`tests/execution_engine/test_tool_engine.py` 那批打的是 `ToolEngine()` 本身，
按接收者分开数过）。⇒ 那把引擎注册面**恒空** ⇒ `tool_executor.py:1472-1488` 对任何调用恒抛
"未注册"再落回后序分支，连带 `:1484` 的 `tool_source = "mcp"` **恒不产生**（全仓仅此一处赋该值）。

真在跑 MCP 的是第 4 档 `tool_layers/tool_router.py`（`_mcp_clients`）。所以本批不改任何可达性，
只把"声称优先、实则恒空"这一档与它的整条装配链退役（教义第 7 条：接通与退役同批，含它的测试）。

**刻意不在本批做的两件**：① 端点单例与咽喉内层合一（甲）——要并必须先裁"MCP 两条可执行路径留哪条"，
router 上挂着 `mcp_grants` 授权闸、请求级身份穿透防火墙、`is_mcp` 的 scan_all 口径；
② "只注册在单例里、又不是 router 成员"那一类工具在面板上**看得见跑不动**——那是读面如实标注
（§6-272 同族），要动 `list_all_tools` 两个源的归属，另批。
"""

from __future__ import annotations

import ast
from pathlib import Path
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
TOOL_EXECUTOR = REPO / "neurova" / "tool_executor.py"
A18_FILE = REPO / "tests" / "unit" / "tools" / "test_a18_tool_engine_eager_init_regression.py"

#: 内层引擎在 ToolExecutor 上的挂载点名字——那一档拆掉后，这些一个都不许留。
RETIRED_MEMBERS = {"_create_tool_engine", "tool_engine", "_tool_engine"}


def _tree() -> ast.AST:
    return parseSource(TOOL_EXECUTOR.read_text(encoding="utf-8"), filename=str(TOOL_EXECUTOR))


def _functionTree(name: str):
    return next((n for n in ast.walk(_tree())
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)


class TestThroatHasNoEmptyEngineBranch:
    def testCoreChainDoesNotCallTheEmptyEngine(self):
        """主红：`_execute_tool_core` 不再把调用送进那把恒空的引擎。"""
        core = _functionTree("_execute_tool_core")
        assert core is not None, "_execute_tool_core 还在（本批拆的是它内部那一档）"
        called = {n.func.attr for n in ast.walk(core)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "execute_with_safeguards" not in called, (
            "那一档还在：注册面恒空的引擎仍被当成第一顺位执行路径")

    def testAccessorChainRetiredWithTheBranch(self):
        """装配链与那一档同批退役——留着 `_create_tool_engine` 就是留着"它会被用到"的谎。"""
        funcs = {n.name for n in ast.walk(_tree())
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert "_create_tool_engine" not in funcs, "取那把空引擎的工厂还在"
        assert "_get_tool_engine_class" not in funcs, "只为那条链服务的延迟导入器还在"

        cls = next(n for n in ast.walk(_tree())
                   if isinstance(n, ast.ClassDef) and n.name == "ToolExecutor")
        members = set()
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                members.add(node.name)
            for target in [t for t in ast.walk(node) if isinstance(t, ast.Assign)]:
                for name in target.targets:
                    if isinstance(name, ast.Attribute):
                        members.add(name.attr)
        assert not (members & RETIRED_MEMBERS), (
            f"ToolExecutor 还持有内层引擎的挂载点 {sorted(members & RETIRED_MEMBERS)}")

    def testMcpToolSourceLabelHasNoProducer(self):
        """`tool_source = "mcp"` 这个值今天恒不产生；本批让它的**赋值语句**消失。

        按 AST 判赋值常量，不扫词——注释里出现 "mcp" 不算（形态集 241／268 那一族）。
        """
        offenders = []
        for node in ast.walk(_tree()):
            if not isinstance(node, ast.Assign):
                continue
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for value in values:
                if isinstance(value, ast.Constant) and value.value == "mcp":
                    targets = [ast.unparse(t) for t in node.targets]
                    if any("tool_source" in t for t in targets):
                        offenders.append(f"{node.lineno}:{targets}")
        assert not offenders, f"仍有一处把 tool_source 赋成 mcp（它没有可达的产出路径）：{offenders}"

    def testCoreChainDocstringMatchesRealBranchOrder(self):
        """归属写清：docstring 里那串**顺序陈述**不许再列一个代码里已不存在的档位。

        只判链条那一句（第一个句号前），解释段允许点名被拆掉的东西——否则这格会被
        自己写的说明咬到（形态集 241／268：按词扫文档迟早自咬，判据要定在"陈述本身"）。
        """
        core = _functionTree("_execute_tool_core")
        doc = ast.get_docstring(core) or ""
        chain = doc.split("。")[0]
        assert "ToolEngine" not in chain, (
            f"顺序陈述还在把 ToolEngine 列成一档（代码里已退役）：{chain.strip()[:160]}")

    def testOldA18CriteriaRetiredNotLeftZombie(self):
        """A-18 那三格钉的是"内层引擎急切构建/构建期失败不吞"——被钉对象已退役，整档不许留成僵尸。"""
        assert not A18_FILE.exists(), (
            f"{A18_FILE.relative_to(REPO).as_posix()} 还在断言一个已被退役的挂载点——"
            "留着一个只会 monkeypatch 不存在名字的档，等于给下一批留一条假证据")
