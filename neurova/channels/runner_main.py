# -*- coding: utf-8 -*-
"""渠道 Runner 子进程入口（对照批 A1）。

职责边界（"渠道 worker 只做平台 I/O" 的切法）：
- 依赖审计 → hello 握手 → 等宿主 ready；
- 加载入口适配器（`module:qualname`）并驱动其 connect/send_message；
- 入站事件回传宿主（event 帧），宿主侧仍走既有 manager/router/台账全链路；
- `builtin:echo` 内置回显模式仅供协议/隔离测试，不加载任何真实渠道。

进程模型：主线程跑 asyncio loop 驱动适配器协程；后台线程阻塞读 stdin 帧，
经 `loop.call_soon_threadsafe` 投递；stdout 是唯一帧出口（写锁串行化）。
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import queue
import sys
import threading
import uuid

from neurova.channels.runner_protocol import (
    DependencyAuditError,
    buildHello,
    readFrame,
    runDependencyAudit,
    writeFrame,
)
from neurova.channels.runner_spec import LaunchSpec, defaultSourceRevision

logger = logging.getLogger(__name__)


def _loadAdapterClass(entrypoint: str):
    """加载入口适配器类；`builtin:echo` 之外的失败如实上抛（不静默降级）。"""
    if entrypoint == "builtin:echo":
        return None
    module_name, _, qualname = entrypoint.partition(":")
    if not module_name or not qualname:
        raise DependencyAuditError(f"入口点格式非法（应为 module:qualname）：{entrypoint!r}")
    module = importlib.import_module(module_name)
    adapter_cls = getattr(module, qualname)
    return adapter_cls


class _FrameWriter:
    """stdout 帧出口（多线程写锁串行化）。"""

    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, payload: dict) -> None:
        with self._lock:
            writeFrame(self._stream, payload)


def runnerMain(spec: LaunchSpec) -> int:
    """子进程主入口：审计 → 握手 → ready → 服务循环。返回退出码。"""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format="%(asctime)s [runner:%(name)s] %(levelname)s %(message)s",
    )
    out = _FrameWriter(sys.stdout.buffer)
    stdin = sys.stdin.buffer

    # 1) 依赖审计（先于加载任何渠道依赖——审计失败的子进程不应已把重模块拉起来）
    audit = runDependencyAudit(spec.required_deps)
    # 2) 握手 hello（源码版本带子进程**实测**值，供宿主与规格核对）
    out.send(buildHello(spec, os.getpid(), defaultSourceRevision()))

    # 3) 等宿主 ready
    first = readFrame(stdin)
    if first.get("op") != "ready":
        # 宿主拒绝（审计未过/版本不符）——如实退出，不假装服务
        logger.error("宿主未确认 ready，子进程退出：%s", first)
        return 2

    if spec.entrypoint == "builtin:echo":
        return _serveEcho(spec, stdin, out)

    return _serveAdapter(spec, stdin, out)


def _serveEcho(spec: LaunchSpec, stdin, out: _FrameWriter) -> int:
    """内置回显模式：协议/隔离测试用。支持 ping/echo/crash/emit。"""
    while True:
        try:
            frame = readFrame(stdin)
        except Exception:
            return 0  # 宿主关流 = 正常结束
        op = frame.get("op")
        if op == "shutdown":
            return 0
        if op == "crash":
            os._exit(int(frame.get("code") or 1))  # 模拟渠道崩溃（不走清理）
        if op == "ping":
            out.send({"op": "pong", "req_id": frame.get("req_id")})
            continue
        if op == "emit":
            # 模拟渠道入站事件上行
            out.send({"op": "event", "event_type": frame.get("event_type") or "message_received",
                      "message": frame.get("message") or {}})
            continue
        if op == "send":
            content = str(frame.get("content") or "")
            out.send({"op": "send_result", "ok": True,
                      "message_id": f"echo-{uuid.uuid4().hex[:12]}",
                      "echo": content, "req_id": frame.get("req_id")})
            continue
        logger.warning("echo 模式未知帧 op=%s，忽略", op)


def _serveAdapter(spec: LaunchSpec, stdin, out: _FrameWriter) -> int:
    """真实适配器模式：asyncio 驱动 connect/send_message，事件经帧上行。"""
    adapter_cls = _loadAdapterClass(spec.entrypoint)

    from neurova.channels.base import ChannelConfig

    config = ChannelConfig(channel_type=spec.channel_type)
    adapter = adapter_cls(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    inbound: "queue.Queue[dict]" = queue.Queue()

    def _stdinReader() -> None:
        while True:
            try:
                frame = readFrame(stdin)
            except Exception:
                break  # 宿主关流
            loop.call_soon_threadsafe(inbound.put, frame)

    threading.Thread(target=_stdinReader, daemon=True, name="runner-stdin").start()

    def _emitEvent(event_type, message) -> None:
        out.send({"op": "event", "event_type": str(getattr(event_type, "value", event_type)),
                  "message": message.to_dict() if hasattr(message, "to_dict") else dict(message or {})})

    adapter.set_event_callback(
        lambda et, msg: loop.call_soon_threadsafe(_emitEvent, et, msg))

    async def _serve() -> int:
        await adapter.connect()
        out.send({"op": "adapter_connected"})
        while True:
            frame = await loop.run_in_executor(None, inbound.get)
            op = frame.get("op")
            if op == "shutdown":
                await adapter.disconnect()
                return 0
            if op == "ping":
                out.send({"op": "pong", "req_id": frame.get("req_id")})
                continue
            if op == "send":
                try:
                    message_id = await adapter.send_message(
                        chat_id=str(frame.get("chat_id") or ""),
                        content=str(frame.get("content") or ""),
                        message_type=str(frame.get("message_type") or "text"),
                        **(frame.get("kwargs") or {}),
                    )
                    out.send({"op": "send_result", "ok": True,
                              "message_id": message_id or "",
                              "req_id": frame.get("req_id")})
                except Exception as e:  # 失败如实回传，宿主侧可见
                    out.send({"op": "send_result", "ok": False,
                              "error": str(e), "req_id": frame.get("req_id")})
            else:
                logger.warning("未知帧 op=%s，忽略", op)

    try:
        return loop.run_until_complete(_serve())
    finally:
        loop.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m neurova.channels.runner_main <spec_json>", file=sys.stderr)
        return 64
    try:
        spec = LaunchSpec.from_json(sys.argv[1])
    except Exception as e:
        print(f"规格解析失败：{e}", file=sys.stderr)
        return 64
    try:
        return runnerMain(spec)
    except DependencyAuditError as e:
        print(f"依赖审计未通过：{e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
