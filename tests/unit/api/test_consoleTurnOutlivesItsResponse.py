"""红绿灯 TDD：回合的落地与续租要跟着**回合**走，不跟着**响应**走。

动机由两笔连出来的实测事实构成，不是推测：

1. 上一批（`a48f815b`）把 console 收尾的 `await task` 改成 `asyncio.shield(task)`，
   客户端断连不再掀掉后台那一轮——这是票面要的取向。但复算活体读数时发现，
   **回合的租约续期与事件落地都长在响应生成器身上**：生成器一被撤走，
   `ledger.heartbeat()` 就停、`_record_timeline(...)` 就停、`buf["done"]` 再没人置。
2. 于是当场量到一条谎报：断连后 `GET /console/tasks` 显示那条 asyncio 任务仍在跑
   （`chat@164s`），而 run 台账已被周期扫描写成 **`failed/process_died`**
   （`reconcile_stale` 只认 `lease_expires_at` 过没过期）。台账说"进程死了"，进程
   活得好好的——这是上一条修法的直接副作用，不修就等于把「持久台账」变成会说谎的事实源。

本批把三件事从响应生成器搬到生产侧单点（sink），各落一条判据：

- **续租跟着回合**：断连后仍活着的一轮，不得被扫描判成死。
- **时间线跟着回合**：断连之后新产生的事件仍要落进会话时间线（那是刷新读回的源；
  不落的后果是"回合跑完了但增量永久缺一截"）。
- **收尾信号跟着回合**：`buf["done"]` 由**这一轮结束**置位，而不是由"投递者还在"
  置位。今天它只在生成器正常收尾路径里写 ⇒ 断连过的那一轮，带 `replay_from` 的重连
  会永远尾随一个不会被置位的标志（P-6 那一族「永不返回的 await」）。

断连的注入形态用 `athrow(CancelledError)`——那正是响应任务被取消时，生成器当前
await 处收到的东西。`aclose()` 量不出来：GeneratorExit 下 finally 里的 `await` 会把
子任务**等完**，收尾照做，等于没断连。
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

CURRENT_USER = {"user_id": "u1", "tenant_id": "default", "role": "admin"}


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


class SteadyRepo:
    """假会话仓：记 id，并把时间线追加记成可读数。

    端点写时间线走的就是 `get_session_repository().append_timeline_event(...)`
    （`console.py` 里 getattr 出来的那一个），所以这里记到几条 == 端点真调用了几次；
    磁盘层另由 `SessionManager` 自己的判据覆盖，不在本档重复量。
    """

    def __init__(self) -> None:
        self.created: typing.List[str] = []
        self.timeline: typing.List[dict] = []

    def create_session(self, agent_id="", user_id="", title="新对话", config=None):
        sid = f"srv-{len(self.created)}"
        self.created.append(sid)
        return sid

    def append_timeline_event(self, agent_id: str, session_id: str, event: dict) -> bool:
        self.timeline.append(dict(event or {}))
        return True


class StagedAgent:
    """分段发事件，段间留足够长的间隔——好让"断连之后还在发"这件事被测得出来。"""

    def __init__(self, gap: float = 0.45, tail: float = 0.9, pieces: int = 3):
        self.gap = gap
        self.tail = tail
        self.pieces = pieces
        self.emitted = 0
        self.completed = False
        self.cancel_seen = False

    async def chat(self, message, **kwargs):
        emitter = (kwargs.get("metadata") or {}).get("event_emitter")
        try:
            for i in range(self.pieces):
                self.emitted += 1
                if emitter:
                    emitter("content", f"片段{i}")
                await asyncio.sleep(self.gap)
            await asyncio.sleep(self.tail)
        except asyncio.CancelledError:
            self.cancel_seen = True
            raise
        self.completed = True
        return {"text": f"片段{self.pieces - 1}", "reasoning": None, "tool_messages": []}


@pytest.fixture()
def shortLeaseStack(tmp_path, monkeypatch):
    """闸开（台账要真落库）＋租约压到 1s＋台账落临时库。

    租约默认 90s、扫描间隔 = 租约/3，判据等不起；压短是仓内既有做法
    （`test_console_run_ledger.py` 同形）。落 tmp_path，不碰开发库。
    """
    monkeypatch.setenv("NEUROVA_RUN_GATE", "on")
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "ledger.db"))
    ars.reset_agent_run_store()
    store = ars.AgentRunStore(tmp_path / "ledger.db", lease_seconds=1.0)
    monkeypatch.setattr(ars, "_store", store)
    yield store
    ars.reset_agent_run_store()


def _patch(monkeypatch, agent) -> SteadyRepo:
    repo = SteadyRepo()
    monkeypatch.setattr(console_module, "_get_user_id", lambda request, current_user=None: "u1")
    monkeypatch.setattr(console_module, "get_session_repository", lambda: repo)
    monkeypatch.setattr(console_module, "get_agent_instance", lambda agent_id: agent)
    return repo


async def _open_and_abandon(body) -> bool:
    """开流：等到**管线真的在发事件**那一帧，再把这轮"断连"打进生成器。

    必须等到 chunk 帧而不是随便一帧：台账 intake 的 `queued` 帧在
    `create_task(run_chat())` **之前**就 yield 出来了，在那儿断连等于这轮从没开始，
    判据会退化成"前置不成立"（本档初版就栽在这里，如实留在此处）。
    """
    resp = await console_module.post_console_chat(body, _make_request(), current_user=CURRENT_USER)
    assert isinstance(resp, StreamingResponse), f"未走流式分支：{type(resp).__name__}"
    it = resp.body_iterator.__aiter__()
    seen_chunk = False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        try:
            chunk = await it.__anext__()
        except BaseException:
            break
        if '"type": "chunk"' in str(chunk) or '"type":"chunk"' in str(chunk):
            seen_chunk = True
            break
    with contextlib.suppress(BaseException):
        await it.athrow(asyncio.CancelledError())
    return seen_chunk


async def _wait_until(done: typing.Callable[[], bool], seconds: float = 12.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done():
            return True
        await asyncio.sleep(0.1)
    return done()


# ---------------------------------------------------------------------------
# 一、续租跟着回合：还活着的一轮不得被扫描判成进程死了
# ---------------------------------------------------------------------------


def test_detachedTurn_keepsItsLeaseAlive():
    """续租的驱动者必须是回合自己，不是响应生成器（结构判据）。

    行为判据在这一格给不出来，两种注入形态都试过并如实留名：
    ① `athrow(CancelledError)`——收尾 finally 拆掉后它仍要等整轮跑完才返回，
       取样时刻早已过去（两次同读数）；
    ② 取到第一帧就不再消费——`create_task(run_chat())` 长在生成器体内，投递者一停，
       这一轮连被创建的机会都没有。②本身就是要登记的新边界：**回合是否存在，
       取决于有没有人在读**（§6-421）。
    行为的红→绿证据落在活体 A/B（本档头部那组读数：断连 164s 任务仍 `chat@164s`，
    而 run 已被周期扫描写成 `failed/process_died`）。本格只钉"驱动者归位"。
    """
    import ast
    import pathlib

    srcTxt = pathlib.Path("neurova/api/endpoints/console.py").read_text(encoding="utf-8")
    tree = ast.parse(srcTxt)

    def _fn(name):
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
                return node
        return None

    assert _fn("_keepLease") is not None, "租约续期没收成一处的实装（`_keepLease` 不在）"
    runner = _fn("run_chat")
    assert runner is not None, "回合执行体 `run_chat` 不在"
    spawned = [
        n for n in ast.walk(runner)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "create_task"
        and n.args and isinstance(n.args[0], ast.Call)
        and getattr(n.args[0].func, "id", "") == "_keepLease"
    ]
    assert spawned, "续租任务不是由回合自己创建并持有的（应挂在 run_chat 上）"

    delivery = _fn("event_stream")
    if delivery is not None:
        # 只看投递循环本身：`_keepLease` 是嵌在 event_stream 里的合法续租源，
        # 但它下面的 While 不能算进"投递段又自己续租"。
        def _outer_bodies(node):
            out = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue  # 嵌套实装各自归位，不在投递段的账上
                out.append(child)
            return out

        loops = [n for w in _outer_bodies(delivery) for n in ast.walk(w) if isinstance(n, ast.While)]
        for w in loops:
            for call in [s for s in ast.walk(w) if isinstance(s, ast.Call)
                         and getattr(s.func, "attr", "") == "heartbeat"]:
                pytest.fail(
                    f"投递循环里出现续租调用（行 {call.lineno}）——续租又系回响应上了，"
                    "唯一驱动者应是 `run_chat` 创建的 `_keepLease`"
                )

# ---------------------------------------------------------------------------
# 二、时间线跟着回合：断连之后新产生的事件仍要落盘
# ---------------------------------------------------------------------------


def test_detachedTurn_keepsAppendingTimeline(shortLeaseStack, monkeypatch):
    agent = StagedAgent(gap=0.4, pieces=5, tail=0.5)
    repo = _patch(monkeypatch, agent)
    body = console_module.ChatRequest(message="你好", session_id="s-tl", stream=True)

    async def scenario() -> dict:
        started = await _open_and_abandon(body)
        assert started, "生成器没等到 chunk 帧，场景没跑起来"
        done = await _wait_until(lambda: agent.completed)
        return {"done": done, "types": [str(e.get("type")) for e in repo.timeline]}

    got = asyncio.run(scenario())
    assert got["done"] is True, "那一轮没跑完，本判据的前置不成立"
    chunks = [t for t in got["types"] if t == "chunk"]
    assert len(chunks) >= 3, (
        f"断连后新产生的增量没有落进时间线（实得 {got['types']}）——"
        "刷新读回的源就此永久缺一截，只剩断连之前的那半"
    )


# ---------------------------------------------------------------------------
# 三、收尾信号跟着回合：done 由这一轮结束置位，重连才不会无限尾随
# ---------------------------------------------------------------------------


def test_replayReconnect_terminatesAfterDetachedTurnEnds(shortLeaseStack, monkeypatch):
    agent = StagedAgent(gap=0.35, pieces=3, tail=0.5)
    _patch(monkeypatch, agent)
    body = console_module.ChatRequest(message="你好", session_id="s-tail", stream=True)
    replay_body = console_module.ChatRequest(
        message="你好", session_id="s-tail", stream=True, replay_from=0
    )

    async def scenario() -> dict:
        started = await _open_and_abandon(body)
        assert started, "生成器没等到 chunk 帧，场景没跑起来"
        done = await _wait_until(lambda: agent.completed)
        buf = console_module._replay_buffers.get("s-tail")
        marked = bool(buf and buf.get("done"))
        got: typing.List[str] = []
        resp = await console_module.post_console_chat(
            replay_body, _make_request(), current_user=CURRENT_USER
        )

        async def drain() -> None:
            async for chunk in resp.body_iterator:
                for line in str(chunk).splitlines():
                    line = line.strip()
                    if line.startswith("data:"):
                        got.append(str(json.loads(line[5:].strip()).get("type")))

        hung = False
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(drain(), timeout=2.5)
        if not got or got[-1] != "done":
            hung = True
        return {"marked": marked, "got": got, "hung": hung, "turnDone": done}

    out = asyncio.run(scenario())
    assert out["marked"] is True, (
        "那一轮已经跑完，重放缓冲的 done 却没被置位——置位长在投递者身上，"
        "投递者断连过就再没人置"
    )
    assert out["hung"] is False, (
        f"带 replay_from 的重连没有正常收尾（已收到 {out['got']}）——它在尾随一个永不置位的 "
        "done，属 P-6 那一族「永不返回的 await」，每重连一次就泄一条挂住的响应任务"
    )
