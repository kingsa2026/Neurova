# -*- coding: utf-8 -*-
"""资源型修复（台账 docs/资源型修复登记台账_2026-09-11.md）API 端点域防回归：

#2  neurflow_api._DEBUG_SESSIONS 无淘汰 → 有界 LRU 注册表（上限
    _DEBUG_SESSIONS_MAX，超限逐出最久未访问条目；collaboration_api 的
    裸赋值路径同样经 __setitem__ 受封顶约束，且保持 isinstance dict 契约）；
#3  mobile_pairing._cancelled_sessions 只增不清 → 取消标记仅在对应
    chat:send 流式执行生命周期内有效（流开始消费残留标记、终态弹出），
    无在流会话消费的孤儿标记按 _CANCELLED_SESSIONS_MAX 封顶逐出最旧；
#6  media.py Content-Disposition 未按 RFC 5987 编码 → ASCII 安全回退名
    + filename*=UTF-8''<percent-encoded>，非 ASCII 名不再直写响应头；
#17 media.py _get_media_manager 死代码删除（全仓 grep 复核零引用）。

隔离纪律：端点函数直调 + monkeypatch，无真实网络/文件/SQLite；
media 存储根指向 tmp_path；模块级内存注册表逐用例替换、自动还原。
"""

import asyncio
import re
from urllib.parse import quote, unquote

import pytest

from neurova.api.endpoints import media as media_module
from neurova.api.endpoints import mobile_pairing as mp


# ---------------------------------------------------------------------------
# 公共隔离件
# ---------------------------------------------------------------------------


class _FakeUploadFile:
    """分块读取语义与 starlette.UploadFile 对齐。"""

    def __init__(self, data: bytes, filename: str = "clip.png"):
        self.filename = filename
        self._data = data
        self._offset = 0

    async def read(self, size: int = -1):
        end = len(self._data) if size is None or size < 0 else min(self._offset + size, len(self._data))
        chunk = self._data[self._offset:end]
        self._offset = end
        return chunk


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


class _StreamAgent:
    """chat_stream 异步生成器桩；hook 在两次 chunk 之间被调用。"""

    def __init__(self, hook=None):
        self._hook = hook

    async def chat_stream(self, *, content, session_id, user_id):
        yield "c1"
        if self._hook:
            self._hook()
        yield "c2"


# ---------------------------------------------------------------------------
# #2 _DEBUG_SESSIONS 有界 LRU
# ---------------------------------------------------------------------------


@pytest.fixture()
def debug_sessions(monkeypatch):
    """替换模块级注册表（与现网同类型的新实例），退出自动还原。"""
    from neurova.api.endpoints import neurflow_api as nf

    reg = type(nf._DEBUG_SESSIONS)()
    monkeypatch.setattr(nf, "_DEBUG_SESSIONS", reg)
    return nf, reg


def test_debug_sessions_cap_evicts_oldest_via_setdefault(debug_sessions):
    """101 个调试会话经 set_breakpoints 写入后，最旧者被逐出、总量封顶。"""
    nf, reg = debug_sessions
    for i in range(101):
        asyncio.run(
            nf.set_breakpoints(f"exec-{i}", nf.BreakpointRequest(breakpoints=[f"n{i}"]), {})
        )
    assert len(reg) == 100, f"注册表未封顶: {len(reg)}"
    assert "exec-0" not in reg, "最旧调试会话未被逐出"
    assert "exec-100" in reg


def test_debug_sessions_plain_assignment_capped_and_is_dict(debug_sessions):
    """collaboration_api 的裸赋值路径同样受封顶；保持 isinstance dict 契约。"""
    nf, reg = debug_sessions
    for i in range(105):
        reg[f"exec-{i}"] = nf.DebugSession()
    assert isinstance(reg, dict)
    assert len(reg) == 100
    assert "exec-0" not in reg
    assert "exec-104" in reg


def test_debug_sessions_get_touches_lru_order(debug_sessions):
    """get 触碰后条目移到队尾：封顶逐出的是最久未访问者而非首个写入者。"""
    nf, reg = debug_sessions
    for i in range(100):
        reg[f"exec-{i}"] = nf.DebugSession()
    reg.get("exec-0")
    reg["exec-100"] = nf.DebugSession()
    assert len(reg) == 100
    assert "exec-0" in reg, "刚被访问的会话被逐出（未按 LRU 触碰）"
    assert "exec-1" not in reg, "逐出的不是最久未访问条目"


# ---------------------------------------------------------------------------
# #3 _cancelled_sessions 有界化 + 流生命周期语义
# ---------------------------------------------------------------------------


@pytest.fixture()
def cancelled_state(monkeypatch):
    monkeypatch.setattr(mp, "_cancelled_sessions", {})
    monkeypatch.setattr(mp, "_CANCELLED_SESSIONS_MAX", 8, raising=False)
    return mp


@pytest.mark.asyncio
async def test_cancel_flag_cleared_when_stream_ends(cancelled_state):
    """取消命中后流返回 chat:cancelled，终态时标记必须被回收（#3 核心断言）。"""
    state = cancelled_state

    def mid_stream():
        state._cancelled_sessions["sess-x"] = True

    ws = _FakeWS()
    with pytest.MonkeyPatch.context() as m:
        m.setattr("neurova.api.endpoints.get_agent_instance", lambda aid: _StreamAgent(hook=mid_stream))
        await state._handle_chat_send(
            ws, {"type": "chat:send", "content": "hi", "session_id": "sess-x"}, "u1"
        )

    types = [msg["type"] for msg in ws.sent]
    assert "chat:cancelled" in types
    assert "sess-x" not in state._cancelled_sessions, "流终态后取消标记仍驻留（只增不清）"


@pytest.mark.asyncio
async def test_orphan_cancel_consumed_by_next_stream(cancelled_state):
    """流结束后才到达的孤儿取消不得误杀下一次发送，且被新流开始时消费。"""
    state = cancelled_state
    state._cancelled_sessions["sess-o"] = True

    ws = _FakeWS()
    with pytest.MonkeyPatch.context() as m:
        m.setattr("neurova.api.endpoints.get_agent_instance", lambda aid: _StreamAgent())
        await state._handle_chat_send(
            ws, {"type": "chat:send", "content": "hi", "session_id": "sess-o"}, "u1"
        )

    types = [msg["type"] for msg in ws.sent]
    assert "chat:done" in types, "孤儿取消标记误杀新流"
    assert "chat:cancelled" not in types
    assert "sess-o" not in state._cancelled_sessions


@pytest.mark.asyncio
async def test_cancelled_sessions_capped_prunes_oldest(cancelled_state):
    """孤儿标记超上限逐出最旧（封顶兜底）。"""
    state = cancelled_state
    ws = _FakeWS()
    for i in range(12):
        await state._handle_chat_cancel(ws, {"type": "chat:cancel", "session_id": f"s-{i}"})
    assert len(state._cancelled_sessions) <= state._CANCELLED_SESSIONS_MAX
    assert "s-0" not in state._cancelled_sessions, "最旧孤儿标记未被逐出"
    assert "s-11" in state._cancelled_sessions


# ---------------------------------------------------------------------------
# #6 Content-Disposition RFC 5987
# ---------------------------------------------------------------------------


@pytest.fixture()
def media_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        media_module,
        "_media_config",
        {**media_module._media_config, "storage_path": str(tmp_path / "media_storage")},
    )
    media_module._media_store.clear()
    yield tmp_path
    media_module._media_store.clear()


def _save(payload: bytes, filename: str, media_type: str = "file"):
    return asyncio.run(
        media_module.save_media(
            file=_FakeUploadFile(payload, filename=filename),
            media_type=media_type,
            agent_id="a1",
        )
    )


def test_content_disposition_ascii_name_keeps_legacy_shape(media_env):
    """ASCII 安全名保持既有契约（兼容 test_media_disk_storage.py）。"""
    resp = _save(b"x", filename="clip.png")
    out = asyncio.run(media_module.get_media(resp["data"]["media_id"]))
    assert out.headers["content-disposition"] == 'attachment; filename="clip.png"'


def test_content_disposition_utf8_filename_rfc5987(media_env):
    """中文文件名：filename= 走 ASCII 回退，原始名走 filename*=UTF-8''，头可 latin-1 编码。"""
    name = "季度报告.pdf"
    resp = _save(b"x", filename=name)

    for endpoint in (media_module.get_media, media_module.download_attachment):
        out = asyncio.run(endpoint(resp["data"]["media_id"]))
        cd = out.headers["content-disposition"]
        assert "attachment" in cd
        assert f"filename*=UTF-8''{quote(name, safe='')}" in cd, f"缺 RFC5987 原始名: {cd}"
        assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == name
        fallback = re.search(r'filename="([^"]*)"', cd)
        assert fallback is not None and fallback.group(1).isascii(), f"filename= 非 ASCII 回退缺失: {cd}"
        cd.encode("latin-1"), "响应头含非 ASCII 字节（旧缺陷：直写原始名）"


def test_content_disposition_helper_blocks_header_injection():
    """引号/换行文件名不得原样进入响应头（CR/LF 与未转义引号是注入向量）。"""
    raw = 'evil".png\r\nX-Inject: 1'
    cd = media_module._content_disposition(raw)
    assert "\r" not in cd and "\n" not in cd
    fallback = re.search(r'filename="([^"]*)"', cd).group(1)
    assert re.fullmatch(r"[A-Za-z0-9._-]*", fallback), f"回退名含未净化字符: {fallback}"
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == raw


# ---------------------------------------------------------------------------
# #17 media.py 死代码删除
# ---------------------------------------------------------------------------


def test_media_dead_code_get_media_manager_removed():
    """_get_media_manager 全仓零引用，删除后模块不可再见该符号。"""
    assert not hasattr(media_module, "_get_media_manager")
