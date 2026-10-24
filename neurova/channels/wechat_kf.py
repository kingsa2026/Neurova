"""微信客服原生事件：kf_msg_or_event 回调解密 → sync_msg → 接管/文本事件。"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from neurova.channels.base import ChannelEventType, ChannelMessage
from neurova.channels.voice_ingress import AUDIO_BYTES_KEY
from neurova.channels.wechat_kf_crypto import decryptKfPayload, verifyKfSignature
from neurova.core.logger import get_logger

logger = get_logger(__name__)


class WeChatKfEventsMixin:
    """依赖 WeChatAdapter 的 kf_mode/token/crypto 字段；消息构造走基类 `_make_message`。"""

    def verifyKfSignature(
        self, msg_signature: str, timestamp: str, nonce: str, encrypt: str
    ) -> None:
        verifyKfSignature(
            self.callback_token, timestamp, nonce, encrypt, msg_signature
        )

    def verify_kf_url(
        self, msg_signature: str, timestamp: str, nonce: str, echostr: str
    ) -> str:
        """URL 验证：验签后解密 echostr 返回明文（不是把密文回给平台）。"""
        self.verifyKfSignature(msg_signature, timestamp, nonce, echostr)
        return decryptKfPayload(self.encoding_aes_key, echostr, self.corpid)

    def handle_kf_callback(
        self, msg_signature: str, timestamp: str, nonce: str, xml_data: str
    ) -> List[Tuple[ChannelEventType, ChannelMessage]]:
        """kf_msg_or_event 回调 → sync_msg → 接管/文本事件列表。"""
        if not self.kf_mode:
            raise ValueError("WeChat webhook only supports kf_mode")
        if len(xml_data) > 1024 * 1024:
            raise ValueError("WeChat kf callback rejected: body too large")
        if "<!doctype" in xml_data[:1024].lower() or "<!entity" in xml_data[:1024].lower():
            raise ValueError("WeChat kf callback rejected: DOCTYPE/ENTITY not allowed")
        root = ET.fromstring(xml_data)
        encrypt = root.findtext("Encrypt", "") or ""
        self.verifyKfSignature(msg_signature, timestamp, nonce, encrypt)
        plainXml = decryptKfPayload(self.encoding_aes_key, encrypt, self.corpid)
        plainRoot = ET.fromstring(plainXml)
        if (plainRoot.findtext("Event", "") or "") != "kf_msg_or_event":
            return []
        syncToken = plainRoot.findtext("Token", "") or ""
        openKfId = plainRoot.findtext("OpenKfId", "") or self.open_kfid
        payload = self.sync_kf_messages(syncToken, openKfId)
        return self._kfPayloadToEvents(payload, openKfId)

    def sync_kf_messages(self, syncToken: str, openKfId: str) -> Dict[str, Any]:
        """拉取客服消息/事件；网络或凭据失败返回空字典并点名（不抛给回调链）。"""
        try:
            import requests
        except ImportError:
            logger.warning("微信客服 sync_msg 跳过：requests 未安装")
            return {}
        if not self._ensure_wecom_token():
            logger.warning("微信客服 sync_msg 跳过：access_token 不可用")
            return {}
        body = {
            "cursor": self._kf_cursors.get(openKfId, ""),
            "token": syncToken,
            "limit": 1000,
            "open_kfid": openKfId,
        }
        try:
            response = requests.post(
                f"{self.WECOM_API_BASE}/cgi-bin/kf/sync_msg",
                params={"access_token": self.access_token},
                json=body,
                timeout=5,
            )
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - 拉取失败不阻断回调应答
            logger.warning("微信客服 sync_msg 失败: %s", exc)
            return {}
        if data.get("errcode") not in (0, None):
            logger.warning("微信客服 sync_msg 返回错误: %s", data)
            return {}
        nextCursor = str(data.get("next_cursor") or "")
        if nextCursor:
            self._kf_cursors[openKfId] = nextCursor
        return data

    def download_kf_media(self, media_id: str) -> Optional[bytes]:
        """微信客服素材下载；失败返回 None（由入站桥报 media_unavailable）。

        取字节走 `wecom.fetchWecomMediaBytes` 那份单源（与语音通路同一个函数）：
        这里只保留自己的 token 前置检查，请求形状不再手抄第二份——手抄那一份既没有
        大小上限，也会在平台协议变更时与单源分叉。
        """
        if not media_id or not self._ensure_wecom_token():
            return None
        from neurova.channels.wecom import fetchWecomMediaBytes

        return fetchWecomMediaBytes(self.access_token, media_id)

    def _kfPayloadToEvents(
        self, payload: Dict[str, Any], openKfId: str
    ) -> List[Tuple[ChannelEventType, ChannelMessage]]:
        """sync_msg 的 msg_list → (事件类型, 统一消息)；接管只认 change_type。"""
        events: List[Tuple[ChannelEventType, ChannelMessage]] = []
        agentId = str(
            (self.config.extra or {}).get("agent_id")
            or getattr(self, "agent_id", "")
            or ""
        )
        for item in (payload or {}).get("msg_list") or []:
            if not isinstance(item, dict):
                continue
            msgId = str(item.get("msgid") or item.get("msg_id") or "")
            external = str(item.get("external_userid") or "")
            if str(item.get("msgtype") or "") == "event":
                event = item.get("event") or {}
                eventName = str(
                    event.get("event_type") or event.get("eventtype") or ""
                ).strip().lower().replace("_", "")
                if eventName != "sessionstatuschange":
                    continue
                try:
                    changeType = int(event.get("change_type") or event.get("changetype") or 0)
                except (TypeError, ValueError):
                    changeType = 0
                oldServicer = str(
                    event.get("old_servicer_userid") or event.get("oldserviceruserid") or ""
                )
                newServicer = str(
                    event.get("new_servicer_userid") or event.get("newserviceruserid") or ""
                )
                chatId = external or oldServicer or newServicer
                if not chatId:
                    continue
                if changeType in (1, 4):
                    events.append(self._kfTakeoverMessage(
                        ChannelEventType.HUMAN_TAKEOVER_STARTED, msgId,
                        changeType, "start", chatId, newServicer, openKfId, agentId,
                    ))
                elif changeType == 2:
                    if oldServicer:
                        events.append(self._kfTakeoverMessage(
                            ChannelEventType.HUMAN_TAKEOVER_ENDED, msgId,
                            changeType, "end", chatId, oldServicer, openKfId, agentId,
                        ))
                    if newServicer:
                        events.append(self._kfTakeoverMessage(
                            ChannelEventType.HUMAN_TAKEOVER_STARTED, msgId,
                            changeType, "start", chatId, newServicer, openKfId, agentId,
                        ))
                elif changeType == 3 and oldServicer:
                    events.append(self._kfTakeoverMessage(
                        ChannelEventType.HUMAN_TAKEOVER_ENDED, msgId,
                        changeType, "end", chatId, oldServicer, openKfId, agentId,
                    ))
                continue
            msgType = str(item.get("msgtype") or "")
            if msgType == "text" and external:
                content = str((item.get("text") or {}).get("content") or "")
                if content:
                    events.append((ChannelEventType.MESSAGE_RECEIVED, self._make_message(
                        message_id=msgId or f"kf_{int(time.time())}",
                        sender_id=external, sender_name=external,
                        content=content, chat_id=external, chat_type="p2p",
                        message_type="text",
                        raw_event=item,
                        metadata={"open_kfid": openKfId, "agent_id": agentId},
                    )))
            elif msgType in ("image", "file", "voice") and external:
                payload = item.get(msgType) or {}
                mediaId = str(payload.get("media_id") or "")
                filename = str(payload.get("filename") or "")
                data = self.download_kf_media(mediaId) if mediaId else None
                metadata = {
                    "open_kfid": openKfId,
                    "agent_id": agentId,
                    "media_id": mediaId,
                    "file_name": filename,
                }
                if data:
                    metadata["media_bytes"] = data
                    if msgType == "voice":
                        metadata[AUDIO_BYTES_KEY] = data
                events.append((ChannelEventType.MESSAGE_RECEIVED, self._make_message(
                    message_id=msgId or f"kf_{int(time.time())}",
                    sender_id=external, sender_name=external,
                    content=filename or ("[%s]" % msgType),
                    chat_id=external, chat_type="p2p",
                    message_type=msgType, raw_event=item, metadata=metadata,
                )))
        return events

    def _kfTakeoverMessage(
        self, eventType: ChannelEventType, msgId: str, changeType: int,
        suffix: str, chatId: str, servicer: str, openKfId: str, agentId: str,
    ) -> Tuple[ChannelEventType, ChannelMessage]:
        message = self._make_message(
            message_id="%s:%s:%s" % (msgId or "kf", changeType, suffix),
            sender_id=servicer, sender_name=servicer, content="",
            chat_id=chatId, chat_type="p2p", message_type="event",
            raw_event={"msgid": msgId, "change_type": changeType},
            metadata={
                "open_kfid": openKfId,
                "takeover_reason": "kf_session_status_change_%d" % changeType,
                "agent_id": agentId,
            },
        )
        return eventType, message
