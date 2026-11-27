# -*- coding: utf-8 -*-
"""P2-27：CLI 凭据、2FA、SSE 增量与命令选项契约回归。"""
import io
import json

import httpx
import pytest
from rich.console import Console

import cli as repl


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks, on_chunk=None):
        self.chunks = chunks
        self.on_chunk = on_chunk
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            if self.on_chunk:
                self.on_chunk(chunk)
            yield chunk

    def close(self):
        self.closed = True


def _cli(handler):
    return repl.NeurovaCLI(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
        console=Console(file=io.StringIO(), force_terminal=False),
    )


def test_provider_api_key_uses_getpass(monkeypatch):
    client = _cli(lambda request: httpx.Response(200, json={"provider_id": "p1"}, request=request))
    answers = iter(["custom-provider", "openai", "", "sk-secret"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    prompted = []
    monkeypatch.setattr("getpass.getpass", lambda prompt: prompted.append(prompt) or "sk-secret")
    sent = []
    monkeypatch.setattr(client, "check_connection", lambda pid: {"success": True})
    original = client._post

    def capture(path, **kwargs):
        sent.append(kwargs["json"])
        return original(path, **kwargs)

    monkeypatch.setattr(client, "_post", capture)
    client.cmd_llm(["add"])
    assert prompted == ["API Key: "]
    assert sent[0]["api_key"] == "sk-secret"


def test_failed_login_and_two_factor_never_retain_old_token(monkeypatch):
    client = _cli(lambda request: httpx.Response(401, json={"detail": "bad"}, request=request))
    client.token = "old-token"
    assert client.login("user", "wrong") is False
    assert client.token is None

    client.token = "stale-token"
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={"two_factor_required": True, "challenge_token": "challenge"}, request=request)
        assert json.loads(request.content) == {"challenge_token": "challenge", "code": "123456"}
        return httpx.Response(200, json={"access_token": "fresh-token"}, request=request)

    client = _cli(handler)
    client.token = "stale-token"
    monkeypatch.setattr("builtins.input", lambda prompt: "123456")
    assert client.login("user", "correct") is True
    assert client.token == "fresh-token"
    assert calls[0].headers.get("authorization") is None


def test_two_factor_verify_failure_clears_old_token(monkeypatch):
    client = _cli(lambda request: httpx.Response(
        200,
        json={"two_factor_required": True, "challenge_token": "challenge"}
        if request.url.path.endswith("/login") else {"detail": "bad code"},
        request=request,
    ))
    client.token = "stale-token"
    monkeypatch.setattr("builtins.input", lambda prompt: "000000")
    assert client.login("user", "correct") is False
    assert client.token is None


def test_sse_callback_runs_before_stream_end_and_session_first_frame(monkeypatch):
    observed = []
    payloads = []
    first = b'data: {"type":"session","session_id":"s-first"}\n\n'
    second = b'data: {"type":"chunk","content":"hello"}\n\n'

    def handler(request):
        payloads.append(json.loads(request.content))
        def on_chunk(chunk):
            observed.append((chunk, client.current_session_id))

        return httpx.Response(200, stream=ChunkStream([first, second], on_chunk), request=request)

    client = _cli(handler)
    events = []
    reply = client.send_chat(
        "hi", stream=True, model="m1", thinking_effort="deep", file_ids=["f1"],
        on_event=lambda kind, data: events.append((kind, data)),
    )
    assert payloads == [{
        "message": "hi", "agent_id": "default", "session_id": None, "stream": True,
        "model": "m1", "thinking_effort": "deep", "file_ids": ["f1"],
    }]
    assert reply == "hello"
    assert observed[0][1] is None
    assert observed[1][1] == "s-first"
    assert events[0] == ("session", {"type": "session", "session_id": "s-first"})
    assert ("chunk", "hello") in events
    assert client.current_session_id == "s-first"


@pytest.mark.parametrize("args, expected", [
    (["save", "hello", "--category", "fact"], ("hello", "fact")),
    (["save", "--category=fact", "hello", "world"], ("hello world", "fact")),
])
def test_memory_options_are_stripped_before_content(args, expected):
    client = _cli(lambda request: httpx.Response(200, json={"data": {}}, request=request))
    captured = []
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(client, "save_memory", lambda content, category=None: captured.append((content, category)) or {"memory_id": "m1"})
    try:
        client.cmd_memory(args)
    finally:
        monkeypatch.undo()
    assert captured == [expected]


def test_knowledge_options_are_stripped_from_title_and_content():
    client = _cli(lambda request: httpx.Response(200, json={}, request=request))
    captured = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(client, "create_knowledge", lambda title, content, **kw: captured.append((title, content, kw)) or {"knowledge_id": "k1"})
        client.cmd_knowledge(["add", "标题", "--content", "正文", "--category", "cat", "--visibility=public"])
    assert captured == [("标题", "正文", {"category": "cat", "visibility": "public"})]


@pytest.mark.parametrize("command, args", [
    ("memory", ["save", "正文", "--category"]),
    ("knowledge", ["add", "标题", "--content"]),
    ("knowledge", ["list", "--scope"]),
    ("knowledge", ["add", "标题", "--content", "正文", "--visibility"]),
])
def test_missing_option_value_errors_before_request(command, args):
    client = _cli(lambda request: pytest.fail("缺值不得请求后端"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(client, "_err", lambda message: setattr(client, "last_error", message))
        getattr(client, f"cmd_{command}")(args)
    assert "--" in client.last_error
