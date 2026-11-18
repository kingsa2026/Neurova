# -*- coding: utf-8 -*-
"""渠道 Runner 帧协议与握手（对照批 A1）。

- 帧：4 字节大端长度前缀 + UTF-8 JSON。1MB 帧上限防畸形长度打爆内存。
- 握手：子进程先做**依赖审计**（required_deps 逐个 import 实测），把结果
  连同协议版本、源码版本、pid 一起写 hello 帧；宿主 `requireSatisfied`
  逐项核对，任何一项不满足即抛 `DependencyAuditError` 并终止子进程——
  **宁可不启动，不带病上线**（供应链防御的落点）。
"""

from __future__ import annotations

import importlib
import json
import struct
from typing import Any, Dict, IO

HANDSHAKE_PROTOCOL_VERSION = "1"
#: 单帧上限：超长即协议错误，防畸形长度前缀打爆内存。
MAX_FRAME_BYTES = 1 * 1024 * 1024

FRAME_HEADER_SIZE = 4


class FrameProtocolError(RuntimeError):
    """帧解析错误（长度越界/JSON 损坏/流提前结束）。"""


class DependencyAuditError(RuntimeError):
    """握手审计不通过（依赖缺失/协议版本不符/源码版本不一致）。"""


def encodeFrame(payload: Dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise FrameProtocolError(f"帧体超限：{len(body)} > {MAX_FRAME_BYTES}")
    return struct.pack(">I", len(body)) + body


def decodeFrame(raw: bytes) -> Dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def readFrame(stream: IO[bytes]) -> Dict[str, Any]:
    """从字节流读一帧；流提前结束抛 FrameProtocolError（区别于"还有数据"）。"""
    header = _readExact(stream, FRAME_HEADER_SIZE)
    if header is None:
        raise FrameProtocolError("流已关闭（读到 EOF）")
    (length,) = struct.unpack(">I", header)
    if length <= 0 or length > MAX_FRAME_BYTES:
        raise FrameProtocolError(f"非法帧长度：{length}")
    body = _readExact(stream, length)
    if body is None:
        raise FrameProtocolError("帧体不完整（流提前结束）")
    return decodeFrame(body)


def writeFrame(stream: IO[bytes], payload: Dict[str, Any]) -> None:
    stream.write(encodeFrame(payload))
    stream.flush()


def _readExact(stream: IO[bytes], size: int):
    buf = b""
    while len(buf) < size:
        chunk = stream.read(size - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def runDependencyAudit(required_deps) -> Dict[str, Any]:
    """子进程侧依赖审计：逐个 import 实测，返回审计结果（进 hello 帧）。"""
    missing = []
    for name in list(required_deps or []):
        try:
            importlib.import_module(str(name))
        except Exception:
            missing.append(str(name))
    return {"ok": not missing, "missing": missing}


def buildHello(spec, pid: int, actual_revision: str) -> Dict[str, Any]:
    """子进程 → 宿主的握手帧（审计结果在此回带）。

    `actual_revision` 是子进程**实测**的源码版本（不是规格转抄）——宿主拿它
    与规格核对，防"拉起来的代码不是我以为的代码"。
    """
    audit = runDependencyAudit(spec.required_deps)
    return {
        "op": "hello",
        "protocol_version": HANDSHAKE_PROTOCOL_VERSION,
        "channel_type": spec.channel_type,
        "source_revision": actual_revision,
        "pid": int(pid),
        "dependency_audit": audit,
    }


def requireSatisfied(hello: Dict[str, Any], spec) -> None:
    """宿主侧握手核对：任何一项不满足即抛 `DependencyAuditError`（fail-closed）。

    核对项：协议版本一致、渠道类型一致、源码版本一致（unknown 互相豁免——
    拿不到版本是"不知道"，不是"不一致"）、依赖审计通过。
    """
    if hello.get("op") != "hello":
        raise DependencyAuditError(f"握手首帧不是 hello：{hello.get('op')!r}")
    if hello.get("protocol_version") != HANDSHAKE_PROTOCOL_VERSION:
        raise DependencyAuditError(
            f"协议版本不符：子进程 {hello.get('protocol_version')!r} ≠ 宿主 {HANDSHAKE_PROTOCOL_VERSION!r}")
    if hello.get("channel_type") != spec.channel_type:
        raise DependencyAuditError(
            f"渠道类型不符：子进程 {hello.get('channel_type')!r} ≠ 规格 {spec.channel_type!r}")
    rev_child, rev_spec = hello.get("source_revision"), spec.source_revision
    if rev_child != rev_spec and "unknown" not in (rev_child, rev_spec):
        raise DependencyAuditError(
            f"源码版本不一致：子进程 {rev_child!r} ≠ 规格 {rev_spec!r}")
    audit = hello.get("dependency_audit") or {}
    if not audit.get("ok"):
        raise DependencyAuditError(
            f"依赖审计未通过，缺失：{audit.get('missing') or ['(未知)']}")
