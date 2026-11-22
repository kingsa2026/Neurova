# -*- coding: utf-8 -*-
"""Axion 方学落地（triage_axion.py）单测——答案先行结果采矿、边界扫描去重、
教师质量门、端到端管线。

不使用 MagicMock；教师用手写确定性函数（注入边界）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.collaboration.triage_axion import (  # noqa: E402
    boundarySweepWindows,
    buildAxionDataset,
    mineOutcomeLabels,
    teacherAgreement,
)
from neurova.collaboration.triage_rules import extractTriageFeatures  # noqa: E402

FEATURE_KEYS = sorted(extractTriageFeatures([], "").keys())


def _writeSession(dataRoot: Path, agentDir: str, sessionId: str, messages: list) -> Path:
    sessionsDir = dataRoot / agentDir / "sessions"
    sessionsDir.mkdir(parents=True, exist_ok=True)
    path = sessionsDir / f"session_{sessionId}_2026-11-22.json"
    payload = {"agent_id": agentDir, "session_id": sessionId, "messages": messages}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class TestMineOutcomeLabels:
    def testFalseKillAndTrueSkip(self, tmp_path):
        """recorded_at 后 5 分钟内人类回归=误杀；10 分钟后回归=真跳过。"""
        recorded = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        # 会话一：skip 后 2 分钟人类回归 → 误杀
        _writeSession(tmp_path, "project_a", "project_a", [
            {"role": "assistant", "content": "独走",
             "timestamp": _iso(recorded - timedelta(minutes=1))},
            {"role": "user", "content": "我回来了",
             "timestamp": _iso(recorded + timedelta(minutes=2))},
        ])
        # 会话二：skip 后 10 分钟人类才回归 → 真跳过
        _writeSession(tmp_path, "project_b", "project_b", [
            {"role": "assistant", "content": "独走",
             "timestamp": _iso(recorded - timedelta(minutes=1))},
            {"role": "user", "content": "我回来了",
             "timestamp": _iso(recorded + timedelta(minutes=10))},
        ])
        records = [
            {"sample_id": "s1", "conversation_id": "project_a",
             "recorded_at": _iso(recorded),
             "features": {k: 1.0 for k in FEATURE_KEYS}},
            {"sample_id": "s2", "conversation_id": "project_b",
             "recorded_at": _iso(recorded),
             "features": {k: 2.0 for k in FEATURE_KEYS}},
        ]
        (tmp_path / "triage_skips.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        rows = mineOutcomeLabels(str(tmp_path))
        assert len(rows) == 2
        byId = {r["sessionId"]: r for r in rows}
        assert byId["outcome/s1"]["label"] == 1.0
        assert byId["outcome/s1"]["outcome"] == "false_kill"
        assert byId["outcome/s1"]["returnAfterSec"] == 120.0
        assert byId["outcome/s2"]["label"] == 0.0
        assert byId["outcome/s2"]["outcome"] == "true_skip"

    def testNaiveTimestampBothZonesTried(self, tmp_path):
        """naive 落盘时间依次按 CST/UTC 解释——两种口径都能命中。"""
        recorded = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        # naive 写成 UTC 口径（12:10Z）——CST 解释不命中，UTC 兜底命中
        _writeSession(tmp_path, "project_c", "project_c", [
            {"role": "user", "content": "回归",
             "timestamp": (recorded + timedelta(minutes=3)).replace(tzinfo=None).isoformat()},
        ])
        records = [{"sample_id": "s3", "conversation_id": "project_c",
                    "recorded_at": _iso(recorded),
                    "features": {k: 1.0 for k in FEATURE_KEYS}}]
        (tmp_path / "triage_skips.jsonl").write_text(json.dumps(records[0]), encoding="utf-8")
        rows = mineOutcomeLabels(str(tmp_path))
        assert rows[0]["label"] == 1.0 and rows[0]["outcome"] == "false_kill"


class TestBoundarySweep:
    def testVariantsDedupeByFeatureKeyAndCap(self):
        seeds = [{"conversationId": "seed0", "events": [
            {"role": "assistant", "content": f"独走第{i}句，各不相同。",
             "timestamp": _iso(datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
                               + timedelta(seconds=i * 5))} for i in range(30)]}]
        variants = boundarySweepWindows(seeds, maxTotal=100)
        keys = [v["featureKey"] for v in variants]
        assert len(keys) == len(set(keys)), "特征向量必须去重"
        assert len(variants) <= 100
        # 每个变体都能被单源特征提取器还原出 11 键
        for variant in variants[:3]:
            assert sorted(extractTriageFeatures(variant["events"], "").keys()) == FEATURE_KEYS

    def testPerSeedCapRespected(self):
        seeds = [{"conversationId": f"seed{i}", "events": [
            {"role": "assistant", "content": f"种子{i}独走第{j}句。",
             "timestamp": _iso(datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
                               + timedelta(seconds=j * 5))} for j in range(30)]}
            for i in range(5)]
        variants = boundarySweepWindows(seeds, maxVariantsPerSeed=3, maxTotal=100)
        perSeed = {}
        for variant in variants:
            seed = variant["conversationId"].split("/")[1]
            perSeed[seed] = perSeed.get(seed, 0) + 1
        assert all(count <= 3 for count in perSeed.values())


class TestTeacherAgreement:
    def testLowAgreementDetected(self):
        known = [{"sessionId": f"s{i}", "events": [], "label": 1.0} for i in range(5)]

        def wrongTeacher(sample):
            return False  # 与结果（actionable）全不一致

        result = teacherAgreement(known, wrongTeacher, limit=5)
        assert result["checked"] == 5 and result["agreement"] == 0.0

    def testTeacherExceptionSkipsBudget(self):
        known = [{"sessionId": "s0", "events": [], "label": 1.0}]

        def brokenTeacher(sample):
            raise RuntimeError("教师不可用")

        result = teacherAgreement(known, brokenTeacher, limit=5)
        assert result["checked"] == 0 and result["agreement"] is None


class TestBuildAxionDataset:
    def testEndToEndWithInjectedTeacher(self, tmp_path):
        recorded = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        # 两个会话：一个 skip 后人类快速回归（误杀），一个纯独走长环（真跳过）
        _writeSession(tmp_path, "project_a", "project_a", [
            {"role": "assistant", "content": "独走",
             "timestamp": _iso(recorded - timedelta(minutes=1))},
            {"role": "user", "content": "我回来了",
             "timestamp": _iso(recorded + timedelta(minutes=2))},
        ])
        _writeSession(tmp_path, "project_b", "project_b", [
            {"role": "assistant", "content": f"独走第{j}句。",
             "timestamp": _iso(recorded - timedelta(minutes=1) + timedelta(seconds=j * 5))}
            for j in range(25)
        ])
        records = [
            {"sample_id": "s1", "conversation_id": "project_a",
             "recorded_at": _iso(recorded),
             "features": {k: 1.0 for k in FEATURE_KEYS}},
        ]
        (tmp_path / "triage_skips.jsonl").write_text(json.dumps(records[0]), encoding="utf-8")

        teacherCalls = []

        def fakeTeacher(sample):
            teacherCalls.append(sample.get("sessionId") or sample.get("conversationId"))
            if "label" in sample:
                return sample["label"] == 1.0  # 教师与结果一致（质量门用）
            return True  # 边界扫描变体一律判可响应

        result = buildAxionDataset(str(tmp_path), fakeTeacher, distillLimit=10,
                                   maxWindows=50, minMessages=2, maxSweepVectors=20)
        labels = {row["sessionId"]: row["label"] for row in result["labeled"]}
        assert result["outcomeSamples"] == 1
        assert result["aborted"] is False
        assert result["teacherAgreement"]["agreement"] == 1.0
        assert result["sweepVectors"] >= 1
        # 规则标签与结果标签都在训练行里
        assert any(sid.startswith("outcome/") for sid in labels)
        assert any("axion/" in sid or sid.startswith("sweep/") for sid in labels)
        assert result["distillUsed"] <= 10

    def testAbortsWhenTeacherUnreliable(self, tmp_path):
        recorded = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        _writeSession(tmp_path, "project_a", "project_a", [
            {"role": "assistant", "content": "独走",
             "timestamp": _iso(recorded - timedelta(minutes=1))},
            {"role": "user", "content": "我回来了",
             "timestamp": _iso(recorded + timedelta(minutes=2))},
        ])
        records = [{"sample_id": "s1", "conversation_id": "project_a",
                    "recorded_at": _iso(recorded),
                    "features": {k: 1.0 for k in FEATURE_KEYS}}]
        (tmp_path / "triage_skips.jsonl").write_text(json.dumps(records[0]), encoding="utf-8")

        def wrongTeacher(sample):
            return False  # 教师与已知结果全不一致

        result = buildAxionDataset(str(tmp_path), wrongTeacher, distillLimit=10,
                                   maxWindows=50, minMessages=2)
        assert result["aborted"] is True
        assert result["sweepVectors"] == 0
