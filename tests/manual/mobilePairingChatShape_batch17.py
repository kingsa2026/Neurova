# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-12 批 17，§6-154）：移动端 `chat:send` 在**活 app** 上真跑通一条回合。

判据档（`tests/unit/api/test_mobilePairingChatSendContract.py`）挂的是手搭 `FastAPI()`；
这一支要证的是另一件事：`/api/v1/mobile/ws` 在 `create_app()` 的真实路由表里可达、
配对码鉴权那一段真走通、并且调用点不再撞 `missing a required argument: 'user_input'`。

刻意**不打真 LLM**：本批修的是"调用形状"，把配额花在读判据上是另一回事（本卷记过）。
替身按真 `Agent` 的签名 bind 入参，因此形状错会照样在这里红。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/mobilePairingChatShape_batch17.py`
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaMobileShape17")

from fastapi.testclient import TestClient  # noqa: E402

import neurova.api.endpoints as endpointsModule  # noqa: E402
from neurova.api.app import create_app  # noqa: E402
from neurova.api.endpoints import mobile_pairing as mobile_ep  # noqa: E402
from neurova.core.identity_context import get_request_user_id  # noqa: E402

failures: list[str] = []
CODE = "LIVE17CODE"
OWNER = "u-live-17"
AGENT_ID = "kai"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _SignatureCheckingAgent:
    def __init__(self) -> None:
        from neurova.agent_core import Agent

        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: list[dict] = []
        self._sigStream = inspect.signature(Agent.chat_stream)
        self._sigChat = inspect.signature(Agent.chat)

    async def chat_stream(self, **kwargs):
        self._sigStream.bind(None, **kwargs)
        self.calls.append({"via": "chat_stream", "kwargs": kwargs,
                           "channel": get_request_user_id()})
        yield "收到"

    async def chat(self, **kwargs):
        self._sigChat.bind(None, **kwargs)
        self.calls.append({"via": "chat", "kwargs": kwargs,
                           "channel": get_request_user_id()})
        return {"text": "收到", "success": True}


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    agent = _SignatureCheckingAgent()
    endpointsModule.get_agent_instance = lambda agent_id="": agent
    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    mobile_ep._pairing_codes[CODE] = {"status": "confirmed", "user_id": OWNER,
                                      "pairing_id": "pair-live-17"}

    app = create_app(enable_memory=False, enable_channels=False)
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/mobile/ws?code={CODE}") as ws:
            ws.send_json({"type": "chat:send", "content": "活体一枪",
                          "session_id": "live-17-1"})
            events = []
            while True:
                payload = json.loads(ws.receive_text())
                events.append(payload)
                if payload.get("type") in ("chat:done", "error"):
                    break

        kinds = [e.get("type") for e in events]
        check("[1] 活 app 上 /api/v1/mobile/ws 真可达并回完一轮（chunk→done）",
              kinds[:1] == ["chat:chunk"] and kinds[-1] == "chat:done", str(kinds))
        failed = [e for e in events if e.get("code") == "chat_failed"]
        check("[2] 不再出现 chat_failed（修复前实测：missing a required argument: 'user_input'）",
              not failed, str(failed))
        check("[3] 替身真被调用，且走的是有 chat_stream 的那条分支",
              len(agent.calls) == 1 and agent.calls[0]["via"] == "chat_stream",
              str([c["via"] for c in agent.calls]))
        kwargs = agent.calls[0]["kwargs"] if agent.calls else {}
        check("[4] 调用点用的是真签名的参数名（user_input/metadata/session_id）",
              set(kwargs) == {"user_input", "session_id", "metadata"}
              and kwargs.get("user_input") == "活体一枪", str(sorted(kwargs)))
        check("[5] metadata 里的 user_id 与请求通道读数同一个人（同 §6-153 的边界口径）",
              (kwargs.get("metadata") or {}).get("user_id") == OWNER
              and agent.calls[0]["channel"] == OWNER,
              f"meta={(kwargs.get('metadata') or {}).get('user_id')!r} "
              f"channel={agent.calls[0].get('channel')!r}")
        check("[6] 回合之外不越权：无效配对码仍被拒（4001）",
              _refusedWithBadCode(client), "见下行细节")
    print()
    if failures:
        print("LIVE-VERIFY FAILED / 批 17 移动端调用形状与属主：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / 工单 2026-10-12 批 17（§6-154 移动端 chat:send 合修）")
    return 0


def _refusedWithBadCode(client) -> bool:
    try:
        with client.websocket_connect("/api/v1/mobile/ws?code=NOPE") as ws:
            ws.receive_text()
        return False
    except Exception as exc:  # noqa: BLE001 - 这里要的就是"被拒"这一形
        return getattr(exc, "code", None) == 4001


if __name__ == "__main__":
    raise SystemExit(main())
