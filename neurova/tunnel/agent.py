"""服务端侧的出站隧道代理（设计方案 §3，S2 批）。

它干的事只有一件：**从家里拨出去**，挂在中继那条控制连接上，等中继把手机侧的请求交给它，
再由它**另开一条数据连接**把这一条请求接回来。服务端不需要公网 IP、不需要固定地址、
不需要开任何入站端口——这条路的全部前提就是"出站总是通的"。

状态口径（`probing` / `via_relay` / `relay_down`）与尺度常量都在 `protocol.py`，
这里不另写一份；面板读的是 `tunnelStatus()`（唯一读处）。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import threading
import time
from typing import Any, Dict, Optional, Set

from neurova.core.logger import get_logger
from neurova.tunnel import protocol

logger = get_logger(__name__)

#: 回连本机后端用的地址。经隧道进来的请求最终要落到自家 FastAPI 上，
#: 而 agent 与后端同机——默认走环回，不经任何公网。
LOCAL_BASE_URL_DEFAULT = "http://127.0.0.1:9527"


def _localBaseUrl() -> str:
    return (os.environ.get("NEUROVA_TUNNEL_LOCAL_BASE_URL") or LOCAL_BASE_URL_DEFAULT).rstrip("/")


def _wsLocalBaseUrl(httpBaseUrl: str) -> str:
    """同一条后端地址换成 ws 形态（隧道里的 WS 落到自家 `/api/v1/mobile/ws`）。"""
    return ("ws://" if httpBaseUrl.startswith("http://") else "wss://") + \
        httpBaseUrl.split("://", 1)[1]


def _relayParts(relayUrl: str) -> tuple:
    """把中继地址拆成 `(wsScheme, netloc, prefix)`，ws/wss 与 http/https 同处换算。"""
    from urllib.parse import urlsplit

    normalized = relayUrl if "://" in relayUrl else "https://" + relayUrl
    parts = urlsplit(normalized)
    secure = parts.scheme in ("https", "wss")
    wsScheme = "wss" if secure else "ws"
    return wsScheme, parts.netloc, parts.path.rstrip("/")


class TunnelAgent:
    """一条控制连接 ＋ N 条按需数据连接的出站代理。

    生命周期由 `run()` 驱动（一个 asyncio task）：内部自己重连，外部只需要
    `start()`／`stop()`。刻意不做"连接成功就打日志然后躺平"——那条日志必须有人读，
    面板上那个通道徽标就是它的读者（AGENTS §2 的闭环要求）。
    """

    def __init__(self, relayUrl: str = "", enrollmentToken: str = "",
                 instanceId: str = "", localBaseUrl: Optional[str] = None,
                 heartbeatSeconds: float = protocol.TUNNEL_HEARTBEAT_INTERVAL_SECONDS,
                 openTimeoutSeconds: float = protocol.TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS):
        self.relayUrl = relayUrl.strip()
        self.enrollmentToken = enrollmentToken
        self.instanceId = instanceId
        self.localBaseUrl = (localBaseUrl or _localBaseUrl()).rstrip("/")
        self.heartbeatSeconds = heartbeatSeconds
        self.openTimeoutSeconds = openTimeoutSeconds

        self.state = protocol.TUNNEL_STATES[0] if not self.relayUrl else "probing"
        self.routeId: Optional[str] = None
        self.lastHeartbeatAt: Optional[float] = None
        self.lastRttMs: Optional[float] = None
        self.lastError: str = ""
        self._activeStreams: Set[str] = set()
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------ 读数

    def tunnelStatus(self) -> Dict[str, Any]:
        """面板/判据的唯一读处：通道此刻是什么状态、归哪条 route、最近一次心跳。

        刻意回**读数**而不是"bool 是否连上"：`registered` 与 `probing` 与 `relay_down`
        在处置上各不相同（前者重连即可，后者要去中继机器上看），压成布尔就看不见了。
        """
        return {
            "state": self.state,
            "configured": bool(self.relayUrl),
            "route_id": self.routeId,
            "instance_id": self.instanceId,
            "last_heartbeat_at": self.lastHeartbeatAt,
            "last_rtt_ms": self.lastRttMs,
            "active_streams": len(self._activeStreams),
            "local_base_url": self.localBaseUrl,
            "last_error": self.lastError,
        }

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        if not self.relayUrl:
            self.state = protocol.TUNNEL_STATES[0]     # disabled
            logger.info("隧道未配置中继地址，通道状态置 disabled（配对面板据此阻断发码）")
            return
        if self._task is not None and not self._task.done():
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 关停路径
                pass
            self._task = None

    async def run(self) -> None:
        """控制连接主循环：失败按指数退避＋抖动重连，永不放弃、也不刷屏。"""
        attempt = 0
        import websockets

        scheme, netloc, prefix = _relayParts(self.relayUrl)
        url = (f"{scheme}://{netloc}{prefix}{protocol.RELAY_CONTROL_PATH}"
               f"?{protocol.ENROLLMENT_TOKEN_PARAM}={self.enrollmentToken}"
               f"&instanceId={self.instanceId}")
        while not self._stop.is_set():
            self.state = "probing"
            try:
                async with websockets.connect(url, ping_interval=None) as socket:
                    await self._serveControl(socket)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - 网络类失败全部按"等一会儿再试"处置
                self.state = "relay_down"
                self.lastError = f"{type(e).__name__}: {e}"
                attempt += 1
                backoff = min(2 ** min(attempt, 5), protocol.TUNNEL_RECONNECT_MAX_BACKOFF_SECONDS)
                backoff += random.uniform(0, 0.5)
                logger.warning("隧道第 %s 次重连，%.1fs 后重试：%s", attempt, backoff, self.lastError)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    return
                except asyncio.TimeoutError:
                    pass

    async def _serveControl(self, socket) -> None:
        """注册 → 心跳 → 收 `open` 就派一条数据连接去接这条请求。"""
        import websockets

        registered = json.loads(await socket.recv())
        if registered.get("type") != protocol.FRAME_REGISTERED:
            self.lastError = f"注册回话形状不对：{registered}"
            self.state = "relay_down"
            return
        self.routeId = registered.get("routeId")
        self.state = "via_relay"
        self.lastHeartbeatAt = time.time()
        self.lastError = ""
        logger.info("隧道已注册 route=%s", self.routeId)

        misses = 0
        tasks: Set[asyncio.Task] = set()
        recvTask = asyncio.create_task(socket.recv())
        try:
            while True:
                # 心跳与收帧并行：控制连接静默时，靠 ping/pong 判死，不等 TCP 自己报错
                try:
                    frame = await asyncio.wait_for(
                        asyncio.shield(recvTask), timeout=self.heartbeatSeconds)
                except asyncio.TimeoutError:
                    misses += 1
                    await socket.send(json.dumps({"type": protocol.FRAME_PING,
                                                  "echo": time.time()}))
                    if misses >= protocol.TUNNEL_MISSES_BEFORE_DOWN:
                        self.state = "relay_down"
                        self.lastError = "心跳连续无回"
                        logger.warning("隧道心跳连续 %s 次无回，判定 relay_down", misses)
                        return
                    continue

                recvTask = asyncio.create_task(socket.recv())
                message = json.loads(frame) if isinstance(frame, (str, bytes)) else {}
                kind = message.get("type")
                if kind == protocol.FRAME_PONG:
                    misses = 0
                    self.lastHeartbeatAt = time.time()
                    sentAt = message.get("echo")
                    if isinstance(sentAt, (int, float)):
                        self.lastRttMs = round((time.time() - sentAt) * 1000, 1)
                elif kind == protocol.FRAME_PING:
                    misses = 0
                    self.lastHeartbeatAt = time.time()
                    await socket.send(json.dumps({"type": protocol.FRAME_PONG,
                                                  "echo": message.get("echo")}))
                elif kind == protocol.FRAME_OPEN:
                    task = asyncio.create_task(self._serveStream(message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        finally:
            recvTask.cancel()
            for task in list(tasks):
                task.cancel()

    async def _serveStream(self, openFrame: Dict[str, Any]) -> None:
        """按中继的 `open` 指令另开一条数据连接，把这条请求接到本机后端。"""
        import websockets

        streamId = str(openFrame.get("streamId") or "")
        if not streamId:
            return
        self._activeStreams.add(streamId)
        scheme, netloc, prefix = _relayParts(self.relayUrl)
        dataUrl = (f"{scheme}://{netloc}{prefix}{protocol.RELAY_DATA_PATH}"
                   f"?{protocol.ENROLLMENT_TOKEN_PARAM}={self.enrollmentToken}")
        try:
            async with websockets.connect(dataUrl, ping_interval=None,
                                          open_timeout=self.openTimeoutSeconds) as socket:
                await socket.send(json.dumps({"type": "hello", "streamId": streamId}))
                if openFrame.get("kind") == "ws":
                    await self._pumpWebSocket(socket, openFrame)
                else:
                    await self._relayHttp(socket, openFrame)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 单条流坏掉不能带走控制连接
            logger.warning("隧道数据流 %s 失败：%s", streamId, e)
        finally:
            self._activeStreams.discard(streamId)

    async def _relayHttp(self, socket, openFrame: Dict[str, Any]) -> None:
        """HTTP：收完请求体 → 打到本机后端 → 回 `head` + `data`。"""
        import httpx

        body = bytearray()
        async for raw in socket:
            frame = json.loads(raw)
            if frame.get("type") == protocol.FRAME_DATA:
                if frame.get("data"):
                    body.extend(base64.b64decode(frame["data"]))
                if frame.get("final") or frame.get("text"):
                    body.extend((frame.get("text") or "").encode("utf-8"))
            elif frame.get("type") == protocol.FRAME_END:
                break

        url = self.localBaseUrl + str(openFrame.get("path") or "/")
        headers = {k: v for k, v in (openFrame.get("headers") or {}).items()
                   if k.lower() not in ("host", "connection")}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(str(openFrame.get("method") or "GET"), url,
                                            headers=headers, content=bytes(body))
            await socket.send(json.dumps({"type": protocol.FRAME_HEAD, "status": resp.status_code,
                                          "headers": dict(resp.headers)}))
            await socket.send(json.dumps({
                "type": protocol.FRAME_DATA,
                "data": base64.b64encode(resp.content).decode("ascii"), "final": True}))
        except Exception as e:  # noqa: BLE001 - 后端没起来也要如实回错误码，不静默
            logger.warning("隧道转发到本机后端失败 %s：%s", url, e)
            await socket.send(json.dumps({"type": protocol.FRAME_ERROR,
                                          "code": "local_backend_unreachable",
                                          "message": str(e)}))

    async def _pumpWebSocket(self, socket, openFrame: Dict[str, Any]) -> None:
        """WS：手机帧 ↔ 本机后端帧，逐条过，不缓冲整条流。"""
        import websockets

        url = _wsLocalBaseUrl(self.localBaseUrl) + str(openFrame.get("path") or "/")
        headers = {k: v for k, v in (openFrame.get("headers") or {}).items()
                   if k.lower() != "host"}
        try:
            local = await websockets.connect(url, ping_interval=None, additional_headers=headers,
                                             open_timeout=self.openTimeoutSeconds)
        except Exception as e:  # noqa: BLE001 - 上游拒绝必须原样报回入口，不能被 accept 掩盖
            status = getattr(getattr(e, "response", None), "status_code", None)
            await socket.send(json.dumps({"type": protocol.FRAME_HEAD,
                                          "status": int(status) if status else 4502,
                                          "reason": type(e).__name__, "headers": {}}))
            return

        async with local:
            # 上游握手成了才报 101：入口据此决定 accept（顺序反了就是把 4001 吞成连接成功）
            await socket.send(json.dumps({"type": protocol.FRAME_HEAD, "status": 101,
                                          "headers": {}}))
            done = asyncio.Event()

            async def tunnelToLocal():
                async for raw in socket:
                    frame = json.loads(raw)
                    kind = frame.get("type")
                    if kind == protocol.FRAME_DATA:
                        await local.send(frame.get("text") or "")
                    elif kind == protocol.FRAME_END:
                        done.set()
                        return

            async def localToTunnel():
                async for message in local:
                    text = message if isinstance(message, str) else \
                        base64.b64encode(bytes(message)).decode("ascii")
                    await socket.send(json.dumps({"type": protocol.FRAME_DATA, "text": text}))
                done.set()

            tasks = [asyncio.create_task(tunnelToLocal()), asyncio.create_task(localToTunnel())]
            try:
                await done.wait()
            finally:
                for task in tasks:
                    task.cancel()


# ---------------------------------------------------------------------------
# 单例与启动接线（AGENTS §3：懒创建必须 DCL ＋ RLock）
# ---------------------------------------------------------------------------

_agent: Optional[TunnelAgent] = None
_agentLock = threading.RLock()


def buildAgentFromEnv() -> TunnelAgent:
    instanceId = (os.environ.get("NEUROVA_TUNNEL_INSTANCE_ID") or "").strip()
    if not instanceId:
        from neurova.core.data_root import dataPath

        # 稳定实例号：重注册要拿到**同一条 routeId**，否则每次重启都换地址，
        # 手机侧已配对的设备就得重扫——那正是本案要避免的那件事。
        instanceId = "nv-" + hashlib.sha256(
            dataPath("tunnel").encode("utf-8")).hexdigest()[:12]
    return TunnelAgent(
        relayUrl=os.environ.get(protocol.RELAY_URL_ENV, ""),
        enrollmentToken=os.environ.get(protocol.ENROLLMENT_TOKEN_ENV, ""),
        instanceId=instanceId,
    )


def getTunnelAgent() -> TunnelAgent:
    global _agent
    if _agent is None:
        with _agentLock:
            if _agent is None:
                _agent = buildAgentFromEnv()
    return _agent


def setTunnelAgent(agent: Optional[TunnelAgent]) -> None:
    """装配点注入/清空（活体脚本与判据走这里，不去改私有字段）。"""
    global _agent
    with _agentLock:
        _agent = agent


def tunnelStatus() -> Dict[str, Any]:
    return getTunnelAgent().tunnelStatus()
