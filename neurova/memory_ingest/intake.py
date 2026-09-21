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
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from neurova.memory_ingest.bundle.manifest import BundleError, BundleManifest, load_manifest
from neurova.memory_ingest.bundle.media import MEDIA_DIRNAME
from neurova.memory_ingest.bundle.records import MemoryRecord, TranscriptRecord
from neurova.memory_ingest.bundle.turns import to_turn_messages
from neurova.memory_ingest.bundle.validate import validate_bundle
from neurova.session_manager import SessionOwnerConflict

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
    owner_user_id: str = ""
    memories_added: int = 0
    memories_skipped: int = 0
    messages_added: int = 0
    messages_skipped: int = 0
    sessions_touched: int = 0
    dropped: Tuple[Dict[str, Any], ...] = ()
    staged_media: Tuple[str, ...] = ()

    def undo(self, *, manager, sessions) -> Tuple[int, int]:
        """返回 (撤销记忆条数, 撤销消息条数)；只删本批，不碰运行期数据。"""
        return undo_run(self.agent_id, self.run_id, manager=manager, sessions=sessions)

    def owner_of_run(self, sessions) -> Tuple[str, ...]:
        """本批落盘消息里记着的属主（去重）。报告态取不到时为空元组，不猜。"""
        return sessions.ingested_run_owners(self.agent_id, self.run_id)


def undo_run(agent_id: str, run_id: str, *, manager, sessions) -> Tuple[int, int]:
    """撤销一条批次——报告在不在手都走这条路，媒体清理不留第二条口径。

    媒体按"这批引用过、删完已无人引用"来清：内容寻址允许共享，所以不能直接删；
    但撤销完还留在盘上就是垃圾（工作区里已经栽过一次几百文件的跟头）。
    候选要在删消息**之前**取：删完再扫，这批碰过谁就无从知道了。
    """
    _, candidates = _referenced_media(agent_id, run_id, sessions)
    removed = (manager.delete_ingested_memories(run_id),
               sessions.delete_ingested_messages(agent_id, run_id))
    _prune_media(agent_id, candidates, sessions)
    return removed


def _referenced_media(agent_id: str, run_id: str, sessions) -> Tuple[Set[str], Set[str]]:
    """一次扫描给出 (当前仍被引用的媒体名, 本批引用过的媒体名)。

    引用只认 metadata.artifacts 里的登记条目：把全部会话拼成一个大串再取子串，
    正文里偶然出现的同名串会把该删的文件永久留住。
    """
    every: Set[str] = set()
    per_run: Set[str] = set()
    for path in sessions.iter_session_files(agent_id):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for message in data.get("messages") or []:
            metadata = message.get("metadata") or {}
            names = {str(artifact["name"]) for artifact in (metadata.get("artifacts") or [])
                     if isinstance(artifact, dict) and artifact.get("name")}
            every |= names
            if metadata.get("ingest_run_id") == run_id:
                per_run |= names
    return every, per_run


def plan_bundle(root: Path) -> IngestPlan:
    """只读出报告：全程不触碰任何 store。"""
    transcripts, memories, manifest = _load(Path(root))
    messages = sum(len(to_turn_messages(records)) for _, records in _group(transcripts))
    return IngestPlan(agent_name=manifest.agent_name, source=dict(manifest.source),
                      counts={"transcripts": len(transcripts), "memories": len(memories)},
                      dropped=tuple(manifest.dropped), turn_messages=messages)


def apply_bundle(root: Path, *, agent_id: str, manager, sessions,
                 run_id: Optional[str] = None,
                 owner_user_id: str = "") -> IngestReport:
    """把一支合规 bundle 写进两条咽喉；返回可直接 undo 的报告。

    `owner_user_id` 缺省为空 = 共享会话（单用户桌面下的合法语义）；多用户/多渠道下
    导入他人历史必须显式给属主，否则读侧"空属主=任何人可见"的规则会让导入的私有
    历史对所有人开放。归属不合法（会话已有别的属主）由咽喉抛 SessionOwnerConflict，
    这里兜成 BundleError：整批拒绝，与坏包同一姿态。
    """
    if not _AGENT_ID.match(str(agent_id or "")):
        raise BundleError(f"agent_id 必须是简单标识符（它会参与目录拼接）: {agent_id!r}")
    transcripts, memories, manifest = _load(Path(root))
    report = IngestReport(run_id=run_id or f"nvimp-{uuid.uuid4().hex[:12]}",
                          agent_id=agent_id, owner_user_id=str(owner_user_id or ""),
                          dropped=tuple(manifest.dropped))

    # 归属冲突是整包级判据：写任何字节之前判完，绝不留"前几支会话已落盘"的半程导入。
    # 咽喉抛的是自己那层的 SessionOwnerConflict；本层收口成 BundleError，让 CLI 与
    # "坏包"走同一条拒绝路径（退出码与 stderr 文案都由 CLI 统一处理）。
    try:
        sessions.check_ingest_owners(report.agent_id, [sid for sid, _ in _group(transcripts)],
                                     report.owner_user_id)
    except SessionOwnerConflict as exc:
        raise BundleError(str(exc)) from exc

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
            _stage_media(bundle_root, message, report)
            by_date[str(message["timestamp"])[:10]].append(message)
        for date, batch in sorted(by_date.items()):
            added, skipped = sessions.import_session_messages(
                report.agent_id, session_id, date, batch, ingest_run_id=report.run_id,
                owner_user_id=report.owner_user_id)
            report.messages_added += added
            report.messages_skipped += skipped
            report.sessions_touched += 1


def workspace_media_dir(agent_id: str, *, create: bool = True) -> Path:
    """导入媒体的落点：agent 工作区下的 media/（文件名即内容摘要）。"""
    from neurova.core.agent_workspaces import get_agent_workspace_dir

    target = get_agent_workspace_dir(agent_id) / MEDIA_DIRNAME
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def _stage_media(bundle_root: Path, message: Dict[str, Any], report: "IngestReport") -> None:
    """包内引用 → 工作区文件 + 运行期同形的 artifact 条目。

    artifact_id 用与 artifacts 注册处同一算法（对定形后路径取 sha1 前 16 位），所以任何
    一侧登记都指向同一条目；不直接 import 注册函数是为了不把数据层挂到 API 层上。
    """
    media = (message.get("metadata") or {}).pop("media", None)
    if not media:
        return
    destination = workspace_media_dir(report.agent_id)
    artifacts = message["metadata"].setdefault("artifacts", [])
    staged = set(report.staged_media)
    for ref in media:
        rel = str(ref.get("media") or "")
        target = destination / Path(rel).name
        if not target.exists():
            shutil.copyfile(bundle_root / rel, target)
        artifacts.append(_artifact_info(target, report.agent_id, ref))
        staged.add(target.name)
    report.staged_media = tuple(sorted(staged))


def _prune_media(agent_id: str, candidates: Set[str], sessions) -> int:
    """删掉这批碰过、且删完已无人引用的媒体；仍被别处引用的留着（内容寻址本就共享）。"""
    if not candidates:
        return 0
    directory = workspace_media_dir(agent_id, create=False)
    still_referenced = _referenced_media(agent_id, "", sessions)[0]   # 删消息已发生，此刻的引用才是活的
    removed = 0
    for name in sorted(candidates - still_referenced):
        path = directory / name
        if path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
    return removed


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
        except (TypeError, ValueError) as exc:
            # ValueError 来自各记录类型的取值域（kind/reasoning_state 等）：与未知字段同属
            # "这行不符合契约"，必须在写库之前整包拒绝，不能让它穿到咽喉才炸。
            raise BundleError(
                f"{path.name}:{lineno} 记录不符合契约（宁可整包拒绝，不做静默忽略）: {exc}"
            ) from exc
    return records
