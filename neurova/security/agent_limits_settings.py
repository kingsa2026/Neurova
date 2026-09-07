"""Agent 运行限制设置持久层（2026-09-07）。

聊天 Agent Loop 的两道安全门控——Token 预算上限（TokenBudgetGate）与
单次会话最大 Loop 轮次（IterationGate）——此前硬编码在 openai_loop.py
（100000 token / 20 轮），生产无管理面。本模块沿用 governance_settings
的模式：JSON 文件持久化 + 管理端读写（require_admin 在端点层）。

优先级约定：环境变量显式设置 > agent_limits 设置 > 内置默认。
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
    # TokenBudgetGate：单次会话累计 token 预算上限（prompt+completion）
    "token_budget": 100000,
    # IterationGate：单次会话最大工具循环轮次
    "max_loop_rounds": 20,
}

MIN_TOKEN_BUDGET = 1000
MAX_TOKEN_BUDGET = 10_000_000
MIN_ROUNDS = 2
MAX_ROUNDS = 200


def settings_path() -> Path:
    """设置文件路径（NEUROVA_AGENT_LIMITS_SETTINGS 可覆盖）"""
    custom = os.environ.get("NEUROVA_AGENT_LIMITS_SETTINGS")
    if custom:
        return Path(custom)
    return Path("data") / "agent_limits_settings.json"


def load_agent_limits(path: Optional[Path] = None) -> Dict[str, Any]:
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
    except Exception as e:  # noqa: BLE001
        logger.warning("加载 agent limits 设置失败，使用默认: %s", e)
    return merged


def save_agent_limits(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """合并保存（原子写：tmp+os.replace）"""
    p = Path(path) if path else settings_path()
    try:
        with _LOCK:
            current = load_agent_limits(p)
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
        logger.error("保存 agent limits 设置失败: %s", e)
        return False


def get_effective_limits() -> Dict[str, Any]:
    """生效限制值（环境变量显式设置优先于持久化设置）。

    env 键：NEUROVA_AGENT_TOKEN_BUDGET / NEUROVA_AGENT_MAX_LOOP_ROUNDS
    """
    settings = load_agent_limits()

    env_budget = os.environ.get("NEUROVA_AGENT_TOKEN_BUDGET")
    if env_budget and env_budget.isdigit():
        settings["token_budget"] = int(env_budget)

    env_rounds = os.environ.get("NEUROVA_AGENT_MAX_LOOP_ROUNDS")
    if env_rounds and env_rounds.isdigit():
        settings["max_loop_rounds"] = int(env_rounds)

    # 夹紧到合法区间
    settings["token_budget"] = max(
        MIN_TOKEN_BUDGET, min(MAX_TOKEN_BUDGET, int(settings["token_budget"]))
    )
    settings["max_loop_rounds"] = max(
        MIN_ROUNDS, min(MAX_ROUNDS, int(settings["max_loop_rounds"]))
    )
    return settings
