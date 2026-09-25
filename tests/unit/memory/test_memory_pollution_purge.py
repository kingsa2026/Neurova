"""历史污染清空：判据必须是正证据，动作必须可回退，且不许连带真实记忆。

病灶（2026-09-21 审计 §7 / B-12 / Issue #75）：仓库根 `neurova_memories_persist.db`
攒了 71,831 行，`agent_id` 含 `test` 或为 `engine_it_*` 的占 71,378（99.369%）——
成因是记忆库曾以裸文件名当默认值，持久库随进程 CWD 散落。围栏堵住了新增，
但存量那份与散落副本仍在盘上；读数每次都得绕过它才可信。

清空是**破坏性动作**，所以本文件的判据是"误删比漏删严重"：

1. 判据是正证据（位置 + 身份两条），不做比例判断——一条真实行在库里就必须保留整块。
2. 默认只预报（`dryRun=True` 是默认值）；落手必须先归档整库（含 sidecar）。
3. 目标落在 agent 工作区里时当场拒——清历史污染不许连带删真实 agent 的记忆。
4. 清完再跑一遍必须报"无事可做"（幂等），且回退只需把归档副本改回原名。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.pollution_purge import (
    LEGACY_DB_NAMES,
    MemoryPollutionPurge,
    isStrayPath,
    isTestAgentId,
)

_MEMORIES_DDL = """
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT 'default',
    metadata TEXT NOT NULL DEFAULT '{}',
    origin TEXT NOT NULL DEFAULT 'agent'
)
"""

# 污染形状取自审计实测：test_agent_* 为最大宗（82%），engine_it_* 次之，
# 另有一小撮非污染余量（真实用户名）必须原样存活。
_RESIDUE_IDS = ["test_agent_auto-gen_0001", "test_agent_auto-gen_0002",
                "test_tools", "engine_it_bench", "engine_it_bench"]
_KEPT_IDS = ["verify-agent", "default", "kai"]


def _makeMemoryDb(path: Path, agentIds: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(_MEMORIES_DDL)
    for index, agentId in enumerate(agentIds):
        conn.execute("INSERT INTO memories (id, content, agent_id) VALUES (?,?,?)",
                     ("m%04d" % index, "内容 %d" % index, agentId))
    conn.commit()
    conn.close()
    return path


def _agentIds(path: Path) -> list:
    conn = sqlite3.connect(str(path))
    try:
        return sorted(r[0] for r in conn.execute("SELECT agent_id FROM memories"))
    finally:
        conn.close()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """仓库根 / 数据根 / 工作区根都指到临时目录：任何真实路径都不参与本文件。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(repo / "data"))
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(repo / "agent_workspaces"))
    return repo


class TestEvidenceIsPositive:
    """身份与位置两条证据都必须是"命中即删"，不做比例判断。"""

    @pytest.mark.parametrize("agentId,expected", [
        ("test_agent_auto-gen_1", True), ("test_tools", True), ("engine_it_bench", True),
        ("default", False), ("kai", False), ("verify-agent", False),
        # 子串含 test 但整段不命中：不做包含判断，否则真实用户名会被误删
        ("contest-agent", False), ("latest-user", False), ("", False),
    ])
    def test_identityEvidenceIsWholeSegment(self, agentId, expected):
        assert isTestAgentId(agentId) is expected

    def test_strayLocationIsOutsideEveryLegalRoot(self, sandbox):
        import os

        stray = sandbox / "neurova_memories_persist.db"
        inside_data = Path(os.environ["NEUROVA_DATA_DIR"]) / "sub" / "neurova_memories_persist.db"
        inside_workspace = (Path(os.environ["NEUROVA_AGENT_WORKSPACES_DIR"])
                            / "kai" / "memory" / "neurova_memories_persist.db")

        assert isStrayPath(stray) is True, "仓库根的散落库必须被判为散落物"
        assert isStrayPath(inside_data) is False, "数据根下的库不是散落物"
        assert isStrayPath(inside_workspace) is False, "agent 工作区里的库不是散落物"


class TestDryRunIsTheDefault:
    def test_planWritesNothing(self, sandbox):
        db = _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)
        before = db.read_bytes()

        report = MemoryPollutionPurge(roots=[sandbox]).plan()

        assert report["mode"] == "dry_run"
        assert report["residue_rows"] == len(_RESIDUE_IDS)
        assert db.exists() and db.read_bytes() == before, "预报阶段不许动数据"
        assert not list(sandbox.glob("*.pre-purge-*")), "预报阶段不许留归档"

    def test_applyDefaultsToDryRun(self, sandbox):
        db = _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)

        report = MemoryPollutionPurge(roots=[sandbox]).apply()

        assert report["mode"] == "dry_run"
        assert db.exists(), "apply() 默认不许真删——落手必须显式 dryRun=False"

    def test_planCountsRowsByPatternWithSamples(self, sandbox):
        _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS + _KEPT_IDS)

        finding = MemoryPollutionPurge(roots=[sandbox]).plan()["strays"][0]

        assert finding["rows"]["total"] == len(_RESIDUE_IDS) + len(_KEPT_IDS)
        assert finding["rows"]["matched"] == len(_RESIDUE_IDS)
        assert finding["rows"]["kept"] == len(_KEPT_IDS)
        assert finding["rows"]["by_pattern"]["test_agent_*"] == 2
        assert finding["rows"]["by_pattern"]["engine_it_*"] == 2
        assert set(finding["rows"]["sample_ids"]) <= set(_RESIDUE_IDS)


class TestApplyIsArchivedAndIdempotent:
    def test_strayFileIsArchivedThenRemoved(self, sandbox):
        db = _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)
        original = db.read_bytes()

        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)

        assert report["mode"] == "apply"
        assert not db.exists(), "散落库必须被删掉"
        archives = list(sandbox.glob("neurova_memories_persist.db.pre-purge-*"))
        assert len(archives) == 1, "删除前必须先归档"
        assert archives[0].read_bytes() == original, "归档内容与原库不一致，回退会丢数据"

    def test_sidecarsAreArchivedAndRemoved(self, sandbox):
        db = _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)
        (db.parent / (db.name + "-wal")).write_bytes(b"wal")
        (db.parent / (db.name + "-shm")).write_bytes(b"shm")

        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)

        assert not (db.parent / (db.name + "-wal")).exists()
        assert not (db.parent / (db.name + "-shm")).exists()
        archive = Path(report["actions"][0]["archive"])
        assert Path(str(archive) + "-wal").read_bytes() == b"wal"

    def test_secondRunFindsNothingLeft(self, sandbox):
        _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)
        purge = MemoryPollutionPurge(roots=[sandbox])
        purge.apply(dryRun=False)

        second = purge.plan()

        assert second["strays"] == [] and second["residue_rows"] == 0, (
            "清完仍有残留：说明清空不幂等"
        )

    def test_rollbackIsRenameBack(self, sandbox):
        db = _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)
        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)

        archive = Path(report["actions"][0]["archive"])
        archive.rename(db)

        assert _agentIds(db) == sorted(_RESIDUE_IDS), "回退后数据不完整"


class TestRealMemoriesSurvive:
    """合法根内的库只删命中身份证据的行，其余原样保留。"""

    def test_rowsInDataRootArePurgedSelectively(self, sandbox):
        import os

        db = _makeMemoryDb(Path(os.environ["NEUROVA_DATA_DIR"])
                           / "neurova_memories_persist.db", _RESIDUE_IDS + _KEPT_IDS)

        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)

        assert report["actions"][0]["action"] == "rows_purged"
        assert _agentIds(db) == sorted(_KEPT_IDS), (
            "真实行被连带删掉了——判据必须逐行看正证据，不许按比例"
        )
        assert Path(report["actions"][0]["archive"]).exists(), "行级清空同样要先归档"

    def test_productionWorkspaceTargetIsRefused(self, sandbox):
        """目标落在工作区里时当场失败：清历史污染不许连带真实 agent 的记忆。"""
        import os

        workspaceDb = (Path(os.environ["NEUROVA_AGENT_WORKSPACES_DIR"]) / "kai"
                       / "memory" / "neurova_memories_persist.db")
        _makeMemoryDb(workspaceDb, _RESIDUE_IDS)
        purge = MemoryPollutionPurge(roots=[sandbox])

        with pytest.raises(RuntimeError, match="agent 工作区"):
            purge.apply(dryRun=False)
        assert workspaceDb.exists(), "拒绝之后不许有任何删动"


class TestEmptyShellsAreReported:
    def test_emptyShellDirsAreListedAndRemoved(self, sandbox):
        (sandbox / "agent_workspaces" / "kai" / "memory" / "memory_storage").mkdir(parents=True)
        (sandbox / "data" / "memory_layer").mkdir(parents=True)

        plan = MemoryPollutionPurge(roots=[sandbox]).plan()

        assert len(plan["empty_shell_dirs"]) == 2
        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)
        assert len(report["removed_empty_shell_dirs"]) == 2
        assert not (sandbox / "agent_workspaces" / "kai" / "memory" / "memory_storage").exists()

    def test_nonEmptyDirIsNeverTouched(self, sandbox):
        target = sandbox / "data" / "memory_layer"
        target.mkdir(parents=True)
        (target / "memories.json").write_text("{}", encoding="utf-8")

        report = MemoryPollutionPurge(roots=[sandbox]).apply(dryRun=False)

        assert report["removed_empty_shell_dirs"] == []
        assert (target / "memories.json").exists()


class TestLegacyNamesAreSingleSource:
    def test_scanCoversBothLegalDatabaseNames(self, sandbox):
        for name in LEGACY_DB_NAMES:
            _makeMemoryDb(sandbox / name, _RESIDUE_IDS[:1])

        found = {Path(item["path"]).name
                 for item in MemoryPollutionPurge(roots=[sandbox]).plan()["strays"]}

        assert found == set(LEGACY_DB_NAMES)

    def test_reportIsJsonSerializable(self, sandbox):
        _makeMemoryDb(sandbox / "neurova_memories_persist.db", _RESIDUE_IDS)

        report = MemoryPollutionPurge(roots=[sandbox]).plan()

        json.dumps(report, ensure_ascii=False), "报告要能直接落审计留痕"
