"""
OpenCode Provider — 免 key 免费网关(opencode.ai zen API)

对齐 QwenPaw 的 OpenCodeProvider 语义:
1. 模型免费标识:优先网关 isFree/is_free 字段,缺省以 ``-free`` 后缀判定。
2. 网关列出但已停止服务的模型须剔除(硬编码封禁清单)。
3. 免 API key 发现(免费层)。
"""

from __future__ import annotations

import typing

from neurova.llm.providers.openai_provider import OpenAIProvider
from neurova.llm.providers.types import ModelInfo, ProviderCapability, ProviderType


class OpenCodeProvider(OpenAIProvider):
    """OpenCode Provider with dynamic free model detection."""

    _FREE_SUFFIX = "-free"

    # 网关仍列出但已停止服务的模型
    _UNAVAILABLE_MODEL_IDS: typing.FrozenSet[str] = frozenset(
        {
            "deepseek-v4-flash-free",
            "nemotron-3-super-free",
        },
    )

    _FREE_DEFAULT_MODELS = []

    def __init__(
        self,
        provider_id: str = "opencode",
        api_key: str = "",
        base_url: str = "https://opencode.ai/zen/v1",
        **kwargs,
    ):
        super().__init__(
            provider_id=provider_id,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
        self.provider_type = ProviderType.OPENCODE

    def _parse_api_model(self, model_data: typing.Dict[str, typing.Any]) -> ModelInfo:
        model = super()._parse_api_model(model_data)
        # 网关显式标记优先,缺省按后缀判定
        api_free = model_data.get("isFree", None)
        if api_free is None:
            api_free = model_data.get("is_free", None)
        model.is_free = (
            bool(api_free)
            if api_free is not None
            else model.id.endswith(self._FREE_SUFFIX)
        )
        # OpenCode 平台层面支持 function calling,恒注入(与 OpenRouter 语义一致)
        if ProviderCapability.TOOL_USE not in model.capabilities:
            model.capabilities = [*model.capabilities, ProviderCapability.TOOL_USE]
        return model

    async def _fetch_models_from_api(self) -> typing.List[ModelInfo]:
        models = await super()._fetch_models_from_api()
        return [
            model
            for model in models
            if model.id not in self._UNAVAILABLE_MODEL_IDS
        ]

    def _get_default_models(self) -> typing.List[ModelInfo]:
        return [model.model_copy(deep=True) for model in self._FREE_DEFAULT_MODELS]


# 默认列表在模块级构造:全部为免费模型,且不含封禁清单中的 id。
_OPENCODE_DEFAULTS = (
    ("mimo-v2.5-free", "MiMo V2.5"),
    ("nemotron-3-ultra-free", "Nemotron 3 Ultra"),
)
for _model_id, _display_name in _OPENCODE_DEFAULTS:
    OpenCodeProvider._FREE_DEFAULT_MODELS.append(
        ModelInfo(
            id=_model_id,
            name=_display_name,
            provider="opencode",
            provider_type=ProviderType.OPENCODE,
            capabilities=[
                ProviderCapability.TEXT,
                ProviderCapability.TOOL_USE,
            ],
            is_free=True,
        ),
    )
