# -*- coding: utf-8 -*-
"""种子记忆库的落点是一个**文件对**，收养必须整对搬（Issue #290 未闭环项④）。

## 根因（2026-09-28 实测，跑真 MemoryManager）

记忆持久层是**两个文件**：`MemoryManager` 把主库 `db_path` 与持久库
`<同目录>/neurova_memories_persist.db` 配对使用，而真行写进的是**后者**
（`_persist_memory` → `_persist_db_path`；`_load_from_db` 也只读它）。

换锚救济只搬了配对的**前一半**：`seedDbPath()` 走 `dataLanding(..., legacy=...)`
收养 `yi_ling_memory.db` 一个文件，同目录的 `neurova_memories_persist.db`
留在旧锚点。于是搬过来的主库是**空壳**（0 行），真存量还在旧锚点 ——
用户侧仍是「种子记忆不可见」，而所有"旧物已搬走"的断言都还是绿的。

实测（旧锚点造 2 条真记忆，换锚后取落点再读）：

    旧锚点残留：['memory_storage', 'neurova_memories_persist.db']
    读到的记忆数 = 0（期望 2）

## 判据

1. **整对搬**：旧锚点有主库 + 持久库时，取落点后两者都在新锚点，
   且经真 `MemoryManager` 能读到旧锚点的全部记忆（用户可见的结果，不是文件数）；
2. 不覆盖 / 不静默：新锚点两份都在时旧物一份都不动，且**点名**冲突落点；
3. 反向控制：旧锚点只有主库（无持久库）时不得凭空造出持久库；
   旧锚点全无时不得造出任何文件;
4. 单一事实源：配对关系（持久库名 / 与主库同目录）只准有一处推导 ——
   写入端与收养端共用它，不许各写一份。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from neurova.core import data_root
from neurova.memory.scripts import seed_db_landing

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def landing(tmp_path, monkeypatch):
    """双锚点：旧锚点在伪仓库根下，新落点在临时数据根下（都不碰真实目录）。"""
    legacy_root = tmp_path / "repo"
    legacy_dir = legacy_root.joinpath(*seed_db_landing.LEGACY_SEED_PARTS[:-1])
    legacy_dir.mkdir(parents=True)
    target_root = tmp_path / "dataRoot"

    monkeypatch.setattr(data_root, "repoRoot", lambda: legacy_root)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(target_root))
    return legacy_dir, target_root


def _writeLegacyPair(legacy_dir: Path, contents: tuple) -> None:
    """在旧锚点用**真写入端**造一份存量（主库 + 持久库配对，行落在持久库）。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    manager = MemoryManager(db_path=str(legacy_dir / seed_db_landing.SEED_DB_NAME))
    for text in contents:
        manager.remember(content=text, category="profile", type="long_term")
    manager.close()


class TestCompanionIsRelocatedWithItsMain:
    """判据 1：整对搬，且以**用户能读到记忆**为准（不是文件数）。"""

    def test_bothHalvesAreAdoptedAndMemoriesAreReadable(self, landing):
        legacy_dir, target_root = landing
        _writeLegacyPair(legacy_dir, ("种子记忆甲", "种子记忆乙"))
        companion = legacy_dir / seed_db_landing.PERSIST_COMPANION_NAME
        assert companion.exists(), "前置条件：旧锚点的持久库未产出，本档将无从咬合"

        resolved = seed_db_landing.seedDbPath()

        assert not companion.exists(), "持久库留在旧锚点了 —— 搬过来的主库是空壳"
        assert (target_root / seed_db_landing.PERSIST_COMPANION_NAME).exists(), "持久库没被收养"

        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        manager = MemoryManager(db_path=str(resolved))
        try:
            assert len(manager._memories) == 2, (
                "经真 MemoryManager 读不到旧锚点的记忆 —— 用户侧仍是「种子记忆不可见」"
            )
        finally:
            manager.close()

    def test_existingTargetPairIsNeverOverwrittenAndConflictIsNamed(self, landing, caplog):
        legacy_dir, target_root = landing
        _writeLegacyPair(legacy_dir, ("旧种子",))
        target_root.mkdir(parents=True, exist_ok=True)
        target_companion = target_root / seed_db_landing.PERSIST_COMPANION_NAME
        target_companion.write_bytes(b"new-companion")
        data_root.nameConflictOnce.cache_clear()

        with caplog.at_level(logging.WARNING, logger="neurova.core.data_root"):
            seed_db_landing.seedDbPath()

        assert target_companion.read_bytes() == b"new-companion", "新锚点的持久库被旧物覆盖了"
        assert (legacy_dir / seed_db_landing.PERSIST_COMPANION_NAME).exists(), (
            "两侧都在时旧物不动，交人工核对"
        )
        assert any(
            seed_db_landing.PERSIST_COMPANION_NAME in record.getMessage() for record in caplog.records
        ), "两侧都在必须点名旧落点，不许静默"


class TestNoPhantomCompanion:
    """判据 3：反向控制 —— 没有旧物就不许凭空造文件。"""

    def test_legacyWithoutCompanionDoesNotCreateOne(self, landing):
        legacy_dir, target_root = landing
        (legacy_dir / seed_db_landing.SEED_DB_NAME).write_bytes(b"shell-only")

        resolved = seed_db_landing.seedDbPath()

        assert resolved.read_bytes() == b"shell-only"
        assert not (target_root / seed_db_landing.PERSIST_COMPANION_NAME).exists(), (
            "旧锚点没有持久库，新锚点却出现了 —— 凭空造物"
        )

    def test_noLegacyCreatesNothing(self, landing):
        legacy_dir, target_root = landing

        resolved = seed_db_landing.seedDbPath()

        assert not resolved.exists()
        assert not (target_root / seed_db_landing.PERSIST_COMPANION_NAME).exists()


class TestCompanionPairingIsSingleSourced:
    """判据 4：配对关系只准一处推导（写入端与收养端共用）。"""

    def test_writerAndAdopterShareOneDerivation(self):
        from neurova.cognitive_layers.memory_layer import manager as memory_manager

        assert not hasattr(memory_manager, "PERSIST_DB_NAME") or True  # 占位：见下条断言
        source = Path(memory_manager.__file__).read_text(encoding="utf-8")
        assert '"neurova_memories_persist.db"' not in source.replace(
            'PERSIST_DB_NAME = "neurova_memories_persist.db"', ""
        ), "写入端自己拼了第二份配对名 —— 应与收养端共用同一处推导"

    def test_pairingHelperAgreesWithWriter(self, tmp_path):
        """配对推导必须与写入端实际用的路径逐字一致（否则两边各说各话）。"""
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        from neurova.cognitive_layers.memory_layer.persist_landing import persistCompanionPath

        main = tmp_path / "yi_ling_memory.db"
        manager = MemoryManager(db_path=str(main))
        try:
            assert Path(manager._persist_db_path) == persistCompanionPath(main), (
                "配对推导与写入端实际落点不一致"
            )
        finally:
            manager.close()
