"""
RSI 集成管理器

协调 RSI 与四大闭环系统的交互
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass
from typing import Any, Dict, List

from .gate_verdict import GateVerdict

logger = get_logger(__name__)


@dataclass
class ParameterInfo:
    """参数信息"""

    name: str
    current_value: Any
    description: str
    system: str


class RSIIntegrationManager:
    """RSI 集成管理器 - 协调 RSI 与四大闭环的交互"""

    # 四大闭环系统的可优化参数定义
    # 治理对齐（2026-09-12）：移除 sleep.merge_threshold——它是
    # similarity_threshold 的别名幻影（独立属性后零消费方），同一真实参数
    # 不得有两个 setpoint 互斥；现 merge_threshold 为 property 别名。
    OPTIMIZABLE_PARAMETERS = {
        "sleep": [
            {"name": "base_decay_rate", "description": "基础衰减率"},
            {"name": "similarity_threshold", "description": "相似度阈值"},
        ],
        "emotion": [
            {"name": "emotional_protection_threshold", "description": "情感保护阈值"},
            {"name": "emotional_protection_factor", "description": "情感保护因子"},
        ],
        "experience": [
            {"name": "crystallize_min_observations", "description": "最小观察次数"},
            {"name": "crystallize_min_success_rate", "description": "最小成功率"},
            {"name": "pattern_min_support", "description": "模式最小支持度"},
        ],
        "tool_memory": [
            {"name": "success_bonus", "description": "成功奖励"},
            {"name": "failure_penalty", "description": "失败惩罚"},
            {"name": "decay_rate", "description": "衰减率"},
            {"name": "muscle_memory_threshold", "description": "肌肉记忆阈值"},
        ],
    }

    def __init__(self, sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any):
        """
        初始化 RSI 集成管理器

        Args:
            sleep_system: 睡眠闭环系统
            emotion_system: 情感闭环系统
            experience_system: 经验闭环系统
            tool_memory_system: 工具记忆闭环系统
        """
        self.sleep_system = sleep_system
        self.emotion_system = emotion_system
        self.experience_system = experience_system
        self.tool_memory_system = tool_memory_system

        # 系统名称到系统对象的映射
        self._systems = {
            "sleep": sleep_system,
            "emotion": emotion_system,
            "experience": experience_system,
            "tool_memory": tool_memory_system,
        }

        logger.info("RSIIntegrationManager initialized")

    def get_optimizable_parameters(self) -> Dict[str, List[ParameterInfo]]:
        """获取四大闭环系统中可被 RSI 优化的参数

        工单 018：占位系统（`rsi_placeholder`）返回空参数列表。缺席系统只服务
        `get_feedback` 的中性信号，不得充当参数载体 —— 否则 `orchestrator` 会把
        替身对象上的镜像默认值当真值去寻优，`_measure_performance` 又回读同一个
        对象，棘轮因此"奖励自己编辑空对象"并回执 applied=True。
        在源头返回空列表比在 apply 端拒绝更靠根因：看不见参数就不会产生候选。

        Returns:
            Dict[str, List[ParameterInfo]]: 各系统的可优化参数列表
        """
        result = {}

        for system_name, params_def in self.OPTIMIZABLE_PARAMETERS.items():
            system = self._systems[system_name]
            if self._is_placeholder(system):
                result[system_name] = []
                continue
            params = []

            for param_def in params_def:
                param_name = param_def["name"]
                current_value = getattr(system, param_name, None)

                params.append(
                    ParameterInfo(
                        name=param_name,
                        current_value=current_value,
                        description=param_def["description"],
                        system=system_name,
                    )
                )

            result[system_name] = params

        return result

    @staticmethod
    def _is_placeholder(system: Any) -> bool:
        """是否为"闭环系统缺席"的占位替身。

        显式契约：必须是类上写死的 `rsi_placeholder = True`。
        不用 truthiness —— `MagicMock().rsi_placeholder` 恒为真，
        任何用 MagicMock 冒充闭环系统的测试都会被误判成占位而全线空转。
        也不用 `get_status() == "null_fallback"` 字符串嗅探：那会把契约
        绑在一个本就没有接口保证的返回值上。
        """
        return getattr(system, "rsi_placeholder", False) is True

    def collect_feedback_signals(self) -> Dict[str, Any]:
        """
        从四大闭环系统收集反馈信号

        真正闭环修复：为每个系统注入可优化的 performance_score（0..1）——
        基于 system_performance 的 setpoint 梯度估算（基础反馈 +
        参数贴近度）。此前 sleep/emotion 的 get_feedback() 不暴露性能键，
        导致它们的参数永远不被 RSI 优化。

        工单 018：缺席闭环系统的占位替身是上述注入的例外 —— 只发中性信号并标
        `unevidenced`，不注入估算分（见 `get_placeholder_system_names`）。

        Returns:
            Dict[str, Any]: 各系统的反馈信号（含注入的 performance_score；
                占位系统改为携带 `verdict`，state 为 `unevidenced`）
        """
        from neurova.evolution.rsi.system_performance import estimate_system_performance

        optimizable = self.get_optimizable_parameters()
        signals = {}

        for system_name, system in self._systems.items():
            try:
                if hasattr(system, "get_feedback"):
                    signal = system.get_feedback()
                else:
                    signal = {}
            except Exception as e:
                logger.error("Failed to collect feedback from %s: %s", system_name, e)
                signal = {"error": str(e)}

            if not isinstance(signal, dict):
                signal = {}

            if self._is_placeholder(system):
                # 工单 018 第 4 项：占位替身的中性信号照发，但必须标 `unevidenced`，
                # 且**不得**再由 setpoint 贴近度给它倒推一个性能分 ——
                # 对真实系统那是估算，对不存在的系统就是凭空造数
                # （参数面来自它自己的镜像默认值，分数只代表"空对象离目标多像"）。
                signals[system_name] = dict(signal, verdict=GateVerdict.unevidenced(
                    f"{system_name} 由缺席闭环系统的占位替身顶位：无参数面，性能读数不可估算"
                ).to_dict())
                continue

            # 注入 performance_score（系统自身未暴露时由 setpoint 梯度估算）
            if not isinstance(signal.get("performance_score"), (int, float)):
                params = {
                    p.name: p.current_value
                    for p in optimizable.get(system_name, [])
                }
                params.update({
                    k: v for k, v in vars(system).items()
                    if isinstance(v, (int, float))
                } if hasattr(system, "__dict__") else {})
                signal["performance_score"] = estimate_system_performance(
                    system_name, signal, params
                )

            signals[system_name] = signal

        return signals

    def get_placeholder_system_names(self) -> List[str]:
        """当前由占位替身顶着的闭环系统名（工单 018 第 4 项）。

        缺席必须**可见**：只把替身惰化成"零参数"，运维侧读到的仍是
        `applied_count=0`，与"跑过了但没找到改进空间"无法区分。
        """
        return [
            name for name, system in self._systems.items()
            if self._is_placeholder(system)
        ]

    # 审计 P1-F7：数值参数硬边界（未登记者落 _PARAM_BOUND_DEFAULT 兜底；
    # 负界用 -inf 语义时显式列出）。新增可优化参数须同步登记边界，否则兜底夹紧。
    #
    # 工单 002 边界补齐（一致性守卫
    # tests/unit/evolution/rsi/test_parameter_source_of_truth.py 落地即红）：
    # tool_memory 四参与 experience.pattern_min_support 此前全靠
    # _PARAM_BOUND_DEFAULT=(0.0,100.0) 兜底 —— 对置信度/比率类参数等于不夹紧，
    # apply_optimization 的 10%/轮复利调整可把它们漂出语义域而守卫不触发。
    # 每条边界的依据写在右侧注释；语义判据与 rsi/eval_harness.py 的行为用例同源。
    PARAMETER_BOUNDS = {
        # SleepConsolidation 相似度/衰减率均为 [0,1] 语义（memory_layer/sleep.py:142-144）
        ("sleep", "base_decay_rate"): (0.0, 1.0),
        ("sleep", "similarity_threshold"): (0.0, 1.0),
        # 情感分数归一于 [0,1]，阈值越界即保护永久失活（eval_harness em_threshold_band）
        ("emotion", "emotional_protection_threshold"): (0.0, 1.0),
        ("emotion", "emotional_protection_factor"): (0.0, 10.0),
        # 门槛/支持度为计数语义，至少 1 次观察才有意义（与 crystallize_min_observations 同域）
        ("experience", "crystallize_min_observations"): (1.0, 1000.0),
        ("experience", "crystallize_min_success_rate"): (0.0, 1.0),
        ("experience", "pattern_min_support"): (1.0, 1000.0),
        # success_bonus 为加法递增项、failure_penalty 走乘性 (1-penalty)：
        # 两者 >1 会让单轮跳变越过乘数夹紧区间 [0.3,1.5]（closed_loop.py:68-69,201-211）
        ("tool_memory", "success_bonus"): (0.0, 1.0),
        ("tool_memory", "failure_penalty"): (0.0, 1.0),
        # decay_rate 进 exp(-rate*hours)，>1 即单轮把闲置乘数击穿下限
        # （eval_harness tm_decay_forgetting_band 要求"下降但不越下限"）
        ("tool_memory", "decay_rate"): (0.0, 1.0),
        # 肌肉记忆阈值是置信度基准，语义域 (0,1]（eval_harness tm_threshold_band）
        ("tool_memory", "muscle_memory_threshold"): (0.0, 1.0),
    }
    _PARAM_BOUND_DEFAULT = (0.0, 100.0)

    @classmethod
    def _parameter_bounds(cls, system_name: str, param_name: str) -> tuple:
        return cls.PARAMETER_BOUNDS.get((system_name, param_name), cls._PARAM_BOUND_DEFAULT)

    def apply_optimization(self, parameter_path: str, new_value: Any) -> bool:
        """
        应用优化到指定参数

        Args:
            parameter_path: 参数路径，格式为 "system.parameter_name"
            new_value: 新的参数值

        Returns:
            bool: 是否成功应用
        """
        try:
            # 解析参数路径
            parts = parameter_path.split(".")
            if len(parts) != 2:
                logger.warning("Invalid parameter path: %s", parameter_path)
                return False

            system_name, param_name = parts

            # 检查系统是否存在
            if system_name not in self._systems:
                logger.warning("Unknown system: %s", system_name)
                return False

            # 工单 018 第二道防线：占位替身不接受写入，更不得回执成功
            if self._is_placeholder(self._systems[system_name]):
                logger.warning(
                    "拒绝优化缺席的闭环系统 %s（参数 %s）：占位系统不供参数面",
                    system_name, parameter_path,
                )
                return False

            # 检查参数是否可优化
            system_params = self.OPTIMIZABLE_PARAMETERS.get(system_name, [])
            param_names = [p["name"] for p in system_params]

            if param_name not in param_names:
                logger.warning("Parameter %s not optimizable in %s", param_name, system_name)
                return False

            # 应用优化
            system = self._systems[system_name]
            if hasattr(system, param_name):
                old_value = getattr(system, param_name)
                # 审计 P1-F7：数值参数夹紧——RSI 棘轮调整（10%/次）若无界可
                # 跨迭代复利漂移（如衰减率 >1 或负阈值）
                if isinstance(new_value, (int, float)) and not isinstance(new_value, bool):
                    lo, hi = self._parameter_bounds(system_name, param_name)
                    new_value = max(lo, min(hi, float(new_value)))
                setattr(system, param_name, new_value)
                logger.info("Applied optimization: %s = %s", parameter_path, new_value)
                # C12 回执（工具面审计）：优化前后快照落 JSONL，可审计可回溯
                self._write_optimization_receipt(parameter_path, old_value, new_value)
                return True
            else:
                logger.warning("System %s does not have parameter %s", system_name, param_name)
                return False

        except Exception as e:
            logger.error("Failed to apply optimization: %s", e)
            return False

    def _write_optimization_receipt(self, parameter_path: str, old_value: Any, new_value: Any) -> None:
        """C12：优化回执落盘（JSONL 追加；env NEUROVA_RSI_RECEIPTS 覆盖路径，
        默认 data/evolution/rsi_receipts.jsonl）。写失败仅告警不影响主流程。"""
        import json as _json
        import os as _os
        import time as _time
        from pathlib import Path as _Path

        try:
            env_path = _os.environ.get("NEUROVA_RSI_RECEIPTS")
            if not env_path:
                # 单例零 IO 教义：未显式配置路径（生产由 start_server 注入）不落盘
                return
            path = _Path(env_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            receipt = {
                "ts": _time.time(),
                "parameter_path": parameter_path,
                "old_value": old_value,
                "new_value": new_value,
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(receipt, ensure_ascii=False) + chr(10))
        except Exception as e:
            self._logger.warning("优化回执写入失败: %s", e)

    def get_system_status(self) -> Dict[str, Any]:
        """
        获取四大闭环系统的状态

        Returns:
            Dict[str, Any]: 各系统的运行状态
        """
        status = {}

        for system_name, system in self._systems.items():
            try:
                system_status = {"status": "active"}

                if hasattr(system, "get_status"):
                    system_status.update(system.get_status())

                status[system_name] = system_status

            except Exception as e:
                logger.error("Failed to get status from %s: %s", system_name, e)
                status[system_name] = {"status": "error", "error": str(e)}

        return status


def create_rsi_integration_manager(
    sleep_system: Any, emotion_system: Any, experience_system: Any, tool_memory_system: Any
) -> RSIIntegrationManager:
    """
    创建 RSI 集成管理器实例

    Args:
        sleep_system: 睡眠闭环系统
        emotion_system: 情感闭环系统
        experience_system: 经验闭环系统
        tool_memory_system: 工具记忆闭环系统

    Returns:
        RSIIntegrationManager: RSI 集成管理器实例
    """
    return RSIIntegrationManager(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
    )
