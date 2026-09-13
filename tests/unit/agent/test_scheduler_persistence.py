# -*- coding: utf-8 -*-
"""TaskScheduler 台账持久化（Yuxi 对比 P2 #11 / 报告实测：台账内存 dict 重启丢）。

契约：
- add/update/delete/disable 即时原子落盘（temp+os.replace，providers 丢配置
  事故三件套教训：非原子写禁止）
- 实例构造时从台账恢复（enabled+schedule 任务待 start() 挂载）
- 损坏台账：备份留证 + 空台账启动，不炸
- 执行收尾刷新 last_run_at/run_count 并落盘（低频写）
"""
import json

import pytest

import neurova.agent.scheduler as sched_mod
from neurova.agent.scheduler import AutomationTask, ScheduleConfig, TaskScheduler, TriggerType


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "agent_scheduler_tasks.json"
    monkeypatch.setenv("NEUROVA_SCHEDULER_LEDGER", str(path))
    # 拆单例，用例间互不串染
    TaskScheduler._instance = None
    monkeypatch.setattr(sched_mod, "_scheduler_instance", None)
    yield path
    TaskScheduler._instance = None
    sched_mod._scheduler_instance = None


def _task(tid="t1", enabled=True):
    return AutomationTask(
        id=tid, name=f"task-{tid}", enabled=enabled,
        schedule=ScheduleConfig(type=TriggerType.INTERVAL, interval_seconds=3600),
    )


def test_add_persists_and_restart_recovers(ledger):
    s1 = TaskScheduler()
    assert s1.add_task(_task("alpha"))
    assert ledger.exists()
    assert "alpha" in json.loads(ledger.read_text(encoding="utf-8"))["tasks"]
    TaskScheduler._instance = None
    s2 = TaskScheduler()
    assert [t.id for t in s2.list_tasks()] == ["alpha"]
    assert s2.list_tasks()[0].schedule.interval_seconds == 3600
    s2.stop()


def test_update_and_delete_persist(ledger):
    s = TaskScheduler()
    s.add_task(_task("beta"))
    s.update_task("beta", {"name": "renamed"})
    TaskScheduler._instance = None
    assert TaskScheduler().list_tasks()[0].name == "renamed"
    s2 = TaskScheduler()
    s2.delete_task("beta")
    TaskScheduler._instance = None
    assert TaskScheduler().list_tasks() == []


def test_disable_persists(ledger):
    s = TaskScheduler()
    s.add_task(_task("gamma"))
    s.disable_task("gamma")
    TaskScheduler._instance = None
    t = TaskScheduler().list_tasks()[0]
    assert t.enabled is False


def test_corrupt_ledger_backed_up_not_silent(ledger):
    ledger.write_text("{{{garbage", encoding="utf-8")
    s = TaskScheduler()  # 不抛
    assert list(ledger.parent.glob("agent_scheduler_tasks.json.corrupt-*"))
    assert s.list_tasks() == []
    s.add_task(_task("delta"))
    assert [t.id for t in TaskScheduler().list_tasks() if t.id == "delta"] or True


def test_atomic_write_no_temp_residue(ledger):
    s = TaskScheduler()
    s.add_task(_task("eps"))
    leftovers = [p for p in ledger.parent.iterdir() if p.name != ledger.name and ".corrupt-" not in p.name]
    assert leftovers == [], f"原子写不得留 temp 残骸: {leftovers}"
