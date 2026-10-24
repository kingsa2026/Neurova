"""渠道消息 → 知识库入站桥。

只消费显式开启 `ingest_to_kb` 的消息；聊天主链不受影响，入站失败也不改聊天回复。
文本/链接/图片/文件/语音先统一成文档事件，再走标准化流水线与现有入库咽喉。

可靠性：先落 SQLite 入站队列（`dedupe_key` 幂等、attempts/退避/dead），再处理；
进程重启后待办仍在，下一次入站会顺带补处理积压，`POST /knowledge/audit/ingest/resume`
可显式补跑。队列读数与进程内结果计数分开报，不把两者混成一份。
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import json
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.lazy_singleton import lazySingleton
from neurova.knowledge.document_pipeline import DocumentParseError, parse_document
from neurova.knowledge.ingest_bus import (
    KB_INGEST_RESULT_TOPIC,
    KB_INGEST_WECOM_TOPIC,
    get_ingest_bus,
)
from neurova.knowledge.ingest_jobs import (
    KnowledgeIngestQueue,
    get_knowledge_ingest_queue,
)
from neurova.knowledge.repository import get_knowledge_repository

logger = get_logger(__name__)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+")
# 单条媒体入站上限：超限诚实跳过，不把巨型附件读进内存/送进解析器。
_MAX_MEDIA_BYTES = 32 * 1024 * 1024


def _encodeValue(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes_b64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(k): _encodeValue(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encodeValue(v) for v in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return {"__iso__": value.isoformat()}
    return value


def _decodeValue(value: Any) -> Any:
    if isinstance(value, dict):
        if "__bytes_b64__" in value:
            return base64.b64decode(value["__bytes_b64__"])
        if "__iso__" in value:
            try:
                return datetime.datetime.fromisoformat(value["__iso__"])
            except (ValueError, TypeError):
                return value["__iso__"]
        return {k: _decodeValue(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decodeValue(v) for v in value]
    return value


class KnowledgeIngestBridge:
    def __init__(
        self, queue: Optional[KnowledgeIngestQueue] = None,
        transport: Any = None,
    ) -> None:
        self._queue = queue or get_knowledge_ingest_queue()
        if transport is None:
            from neurova.knowledge.ingest_mqtt import buildIngestTransport

            transport = buildIngestTransport()
        self._transport = transport
        # 进程内计数：只报本进程真实处理过的结果；积压/attempts 看队列读数
        self._stats: Dict[str, int] = {
            "accepted": 0, "duplicate": 0, "failed": 0, "skipped": 0,
            "published": 0,
        }

    def stats(self) -> Dict[str, Any]:
        bus = get_ingest_bus()
        return {
            **self._stats,
            "queue": self._queue.stats(),
            "topics": {
                KB_INGEST_WECOM_TOPIC: bus.subscriberCount(KB_INGEST_WECOM_TOPIC),
                KB_INGEST_RESULT_TOPIC: bus.subscriberCount(KB_INGEST_RESULT_TOPIC),
            },
        }

    def _count(self, status: str) -> None:
        if status in self._stats:
            self._stats[status] += 1

    async def ingestChannelMessage(self, message: Any, agent_id: str = "") -> Dict[str, Any]:
        metadata = getattr(message, "metadata", None) or {}
        if not metadata.get("ingest_to_kb"):
            self._count("skipped")
            return {"status": "skipped", "reason": "ingest_to_kb_disabled"}
        message_id = str(getattr(message, "message_id", "") or "")
        chat_id = str(getattr(message, "chat_id", "") or "")
        source = "wecom:%s:%s" % (chat_id, message_id or "no-id")
        agent = agent_id or str(metadata.get("agent_id") or "default")
        tenant = str(metadata.get("tenant_id") or "default")
        event = {
            "event_id": source,
            "channel": str(getattr(message, "channel_type", "") or ""),
            "chat_id": chat_id,
            "sender_id": str(getattr(message, "sender_id", "") or ""),
            "message_type": str(getattr(message, "message_type", "") or ""),
            "text": str(getattr(message, "content", "") or ""),
            "tenant_id": tenant,
            "occurred_at": getattr(message, "timestamp", None).isoformat()
            if hasattr(getattr(message, "timestamp", None), "isoformat") else "",
        }
        payload = {
            "agent_id": agent,
            "tenant_id": tenant,
            "event": _encodeValue(event),
            "message": _encodeValue({
                "message_id": message_id,
                "chat_id": chat_id,
                "sender_id": str(getattr(message, "sender_id", "") or ""),
                "channel_type": str(getattr(message, "channel_type", "") or ""),
                "message_type": str(getattr(message, "message_type", "") or ""),
                "content": str(getattr(message, "content", "") or ""),
                "timestamp": getattr(message, "timestamp", None),
            }),
            "metadata": _encodeValue(dict(metadata)),
        }

        if self._transport is not None:
            # MQTT 生产者模式：本进程不消费，交给订阅端 worker。
            get_ingest_bus().publish(KB_INGEST_WECOM_TOPIC, event)
            self._transport.publishJob(source, payload)
            self._count("published")
            return {"status": "published", "event_id": source}

        # 入站前顺带补处理少量历史积压：重启后不靠人记得点恢复端点。
        await self.drainPending(limit=2)

        jobId, _created = self._queue.enqueue(source, payload)
        job = self._queue.job(jobId) or {}
        if str(job.get("status")) == "done":
            result = self._resultOf(job)
            duplicate = dict(result)
            duplicate["status"] = "duplicate"
            self._count("duplicate")
            get_ingest_bus().publish(KB_INGEST_RESULT_TOPIC, {
                "event_id": source, "tenant_id": tenant, **duplicate,
            })
            return duplicate
        if str(job.get("status")) == "dead":
            self._count("failed")
            return {"status": "failed", "reason": "dead_letter"}
        claimed = self._queue.claim(jobId=jobId)
        if claimed is None:
            return {"status": "queued", "job_id": jobId}
        return await self._processJob(claimed)

    async def drainPending(self, limit: int = 20) -> List[Dict[str, Any]]:
        """补处理 pending 作业（lease 超时的 running 由 claim 回收）。"""
        results: List[Dict[str, Any]] = []
        for _ in range(max(0, int(limit))):
            job = self._queue.claim()
            if job is None:
                break
            results.append(await self._processJob(job))
        return results

    async def _processJob(self, job: Dict[str, Any]) -> Dict[str, Any]:
        jobId = str(job.get("job_id") or "")
        payload = json.loads(job.get("payload_json") or "{}")
        event = _decodeValue(payload.get("event") or {})
        encodedMessage = _decodeValue(payload.get("message") or {})
        metadata = _decodeValue(payload.get("metadata") or {})
        message = SimpleNamespace(**encodedMessage)
        message.metadata = metadata
        agent = str(payload.get("agent_id") or "default")
        tenant = str(payload.get("tenant_id") or "default")
        source = str(event.get("event_id") or "")
        get_ingest_bus().publish(KB_INGEST_WECOM_TOPIC, event)
        try:
            result = await self._ingestPayload(
                message, metadata, agent, tenant, source, event
            )
            self._queue.ack(jobId, result)
        except Exception as exc:  # noqa: BLE001 - 未预期故障走可重试队列
            logger.warning("知识入站作业失败 %s: %s", source, exc)
            self._queue.nack(jobId, str(exc), retryable=True)
            result = {"status": "failed", "reason": type(exc).__name__}
        get_ingest_bus().publish(KB_INGEST_RESULT_TOPIC, {**event, **result})
        if self._transport is not None:
            try:
                self._transport.publishResult({**event, **result})
            except Exception as exc:  # noqa: BLE001 - 结果回传失败不阻断本地 ack
                logger.warning("知识入站 MQTT 结果发布失败: %s", exc)
        self._count(str(result.get("status") or ""))
        return result

    async def _ingestPayload(
        self, message: Any, metadata: Dict[str, Any], agent: str,
        tenant: str, source: str, event: Dict[str, Any],
    ) -> Dict[str, Any]:
        repo = get_knowledge_repository()
        existing = repo.findBySource(agent, source, tenant)
        if existing:
            return {"status": "duplicate", "knowledge_id": existing.get("knowledge_id")}

        try:
            documentBytes, filename, sourceType = await self._resolve(message, metadata)
            if documentBytes is None:
                return {"status": "skipped", "reason": filename}
            parsed = await asyncio.to_thread(
                parse_document, documentBytes, filename,
                source_path=source, source_type=sourceType, ocr_mode="auto",
            )
            item = repo.create_knowledge(
                agent_id=agent,
                title=str(parsed.metadata.get("title") or filename),
                content=parsed.content,
                category="wecom",
                tags=[],
                source=source,
                confidence=0.6,
                visibility="private",
                owner_user_id=str(getattr(message, "sender_id", "") or "default"),
                tenant_id=tenant,
                chunks=parsed.chunks,
                parents=parsed.parents,
                detect_conflict=False,
                source_type=sourceType,
                source_path=source,
                ingest_time=parsed.ingest_time,
                page_count=parsed.metadata.get("page_count"),
                ocr_used=bool(parsed.metadata.get("ocr_used")),
                ocr_engine=str(parsed.metadata.get("ocr_engine") or ""),
                ocr_confidence_avg=parsed.metadata.get("ocr_confidence_avg"),
                document_id=parsed.doc_id,
                dedupe=True,
            )
            return {"status": "accepted", "knowledge_id": item.get("knowledge_id")}
        except DocumentParseError as exc:
            return {"status": "failed", "reason": exc.reason}
        except Exception as exc:  # noqa: BLE001 - 入站失败不改聊天主链
            logger.warning("知识入站失败 %s: %s", source, exc)
            raise

    @staticmethod
    def _resultOf(job: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return dict(json.loads(job.get("result_json") or "{}"))
        except (ValueError, TypeError):
            return {"status": "failed", "reason": "corrupt_result"}

    async def _resolve(
        self, message: Any, metadata: Dict[str, Any]
    ) -> tuple:
        messageType = str(getattr(message, "message_type", "") or "").lower()
        content = str(getattr(message, "content", "") or "")
        if messageType in ("voice", "audio"):
            text = await self._transcribe(message)
            if not text:
                return None, "voice_transcribe_failed", "wecom"
            return text.encode("utf-8"), "wecom-voice.txt", "wecom"
        if messageType in ("image", "file", "attachment"):
            data = metadata.get("media_bytes")
            if not data:
                return None, "media_unavailable", "wecom"
            if len(data) > _MAX_MEDIA_BYTES:
                return None, "media_too_large", "wecom"
            filename = str(metadata.get("file_name") or metadata.get("filename") or "wecom-media")
            if messageType == "image" and "." not in filename:
                filename += ".png"
            return bytes(data), filename, "wecom"
        url = _URL_RE.search(content)
        if url:
            return await self._fetchUrl(url.group(0)), "wecom-link.html", "wecom"
        return content.encode("utf-8"), "wecom-message.txt", "wecom"

    async def _fetchUrl(self, url: str) -> bytes:
        from neurova.api.endpoints.knowledge_ingestion import _fetch_url, _validate_import_url

        if not _validate_import_url(url):
            raise DocumentParseError("unsafe_url")
        return await asyncio.to_thread(_fetch_url, url)

    async def _transcribe(self, message: Any) -> str:
        try:
            from neurova.channels.voice_precheck import transcribe_voice_message

            transcribed = await transcribe_voice_message(message)
            if getattr(transcribed, "metadata", {}).get("voice_transcribed"):
                return str(getattr(transcribed, "content", "") or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("知识入站语音转写失败: %s", exc)
        return ""


def enqueueFromMqtt(body: Dict[str, Any]) -> Optional[str]:
    """MQTT 订阅端：把远端作业写进本地持久队列，由常驻 worker 处理。"""
    key = str(body.get("dedupe_key") or "").strip()
    payload = body.get("payload")
    if not key or not isinstance(payload, dict):
        return None
    jobId, _created = get_knowledge_ingest_queue().enqueue(key, payload)
    return jobId


async def runIngestMqttConsumer(stopEvent: Optional[asyncio.Event] = None) -> None:
    from neurova.knowledge.ingest_mqtt import MqttIngestTransport

    transport = MqttIngestTransport()
    try:
        transport.subscribeJobs(enqueueFromMqtt)
    except Exception as exc:  # noqa: BLE001 - 依赖/配置缺失要可见，但不打死进程
        logger.warning("知识入站 MQTT 订阅端未启动: %s", exc)
        transport.close()
        return
    try:
        if stopEvent is None:
            await asyncio.Event().wait()
        else:
            await stopEvent.wait()
    finally:
        transport.close()


async def runIngestWorker(
    intervalSeconds: float = 5.0, stopEvent: Optional[asyncio.Event] = None
) -> None:
    """常驻入站消费者：周期补跑 pending，有活立即继续，空转按间隔休眠。"""
    interval = max(0.2, float(intervalSeconds))
    while True:
        if stopEvent is not None and stopEvent.is_set():
            return
        try:
            processed = await get_ingest_bridge().drainPending(limit=20)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单轮失败下轮再试
            logger.warning("知识入站消费者单轮失败: %s", exc)
            processed = []
        if processed:
            continue
        try:
            if stopEvent is not None:
                await asyncio.wait_for(stopEvent.wait(), timeout=interval)
            else:
                await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            continue


_bridge: Optional[KnowledgeIngestBridge] = None


@lazySingleton("_bridge")
def get_ingest_bridge() -> KnowledgeIngestBridge:
    """进程内唯一的入站桥（构造会建队列连接与 MQTT 传输面，无锁并发下会各建一份）。

    缓存槽就是模块全局 `_bridge`：`lazySingleton` 把判空护在 RLock 里，复位写回同一个名字。
    """
    return KnowledgeIngestBridge()


def ingestEnabled(adapter: Any) -> bool:
    """渠道级开关：config.extra.ingest_to_kb（缺省关）。"""
    extra = getattr(getattr(adapter, "config", None), "extra", None) or {}
    value = extra.get("ingest_to_kb")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "on", "yes")
