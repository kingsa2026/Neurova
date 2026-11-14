"""受限脚本工作流引擎（P3-14）：父侧编排 + 子进程隔离执行。

- 静态校验（validator.validateScript，解析走全仓唯一出口）通过后才执行；
- 执行在**独立子进程**（runner.py）：纵深防御——即便校验/白名单被绕过，
  子进程也无法触碰父进程状态；超时直接终止子进程；
- 副作用只能经 NDJSON 桥 ``ctx.callTool`` 请求父侧，由父侧走**完整治理
  管线**（审批/审计不旁路）并逐调用 journal 落盘；
- 续跑（resume）：账本里已留痕的调用按序复用结果，**不重复执行副作用**；
- 脚本可见内建 = 白名单子集（SAFE_BUILTINS，无 I/O 原语；True/False/None
  是关键字天然可用）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.workflow.scripted.journal import WorkflowJournal
from neurova.workflow.scripted.validator import validateScript

logger = get_logger(__name__)

#: 脚本可见的内建白名单（纯计算；无 I/O 原语；runner 子进程同用此表）
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


async def runScriptedWorkflowSubprocess(
    script: str,
    callTool: Callable,
    journal: Optional[WorkflowJournal] = None,
    resumeRows: Optional[List[Dict[str, Any]]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """校验并在独立子进程中执行受限脚本。

    Args:
        script: 模型写下的 ``async def main(ctx)`` 脚本。
        callTool: 父侧治理执行器（子进程的每次 ctx.callTool 都经此走完整管线）。
        journal: 逐调用落盘的账本（resume 的重放事实源）。
        resumeRows: 续跑时账本里已留痕的调用行（按序复用结果，不重复执行）。
        timeout: 执行超时秒（5-600）；超时终止子进程并诚实报错。
    """
    violations = validateScript(script)
    if violations:
        return {"success": False, "errors": violations}

    replayCalls = [r for r in (resumeRows or []) if r.get("kind") == "callTool"]
    effectiveTimeout = min(max(float(timeout), 5.0), MAX_TIMEOUT)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "neurova.workflow.scripted.runner",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    state: Dict[str, Any] = {"logs": [], "vars": {}, "calls": [], "replayed": 0}
    stderrTask = asyncio.create_task(proc.stderr.read()) if proc.stderr else None
    done: Dict[str, Any] = {}

    def _journalCall(seq: int, name: str, params: Dict, result: Any, replayed: bool) -> None:
        state["calls"].append({"name": name, "params": params, "result": result, "replayed": replayed})
        if journal is not None and not replayed:
            journal.append({"seq": seq, "kind": "callTool", "name": name, "params": params, "result": result})

    async def _pump() -> None:
        nonlocal done
        replayIdx = 0
        proc.stdin.write(
            (json.dumps({"type": "start", "script": script,
                         "replayCalls": replayCalls,
                         "safeBuiltins": list(SAFE_BUILTINS.keys())},
                        ensure_ascii=False) + "\n").encode("utf-8")
        )
        await proc.stdin.drain()
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise RuntimeError("脚本子进程异常退出（未收到 done）")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "callTool":
                name = str(msg.get("name") or "")
                params = dict(msg.get("params") or {})
                seq = int(msg.get("seq", 0))
                if replayIdx < len(replayCalls):
                    result = replayCalls[replayIdx].get("result")
                    replayIdx += 1
                    _journalCall(seq, name, params, result, replayed=True)
                else:
                    result = await callTool(name, params)
                    _journalCall(seq, name, params, result, replayed=False)
                proc.stdin.write(
                    (json.dumps({"type": "callResult", "seq": seq, "result": result},
                                ensure_ascii=False, default=str) + "\n").encode("utf-8")
                )
                await proc.stdin.drain()
            elif mtype == "log":
                message = str(msg.get("message") or "")
                state["logs"].append(message)
                if journal is not None:
                    journal.append({"seq": msg.get("seq"), "kind": "log", "message": message})
            elif mtype == "setVar":
                name = str(msg.get("name") or "")
                state["vars"][name] = msg.get("value")
                if journal is not None:
                    journal.append({"seq": msg.get("seq"), "kind": "setVar",
                                    "name": name, "value": msg.get("value")})
            elif mtype == "done":
                done = dict(msg)
                return

    try:
        await asyncio.wait_for(_pump(), timeout=effectiveTimeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "success": False,
            "error": f"脚本执行超时（{effectiveTimeout:.0f}s，子进程已终止）",
            "logs": state["logs"], "vars": state["vars"], "calls": state["calls"][-50:],
        }
    except Exception as e:  # noqa: BLE001 - 子进程崩溃/管道断裂：诚实报错带诊断
        proc.kill()
        await proc.wait()
        stderrTail = ""
        if stderrTask is not None:
            try:
                stderrTail = (stderrTask.result() or "")[-2000:]
            except Exception:  # noqa: BLE001
                pass
        return {
            "success": False,
            "error": f"脚本子进程异常退出: {e}",
            "stderr": stderrTail,
            "logs": state["logs"], "vars": state["vars"], "calls": state["calls"][-50:],
        }
    finally:
        if stderrTask is not None and not stderrTask.done():
            stderrTask.cancel()
        if proc.returncode is None:
            proc.kill()

    if stderrTask is not None:
        try:
            stderrTail = (stderrTask.result() or "")[-2000:]
        except Exception:  # noqa: BLE001
            stderrTail = ""
    else:
        stderrTail = ""

    if not done.get("success", False):
        result = {"success": False, "logs": state["logs"], "vars": state["vars"],
                  "calls": state["calls"][-50:]}
        if "error" in done:
            result["error"] = done["error"]
        if "errors" in done:
            result["errors"] = done["errors"]
        if stderrTail:
            result["stderr"] = stderrTail
        return result

    return {
        "success": True,
        "logs": state["logs"], "vars": state["vars"], "calls": state["calls"][-50:],
        "replayed_calls": len(replayCalls) if resumeRows else 0,
        "stderr": stderrTail,
    }
