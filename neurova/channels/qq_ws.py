# -*- coding: utf-8 -*-
"""QQ 机器人 WebSocket 接收回路适配器（官方网关，端到端收发）。

补齐 NV QQ 此前"只能发不能收"的断裂：官方规范是 WebSocket 网关收事件 +
HTTP API 回复。本模块在后台线程用 `websockets` 连网关，走标准握手：

  HELLO(op10) → IDENTIFY(op2, token=QQBot {access_token}, intents) / RESUME(op6)
  DISPATCH(op0): READY 存 session_id；C2C_MESSAGE_CREATE / GROUP_AT_MESSAGE_CREATE
    / AT_MESSAGE_CREATE / DIRECT_MESSAGE_CREATE → 解析成 NV ChannelMessage 回投主 loop
  HEARTBEAT(op1) 周期发 last_seq；HEARTBEAT_ACK(op11)；RECONNECT(op7)/
    INVALID_SESSION(op9) → 断线重连（指数退避）。

回复走 HTTP：单聊 /v2/users/{openid}/messages、群聊 /v2/groups/{group_openid}/messages，
body 携带被动回复所需的 msg_id + 递增 msg_seq（官方：同一 msg_id 60 分钟内多次回复
须递增 seq）。鉴权头 QQBot {access_token}（旧 Bot {appid}.{token} 头已废弃）。

凭据校验（access_token + GET /gateway/bot）通过才算连接；无入站消息时主动发送
诚实失败（QQ 被动回复机制）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.channels.base import ChannelAdapter, ChannelConfig, ChannelEventType

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger(__name__)

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

OP_DISPATCH, OP_HEARTBEAT, OP_IDENTIFY, OP_RESUME = 0, 1, 2, 6
OP_RECONNECT, OP_INVALID_SESSION, OP_HELLO, OP_HEARTBEAT_ACK = 7, 9, 10, 11

INTENT_GUILD_MEMBERS = 1 << 1
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_INTERACTION = 1 << 26
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30

# event → (message_type, sender_keys, extra_meta_keys)
_MESSAGE_EVENT_SPECS: Dict[str, tuple] = {
    "C2C_MESSAGE_CREATE": ("c2c", ("user_openid", "id"), ()),
    "GROUP_AT_MESSAGE_CREATE": ("group", ("member_openid", "id"), ("group_openid",)),
    "AT_MESSAGE_CREATE": ("guild", ("id", "username"), ("channel_id", "guild_id")),
    "DIRECT_MESSAGE_CREATE": ("dm", ("id", "username"), ("channel_id", "guild_id")),
}
_RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]


class QQWebSocketAdapter(ChannelAdapter):
    """QQ 官方 WebSocket 网关收发适配器。"""

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self.config.channel_type = "qq"
        extra = config.extra or {}
        self.app_id = str(config.app_id or extra.get("app_id", ""))
        self.secret = str(config.app_secret or extra.get("client_secret", ""))
        self.token = str(extra.get("token", ""))  # HTTP 回调验签可选，WS 不需要
        self._cfg_extra = extra

        _share = extra.get("share_session_in_group", extra.get("group_share_session", True))
        self.share_session_in_group = (
            _share.strip().lower() not in ("false", "0", "no", "off")
            if isinstance(_share, str) else bool(_share))

        self.access_token = ""
        self.token_expire_time = 0.0
        self._session_id: Optional[str] = None
        self._last_seq: Optional[int] = None
        self._reconnect_attempts = 0
        self._stop_event = threading.Event()
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._hb_interval_ms = 45000
        # 被动回复所需：per-chat 最近入站 msg_id + msg_seq 计数
        self._last_msg_id: Dict[str, str] = {}
        self._msg_seq: Dict[str, int] = {}
        self._seen_ids: "set[str]" = set()

    # ------------------------------------------------------------------
    # 鉴权（requests，可注入替身）
    # ------------------------------------------------------------------

    def _ensure_token(self) -> bool:
        if self.access_token and time.time() < self.token_expire_time:
            return True
        if not REQUESTS_AVAILABLE:
            return False
        try:
            resp = requests.post(TOKEN_URL,
                                 json={"appId": self.app_id, "clientSecret": self.secret},
                                 timeout=10)
            data = resp.json()
            token = data.get("access_token", "")
            if resp.status_code == 200 and token:
                self.access_token = token
                self.token_expire_time = time.time() + max(int(data.get("expires_in", 7200)) - 60, 60)
                return True
            logger.error("QQ access_token 获取失败: %s", data)
            return False
        except Exception as e:
            logger.error("QQ access_token 请求异常: %s", e)
            return False

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"QQBot {self.access_token}",
                "Content-Type": "application/json"}

    def _fetch_gateway_url(self) -> str:
        resp = requests.get(f"{API_BASE}/gateway", headers=self._auth_headers(), timeout=10)
        return (resp.json() or {}).get("url", "")

    def _verify_credentials(self) -> bool:
        try:
            resp = requests.get(f"{API_BASE}/gateway/bot", headers=self._auth_headers(), timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error("QQ 凭证校验异常: %s", e)
            return False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not self.app_id or not self.secret:
            logger.warning("qq(ws) 未连接：缺 app_id/client_secret")
            return False
        self._main_loop = asyncio.get_running_loop()
        if not await asyncio.to_thread(self._ensure_token):
            return False
        if not await asyncio.to_thread(self._verify_credentials):
            logger.warning("qq(ws) 凭证校验失败（GET /gateway/bot）")
            return False
        self._stop_event.clear()
        self._connected = True
        self._ws_thread = threading.Thread(target=self._run_ws_forever, daemon=True, name="qq-ws")
        self._ws_thread.start()
        logger.info("qq(ws) 已连接，网关接收线程启动")
        return True

    def _run_ws_forever(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ws_loop = loop
        try:
            loop.run_until_complete(self._ws_main())
        except Exception:
            logger.exception("qq(ws) 网关线程异常")
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except Exception:
                pass
            self._ws_loop = None

    async def _ws_main(self) -> None:
        import websockets
        while not self._stop_event.is_set():
            try:
                # _ensure_token 是同步方法：必须 to_thread 包装。直接 await 其
                # bool 返回 → TypeError → 重连死循环，网关永远连不上
                # （2026-09-15 QQ"该机器人未连接服务"事故）
                await asyncio.to_thread(self._ensure_token)
                url = await asyncio.to_thread(self._fetch_gateway_url)
                if not url:
                    raise RuntimeError("gateway url empty")
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    hb_task = asyncio.ensure_future(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            action = self._handle_frame(json.loads(raw), ws)
                            if action == "break":
                                break
                    finally:
                        hb_task.cancel()
                        self._ws = None
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning("qq(ws) 连接中断，重连：%s", e)
            if self._stop_event.is_set():
                break
            delay = _RECONNECT_DELAYS[min(self._reconnect_attempts, len(_RECONNECT_DELAYS) - 1)]
            self._reconnect_attempts += 1
            await asyncio.sleep(delay)

    async def _heartbeat(self, ws) -> None:
        while not self._stop_event.is_set():
            await asyncio.sleep(self._hb_interval_ms / 1000.0)
            try:
                await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._last_seq}))
            except Exception:
                return

    def _handle_frame(self, payload: Dict[str, Any], ws) -> Optional[str]:
        op = payload.get("op")
        d = payload.get("d")
        s = payload.get("s")
        t = payload.get("t")
        if s is not None:
            self._last_seq = s

        if op == OP_HELLO:
            self._hb_interval_ms = (d or {}).get("heartbeat_interval", 45000)
            token = f"QQBot {self.access_token}"
            if self._session_id and self._last_seq is not None:
                coro = ws.send(json.dumps({"op": OP_RESUME, "d": {
                    "token": token, "session_id": self._session_id, "seq": self._last_seq}}))
            else:
                intents = (INTENT_PUBLIC_GUILD_MESSAGES | INTENT_GUILD_MEMBERS | INTENT_INTERACTION
                           | INTENT_DIRECT_MESSAGE | INTENT_GROUP_AND_C2C)
                coro = ws.send(json.dumps({"op": OP_IDENTIFY, "d": {
                    "token": token, "intents": intents, "shard": [0, 1]}}))
            if self._ws_loop:
                asyncio.run_coroutine_threadsafe(coro, self._ws_loop)
            return None

        if op == OP_DISPATCH:
            if t == "READY":
                self._session_id = (d or {}).get("session_id")
                self._reconnect_attempts = 0
            elif t == "RESUMED":
                self._reconnect_attempts = 0
            elif t in _MESSAGE_EVENT_SPECS:
                self._on_msg_event(t, d or {})
            elif t in ("GROUP_DEL_ROBOT", "KICK_GROUP_ROBOT"):
                self._on_bot_removed(d or {})
            elif t == "GROUP_ADD_ROBOT":
                self._on_bot_added(d or {})
            return None

        if op == OP_HEARTBEAT_ACK:
            return None
        if op == OP_RECONNECT:
            return "break"
        if op == OP_INVALID_SESSION:
            if not d:  # 不可恢复
                self._session_id = None
                self._last_seq = None
            return "break"
        return None

    # ------------------------------------------------------------------
    # 收：入站事件 → ChannelMessage → 主 loop
    # ------------------------------------------------------------------

    def _on_msg_event(self, event_type: str, d: Dict[str, Any]) -> None:
        spec = _MESSAGE_EVENT_SPECS.get(event_type)
        if spec is None:
            return
        message_type, sender_keys, extra_keys = spec
        author = d.get("author") or {}
        text = (d.get("content") or "").strip()
        msg_id = d.get("id", "")
        if msg_id in self._seen_ids:
            return
        if msg_id:
            self._seen_ids.add(msg_id)
            if len(self._seen_ids) > 1024:
                self._seen_ids.pop()

        sender = ""
        for key in sender_keys:
            sender = author.get(key) or ""
            if sender:
                break
        if not sender:
            return

        is_group = message_type in ("group", "guild")
        meta: Dict[str, Any] = {
            "qq_message_type": message_type, "qq_msg_id": msg_id,
            "user_name": author.get("username", ""), "is_group": is_group,
        }
        for key in extra_keys:
            meta[key] = d.get(key, "")
        # @提及：官方群消息 at_infos（被@成员列表）→ metadata.mentions，供 require_mention 判定
        at_infos = d.get("at_infos") or d.get("mentions") or []
        if at_infos:
            meta["mentions"] = at_infos
        # 记录被动回复所需 msg_id
        chat_id = meta.get("group_openid") or meta.get("channel_id") or sender
        if msg_id:
            self._last_msg_id[chat_id] = msg_id

        if not text and not d.get("attachments"):
            return
        att = d.get("attachments") or []
        media: Dict[str, Any] = {}
        out_type = "text"
        if att:
            first = att[0] if isinstance(att[0], dict) else {}
            if first.get("url"):
                media["qq_attachment_url"] = first.get("url")
                out_type = {"image": "image", "video": "video", "file": "file"}.get(
                    first.get("content_type", ""), "file")

        channel_msg = self._make_message(
            message_id=str(msg_id or ""),
            sender_id=sender,
            sender_name=author.get("username", "") or sender,
            content=text or {"image": "[图片]", "video": "[视频]", "file": "[文件]"}.get(out_type, ""),
            chat_id=chat_id,
            chat_type="group" if is_group else "p2p",
            message_type=out_type if not text else "text",
            metadata={**meta, **media},
            raw_event=d,
        )
        if self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg),
                self._main_loop)

    # ------------------------------------------------------------------
    # 发：HTTP 被动回复（msg_id + 递增 msg_seq）
    # ------------------------------------------------------------------

    def _emit_chat_event(self, event_type, group_openid: str) -> None:
        """群成员变更（机器人被移出/加入群）→ CHAT_BOT_REMOVED/ADDED。"""
        if not group_openid:
            return
        msg = self._make_message(
            message_id="", sender_id="", sender_name="", content="",
            chat_id=group_openid, chat_type="group", message_type="event",
        )
        if self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(self._emit_event(event_type, msg), self._main_loop)

    def _on_bot_removed(self, d: Dict[str, Any]) -> None:
        self._emit_chat_event(ChannelEventType.CHAT_BOT_REMOVED, d.get("group_openid", ""))

    def _on_bot_added(self, d: Dict[str, Any]) -> None:
        self._emit_chat_event(ChannelEventType.CHAT_BOT_ADDED, d.get("group_openid", ""))

    def _reply_path(self, chat_id: str, message_type: str) -> str:
        # 官方分三类端点：频道(guild/dm)→/channels/{channel_id}、群→/v2/groups/{group_openid}、
        # 单聊→/v2/users/{openid}。此前 guild 误并入 group → 频道回复走错端点必失败。
        if message_type == "guild" or message_type == "dm":
            return f"{API_BASE}/channels/{chat_id}/messages"
        if message_type == "group" or chat_id.startswith(("g_", "oc_")):
            return f"{API_BASE}/v2/groups/{chat_id}/messages"
        return f"{API_BASE}/v2/users/{chat_id}/messages"

    async def send_message(self, chat_id: str, content: str,
                           message_type: str = "text", **kwargs) -> Optional[str]:
        if not await asyncio.to_thread(self._ensure_token):
            return None
        msg_id = kwargs.get("message_id") or self._last_msg_id.get(chat_id, "")
        if not msg_id:
            logger.warning(
                "qq 无法主动发消息给 %s：官方仅支持被动回复（需入站 msg_id）", chat_id)
            return None
        seq_key = msg_id
        self._msg_seq[seq_key] = self._msg_seq.get(seq_key, 0) + 1
        body: Dict[str, Any] = {
            "content": content, "msg_id": msg_id, "msg_seq": self._msg_seq[seq_key],
            "msg_type": 0 if message_type == "text" else kwargs.get("qq_msg_type", 0),
        }
        # 群聊回复@提问者：官方 at 对象（type=3 按群成员 openid @）。at_user_id/chat_type
        # 由 manager._dispatch_message 回发注入。字段以 QQ 开放平台"发送群聊消息"为准，
        # 若网关拒绝可回退去掉 at（不影响正文）。
        at_uid = kwargs.get("at_user_id") or ""
        if kwargs.get("chat_type") == "group" and at_uid:
            body["at"] = {"name": "", "qq": str(at_uid), "type": 3}
        path = self._reply_path(chat_id, kwargs.get("qq_message_type", message_type))

        async def _post(b):
            resp = await asyncio.to_thread(
                lambda: requests.post(path, json=b, headers=self._auth_headers(), timeout=15))
            if resp.status_code in (200, 202, 204):
                try:
                    return str((resp.json() or {}).get("id") or f"qq_{int(time.time())}"), None
                except Exception:
                    return f"qq_{int(time.time())}", None
            return None, f"{resp.status_code} {getattr(resp, 'text', '')[:200]}"

        try:
            mid, err = await _post(body)
            if mid is None and "at" in body:
                # at 字段被网关拒（真机核验未知格式）→ 去 at 重发，保证正文送达（自愈回退）
                logger.warning("qq 带 at 发送被拒(%s)，去掉 at 回退重发", err)
                body.pop("at", None)
                mid, err = await _post(body)
            if mid is None:
                logger.error("qq 发送失败: %s", err)
                return None
            logger.info("qq message sent: %s", mid)
            return mid
        except Exception as e:
            logger.exception("qq 发送异常: %s", e)
            return None

    async def disconnect(self):
        self._connected = False
        self._stop_event.set()
        ws, loop = self._ws, self._ws_loop
        if ws is not None and loop is not None and loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop).result(timeout=5)
            except Exception:
                pass
        thread = self._ws_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._ws_thread = None
        logger.info("qq(ws) 已断开")

    async def health_check(self) -> Dict[str, Any]:
        base = await super().health_check()
        base.update({
            "mode": "ws_gateway",
            "app_id": (self.app_id[:6] + "***") if self.app_id else "",
            "session_id": self._session_id or "",
            "ws_thread_alive": bool(self._ws_thread and self._ws_thread.is_alive()),
        })
        return base
