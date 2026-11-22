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
