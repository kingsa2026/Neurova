"""SB-3 离线训练脚本：从合成窗口自举训练 NeuJudge（规则弱标注）。

出处：docs/04-plans/2026-11-22-small-brain-triage-gate-wiring-plan.md §5.3
（训练数据与标签：规则强标签自举）与 §8-SB-3（离线训练脚本）。

弱标注口径：**规则即标注器**——evaluateTriage 在无歧义区给出强标签：
人类在场窗口 → allow（值得响应，y=1）；≥20 条独走环 / 复读环窗口 → skip
（不值得响应，y=0）；default_allow 灰区窗口是规则的弃权区，**不进训练集**，
只进评估集单独计数报告规则标注器的覆盖率，不许拿弃权区样本硬训。

与 EvalCase 棘轮（计划 §5.5）的关系：本脚本产出的新权重在替换默认权重
（neu_judge_default.json）之前，必须先过冻结验证集上的 EvalCase 红绿与指标
棘轮——准确率 / skip 精确率 / skip 召回不回退才可替换；本脚本写出的
eval_metrics 即棘轮判据的数据来源。换模型前先过冻结集，不回退才可替换。

流程：合成事件窗口（四类模板：人类在场 / 独走环 / 复读环 / 灰区；事件形态
{"role","content","timestamp"}，时间戳为确定性基准递增）→ evaluateTriage 打
弱标签 → extractTriageFeatures 提特征 → 纯 Python 全批量梯度下降训练逻辑
回归（random.Random(seed) 固定种子；在标准化特征空间训练，再把均值/方差
折回权重，使产物直接消费原始特征向量）→ 按会话 sha256 切训练/冻结验证集 →
冻结集指标（准确率、skip 类精确率/召回率）→ 写权重产物 JSON（可被
NeuJudge.loadFrom 加载；model_version="0.2.0-trained"，feature_version 契约
为 triage-features-v1）。

只依赖标准库，不引入任何运行时依赖（计划 §11：训练亦纯离线脚本）。确定性
可复现：固定种子 + 确定性哈希切分 + 固定特征求和顺序 + sort_keys 序列化，
同参数两次运行产物逐字节一致。为将来接真实会话归档数据留接口：换数据源
只需替换 buildSyntheticWindows 的窗口生产（或实现同形态的窗口迭代器），
弱标注→训练→评测→产物管线不变。

用法：
    python scripts/training/train_neu_judge.py [--windows 400] [--seed 42] [--out neu_judge_trained.json]

产物默认写到当前工作目录的 neu_judge_trained.json，不覆盖仓内
neurova/collaboration/neu_judge_default.json（部署期用重训版覆盖默认权重
属显式操作，见计划 §5.4）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# 脚本目录形态运行（python scripts/training/train_neu_judge.py）时，sys.path[0]
# 是本文件所在目录而非仓库根，先补上仓库根再 import neurova（与
# scripts/backfill_memory_embeddings.py 同一模式）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from neurova.collaboration.neu_judge import FEATURE_KEYS, FEATURE_VERSION
from neurova.collaboration.triage_rules import evaluateTriage, extractTriageFeatures

# --- 产物与训练常量 ---

MODEL_VERSION_TRAINED = "0.2.0-trained"
DEFAULT_WINDOWS = 400
DEFAULT_SEED = 42
DEFAULT_OUT = "neu_judge_trained.json"

LEARNING_RATE = 0.3
MAX_ITERATIONS = 2000
CONVERGENCE_TOL = 1e-9
TRAIN_SPLIT_PERCENT = 80  # sha256 % 100 < 80 → 训练集，否则冻结验证集

# 与 NeuJudge.score 的预处理保持同一口径：无人类哨兵 -1.0 先映射为 0.0 再计权。
# 本地复刻而非 import 私有常量；方向正确性测试（真实提取特征打分）会咬合
# 这份口径，一旦漂移质量门槛即红。
_NO_HUMAN_SENTINEL = -1.0
_NO_HUMAN_KEYS = frozenset({"humanEventDistance", "humanTimeDistanceSec"})
_SIGMA_FLOOR = 1e-6

_CATEGORIES = ("human_present", "solo_loop", "verbatim_loop", "grey_zone")

# 确定性时间基准：每窗口错开一分钟、窗口内事件按秒递增，杜绝墙钟
_BASE_TIME = datetime(2026, 11, 22, 12, 0, 0)

# --- 合成窗口内容池（均不含疑问词，questionRatio 信号只来自人类消息） ---

_ASSISTANT_FRAGMENTS = (
    "正在读取配置文件并校验字段",
    "已把中间结果写入工作区文档",
    "开始聚合上一轮的统计数据",
    "正在调用检索工具补充上下文",
    "已完成本轮检查未发现异常",
    "正在生成下一步的执行计划",
)

_USER_LINES = (
    "这个报错应该怎么修？",
    "帮我把刚才的结论整理成清单",
    "为什么这一步的输出和预期不一样？",
    "继续，我看着呢",
    "刚才说的方案风险点在哪？",
)

_VERBATIM_SENTENCE = "当前任务仍在等待外部资源就绪，暂无新的进展可以汇报。"


def _assistantLine(rng: random.Random, index: int) -> str:
    """带序号后缀的 assistant 消息，保证窗口内归一化后互不相同（防误触 R3）。"""
    fragment = _ASSISTANT_FRAGMENTS[rng.randrange(len(_ASSISTANT_FRAGMENTS))]
    return f"{fragment}（第{index}步）"


def _userLine(rng: random.Random) -> str:
    return _USER_LINES[rng.randrange(len(_USER_LINES))]


def _humanPresentWindow(rng: random.Random, sessionIndex: int) -> Tuple[List[Dict], str]:
    """人类在场窗口：若干 assistant 后人类发言 → R0/R1 强标签 allow。

    按同亚型窗口的出现次序奇偶分两个亚型，保证两个亚型在任何样本量下都出现：
    偶数次序人类消息收尾（human_last，距离 0）；奇数次序人类发言后再跟
    1-2 条 assistant 回应（human_in_window，事件/时间距离 >0）——否则
    humanEventDistance / humanTimeDistanceSec 在训练集恒为 0，退化为
    无信号的常量特征（见 _foldIntoRawSpace 的常量特征守卫）。
    """
    moment = _BASE_TIME + timedelta(minutes=sessionIndex)
    events: List[Dict] = []
    assistantCount = rng.randint(6, 16)
    for i in range(assistantCount):
        events.append(
            {"role": "assistant", "content": _assistantLine(rng, i), "timestamp": moment.isoformat()}
        )
        moment += timedelta(seconds=rng.randint(15, 60))
    currentUser = _userLine(rng)
    for _ in range(rng.randint(1, 3)):
        events.append({"role": "user", "content": _userLine(rng), "timestamp": moment.isoformat()})
        moment += timedelta(seconds=rng.randint(10, 45))
    if (sessionIndex // len(_CATEGORIES)) % 2 == 1:
        for i in range(rng.randint(1, 2)):
            events.append(
                {
                    "role": "assistant",
                    "content": _assistantLine(rng, assistantCount + i),
                    "timestamp": moment.isoformat(),
                }
            )
            moment += timedelta(seconds=rng.randint(10, 45))
    return events, currentUser


def _soloLoopWindow(rng: random.Random, sessionIndex: int) -> Tuple[List[Dict], str]:
    """独走环窗口：≥20 条纯 assistant、全程无人类 → R2 强标签 skip。"""
    moment = _BASE_TIME + timedelta(minutes=sessionIndex)
    events: List[Dict] = []
    for i in range(rng.randint(22, 30)):
        events.append(
            {"role": "assistant", "content": _assistantLine(rng, i), "timestamp": moment.isoformat()}
        )
        moment += timedelta(seconds=rng.randint(15, 60))
    # 本回合输入为短续跑指令（归一化 <8 字符 → maxSimilarity=0，独走证据由 streak 承担）
    return events, "继续"


def _verbatimLoopWindow(rng: random.Random, sessionIndex: int) -> Tuple[List[Dict], str]:
    """复读环窗口：独走 <20 条，但近 6 条 assistant 内 ≥3 条重复 → R3 强标签 skip。"""
    moment = _BASE_TIME + timedelta(minutes=sessionIndex)
    events: List[Dict] = []
    for i in range(rng.randint(6, 10)):
        events.append(
            {"role": "assistant", "content": _assistantLine(rng, i), "timestamp": moment.isoformat()}
        )
        moment += timedelta(seconds=rng.randint(15, 60))
    for _ in range(rng.randint(3, 4)):
        events.append(
            {"role": "assistant", "content": _VERBATIM_SENTENCE, "timestamp": moment.isoformat()}
        )
        moment += timedelta(seconds=rng.randint(15, 60))
    # 本回合输入与复读句几乎相同 → maxSimilarity≈1，与 R3 的相似度分支同构
    return events, _VERBATIM_SENTENCE


def _greyZoneWindow(rng: random.Random, sessionIndex: int) -> Tuple[List[Dict], str]:
    """灰区窗口：独走 5-15 条、无人类、消息互异、输入低相似 → default_allow 弃权。"""
    moment = _BASE_TIME + timedelta(minutes=sessionIndex)
    events: List[Dict] = []
    for i in range(rng.randint(5, 15)):
        events.append(
            {"role": "assistant", "content": _assistantLine(rng, i), "timestamp": moment.isoformat()}
        )
        moment += timedelta(seconds=rng.randint(15, 60))
    return events, "帮我把目前的进展总结成三句话"


_WINDOW_BUILDERS = {
    "human_present": _humanPresentWindow,
    "solo_loop": _soloLoopWindow,
    "verbatim_loop": _verbatimLoopWindow,
    "grey_zone": _greyZoneWindow,
}


def buildSyntheticWindows(windowCount: int, seed: int) -> List[Dict]:
    """按四类模板轮转生成确定性合成窗口（真实数据接入前的主力量来源，§5.3-1）。

    每个窗口形如 {"sessionId", "category", "events", "currentInput"}；
    events 为 {"role","content","timestamp"} 字典列表（SessionSyncManager
    get_messages 形态），时间戳由固定基准递增，全程无墙钟、无全局随机。
    """
    rng = random.Random(seed)
    windows: List[Dict] = []
    for index in range(windowCount):
        category = _CATEGORIES[index % len(_CATEGORIES)]
        events, currentInput = _WINDOW_BUILDERS[category](rng, index)
        windows.append(
            {
                "sessionId": f"{category}#{index:04d}",
                "category": category,
                "events": events,
                "currentInput": currentInput,
            }
        )
    return windows


def _isTrainSplit(sessionId: str) -> bool:
    """按会话 sha256 确定切分（计划 §5.3：按会话切分防同会话泄漏；禁 built-in hash）。"""
    digest = hashlib.sha256(sessionId.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % 100 < TRAIN_SPLIT_PERCENT


def _prepareFeatureVector(features: Dict[str, float]) -> Dict[str, float]:
    """固定 11 键顺序 + 无人类哨兵 -1.0→0.0（与 NeuJudge.score 预处理一致）。"""
    prepared: Dict[str, float] = {}
    for key in FEATURE_KEYS:
        value = float(features.get(key, 0.0))
        if value == _NO_HUMAN_SENTINEL and key in _NO_HUMAN_KEYS:
            value = 0.0
        prepared[key] = value
    return prepared


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    expX = math.exp(x)
    return expX / (1.0 + expX)


def _standardize(
    trainVectors: List[Dict[str, float]],
) -> Tuple[Dict[str, float], Dict[str, float], frozenset]:
    """训练集逐特征均值/标准差（标准差下限防除零）。

    返回 (mean, sigma, constantKeys)：constantKeys 是训练集上方差恰为 0 的
    特征——它们对判别零贡献，折回原始空间时权重必须置 0（否则初始化噪声
    会被 1/σ_floor 放大成 ±数千的伪权重，见 _foldIntoRawSpace）。
    """
    mean: Dict[str, float] = {}
    sigma: Dict[str, float] = {}
    constantKeys: List[str] = []
    count = len(trainVectors)
    for key in FEATURE_KEYS:
        values = [vector[key] for vector in trainVectors]
        mu = sum(values) / count
        variance = sum((value - mu) ** 2 for value in values) / count
        mean[key] = mu
        if variance == 0.0:
            constantKeys.append(key)
        sigma[key] = max(math.sqrt(variance), _SIGMA_FLOOR)
    return mean, sigma, frozenset(constantKeys)


def _trainLogisticRegression(
    trainSamples: List[Dict],
    mean: Dict[str, float],
    sigma: Dict[str, float],
    rng: random.Random,
) -> Tuple[Dict[str, float], float, int, float]:
    """标准化空间全批量梯度下降（凸损失，固定种子初始化，确定性收敛）。

    返回 (标准化权重, 标准化偏置, 迭代数, 末轮损失)。
    """
    weights = {key: rng.uniform(-0.01, 0.01) for key in FEATURE_KEYS}
    bias = 0.0
    stdVectors = [
        {key: (sample["features"][key] - mean[key]) / sigma[key] for key in FEATURE_KEYS}
        for sample in trainSamples
    ]
    labels = [sample["label"] for sample in trainSamples]
    count = len(stdVectors)
    # 类平衡权重：真实流量里 skip 类稀少（多数为人类在场放行），不加权会
    # 塌缩成"全放行"（skipRecall=0）。权重 = n / (2·类数)，两类等权贡献。
    labelCounts: Dict[float, int] = {}
    for label in labels:
        labelCounts[label] = labelCounts.get(label, 0) + 1
    sampleWeights = [count / (2.0 * labelCounts[label]) for label in labels]
    weightTotal = sum(sampleWeights) or 1.0
    previousLoss: float | None = None
    finalLoss = 0.0
    iteration = 0
    for iteration in range(1, MAX_ITERATIONS + 1):
        grad = {key: 0.0 for key in FEATURE_KEYS}
        gradBias = 0.0
        loss = 0.0
        for vector, label, sampleWeight in zip(stdVectors, labels, sampleWeights):
            z = bias
            for key in FEATURE_KEYS:
                z += weights[key] * vector[key]
            probability = _sigmoid(z)
            error = probability - label
            gradBias += sampleWeight * error
            for key in FEATURE_KEYS:
                grad[key] += sampleWeight * error * vector[key]
            loss -= sampleWeight * (
                label * math.log(probability + 1e-15)
                + (1.0 - label) * math.log(1.0 - probability + 1e-15)
            )
        loss /= weightTotal
        bias -= LEARNING_RATE * gradBias / weightTotal
        for key in FEATURE_KEYS:
            weights[key] -= LEARNING_RATE * grad[key] / weightTotal
        finalLoss = loss
        if previousLoss is not None and abs(previousLoss - loss) < CONVERGENCE_TOL:
            break
        previousLoss = loss
    return weights, bias, iteration, finalLoss


def _foldIntoRawSpace(
    weights: Dict[str, float],
    bias: float,
    mean: Dict[str, float],
    sigma: Dict[str, float],
    constantKeys: frozenset,
) -> Tuple[Dict[str, float], float]:
    """把标准化空间的 (w, b) 折回原始特征空间：w_raw=w/σ，b_raw=b-Σwμ/σ。

    折回后 NeuJudge.score(原始特征) 与标准化空间打分逐位等价
    （score 内部先做 -1.0→0.0 哨兵映射，训练侧 _prepareFeatureVector 同口径）。

    常量特征守卫：训练集上方差为 0 的特征对判别零贡献（标准化后恒为 0，
    梯度恒 0，其标准化权重只是初始化噪声）——折回时权重必须置 0 并从偏置
    修正中剔除；否则除以 σ_floor(1e-6) 会把初始化噪声放大成 ±数千的伪权重，
    在推理期特征非零时产生灾难性打分（根因修复点，不是下游补丁）。
    """
    rawWeights = {
        key: (0.0 if key in constantKeys else weights[key] / sigma[key]) for key in FEATURE_KEYS
    }
    rawBias = bias - sum(
        weights[key] * mean[key] / sigma[key]
        for key in FEATURE_KEYS
        if key not in constantKeys
    )
    return rawWeights, rawBias


def _evaluateFrozen(
    frozenSamples: List[Dict], weights: Dict[str, float], bias: float
) -> Dict[str, float]:
    """冻结验证集指标：准确率 + skip 类精确率/召回率（0.5 概率阈值二分）。"""
    truePositive = 0
    falsePositive = 0
    trueNegative = 0
    falseNegative = 0
    for sample in frozenSamples:
        z = bias
        for key in FEATURE_KEYS:
            z += weights[key] * sample["features"][key]
        predictedSkip = _sigmoid(z) < 0.5
        actualSkip = sample["label"] == 0.0
        if predictedSkip and actualSkip:
            truePositive += 1
        elif predictedSkip and not actualSkip:
            falsePositive += 1
        elif not predictedSkip and actualSkip:
            falseNegative += 1
        else:
            trueNegative += 1
    total = len(frozenSamples)
    skipPredicted = truePositive + falsePositive
    skipActual = truePositive + falseNegative
    return {
        "accuracy": (truePositive + trueNegative) / total if total else 0.0,
        "skipPrecision": truePositive / skipPredicted if skipPredicted else 0.0,
        "skipRecall": truePositive / skipActual if skipActual else 0.0,
    }


def _dataFingerprint(trainSamples: List[Dict]) -> str:
    """训练样本 canonical JSON 的 sha256（sort_keys + 紧凑分隔符，确定性）。"""
    canonical = json.dumps(
        [
            {"sessionId": sample["sessionId"], "label": sample["label"], "features": sample["features"]}
            for sample in trainSamples
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stratifiedSplit(labelled: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """按会话哈希切分 + 分层补救：任一类整体落在一侧时，移动确定性样本，
    保证训练/冻结两侧都见到各类（否则冻结指标退化成全类准确率，skip 能力
    无从验证）。"""
    train: List[Dict] = []
    frozen: List[Dict] = []
    for sample in labelled:
        (train if _isTrainSplit(sample["sessionId"]) else frozen).append(sample)
    for labelValue in (0.0, 1.0):
        trainCount = sum(1 for sample in train if sample["label"] == labelValue)
        frozenCount = sum(1 for sample in frozen if sample["label"] == labelValue)
        if frozenCount == 0 and trainCount >= 2:
            for idx in range(len(train) - 1, -1, -1):
                if train[idx]["label"] == labelValue:
                    frozen.append(train.pop(idx))
                    break
        elif trainCount == 0 and frozenCount >= 2:
            for idx in range(len(frozen) - 1, -1, -1):
                if frozen[idx]["label"] == labelValue:
                    train.append(frozen.pop(idx))
                    break
    return train, frozen


def _trainAndEvaluate(
    labelled: List[Dict],
    greyCount: int,
    totalWindows: int,
    seed: int,
    modelVersion: str = MODEL_VERSION_TRAINED,
) -> Dict:
    """标注样本 → 标准化训练 → 冻结集评测 → 权重产物（合成/真实两源共用）。"""
    trainSamples, frozenSamples = _stratifiedSplit(labelled)
    if not trainSamples or not frozenSamples:
        raise RuntimeError("训练/冻结验证集切分为空，请增大 --windows 或提供更多会话")

    mean, sigma, constantKeys = _standardize([sample["features"] for sample in trainSamples])
    weightsStd, biasStd, iterations, finalLoss = _trainLogisticRegression(
        trainSamples, mean, sigma, random.Random(seed)
    )
    rawWeights, rawBias = _foldIntoRawSpace(weightsStd, biasStd, mean, sigma, constantKeys)

    metrics: Dict[str, float] = _evaluateFrozen(frozenSamples, rawWeights, rawBias)
    metrics.update(
        {
            "trainWindows": float(len(trainSamples)),
            "frozenWindows": float(len(frozenSamples)),
            "skipTrainCount": float(sum(1 for s in trainSamples if s["label"] == 0.0)),
            "skipFrozenCount": float(sum(1 for s in frozenSamples if s["label"] == 0.0)),
            "allowFrozenCount": float(sum(1 for s in frozenSamples if s["label"] == 1.0)),
            "greyZoneWindows": float(greyCount),
            "greyZoneRatio": greyCount / totalWindows if totalWindows else 0.0,
            "constantFeatureCount": float(len(constantKeys)),
            "iterations": float(iterations),
            "finalLoss": finalLoss,
            "learningRate": LEARNING_RATE,
        }
    )

    return {
        "model_version": modelVersion,
        "feature_version": FEATURE_VERSION,
        "bias": rawBias,
        "weights": {key: rawWeights[key] for key in FEATURE_KEYS},
        "data_fingerprint": _dataFingerprint(trainSamples),
        "eval_metrics": metrics,
    }


def trainNeuJudge(windowCount: int = DEFAULT_WINDOWS, seed: int = DEFAULT_SEED) -> Dict:
    """跑完整训练管线（合成窗口），返回可被 NeuJudge.loadFrom 加载的权重产物。"""
    windows = buildSyntheticWindows(windowCount, seed)
    if not windows:
        raise RuntimeError("--windows 必须为正整数")

    # 弱标注：规则即标注器；default_allow 灰区弃权不入训，只计覆盖率
    labelled: List[Dict] = []
    greyWindows: List[Dict] = []
    for window in windows:
        verdict = evaluateTriage(window["events"], window["currentInput"])
        if verdict.reason == "default_allow":
            greyWindows.append(window)
            continue
        labelled.append(
            {
                "sessionId": window["sessionId"],
                "category": window["category"],
                "features": _prepareFeatureVector(
                    extractTriageFeatures(window["events"], window["currentInput"])
                ),
                "label": 1.0 if verdict.action == "allow" else 0.0,
            }
        )

    return _trainAndEvaluate(labelled, len(greyWindows), len(windows), seed)


def _ingestSkipFeedback(dataRoot: str) -> List[Dict]:
    """把 triage_skips.jsonl（SB-5 回流样本）直接变训练行。

    - label：not_actionable→0（真跳过）；actionable（含 admin 改标）→1（误杀）；
    - sessionId 用 skipfb/<sample_id>（与收割窗口的会话切分空间隔离）；
    - 坏行跳过；无文件返回空。这是**真实流量里最稀缺的 skip 类正样本**来源。
    """
    path = Path(dataRoot) / "triage_skips.jsonl"
    if not path.exists():
        return []
    rows: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("features"), dict):
            continue
        rows.append({
            "sessionId": f"skipfb/{record.get('sample_id') or len(rows)}",
            "features": _prepareFeatureVector(record["features"]),
            "label": 1.0 if record.get("label") == "actionable" else 0.0,
        })
    return rows


def trainNeuJudgeFromRealData(
    dataRoot: str,
    seed: int = DEFAULT_SEED,
    distill: int = 0,
    minMessages: int = 6,
    maxWindows: int = 200,
    distillScope: str = "gray",
) -> Dict:
    """D-SB3/D-SB1：真实会话窗口收割 → 规则/离线蒸馏弱标注 → 训练。

    - D-SB3：窗口来自数据根的真实会话落盘文件（不再只有合成模板）；
    - D-SB1：灰区窗口可用既有 LLM 分诊门离线打弱标签（--distill 封顶，
      人工触发、全部离线，运行时路径零改动）；distillScope="audit" 时
      规则已决窗口也送教师复核（不一致即最高价值标注）；
    - triage_skips.jsonl（SB-5 回流）直接并入训练行（skip 类稀缺正样本）。
    """
    from neurova.collaboration.triage_dataset import (
        harvestSessionWindows,
        labelWindows,
        realGateTriageFn,
    )

    windows = harvestSessionWindows(dataRoot, maxWindows=maxWindows, minMessages=minMessages)
    if not windows:
        raise RuntimeError(
            f"真实数据源未收割到可用窗口（数据根 {dataRoot} 下无 ≥{minMessages} 条消息的会话）"
        )
    labelledRaw = labelWindows(
        windows,
        distillLimit=distill,
        triageFn=realGateTriageFn if distill > 0 else None,
        distillScope=distillScope,
    )
    labelled = [
        {
            "sessionId": entry["conversationId"],
            "category": entry["labeler"],
            "features": _prepareFeatureVector(entry["features"]),
            "label": float(entry["label"]),
        }
        for entry in labelledRaw["labeled"]
    ]
    feedbackRows = _ingestSkipFeedback(dataRoot)
    labelled.extend(feedbackRows)
    if len(labelled) < 8:
        raise RuntimeError(
            f"可训练样本不足（{len(labelled)} < 8）——需要更多会话流量、"
            "调低 --min-messages，或开启 --distill 让灰区窗口离线蒸馏打标"
        )
    payload = _trainAndEvaluate(
        labelled, labelledRaw["grayUnlabeled"], len(windows), seed,
        modelVersion="0.3.0-real",
    )
    payload["eval_metrics"]["distillUsed"] = float(labelledRaw["distillUsed"])
    payload["eval_metrics"]["distillErrors"] = float(labelledRaw["distillErrors"])
    payload["eval_metrics"]["skipFeedbackSamples"] = float(len(feedbackRows))
    payload["eval_metrics"]["distillScope"] = 1.0 if distillScope == "audit" else 0.0
    return payload


def trainAxionFromRealData(
    dataRoot: str,
    seed: int = DEFAULT_SEED,
    distill: int = 60,
    minMessages: int = 6,
    maxWindows: int = 400,
    windowMinutes: float = 5.0,
) -> Dict:
    """Axion 1.0 方学金：答案先行结果采矿 + 教师质量门 + 边界扫描蒸馏。"""
    from neurova.collaboration.triage_axion import buildAxionDataset
    from neurova.collaboration.triage_dataset import realGateTriageFn

    result = buildAxionDataset(
        dataRoot, realGateTriageFn, distillLimit=distill,
        windowMinutes=windowMinutes, maxWindows=maxWindows,
        minMessages=minMessages,
    )
    labelled = []
    for row in result["labeled"]:
        sessionId = row.get("sessionId") or row.get("conversationId") or ""
        labelled.append({
            "sessionId": sessionId,
            "category": row.get("category") or row.get("labeler") or "rules",
            "features": _prepareFeatureVector(row["features"]),
            "label": float(row["label"]),
        })
    if len(labelled) < 8:
        raise RuntimeError(
            f"Axion 管线可训练样本不足（{len(labelled)} < 8）——需要更多会话流量"
        )
    payload = _trainAndEvaluate(
        labelled, result["grayUnlabeled"], len(labelled), seed,
        modelVersion="0.4.0-axion",
    )
    agreementValue = result["teacherAgreement"].get("agreement")
    payload["eval_metrics"].update({
        "outcomeSamples": float(result["outcomeSamples"]),
        "teacherChecked": float(result["teacherAgreement"].get("checked") or 0),
        "teacherAgreement": (float(agreementValue) if agreementValue is not None else -1.0),
        "sweepVectors": float(result["sweepVectors"]),
        "distillUsed": float(result["distillUsed"]),
        "distillErrors": float(result["distillErrors"]),
        "aborted": 1.0 if result["aborted"] else 0.0,
    })
    return payload


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SB-3 离线训练 NeuJudge：合成窗口规则弱标注自举（计划 §5.3/§8-SB-3）；"
        "D-SB3 真实会话数据源 + D-SB1 离线 LLM 蒸馏（--source real，全部离线、运行路径零改动）"
    )
    parser.add_argument("--windows", type=int, default=DEFAULT_WINDOWS, help="合成窗口数量（默认 400）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="固定随机种子（默认 42）")
    parser.add_argument(
        "--source", choices=("synthetic", "real", "axion"), default="synthetic",
        help="训练数据源：synthetic=规则自举合成窗口（默认）；real=从数据根收割真实"
        "会话窗口；axion=Axion 方学（答案先行结果采矿+教师质量门+边界扫描蒸馏）",
    )
    parser.add_argument(
        "--data-root", type=str, default="",
        help="real 源的数据根目录（默认仓库 data/）",
    )
    parser.add_argument(
        "--distill", type=int, default=0,
        help="D-SB1 离线蒸馏配额：灰区窗口用既有 LLM 分诊门离线打弱标签的最大条数"
        "（默认 0=不蒸馏；仅 real 源生效，成本封顶、人工触发）",
    )
    parser.add_argument(
        "--distill-scope", choices=("gray", "audit"), default="audit",
        help="蒸馏范围：gray=仅灰区（规则弃权）窗口；audit=灰区之外再把规则已决"
        "的非平凡窗口送教师复核（不一致即最高价值标注；默认 audit）",
    )
    parser.add_argument(
        "--min-messages", type=int, default=6,
        help="real 源会话入样的最小消息数（默认 6）",
    )
    parser.add_argument(
        "--max-windows", type=int, default=200,
        help="real 源收割窗口上限（默认 200）",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=DEFAULT_OUT,
        help="产物输出路径，默认写到当前工作目录 neu_judge_trained.json",
    )
    args = parser.parse_args(argv)

    if args.source == "axion":
        dataRoot = args.data_root or str(Path(__file__).resolve().parents[2] / "data")
        payload = trainAxionFromRealData(
            dataRoot,
            seed=args.seed,
            distill=args.distill,
            minMessages=args.min_messages,
            maxWindows=args.max_windows,
        )
    elif args.source == "real":
        dataRoot = args.data_root or str(Path(__file__).resolve().parents[2] / "data")
        payload = trainNeuJudgeFromRealData(
            dataRoot,
            seed=args.seed,
            distill=args.distill,
            minMessages=args.min_messages,
            maxWindows=args.max_windows,
            distillScope=args.distill_scope,
        )
    else:
        payload = trainNeuJudge(args.windows, args.seed)
    outPath = Path(args.out)
    outPath.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    metrics = payload["eval_metrics"]
    print(f"已写出权重产物: {outPath}")
    print(
        f"model_version={payload['model_version']} feature_version={payload['feature_version']} "
        f"fingerprint={payload['data_fingerprint']}"
    )
    print(
        f"train={metrics['trainWindows']:.0f} frozen={metrics['frozenWindows']:.0f} "
        f"grey={metrics['greyZoneWindows']:.0f} ({metrics['greyZoneRatio']:.1%}) "
        f"iterations={metrics['iterations']:.0f} finalLoss={metrics['finalLoss']:.6f}"
    )
    print(
        f"accuracy={metrics['accuracy']:.4f} skipPrecision={metrics['skipPrecision']:.4f} "
        f"skipRecall={metrics['skipRecall']:.4f}"
    )
    if "distillUsed" in metrics:
        print(
            f"distillUsed={metrics['distillUsed']:.0f} distillErrors={metrics['distillErrors']:.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
