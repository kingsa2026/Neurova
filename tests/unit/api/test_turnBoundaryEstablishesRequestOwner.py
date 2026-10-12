# -*- coding: utf-8 -*-
"""§6-153（工单 2026-10-11 批 12，裁定甲 + 教义第 5 条扫荡）：跑回合的入口都得上报属主。

## 两件事同批，因为是同一条链上的同一个缺口

1. **流式 `/v1/chat/stream`**：既不写 `call_metadata["user_id"]`，也不设请求通道，而非流式
   `/chat` 两处都写。于是流式回合里 `mem_core.save_to_session:1425` 的 `get_request_user_id()`
   取到空串，而 `session_manager.py:1650` 的过滤口径是「空属主**不过滤**」——结果不是
   "这条会话没属主"，而是 **它出现在每一个登录用户的会话列表里**（标题、时间、条数全见）。
2. **网页 console 那条面（批 9 自己漏的命中点）**：批 9 按乙案删掉管线里"每轮按
   `metadata['user_id']` 补写通道"的双写时，只在 `api/endpoints/chat.py` 补了边界写点，
   `api/endpoints/console.py` 没补——网页回合里这条通道从此为空：usage 入账落
   `"anonymous"`（`multi_model_client:876/1156`）、按日 LLM 配额整条不判（`:1426` 无身份即放行）、
   客户端自带全新 session_id 时会话落空属主。`/ws/{client_id}` 是同一条链上更早的一处
   （它验了 token 却只把 `sub` 拼进连接键，从不建立属主）。**判据当时一条都没红**——
   它只审已登记的入口，而漏的是"没登记的那一行"，所以本文件除行为格外还带一格按形状
   自己数入口的覆盖面（见 `test_requestUserIdEntryConsistency.py` 的 ⑤）。

## 为什么判据要落在 HTTP 栈而不是只看 AST

写点的位置在这里是**语义**的一部分：`create_task` 在创建时复制当前上下文，所以
`set_request_user_id()` 必须发生在 `asyncio.create_task(run_chat())` **之前**、且在
`event_generator`/`event_stream` 那条执行链上——把它"顺手提到端点函数开头"看着更整齐，实则
生成器被恢复时的上下文未必带着那次写入，修复当场退化成死码。行为格走真 TestClient
（属主由生产写盘路径算出），形态格按 AST 比对两处行号并自带变异对照。
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import create_access_token, get_current_user as authStrict
from neurova.api.deps import get_current_user as depsUser
from neurova.api.endpoints import chat as chat_ep
from neurova.api.endpoints import console as console_ep
from neurova.session_manager import SessionManager

_REPO = Path(__file__).resolve().parents[3]
AGENT_ID = "stream-owner-agent"
ALICE = "u-alice"
BOB = "u-bob"


class _OwnerRecordingAgent:
    """记录被调那一刻的通道读数与载体读数，并把回合交给**生产写盘路径**落盘。

    不在测试里自己拼属主：`post_chat_pipeline.resolveSessionOwner` + `MemCore.save_to_session()`
    才是那两行的作者，替它们写就等于把被审对象换成自己的复制品（判据会恒绿）。

    `user_input` 收位置参：`console.py:826` 与 `/ws`(:2106) 都是按位置传的，
    只声明关键字会在替身里 TypeError 被端点的 catch-all 吞成 `Echo:` —— 那就是假绿。
    """

    def __init__(self, session_manager=None) -> None:
        self.session_manager = session_manager
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=ALICE,
                                      llm_model="test-model")
        self.turns: List[Dict[str, Any]] = []

    async def chat(self, user_input=None, *, session_id=None, metadata=None,
                   stream: bool = False, **kw):
        from neurova.core.identity_context import get_request_user_id
        from neurova.mem_core import MemCore

        self.turns.append({
            "stream": stream,
            "meta_user_id": (metadata or {}).get("user_id"),
            "request_channel": get_request_user_id(),
        })
        if self.session_manager is not None:
            # 属主由**生产那一个取法函数**给出（`resolveSessionOwner`，§6-163）：测试自己拼
            # `user_id=` 就等于把被审的那一行换成复制品，判据会绿得没有意义。
            from neurova.mem_core import MemCore
            from neurova.post_chat_pipeline import resolveSessionOwner

            MemCore(self).save_to_session(user_input or "", "好的", session_id=session_id,
                                          metadata=metadata,
                                          session_owner=resolveSessionOwner(metadata))
        emitter = (metadata or {}).get("event_emitter")
        if callable(emitter):
            emitter("content", {"type": "content", "content": "好的"})
        return {"text": "好的", "tool_messages": [], "reasoning": ""}


@pytest.fixture()
def ownerClient(tmp_path, monkeypatch):
    """最小装配：只挂 chat 路由 + 严格鉴权覆盖为 alice，会话落点由根 conftest 隔离。"""
    agent = _OwnerRecordingAgent(SessionManager())
    monkeypatch.setattr(chat_ep, "_get_agent", lambda agent_id="": agent)

    app = FastAPI()
    # 端点是 @router.post("") / @router.post("/stream")：前缀必须挂到 /chat 这一层
    app.include_router(chat_ep.router, prefix="/api/v1/chat")
    identity = {"user_id": ALICE, "username": ALICE, "role": "user"}
    app.dependency_overrides[authStrict] = lambda: dict(identity)
    app.dependency_overrides[depsUser] = lambda: dict(identity)
    return TestClient(app, raise_server_exceptions=False), agent


def _postStream(client, *, message: str, session_id: str,
                metadata: Optional[Dict[str, Any]] = None):
    payload: Dict[str, Any] = {"message": message, "agent_id": AGENT_ID,
                               "session_id": session_id}
    if metadata:
        payload["metadata"] = metadata
    return client.post("/api/v1/chat/stream", json=payload)


class TestStreamTurnCarriesTheAuthenticatedOwner:
    def test_streamPassesLoggedInUserIntoBothIdentityChannels(self, ownerClient):
        client, agent = ownerClient
        resp = _postStream(client, message="你好", session_id="sess-stream-1")

        assert resp.status_code == 200, resp.text
        assert len(agent.turns) == 1, "流式回合根本没打到 agent，下面的断言是空转"
        turn = agent.turns[0]
        assert turn["stream"] is True, "流式端点没把 stream=True 传给 agent"
        assert turn["meta_user_id"] == ALICE, (
            f"流式回合的 metadata['user_id'] 是 {turn['meta_user_id']!r}——"
            "管线与技能据此归属条目，缺它即匿名"
        )
        assert turn["request_channel"] == ALICE, (
            "请求通道在流式回合里为空 ⇒ save_to_session 落空属主，"
            "而空属主会话对**所有**登录用户可见（这格是修复前实测的红）"
        )

    def test_clientSuppliedUserIdIsOverriddenByTheServer(self, ownerClient):
        """报文自带 `metadata.user_id` 不得作数——否则外部可指定"这条会话算谁的"。"""
        client, agent = ownerClient
        resp = _postStream(client, message="冒充一下", session_id="sess-stream-2",
                           metadata={"user_id": BOB})

        assert resp.status_code == 200, resp.text
        assert agent.turns[-1]["meta_user_id"] == ALICE, (
            f"客户端自报的 user_id 被采纳了：{agent.turns[-1]}"
        )

    def test_nonStreamPathKeepsTheSameTwoReadings(self, ownerClient):
        """防"只修流式、把非流式改坏"：`/chat` 那两条读数必须同样成立。"""
        client, agent = ownerClient
        resp = client.post("/api/v1/chat",
                           json={"message": "非流式", "agent_id": AGENT_ID,
                                 "session_id": "sess-direct-1"})

        assert resp.status_code == 200, resp.text
        turn = agent.turns[-1]
        assert turn["meta_user_id"] == ALICE and turn["request_channel"] == ALICE, (
            f"非流式侧的归属读数分叉：{turn}"
        )

    def testSessionLandsUnderTheOwnerAndIsInvisibleToOthers(self, ownerClient):
        """落盘后必须真的按属主隔离——「字段写了但没人读」不算修好。"""
        client, agent = ownerClient
        assert _postStream(client, message="你好", session_id="sess-stream-1").status_code == 200

        manager = agent.session_manager
        owners = {s["session_id"]: s.get("user_id") for s in manager.list_sessions(agent_id=AGENT_ID)}
        assert owners.get("sess-stream-1") == ALICE, (
            f"生产写盘路径落下的属主不是登录用户：{owners}"
        )
        mine = [s["session_id"] for s in manager.list_sessions(agent_id=AGENT_ID, user_id=ALICE)]
        others = [s["session_id"] for s in manager.list_sessions(agent_id=AGENT_ID, user_id=BOB)]
        assert "sess-stream-1" in mine
        assert "sess-stream-1" not in others, (
            f"以 {BOB} 身份列出了别人的流式会话：{others}"
        )

    def testReverseControlEmptyOwnerIsVisibleToEveryone(self, ownerClient):
        """上一格的牙来自"这次真写了属主"：空属主必须仍然对任何人可见，否则它是恒真。"""
        _client, agent = ownerClient
        manager = agent.session_manager
        manager.add_message(agent_id=AGENT_ID, session_id="sess-legacy-empty",
                            user_content="旧数据", assistant_content="…", user_id="")

        for viewer in (ALICE, BOB):
            visible = [s["session_id"] for s in manager.list_sessions(agent_id=AGENT_ID,
                                                                     user_id=viewer)]
            assert "sess-legacy-empty" in visible, (
                f"空属主会话对 {viewer} 不可见 ⇒ `:1650` 的口径已改，"
                "上一格不再由「写了属主」这一件事决定（判据失去意义，须连同口径一起重写）"
            )


class TestTheWriteSitsWhereTheTaskCanSeeIt:
    """`set_request_user_id` 与 `create_task(run_chat())` 的先后是语义，不是风格。"""

    @staticmethod
    def _orderViolation(source: str) -> str:
        tree = ast.parse(source)
        stream = next((n for n in tree.body
                       if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat_stream"), None)
        if stream is None:
            return "找不到 chat_stream"
        generator = next((n for n in ast.walk(stream)
                          if isinstance(n, ast.AsyncFunctionDef) and n.name == "event_generator"),
                         None)
        if generator is None:
            return "chat_stream 里不再有 event_generator（本格的被审对象已换，须重写）"

        setLine = taskLine = None
        for node in ast.walk(generator):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == "set_request_user_id":
                    setLine = node.lineno if setLine is None else min(setLine, node.lineno)
                elif name == "create_task":
                    taskLine = node.lineno if taskLine is None else min(taskLine, node.lineno)
        if setLine is None:
            return "event_generator 内不再写请求通道（流式回合退回空属主）"
        if taskLine is None:
            return "event_generator 内不再有 create_task（写点与 task 的关系要重新判定）"
        if setLine > taskLine:
            return f"写点（:{setLine}）落在 create_task（:{taskLine}）之后——task 复制的是创建时的上下文"
        return ""

    def testOwnerIsWrittenBeforeTheRunChatTaskIsCreated(self):
        source = (_REPO / "neurova/api/endpoints/chat.py").read_text(encoding="utf-8")
        violation = self._orderViolation(source)
        assert not violation, violation

    def test_theOrderCheckItselfIsNotVacuous(self):
        """变异对照：把写点搬到 create_task 之后，上一格必须红——否则这格从不判事。

        只动 `event_generator` 那一段：`chat.py` 里这句有**两处**（非流式与流式各一），
        不切开就变异到非流式那一处，对照会"假合规"（本仓老坑：锚点命中了别处同名片段）。
        """
        source = (_REPO / "neurova/api/endpoints/chat.py").read_text(encoding="utf-8")
        _head, sep, tail = source.partition("async def event_generator")
        assert sep, "没有 event_generator，本对照的锚点已失效"

        lines = tail.splitlines(keepends=True)

        def _indexOf(needle: str) -> int:
            for i, line in enumerate(lines):
                if needle in line:
                    return i
            return -1

        writeIdx = _indexOf("set_request_user_id(user_id)")
        taskIdx = _indexOf("asyncio.create_task(run_chat())")
        assert writeIdx != -1 and taskIdx != -1, (
            f"生成器内找不到变异锚点（写点 :{writeIdx} / create_task :{taskIdx}）——"
            "本对照的前置已失效，上一格的形态判据也随之空转"
        )
        assert writeIdx < taskIdx, "原样就不是「写点在 create_task 之前」——上一格测的另有其事"

        indent = lines[taskIdx][:len(lines[taskIdx]) - len(lines[taskIdx].lstrip())]
        moved = f"{indent}{lines[writeIdx].strip()}\n"
        rest = lines[:writeIdx] + lines[writeIdx + 1:]
        mutatedTail = "".join(rest[:taskIdx] + [moved] + rest[taskIdx:])

        violation = self._orderViolation(source[:len(source) - len(tail)] + mutatedTail)
        assert violation and "之后" in violation, (
            f"搬到 create_task 之后仍判合规 ⇒ 这格恒真：{violation!r}"
        )


@pytest.fixture()
def consoleClient(monkeypatch):
    """挂 console 路由（REST `/chat` 与 `/ws/{client_id}` 共用这一份装配）。

    这里**不**注入 `session_manager`：网页那条面的落盘由真管线的 `_step_save_session` 负责，
    替身跑不到那一步。本格审的是被批 9 漏掉的那一件事——**边界有没有建立请求级属主**，
    读数取在 `agent.chat` 被调的那一刻，也就是管线随后读它的那一刻。
    """
    agent = _OwnerRecordingAgent()
    monkeypatch.setattr(console_ep, "get_agent_instance", lambda agent_id="": agent)

    app = FastAPI()
    app.include_router(console_ep.router, prefix="/api/v1/console")
    identity = {"user_id": ALICE, "username": ALICE, "role": "user"}
    app.dependency_overrides[depsUser] = lambda: dict(identity)
    app.dependency_overrides[authStrict] = lambda: dict(identity)
    return TestClient(app, raise_server_exceptions=False), agent


class TestConsoleTurnEstablishesTheRequestOwner:
    def test_consoleChatTurnCarriesTheAuthenticatedOwner(self, consoleClient):
        client, agent = consoleClient
        resp = client.post("/api/v1/console/chat",
                           json={"message": "hi", "agent_id": AGENT_ID,
                                 "session_id": "console-1", "stream": True})

        assert resp.status_code == 200, resp.text
        assert agent.turns, "这一轮根本没打到 agent——下面的断言是空转"
        turn = agent.turns[-1]
        assert turn["meta_user_id"] == ALICE, f"console 没把登录用户放进 metadata：{turn}"
        assert turn["request_channel"] == ALICE, (
            "网页回合里请求通道为空（批 9 删掉管线双写后没在 console 边界补上）："
            "usage 入账落 anonymous、按日 LLM 配额整条不判、"
            "客户端自带全新 session_id 时会话落空属主而对全员可见"
        )

    def test_consoleWsTurnCarriesTheAuthenticatedOwner(self, consoleClient):
        """/ws 这条更早的缺口：验了 token 却只把 `sub` 拼进连接键，从不建立属主。"""
        client, agent = consoleClient
        token = create_access_token({"sub": ALICE, "username": ALICE, "role": "user"})

        with client.websocket_connect(f"/api/v1/console/ws/c1?token={token}") as ws:
            ws.send_json({"type": "chat", "message": "hi", "session_id": "ws-1"})
            got = ws.receive_json()

        assert got.get("type") == "chat_reply", got
        assert agent.turns, (
            "WS 回合没打到 agent（reply 是端点 catch-all 造的 Echo 兜底）——"
            "本格的读数与那条兜底一起被吞掉了，须先让替身可见"
        )
        assert agent.turns[-1]["request_channel"] == ALICE, (
            f"WS 回合没建立请求级属主：{agent.turns[-1]}"
        )

    def test_unauthenticatedWsIsRefusedNotDefaulted(self, consoleClient):
        """边界补写属主不许顺手把"没 token"当成"有人"——4401 那条闸必须还在。"""
        client, agent = consoleClient
        # 按具体异常类收口：`pytest.raises(Exception)` 会把"替身装配失败"也算成"被拒"，
        # 于是这道闸的判据能在它根本没判的情况下绿。
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as raised:
            with client.websocket_connect("/api/v1/console/ws/c2?token=not-a-jwt") as ws:
                ws.send_json({"type": "chat", "message": "hi"})
                ws.receive_json()
        assert getattr(raised.value, "code", None) == 4401, (
            f"未带有效 token 的连接不是被 4401 拒掉（实测 code={getattr(raised.value, 'code', None)!r}、"
            f"异常={raised.value!r}）——补属主时把这道闸放宽成'匿名也算有人'就是本格的靶"
        )
        assert agent.turns == [], "未鉴权的连接跑了一轮对话"
