from __future__ import annotations

import asyncio

from neurova.core.logger import get_logger
from typing import Any, Dict

try:
    import requests  # type: ignore[import-not-found]
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = get_logger(__name__)


class TelegramAPIMixin:
    """Telegram API client mixin — low-level request, download, temp file."""

    def _api_request(self: Any, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not REQUESTS_AVAILABLE:
            return {"ok": False, "description": "requests 库未安装"}

        url = f"{self.API_BASE}{path}"
        kwargs.setdefault("timeout", 10)
        if self._proxies:
            kwargs["proxies"] = self._proxies

        try:
            resp = requests.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            logger.error("Telegram API 请求超时: %s", url)
            return {"ok": False, "description": "请求超时"}
        except requests.exceptions.HTTPError as e:
            logger.error("Telegram API HTTP 错误: %s", e)
            return {"ok": False, "description": f"HTTP 错误: {e.response.status_code}"}
        except Exception as e:
            logger.error("Telegram API 请求异常: %s", e)
            return {"ok": False, "description": str(e)}

    async def _download_url(self: Any, url: str, timeout: int = 60) -> bytes | None:
        try:
            import httpx  # type: ignore[import-not-found]
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.content
                logger.error("下载失败 HTTP %s: %s", response.status_code, url)
                return None
        except Exception:
            pass

        try:
            # P2-12: 回退分支为同步 requests，直调阻塞事件循环至 60s
            response = await asyncio.to_thread(requests.get, url, timeout=timeout)
            if response.status_code == 200:
                return response.content
            logger.error("下载失败 HTTP %s: %s", response.status_code, url)
            return None
        except Exception as e:
            logger.error("下载异常: %s", e)
            return None

    async def _save_temp_file(self: Any, data: bytes, extension: str) -> str | None:
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as f:
                f.write(data)
                temp_path = f.name
            logger.info("临时文件已保存: %s", temp_path)
            return temp_path
        except Exception as e:
            logger.error("保存临时文件失败: %s", e)
            return None

    def _cleanup_temp_file(self: Any, temp_path: str | None) -> None:
        """C-18: 统一清理 _save_temp_file 产出的临时文件（消费侧 finally 调用）。

        delete=False 的 NamedTemporaryFile 无人清理会无限堆积在磁盘；
        清理失败仅告警（临时文件残留不应掩盖发送结果/二次抛错）。
        """
        if not temp_path:
            return
        import os
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("临时文件清理失败: %s (%s)", temp_path, e)
