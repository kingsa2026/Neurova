# -*- coding: utf-8 -*-
"""`shared_core.ExecutionEngine` 孤儿方法面退役判据（§6-303 档案落地，批 76 笔 1）。

这把引擎今天**只剩一条活路**：`api/endpoints/monitor.py` 三个端点经
`get_execution_engine().get_execution_monitor()` 取监控器。除此之外——
- **plan 子树**（`execute_plan`／`_execute_plan_nodes`／`_execute_simple_plan`／`_execute_node`／
  `_get_next_node`／`_evaluate_condition`）全仓零消费者，且它执行的那个 plan schema
  （`{"nodes": [...], "execution_order": [...]}`）**没有任何生产者**——双向断点。
  替代品 `collaboration/neurflow/` 是**超集**：真做拓扑分层、层内并发、`safe_eval_condition` 真分支；
  而这里的 `_evaluate_condition` 把 `variable`/`value` 读出来丢弃、恒返 True，连"条件"这一维都没实现。
- **`execute_tool`／`register_tool`** 的替代是真咽喉 `tool_executor._execute_tool_core`（治理、票据、
  hooks、`on_tool_executed` 都在它身上）。运行时探针实测：`POST /api/v1/tool-layers/tools/execute` 回 200
  而 `execute_tool` 计数为 0——工具真跑了，不经这把引擎。
- **`execute_workflow`＋`_load_neurflow_workflow`** 是 `53875590`(2026-09-04) 同一笔把转发 shim 和它自己的
  契约测试一起入库的自产自销面；neurflow 端点回 404 时它的计数仍是 0，说明那条"收敛契约"没有一条来路。
- **`ExecutionResult`＋`_executions`＋三个读口**（`get_execution_result`／`list_executions`／`cancel_execution`）
  是纯进程内台账：写侧全在上面那几条死路里，读侧零消费者。执行记录在本仓的真落点是
  `core/agent_run_ledger` 与 neurflow 的 `event_recorder`/`checkpoint`。
- **`set_event_bus`／`_call_llm`**：后者是占位符（打一条 warning 返回"LLM 调用未实现"）；前者是
  `ExecutionMonitor._event_bus` 的唯一注入口，而那条总线**只写不读**——那处缺陷另有等裁票（D1），
  本批**刻意不动监控器那侧**，由 `test_monitorBusSurfaceIsKeptForPendingRuling` 反向钉住。

判据两轨：主格钉"孤儿面不再是这把引擎的声明面"，且钉**存活集合恰好是那四个**（防我把活的那条一起删）；
交付锁走**真单例真监控器**（不 Mock 生产对象），并钉"本批不制造新的只写不读字段"——
这正是 §2 断点条款的形状化表达：删完之后，`__init__` 里每一个 `self.X = …` 都必须有人读。
"""
from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE = REPO_ROOT / "neurova" / "shared_core" / "execution_engine.py"

#: 退役对象——`ExecutionEngine` 类体上的孤儿方法（探针读数全 0，见档案 §2）
ORPHAN_METHODS = (
    "execute_plan", "_execute_plan_nodes", "_execute_simple_plan", "_execute_node",
    "_get_next_node", "_evaluate_condition", "execute_tool", "_call_llm",
    "execute_workflow", "get_execution_result", "list_executions", "cancel_execution",
    "register_tool", "set_event_bus",
)
#: 退役对象——模块顶层的孤儿声明（同名陷阱：`execution_layers` 里另有一个 `ExecutionResult`，
#: 那条与本批无关，所以判据只按**本模块的顶层定义**取数，不按类名扫全仓）
ORPHAN_TOP_LEVEL = ("ExecutionResult", "_load_neurflow_workflow")
#: 必须活下来的那一小圈（少一条就是删过头）
LIVE_METHODS = ("__new__", "__init__", "_init_components", "get_execution_monitor")
#: 只服务于上面那些死路的实例字段——留着就是"写出无人读的字段"（AGENTS §2）
ORPHAN_FIELDS = ("_executions", "_tool_engine", "_workflow_engine", "_event_bus", "_running")


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8", errors="replace"))


def _classBody() -> ast.ClassDef:
    for node in _tree().body:
        if isinstance(node, ast.ClassDef) and node.name == "ExecutionEngine":
            return node
    raise AssertionError("类 `ExecutionEngine` 不在这张树里——装配点被整体搬走了？")


def _methodNames() -> set:
    return {
        m.name for m in _classBody().body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _initAssignedFields() -> set:
    """`__init__` 体里被赋值的 `self.X` 名集合（按 AST 取，不按文本搜）。"""
    init = next((m for m in _classBody().body
                 if isinstance(m, ast.FunctionDef) and m.name == "__init__"), None)
    assert init is not None, "类里没有 `__init__`"
    targets = set()
    for node in ast.walk(init):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            holders = node.targets if isinstance(node, ast.Assign) else [node.target]
            for h in holders:
                if isinstance(h, ast.Attribute) and isinstance(h.value, ast.Name) \
                        and h.value.id == "self":
                    targets.add(h.attr)
    return targets


def test_orphanMethodsAreNoLongerOnThisClass():
    """主格①：14 条孤儿方法不再是类成员，而**存活集合恰好**是那四条（双向钉，防删过头）。"""
    names = _methodNames()
    left = sorted(names & set(ORPHAN_METHODS))
    assert not left, f"这些孤儿方法还挂在类上：{left}"
    missing = sorted(set(LIVE_METHODS) - names)
    assert not missing, f"活路被删过头了（这些必须还在）：{missing}"
    assert names == set(LIVE_METHODS), f"类体出现了清单外的新成员：{sorted(names - set(LIVE_METHODS))}"


def test_moduleNoLongerDeclaresTheOrphanDataclassAndLoader():
    """主格②：模块顶层不再有 `ExecutionResult` 与 `_load_neurflow_workflow`，工厂两条必须还在。"""
    top = {n.name for n in _tree().body
           if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
    left = sorted(top & set(ORPHAN_TOP_LEVEL))
    assert not left, f"这两个孤儿声明还在模块顶层：{left}"
    assert {"get_execution_engine", "reset_execution_engine"} <= top, f"工厂面被带走了：{top}"


def test_initNoLongerWritesFieldsNobodyReads():
    """主格③：`__init__` 里不再出现只服务于死路的字段——本批不许自己造出新断点。

    存活字段名按现读取：`_execution_monitor`（被 `get_execution_monitor` 读）、
    `_initialized`（被 `__new__`/`__init__` 双向读）。
    """
    fields = _initAssignedFields()
    left = sorted(fields & set(ORPHAN_FIELDS))
    assert not left, f"这些字段没人读了还留着（写出无人读的字段＝断点）：{left}"
    assert "_execution_monitor" in fields, f"监控器字段被顺手删了，活路就断了：{sorted(fields)}"


def test_realSingletonStillHandsOutAMonitor():
    """交付锁①：走**真单例**取监控器——这是这把引擎今天唯一的来路，必须照常能用。"""
    from neurova.execution_engine.execution_monitor import ExecutionMonitor
    from neurova.shared_core.execution_engine import get_execution_engine

    engine = get_execution_engine()
    assert get_execution_engine() is engine, "单例语义被动过"
    monitor = engine.get_execution_monitor()
    assert isinstance(monitor, ExecutionMonitor), \
        f"监控器取不到了（本批只该删死路）：{monitor!r}"


def test_resetStillYieldsAFreshFullyBuiltEngine():
    """交付锁②：隔离契约照旧成立，只是**见证物换掉了**。

    原来那格钉的是"reset 后 `_executions == {}`"；执行记录这一面整个退役后，那条断言会变成
    恒真（拿不到字段也等于"清了"）。所以按同样目的改钉存活面：再取是新对象、`_initialized` 为真、
    监控器重新装配出来——这三条坏在 reset 实现上时都会红。
    """
    from neurova.execution_engine.execution_monitor import ExecutionMonitor
    from neurova.shared_core import execution_engine as ee

    first = ee.get_execution_engine()
    ee.reset_execution_engine()
    second = ee.get_execution_engine()
    assert second is not first, "reset 后取回同一对象＝隔离无效"
    assert second._initialized is True
    assert isinstance(second.get_execution_monitor(), ExecutionMonitor), \
        "重建后监控器没装配出来（`_init_components` 被改坏了）"
    assert not hasattr(second, "_executions"), "执行记录面还在，本批没删净"


def test_monitorBusSurfaceIsKeptForPendingRuling():
    """反向钉：本批**不许**顺手处置 D1（监控器的事件总线只写不读）。

    被删的是 `ExecutionEngine.set_event_bus` 那条死路转发；`ExecutionMonitor` 自己的
    `set_event_bus`/`_event_bus` 属另一张票（接总线还是放弃该能力，等裁）。这张格的作用是让
    "顺手一起删"当场变红——同一根因要扫荡，**不同**根因不许捆绑（教义第 5 条与档案第 5 节同一口径）。
    """
    from neurova.execution_engine.execution_monitor import ExecutionMonitor

    assert hasattr(ExecutionMonitor, "set_event_bus"), "监控器的总线注入口被本批带走了（D1 尚未裁）"
    probe = ExecutionMonitor()
    assert hasattr(probe, "_event_bus"), "`_event_bus` 字段被带走了（D1 尚未裁）"


def test_docstringNoLongerClaimsTheRetiredDuties():
    """主格④：模块说明块的职责**清单行**不再列退役掉的那三件，而"执行监控"必须在。

    判的是 bullet 清单（`- xxx` 那几行）＝对外承诺的能力面，不是全文搜词——
    退役理由的说明句写在正文里，不会被这条判红（按词扫整段会被自家文档自咬，是本案同族的老坑）。

    取数按**模块开头那段裸字符串**（本仓这型文件把 `from __future__` 写在最前，那份说明串因此
    不是 `__doc__`；按 `ast.get_docstring` 取会拿到 None，这条格就变成恒红的空判——按体位取才咬得住）。
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8", errors="replace"))
    block = next((n.value.value for n in tree.body
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                  and isinstance(n.value.value, str)), None)
    assert block, "模块开头那段说明串不见了（判据没有对象）"
    bullets = [ln.strip()[1:].strip() for ln in block.splitlines() if ln.strip().startswith("- ")]
    claimed = " ".join(bullets)
    for retired in ("工具执行", "工作流执行", "MCP"):
        assert retired not in claimed, f"清单行还承诺着已退役的职责：{bullets}"
    assert "监控" in claimed, f"清单行把唯一活路也抹掉了：{bullets}"
