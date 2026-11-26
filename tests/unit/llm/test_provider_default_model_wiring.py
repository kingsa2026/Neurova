# -*- coding: utf-8 -*-
"""OPS-03 服务商默认模型字段全链闭环（模板写 → 装载器读 → 种子 → 消费方）。

审计 2026-11-25 批次 E 实测：D-R4 铺量已在 `config/llm_provider_templates.json`
给 deepseek/moonshot/zhipu/siliconflow 声明 `default_model`，但读取侧的
`_ProviderTemplate` 没有该字段——Pydantic 静默丢弃，`_load_builtin_providers`
构造 `ProviderConfig` 时也不传，于是种子项的 `default_model` 恒为 None。
消费方 `default_model or models[0]` 因此回落到模型列表首项：**配置里写的默认
模型从未生效，且日志里一个字都没有**。

判据取"同一份数据穿过四层，逐层不许丢"：

1. 模板 raw 文件里有声明（否则本套件静默空转，先自证非空）；
2. `builtinProviderDefs()` 原样保留每条的声明值；
3. 空配置下管理器种子出的 `ProviderConfig.default_model` 与模板一致；
4. `resolve_llm_config()` 真把它当候选模型用（消费方，不是"存着好看"）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.llm import provider_manager as pm
from neurova.llm.config_resolver import resolve_llm_config
from neurova.llm.provider_manager import LLMProviderManager

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = REPO_ROOT / "config" / "llm_provider_templates.json"


def _rawDeclaredDefaults() -> dict:
    """模板里显式声明 default_model 的条目（期望值只从这份文件取，不另抄一份）。"""
    data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return {
        entry["id"]: entry["default_model"]
        for entry in data["providers"]
        if entry.get("default_model")
    }


def _newManager(tmp_path: Path) -> LLMProviderManager:
    """空配置管理器：走真实的「无配置文件 → 内置种子 → 落盘」路径。"""
    return LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})


class TestTemplateDeclaresDefaultModel:
    def test_someBuiltinTemplateDeclaresDefaultModel(self):
        """本套件的前置事实：模板里确实有 default_model（没有则其余断言无意义）。"""
        declared = _rawDeclaredDefaults()
        assert declared, (
            "config/llm_provider_templates.json 没有任何 default_model 声明——"
            "OPS-03 的判据会静默空转"
        )
        assert "deepseek" in declared, (
            f"deepseek 的默认模型声明丢失（现有声明：{sorted(declared)}）"
        )


class TestLoaderPreservesDeclaredDefaultModel:
    def test_builtinProviderDefsKeepsEveryDeclaredDefaultModel(self):
        """装载器不得静默丢字段：raw 文件声明了几个，defs 就要原样带回几个。"""
        declared = _rawDeclaredDefaults()
        loaded = {
            d["id"]: d["default_model"]
            for d in pm.builtinProviderDefs()
            if d.get("default_model")
        }
        assert loaded == declared, (
            "模板声明与装载结果不一致："
            f"声明 {declared}，装载后只剩 {loaded}——"
            "Pydantic 模板类漏字段时该值被静默丢弃，配置里写的默认模型不生效"
        )


class TestSeededProviderCarriesDefaultModel:
    def test_freshSeedProviderCarriesTemplateDefaultModel(self, tmp_path):
        """空配置首启（镜像/新装）时，种子 ProviderConfig 必须带上默认模型。"""
        declared = _rawDeclaredDefaults()
        manager = _newManager(tmp_path)
        actual = {
            pid: manager.get_provider(pid).default_model
            for pid in declared
        }
        assert actual == declared, (
            f"种子 ProviderConfig 的 default_model 与模板不一致：模板 {declared}，实际 {actual}"
        )

    def test_existingSeedWithoutDefaultModelIsBackfilled(self, tmp_path):
        """存量配置（升级前已落盘的种子项）也要补齐：None 不是用户选择。

        `_load_builtin_providers` 的契约是「只补缺失 id，绝不覆盖用户已配置项」。
        但 `default_model=None` 是**未设置**状态（`update_provider` 传 None 即
        「不改」），不是用户选择；不补齐则升级用户的该项永远停在 None，
        审计命中的故障面只对新装用户关闭。
        """
        config_path = tmp_path / "providers.json"
        config_path.write_text(
            json.dumps(
                {
                    "providers": [
                        {
                            "id": "deepseek",
                            "name": "DeepSeek",
                            "provider": "openai",
                            "base_url": "https://api.deepseek.com/v1",
                            "api_key": "sk-user",
                            "default_model": None,
                            "models": ["deepseek-reasoner", "deepseek-chat"],
                        }
                    ],
                    "default_provider_id": "deepseek",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manager = LLMProviderManager(config={"config_path": str(config_path)})
        provider = manager.get_provider("deepseek")
        assert provider.default_model == "deepseek-chat", (
            "存量种子项未按模板补齐 default_model——升级用户的默认模型仍不生效"
        )
        # 用户其余配置原样保留（补齐只碰空的 default_model）
        assert provider.api_key == "sk-user"
        assert provider.models == ["deepseek-reasoner", "deepseek-chat"]
        assert provider.base_url == "https://api.deepseek.com/v1"


class TestResolverConsumesDefaultModel:
    def test_resolvedLlmConfigUsesSeededDefaultModel(self, tmp_path):
        """消费方闭环：三层合并的服务商层真的把 default_model 当模型候选。"""
        declared = _rawDeclaredDefaults()
        manager = _newManager(tmp_path)
        for provider_id, expected_model in declared.items():
            agent = SimpleNamespace(llm_config=None, llm_provider=provider_id)
            resolved = resolve_llm_config(agent, manager)
            assert resolved.model == expected_model, (
                f"{provider_id}: 解析结果 model={resolved.model!r}，"
                f"模板声明 {expected_model!r}——默认模型未进入消费链路"
            )
            assert resolved._source_model == f"provider:{provider_id}"