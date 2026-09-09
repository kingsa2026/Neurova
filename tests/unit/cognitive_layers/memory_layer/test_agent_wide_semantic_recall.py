# -*- coding: utf-8 -*-
"""防回归：agent_wide=True 的管理口径语义检索必须不被请求作用域清零。

根因（2026-09-09 Kai 记忆迁移验收发现）：
get_memory_manager 为登录用户注入请求作用域 (neuser_id='1', user_id='1')，
recall(query, agent_wide=True) 基集正确取 agent 全量，但 _semantic_recall
内部无条件再做一次三元组收窄 → 存量 default/default 记忆（Kai 导入 921 条、
default agent 223 条）在管理页/记忆 API 的关键词与语义搜索全部 0 命中。
空查询路径不走语义分支所以列表可见——列表可见、搜索不可见的割裂即此根因。

修复口径对齐 get_memory(memory_id, agent_wide=True) 的既有先例：
agent_wide 时只校验 agent 归属，跳过三元组收窄；聊天检索
（agent_wide=False）三层隔离原样保留。
"""

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import Memory


@pytest.fixture()
def scoped_manager(tmp_path):
    """default 三元组存量的 manager + admin 请求作用域。"""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    mm = MemoryManager(
        str(mem_dir / "memory.db"),
        agent_id="kai", neuser_id="default", user_id="default",
    )
    mm.remember(
        content="喂食器项目正式取消的决策记忆",
        memory_type="episodic",
        category="experience",
        importance=50.0,
    )
    # admin 作用域注入（与 memory/base.py get_memory_manager 同路径）
    mm.set_request_scope(neuser_id="1", user_id="1")
    yield mm
    mm.set_request_scope(neuser_id=None, user_id=None)


class TestAgentWideSemanticRecall:
    def test_agent_wide_query_hits_default_triplet_memory(self, scoped_manager):
        """管理口径 + 查询词：default 三元组存量记忆必须可检索。"""
        hits = scoped_manager.recall(query="喂食器", agent_wide=True, limit=5)
        assert len(hits) == 1
        assert "喂食器" in hits[0]["content"]

    def test_chat_scoped_query_still_isolated(self, scoped_manager):
        """聊天口径（agent_wide=False）：三层隔离原样保留，跨作用域不可见。"""
        hits = scoped_manager.recall(query="喂食器", agent_wide=False, limit=5)
        assert hits == []

    def test_agent_wide_no_query_lists_all(self, scoped_manager):
        """管理口径 + 空查询：行为与修复前一致（基集即 agent 全量）。"""
        hits = scoped_manager.recall(query="", agent_wide=True, limit=10)
        assert len(hits) == 1
