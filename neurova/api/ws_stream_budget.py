# -*- coding: utf-8 -*-
"""SSE / 推送流的性能与资源治理单源（参照系 ac 追平计划批三 E3）。

三件事：
1. **压缩协商单源**：:func:`negotiateCompression` 统一解析 ``Accept-Encoding``，
   各推送出口不再各自判读（当前服务端仅支持 gzip，不支持时诚实回落 identity）。
2. **单事件字节上限**：:data:`MAX_EVENT_BYTES` + :func:`enforceEventCap`——
   超限事件**整体替换**为诚实占位负载，绝不产出半截 JSON（半截 JSON 会让
   客户端解析失败且无法判断丢了什么；占位帧带 ``event_truncated`` 标注与
   原始字节数，客户端可计数、可告警）。
3. **重放字节预算**：:class:`ReplayByteBudget` 按帧累计本流外发字节，超预算置
   ``downgraded`` 标记，调用方据此降级为快照——与全局事件库
   ``swarm_event_store.replayThrough`` 的预算降级语义（degraded → 快照）协同，
   也与移动 WS 账本的重放窗口同构。预算可重置（连接续期场景复用同一对象）。

本模块不依赖仓内其他模块（仅标准库），可被 api 层与测试独立引用。
"""
from __future__ import annotations

import json
from typing import Optional, Tuple

__all__ = [
    "MAX_EVENT_BYTES",
    "negotiateCompression",
    "enforceEventCap",
    "ReplayByteBudget",
]

#: 单事件字节上限（64KiB）。
#:
#: 依据：通知 / 状态 / 增量类事件帧的合理量级在数 KB 以内，64KiB 已覆盖常规
#: 业务帧并留足余量；同时封顶"单帧 × 订阅数"的背压放大——一个 64KiB 帧推给
#: 一千条慢连接就是 64MB 级的瞬时输出。与移动 WS 账本的留档上限
#: （mobile_ws_ledger._RESULT_JSON_MAX，64KiB）、全局事件库的默认重放字节预算
#: 同一量级，各推送出口与三端（PC / 鸿蒙 / 安卓）按同一口径治理。
#: 超限不走"截断半截 JSON"，而是整体替换为诚实占位（见 enforceEventCap）。
MAX_EVENT_BYTES = 64 * 1024

#: 服务端支持的压缩编码偏好序（当前仅 gzip；identity 恒为隐式兜底）
_SERVER_PREFERRED_ENCODINGS = ("gzip",)


def negotiateCompression(accept_encoding_header: Optional[str]) -> dict:
    """解析 ``Accept-Encoding`` 请求头，返回 ``{"enabled": bool, "encoding": "gzip"|"identity"}``。

    规则（服务端压缩协商单源，各 SSE/WS 出口共用）：
    - 头缺失 / 为空 / 全空白 → 不启用压缩，``identity``；
    - 候选按 ``,`` 切分，编码名大小写不敏感；带 ``q=0``（或 q 值为 0）的候选视为
      **显式拒绝**；无 q 视为 q=1；
    - 通配 ``*`` 视为接受本服务端支持的 gzip；
    - 服务端按 ``_SERVER_PREFERRED_ENCODINGS`` 偏好序选取第一个可接受的编码；
      当前仅支持 gzip——候选里没有可接受的 gzip 时诚实回落 identity（不启用）。
    """
    raw = (accept_encoding_header or "").strip()
    if not raw:
        return {"enabled": False, "encoding": "identity"}

    acceptable: set = set()
    for token in raw.split(","):
        parts = token.strip().split(";")
        name = parts[0].strip().lower()
        if not name:
            continue
        quality = 1.0
        for param in parts[1:]:
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 1.0
        if quality > 0:
            acceptable.add(name)

    for candidate in _SERVER_PREFERRED_ENCODINGS:
        if candidate in acceptable or "*" in acceptable:
            return {"enabled": True, "encoding": candidate}
    return {"enabled": False, "encoding": "identity"}


def enforceEventCap(payload_bytes: bytes, *, max_bytes: Optional[int] = None) -> Tuple[bool, bytes]:
    """单事件字节上限判定：返回 ``(ok, honest_payload)``。

    - ``ok=True``：``payload_bytes`` 在上限内，``honest_payload`` 即原字节（原样外发）；
    - ``ok=False``：超限。``honest_payload`` 是一份**诚实占位**字节，与入参同形：
      入参是 SSE 数据帧（以 ``data: `` 开头）时返回完整 SSE 占位帧
      （``data: {"event_truncated": true, ...}\\n\\n``）；入参是裸负载字节时返回
      裸 JSON 占位字节（``{"event_truncated": true, ...}``）。占位内容为完整
      JSON——超限事件要么完整外发、要么整体替换为占位标注，绝不产出半截 JSON。

    ``max_bytes`` 缺省用 :data:`MAX_EVENT_BYTES`。入参 ``payload_bytes`` 是准备
    外发的整帧编码字节（SSE 语境即 ``renderFrame`` 产物）或事件负载字节，
    两者都按同一上限判定。
    """
    cap = MAX_EVENT_BYTES if max_bytes is None else int(max_bytes)
    if len(payload_bytes) <= cap:
        return True, payload_bytes
    placeholder = {
        "event_truncated": True,
        "reason": "event_bytes_exceed_cap",
        "original_bytes": len(payload_bytes),
        "cap_bytes": cap,
    }
    encoded = json.dumps(placeholder, ensure_ascii=False).encode("utf-8")
    if payload_bytes.startswith(b"data: "):
        # 入参是 SSE 数据帧：占位也包成同形完整帧（含 data: 前缀与结尾空行）
        return False, b"data: " + encoded + b"\n\n"
    return False, encoded


class ReplayByteBudget:
    """重放 / 推送字节预算：累计记账，超预算置降级标记，可重置。

    语义与全局事件库 ``replayThrough`` 的预算协同：调用方在把每帧外发前
    ``feed(字节数)``，返回 ``False`` 表示这一笔使累计**突破预算**——调用方应把
    该帧扣下不发、转快照恢复（绝不部分回放）。降级后继续 feed 一律拒绝。
    """

    def __init__(self, max_bytes: int):
        max_bytes = int(max_bytes)
        if max_bytes < 0:
            raise ValueError("max_bytes 不能为负数")
        self._maxBytes = max_bytes
        self._fed = 0
        self._downgraded = False

    @property
    def maxBytes(self) -> int:
        return self._maxBytes

    @property
    def fedBytes(self) -> int:
        """累计记账字节（含被扣下的溢出帧——账面反映真实需求）。"""
        return self._fed

    @property
    def downgraded(self) -> bool:
        """是否已突破预算（调用方据此降级为快照）。"""
        return self._downgraded

    def remaining(self) -> int:
        """剩余可用字节（降级后为 0）。"""
        return max(0, self._maxBytes - self._fed)

    def wouldExceed(self, n_bytes: int) -> bool:
        """预判：再记 ``n_bytes`` 是否会突破预算（不真正记账）。"""
        return self._fed + int(n_bytes) > self._maxBytes

    def feed(self, n_bytes: int) -> bool:
        """记账 ``n_bytes``；返回 ``False`` 表示本笔使累计突破预算（已置降级标记）。"""
        self._fed += int(n_bytes)
        if self._fed > self._maxBytes:
            self._downgraded = True
            return False
        return True

    def reset(self) -> None:
        """清零账面与降级标记（连接续期 / 重连后复用同一预算对象）。"""
        self._fed = 0
        self._downgraded = False

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"ReplayByteBudget(max_bytes={self._maxBytes}, fed={self._fed}, downgraded={self._downgraded})"
