"""记忆库必须与知识库受同一个写入围栏，且"落哪去"不能靠 CWD 决定。

病灶形状（2026-09-21 审计 §7）：仓库根 `neurova_memories_persist.db` 现有 71,831 行，
`agent_id LIKE 'engine_it_%'` 数万个、`metadata` 全 `{}`、`origin` 全 `agent`，
真实用户数据只在 `agent_workspaces/*`（324 + 988 行）。根因有两条，都必须在这里堵：

1. **裸文件名当默认值**：`MemoryManager(db_path="neurova_memory.db")` 是相对路径，
   `_init_persistence_db` 用 `os.path.dirname(...) or "."` 派生 persist 库目录 ⇒
   文件随进程 CWD 散落（实测 5 份：仓库根 / `neurova/memory/data/` / `data/default/` /
   `data/` / `test_workspace/memory/`）。默认值必须按 agent 工作区推导，不留裸名。
2. **无围栏**：知识侧有 `storage_fence`，记忆侧连对等物都没有 ⇒ 测试会话写生产记忆库
   没人拦。围栏要把记忆侧的写入面（主库 + 同目录 persist 库 + JSON 镜像目录）一起纳入。

判据：默认路径不落 CWD；测试会话里碰生产记忆目录当场失败；隔离目录照常可写。
"""

from __future__ import annotations

import os

import pytest

from neurova.knowledge.foundation.storage_fence import (
    assertNotUnderProductionMemory,
    underProductionMemory,
)
from neurova.cognitive_layers.memory_layer.manager import MemoryManager


class TestDefaultPathIsNotCwdRelative:
    def test_defaultDbPathLandsInTheAgentWorkspace(self, monkeypatch, tmp_path):
        """默认值不许是裸文件名——落点必须由 agent 工作区推导。

        用假生产目录证明：`NEUROVA_AGENT_WORKSPACES_DIR` 指向仓库内一个隔离目录，
        围栏放行，而落点仍严格等于该目录下的 `<agent>/memory/`。
        """
        workspaces = tmp_path / "ws"
        monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(workspaces))
        monkeypatch.chdir(tmp_path)

        manager = MemoryManager(agent_id="abc", user_id="u1", enable_buffer=False)
        try:
            assert os.path.isabs(manager._db_path), "默认路径必须是绝对路径"
            assert str(manager._db_path).startswith(str(workspaces)), \
                "默认落点必须是该 agent 的工作区，不是进程 CWD"
            assert manager._persist_db_path is not None
            assert os.path.dirname(manager._persist_db_path) == os.path.dirname(manager._db_path)
        finally:
            manager.close()

        assert not (tmp_path / "neurova_memories_persist.db").exists(), \
            "CWD 下不得再出现裸名 persist 库——这正是仓库根那 71,831 行的来路"

    def test_emptyPathIsStillRejected(self):
        """空串仍是显式的非法输入（与"没给"是两件事），不许被默认逻辑吞掉。"""
        with pytest.raises(ValueError):
            MemoryManager(db_path="")


class TestFenceCoversMemorySurfaces:
    def test_productionMemoryDirIsTheRepoWorkspacesRoot(self):
        """生产目录是磁盘上那个事实，不随进程配置（`NEUROVA_AGENT_WORKSPACES_DIR`）漂移。"""
        from neurova.knowledge.foundation.storage_fence import productionMemoryDir

        assert productionMemoryDir().name == "agent_workspaces"
        assert underProductionMemory(productionMemoryDir() / "default" / "memory"
                                     / "neurova_memories_persist.db")

    def test_isolatedDirectoryIsNotProduction(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "ws"))

        assert not underProductionMemory(tmp_path / "ws" / "default" / "memory" / "m.db")

    def test_pytestSessionIsBlockedAtTheProductionDir(self, monkeypatch):
        from neurova.knowledge.foundation.storage_fence import productionMemoryDir

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        prod = str(productionMemoryDir() / "default" / "memory" / "x.db")

        with pytest.raises(RuntimeError, match="生产记忆"):
            assertNotUnderProductionMemory(prod, "主记忆库")

    def test_nonPytestSessionIsNotBlocked(self, monkeypatch):
        """围栏只对测试会话生效——生产与脚本的正常写入不该被它拦住。"""
        from neurova.knowledge.foundation.storage_fence import productionMemoryDir

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("PYTEST_VERSION", raising=False)

        assertNotUnderProductionMemory(productionMemoryDir() / "default" / "memory" / "x.db",
                                       "主记忆库")

    def test_managerConstructionIsFencedUnderPytest(self, monkeypatch):
        """围栏必须长在构造上：建库就会落文件，只守写入边界等于守不住。"""
        from neurova.knowledge.foundation.storage_fence import productionMemoryDir

        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")
        prod = str(productionMemoryDir() / "default" / "memory" / "memory.db")

        with pytest.raises(RuntimeError, match="生产记忆"):
            MemoryManager(db_path=prod, agent_id="default", enable_buffer=False)

    def test_isolatedManagerStaysUsable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "guard")

        manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="probe",
                                enable_buffer=False)
        try:
            assert manager._persist_db_path
        finally:
            manager.close()
