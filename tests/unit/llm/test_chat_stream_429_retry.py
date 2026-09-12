"""429 同模型等待重试 + 切换容错（ZCode 对齐）单元测试。

契约（2026-09-11 用户需求）：
- 流式 429：同模型等待重试（默认 ≤10 次、间隔 10s、服务端 Retry-After 优先、
  单次等待封顶 120s），每次等待 yield ``{"retry_status": {"phase": "waiting", ...}}``
  供前端倒计时显示
- 同模型重试预算耗尽 → 切下一候选模型（failover），同一 messages 全量透传
  （上下文连续），切换动作 yield switched 事件提示用户
- 切换容错：连续失败模型计数 ≤ ``NEUROVA_LLM_MAX_SWITCHES``（默认 5）；
  任一模型成功出过内容（"链接成功"）→ 计数归零重计
- 已吐部分内容后失败：重试/切换事件带 ``reset=True``（消费方清空半截回复
  再重来），避免内容重复拼接（ZCode 重试替换语义）
- 全部耗尽 → exhausted 事件 + 流内错误 dict（本轮此时才死）
- 非流式 chat()：429 同模型等待重试后仍失败才走既有 failover；等待重试绕过
  per-provider 快速重试/熔断（10 次重试预算不喂爆 5 次阈值的熔断器）
- 限流器新增 clear_pause：主动重试路径清除自身 429 暂停——工具循环续轮
  撞上本轮自己上报的暂停不再断流
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("openai")

from neurova.llm_client import LLMConnectionError, LLMRateLimitError, LLMResponse
from neurova.llm.model_rate_limiter import get_shared_limiter, reset_shared_limiter
from neurova.llm.multi_model_client import MultiModelLLMClient, _get_429_retry_config

RL = lambda msg="Error code: 429 - Too Many Requests": LLMRateLimitError(msg)  # noqa: E731
CONN = lambda msg="connection reset by peer": LLMConnectionError(msg)  # noqa: E731


def _chunk(text):
    return SimpleNamespace(content=text, reasoning_content=None, usage=None,
                           tool_calls=None, finish_reason=None)


class _ScriptedStream:
    """按脚本出牌的内层异步流（chat_stream_async）。

    脚本项：Exception → 立即抛；list → 逐个 yield（末项若为 Exception 则
    吐完前面的 chunk 后抛——模拟中流断掉）。
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def chat_stream_async(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        for piece in item:
            if isinstance(piece, Exception):
                raise piece
            yield piece


class _ScriptedInner:
    """按脚本出牌的内层同步 chat（模拟 LLMClient.chat，非流式路径用）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(1)
        behavior = self.script.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _stream_client(inner, model, provider="p1"):
    return SimpleNamespace(client=inner, model=model,
                           provider=SimpleNamespace(id=provider),
                           increment_request=MagicMock())


def _make_mmc(client, failover_chain=None):
    """绕 __init__ 构造最小 mmc；failover_chain 为候选列表（逐次弹出，None 结束）。"""
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: client
    chain = list(failover_chain or [])

    def _next(failed_model, excluded=None):
        return chain.pop(0) if chain else None

    mmc._next_failover_client = _next
    mmc._sleeps = []

    async def _fake_sleep(seconds):
        mmc._sleeps.append(seconds)

    mmc._sleep_for_retry = _fake_sleep
    return mmc


async def collect(agen):
    return [c async for c in agen]


def _split(items):
    statuses = [c["retry_status"] for c in items if isinstance(c, dict) and c.get("retry_status")]
    errors = [c for c in items if isinstance(c, dict) and c.get("error")]
    chunks = [c for c in items if not isinstance(c, dict)]
    return statuses, errors, chunks


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_shared_limiter()
    # 单例 __new__ 使熔断器实例字典跨文件共享——防其他文件遗留的打开态熔断器
    inst = MultiModelLLMClient._instance
    if inst is not None and hasattr(inst, "_retry_guards_inst"):
        inst._retry_guards_inst = {}
    for key in ("NEUROVA_LLM_429_MAX_RETRIES", "NEUROVA_LLM_429_RETRY_INTERVAL",
                "NEUROVA_LLM_429_WAIT_CAP", "NEUROVA_LLM_MAX_SWITCHES"):
        monkeypatch.delenv(key, raising=False)
    # usage/指标单例隔离：测试不写真实 SQLite/指标
    ua = MagicMock()
    ua.record.return_value = {"id": 1}
    monkeypatch.setattr("neurova.core.usage_accounting.get_usage_accounting", lambda: ua)
    monkeypatch.setattr("neurova.core.usage_accounting.set_task_last_call", lambda x: x)
    monkeypatch.setattr("neurova.core.usage_history.get_usage_history", lambda: MagicMock())
    monkeypatch.setattr("neurova.core.metrics.get_metrics", lambda: MagicMock())
    monkeypatch.setattr("neurova.core.identity_context.get_request_user_id", lambda: None)
    yield
    reset_shared_limiter()


class TestRetryConfig:
    def test_defaults(self):
        cfg = _get_429_retry_config()
        assert cfg == {"max_retries": 10, "interval": 10.0, "cap": 120.0, "max_switches": 5}

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "3")
        monkeypatch.setenv("NEUROVA_LLM_429_RETRY_INTERVAL", "2.5")
        monkeypatch.setenv("NEUROVA_LLM_429_WAIT_CAP", "60")
        monkeypatch.setenv("NEUROVA_LLM_MAX_SWITCHES", "2")
        cfg = _get_429_retry_config()
        assert cfg == {"max_retries": 3, "interval": 2.5, "cap": 60.0, "max_switches": 2}

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_429_RETRY_INTERVAL", "abc")
        assert _get_429_retry_config()["interval"] == 10.0


class TestLimiterClearPause:
    def test_clear_pause_removes_pause(self):
        limiter = get_shared_limiter()
        limiter.report_429("m", pause_seconds=30)
        assert limiter.pause_remaining("m") > 0
        limiter.clear_pause("m")
        assert limiter.pause_remaining("m") == 0.0

    def test_clear_pause_keeps_consecutive_counter(self):
        """清暂停不清连续 429 计数（其他路径的退避升级不受主动重试影响）。"""
        limiter = get_shared_limiter()
        limiter.report_429("m", pause_seconds=30)
        limiter.clear_pause("m")
        assert limiter._consecutive_429.get("m") == 1


class TestChatStreamSameModelRetry:
    @pytest.mark.asyncio
    async def test_rate_limited_retries_same_model_and_succeeds(self):
        inner = _ScriptedStream([RL(), [_chunk("你"), _chunk("好")]])
        client = _stream_client(inner, "model-a")
        mmc = _make_mmc(client)

        items = await collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        statuses, errors, chunks = _split(items)
        assert [c.content for c in chunks] == ["你", "好"]
        assert errors == []
        assert len(inner.calls) == 2  # 失败一次 + 重试成功
        assert mmc._sleeps == [10.0]  # 默认间隔 10s
        assert len(statuses) == 1
        s = statuses[0]
        assert s["phase"] == "waiting"
        assert s["retry"] == 1 and s["max_retries"] == 10
        assert s["wait_seconds"] == 10.0
        assert s["model"] == "model-a"
        assert s["reason"] == "rate_limited"
        assert "reset" not in s  # 未吐过内容，无需重置

    @pytest.mark.asyncio
    async def test_retry_after_header_overrides_interval(self):
        err = RL()
        err.response = SimpleNamespace(headers={"retry-after": "7"})
        inner = _ScriptedStream([err, [_chunk("ok")]])
        mmc = _make_mmc(_stream_client(inner, "model-a"))

        await collect(mmc.chat_stream([{"role": "user", "content": "hi"}]))

        assert mmc._sleeps == [7.0]  # 服务端 Retry-After 优先于默认间隔

    @pytest.mark.asyncio
    async def test_wait_capped_at_maximum(self):
        err = RL()
        err.response = SimpleNamespace(headers={"retry-after": "500"})
        inner = _ScriptedStream([err, [_chunk("ok")]])
        mmc = _make_mmc(_stream_client(inner, "model-a"))

        statuses, _, _ = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert mmc._sleeps == [120.0]  # 封顶 120s
        assert statuses[0]["wait_seconds"] == 120.0

    @pytest.mark.asyncio
    async def test_pre_paused_acquire_retries_instead_of_dying(self):
        """工具循环续轮撞上本轮自己上报的 429 暂停：等待重试而非立即断流。"""
        limiter = get_shared_limiter()
        limiter.report_429("model-a", pause_seconds=5)
        inner = _ScriptedStream([[_chunk("ok")]])
        mmc = _make_mmc(_stream_client(inner, "model-a"))

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert [c.content for c in chunks] == ["ok"]
        assert errors == []
        assert mmc._sleeps == [10.0]
        assert statuses[0]["phase"] == "waiting"

    @pytest.mark.asyncio
    async def test_midstream_429_resets_partial_and_retries(self):
        """中流断掉：先 reset（消费方清空半截回复）再同模型重试，避免重复拼接。"""
        inner = _ScriptedStream([[_chunk("部分"), RL()], [_chunk("全")]])
        mmc = _make_mmc(_stream_client(inner, "model-a"))

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert [c.content for c in chunks] == ["部分", "全"]
        assert errors == []
        assert mmc._sleeps == [10.0]
        assert statuses[0]["phase"] == "waiting"
        assert statuses[0]["reset"] is True  # 半截内容已吐，必须重置


class TestChatStreamFailover:
    @pytest.mark.asyncio
    async def test_exhausted_retries_switch_with_same_messages(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "2")
        inner_a = _ScriptedStream([RL(), RL(), RL()])  # 首次 + 2 次重试全失败
        inner_b = _ScriptedStream([[_chunk("b-ok")]])
        client_a = _stream_client(inner_a, "model-a", "pa")
        client_b = _stream_client(inner_b, "model-b", "pb")
        mmc = _make_mmc(client_a, failover_chain=[client_b])

        messages = [{"role": "user", "content": "hi"}]
        statuses, errors, chunks = _split(await collect(mmc.chat_stream(messages)))

        assert [c.content for c in chunks] == ["b-ok"]
        assert errors == []
        assert len(inner_a.calls) == 3
        assert mmc._sleeps == [10.0, 10.0]
        # 上下文连续：候选模型收到同一份 messages
        assert inner_b.calls[0] == messages
        switched = [s for s in statuses if s["phase"] == "switched"]
        assert len(switched) == 1
        assert switched[0]["model"] == "model-b"
        assert switched[0]["from_model"] == "model-a"
        assert switched[0]["fail_count"] == 1 and switched[0]["max_switches"] == 5

    @pytest.mark.asyncio
    async def test_switch_chain_budget_exhausts_then_error(self, monkeypatch):
        """连续失败模型数达上限（无任何链接成功）→ exhausted 事件 + 错误收尾。"""
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "1")
        monkeypatch.setenv("NEUROVA_LLM_MAX_SWITCHES", "2")
        inner_a = _ScriptedStream([RL(), RL()])  # 首次 + 1 重试
        inner_b = _ScriptedStream([RL(), RL()])
        client_a = _stream_client(inner_a, "model-a")
        client_b = _stream_client(inner_b, "model-b")
        mmc = _make_mmc(client_a, failover_chain=[client_b])  # 之后无候选

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert chunks == []
        assert len(errors) == 1
        assert errors[0]["error_type"] == "rate_limited"
        assert len(inner_a.calls) == 2 and len(inner_b.calls) == 2
        assert mmc._sleeps == [10.0, 10.0]
        switched = [s for s in statuses if s["phase"] == "switched"]
        assert len(switched) == 1  # A→B 一次切换
        exhausted = [s for s in statuses if s["phase"] == "exhausted"]
        assert len(exhausted) == 1
        assert exhausted[0]["fail_count"] == 2  # A、B 两个模型连续失败（≤5 归零重计口径）

    @pytest.mark.asyncio
    async def test_transient_error_switches_immediately(self):
        inner_a = _ScriptedStream([CONN()])
        inner_b = _ScriptedStream([[_chunk("b-ok")]])
        mmc = _make_mmc(_stream_client(inner_a, "model-a"),
                        failover_chain=[_stream_client(inner_b, "model-b")])

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert [c.content for c in chunks] == ["b-ok"]
        assert errors == []
        assert mmc._sleeps == []  # 非 429 不等待，直接切换
        assert len(inner_a.calls) == 1
        switched = [s for s in statuses if s["phase"] == "switched"]
        assert switched[0]["reason"] == "transient"

    @pytest.mark.asyncio
    async def test_connection_success_resets_fail_budget(self, monkeypatch):
        """"链接成功"归零：B 成功出过内容后再失败，失败计数从 0 重计。

        max_switches=2：A 未连接即失败（计数 1→切 B）；B 出过内容后死亡
        （归零后 +1=1→切 C）；C 未连接失败（计数 2，达上限）→ 本轮才死。
        无归零语义时 B 死后计数已是 2，C 根本不会被尝试。
        """
        monkeypatch.setenv("NEUROVA_LLM_MAX_SWITCHES", "2")
        inner_a = _ScriptedStream([CONN()])
        inner_b = _ScriptedStream([[_chunk("b1"), CONN()]])  # 连接成功后中流死亡
        inner_c = _ScriptedStream([RL(), RL()])  # max_retries=1 默认未改 → 用 10 次太多，改由 env 控
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "1")
        inner_c = _ScriptedStream([RL(), RL()])
        client_b = _stream_client(inner_b, "model-b")
        client_c = _stream_client(inner_c, "model-c")
        mmc = _make_mmc(_stream_client(inner_a, "model-a"), failover_chain=[client_b, client_c])

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        # C 被尝试过 = B 的"链接成功"把失败计数归零了
        assert len(inner_c.calls) == 2
        assert len(errors) == 1
        switched = [s for s in statuses if s["phase"] == "switched"]
        assert len(switched) == 2
        # A→B：A 未连接过，无 reset，失败计数 1
        assert "reset" not in switched[0]
        assert switched[0]["fail_count"] == 1
        # B→C：B"链接成功"过 → 归零后 +1=1，切换带 reset（半截内容作废）
        assert switched[1]["reset"] is True
        assert switched[1]["fail_count"] == 1

    @pytest.mark.asyncio
    async def test_midstream_transient_switch_carries_reset(self):
        """中流 transient 死亡 → 带 reset 的切换事件，新模型重出全文。"""
        inner_a = _ScriptedStream([[_chunk("半截"), CONN()]])
        inner_b = _ScriptedStream([[_chunk("完整")]])
        mmc = _make_mmc(_stream_client(inner_a, "model-a"),
                        failover_chain=[_stream_client(inner_b, "model-b")])

        statuses, errors, chunks = _split(await collect(mmc.chat_stream([{"role": "user", "content": "hi"}])))

        assert [c.content for c in chunks] == ["半截", "完整"]
        assert errors == []
        switched = [s for s in statuses if s["phase"] == "switched"]
        assert switched[0]["reset"] is True


class TestChatNonStream429:
    def _chat_mmc(self, script, failover_chain=None):
        inner = _ScriptedInner(script)
        client = SimpleNamespace(client=inner, model="test-model",
                                 provider=SimpleNamespace(id="p1"),
                                 increment_request=MagicMock())
        mmc = _make_mmc(client, failover_chain=failover_chain)
        return mmc, inner

    @pytest.mark.asyncio
    async def test_same_model_429_waits_then_retries(self):
        """内层 3 次快速重试耗尽 → 外层等 10s 绕过熔断直调 → 成功。"""
        mmc, inner = self._chat_mmc([RL(), RL(), RL(), LLMResponse(content="ok")])

        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is True
        assert len(inner.calls) == 4
        assert mmc._sleeps == [10.0]

    @pytest.mark.asyncio
    async def test_429_budget_bypasses_circuit_breaker(self):
        """10 次重试预算不被 5 次阈值的熔断器截断（直调不喂熔断计数）。"""
        mmc, inner = self._chat_mmc([RL()] * 13, failover_chain=[None])  # 3 快速 + 10 等待重试

        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is False
        assert len(inner.calls) == 13
        assert len(mmc._sleeps) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
