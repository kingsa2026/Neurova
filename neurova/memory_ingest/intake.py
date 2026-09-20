# -*- coding: utf-8 -*-
"""唯一写入口：校验 → 只读出计划（plan）→ 显式写库（apply）→ 按批次撤销（undo）。

三条姿态都在这里落地：不 --apply 就不碰 store；包不合规就整包拒绝（半导的数据既难察觉
又难撤销）；写会话前先过轮形装配，导入产物与运行期落盘同形。
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest, load_manifest
from neurova.memory_ingest.bundle.media import MEDIA_DIRNAME
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord
from neurova.memory_ingest.bundle.turns import to_turn_messages
from neurova.memory_ingest.bundle.validate import validate_bundle

MAX_RECORDS = 200_000          # 误指大目录的兜底闸
_AGENT_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._@-]*$")
_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".csv", ".log", ".py", ".ts"})


@dataclass(frozen=True)
class IngestPlan:
    agent_name: str
    source: Dict[str, Any]
    counts: Dict[str, int]
    dropped: Tuple[Dict[str, Any], ...]
    turn_messages: int = 0


@dataclass
class IngestReport:
    run_id: str
    agent_id: str
    memories_added: int = 0
    memories_skipped: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    sessions_touched: int = 0
    dropped: Tuple[Dict[str, Any], ...] = ()

    def undo(self, *, manager, sessions) -> Tuple[int, int]:
        """返回 (撤销记忆条数, 撤销消息条数)；只删本批，不碰运行期数据。"""
        return (manager.delete_ingested_memories(self.run_id),
                sessions.delete_ingested_messages(self.agent_id, self.run_id))


def plan_bundle(root: Path) -> IngestPlan:
    """只读出报告：全程不触碰任何 store。"""
    transcripts, memories, manifest = _load(Path(root))
    messages = sum(len(to_turn_messages(records)) for _, records in _group(transcripts))
    return IngestPlan(agent_name=manifest.agent_name, source=dict(manifest.source),
                      counts={"transcripts": len(transcripts), "memories": len(memories)},
                      dropped=tuple(manifest.dropped), turn_messages=messages)


def apply_bundle(root: Path, *, agent_id: str, manager, sessions,
                 run_id: Optional[str] = None) -> IngestReport:
    """把一支合规 bundle 写进两条咽喉；返回可直接 undo 的报告。"""
    if not _AGENT_ID.match(str(agent_id or "")):
        raise BundleError(f"agent_id 必须是简单标识符（它会参与目录拼接）: {agent_id!r}")
    transcripts, memories, manifest = _load(Path(root))
    report = IngestReport(run_id=run_id or f"nvimp-{uuid.uuid4().hex[:12]}",
                          agent_id=agent_id, dropped=tuple(manifest.dropped))

    report.memories_added, report.memories_skipped = manager.import_memories(
        memories, ingest_run_id=report.run_id)

    try:
        _write_sessions(report, transcripts, sessions, Path(root))
    except BundleError:
        raise
    except Exception as exc:                       # 半途失败必须给出去路，不能留悬批
        raise BundleError(
            f"写会话中断（run_id={report.run_id}）：{exc}；"
            f"已写入部分请用 undo(manager=..., sessions=...) 或 --undo 撤销") from exc
    return report


def _write_sessions(report: IngestReport, transcripts: Sequence[TranscriptRecord],
                    sessions, bundle_root: Path) -> None:
    for session_id, records in _group(transcripts):
        by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for message in to_turn_messages(records):
            _stage_media(bundle_root, message, report.agent_id)
            by_date[str(message["timestamp"])[:10]].append(message)
        for date, batch in sorted(by_date.items()):
            added, skipped = sessions.import_session_messages(
                report.agent_id, session_id, date, batch, ingest_run_id=report.run_id)
            report.messages_added += added
            report.messages_skipped += skipped
            report.sessions_touched += 1


def workspace_media_dir(agent_id: str) -> Path:
    """导入媒体的落点：agent 工作区下的 media/（文件名即内容摘要）。"""
    from neurova.core.agent_workspaces import get_agent_workspace_dir

    target = get_agent_workspace_dir(agent_id) / MEDIA_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def _stage_media(bundle_root: Path, message: Dict[str, Any], agent_id: str) -> None:
    """包内引用 → 工作区文件 + 运行期同形的 artifact 条目。

    artifact_id 用与 artifacts 注册处同一算法（对定形后路径取 sha1 前 16 位），所以任何
    一侧登记都指向同一条目；不直接 import 注册函数是为了不把数据层挂到 API 层上。
    """
    media = (message.get("metadata") or {}).pop("media", None)
    if not media:
        return
    destination = workspace_media_dir(agent_id)
    artifacts = (message["metadata"]).setdefault("artifacts", [])
    for ref in media:
        rel = str(ref.get("media") or "")
        name = Path(rel).name
        target = destination / name
        if not target.exists():
            shutil.copyfile(bundle_root / rel, target)
        artifacts.append(_artifact_info(target, agent_id, ref))


def _artifact_info(path: Path, agent_id: str, ref: Dict[str, Any]) -> Dict[str, Any]:
    mime = str(ref.get("mime") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return {
        "artifact_id": hashlib.sha1(str(path.resolve()).encode("utf-8", errors="replace"))
        .hexdigest()[:16],
        "kind": _artifact_kind(path.name, mime),
        "name": path.name,
        "size": path.stat().st_size,
        "mime_type": mime,
        "agent_id": agent_id,
        "path": str(path.resolve()),
        "source": "ingest",
    }


def _artifact_kind(name: str, mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/") or mime.startswith("video/"):
        return "media"
    return "text" if Path(name).suffix.lower() in _TEXT_SUFFIXES else "file"


def _group(transcripts: Sequence[TranscriptRecord]):
    """按会话分组并按 seq 定序：会话内顺序靠 seq，不靠时钟（时钟会倒退）。"""
    grouped: Dict[str, List[TranscriptRecord]] = {}
    for record in transcripts:
        grouped.setdefault(record.session_id, []).append(record)
    for records in grouped.values():
        records.sort(key=lambda record: record.seq)
    return grouped.items()


def _load(root: Path) -> Tuple[List[TranscriptRecord], List[MemoryRecord], BundleManifest]:
    errors = validate_bundle(root)
    if errors:
        raise BundleError("包校验未通过：" + "；".join(errors))
    manifest = load_manifest(root / "manifest.json")
    transcripts = _read_records(TranscriptRecord, root / "transcripts.jsonl")
    memories = _read_records(MemoryRecord, root / "memories.jsonl")
    total = len(transcripts) + len(memories)
    if total > MAX_RECORDS:
        raise BundleError(f"条目数 {total} 超上限 {MAX_RECORDS}，拒绝（疑似指错目录）")
    return transcripts, memories, manifest


def _read_records(cls, path: Path) -> List[Any]:
    if not path.exists():
        return []
    records: List[Any] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(cls(**json.loads(line)))
        except TypeError as exc:
            raise BundleError(
                f"{path.name}:{lineno} 字段不在契约内（宁可整包拒绝，不做静默忽略）: {exc}"
            ) from exc
    return records
