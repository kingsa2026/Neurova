"""子进程侧 runner（P3-14）：受限脚本在独立进程执行，ctx 经 NDJSON 桥接。

协议（stdin/stdout 每行一个 JSON，UTF-8）：
- 父 → 子首行：``{"type":"start","script":...,"replayCalls":[...],
  "safeBuiltins":[...]}``；
- 子 → 父：``{"type":"callTool","seq":n,"name":...,"params":{...}}``（等待父回
  ``{"type":"callResult","seq":n,"result":...}``）；``{"type":"log",...}``/
  ``{"type":"setVar",...}``（fire-and-forget，父侧 journal）；
- 子 → 父末行：``{"type":"done","success":...,"logs":[...],"vars":{...}}``。

设计约束：本模块**只依赖标准库**（不 import neurova——父包导入链很重，
子进程必须秒级拉起）。静态校验在父侧完成（单份实现）；本进程是纵深
防御的最后一层：即便白名单被绕过，子进程也触不到父进程状态，超时即杀。
"""

from __future__ import annotations

import asyncio
import json
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


def _bootstrapRepoRoot() -> None:
    root = str(Path(__file__).resolve().parents[3])
    if root not in sys.path:
        sys.path.insert(0, root)


def _emitLine(row: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


class _StdinBridge:
    """后台线程阻塞读 stdin，逐行推给 asyncio 侧（避开 Windows 管道异步怪癖）。"""

    def __init__(self):
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()

    def start(self) -> None:
        def _reader() -> None:
            for line in sys.stdin:
                self._queue.put(line)
            self._queue.put(None)

        threading.Thread(target=_reader, name="scripted-stdin", daemon=True).start()

    async def nextLine(self) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._queue.get)


class _ProxyCtx:
    """子进程内的 ctx：callTool 经桥接请求父侧（父侧走治理管线并 journal）。"""

    def __init__(self, send: Any, safeBuiltins: Dict[str, Any]):
        self._send = send
        self._safeBuiltins = safeBuiltins
        self._pending: Dict[int, asyncio.Future] = {}
        self._seq = 0
        self.vars: Dict[str, Any] = {}
        self.logs: List[str] = []

    def log(self, message: str) -> None:
        self.logs.append(str(message)[:500])
        self._send({"type": "log", "message": str(message)[:500]})

    def setVar(self, name: str, value: Any) -> None:
        self.vars[str(name)] = value
        self._send({"type": "setVar", "name": str(name), "value": value})

    def getVar(self, name: str, default: Any = None) -> Any:
        return self.vars.get(str(name), default)

    async def callTool(self, name: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._seq += 1
        seq = self._seq
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[seq] = fut
        self._send({"type": "callTool", "seq": seq, "name": str(name), "params": dict(params or {})})
        return await fut

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(min(max(0.0, float(seconds)), 30.0))

    def resolveCallResult(self, seq: int, result: Any) -> None:
        fut = self._pending.pop(int(seq), None)
        if fut is not None and not fut.done():
            fut.set_result(result)

    def failAll(self, error: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(error))
        self._pending.clear()


async def _runScriptTask(script: str, ctx: _ProxyCtx, safeBuiltins: Dict[str, Any]) -> Dict[str, Any]:
    namespace: Dict[str, Any] = {"ctx": ctx, "__builtins__": dict(safeBuiltins)}
    try:
        compiled = compile(script, "<scripted-workflow>", "exec")
        exec(compiled, namespace)  # noqa: S102 - 父侧已过 AST 白名单；本进程是隔离层
        main = namespace.get("main")
        if not callable(main):
            return {"type": "done", "success": False, "errors": ["脚本必须定义 async def main(ctx)"]}
        await main(ctx)
        return {"type": "done", "success": True, "logs": ctx.logs, "vars": ctx.vars}
    except Exception as e:  # noqa: BLE001 - 异常诚实回传父侧
        ctx.failAll(str(e))
        return {"type": "done", "success": False, "error": f"脚本执行异常: {e}", "logs": ctx.logs, "vars": ctx.vars}


async def _amain() -> None:
    bridge = _StdinBridge()
    bridge.start()

    script: Optional[str] = None
    replayCalls: List[Dict[str, Any]] = []
    safeNames: List[str] = []
    while script is None:
        raw = await bridge.nextLine()
        if raw is None:
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "start":
            script = str(msg.get("script") or "")
            replayCalls = list(msg.get("replayCalls") or [])
            safeNames = list(msg.get("safeBuiltins") or [])

    import builtins as _builtinModule

    safeBuiltins = {n: getattr(_builtinModule, n) for n in safeNames if hasattr(_builtinModule, n)}
    ctx = _ProxyCtx(_emitLine, safeBuiltins)
    # 续跑重放：账本里已留痕的调用按序复用结果（不重复执行副作用）
    for row in replayCalls:
        ctx._seq += 1
        ctx.resolveCallResult(ctx._seq, row.get("result"))

    scriptTask = asyncio.create_task(_runScriptTask(script, ctx, safeBuiltins))
    lineTask = asyncio.create_task(bridge.nextLine())
    while True:
        doneSet, _pending = await asyncio.wait({scriptTask, lineTask}, return_when=asyncio.FIRST_COMPLETED)
        if lineTask in doneSet:
            raw = lineTask.result()
            lineTask = asyncio.create_task(bridge.nextLine())
            if raw is None:
                scriptTask.cancel()
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "callResult":
                ctx.resolveCallResult(int(msg.get("seq", 0)), msg.get("result"))
        if scriptTask in doneSet:
            break
    lineTask.cancel()
    done = scriptTask.result() if not scriptTask.cancelled() else {
        "type": "done", "success": False, "error": "stdin 已关闭（父进程退出）",
    }
    _emitLine(done)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
