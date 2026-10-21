# -*- coding: utf-8 -*-
"""旧 agent 扁平落点 → `data/<agent_id>/` 统一布局的一次性迁移。

旧布局（v1）的 agent 私有面散在至少十处：

    agent_workspaces/<id>/                 # 工作区（memory、附件、图谱、配置）
    data/sessions/<id>/                    # 会话
    data/agents/<id>/{skills,proposals,evolution}
    data/agents/souls/<id>/soul.json
    data/personality/<id>.json
    data/sleep_settings/<id>.json
    data/media_config/<id>.json
    data/seen-cursors/agents/<id>.json
    data/context_ledger/<id>.db
    data/checkpoints/<id>.git
    data/evolution/evidence/<id>/

v2 目标布局见 `core/agent_workspaces.py`。本模块只做搬迁，不改任何业务语义：

- **不覆盖**：新旧同名物同时存在时保留双方并写入冲突报告；
- **幂等**：搬完即源消失，第二次执行不再产生移动；
- **dry-run**：只计算计划，不写盘；
- **不跟随符号链接**：链接本身按冲突处理，避免把外部目录搬进来。

启动时在加载 agent 之前调用 `migrate_legacy_agent_layout()`；运维可用
`scripts/agent_layout_migration.py` 先 dry-run 再 apply。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from neurova.core.agent_workspaces import (
    _resolve_agent_id,
    get_agent_evolution_dir,
    get_agent_root,
    get_agent_root_dir,
    is_agent_root,
    is_reserved_agent_id,
)
from neurova.core.data_root import get_data_root, repoRoot
from neurova.core.logger import get_logger

logger = get_logger(__name__)

REPORT_NAME = "agent_layout_migration.json"
_MIGRATION_LOCK = threading.RLock()


@dataclass
class _MigrationReport:
    dry_run: bool
    started_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    finished_at: str = ""
    moved: List[Dict[str, str]] = field(default_factory=list)
    conflicts: List[Dict[str, str]] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    skipped: List[Dict[str, str]] = field(default_factory=list)
    rewrites: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "moved_count": len(self.moved),
            "conflict_count": len(self.conflicts),
            "error_count": len(self.errors),
            "skipped_count": len(self.skipped),
            "rewrites": self.rewrites,
            "moved": self.moved,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "skipped": self.skipped,
        }


def _record_move(report: _MigrationReport, src: Path, dst: Path, label: str) -> None:
    report.moved.append({"source": str(src), "target": str(dst), "label": label})


def _record_conflict(report: _MigrationReport, src: Path, dst: Path, label: str, reason: str) -> None:
    report.conflicts.append(
        {"source": str(src), "target": str(dst), "label": label, "reason": reason}
    )


def _merge_move(src: Path, dst: Path, report: _MigrationReport, label: str) -> None:
    """把 src 搬到 dst；dst 已存在时只并入缺失的子项，绝不覆盖。"""
    try:
        if not src.exists() and not src.is_symlink():
            return
        if src.is_symlink():
            _record_conflict(report, src, dst, label, "symbolic link is not migrated")
            return
        if src.resolve() == dst.resolve():
            return
        if not dst.exists():
            _record_move(report, src, dst, label)
            if report.dry_run:
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return
        if src.is_dir() and dst.is_dir():
            for child in sorted(src.iterdir()):
                _merge_move(child, dst / child.name, report, label)
            if not report.dry_run:
                _prune_empty_dir(src)
            return
        _record_conflict(report, src, dst, label, "target already exists")
    except Exception as e:  # noqa: BLE001 - 单个面失败不阻断其余面搬迁
        report.errors.append(
            {"source": str(src), "target": str(dst), "label": label, "error": f"{type(e).__name__}: {e}"}
        )
        logger.error("agent 布局迁移失败 %s → %s: %s", src, dst, e)


def _prune_empty_dir(path: Path) -> None:
    try:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except OSError:
        pass


def _discover_agent_ids(
    data_root: Path,
    legacy_workspace_root: Optional[Path],
    sessions_root: Path,
) -> List[str]:
    found: set = set()

    def add(value: str) -> None:
        try:
            found.add(_resolve_agent_id(value))
        except ValueError:
            return

    if legacy_workspace_root is not None and legacy_workspace_root.is_dir():
        for child in legacy_workspace_root.iterdir():
            if child.is_dir():
                add(child.name)

    if sessions_root.is_dir():
        for child in sessions_root.iterdir():
            if child.is_dir():
                add(child.name)

    agents_root = data_root / "agents"
    if agents_root.is_dir():
        for child in agents_root.iterdir():
            if child.is_dir() and child.name != "souls":
                add(child.name)

    for pattern in (
        "personality/*.json",
        "sleep_settings/*.json",
        "media_config/*.json",
        "seen-cursors/agents/*.json",
        "context_ledger/*.db",
        "checkpoints/*.git",
        "evolution/evidence/*",
    ):
        for path in data_root.glob(pattern):
            if path.name.endswith(".git"):
                add(path.name[:-4])
            else:
                add(path.stem)

    registry = agents_root / "agents.json"
    try:
        raw = json.loads(registry.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for agent_id in raw:
                add(str(agent_id))
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    for parent in {get_agent_root(), data_root}:
        if parent.is_dir():
            for child in parent.iterdir():
                if is_agent_root(child):
                    add(child.name)

    return sorted(found)


def _default_legacy_workspace_root() -> Optional[Path]:
    """生产旧工作区根；测试/隔离部署注入了 agent 根时不动仓库里的真实旧物。"""
    if (os.environ.get("NEUROVA_AGENT_WORKSPACES_DIR") or "").strip():
        return None
    return repoRoot() / "agent_workspaces"


def _default_sessions_root(data_root: Path) -> Path:
    injected = (os.environ.get("NEUROVA_SESSIONS_DIR") or "").strip()
    return Path(injected) if injected else data_root / "sessions"


def _registry_agent_ids(data_root: Path) -> set:
    try:
        raw = json.loads((data_root / "agents" / "agents.json").read_text(encoding="utf-8"))
        return set(raw) if isinstance(raw, dict) else set()
    except (OSError, ValueError, json.JSONDecodeError):
        return set()


def _is_real_agent(
    agent_id: str,
    data_root: Path,
    legacy_workspace_root: Optional[Path],
    sessions_root: Path,
    registry_ids: set,
) -> bool:
    """只认有归属证据的 agent；孤立的游标/人格/检查点文件不立新根（防幽灵）。"""
    if agent_id in registry_ids:
        return True
    if legacy_workspace_root is not None and (legacy_workspace_root / agent_id).is_dir():
        return True
    if (sessions_root / agent_id).is_dir():
        return True
    if (data_root / "agents" / agent_id).is_dir():
        return True
    root = get_agent_root_dir(agent_id)
    return any(
        (root / marker).exists()
        for marker in ("agent_config.json", "workspaces", "memory", "sessions")
    )


def _migrate_workspace(legacy_ws: Path, root: Path, report: _MigrationReport, agent_id: str) -> None:
    if not legacy_ws.is_dir():
        return
    _merge_move(legacy_ws / "agent_config.json", root / "agent_config.json", report, f"{agent_id}:config")
    _merge_move(legacy_ws / "memory", root / "memory", report, f"{agent_id}:memory")

    # 身份文件属于配置，不随记忆目录；旧布局把它们放在 memory/ 下。
    memory_dir = root / "memory"
    for name in ("soul.md", "personality.md"):
        _merge_move(memory_dir / name, root / name, report, f"{agent_id}:identity:{name}")

    for child in sorted(legacy_ws.iterdir()):
        if child.name in ("agent_config.json", "memory"):
            continue
        _merge_move(child, root / "workspaces" / child.name, report, f"{agent_id}:workspace:{child.name}")
    if not report.dry_run:
        _prune_empty_dir(legacy_ws)


def _migrate_agent_library(agent_id: str, data_root: Path, root: Path, report: _MigrationReport) -> None:
    library = data_root / "agents" / agent_id
    if library.is_dir():
        for child in sorted(library.iterdir()):
            _merge_move(child, root / child.name, report, f"{agent_id}:library:{child.name}")
        if not report.dry_run:
            _prune_empty_dir(library)

    soul_dir = data_root / "agents" / "souls" / agent_id
    _merge_move(soul_dir / "soul.json", root / "soul.json", report, f"{agent_id}:soul")
    if not report.dry_run:
        _prune_empty_dir(soul_dir)


_PATH_BOUNDARY = r"(?=$|[\\/\"'\s,;:)\]}>])"


def _pathPairs(agent_id: str, legacy_ws_root: Optional[Path], data_root: Path, root: Path) -> List[tuple]:
    """旧绝对路径 → 新绝对路径（长前缀优先，避免 memory 被 workspace 泛映射吞掉）。"""
    pairs: List[tuple] = []
    if legacy_ws_root is not None:
        old_ws = legacy_ws_root / agent_id
        pairs.extend(
            [
                (str(old_ws / "agent_config.json"), str(root / "agent_config.json")),
                (str(old_ws / "memory"), str(root / "memory")),
                (str(old_ws), str(root / "workspaces")),
            ]
        )
    pairs.extend(
        [
            (str(data_root / "sessions" / agent_id), str(root / "sessions")),
            (str(data_root / "agents" / agent_id), str(root)),
            (str(data_root / "agents" / "souls" / agent_id / "soul.json"), str(root / "soul.json")),
            (str(data_root / "personality" / f"{agent_id}.json"), str(root / "personality.json")),
            (str(data_root / "sleep_settings" / f"{agent_id}.json"), str(root / "sleep_settings.json")),
            (str(data_root / "media_config" / f"{agent_id}.json"), str(root / "media_config.json")),
            (
                str(data_root / "seen-cursors" / "agents" / f"{agent_id}.json"),
                str(root / "seen_cursors.json"),
            ),
            (str(data_root / "context_ledger" / f"{agent_id}.db"), str(root / "context_ledger.db")),
            (
                str(data_root / "context_ledger" / f"{agent_id}.db-wal"),
                str(root / "context_ledger.db-wal"),
            ),
            (
                str(data_root / "context_ledger" / f"{agent_id}.db-shm"),
                str(root / "context_ledger.db-shm"),
            ),
            (str(data_root / "checkpoints" / f"{agent_id}.git"), str(root / "checkpoints.git")),
            (
                str(data_root / "evolution" / "evidence" / agent_id),
                str(root / "evolution" / "evidence"),
            ),
        ]
    )

    expanded: List[tuple] = []
    seen = set()
    for src, dst in pairs:
        if not src or src == dst:
            continue
        for s, d in (
            (src, dst),
            (src.replace("\\", "/"), dst.replace("\\", "/")),
            (src.replace("/", "\\"), dst.replace("/", "\\")),
        ):
            if s and s != d and (s, d) not in seen:
                seen.add((s, d))
                expanded.append((s, d))
    expanded.sort(key=lambda pair: len(pair[0]), reverse=True)
    return expanded


def _replacePathString(value: str, pairs: List[tuple]) -> str:
    for src, dst in pairs:
        if src in value:
            value = re.sub(re.escape(src) + _PATH_BOUNDARY, lambda _m: dst, value)
    return value


def _rewriteJsonValue(value: Any, pairs: List[tuple]) -> Any:
    if isinstance(value, dict):
        return {k: _rewriteJsonValue(v, pairs) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewriteJsonValue(v, pairs) for v in value]
    if isinstance(value, str):
        return _replacePathString(value, pairs)
    return value


def _rewriteJsonFile(path: Path, pairs: List[tuple]) -> bool:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    rewritten = _rewriteJsonValue(data, pairs)
    if rewritten == data:
        return False
    tmp = path.with_name(path.name + ".nvmig.tmp")
    tmp.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return True


def _rewriteJsonLinesFile(path: Path, pairs: List[tuple]) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    changed = False
    out: List[str] = []
    for line in lines:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        rewritten = _rewriteJsonValue(data, pairs)
        if rewritten != data:
            changed = True
            out.append(json.dumps(rewritten, ensure_ascii=False))
        else:
            out.append(line)
    if not changed:
        return False
    tmp = path.with_name(path.name + ".nvmig.tmp")
    tmp.write_text("\n".join(out) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(path)
    return True


def _quoteIdent(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _rewriteSqliteFile(path: Path, pairs: List[tuple], report: _MigrationReport, label: str) -> int:
    try:
        with open(path, "rb") as f:
            if f.read(16) != b"SQLite format 3\x00":
                return 0
    except OSError:
        return 0
    changed = 0
    try:
        conn = sqlite3.connect(str(path))
        try:
            tables = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            ).fetchall()
            for name, sql in tables:
                if name.startswith("sqlite_") or "_fts_" in name:
                    continue
                if sql and "VIRTUAL TABLE" in sql.upper():
                    continue
                columns = conn.execute(f"PRAGMA table_info({_quoteIdent(name)})").fetchall()
                for column in columns:
                    col_name = column[1]
                    decl = str(column[2] or "").upper()
                    if decl and not any(token in decl for token in ("TEXT", "CHAR", "CLOB")):
                        continue
                    for src, dst in pairs:
                        cur = conn.execute(
                            f"UPDATE {_quoteIdent(name)} SET {_quoteIdent(col_name)} = "
                            f"replace({_quoteIdent(col_name)}, ?, ?) "
                            f"WHERE instr({_quoteIdent(col_name)}, ?) > 0",
                            (src, dst, src),
                        )
                        changed += max(cur.rowcount or 0, 0)
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        report.errors.append({"source": str(path), "target": "", "label": label, "error": f"sqlite: {e}"})
        return 0
    return changed


def _rewriteAgentPaths(
    agent_id: str,
    legacy_ws_root: Optional[Path],
    data_root: Path,
    root: Path,
    report: _MigrationReport,
) -> None:
    if report.dry_run or not root.is_dir():
        return
    pairs = _pathPairs(agent_id, legacy_ws_root, data_root, root)
    if not pairs:
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not (Path(dirpath) / d).is_symlink())
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            suffix = path.suffix.lower()
            try:
                if suffix in (".db", ".sqlite", ".sqlite3"):
                    report.rewrites += _rewriteSqliteFile(path, pairs, report, f"{agent_id}:rewrite:{name}")
                elif suffix in (".json",):
                    report.rewrites += int(_rewriteJsonFile(path, pairs))
                elif suffix in (".jsonl", ".ndjson"):
                    report.rewrites += int(_rewriteJsonLinesFile(path, pairs))
            except OSError as e:
                report.errors.append(
                    {"source": str(path), "target": "", "label": f"{agent_id}:rewrite", "error": str(e)}
                )


def _migrate_agent(
    agent_id: str,
    data_root: Path,
    legacy_workspace_root: Optional[Path],
    sessions_root: Path,
    report: _MigrationReport,
) -> None:
    root = get_agent_root_dir(agent_id)
    if report.dry_run:
        # dry-run 不建目录；_merge_move 只用目标是否存在来判定冲突。
        pass
    else:
        root.mkdir(parents=True, exist_ok=True)

    if legacy_workspace_root is not None:
        _migrate_workspace(legacy_workspace_root / agent_id, root, report, agent_id)

    _merge_move(sessions_root / agent_id, root / "sessions", report, f"{agent_id}:sessions")
    _migrate_agent_library(agent_id, data_root, root, report)

    file_faces = (
        (data_root / "personality" / f"{agent_id}.json", root / "personality.json", "personality"),
        (data_root / "sleep_settings" / f"{agent_id}.json", root / "sleep_settings.json", "sleep_settings"),
        (data_root / "media_config" / f"{agent_id}.json", root / "media_config.json", "media_config"),
        (data_root / "seen-cursors" / "agents" / f"{agent_id}.json", root / "seen_cursors.json", "seen_cursors"),
        (data_root / "checkpoints" / f"{agent_id}.git", root / "checkpoints.git", "checkpoints"),
        (data_root / "evolution" / "evidence" / agent_id, get_agent_evolution_dir(agent_id) / "evidence", "evolution_evidence"),
    )
    for src, dst, label in file_faces:
        _merge_move(src, dst, report, f"{agent_id}:{label}")

    for suffix in ("", "-wal", "-shm"):
        _merge_move(
            data_root / "context_ledger" / f"{agent_id}.db{suffix}",
            root / f"context_ledger.db{suffix}",
            report,
            f"{agent_id}:context_ledger{suffix}",
        )

    _rewriteAgentPaths(agent_id, legacy_workspace_root, data_root, root, report)


def _cleanup_legacy_roots(legacy_workspace_root: Optional[Path], sessions_root: Path, data_root: Path) -> None:
    if legacy_workspace_root is not None:
        _prune_empty_dir(legacy_workspace_root)
    _prune_empty_dir(sessions_root)
    _prune_empty_dir(data_root / "agents" / "souls")
    _prune_empty_dir(data_root / "agents")


def _write_report(data_root: Path, report: _MigrationReport) -> Optional[Path]:
    if report.dry_run:
        return None
    if not (report.moved or report.conflicts or report.errors):
        return None
    target = data_root / REPORT_NAME
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target
    except OSError as e:
        logger.error("写入 agent 布局迁移报告失败 %s: %s", target, e)
        return None


def auto_migrate_legacy_agent_layout() -> Dict[str, Any]:
    """启动期自动迁移：只在"本进程的数据根就是仓库 data/"时动手。

    数据根被显式注入到别处（测试临时根、取证隔离根、桌面部署自定义根）时，
    仓库里的 `agent_workspaces/` 不属于这个进程——搬它就是把操作者的真实数据
    搬进一个临时目录。与 `data_root.homeAdoptionAllowed()` 同一道闸、同一理由。
    """
    injected = (os.environ.get("NEUROVA_DATA_DIR") or "").strip()
    if injected:
        try:
            root = get_data_root()
        except ValueError as e:
            logger.warning("数据根注入非法，跳过 agent 布局自动迁移：%s", e)
            return {"skipped": "invalid_data_root"}
        if root.resolve() != (repoRoot() / "data").resolve():
            logger.warning(
                "数据根已被注入到 %s（非仓库 data/），跳过自动迁移；"
                "需要迁移请显式运行 scripts/agent_layout_migration.py --legacy-workspace-root <旧根> --apply",
                root,
            )
            return {"skipped": "injected_data_root"}
    return migrate_legacy_agent_layout()


def migrate_legacy_agent_layout(
    *,
    legacy_workspace_root: Optional[Path | str] = None,
    sessions_root: Optional[Path | str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """把旧布局搬进 `data/<agent_id>/`。

    Args:
        legacy_workspace_root: 旧工作区根（缺省为仓库 `agent_workspaces/`）；
            测试/隔离部署显式传入，避免误动仓库真实旧物。
        sessions_root: 旧会话根（缺省 `data/sessions/`，或 `NEUROVA_SESSIONS_DIR`）。
        dry_run: 只计算计划，不落盘。

    Returns:
        迁移报告：`moved` / `conflicts` / `errors` / `dry_run` / 时间戳。
    """
    with _MIGRATION_LOCK:
        data_root = get_data_root()
        legacy_root = (
            Path(legacy_workspace_root)
            if legacy_workspace_root is not None
            else _default_legacy_workspace_root()
        )
        legacy_sessions = (
            Path(sessions_root) if sessions_root is not None else _default_sessions_root(data_root)
        )
        report = _MigrationReport(dry_run=dry_run)

        if not data_root.is_dir() and not dry_run:
            data_root.mkdir(parents=True, exist_ok=True)

        agent_ids = _discover_agent_ids(data_root, legacy_root, legacy_sessions)
        registry_ids = _registry_agent_ids(data_root)
        for agent_id in agent_ids:
            if is_reserved_agent_id(agent_id):
                continue
            if not _is_real_agent(agent_id, data_root, legacy_root, legacy_sessions, registry_ids):
                report.skipped.append({"agent_id": agent_id, "reason": "no agent ownership evidence"})
                continue
            _migrate_agent(agent_id, data_root, legacy_root, legacy_sessions, report)

        if not dry_run:
            _cleanup_legacy_roots(legacy_root, legacy_sessions, data_root)
        report.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report_path = _write_report(data_root, report)
        result = report.as_dict()
        if report_path is not None:
            result["report_path"] = str(report_path)

        if report.moved or report.conflicts or report.errors:
            logger.info(
                "agent 布局迁移完成：moved=%d conflicts=%d errors=%d dry_run=%s",
                len(report.moved), len(report.conflicts), len(report.errors), dry_run,
            )
            for conflict in report.conflicts[:10]:
                logger.warning("agent 布局迁移冲突：%s", conflict)
        return result
