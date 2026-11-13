"""任务级档位分类器开关设置（R3 治理面，2026-11-13）。

`NEUROVA_TASK_PROFILE` 环境变量原本是唯一的开关（灰度直开形态）；本模块把
它升级为**设置项**：JSON 文件持久化 + governance 管理端读写（仅管理员），
env 仍保留最高优先级（灰度/应急直开，优先级约定与 agent_limits_settings
同族：env 显式设置 > 设置文件 > 内置默认关）。
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

DEFAULTS: Dict[str, Any] = {"classification_enabled": False}


def settings_path() -> Path:
    custom = os.environ.get("NEUROVA_TASK_PROFILE_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("task_profile_settings.json")


def _envEnabled() -> Optional[bool]:
    """env 灰度直开形态：NEUROVA_TASK_PROFILE=1 开 / =0 关 / 未设 None。"""
    raw = os.environ.get("NEUROVA_TASK_PROFILE", "").strip()
    if raw == "1":
        return True
    if raw == "0":
        return False
    return None


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """env 显式设置 > 设置文件 > 内置默认关；损坏文件回落默认。"""
    merged = dict(DEFAULTS)
    p = Path(path) if path else settings_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("classification_enabled") is not None:
                merged["classification_enabled"] = bool(data["classification_enabled"])
    except Exception as e:  # noqa: BLE001
        logger.warning("加载任务级档位设置失败，使用默认: %s", e)
    env = _envEnabled()
    if env is not None:
        merged["classification_enabled"] = env
    return merged


def save_settings(classification_enabled: bool, path: Optional[Path] = None) -> bool:
    """原子写（tmp+os.replace）；布尔值直存。"""
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps({"classification_enabled": bool(classification_enabled)},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存任务级档位设置失败: %s", e)
            return False


def classification_enabled() -> bool:
    """生效开关（env > 文件 > 默认关）——turn_profile.taskProfileEnabled 的单源。"""
    return bool(load_settings()["classification_enabled"])
