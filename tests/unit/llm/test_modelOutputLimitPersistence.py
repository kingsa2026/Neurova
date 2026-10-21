# -*- coding: utf-8 -*-
"""输出上限的持久化与运行时优先级（2026-10-21 模型管理探测）。

口径：
- `providers.json` 的 `model_metadata[model].max_output_tokens` 是一次性探测的
  持久化结果（provider+model 维度）；
- 运行时 `clamp_max_tokens` 优先级：用户显式值 > 持久化探测值 > 静态目录 > 默认；
- `None`（未配置）仍回落 DEFAULT，不被探测值越权改写。
"""

import pytest

from neurova.llm import model_limits as ml
from neurova.llm.provider_manager import LLMProviderManager


@pytest.fixture(autouse=True)
def _clearMirror():
    ml.clear_persisted_output_limits()
    yield
    ml.clear_persisted_output_limits()


class TestPersistedPrecedence:
    def testPersistedLimitOverridesStaticAndCapsExplicit(self):
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        assert ml.clamp_max_tokens(65536, "GLM-5.3-Flash", "amd") == 65536
        assert ml.clamp_max_tokens(100000, "GLM-5.3-Flash", "amd") == 65536, (
            "持久化探测值是本机验证过的上限，必须优先于静态目录/显式大值"
        )

    def testProviderKeyIsolation(self):
        ml.set_persisted_output_limit("amd", "same-name", 1234)
        assert ml.clamp_max_tokens(65536, "same-name", "amd") == 1234
        assert ml.clamp_max_tokens(65536, "same-name", "other-provider") == 65536, (
            "同名模型在不同服务商的上限不同，键必须带 provider_id"
        )

    def testNoneStillUsesDefault(self):
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 32768)
        assert ml.clamp_max_tokens(None, "GLM-5.3-Flash", "amd") == ml.DEFAULT_MAX_TOKENS


class TestProviderPersistence:
    def testSetGetReloadAndModelView(self, tmp_path):
        path = str(tmp_path / "providers.json")
        manager = LLMProviderManager(config={"config_path": path})
        provider = next(p for p in manager.list_providers() if p.models)
        model = provider.models[0]

        assert manager.set_model_output_limit(provider.id, model, 65536, source="probed")
        assert manager.get_model_output_limit(provider.id, model) == 65536
        assert ml.get_persisted_output_limit(provider.id, model) == 65536

        reloaded = LLMProviderManager(config={"config_path": path})
        assert reloaded.get_model_output_limit(provider.id, model) == 65536
        view = next(
            v for v in reloaded.get_all_models()
            if v.id == model and v.owned_by == provider.id
        )
        assert view.max_output_tokens == 65536
        assert view.max_output_tokens_source == "probed"
        assert view.max_output_tokens_probed_at


class TestParseProviderLimit:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("... max_model_len=max_total_tokens=262144. ...", 262144),
            ("This model's maximum context length is 262144 tokens.", 262144),
            ("cannot be greater than max_model_len=131072", 131072),
            ("model is not supported by TokenPlan", None),
        ],
    )
    def testParse(self, text, expected):
        assert LLMProviderManager._parseOutputLimitFromError(text) == expected
