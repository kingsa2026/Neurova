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
- **来源两态（批 C7b，甲案 §4）**：描述符 `chatSource`＝`capture`（缺省，既有行为）或
  `archive`（会话存档投影面 `channel_archive_messages`，通道层拉取落库、本适配器只读
  `mode=ro` 短连接）。存档面行集与捕获面**同一六列＋media_ref**；media_ref 值形态是
  **sdkfileid**（存档侧引用，与捕获面 media_id 不同源，取字节路径属媒体触发面批次）；
  历史拉取的凭据/拉取逻辑全在通道层单点（channels/wecom_archive.py），本适配器仍零凭据；
- 游标 token 风格沿用 connectors_file（key=value 以冒号连接）；`since=` 承载的值按面
  语义切换——捕获面＝自增 id、存档面＝存档 seq（都是单调、无时钟回拨面）；
  两面都是 append-only 表，无 connectors_file 的指纹重置面；
- 聊天原文不整段进 facts（那是映射层/narrative 的事，C7c 承 §14-C 分档）——本适配器只负责行集。
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

#: 来源两态闭集（批 C7b，方案 §4/§11）：capture=既有入站捕获面；archive=会话存档投影面。
#: wechat 无存档面（§1 表），chatSource=archive＋vendor=wechat 构造期即拒。
SOURCE_FACES: Tuple[str, ...] = ("capture", "archive")
ARCHIVE_FACE = "archive"
CAPTURE_FACE = "capture"

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
        # 来源两态（批 C7b）：capture（缺省，存量描述符行为不变）/ archive。
        self._sourceFace = str(self._descriptor.get("chatSource") or CAPTURE_FACE)
        if self._sourceFace not in SOURCE_FACES:
            raise MappingError("chat.chatSource %r 不在闭集（%s）"
                               % (self._sourceFace or "<空>", " / ".join(SOURCE_FACES)))
        if self._sourceFace == ARCHIVE_FACE and self._vendor == "wechat":
            raise MappingError("微信侧无会话存档面（chatSource=archive 仅 wecom 可用）")
        self._ingressDb = (None if self._sourceFace == ARCHIVE_FACE
                           else self._resolveIngressDb())
        self._archiveDb = (self._resolveArchiveDb()
                           if self._sourceFace == ARCHIVE_FACE else None)

    # ── Protocol 四动词 ──────────────────────────────────────

    async def describeSchema(self) -> SourceSchema:
        if self._sourceFace == ARCHIVE_FACE:
            return SourceSchema(
                sourceId=self._sourceId, sourceType="chat",
                tables=[{
                    "name": "channel_archive_messages（会话存档投影面，vendor=%s；"
                            "甲案：通道层拉取落库、本源只读）" % self._vendor,
                    "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN],
                    "chat_type": "p2p=私聊（chat_id＝双方排序对，同会话双向同键）/ "
                                 "group=群聊（chat_id＝roomid，subject 语义＝群 id）",
                    "media_ref": "附件透传列（可空）：值形态＝**sdkfileid**（会话存档侧"
                                 "引用，与捕获面 media_id **不是同一种引用**——取字节路径"
                                 "＝存档 GetMediaData 分片续传，属媒体触发面批次，本批"
                                 "只落引用不主动触发；引用有效期与存档窗口同族，"
                                 "「有引用」不等于「附件可检索」）",
                }],
            )
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
        if self._sourceFace == ARCHIVE_FACE:
            rows, lastId, hasMore = self._readArchiveRows(since, max(1, int(limit)))
        else:
            rows, lastId, hasMore = self._readRows(since, max(1, int(limit)))
        nextCursor = None
        if rows or hasMore:
            nextCursor = SourceCursor(self._cursorToken(lastId))
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore, fetchedAt="")

    async def health(self) -> SourceHealth:
        if self._sourceFace == ARCHIVE_FACE:
            return self._archiveHealth()
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
        # 捕获面可达即如实 degraded（历史拉取缺口具名）＋附件能力点名，不冒充全量；
        # 存档凭据面自身配置错（库文件不在/私钥不合口径）则如实 error，不掩盖成 degraded
        reading = self._archiveReading()
        if reading.status == "error":
            return SourceHealth(status="error", reason=reading.reason)
        reason = "%s，仅既有捕获面可达；附件能力：media_ref 列透传图片/文档引用，" \
                 "复用既有媒体管线（mediaIngress/ingest_bridge），本批不主动触发" % reading.reason
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

        from neurova.channels.channel_ingress_queue import CHANNEL_INGRESS_DB_ENV

        return callerPath(os.environ.get(CHANNEL_INGRESS_DB_ENV),
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

    # ── 存档投影面（批 C7b，甲案：通道层写、本源只读 ro 短连接）──

    def _resolveArchiveDb(self) -> Path:
        """存档投影库落点：描述符显式 archiveDb 优先；缺省与通道层写入口同一
        注入口径（`NEUROVA_CHANNEL_ARCHIVE_DB`，未注入落数据根 channel_archive.db，
        env 名单点在 channels/wecom_archive.py，与捕获面同款纪律）。"""
        explicit = str(self._descriptor.get("archiveDb") or "").strip()
        if explicit:
            return Path(explicit)
        from neurova.core.data_root import callerPath

        from neurova.channels.wecom_archive import CHANNEL_ARCHIVE_DB_ENV

        return callerPath(os.environ.get(CHANNEL_ARCHIVE_DB_ENV),
                          "channel_archive.db")

    def _readArchiveRows(self, since: int, limit: int) -> Tuple[List[Dict[str, Any]], int, bool]:
        """只读拉一批存档投影行：按 seq 扫描、send 过滤在 Python 侧（recall/switch
        留档不入账但**游标推进过它们**——否则水位卡死、扫描窗无限增长，§5 同规）。

        投影库尚未落盘（worker 未拉过）→ 空批诚实返回，不炸、不冒充有数；
        mode=ro 短连接，不写通道库、不留常驻连接。"""
        from neurova.channels.wecom_archive import SEND_ROWS_SQL

        if not self._archiveDb.exists():
            return [], int(since), False
        conn = sqlite3.connect(self._roUriFor(self._archiveDb), uri=True,
                               timeout=_RO_TIMEOUT_SECONDS)
        try:
            fetched = conn.execute(SEND_ROWS_SQL,
                                   (int(since), int(limit) + 1)).fetchall()
        finally:
            conn.close()
        hasMore = len(fetched) > limit
        scanned = fetched[:limit]
        lastSeq = max((int(r[0]) for r in scanned), default=int(since))
        rows = [self._rowFromArchive(dbRow) for dbRow in scanned if dbRow[2] == "send"]
        return rows, lastSeq, hasMore

    def _rowFromArchive(self, dbRow: tuple) -> Dict[str, Any]:
        """投影行 → 六列行集（与捕获面同体形状；chat_id 按面语义：群＝roomid、
        p2p＝双方排序对——同会话双向同键，不随消息方向漂）。"""
        from neurova.channels.wecom_archive import msgtimeMillisToIso

        (_seq, msgid, _action, _msgtype, fromId, tolistJson, roomid,
         msgtimeMs, text, mediaRef) = dbRow
        try:
            tolist = json.loads(tolistJson) if tolistJson else []
        except (TypeError, ValueError):
            tolist = []
        participants = sorted({str(p) for p in ([fromId] + list(tolist or [])) if p})
        chatId = roomid or ("p2p:%s" % ":".join(participants) if participants else msgid)
        return {
            "msg_id": str(msgid),
            "chat_id": chatId,
            "chat_type": "group" if roomid else "p2p",
            "sender": str(fromId),
            "sent_at": msgtimeMillisToIso(int(msgtimeMs)),
            "text": str(text),
            MEDIA_REF_COLUMN: str(mediaRef),
        }

    def _roUriFor(self, dbPath: Path) -> str:
        return "file:%s?mode=ro" % dbPath.as_posix()

    def _archiveHealth(self) -> SourceHealth:
        """存档源健康读数：凭据面 error 照搬；投影面可达性另探，不冒充 ok。

        C7b 阶段常驻拉取未启动（C7c），投影面要么空要么无自动落库——degraded
        是诚实形态；凭据齐备也不报 ok（覆盖范围由席位与成员同意决定，§3）。"""
        reading = self._archiveReading()
        if reading.status == "error":
            return SourceHealth(status="error", reason=reading.reason)
        if not self._archiveDb.exists():
            return SourceHealth(
                status="degraded",
                reason="%s；会话存档投影面尚未落库: %s（常驻增量拉取属批 C7c 未启动）"
                       % (reading.reason, self._archiveDb))
        from neurova.channels.wecom_archive import SEND_ROWS_SQL

        try:
            conn = sqlite3.connect(self._roUriFor(self._archiveDb), uri=True,
                                   timeout=_RO_TIMEOUT_SECONDS)
            try:
                conn.execute("SELECT 1 FROM (" + SEND_ROWS_SQL + ") LIMIT 1",
                             (0, 1)).fetchone()
                row = conn.execute(
                    "SELECT COUNT(*) FROM channel_archive_messages"
                    " WHERE action = 'send'").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return SourceHealth(status="error",
                                reason="会话存档投影面不可读: %s" % exc)
        return SourceHealth(
            status="degraded",
            reason="%s；存档投影面可达（send 行已落 %d），常驻增量拉取属批 C7c 未启动"
                   % (reading.reason, row[0]))

    # ── 游标（token 风格沿用 connectors_file）────────────────

    def _cursorToken(self, lastId: int) -> str:
        return "src=%s:since=%d" % (self._vendor, int(lastId))

    def _parseSince(self, token: str) -> int:
        try:
            return int(token.rsplit("since=", 1)[1])
        except (IndexError, ValueError):
            return 0  # 游标不可解析＝从 0 重读（幂等由咽喉内容键兜底）

    # ── 历史拉取缺口（如实点名，不冒充全量）─────────────────

    def _archiveReading(self) -> Any:
        """历史缺口读数＝通道层存档凭据面的同一份判断（批 C7a，方案 §6.1/§16-1）。

        本适配器仍零凭据：只向通道层要一个 status＋reason，自己不探测原生库、
        不碰私钥路径与 Secret。旧实现那份 `importlib` 模块名探测已退役——官方只分发
        C 动态库、无官方 Python 包，那个探测名不对应任何可安装件（恒 ImportError＝假判据）。
        """
        from neurova.channels.wecom_archive import ArchiveReadiness, wecomArchiveReadiness

        if self._vendor == "wechat":
            return ArchiveReadiness(
                status="degraded",
                reason="微信侧无官方历史消息拉取通道（会话存档仅企微提供）")
        return wecomArchiveReadiness(
            agentId=str(self._descriptor.get("agentId") or "default"))
