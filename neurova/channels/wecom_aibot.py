# -*- coding: utf-8 -*-
"""企业微信「智能机器人」渠道适配器（aibot WebSocket 长连接，端到端收发）。

对齐 QwenPaw wecom/channel.py：使用官方 `wecom-aibot-python-sdk`（import aibot）
的 WSClient 事件驱动模型——后台线程跑 SDK 的 asyncio 事件循环（connect +
run_forever），收到 message 帧解析成 NV ChannelMessage 经主事件循环派发；回复
用 reply_stream(frame, finish=True) 调度回 SDK 线程执行。

与旧 WeComAdapter（企业自建应用 corpid/agentid + HTTP 回调验签）互斥：本类走
BotID + Secret 长连接，无需公网回调地址（官方文档 101039/101463）。工厂按
bot_id/secret 是否存在分派：有→本类，无→旧 WeComAdapter。

线程纪律：SDK 的协程只能在其 ws_loop 线程执行；主 loop 通过
asyncio.run_coroutine_threadsafe + wrap_future 跨线程调用；入站事件通过
run_coroutine_threadsafe 回投主 loop（与 feishu/dingtalk/wecom 回调同构）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.channels.base import ChannelAdapter, ChannelConfig, ChannelEventType

logger = logging.getLogger(__name__)


class WeComAIBotAdapter(ChannelAdapter):
    """企业微信智能机器人（aibot WS 长连接）适配器。"""

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "wecom"
        extra = config.extra or {}
        self._bot_id = str(config.app_id or extra.get("bot_id", ""))
        self._secret = str(config.app_secret or extra.get("secret", ""))
        self._ws_url = str(extra.get("ws_url", "") or "")
        self._media_dir = str(extra.get("media_dir", "") or extra.get("media_directory", "") or "")
        self._max_reconnect = int(extra.get("max_reconnect_attempts", -1))

        _cfg_meta = getattr(config, "metadata", None) or extra
        _share = _cfg_meta.get("share_session_in_group", _cfg_meta.get("group_share_session", True))
        self.share_session_in_group = (
            _share.strip().lower() not in ("false", "0", "no", "off")
            if isinstance(_share, str) else bool(_share)
        )

        self._client = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._authenticated = threading.Event()
        self._auth_failed = threading.Event()
        self._last_error: str = ""
        self._seen_msg_ids: "set[str]" = set()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not self._bot_id or not self._secret:
            logger.warning("wecom(aibot) 未连接：缺 bot_id/secret（智能机器人长连接凭证）")
            return False
        try:
            from aibot import WSClient, WSClientOptions
        except ImportError:
            logger.error("wecom(aibot) 需要 wecom-aibot-python-sdk：pip install wecom-aibot-python-sdk")
            return False

        self._main_loop = asyncio.get_running_loop()
        options = WSClientOptions(
            bot_id=self._bot_id,
            secret=self._secret,
            max_reconnect_attempts=self._max_reconnect,
            **({"ws_url": self._ws_url} if self._ws_url else {}),
        )
        self._client = WSClient(options)
        self._client.on("message", self._on_message_sync)
        self._client.on("authenticated", self._on_authenticated)
        self._client.on("error", self._on_error)

        self._authenticated.clear()
        self._auth_failed.clear()
        self._ws_thread = threading.Thread(
            target=self._run_ws_forever, daemon=True, name="wecom-aibot-ws")
        self._ws_thread.start()

        # 有界等待认证结果：拿到 authenticated 才算真连接（诚实 test_connection）；
        # SDK error 事件置 _auth_failed，立即提前退出，不空等超时。
        ok = await asyncio.get_running_loop().run_in_executor(
            None, self._wait_auth, 15.0)
        if ok:
            self._connected = True
            logger.info("wecom(aibot) 已连接（bot_id=%s）", self._bot_id[:12])
            return True
        self._connected = False
        logger.warning("wecom(aibot) 认证失败/超时：%s", self._last_error or "未收到 authenticated 事件")
        await self.disconnect()
        return False

    def _wait_auth(self, timeout: float) -> bool:
        """阻塞等 authenticated；error 置位即提前返回 False（供 executor 调用）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._authenticated.is_set():
                return True
            if self._auth_failed.is_set():
                return False
            time.sleep(0.05)
        return self._authenticated.is_set()

    def _run_ws_forever(self) -> None:
        ws_loop = asyncio.SelectorEventLoop() if sys.platform == "darwin" else asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        self._ws_loop = ws_loop
        try:
            ws_loop.run_until_complete(self._client.connect())
            ws_loop.run_forever()
        except Exception:
            logger.exception("wecom(aibot) WS 线程异常")
        finally:
            try:
                pending = asyncio.all_tasks(ws_loop)
                for t in pending:
                    t.cancel()
                if pending:
                    ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                ws_loop.run_until_complete(ws_loop.shutdown_asyncgens())
                ws_loop.close()
            except Exception:
                pass
            self._ws_loop = None

    async def disconnect(self):
        self._connected = False
        client, ws_loop, thread = self._client, self._ws_loop, self._ws_thread
        if client is not None and ws_loop is not None and ws_loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._safe_disconnect(client), ws_loop)
                fut.result(timeout=5)
            except Exception as e:
                logger.debug("wecom(aibot) 断开调度异常: %s", e)
        if ws_loop is not None and ws_loop.is_running():
            ws_loop.call_soon_threadsafe(ws_loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._ws_thread = None
        self._client = None
        logger.info("wecom(aibot) 已断开")

    @staticmethod
    async def _safe_disconnect(client) -> None:
        try:
            client.disconnect()
        except Exception:
            pass

    def _on_authenticated(self):
        self._authenticated.set()

    def _on_error(self, error: Any):
        self._last_error = str(error)
        self._auth_failed.set()
        logger.error("wecom(aibot) SDK error: %s", error)

    async def health_check(self) -> Dict[str, Any]:
        base = await super().health_check()
        base.update({
            "mode": "aibot_ws",
            "bot_id": (self._bot_id[:6] + "***") if self._bot_id else "",
            "ws_thread_alive": bool(self._ws_thread and self._ws_thread.is_alive()),
        })
        return base

    # ------------------------------------------------------------------
    # 收：SDK 线程 message 事件 → 主 loop
    # ------------------------------------------------------------------

    def _on_message_sync(self, frame: Any) -> None:
        if self._main_loop is None or not self._main_loop.is_running():
            logger.warning("wecom(aibot) 主事件循环未运行，丢弃消息")
            return
        asyncio.run_coroutine_threadsafe(self._on_message(frame), self._main_loop)

    async def _on_message(self, frame: Any) -> None:
        try:
            body = (frame or {}).get("body") or {}
            msgtype = body.get("msgtype") or ""
            sender_id = (body.get("from") or {}).get("userid", "")
            chatid = body.get("chatid", "") or sender_id
            chat_type = body.get("chattype", "single")
            msg_id = body.get("msgid") or f"{sender_id}_{body.get('send_time', '')}"
            if msg_id and msg_id in self._seen_msg_ids:
                return
            if msg_id:
                self._seen_msg_ids.add(msg_id)
                if len(self._seen_msg_ids) > 1024:
                    self._seen_msg_ids.pop()

            text_parts: List[str] = []
            media: Dict[str, Any] = {}
            message_type = "text"
            if msgtype == "text":
                text = ((body.get("text") or {}).get("content", "")).strip()
                if text:
                    text_parts.append(text)
            elif msgtype == "voice":
                asr = ((body.get("voice") or {}).get("content", "") or "").strip()
                text_parts.append(asr or "[voice: no transcription]")
            elif msgtype in ("image", "file"):
                info = body.get(msgtype) or {}
                url = info.get("url") or ""
                path = await self._download_media(url, info.get("aeskey") or "",
                                                  info.get("filename") or f"{msgtype}.bin")
                if path:
                    media[{"image": "image_path", "file": "file_path"}[msgtype]] = path
                    message_type = msgtype
                else:
                    text_parts.append(f"[{msgtype}: download failed]")
            elif msgtype == "mixed":
                for part in (body.get("mixed") or {}).get("items", []) or []:
                    if part.get("msgtype") == "text":
                        t = ((part.get("text") or {}).get("content", "") or "").strip()
                        if t:
                            text_parts.append(t)

            text = "\n".join(text_parts).strip()
            if not text and not media:
                return
            content = text or {"image": "[图片]", "file": "[文件]", "voice": "[语音]"}.get(message_type, "")
            channel_msg = self._make_message(
                message_id=str(msg_id or ""),
                sender_id=sender_id,
                sender_name=sender_id,
                content=content,
                chat_id=chatid,
                chat_type="group" if chat_type == "group" else "p2p",
                message_type=message_type,
                metadata={"wecom_frame": frame, "wecom_chatid": chatid, **media},
                raw_event=body,
            )
            await self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
        except Exception:
            logger.exception("wecom(aibot) _on_message 失败")

    async def _download_media(self, url: str, aes_key: str, filename_hint: str) -> Optional[str]:
        if not url or self._client is None:
            return None
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._client.download_file(url, aes_key or None), self._ws_loop)
            data, fname = await asyncio.wrap_future(fut)
        except Exception as e:
            logger.warning("wecom(aibot) 媒体下载失败: %s", e)
            return None
        base = self._media_dir or str(Path.home() / ".neurova" / "wecom_media")
        try:
            Path(base).mkdir(parents=True, exist_ok=True)
            path = Path(base) / f"{int(time.time() * 1000)}_{fname or filename_hint}"
            path.write_bytes(data)
            return str(path)
        except OSError as e:
            logger.warning("wecom(aibot) 媒体落盘失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 发：reply_stream 调度回 SDK 线程
    # ------------------------------------------------------------------

    async def send_message(self, chat_id: str, content: str,
                           message_type: str = "text", **kwargs) -> Optional[str]:
        if self._client is None or self._ws_loop is None:
            logger.warning("wecom(aibot) 未连接，发送跳过")
            return None
        frame = kwargs.get("wecom_frame") or (self._last_frame_for(chat_id))
        body = {"msgtype": "markdown", "markdown": {"content": content}}
        try:
            from aibot import generate_req_id
            if frame is not None:
                coro = self._client.reply_stream(
                    frame, stream_id=generate_req_id("stream"), content=content, finish=True)
            else:
                coro = self._client.send_message(chat_id, body)
            fut = asyncio.run_coroutine_threadsafe(coro, self._ws_loop)
            await asyncio.wrap_future(fut)
            return f"wecom_{int(time.time())}"
        except Exception as e:
            logger.exception("wecom(aibot) 发送失败: %s", e)
            return None

    def _last_frame_for(self, chat_id: str) -> Optional[Dict[str, Any]]:
        return None  # 简化：主动发送走 send_message(chat_id)；被动回复由 manager 透传 kwargs
