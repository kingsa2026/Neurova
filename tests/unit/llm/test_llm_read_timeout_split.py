"""读/建连超时分离 + 服务商级覆盖 + 流内静默遥测（2026-09-10 流中断事故加固）。

事故：api.b.ai 流式响应思考阶段静默 120s → httpx.ReadTimeout。LLMConfig.timeout
一根管子既管建连又管读间隙——思考模型经缓冲型网关的健康长静默（reasoning 停发、
工具调用参数缓冲）被误杀；且客户端无法区分"健康长思考"与"上游停滞"，需要
静默看门狗留判据（provider/模型/静默时长/已收字节）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.provider_manager import ProviderConfig
from neurova.llm_client import LLMClient, LLMConfig

import pytest

# LLMClient 真实客户端构造依赖 openai 库（未安装时 client=None，无法验证 timeout 装配）
pytest.importorskip("openai")


class TestTimeoutSplit:
    def test_default_split(self):
        """读间隙默认 300s（思考模型长静默），建连收紧 15s（死端点快速失败）"""
        cfg = LLMConfig()
        assert cfg.timeout == 300
        assert cfg.connect_timeout == 15

    def test_httpx_timeout_split_applied(self):
        """底层 openai 客户端必须收到分离后的 httpx.Timeout"""
        client = LLMClient(LLMConfig(api_key="sk-test", timeout=600, connect_timeout=20))
        t = client.client.timeout
        assert isinstance(t, httpx.Timeout), "必须以 httpx.Timeout 传入（原 int 是四值同限）"
        assert t.read == 600
        assert t.connect == 20
        if client.async_client is not None:
            assert client.async_client.timeout.connect == 20

    def test_provider_timeout_overrides_read(self):
        """providers.json 的 timeout 字段覆盖读超时（秒），建连保持收紧"""
        manager = MultiModelLLMClient.__new__(MultiModelLLMClient)
        manager._clients = {}
        provider = ProviderConfig(
            id="bai",
            name="bai",
            provider="openai",
            base_url="https://api.b.ai/v1",
            api_key="sk-test",
            models=["glm-5.3-flash"],
            timeout=600,
        )
        mc = manager._create_model_client(provider, "glm-5.3-flash")
        assert mc is not None, "api_key 就绪时必须建出客户端"
        assert mc.client.config.timeout == 600, "服务商级读超时覆盖生效"
        assert mc.client.config.connect_timeout == 15, "建连不随覆盖放宽"

    def test_provider_timeout_none_uses_default(self):
        """未配置 timeout 的服务商走 LLMConfig 默认"""
        manager = MultiModelLLMClient.__new__(MultiModelLLMClient)
        manager._clients = {}
        provider = ProviderConfig(
            id="p2",
            name="p2",
            provider="openai",
            base_url="https://x.example/v1",
            api_key="sk-test",
            models=["m"],
        )
        mc = manager._create_model_client(provider, "m")
        assert mc.client.config.timeout == 300
        assert mc.client.config.connect_timeout == 15

    def test_provider_timeout_persisted_roundtrip(self):
        """timeout 字段必须随 to_dict/from_dict 往返（providers.json 持久化）"""
        cfg = ProviderConfig(id="x", name="x", provider="openai", base_url="u", timeout=600)
        data = cfg.to_dict()
        assert data["timeout"] == 600
        assert ProviderConfig.from_dict(data).timeout == 600


class TestStreamSilenceTelemetry:
    """看门狗：静默跨过阈值时留 WARNING（provider/模型/静默时长/已收字节）。

    用真实时钟 + 缩小阈值/轮询常量模拟长静默，不 mock time（mock 时钟
    对并发看门狗失真）。
    """

    def _make_manager(self, monkeypatch):
        import neurova.llm.multi_model_client as mmc
        from neurova.llm.model_rate_limiter import reset_shared_limiter

        # 共享限流器隔离：其他测试文件可能对同名 model key 留下 429 暂停
        reset_shared_limiter()
        monkeypatch.setattr(mmc, "_STREAM_SILENCE_WARN_SECONDS", 0.1)
        monkeypatch.setattr(mmc, "_STREAM_SILENCE_POLL_SECONDS", 0.02)
        logs: list[str] = []

        class _Cap:
            def warning(self, msg, *a, **k):
                logs.append(msg % a if a else msg)

            def debug(self, *a, **k):
                pass

            def info(self, *a, **k):
                pass

            def error(self, *a, **k):
                pass

        monkeypatch.setattr(mmc, "logger", _Cap())
        manager = MultiModelLLMClient.__new__(MultiModelLLMClient)
        manager._provider_manager = None
        manager._clients = {}
        manager._current_provider_id = None
        manager._current_model = None
        return manager, logs

    def _attach_client(self, manager, fake_stream):
        client = SimpleNamespace(
            client=SimpleNamespace(chat_stream_async=fake_stream),
            increment_request=lambda **k: None,
            model="gpt-test",
            provider=SimpleNamespace(id="test-provider"),
        )
        manager._get_client_for_request = lambda model=None, provider_id=None: client

    @staticmethod
    def _chunk(text=""):
        return SimpleNamespace(
            content=text, reasoning_content=None, usage=None, tool_calls=None, finish_reason=None
        )

    def test_silence_warning_fires_on_gap_then_recovers(self, monkeypatch):
        manager, logs = self._make_manager(monkeypatch)

        async def _fake_stream(messages, **kwargs):
            yield self._chunk("think")
            await asyncio.sleep(0.25)  # 静默 ≥ 阈值 0.1s
            yield self._chunk("done")

        self._attach_client(manager, _fake_stream)

        async def _collect():
            return [c async for c in manager.chat_stream([{"role": "user", "content": "hi"}])]

        chunks = asyncio.run(_collect())
        assert len(chunks) == 2, "静默恢复后流必须正常走完"
        assert any("STREAM_SILENCE" in m and "test-provider" in m for m in logs), (
            f"静默跨阈值必须留 WARNING（含 provider），got {logs!r}"
        )

    def test_no_warning_on_fast_stream(self, monkeypatch):
        manager, logs = self._make_manager(monkeypatch)

        async def _fake_stream(messages, **kwargs):
            yield self._chunk("a")
            await asyncio.sleep(0.005)  # 远小于阈值
            yield self._chunk("b")

        self._attach_client(manager, _fake_stream)

        async def _collect():
            return [c async for c in manager.chat_stream([{"role": "user", "content": "hi"}])]

        asyncio.run(_collect())
        assert not any("STREAM_SILENCE" in m for m in logs), f"快速流不得误报，got {logs!r}"

    def test_reasoning_bytes_counted_for_telemetry(self, monkeypatch):
        """已收 reasoning 长度进入静默留痕——判读'思考已吐多少'的关键证据"""
        import neurova.llm.multi_model_client as mmc

        manager, logs = self._make_manager(monkeypatch)

        async def _fake_stream(messages, **kwargs):
            yield SimpleNamespace(
                content="", reasoning_content="思考内容十二字以上吧", usage=None,
                tool_calls=None, finish_reason=None,
            )
            await asyncio.sleep(0.25)
            yield self._chunk("done")

        self._attach_client(manager, _fake_stream)

        async def _collect():
            return [c async for c in manager.chat_stream([{"role": "user", "content": "hi"}])]

        asyncio.run(_collect())
        assert any("STREAM_SILENCE" in m and "reasoning 10" in m for m in logs), (
            f"留痕必须含已收 reasoning 字数（10），got {logs!r}"
        )
