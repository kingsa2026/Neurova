# -*- coding: utf-8 -*-
"""微信个人号 iLink Bot 渠道适配器（端到端收发，QwenPaw wechat/channel.py 协议照搬）。

NV 旧 wechat 适配器的 ilink 路径建立在虚构端点 ilink.wechat.bot 上（代码自注
"假设的端点"），真实网络下永远不可用。本模块按 QwenPaw 真实协议重建：

- 收：POST getupdates 长轮询后台任务（服务端挂 ~35s；连续失败指数退避熔断）；
- 发：sendmessage 必带该用户最近一条入站的 context_token（平台限制每 token
  ≤10 回复；manager 回复路径只传 chat_id，故适配器自持 per-user 缓存并落盘
  wechat_context_tokens.json，重启不丢）；无缓存时诚实拒发（不假成功）；
- 媒体：图片/文件/视频 CDN AES 解密落盘（metadata.image_path/file_path/video_path），
  语音优先用平台 ASR 文本，无则回传 audio_bytes 走 NV voice_precheck；
- 去重：context_token 集合 + 同用户同文本 5 分钟窗口（平台跨轮重发防护）。

wecom/official 模式仍走原 WeChatAdapter——本类只接管 mode=ilink。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.channels.base import ChannelAdapter, ChannelConfig, ChannelEventType
from neurova.channels.wechat_ilink_client import DEFAULT_BASE_URL, ILinkClient

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_FILE = "~/.Neurova/weixin_bot_token"
_TEXT_DEDUP_WINDOW_S = 300.0
_MAX_BACKOFF_S = 120.0

# 入站 item 类型（官方协议）
_ITEM_TEXT, _ITEM_IMAGE, _ITEM_VOICE, _ITEM_FILE, _ITEM_VIDEO = 1, 2, 3, 4, 5


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


class WeChatILinkAdapter(ChannelAdapter):
    """微信 iLink 个人号 Bot 适配器（真实协议，端到端收发）。"""

    # 与旧 WeChatAdapter 一致的校验面：_wechat_authenticated 按 mode 分派核验，
    # ilink 路径迁移到本类后 test_connection 仍走同一契约（connect() 已含
    # getconfig 有界校验，_connected 即真实认证态）。
    mode = "ilink"

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "wechat"
        extra = config.extra or {}
        self._extra = extra

        self._token_file = str(Path(extra.get("token_file") or _DEFAULT_TOKEN_FILE).expanduser())
        self._base_url = str(extra.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        self._media_dir = str(extra.get("media_directory") or "")

        # 凭据优先级：表单/配置 bot_token > token 文件（扫码 confirmed 落盘）
        self._bot_token = str(extra.get("bot_token") or "")
        if not self._bot_token:
            self._bot_token = self._read_token_file()

        # 群聊会话共享（manager.resolve_session_scope_id 消费，同 feishu/dingtalk）
        self.share_session_in_group = _as_bool(
            extra.get("share_session_in_group", extra.get("group_share_session", True)))

        self._client = ILinkClient(bot_token=self._bot_token, base_url=self._base_url)
        self._cursor = ""
        self._poll_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        # per-user context_token 缓存（落盘 sidecar，重启后可主动回复）
        self._context_tokens: Dict[str, str] = {}
        self._context_file = Path(self._token_file).parent / "wechat_context_tokens.json"
        self._load_context_tokens()

        self._seen_keys: "deque[str]" = deque(maxlen=512)
        self._text_seen: "deque[tuple]" = deque(maxlen=512)

    # ------------------------------------------------------------------
    # token / context 持久化
    # ------------------------------------------------------------------

    @property
    def _ilink_initialized(self) -> bool:
        """与旧 WeChatAdapter 同名校验面：connect() 的 getconfig 校验通过即为真。"""
        return bool(self._connected)

    def _read_token_file(self) -> str:
        try:
            return Path(self._token_file).read_text(encoding="utf-8").strip()
        except (OSError, IOError):
            return ""

    def _save_token_file(self) -> None:
        try:
            Path(self._token_file).parent.mkdir(parents=True, exist_ok=True)
            Path(self._token_file).write_text(self._bot_token, encoding="utf-8")
            logger.info("iLink bot_token 已持久化: %s", self._token_file)
        except OSError as e:
            logger.warning("iLink bot_token 持久化失败: %s", e)

    def _load_context_tokens(self) -> None:
        try:
            if self._context_file.exists():
                data = json.loads(self._context_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._context_tokens = {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            logger.warning("wechat ilink: context_tokens 读取失败: %s", e)

    def _save_context_tokens(self) -> None:
        try:
            self._context_file.parent.mkdir(parents=True, exist_ok=True)
            self._context_file.write_text(
                json.dumps(self._context_tokens, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("wechat ilink: context_tokens 落盘失败: %s", e)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not self._bot_token:
            logger.warning(
                "wechat(ilink) 未连接：尚无 bot_token，请在渠道页扫码登录后保存配置")
            self._connected = False
            return False
        await self._client.start()
        try:
            # 有界轻校验：getconfig 401/异常即凭据无效（诚实失败，不假连接）
            await self._client.getconfig()
        except Exception as e:
            logger.warning("wechat(ilink) 凭据校验失败: %s", e)
            await self._client.stop()
            self._connected = False
            return False
        # 表单直填的 token（非扫码路径）也落盘，重启免再扫码
        if not self._read_token_file():
            self._save_token_file()
        self._connected = True
        self._stop_event = asyncio.Event()
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("wechat(ilink) 已连接，长轮询启动")
        return True

    async def disconnect(self):
        self._connected = False
        self._stop_event.set()
        task = self._poll_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._poll_task = None
        await self._client.stop()
        logger.info("wechat(ilink) 已断开")

    async def health_check(self) -> Dict[str, Any]:
        base = await super().health_check()
        base.update({
            "mode": "ilink",
            "bot_token": (self._bot_token[:6] + "***") if self._bot_token else "",
            "base_url": self._base_url,
            "context_users": len(self._context_tokens),
        })
        return base

    # ------------------------------------------------------------------
    # 收：长轮询
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """getupdates 长轮询主循环（连续失败指数退避，成功即复位）。"""
        consecutive_failures = 0
        while not self._stop_event.is_set():
            try:
                data = await self._client.getupdates(self._cursor)
                new_cursor = data.get("get_updates_buf")
                if new_cursor is not None:
                    self._cursor = new_cursor
                msgs: List[Dict[str, Any]] = data.get("msgs") or []
                for msg in msgs:
                    try:
                        await self._on_message(msg)
                    except Exception:
                        logger.exception("wechat ilink _on_message 异常")
                consecutive_failures = 0
                ret = data.get("ret", -1)
                if ret != 0 and not msgs:
                    if ret != -1:  # ret=-1 是正常长轮询超时
                        logger.warning("wechat getupdates ret=%s，3s 后重试", ret)
                        await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(5 * (2 ** (consecutive_failures - 1)), _MAX_BACKOFF_S)
                logger.warning("wechat ilink 轮询异常（第 %d 次），%ds 后重试: %s",
                               consecutive_failures, backoff, e)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break
                except asyncio.TimeoutError:
                    pass

    def _is_duplicate(self, key: str) -> bool:
        if not key:
            return False
        if key in self._seen_keys:
            return True
        self._seen_keys.append(key)
        return False

    def _is_text_duplicate(self, user: str, text: str) -> bool:
        now = time.time()
        dup = any(u == user and t == text and now - ts < _TEXT_DEDUP_WINDOW_S
                  for u, t, ts in self._text_seen)
        self._text_seen.append((user, text, now))
        return dup

    async def _on_message(self, msg: Dict[str, Any]) -> None:
        """解析一条入站 WeChatMessage → ChannelMessage → 事件回调。"""
        from_user_id = msg.get("from_user_id", "")
        context_token = msg.get("context_token", "")
        group_id = msg.get("group_id", "")
        # 只处理用户→bot 消息（message_type==1；bot 自身回显等跳过）
        if msg.get("message_type", 0) != 1:
            return
        dedup_key = context_token or f"{from_user_id}_{msg.get('msg_id', '')}"
        if self._is_duplicate(dedup_key):
            logger.debug("wechat ilink: 重复消息跳过 %s", dedup_key[:40])
            return

        text_parts: List[str] = []
        media: Dict[str, Any] = {}
        message_type = "text"
        for item in msg.get("item_list") or []:
            it = item.get("type", 0)
            if it == _ITEM_TEXT:
                text = ((item.get("text_item") or {}).get("text", "")).strip()
                if text:
                    text_parts.append(text)
            elif it == _ITEM_IMAGE:
                path = await self._download_item(item.get("image_item") or {}, "image.jpg")
                if path:
                    media["image_path"] = path
                    message_type = "image"
                else:
                    text_parts.append("[image: download failed]")
            elif it == _ITEM_VOICE:
                voice = item.get("voice_item") or {}
                asr = ""
                ti = voice.get("text_item")
                if isinstance(ti, dict):
                    asr = (ti.get("text", "") or "").strip()
                asr = asr or (voice.get("text", "") or "").strip()
                if asr:
                    text_parts.append(asr)
                else:
                    raw = await self._download_bytes(item.get("voice_item") or {})
                    if raw:
                        media["audio_bytes"] = raw
                        message_type = "voice"
                    else:
                        text_parts.append("[voice: no transcription]")
            elif it == _ITEM_FILE:
                fi = item.get("file_item") or {}
                name = fi.get("file_name") or "file.bin"
                path = await self._download_item(fi, name)
                if path:
                    media["file_path"] = path
                    message_type = "file"
                else:
                    text_parts.append("[file: download failed]")
            elif it == _ITEM_VIDEO:
                path = await self._download_item(item.get("video_item") or {}, "video.mp4")
                if path:
                    media["video_path"] = path
                    message_type = "video"
                else:
                    text_parts.append("[video: download failed]")

        text = "\n".join(text_parts).strip()
        if text and message_type == "text":
            if self._is_text_duplicate(from_user_id, text):
                logger.debug("wechat ilink: 内容重复跳过 user=%s", from_user_id[:12])
                return
        if not text and not media:
            return

        # 缓存最近 context_token（主动/后续回复用），落盘重启不丢
        if from_user_id and context_token:
            self._context_tokens[from_user_id] = context_token
            self._save_context_tokens()

        content = text or {"image": "[图片]", "voice": "[语音]",
                           "file": f"[文件] {media.get('file_path', '')}",
                           "video": "[视频]"}.get(message_type, "")
        channel_msg = self._make_message(
            message_id=str(msg.get("msg_id", "") or context_token or ""),
            sender_id=from_user_id,
            sender_name=from_user_id,
            content=content,
            chat_id=group_id or from_user_id,
            chat_type="group" if group_id else "p2p",
            message_type=message_type,
            metadata={"wechat_context_token": context_token, **media},
            raw_event=msg,
        )
        logger.info("wechat ilink recv: from=%s group=%s type=%s text_len=%d",
                    from_user_id[:20], (group_id or "")[:20], message_type, len(text))
        await self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)

    async def _download_bytes(self, item_media_owner: Dict[str, Any]) -> Optional[bytes]:
        media = item_media_owner.get("media") or {}
        eqp = media.get("encrypt_query_param", "")
        if not eqp:
            return None
        try:
            return await self._client.download_media(
                "", aes_key_b64=media.get("aes_key", ""), encrypt_query_param=eqp)
        except Exception as e:
            logger.warning("wechat ilink 媒体下载失败: %s", e)
            return None

    async def _download_item(self, item: Dict[str, Any], default_name: str) -> Optional[str]:
        raw = await self._download_bytes(item)
        if raw is None:
            return None
        name = item.get("file_name") or default_name
        # 图片协议字段是 aeskey(hex)（media.aes_key 缺时）——download_media 已兼容
        if default_name.endswith(".jpg") and item.get("aeskey") and not (item.get("media") or {}).get("aes_key"):
            try:
                eqp = (item.get("media") or {}).get("encrypt_query_param", "")
                raw = await self._client.download_media("", aes_key_b64=item["aeskey"],
                                                        encrypt_query_param=eqp)
            except Exception as e:
                logger.warning("wechat ilink 图片按 hex aeskey 重下载失败: %s", e)
                return None
        base = self._media_dir or os.path.join(tempfile.gettempdir(), "neurova_wechat_ilink")
        try:
            Path(base).mkdir(parents=True, exist_ok=True)
            path = Path(base) / f"{int(time.time() * 1000)}_{name}"
            path.write_bytes(raw)
            return str(path)
        except OSError as e:
            logger.warning("wechat ilink 媒体落盘失败: %s", e)
            return None

    # ------------------------------------------------------------------
    # 发
    # ------------------------------------------------------------------

    async def send_message(self, chat_id: str, content: str,
                           message_type: str = "text", **kwargs) -> Optional[str]:
        """回复用户。平台硬约束：必带该用户最近入站的 context_token；
        缓存缺失（从未收过消息）时诚实拒发返回 None。"""
        user_id = kwargs.get("user_id") or chat_id
        ctx = self._context_tokens.get(str(user_id), "")
        if not ctx:
            logger.warning(
                "wechat ilink 无法主动发消息给 %s：无 context_token（iLink 仅支持"
                "被动回复，请先由该用户发起会话）", str(user_id)[:20])
            return None
        if not self._connected:
            logger.warning("wechat ilink 未连接，发送跳过")
            return None
        try:
            if message_type == "image" and kwargs.get("image_path"):
                resp = await self._client.send_image(str(user_id), str(kwargs["image_path"]), ctx)
            elif message_type in ("file", "video") and kwargs.get("file_path"):
                fn = str(kwargs.get("file_name") or Path(str(kwargs["file_path"])).name)
                if message_type == "file":
                    resp = await self._client.send_file(str(user_id), str(kwargs["file_path"]), fn, ctx)
                else:
                    resp = await self._client.send_video(str(user_id), str(kwargs["file_path"]), ctx)
            else:
                resp = await self._client.send_text(str(user_id), content, ctx)
            if resp.get("ret", 0) != 0:
                logger.error("wechat ilink 发送失败: %s", resp)
                return None
            return str(resp.get("msg_id") or resp.get("message_id") or f"wx_{int(time.time())}")
        except Exception as e:
            logger.exception("wechat ilink 发送异常: %s", e)
            return None
