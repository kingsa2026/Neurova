"""LLM 429 重试设置持久层（2026-09-11，设置页"模型"tab 对齐）。

429 同模型等待重试 + 切换容错的四个参数此前只有 env 开关（见
multi_model_client._get_429_retry_config），生产无管理面。本模块沿用
governance_settings / agent_limits_settings 的模式：JSON 文件持久化 +
管理端读写（require_admin 在端点层）。

优先级约定：环境变量显式设置 > 持久化设置 > 内置默认。

env 键（与 multi_model_client 历史口径一致）：
- NEUROVA_LLM_429_MAX_RETRIES    同模型最大等待重试次数
- NEUROVA_LLM_429_RETRY_INTERVAL 重试间隔秒
- NEUROVA_LLM_429_WAIT_CAP       单次等待封顶秒
- NEUROVA_LLM_MAX_SWITCHES       连续失败模型容错数
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.Lock()

DEFAULTS: Dict[str, Any] = {
    "max_retries": 10,     # 同模型最大等待重试次数
    "interval": 10.0,      # 重试间隔秒（服务端 Retry-After 优先于该间隔）
    "wait_cap": 120.0,     # 单次等待封顶秒（防超长 Retry-After 挂死整轮）
    "max_switches": 5,     # 连续失败模型容错数（任一模型成功出内容即归零）
}

MIN_RETRIES, MAX_RETRIES = 0, 50
MIN_INTERVAL, MAX_INTERVAL = 1.0, 600.0
MIN_CAP, MAX_CAP = 1.0, 3600.0
MIN_SWITCHES, MAX_SWITCHES = 1, 20


def settings_path() -> Path:
    """设置文件路径（NEUROVA_LLM_RETRY_SETTINGS 可覆盖）"""
    custom = os.environ.get("NEUROVA_LLM_RETRY_SETTINGS")
    if custom:
        return Path(custom)
    return Path("data") / "llm_retry_settings.json"


def load_llm_retry_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载设置（文件不存在/损坏 → 内置默认）"""
    p = Path(path) if path else settings_path()
    merged = dict(DEFAULTS)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULTS:
                    if key in data and data[key] is not None:
                        merged[key] = data[key]
    except Exception as e:  # noqa: BLE001 - 读取失败回退默认，不阻断
        logger.warning("加载 LLM 429 重试设置失败，使用默认: %s", e)
    return merged


def save_llm_retry_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """合并保存（原子写：tmp+os.replace）"""
    p = Path(path) if path else settings_path()
    try:
        with _LOCK:
            current = load_llm_retry_settings(p)
            for key, value in data.items():
                if key in DEFAULTS and value is not None:
                    current[key] = value
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, p)
            return True
    except Exception as e:  # noqa: BLE001
        logger.error("保存 LLM 429 重试设置失败: %s", e)
        return False


def _env_float(key: str) -> Optional[float]:
    raw = os.environ.get(key, "")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _env_int(key: str) -> Optional[int]:
    raw = os.environ.get(key, "")
    if not raw or not raw.strip().lstrip("-").isdigit():
        return None
    return int(raw)


def get_effective_llm_retry_settings() -> Dict[str, Any]:
    """生效重试参数（环境变量显式设置优先于持久化设置，最后夹紧到合法区间）。"""
    settings = load_llm_retry_settings()

    env_retries = _env_int("NEUROVA_LLM_429_MAX_RETRIES")
    if env_retries is not None:
        settings["max_retries"] = env_retries
    env_interval = _env_float("NEUROVA_LLM_429_RETRY_INTERVAL")
    if env_interval is not None:
        settings["interval"] = env_interval
    env_cap = _env_float("NEUROVA_LLM_429_WAIT_CAP")
    if env_cap is not None:
        settings["wait_cap"] = env_cap
    env_switches = _env_int("NEUROVA_LLM_MAX_SWITCHES")
    if env_switches is not None:
        settings["max_switches"] = env_switches

    settings["max_retries"] = max(MIN_RETRIES, min(MAX_RETRIES, int(settings["max_retries"])))
    settings["interval"] = max(MIN_INTERVAL, min(MAX_INTERVAL, float(settings["interval"])))
    settings["wait_cap"] = max(MIN_CAP, min(MAX_CAP, float(settings["wait_cap"])))
    settings["max_switches"] = max(MIN_SWITCHES, min(MAX_SWITCHES, int(settings["max_switches"])))
    return settings
