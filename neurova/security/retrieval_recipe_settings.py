"""检索配方设置（C3，graphiti 对照批）。

active_recipe：命名检索配方（default/balanced/precise/graph_expanded），
参数定义单源在 `neurova/knowledge/search_recipes.py`。优先级与
eval_experiment_settings 同族纪律：env 显式设置（NEUROVA_RETRIEVAL_RECIPE）
> 设置文件 > 内置 default。
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

DEFAULTS: Dict[str, Any] = {"active_recipe": "default"}


def settings_path() -> Path:
    custom = os.environ.get("NEUROVA_RETRIEVAL_RECIPE_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("retrieval_recipe_settings.json")


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """读当前配方名与来源。非法名一律回落 default（不炸、不伪造来源）。"""
    merged: Dict[str, Any] = {"active_recipe": "default", "source": "default"}
    p = Path(path) if path else settings_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("active_recipe"):
                merged["active_recipe"] = str(data["active_recipe"])
                merged["source"] = "file"
    except Exception as e:  # noqa: BLE001
        logger.warning("加载检索配方设置失败，使用默认: %s", e)
    env_recipe = os.environ.get("NEUROVA_RETRIEVAL_RECIPE", "").strip()
    if env_recipe:
        merged["active_recipe"] = env_recipe
        merged["source"] = "env"
    from neurova.knowledge.search_recipes import RECIPE_NAMES

    if merged["active_recipe"] not in RECIPE_NAMES:
        logger.warning("检索配方名 %r 不在可选集，回落 default", merged["active_recipe"])
        merged["active_recipe"] = "default"
        merged["source"] = "default"
    return merged


def save_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """保存 active_recipe（原子写）。非法配方名抛 ValueError（端点转 422）；
    IO 失败返回 False（端点转 500）。"""
    name = str(data.get("active_recipe") or "").strip().lower()
    from neurova.knowledge.search_recipes import RECIPE_NAMES

    if name not in RECIPE_NAMES:
        raise ValueError("未知检索配方: %r（可选 %s）" % (name, "/".join(RECIPE_NAMES)))
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"active_recipe": name},
                                      ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存检索配方设置失败: %s", e)
            return False
