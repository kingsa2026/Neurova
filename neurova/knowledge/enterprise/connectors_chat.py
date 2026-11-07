# -*- coding: utf-8 -*-
"""聊天信息源连接器（立项方案批 C6，2026-11-07 裁定 §2.4-3：企微＋微信/小微）。

桥接既有通道层，不另起凭据面/长连接面：
- 数据源＝既有入站捕获持久面 `channel_ingress.db` 的 `channel_ingress_events` 表
  （`channels/channel_ingress_queue.py` 落库，`channels/manager.py` 入队）——本适配器
  只读拉取（SQLite `mode=ro` 独立短连接，旁库只读纪律同批 C2），不写通道库、
  不接任何平台凭据、不建长连接；
- 行形状与 `applyMapping` 同构：六列 msg_id/chat_id/chat_type/sender/sent_at/text
  ＋附件透传列 media_ref（可空，值为既有媒体管线 `mediaIngress.mediaCandidates`
  单点上可定位的引用）。群聊 subject 语义＝群 id，模板（order:{msg_id} 类）由映射层拼；
- 附件（图片/文档）：本批只把 media_ref 如实放进行里，并在 describeSchema/health
  点名附件能力；**不主动调用** ingest_bridge 媒体下载/解析/OCR 管线——触发面归属
  C6 报告裁定项（ingest_bridge 是既有「消息→条目」桥，复用它不算第二写路径）；
- 历史消息拉取：企微官方通道是「会话存档」原生 SDK（腾讯 C 库，第三方二进制）——
  本批未接入，health() 显式 degraded 点名「会话存档 SDK 未接入，仅既有捕获面可达」，
  不静默冒充全量；微信侧无官方历史通道，同以 degraded 如实点名；
- 游标按捕获面自增 id 推进（单调、无时钟回拨面），token 风格沿用 connectors_file
  （key=value 以冒号连接）；捕获面是 append-only 表，无 connectors_file 的指纹重置面；
- 聊天原文不整段进 facts（那是映射层/narrative 的事）——本适配器只负责行集。
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .protocols import ChangeBatch, SourceCursor, SourceHealth, SourceSchema
from .schema_mapping import VARIANT_CLOSED_SETS, MappingError

#: 行集六列：与描述符 columns 对齐（映射模板/qualifier/源钟列就声明这六个）
ROW_COLUMNS: Tuple[str, ...] = ("msg_id", "chat_id", "chat_type", "sender", "sent_at", "text")
#: 附件透传列：可空；描述符可把它声明进 columns 供 qualifier/源钟之外的消费用
MEDIA_REF_COLUMN = "media_ref"

#: 会话存档适配槽探测名：腾讯官方 C 库的 Python 包装（第三方二进制，
#: 未入依赖清单——惰性 import 探测，未装即 degraded，不崩进程）
_WECOM_ARCHIVE_SDK_MODULE = "WeWorkFinanceSdk"

#: 只读连接超时（秒）：捕获面 WAL 库，读不应久等
_RO_TIMEOUT_SECONDS = 5.0


class ChatChannelAdapter:
    """`sourceType=chat` 的 Protocol 实现（fetchBatch 是 async 契约，读库本身同步短连接）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._descriptor = dict(descriptor)
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._vendor = str(self._descriptor.get("vendor") or "")
        # 闭集收口：编译期 validateDescriptor 判过一次，工厂 _requireVariant 只查非空，
        # 构造处按同一单点（VARIANT_CLOSED_SETS）再拦——闭集外描述符到不了运行时。
        _variantField, closed = VARIANT_CLOSED_SETS["chat"]
        if self._vendor not in closed:
            raise MappingError("chat.vendor %r 不在闭集（%s）"
                               % (self._vendor or "<空>", " / ".join(closed)))
        # wecom/wechat 与通道层 MessageChannel 枚举值同名，直接作 channel_type 过滤
        self._channelType = self._vendor
        self._ingressDb = self._resolveIngressDb()

    # ── Protocol 四动词 ──────────────────────────────────────

    async def describeSchema(self) -> SourceSchema:
        return SourceSchema(
            sourceId=self._sourceId, sourceType="chat",
            tables=[{
                "name": "channel_ingress_events（既有通道捕获面，vendor=%s）" % self._vendor,
                "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN],
                "chat_type": "p2p=私聊 / group=群聊（群聊 subject 语义＝群 id，"
                             "模板由映射层拼）",
                "media_ref": "附件透传列（可空）：图片/文档在既有媒体管线"
                             "（mediaIngress 暂存/路径键）上的引用；解析消费走"
                             " ingest_bridge 既有管线，本批不主动触发",
            }],
        )

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        since = 0
        if cursor is not None and not cursor.isEmpty():
            since = self._parseSince(str(cursor.token))
        rows, lastId, hasMore = self._readRows(since, max(1, int(limit)))
        nextCursor = None
        if rows or hasMore:
            nextCursor = SourceCursor(self._cursorToken(lastId))
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore, fetchedAt="")

    async def health(self) -> SourceHealth:
        if not self._ingressDb.exists():
            return SourceHealth(status="error",
                                reason="既有通道捕获面 DB 不存在: %s" % self._ingressDb)
        try:
            conn = sqlite3.connect(self._roUri(), uri=True,
                                   timeout=_RO_TIMEOUT_SECONDS)
            try:
                conn.execute("SELECT 1 FROM channel_ingress_events LIMIT 1").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return SourceHealth(status="error",
                                reason="既有通道捕获面不可读: %s" % exc)
        # 捕获面可达即如实 degraded（历史拉取缺口具名）＋附件能力点名，不冒充全量
        reason = "%s；附件能力：media_ref 列透传图片/文档引用，复用既有媒体管线" \
                 "（mediaIngress/ingest_bridge），本批不主动触发" % self._historyGapReason()
        return SourceHealth(status="degraded", reason=reason)

    async def close(self) -> None:
        return None

    # ── 数据源落点（只读） ────────────────────────────────────

    def _resolveIngressDb(self) -> Path:
        """捕获面落点：描述符显式 ingressDb 优先；缺省与通道层入队同一注入口径
        （`NEUROVA_CHANNEL_INGRESS_DB` 注入，未注入落数据根 channel_ingress.db，
        见 channels/manager.py:619）。env 名的单点收口在通道层（本批不动共享文件），
        此处只消费同一注入面；理想收口是把 env 名提为 channel_ingress_queue 常量。
        """
        explicit = str(self._descriptor.get("ingressDb") or "").strip()
        if explicit:
            return Path(explicit)
        from neurova.core.data_root import callerPath

        return callerPath(os.environ.get("NEUROVA_CHANNEL_INGRESS_DB"),
                          "channel_ingress.db")

    def _roUri(self) -> str:
        return "file:%s?mode=ro" % self._ingressDb.as_posix()

    def _readRows(self, since: int, limit: int) -> Tuple[List[Dict[str, Any]], int, bool]:
        """只读拉一批已捕获消息：按 id 升序取 limit+1 行探测 hasMore。

        - 只按 channel_type 过滤本 vendor（wecom/wechat），不按排水 status 过滤——
          pending/processing/done/dead 都是「已捕获」的真实消息（tombstone 去重保证
          无重复行）；
        - 坏 payload 行跳过但游标推进过它（不卡水位、不重复消费）；
        - 独立 mode=ro 短连接：不写通道库、不留常驻连接。
        """
        conn = sqlite3.connect(self._roUri(), uri=True, timeout=_RO_TIMEOUT_SECONDS)
        try:
            fetched = conn.execute(
                "SELECT id, payload FROM channel_ingress_events"
                " WHERE channel_type = ? AND id > ? ORDER BY id LIMIT ?",
                (self._channelType, since, limit + 1),
            ).fetchall()
        finally:
            conn.close()
        hasMore = len(fetched) > limit
        kept = fetched[:limit]
        rows: List[Dict[str, Any]] = []
        lastId = since
        for rowId, payloadJson in kept:
            lastId = int(rowId)
            row = self._rowFromPayload(rowId, payloadJson)
            if row is not None:
                rows.append(row)
        return rows, lastId, hasMore

    def _rowFromPayload(self, eventId: int, payloadJson: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(payloadJson)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        metadata = data.get("metadata")
        return {
            "msg_id": str(data.get("message_id") or "ingress:%s" % eventId),
            "chat_id": str(data.get("chat_id") or ""),
            "chat_type": str(data.get("chat_type") or "p2p"),
            "sender": str(data.get("sender_id") or ""),
            "sent_at": str(data.get("timestamp") or ""),
            "text": str(data.get("content") or ""),
            MEDIA_REF_COLUMN: self._mediaRef(metadata),
        }

    def _mediaRef(self, metadata: Any) -> str:
        """附件引用透传：值＝既有媒体管线上可定位的引用。

        键的单点是 channels/mediaIngress.mediaCandidates（image_path/video_path/
        file_path/staged_media_path，字节键过队即变形故不在此列）——复用它，
        键集变化时本适配器自动跟随，不另造第二份键名表。
        """
        from neurova.channels.mediaIngress import mediaCandidates

        candidates = mediaCandidates(metadata)
        return str(candidates[0][0]) if candidates else ""

    # ── 游标（token 风格沿用 connectors_file）────────────────

    def _cursorToken(self, lastId: int) -> str:
        return "src=%s:since=%d" % (self._vendor, int(lastId))

    def _parseSince(self, token: str) -> int:
        try:
            return int(token.rsplit("since=", 1)[1])
        except (IndexError, ValueError):
            return 0  # 游标不可解析＝从 0 重读（幂等由咽喉内容键兜底）

    # ── 历史拉取缺口（如实点名，不冒充全量）─────────────────

    def _historyGapReason(self) -> str:
        if self._vendor == "wechat":
            return "微信侧无官方历史消息拉取通道（会话存档仅企微提供），仅既有捕获面可达"
        sdkInstalled = False
        try:
            import importlib

            importlib.import_module(_WECOM_ARCHIVE_SDK_MODULE)
            sdkInstalled = True
        except ImportError:
            sdkInstalled = False
        if not sdkInstalled:
            return "会话存档 SDK 未接入，仅既有捕获面可达"
        chatArchive = self._descriptor.get("chatArchive")
        if not isinstance(chatArchive, dict) or not chatArchive:
            return "会话存档 SDK 已装但凭据未配置（描述符 chatArchive 段），" \
                   "仅既有捕获面可达"
        return "会话存档读取面未实现，仅既有捕获面可达"
