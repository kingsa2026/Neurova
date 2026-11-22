# -*- coding: utf-8 -*-
"""Axion 1.0 方法学在 NeuJudge 训练数据上的落地（离线，不在运行链路上）。

方法映射（论文 arXiv:2611.03233 / bytedance/axion1_0 → 本仓）：
- Stage II「先定答案、后出题」（参考答案由确定性程序先行算出）→
  `mineOutcomeLabels`：skip 样本的标签由**可观测结果**决定——recorded_at
  之后 5 分钟内会话出现人类消息 = 误杀（actionable）；否则 = 真跳过。
  教师只在结果不可知的合成变体上打标；
- Stage I「模型感知的边界增强」（组合/参数化/范围偏移/分类讨论）→
  `boundarySweepWindows`：对真实种子窗口沿判定敏感轴做参数化扰动
  （独走长度/人类距离/复读/人类疑问），相同特征向量只保留一份——
  教师一次标注即覆盖全部同特征变体；
- 「剔除不用工具也能解的题」→ 规则高置信窗不占教师配额（规则直标即可）；
- 教师质量门 `teacherAgreement`：先在结果已知的窗口上测教师与结果的一致率，
  低于阈值即中止蒸馏——教师标签不可信时不浪费配额。

纪律：确定性（文件排序、无随机、sha256 去重不用 built-in hash）；特征一律
经 triage_rules.extractTriageFeatures 单源提取；教师调用走
triage_dataset.realGateTriageFn（含节流与内容截断）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.collaboration.triage_rules import extractTriageFeatures

#: 误杀判定窗口（秒）——与 falseRescueStats 同一口径
OUTCOME_WINDOW_SECONDS = 300.0

#: 边界扫描轴（Axion 参数化/范围偏移的映射）
SWEEP_HUMAN_DISTANCES = (0, 3, 6, 10, 15)
SWEEP_STREAKS = (5, 10, 20, 30)

#: 每种子最多派生变体数 / 全局唯一特征向量上限
MAX_VARIANTS_PER_SEED = 12
DEFAULT_MAX_SWEEP_VECTORS = 60

#: 教师质量门默认阈值：结果已知窗口上一致率低于它即中止蒸馏
DEFAULT_AGREEMENT_THRESHOLD = 0.7

_CST = timezone(timedelta(hours=8))


def _candidateTimestamps(value: Any) -> List[datetime]:
    """把落盘时间戳展开成候选 aware datetime 列表。

    aware 值原样；naive 值依次按 CST(+8，房仓现行惯例) 与 UTC(旧库惯例)
    解释——结果采矿对两种落盘口径都试，避免历史数据因时区歧义漏判。
    """
    out: List[datetime] = []
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if value > 1e12 else float(value)
        out.append(datetime.fromtimestamp(seconds, timezone.utc))
        return out
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return out
        if parsed.tzinfo is not None:
            out.append(parsed)
        else:
            out.append(parsed.replace(tzinfo=_CST))
            out.append(parsed.replace(tzinfo=timezone.utc))
    return out


def _loadConversationUserTimestamps(dataRoot: Path, conversationId: str) -> List[datetime]:
    """读会话落盘（<root>/<convId>/sessions/session_*.json）里全部人类消息时间。"""
    stamps: List[datetime] = []
    base = Path(dataRoot) / conversationId / "sessions"
    if not base.exists():
        return stamps
    for path in sorted(base.glob("session_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 离线采矿不因脏数据中断
            continue
        for message in payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "user":
                continue
            stamps.extend(_candidateTimestamps(message.get("timestamp")))
    return stamps


def mineOutcomeLabels(
    dataRoot: str,
    windowMinutes: float = 5.0,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """答案先行（Axion Stage II）：skip 样本的标签由可观测结果决定。

    对 triage_skips.jsonl 的每条样本：其会话在 recorded_at 之后
    `windowMinutes` 分钟内出现人类消息 → 误杀（label=1 actionable）；
    否则 → 真跳过（label=0）。返回训练行（sessionId=outcome/<sample_id>），
    特征直接用样本落盘的闸时刻特征快照（运行时所见，零二次加工）。
    """
    path = Path(dataRoot) / "triage_skips.jsonl"
    if not path.exists():
        return []
    windowSeconds = windowMinutes * 60.0
    cache: Dict[str, List[datetime]] = {}
    rows: List[Dict[str, Any]] = []
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
        recordedAt = _candidateTimestamps(record.get("recorded_at"))
        if not recordedAt:
            continue
        conversationId = str(record.get("conversation_id") or "")
        if conversationId not in cache:
            cache[conversationId] = _loadConversationUserTimestamps(dataRoot, conversationId)
        returnAfter: Optional[float] = None
        for candidate in recordedAt:
            for stamp in cache[conversationId]:
                delta = (stamp - candidate).total_seconds()
                if 0.0 <= delta <= windowSeconds:
                    if returnAfter is None or delta < returnAfter:
                        returnAfter = delta
        falseKill = returnAfter is not None
        sampleId = str(record.get("sample_id") or len(rows))
        rows.append({
            "sessionId": f"outcome/{sampleId}",
            "conversationId": conversationId,
            "features": record["features"],
            "label": 1.0 if falseKill else 0.0,
            "category": "outcome",
            "outcome": "false_kill" if falseKill else "true_skip",
            "returnAfterSec": round(returnAfter, 1) if returnAfter is not None else None,
        })
        if limit is not None and len(rows) >= limit:
            break
    return rows


def _featureKey(features: Dict[str, float]) -> str:
    """特征向量 canonical sha256（6 位小数舍入，去重用；不用 built-in hash）。"""
    canonical = json.dumps(
        {k: round(float(v), 6) for k, v in sorted(features.items())},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _soloEvents(count: int, content: str, base: datetime) -> List[Dict[str, Any]]:
    return [{"role": "assistant", "content": content,
             "timestamp": (base + timedelta(seconds=i * 5)).isoformat()}
            for i in range(count)]


def boundarySweepWindows(
    seedWindows: List[Dict[str, Any]],
    maxVariantsPerSeed: int = MAX_VARIANTS_PER_SEED,
    maxTotal: int = DEFAULT_MAX_SWEEP_VECTORS,
) -> List[Dict[str, Any]]:
    """模型感知边界增强（Axion Stage I 的参数化/范围偏移/组合/分类讨论）。

    对每个种子窗口沿判定敏感轴派生变体：独走长度（5/10/20/30）、人类距离
    （0/3/6/10/15 事件前插入人类消息）、复读（同句 ×3）、人类疑问收尾。
    变体按 extractTriageFeatures 特征向量去重（同特征 = 同标签 = 教师一次
    标注覆盖全部同特征变体），全局 maxTotal 封顶。确定性：无随机。
    """
    variants: List[Dict[str, Any]] = []
    seenKeys = set()
    base0 = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
    for seedIndex, seed in enumerate(seedWindows):
        events = seed.get("events") or []
        agentContent = ""
        for message in reversed(events):
            if message.get("role") == "assistant":
                agentContent = str(message.get("content") or "")[:200]
                break
        if not agentContent:
            agentContent = "接龙内容续写。"
        perSeed: List[Tuple[str, List[Dict[str, Any]]]] = []
        for streak in SWEEP_STREAKS:
            perSeed.append((f"solo{streak}", _soloEvents(streak, agentContent, base0)))
        loop = _soloEvents(15, agentContent, base0)
        for distance in SWEEP_HUMAN_DISTANCES:
            variant = list(loop)
            insertAt = max(0, len(variant) - distance)
            variant.insert(insertAt, {"role": "user", "content": "（人类插话）这里我来复核。",
                                      "timestamp": (base0 + timedelta(seconds=90)).isoformat()})
            perSeed.append((f"dist{distance}", variant))
        repeat = _soloEvents(6, agentContent, base0)
        repeat[-1] = dict(repeat[-2])
        perSeed.append(("repeat3", repeat))
        question = _soloEvents(15, agentContent, base0)
        question.append({"role": "user", "content": "（人类提问）这个方案你确认过吗？",
                         "timestamp": (base0 + timedelta(seconds=120)).isoformat()})
        perSeed.append(("question", question))

        emitted = 0
        for name, variantEvents in perSeed:
            if emitted >= maxVariantsPerSeed:
                break
            features = extractTriageFeatures(variantEvents, "")
            key = _featureKey(features)
            if key in seenKeys:
                continue
            seenKeys.add(key)
            emitted += 1
            variants.append({
                "conversationId": f"sweep/seed{seedIndex}/{name}",
                "events": variantEvents,
                "featureKey": key,
            })
            if len(variants) >= maxTotal:
                return variants
    return variants


def teacherAgreement(
    knownSamples: List[Dict[str, Any]],
    triageFn: Callable[[Dict[str, Any]], bool],
    limit: int = 8,
) -> Dict[str, Any]:
    """教师质量门（Axion：参考答案程序化核验的映射）。

    在**结果已知**的窗口上测教师与结果的一致率：一致率低于阈值说明教师
    标签不可信，调用方应中止蒸馏。knownSamples 元素含 events/label。
    """
    checked = 0
    agrees = 0
    disagreements: List[Dict[str, Any]] = []
    for sample in knownSamples:
        if checked >= limit:
            break
        try:
            verdict = bool(triageFn(sample))
        except Exception:  # noqa: BLE001 - 教师不可用时不消耗预算，如实跳过
            continue
        checked += 1
        if verdict == (sample["label"] == 1.0):
            agrees += 1
        else:
            disagreements.append({"sessionId": sample.get("sessionId"), "teacherSaidActionable": verdict})
    return {
        "checked": checked,
        "agreement": (agrees / checked) if checked else None,
        "disagreements": disagreements,
    }


def buildAxionDataset(
    dataRoot: str,
    triageFn: Callable[[Dict[str, Any]], bool],
    distillLimit: int = 60,
    windowMinutes: float = 5.0,
    agreementThreshold: float = DEFAULT_AGREEMENT_THRESHOLD,
    maxWindows: int = 400,
    minMessages: int = 6,
    maxSweepVectors: int = DEFAULT_MAX_SWEEP_VECTORS,
) -> Dict[str, Any]:
    """完整 Axion 式管线：收割 → 规则直标 → 结果采矿 → 教师质量门 →
    边界扫描 → 教师标注（配额内，特征向量去重，已知标签免费继承）。

    返回 {"labeled": [...], "outcomeSamples", "teacherAgreement",
          "sweepVectors", "distillUsed", "distillErrors", "aborted"}。
    """
    from neurova.collaboration.triage_dataset import (
        harvestSessionWindows,
        labelWindows,
        realGateTriageFn,
    )

    labeled: List[Dict[str, Any]] = []
    windows = harvestSessionWindows(dataRoot, maxWindows=maxWindows, minMessages=minMessages)
    ruled = labelWindows(windows, distillLimit=0)
    for row in ruled["labeled"]:
        labeled.append({
            "sessionId": row.get("sessionId") or row.get("conversationId") or "",
            "conversationId": row.get("conversationId") or "",
            "features": row["features"],
            "label": row["label"],
            "category": row.get("labeler") or "rules",
        })

    outcomeRows = mineOutcomeLabels(dataRoot, windowMinutes=windowMinutes)
    labeled.extend(outcomeRows)

    # 教师质量门：在**结果已知**的真实窗口上测教师与结果的一致率（Axion
    # 「参考答案程序化核验」的映射）。结果行只有特征快照，这里按会话回挂
    # 收割到的真实事件窗口作为教师输入。
    agreement = {"checked": 0, "agreement": None, "disagreements": []}
    if outcomeRows and triageFn is not None:
        outcomeByConversation: Dict[str, float] = {}
        for row in outcomeRows:
            outcomeByConversation[str(row.get("conversationId") or "")] = row["label"]
        knownForGate: List[Dict[str, Any]] = []
        for window in windows:
            conversationId = str(window.get("conversationId") or "")
            for sampleConversation, label in outcomeByConversation.items():
                if conversationId.startswith(sampleConversation + "/"):
                    knownForGate.append({
                        "sessionId": f"gate/{conversationId}",
                        "events": window.get("events") or [],
                        "label": label,
                    })
                    break
        agreement = teacherAgreement(knownForGate, triageFn, limit=8)

    aborted = bool(
        agreement["agreement"] is not None and agreement["agreement"] < agreementThreshold
    )
    distillUsed = 0
    distillErrors = 0
    sweepVectors = 0
    if not aborted and triageFn is not None:
        seeds = windows[:20]
        variants = boundarySweepWindows(seeds, maxTotal=maxSweepVectors)
        knownKeys = {_featureKey(row["features"]) for row in labeled}
        for variant in variants:
            if variant["featureKey"] in knownKeys:
                continue  # 已有同特征标签：免费继承，不花教师配额
            if distillUsed >= distillLimit:
                break
            try:
                actionable = bool(triageFn(variant))
            except Exception:  # noqa: BLE001 - 教师失败诚实计数，变体弃权
                distillErrors += 1
                continue
            distillUsed += 1
            knownKeys.add(variant["featureKey"])
            sweepVectors += 1
            labeled.append({
                "sessionId": f"axion/{variant['conversationId']}",
                "features": extractTriageFeatures(variant["events"], ""),
                "label": 1.0 if actionable else 0.0,
                "category": "axion_sweep",
            })
    return {
        "labeled": labeled,
        "outcomeSamples": len(outcomeRows),
        "teacherAgreement": agreement,
        "sweepVectors": sweepVectors,
        "distillUsed": distillUsed,
        "distillErrors": distillErrors,
        "aborted": aborted,
        "rulesLabeled": len(ruled["labeled"]),
    }
