# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-10 批 4）：渠道自助绑定在**真 HTTP + 真渠道路径**上的闭环。

## 为什么必须活体跑，单测全绿不够

批 4 把两张 sqlite 常驻表放上了**跨线程**路径：发码走 FastAPI 线程池，
消费码走渠道事件循环，读列表又回到线程池。单测里一切都发生在同一条线程上，
这条故障（`SQLite objects created in a thread can only be used in that same thread`）
只有真 HTTP 栈才暴露得彻底——本批的端点判据第一次跑出 500 时，报的就是它，
据此根修了三处常驻连接（`channels/user_identity`、`auth/verification_code`、
`auth/invitation_code`），并把它钉成常驻清单上的常驻判据
（`tests/unit/core/test_connection_pool_scope_adr0014.py`）。

## 判据

1. 网页发码 200，且回给前端的提示语在渠道侧**真的解析得出来**（同源正则）；
2. 渠道里那句"绑定 XXXX"就地消费：不进模型、不落会话；
3. 线程池里读绑定列表（跨线程读，前一条的写方在另一条线程上）；
4. 绑定生效后同一发送者的**下一轮**轮身份＝平台账号，记忆作用域成对下发；
5. 网页解绑 → 渠道下一轮回落 `ch:{渠道}:{发送者}`（不是 default 共享桶）；
6. 非管理员对无主 `default` 的读面 403（门沿本仓既有口径，未新造）；
7. 两张表都落在隔离数据根内（真实 `data/` 零写入）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/channelIdentityBinding_batch4.py`
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaIdentityBind4")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.auth import get_current_user as auth_u  # noqa: E402
from neurova.api.endpoints import channel_config as cc  # noqa: E402
from neurova.api.endpoints import set_app_state  # noqa: E402
from neurova.channels import channel_router  # noqa: E402
from neurova.channels.base import ChannelMessage  # noqa: E402
from neurova.channels.manager import ChannelManager  # noqa: E402
from neurova.channels.user_identity import UserIdentityManager  # noqa: E402

ADMIN = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "ne-root"}
OWNER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "ne-u1"}
STRANGER = {"user_id": "u2", "username": "bob", "role": "user", "neuser_id": "ne-u2"}
SENDER = "ou_77"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _ScopeSpy:
    def __init__(self):
        self.scopes = []

    def set_request_scope(self, neuser_id=None, user_id=None):
        self.scopes.append((neuser_id, user_id))


class _FakeAgent:
    """渠道处理器的最小被调方：记录每一轮拿到的身份，reply 用于反证"绑定消息没进模型"。"""

    def __init__(self):
        self.calls = []
        self.config = SimpleNamespace(owner_user_id="u1", agent_id="kai")
        self.memory_manager = _ScopeSpy()

    @property
    def current_reasoning(self):
        return ""

    def get_tool_messages_snapshot(self):
        return []

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append({"user_input": user_input, "metadata": metadata or {}})
        return {"text": "pong"}


def _msg(content: str) -> ChannelMessage:
    return ChannelMessage(
        channel_type="feishu", message_id="m1", sender_id=SENDER, sender_name="飞书用户",
        content=content, chat_id="oc_1", chat_type="p2p", metadata={"agent_id": "kai"},
    )


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    set_app_state({"agents": {"kai": SimpleNamespace(
        agent_id="kai", config=SimpleNamespace(owner_user_id="u1", agent_id="kai"))}})

    ChannelManager._instance = None
    manager = ChannelManager()

    app = FastAPI()
    app.include_router(cc.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(OWNER)
    base = "/api/v1/channel-configs"

    agent = _FakeAgent()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)

    with TestClient(app, raise_server_exceptions=False) as client:
        # ── [1] 网页发码（线程池线程）───────────────────────────────
        r = client.post(f"{base}/identity/bindings/code",
                        json={"agent_id": "kai", "channel_type": "feishu"})
        body = r.json() if r.status_code == 200 else {}
        code = body.get("code", "")
        command = body.get("command", "")
        check("[1] 发码 200 且带 6 位码与提示语",
              r.status_code == 200 and len(code) == 6 and "绑定" in command,
              f"{r.status_code} {body}")

        # ── [2] 渠道里那句"绑定 XXXX"就地消费（事件循环线程）──────
        reply = asyncio.run(handler(_msg(command)))
        check("[2] 渠道消费绑定码：回确认且没进模型",
              bool(reply) and "已绑定" in str(reply) and agent.calls == [],
              f"{reply} / calls={len(agent.calls)}")

        # ── [3] 线程池里读绑定列表（跨线程读，写方在另一条线程）───
        r = client.get(f"{base}/identity/bindings", params={"agent_id": "kai"})
        rows = (r.json().get("bindings") or []) if r.status_code == 200 else []
        check("[3] 列表 200 且记下归属与操作痕迹",
              r.status_code == 200 and len(rows) == 1
              and rows[0]["channel_user_id"] == SENDER
              and rows[0]["user_id"] == "u1" and rows[0]["bound_by"] == "bind-code",
              f"{r.status_code} {rows}")

        # ── [4] 下一轮：轮身份＝平台账号，记忆作用域成对 ──────────
        reply = asyncio.run(handler(_msg("我们上次聊到哪了")))
        meta = agent.calls[0]["metadata"] if agent.calls else {}
        check("[4] 绑定后下一轮身份＝平台账号且作用域成对",
              agent.calls and meta.get("user_id") == "u1"
              and meta.get("identity_bound") == "true"
              and agent.memory_manager.scopes == [("ne-u1", "u1")],
              f"calls={len(agent.calls)} meta={ {k: meta.get(k) for k in ('user_id', 'identity_bound')} }")

        # ── [5] 网页解绑 → 渠道回落渠道命名空间 ───────────────────
        r = client.delete(f"{base}/identity/bindings",
                          params={"agent_id": "kai", "channel_type": "feishu",
                                  "channel_user_id": SENDER})
        check("[5a] 解绑 200", r.status_code == 200, str(r.status_code))
        agent.calls.clear()
        reply = asyncio.run(handler(_msg("再问一次")))
        meta = agent.calls[0]["metadata"] if agent.calls else {}
        check("[5b] 解绑后下一轮回落 ch:feishu:ou_77（不是 default）",
              meta.get("user_id") == f"ch:feishu:{SENDER}" and meta.get("identity_bound") == "false",
              str(meta.get("user_id")))
        r = client.get(f"{base}/identity/bindings", params={"agent_id": "kai"})
        statuses = [row["status"] for row in (r.json().get("bindings") or [])]
        check("[5c] 解绑留痕（revoked 行仍在，答得出这人以前算谁的）",
              statuses == ["revoked"], str(statuses))

        # ── [6] 非管理员对无主 default 一律 403 ────────────────────
        app.dependency_overrides[auth_u] = lambda: dict(STRANGER)
        codes = {
            "读": client.get(f"{base}/identity/bindings", params={"agent_id": "default"}).status_code,
            "发码": client.post(f"{base}/identity/bindings/code",
                                json={"agent_id": "default", "channel_type": "feishu"}).status_code,
            "手工绑": client.post(f"{base}/identity/bindings", json={
                "agent_id": "default", "channel_type": "feishu",
                "channel_user_id": "ou_x", "user_id": "u2"}).status_code,
        }
        check("[6] 陌生人对 default 的绑定面全 403", set(codes.values()) == {403}, str(codes))

        # ── [7] 落点：两张表都在隔离根内 ──────────────────────────
        names = sorted(p.name for p in Path(WORK_ROOT).rglob("*.db"))
        check("[7] 绑定表与码表都落在隔离数据根",
              "channel_user_bindings.db" in names and "verification_codes.db" in names,
              str(names))

    UserIdentityManager.resetInstance()
    ChannelManager._instance = None
    set_app_state(None)

    print()
    if failures:
        print("LIVE-VERIFY FAILED / 批 4 渠道自助绑定：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / 工单 2026-10-10 批 4 渠道自助绑定闭环")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
