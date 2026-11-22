"""SB-2 小脑分诊微型判定模型 NeuJudge：特征向量 → 概率 → 三档裁决的纯数学推理器。

命名出处：Neu 前缀沿 neuacp 系，Judge 指其判定职能。

计划出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md §5
（自研微型判定模型）。本模块只做「特征 → sigmoid → skip/abstain/allow」的确定性
计算，不负责特征提取（上游为 triage_rules.extractTriageFeatures，本模块不 import
它，直接消费特征字典），同输入同输出，单次判定亚毫秒、零网络零 LLM。

权重产物 schema（默认产物为同目录 neu_judge_default.json）：
{"model_version", "feature_version", "bias", "weights", "data_fingerprint", "eval_metrics"}。
加载失败（文件缺失/JSON 损坏/缺字段/版本不匹配/权重非法）抛 NeuJudgeUnavailable，
由调用方按计划 §5.4 诚实降级为仅规则模式（不 fail-open 到放行一切）。
"""

import json
import math
from pathlib import Path
from typing import Dict, Union

__all__ = [
    "MODEL_VERSION",
    "FEATURE_VERSION",
    "SKIP_P",
    "ALLOW_P",
    "FEATURE_KEYS",
    "NeuJudgeUnavailable",
    "NeuJudge",
]

MODEL_VERSION = "0.1.0-seed"
FEATURE_VERSION = "triage-features-v1"
SKIP_P = 0.25
ALLOW_P = 0.75

# 特征键固定名单（与规则层 triage-features-v1 契约一致）；求和按此顺序，保证确定性
FEATURE_KEYS = (
    "humanEventDistance",
    "humanTimeDistanceSec",
    "agentStreakLength",
    "maxRepeatCount",
    "maxSimilarity",
    "messageRatePerMin",
    "userCount",
    "assistantCount",
    "meanAssistantLength",
    "maxAssistantLength",
    "questionRatio",
)

_DEFAULT_WEIGHTS_FILENAME = "neu_judge_default.json"
_REQUIRED_FIELDS = ("model_version", "feature_version", "bias", "weights")
_NO_HUMAN_VALUE = -1.0
_NO_HUMAN_KEYS = frozenset({"humanEventDistance", "humanTimeDistanceSec"})


class NeuJudgeUnavailable(RuntimeError):
    """权重产物缺失、损坏、缺字段或版本不匹配时抛出（诚实失败，不静默放行）。"""


def _sigmoid(x: float) -> float:
    """数值稳定 logistic：x≥0 走 1/(1+e^-x)，x<0 走 e^x/(1+e^x)，杜绝 exp 溢出。"""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    expX = math.exp(x)
    return expX / (1.0 + expX)


class NeuJudge:
    """微型逻辑回归判定器（计划 §5.4：权重常驻内存，推理零网络零磁盘读）。

    p = score(features) = sigmoid(bias + Σ weights[k]·x[k])，语义为「该回合
    值得响应（actionable）」的概率；缺失特征键按 0.0 计。humanEventDistance /
    humanTimeDistanceSec 的 -1.0（"无人类"哨兵）先映射为 0.0 再计权——即不贡献
    任何 human 侧证据。decide 按 SKIP_P/ALLOW_P 切三档（p<SKIP_P→skip、
    p>ALLOW_P→allow、其间含恰等→abstain），弃权带由调用方保守放行。

    默认权重符号与规则单调一致（计划 §3：人在场→放行、独走/复读→拦截）：
    独走证据 agentStreakLength/maxRepeatCount/maxSimilarity 为负，人类在场证据
    humanEventDistance/humanTimeDistanceSec 为正，其余小幅或 0。
    """

    def __init__(
        self,
        bias: float,
        weights: Dict[str, float],
        modelVersion: str,
        featureVersion: str,
    ) -> None:
        self._bias = bias
        self._weights = dict(weights)
        self._modelVersion = modelVersion
        self._featureVersion = featureVersion

    @classmethod
    def loadDefault(cls) -> "NeuJudge":
        """读取同目录 neu_judge_default.json 构建模型；失败抛 NeuJudgeUnavailable。"""
        return cls.loadFrom(Path(__file__).resolve().parent / _DEFAULT_WEIGHTS_FILENAME)

    @classmethod
    def loadFrom(cls, path: Union[str, Path]) -> "NeuJudge":
        """从 JSON 权重产物构建模型；schema/版本校验失败抛 NeuJudgeUnavailable。"""
        weightsPath = Path(path)
        try:
            rawText = weightsPath.read_text(encoding="utf-8")
        except OSError as exc:
            raise NeuJudgeUnavailable(f"权重产物不可读: {weightsPath} ({exc})") from exc
        try:
            payload = json.loads(rawText)
        except json.JSONDecodeError as exc:
            raise NeuJudgeUnavailable(f"权重产物不是合法 JSON: {weightsPath} ({exc})") from exc
        return cls._fromPayload(payload, source=str(weightsPath))

    @classmethod
    def _fromPayload(cls, payload: object, source: str) -> "NeuJudge":
        """校验并装配权重产物；任何 schema/版本偏差都点名拒绝，不带病上岗。"""
        if not isinstance(payload, dict):
            raise NeuJudgeUnavailable(f"权重产物顶层必须是 JSON 对象: {source}")
        missing = [field for field in _REQUIRED_FIELDS if field not in payload]
        if missing:
            raise NeuJudgeUnavailable(f"权重产物缺字段 {missing}: {source}")
        if payload["model_version"] != MODEL_VERSION:
            raise NeuJudgeUnavailable(
                f"model_version 不匹配: 期望 {MODEL_VERSION!r}, 实得 {payload['model_version']!r}: {source}"
            )
        if payload["feature_version"] != FEATURE_VERSION:
            raise NeuJudgeUnavailable(
                f"feature_version 不匹配: 期望 {FEATURE_VERSION!r}, 实得 {payload['feature_version']!r}: {source}"
            )
        bias = payload["bias"]
        if isinstance(bias, bool) or not isinstance(bias, (int, float)):
            raise NeuJudgeUnavailable(f"bias 不是数值: {source}")
        rawWeights = payload["weights"]
        if not isinstance(rawWeights, dict):
            raise NeuJudgeUnavailable(f"weights 必须是 JSON 对象: {source}")
        unknown = sorted(str(key) for key in rawWeights if key not in FEATURE_KEYS)
        if unknown:
            raise NeuJudgeUnavailable(f"weights 含未知特征键 {unknown}: {source}")
        weights: Dict[str, float] = {}
        for key in FEATURE_KEYS:
            if key not in rawWeights:
                raise NeuJudgeUnavailable(f"weights 缺特征键 {key}: {source}")
            value = rawWeights[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise NeuJudgeUnavailable(f"权重 {key} 不是数值: {source}")
            weights[key] = float(value)
        return cls(
            float(bias),
            weights,
            str(payload["model_version"]),
            str(payload["feature_version"]),
        )

    @property
    def modelVersion(self) -> str:
        return self._modelVersion

    @property
    def featureVersion(self) -> str:
        return self._featureVersion

    @property
    def bias(self) -> float:
        return self._bias

    @property
    def weights(self) -> Dict[str, float]:
        return dict(self._weights)

    def score(self, features: Dict[str, float]) -> float:
        """sigmoid(bias + Σ w[k]·x[k])；缺键按 0.0 计；固定求和顺序保证同输入同输出。

        返回值为「值得响应」概率：独走证据（负权重）压低它，人类在场证据（正权重）
        抬高它，与计划 §3 的规则取向单调一致。
        """
        z = self._bias
        for key in FEATURE_KEYS:
            value = float(features.get(key, 0.0))
            if value == _NO_HUMAN_VALUE and key in _NO_HUMAN_KEYS:
                value = 0.0
            z += self._weights[key] * value
        return _sigmoid(z)

    def decide(self, p: float) -> str:
        """三档裁决：p < SKIP_P → "skip"（拦截本轮响应）；p > ALLOW_P → "allow"（放行）；
        其间（含恰等）→ "abstain"（弃权，由调用方保守放行）。

        p 为 score 产出的「值得响应」概率，与计划 §3 的级联语义一致。
        """
        if p < SKIP_P:
            return "skip"
        if p > ALLOW_P:
            return "allow"
        return "abstain"
