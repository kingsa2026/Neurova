# -*- coding: utf-8 -*-
"""P2-11 agent_config 原子写与诚实返回值红绿测试（全库代码审计 2026-11-14）。

缺陷：_save_agents_list/_save_models 直接以 "w" 打开目标文件写 JSON——
写一半崩溃/磁盘满会把 agents.json 截断成半截（配置丢失）；且保存异常
被吞掉后写方法照常返回 True（假成功），调用方无从感知持久化失败。

修复口径：tmp + os.replace 原子写，保存失败记 error 并返回 False；
create/update/delete/add_model 等写方法把保存结果上抛为返回值，
且保存失败时内存不应用变更（副本提交，不产生内存/磁盘漂移）。
"""
import json
from pathlib import Path

import pytest

from neurova.agent_config import AgentConfigManager


@pytest.fixture
def manager(tmp_path):
    return AgentConfigManager(config_dir=tmp_path / "agents")


class TestAgentConfigAtomicSave:
    def test_createAgent_jsonDumpFails_returnsFalseAndKeepsOriginalFile(self, manager, monkeypatch):
        """json.dump 抛异常 → create_agent 返回 False，且原文件内容完好（原子性）。"""
        # 预置：先成功创建一个 agent，作为"原文件内容"
        assert manager.create_agent("a1", "Existing") is True
        original = manager._agents_file.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json, "dump", boom)

        assert manager.create_agent("a2", "New") is False, "保存失败不得谎报创建成功"
        # 原文件内容完好（未被半写状态覆盖）
        assert manager._agents_file.read_text(encoding="utf-8") == original
        # tmp 残留已清理
        assert not (manager._agents_file.parent / "agents.json.tmp").exists()
        # 内存不漂移：失败的创建不进内存
        assert manager.get_agent("a2") is None
        assert manager.get_agent("a1") is not None

    def test_updateAgent_saveFails_returnsFalseAndKeepsOldValue(self, manager, monkeypatch):
        assert manager.create_agent("a1", "Existing") is True
        original = manager._agents_file.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json, "dump", boom)

        assert manager.update_agent("a1", {"name": "Changed"}) is False
        assert manager._agents_file.read_text(encoding="utf-8") == original
        assert manager.get_agent("a1")["name"] == "Existing", "保存失败时内存不应用变更"

    def test_deleteAgent_saveFails_returnsFalseAndAgentStays(self, manager, monkeypatch):
        assert manager.create_agent("a1", "Existing") is True
        original = manager._agents_file.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json, "dump", boom)

        assert manager.delete_agent("a1") is False
        assert manager._agents_file.read_text(encoding="utf-8") == original
        assert manager.get_agent("a1") is not None, "删除落盘失败时内存不撤条目"

    def test_addModel_saveFails_returnsFalse(self, manager, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(json, "dump", boom)

        assert manager.add_model({"id": "m1", "name": "M", "provider": "openai", "model": "gpt-4"}) is False
        assert manager.get_model("m1") is None

    def test_successPath_returnsTrue_andNoTmpResidue(self, manager):
        """成功路径回归：写方法返回 True、文件内容正确、无 .tmp 残留。"""
        assert manager.create_agent("a1", "Alpha") is True
        assert manager.update_agent("a1", {"description": "d"}) is True
        assert manager.add_model({"id": "m1", "name": "M", "provider": "openai", "model": "gpt-4"}) is True
        assert manager.update_model("m1", {"name": "M2"}) is True
        assert manager.delete_model("m1") is True
        assert manager.delete_agent("a1") is True

        data = json.loads(manager._agents_file.read_text(encoding="utf-8"))
        assert data == {}
        assert not (manager._agents_file.parent / "agents.json.tmp").exists()
        assert not (manager._models_file.parent / "models.json.tmp").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
