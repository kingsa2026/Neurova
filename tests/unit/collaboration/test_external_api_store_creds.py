"""
客户端 store_creds 注入契约测试 — TDD 红灯先行。

范围（P3 客户端注入，§5.2）：
1. _OpenGatewayClientBase._resolve_credentials 优先级：显式传参 > store_creds > 环境变量；
2. _access_token 缓存按 store_id 多键隔离（多店铺 token 互不踩）；
3. TikTokShopClient：shop_cipher 取自 store_creds.extra 并参与签名；
   fetch_shop_cipher 经 /authorization/202309/shops 取回；
4. CommercePlatformClient.fetch_* 透传 store_id / store_creds 到 CN 客户端。

占位值均为无敏感含义片段（kkkk 形态）。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MOD = "neurova.collaboration.neurflow.external_api"
from neurova.collaboration.neurflow.external_api import (
    CommercePlatformClient,
    TaobaoTopClient,
    TikTokShopClient,
    _tiktok_sign_sha256,
)
from neurova.collaboration.neurflow.store_connections import StoreCredentials


def _store_with(mapping: dict):
    store = MagicMock()
    store.get.side_effect = lambda name: mapping.get(name)
    return store


def _creds(app_key="shop" + "aaaa", app_secret="shop" + "bbbb", access_token="shop" + "ccccc",
           refresh_token="", **extra):
    return StoreCredentials(
        app_key=app_key,
        app_secret=app_secret,
        access_token=access_token,
        refresh_token=refresh_token,
        extra=extra,
    )


class TestResolveCredentialsPriority:
    def test_store_creds_over_env(self):
        client = TaobaoTopClient()
        env_store = _store_with({"NEUROVA_TAOBAO_APP_KEY": "env" + "aa1111", "NEUROVA_TAOBAO_APP_SECRET": "env" + "bb2222"})
        with patch(f"{MOD}.get_secret_store", return_value=env_store):
            creds = _creds()
            ak, sk, at, rt = client._resolve_credentials(store_creds=creds)
            assert ak == creds.app_key
            assert sk == creds.app_secret
            assert at == creds.access_token

    def test_explicit_over_store_creds(self):
        client = TaobaoTopClient()
        ak, sk, at, rt = client._resolve_credentials(
            app_key="explicit" + "xx",
            store_creds=_creds(),
        )
        assert ak == "explicit" + "xx"
        assert sk == _creds().app_secret  # 未显式给的槽位回落 store_creds

    def test_env_fallback_when_no_store(self):
        client = TaobaoTopClient()
        env_store = _store_with({"NEUROVA_TAOBAO_APP_KEY": "env" + "aa1111"})
        with patch(f"{MOD}.get_secret_store", return_value=env_store):
            ak, sk, at, rt = client._resolve_credentials()
        assert ak == "env" + "aa1111"


class TestTokenCacheMultikey:
    @pytest.mark.asyncio
    async def test_cache_isolated_by_store_id(self):
        client = TaobaoTopClient()
        responses = [
            {"error_response": None, "access_token": "tknAAAA"},
            {"error_response": None, "access_token": "tknBBBB"},
        ]
        with patch(f"{MOD}._http_post", new=AsyncMock(side_effect=responses)):
            t1 = await client._access_token(
                app_key="k" * 8, app_secret="s" * 8, refresh_token="rk111111", store_id="store_000001"
            )
            t2 = await client._access_token(
                app_key="k" * 8, app_secret="s" * 8, refresh_token="rk222222", store_id="store_000002"
            )
            assert t1 == "tknAAAA"
            assert t2 == "tknBBBB"
            assert set(client._token_cache.keys()) == {"store_000001", "store_000002"}
            # 命中缓存不重复刷新
            t1_again = await client._access_token(
                app_key="k" * 8, app_secret="s" * 8, refresh_token="rk111111", store_id="store_000001"
            )
            assert t1_again == "tknAAAA"
            assert client._token_cache["store_000001"]["token"] == "tknAAAA"

    @pytest.mark.asyncio
    async def test_unkeyed_call_uses_default_slot(self):
        client = TaobaoTopClient()
        with patch(f"{MOD}._http_post", new=AsyncMock(return_value={"access_token": "tknDDDD"})):
            token = await client._access_token(app_key="k" * 8, app_secret="s" * 8, refresh_token="rk333333")
            assert token == "tknDDDD"
            assert "default" in client._token_cache


class TestTikTokShopCipher:
    @pytest.mark.asyncio
    async def test_shop_cipher_injected_and_signed(self):
        client = TikTokShopClient()
        captured = {}

        async def fake_get(url, **kwargs):
            captured.update(kwargs)
            return {"code": 0, "data": {"products": []}}

        with patch(f"{MOD}._http_get", new=fake_get):
            creds = _creds(shop_cipher="cipher9900")
            await client.fetch_products(store_creds=creds)

        params = captured.get("params") or {}
        assert params.get("shop_cipher") == "cipher9900"
        # shop_cipher 参与签名：用同一算法重算应一致
        signable = {k: v for k, v in params.items() if k != "sign"}
        assert params.get("sign") == _tiktok_sign_sha256(creds.app_secret, signable)

    @pytest.mark.asyncio
    async def test_no_cipher_when_extra_empty(self):
        client = TikTokShopClient()
        captured = {}

        async def fake_get(url, **kwargs):
            captured.update(kwargs)
            return {"code": 0, "data": {"products": []}}

        with patch(f"{MOD}._http_get", new=fake_get):
            await client.fetch_products(store_creds=_creds())
        assert "shop_cipher" not in (captured.get("params") or {})

    @pytest.mark.asyncio
    async def test_fetch_shop_cipher(self):
        client = TikTokShopClient()

        async def fake_get(url, **kwargs):
            return {"code": 0, "data": {"shops": [{"shop_cipher": "cipher9900", "shop_name": "抖区店"}]}}

        with patch(f"{MOD}._http_get", new=fake_get):
            result = await client.fetch_shop_cipher(
                app_key="ak" * 6, app_secret="sk" * 6, access_token="tk" * 6
            )
        assert result.get("status") == "success"
        shops = result.get("output", {}).get("shops") or []
        assert shops and shops[0].get("shop_cipher") == "cipher9900"


class TestCommercePlatformClientForwardsCreds:
    @pytest.mark.asyncio
    async def test_fetch_prices_forwards_store_creds_to_taobao(self):
        mock_client = MagicMock()
        mock_client.fetch_prices = AsyncMock(return_value={"status": "success", "output": {"prices": {}}})
        with patch(f"{MOD}.get_taobao_top_client", return_value=mock_client):
            cpc = CommercePlatformClient()
            creds = _creds()
            result = await cpc.fetch_prices("taobao", ["101010"], store_id="store_000001", store_creds=creds)
        assert result.get("status") == "success"
        mock_client.fetch_prices.assert_awaited_once_with(
            ["101010"], store_id="store_000001", store_creds=creds
        )
