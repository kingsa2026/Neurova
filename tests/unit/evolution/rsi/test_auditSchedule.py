# -*- coding: utf-8 -*-
"""D2 审计预定表（survey §10.2）——独立审计只读预定时刻，表外被拒。

"看了测试分再挑点"是选点污染：审计者若能事后任选时刻取快照，就总能挑到
对自己有利的那个。预定表在序列启动前写死（步长固定），命中时点由编排器
封存快照；表外审计请求被拒并点名理由。
"""

import pytest

from neurova.evolution.rsi.audit_schedule import AuditSchedule


def test_off_schedule_audit_request_rejected():
    """红灯判据本体：表外时刻的审计请求被拒并点名理由。"""
    schedule = AuditSchedule(None, stride=10)
    with pytest.raises(KeyError, match="不在预定审计表"):
        schedule.readAuditSnapshot(7)  # 表外挑点


def test_scheduled_point_snapshot_roundtrip(tmp_path):
    schedule = AuditSchedule(tmp_path / "audit.json", stride=10)
    assert schedule.isScheduled(10) and schedule.isScheduled(20)
    assert not schedule.isScheduled(15)
    assert schedule.recordSnapshot(10, {"sealed_evidence": {"state": "measured"}})
    # 落盘可读回（新实例读同一文件）
    reopened = AuditSchedule(tmp_path / "audit.json", stride=10)
    readout = reopened.readAuditSnapshot(10)
    assert readout["state"] == "measured"
    assert readout["snapshot"]["sealed_evidence"]["state"] == "measured"


def test_scheduled_but_not_yet_reached_reports_unevidenced():
    schedule = AuditSchedule(None, stride=10)
    readout = schedule.readAuditSnapshot(30)
    assert readout["state"] == "unevidenced"
    assert "尚未到达" in readout["reason"]


def test_off_schedule_record_also_rejected():
    """封存侧同样只认预定时刻（运行中不许私加审计点）。"""
    schedule = AuditSchedule(None, stride=10)
    assert schedule.recordSnapshot(7, {"x": 1}) is False
    with pytest.raises(KeyError):
        schedule.readAuditSnapshot(7)
