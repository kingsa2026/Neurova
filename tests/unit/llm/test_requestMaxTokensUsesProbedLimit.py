# -*- coding: utf-8 -*-
"""请求侧输出预算必须认持久化探测值（2026-10-22 default 会话「思考吃满正文饿死」事故）。

事故读数：amd/GLM-5.3-Flash 一轮思考连发 16384 字符同质片段后 `finish_reason=length`、
正文 0 字——16384 字符恰为 4096 token × 4 字符，即**整次调用的输出预算就是
`DEFAULT_MAX_TOKENS = 4096`**。而同一个模型早先已在模型管理里探测出 65536 并写进
`providers.json`。两份数各管一头：探测值只进了 `clamp_max_tokens` 的**上限**口径
（只能压低），请求值另走 `get_model_max_tokens`（只看静态目录，未收录即回落 4096）。
思考模型的思考与正文共享这一个预算，拿目录占位值当请求值 ⇒ 想长一点必然饿死正文。

本档钉的是**请求值口径**与 `clamp_max_tokens` 的优先级列表同一份事实源：
持久化探测值 > 静态目录 > DEFAULT。
"""
from __future__ import annotations

import pytest

from neurova.llm import model_limits as ml

# 真装配点要构造 openai 客户端（未安装时 `_create_model_client` 返回 None，测不到装配）
pytest.importorskip("openai")


@pytest.fixture(autouse=True)
def _clearMirror():
    ml.clear_persisted_output_limits()
    yield
    ml.clear_persisted_output_limits()


class TestRequestBudgetPrecedence:
    def testProbedLimitBecomesTheRequestedBudget(self):
        """本次事故的正面：探测到 65536 后，请求值就该是 65536 而不是 4096。"""
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        assert ml.get_model_max_tokens("GLM-5.3-Flash", "amd") == 65536, (
            "探测值是本机对该服务商实际验证过的输出上限，只当上限用会让请求值停在目录占位 4096"
        )

    def testProbedLimitOverridesStaticCatalog(self):
        """探测值优先于静态目录：目录可能是占位值，与 clamp 的同一优先级列表不得分叉。"""
        assert ml.get_model_max_tokens("deepseek-v4-flash", "sensetime") == 65536
        ml.set_persisted_output_limit("sensetime", "deepseek-v4-flash", 32768)
        assert ml.get_model_max_tokens("deepseek-v4-flash", "sensetime") == 32768

    def testWithoutProbeKeepsCatalogThenDefault(self):
        """无探测值时语义不变：收录模型走目录，未收录才回落 DEFAULT（不杜撰上限）。"""
        assert ml.get_model_max_tokens("gpt-4o", "openai") == 16384
        assert ml.get_model_max_tokens("totally-unknown-model", "amd") == ml.DEFAULT_MAX_TOKENS

    def testProbeDoesNotLeakAcrossProviders(self):
        """同名模型在别的服务商未被探测过，不得借用别人的探测值。"""
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        assert ml.get_model_max_tokens("GLM-5.3-Flash", "shanghai") == ml.DEFAULT_MAX_TOKENS

    def testProviderUnknownUsesProbeOnlyWhenUnambiguous(self):
        """调用点拿不到 provider（schema 面）：该模型只有一个探测值时认它，
        两个服务商给出不同值时诚实回落目录——不猜，猜就是第二个事实源。"""
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        assert ml.get_model_max_tokens("GLM-5.3-Flash") == 65536

        ml.set_persisted_output_limit("amd", "same-name", 65536)
        ml.set_persisted_output_limit("other", "same-name", 8192)
        assert ml.get_model_max_tokens("same-name") == ml.DEFAULT_MAX_TOKENS, (
            "两份冲突的探测值不知该信哪份，必须回落既有口径而不是任选一个"
        )


class TestLiveClientCarriesProbedBudget:
    """判据落在真装配点上：`_create_model_client` 建出的 client 配置里带的就是请求值。"""

    def _provider(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm.provider_manager import ProviderConfig

        manager = MultiModelLLMClient.__new__(MultiModelLLMClient)
        manager._clients = {}
        provider = ProviderConfig(
            id="amd",
            name="AMD",
            provider="openai",
            base_url="https://developer.amd.com.cn/radeon/api/v1",
            api_key="sk-test",
            models=["GLM-5.3-Flash"],
        )
        return manager, provider

    def testClientConfigUsesProbedLimit(self):
        ml.set_persisted_output_limit("amd", "GLM-5.3-Flash", 65536)
        manager, provider = self._provider()
        client = manager._create_model_client(provider, "GLM-5.3-Flash")
        assert client is not None, "api_key 就绪时必须建出客户端"
        assert client.client.config.max_tokens == 65536, (
            "思考模型的思考与正文共享这一个预算；装配点若不读探测值，"
            "模型管理里探测出来的上限就只写了不读（事故读数 16384 字符 = 4096 token 吃满）"
        )

    def testClientConfigWithoutProbeKeepsCurrentBudget(self):
        manager, provider = self._provider()
        client = manager._create_model_client(provider, "GLM-5.3-Flash")
        assert client.client.config.max_tokens == ml.DEFAULT_MAX_TOKENS
