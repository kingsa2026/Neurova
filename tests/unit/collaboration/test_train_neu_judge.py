"""SB-3 离线训练脚本（train_neu_judge.py）单测——先红后绿的红灯件。

计划出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md
§5.3（训练数据与标签）、§5.5（评测与棘轮）与 §8-SB-3（离线训练脚本）。

覆盖面：
- 主流程冒烟：小样本跑 main → 产物生成且 schema 合法（版本/偏置/11 权重键/
  数据指纹/评估指标/灰区覆盖计数）；
- 可复现：同参数两次训练产物逐字节一致（固定种子 + 确定性哈希切分）；
- 质量门槛：冻结验证集准确率 ≥0.9 且 skip 类精确率/召回率 ≥0.9（合成数据
  可分性好，达不到即实现有错）；
- 可加载：产物经 NeuJudge.loadFrom 成功——这条同时是 neu_judge 版本策略
  修正（model_version 只要求非空字符串）的红灯件：重训产物
  model_version="0.2.0-trained" 必须能上岗；
- 方向正确：对「25 条独走」真实提取特征 p<0.25、对「人类在场」p>0.75
  （特征一律 extractTriageFeatures 从合成窗口现提，不手写特征字典造假）；
- feature_version 契约回归：不匹配仍拒载。

不使用 MagicMock 冒充业务对象；全部用真实 dict 事件与真实训练产物。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from neurova.collaboration.neu_judge import (
    FEATURE_KEYS,
    FEATURE_VERSION,
    NeuJudge,
    NeuJudgeUnavailable,
)
from neurova.collaboration.triage_rules import extractTriageFeatures

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "training" / "train_neu_judge.py"
)


def _loadScript():
    """按文件路径加载训练脚本模块（不依赖 scripts/training 是否为包）。"""
    spec = importlib.util.spec_from_file_location("train_neu_judge_under_test", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail(f"无法定位训练脚本: {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _loadCalibrateModule():
    """按路径加载标定脚本模块（供各测试类共用）。"""
    path = (Path(__file__).resolve().parents[3] / "scripts" / "training"
            / "calibrate_neu_judge.py")
    spec = importlib.util.spec_from_file_location("calibrate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    try:
        return _loadScript()
    except FileNotFoundError as exc:
        pytest.fail(f"SB-3 红灯：训练脚本尚未实现（{_SCRIPT_PATH}）: {exc}")


@pytest.fixture(scope="module")
def trained(tmp_path_factory, script):
    """模块级共享：小样本训练一次，返回产物路径与 payload。"""
    outPath = tmp_path_factory.mktemp("trained") / "neu_judge_trained.json"
    exitCode = script.main(["--windows", "160", "--seed", "42", "--out", str(outPath)])
    assert exitCode == 0
    payload = json.loads(outPath.read_text(encoding="utf-8"))
    return {"path": outPath, "payload": payload}


class TestTrainingPipeline:
    def testMainSmokeProducesValidArtifact(self, tmp_path, script):
        outPath = tmp_path / "neu_judge_trained.json"
        exitCode = script.main(["--windows", "120", "--seed", "7", "--out", str(outPath)])
        assert exitCode == 0
        assert outPath.exists()
        payload = json.loads(outPath.read_text(encoding="utf-8"))
        assert payload["model_version"] == "0.2.0-trained"
        assert payload["feature_version"] == FEATURE_VERSION == "triage-features-v1"
        assert isinstance(payload["bias"], float)
        assert not isinstance(payload["bias"], bool)
        assert set(payload["weights"]) == set(FEATURE_KEYS)
        assert len(payload["weights"]) == 11
        assert payload["data_fingerprint"].startswith("sha256:")
        metrics = payload["eval_metrics"]
        assert isinstance(metrics, dict)
        for key in (
            "accuracy",
            "skipPrecision",
            "skipRecall",
            "trainWindows",
            "frozenWindows",
            "greyZoneWindows",
            "greyZoneRatio",
        ):
            assert key in metrics, f"eval_metrics 缺 {key}"
        assert metrics["trainWindows"] > 0
        assert metrics["frozenWindows"] > 0
        # 灰区弃权窗口不进训练集，但必须被单独统计进覆盖率报告
        assert metrics["greyZoneWindows"] > 0
        assert 0.0 < metrics["greyZoneRatio"] < 1.0
        # 合成窗口必须让 11 个特征全部有方差（常量特征会被零权处理，
        # 意味着该特征在训练集中无信号——对本数据源即生成模板有错）
        assert metrics["constantFeatureCount"] == 0

    def testTrainingIsByteReproducible(self, tmp_path, script):
        firstPath = tmp_path / "first.json"
        secondPath = tmp_path / "second.json"
        script.main(["--windows", "120", "--seed", "42", "--out", str(firstPath)])
        script.main(["--windows", "120", "--seed", "42", "--out", str(secondPath)])
        assert firstPath.read_bytes() == secondPath.read_bytes()

    def testFrozenSetQualityGate(self, trained):
        metrics = trained["payload"]["eval_metrics"]
        assert metrics["accuracy"] >= 0.9, f"冻结集准确率 {metrics['accuracy']} < 0.9"
        assert metrics["skipRecall"] >= 0.9, f"skip 召回 {metrics['skipRecall']} < 0.9"
        assert metrics["skipPrecision"] >= 0.9, f"skip 精确率 {metrics['skipPrecision']} < 0.9"

    def testTrainedArtifactLoadsViaNeuJudge(self, trained):
        # SB-3 版本策略修正红灯件：重训产物 model_version="0.2.0-trained"
        # 必须能被 loadFrom 加载（model_version 是溯源元数据，不再精确比对）
        model = NeuJudge.loadFrom(trained["path"])
        assert model.modelVersion == "0.2.0-trained"
        assert model.featureVersion == FEATURE_VERSION
        assert set(model.weights) == set(FEATURE_KEYS)

    def testDirectionOnExtractedFeatures(self, trained):
        model = NeuJudge.loadFrom(trained["path"])
        base = datetime(2026, 11, 22, 12, 0, 0)

        # 25 条纯 assistant 独走：无人类、长独走、无复读、无提问
        soloEvents = [
            {
                "role": "assistant",
                "content": f"自动巡检任务进行中，第{i}轮未发现新的用户输入，继续等待。",
                "timestamp": (base + timedelta(seconds=30 * i)).isoformat(),
            }
            for i in range(25)
        ]
        soloFeatures = extractTriageFeatures(soloEvents, "")
        soloP = model.score(soloFeatures)
        assert soloP < 0.25, f"25 条独走 p={soloP} 应 <0.25"
        assert model.decide(soloP) == "skip"

        # 人类在场：8 条 assistant + 人类发言 + 1 条 assistant 回应
        humanEvents = [
            {
                "role": "assistant",
                "content": f"已完成第{i}项检查，结果正常。",
                "timestamp": (base + timedelta(seconds=20 * i)).isoformat(),
            }
            for i in range(8)
        ]
        humanEvents.append(
            {
                "role": "user",
                "content": "这个结果和预期不一致，帮我看看？",
                "timestamp": (base + timedelta(seconds=160)).isoformat(),
            }
        )
        humanEvents.append(
            {
                "role": "assistant",
                "content": "收到，我正在比对最近一次的输出。",
                "timestamp": (base + timedelta(seconds=185)).isoformat(),
            }
        )
        humanFeatures = extractTriageFeatures(humanEvents, "为什么和预期不一致？")
        humanP = model.score(humanFeatures)
        assert humanP > 0.75, f"人类在场 p={humanP} 应 >0.75"
        assert model.decide(humanP) == "allow"

    def testFeatureVersionMismatchStillRejected(self, trained, tmp_path):
        payload = dict(trained["payload"])
        payload["feature_version"] = "triage-features-v2"
        tampered = tmp_path / "tampered.json"
        tampered.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(tampered)


class TestRealSourceTraining:
    """D-SB3：--source real 从真实会话文件收割窗口训练（不再只有合成数据）。"""

    def testRealSourceMainTrainsFromSessionFiles(self, script, tmp_path):
        dataRoot = tmp_path / "data"

        def writeSession(agentDir: str, sessionId: str, messages: list) -> None:
            sessionsDir = dataRoot / agentDir / "sessions"
            sessionsDir.mkdir(parents=True, exist_ok=True)
            base = datetime(2026, 11, 22, 9, 0, 0)
            payload = {
                "agent_id": agentDir,
                "session_id": sessionId,
                "messages": [
                    {"role": m["role"], "content": m["content"],
                     "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
                    for i, m in enumerate(messages)
                ],
            }
            (sessionsDir / f"session_{sessionId}_2026-11-22.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        def alternating(count: int) -> list:
            msgs = [{"role": "user" if i % 2 == 0 else "assistant",
                     "content": f"问题{i}，各不相同。"} for i in range(count - 1)]
            msgs.append({"role": "user", "content": "最后一条人类消息"})
            return msgs

        def solo(count: int) -> list:
            return [{"role": "assistant", "content": f"独走{i}"} for i in range(count)]

        for i in range(6):
            writeSession(f"agentH{i}", f"human{i}", alternating(8))
        for i in range(6):
            writeSession(f"agentL{i}", f"loop{i}", solo(25))

        out = tmp_path / "artifact.json"
        rc = script.main([
            "--source", "real", "--data-root", str(dataRoot),
            "--out", str(out), "--min-messages", "6", "--max-windows", "50",
        ])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["model_version"] == "0.3.0-real"
        assert payload["feature_version"] == FEATURE_VERSION
        assert NeuJudge.loadFrom(out) is not None


class TestDistillImprovements:
    """D-SB1 增强：skip 样本回流直训 + 类平衡权重 + 分层切分。"""

    def _labelled(self, script, allowCount: int, skipCount: int) -> list:
        """用真实事件提取特征（不手写特征字典）：allow=人类收尾，skip=纯独走。"""
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)
        labelled = []
        for i in range(allowCount):
            events = []
            for j in range(10):
                events.append({"role": "user" if j % 2 == 0 else "assistant",
                               "content": f"人类问题{i}_{j}，各不相同？",
                               "timestamp": (base + timedelta(seconds=j)).isoformat()})
            events.append({"role": "user", "content": f"最后人类消息{i}",
                           "timestamp": (base + timedelta(seconds=99)).isoformat()})
            labelled.append({"sessionId": f"allow/{i}",
                             "features": script._prepareFeatureVector(
                                 extractTriageFeatures(events, "")), "label": 1.0})
        for i in range(skipCount):
            events = [{"role": "assistant", "content": f"独走消息 {i} 号，完全相同的句式。",
                       "timestamp": (base + timedelta(seconds=j)).isoformat()}
                      for j in range(25)]
            labelled.append({"sessionId": f"skip/{i}",
                             "features": script._prepareFeatureVector(
                                 extractTriageFeatures(events, "")), "label": 0.0})
        return labelled

    def testClassWeightsPreventSkipCollapse(self, script):
        """多数类压制下（40 放行 vs 6 拦截），类平衡权重必须让 skip 类仍可学。"""
        labelled = self._labelled(script, allowCount=40, skipCount=6)
        payload = script._trainAndEvaluate(labelled, 0, len(labelled), 42)
        metrics = payload["eval_metrics"]
        assert metrics["skipFrozenCount"] >= 1, "分层切分后冻结集必须含 skip 类"
        assert metrics["skipRecall"] > 0.0, "skip 召回不得塌缩为 0"
        assert metrics["skipPrecision"] > 0.0, "skip 精确率不得为 0"

    def testStratifiedSplitKeepsBothClassesInFrozen(self, script):
        labelled = self._labelled(script, allowCount=30, skipCount=4)
        payload = script._trainAndEvaluate(labelled, 0, len(labelled), 42)
        metrics = payload["eval_metrics"]
        assert metrics["skipFrozenCount"] >= 1 and metrics["allowFrozenCount"] >= 1

    def testIngestSkipFeedbackRows(self, script, tmp_path):
        """triage_skips.jsonl 直接回流：默认 not_actionable→0，改标 actionable→1。"""
        records = [
            {"sample_id": "aa11", "features": {k: 1.0 for k in FEATURE_KEYS},
             "label": "not_actionable"},
            {"sample_id": "bb22", "features": {k: 2.0 for k in FEATURE_KEYS},
             "label": "actionable", "relabeled": True},
        ]
        (tmp_path / "triage_skips.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
        rows = script._ingestSkipFeedback(str(tmp_path))
        assert len(rows) == 2
        byId = {r["sessionId"]: r for r in rows}
        assert byId["skipfb/aa11"]["label"] == 0.0
        assert byId["skipfb/bb22"]["label"] == 1.0
        assert sorted(byId["skipfb/aa11"]["features"].keys()) == sorted(FEATURE_KEYS)

    def testRealSourceTrainsWithSkipFeedback(self, script, tmp_path):
        """端到端：会话文件 + triage_skips.jsonl 同喂，skip 反馈样本计入训练。"""
        from datetime import datetime, timedelta, timezone

        dataRoot = tmp_path / "data"
        base = datetime(2026, 11, 22, 10, 0, 0, tzinfo=timezone.utc)

        def writeSession(agentDir: str, sessionId: str, messages: list):
            sessionsDir = dataRoot / agentDir / "sessions"
            sessionsDir.mkdir(parents=True, exist_ok=True)
            payload = {"agent_id": agentDir, "session_id": sessionId,
                       "messages": [{"role": m["role"], "content": m["content"],
                                     "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
                                    for i, m in enumerate(messages)]}
            (sessionsDir / f"session_{sessionId}_2026-11-22.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        for i in range(6):
            writeSession(f"agentH{i}", f"human{i}",
                         [{"role": "user" if j % 2 == 0 else "assistant",
                           "content": f"问题{i}_{j}，各不相同。"} for j in range(8)])
        for i in range(6):
            writeSession(f"agentL{i}", f"loop{i}",
                         [{"role": "assistant", "content": f"独走{i}号第{j}句。"} for j in range(25)])
        records = [
            {"sample_id": "fb1", "features": {k: 1.0 for k in FEATURE_KEYS},
             "label": "not_actionable"},
            {"sample_id": "fb2", "features": {k: 3.0 for k in FEATURE_KEYS},
             "label": "actionable"},
        ]
        (dataRoot / "triage_skips.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")

        out = tmp_path / "artifact.json"
        rc = script.main(["--source", "real", "--data-root", str(dataRoot),
                          "--out", str(out), "--min-messages", "6",
                          "--max-windows", "50", "--distill-scope", "gray"])
        assert rc == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["eval_metrics"]["skipFeedbackSamples"] == 2


    def testSoftLabelWeakenSkipSignal(self, script, tmp_path):
        """软标签（教师不自信 0.5）参与训练：指纹随之变化，产物仍可加载。"""
        labelled = self._labelled(script, allowCount=30, skipCount=4)
        softened = [dict(s) for s in labelled]
        for sample in softened:
            if sample["label"] == 0.0:
                sample["softLabel"] = 0.5
        hard = script._trainAndEvaluate(labelled, 0, len(labelled), 42)
        soft = script._trainAndEvaluate(softened, 0, len(softened), 42)
        assert hard["data_fingerprint"] != soft["data_fingerprint"]
        weightsPath = tmp_path / "soft.json"
        weightsPath.write_text(json.dumps(soft, ensure_ascii=False), encoding="utf-8")
        assert NeuJudge.loadFrom(weightsPath) is not None

    def testThresholdsWrittenToArtifactAndLoadable(self, script, tmp_path):
        labelled = self._labelled(script, allowCount=20, skipCount=6)
        payload = script._trainAndEvaluate(labelled, 0, len(labelled), 42,
                                           thresholds={"skip_p": 0.1, "allow_p": 0.9})
        assert payload["thresholds"] == {"skip_p": 0.1, "allow_p": 0.9}
        weightsPath = tmp_path / "calibrated.json"
        weightsPath.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        model = NeuJudge.loadFrom(weightsPath)
        assert model.decide(0.05) == "skip"   # 0.05 < 0.1
        assert model.decide(0.5) == "abstain"  # 0.1 ≤ 0.5 ≤ 0.9
        assert model.decide(0.95) == "allow"   # 0.95 > 0.9


class TestCalibrateScript:
    """标定脚本：真实评估集上反推零误拦的最大 skip_p，可写回产物。"""

    def testRecommendPrefersZeroFalseAlarm(self, script):
        cal = _loadCalibrateModule()
        rows = [
            {"features": {k: 1.0 for k in FEATURE_KEYS}, "label": 1.0},
            {"features": {k: 0.0 for k in FEATURE_KEYS}, "label": 0.0},
        ]

        class FakeJudge:
            def score(self, features):
                return 0.9 if features[FEATURE_KEYS[0]] > 0.5 else 0.05

        results = [cal.simulate(rows, FakeJudge(), skipP, 0.75)
                   for skipP in (0.1, 0.3, 0.5)]
        chosen = cal.recommend(results, targetPrecision=0.99)
        assert chosen is not None and chosen["falseAlarms"] == 0

    def testEndToEndCalibrationWritesThresholds(self, script, tmp_path):
        from datetime import datetime, timedelta, timezone

        base = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
        dataRoot = tmp_path / "data"

        def writeSession(agentDir, sessionId, messages):
            sessionsDir = dataRoot / agentDir / "sessions"
            sessionsDir.mkdir(parents=True, exist_ok=True)
            payload = {"agent_id": agentDir, "session_id": sessionId,
                       "messages": [{"role": m["role"], "content": m["content"],
                                     "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
                                    for i, m in enumerate(messages)]}
            (sessionsDir / f"session_{sessionId}_2026-11-22.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        for i in range(6):
            writeSession(f"agentH{i}", f"human{i}",
                         [{"role": "user" if j % 2 == 0 else "assistant",
                           "content": f"问题{i}_{j}，各不相同？"} for j in range(8)])
        for i in range(6):
            writeSession(f"agentL{i}", f"loop{i}",
                         [{"role": "assistant", "content": f"独走{i}号第{j}句。"}
                          for j in range(25)])

        # 先训一个可分模型（同数据根），再做标定
        trainedOut = tmp_path / "trained.json"
        assert script.main(["--source", "real", "--data-root", str(dataRoot),
                            "--out", str(trainedOut), "--min-messages", "6",
                            "--max-windows", "50"]) == 0

        cal = _loadCalibrateModule()
        assert cal.main(["--data-root", str(dataRoot), "--artifact", str(trainedOut),
                         "--max-allow", "40", "--apply"]) == 0
        calibrated = json.loads(trainedOut.read_text(encoding="utf-8"))
        assert "thresholds" in calibrated
        assert calibrated["thresholds"]["skip_p"] <= calibrated["thresholds"]["allow_p"]
        assert NeuJudge.loadFrom(trainedOut) is not None


class TestExternalLabelIngestion:
    """外部数据集/合成灰区标签注入：external_labels.jsonl → 训练行。

    答案先行：标签来自可观测结果或教师裁决（合成灰区由真分诊门打标），
    同会话规则/蒸馏标签被外部标签覆盖；灰区弃权窗带外部标签时补入训练
    （category="external"），评估指标透出 externalLabels/externalApplied。
    """

    def testIngestExternalLabelsParsesAndSkipsBadLines(self, script, tmp_path):
        labels = tmp_path / "external_labels.jsonl"
        lines = [
            json.dumps({"sessionId": "a/x", "label": 1, "softLabel": 0.9}),
            json.dumps({"sessionId": "b/y", "label": 0}),
            "not-json-line",
            json.dumps({"sessionId": "", "label": 1}),
            json.dumps({"sessionId": "c/z"}),
        ]
        labels.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = script._ingestExternalLabels(str(tmp_path))
        assert out == {"a/x": (1.0, 0.9), "b/y": (0.0, 0.0)}
        # 文件缺失 → 空映射（不报错，离线训练不因无外部数据中断）
        assert script._ingestExternalLabels(str(tmp_path / "missing")) == {}

    def testApplyExternalOverridesOverridesAndAppends(self, script):
        base = datetime(2026, 11, 22, 9, 0, 0)

        def events(tag: str) -> list:
            return [{"role": "assistant", "content": f"{tag}第{j}句，各不相同。",
                     "timestamp": (base + timedelta(seconds=j * 5)).isoformat()}
                    for j in range(5)]

        windows = [
            {"conversationId": "a/x", "events": events("甲")},
            {"conversationId": "c/z", "events": events("丙")},
        ]
        labelled = [{
            "sessionId": "a/x", "category": "llm_distill",
            "features": script._prepareFeatureVector(
                extractTriageFeatures(windows[0]["events"], "")),
            "label": 0.0, "softLabel": 0.3,
        }]
        applied = script._applyExternalOverrides(
            labelled, windows, {"a/x": (1.0, 0.9), "c/z": (0.0, 0.8)})
        assert applied == 2
        byId = {row["sessionId"]: row for row in labelled}
        # 同会话：外部标签覆盖旧标签与软标签
        assert byId["a/x"]["label"] == 1.0
        assert byId["a/x"]["softLabel"] == 0.9
        # 灰区弃权窗：带外部标签补入，category=external
        assert byId["c/z"]["category"] == "external"
        assert byId["c/z"]["label"] == 0.0
        assert byId["c/z"]["softLabel"] == 0.8

    def testSweepTrainingAbsorbsExternalLabels(self, script, tmp_path):
        dataRoot = tmp_path / "data"

        def writeSession(agentDir: str, sessionId: str, messages: list) -> None:
            sessionsDir = dataRoot / agentDir / "sessions"
            sessionsDir.mkdir(parents=True, exist_ok=True)
            base = datetime(2026, 11, 22, 9, 0, 0)
            payload = {"agent_id": agentDir, "session_id": sessionId,
                       "messages": [{"role": m["role"], "content": m["content"],
                                     "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
                                    for i, m in enumerate(messages)]}
            (sessionsDir / f"session_{sessionId}_2026-11-22.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        for i in range(6):
            writeSession(f"agentH{i}", f"human{i}",
                         [{"role": "user" if j % 2 == 0 else "assistant",
                           "content": f"问题{i}_{j}，各不相同？"} for j in range(8)])
        for i in range(6):
            writeSession(f"agentL{i}", f"loop{i}",
                         [{"role": "assistant", "content": f"独走{i}号第{j}句。"}
                          for j in range(25)])
        # 灰区窗（短独走、非逐字、规则弃权）+ 教师外部标签 → 应补入训练
        writeSession("synthGray", "synth",
                     [{"role": "assistant", "content": f"灰区独走第{j}句，进展与待确认并存。"}
                      for j in range(8)])
        (dataRoot / "external_labels.jsonl").write_text(
            json.dumps({"sessionId": "synthGray/synth", "label": 1,
                        "softLabel": 0.85, "source": "synth-gray"}) + "\n",
            encoding="utf-8")

        out = tmp_path / "artifact.json"
        assert script.main(["--source", "sweep", "--data-root", str(dataRoot),
                            "--out", str(out), "--distill", "0",
                            "--min-messages", "6", "--max-windows", "50"]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        metrics = payload["eval_metrics"]
        assert metrics["externalLabels"] == 1.0
        assert metrics["externalApplied"] == 1.0
        assert payload["model_version"] == "0.4.0-neurova"
        assert NeuJudge.loadFrom(out) is not None


class TestExcludeAgents:
    """--exclude-agents：按 agentDir 前缀整目录剔除会话（数据源消融）。"""

    def testExcludeAgentsDropsMatchingDirectories(self, script, tmp_path):
        dataRoot = tmp_path / "data"

        def writeSession(agentDir: str, sessionId: str, messages: list) -> None:
            sessionsDir = dataRoot / agentDir / "sessions"
            sessionsDir.mkdir(parents=True, exist_ok=True)
            base = datetime(2026, 11, 22, 9, 0, 0)
            payload = {"agent_id": agentDir, "session_id": sessionId,
                       "messages": [{"role": m["role"], "content": m["content"],
                                     "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
                                    for i, m in enumerate(messages)]}
            (sessionsDir / f"session_{sessionId}_2026-11-22.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        for i in range(9):
            writeSession(f"agentH{i}", f"human{i}",
                         [{"role": "user" if j % 2 == 0 else "assistant",
                           "content": f"问题{i}_{j}，各不相同？"} for j in range(8)])
        for i in range(6):
            writeSession(f"taubench-x{i}", f"t{i}",
                         [{"role": "assistant", "content": f"外部独走{i}号第{j}句。"}
                          for j in range(25)])

        out = tmp_path / "artifact.json"
        assert script.main(["--source", "real", "--data-root", str(dataRoot),
                            "--out", str(out), "--min-messages", "6",
                            "--max-windows", "50",
                            "--exclude-agents", "taubench"]) == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        metrics = payload["eval_metrics"]
        # 只剩 9 个人类在场会话入训；6 个外部独走会话被整目录剔除
        assert metrics["trainWindows"] + metrics["frozenWindows"] == 9

        # 不剔除时同数据根应多出 6 个 skip 训练行（15 行）
        out2 = tmp_path / "artifact_all.json"
        assert script.main(["--source", "real", "--data-root", str(dataRoot),
                            "--out", str(out2), "--min-messages", "6",
                            "--max-windows", "50"]) == 0
        metrics2 = json.loads(out2.read_text(encoding="utf-8"))["eval_metrics"]
        assert metrics2["trainWindows"] + metrics2["frozenWindows"] == 15


class TestRecommendObjectives:
    """标定推荐目标可配：零误拦（保守）/最大 F1（正确拦截率与覆盖并重）/代价加权。

    误杀与漏拦的代价不对称是业务假设而非定理：enforce 下误杀=静默终止
    一个需要人看的工作回合；漏拦=多花一轮 LLM 调用、agent 多说一轮。
    两种口径都要能一键出推荐，工作点由业务拍板。
    """

    def _rows(self):
        return [
            {"skip_p": 0.25, "skipped": 15, "tp": 15, "falseAlarms": 0, "missed": 6,
             "skipPrecision": 1.0, "skipRecall": 0.7143},
            {"skip_p": 0.45, "skipped": 21, "tp": 18, "falseAlarms": 3, "missed": 3,
             "skipPrecision": 0.8571, "skipRecall": 0.8571},
        ]

    def testZeroFpObjectiveKeepsConservativePick(self, script):
        cal = _loadCalibrateModule()
        chosen = cal.recommend(self._rows(), objective="zero-fp")
        assert chosen["skip_p"] == 0.25

    def testMaxF1ObjectiveBalancesPrecisionAndRecall(self, script):
        cal = _loadCalibrateModule()
        chosen = cal.recommend(self._rows(), objective="max-f1")
        # F1：0.25→0.833，0.45→0.857 → 取 0.45（多拦 3 个真 skip，代价 3 误拦）
        assert chosen["skip_p"] == 0.45

    def testCostObjectiveFollowsCostRatio(self, script):
        cal = _loadCalibrateModule()
        # 误拦:漏拦 = 10:1 → 零误拦行胜出
        assert cal.recommend(self._rows(), objective="cost",
                             fpCost=10.0, fnCost=1.0)["skip_p"] == 0.25
        # 误拦:漏拦 = 1:10 → 高召回行胜出
        assert cal.recommend(self._rows(), objective="cost",
                             fpCost=1.0, fnCost=10.0)["skip_p"] == 0.45


class TestMixAndScale:
    """10 万条级训练：数据揉合（固定种子洗牌再截断）+ numpy 向量化训练。"""

    def testMixWindowsDeterministicAndFair(self, script):
        windows = ([{"conversationId": f"a{i}/s"} for i in range(30)] +
                   [{"conversationId": f"z{i}/s"} for i in range(30)])
        mixed = script._mixWindows(windows, seed=42, maxWindows=30)
        assert len(mixed) == 30
        prefixes = {w["conversationId"][0] for w in mixed}
        assert prefixes == {"a", "z"}  # 揉合采样而非按路径截断
        again = script._mixWindows(windows, seed=42, maxWindows=30)
        assert [w["conversationId"] for w in mixed] == [w["conversationId"] for w in again]
        other = script._mixWindows(windows, seed=7, maxWindows=30)
        assert [w["conversationId"] for w in mixed] != [w["conversationId"] for w in other]

    def testNumpyTrainerAgreesWithPurePython(self, script):
        base = datetime(2026, 11, 22, 9, 0, 0)
        rows = []
        for i in range(40):
            events = [{"role": "user" if j % 2 == 0 else "assistant",
                       "content": f"问题{i}_{j}，各不相同？",
                       "timestamp": (base + timedelta(seconds=j)).isoformat()}
                      for j in range(8)]
            rows.append({"label": 1.0, "softLabel": 1.0,
                         "features": script._prepareFeatureVector(extractTriageFeatures(events, ""))})
        for i in range(40):
            events = [{"role": "assistant", "content": f"独走{i}号第{j}句，完全一样的句式。",
                       "timestamp": (base + timedelta(seconds=j)).isoformat()}
                      for j in range(25)]
            rows.append({"label": 0.0, "softLabel": 0.0,
                         "features": script._prepareFeatureVector(extractTriageFeatures(events, ""))})
        mean, sigma, _ = script._standardize([row["features"] for row in rows])
        saved = script._numpy
        try:
            script._numpy = None
            w1, b1, it1, _ = script._trainLogisticRegression(rows, mean, sigma, __import__("random").Random(42))
            script._numpy = __import__("numpy")
            w2, b2, it2, _ = script._trainLogisticRegression(rows, mean, sigma, __import__("random").Random(42))
        finally:
            script._numpy = saved
        for key in FEATURE_KEYS:
            assert abs(w1[key] - w2[key]) < 0.05, f"{key} 两路径权重差异过大"
        assert abs(b1 - b2) < 0.05

    def testBuildEvalSetExcludesBulkExternalSources(self, script, tmp_path):
        cal = _loadCalibrateModule()
        dataRoot = tmp_path / "data"
        def writeSession(agentDir, sessionId):
            sd = dataRoot / agentDir / "sessions"
            sd.mkdir(parents=True, exist_ok=True)
            base = datetime(2026, 11, 22, 9, 0, 0)
            payload = {"agent_id": agentDir, "session_id": sessionId,
                       "messages": [{"role": "user" if j % 2 == 0 else "assistant",
                                     "content": f"问题{sessionId}_{j}，各不相同？",
                                     "timestamp": (base + timedelta(seconds=j * 5)).isoformat()}
                                    for j in range(8)]}
            (sd / f"session_{sessionId}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        for i in range(6):
            writeSession(f"agentH{i}", f"human{i}")
        for i in range(6):
            writeSession(f"glaive-x{i}", f"g{i}")
        rows = cal.buildEvalSet(str(dataRoot), maxAllow=60)
        allowRows = [r for r in rows if r["label"] == 1.0]
        # 大体积外部源不进评估集：放行侧只来自真实房间会话（6 行）
        assert len(allowRows) == 6
