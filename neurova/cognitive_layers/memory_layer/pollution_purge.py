"""记忆库历史污染清空：按**正证据**判定，先归档再删，默认只预报不落手。

病灶（2026-09-21 审计 §7 / B-12 / Issue #75）：仓库根 `neurova_memories_persist.db`
攒了 71,831 行，`agent_id` 含 `test` 或为 `engine_it_*` 的占 71,378（99.369%）——
成因是 `MemoryManager` 曾以裸文件名 `neurova_memory.db` 当默认值，persist 库随进程
CWD 散落。围栏（`storage_fence.assertNotUnderProductionMemory`）已堵住**新增**，
但存量那份与散落副本仍在盘上，读数每次都要绕过它才可信。

本模块把"清空"做成可重复执行、可回退、可复核的动作，判据只有两条，都必须是正证据：

1. **位置证据**：库文件落在合法根（agent 工作区根 / `data` 根）之外 ⇒ 它是散落物。
   与 `storage_fence` 同一条纪律——合法根是磁盘上那个事实，不是进程的 CWD。
2. **身份证据**：行上的 `agent_id` 命中测试/基准命名（`test_agent_*` / `test_*` /
   `engine_it_*`）。**不做模糊匹配、不做比例判断**：不命中的行一律保留（真实用户
   工作区里 `default` / `kai` / `verify-agent` 等 453 行因此在清空后原样存活）。

三条硬约束，防止这套工具自己变成新的污染源：

- **默认预报**：`plan()` 只读、`apply(dryRun=True)` 是默认值，落手必须显式。
- **先归档**：删除前把整库（含 `-wal` / `-shm`）副本存成 `.pre-purge-<stamp>`，
  把归档副本改回原名即可回退。
- **生产工作区不可脚本化删除**：目标落在 agent 工作区根下时当场失败——
  清空历史污染不许连带删掉真实 agent 的记忆。
"""

from __future__ import annotations

import datetime
import fnmatch
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from neurova.core.logger import get_logger
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

# 散落物判定的两个法定库名：裸文件名默认值留下的就是这两个（persist 与主库）。
LEGACY_DB_NAMES = ("neurova_memories_persist.db", "neurova_memory.db")

# 污染身份的唯一事实源（2026-09-21 审计 §7 的实测口径）。
# 只认这三种命名，且一律整段匹配：`test_*` 里的 `*` 由 fnmatch 承担，
# 不做子串包含判断（否则真实用户名里带 "test" 的会被误删）。
TEST_AGENT_PATTERNS = ("test_agent_*", "test_*", "engine_it_*")

# 第三类散落物：只 `mkdir` 出来、一个文件都没有的空壳目录（审计 §7 实测 0 文件）。
EMPTY_SHELL_DIR_NAMES = ("memory_storage", "memory_layer", "memory_pending")

# 单个库判为"纯散落物"的提前退出阈值：行级扫描对百万行库不便宜，
# 但判据不看比例，只看"有没有一条不命中"——所以先做完身份扫描再下结论。
_SAMPLE_IDS = 12


def dataRoot() -> Path:
    """`data` 根：与各存储默认落点同源（`NEUROVA_DATA_DIR` 可注入）。"""

    return get_data_root()


def workspaceRoot() -> Path:
    """agent 工作区根：与写入端同源（`NEUROVA_AGENT_WORKSPACES_DIR` 可注入）。

    **刻意不走 `storage_fence.productionMemoryDir()`**：两者回答的是不同问题。

    - 围栏问"这在真实生产目录里吗"——必须由磁盘事实决定，不许被进程配置骗过，
      所以它对注入视而不见；
    - 本工具问"按当前配置，哪块地是合法的"——必须认注入，否则在隔离目录/CI 上
      它会把全部合法数据判成散落物，那是"围栏把每条用例都判红"的同一种错。
    """
    from neurova.core.agent_workspaces import get_agent_workspaces_root

    return get_agent_workspaces_root()


def legalRoots() -> List[Path]:
    """合法根的穷举：真实数据只会落在这两处之下，其余位置的文件都是散落物。"""
    return [workspaceRoot().resolve(), dataRoot().resolve()]


def isTestAgentId(agentId: str) -> bool:
    """行是否属于测试/基准残留。整段 glob 匹配，不做子串包含。"""
    value = str(agentId or "")
    if not value:
        return False
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in TEST_AGENT_PATTERNS)


def isStrayPath(path: Path) -> bool:
    """位置证据：库文件不在任何合法根之内 ⇒ 散落物。

    合法根两处：agent 工作区根（真实用户数据）与 `data` 根（生产数据目录）。
    两者都在仓库内但彼此不重叠；散落物恰恰落在它们的**外面**（仓库根、
    `neurova/memory/data/`、`test_workspace/` …）。
    """
    target = Path(path).resolve()
    for root in legalRoots():
        if target == root or root in target.parents:
            return False
    return True


@dataclass
class ResidueRows:
    """一个库里的残留行账（按 pattern 计数 + 抽样 id）。"""

    total: int = 0
    matched: int = 0
    byPattern: Dict[str, int] = field(default_factory=dict)
    sampleIds: List[str] = field(default_factory=list)

    @property
    def kept(self) -> int:
        return self.total - self.matched

    def asDict(self) -> Dict[str, Any]:
        return {"total": self.total, "matched": self.matched,
                "kept": self.kept, "by_pattern": dict(self.byPattern),
                "sample_ids": list(self.sampleIds)}


@dataclass
class StrayFinding:
    """一条散落物（位置证据）＋它在库里的残留行账（身份证据）。"""

    path: Path
    reason: str
    bytes: int = 0
    rows: ResidueRows = field(default_factory=ResidueRows)
    sidecars: Tuple[Path, ...] = ()

    def asDict(self) -> Dict[str, Any]:
        return {"path": str(self.path), "reason": self.reason, "bytes": self.bytes,
                "rows": self.rows.asDict(),
                "sidecars": [str(p) for p in self.sidecars]}


class MemoryPollutionPurge:
    """按正证据清空记忆库历史污染。"""

    def __init__(self, roots: Optional[Sequence[Path]] = None,
                 archiveDir: Optional[Path] = None) -> None:
        self._roots = [Path(r) for r in roots] if roots else self._defaultRoots()
        self._archiveDir = Path(archiveDir) if archiveDir else None

    # ── 候选扫描 ──────────────────────────────────────────────

    @staticmethod
    def _defaultRoots() -> List[Path]:
        """默认扫描面：仓库根（不递归进任何合法根）。"""
        repo = Path(__file__).resolve().parents[3]
        return [repo]

    def _candidates(self) -> List[Path]:
        """命中法定库名的文件；合法根之外的才算散落物，合法根内的留作行级清空。

        合法根内不做递归（那是真实数据所在），只在 `data` 根顶层的散落副本
        （审计实测 `data/neurova_memories_persist.db` 0 行）也纳入。
        """
        found: List[Path] = []
        seen = set()
        for root in self._roots:
            for name in LEGACY_DB_NAMES:
                for path in root.rglob(name):
                    if not path.is_file():
                        continue
                    resolved = path.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    found.append(path)
        return sorted(found)

    # ── 计划（只读）───────────────────────────────────────────

    def plan(self) -> Dict[str, Any]:
        """只读预报：列出散落物、残留行账、空壳目录。不写任何东西。"""
        strays: List[StrayFinding] = []
        for path in self._candidates():
            finding = self._inspect(path)
            # 合法根内且没有任何残留行 ⇒ 不是本次处置对象（真实数据不在此列）
            if not isStrayPath(path) and finding.rows.matched == 0:
                continue
            strays.append(finding)
        shells = self._emptyShells()
        return {
            "mode": "dry_run",
            "roots": [str(r) for r in self._roots],
            "legal_roots": [str(r) for r in legalRoots()],
            "strays": [f.asDict() for f in strays],
            "empty_shell_dirs": [str(p) for p in shells],
            "residue_rows": sum(f.rows.matched for f in strays),
            "bytes": sum(f.bytes for f in strays),
        }

    def _inspect(self, path: Path) -> StrayFinding:
        rows = self._scanRows(path)
        sidecars = tuple(
            path.with_name(path.name + suffix) for suffix in ("-wal", "-shm")
            if path.with_name(path.name + suffix).exists()
        )
        reason = ("合法根之外的散落副本" if isStrayPath(path) else "合法根内的测试残留行")
        return StrayFinding(path=path, reason=reason,
                            bytes=path.stat().st_size if path.exists() else 0,
                            rows=rows, sidecars=sidecars)

    @staticmethod
    def _scanRows(path: Path) -> ResidueRows:
        """按身份证据扫行。表结构不认识（不是记忆库）时如实报 0 而不是猜。"""
        out = ResidueRows()
        try:
            conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=3.0)
        except sqlite3.Error:
            return out
        try:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
            if "agent_id" not in columns:
                return out
            for (agentId,) in conn.execute("SELECT agent_id FROM memories").fetchall():
                out.total += 1
                value = str(agentId or "")
                hit = next((p for p in TEST_AGENT_PATTERNS
                            if fnmatch.fnmatchcase(value, p)), None)
                if hit is None:
                    continue
                out.matched += 1
                out.byPattern[hit] = out.byPattern.get(hit, 0) + 1
                if len(out.sampleIds) < _SAMPLE_IDS:
                    out.sampleIds.append(value)
        except sqlite3.Error as exc:  # noqa: BLE001 — 损坏/非 SQLite 文件如实记账
            logger.warning("清空扫描跳过 %s：%s", path, exc)
        finally:
            conn.close()
        return out

    def _emptyShells(self) -> List[Path]:
        shells: List[Path] = []
        for root in self._roots:
            for name in EMPTY_SHELL_DIR_NAMES:
                for path in root.rglob(name):
                    if path.is_dir() and not any(path.iterdir()):
                        shells.append(path)
        return sorted(shells)

    # ── 落手 ──────────────────────────────────────────────────

    def apply(self, dryRun: bool = True) -> Dict[str, Any]:
        """执行清空：先归档整库（含 sidecar）再删；`dryRun=True` 时只回计划。"""
        if dryRun:
            return self.plan()
        self._refuseWorkspaceTargets()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        plan = self.plan()
        actions: List[Dict[str, Any]] = []
        for item in plan["strays"]:
            path = Path(item["path"])
            finding = self._inspect(path)
            if finding.rows.matched == 0 and finding.rows.total > 0:
                actions.append({"path": str(path), "action": "kept",
                                "reason": "库内无残留行，且位于合法根内"})
                continue
            if finding.rows.total > 0 and finding.rows.kept > 0:
                actions.append(self._purgeRows(path, finding, stamp))
            else:
                actions.append(self._purgeFile(path, finding, stamp))
        removedShells = [str(p) for p in self._emptyShells()]
        for raw in removedShells:
            Path(raw).rmdir()
        # 落手报告与预报用**同一组表头字段**：读的人不该因为模式不同而看不到
        # "扫的是哪些根、合法根是谁"——审计留痕两份报告要能并列比较。
        return {"mode": "apply", "stamp": stamp,
                "roots": plan["roots"], "legal_roots": plan["legal_roots"],
                "actions": actions,
                "removed_empty_shell_dirs": removedShells,
                "residue_rows_removed": sum(
                    a.get("rows_removed", 0) for a in actions),
                "files_removed": sum(1 for a in actions if a["action"] == "removed")}

    def _refuseWorkspaceTargets(self) -> None:
        """工作区里的库一律不许整库删：那底下放的是真实 agent 的记忆。

        只拒**工作区**根，不拒 `data` 根——`data` 下的散落副本（审计实测 0 行）
        与仓库根的散落库是同一件事，都该清掉。
        """
        root = workspaceRoot().resolve()
        for path in self._candidates():
            resolved = path.resolve()
            if resolved == root or root in resolved.parents:
                raise RuntimeError(
                    "清空目标落在 agent 工作区内（%s）——历史污染清空不得连带删真实"
                    " agent 的记忆。要处置它请先把它移出工作区。" % path)

    def _archive(self, path: Path, stamp: str) -> Tuple[Path, List[Path]]:
        if self._archiveDir is not None:
            self._archiveDir.mkdir(parents=True, exist_ok=True)
            target = self._archiveDir / path.name
            index = 1
            while target.exists():
                target = self._archiveDir / ("%s.%d" % (path.name, index))
                index += 1
        else:
            target = path.with_name("%s.pre-purge-%s" % (path.name, stamp))
        shutil.copy2(str(path), str(target))
        sidecars: List[Path] = []
        for suffix in ("-wal", "-shm"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                copies = target.with_name(target.name + suffix)
                shutil.copy2(str(side), str(copies))
                sidecars.append(copies)
        return target, sidecars

    def _purgeFile(self, path: Path, finding: StrayFinding, stamp: str) -> Dict[str, Any]:
        archive, sidecars = self._archive(path, stamp)
        for suffix in ("-wal", "-shm"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                side.unlink()
        path.unlink()
        logger.info("清空散落记忆库 %s（%d 行，归档 %s）", path, finding.rows.matched, archive)
        return {"path": str(path), "action": "removed", "archive": str(archive),
                "archive_sidecars": [str(p) for p in sidecars],
                "rows_removed": finding.rows.total, "rows_kept": 0,
                "by_pattern": dict(finding.rows.byPattern)}

    def _purgeRows(self, path: Path, finding: StrayFinding, stamp: str) -> Dict[str, Any]:
        """合法根内的库：只删命中身份证据的行，其余原样保留。"""
        archive, _ = self._archive(path, stamp)
        conn = sqlite3.connect(str(path), timeout=10.0)
        try:
            victims = [(r[0],) for r in conn.execute(
                "SELECT id FROM memories").fetchall()
                if self._isResidueRow(conn, r[0])]
            conn.executemany("DELETE FROM memories WHERE id = ?", victims)
            conn.commit()
        finally:
            conn.close()
        return {"path": str(path), "action": "rows_purged", "archive": str(archive),
                "rows_removed": len(victims), "rows_kept": finding.rows.kept,
                "by_pattern": dict(finding.rows.byPattern)}

    @staticmethod
    def _isResidueRow(conn: sqlite3.Connection, rowId: str) -> bool:
        row = conn.execute("SELECT agent_id FROM memories WHERE id = ?",
                           (rowId,)).fetchone()
        return bool(row) and isTestAgentId(row[0])
