"""实验性评测机制开关设置（N1–N3 治理面，2026-11-13）。

把三项灰度机制升级为**治理设置项**（JSON 持久化 + governance 端点读写，
仅管理员）；env 灰度直改保留最高优先级（与 task_profile_settings /
eval_coreset_settings 同族：env 显式设置 > 设置文件 > 内置默认）。

- profile_variants_enabled：N1 Pareto 多档交付（多变体轮档位轮转评测）；
- lineage_pareto_enabled：N2 候选集并行递归（非劣幸存者进下轮池）；
- diagnosis_rollouts：N3 G-rollout 采样次数（1 = 旧单采样形态）。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import resolveDataPath

logger = get_logger(__name__)

_LOCK = threading.Lock()

DEFAULTS: Dict[str, Any] = {
    "profile_variants_enabled": False,
    "lineage_pareto_enabled": False,
    "diagnosis_rollouts": 1,
}
MIN_DIAGNOSIS_ROLLOUTS = 1
MAX_DIAGNOSIS_ROLLOUTS = 5


def settings_path() -> Path:
    custom = os.environ.get("NEUROVA_EVAL_EXPERIMENT_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("eval_experiment_settings.json")


def _clampRollouts(v: Any) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return DEFAULTS["diagnosis_rollouts"]
    return max(MIN_DIAGNOSIS_ROLLOUTS, min(MAX_DIAGNOSIS_ROLLOUTS, v))


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """env 显式设置 > 设置文件 > 内置默认（全关/1 次采样）。"""
    merged = dict(DEFAULTS)
    p = Path(path) if path else settings_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("profile_variants_enabled") is not None:
                    merged["profile_variants_enabled"] = bool(
                        data["profile_variants_enabled"])
                if data.get("lineage_pareto_enabled") is not None:
                    merged["lineage_pareto_enabled"] = bool(
                        data["lineage_pareto_enabled"])
                if data.get("diagnosis_rollouts") is not None:
                    merged["diagnosis_rollouts"] = _clampRollouts(
                        data["diagnosis_rollouts"])
    except Exception as e:  # noqa: BLE001
        logger.warning("加载实验性评测设置失败，使用默认: %s", e)
    env_variants = os.environ.get("NEUROVA_PROFILE_VARIANTS", "").strip()
    if env_variants:
        merged["profile_variants_enabled"] = env_variants == "1"
    env_pareto = os.environ.get("NEUROVA_LINEAGE_PARETO", "").strip()
    if env_pareto:
        merged["lineage_pareto_enabled"] = env_pareto == "1"
    env_rollouts = os.environ.get("NEUROVA_DIAGNOSIS_ROLLOUTS", "").strip()
    if env_rollouts:
        merged["diagnosis_rollouts"] = _clampRollouts(env_rollouts)
    return merged


def save_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """合并保存（原子写）；diagnosis_rollouts 越界钳位到 1–5。"""
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            current = load_settings(p)
            if "profile_variants_enabled" in data:
                current["profile_variants_enabled"] = bool(
                    data["profile_variants_enabled"])
            if "lineage_pareto_enabled" in data:
                current["lineage_pareto_enabled"] = bool(
                    data["lineage_pareto_enabled"])
            if "diagnosis_rollouts" in data:
                current["diagnosis_rollouts"] = _clampRollouts(
                    data["diagnosis_rollouts"])
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存实验性评测设置失败: %s", e)
            return False


def profile_variants_enabled() -> bool:
    return bool(load_settings()["profile_variants_enabled"])


def lineage_pareto_enabled() -> bool:
    return bool(load_settings()["lineage_pareto_enabled"])


def diagnosis_rollouts() -> int:
    return int(load_settings()["diagnosis_rollouts"])
