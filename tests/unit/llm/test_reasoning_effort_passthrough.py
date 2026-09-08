"""AMD RADEON 网关推理透传接入测试（TDD）

背景（2026-09-08 AMD 推理过程不显示事故）：
  AMD 网关（developer.amd.com.cn/radeon）三模型实测：
  - DeepSeek-V4-Flash / DeepSeek-V4-Flash-Vision-Exp：
    默认不吐 reasoning_content；必须显式带 reasoning_effort 参数才回传
    （high 实测 522/213 字符，xhigh 386 字符）。
  - Qwen3.8-Flash-Next：默认即吐 delta.reasoning（非标准 reasoning_content
    字段名），Neurova _pick_reasoning 已兼容读取。

修复面：
  1. ProviderCompat 新增 supports_reasoning_effort 声明式开关 + amd 静态表行
  2. LLMConfig compat 开关消费：chat/chat_stream/chat_stream_async 请求参数
     按用户 effort 映射注入 reasoning_effort（standard→medium, deep→high, light→不传）
  3. 管线 thinking_effort 经 loop kwargs 透传到 LLMClient
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

import pytest

from neurova.llm.provider_compat import ProviderCompat, resolve_compat
from neurova.llm_client import LLMClient, LLMConfig


# ---------------------------------------------------------------------------
# 1) compat 开关声明与解析
# ---------------------------------------------------------------------------


class TestProviderCompatReasoningEffort:
    def test_amd_resolves_supports_reasoning_effort(self):
        """amd provider（静态表）解析出 supports_reasoning_effort=True。"""
        compat = resolve_compat(provider_id="amd", base_url="https://developer.amd.com.cn/radeon/api/v1")
        assert compat.supports_reasoning_effort is True

    def test_unknown_provider_defaults_false(self):
        """未实测 provider 默认 False（防 400 炸其他网关——商汤等低容忍网关）。"""
        compat = resolve_compat(provider_id="sensetime", base_url="https://token.sensenova.cn/v1")
        assert compat.supports_reasoning_effort is False

    def test_explicit_override_wins(self):
        """ProviderConfig 显式声明覆盖静态表。"""
        compat = resolve_compat(
            provider_id="whatever",
            base_url="https://x.example/v1",
            compat_dict={"supports_reasoning_effort": True},
        )
        assert compat.supports_reasoning_effort is True

    def test_effort_mapping(self):
        """thinking_effort → reasoning_effort 映射：light→None, standard→medium, deep→high。"""
        c = ProviderCompat(supports_reasoning_effort=True)
        assert c.map_reasoning_effort("light") is None
        assert c.map_reasoning_effort("") is None
        assert c.map_reasoning_effort("standard") == "medium"
        assert c.map_reasoning_effort("deep") == "high"
        # 未知值不猜（fail-safe）
        assert c.map_reasoning_effort("ultra") is None


# ---------------------------------------------------------------------------
# 2) LLMClient 请求参数注入（mock 层验证，不发真实请求）
# ---------------------------------------------------------------------------


def _client_with_compat(monkeypatch, supports: bool) -> LLMClient:
    cfg = LLMConfig(
        api_key="test-key",
        base_url="https://developer.amd.com.cn/radeon/api/v1",
        model="DeepSeek-V4-Flash",
    )
    cfg.compat = resolve_compat(
        provider_id="amd" if supports else "sensetime",
        base_url=cfg.base_url if supports else "https://token.sensenova.cn/v1",
    )
    return LLMClient(cfg)


class TestRequestParamsInjection:
    def test_chat_stream_injects_reasoning_effort(self, monkeypatch):
        """流式请求参数按 effort=deep 注入 reasoning_effort=high。"""
        client = _client_with_compat(monkeypatch, supports=True)
        captured = {}

        class _FakeAsyncClient:
            pass

        def _fake_create(**params):
            captured.update(params)
            return None

        # 直接测参数组装函数（_build_stream_params 若存在）或走 chunk 前的 params dict
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}], thinking_effort="deep", stream=True
        )
        assert params.get("reasoning_effort") == "high"

    def test_chat_stream_light_no_injection(self, monkeypatch):
        """effort=light 不注入 reasoning_effort（简洁速答语义）。"""
        client = _client_with_compat(monkeypatch, supports=True)
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}], thinking_effort="light", stream=True
        )
        assert "reasoning_effort" not in params

    def test_non_supporting_provider_no_injection(self, monkeypatch):
        """compat 未声明支持的 provider 永不注入（防 400）。"""
        client = _client_with_compat(monkeypatch, supports=False)
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}], thinking_effort="deep", stream=True
        )
        assert "reasoning_effort" not in params

    def test_sync_chat_injects(self, monkeypatch):
        """非流式 chat 同样注入。"""
        client = _client_with_compat(monkeypatch, supports=True)
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}], thinking_effort="deep", stream=False
        )
        assert params.get("reasoning_effort") == "high"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
