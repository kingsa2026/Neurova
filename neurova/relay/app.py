"""可独立部署的中继（设计方案 §3，S2 批）。

一台有固定地址的机器替「无固定 IP 的服务端」持有入口：

    手机 ──wss/https──▶ 本中继 ──(agent 主动出站的连接)──▶ 家里的 Neurova

连接方向只有一头：**服务端从不监听公网入口**。服务端与中继之间是它自己拨出去的
`/agent/control`（长期）＋每条手机请求按需再开一条 `/agent/data`。

两条边界如实写出：
- **HTTP 体是缓冲搬运的**（`TUNNEL_MAX_BUFFERED_BYTES`）。移动端真正的流式对话走 WS，
  WS 帧是逐条过的，不受这条限制；别把这里当成通用大文件代理。
- **本中继终结 TLS**（已裁），所以它在位置上能读到明文。这是登记过的已知代价
  （设计方案 §4.5），访问日志走 `sensitive_info` 那台单源脱敏引擎，E2E 排在 S3。

数据面刻意用"每条手机连接另开一条数据通道"而不是自研多路复用帧层：
少一层协议，就没有队头阻塞——本仓「大产物 chunk」那条链上，一条长流不该拖住另一条。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse

from neurova.core.logger import get_logger
from neurova.tunnel import protocol

logger = get_logger(__name__)


#: 入口路径模板：`/t/<routeId>/<后端路径>`。
#: 这里**不能**写成 f-string——`{routeId}` 是 Starlette 的路径参数占位符，
#: f-string 会把单个 `}` 当语法错误（本仓实测撞过一次）。
RELAY_HTTP_ROUTE = protocol.RELAY_ROUTE_PREFIX + "{routeId}{rest:path}"


def _normaliseRestPath(rest: str) -> str:
    """`{rest:path}` 捕到的片段**本身可能已带前导斜杠**，这里统一成 `/xxx`。

    Starlette 对 `{routeId}{rest:path}` 的匹配里，`rest` 是 `.*`——`db8c.../api/v1/...`
    这种写法下它连那个 `/` 一起吃进来。若再手工前置一次，转出去的就是 `//api/v1/...`，
    后端回 404，而报错的地方离根因隔了一整条隧道（教义第 1 条：修在产生非法状态处）。
    """
    cleaned = rest or ""
    return cleaned if cleaned.startswith("/") else "/" + cleaned


def _routeIdFor(enrollmentToken: str, instanceId: str) -> str:
    """routeId 由**准入凭据 + instanceId** 派生，不接受调用方指定。

    为什么不能让它自己报：否则任何人注册一个撞名的 routeId，就能把别人手机的流量接走
    ——这是本设计新引入的最大攻击面，必须在入口堵死（设计方案 §4.4）。
    同一 instanceId 重连得到同一个 routeId ⇒ 幂等重注册，地址漂移不需要重新配对。
    """
    digest = hmac.new(enrollmentToken.encode("utf-8"), instanceId.encode("utf-8"),
                      hashlib.sha256).hexdigest()
    return digest[:12]


@dataclass
class _Stream:
    """一次手机侧请求对应的隧道通道（agent 会为此另开一条数据连接）。"""

    streamId: str
    routeId: str
    opened: asyncio.Event = field(default_factory=asyncio.Event)
    dataSocket: Optional[WebSocket] = None
    head: Optional[Dict[str, Any]] = None
    headArrived: asyncio.Event = field(default_factory=asyncio.Event)
    chunks: asyncio.Queue = field(default_factory=asyncio.Queue)
    ended: bool = False
    #: 上游（本机后端）的握手结果。**入口必须先拿到它**再决定是否 accept——
    #: 反过来做就会把后端的 4001 吞成"手机连上了"（活体 `[5b]` 实测红过这一形）。
    upstreamHead: Optional[Dict[str, Any]] = None
    upstreamReady: asyncio.Event = field(default_factory=asyncio.Event)


class RelayState:
    """控制面注册表：谁在册、每条 routeId 现在归哪条控制连接、在途 stream。"""

    def __init__(self, enrollmentToken: str) -> None:
        if not enrollmentToken:
            raise ValueError("中继必须配置准入凭据（空凭据＝任何人都能注册）")
        self.enrollmentToken = enrollmentToken
        self.controlByRoute: Dict[str, WebSocket] = {}
        self.lastSeenByRoute: Dict[str, float] = {}
        self.routeByInstance: Dict[str, str] = {}
        self.streams: Dict[str, _Stream] = {}
        self._lock = asyncio.Lock()

    def admits(self, presentedToken: Optional[str]) -> bool:
        return bool(presentedToken) and hmac.compare_digest(
            str(presentedToken), self.enrollmentToken)

    async def register(self, instanceId: str, socket: WebSocket) -> str:
        async with self._lock:
            routeId = self.routeByInstance.get(instanceId) or _routeIdFor(
                self.enrollmentToken, instanceId)
            self.routeByInstance[instanceId] = routeId
            self.controlByRoute[routeId] = socket
            self.lastSeenByRoute[routeId] = time.time()
            return routeId

    async def drop(self, routeId: str, socket: WebSocket) -> None:
        async with self._lock:
            # 只摘"还是这条连接"的那份：agent 重连快时，旧连接的 finally 会晚于新连接注册到达，
            # 无条件 pop 会把刚建好的在册状态一起删掉（表现为"明明连上了却回 503"）
            if self.controlByRoute.get(routeId) is socket:
                self.controlByRoute.pop(routeId, None)
                self.lastSeenByRoute.pop(routeId, None)

    def controlOf(self, routeId: str) -> Optional[WebSocket]:
        return self.controlByRoute.get(routeId)

    def touch(self, routeId: str) -> None:
        self.lastSeenByRoute[routeId] = time.time()

    def evictStale(self, afterSeconds: float) -> List[str]:
        now = time.time()
        stale = [routeId for routeId, seen in self.lastSeenByRoute.items()
                 if now - seen > afterSeconds]
        for routeId in stale:
            self.controlByRoute.pop(routeId, None)
            self.lastSeenByRoute.pop(routeId, None)
        return stale

    def snapshot(self) -> Dict[str, Any]:
        return {
            "registeredRoutes": sorted(self.controlByRoute),
            "inFlightStreams": len(self.streams),
        }


def create_relay_app(enrollmentToken: str) -> FastAPI:
    """建中继应用。`enrollmentToken` 为空 ⇒ 直接拒绝启动（空凭据等于没有入口）。"""
    state = RelayState(enrollmentToken)
    app = FastAPI(title="Neurova Tunnel Relay")
    app.state.relay = state

    # ------------------------------------------------------------------ 控制面

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, **state.snapshot()}

    @app.websocket(protocol.RELAY_CONTROL_PATH)
    async def control(websocket: WebSocket):
        """agent 的出站长连接：注册、心跳、接收 `open` 指令。"""
        if not state.admits(websocket.query_params.get(protocol.ENROLLMENT_TOKEN_PARAM)):
            await websocket.close(code=4401, reason=protocol.TUNNEL_ERROR_CODES[1])
            return
        instanceId = (websocket.query_params.get("instanceId") or "").strip()
        if not instanceId:
            await websocket.close(code=4400, reason="missing instanceId")
            return

        await websocket.accept()
        routeId = await state.register(instanceId, websocket)
        await websocket.send_json({"type": protocol.FRAME_REGISTERED, "routeId": routeId})
        logger.info("隧道注册 instance=%s route=%s", instanceId, routeId)

        try:
            while True:
                frame = await websocket.receive_json()
                kind = frame.get("type")
                if kind == protocol.FRAME_PING:
                    state.touch(routeId)
                    await websocket.send_json({"type": protocol.FRAME_PONG,
                                               "echo": frame.get("echo")})
                elif kind == protocol.FRAME_PONG:
                    state.touch(routeId)
                else:
                    state.touch(routeId)
        except Exception as e:  # noqa: BLE001 - 连接断开是常态，不是异常分支
            logger.info("隧道控制连接结束 route=%s：%s", routeId, type(e).__name__)
        finally:
            await state.drop(routeId, websocket)

    @app.websocket(protocol.RELAY_DATA_PATH)
    async def dataChannel(websocket: WebSocket):
        """agent 为某条 stream 另开的数据连接。

        先收一个 `hello{streamId}` 再绑定：握手阶段还不能确定它属于哪条请求，
        而 streamId 是一次性的随机数——凭它认领即可，不需要额外的授权面。
        """
        if not state.admits(websocket.query_params.get(protocol.ENROLLMENT_TOKEN_PARAM)):
            await websocket.close(code=4401, reason=protocol.TUNNEL_ERROR_CODES[1])
            return
        await websocket.accept()
        try:
            hello = await websocket.receive_json()
        except Exception:  # noqa: BLE001
            await websocket.close(code=4400)
            return

        stream = state.streams.get(str(hello.get("streamId") or ""))
        if stream is None or stream.dataSocket is not None:
            # 不认识的 streamId，或这条已经被认领过：宁可拒绝，不把流量接到别人身上
            await websocket.close(code=4404, reason="unknown or claimed stream")
            return
        stream.dataSocket = websocket
        stream.opened.set()

        try:
            async for raw in websocket.iter_text():
                _absorbChunk(stream, json.loads(raw))
        except Exception as e:  # noqa: BLE001
            logger.debug("数据通道结束 stream=%s：%s", stream.streamId, type(e).__name__)
        finally:
            stream.ended = True
            stream.chunks.put_nowait(None)

    # ------------------------------------------------------------------ 入口面

    async def _openStream(routeId: str, *, kind: str, method: str, path: str,
                          headers: Dict[str, str]) -> Optional[_Stream]:
        controlSocket = state.controlOf(routeId)
        if controlSocket is None:
            return None
        stream = _Stream(streamId=uuid.uuid4().hex, routeId=routeId)
        state.streams[stream.streamId] = stream
        try:
            await controlSocket.send_json({
                "type": protocol.FRAME_OPEN, "streamId": stream.streamId, "kind": kind,
                "method": method, "path": path, "headers": headers,
            })
            await asyncio.wait_for(stream.opened.wait(),
                                   protocol.TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            state.streams.pop(stream.streamId, None)
            return None
        except Exception:  # noqa: BLE001 - 控制连接刚断
            state.streams.pop(stream.streamId, None)
            return None
        return stream

    async def _driveHttp(stream: _Stream, body: bytes) -> None:
        if body:
            await stream.dataSocket.send_json({
                "type": protocol.FRAME_DATA, "streamId": stream.streamId,
                "data": base64.b64encode(body).decode("ascii"), "final": False,
            })
        await stream.dataSocket.send_json(
            {"type": protocol.FRAME_END, "streamId": stream.streamId})

    @app.api_route(RELAY_HTTP_ROUTE, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def proxyHttp(request: Request, routeId: str, rest: str):
        stream = await _openStream(
            routeId, kind="http", method=request.method,
            path=_normaliseRestPath(rest) + (f"?{request.url.query}"
                                            if request.url.query else ""),
            headers={k: v for k, v in request.headers.items()
                     if k.lower() not in ("host", "content-length")},
        )
        if stream is None:
            # 诚实失败：显式 503 ＋ 点名原因，不静默重发、不降级成 warning（教义第 2 条）
            return JSONResponse(
                status_code=503,
                content={"code": protocol.TUNNEL_ERROR_CODES[0],
                         "message": "隧道未就绪（agent 未注册或未在窗口内开出数据通道）"},
            )

        body = await request.body()
        if len(body) > protocol.TUNNEL_MAX_BUFFERED_BYTES:
            state.streams.pop(stream.streamId, None)
            return JSONResponse(status_code=413,
                                content={"code": "payload_too_large"})
        await _driveHttp(stream, body)

        try:
            await asyncio.wait_for(stream.headArrived.wait(),
                                   protocol.TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS * 6)
        except asyncio.TimeoutError:
            state.streams.pop(stream.streamId, None)
            return JSONResponse(status_code=504, content={"code": "upstream_timeout"})

        head = stream.head or {}
        collected = bytearray()
        while True:
            piece = await stream.chunks.get()
            if piece is None:
                break
            collected.extend(piece)

        headers = {k: v for k, v in (head.get("headers") or {}).items()
                   if k.lower() not in ("transfer-encoding", "content-length")}
        state.streams.pop(stream.streamId, None)
        return StreamingResponse(iter([bytes(collected)]),
                                 status_code=int(head.get("status", 502)), headers=headers)

    @app.websocket(RELAY_HTTP_ROUTE)   # 同一条路径，WS 与 HTTP 各一条路由
    async def proxyWs(websocket: WebSocket, routeId: str, rest: str):
        """WS 入口（移动端对话那条真流式路径）。帧逐条搬运，不缓冲整条流。"""
        query = websocket.query_params
        path = _normaliseRestPath(rest) + (f"?{query}" if str(query) else "")
        stream = await _openStream(
            routeId, kind="ws", method="WS", path=path,
            # Authorization 随 header 过隧道，不进 URL，也就不进中继的访问日志（§4.2）
            headers={k: v for k, v in websocket.headers.items()
                     if k.lower() in ("authorization", "sec-websocket-protocol", "content-type")},
        )
        if stream is None:
            await websocket.close(code=4503, reason=protocol.TUNNEL_ERROR_CODES[0])
            return

        try:
            await asyncio.wait_for(stream.upstreamReady.wait(),
                                   protocol.TUNNEL_STREAM_OPEN_TIMEOUT_SECONDS * 4)
        except asyncio.TimeoutError:
            state.streams.pop(stream.streamId, None)
            await websocket.close(code=4504, reason="upstream handshake timeout")
            return
        head = stream.upstreamHead or {}
        if int(head.get("status") or 0) != 101:
            # 后端拒了（凭证失效/已解除/超连接数）——把那个结果如实带出去，不伪装成连上
            state.streams.pop(stream.streamId, None)
            await websocket.close(code=int(head.get("status") or 4502),
                                  reason=str(head.get("reason") or "upstream refused"))
            return

        await websocket.accept()
        pumpOut = asyncio.create_task(_pumpClientToAgent(websocket, stream))
        pumpIn = asyncio.create_task(_pumpAgentToClient(websocket, stream))
        try:
            await asyncio.wait({pumpOut, pumpIn}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (pumpOut, pumpIn):
                task.cancel()
            state.streams.pop(stream.streamId, None)
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001 - 已经断了就不算失败
                pass

    async def _pumpClientToAgent(websocket: WebSocket, stream: _Stream) -> None:
        async for raw in websocket.iter_text():
            await stream.dataSocket.send_json(
                {"type": protocol.FRAME_DATA, "streamId": stream.streamId, "text": raw})
        await stream.dataSocket.send_json(
            {"type": protocol.FRAME_END, "streamId": stream.streamId})

    async def _pumpAgentToClient(websocket: WebSocket, stream: _Stream) -> None:
        while True:
            piece = await stream.chunks.get()
            if piece is None:
                return
            await websocket.send_text(piece.decode("utf-8", errors="replace"))

    return app


def _absorbChunk(stream: _Stream, frame: Dict[str, Any]) -> None:
    """把 agent 回的一帧归进这条 stream（`head` 给状态码/头，`data` 给体）。"""
    kind = frame.get("type")
    if kind == protocol.FRAME_HEAD:
        stream.head = {"status": frame.get("status"), "headers": frame.get("headers") or {}}
        stream.headArrived.set()
        stream.upstreamHead = stream.head
        stream.upstreamReady.set()
    elif kind == protocol.FRAME_DATA:
        payload = frame.get("text")
        if isinstance(payload, str):
            stream.chunks.put_nowait(payload.encode("utf-8"))
        else:
            stream.chunks.put_nowait(base64.b64decode(frame.get("data") or ""))
    elif kind == protocol.FRAME_ERROR:
        stream.head = stream.head or {"status": 502, "headers": {}}
        stream.headArrived.set()
        stream.upstreamHead = stream.head
        stream.upstreamReady.set()
        stream.chunks.put_nowait(json.dumps({"code": frame.get("code", "tunnel_error"),
                                             "message": frame.get("message", "")},
                                            ensure_ascii=False).encode("utf-8"))
