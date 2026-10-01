"""探测**下不了结论**时不许写成"实测不支持图"（T-09 · U-05 落地时活体撞出来的）。

## 为什么会红

2026-10-01 对活跃模型跑真探测，服务商回的是网关错：

```
probe_source = "inconclusive"
probe_detail = "HTTP 400: Model id : moonshotai/Kimi-K2.6 , has no provider supported"
```

`openai_provider.py:488` 把这类情况明确标成"无法下结论"，但
`_persist_probe_result` 不看这个标记，照样：

1. 往 `model_metadata` 盖 `probe_source="probed"`；
2. 往进程级缓存 `learn(supports_multimodal=False)`。

后果比"读数难看"大两条：`maybe_probe_multimodal` 见到 `probe_source=="probed"` 就**不再重探**
（一次限频/网络抖变成永久结论），而 `capability_state._probeVision` 的实测档读到那条 False，
会把 `capabilities.vision` 报成 `configured-unreachable`——T-09 的附图闸门于是**基于一个
从没成立过的测量**永久关闭。这与 T-12 打的是同一类形状："没拿到事实"被当成"事实是没有"。

## 判据口径

不 mock 探测函数：喂给写侧的 `ProbeResult` 就是生产 provider 会回的那三种形状
（inconclusive / media_rejected / 正证），断言的是**元数据与缓存的实际状态**。
"""
import threading

import pytest

from neurova.llm.model_capability_cache import (
    CAP_SUPPORTS_MULTIMODAL,
    ModelCapabilityCache,
    reset_capability_cache,
)
from neurova.llm.provider_manager import LLMProviderManager
from neurova.llm.providers.types import ProbeResult

MODEL_ID = "m-gateway-broken"


class _Provider:
    def __init__(self, model_metadata=None):
        self.id = "probe"
        self.model_metadata = dict(model_metadata or {})


class _WriterSelf:
    """只借 `_persist_probe_result` 的锁与写回逻辑；落盘摘掉，不碰用户配置。"""

    _config_lock = threading.RLock()

    def __init__(self):
        self.saved = 0

    def _save_config(self) -> None:
        self.saved += 1


def _persist(result: ProbeResult, provider: _Provider) -> _WriterSelf:
    writer = _WriterSelf()
    LLMProviderManager._persist_probe_result(writer, provider, MODEL_ID, result)
    return writer


def test_inconclusiveProbeWritesNoMeasuredStampAndLearnsNothing():
    """网关错 ⇒ 元数据不许被盖成"已探测"，缓存里也不许出现 False，且压根不该落盘。"""
    reset_capability_cache()
    provider = _Provider({})
    try:
        result = ProbeResult(
            model_id=MODEL_ID,
            supported=False,
            capabilities=[],
            metadata={"probe_source": "inconclusive",
                      "probe_detail": "HTTP 400: Model id : x , has no provider supported"},
        )
        writer = _persist(result, provider)

        entry = provider.model_metadata.get(MODEL_ID) or {}
        assert entry.get("probe_source") != "probed", (
            f"下不了结论却盖了 probed——后台探测从此不再重探：{entry}"
        )
        assert "probed_at" not in entry, entry
        assert ModelCapabilityCache.get_instance().get(
            f"{provider.id}:{MODEL_ID}", CAP_SUPPORTS_MULTIMODAL) is None, \
            "inconclusive 被当成实测结论学了进去"
        assert writer.saved == 0, "没结论也写了一次用户配置"
    finally:
        reset_capability_cache()


def test_inconclusiveDoesNotEraseAnExistingVisionMark():
    """已有 vision 标记的模型，撞上一次网关错 ⇒ 标记必须原样留着（幂等不等于覆盖）。"""
    reset_capability_cache()
    provider = _Provider({MODEL_ID: {"capabilities": ["vision", "text"]}})
    try:
        _persist(ProbeResult(model_id=MODEL_ID, supported=False, capabilities=[],
                             metadata={"probe_source": "inconclusive"}), provider)
        assert provider.model_metadata[MODEL_ID]["capabilities"] == ["vision", "text"]
    finally:
        reset_capability_cache()


def test_mediaRejectionIsTheOnlyPathThatStripsVision():
    """真否证（媒体被拒）才允许摘掉 vision 并学 False——这条不许被上一条的修法顺手关掉。"""
    reset_capability_cache()
    provider = _Provider({MODEL_ID: {"capabilities": ["vision"]}})
    try:
        _persist(ProbeResult(model_id=MODEL_ID, supported=False, capabilities=[],
                             metadata={"probe_source": "probed",
                                       "probe_detail": "media_rejected"}), provider)
        assert "vision" not in provider.model_metadata[MODEL_ID]["capabilities"]
        assert ModelCapabilityCache.get_instance().get(
            f"{provider.id}:{MODEL_ID}", CAP_SUPPORTS_MULTIMODAL) is False
        assert provider.model_metadata[MODEL_ID]["probe_source"] == "probed"
    finally:
        reset_capability_cache()


def test_positiveProbeStillPersistsAndLearnsTrue():
    """正证照旧写 probed 并学 True（改形的唯一目的是不再误判，不是把探测写废）。"""
    reset_capability_cache()
    provider = _Provider({})
    try:
        _persist(ProbeResult(model_id=MODEL_ID, supported=True, capabilities=["vision"],
                             metadata={"probe_source": "probed"}), provider)
        assert "vision" in provider.model_metadata[MODEL_ID]["capabilities"]
        assert ModelCapabilityCache.get_instance().get(
            f"{provider.id}:{MODEL_ID}", CAP_SUPPORTS_MULTIMODAL) is True
    finally:
        reset_capability_cache()

