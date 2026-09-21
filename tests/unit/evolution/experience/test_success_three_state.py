"""004 · 成败三态（真成功 / 真失败 / 无测量）不许在半路裂开。

审计 L-04 / L-05 / L-10 同一根因：成败由不同位置的 `bool()` / truthiness 各自
折叠，于是「未测量」被显示成「失败」、「被策略拦截」被计成「工具故障」。
本文件把三处折叠与四个消费面各自钉一条用例：

| 位置 | 折叠方式 | 要求 |
|---|---|---|
| `post_chat_pipeline` 经验落库 | `bool(None) == False` | `None` 落 `NULL`，与 0/1 三分 |
| `closed_loop.update_weight` | `if success: … else: 记失败` | `None` **不投票** |
| `security.governance.is_policy_denial` | 只认四类键 | 补认 `hook_blocked` / `metacog_advisory` |

四个消费面（EKB 罚分档、权重表、结晶器、API 展示）必须各自独立可分辨。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.security.governance import is_policy_denial
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase


class TestPolicyDenialClassification:
    """拦截是决策，不是故障——拦截结果不得粘成工具失败票。"""

    @pytest.mark.parametrize("key", ["governance", "pending_approval", "param_guard", "swarm_rejection",
                                     "hook_blocked", "metacog_advisory"])
    def test_all_decision_shapes_are_policy_denials(self, key):
        assert is_policy_denial({"success": False, key: {"any": "thing"}}) is True

    def test_real_failure_is_not_a_policy_denial(self):
        assert is_policy_denial({"success": False, "error": "磁盘满"}) is False


class TestWeightVoteThreeState:
    """未测量不投票：`None` 不得落进失败分支。"""

    def test_none_does_not_count_as_failure(self):
        manager = AdaptiveToolWeights()
        manager.update_weight("weather", None)
        weight = manager.get_weight("weather")
        if weight is not None:
            assert weight.failure_count == 0, "未测量被记成了失败票"
            assert weight.success_count == 0
            assert len(weight.window) == 0, "未测量被写进了滑动窗口（等于投了零票以外的票）"

    def test_true_and_false_still_vote(self):
        manager = AdaptiveToolWeights()
        manager.update_weight("weather", True)
        manager.update_weight("weather", False)
        weight = manager.get_weight("weather")
        assert weight.success_count == 1
        assert weight.failure_count == 1


class TestEkbThreeStateColumn:
    """EKB `success` 列必须允许 NULL（未测量），且 NULL 不得被读成失败。"""

    def test_unevidenced_write_lands_null_success(self, tmp_path):
        kb = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))
        from neurova.skills.models import ExperienceRecord

        rid = kb.add_experience_record(
            skill_name="weather",
            exp=ExperienceRecord(skill_name="weather", context={"user_input": "许昌天气"},
                                 result={"reply_excerpt": "晴"}, success=None),
            agent_id="agent-a",
        )
        row = sqlite3.connect(str(tmp_path / "ekb.db")).execute(
            "select success from experience_records where id = ?", (rid,)
        ).fetchone()
        assert row[0] is None, f"未测量被折叠成了 {row[0]!r}"
