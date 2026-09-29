"""治理设置持久层（治理遗留收口 2026-09-05）

Step9.96 对话规则提取的 LLM 成本门控此前只有 env 开关（NEUROVA_CONVERSATION_RULES），
生产无管理面；RSI 部署阶段同样只能靠 env。本模块提供独立于 /v1/settings 扁平 kv 的
治理设置：JSON 文件持久化 + 管理端读写（require_admin 在端点层）。

V3 调控门（NEUROVA_METACOG_GATE）同病同治：裸 env 开关在生产无写入方，导致教训的
硬拦截臂恒关，故一并纳入本设置面（metacog_gate_enabled）。工单 015 把同病的另两个
裸 env（结晶 LLM 裁决闸、技能自动淘汰）收进同一设置面，并抽出 `resolve_flag`
作为优先级口径的唯一事实源。

优先级约定：env 显式设 0 强制关 > env 显式设 1 强制开 > 治理设置值 > 内置默认。

进程级单文件与 `rsi_phase` 的归属（工单 005 明确并写死，不改行为）：
本设置面是**一个进程一份 JSON**，`rsi_phase` 因而是全局的而非按 agent 的。
两个写入方共用同一颗键：管理端（`api/endpoints/governance.py`）代表人工设定，
`RSIOrchestrator._persist_rsi_phase` 代表自动晋升的回写。多 agent 场景下每个
编排器各持一个部署控制器，谁最后晋升谁的阶段留在盘上（后写者胜）；按 agent 隔离
阶段属"明确不做"，因为阶段说的是"这套部署允许 RSI 走多远"，是运维决定而非
每个 agent 的私有状态。要读当前阶段的唯一真相，读这个文件，不要读任一进程里的
内存值 —— 后者在重启后按本文件重建。
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
    "conversation_rules_enabled": False,  # Step9.96 LLM 成本门控，默认关
    "rsi_phase": 0,  # RSI 部署阶段 0..4（0=观察）
    "metacog_gate_enabled": False,  # V3 调控门（教训拦截工具），默认关
    # 工单 015 收口的两个裸 env。默认值＝收口前的现网默认，不顺手改口径
    "crystallization_llm_gate_enabled": True,  # 结晶 LLM 裁决闸（关=候选直写存储引擎）
    "skill_auto_retire_enabled": False,  # 技能自动淘汰（关=只上报候选不执行禁用）
    # 压缩经济性判据（关=沿用"必然装不下就等比缩小"的既有行为，现网零变更）
    "compression_economics_enabled": False,
    # G5-D：治理判 ASK 时，执行咽喉阻塞等待人工裁决的上界（秒）。
    # 为什么必须有键、而不是在代码里写字面量：把"不阻塞"改成"阻塞"之后，
    # 没有上界的阻塞就是永久挂起——审批人在别处、不点、会话就永远卡在这一次调用上。
    #
    # 默认 **0＝不阻塞**，沿用收口前的现网语义（pending 当结果 + 带外重放投递），
    # 与 `工单 015` 立的口径同形："默认值＝收口前的现网默认，不顺手改口径"。
    # 阻塞会把每个 ASK 变成最长 budget 的停顿，属于必须由运维显式开启的行为变更。
    "approval_wait_seconds": 0.0,
}

#: `approval_wait_seconds` 的合法域。夹紧而非报错：配置写歪不该让整轮失败。
APPROVAL_WAIT_BOUNDS = (0.0, 3600.0)


def settings_path() -> Path:
    """治理设置文件路径（NEUROVA_GOVERNANCE_SETTINGS 可覆盖）"""
    custom = os.environ.get("NEUROVA_GOVERNANCE_SETTINGS")
    if custom:
        return Path(custom)
    return resolveDataPath("governance_settings.json")


def load_governance_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载治理设置（文件不存在/损坏 → 内置默认）"""
    p = Path(path) if path else settings_path()
    merged = dict(DEFAULTS)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULTS:
                    if key in data:
                        merged[key] = data[key]
    except Exception as e:  # noqa: BLE001 - 读取失败回退默认，不阻断
        logger.warning("治理设置加载失败，使用默认: %s", e)
    return merged


def save_governance_settings(data: Dict[str, Any], path: Optional[Path] = None) -> bool:
    """保存治理设置（merge 进现有值后落盘）"""
    p = Path(path) if path else settings_path()
    with _LOCK:
        try:
            current = load_governance_settings(p)
            for key in DEFAULTS:
                if key in data:
                    current[key] = data[key]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("治理设置已保存: %s", p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("治理设置保存失败: %s", e)
            return False


def resolve_flag(key: str, env_var: str) -> bool:
    """治理布尔开关的唯一优先级口径（工单 015，与 metacog_gate_enabled 同形）。

    env 显式 "0" 强制关 > env 显式 "1" 强制开 > 治理设置值 > DEFAULTS 内置默认。
    env 里是别的值（拼错、空串）不算"显式设置"，仍由治理面决定——否则一个
    写歪的 `NEUROVA_X=` 会把整个管理面旁路掉。

    必须在**决策时刻**调用：构造期把结果缓存成属性，等于又造出一个
    "治理页能改、运行时不认"的幻影旋钮（015 收口前的老毛病）。
    """
    if key not in DEFAULTS:
        raise KeyError(f"治理开关 {key!r} 未在 DEFAULTS 声明，读不到即不可用")
    raw = os.environ.get(env_var)
    if raw == "0":
        return False
    if raw == "1":
        return True
    return bool(load_governance_settings()[key])


def resolve_seconds(key: str, env_var: str, bounds: tuple) -> float:
    """治理数值开关的优先级口径——与 `resolve_flag` 同一条，只是值域不同。

    为什么不另写一份读法、也不在调用方就地 `float(env or default)`：优先级
    "env > 治理面 > 默认"这件事若有两份实现，两份迟早对不上（一个认 env、
    一个不认），而这正是本模块被抽出来的原因。

    `bounds` 必填：无上界的"可配置"等于把会话挂起的时长交给一个手滑的数字。
    env 里写歪（非数字/越界）不旁路治理面，与 resolve_flag 对"别的值"的处置同形。
    """
    if key not in DEFAULTS:
        raise KeyError(f"治理数值键 {key!r} 未在 DEFAULTS 声明，读不到即不可用")
    low, high = bounds
    raw = os.environ.get(env_var)
    if raw is not None:
        try:
            return min(max(float(raw), low), high)
        except (TypeError, ValueError):
            logger.debug("%s 环境变量 %r 非数值，回落治理面", key, raw)
    try:
        value = float(load_governance_settings()[key])
    except (TypeError, ValueError):
        value = float(DEFAULTS[key])
    return min(max(value, low), high)
