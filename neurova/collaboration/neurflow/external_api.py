"""
Neurflow 外部平台 API 统一客户端层 — 深模块

为 Neurflow 节点提供统一的外部平台接入：
- 图像生成 ImageGenClient（ComfyUI / OpenAI / 可灵 / 即梦 / 通义万相 / Stability）
- 视频生成 VideoGenClient（可灵 / 即梦 / Runway / Pika / ComfyUI，提交+轮询）
- 电商数据 CommercePlatformClient（亚马逊/淘宝/京东/抖音/TikTok/拼多多/1688/小红书/咸鱼/希音）
- 视频发布 PublishPlatformClient（抖音/快手/B站/TikTok/小红书）

约定：
- API Key 统一经 SecretStore 加密存储，resolve_api_key() 解析（显式 key 优先）
- 所有调用失败返回 {"status": "failed", "output": None, "error": ..., "provider": ...}
- httpx 为可选依赖；未安装时明确报错
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ==================== 服务商 / 平台目录 ====================

IMAGE_PROVIDERS: Dict[str, str] = {
    "comfyui": "ComfyUI 自建",
    "openai": "OpenAI",
    "kling": "可灵 Kling",
    "jimeng": "即梦",
    "wanx": "通义万相",
    "stability": "Stability",
}

VIDEO_PROVIDERS: Dict[str, str] = {
    "kling": "可灵 Kling",
    "jimeng": "即梦",
    "runway": "Runway",
    "pika": "Pika",
    "comfyui": "ComfyUI 自建",
}

COMMERCE_PLATFORMS: Dict[str, str] = {
    "amazon": "亚马逊",
    "taobao": "淘宝",
    "jd": "京东",
    "douyin-ecom": "抖音电商",
    "tiktok": "TikTok",
    "pdd": "拼多多",
    "ali1688": "1688",
    "xiaohongshu": "小红书",
    "xianyu": "咸鱼",
    "shein": "希音",
}

PUBLISH_PLATFORMS: Dict[str, str] = {
    "douyin": "抖音",
    "kuaishou": "快手",
    "bilibili": "B站",
    "tiktok": "TikTok",
    "xiaohongshu": "小红书",
}

# ==================== SecretStore Key 命名映射 ====================

IMAGE_KEY_NAMES: Dict[str, List[str]] = {
    "comfyui": [],
    "openai": ["NEUROVA_IMAGE_OPENAI_KEY", "NEUROVA_OPENAI_API_KEY"],
    "kling": ["NEUROVA_IMAGE_KLING_KEY", "NEUROVA_KLING_API_KEY"],
    "jimeng": ["NEUROVA_IMAGE_JIMENG_KEY", "NEUROVA_JIMENG_API_KEY"],
    "wanx": ["NEUROVA_IMAGE_WANX_KEY", "NEUROVA_WANX_API_KEY", "NEUROVA_DASHSCOPE_API_KEY"],
    "stability": ["NEUROVA_IMAGE_STABILITY_KEY", "NEUROVA_STABILITY_API_KEY"],
}

VIDEO_KEY_NAMES: Dict[str, List[str]] = {
    "kling": ["NEUROVA_VIDEO_KLING_KEY", "NEUROVA_KLING_API_KEY"],
    "jimeng": ["NEUROVA_VIDEO_JIMENG_KEY", "NEUROVA_JIMENG_API_KEY"],
    "runway": ["NEUROVA_VIDEO_RUNWAY_KEY", "NEUROVA_RUNWAY_API_KEY"],
    "pika": ["NEUROVA_VIDEO_PIKA_KEY", "NEUROVA_PIKA_API_KEY"],
    "comfyui": [],
}

COMMERCE_KEY_NAMES: Dict[str, List[str]] = {
    "amazon": ["NEUROVA_AMAZON_API_KEY"],
    "taobao": ["NEUROVA_TAOBAO_API_KEY", "NEUROVA_TAOBAO_APP_KEY"],
    "jd": ["NEUROVA_JD_API_KEY"],
    "douyin-ecom": ["NEUROVA_DOUYIN_ECOM_API_KEY"],
    "tiktok": ["NEUROVA_TIKTOK_API_KEY"],
    "pdd": ["NEUROVA_PDD_API_KEY"],
    "ali1688": ["NEUROVA_1688_API_KEY"],
    "xiaohongshu": ["NEUROVA_XIAOHONGSHU_API_KEY"],
    "xianyu": ["NEUROVA_XIANYU_API_KEY"],
    "shein": ["NEUROVA_SHEIN_API_KEY"],
}

PUBLISH_KEY_NAMES: Dict[str, List[str]] = {
    "douyin": ["NEUROVA_DOUYIN_ACCESS_TOKEN"],
    "kuaishou": ["NEUROVA_KUAISHOU_ACCESS_TOKEN"],
    "bilibili": ["NEUROVA_BILIBILI_ACCESS_TOKEN"],
    "tiktok": ["NEUROVA_TIKTOK_ACCESS_TOKEN"],
    "xiaohongshu": ["NEUROVA_XIAOHONGSHU_ACCESS_TOKEN"],
}

# 默认服务地址（可用 base_url / 环境变量覆盖）
_DEFAULT_BASES: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "kling": "https://api.klingai.com/v1",
    "jimeng": "https://ark.cn-beijing.volces.com/api/v3",
    "wanx": "https://dashscope.aliyuncs.com/api/v1",
    "stability": "https://api.stability.ai/v2beta",
    "runway": "https://api.dev.runwayml.com/v1",
    "pika": "https://api.pika.art/v1",
    "amazon": "https://sellingpartnerapi-na.amazon.com",
    "taobao": "https://eco.taobao.com/router/rest",
    "jd": "https://api.jd.com/routerjson",
    "douyin-ecom": "https://openapi-fxg.jinritemai.com",
    "tiktok": "https://open-api.tiktokglobalshop.com",
    "pdd": "https://gw-api.pinduoduo.com/api/router",
    "ali1688": "https://gw.open.1688.com/openapi",
    "xiaohongshu": "https://ark.xiaohongshu.com",
    "xianyu": "https://openapi.taobao.com/router/rest",
    "shein": "https://openapi.sheincorp.cn",
    "douyin": "https://open.douyin.com",
    "kuaishou": "https://open.kuaishou.com",
    "bilibili": "https://api.bilibili.com",
    "tiktok-pub": "https://open.tiktokapis.com",
}

# ==================== HTTP 辅助（httpx 可选依赖） ====================

try:
    import httpx  # type: ignore

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
    _HTTPX_AVAILABLE = False


class ExternalAPIError(Exception):
    """外部 API 调用失败（网络 / 平台错误）"""


def _http_client(timeout: float):
    return httpx.AsyncClient(timeout=timeout)


async def _http_post(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Any = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    if not _HTTPX_AVAILABLE:
        raise ExternalAPIError("httpx 未安装，无法调用外部 API")
    try:
        async with _http_client(timeout) as client:
            resp = await client.post(url, headers=headers, json=json, data=data, params=params)
            resp.raise_for_status()
            return resp.json()
    except ExternalAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExternalAPIError(f"HTTP POST 失败: {exc}") from exc


async def _http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    if not _HTTPX_AVAILABLE:
        raise ExternalAPIError("httpx 未安装，无法调用外部 API")
    try:
        async with _http_client(timeout) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()
    except ExternalAPIError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExternalAPIError(f"HTTP GET 失败: {exc}") from exc


# ==================== SecretStore 集成 ====================

def get_secret_store():
    """懒导入避免循环依赖"""
    from neurova.llm.providers.secret_store import get_secret_store as _gss

    return _gss()


def get_api_key(key_name: str) -> Optional[str]:
    try:
        value = get_secret_store().get(key_name)
        return str(value) if value else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 SecretStore key %s 失败: %s", key_name, exc)
        return None


def resolve_api_key(key_names: List[str], explicit: str = "") -> Optional[str]:
    """显式 key 优先，否则逐个回落 SecretStore"""
    if explicit:
        stripped = str(explicit).strip()
        if stripped:
            return stripped
    for name in key_names:
        value = get_api_key(name)
        if value:
            return value
    return None


def _comfyui_host() -> Optional[str]:
    try:
        from neurova.core.config import get

        host = get("NEUROVA_COMFYUI_HOST", None)
        return str(host) if host else None
    except Exception:  # noqa: BLE001
        return None


def _base_url(service: str, base_url: str = "") -> str:
    if base_url:
        return base_url.rstrip("/")
    try:
        from neurova.core.config import get

        env_val = get(f"NEUROVA_{service.upper().replace('-', '_')}_API_BASE", None)
        if env_val:
            return str(env_val).rstrip("/")
    except Exception:  # noqa: BLE001
        pass
    return _DEFAULT_BASES.get(service, "").rstrip("/")


# ==================== 结果辅助 ====================

def _ok(output: Dict[str, Any], provider: str = "") -> Dict[str, Any]:
    return {"status": "success", "output": output, "error": None, "provider": provider}


def _fail(error: str, provider: str = "") -> Dict[str, Any]:
    return {"status": "failed", "output": None, "error": error, "provider": provider}


def _extract(data: Any, keys: List[str], default: Any = None) -> Any:
    """从嵌套响应中提取第一个命中的键值（顶层优先）"""
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data[key]
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in keys:
                if key in inner:
                    return inner[key]
    return default


def _deep_extract(data: Any, keys: List[str], default: Any = None) -> Any:
    """从嵌套响应中提取第一个命中的键值（跳过 data 包装层）"""
    if isinstance(data, dict):
        for key in keys:
            if key in data:
                return data[key]
        inner = data.get("data")
        if isinstance(inner, dict):
            for key in keys:
                if key in inner:
                    return inner[key]
    return default


# ==================== ImageGenClient ====================

class ImageGenClient:
    """文生图客户端：多服务商，通过 httpx 调用"""

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(_comfyui_host())
        names = IMAGE_KEY_NAMES.get(provider, [])
        return bool(resolve_api_key(names, api_key))

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
        if provider not in IMAGE_PROVIDERS:
            return _fail(f"不支持的图像服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return _fail(f"图像服务商 '{IMAGE_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            return await self._generate_comfyui(prompt, size)
        key = resolve_api_key(IMAGE_KEY_NAMES[provider], api_key)
        url = f"{_base_url(provider, base_url)}/images/generations"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"prompt": prompt, "size": size, "n": 1}
        try:
            data = await _http_post(url, headers=headers, json=body, timeout=timeout)
            url_out = _extract(data, ["url", "image_url"])
            if not url_out:
                items = _extract(data, ["data", "images"])
                if isinstance(items, list) and items:
                    url_out = _extract(items[0], ["url", "image_url"])
            return _ok(
                {"prompt": prompt, "size": size, "provider": provider, "url": url_out, "raw": data},
                provider,
            )
        except ExternalAPIError as exc:
            logger.warning("图像生成失败 (%s): %s", provider, exc)
            return _fail(str(exc), provider)

    async def _generate_comfyui(self, prompt: str, size: str) -> Dict[str, Any]:
        width, height = _parse_size(size)
        client = get_comfyui_client()
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


def get_comfyui_client():
    """懒加载 ComfyUI 客户端（延迟导入避免循环依赖）"""
    from .comfyui_client import get_comfyui_client as _impl

    return _impl()


def _parse_size(size: str):
    try:
        width, height = (int(part) for part in str(size).lower().split("x")[:2])
        return width, height
    except Exception:  # noqa: BLE001
        return 1024, 1024


_image_gen_instance: Optional[ImageGenClient] = None


def get_image_gen_client() -> ImageGenClient:
    global _image_gen_instance
    if _image_gen_instance is None:
        _image_gen_instance = ImageGenClient()
    return _image_gen_instance


def reset_image_gen_client() -> None:
    global _image_gen_instance
    _image_gen_instance = None


# ==================== VideoGenClient ====================

class VideoGenClient:
    """图生视频/文生视频客户端：提交任务 + 轮询状态"""

    def __init__(self, poll_interval: float = 2.0) -> None:
        self._poll_interval = poll_interval

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(_comfyui_host())
        names = VIDEO_KEY_NAMES.get(provider, [])
        return bool(resolve_api_key(names, api_key))

    async def generate(
        self,
        provider: str,
        prompt: str,
        api_key: str = "",
        first_frame_url: str = "",
        duration: int = 5,
        base_url: str = "",
        timeout: float = 180.0,
        max_polls: int = 10,
    ) -> Dict[str, Any]:
        provider = str(provider or "").lower()
        if provider not in VIDEO_PROVIDERS:
            return _fail(f"不支持的视频服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return _fail(f"视频服务商 '{VIDEO_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            return self._fail_not_impl("ComfyUI 图生视频暂未支持", provider)
        key = resolve_api_key(VIDEO_KEY_NAMES[provider], api_key)
        base = _base_url(provider, base_url)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body: Dict[str, Any] = {"prompt": prompt, "duration": duration}
        if first_frame_url:
            body["first_frame_url"] = first_frame_url
            body["image_url"] = first_frame_url
        try:
            submit = await _http_post(f"{base}/videos/generations", headers=headers, json=body, timeout=timeout)
            task_id = _extract(submit, ["task_id", "id"])
            if not task_id:
                return _ok(
                    {"provider": provider, "task_id": None, "video_url": None, "raw": submit},
                    provider,
                )
            for _ in range(max_polls):
                status = await _http_get(f"{base}/videos/tasks/{task_id}", headers=headers, timeout=timeout)
                task_status = str(_extract(status, ["status", "task_status"]) or "pending").lower()
                if task_status in ("succeed", "success", "completed", "done"):
                    video_url = _extract(status, ["video_url", "url", "result"])
                    if isinstance(video_url, dict):
                        video_url = _extract(video_url, ["video_url", "url"])
                    return _ok(
                        {"provider": provider, "task_id": task_id, "video_url": video_url, "raw": status},
                        provider,
                    )
                if task_status in ("failed", "error", "fail"):
                    return _fail(f"视频任务失败: {_extract(status, ['message', 'error', 'reason'], '未知原因')}", provider)
                await _sleep(self._poll_interval)
            return _fail(f"视频生成轮询超时（任务 {task_id}）", provider)
        except ExternalAPIError as exc:
            logger.warning("视频生成失败 (%s): %s", provider, exc)
            return _fail(str(exc), provider)

    async def _fail_not_impl(self, message: str, provider: str) -> Dict[str, Any]:
        return _fail(message, provider)


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


_video_gen_instance: Optional[VideoGenClient] = None


def get_video_gen_client() -> VideoGenClient:
    global _video_gen_instance
    if _video_gen_instance is None:
        _video_gen_instance = VideoGenClient()
    return _video_gen_instance


def reset_video_gen_client() -> None:
    global _video_gen_instance
    _video_gen_instance = None


# ==================== CommercePlatformClient ====================

class CommercePlatformClient:
    """电商平台数据客户端：价格 / 库存 / 评论 / 报表 / 竞品"""

    def is_available(self, platform: str, api_key: str = "") -> bool:
        platform = str(platform or "").lower()
        names = COMMERCE_KEY_NAMES.get(platform, [])
        return bool(resolve_api_key(names, api_key))

    def _headers(self, platform: str, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async def fetch_prices(
        self, platform: str, product_ids: List[str], api_key: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/prices"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"product_ids": ",".join(product_ids)})
            prices = _extract(data, ["prices", "data"])
            return _ok({"prices": prices if isinstance(prices, dict) else {}, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_inventory(
        self, platform: str, skus: List[str], api_key: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/inventory"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"skus": ",".join(skus)})
            inventory = _extract(data, ["inventory", "data"])
            return _ok({"inventory": inventory if isinstance(inventory, dict) else {}, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_reviews(
        self, platform: str, product_id: str, api_key: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/reviews"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"product_id": product_id})
            items = _deep_extract(data, ["items", "reviews"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_sales_report(
        self, platform: str, period: str = "", api_key: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/sales-report"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"period": period})
            report = _extract(data, ["report", "data"])
            if isinstance(report, dict):
                return _ok(dict(report), platform)
            return _ok({"raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_competitors(
        self, platform: str, keyword: str, api_key: str = "", base_url: str = ""
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/competitors"
        try:
            data = await _http_get(url, headers=self._headers(platform, key), params={"keyword": keyword})
            items = _deep_extract(data, ["items"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)

    async def fetch_ad_metrics(
        self,
        platform: str,
        ad_ids: List[str],
        metrics: List[str],
        api_key: str = "",
        base_url: str = "",
    ) -> Dict[str, Any]:
        """获取广告活动投放指标（曝光/点击/转化/花费等）"""
        platform = str(platform or "").lower()
        if not self.is_available(platform, api_key):
            return _fail(f"电商平台 '{COMMERCE_PLATFORMS.get(platform, platform)}' 未配置 API Key", platform)
        key = resolve_api_key(COMMERCE_KEY_NAMES.get(platform, []), api_key)
        url = f"{_base_url(platform, base_url)}/ad-metrics"
        try:
            data = await _http_get(
                url,
                headers=self._headers(platform, key),
                params={"ad_ids": ",".join(ad_ids), "metrics": ",".join(metrics)},
            )
            items = _deep_extract(data, ["items", "metrics"])
            return _ok({"items": items if isinstance(items, list) else [], "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)


_commerce_instance: Optional[CommercePlatformClient] = None


def get_commerce_platform_client() -> CommercePlatformClient:
    global _commerce_instance
    if _commerce_instance is None:
        _commerce_instance = CommercePlatformClient()
    return _commerce_instance


def reset_commerce_platform_client() -> None:
    global _commerce_instance
    _commerce_instance = None


# ==================== PublishPlatformClient ====================

class PublishPlatformClient:
    """视频发布客户端：上传并发布到短视频平台"""

    def is_available(self, platform: str, access_token: str = "") -> bool:
        platform = str(platform or "").lower()
        names = PUBLISH_KEY_NAMES.get(platform, [])
        return bool(resolve_api_key(names, access_token))

    async def publish(
        self,
        platform: str,
        video_url: str,
        title: str,
        tags: Optional[List[str]] = None,
        access_token: str = "",
        cover_url: str = "",
        description: str = "",
        base_url: str = "",
    ) -> Dict[str, Any]:
        platform = str(platform or "").lower()
        if platform not in PUBLISH_PLATFORMS:
            return _fail(f"不支持的发布平台: {platform}", platform)
        if not self.is_available(platform, access_token):
            return _fail(f"发布平台 '{PUBLISH_PLATFORMS[platform]}' 未配置 access_token", platform)
        token = resolve_api_key(PUBLISH_KEY_NAMES.get(platform, []), access_token)
        url = f"{_base_url(platform, base_url)}/video/publish"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "video_url": video_url,
            "title": title,
            "tags": tags or [],
            "cover_url": cover_url,
            "description": description,
        }
        try:
            data = await _http_post(url, headers=headers, json=body)
            item_id = _extract(data, ["item_id", "video_id", "id"])
            published_url = _extract(data, ["url", "share_url", "item_url"])
            if not published_url and item_id:
                published_url = f"https://www.{platform}.com/video/{item_id}"
            return _ok({"item_id": item_id, "url": published_url, "raw": data}, platform)
        except ExternalAPIError as exc:
            return _fail(str(exc), platform)


_publish_instance: Optional[PublishPlatformClient] = None


def get_publish_platform_client() -> PublishPlatformClient:
    global _publish_instance
    if _publish_instance is None:
        _publish_instance = PublishPlatformClient()
    return _publish_instance


def reset_publish_platform_client() -> None:
    global _publish_instance
    _publish_instance = None
