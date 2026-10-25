# -*- coding: utf-8 -*-
"""活体验证（设计方案 §8-S2）：**手机照着中继那条地址，真的连得上、真的流式回话**。

这一段要证的不是单元里那些决定点，而是三件事同时成立：

1. 服务端**不出站就连不进来**——agent 只往中继拨，中继那侧才有固定入口；
2. 配对发出的地址落在**隧道 route** 上（不是家里的地址），手机照它 connect 能被接受；
3. 一条真 WebSocket 穿过「手机 → 中继 → agent 另开的数据连接 → 本机后端」，
   流式 chunk 逐条回得来，`chat:cancel` 中途取消也回得来。

刻意不接真 LLM：本批审的是**传输面**，把配额花在这一格上是另一回事（本卷记过）。
后端 Agent 用一份脚本化的流式替身（`_StreamingStub`），其余全真——
真 uvicorn、真中继、真 agent、真 ticket、真 WS 帧。

跑法：
    PYTHONPATH="$(git rev-parse --show-toplevel)" \\
      .venv/Scripts/python.exe tests/manual/mobilePairingTunnel_batchS2.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaTunnelS2")

import httpx  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from neurova.api.endpoints import mobile_pairing as MP  # noqa: E402
from neurova.relay.app import create_relay_app  # noqa: E402
from neurova.tunnel import protocol  # noqa: E402
from neurova.tunnel.agent import TunnelAgent  # noqa: E402

OWNER = "u-tunnel-s2"
ENROLLMENT = "enrollment-token-for-live-s2"
failures: list[str] = []

BACKEND_HOST, BACKEND_PORT = "127.0.0.1", 9731
RELAY_HOST, RELAY_PORT = "127.0.0.1", 9732


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}", flush=True)
    if not ok:
        failures.append(name)


class _StreamingStub:
    """脚本化的流式 Agent：只为把传输面跑满，不接真 LLM（见模块 docstring）。"""

    async def chat_stream(self, user_input="", session_id="", metadata=None):
        for index in range(3):
            await asyncio.sleep(0.05)
            yield f"chunk-{index}"

    async def chat(self, user_input="", session_id="", metadata=None):
        return {"text": "sync-answer"}


def _buildBackendApp() -> FastAPI:
    """真挂载的配对路由（含真 WS 面），身份用 dependency_overrides 给一个固定属主。"""
    app = FastAPI()
    app.include_router(MP.router, prefix="/api/v1/mobile")
    app.dependency_overrides[MP._get_current_user_id] = lambda: OWNER
    return app


def _serve(app: FastAPI, host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(80):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError(f"服务没起来 {host}:{port}")


async def _waitPort(port: int) -> None:
    for _ in range(60):
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                await client.get(f"http://{RELAY_HOST}:{port}/healthz")
            return
        except Exception:  # noqa: BLE001 - 端口还没开就继续等
            await asyncio.sleep(0.1)
    raise RuntimeError("中继 /healthz 起不来")


async def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    # 后端先起：agent 要把请求打回它自己
    backendApp = _buildBackendApp()
    import neurova.api.endpoints as endpointsModule

    endpointsModule.get_agent_instance = lambda agent_id: _StreamingStub()
    backend = _serve(backendApp, BACKEND_HOST, BACKEND_PORT)

    relay = _serve(create_relay_app(ENROLLMENT), RELAY_HOST, RELAY_PORT)
    await _waitPort(RELAY_PORT)

    agent = TunnelAgent(
        relayUrl=f"http://{RELAY_HOST}:{RELAY_PORT}",
        enrollmentToken=ENROLLMENT,
        instanceId="nv-live-s2",
        localBaseUrl=f"http://{BACKEND_HOST}:{BACKEND_PORT}",
        heartbeatSeconds=2.0,
    )
    # 必须装进**模块单例**：`_wsOrigin` 读的是 `getTunnelAgent()`，而它在后端的线程里跑。
    # 手搓一个局部实例会装到本进程却装不进那条读路——第一版活体 `[2c]` 就是这么红的
    # （发出去的是 `ws://127.0.0.1:9731/...`，也就是后端自己的地址，不是隧道入口）。
    # 生产上这一点由 `neurova/api/app.py` 的 `_on_startup` 装配。
    from neurova.tunnel.agent import setTunnelAgent

    setTunnelAgent(agent)
    agent.start()

    # 1) 控制连接真注册上了
    routeId = None
    for _ in range(60):
        status = agent.tunnelStatus()
        if status["state"] == "via_relay":
            routeId = status["route_id"]
            break
        await asyncio.sleep(0.1)
    check("[1] agent 出站注册成功（state=via_relay 并拿到 routeId）",
          routeId is not None, json.dumps(agent.tunnelStatus(), ensure_ascii=False)[:160])
    if routeId is None:
        return 1

    entryBase = f"http://{RELAY_HOST}:{RELAY_PORT}{protocol.RELAY_ROUTE_PREFIX}{routeId}"

    # 2) 配对：发码必须走闸门，扫码换到的地址必须落在隧道 route 上
    async with httpx.AsyncClient(base_url=entryBase, timeout=15) as phone:
        gen = await phone.post("/api/v1/mobile/pairing/generate",
                               json={"device_name": "live-s2", "device_type": "mobile"})
        check("[2a] 经隧道发码 200", gen.status_code == 200,
              f"{gen.status_code} {gen.text[:140]}")
        if gen.status_code != 200:
            return 1
        body = gen.json()

        resolved = await phone.post("/api/v1/mobile/pairing/resolve", json={"ref": body["ref"]})
        check("[2b] 经隧道 resolve 200", resolved.status_code == 200, resolved.text[:160])
        wsUrl = resolved.json()["ws_url"]
        check("[2c] 换到的地址是隧道入口（含 /t/<routeId>，不含后端本机地址）",
              f"/t/{routeId}" in wsUrl and str(BACKEND_PORT) not in wsUrl, wsUrl)

        secondResolve = await phone.post("/api/v1/mobile/pairing/resolve", json={"ref": body["ref"]})
        check("[2d] 反向校准：同一个 ref 第二次兑换被拒",
              secondResolve.status_code in (409, 410), str(secondResolve.status_code))

        conf = await phone.post("/api/v1/mobile/pairing/confirm",
                               json={"ref": body["ref"], "device_name": "live-s2",
                                     "device_id": "dev-s2"})
        check("[3a] confirm 200 并回一次性 ticket", conf.status_code == 200, conf.text[:160])
        if conf.status_code != 200:
            return 1
        ticket = conf.json()["connect_ticket"]
        cleanUrl = conf.json()["ws_url"]
        check("[3b] 回连地址里不含凭证（§4.2）", "?" not in cleanUrl, cleanUrl)

        # 3) WS 穿隧道：真流式 chunk 逐条回得来
        wsTarget = cleanUrl.replace("ws://", "ws://").replace(
            f"{RELAY_HOST}:{RELAY_PORT}", f"{RELAY_HOST}:{RELAY_PORT}")
        chunks: list[str] = []
        async with websockets.connect(wsTarget, additional_headers={
                "Authorization": f"Bearer {ticket}"}) as sock:
            await sock.send(json.dumps({"type": "chat:send", "content": "隧道活体",
                                        "agent_id": "default", "session_id": "s2-live"}))
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    frame = json.loads(await asyncio.wait_for(sock.recv(), timeout=2))
                except asyncio.TimeoutError:
                    break
                if frame.get("type") == "chat:chunk":
                    chunks.append(frame.get("content", ""))
                elif frame.get("type") == "chat:done":
                    break
        check("[3c] 流式 chunk 逐条穿过隧道回来", len(chunks) >= 2, f"收到 {chunks}")

        # 4) 同一条连接上跑 ping/pong + 中途取消（cancel 要在流里被处理，不是等流结束）
        # 解除**之前**先备好一张没用过的新票：这样 [5b] 被拒的原因只能是在册判定，
        # 而不是"这张票已经被消费过"（一次性那条判据在 2d 与单测里各自钉着）。
        spareTicket = await _refreshTicket(phone, conf.json())
        async with websockets.connect(wsTarget, additional_headers={
                "Authorization": f"Bearer {await _refreshTicket(phone, conf.json())}"}) as sock:
            await sock.send(json.dumps({"type": "ping"}))
            pong = json.loads(await asyncio.wait_for(sock.recv(), timeout=5))
            check("[4a] 隧道上的应用层心跳有回", pong.get("type") == "pong", str(pong)[:120])

            await sock.send(json.dumps({"type": "chat:send", "content": "要取消",
                                        "agent_id": "default", "session_id": "s2-cancel"}))
            await sock.send(json.dumps({"type": "chat:cancel", "session_id": "s2-cancel"}))
            seen = []
            for _ in range(6):
                try:
                    seen.append(json.loads(await asyncio.wait_for(sock.recv(), timeout=3)).get("type"))
                except asyncio.TimeoutError:
                    break
            check("[4b] chat:cancel 在流里被处理（回 chat:cancelled）",
                  "chat:cancelled" in seen, str(seen))

        # 5) 撤销必须对**重连**生效：旧 ticket 与新 ticket 都不能再用
        pairingId = conf.json()["pairing_id"]
        revoked = await phone.delete(f"/api/v1/mobile/pairing/{pairingId}")
        check("[5a] 经隧道解除配对 200", revoked.status_code == 200, revoked.text[:140])
        refused = None
        try:
            async with websockets.connect(wsTarget, additional_headers={
                    "Authorization": f"Bearer {spareTicket}"}) as sock:
                refused = "accepted"
        except Exception as e:  # noqa: BLE001
            refused = f"refused {type(e).__name__}"
        check("[5b] 反向校准：解除后用旧凭证重连被拒（§4.8 那格洞的活体读数）",
              refused != "accepted", str(refused))

    # 6) 中继掉线 → agent 自己退回非 via_relay，再重连回注册（幂等，routeId 不变）
    await _stopServer(relay)
    downState = None
    for _ in range(80):
        state = agent.tunnelStatus()["state"]
        if state != "via_relay":
            downState = state
            break
        await asyncio.sleep(0.1)
    check("[6a] 中继没了，通道状态如实退化（不是仍报 via_relay）",
          downState in ("relay_down", "probing"), str(downState))

    relay2 = _serve(create_relay_app(ENROLLMENT), RELAY_HOST, RELAY_PORT)
    await _waitPort(RELAY_PORT)
    routeAgain = None
    for _ in range(120):
        status = agent.tunnelStatus()
        if status["state"] == "via_relay":
            routeAgain = status["route_id"]
            break
        await asyncio.sleep(0.1)
    check("[6b] 中继回来后同 instanceId 重注册拿到**同一条 routeId**（设备不必重扫）",
          routeAgain == routeId and routeAgain is not None, f"{routeAgain} vs {routeId}")

    await agent.stop()
    await _stopServer(backend)
    await _stopServer(relay2)

    print("\nLIVE-VERIFY PASSED / S2 隧道端到端（出站注册·隧道地址·流式回话·中途取消·撤销对重连生效·重注册幂等）"
          if not failures else f"\nLIVE-VERIFY FAILED：{failures}")
    return 0 if not failures else 1


async def _refreshTicket(phone, confirmBody: dict) -> str:
    """用设备身份换一张新票——顺带把 refresh 也活体跑一遍。"""
    resp = await phone.post("/api/v1/mobile/pairing/refresh", json={
        "pairing_id": confirmBody["pairing_id"],
        "device_secret": confirmBody["device_secret"],
        "challenge": "live-s2",
    })
    assert resp.status_code == 200, f"refresh 失败：{resp.status_code} {resp.text[:160]}"
    return resp.json()["connect_ticket"]


async def _stopServer(server) -> None:
    server.should_exit = True
    for _ in range(60):
        if not server.started:
            return
        await asyncio.sleep(0.1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
