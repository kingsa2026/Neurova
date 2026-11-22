# -*- coding: utf-8 -*-
"""D-SB1/D-SB3 训练数据集构建：真实会话窗口收割 + 规则/离线蒸馏弱标注。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.3 训练数据三级来源（D-SB1 离线 LLM 蒸馏 / D-SB3 真实训练数据源）与 §8。

覆盖面：
- 收割（harvestSessionWindows）：真实会话 JSON 格式（role/content/timestamp）、
  短会话跳过、损坏文件跳过、maxWindows 封顶、conversationId=agentDir/sessionId；
- 标注（labelWindows）：规则高置信区直接打标（人类在场→1、独走环→0）、
  灰区（default_allow）无蒸馏配额时弃权不入训、注入 triageFn 后灰区蒸馏打标、
  蒸馏配额封顶、triageFn 异常计 distillErrors 且不外抛；
- realGateTriageFn：把窗口灌进真实 SessionSyncManager 并调真分诊门——
  无凭据环境下诚实抛 TriageGateError（种子会话已落，可断言接线本身）。

不使用 MagicMock；triageFn 用手写确定性函数（注入边界，非业务对象冒充）。
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

from neurova.collaboration.triage_rules import extractTriageFeatures  # noqa: E402

FEATURE_KEYS = sorted(extractTriageFeatures([], "").keys())


def _writeSession(dataRoot: Path, agentDir: str, sessionId: str, messages: list) -> Path:
    """按仓内真实会话落盘格式写一个会话文件（role/content/timestamp）。"""
    sessionsDir = dataRoot / agentDir / "sessions"
    sessionsDir.mkdir(parents=True, exist_ok=True)
    path = sessionsDir / f"session_{sessionId}_2026-11-22.json"
    base = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
    payload = {
        "agent_id": agentDir,
        "session_id": sessionId,
        "session_date": "2026-11-22",
        "messages": [
            {
                "role": m["role"],
                "content": m["content"],
                "timestamp": (base + timedelta(seconds=i * 5)).isoformat(),
            }
            for i, m in enumerate(messages)
        ],
        "created_at": base.isoformat(),
        "updated_at": base.isoformat(),
        "total_messages": len(messages),
        "title": sessionId,
        "user_id": "seed-user",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _alternating(count: int, prefix: str = "普通问题") -> list:
    """人类收尾的交替会话（最后一手是人类→规则高置信放行）。"""
    msgs = []
    for i in range(count - 1):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"{prefix} 第{i}句，内容各不相同。"})
    msgs.append({"role": "user", "content": "最后一条人类消息"})
    return msgs


def _soloLoop(count: int) -> list:
    """纯 assistant 独走环（无人类）→规则高置信拦截。"""
    return [{"role": "assistant", "content": f"独走消息第{i}条，内容互不相同。"} for i in range(count)]


class TestHarvestSessionWindows:
    def testHarvestReadsRealSessionFormat(self, tmp_path):
        from neurova.collaboration.triage_dataset import harvestSessionWindows

        _writeSession(tmp_path, "agentA", "s1", _alternating(8))
        windows = harvestSessionWindows(tmp_path, maxWindows=10, minMessages=6)
        assert len(windows) == 1
        window = windows[0]
        assert window["conversationId"] == "agentA/s1"
        assert len(window["events"]) == 8
        assert window["events"][0]["role"] == "user"
        assert window["events"][-1]["role"] == "user"
        assert window["events"][0]["timestamp"].startswith("2026-11-22T10:00:00")

    def testHarvestSkipsShortSessionsAndCaps(self, tmp_path):
        from neurova.collaboration.triage_dataset import harvestSessionWindows

        _writeSession(tmp_path, "agentA", "rich1", _alternating(8))
        _writeSession(tmp_path, "agentA", "rich2", _soloLoop(25))
        _writeSession(tmp_path, "agentB", "tiny", _alternating(3))
        windows = harvestSessionWindows(tmp_path, maxWindows=1, minMessages=6)
        assert len(windows) == 1  # 封顶生效
        assert windows[0]["conversationId"] == "agentA/rich1"  # 排序确定、短会话被跳过

    def testHarvestSkipsCorruptFile(self, tmp_path):
        from neurova.collaboration.triage_dataset import harvestSessionWindows

        _writeSession(tmp_path, "agentA", "good", _alternating(8))
        bad = tmp_path / "agentB" / "sessions"
        bad.mkdir(parents=True, exist_ok=True)
        (bad / "session_bad_2026-11-22.json").write_text("{not json", encoding="utf-8")
        windows = harvestSessionWindows(tmp_path, maxWindows=10, minMessages=6)
        assert len(windows) == 1 and windows[0]["conversationId"] == "agentA/good"

    def testHarvestEmptyDataRoot(self, tmp_path):
        from neurova.collaboration.triage_dataset import harvestSessionWindows

        assert harvestSessionWindows(tmp_path, maxWindows=10, minMessages=6) == []


class TestLabelWindows:
    def testRuleLabelsHighConfidenceWindows(self, tmp_path):
        from neurova.collaboration.triage_dataset import labelWindows

        windows = [
            {"conversationId": "a/human", "events": _alternating(8)},
            {"conversationId": "a/loop", "events": _soloLoop(25)},
        ]
        result = labelWindows(windows, distillLimit=0)
        byId = {e["conversationId"]: e for e in result["labeled"]}
        assert byId["a/human"]["label"] == 1 and byId["a/human"]["labeler"] == "rules"
        assert byId["a/human"]["reason"] == "human_last"
        assert byId["a/loop"]["label"] == 0 and byId["a/loop"]["labeler"] == "rules"
        assert byId["a/loop"]["reason"] == "agent_loop_no_human"
        assert result["grayUnlabeled"] == 0 and result["distillUsed"] == 0
        # 特征单源：每个标注样本带全量 11 键特征
        for entry in result["labeled"]:
            assert sorted(entry["features"].keys()) == FEATURE_KEYS

    def testGrayWindowWithoutDistillStaysUnlabeled(self, tmp_path):
        from neurova.collaboration.triage_dataset import labelWindows

        windows = [{"conversationId": "a/gray", "events": _soloLoop(12)}]
        result = labelWindows(windows, distillLimit=0)
        assert result["labeled"] == []
        assert result["grayUnlabeled"] == 1

    def testGrayWindowDistilledViaInjectedTriageFn(self, tmp_path):
        from neurova.collaboration.triage_dataset import labelWindows

        windows = [{"conversationId": "a/gray", "events": _soloLoop(12)}]

        def fakeGate(window):  # 手写确定性注入（非 MagicMock）
            return False  # 蒸馏结论：不可响应

        result = labelWindows(windows, distillLimit=1, triageFn=fakeGate)
        assert result["distillUsed"] == 1
        assert result["grayUnlabeled"] == 0
        entry = result["labeled"][0]
        assert entry["label"] == 0 and entry["labeler"] == "llm_distill"

    def testDistillCapRespected(self, tmp_path):
        from neurova.collaboration.triage_dataset import labelWindows

        windows = [{"conversationId": f"a/gray{i}", "events": _soloLoop(12)} for i in range(2)]
        calls = []

        def fakeGate(window):
            calls.append(window["conversationId"])
            return False

        result = labelWindows(windows, distillLimit=1, triageFn=fakeGate)
        assert len(calls) == 1 and result["distillUsed"] == 1
        assert result["grayUnlabeled"] == 1

    def testDistillErrorLeavesWindowUnlabeled(self, tmp_path):
        from neurova.collaboration.triage_dataset import labelWindows

        windows = [{"conversationId": "a/gray", "events": _soloLoop(12)}]

        def brokenGate(window):
            raise RuntimeError("凭据缺失")

        result = labelWindows(windows, distillLimit=1, triageFn=brokenGate)
        assert result["distillErrors"] == 1 and result["labeled"] == []


class TestRealGateTriageFn:
    def testSeedsRealSessionManagerAndFailsHonestlyWithoutCredentials(self, monkeypatch):
        """无 LLM 凭据时真分诊门诚实抛 TriageGateError；但窗口种子必须已落
        SessionSyncManager（接线本身可验）。"""
        from neurova.collaboration.triage_dataset import realGateTriageFn
        from neurova.llm.triage import TriageGateError
        from neurova.sync import session_sync_manager as ssm
        from neurova.sync.session_sync_manager import SessionSyncManager

        ssm.reset_session_sync_manager()
        manager = SessionSyncManager(
            config={"max_sessions": 200, "session_timeout": 3600, "max_history_size": 5000}
        )
        monkeypatch.setattr(ssm, "_manager_instance", manager)
        window = {"conversationId": "agentA/s1", "events": _alternating(8)}

        with pytest.raises(TriageGateError):
            realGateTriageFn(window)
        assert manager.get_session("distill::agentA/s1") is not None
