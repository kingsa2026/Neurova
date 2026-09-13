"""Wave 3 — 技能遥测生命周期状态机测试。

对位 Hermes curator.apply_automatic_transitions:
  active → stale(14天)→ archived(30天);用后回暖 reactivated
保护语义:pinned 全绕开;created_by != agent 不动;从未活跃者锚 created_at 不自归档。
"""

import time

import pytest

from neurova.evolution.skill_lifecycle import SkillLifecycle, apply_transitions

DAY_MS = 86_400_000


def _svc(records):
    """构造一个最小 skill_service stub(只实现生命周期需要的接口)。"""
    class _S:
        def __init__(self, recs):
            self._recs = recs

        def iter_skills(self):
            for sid, rec in self._recs.items():
                yield sid, rec

        def set_skill_lifecycle_state(self, sid, state):
            self._recs[sid]["usage"]["state"] = state
            return True

        def archive_skill(self, sid):
            self._recs[sid]["usage"]["state"] = "archived"
            return {"success": True}

    return _S(records)


def _rec(state="active", last_activity_ms=None, use_count=1, pinned=False,
         created_by="agent", created_ms=None):
    now = int(time.time() * 1000)
    return {
        "usage": {
            "state": state,
            "use_count": use_count,
            "last_activity_at_ms": last_activity_ms if last_activity_ms is not None else now,
            "pinned": pinned,
            "created_by": created_by,
            "created_at_ms": created_ms if created_ms is not None else now,
        }
    }


class TestTransitions:
    def test_active_to_stale_after_14_days(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(last_activity_ms=now - 15 * DAY_MS)}
        counts = apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "stale"
        assert counts["marked_stale"] == 1

    def test_stale_to_archived_after_30_days(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(state="stale", last_activity_ms=now - 31 * DAY_MS)}
        counts = apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "archived"
        assert counts["archived"] == 1

    def test_recent_active_untouched(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(last_activity_ms=now - 1 * DAY_MS)}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "active"

    def test_stale_reactivated_on_new_activity(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(state="stale", last_activity_ms=now - 1 * DAY_MS)}
        counts = apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "active"
        assert counts["reactivated"] == 1

    def test_never_archived_when_recently_active(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(state="active", last_activity_ms=now - 20 * DAY_MS, use_count=0)}
        # use_count==0 且活跃时间在 stale 窗口内 → 不归档
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] != "archived"


class TestProtections:
    def test_pinned_never_touched(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(last_activity_ms=now - 100 * DAY_MS, pinned=True)}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "active"

    def test_non_agent_created_untouched(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(last_activity_ms=now - 100 * DAY_MS, created_by="hub")}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "active"

    def test_never_active_anchors_created_at(self):
        """从未活跃(use_count=0)的年轻技能不自归档。"""
        now = int(time.time() * 1000)
        recs = {"s1": _rec(use_count=0, last_activity_ms=0, created_ms=now - 5 * DAY_MS)}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "active"

    def test_old_never_active_can_be_archived(self):
        """从未活跃但很老(created_at > 30 天)可归档。"""
        now = int(time.time() * 1000)
        recs = {"s1": _rec(state="active", use_count=0,
                           last_activity_ms=0, created_ms=now - 40 * DAY_MS)}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "archived"

    def test_pinned_stale_not_reactivated_side_effect(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(state="archived", pinned=True)}
        apply_transitions(_svc(recs), now_ms=now)
        assert recs["s1"]["usage"]["state"] == "archived"


class TestCounts:
    def test_counts_shape(self):
        now = int(time.time() * 1000)
        recs = {"s1": _rec(last_activity_ms=now - 15 * DAY_MS)}
        counts = apply_transitions(_svc(recs), now_ms=now)
        for k in ("marked_stale", "archived", "reactivated", "checked", "seeded"):
            assert k in counts

    def test_checked_counts_all(self):
        now = int(time.time() * 1000)
        recs = {
            "s1": _rec(last_activity_ms=now - 1 * DAY_MS),
            "s2": _rec(last_activity_ms=now - 15 * DAY_MS),
        }
        counts = apply_transitions(_svc(recs), now_ms=now)
        assert counts["checked"] == 2
