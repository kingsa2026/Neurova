# -*- coding: utf-8 -*-
"""把历史 memory_attachments 一次性迁移到 artifact 注册表。

用法（后端停止后执行）：
    python scripts/migrate_memory_attachments_to_artifacts.py \
        --source-db data/agent/<bucket>/<agent_id>/memory/memory.db \
        --target-db data/users.db --agent-id <agent_id>

约束：
- 只读源库；不删除历史表、关联记录或源文件。
- 文件必须存在、大小与内容哈希均匹配，且通过 artifact 当前路径白名单。
- 归属沿用 artifact 契约：有 user_id 为属主；无属主时显式 shared=True。
- 同一附件关联多条记忆只生成一条 artifact；重复运行按 artifact_id 幂等。
- 单条失败继续处理其余记录，最终以非零退出码暴露失败。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from neurova.api.endpoints import artifacts_api  # noqa: E402


def _readLegacyAttachments(sourceDbPath: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sourceDbPath)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = {"attachments", "memory_attachments"} - tables
        if missing:
            raise ValueError(f"源库缺少历史表: {', '.join(sorted(missing))}")

        rows = conn.execute(
            """
            SELECT a.*, ma.memory_id
            FROM attachments a
            JOIN memory_attachments ma ON ma.attachment_id = a.id
            ORDER BY a.id, ma.memory_id
            """
        ).fetchall()
    finally:
        conn.close()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = dict(row)
        attachmentId = str(record["id"])
        if attachmentId not in grouped:
            record["memory_ids"] = []
            grouped[attachmentId] = record
        grouped[attachmentId]["memory_ids"].append(str(record["memory_id"]))
    return list(grouped.values())


def _parseMetadata(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("历史 metadata 不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("历史 metadata 必须是 JSON 对象")
    return value


def _resolveSourcePath(rawPath: Any, sourceDbPath: Path) -> Path:
    value = str(rawPath or "").strip()
    if not value:
        raise ValueError("历史记录缺少 file_path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = sourceDbPath.parent / path
    return path.resolve()


def _verifySourceFile(path: Path, expectedSize: Any, expectedHash: Any) -> None:
    if not path.is_file():
        raise ValueError(f"源文件不存在: {path}")
    actualSize = path.stat().st_size
    if expectedSize is not None and int(expectedSize) != actualSize:
        raise ValueError(
            f"源文件大小不匹配: 记录 {expectedSize}, 实际 {actualSize}"
        )

    digestText = str(expectedHash or "").strip().lower()
    algorithm = {32: "md5", 40: "sha1", 64: "sha256"}.get(len(digestText))
    if not algorithm:
        raise ValueError("历史记录缺少可识别的内容哈希")
    digest = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as sourceFile:
        while chunk := sourceFile.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest().lower() != digestText:
        raise ValueError("源文件内容哈希不匹配")


def _findArtifactByPath(targetDbPath: Path, path: Path) -> sqlite3.Row | None:
    if not targetDbPath.exists():
        return None
    conn = sqlite3.connect(targetDbPath)
    conn.row_factory = sqlite3.Row
    try:
        hasTable = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'artifacts'"
        ).fetchone()
        if not hasTable:
            return None
        return conn.execute(
            "SELECT * FROM artifacts WHERE path = ?", (str(path),)
        ).fetchone()
    finally:
        conn.close()


def _ownershipConflict(
    existing: sqlite3.Row,
    *,
    artifactId: str,
    owner: str,
    shared: bool,
) -> str:
    if str(existing["artifact_id"]) != artifactId:
        return "同路径已有 artifact，但 artifact_id 与当前契约不一致"
    existingOwner = str(existing["user_id"] or "").strip()
    existingShared = bool(existing["shared"])
    if existingOwner and existingOwner != owner:
        return "同路径已有 artifact 的属主与历史记录冲突"
    if existingShared != shared:
        return "同路径已有 artifact 的共享标记与历史记录冲突"
    return ""


def _persistedArtifact(targetDbPath: Path, artifactId: str) -> sqlite3.Row:
    conn = sqlite3.connect(targetDbPath)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifactId,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("artifact 注册表持久化失败：目标库查无该条目")
    return row


def _verifyPersistedArtifact(
    persisted: sqlite3.Row,
    *,
    path: Path,
    owner: str,
    shared: bool,
) -> None:
    if str(persisted["path"]) != str(path):
        raise ValueError("artifact 持久化路径与迁移路径不一致")
    if str(persisted["user_id"] or "").strip() != owner:
        raise ValueError("artifact 持久化属主与迁移属主不一致")
    if bool(persisted["shared"]) != shared:
        raise ValueError("artifact 持久化共享标记与迁移标记不一致")
    if int(persisted["size"] or 0) != path.stat().st_size:
        raise ValueError("artifact 持久化大小与源文件不一致")


def migrateMemoryAttachments(
    sourceDbPath: str | Path,
    targetDbPath: str | Path | None = None,
    agentId: str = "",
) -> dict[str, Any]:
    """迁移单个历史记忆库；返回可 JSON 序列化的逐附件报告。"""
    sourcePath = Path(sourceDbPath).expanduser().resolve()
    if not sourcePath.is_file():
        raise ValueError(f"源库不存在: {sourcePath}")
    targetPath = Path(
        targetDbPath or artifacts_api._defaultArtifactsDbPath()
    ).expanduser().resolve()

    records = _readLegacyAttachments(sourcePath)
    results: list[dict[str, Any]] = []
    migrated = 0
    alreadyMigrated = 0
    failed = 0

    for record in records:
        attachmentId = str(record["id"])
        memoryIds = list(record.get("memory_ids") or [])
        result: dict[str, Any] = {
            "attachment_id": attachmentId,
            "memory_ids": memoryIds,
            "status": "failed",
            "artifact_id": "",
            "error": "",
        }
        try:
            sourceFile = _resolveSourcePath(record.get("file_path"), sourcePath)
            _verifySourceFile(
                sourceFile,
                record.get("file_size"),
                record.get("file_hash"),
            )
            metadata = _parseMetadata(record.get("metadata"))
            owner = str(record.get("user_id") or "").strip()
            metadataShared = metadata.get("shared")
            shared = metadataShared if isinstance(metadataShared, bool) else not owner
            rowAgentId = str(record.get("agent_id") or agentId or "").strip()
            expectedArtifactId = artifacts_api.artifactIdForPath(str(sourceFile))

            existing = _findArtifactByPath(targetPath, sourceFile)
            if existing is not None:
                conflict = _ownershipConflict(
                    existing,
                    artifactId=expectedArtifactId,
                    owner=owner,
                    shared=shared,
                )
                if conflict:
                    raise ValueError(conflict)

            info = artifacts_api.register_artifact(
                str(sourceFile),
                agent_id=rowAgentId,
                user_id=owner,
                shared=shared,
                db_path=str(targetPath),
            )
            if existing is not None and not info.get("source"):
                info["source"] = str(existing["source"] or "")
            if not info.get("source"):
                info["source"] = f"memory_attachment:{attachmentId}"
                artifacts_api.persist_artifact(info, db_path=str(targetPath))

            persisted = _persistedArtifact(targetPath, expectedArtifactId)
            _verifyPersistedArtifact(
                persisted,
                path=sourceFile,
                owner=owner,
                shared=shared,
            )
            result["artifact_id"] = expectedArtifactId
            if existing is None:
                result["status"] = "migrated"
                migrated += 1
            else:
                result["status"] = "already_migrated"
                alreadyMigrated += 1
        except Exception as exc:  # noqa: BLE001 - 逐条失败是迁移工具的契约
            result["status"] = "failed"
            result["error"] = str(exc)
            failed += 1
        results.append(result)

    return {
        "source_db": str(sourcePath),
        "target_db": str(targetPath),
        "total": len(records),
        "migrated": migrated,
        "already_migrated": alreadyMigrated,
        "failed": failed,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="历史 memory_attachments → artifact 注册表一次性迁移"
    )
    parser.add_argument("--source-db", required=True, help="历史 memory.db 路径")
    parser.add_argument(
        "--target-db",
        default="",
        help="artifact 元数据库路径（缺省为数据根 users.db）",
    )
    parser.add_argument(
        "--agent-id",
        default="",
        help="历史行 agent_id 为空时的回退 agent_id",
    )
    args = parser.parse_args(argv)

    try:
        report = migrateMemoryAttachments(
            args.source_db,
            args.target_db or None,
            args.agent_id,
        )
    except Exception as exc:  # noqa: BLE001 - CLI 必须诚实非零退出
        print(json.dumps({"failed": 1, "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
