"""007 · 肌肉记忆止血：脏参数不再自动执行、不再往证据库续毒。

根因链（审计 L-07）：
1. 文本模式非 JSON 参数降级成 `{"_raw": "location=\\"许昌\\", city=\\"许昌\\""}`
   （`tool_executor.py` 的降级分支），被肌肉记忆**原样存下**；
2. 命中后把它原样喂给执行；
3. 参数校验默认开，required 键缺失被拒；
4. 咽喉 finally 仍打票且 `success=False` ⇒ 该结构身份**失败粘性永久**；
5. 后续同结构的每一轮经验都被判失败。

本票只收紧裁定档位与形状判据，**不改指纹口径、不砍肌肉记忆整条臂**。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

DIRTY_PARAMS = {"_raw": 'location="许昌", city="许昌"'}
CLEAN_PARAMS = {"location": "许昌", "city": "许昌"}
QUERY = "许昌天气怎么样"


def _integration_with_legacy_entry(tmp_path, params: Dict[str, Any]) -> ToolMemoryIntegration:
    """构造一条**存量脏条目**（写在 L2 文件里，经加载路径进内存）。

    工单 008 已把写侧改成存规范 dict，所以新条目不会再是脏形状；仍然存在的攻击面
    是**已在盘上的历史条目**（现网 `muscle_l2.json` 两条都是 `_raw`）。本夹具复现
    的正是这条路径——门必须咬合在"条目形状本身"，与它从哪来无关。
    """
    storage = tmp_path / "muscle_memory"
    storage.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": "legacy-dirty", "tool_name": "weather",
        "query_fingerprint": MuscleMemory()._extract_keywords(QUERY),
        "vector_fingerprint": MuscleMemory()._text_to_embedding_hash(QUERY),
        "parameters": params, "result_summary": "许昌 晴 26℃", "level": "l2",
        "success_count": 2, "failure_count": 0, "consecutive_successes": 2,
        "last_used": 1787748120.24, "created_at": 1787748120.24,
        "metadata": {"tool_source": "builtin"},
    }
    (storage / "muscle_l2.json").write_text(
        json.dumps([entry], ensure_ascii=False), encoding="utf-8"
    )
    memory = MuscleMemory(storage_dir=str(storage))
    assert memory._l2, "存量脏条目没有从盘上加载进内存，夹具失效"
    return ToolMemoryIntegration(muscle_memory=memory)


class TestDirtyParamsDoNotAutoExecute:
    def test_raw_params_never_reach_auto_execute(self, tmp_path):
        """存量 `_raw` 型条目 ⇒ 不得进自动执行分支（判定落在参数形状本身）。"""
        integration = _integration_with_legacy_entry(tmp_path, DIRTY_PARAMS)
        result, decision = integration.check_tool_memory(QUERY)
        if result is not None:
            assert decision != "auto_execute", (
                f"脏参数被送去自动执行（必然被参数校验拒 → 永久失败票）：{result}"
            )

    def test_reverse_lock_clean_params_still_auto_execute(self, tmp_path):
        """反向锁：换成规范 dict ⇒ 自动执行分支必须仍可达（拦的是形状，不是整条臂）。"""
        integration = _integration_with_legacy_entry(tmp_path, CLEAN_PARAMS)
        result, decision = integration.check_tool_memory(QUERY)
        assert result is not None, "规范参数下肌肉记忆命中丢失，说明拦过了头"
        assert decision == "auto_execute", (
            f"规范参数进不了自动执行分支（整条臂被误伤）：decision={decision}"
        )

    def test_hit_with_dirty_params_still_surfaces_as_hint(self, tmp_path):
        """脏参数命中要降级为可注入的提示，不是静默丢弃（否则等于砍掉这条臂）。"""
        integration = _integration_with_legacy_entry(tmp_path, DIRTY_PARAMS)
        result, decision = integration.check_tool_memory(QUERY)
        assert result is not None
        assert result.get("tool_name") == "weather"
        assert decision in ("suggest", "do_not_execute")


class TestNoNewFailureTickets:
    """脏结构重放不得在票据库上续毒（失败票计数前后差为 0）。"""

    def test_dirty_replay_does_not_grow_failure_tickets(self, tmp_path, monkeypatch):
        from neurova.skills.creation_governance import (
            begin_task,
            flush_task,
            record_tool_execution,
        )
        from neurova.skills.skill_service import SkillService

        monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "ekb.db"))
        agent_id = "probe-agent"
        service = SkillService(agent_id=agent_id)
        steps = [{"tool": "weather", "params": DIRTY_PARAMS}]

        def failure_tickets() -> int:
            results = service.creation_evidence.task_results(steps)
            return sum(1 for ok in results.values() if not ok)

        before = failure_tickets()
        integration = _integration_with_legacy_entry(tmp_path, DIRTY_PARAMS)
        _, decision = integration.check_tool_memory(QUERY)
        if decision == "auto_execute":
            begin_task()
            record_tool_execution("weather", DIRTY_PARAMS, False, {"error": "参数校验未通过"})
            flush_task(service, QUERY, completed=True)
        assert failure_tickets() == before, "脏结构重放又往票据库续了一张失败票"
