"""记忆/数据默认落点必须单源，且不许随 CWD 散落。

病灶（2026-09-21 审计 §7 / B-12、Issue #75）：仓库根 `neurova_memories_persist.db`
攒了 71,831 行，成因是记忆库曾以裸文件名 `neurova_memory.db` 当默认值，持久库
随进程 CWD 散落五处。`MemoryManager` 的默认已改成按 agent 工作区推导，但**同一族
的第二批仍在**——`core/database.py`、`connection_pool.py`、`db_indexes.py`、
`files_api`、`memory_layer/storage.py`、`memory/pending_memory.py`、
`CognitiveStorageEngine` 的默认值全是 CWD 相对路径，换个工作目录就换个库。

判据（每条都可由本文件复现，不用替身）：

1. 默认落点是**绝对路径**，且落在数据根之内；数据根可由 `NEUROVA_DATA_DIR` 注入。
2. 在任意 CWD 下用默认值取连接 / 建存储引擎，**不得在 CWD 造出文件**。
3. 认知图谱目录与它的删除方必须是**同一处推导**（写出去了没人删 = 断点）。
4. 权威字面量只剩一处：全仓不得再有用裸文件名当默认值的函数签名。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"


class TestDataRootIsSingleSource:
    def test_defaultRootIsRepoData(self, monkeypatch):
        from neurova.core.data_root import get_data_root

        monkeypatch.delenv("NEUROVA_DATA_DIR", raising=False)
        root = get_data_root()

        assert root.is_absolute(), "数据根必须是绝对路径——相对路径就是散落的入口"
        assert root == PROJECT_ROOT / "data"

    def test_envInjectionIsHonored(self, monkeypatch, tmp_path):
        from neurova.core.data_root import get_data_root

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "elsewhere"))

        assert get_data_root() == tmp_path / "elsewhere"

    def test_agentDataDirJoinsAgentId(self, monkeypatch, tmp_path):
        from neurova.core.data_root import get_agent_data_dir

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        assert get_agent_data_dir("kai") == tmp_path / "kai"
        assert get_agent_data_dir("") == tmp_path / "default"

    def test_dataRootLiteralLivesOnlyInTheResolver(self):
        """`parents[N] / "data"` 这类按层数反推只准出现在数据根本身里。

        反向控制：数据根本身必须真的按层数解析一次——否则这条断言会在
        "根被挪到别处、字面量也被删掉"时依然全绿。
        """
        resolver = (NEUROVA / "core" / "data_root.py").read_text(encoding="utf-8")
        assert "parents[2]" in resolver and "_DEFAULT_DATA_DIR" in resolver, \
            "数据根本身没有按层数解析仓库根，这条判据失去基准"
        offenders = []
        for path in NEUROVA.rglob("*.py"):
            if path.name == "data_root.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if 'parents[2] / "data"' in text or 'parents[3] / "data"' in text:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        assert offenders == [], "数据根字面量被抄到了别处：%s" % offenders


class TestDefaultsAreNotCwdRelative:
    """每一条都实证"在别的 CWD 下用默认值会不会造出文件"。"""

    @pytest.fixture
    def elsewhere(self, tmp_path, monkeypatch):
        """把 CWD 与数据根都指到临时目录：任何落点漂移都会在这里现形。"""
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "dataRoot"))
        return cwd

    def test_coreDatabaseDefaultsLandUnderDataRoot(self, elsewhere):
        from neurova.core import database
        from neurova.core.data_root import get_data_root

        path = Path(database.defaultDbPath())

        assert path.is_absolute() and str(get_data_root()) in str(path), \
            "core 数据库默认落点必须由数据根推导"
        with database.database_connection() as conn:
            conn.execute("SELECT 1")
        assert list(elsewhere.iterdir()) == [], (
            "默认连接在 CWD 造出了文件：%s" % [p.name for p in elsewhere.iterdir()]
        )

    def test_connectionPoolDefaultsLandUnderDataRoot(self, elsewhere):
        from neurova.core.connection_pool import get_db_connection

        with get_db_connection() as conn:
            conn.execute("SELECT 1")

        assert list(elsewhere.iterdir()) == [], (
            "连接池默认落点在 CWD 造出了文件：%s" % [p.name for p in elsewhere.iterdir()]
        )

    def test_filesMetadataDefaultsLandUnderDataRoot(self, elsewhere):
        from neurova.api.endpoints import files_api

        assert Path(files_api._FILES_DB_PATH).is_absolute(), \
            "files 元数据库的默认值不得是 CWD 相对路径"

    def test_memoryStorageSingletonLandsUnderDataRoot(self, elsewhere):
        from neurova.cognitive_layers.memory_layer import storage as mod

        target = Path(mod.defaultStorageDir())

        assert target.is_absolute() and "dataRoot" in str(target), \
            "memory_storage 单例的默认目录必须由数据根推导"

    def test_pendingStoreDefaultLandsUnderDataRoot(self, elsewhere):
        from neurova.memory import pending_memory

        target = Path(pending_memory.defaultPendingDbPath())

        assert target.is_absolute() and "dataRoot" in str(target), \
            "待确认记忆库默认落点必须由数据根推导"
        store = pending_memory.get_pending_memory_store()
        try:
            assert Path(store._db_path).is_absolute(), "真建出来的库也必须是绝对路径"
        finally:
            store.close()
            pending_memory._process_store = None

    def test_cognitiveEngineDefaultLandsUnderDataRoot(self, elsewhere):
        from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
            CognitiveStorageEngine,
        )

        engine = CognitiveStorageEngine(agent_id="probe")
        try:
            assert engine.data_dir.is_absolute(), "认知图谱目录必须是绝对路径"
            assert list(elsewhere.iterdir()) == [], (
                "认知引擎默认落点在 CWD 造出了文件：%s" % [p.name for p in elsewhere.iterdir()]
            )
        finally:
            engine._db.close()


class TestCognitiveDataDirIsOneDerivation:
    """写它的人与删它的人必须同一处推导，否则删除端永远删不掉。"""

    def test_producerAndConsumerShareTheResolver(self):
        from neurova.core.data_root import get_agent_data_dir

        producer = (NEUROVA / "agent_core.py").read_text(encoding="utf-8")
        consumer = (NEUROVA / "api" / "endpoints" / "agent.py").read_text(encoding="utf-8")
        engine = (NEUROVA / "cognitive_layers" / "memory_layer"
                  / "cognitive_storage_engine.py").read_text(encoding="utf-8")

        assert "ensure_agent_data_dir" in producer, "agent_core 仍在自己拼 data/{agent_id}"
        assert "get_agent_data_dir" in engine, "认知引擎仍在自己拼 data/{agent_id}"
        assert get_agent_data_dir.__name__ in consumer, (
            "删除端点仍按 Path('data')/agent_id 推导——与写入端不是一处，"
            "CWD 一变就删不掉"
        )


class TestNoBareFilenameDefaultsRemain:
    """权威字面量只剩一处：签名里不许再拿裸文件名当默认值。"""

    _PATTERN = re.compile(
        r"def\s+\w+\([^)]*db_path\s*(?::\s*str\s*)?=\s*[\"'](?!:memory:)"
        r"(?![\"'])", re.S)

    def test_coreModulesHaveNoBareDbDefault(self):
        offenders = []
        for name in ("core/database.py", "core/connection_pool.py", "core/db_indexes.py"):
            text = (NEUROVA / name).read_text(encoding="utf-8")
            if self._PATTERN.search(text):
                offenders.append(name)
        assert offenders == [], "仍有裸路径当默认值的签名：%s" % offenders
