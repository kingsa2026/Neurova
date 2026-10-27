"""红绿灯 TDD：控制台流式回合的两条契约——断连不杀后台轮、开局即知会话归属。

动机来自 2026-10-26 的真浏览器复现（不是推测）：发一轮长回答，中途刷新页面，
读回来的只有用户那一句；`/console/chat/runs` 里这条 run 的终态是
`cancelled` + `error_type=stopped`，`finished_at` 恰好是断连那一刻，会话文件里
assistant 一条都没有（复算时距断连已过 6 分钟，不是"还没写完"）。
票面症状「刷新后看不到 agent 持续的输出」因此不止是"读不回"——
**这一轮在断连时就被取消了**，后台根本没有"持续输出"可读回。

取消的传播路径（同批用最小 asyncio 样本复算过两种形态）：`event_stream()` 的
收尾块 `finally: result = await task`。客户端断连时被取消的是响应任务，而
`await 子任务` 会把这份取消沿等待链带进被等待的 `run_chat`；紧邻其下的分支注释
「生成器自身被取消（客户端断连）而非任务取消——保持原语义」因此永远走不到。
语义要保住，等待就得脱钩：`asyncio.shield` 只护住"我在等的这一件"不被我的取消带走。

第二条契约同源于那次复现：会话 id 只在 `done` 帧回传（前端
`if (!currentSessionId.value && event.session_id)` 才认领），于是首轮流式期间
前端手里仍是空。补课 8 的断线重连据此以空 `session_id` 重新 POST，服务端按
"没带会话"另行 `create_session` ——实测落出一个 0 消息的空会话 `44779684`，
与真正在跑的 `e41ff42c` 各说各话，那一轮还被让位闸挂起、无人可读。
分配权仍在服务端（`useChat.createSession` 那条"前端不自行 mint id、避免前后端
id 漂移"的既有裁定不动），但**分配发生的当场就该告知客户端**，而不是等回合结束。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
import typing

import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from neurova.api.endpoints import console as console_module
from neurova.core import agent_run_store as ars


@pytest.fixture()
def quietStack(tmp_path, monkeypatch):
    """闸旁路 + 台账落临时库。

    让位闸按实时 pacer 读数会等到 40s 量级（本批复现时它就是那么挂起的），
    判据等不起；`NEUROVA_RUN_GATE=off` 是仓内既有的应急旁路口，不是为测试新造的形态。
    """
    monkeypatch.setenv("NEUROVA_RUN_GATE", "off")
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "ledger.db"))
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(tmp_path / "ledger.db")
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


def _make_request() -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "headers": [(b"content-type", b"application/json")],
    }
    return Request(scope, receive=receive)


CURRENT_USER = {"user_id": "u1", "tenant_id": "default", "role": "admin"}


class FakeRepo:
    def __init__(self) -> None:
        self.created: typing.List[str] = []

    def create_session(self, agent_id="", user_id="", title="新对话", config=None):
        sid = f"srv-{len(self.created)}"
        self.created.append(sid)
        return sid


class SlowAgent:
    """第一帧立刻出，之后仍在逐字产出——用来量"断连时这一轮是否还活着"。"""

    def __init__(self) -> None:
        self.completed = False
        self.cancel_seen = False
        self.chat_kwargs: typing.Optional[dict] = None

    async def chat(self, message, **kwargs):
        self.chat_kwargs = kwargs
        emitter = (kwargs.get("metadata") or {}).get("event_emitter")
        if emitter:
            emitter("reasoning", "开头一段")
        try:
            await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            self.cancel_seen = True
            raise
        self.completed = True
        return {"text": "收尾正文", "reasoning": "开头一段", "tool_messages": []}


def _patch(monkeypatch, agent, repo: typing.Optional[FakeRepo] = None) -> FakeRepo:
    repo = repo or FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request, current_user=None: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id: agent)
    return repo


def _events_from(chunk: typing.Any) -> typing.List[dict]:
    out: typing.List[dict] = []
    for line in str(chunk).splitlines():
        line = line.strip()
        if line.startswith("data:"):
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line[len("data:"):].strip()))
    return out


# ---------------------------------------------------------------------------
# 契约一：客户端断连只停"投递"，不停"这一轮"
# ---------------------------------------------------------------------------


def test_disconnect_midTurn_stopsDeliveryButNotExecution(quietStack, monkeypatch):
    """真 ASGI 栈（含全套 BaseHTTPMiddleware）上断连：投递停，执行不停。

    取舍：先前用「直接调端点函数 + 掐掉消费任务」的形态量过，那条路径量不出故障
    ——生产上的取消是中间件栈的 anyio 作用域随响应结束撤走时才落到这一轮的。
    判据因此走 `TestClient` 的真 ASGI 栈，与那次真浏览器复现同一形态（客户端读到
    开头两帧就关连接），断连后只看一件事：这一轮自己跑完了没有。
    """
    agent = SlowAgent()
    repo = FakeRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request, current_user=None: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id: agent)

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.deps import get_current_user

    app = create_app(enable_memory=False, enable_channels=False)
    app.dependency_overrides[get_current_user] = lambda: dict(CURRENT_USER)
    client = TestClient(app)
    with client.stream(
        "POST",
        "/api/v1/console/chat",
        json={"agent_id": "default", "session_id": "s1", "message": "你好", "stream": True},
    ) as resp:
        read = 0
        for _ in resp.iter_lines():
            read += 1
            if read >= 2:
                break  # 离开 with ＝ 客户端关连接（刷新/掉线）
    assert read >= 2, f"只读到 {read} 帧，场景没跑起来"

    deadline = time.monotonic() + 8.0
    while not agent.completed and not agent.cancel_seen and time.monotonic() < deadline:
        time.sleep(0.05)

    assert agent.cancel_seen is False, (
        "客户端断连把后台回合一起取消了（取消沿响应任务的等待链落进 run_chat）——"
        "断连应只停投递，不停执行"
    )
    assert agent.completed is True, "断连后这一轮没有自己跑完，后台无输出可读回"


# ---------------------------------------------------------------------------
# 契约二：分配发生当场就告知会话归属
# ---------------------------------------------------------------------------


def test_streamAnnouncesSessionIdBeforeTurnFinishes(quietStack, monkeypatch):
    agent = SlowAgent()
    repo = _patch(monkeypatch, agent)
    # 不带 session_id：由服务端当场分配
    body = console_module.ChatRequest(message="你好", stream=True)

    async def scenario() -> typing.List[dict]:
        resp = await console_module.post_console_chat(body, _make_request(), current_user=CURRENT_USER)
        events: typing.List[dict] = []
        it = resp.body_iterator.__aiter__()
        while True:
            try:
                chunk = await it.__anext__()
            except StopAsyncIteration:
                break
            events.extend(_events_from(chunk))
            if events and events[0].get("session_id"):
                break
        with contextlib.suppress(BaseException):
            await it.aclose()
        return events

    events = asyncio.run(scenario())
    announced = [e for e in events if e.get("session_id")]
    assert announced, f"回合结束前没有任何一帧告知 session_id：{[e.get('type') for e in events]}"
    first = announced[0]
    assert first.get("type") != "done", (
        f"session_id 只在 done 帧回传（type={first.get('type')}），"
        "首轮流式期间前端手里是空——断线重连会另行 create_session"
    )
    assert repo.created, "服务端并未分配会话 id，判据落空"
    assert first.get("session_id") == repo.created[0]


def test_announcedSessionFrameDoesNotLeakIntoTimelineOrReplayBuffer(quietStack, monkeypatch):
    """开局帧是传输层的"这一轮属于哪个会话"，不是会话内容。

    反向钉住：它不得进断线重连缓冲，也不得进会话时间线——否则重放会把它当
    业务事件再消费一遍，时间线里也多出一条不属于任何回合的记录。
    """
    agent = SlowAgent()
    _patch(monkeypatch, agent)
    body = console_module.ChatRequest(message="你好", session_id="s-frame", stream=True)

    async def scenario() -> dict:
        resp = await console_module.post_console_chat(body, _make_request(), current_user=CURRENT_USER)
        async for _ in resp.body_iterator:
            pass
        buf = console_module._replay_buffers.get("s-frame")
        return {"buffered": [ev.get("type") for _, ev in (buf or {}).get("events", [])]}

    got = asyncio.run(scenario())
    assert "session" not in got["buffered"], (
        f"开局 session 帧进了断线重连缓冲，重放会重复投递：{got['buffered']}"
    )


def test_consoleCleanupDoesNotAwaitTheTurnTaskAtAll():
    """结构判据：响应生成器不得等待回合任务——无论裸 await 还是 shield 包裹。

    第一版（`a48f815b`）把裸 `await task` 改成 `await asyncio.shield(task)`，
    那只解决"取消别带走这一轮"，但回合的**收尾记账**（时间线／重放缓冲／done／
    续租）当时仍长在生成器的 finally 里：客户端一走，四件一起停——实测断连 164s
    后任务还活着（`chat@164s`）而 run 已被扫成 `failed/process_died`，且
    `_timeline/e41ff42c.jsonl` 的写入停在断连那一秒。第 0 步把四件搬到生产侧后，
    生成器连"等"这个动作都不该有：等 = 回合寿命还系在响应上。
    """
    import ast
    import pathlib

    src = pathlib.Path("neurova/api/endpoints/console.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != "event_stream":
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Try) or not sub.finalbody:
                continue
            for stmt in ast.walk(sub):
                if isinstance(stmt, ast.Await) and isinstance(stmt.value, ast.Name)                         and stmt.value.id == "task":
                    offenders.append(stmt.lineno)
    assert offenders == [], f"收尾处裸 await 后台轮任务（行 {offenders}）：断连会把它一起取消"
    shielded = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "event_stream"
        for sub in ast.walk(n)
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "shield"
    ]
    assert shielded == [], (
        f"event_stream 仍在等待回合任务（shield 于行 {[n.lineno for n in shielded]}）——"
        "收尾记账应系在生产侧 run_chat，不该由响应去等"
    )
