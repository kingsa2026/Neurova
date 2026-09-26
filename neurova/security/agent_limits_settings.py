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
from neurova.core.data_root import resolveDataPath

logger = get_logger(__name__)

_LOCK = threading.Lock()

DEFAULTS: Dict[str, Any] = {
    # TokenBudgetGate：单次会话累计 token 预算上限（prompt+completion）
    "token_budget": 100000,
    # IterationGate：单次会话最大工具循环轮次
    "max_loop_rounds": 20,
    # GoalGate：单轮内"目标未达成 → 注入提示续跑"的次数上限。
    # **独立配置键**，不与 max_loop_rounds 共享尺度来源——一次续跑消耗本键一格，
    # 不消耗工具轮预算（IterationGate 因同键两尺度被机器算成 scaled_sparse，
    # 本键不得再现该形态；阈值可达性由 tool_loop_deadline_ledger 机器复算）。
    "goal_max_continuations": 2,
    # GoalGate 总开关：目标验收链的成本闸（默认**开**）。
    # 默认关等于"接了线不通电"——本片修的正是"假完成无人拦"，关着就等于没修。
    # 成本边界由**目标是否存在**守住（无目标 → 零判定调用，见 D-4），
    # 本开关只作运营侧的成本闸，且已登记进 toolLoopDeadlines 台账（不留只写不读的配置）。
    "goal_verification_enabled": True,
    # 单批工具调用并行上限（护栏）：一轮里资格项成组并发时的组内上限。
    # 4 已能在典型"读 3~4 个文件"场景吃满收益；更高只会加剧连接池/共享外设
    # 竞争。它是**独立配置键**：不与 max_loop_rounds 共享尺度（那个键已有
    # 两尺度，见下方 GoalGate 注释）。
    "max_parallel_tools": 4,
}

MIN_TOKEN_BUDGET = 1000
MAX_TOKEN_BUDGET = 10_000_000
MIN_ROUNDS = 2
MAX_ROUNDS = 200
# 续跑预算合法域：0 = 只判定不续跑（判定结果仍入观测面），上限 5
# （每次续跑 ≈ 一次完整模型往返，3 次以上收益递减且会掩盖"目标本身不可达"）。
MIN_GOAL_CONTINUATIONS = 0
MAX_GOAL_CONTINUATIONS = 5
# 并行上限合法域。下界 1 = 串行（关掉并行组的唯一形态）；
# 上界 16 与 `ToolOrchestrator._max_parallel` 的默认量级同档：再高没有收益，
# 只会让一轮把连接池/共享外设的等待叠在一起。
MIN_PARALLEL_TOOLS = 1
MAX_PARALLEL_TOOLS = 16


def settings_path() -> Path:
    """设置文件路径（NEUROVA_AGENT_LIMITS_SETTINGS 可覆盖）"""
    custom = os.environ.get("NEUROVA_AGENT_LIMITS_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("agent_limits_settings.json")


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

    env_parallel = os.environ.get("NEUROVA_AGENT_MAX_PARALLEL_TOOLS")
    if env_parallel and env_parallel.isdigit():
        settings["max_parallel_tools"] = int(env_parallel)

    # 夹紧到合法区间
    settings["token_budget"] = max(
        MIN_TOKEN_BUDGET, min(MAX_TOKEN_BUDGET, int(settings["token_budget"]))
    )
    settings["max_loop_rounds"] = max(
        MIN_ROUNDS, min(MAX_ROUNDS, int(settings["max_loop_rounds"]))
    )
    settings["goal_max_continuations"] = max(
        MIN_GOAL_CONTINUATIONS,
        min(MAX_GOAL_CONTINUATIONS, int(settings["goal_max_continuations"])),
    )
    settings["goal_verification_enabled"] = bool(settings["goal_verification_enabled"])
    settings["max_parallel_tools"] = max(
        MIN_PARALLEL_TOOLS,
        min(MAX_PARALLEL_TOOLS, int(settings["max_parallel_tools"])),
    )
    return settings
