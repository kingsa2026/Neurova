"""010 · 采不到要出声：票据上下文缺失可观测 + 两个小尾巴。

三处：
- a `creation_governance.record_tool_execution` 首行 `if task is None: return`
  零日志零计数——"这个 agent 从没调过工具"与"它的工具调用没被采到"在观测面
  必须分得开，否则 003/005 迁移期的漏采会静默发生。
- b `turn_context.clear_turn_state` 的复位元组漏了 `_injected_experiences_var`，
  测试 teardown 残留跨用例互串（"用互串掩护真断线"）。
- c `experience_knowledge_base.get_experience_stats` 顶层 `neurova/` 零生产调用方
  （`/stats` 端点自己重算），删掉并改测试走真实数据源。
"""

from __future__ import annotations

import json
import logging

import pytest

from neurova.core import turn_context as tc
from neurova.skills import creation_governance as cg


@pytest.fixture(autouse=True)
def _reset_context():
    cg._execution.set(None)
    yield
    cg._execution.set(None)


class TestMissingContextSpeaksUp:
    def test_missing_task_context_counts_and_warns(self, caplog):
        cg._execution.set(None)
        with caplog.at_level(logging.WARNING, logger="neurova.skills.creation_governance"):
            cg.record_tool_execution("weather", {"city": "许昌"}, True, {"ok": True})
        assert cg.missing_context_count() >= 1, "上下文缺失没有计数，漏采在观测面不可见"
        assert any("weather" in record.message for record in caplog.records), (
            "上下文缺失没有点名入口/工具，运维无从定位："
            f"{[r.message for r in caplog.records]}"
        )

    def test_normal_path_does_not_count(self):
        before = cg.missing_context_count()
        cg.begin_task()
        cg.record_tool_execution("weather", {"city": "许昌"}, True, {"ok": True})
        assert cg.missing_context_count() == before


class TestTurnContextReset:
    def test_injected_experiences_cleared_by_teardown(self):
        tc.set_turn_injected_experiences([1, 2, 3])
        assert tc.get_turn_injected_experiences() == [1, 2, 3]
        tc.clear_turn_state()
        assert tc.get_turn_injected_experiences() in (None, []), (
            "teardown 未复位注入身份集，跨用例互串会掩护真断线"
        )


class TestOrphanMethodRemoved:
    def test_get_experience_stats_is_not_reintroduced(self):
        from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

        assert not hasattr(ExperienceKnowledgeBase, "get_experience_stats"), (
            "零生产调用方的孤岛方法又回来了；统计面唯一事实源是 /stats 端点重算"
        )


class TestExperienceMetrics:
    """009 · 经验要带得出度量：置信度、耗时与结构身份落库。"""

    def test_turn_elapsed_is_accumulated_by_the_choke(self, tmp_path):
        """轮级耗时由执行咽喉累加（单源），post-chat 直接取用，不再无人写入。"""
        from neurova.core import turn_context as tc2

        tc2.reset_turn_tool_messages()
        assert tc2.get_turn_tool_elapsed() == 0.0
        tc2.add_turn_tool_elapsed(0.4)
        tc2.add_turn_tool_elapsed(0.6)
        assert abs(tc2.get_turn_tool_elapsed() - 1.0) < 1e-9

    def test_reset_clears_elapsed(self):
        from neurova.core import turn_context as tc2

        tc2.add_turn_tool_elapsed(0.5)
        tc2.reset_turn_tool_messages()
        assert tc2.get_turn_tool_elapsed() == 0.0



class TestMuscleMemoryElapsedObservability:
    """007 的连带代价必须留痕（不许静默遗留）。"""

    def test_param_shape_blocked_is_observable(self, tmp_path):
        """形状门挡下的命中要能被统计区分——否则"档位收紧了"在观测面不可见。"""
        from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
            ToolMemoryIntegration,
        )

        # 存量脏条目：写侧已改存规范 dict，攻击面在**盘上的历史条目**
        storage = tmp_path / "mm"
        storage.mkdir(parents=True, exist_ok=True)
        probe = MuscleMemory()
        (storage / "muscle_l2.json").write_text(json.dumps([{
            "id": "legacy-dirty", "tool_name": "weather",
            "query_fingerprint": probe._extract_keywords("许昌天气怎么样"),
            "vector_fingerprint": probe._text_to_embedding_hash("许昌天气怎么样"),
            "parameters": {"_raw": 'location="许昌"'}, "result_summary": "",
            "level": "l2", "success_count": 2, "failure_count": 0,
            "consecutive_successes": 2, "last_used": 1787748120.24,
            "created_at": 1787748120.24, "metadata": {"tool_source": "builtin"},
        }], ensure_ascii=False), encoding="utf-8")
        memory = MuscleMemory(storage_dir=str(storage))
        integration = ToolMemoryIntegration(muscle_memory=memory)
        result, decision = integration.check_tool_memory("许昌天气怎么样")
        assert decision == "suggest"
        assert result.get("param_shape_blocked") is True, (
            "形状门挡下的命中没有可观测标记，运营看不到档位被收紧"
        )
