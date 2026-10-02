"""网关把某个采样值钉死时，客户端照发 `LLMConfig` 默认值必然 400（T-18 主体 · 回执学习）。

## 为什么会红

2026-10-01 活体实测（工单集 §35.2）：商汤网关的 kimi-k3 把 `temperature` 钉成 1、
`top_p` 钉成 0.95，而 `LLMConfig` 默认发 0.7 / 1.0 ⇒ 这个模型上**任何一次真实对话
第一发就 400**，不是偶发：

```
400 field Temperature invalid, only 1 is allowed for this model   (param=temperature)
400 field TopP invalid, only 0.95 is allowed for this model        (param=top_p)
```

能提前知道"这个模型钉死了"的信息源都不存在（三条都实测过）：

- 模型档案 `supported_sampling_parameters` 只列名字、**不列值域**，且全仓零消费方；
- `ProviderCompat` 是 per-provider/per-host/per-protocol 三个维度，钉死是 **per-model**，
  维度装不下；
- A2 量测（2026-10-02，10 在册模型 × temperature=0.7）：5 个明确**受理**、1 个钉死、
  4 个因 403/404 判不了 ⇒ "整个 sensetime 都不发 temperature" 会把 5 个可用模型的
  旋钮白白摘掉。**唯一不误伤的信息源是网关回执本身。**

所以本片把回执接成闭环：命中"字段被钉死"的 400 → 按 `provider_id:model` 学进
`ModelCapabilityCache`（天生 per-model、带 TTL）→ 咽喉 `_build_request_params`
按学习态摘键 → 本次请求摘键重发一次，用户不再看到那个 400。

## 判据口径

装配点与 `chat()` 全走生产路径，假件只替换 SDK 传输面
（`client.chat.completions.create`），断言两件事：
① 逐次请求**实际携带的键**；② 能力缓存里的**实际学习状态**。

两类判据分开看，别混：
- **新行为判据**（摘键、回执重发、学习落库）在未接线的 HEAD 上必红；
- **反向控制判据**（未学习过的模型必须照发全部采样键、无关 400 必须原样上抛且不重发）
  在 HEAD 上应绿——它钉的是"别把能力修成永不发"和"别把回执解析扩成盲重试"。
"""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("openai")

import httpx

from neurova.llm.model_capability_cache import (
    CAP_REJECTED_SAMPLING_PARAMS,
    get_capability_cache,
    reset_capability_cache,
)
from neurova.llm.sampling_receipt import (
    SAMPLING_PARAM_KEYS,
    rejectedSamplingParam,
)
from neurova.llm_client import LLMBadRequestError, LLMClient, LLMConfig

PIN_TEMPERATURE = "field Temperature invalid, only 1 is allowed for this model"
PIN_TOP_P = "field TopP invalid, only 0.95 is allowed for this model"
UNRELATED_400 = (
    "Model id : some/Model , has no provider supported"
)

PROVIDER = "tp-pin"
MODEL = "m-tp-pin"


def _badRequest(message):
    """生产形态的网关 400：openai.BadRequestError，回执文案在 .message 里。"""
    from openai import BadRequestError

    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    resp = httpx.Response(400, request=req)
    return BadRequestError(message, response=resp, body=None)


def _response(text="ok"):
    """chat() 成功路径要读的最小响应形状（choices/usage/model/id）。"""
    return SimpleNamespace(
        id="resp-1",
        model=MODEL,
        usage=None,
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=text, tool_calls=None),
            finish_reason="stop",
        )],
    )


def _chunk(text):
    return SimpleNamespace(
        id="chunk-1",
        model=MODEL,
        usage=None,
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=text, tool_calls=None),
            finish_reason="stop",
        )],
    )


class _FakeCompletions:
    """SDK 传输面替身：按脚本报错或回包，并逐次记下收到的 kwargs。

    脚本耗尽后重复最后一项——"这个模型永远钉死 temperature"就用单项脚本表达。
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def _next(self):
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        outcome = self._next()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeStreamCompletions(_FakeCompletions):
    """流式 create 回的是可迭代对象，不是响应体。"""

    def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        outcome = self._next()
        if isinstance(outcome, BaseException):
            raise outcome
        return iter(outcome)


class _AsyncChunks:
    """`async for` 消费的分片序列（chat_stream_async 读的就是这个形状）。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


class _FakeAsyncCompletions(_FakeCompletions):
    """异步传输面：`await create(**kwargs)` 返回可 `async for` 的对象。"""

    async def __call__(self, **kwargs):
        self.calls.append(dict(kwargs))
        outcome = self._next()
        if isinstance(outcome, BaseException):
            raise outcome
        return _AsyncChunks(outcome)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """能力缓存逐用例重置；记账/指标/成本账本全替身，测试不写真实 SQLite。"""
    reset_capability_cache()
    for path, value in (
        ("neurova.core.usage_accounting.get_usage_accounting", lambda: SimpleNamespace(record=lambda **kw: None)),
        ("neurova.core.usage_accounting.set_task_last_call", lambda x: x),
        ("neurova.core.usage_history.get_usage_history", lambda: SimpleNamespace()),
        ("neurova.core.metrics.get_metrics", lambda: SimpleNamespace()),
        ("neurova.core.identity_context.get_request_user_id", lambda: None),
        # LLMClient 成功路径会走 record_llm_cost → 账本未装配时静默降级
        ("neurova.models.cost_store.get_llm_cost_store", lambda: None),
    ):
        monkeypatch.setattr(path, value, raising=False)
    yield
    reset_capability_cache()


def _client(script, mode="chat"):
    """真 LLMClient + 假传输面：provider_id 必须来自生产装配口。

    mode 决定接线到哪个客户端：chat/chat_stream 用同步 client，
    chat_stream_async 用 async_client——三条链共用同一个 `_next()` 脚本口径。
    """
    client = LLMClient(LLMConfig(model=MODEL), provider_id=PROVIDER)
    factory = {"chat": _FakeCompletions, "stream": _FakeStreamCompletions,
               "async_stream": _FakeAsyncCompletions}[mode]
    fake = factory(script)
    transport = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake)))
    if mode == "async_stream":
        client.async_client = transport
    else:
        client.client = transport
    return client, fake


class TestReceiptParsing:
    """回执文案里点名哪个字段被钉死——解析必须只认在册采样键，别的字段不猜。"""

    def test_temperatureReceiptMapsToWireKey(self):
        assert rejectedSamplingParam(PIN_TEMPERATURE) == "temperature"

    def test_topPReceiptMapsToWireKey(self):
        """网关写 `TopP`，我们线上的键是 `top_p`：别名必须从在册键派生而非另立一张表。"""
        assert rejectedSamplingParam(PIN_TOP_P) == "top_p"

    def test_unrelatedGatewayMessageYieldsNoVerdict(self):
        assert rejectedSamplingParam(UNRELATED_400) is None

    def test_fieldOutsideSamplingKeysIsNotGuessed(self):
        """`MaxTokens` 被钉死不属于本链可摘的键：摘 max_tokens 会改输出预算语义。"""
        assert rejectedSamplingParam(
            "field MaxTokens invalid, only 8 is allowed for this model") is None

    def test_missingMessageIsNotAVerdict(self):
        assert rejectedSamplingParam(None) is None
        assert rejectedSamplingParam("") is None


class TestAssemblyConsultsTheCache:
    def test_unlearnedModelSendsEverySamplingKey(self):
        """反向控制：没学过钉子就必须照发——否则本片把能力修成了"永不发"。"""
        client, _ = _client([_response()])
        params = client._build_request_params([{"role": "user", "content": "hi"}])
        for key in SAMPLING_PARAM_KEYS:
            assert key in params, f"{key} 被无端摘掉了"

    def test_learnedRejectionDropsOnlyThatKey(self):
        """学过 temperature 钉死 ⇒ 只摘 temperature，top_p 等其余照发（per-model 判定不扩散）。"""
        get_capability_cache().learn(
            f"{PROVIDER}:{MODEL}", CAP_REJECTED_SAMPLING_PARAMS, frozenset({"temperature"}))
        client, _ = _client([_response()])
        params = client._build_request_params([{"role": "user", "content": "hi"}])
        assert "temperature" not in params
        for key in SAMPLING_PARAM_KEYS:
            if key != "temperature":
                assert key in params

    def test_learningIsScopedToThatProviderModel(self):
        """同型号在别的提供方 / 同提供方的别的模型不许被牵连：键是 provider_id:model。"""
        get_capability_cache().learn(
            f"{PROVIDER}:{MODEL}", CAP_REJECTED_SAMPLING_PARAMS, frozenset({"temperature"}))
        other = LLMClient(LLMConfig(model=MODEL), provider_id="tp-other")
        assert "temperature" in other._build_request_params(
            [{"role": "user", "content": "hi"}])
        sibling = LLMClient(LLMConfig(model="m-tp-sibling"), provider_id=PROVIDER)
        assert "temperature" in sibling._build_request_params(
            [{"role": "user", "content": "hi"}])

    def test_everySamplingKeyTheThroatSendsIsUnderDiscipline(self):
        """咽喉发的键必须要么在册受采样纪律管、要么点名豁免——新增键漏登记即红。

        非流式与流式两条组装都扫，豁免名单里没登记过的键（如将来新加的
        `response_format`）会立刻落进 unexplained。
        """
        exempt = {
            "model", "messages", "max_tokens", "stream", "stream_options", "tools",
            "tool_choice", "reasoning_effort", "enable_thinking", "thinking_budget",
        }
        client, _ = _client([_response()])
        emitted = set(client._build_request_params(
            [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]))
        emitted |= set(client._build_request_params(
            [{"role": "user", "content": "hi"}], stream=True))
        unexplained = emitted - set(SAMPLING_PARAM_KEYS) - exempt
        assert not unexplained, f"未登记的请求键：{sorted(unexplained)}"


class TestFirstFailureSelfHeals:
    def test_pinnedModelLearnsOnFirstFailureAndSucceedsOnRetry(self):
        """用户视角：第一发撞钉子，本次请求摘键重发并成功——400 不再抛给上层。"""
        client, fake = _client([_badRequest(PIN_TEMPERATURE), _response("你好")])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result.content == "你好"
        assert len(fake.calls) == 2
        assert "temperature" in fake.calls[0]
        assert "temperature" not in fake.calls[1]
        assert get_capability_cache().get(
            f"{PROVIDER}:{MODEL}", CAP_REJECTED_SAMPLING_PARAMS) == frozenset({"temperature"})

    def test_secondCallNeverSendsTheLearnedKey(self):
        """学习态生效于装配处，不靠每次都撞一次 400 再重试。"""
        client, fake = _client([
            _badRequest(PIN_TEMPERATURE), _response("a"), _response("b"),
        ])
        client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == 2, "首轮=撞钉子 1 发 + 摘键重发 1 发"
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result.content == "b"
        assert len(fake.calls) == 3, "第二轮只发了 1 次——它压根没再撞 400"
        assert "temperature" not in fake.calls[2]

    def test_twoPinnedKeysAreBothLearnedInOneRound(self):
        """网关逐个拒：temperature 摘掉重发后撞上 top_p，同轮内两颗都学进。"""
        client, fake = _client([
            _badRequest(PIN_TEMPERATURE),
            _badRequest(PIN_TOP_P),
            _response("ok"),
        ])
        result = client.chat([{"role": "user", "content": "hi"}])
        assert result.content == "ok"
        assert len(fake.calls) == 3
        assert "temperature" not in fake.calls[1] and "top_p" in fake.calls[1]
        assert "top_p" not in fake.calls[2]
        assert get_capability_cache().get(
            f"{PROVIDER}:{MODEL}", CAP_REJECTED_SAMPLING_PARAMS) == \
            frozenset({"temperature", "top_p"})

    def test_streamAppliesTheSameReceipt(self):
        client, fake = _client(
            [_badRequest(PIN_TEMPERATURE), [_chunk("你"), _chunk("好")]], mode="stream")
        chunks = list(client.chat_stream([{"role": "user", "content": "hi"}]))
        assert [c.content for c in chunks][-1] == "好"
        assert len(fake.calls) == 2
        assert "temperature" not in fake.calls[1]

    def test_asyncStreamAppliesTheSameReceipt(self):
        client, fake = _client(
            [_badRequest(PIN_TEMPERATURE), [_chunk("你"), _chunk("好")]], mode="async_stream")

        async def collect():
            return [c async for c in client.chat_stream_async(
                [{"role": "user", "content": "hi"}])]

        chunks = asyncio.run(collect())
        assert [c.content for c in chunks][-1] == "好"
        assert len(fake.calls) == 2
        assert "temperature" not in fake.calls[1]


class TestReceiptDiscipline:
    """回执判据不许扩成盲重试：认不出的失败必须原样上抛，且一次都不重发。"""

    def test_unrelatedBadRequestIsNotRetried(self):
        client, fake = _client([_badRequest(UNRELATED_400)])
        with pytest.raises(LLMBadRequestError):
            client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == 1, "无关 400 被重发了——回执解析已退化成盲重试"
        assert get_capability_cache().get(
            f"{PROVIDER}:{MODEL}", CAP_REJECTED_SAMPLING_PARAMS) is None

    def test_retryIsBoundedWhenTheKeyIsAlreadyGone(self):
        """网关永远回同一句 temperature 钉子（哪怕我们已不发它）：必须有界收场。

        摘键循环的终止条件是"该键确实还在本次请求里"，学过一次后第二次摘不动即上抛，
        因此总请求数 = 1（撞钉子）+ 1（摘键重发）后终止，不会转圈。
        """
        client, fake = _client([_badRequest(PIN_TEMPERATURE)])
        with pytest.raises(LLMBadRequestError):
            client.chat([{"role": "user", "content": "hi"}])
        assert len(fake.calls) == 2

    def test_learnedKeySurvivesFreshClientInstance(self):
        """学习态在进程级缓存，不在客户端实例上：换客户端不重犯同一个 400。"""
        first, _ = _client([_badRequest(PIN_TEMPERATURE), _response("a")])
        first.chat([{"role": "user", "content": "hi"}])
        second, second_fake = _client([_response("b")])
        assert second.chat([{"role": "user", "content": "hi"}]).content == "b"
        assert len(second_fake.calls) == 1
        assert "temperature" not in second_fake.calls[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
