from __future__ import annotations

import asyncio

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

from neurova.channels.voice_ingress import VOICE_DOWNLOAD_MAX_BYTES

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

    def fetchVoiceBytes(self: Any, fileId: str) -> Optional[bytes]:
        """按 file_id 取回入站语音/音频字节：getFile 拿相对路径 → /file/bot<token>/<路径>。

        同步实现——调用点在轮询线程里，不进事件循环。任一步失败返回 None，由调用方降级
        占位：取不到字节不能把整条消息吞掉。超限的语音**先按声明长度拒收**（`stream=True`
        只读头），再按累计字节拒收，不为拒收而先把大文件吸进内存。
        """
        if not REQUESTS_AVAILABLE:
            logger.warning("Telegram 语音下载跳过: requests 库未安装")
            return None

        info = self._api_request("GET", f"/bot{self.bot_token}/getFile", params={"file_id": fileId})
        if not info.get("ok"):
            logger.warning("Telegram getFile 失败: %s", info.get("description"))
            return None
        filePath = str((info.get("result") or {}).get("file_path") or "")
        if not filePath:
            logger.warning("Telegram getFile 未返回 file_path，放弃取字节")
            return None

        url = f"{self.API_BASE}/file/bot{self.bot_token}/{filePath}"
        resp = None
        try:
            resp = requests.get(url, timeout=20, stream=True, proxies=self._proxies or None)
            if resp.status_code != 200:
                logger.warning("Telegram 语音下载 HTTP %s", resp.status_code)
                return None
            declared = resp.headers.get("Content-Length")
            if declared and int(declared) > VOICE_DOWNLOAD_MAX_BYTES:
                logger.warning("Telegram 语音声明长度超上限，拒收: %s 字节", declared)
                return None
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                buf += chunk
                if len(buf) > VOICE_DOWNLOAD_MAX_BYTES:
                    logger.warning("Telegram 语音实际字节超上限，拒收")
                    return None
            return bytes(buf)
        except Exception as e:  # noqa: BLE001 - 取字节失败由调用方降级占位
            logger.warning("Telegram 语音下载异常: %s", e)
            return None
        finally:
            if resp is not None:
                resp.close()

    async def _download_url(self: Any, url: str, timeout: int = 60) -> bytes | None:
        # 批次0：facade 产物契约是服务端本地路径（provider URL 临时有效，生成即落盘）
        if url and not url.lower().startswith(("http://", "https://", "data:")):
            from pathlib import Path as _Path

            try:
                p = _Path(url)
                if p.is_file():
                    return p.read_bytes()
            except OSError:
                pass
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
