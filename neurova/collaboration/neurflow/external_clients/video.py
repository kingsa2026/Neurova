"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class VideoGenClient:
    """图生视频/文生视频客户端：提交任务 + 轮询状态"""

    def __init__(self, poll_interval: float = 2.0) -> None:
        self._poll_interval = poll_interval

    def is_available(self, provider: str, api_key: str = "") -> bool:
        provider = str(provider or "").lower()
        if provider == "comfyui":
            return bool(api._comfyui_host())
        names = api.VIDEO_KEY_NAMES.get(provider, [])
        return bool(api.resolve_api_key(names, api_key))

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
        if provider not in api.VIDEO_PROVIDERS:
            return api._fail(f"不支持的视频服务商: {provider}", provider)
        if not self.is_available(provider, api_key):
            return api._fail(f"视频服务商 '{api.VIDEO_PROVIDERS[provider]}' 未配置 API Key", provider)
        if provider == "comfyui":
            # 批次4 根因修复：_fail_not_impl 是 async 方法，漏 await 会把协程对象
            # 直接返回给调用方（.get 抛错被外层 except 吞成降级路径，错误原文丢失）
            return await self._fail_not_impl("ComfyUI 图生视频暂未支持", provider)
        key = api.resolve_api_key(api.VIDEO_KEY_NAMES[provider], api_key)
        base = api._base_url(provider, base_url)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body: Dict[str, Any] = {"prompt": prompt, "duration": duration}
        if first_frame_url:
            body["first_frame_url"] = first_frame_url
            body["image_url"] = first_frame_url
        try:
            submit = await api._http_post(f"{base}/videos/generations", headers=headers, json=body, timeout=timeout)
            task_id = api._extract(submit, ["task_id", "id"])
            if not task_id:
                return api._ok(
                    {"provider": provider, "task_id": None, "video_url": None, "raw": submit},
                    provider,
                )
            for _ in range(max_polls):
                status = await api._http_get(f"{base}/videos/tasks/{task_id}", headers=headers, timeout=timeout)
                task_status = str(api._extract(status, ["status", "task_status"]) or "pending").lower()
                if task_status in ("succeed", "success", "completed", "done"):
                    video_url = api._extract(status, ["video_url", "url", "result"])
                    if isinstance(video_url, dict):
                        video_url = api._extract(video_url, ["video_url", "url"])
                    return api._ok(
                        {"provider": provider, "task_id": task_id, "video_url": video_url, "raw": status},
                        provider,
                    )
                if task_status in ("failed", "error", "fail"):
                    return api._fail(f"视频任务失败: {api._extract(status, ['message', 'error', 'reason'], '未知原因')}", provider)
                await api._sleep(self._poll_interval)
            return api._fail(f"视频生成轮询超时（任务 {task_id}）", provider)
        except api.ExternalAPIError as exc:
            api.logger.warning("视频生成失败 (%s): %s", provider, exc)
            return api._fail(str(exc), provider)

    async def _fail_not_impl(self, message: str, provider: str) -> Dict[str, Any]:
        return api._fail(message, provider)


VideoGenClient.__module__ = api.__name__
VideoGenClient.__init__.__module__ = api.__name__
VideoGenClient.is_available.__module__ = api.__name__
VideoGenClient.generate.__module__ = api.__name__
VideoGenClient._fail_not_impl.__module__ = api.__name__
