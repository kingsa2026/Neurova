"""L-20 回归测试：模型匹配单源函数 _model_matches 支持版本后缀。

红绿：无修复时模型匹配只有 `client.model == model or
client.model.endswith(model)`——请求 "qwen-plus" 命中不了客户端名
"qwen-plus-latest"（也不支持反向/preview 后缀）。断言：相等或任一方
剥掉 -latest/-preview 后相等；get_client 与 _get_client_for_request
两处消费同一匹配语义。
"""

from types import SimpleNamespace

import pytest

import neurova.llm.multi_model_client as mmc
from neurova.llm.multi_model_client import MultiModelLLMClient


class TestL20ModelMatchesFunction:
    def test_exact_match(self):
        assert mmc._model_matches("qwen-plus", "qwen-plus") is True

    def test_latest_suffix_client_side(self):
        """客户端名带 -latest，请求裸名 → 命中。"""
        assert mmc._model_matches("qwen-plus-latest", "qwen-plus") is True

    def test_latest_suffix_requested_side(self):
        """请求带 -latest，客户端裸名 → 命中。"""
        assert mmc._model_matches("qwen-plus", "qwen-plus-latest") is True

    def test_preview_suffix(self):
        assert mmc._model_matches("moonshot-v1-8k-vision-preview", "moonshot-v1-8k-vision") is True

    def test_different_models_no_match(self):
        assert mmc._model_matches("qwen-plus-latest", "qwen-max") is False

    def test_empty_inputs_no_match(self):
        assert mmc._model_matches("", "qwen-plus") is False
        assert mmc._model_matches("qwen-plus", "") is False


def _make_stub_client():
    """构造绕过 __init__ 的 MultiModelClient 桩：default 在前，qwen-plus-latest 在后。"""
    mc = object.__new__(MultiModelLLMClient)
    default = SimpleNamespace(model="default-model")
    qwen = SimpleNamespace(model="qwen-plus-latest")
    mc._clients = {"p/default": default, "p/qwen": qwen}
    mc._current_provider_id = "p/default"
    mc._current_model = "default-model"
    return mc, default, qwen


class TestL20GetClientWiring:
    def test_get_client_matches_latest_suffix(self):
        """get_client(model="qwen-plus") 必须命中 "qwen-plus-latest" 客户端。"""
        mc, default, qwen = _make_stub_client()
        got = mc.get_client(model="qwen-plus")
        assert got is qwen, "L-20: get_client 应剥后缀命中 qwen-plus-latest"

    def test_get_client_falls_back_when_no_match(self):
        """无匹配时保持既有回落行为。"""
        mc, default, qwen = _make_stub_client()
        got = mc.get_client(model="no-such-model")
        assert got is default

    def test_get_client_for_request_uses_same_match(self):
        """_get_client_for_request 消费同一匹配函数。"""
        mc, default, qwen = _make_stub_client()
        mc._provider_manager = SimpleNamespace(list_providers=lambda: [])
        mc._resolve_available_fallback = lambda: "FALLBACK"
        got = mc._get_client_for_request(model="qwen-plus")
        assert got is qwen, "L-20: _get_client_for_request 应与 get_client 同源匹配"
