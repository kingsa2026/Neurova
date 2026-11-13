"""评测集核选 K 值设置（R7/HC6 治理面，2026-11-13）。

核选此前只挂在 `EvolutionConfig.eval_coreset_k`（代码级默认 0=关）；本模块
把它升级为**治理设置项**：JSON 持久化 + governance 端点读写（仅管理员），
env `NEUROVA_EVAL_CORESET_K` 保留灰度直改的最高优先级（与
task_profile_settings 同族：env 显式设置 > 设置文件 > 内置默认）。

合法域 0–200：0 = 不核选（逐字旧行为）；上限 200 防止「核选」退化成
「全量」（核选的意义是小核选集探路）。
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

DEFAULTS: Dict[str, Any] = {"coreset_k": 0}
MIN_CORESET_K = 0
MAX_CORESET_K = 200


def settings_path() -> Path:
    custom = os.environ.get("NEUROVA_EVAL_CORESET_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("eval_coreset_settings.json")


def _clamp(v: Any) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return max(MIN_CORESET_K, min(MAX_CORESET_K, v))


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """env 显式设置 > 设置文件 > 内置默认 0；损坏文件回落默认。"""
    merged = dict(DEFAULTS)
    p = Path(path) if path else settings_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("coreset_k") is not None:
                merged["coreset_k"] = _clamp(data["coreset_k"])
    except Exception as e:  # noqa: BLE001
        logger.warning("加载核选设置失败，使用默认: %s", e)
    env = os.environ.get("NEUROVA_EVAL_CORESET_K", "").strip()
    if env:
        merged["coreset_k"] = _clamp(env)
    return merged


def save_settings(coreset_k: int, path: Optional[Path] = None) -> bool:
    """原子写（tmp+os.replace）；越界钳位到合法域。"""
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"coreset_k": _clamp(coreset_k)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存核选设置失败: %s", e)
            return False


def coreset_k() -> int:
    """生效核选容量（env > 文件 > 默认 0）。"""
    return int(load_settings()["coreset_k"])
