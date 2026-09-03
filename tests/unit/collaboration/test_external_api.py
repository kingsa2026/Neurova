"""
Neurflow 外部平台 API 统一客户端层测试 — Phase 1

验证 external_api.py：
1. 服务商/平台目录（图像 6 / 视频 5 / 电商 10 / 发布 5）
2. SecretStore API Key 解析
3. ImageGenClient：可用性检测 + 生成（含 ComfyUI 委托）
4. VideoGenClient：任务提交 + 轮询 + 超时
5. CommercePlatformClient：价格/库存/评论/报表/竞品
6. PublishPlatformClient：视频发布
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TestProviderCatalogs:
    def test_image_providers_include_six(self):
        from neurova.collaboration.neurflow.external_api import IMAGE_PROVIDERS
        assert set(IMAGE_PROVIDERS.keys()) == {"comfyui", "openai", "kling", "jimeng", "wanx", "stability"}
        assert IMAGE_PROVIDERS["comfyui"] == "ComfyUI 自建"

    def test_video_providers_include_five(self):
        from neurova.collaboration.neurflow.external_api import VIDEO_PROVIDERS
        assert set(VIDEO_PROVIDERS.keys()) == {"kling", "jimeng", "runway", "pika", "comfyui"}

    def test_commerce_platforms_include_ten(self):
        from neurova.collaboration.neurflow.external_api import COMMERCE_PLATFORMS
        assert set(COMMERCE_PLATFORMS.keys()) == {
            "amazon", "taobao", "jd", "douyin-ecom", "tiktok", "pdd", "ali1688", "xiaohongshu", "xianyu", "shein",
        }
        assert COMMERCE_PLATFORMS["xianyu"] == "咸鱼"

    def test_publish_platforms_include_five(self):
        from neurova.collaboration.neurflow.external_api import PUBLISH_PLATFORMS
        assert set(PUBLISH_PLATFORMS.keys()) == {"douyin", "kuaishou", "bilibili", "tiktok", "xiaohongshu"}


class TestApiKeyResolution:
    def test_get_api_key_reads_from_secret_store(self):
        from neurova.collaboration.neurflow.external_api import get_api_key
        store = MagicMock()
        store.get.return_value = "sk-test-123"
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert get_api_key("NEUROVA_IMAGE_OPENAI_KEY") == "sk-test-123"
            store.get.assert_called_once_with("NEUROVA_IMAGE_OPENAI_KEY")

    def test_get_api_key_returns_none_when_missing(self):
        from neurova.collaboration.neurflow.external_api import get_api_key
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert get_api_key("X") is None

    def test_resolve_api_key_explicit_wins(self):
        from neurova.collaboration.neurflow.external_api import resolve_api_key
        assert resolve_api_key(["NEUROVA_IMAGE_OPENAI_KEY"], explicit="sk-explicit") == "sk-explicit"

    def test_resolve_api_key_falls_back_to_store(self):
        from neurova.collaboration.neurflow.external_api import resolve_api_key
        store = MagicMock()
        store.get.return_value = "sk-store"
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert resolve_api_key(["NEUROVA_IMAGE_OPENAI_KEY"], explicit="") == "sk-store"

    def test_resolve_api_key_none_when_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import resolve_api_key
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert resolve_api_key(["X"], explicit="") is None


class TestImageGenClient:
    def test_is_available_false_without_key(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert ImageGenClient().is_available("openai") is False

    def test_is_available_true_with_key(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        assert ImageGenClient().is_available("openai", api_key="sk-test") is True

    def test_is_available_comfyui_uses_host(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        with patch("neurova.core.config.get", return_value="http://localhost:8188"):
            assert ImageGenClient().is_available("comfyui") is True
        with patch("neurova.core.config.get", return_value=None):
            assert ImageGenClient().is_available("comfyui") is False

    @pytest.mark.asyncio
    async def test_generate_success(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        mock_post = AsyncMock(return_value={"data": [{"url": "https://img.example.com/a.png"}]})
        with patch("neurova.collaboration.neurflow.external_api._http_post", mock_post):
            result = await ImageGenClient().generate("openai", "一只猫", api_key="sk-test")
        assert result["status"] == "success"
        assert result["output"]["url"] == "https://img.example.com/a.png"
        assert result["output"]["provider"] == "openai"

    @pytest.mark.asyncio
    async def test_generate_failed_when_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        result = await ImageGenClient().generate("openai", "一只猫", api_key="")
        assert result["status"] == "failed"
        assert result["output"] is None

    @pytest.mark.asyncio
    async def test_generate_network_error_isolated(self):
        from neurova.collaboration.neurflow import external_api
        from neurova.collaboration.neurflow.external_api import ImageGenClient

        async def _boom(*a, **k):
            raise external_api.ExternalAPIError("connection refused")

        with patch("neurova.collaboration.neurflow.external_api._http_post", _boom):
            result = await ImageGenClient().generate("openai", "一只猫", api_key="sk-test")
        assert result["status"] == "failed"
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_comfyui_delegates(self):
        from neurova.collaboration.neurflow.external_api import ImageGenClient
        comfy_client = MagicMock()
        comfy_client.execute_node = AsyncMock(return_value={"status": "success", "output": {"prompt_id": "abc"}, "error": None})
        with patch("neurova.collaboration.neurflow.external_api.get_comfyui_client", return_value=comfy_client), \
             patch("neurova.core.config.get", return_value="http://localhost:8188"):
            result = await ImageGenClient().generate("comfyui", "一只猫")
        assert result["status"] == "success"
        assert result["provider"] == "comfyui"
        comfy_client.execute_node.assert_called_once()


class TestVideoGenClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import VideoGenClient
        assert VideoGenClient().is_available("kling", api_key="sk-test") is True
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert VideoGenClient().is_available("kling") is False

    @pytest.mark.asyncio
    async def test_generate_submits_and_polls(self):
        from neurova.collaboration.neurflow.external_api import VideoGenClient
        mock_post = AsyncMock(return_value={"data": {"task_id": "task-1"}})
        mock_get = AsyncMock(return_value={"data": {"task_id": "task-1", "status": "succeed", "video_url": "https://v.example.com/a.mp4"}})
        with patch("neurova.collaboration.neurflow.external_api._http_post", mock_post), \
             patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await VideoGenClient(poll_interval=0).generate("kling", "雨夜奔跑", api_key="sk-test")
        assert result["status"] == "success"
        assert result["output"]["video_url"] == "https://v.example.com/a.mp4"

    @pytest.mark.asyncio
    async def test_generate_polls_times_out(self):
        from neurova.collaboration.neurflow.external_api import VideoGenClient
        mock_post = AsyncMock(return_value={"data": {"task_id": "task-1"}})
        mock_get = AsyncMock(return_value={"data": {"task_id": "task-1", "status": "pending"}})
        with patch("neurova.collaboration.neurflow.external_api._http_post", mock_post), \
             patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await VideoGenClient(poll_interval=0).generate("kling", "雨夜奔跑", api_key="sk-test", max_polls=3)
        assert result["status"] == "failed"
        assert "超时" in result["error"]

    @pytest.mark.asyncio
    async def test_generate_failed_when_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import VideoGenClient
        result = await VideoGenClient().generate("kling", "雨夜奔跑", api_key="")
        assert result["status"] == "failed"


class TestCommercePlatformClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        # shein 无专用客户端，仍走通用 REST 兜底（存在通用 API Key 即可用）
        assert CommercePlatformClient().is_available("shein", api_key="ak-test") is True
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert CommercePlatformClient().is_available("shein") is False

    def test_is_available_amazon_requires_sp_api_credentials(self):
        """亚马逊走 SP-API：需 refresh_token + client_id + client_secret 三件套"""
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mapping = {
            "NEUROVA_AMAZON_SP_REFRESH_TOKEN": "rt",
            "NEUROVA_AMAZON_SP_CLIENT_ID": "cid",
            "NEUROVA_AMAZON_SP_CLIENT_SECRET": "cs",
        }
        store = MagicMock()
        store.get.side_effect = lambda name: mapping.get(name)
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert CommercePlatformClient().is_available("amazon") is True

    @pytest.mark.asyncio
    async def test_fetch_prices_success(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mock_get = AsyncMock(return_value={"data": {"ITEM1": {"price": "99.00", "currency": "CNY"}}})
        with patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await CommercePlatformClient().fetch_prices("shein", ["ITEM1"], api_key="ak-test")
        assert result["status"] == "success"
        assert result["output"]["prices"]["ITEM1"]["price"] == "99.00"

    @pytest.mark.asyncio
    async def test_fetch_prices_failed_when_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        result = await CommercePlatformClient().fetch_prices("amazon", ["B0TEST"], api_key="")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_fetch_inventory_success(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mock_get = AsyncMock(return_value={"data": {"SKU1": 12}})
        with patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await CommercePlatformClient().fetch_inventory("shein", ["SKU1"], api_key="ak-test")
        assert result["status"] == "success"
        assert result["output"]["inventory"]["SKU1"] == 12

    @pytest.mark.asyncio
    async def test_fetch_reviews_success(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mock_get = AsyncMock(return_value={"data": {"items": [{"text": "很好", "sentiment": "positive"}]}})
        with patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await CommercePlatformClient().fetch_reviews("shein", "item-1", api_key="ak-test")
        assert result["status"] == "success"
        assert result["output"]["items"][0]["text"] == "很好"

    @pytest.mark.asyncio
    async def test_fetch_sales_report_success(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mock_get = AsyncMock(return_value={"data": {"total_sales": "12345.67", "orders": 88}})
        with patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await CommercePlatformClient().fetch_sales_report("shein", period="2026-08", api_key="ak-test")
        assert result["status"] == "success"
        assert result["output"]["total_sales"] == "12345.67"

    @pytest.mark.asyncio
    async def test_fetch_competitors_success(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient
        mock_get = AsyncMock(return_value={"data": {"items": [{"title": "竞品A", "price": "12.00"}]}})
        with patch("neurova.collaboration.neurflow.external_api._http_get", mock_get):
            result = await CommercePlatformClient().fetch_competitors("shein", "蓝牙耳机", api_key="ak-test")
        assert result["status"] == "success"
        assert result["output"]["items"][0]["title"] == "竞品A"


class TestPublishPlatformClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import PublishPlatformClient
        assert PublishPlatformClient().is_available("douyin", access_token="tok-test") is True
        store = MagicMock()
        store.get.return_value = None
        with patch("neurova.collaboration.neurflow.external_api.get_secret_store", return_value=store):
            assert PublishPlatformClient().is_available("douyin") is False

    @pytest.mark.asyncio
    async def test_publish_success(self):
        from neurova.collaboration.neurflow.external_api import PublishPlatformClient
        mock_post = AsyncMock(return_value={"data": {"item_id": "v-1", "url": "https://www.douyin.com/video/v-1"}})
        with patch("neurova.collaboration.neurflow.external_api._http_post", mock_post):
            result = await PublishPlatformClient().publish("douyin", "https://v.example.com/a.mp4", "标题", ["tag1"], access_token="tok-test")
        assert result["status"] == "success"
        assert "douyin.com" in result["output"]["url"]

    @pytest.mark.asyncio
    async def test_publish_failed_when_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import PublishPlatformClient
        result = await PublishPlatformClient().publish("douyin", "https://v.example.com/a.mp4", "标题", [], access_token="")
        assert result["status"] == "failed"
