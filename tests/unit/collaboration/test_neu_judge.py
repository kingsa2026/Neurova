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
        assert model.modelVersion == MODEL_VERSION
        assert model.modelVersion == "0.1.0-seed"
        assert model.featureVersion == FEATURE_VERSION
        assert model.featureVersion == "triage-features-v1"
        assert isinstance(model.bias, float)
        assert set(model.weights) == set(FEATURE_KEYS)
        assert len(FEATURE_KEYS) == 11

    def testDefaultWeightFileCarriesRequiredSchemaFields(self):
        payload = json.loads(DEFAULT_WEIGHTS_PATH.read_text(encoding="utf-8"))
        assert payload["model_version"] == MODEL_VERSION
        assert payload["feature_version"] == FEATURE_VERSION
        assert isinstance(payload["bias"], (int, float))
        assert not isinstance(payload["bias"], bool)
        assert set(payload["weights"]) == set(FEATURE_KEYS)
        assert isinstance(payload["data_fingerprint"], str)
        assert payload["data_fingerprint"]
        assert isinstance(payload["eval_metrics"], dict)

    def testDefaultWeightSignsMatchRuleMonotonicity(self):
        # 独走证据压低「值得响应」概率（负权重），人类在场证据抬高之（正权重），
        # 与规则 R0/R1（人在场→放行）、R2/R3（独走/复读→拦截）单调一致
        weights = NeuJudge.loadDefault().weights
        assert weights["agentStreakLength"] < 0
        assert weights["maxRepeatCount"] < 0
        assert weights["maxSimilarity"] < 0
        assert weights["humanEventDistance"] > 0
        assert weights["humanTimeDistanceSec"] > 0

    def testDefaultModelScoresTypicalScenariosIntoThreeBands(self):
        # 独走 → p 落低档（skip），人类在场 → p 落高档（allow），灰色区 → 弃权带
        model = NeuJudge.loadDefault()
        soloP = model.score(dict(SOLO_RUN_FEATURES))
        humanP = model.score(dict(HUMAN_PRESENT_FEATURES))
        greyP = model.score(dict(GREY_ZONE_FEATURES))
        assert soloP < SKIP_P
        assert humanP > ALLOW_P
        assert SKIP_P < greyP < ALLOW_P
        assert model.decide(soloP) == "skip"
        assert model.decide(humanP) == "allow"
        assert model.decide(greyP) == "abstain"


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
        # maxSimilarity 权重为负：极端大相似度 → p≈0，极端小（大负值）→ p≈1，均不得溢出抛错
        model = NeuJudge.loadDefault()
        assert model.score({"maxSimilarity": 1e9}) == pytest.approx(0.0, abs=1e-9)
        assert model.score({"maxSimilarity": -1e9}) == pytest.approx(1.0, abs=1e-9)


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
