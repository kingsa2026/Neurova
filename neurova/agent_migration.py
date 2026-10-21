# -*- coding: utf-8 -*-
"""agent 迁移包（zip）：把统一布局下的一个 agent 完整导出/导入。

包结构：

    manifest.json                 # 清单：配置面 + 技能/cron/MCP 引用 + 来源
    agent/...                     # data/<agent_id>/ 全量（SQLite 取一致性快照）
    trajectories/<user>/...       # 轨迹（仍在全局面 data/trajectories/）

导入语义（用户已拍板）：
- **归属按导入者**：agent 属主、会话 user_id、记忆 user_id/neuser_id、
  轨迹 user_id、配置 owner_user_id 一律写成导入者；
- 目标 agent_id 冲突默认 409；admin 显式 overwrite 才允许覆盖；
- 覆盖先完整校验包，再把旧根移到同卷备份，失败原路恢复；
- 技能/cron/MCP 引用面按开关登记；MCP 凭据永不入包。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.agent_workspaces import (
    RESERVED_AGENT_ROOT_NAMES,
    get_agent_config_path,
    get_agent_root_dir,
    get_agent_workspace_dir,
)
from neurova.core.data_root import get_data_root, repoRoot
from neurova.core.logger import get_logger
from neurova.security.safe_archive import UnsafeArchiveError, safe_extract_zip

logger = get_logger(__name__)

MANIFEST_KIND = "neurova.agent-migration"
MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
MAX_PACKAGE_BYTES = int(os.environ.get("NEUROVA_AGENT_MIGRATION_MAX_BYTES", str(2 * 1024**3)))
MAX_ENTRIES = 200_000
WINDOWS_MAX_PATH = 240
_SAFE_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TRANSIENT_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".lck")
_AGENT_ID_KEYS = frozenset({"agent_id", "agentId", "agent"})
_OWNER_KEYS = frozenset({"user_id", "neuser_id", "owner_user_id", "session_owner_id"})
_MIGRATION_LOCK = threading.RLock()


class MigrationError(Exception):
    status_code = 422


class MigrationConflict(MigrationError):
    status_code = 409


class MigrationForbidden(MigrationError):
    status_code = 403


class MigrationTooLarge(MigrationError):
    status_code = 413


@dataclass
class MigrationExport:
    zip_path: Path
    temp_dir: Path
    manifest: Dict[str, Any]


@dataclass
class PreparedImport:
    manifest: Dict[str, Any]
    source_id: str
    target_id: str
    importer: str
    overwrite: bool
    stage_dir: Path
    target_root: Path
    target_trajectory_dir: Path
    source_paths: Dict[str, str]
    trajectory_sources: Dict[str, str]
    registry_entry: Optional[Dict[str, Any]]
    import_skills: bool = True
    import_cron: bool = True
    import_mcp: bool = False
    old_cron_tasks: List[Any] = field(default_factory=list)
    created_cron_tasks: List[Any] = field(default_factory=list)
    backup_token: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    backup_dirs: List[Path] = field(default_factory=list)
    placed_root: bool = False
    placed_trajectory: bool = False
    applied: bool = False


def _validate_agent_id(value: str, *, for_import: bool) -> str:
    agent_id = str(value or "").strip()
    if not _SAFE_AGENT_ID_RE.fullmatch(agent_id):
        raise MigrationError(f"非法 agent_id: {value!r}")
    if for_import:
        if agent_id == "default":
            raise MigrationForbidden("不能把迁移包导入为系统默认 agent")
        if agent_id in RESERVED_AGENT_ROOT_NAMES:
            raise MigrationError(f"agent_id {agent_id!r} 与数据根下的全局目录同名")
    return agent_id


def _is_sqlite(path: Path) -> bool:
    if path.suffix.lower() not in (".db", ".sqlite", ".sqlite3"):
        return False
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _iterAgentFiles(root: Path) -> Tuple[List[Path], int]:
    files: List[Path] = []
    skipped = 0
    if not root.is_dir():
        return files, skipped
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if not (Path(dirpath) / d).is_symlink()
            and not d.startswith(".nvmig-backup-")
        )
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                skipped += 1
                continue
            if any(name.endswith(suffix) for suffix in _TRANSIENT_SUFFIXES):
                continue
            files.append(path)
    return files, skipped


def _snapshotSqlite(src: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / f"{uuid.uuid4().hex}.db"
    try:
        uri = src.resolve().as_uri() + "?mode=ro"
        src_conn = sqlite3.connect(uri, uri=True, timeout=15)
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        return dst
    except sqlite3.DatabaseError:
        shutil.copy2(src, dst)
        return dst


def _trajectorySources(agent_id: str) -> Dict[str, Path]:
    root = get_data_root() / "trajectories"
    found: Dict[str, Path] = {}
    if not root.is_dir():
        return found
    for user_dir in sorted(root.iterdir()):
        candidate = user_dir / agent_id
        if user_dir.is_dir() and candidate.is_dir():
            found[user_dir.name] = candidate
    return found


def export_agent_migration(agent_id: str, package_manifest: Dict[str, Any]) -> MigrationExport:
    """把 agent 根与轨迹打成 zip（SQLite 用 backup API 取一致快照）。"""
    with _MIGRATION_LOCK:
        aid = _validate_agent_id(agent_id, for_import=False)
        root = get_agent_root_dir(aid)
        temp_dir = Path(tempfile.mkdtemp(prefix="nvmig_export_"))
        snap_dir = temp_dir / "snapshots"
        zip_path = temp_dir / f"agent-migration-{aid}.zip"
        files, skipped = _iterAgentFiles(root)
        traj_sources = _trajectorySources(aid)

        agent_bytes = 0
        for path in files:
            try:
                agent_bytes += path.stat().st_size
            except OSError:
                continue
        traj_bytes = 0
        for src in traj_sources.values():
            for path in src.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    traj_bytes += path.stat().st_size
        total_bytes = agent_bytes + traj_bytes
        if total_bytes > MAX_PACKAGE_BYTES:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise MigrationTooLarge(f"迁移包过大：{total_bytes} > {MAX_PACKAGE_BYTES}")

        manifest = {
            "kind": MANIFEST_KIND,
            "manifest_version": MANIFEST_VERSION,
            "agent": package_manifest.get("agent") or {},
            "skills": package_manifest.get("skills") or [],
            "cron": package_manifest.get("cron") or [],
            "mcp": package_manifest.get("mcp") or [],
            "source": {
                "agent_id": aid,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": "neurova",
            },
            "source_paths": {"agent_root": str(root)},
            "trajectory_sources": {user: str(path) for user, path in traj_sources.items()},
            "faces": {
                "agent_root": {"files": len(files), "bytes": agent_bytes},
                "trajectories": {"users": sorted(traj_sources), "bytes": traj_bytes},
            },
            "skipped_symlinks": skipped,
        }

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                for path in files:
                    if _is_sqlite(path):
                        snap = _snapshotSqlite(path, snap_dir)
                        zf.write(snap, f"agent/{path.relative_to(root).as_posix()}")
                    else:
                        zf.write(path, f"agent/{path.relative_to(root).as_posix()}")
                for user, src in traj_sources.items():
                    for path in sorted(src.rglob("*")):
                        if path.is_file() and not path.is_symlink():
                            zf.write(path, f"trajectories/{user}/{path.relative_to(src).as_posix()}")
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(snap_dir, ignore_errors=True)

        return MigrationExport(zip_path=zip_path, temp_dir=temp_dir, manifest=manifest)


def _validateZip(zip_path: Path) -> Dict[str, Any]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise MigrationTooLarge(f"压缩包成员数超上限：{len(infos)} > {MAX_ENTRIES}")
            total = 0
            names = set()
            for info in infos:
                name = info.filename
                if not name or name in names:
                    raise MigrationError(f"压缩包含空/重复成员名：{name!r}")
                names.add(name)
                if name.startswith(("/", "\\")) or ".." in Path(name).parts or "\\" in name:
                    raise MigrationError(f"压缩包含非法成员路径：{name}")
                if info.flag_bits & 0x1:
                    raise MigrationError("不支持加密压缩包")
                total += info.file_size
                if total > MAX_PACKAGE_BYTES:
                    raise MigrationTooLarge(f"压缩包解压后过大：{total} > {MAX_PACKAGE_BYTES}")
            raw = zf.read(MANIFEST_NAME)
    except (zipfile.BadZipFile, KeyError) as e:
        raise MigrationError(f"迁移包损坏或缺少 {MANIFEST_NAME}：{e}") from e
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise MigrationError(f"manifest 不是合法 JSON：{e}") from e
    if not isinstance(manifest, dict) or manifest.get("kind") != MANIFEST_KIND:
        raise MigrationError(f"manifest.kind 必须是 {MANIFEST_KIND}")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise MigrationError(f"manifest_version 必须是 {MANIFEST_VERSION}")
    source = manifest.get("source") or {}
    _validate_agent_id(str(source.get("agent_id") or ""), for_import=False)
    return manifest


def _quoteIdent(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _rewriteSqlite(path: Path, agent_from: str, agent_to: str, importer: str, pathPairs: List[Tuple[str, str]]) -> int:
    if not _is_sqlite(path):
        return 0
    changed = 0
    conn = sqlite3.connect(str(path))
    try:
        tables = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
        for name, sql in tables:
            if name.startswith("sqlite_") or "_fts_" in name:
                continue
            if sql and "VIRTUAL TABLE" in sql.upper():
                continue
            columns = conn.execute(f"PRAGMA table_info({_quoteIdent(name)})").fetchall()
            for column in columns:
                col = column[1]
                lower = col.lower()
                if lower in ("agent_id", "agentid"):
                    cur = conn.execute(
                        f"UPDATE {_quoteIdent(name)} SET {_quoteIdent(col)} = ? WHERE {_quoteIdent(col)} = ?",
                        (agent_to, agent_from),
                    )
                    changed += max(cur.rowcount or 0, 0)
                elif lower in _OWNER_KEYS:
                    cur = conn.execute(
                        f"UPDATE {_quoteIdent(name)} SET {_quoteIdent(col)} = ?",
                        (importer,),
                    )
                    changed += max(cur.rowcount or 0, 0)
            for src, dst in pathPairs:
                for column in columns:
                    col = column[1]
                    decl = str(column[2] or "").upper()
                    if decl and not any(t in decl for t in ("TEXT", "CHAR", "CLOB")):
                        continue
                    cur = conn.execute(
                        f"UPDATE {_quoteIdent(name)} SET {_quoteIdent(col)} = "
                        f"replace({_quoteIdent(col)}, ?, ?) WHERE instr({_quoteIdent(col)}, ?) > 0",
                        (src, dst, src),
                    )
                    changed += max(cur.rowcount or 0, 0)
        conn.commit()
    finally:
        conn.close()
    return changed


def _rewriteJsonValue(value: Any, agent_from: str, agent_to: str, importer: str, pathPairs: List[Tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _AGENT_ID_KEYS and item == agent_from:
                out[key] = agent_to
            elif key in _OWNER_KEYS and isinstance(item, str):
                out[key] = importer
            else:
                out[key] = _rewriteJsonValue(item, agent_from, agent_to, importer, pathPairs)
        return out
    if isinstance(value, list):
        return [_rewriteJsonValue(v, agent_from, agent_to, importer, pathPairs) for v in value]
    if isinstance(value, str):
        for src, dst in pathPairs:
            if src in value:
                value = re.sub(
                    re.escape(src) + r"(?=$|[\\/\"'\s,;:)\]}>])",
                    lambda _m: dst,
                    value,
                )
        return value
    return value


def _rewriteFile(path: Path, agent_from: str, agent_to: str, importer: str, pathPairs: List[Tuple[str, str]]) -> int:
    suffix = path.suffix.lower()
    if suffix in (".db", ".sqlite", ".sqlite3"):
        return _rewriteSqlite(path, agent_from, agent_to, importer, pathPairs)
    if suffix == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return 0
        rewritten = _rewriteJsonValue(data, agent_from, agent_to, importer, pathPairs)
        if rewritten != data:
            tmp = path.with_name(path.name + ".nvmig.tmp")
            tmp.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            return 1
        return 0
    if suffix in (".jsonl", ".ndjson"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return 0
        changed = False
        out = []
        for line in lines:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                out.append(line)
                continue
            rewritten = _rewriteJsonValue(data, agent_from, agent_to, importer, pathPairs)
            changed = changed or rewritten != data
            out.append(json.dumps(rewritten, ensure_ascii=False) if rewritten != data else line)
        if changed:
            tmp = path.with_name(path.name + ".nvmig.tmp")
            tmp.write_text("\n".join(out) + ("\n" if lines else ""), encoding="utf-8")
            tmp.replace(path)
            return 1
    return 0


def prepare_import(
    zip_path: Path,
    target_agent_id: str,
    *,
    overwrite: bool,
    importer: str,
    is_admin: bool,
    import_skills: bool = True,
    import_cron: bool = True,
    import_mcp: bool = False,
) -> PreparedImport:
    """校验、解包、重写归属/ID/路径；不触碰目标目录。"""
    with _MIGRATION_LOCK:
        manifest = _validateZip(zip_path)
        source_id = _validate_agent_id(str((manifest.get("source") or {}).get("agent_id") or ""), for_import=False)
        target_id = _validate_agent_id(target_agent_id or source_id, for_import=True)
        if overwrite and not is_admin:
            raise MigrationForbidden("只有管理员可以覆盖现有 agent")
        importer = str(importer or "").strip()
        if not importer:
            raise MigrationForbidden("导入者身份为空")

        target_root = get_agent_root_dir(target_id)
        target_traj = get_data_root() / "trajectories" / importer / target_id
        from neurova.api.endpoints import get_app_state
        from neurova.agent_config import get_config_manager

        state_agent = ((get_app_state() or {}).get("agents") or {}).get(target_id)
        registry_entry = get_config_manager().get_agent(target_id)
        exists = bool(
            registry_entry
            or state_agent
            or target_root.exists()
            or target_traj.exists()
        )
        if exists and not overwrite:
            raise MigrationConflict(f"Agent '{target_id}' already exists")

        stage_dir = Path(tempfile.mkdtemp(prefix="nvmig_import_"))
        try:
            safe_extract_zip(zip_path, stage_dir)
            if os.name == "nt":
                for base, dest in (
                    (stage_dir / "agent", target_root),
                    (stage_dir / "trajectories", target_traj),
                ):
                    if not base.is_dir():
                        continue
                    for path in base.rglob("*"):
                        if not path.is_file():
                            continue
                        projected = dest / path.relative_to(base)
                        if len(str(projected)) > WINDOWS_MAX_PATH:
                            raise MigrationError(
                                f"目标路径过长（{len(str(projected))} > {WINDOWS_MAX_PATH}）："
                                f"{path.relative_to(base)}。请缩短目标 agent_id 或数据根路径后重试。"
                            )
            source_paths = manifest.get("source_paths") or {}
            traj_sources = manifest.get("trajectory_sources") or {}
            pathPairs: List[Tuple[str, str]] = []
            src_root = str(source_paths.get("agent_root") or "")
            if src_root:
                pathPairs.append((src_root, str(target_root)))
            for user, src in traj_sources.items():
                if src:
                    pathPairs.append((str(src), str(target_traj)))
            pathPairs.sort(key=lambda pair: len(pair[0]), reverse=True)

            for dirpath, dirnames, filenames in os.walk(stage_dir, followlinks=False):
                dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
                for name in filenames:
                    path = Path(dirpath) / name
                    if path == stage_dir / MANIFEST_NAME or path.is_symlink():
                        continue
                    _rewriteFile(path, source_id, target_id, importer, pathPairs)

            config_path = stage_dir / "agent" / "agent_config.json"
            if config_path.is_file():
                try:
                    cfg = json.loads(config_path.read_text(encoding="utf-8"))
                    if isinstance(cfg, dict):
                        cfg["owner_user_id"] = importer
                        config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass

            old_cron: List[Any] = []
            try:
                from neurova.collaborate.workflow.scheduler import get_scheduler

                old_cron = [t for t in get_scheduler().list_tasks() if getattr(t, "agent_id", "") == target_id]
            except Exception as e:  # noqa: BLE001 - cron 面故障不阻断文件导入
                logger.warning("读取旧 cron 任务失败 %s: %s", target_id, e)

            return PreparedImport(
                manifest=manifest,
                source_id=source_id,
                target_id=target_id,
                importer=importer,
                overwrite=overwrite,
                stage_dir=stage_dir,
                target_root=target_root,
                target_trajectory_dir=target_traj,
                source_paths=source_paths,
                trajectory_sources=traj_sources,
                registry_entry=registry_entry,
                import_skills=import_skills,
                import_cron=import_cron,
                import_mcp=import_mcp,
                old_cron_tasks=old_cron,
            )
        except Exception:
            shutil.rmtree(stage_dir, ignore_errors=True)
            raise


def _backupPath(path: Path, token: str) -> Path:
    return path.parent / f".nvmig-backup-{token}" / path.name


def _moveToBackup(path: Path, prepared: PreparedImport) -> None:
    if not path.exists():
        return
    backup = _backupPath(path, prepared.backup_token)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(backup))
    prepared.backup_dirs.append(backup.parent)


def _restoreBackup(prepared: PreparedImport) -> None:
    for backup_parent in prepared.backup_dirs:
        if not backup_parent.is_dir():
            continue
        for child in list(backup_parent.iterdir()):
            target = backup_parent.parent / child.name
            if not target.exists():
                shutil.move(str(child), str(target))
        shutil.rmtree(backup_parent, ignore_errors=True)


def _purgeBackup(prepared: PreparedImport) -> None:
    for backup_parent in prepared.backup_dirs:
        shutil.rmtree(backup_parent, ignore_errors=True)


def _removePath(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _buildAgentConfig(target_id: str, target_root: Path, manifest: Dict[str, Any], importer: str):
    from neurova.agent_core import AgentConfig

    cfg: Dict[str, Any] = {}
    config_path = get_agent_config_path(target_id)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg = raw
    except (OSError, json.JSONDecodeError):
        pass
    agent_face = manifest.get("agent") or {}
    kwargs = dict(
        name=str(cfg.get("name") or agent_face.get("name") or target_id),
        agent_id=target_id,
        workspace_path=str(get_agent_workspace_dir(target_id)),
        llm_model=str(cfg.get("model") or agent_face.get("model") or "gpt-4"),
        llm_provider=str(cfg.get("provider") or agent_face.get("provider") or ""),
        description=str(cfg.get("description") or agent_face.get("description") or ""),
        owner_user_id=importer,
        personality=str(cfg.get("personality") or ""),
        constitution=str(cfg.get("constitution") or ""),
        enable_tts=bool(cfg.get("enable_tts", False)),
        tts_voice=str(cfg.get("tts_voice") or "zh-CN-XiaoxiaoNeural"),
        tts_speed=float(cfg.get("tts_speed", 1.0) or 1.0),
        tts_pitch=float(cfg.get("tts_pitch", 1.0) or 1.0),
    )
    if cfg.get("temperature") is not None:
        kwargs["llm_temperature"] = float(cfg["temperature"])
    return AgentConfig(**kwargs)


def apply_import(prepared: PreparedImport, old_agent_config: Any = None) -> Dict[str, Any]:
    """落盘 + 登记 + 建运行时；失败原路恢复。调用前目标运行时须已 shutdown。"""
    with _MIGRATION_LOCK:
        from neurova.api.endpoints import get_app_state
        from neurova.agent_config import get_config_manager

        state = get_app_state() or {}
        registry = get_config_manager()
        new_agent = None
        try:
            if prepared.overwrite:
                _moveToBackup(prepared.target_root, prepared)
                _moveToBackup(prepared.target_trajectory_dir, prepared)

            staged_root = prepared.stage_dir / "agent"
            if staged_root.is_dir():
                prepared.target_root.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged_root), str(prepared.target_root))
                prepared.placed_root = True

            staged_traj = prepared.stage_dir / "trajectories"
            if staged_traj.is_dir():
                prepared.target_trajectory_dir.mkdir(parents=True, exist_ok=True)
                for user_dir in sorted(staged_traj.iterdir()):
                    if user_dir.is_dir():
                        for child in sorted(user_dir.iterdir()):
                            dst = prepared.target_trajectory_dir / child.name
                            if dst.exists():
                                shutil.rmtree(dst, ignore_errors=True)
                            shutil.move(str(child), str(dst))
                prepared.placed_trajectory = True

            if prepared.registry_entry is not None:
                registry.delete_agent(prepared.target_id)

            agent_face = prepared.manifest.get("agent") or {}
            config_path = get_agent_config_path(prepared.target_id)
            if not config_path.is_file():
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_text(
                    json.dumps(
                        {
                            "name": str(agent_face.get("name") or prepared.target_id),
                            "description": str(agent_face.get("description") or ""),
                            "model": str(agent_face.get("model") or "gpt-4"),
                            "provider": str(agent_face.get("provider") or ""),
                            "personality": str(agent_face.get("personality") or ""),
                            "constitution": str(agent_face.get("constitution") or ""),
                            "owner_user_id": prepared.importer,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            registry.create_agent(
                agent_id=prepared.target_id,
                name=str(agent_face.get("name") or prepared.target_id),
                description=str(agent_face.get("description") or ""),
                config={
                    "model": str(agent_face.get("model") or ""),
                    "provider": str(agent_face.get("provider") or ""),
                },
                owner_user_id=prepared.importer,
            )

            # 旧 cron 在覆盖场景下先移除；新任务由清单面登记，回滚时一并处理。
            if prepared.old_cron_tasks:
                from neurova.collaborate.workflow.scheduler import get_scheduler

                scheduler = get_scheduler()
                for task in prepared.old_cron_tasks:
                    scheduler.remove_task(task.task_id)

            from neurova.api.endpoints.agent_package import applyManifestFaces

            imported = applyManifestFaces(
                prepared.target_id,
                prepared.manifest,
                import_skills=prepared.import_skills,
                import_cron=prepared.import_cron,
                import_mcp=prepared.import_mcp,
                created_cron_tasks=prepared.created_cron_tasks,
            )

            from neurova.agent_core import Agent

            config = _buildAgentConfig(
                prepared.target_id,
                prepared.target_root,
                prepared.manifest,
                prepared.importer,
            )
            new_agent = Agent(config=config)
            state.setdefault("agents", {})[prepared.target_id] = new_agent
            prepared.applied = True
            return {
                "success": True,
                "agent_id": prepared.target_id,
                "source_agent_id": prepared.source_id,
                "overwritten": prepared.overwrite,
                "owner_user_id": prepared.importer,
                "imported": imported,
                "manifest_version": MANIFEST_VERSION,
            }
        except Exception as e:
            logger.error("agent 迁移包导入失败 %s: %s", prepared.target_id, e, exc_info=True)
            if new_agent is not None:
                try:
                    state.get("agents", {}).pop(prepared.target_id, None)
                except Exception:
                    pass
            if prepared.placed_root:
                _removePath(prepared.target_root)
            if prepared.placed_trajectory:
                _removePath(prepared.target_trajectory_dir)
            try:
                registry.delete_agent(prepared.target_id)
            except Exception:
                pass
            if prepared.registry_entry is not None:
                try:
                    registry.create_agent(
                        agent_id=prepared.target_id,
                        name=str(prepared.registry_entry.get("name") or prepared.target_id),
                        description=str(prepared.registry_entry.get("description") or ""),
                        config=prepared.registry_entry.get("config") or {},
                        owner_user_id=prepared.registry_entry.get("owner_user_id"),
                    )
                except Exception:
                    pass
            _restoreBackup(prepared)
            try:
                from neurova.collaborate.workflow.scheduler import get_scheduler

                scheduler = get_scheduler()
                for task in prepared.created_cron_tasks:
                    task_id = getattr(task, "task_id", "")
                    if task_id:
                        scheduler.remove_task(task_id)
                for task in prepared.old_cron_tasks:
                    scheduler.add_task(task)
            except Exception:
                pass
            if old_agent_config is not None:
                try:
                    from neurova.agent_core import Agent

                    state.setdefault("agents", {})[prepared.target_id] = Agent(config=old_agent_config)
                except Exception:
                    logger.warning("回滚后重建旧 agent 运行时失败：%s", prepared.target_id)
            raise


def finalize_import(prepared: PreparedImport) -> None:
    _purgeBackup(prepared)
    shutil.rmtree(prepared.stage_dir, ignore_errors=True)


def discard_prepared(prepared: PreparedImport) -> None:
    if prepared.applied:
        return
    _purgeBackup(prepared)
    shutil.rmtree(prepared.stage_dir, ignore_errors=True)
