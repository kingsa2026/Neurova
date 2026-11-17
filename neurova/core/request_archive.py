# -*- coding: utf-8 -*-
"""模型请求级归档（S17 F1 收尾）：每次真实 provider 请求落一条 JSONL。

形态与纪律（方案 S17）：
- 每 run/会话一份 JSONL：``<数据根>/request_archives/<sessionId>.jsonl``，一行一条
  请求。键取轮上下文的 session id（`turn_context.get_turn_session_id`）——member
  会话与主聊天回合在该通道上与台账行同键，档案聚合按 session→run→project 读时
  join（S12 既有等式）。无会话上下文的调用落 ``unscoped.jsonl``（诚实聚合，不静默丢）。
- 默认不落全文：记录时间戳、model/provider、消息角色与字符数、usage、时延、
  成败/错误族；错误摘要经 S7 的 ``SENSITIVE_KEY_PATTERNS``（`memory_admission`
  单源）脱敏后再截断。``fullText`` 恒 False——全文归档留
  ``NEUROVA_REQUEST_ARCHIVE_FULL`` 门控另议，门开时发一次性 WARNING（旋钮不允许
  静默失效），落盘内容本批不变。
- 写入 fail-soft 不阻断主链路：后台单写线程（懒创建 + 队列），任何失败
  ``logger.warning`` + 计数器（`requestArchiveWriteStats` 读数），不静默吞。
- 独立于 H-4 事件账本：本模块不往 run 账本写请求级事件，账本纪律不变。
- 归档是独立 trace 面：消费面只有档案聚合（`summarizeSessionArchives`，
  projects_api 的 dossier 读时 join），聚合带读数窗口上限（诚实口径：
  窗口外条目不计入并在 ``entryWindowComplete=False`` 显式声明）。

异步写：入队（put_nowait）在调用路径上，格式化与落盘在写线程——不拖慢调用路径。
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ── 具名常量（附录 A2：字面量上界一律红）──────────────────────────
ARCHIVE_DIR_NAME = "request_archives"
#: 全文归档门（本批只做钩子：门开有 WARNING，落盘仍只落脱敏摘要）
FULL_TEXT_ENV = "NEUROVA_REQUEST_ARCHIVE_FULL"
#: 会话键清洗后长度上限
ARCHIVE_KEY_MAX_CHARS = 128
#: 单份 JSONL 尺寸上限，超限滚动为 ``<key>.rN.jsonl``（单写线程内滚动，无竞态）
ARCHIVE_FILE_MAX_BYTES = 10 * 1024 * 1024
#: 错误摘要长度上限（先脱敏后截断）
ERROR_SUMMARY_MAX_CHARS = 300
#: 后台写队列深度（满 = 丢弃 + 计数，不阻塞调用路径）
WRITER_QUEUE_MAX_ENTRIES = 2048
#: flush 默认等待上限（秒）
WRITER_FLUSH_TIMEOUT_SECONDS = 5.0
#: 聚合摘要"最近错误"条数
RECENT_ERROR_LIMIT = 5
#: 聚合读取每会话最多计入的条数（取尾部最近窗口）
AGGREGATE_MAX_ENTRIES_PER_SESSION = 200
#: 时延分布桶边（ms）与桶名：lt1s / s1to5 / s5to20 / gt20s
LATENCY_BUCKET_EDGES_MS: Tuple[int, ...] = (1000, 5000, 20000)
LATENCY_BUCKET_LABELS: Tuple[str, ...] = ("lt1s", "s1to5", "s5to20", "gt20s")
#: 无会话上下文调用的归档键
UNSCOPED_ARCHIVE_KEY = "unscoped"
#: 尾读分块大小（聚合反向读，不整载大文件）
_TAIL_READ_CHUNK_BYTES = 64 * 1024

_KEY_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]")


# ── 脱敏（S7 单源复用）────────────────────────────────────────────


def redactSensitiveText(text: Any) -> str:
    """逐条套用 S7 的 SENSITIVE_KEY_PATTERNS，命中段以 redactSecret 遮蔽。

    模式族与遮蔽实现都只在 `neurova.memory_admission` 一处定义，本模块不复制
    正则（教义第 6 条）。
    """
    from neurova.memory_admission import SENSITIVE_KEY_PATTERNS, redactSecret

    out = str(text or "")
    for pattern in SENSITIVE_KEY_PATTERNS:
        out = pattern.regex.sub(lambda matched: redactSecret(matched.group(0)), out)
    return out


def _redactAndTruncateSummary(text: Any) -> str:
    """错误摘要出口：先脱敏后截断（截断不得把未脱敏原文带出去）。"""
    return redactSensitiveText(text)[:ERROR_SUMMARY_MAX_CHARS]


# ── 归档键与路径 ──────────────────────────────────────────────────


def sanitizeArchiveKey(sessionId: Any) -> str:
    """会话键清洗：只留 ``[A-Za-z0-9._-]``，长度封顶；空键落 unscoped。"""
    cleaned = _KEY_SANITIZE_RE.sub("_", str(sessionId or ""))[:ARCHIVE_KEY_MAX_CHARS]
    return cleaned or UNSCOPED_ARCHIVE_KEY


def archiveDir() -> Path:
    from neurova.core.data_root import get_data_root

    return get_data_root() / ARCHIVE_DIR_NAME


def archiveFilePath(key: str) -> Path:
    return archiveDir() / f"{sanitizeArchiveKey(key)}.jsonl"


def _rotationIndex(path: Path) -> int:
    match = re.search(r"\.r(\d+)\.jsonl$", path.name)
    return int(match.group(1)) if match else 0


def _archiveFilesNewestFirst(key: str) -> List[Path]:
    """该会话的归档文件，新→旧：主文件在前，滚动件按序号倒序在后。"""
    main = archiveFilePath(key)
    if not main.exists():
        return []
    rotations = [
        p for p in archiveDir().glob(f"{sanitizeArchiveKey(key)}.r*.jsonl")
        if _rotationIndex(p) > 0
    ]
    rotations.sort(key=_rotationIndex, reverse=True)
    return [main, *rotations]


# ── 写器（后台单线程；懒创建单例）─────────────────────────────────


class RequestArchiveWriter:
    """队列 + 单写线程：入队不阻塞调用路径，落盘失败计数可见。"""

    def __init__(self) -> None:
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(
            maxsize=WRITER_QUEUE_MAX_ENTRIES
        )
        self._threadLock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._written = 0
        self._writeFailures = 0
        self._queueDrops = 0

    def enqueue(self, entry: Dict[str, Any]) -> None:
        self._ensureThread()
        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            self._queueDrops += 1
            logger.warning(
                "请求归档队列已满（上限 %d），丢弃一条（累计 %d）",
                WRITER_QUEUE_MAX_ENTRIES, self._queueDrops,
            )

    def _ensureThread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        with self._threadLock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="request-archive-writer", daemon=True,
                )
                self._thread.start()

    def _run(self) -> None:
        while True:
            entry = self._queue.get()
            try:
                key = sanitizeArchiveKey(entry.get("sessionId"))
                self._appendEntry(entry, archiveFilePath(key))
            except Exception as e:  # noqa: BLE001 - fail-soft：日志+计数，不外抛
                self._writeFailures += 1
                logger.warning("请求归档写入失败（不阻断主链路）: %s", e)
            finally:
                self._queue.task_done()

    def _appendEntry(self, entry: Dict[str, Any], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._rotateIfNeeded(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._written += 1

    def _rotateIfNeeded(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size < ARCHIVE_FILE_MAX_BYTES:
            return
        existing = [
            _rotationIndex(p)
            for p in archiveDir().glob(f"{path.stem}.r*.jsonl")
            if _rotationIndex(p) > 0
        ]
        nextIndex = (max(existing) if existing else 0) + 1
        path.rename(path.with_name(f"{path.stem}.r{nextIndex}.jsonl"))
        logger.warning(
            "请求归档 %s 达尺寸上限（%d 字节），滚动为 .r%d",
            path.name, size, nextIndex,
        )

    def flush(self, timeout: float = WRITER_FLUSH_TIMEOUT_SECONDS) -> bool:
        """等待队列清空（测试/收尾用）；超时返回 False（不吞，如实报告）。"""
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.unfinished_tasks > 0:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def stats(self) -> Dict[str, int]:
        return {
            "written": self._written,
            "writeFailures": self._writeFailures,
            "queueDrops": self._queueDrops,
        }


_archiveWriter: Optional[RequestArchiveWriter] = None
_archiveWriterLock = threading.RLock()


def getArchiveWriter() -> RequestArchiveWriter:
    """写器懒创建单例（DCL + RLock，§3 纪律）。"""
    global _archiveWriter
    if _archiveWriter is None:
        with _archiveWriterLock:
            if _archiveWriter is None:
                _archiveWriter = RequestArchiveWriter()
    return _archiveWriter


def resetRequestArchive() -> None:
    """测试/teardown：尽力落盘排队条目后重置写器单例。"""
    global _archiveWriter
    with _archiveWriterLock:
        writer = _archiveWriter
        _archiveWriter = None
    if writer is not None:
        writer.flush()


def requestArchiveWriteStats() -> Dict[str, int]:
    """写侧读数（written/writeFailures/queueDrops/enqueueFailures）——失败可见面。"""
    stats = {"written": 0, "writeFailures": 0, "queueDrops": 0, "enqueueFailures": 0}
    with _archiveWriterLock:
        writer = _archiveWriter
        enqueueFailures = _enqueueFailures
    if writer is not None:
        stats.update(writer.stats())
    stats["enqueueFailures"] = enqueueFailures
    return stats


_enqueueFailures = 0


# ── 全文归档门（钩子）─────────────────────────────────────────────

_fullTextWarned = False
_fullTextWarnLock = threading.RLock()


def requestFullTextEnabled() -> bool:
    """全文归档门（S17 拍板：本批只做门控钩子，全文形态另议）。

    门开（env 置 1）时**不改落盘内容**，只发一次性 WARNING——门开着却静默
    无效是最糟的旋钮形态；归档仍只落脱敏摘要（``fullText`` 恒 False）。
    """
    global _fullTextWarned
    enabled = (os.environ.get(FULL_TEXT_ENV) or "").strip() == "1"
    if enabled:
        with _fullTextWarnLock:
            if not _fullTextWarned:
                _fullTextWarned = True
                logger.warning(
                    "全文归档门 %s 已开：本批未实现全文落盘，归档仍只落脱敏摘要（S17 另议）",
                    FULL_TEXT_ENV,
                )
    return enabled


# ── 记录入口 ──────────────────────────────────────────────────────


def summarizeMessageRoles(messages: Any) -> Dict[str, Dict[str, int]]:
    """消息列表 → 角色×(条数, 字符数) 摘要（不落正文）。"""
    roles: Dict[str, Dict[str, int]] = {}
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "unknown")
        content = message.get("content")
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            chars = sum(
                len(part.get("text") or "")
                for part in content if isinstance(part, dict)
            )
        else:
            chars = 0
        slot = roles.setdefault(role, {"count": 0, "chars": 0})
        slot["count"] += 1
        slot["chars"] += chars
    return roles


def normalizeArchiveUsage(usage: Any) -> Dict[str, Any]:
    """usage 归一（调用方键面：promptTokens/completionTokens/estimated/cache*）。"""
    values = usage if isinstance(usage, dict) else {}

    def _int(key: str) -> int:
        try:
            return int(values.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "promptTokens": _int("promptTokens"),
        "completionTokens": _int("completionTokens"),
        "estimated": bool(values.get("estimated")),
        "cacheReadTokens": _int("cacheReadTokens"),
        "cacheWriteTokens": _int("cacheWriteTokens"),
    }


def recordRequestArchive(
    *,
    provider: Any,
    model: Any,
    messages: Any = None,
    usage: Any = None,
    durationMs: Any = 0,
    success: bool = True,
    errorKind: str = "",
    errorSummary: str = "",
    stream: bool = False,
    firstTokenMs: Any = 0,
    responseId: Any = None,
) -> None:
    """入队一条请求归档（fail-soft：任何异常 WARNING + 计数，不外抛）。

    轮上下文（session/user/trace）在**入队时**同步捕获——写线程读到的是
    它自己的 context，不是请求的。
    """
    global _enqueueFailures
    try:
        requestFullTextEnabled()  # 门钩子消费：门开有一次性 WARNING，落盘不变
        from neurova.core.identity_context import get_request_user_id
        from neurova.core.trace_context import get_trace_id
        from neurova.core.turn_context import get_turn_session_id

        now = time.time()
        entry: Dict[str, Any] = {
            "ts": round(now, 3),
            "tsIso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "sessionId": get_turn_session_id() or "",
            "userId": get_request_user_id() or "",
            "provider": str(provider or ""),
            "model": str(model or ""),
            "roles": summarizeMessageRoles(messages),
            "usage": normalizeArchiveUsage(usage),
            "durationMs": max(0, int(durationMs or 0)),
            "success": bool(success),
            "stream": bool(stream),
            # 本批恒 False：全文归档门控另议（见 requestFullTextEnabled）
            "fullText": False,
        }
        traceId = get_trace_id()
        if traceId:
            entry["traceId"] = str(traceId)
        if stream:
            entry["firstTokenMs"] = max(0, int(firstTokenMs or 0))
        if responseId:
            entry["responseId"] = str(responseId)
        if not success:
            entry["errorKind"] = str(errorKind or "unknown")
            if errorSummary:
                entry["errorSummary"] = _redactAndTruncateSummary(errorSummary)
        getArchiveWriter().enqueue(entry)
    except Exception as e:  # noqa: BLE001 - fail-soft：日志+计数，不外抛
        with _archiveWriterLock:
            _enqueueFailures += 1
        logger.warning("请求归档入队失败（不阻断主链路）: %s", e)


def flushRequestArchive(timeout: float = WRITER_FLUSH_TIMEOUT_SECONDS) -> bool:
    """等待排队条目落盘（测试/收尾用）。"""
    with _archiveWriterLock:
        writer = _archiveWriter
    if writer is None:
        return True
    return writer.flush(timeout)


# ── 消费面：档案聚合（S12 dossier 读时 join 的单源）────────────────


def _readTailEntries(path: Path, maxEntries: int) -> Tuple[List[Dict[str, Any]], bool]:
    """反向分块读文件尾部至多 maxEntries 条；返回 (条目, 是否还有更多)。"""
    entries: List[Dict[str, Any]] = []
    hasMore = False
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            position = f.tell()
            tail = b""
            while position > 0 and len(entries) < maxEntries:
                chunkSize = min(_TAIL_READ_CHUNK_BYTES, position)
                position -= chunkSize
                f.seek(position)
                block = f.read(chunkSize) + tail
                lines = block.split(b"\n")
                tail = lines[0]  # 块首半行留给上一块
                for raw in reversed(lines[1:]):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entries.append(json.loads(raw.decode("utf-8")))
                    except (ValueError, UnicodeDecodeError):
                        continue  # 损坏行跳过，不阻断聚合
                    if len(entries) >= maxEntries:
                        break
            if len(entries) >= maxEntries and (position > 0 or tail.strip()):
                hasMore = True
            elif position == 0 and len(entries) < maxEntries and tail.strip():
                # 首块补上文件第一行
                try:
                    entries.append(json.loads(tail.strip().decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    pass
    except OSError as e:
        logger.debug("请求归档尾读失败 (%s): %s", path, e)
        return [], False
    entries.reverse()
    return entries, hasMore


def _latencyBucketLabel(durationMs: int) -> str:
    for label, edge in zip(LATENCY_BUCKET_LABELS, LATENCY_BUCKET_EDGES_MS):
        if durationMs < edge:
            return label
    return LATENCY_BUCKET_LABELS[-1]


def summarizeSessionArchives(
    sessionIds: Any,
    *,
    maxEntriesPerSession: int = AGGREGATE_MAX_ENTRIES_PER_SESSION,
    maxErrors: int = RECENT_ERROR_LIMIT,
) -> Dict[str, Any]:
    """聚合若干会话的请求归档（档案消费面单源；fail-open：读失败按 0 计）。

    每会话取**尾部最近窗口**（``maxEntriesPerSession`` 条，新→旧跨滚动件回溯）；
    窗口外条目不计入，且 ``entryWindowComplete=False`` 显式声明——摘要不冒充全量。
    """
    sessionKeys: List[str] = []
    seenKeys = set()
    for sessionId in sessionIds or []:
        key = sanitizeArchiveKey(sessionId)
        if key not in seenKeys:
            seenKeys.add(key)
            sessionKeys.append(key)

    requestCount = 0
    successCount = 0
    failureCount = 0
    promptTokens = 0
    completionTokens = 0
    estimatedCalls = 0
    durations: List[int] = []
    errorEntries: List[Dict[str, Any]] = []
    readSessions: List[str] = []
    windowComplete = True

    for key in sessionKeys:
        collected = 0
        for path in _archiveFilesNewestFirst(key):
            remaining = maxEntriesPerSession - collected
            if remaining <= 0:
                windowComplete = False
                break
            tailEntries, hasMore = _readTailEntries(path, remaining)
            if hasMore:
                windowComplete = False
            collected += len(tailEntries)
            for entry in tailEntries:
                requestCount += 1
                if entry.get("success"):
                    successCount += 1
                else:
                    failureCount += 1
                    errorEntries.append({
                        "ts": entry.get("ts"),
                        "provider": entry.get("provider", ""),
                        "model": entry.get("model", ""),
                        "errorKind": entry.get("errorKind", ""),
                        "errorSummary": entry.get("errorSummary", ""),
                    })
                usageValues = entry.get("usage") or {}
                promptTokens += int(usageValues.get("promptTokens") or 0)
                completionTokens += int(usageValues.get("completionTokens") or 0)
                if usageValues.get("estimated"):
                    estimatedCalls += 1
                durations.append(int(entry.get("durationMs") or 0))
        if collected:
            readSessions.append(key)

    buckets = {label: 0 for label in LATENCY_BUCKET_LABELS}
    for duration in durations:
        buckets[_latencyBucketLabel(duration)] += 1
    errorEntries.sort(key=lambda e: e.get("ts") or 0, reverse=True)
    return {
        "sessions": readSessions,
        "requestCount": requestCount,
        "successCount": successCount,
        "failureCount": failureCount,
        "promptTokens": promptTokens,
        "completionTokens": completionTokens,
        "estimatedCalls": estimatedCalls,
        "latencyMs": {
            "avgMs": round(sum(durations) / len(durations)) if durations else 0,
            "maxMs": max(durations) if durations else 0,
            "buckets": buckets,
        },
        "recentErrors": errorEntries[:max(0, maxErrors)],
        "entryWindowComplete": windowComplete,
    }
