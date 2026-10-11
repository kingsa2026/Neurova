# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-11 批 12，裁定甲）：流式对话的会话属主。

## 为什么必须真 HTTP 栈

这条判据的三个环节分处不同执行上下文：端点 → SSE 异步生成器 → `create_task(run_chat())`。
`asyncio.run`/`create_task` 会**复制**当前上下文，所以"写在哪一行"决定"那条 task 看不看得到"
——只有走真的 `/api/v1/chat/stream` 请求才测得准，单测里直接调 `event_generator()` 会假绿。

## 实测到的原缺陷（本批要修的）

`chat_stream` 从不写 `call_metadata["user_id"]`，也不设请求通道；而非流式 `/chat` 两处都写
（批 9 之后是在边界写一次）。于是流式回合里 `mem_core.save_to_session:1425` 取到**空属主**，
而 `session_manager.py:1650` 的过滤规则是「空属主不过滤」⇒ **任何登录用户的会话列表都能看见
别人流式对话的标题**。（`/chat` 非流式不受影响：它按登录用户落属主。）

## 判据

1. 流式回合内：`metadata['user_id']` ＝ 登录用户（不是客户端自报，也不是空）；
2. 同一回合内读请求通道 `get_request_user_id()` ＝ 同一人；
3. 报文里自报的 `metadata.user_id` 被服务端覆盖（客户端不能指定自己是谁）；
4. 非流式 `/chat` 两条读数同样成立（防"只修流式、把非流式改坏"）；
5. **落盘属主由生产代码算出**：替身 agent 在回合内调真的 `MemCore.save_to_session()`
   （脚本不自己拼 `user_id=`），于是磁盘上那条会话的属主是 `:1425` 的读数——
   然后 `list_sessions(agent_id, user_id=别人)` 不带出它、`user_id=本人` 带出它。
   最后一格才是"看不见别人的"，而不是"字段写了但没人用"；
6. 按教义第 5 条扫出的同根命中点（批 9 删管线双写时漏掉的网页面）：`/console/chat` 与
   `/console/ws/{client_id}` 两条回合内**也必须**在边界建立请求级属主——那里为空不只是会话
   归属问题，还让 usage 入账落 `"anonymous"`（`multi_model_client:876/1156`）、按日 LLM 配额
   整条不判（`:1426` 无身份即放行）；另带一格「无效 token 仍被 4401 拒且不跑回合」，
   防"补属主"把闸门放宽成"匿名即有人"。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/streamSessionOwnership_batch12.py`
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaStreamOwner12")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.auth import get_current_user as auth_u  # noqa: E402
from neurova.api.endpoints import chat as chat_ep  # noqa: E402
from neurova.api.endpoints import set_app_state  # noqa: E402

failures: list[str] = []

USER_A = {"user_id": "u-alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}

AGENT_ID = "kai"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _StreamingStubAgent:
    """在被调用的那一刻记录两条通道的读数，并把回合交给**生产写盘路径**落盘。

    落盘不自己拼 `user_id=`：`MemCore.save_to_session()` 才是那行的作者（`:1425`），
    脚本替它写就等于把被审对象换成了自己的复制品。

    `user_input` 收位置参：console 与 `/ws` 都是按位置传的，只声明关键字会在替身里
    TypeError，再被端点自己的 catch-all 吞成 `Echo:` ——读不到数却照样 200（假绿）。
    """

    def __init__(self, session_manager=None):
        self.session_manager = session_manager
        self.seen: list[dict] = []
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id="u-alice",
                                      llm_model="test-model")

    async def chat(self, user_input=None, *, session_id=None, metadata=None,
                   stream=False, **kw):
        from neurova.core.identity_context import get_request_user_id
        from neurova.mem_core import MemCore

        self.seen.append({
            "stream": stream,
            "meta_user_id": (metadata or {}).get("user_id"),
            "request_channel": get_request_user_id(),
        })
        if self.session_manager is not None:
            MemCore(self).save_to_session(user_input or "", "好的", session_id=session_id,
                                          metadata=metadata)
        emitter = (metadata or {}).get("event_emitter")
        if callable(emitter):
            emitter("content", {"type": "content", "content": "好的"})
        return {"success": True, "text": "好的", "response": "好的"}


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    # SessionManager 是 DCL 单例：构造参数只在首次生效，落点必须在任何生产路径
    # 碰到它之前定下，并且**当场核对它真的落在隔离根下**——否则 [5] 读的是别的目录，
    # 整格结论无效（写侧与读侧不同源会造出稳定的假结果）。
    from neurova.session_manager import SessionManager

    sm = SessionManager()
    sessionsDir = Path(getattr(sm, "_sessions_dir", Path("."))).resolve()
    check("[S] 会话落点确实在隔离数据根内（[5] 的读写同源）",
          str(sessionsDir).startswith(str(Path(WORK_ROOT).resolve())), str(sessionsDir))

    agent = _StreamingStubAgent(sm)
    set_app_state({"agents": {AGENT_ID: agent}})

    app = FastAPI()
    # 端点是 `@router.post("")` / `@router.post("/stream")`，前缀必须挂到 /chat 这一层
    app.include_router(chat_ep.router, prefix="/api/v1/chat")
    app.dependency_overrides[auth_u] = lambda: dict(USER_A)

    with TestClient(app, raise_server_exceptions=False) as client:
        # ── [0][1][2] 流式回合内两条通道都是登录用户 ──────────────────
        resp = client.post("/api/v1/chat/stream",
                           json={"message": "你好", "agent_id": AGENT_ID,
                                 "session_id": "sess-stream-1"})
        check("[0] 流式端点真的跑完一轮（非 4xx/5xx 且无异常）",
              resp.status_code == 200 and bool(agent.seen),
              f"{resp.status_code} 记录={len(agent.seen)}")
        got = agent.seen[-1] if agent.seen else {}
        check("[1] 流式 metadata['user_id'] ＝ 登录用户",
              got.get("meta_user_id") == "u-alice", str(got))
        check("[2] 流式回合内请求通道 ＝ 同一人（save_to_session 读的就是这条）",
              got.get("request_channel") == "u-alice", str(got.get("request_channel")))

        # ── [3] 客户端自报的身份不得作数 ──────────────────────────────
        resp = client.post("/api/v1/chat/stream",
                           json={"message": "冒充一下", "agent_id": AGENT_ID,
                                 "session_id": "sess-stream-2",
                                 "metadata": {"user_id": "u-victim"}})
        got3 = agent.seen[-1] if agent.seen else {}
        check("[3] 报文自报 metadata.user_id 被服务端覆盖",
              resp.status_code == 200 and got3.get("meta_user_id") == "u-alice", str(got3))

        # ── [4] 非流式同样两条通道一致（防只修一半）───────────────────
        resp = client.post("/api/v1/chat",
                           json={"message": "非流式", "agent_id": AGENT_ID,
                                 "session_id": "sess-direct-1"})
        got4 = agent.seen[-1] if agent.seen else {}
        check("[4] 非流式回合内两条通道也同为登录用户",
              resp.status_code == 200 and got4.get("meta_user_id") == "u-alice"
              and got4.get("request_channel") == "u-alice", str(got4))

    # ── [5] 落盘归属真生效：别人的列表看不见，本人的看得见 ────────────
    owners = {s["session_id"]: s.get("user_id") for s in sm.list_sessions(agent_id=AGENT_ID)}
    check("[5a] 生产写盘路径把流式会话的属主落成了登录用户",
          owners.get("sess-stream-1") == "u-alice", str(owners))

    mine = [s["session_id"] for s in sm.list_sessions(agent_id=AGENT_ID, user_id="u-alice")]
    others = [s["session_id"] for s in sm.list_sessions(agent_id=AGENT_ID, user_id="u-bob")]
    check("[5b] 本人列表能看见自己的流式会话", "sess-stream-1" in mine, str(mine))
    check("[5c] 别人的列表看不见它（修复前：空属主会话对全员可见）",
          "sess-stream-1" not in others, f"以 u-bob 身份看到 {others}")

    # 反向对照：空属主确实对任何人可见——[5c] 不是恒真，而是"这次写了属主"的结果
    sm.add_message(agent_id=AGENT_ID, session_id="sess-legacy-empty",
                   user_content="旧数据", assistant_content="…", user_id="")
    legacyForBob = [s["session_id"] for s in sm.list_sessions(agent_id=AGENT_ID, user_id="u-bob")]
    check("[5d] 反向对照成立：空属主会话确实对任何人可见（所以 [5c] 有牙）",
          "sess-legacy-empty" in legacyForBob, str(legacyForBob))

    # ── [6] console 那条面（批 9 删双写时漏掉的命中点；教义第 5 条扫荡）──
    # 不落盘（`session_manager=None`）：网页那条路的落盘发生在真管线的
    # `_step_save_session` 里，替身跑不到那一步。这里审的是**边界有没有建立请求级属主**——
    # 读数取在 `agent.chat` 被调的那一刻，也就是管线随后读它的那一刻。
    from neurova.api.auth import create_access_token
    from neurova.api.deps import get_current_user as depsUser
    from neurova.api.endpoints import console as console_ep

    consoleAgent = _StreamingStubAgent()
    console_ep.get_agent_instance = lambda agent_id="": consoleAgent
    capp = FastAPI()
    capp.include_router(console_ep.router, prefix="/api/v1/console")
    capp.dependency_overrides[depsUser] = lambda: dict(USER_A)
    capp.dependency_overrides[auth_u] = lambda: dict(USER_A)

    with TestClient(capp, raise_server_exceptions=False) as cclient:
        resp = cclient.post("/api/v1/console/chat",
                            json={"message": "网页一枪", "agent_id": AGENT_ID,
                                  "session_id": "console-live-1", "stream": True})
        got6 = consoleAgent.seen[-1] if consoleAgent.seen else {}
        check("[6a] 网页 /console/chat 回合内请求通道 ＝ 登录用户（批 9 漏的那一处）",
              resp.status_code == 200 and got6.get("request_channel") == "u-alice",
              f"{resp.status_code} {got6}")

        token = create_access_token({"sub": "u-alice", "username": "alice", "role": "user"})
        with cclient.websocket_connect(f"/api/v1/console/ws/c1?token={token}") as ws:
            ws.send_json({"type": "chat", "message": "ws 一枪", "session_id": "ws-live-1"})
            replyEvent = ws.receive_json()
        got6b = consoleAgent.seen[-1] if consoleAgent.seen else {}
        check("[6b] /console/ws 带真 token 的回合内请求通道 ＝ 同一人",
              replyEvent.get("type") == "chat_reply"
              and got6b.get("request_channel") == "u-alice", f"{replyEvent} {got6b}")

        seenBeforeBad = len(consoleAgent.seen)
        try:
            with cclient.websocket_connect("/api/v1/console/ws/c2?token=not-a-jwt") as ws:
                ws.send_json({"type": "chat", "message": "冒充"})
                ws.receive_json()
            refused = False
            code = None
        except Exception as exc:  # noqa: BLE001 - 这里要的就是"被拒"这一形
            refused = getattr(exc, "code", None) == 4401
            code = getattr(exc, "code", None)
        check("[6c] 无效 token 仍被 4401 拒、且不跑回合（补属主没把闸放宽成「匿名即有人」）",
              refused and len(consoleAgent.seen) == seenBeforeBad, f"code={code}")

    capp.dependency_overrides.clear()
    app.dependency_overrides.clear()
    set_app_state(None)

    print()
    if failures:
        print("LIVE-VERIFY FAILED / 批 12 流式会话属主：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / 工单 2026-10-11 批 12（流式对话按登录用户归属）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
