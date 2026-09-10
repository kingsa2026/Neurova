"""L-15 / L-16 回归测试：能力探测错误缓存与流未关闭。

L-15 红绿：无修复时 probe() 探测异常只把 capabilities[cap]=False，error 字段
(:38 默认 None) 从不赋值，detect_capabilities() 把含错误的结果按 ttl=3600
缓存 1 小时 → 网络抖动被固化为"零能力"。断言：异常探测后 result.error
非 None，且 cache.get 返回 None（错误结果不进长缓存）；正常结果仍进缓存。

L-16 红绿：无修复时 _probe_streaming 读到首个 delta 即 return True，
HTTP 流未关闭。断言：返回前后 response.aclose() 均被调用。
"""

from types import SimpleNamespace

import pytest

from neurova.llm.providers.capability_detector import (
    CapabilityDetector,
    ModelCapability,
    detect_capabilities,
    reset_capability_cache,
    reset_capability_detector,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_capability_detector()
    reset_capability_cache()
    yield
    reset_capability_detector()
    reset_capability_cache()


class _FakeCompletions:
    def __init__(self, behavior):
        self._behavior = behavior

    async def create(self, **kwargs):
        return await self._behavior(**kwargs)


class _FakeChat:
    def __init__(self, behavior):
        self.completions = _FakeCompletions(behavior)


class _FakeLLMClient:
    def __init__(self, behavior):
        self.chat = _FakeChat(behavior)


class _FakeStreamResponse:
    """可异步迭代 + 可 aclose 的伪 HTTP 流。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._iter = iter(self._chunks)
        self.aclose_called = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self):
        self.aclose_called = True


def _make_chunk():
    delta = SimpleNamespace(content="streaming test")
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


# ── L-15 ──────────────────────────────────────────────────────────────────


class TestL15ErrorNotCached:
    @pytest.mark.asyncio
    async def test_probe_error_recorded_in_result(self):
        """探测异常时 error 字段必须记录原因。"""
        async def _fail(**kwargs):
            raise RuntimeError("network down")

        detector = CapabilityDetector()
        result = await detector.probe("m1", "prov1", _FakeLLMClient(_fail))
        assert result.error is not None, "L-15: 探测异常必须写入 error 字段"
        assert "network down" in result.error

    @pytest.mark.asyncio
    async def test_error_result_not_cached_for_an_hour(self):
        """含错误的结果不得进 3600s 长缓存。"""
        from neurova.llm.providers.capability_detector import get_capability_cache

        async def _fail(**kwargs):
            raise RuntimeError("network down")

        result = await detect_capabilities("m1", "prov1", _FakeLLMClient(_fail), use_cache=True)
        assert result.error is not None
        cache = get_capability_cache()
        assert cache.get("m1", "prov1") is None, (
            "L-15: 含错误的结果不得被缓存（网络抖动会被固化为零能力）"
        )

    @pytest.mark.asyncio
    async def test_clean_result_still_cached(self):
        """无错误结果仍正常进缓存（防过修）。"""
        from neurova.llm.providers.capability_detector import get_capability_cache

        def _ok_response():
            choice = SimpleNamespace(
                delta=SimpleNamespace(content="ok"),
                message=SimpleNamespace(content='{"status": "ok"}', tool_calls=[object()]),
            )
            resp = SimpleNamespace(choices=[choice])
            # 让响应可异步迭代（streaming 探测用）
            async def _gen():
                return
                yield  # pragma: no cover
            return resp

        async def _ok(**kwargs):
            resp = _ok_response()
            if kwargs.get("stream"):
                async def _aiter():
                    yield _make_chunk()
                return _aiter()
            return resp

        result = await detect_capabilities("m2", "prov2", _FakeLLMClient(_ok), use_cache=True)
        assert result.error is None
        assert get_capability_cache().get("m2", "prov2") is not None


# ── L-16 ──────────────────────────────────────────────────────────────────


class TestL16StreamClosed:
    @pytest.mark.asyncio
    async def test_stream_closed_on_first_delta(self):
        """读到首个 delta 提前 return True 时必须 aclose 流。"""
        resp = _FakeStreamResponse([_make_chunk(), _make_chunk()])

        async def _create(**kwargs):
            return resp

        detector = CapabilityDetector()
        supported = await detector._probe_streaming(_FakeLLMClient(_create), "m1")
        assert supported is True
        assert resp.aclose_called is True, "L-16: 提前返回前必须关闭 HTTP 流"

    @pytest.mark.asyncio
    async def test_stream_closed_when_no_delta(self):
        """流读完（无 delta）也必须 aclose。"""
        resp = _FakeStreamResponse([])

        async def _create(**kwargs):
            return resp

        detector = CapabilityDetector()
        supported = await detector._probe_streaming(_FakeLLMClient(_create), "m1")
        assert supported is False
        assert resp.aclose_called is True

    @pytest.mark.asyncio
    async def test_probe_via_public_api_closes_stream(self):
        """经 probe() 全链路探测 streaming 时流被收口。"""
        resp = _FakeStreamResponse([_make_chunk()])

        async def _create(**kwargs):
            return resp

        detector = CapabilityDetector()
        result = await detector.probe(
            "m1", "prov1", _FakeLLMClient(_create),
            capabilities_to_probe=[ModelCapability.STREAMING],
        )
        assert result.has_capability(ModelCapability.STREAMING) is True
        assert resp.aclose_called is True
