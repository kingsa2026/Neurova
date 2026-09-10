"""M-?/L-05 回归测试：update_provider 改 api_key/base_url 后必须失效实例缓存。

红绿：无修复时 _provider_instances 把实例永久缓存，update_provider 改 key 后
不失效 → 第二次 _get_provider_instance 仍返回旧实例（api_key=="a"，即"填了 key 还是 401"）
→ 断言 inst2.api_key == "b" 失败（红）；修复后（update_provider 内 pop 缓存）→ 绿。
"""

from types import SimpleNamespace
from unittest.mock import patch

import neurova.llm.provider_manager as pm_mod
from neurova.llm.provider_manager import LLMProviderManager


class FakeProvider:
    def __init__(self, provider_id=None, provider_type=None, api_key="", base_url=""):
        self.api_key = api_key
        self.base_url = base_url


def test_l05_cache_invalidated_on_update():
    fake_cfg = SimpleNamespace(
        id="p1",
        provider="openai",
        api_key="a",
        base_url="",
        models=None,
        model_metadata=None,
        name="p1",
    )

    with patch.object(LLMProviderManager, "_load_config", lambda self: None), \
         patch.object(LLMProviderManager, "_save_config", lambda self: None):
        mgr = LLMProviderManager(config={})
        mgr._providers = {"p1": fake_cfg}

        target = "neurova.llm.providers"
        with patch(f"{target}.OpenAIProvider", FakeProvider), \
             patch(f"{target}.AnthropicProvider", FakeProvider), \
             patch(f"{target}.GeminiProvider", FakeProvider), \
             patch(f"{target}.OllamaProvider", FakeProvider), \
             patch(f"{target}.OpenCodeProvider", FakeProvider), \
             patch(f"{target}.OpenRouterProvider", FakeProvider):

            inst1 = mgr._get_provider_instance("p1")
            assert inst1.api_key == "a"

            mgr.update_provider("p1", api_key="b")

            inst2 = mgr._get_provider_instance("p1")
            assert inst2.api_key == "b", "L-05: update_provider 后旧实例缓存必须失效"
