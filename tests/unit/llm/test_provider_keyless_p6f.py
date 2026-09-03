"""
P6f 修复:无 key 提示只对需要 API Key 的服务商生效(OpenCode/Kilo 免 key)。

TDD Red Phase:当前实现(无条件拦截无 key provider)下全部失败。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.llm.provider_manager import KEYLESS_PROVIDER_IDS, ProviderConfig


@pytest.mark.parametrize(
    ("provider_id", "expect_hint"),
    [
        ("openrouter", True),   # 需要 key
        ("opencode", False),    # 免 key 网关
        ("kilo-code", False),   # 免 key 网关
    ],
)
def test_discover_missing_key_hint_respects_provider_type(provider_id, expect_hint):
    from neurova.api.endpoints import provider as provider_module

    fake_manager = MagicMock()
    fake_cfg = ProviderConfig(
        id=provider_id,
        name=provider_id,
        provider=provider_id,
        base_url="https://api.example.com/v1",
        api_key="",
        models=[],
    )
    fake_manager.get_provider = MagicMock(return_value=fake_cfg)
    fake_manager.fetch_provider_models = AsyncMock(return_value=[])
    with patch.object(provider_module, "_get_provider_manager", return_value=fake_manager):
        request = MagicMock()
        request.state.request_id = "hint-check"
        result = asyncio.run(
            provider_module.discover_models(
                request, provider_id, {"role": "user", "user_id": "7"},
            ),
        )
    got_hint = bool(result["data"].get("message"))
    assert got_hint is expect_hint


@pytest.mark.parametrize(
    ("provider_id", "expect_hint"),
    [
        ("openrouter", True),
        ("opencode", False),
    ],
)
def test_filter_missing_key_hint_respects_provider_type(provider_id, expect_hint):
    from neurova.api.endpoints import provider as provider_module

    fake_manager = MagicMock()
    fake_cfg = ProviderConfig(
        id=provider_id,
        name=provider_id,
        provider=provider_id,
        base_url="https://api.example.com/v1",
        api_key="",
        models=[],
    )
    fake_manager.get_provider = MagicMock(return_value=fake_cfg)
    fake_manager.filter_provider_models = AsyncMock(return_value=[])
    with patch.object(provider_module, "_get_provider_manager", return_value=fake_manager):
        request = MagicMock()
        request.state.request_id = "hint-check-filter"
        body = MagicMock()
        body.providers = None
        body.input_modalities = None
        body.output_modalities = None
        body.max_prompt_price = None
        body.is_free = True
        result = asyncio.run(
            provider_module.filter_provider_models(
                request, provider_id, body, {"role": "user", "user_id": "7"},
            ),
        )
    got_hint = bool(result["data"].get("message"))
    assert got_hint is expect_hint


def test_keyless_ids_include_core_free_gateways():
    assert {"opencode", "kilo-code"} <= KEYLESS_PROVIDER_IDS
