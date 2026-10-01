"""评测噪声地板 — δ 校准与按数据集指纹的缓存。

接受判据阈值 = max(min_improvement, δ)；δ = z × sd(同一基线在同批用例上
重复评测的得分)。确定性评测（sd=0）或未校准（repeats<2 / 用例为空）时
δ=0，判据自动回退 min_improvement——增量不降级。

校准必须复用 runner 的评测路径（evaluate_fn 注入），禁止另写第二套打分；
评测函数抛异常原样上抛，由调用方决定降级——校准失败不造证据。
"""

from __future__ import annotations

import hashlib
import json
import statistics as st
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional, Sequence

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# evaluate_fn(skill_text, examples, artifact_type) -> float，即 runner._evaluate_avg 的形态
EvaluateFn = Callable[[str, Sequence, str], Awaitable[float]]

_MAX_CACHE_ENTRIES = 32


@dataclass
class NoiseBand:
    """一次校准的产物（审计面：method/scores 必须可追溯）。"""

    delta: float
    sd_null: float
    z: float
    method: str  # repeated_baseline_evals | config | uncalibrated
    n_repeats: int
    scores: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["delta"] = round(self.delta, 6)
        d["sd_null"] = round(self.sd_null, 6)
        d["scores"] = [round(x, 6) for x in self.scores]
        return d


async def calibrate_noise_band(
    *,
    baseline_text: str,
    artifact_type: str,
    examples: Sequence,
    evaluate_fn: EvaluateFn,
    z: float = 2.0,
    repeats: int = 3,
) -> NoiseBand:
    """对同一基线在同批用例上独立评测 repeats 次，δ = z·sd(得分)。

    repeats<2 或用例为空 → 未校准（δ=0 且不花评测预算）。
    """
    if repeats < 2 or not examples:
        return NoiseBand(delta=0.0, sd_null=0.0, z=z,
                         method="uncalibrated", n_repeats=max(0, repeats))
    scores = [float(await evaluate_fn(baseline_text, list(examples), artifact_type))
              for _ in range(repeats)]
    sd = st.stdev(scores) if len(scores) > 1 else 0.0
    return NoiseBand(delta=z * sd, sd_null=sd, z=z,
                     method="repeated_baseline_evals", n_repeats=repeats, scores=scores)


def dataset_fingerprint(examples: Sequence) -> str:
    """数据集指纹：按 (task_input, expected_behavior) 排序后 sha256 前 12 位。

    顺序不敏感——同一批用例无论装载顺序如何都命中同一份缓存。
    """
    items = sorted((ex.task_input, ex.expected_behavior) for ex in examples)
    payload = json.dumps(items, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def load_cached_band(cache_path: Path, fingerprint: str) -> Optional[NoiseBand]:
    try:
        data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    band = data.get(fingerprint)
    if not isinstance(band, dict):
        return None
    try:
        return NoiseBand(
            delta=float(band["delta"]),
            sd_null=float(band.get("sd_null", 0.0)),
            z=float(band.get("z", 2.0)),
            method=str(band.get("method", "")),
            n_repeats=int(band.get("n_repeats", 0)),
            scores=[float(x) for x in band.get("scores", [])],
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_cached_band(cache_path: Path, fingerprint: str, band: NoiseBand) -> None:
    path = Path(cache_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data[fingerprint] = band.to_dict()
    for key in list(data)[: -_MAX_CACHE_ENTRIES]:
        data.pop(key, None)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        logger.debug("噪声带缓存落盘失败: %s", e)
