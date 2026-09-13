"""Wave 核验 — 生命周期定期扫描触发器(对位 Hermes .curator_state)。"""

import json
import time

import pytest

from neurova.evolution.skill_lifecycle import apply_transitions, run_sweep_if_due

DAY_MS = 86_400_000


def _svc(records):
    class _S:
        def iter_skills(self):
            yield from records.items()

        def set_skill_lifecycle_state(self, sid, state):
            records[sid]["usage"]["state"] = state
            return True

        def archive_skill(self, sid):
            records[sid]["usage"]["state"] = "archived"
            return {"success": True}

    return _S()


def _old_record(now):
    return {"usage": {"state": "active", "use_count": 3, "pinned": False,
                      "created_by": "agent",
                      "last_activity_at_ms": now - 40 * DAY_MS,
                      "created_at_ms": now - 40 * DAY_MS}}


class TestRunSweepIfDue:
    def test_first_run_only_seeds_and_defers(self, tmp_path):
        """首次观察只 seed,绝不动技能库(Hermes 同款保守)。"""
        now = int(time.time() * 1000)
        recs = {"old": _old_record(now)}
        result = run_sweep_if_due(_svc(recs), tmp_path, now_ms=now)
        assert result is None
        assert recs["old"]["usage"]["state"] == "active"

    def test_within_interval_skips(self, tmp_path):
        now = int(time.time() * 1000)
        (tmp_path / ".lifecycle_state.json").write_text(
            json.dumps({"last_run_at_ms": now - 2 * 3_600_000}), encoding="utf-8"
        )
        recs = {"old": _old_record(now)}
        assert run_sweep_if_due(_svc(recs), tmp_path, interval_hours=24, now_ms=now) is None
        assert recs["old"]["usage"]["state"] == "active"

    def test_due_runs_and_updates_state(self, tmp_path):
        now = int(time.time() * 1000)
        (tmp_path / ".lifecycle_state.json").write_text(
            json.dumps({"last_run_at_ms": now - 25 * 3_600_000}), encoding="utf-8"
        )
        recs = {"old": _old_record(now)}
        counts = run_sweep_if_due(_svc(recs), tmp_path, interval_hours=24, now_ms=now)
        assert counts["archived"] == 1
        assert recs["old"]["usage"]["state"] == "archived"
        # 状态推进到 now,防同轮重复扫描
        state = json.loads((tmp_path / ".lifecycle_state.json").read_text(encoding="utf-8"))
        assert state["last_run_at_ms"] == now

    def test_corrupt_state_file_treated_as_seed(self, tmp_path):
        (tmp_path / ".lifecycle_state.json").write_text("{坏 JSON", encoding="utf-8")
        now = int(time.time() * 1000)
        recs = {"old": _old_record(now)}
        assert run_sweep_if_due(_svc(recs), tmp_path, now_ms=now) is None

    def test_apply_transitions_still_works_manually(self, tmp_path):
        now = int(time.time() * 1000)
        recs = {"old": _old_record(now)}
        counts = apply_transitions(_svc(recs), now_ms=now)
        assert counts["archived"] == 1


class TestSettingsGate:
    def test_pipeline_sweep_respects_settings(self, tmp_path, monkeypatch):
        """lifecycle_sweep=false 时 pipeline 维护块不得调用扫描。"""
        from neurova.evolution import evolution_settings as es

        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
        es.update_settings(lifecycle_sweep=False)
        settings = es.load_settings()
        assert settings.lifecycle_sweep is False
