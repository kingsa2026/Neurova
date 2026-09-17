"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class ImageGenClient:
    """文生图客户端：多服务商，通过 httpx 调用"""

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(api._comfyui_host())
        names = api.IMAGE_KEY_NAMES.get(provider, [])
        return bool(api.resolve_api_key(names, api_key))

    async def generate(
        self,
        provider: str,
        prompt: str,
        api_key: str = "",
        size: str = "1024x1024",
        base_url: str = "",
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        provider = str(provider or "").lower()
        if provider not in api.IMAGE_PROVIDERS:
            return api._fail(f"不支持的图像服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return api._fail(f"图像服务商 '{api.IMAGE_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            return await self._generate_comfyui(prompt, size)
        key = api.resolve_api_key(api.IMAGE_KEY_NAMES[provider], api_key)
        url = f"{api._base_url(provider, base_url)}/images/generations"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"prompt": prompt, "size": size, "n": 1}
        try:
            data = await api._http_post(url, headers=headers, json=body, timeout=timeout)
            url_out = api._extract(data, ["url", "image_url"])
            if not url_out:
                items = api._extract(data, ["data", "images"])
                if isinstance(items, list) and items:
                    url_out = api._extract(items[0], ["url", "image_url"])
            return api._ok(
                {"prompt": prompt, "size": size, "provider": provider, "url": url_out, "raw": data},
                provider,
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("图像生成失败 (%s): %s", provider, exc)
            return api._fail(str(exc), provider)

    async def _generate_comfyui(self, prompt: str, size: str) -> Dict[str, Any]:
        width, height = api._parse_size(size)
        client = api.get_comfyui_client()
        result = await client.execute_node(
            "EmptyLatentImage",
            {"width": width, "height": height, "batch_size": 1},
            {"prompt": prompt, "save_images": True},
        )
        return {
            "status": result.get("status", "failed"),
            "output": result.get("output"),
            "error": result.get("error"),
            "provider": "comfyui",
        }


ImageGenClient.__module__ = api.__name__
ImageGenClient.is_available.__module__ = api.__name__
ImageGenClient.generate.__module__ = api.__name__
ImageGenClient._generate_comfyui.__module__ = api.__name__
