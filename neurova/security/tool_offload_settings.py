"""工具结果溢出阈值设置持久层（P1 #6，对比报告 §5.6 定稿）。

单源参数：可重现工具结果超过该阈值（KB）时全文落工作区文件、消息体留
预览+指针；不可重现工具豁免（全文直进会话台账）。agent_limits_settings
同模式：JSON 持久 + 管理端读写 + env 优先。

优先级约定：环境变量 NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB 显式设置
> tool_offload 设置 > 内置默认 64。
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

DEFAULT_THRESHOLD_KB = 64
MIN_THRESHOLD_KB = 8
MAX_THRESHOLD_KB = 512  # 上限拍板 2026-09-13（512KB 之上的单结果实际只剩
# execute 类长输出，其要么可重放（落文件零损失）要么走豁免，2M 收益为空而
# 会话读取面成本实打实）

DEFAULTS: Dict[str, Any] = {"threshold_kb": DEFAULT_THRESHOLD_KB}


def settings_path() -> Path:
    custom = os.environ.get("NEUROVA_TOOL_OFFLOAD_SETTINGS")
    if custom:
        return Path(custom)
    return Path("data") / "tool_offload_settings.json"


def _clamp(v: Any) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD_KB
    return max(MIN_THRESHOLD_KB, min(MAX_THRESHOLD_KB, v))


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """env 优先 > 文件 > 默认；损坏文件回落默认（agent_limits 同语义）。"""
    p = Path(path) if path else settings_path()
    merged = dict(DEFAULTS)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("threshold_kb") is not None:
                merged["threshold_kb"] = _clamp(data["threshold_kb"])
    except Exception as e:  # noqa: BLE001
        logger.warning("加载 tool_offload 设置失败，使用默认: %s", e)
    env = os.environ.get("NEUROVA_TOOL_OFFLOAD_THRESHOLD_KB")
    if env:
        merged["threshold_kb"] = _clamp(env)
    return merged


def get_threshold_kb() -> int:
    return int(load_settings()["threshold_kb"])


def save_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """校验并原子落盘（temp+os.replace）。threshold_kb 超范围钳位。"""
    if "threshold_kb" not in data:
        return False
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            merged = load_settings(p)
            merged["threshold_kb"] = _clamp(data["threshold_kb"])
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("保存 tool_offload 设置失败: %s", e)
            return False
