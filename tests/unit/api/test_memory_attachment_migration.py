"""历史记忆附件迁移到 artifact 注册表的真实文件/SQLite 契约测试。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATOR = PROJECT_ROOT / "scripts" / "migrate_memory_attachments_to_artifacts.py"


def _legacy_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE attachments (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            stored_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            file_type TEXT,
            mime_type TEXT,
            file_category TEXT,
            file_hash TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            agent_id TEXT,
            user_id TEXT
        );
        CREATE TABLE memory_attachments (
            memory_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (memory_id, attachment_id)
        );
        """
    )


def _insert_attachment(
    conn: sqlite3.Connection,
    *,
    attachment_id: str,
    memory_id: str,
    path: Path,
    content: bytes,
    agent_id: str = "ag1",
    user_id: str = "u_alice",
    stored_hash: str | None = None,
    metadata: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO attachments (
            id, filename, stored_name, file_path, file_size, file_type,
            mime_type, file_category, file_hash, metadata, created_at,
            agent_id, user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attachment_id,
            path.name,
            path.name,
            str(path),
            len(content),
            path.suffix,
            "text/plain",
            "document",
            stored_hash or hashlib.md5(content).hexdigest(),
            json.dumps(metadata or {}),
            "2026-01-01T00:00:00+00:00",
            agent_id,
            user_id,
        ),
    )
    conn.execute(
        "INSERT INTO memory_attachments VALUES (?, ?, ?)",
        (memory_id, attachment_id, "2026-01-01T00:00:00+00:00"),
    )


def _run_migrator(source_db: Path, target_db: Path, agent_root: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["NEUROVA_AGENT_WORKSPACES_DIR"] = str(agent_root)
    env["NEUROVA_DATA_DIR"] = str(agent_root / "data")
    return subprocess.run(
        [
            sys.executable,
            str(MIGRATOR),
            "--source-db",
            str(source_db),
            "--target-db",
            str(target_db),
            "--agent-id",
            "ag1",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=60,
    )


def _artifact_rows(target_db: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM artifacts ORDER BY path").fetchall()
    finally:
        conn.close()


def test_migrates_real_files_and_sqlite_rows_idempotently(tmp_path: Path) -> None:
    agent_root = tmp_path / "agents"
    workspace = agent_root / "ag1" / "workspaces"
    attachment_dir = workspace / "attachments"
    attachment_dir.mkdir(parents=True)
    owner_file = attachment_dir / "owner.txt"
    shared_file = attachment_dir / "shared.txt"
    owner_file.write_bytes(b"owner data")
    shared_file.write_bytes(b"shared data")

    source_db = tmp_path / "memory.db"
    target_db = tmp_path / "users.db"
    conn = sqlite3.connect(source_db)
    try:
        _legacy_schema(conn)
        _insert_attachment(
            conn,
            attachment_id="a-owner",
            memory_id="m-owner",
            path=owner_file,
            content=b"owner data",
        )
        _insert_attachment(
            conn,
            attachment_id="a-shared",
            memory_id="m-shared",
            path=shared_file,
            content=b"shared data",
            user_id="",
        )
        conn.commit()
    finally:
        conn.close()

    first = _run_migrator(source_db, target_db, agent_root)
    assert first.returncode == 0, first.stdout + first.stderr
    report = json.loads(first.stdout)
    assert report["total"] == 2
    assert report["migrated"] == 2
    assert report["already_migrated"] == 0
    assert report["failed"] == 0

    rows = _artifact_rows(target_db)
    assert len(rows) == 2
    owner_row = next(row for row in rows if row["name"] == "owner.txt")
    shared_row = next(row for row in rows if row["name"] == "shared.txt")
    assert owner_row["user_id"] == "u_alice"
    assert owner_row["shared"] == 0
    assert owner_row["mime_type"] == "text/plain"
    assert owner_row["kind"] == "text"
    assert owner_row["path"] == str(owner_file.resolve())
    assert owner_row["source"] == "memory_attachment:a-owner"
    assert shared_row["user_id"] == ""
    assert shared_row["shared"] == 1

    second = _run_migrator(source_db, target_db, agent_root)
    assert second.returncode == 0, second.stdout + second.stderr
    rerun = json.loads(second.stdout)
    assert rerun["total"] == 2
    assert rerun["migrated"] == 0
    assert rerun["already_migrated"] == 2
    assert rerun["failed"] == 0
    assert len(_artifact_rows(target_db)) == 2

    conn = sqlite3.connect(source_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM memory_attachments").fetchone()[0] == 2
    finally:
        conn.close()
    assert owner_file.read_bytes() == b"owner data"
    assert shared_file.read_bytes() == b"shared data"


def test_failures_are_per_record_and_never_touch_source(tmp_path: Path) -> None:
    agent_root = tmp_path / "agents"
    attachment_dir = agent_root / "ag1" / "workspaces" / "attachments"
    attachment_dir.mkdir(parents=True)
    good_file = attachment_dir / "good.txt"
    bad_hash_file = attachment_dir / "bad-hash.txt"
    outside_file = tmp_path / "outside.txt"
    good_file.write_bytes(b"good")
    bad_hash_file.write_bytes(b"changed")
    outside_file.write_bytes(b"outside")

    source_db = tmp_path / "memory.db"
    target_db = tmp_path / "users.db"
    conn = sqlite3.connect(source_db)
    try:
        _legacy_schema(conn)
        _insert_attachment(
            conn,
            attachment_id="a-good",
            memory_id="m-good",
            path=good_file,
            content=b"good",
        )
        _insert_attachment(
            conn,
            attachment_id="a-bad-hash",
            memory_id="m-bad-hash",
            path=bad_hash_file,
            content=b"changed",
            stored_hash=hashlib.md5(b"original").hexdigest(),
        )
        _insert_attachment(
            conn,
            attachment_id="a-missing",
            memory_id="m-missing",
            path=attachment_dir / "missing.txt",
            content=b"missing",
        )
        _insert_attachment(
            conn,
            attachment_id="a-outside",
            memory_id="m-outside",
            path=outside_file,
            content=b"outside",
        )
        conn.commit()
    finally:
        conn.close()

    result = _run_migrator(source_db, target_db, agent_root)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["total"] == 4
    assert report["migrated"] == 1
    assert report["failed"] == 3
    assert all(item["error"] for item in report["results"] if item["status"] == "failed")

    rows = _artifact_rows(target_db)
    assert len(rows) == 1
    assert rows[0]["source"] == "memory_attachment:a-good"

    conn = sqlite3.connect(source_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM memory_attachments").fetchone()[0] == 4
    finally:
        conn.close()
    assert good_file.read_bytes() == b"good"
    assert bad_hash_file.read_bytes() == b"changed"
    assert outside_file.read_bytes() == b"outside"


def test_existing_artifact_owner_conflict_is_not_overwritten(tmp_path: Path) -> None:
    agent_root = tmp_path / "agents"
    attachment_dir = agent_root / "ag1" / "workspaces" / "attachments"
    attachment_dir.mkdir(parents=True)
    attachment_file = attachment_dir / "conflict.txt"
    attachment_file.write_bytes(b"conflict")

    source_db = tmp_path / "memory.db"
    target_db = tmp_path / "users.db"
    conn = sqlite3.connect(source_db)
    try:
        _legacy_schema(conn)
        _insert_attachment(
            conn,
            attachment_id="a-conflict",
            memory_id="m-conflict",
            path=attachment_file,
            content=b"conflict",
        )
        conn.commit()
    finally:
        conn.close()

    artifact_id = hashlib.sha1(str(attachment_file.resolve()).encode("utf-8")).hexdigest()[:16]
    conn = sqlite3.connect(target_db)
    try:
        conn.execute(
            """
            CREATE TABLE artifacts (
                artifact_id TEXT PRIMARY KEY,
                kind TEXT, name TEXT, size INTEGER, mime_type TEXT,
                agent_id TEXT, user_id TEXT, shared INTEGER,
                path TEXT, source TEXT, created_at REAL
            )
            """
        )
        conn.execute(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                "text",
                attachment_file.name,
                attachment_file.stat().st_size,
                "text/plain",
                "ag1",
                "someone-else",
                0,
                str(attachment_file.resolve()),
                "existing",
                0.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = _run_migrator(source_db, target_db, agent_root)
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["migrated"] == 0
    assert report["failed"] == 1
    assert report["results"][0]["status"] == "failed"

    rows = _artifact_rows(target_db)
    assert len(rows) == 1
    assert rows[0]["user_id"] == "someone-else"
    assert rows[0]["source"] == "existing"
    assert attachment_file.read_bytes() == b"conflict"
