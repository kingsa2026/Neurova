# -*- coding: utf-8 -*-
"""S17 F1：模型请求级归档（TDD RED→GREEN）。

红灯四条（方案 S17）：
① 一次 LLM 调用产生一条归档（含 usage/时延/角色计数）；
② 含 key 样式内容被脱敏（错误摘要经 S7 SENSITIVE_KEY_PATTERNS 遮蔽，不落原文）；
③ 写失败不阻断调用（fail-soft：日志+计数可见，不静默吞）；
④ 流式路径同形态（一次成功流 = 一条 stream 归档，含 usage/首块时延）。
另：全文归档门 NEUROVA_REQUEST_ARCHIVE_FULL 本批只做钩子——门开有 WARNING、
归档仍只落脱敏摘要（旋钮不允许静默失效）；无会话上下文的调用落 unscoped 键。
"""

import asyncio
import json
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

pytest.importorskip("openai")

from neurova.llm_client import LLMResponse  # noqa: E402
from neurova.llm.multi_model_client import MultiModelLLMClient  # noqa: E402


@pytest.fixture
def archiveEnv(tmp_path, monkeypatch):
    """数据根重定向到临时目录 + 归档写器逐测试复位。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    from neurova.core import request_archive

    request_archive.resetRequestArchive()
    yield tmp_path / "data"
    request_archive.resetRequestArchive()


@pytest.fixture(autouse=True)
def _cleanTurnIdentity():
    """轮上下文 session 逐测试清理，防跨用例串档。"""
    yield
    from neurova.core.turn_context import set_turn_identity

    set_turn_identity("", None)


def _make_mmc(inner_chat, model="test-model", provider_id="p1"):
    """最小 MultiModelLLMClient：绕 __init__，桩 _get_client_for_request。"""
    stub = SimpleNamespace(
        client=SimpleNamespace(chat=inner_chat),
        model=model,
        provider=SimpleNamespace(id=provider_id),
        increment_request=MagicMock(),
    )
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: stub
    return mmc, stub


def _readArchiveLines(dataRoot, key):
    path = dataRoot / "request_archives" / f"{key}.jsonl"
    if not path.exists():
        return None, []
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return path, lines


class TestChatArchivesOneRequest:
    """① 一次 LLM 调用产生一条归档（含 usage/时延/角色计数）。"""

    def test_chatProducesOneArchiveEntry(self, archiveEnv):
        from neurova.core.request_archive import flushRequestArchive
        from neurova.core.turn_context import set_turn_identity

        set_turn_identity("你好", session_id="sess_arc1")

        def inner_chat(messages, **kwargs):
            return LLMResponse(
                content="ok",
                model="test-model",
                usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            )

        mmc, _ = _make_mmc(inner_chat)
        result = asyncio.run(mmc.chat([{"role": "user", "content": "你好"}]))
        assert result.get("success"), result

        flushRequestArchive(timeout=5)
        path, lines = _readArchiveLines(archiveEnv, "sess_arc1")
        assert path is not None, "红灯：chat 成功后归档文件未落盘"
        assert len(lines) == 1, f"红灯：期望 1 条归档，实际 {len(lines)}"

        entry = lines[0]
        assert entry["provider"] == "p1"
        assert entry["model"] == "test-model"
        assert entry["success"] is True
        assert entry["usage"]["promptTokens"] == 12
        assert entry["usage"]["completionTokens"] == 5
        assert entry["usage"]["estimated"] is False
        assert entry["durationMs"] >= 0
        assert entry["roles"]["user"]["count"] == 1
        assert entry["roles"]["user"]["chars"] == 2  # "你好" = 2 字符
        assert entry["sessionId"] == "sess_arc1"
        assert entry["stream"] is False
        assert entry["fullText"] is False  # 本批恒不落全文

    def test_noSessionFallsToUnscopedKey(self, archiveEnv):
        """无会话上下文的调用落 unscoped 键（诚实聚合，不静默丢）。"""
        from neurova.core.request_archive import flushRequestArchive

        def inner_chat(messages, **kwargs):
            return LLMResponse(content="ok", model="test-model", usage={})

        mmc, _ = _make_mmc(inner_chat)
        result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
        assert result.get("success"), result

        flushRequestArchive(timeout=5)
        path, lines = _readArchiveLines(archiveEnv, "unscoped")
        assert path is not None, "红灯：无会话调用未落 unscoped 归档"
        assert lines and lines[0]["sessionId"] == ""


class TestSecretRedaction:
    """② 含 key 样式内容被脱敏（S7 SENSITIVE_KEY_PATTERNS 单源复用）。"""

    def test_errorSummaryMaskedOnFailure(self, archiveEnv):
        from neurova.core.request_archive import flushRequestArchive
        from neurova.core.turn_context import set_turn_identity

        set_turn_identity("查一下", session_id="sess_leak")

        def inner_chat(messages, **kwargs):
            raise RuntimeError("invalid request: api_key=sk-SecretValue1234567890ABCDEF rejected")

        mmc, _ = _make_mmc(inner_chat)
        result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
        assert result.get("success") is False  # 错误如实上抛为信封，不受归档影响

        flushRequestArchive(timeout=5)
        path, lines = _readArchiveLines(archiveEnv, "sess_leak")
        assert path is not None, "红灯：失败调用未落归档"
        assert len(lines) == 1
        entry = lines[0]
        assert entry["success"] is False
        assert entry["errorKind"], "红灯：失败归档缺错误族"
        summary = entry.get("errorSummary", "")
        assert "sk-SecretValue1234567890ABCDEF" not in summary, (
            f"红灯：密钥原文泄漏进归档：{summary!r}"
        )
        assert "***" in summary, f"红灯：脱敏摘要未遮蔽密钥：{summary!r}"

    def test_redactSensitiveTextDirect(self):
        """脱敏函数直测：credentialAssignment 族命中即遮蔽。"""
        from neurova.core.request_archive import redactSensitiveText

        text = "config: password=hunter2secret and host=example.com"
        out = redactSensitiveText(text)
        assert "hunter2secret" not in out
        assert "host=example.com" in out  # 非敏感内容保留

    def test_archiveNeverStoresMessageFullText(self, archiveEnv):
        """默认不落全文：归档行内不出现消息正文（只落角色与字符数）。"""
        from neurova.core.request_archive import flushRequestArchive
        from neurova.core.turn_context import set_turn_identity

        secretBody = "my password=SuperSecret99 body"
        set_turn_identity(secretBody, session_id="sess_body")

        def inner_chat(messages, **kwargs):
            return LLMResponse(content="ok", model="test-model", usage={})

        mmc, _ = _make_mmc(inner_chat)
        asyncio.run(mmc.chat([{"role": "user", "content": secretBody}]))
        flushRequestArchive(timeout=5)

        path, lines = _readArchiveLines(archiveEnv, "sess_body")
        assert path is not None
        raw = path.read_text(encoding="utf-8")
        assert "SuperSecret99" not in raw, "红灯：消息正文泄漏进归档"


class TestWriteFailureFailSoft:
    """③ 写失败不阻断调用（错误日志+计数可见，不静默吞）。"""

    def test_writeFailureDoesNotBlockChat(self, archiveEnv, monkeypatch):
        from neurova.core import request_archive

        def _boom(self, entry, path):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(request_archive.RequestArchiveWriter, "_appendEntry", _boom)

        def inner_chat(messages, **kwargs):
            return LLMResponse(content="ok", model="test-model", usage={})

        mmc, _ = _make_mmc(inner_chat)
        result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
        assert result.get("success"), "红灯：归档写失败阻断了主调用"

        request_archive.flushRequestArchive(timeout=5)
        stats = request_archive.requestArchiveWriteStats()
        assert stats["writeFailures"] >= 1, (
            f"红灯：写失败未计数（stats={stats}）——fail-soft 不等于静默吞"
        )


class TestStreamArchive:
    """④ 流式路径同形态：一次成功流 = 一条 stream 归档。"""

    def test_chatStreamProducesOneArchiveEntry(self, archiveEnv):
        from neurova.core.request_archive import flushRequestArchive
        from neurova.core.turn_context import set_turn_identity

        set_turn_identity("流式吗", session_id="sess_stream")

        async def gen(messages, **kwargs):
            yield SimpleNamespace(content="he", reasoning_content=None, usage=None,
                                  tool_calls=None, finish_reason=None)
            yield SimpleNamespace(content="llo", reasoning_content=None, usage=None,
                                  tool_calls=None, finish_reason=None)
            yield SimpleNamespace(
                content="", reasoning_content=None,
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
                tool_calls=None, finish_reason="stop",
            )

        mmc, stub = _make_mmc(lambda messages, **kwargs: None)
        stub.client.chat_stream_async = gen
        stub.client._compat_include_stream_usage = lambda: True

        async def _consume():
            chunks = []
            async for chunk in mmc.chat_stream([{"role": "user", "content": "流式吗"}]):
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(_consume())
        assert chunks, "红灯：流式消费为空"
        assert not any(isinstance(c, dict) and "error" in c for c in chunks), chunks[-1]

        flushRequestArchive(timeout=5)
        path, lines = _readArchiveLines(archiveEnv, "sess_stream")
        assert path is not None, "红灯：流式成功后归档未落盘"
        assert len(lines) == 1, f"红灯：期望 1 条流式归档，实际 {len(lines)}"
        entry = lines[0]
        assert entry["stream"] is True
        assert entry["success"] is True
        assert entry["usage"]["promptTokens"] == 7
        assert entry["usage"]["completionTokens"] == 3
        assert entry["firstTokenMs"] >= 0


class TestFullTextGateHook:
    """全文归档门只做钩子：门开有 WARNING（旋钮不静默失效），归档仍只落摘要。"""

    def test_gateOpenWarnsAndStillSummarizes(self, archiveEnv, monkeypatch, caplog):
        from neurova.core import request_archive

        monkeypatch.setenv(request_archive.FULL_TEXT_ENV, "1")
        assert request_archive.requestFullTextEnabled() is True

        def inner_chat(messages, **kwargs):
            return LLMResponse(content="ok", model="test-model", usage={})

        mmc, _ = _make_mmc(inner_chat)
        with caplog.at_level(logging.WARNING, logger="neurova.core.request_archive"):
            asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))
            request_archive.flushRequestArchive(timeout=5)

        warnings = [r for r in caplog.records
                    if r.levelno >= logging.WARNING and "全文" in r.getMessage()]
        assert warnings, "红灯：全文门打开却无任何 WARNING——旋钮静默失效"
        path, lines = _readArchiveLines(archiveEnv, "unscoped")
        assert lines and all(entry.get("fullText") is False for entry in lines), (
            "红灯：门开即落全文（本批未实现全文落盘）"
        )
