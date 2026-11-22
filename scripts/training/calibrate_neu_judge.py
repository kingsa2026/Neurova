# -*- coding: utf-8 -*-
"""NeuJudge skip 阈值标定（阈值由真实评估集反推，不拍脑袋）。

流程：
1. 构建真实评估集：triage_skips.jsonl 结果采矿（skip 后 5 分钟内人类回归=误杀，
   与 falseRescueStats 同口径）+ 收割窗口的规则高置信放行（human_last/
   human_in_window）；
2. 载入权重产物（默认=运行时默认 neu_judge_default.json）逐行打分；
3. 对 skip_p 网格逐点模拟三档裁决（p<skip_p→skip、p>allow_p→allow、其间弃权
   放行），输出 准确率/skip 精确率/召回率/误拦数(fp)/漏拦数(fn)；
4. 推荐口径：在**零误拦（fp=0）**的行里取最大的 skip_p（最激进的可靠阈值）；
   `--target-precision` 可改为精确率门槛；
5. `--apply` 把推荐（或 `--skip-p` 指定）的阈值写回产物 thresholds 字段，
   并经 NeuJudge.loadFrom 试载验证。

注意：评估集的放行侧与训练集同源（规则标注），指标存在轻度同源偏置——
阈值以"评估集上零误拦"为保守下界，上线后仍以 enforce 真实误杀反馈为准。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neurova.collaboration.neu_judge import (  # noqa: E402
    ALLOW_P,
    FEATURE_KEYS,
    NeuJudge,
    NeuJudgeUnavailable,
    SKIP_P,
)
from neurova.collaboration.triage_boundary import mineOutcomeLabels  # noqa: E402
from neurova.collaboration.triage_dataset import (  # noqa: E402
    harvestSessionWindows,
    labelWindows,
)

DEFAULT_ARTIFACT = (
    Path(__file__).resolve().parents[2] / "neurova" / "collaboration" / "neu_judge_default.json"
)

#: 分域阈值目录（agent_id → 阈值覆盖；运行时由分诊门懒加载）
CATALOGUE_PATH = (
    Path(__file__).resolve().parents[2] / "neurova" / "collaboration" / "neu_judge_catalogue.json"
)


def buildEvalSet(dataRoot: str, maxAllow: int = 60) -> List[Dict]:
    """真实评估集：结果标注的 would-skip + 规则高置信放行（均无教师参与）。"""
    rows: List[Dict] = []
    for row in mineOutcomeLabels(dataRoot):
        rows.append({"features": row["features"], "label": row["label"],
                     "src": f"outcome/{row['outcome']}"})
    windows = harvestSessionWindows(dataRoot, maxWindows=1200, minMessages=6)
    ruled = labelWindows(windows, distillLimit=0)
    allowCount = 0
    for row in ruled["labeled"]:
        if row["label"] == 1:
            # 放行类封顶（skip 类是稀缺正样本，全量保留）
            if allowCount >= maxAllow:
                continue
            allowCount += 1
        rows.append({"features": row["features"], "label": row["label"],
                     "src": f"rules/{row['reason']}"})
    return rows


def simulate(rows: List[Dict], judge: NeuJudge, skipP: float, allowP: float) -> Dict[str, float]:
    """按 (skip_p, allow_p) 模拟三档裁决，返回混淆矩阵与衍生指标。"""
    tp = fp = tn = fn = 0
    for row in rows:
        p = judge.score(row["features"])
        predictedSkip = p < skipP
        actualSkip = row["label"] == 0.0
        if predictedSkip and actualSkip:
            tp += 1
        elif predictedSkip and not actualSkip:
            fp += 1
        elif (not predictedSkip) and actualSkip:
            fn += 1
        else:
            tn += 1
    total = len(rows)
    return {
        "skip_p": round(skipP, 2),
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "skipPrecision": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "skipRecall": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
        "skipped": tp + fp,
        "falseAlarms": fp,
        "missed": fn,
    }


def recommend(results: List[Dict[str, float]], targetPrecision: float) -> Optional[Dict[str, float]]:
    """零误拦行里取最大 skip_p；没有零误拦行则取精确率达标的最大 skip_p。"""
    zeroFp = [r for r in results if r["falseAlarms"] == 0 and r["skipped"] > 0]
    if zeroFp:
        return max(zeroFp, key=lambda r: r["skip_p"])
    qualified = [r for r in results
                 if r["skipped"] > 0 and r["skipPrecision"] >= targetPrecision]
    return max(qualified, key=lambda r: r["skip_p"]) if qualified else None


def applyThresholds(artifactPath: Path, skipP: float, allowP: float) -> None:
    """把标定阈值写回产物 thresholds 字段，并经 NeuJudge.loadFrom 试载验证。"""
    payload = json.loads(artifactPath.read_text(encoding="utf-8"))
    payload["thresholds"] = {"skip_p": round(skipP, 4), "allow_p": round(allowP, 4)}
    artifactPath.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    NeuJudge.loadFrom(artifactPath)  # 试载验证（失败抛 NeuJudgeUnavailable）


def writeCatalogueProfile(agentId: str, skipP: float, allowP: float) -> None:
    """把分域阈值写入目录（agent_id → 阈值覆盖），保留既有档案。"""
    profiles: Dict[str, Any] = {}
    version = 1
    if CATALOGUE_PATH.exists():
        try:
            loaded = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                if isinstance(loaded.get("profiles"), dict):
                    profiles = loaded["profiles"]
                version = loaded.get("version", 1)
        except json.JSONDecodeError:
            pass
    profiles[agentId] = {"thresholds": {"skip_p": round(skipP, 4),
                                        "allow_p": round(allowP, 4)}}
    CATALOGUE_PATH.write_text(
        json.dumps({"version": version, "profiles": profiles},
                   ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NeuJudge skip 阈值标定：真实评估集上反推零误拦的最大 skip_p"
    )
    parser.add_argument("--data-root", default=str(
        Path(__file__).resolve().parents[2] / "data"))
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT),
                        help="待标定的权重产物（默认=运行时默认 neu_judge_default.json）")
    parser.add_argument("--max-allow", type=int, default=60,
                        help="评估集放行类样本上限（默认 60）")
    parser.add_argument("--target-precision", type=float, default=0.99,
                        help="无零误拦行时的精确率门槛（默认 0.99）")
    parser.add_argument("--apply", action="store_true",
                        help="把推荐阈值写回产物 thresholds 字段（试载验证）")
    parser.add_argument("--agent-id", type=str, default=None,
                        help="分域目录：把阈值写为该 agent 的目录档案（替代全局产物阈值）")
    parser.add_argument("--skip-p", type=float, default=None,
                        help="跳过推荐，直接把该阈值写回产物（需 --apply）")
    args = parser.parse_args(argv)

    rows = buildEvalSet(args.data_root, maxAllow=args.max_allow)
    skipCount = sum(1 for r in rows if r["label"] == 0.0)
    if not rows or skipCount == 0:
        print("评估集为空或无 skip 类——先积累真实流量再标定")
        return 1
    judge = NeuJudge.loadFrom(args.artifact)
    allowP = judge.thresholds.get("allow_p", ALLOW_P)

    results = [simulate(rows, judge, skipP, allowP)
               for skipP in [round(0.05 + 0.05 * i, 2) for i in range(12)]]

    print(f"评估集 {len(rows)} 行（skip {skipCount} / allow {len(rows) - skipCount}）"
          f" | 产物 {Path(args.artifact).name} | allow_p={allowP}")
    print(f"{'skip_p':>7}{'accuracy':>10}{'skipP':>8}{'skipR':>8}"
          f"{'skipped':>9}{'误拦':>6}{'漏拦':>6}")
    for r in results:
        print(f"{r['skip_p']:>7.2f}{r['accuracy']:>10.4f}{r['skipPrecision']:>8.4f}"
              f"{r['skipRecall']:>8.4f}{r['skipped']:>9}{r['falseAlarms']:>6}{r['missed']:>6}")

    chosen = ({"skip_p": float(args.skip_p)} if args.skip_p is not None
              else recommend(results, targetPrecision=args.target_precision))
    if chosen:
        chosenRow = next((r for r in results if r["skip_p"] == round(chosen["skip_p"], 2)),
                         None)
        print(f"\n推荐: skip_p={chosen['skip_p']}（零误拦下最激进；"
              f"精确率={chosenRow['skipPrecision'] if chosenRow else '-'}，"
              f"召回={chosenRow['skipRecall'] if chosenRow else '-'}）")
    else:
        print("\n无满足门槛的阈值——评估集太小或特征不可分，保持现值并继续积累")

    if args.apply and chosen:
        if args.agent_id:
            writeCatalogueProfile(args.agent_id, chosen["skip_p"], allowP)
            print(f"已写入分域目录: profiles[{args.agent_id!r}] = "
                  f"{{'skip_p': {chosen['skip_p']}, 'allow_p': {allowP}}}")
        else:
            applyThresholds(Path(args.artifact), chosen["skip_p"], allowP)
            print(f"已写回 {args.artifact}: thresholds={{'skip_p': {chosen['skip_p']}, "
                  f"'allow_p': {allowP}}}（loadFrom 试载通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
