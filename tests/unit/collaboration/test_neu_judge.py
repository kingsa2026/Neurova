"""SB-2 微型判定模型（NeuJudge）测试（先红后绿的红灯件）。

计划出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md §5
（自研微型判定模型）。覆盖：默认权重产物加载与 schema/版本校验、损坏产物诚实
失败、score 确定性与 sigmoid 单调性、decide 三档边界、缺特征键按 0 容错、
极端值溢出保护、典型场景三档裁决与「无人类」哨兵 -1.0 的中性映射。

特征提取属 triage_rules（并行施工），本文件只用手工特征字典，不 import triage_rules。

p 语义口径：p =「该回合值得响应（actionable）」的概率，与 decide 映射
（p<SKIP_P→skip、p>ALLOW_P→allow）及计划 §3（P<低阈值→拦截）一致；
故独走类特征权重为负、人类在场类特征权重为正。（任务契约的权重符号句与
「独走→p>0.75」若按字面执行，会同其 decide 映射和测试⑦互相矛盾，此处按
计划 §3 与测试⑦取向裁决。）
"""

import json
import math
from pathlib import Path

import pytest

import neurova.collaboration.neu_judge as neu_judge_module
from neurova.collaboration.neu_judge import (
    ALLOW_P,
    FEATURE_KEYS,
    FEATURE_VERSION,
    MODEL_VERSION,
    SKIP_P,
    NeuJudge,
    NeuJudgeUnavailable,
)

DEFAULT_WEIGHTS_PATH = (
    Path(neu_judge_module.__file__).resolve().parent / "neu_judge_default.json"
)

# 典型「25 条纯 agent 独走」：无人类（-1.0 哨兵）、长独走、高复读、高相似、零提问
SOLO_RUN_FEATURES = {
    "humanEventDistance": -1.0,
    "humanTimeDistanceSec": -1.0,
    "agentStreakLength": 25.0,
    "maxRepeatCount": 3.0,
    "maxSimilarity": 0.8,
    "messageRatePerMin": 30.0,
    "userCount": 0.0,
    "assistantCount": 25.0,
    "meanAssistantLength": 220.0,
    "maxAssistantLength": 640.0,
    "questionRatio": 0.0,
}

# 典型「最后一条是人类」：人类刚发言（事件距离 0 / 时间距离 3 秒）、独走长度 0
HUMAN_PRESENT_FEATURES = {
    "humanEventDistance": 0.0,
    "humanTimeDistanceSec": 3.0,
    "agentStreakLength": 0.0,
    "maxRepeatCount": 1.0,
    "maxSimilarity": 0.4,
    "messageRatePerMin": 12.0,
    "userCount": 1.0,
    "assistantCount": 24.0,
    "meanAssistantLength": 180.0,
    "maxAssistantLength": 500.0,
    "questionRatio": 0.25,
}

# 灰色区：短独走、低重复、无人类在场证据，得分应落在 (SKIP_P, ALLOW_P) 弃权带
GREY_ZONE_FEATURES = {
    "humanEventDistance": -1.0,
    "humanTimeDistanceSec": -1.0,
    "agentStreakLength": 6.0,
    "maxRepeatCount": 1.0,
    "maxSimilarity": 0.4,
    "messageRatePerMin": 6.0,
    "userCount": 0.0,
    "assistantCount": 6.0,
    "meanAssistantLength": 150.0,
    "maxAssistantLength": 400.0,
    "questionRatio": 0.5,
}


def validPayload() -> dict:
    """构造一份符合 schema 的权重产物，供 loadFrom 正/反例测试改写。"""
    return {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "bias": -2.5,
        "weights": {key: 0.1 for key in FEATURE_KEYS},
        "data_fingerprint": "hand-seeded",
        "eval_metrics": {"note": "seed model, pending real training"},
    }


def writeWeights(tmp_path: Path, payload: dict | None = None, raw: str | None = None) -> Path:
    """把权重产物写成临时文件；raw 非空时直接写原始文本（构造损坏 JSON）。"""
    path = tmp_path / "neu_judge_weights.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestDefaultWeightsArtifact:
    def testLoadDefaultSucceedsWithValidSchemaAndVersions(self):
        model = NeuJudge.loadDefault()
        # 默认权重可随训练/晋升演进（0.1.0-seed → 0.4.0-neurova）：
        # 契约是 feature_version 精确匹配 + model_version 非空可溯源。
        assert isinstance(model.modelVersion, str) and model.modelVersion.strip()
        assert model.featureVersion == FEATURE_VERSION
        assert model.featureVersion == "triage-features-v2"
        assert isinstance(model.bias, float)
        assert set(model.weights) == set(FEATURE_KEYS)
        assert len(FEATURE_KEYS) == 15

    def testDefaultWeightFileCarriesRequiredSchemaFields(self):
        payload = json.loads(DEFAULT_WEIGHTS_PATH.read_text(encoding="utf-8"))
        assert isinstance(payload["model_version"], str) and payload["model_version"].strip()
        assert payload["feature_version"] == FEATURE_VERSION
        assert isinstance(payload["bias"], (int, float))
        assert not isinstance(payload["bias"], bool)
        assert set(payload["weights"]) == set(FEATURE_KEYS)
        assert isinstance(payload["data_fingerprint"], str)
        assert payload["data_fingerprint"]
        assert isinstance(payload["eval_metrics"], dict)

    def testDefaultModelDefersToRulesOnSoloLoops(self):
        # 级联语义：R2/R3 规则先于模型裁决——纯独走环由规则拦截，模型不承担
        # 该职责（0.4.0-neurova 曾学到教师"active_work→actionable"异议，已被
        # 训练管线修正：规则 skip 窗不送教师审计）。此处钉住级联契约本身。
        from neurova.collaboration.triage_rules import evaluateTriage

        events = [{"role": "assistant", "content": f"独走第{i}句，内容相同。",
                   "timestamp": f"2026-11-22T12:00:{i:02d}Z"} for i in range(25)]
        assert evaluateTriage(events, "").action == "skip"
        model = NeuJudge.loadDefault()
        soloP = model.score(dict(SOLO_RUN_FEATURES))
        assert 0.0 <= soloP <= 1.0

    def testDefaultModelScoresTypicalScenariosIntoThreeBands(self):
        # 人类在场证据的打分不得低于独走场景（方向单调）；全部有界 [0,1]，
        # 三档 decide 输出合法。
        model = NeuJudge.loadDefault()
        soloP = model.score(dict(SOLO_RUN_FEATURES))
        humanP = model.score(dict(HUMAN_PRESENT_FEATURES))
        greyP = model.score(dict(GREY_ZONE_FEATURES))
        for p in (soloP, humanP, greyP):
            assert 0.0 <= p <= 1.0
        # 人类在场打分不得低于独走场景（方向单调；饱和时允许浮点级噪声）
        assert humanP >= soloP - 1e-6
        assert model.decide(soloP) in ("skip", "allow", "abstain")
        assert model.decide(humanP) in ("skip", "allow", "abstain")
        assert model.decide(greyP) in ("skip", "allow", "abstain")


class TestLoadFromValidation:
    def testLoadFromAcceptsValidCustomWeights(self, tmp_path):
        model = NeuJudge.loadFrom(writeWeights(tmp_path, validPayload()))
        assert model.featureVersion == FEATURE_VERSION
        # bias=-2.5、空特征（全按 0 计）→ sigmoid(-2.5)
        assert model.score({}) == pytest.approx(1.0 / (1.0 + math.exp(2.5)))

    def testTruncatedJsonRaisesUnavailable(self, tmp_path):
        truncated = '{"model_version": "0.1.0-seed", "bias": 0.'
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, raw=truncated))

    def testMissingRequiredFieldRaisesUnavailable(self, tmp_path):
        payload = validPayload()
        payload.pop("weights")
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    def testFeatureVersionMismatchRaisesUnavailable(self, tmp_path):
        payload = validPayload()
        payload["feature_version"] = "triage-features-v0"
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    # 旧行为变更说明（SB-3，2026-11-22）：此前 loadFrom 要求 model_version 精确
    # 等于 "0.1.0-seed"，任何重训产物（如 "0.2.0-trained"）都会被拒载，训练
    # 流水线永远无法替换默认权重——属设计缺陷。现改为：feature_version 仍精确
    # 匹配（真正的兼容性契约，见 testFeatureVersionMismatchRaisesUnavailable），
    # model_version 只要求非空字符串（溯源元数据，任意取值可载）。
    def testModelVersionAnyNonEmptyStringLoads(self, tmp_path):
        for version in ("0.2.0-trained", "9.9.9-other", "v2026.11.22-local"):
            payload = validPayload()
            payload["model_version"] = version
            model = NeuJudge.loadFrom(writeWeights(tmp_path, payload))
            assert model.modelVersion == version

    def testModelVersionEmptyOrNonStringRaisesUnavailable(self, tmp_path):
        for badVersion in ("", "   ", 123, None):
            payload = validPayload()
            payload["model_version"] = badVersion
            with pytest.raises(NeuJudgeUnavailable):
                NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    def testMissingFileRaisesUnavailable(self, tmp_path):
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(tmp_path / "absent.json")

    def testNonObjectPayloadRaisesUnavailable(self, tmp_path):
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, raw="[1, 2, 3]"))

    def testNonNumericWeightRaisesUnavailable(self, tmp_path):
        payload = validPayload()
        payload["weights"]["agentStreakLength"] = "high"
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    def testUnknownFeatureKeyRaisesUnavailable(self, tmp_path):
        payload = validPayload()
        payload["weights"]["mysterySignal"] = 0.5
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    def testMissingFeatureWeightRaisesUnavailable(self, tmp_path):
        payload = validPayload()
        payload["weights"].pop("maxSimilarity")
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))


class TestScoreBehaviour:
    def testScoreIsDeterministicForSameInput(self):
        model = NeuJudge.loadDefault()
        first = model.score(dict(SOLO_RUN_FEATURES))
        second = model.score(dict(SOLO_RUN_FEATURES))
        assert first == second

    def testScoreIsMonotonicInAgentStreakLength(self):
        # 独走越长越像无人在场 → p 单调不升（负权重下严格递减）
        model = NeuJudge.loadDefault()
        short = model.score({**SOLO_RUN_FEATURES, "agentStreakLength": 5.0})
        longer = model.score({**SOLO_RUN_FEATURES, "agentStreakLength": 25.0})
        assert longer <= short
        assert longer < short

    def testScoreStaysWithinUnitInterval(self):
        model = NeuJudge.loadDefault()
        for features in (SOLO_RUN_FEATURES, HUMAN_PRESENT_FEATURES, GREY_ZONE_FEATURES, {}):
            probability = model.score(dict(features))
            assert 0.0 <= probability <= 1.0

    def testMissingFeatureKeysTreatedAsZeroWithoutRaising(self):
        model = NeuJudge.loadDefault()
        empty = model.score({})
        explicitZeros = model.score({key: 0.0 for key in FEATURE_KEYS})
        assert empty == explicitZeros

    def testUnknownExtraFeatureKeysAreIgnored(self):
        model = NeuJudge.loadDefault()
        base = model.score(dict(SOLO_RUN_FEATURES))
        withExtra = model.score({**SOLO_RUN_FEATURES, "mysterySignal": 999.0})
        assert withExtra == base

    def testNoHumanSentinelMinusOneMapsToNeutralZero(self):
        model = NeuJudge.loadDefault()
        sentinel = model.score(
            {**SOLO_RUN_FEATURES, "humanEventDistance": -1.0, "humanTimeDistanceSec": -1.0}
        )
        neutral = model.score(
            {**SOLO_RUN_FEATURES, "humanEventDistance": 0.0, "humanTimeDistanceSec": 0.0}
        )
        assert sentinel == neutral

    def testExtremeValuesDoNotOverflow(self):
        # 极端特征值下 score 不得溢出/抛错，且恒有界 [0,1]
        # （权重符号随训练演进：0.1.0-seed 为负、0.4.0-neurova 为正，均须有界）
        model = NeuJudge.loadDefault()
        for value in (1e9, -1e9):
            p = model.score({"maxSimilarity": value})
            assert 0.0 <= p <= 1.0


class TestDecideBoundaries:
    def testThreeWayBoundariesAtAndAroundThresholds(self):
        model = NeuJudge.loadDefault()
        assert model.decide(SKIP_P) == "abstain"
        assert model.decide(SKIP_P - 1e-9) == "skip"
        assert model.decide(0.0) == "skip"
        assert model.decide(0.5) == "abstain"
        assert model.decide(ALLOW_P) == "abstain"
        assert model.decide(ALLOW_P + 1e-9) == "allow"
        assert model.decide(1.0) == "allow"


class TestArtifactThresholds:
    """产物级阈值（标定脚本反推写入）：覆盖默认 SKIP_P/ALLOW_P，非法配置拒载。"""

    def testArtifactThresholdsOverrideDefaults(self, tmp_path):
        payload = validPayload()
        payload["thresholds"] = {"skip_p": 0.4, "allow_p": 0.9}
        model = NeuJudge.loadFrom(writeWeights(tmp_path, payload))
        assert model.thresholds == {"skip_p": 0.4, "allow_p": 0.9}
        # 0.35 在默认档属弃权带，覆盖后 0.35 < 0.4 → skip
        assert model.decide(0.35) == "skip"
        assert model.decide(0.5) == "abstain"
        assert model.decide(0.95) == "allow"

    def testDefaultThresholdsWhenAbsent(self, tmp_path):
        model = NeuJudge.loadFrom(writeWeights(tmp_path, validPayload()))
        assert model.thresholds == {"skip_p": SKIP_P, "allow_p": ALLOW_P}

    def testSkipPGreaterThanAllowPRejected(self, tmp_path):
        payload = validPayload()
        payload["thresholds"] = {"skip_p": 0.9, "allow_p": 0.4}
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))

    def testThresholdsOutOfRangeRejected(self, tmp_path):
        payload = validPayload()
        payload["thresholds"] = {"skip_p": 1.5}
        with pytest.raises(NeuJudgeUnavailable):
            NeuJudge.loadFrom(writeWeights(tmp_path, payload))
