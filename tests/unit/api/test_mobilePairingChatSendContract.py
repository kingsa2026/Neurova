# -*- coding: utf-8 -*-
"""§6-154（工单 2026-10-12 批 17）：移动端 `chat:send` 的调用形状与请求级属主合修。

## 实测到的原缺陷（不是"零消费者"，是"调用必抛"）

`_handle_chat_send:415/423` 两条分支都按 `content=` / `user_id=` 传参：

- `agent.chat_stream(content=…, session_id=…, user_id=…)` —— 真签名是
  `agent_core.py:1768 chat_stream(self, user_input, session_id=None, metadata=None, **kwargs)`，
  `user_input` 没有缺省值 ⇒ **missing 1 required positional argument**；
- `agent.chat(content=…, session_id=…, user_id=…)` —— 真签名 `agent_core.py:1704` 里
  **没有 `**kwargs`**，也没有 `content`/`user_id` 这两个参数 ⇒ unexpected keyword。

两条都 TypeError，而它们落在 `except Exception as e: await ws.send_json({"code":"chat_failed",
"message":str(e)})` 里，且**那一段一行日志都不记** ⇒ 手机客户端每次发消息只看到 `chat_failed`，
服务端侧什么痕迹都没有。`agent_core.py:1777` 的注释还写着
「mobile_pairing 与 chat.py 按 `user_input=`/`session_id=`/`metadata=` 消费本方法」——
注释描述的契约与调用点是反的。

## 为什么这一批合修两件事

§6-154 登记时特意**不**在这条路径上补请求级属主：一条 100% 抛异常的路径上补另一半，
等于把形状问题洗成"看着已修"。形状接对之后，属主这一半才有助手可言——
`set_request_user_id(user_id)` 决定 usage 入账归谁、按日配额判不判、会话落谁名下
（口径同 §6-153 那三条边界）。

## 判据的形状

替身不自己声明一套签名，而是**每次被调时按真 `Agent` 的签名 bind 一遍**——
这样"调用点写错参数名"会落在行为断言上（客户端收到 `error/chat_failed`），
而不是落在一个手抄的签名清单上（手抄清单会随生产签名一起漂，本卷已记过两次）。
"""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep
from neurova.core.identity_context import get_request_user_id

REPO = Path(__file__).resolve().parents[3]
PAIRING_CODE = "MOBILE-CODE-1"
OWNER = "u-mobile"
AGENT_ID = "mobile-agent"


def _checkAgainstRealSignature(agent, methodName: str, kwargs: Dict[str, Any], sink: List[dict]):
    """按真 `Agent.<method>` 的签名 bind 一遍：参数名不对、必填没给，都在这一步抛。"""
    from neurova.agent_core import Agent

    signature = inspect.signature(getattr(Agent, methodName))
    signature.bind(None, **kwargs)
    sink.append({**kwargs, "request_channel": get_request_user_id()})


class _StreamAgent:
    """有 `chat_stream` ⇒ 走 `hasattr` 的流式分支。"""

    def __init__(self) -> None:
        self.config = SimpleNamespace(agent_id=AGENT_ID, owner_user_id=OWNER,
                                      llm_model="test-model")
        self.calls: List[Dict[str, Any]] = []

    async def chat_stream(self, **kwargs):
        _checkAgainstRealSignature(self, "chat_stream", kwargs, self.calls)
        for piece in ("第一段", "第二段"):
            yield piece

    async def chat(self, **kwargs):
        _checkAgainstRealSignature(self, "chat", kwargs, self.calls)
        return {"text": "整段回复", "success": True}


class _NoStreamAgent(_StreamAgent):
    """没有 `chat_stream` ⇒ 走 `agent.chat` 那一分支（用子类删属性，不去动父类）。"""

    chat_stream = None  # `hasattr(agent,"chat_stream") and callable(...)` 因此为假


@pytest.fixture()
def wsClient(monkeypatch, request):
    useStream = request.param if getattr(request, "param", None) is not None else True
    agent = _StreamAgent() if useStream else _NoStreamAgent()
    # `get_agent_instance` 是在 `_handle_chat_send` 里就近 import 的（模块级没有这个名字），
    # 所以要打在它的出处 `neurova.api.endpoints` 上——打在 mobile_pairing 模块上会得到
    # AttributeError: module has no attribute（第一次跑就撞上）。
    import neurova.api.endpoints as endpointsModule

    monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": agent)

    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    monkeypatch.setitem(
        mobile_ep._pairing_codes, PAIRING_CODE,
        {"status": "confirmed", "user_id": OWNER, "pairing_id": "pair-1"},
    )

    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    client = TestClient(app)
    client.agent = agent  # type: ignore[attr-defined]
    return client


def _driveChat(client, content: str = "你好", sessionId: str = "s-1") -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with client.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
        ws.send_json({"type": "chat:send", "content": content, "session_id": sessionId})
        while True:
            payload = json.loads(ws.receive_text())
            events.append(payload)
            if payload.get("type") in ("chat:done", "error"):
                break
    return events


class TestChatSendCallShapeIsTheRealSignature:
    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_streamBranchCompletesWithoutErrorEvent(self, wsClient):
        events = _driveChat(wsClient)

        failed = [e for e in events if e.get("code") == "chat_failed"]
        assert not failed, (
            f"流式分支又把这一轮吞成 chat_failed：{failed[0].get('message')!r}——"
            "调用点的参数名与 `Agent.chat_stream` 的真签名不一致时，客户端只看到一句失败，"
            "服务端一行日志都没有")
        assert events[0]["type"] == "chat:chunk", events
        assert events[-1]["type"] == "chat:done", events

    @pytest.mark.parametrize("wsClient", [False], indirect=True)
    def test_nonStreamBranchCompletesWithoutErrorEvent(self, wsClient):
        events = _driveChat(wsClient)

        failed = [e for e in events if e.get("code") == "chat_failed"]
        assert not failed, f"非流式分支同样必抛：{failed[0].get('message')!r}"
        assert events[-1]["type"] == "chat:done", events

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_callSiteUsesTheProductionParameterNames(self, wsClient):
        """被调那一刻的入参逐条落档：`user_input`/`metadata`，不是自造的 `content`/`user_id`。"""
        _driveChat(wsClient)

        assert wsClient.agent.calls, "一轮都没打到 agent，下面的断言是空转"
        call = wsClient.agent.calls[0]
        assert "content" not in call and "user_id" not in call, (
            f"调用点仍在按自造的参数名传身份：{sorted(call)}")
        assert call.get("user_input") == "你好", call
        assert isinstance(call.get("metadata"), dict), f"metadata 没带过去：{call}"


class TestMobileTurnEstablishesTheRequestOwner:
    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_mobileTurnCarriesThePairedUserIntoTheRequestChannel(self, wsClient):
        _driveChat(wsClient)

        call = wsClient.agent.calls[0]
        assert call["request_channel"] == OWNER, (
            f"移动回合没建立请求级属主（读数 {call['request_channel']!r}）："
            "usage 记 anonymous、按日 LLM 配额整条不判、会话落空属主而对全员可见"
        )

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_metadataAlsoCarriesTheSameUser(self, wsClient):
        """两条通道同源：metadata 里那一格与请求通道必须同一个人，否则两处产出两个身份。"""
        _driveChat(wsClient)

        call = wsClient.agent.calls[0]
        assert (call.get("metadata") or {}).get("user_id") == OWNER == call["request_channel"], call


class TestRejectionsStayHonest:
    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_unknownAgentIsStillReportedAsAgentNotFound(self, wsClient, monkeypatch):
        import neurova.api.endpoints as endpointsModule

        monkeypatch.setattr(endpointsModule, "get_agent_instance", lambda agent_id="": None)

        events = _driveChat(wsClient)

        assert events[0]["code"] == "agent_not_found", events
        assert wsClient.agent.calls == [], "没有 agent 却跑了一轮"

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_lookupRaisingIsNotReportedAsNotFound(self, wsClient, monkeypatch):
        """装配/导入坏掉 ≠ "Agent 不存在"：两者必须分开回，否则真因永久隐身。"""
        import neurova.api.endpoints as endpointsModule

        def _boom(agent_id=""):
            raise RuntimeError("agent 注册表没起来")

        monkeypatch.setattr(endpointsModule, "get_agent_instance", _boom)

        events = _driveChat(wsClient)

        assert events[0]["code"] == "agent_lookup_failed", events
        assert "chat_failed" not in json.dumps(events)

    @pytest.mark.parametrize("wsClient", [True], indirect=True)
    def test_emptyContentIsRefusedBeforeTouchingTheAgent(self, wsClient):
        events = _driveChat(wsClient, content="   ")

        assert events[0]["code"] == "empty_content", events
        assert wsClient.agent.calls == [], "空内容也打到 agent"


class TestTheCatchAllNoLongerSwallowsSilently:
    """吞异常可以，但"客户端看到失败、服务端什么都不知道"这条不能再留（教义第 2 条）。

    口径按**整档**扫，不按函数名点靶：同一根因在本文件里有四处（`chat:send`、`session:list`、
    `session:create`、分发器），只钉报告里那一条就是本卷点过四次的老毛病。
    """

    MODULE = "neurova/api/endpoints/mobile_pairing.py"

    @classmethod
    def _swallowsWithoutLogging(cls, source: str) -> List[str]:
        """把异常转成 `ws.send_json(...)` 却一行不记的 catch-all → 记为违例。"""
        tree = ast.parse(source)
        offenders: List[str] = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.ExceptHandler)
                        and isinstance(node.type, ast.Name)
                        and node.type.id in ("Exception", "BaseException")):
                    continue
                sendsClient = any(
                    isinstance(call, ast.Call) and getattr(call.func, "attr", "") == "send_json"
                    for stmt in node.body for call in ast.walk(stmt)
                )
                if not sendsClient:
                    continue
                logged = any(
                    isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("exception", "error", "warning")
                    and getattr(call.func.value, "id", "") in ("logger", "log")
                    for stmt in node.body for call in ast.walk(stmt)
                )
                if not logged:
                    offenders.append(f"{fn.name}:{node.lineno}")
        return offenders

    def test_everyClientFacingSwallowLogs(self):
        source = (REPO / self.MODULE).read_text(encoding="utf-8")
        offenders = self._swallowsWithoutLogging(source)
        assert not offenders, (
            f"这些 catch-all 把异常转成客户端事件却不记日志：{offenders}——"
            "形状类缺陷（TypeError/AttributeError）会在这里永久隐身："
            "本档修的正是这条，一次 TypeError 挂了整个移动端对话面")

    def test_theDetectorDiscriminatesBothWays(self):
        """判据自证两侧都验：现码判合规，把那些日志摘掉就必须点名。

        只留一侧会空转两种方向：恒报违例（改多少都红）与恒不报（抄现码抄出来的绿）。
        修之前这一格验的是"加了日志仍判违例"，修之后翻成"摘掉日志仍判合规"——
        转绿时把对照方向一起翻过来，这本身就是判据的一部分。
        """
        source = (REPO / self.MODULE).read_text(encoding="utf-8")
        assert self._swallowsWithoutLogging(source) == [], "现码本侧失败：仍有不记日志的命中点"

        stripped = "\n".join(line for line in source.splitlines()
                             if not line.strip().startswith('logger.exception("mobile'))
        assert stripped != source, "找不到那条日志行，摘除式对照无从做起"
        found = self._swallowsWithoutLogging(stripped)
        assert len(found) >= 4, (
            f"摘掉全部四处日志只抓到 {found} ⇒ 探测器覆盖不全，上一格是恒真的空守卫")
