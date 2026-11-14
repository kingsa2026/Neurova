"""受限脚本工作流引擎（P3-14）。

执行模型写下的 ``async def main(ctx)`` 脚本：
- 静态校验（validator.validateScript）通过后才执行；
- 脚本可见的内建是**白名单子集**（无 I/O 原语），副作用只能经
  ``ctx.callTool(工具名, 参数)`` 走完整治理管线（审批/审计不旁路）；
- journal 逐行落盘；续跑（resume）时已留痕的调用直接复用结果，
  **不重复执行**（确定性重放到断点之后继续）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.workflow.scripted.journal import WorkflowJournal
from neurova.workflow.scripted.validator import validateScript

logger = get_logger(__name__)

#: 脚本可见的内建白名单（纯计算；无 I/O 原语；True/False/None 是关键字，天然可用）
SAFE_BUILTINS: Dict[str, Any] = {
    name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
    for name in (
        "len", "str", "int", "float", "bool", "abs", "min", "max", "sum",
        "round", "sorted", "list", "dict", "set", "tuple", "range",
        "enumerate", "zip", "any", "all", "repr", "ord", "chr", "divmod",
        "pow", "Exception", "RuntimeError", "ValueError", "TypeError",
        "KeyError", "IndexError",
    )
}

DEFAULT_TIMEOUT = 120.0
MAX_TIMEOUT = 600.0
MAX_CALL_RESULT_CHARS = 100_000


class ScriptHost:
    """脚本可见的受限宿主对象（脚本里的 ``ctx``）。"""

    def __init__(self, callTool: Callable, journal: Optional[WorkflowJournal],
                 replayRows: Optional[List[Dict[str, Any]]] = None):
        self._callTool = callTool
        self._journal = journal
        self._replayCalls = [r for r in (replayRows or []) if r.get("kind") == "callTool"]
        self._replayIdx = 0
        self._seq = 0
        self.vars: Dict[str, Any] = {}
        self.logs: List[str] = []
        self.calls: List[Dict[str, Any]] = []

    def log(self, message: str) -> None:
        """记录过程日志（进 journal 与返回值）。"""
        self.logs.append(str(message)[:500])
        if self._journal is not None:
            self._journal.append({"seq": self._seq, "kind": "log", "message": str(message)[:500]})
        self._seq += 1

    def setVar(self, name: str, value: Any) -> None:
        self.vars[str(name)] = value

    def getVar(self, name: str, default: Any = None) -> Any:
        return self.vars.get(str(name), default)

    async def callTool(self, name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """调用一个工具（走完整治理管线）。续跑时已留痕的调用复用结果。"""
        self._seq += 1
        if self._replayIdx < len(self._replayCalls):
            row = self._replayCalls[self._replayIdx]
            self._replayIdx += 1
            result = row.get("result")
            self.calls.append({"name": str(name), "params": params or {}, "result": result, "replayed": True})
            return result
        result = await self._callTool(str(name), dict(params or {}))
        self.calls.append({"name": str(name), "params": params or {}, "result": result})
        if self._journal is not None:
            self._journal.append({
                "seq": self._seq, "kind": "callTool",
                "name": str(name), "params": params or {}, "result": result,
            })
        return result

    async def sleep(self, seconds: float) -> None:
        """有限等待（0-30s 封顶）。"""
        await asyncio.sleep(min(max(0.0, float(seconds)), 30.0))


async def runScriptedWorkflow(
    script: str,
    callTool: Callable,
    journal: Optional[WorkflowJournal] = None,
    resumeRows: Optional[List[Dict[str, Any]]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """校验并执行受限脚本；返回 {success, logs, vars, calls, errors?}。"""
    violations = validateScript(script)
    if violations:
        return {"success": False, "errors": violations}

    host = ScriptHost(callTool, journal, resumeRows)
    try:
        compiled = compile(script, "<scripted-workflow>", "exec")
    except SyntaxError as e:
        return {"success": False, "errors": [f"脚本语法错误: {e}"]}

    namespace: Dict[str, Any] = {"ctx": host, "__builtins__": dict(SAFE_BUILTINS)}
    try:
        exec(compiled, namespace)  # noqa: S102 - AST 白名单校验后执行
    except Exception as e:  # noqa: BLE001
        return {"success": False, "errors": [f"脚本加载失败: {e}"], "logs": host.logs}

    main = namespace.get("main")
    if not callable(main):
        return {"success": False, "errors": ["脚本必须定义 async def main(ctx)"], "logs": host.logs}

    effectiveTimeout = min(max(float(timeout), 5.0), MAX_TIMEOUT)
    try:
        await asyncio.wait_for(main(host), timeout=effectiveTimeout)
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"脚本执行超时（{effectiveTimeout:.0f}s）",
            "logs": host.logs, "vars": host.vars,
            "calls": host.calls[-50:],
        }
    except Exception as e:  # noqa: BLE001 - 脚本异常诚实返回（journal 已留痕）
        return {
            "success": False, "error": f"脚本执行异常: {e}",
            "logs": host.logs, "vars": host.vars, "calls": host.calls[-50:],
        }
    return {
        "success": True,
        "logs": host.logs, "vars": host.vars,
        "calls": host.calls[-50:], "replayed_calls": host._replayIdx,
    }
