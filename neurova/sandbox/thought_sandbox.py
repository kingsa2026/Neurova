"""
Thought Sandbox - 思维沙箱

提供安全隔离的思维实验环境，允许 Agent 在沙箱中进行推理和模拟，
而不影响主系统的状态。支持：
1. 安全的代码执行环境
2. 推理模拟和假设测试
3. 思维回滚和状态恢复
4. 执行超时和资源限制
"""

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SandboxState(str, Enum):
    """沙箱状态"""

    IDLE = "idle"  # 空闲
    RUNNING = "running"  # 运行中
    PAUSED = "paused"  # 暂停
    COMPLETED = "completed"  # 完成
    FAILED = "failed"  # 失败
    TIMEOUT = "timeout"  # 超时
    ROLLED_BACK = "rolled_back"  # 已回滚


class ThoughtType(str, Enum):
    """思维类型"""

    REASONING = "reasoning"  # 推理
    HYPOTHESIS = "hypothesis"  # 假设
    SIMULATION = "simulation"  # 模拟
    ANALYSIS = "analysis"  # 分析
    EXPLORATION = "exploration"  # 探索
    COUNTERFACTUAL = "counterfactual"  # 反事实推理


@dataclass
class ThoughtStep:
    """思维步骤"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thought_type: ThoughtType = ThoughtType.REASONING
    content: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "step_id": self.step_id,
            "thought_type": self.thought_type.value,
            "content": self.content,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class ThoughtSnapshot:
    """思维快照（用于回滚）"""

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: Dict[str, Any] = field(default_factory=dict)
    step_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "snapshot_id": self.snapshot_id,
            "state": self.state,
            "step_count": self.step_count,
            "created_at": self.created_at,
        }


@dataclass
class SandboxResult:
    """沙箱执行结果"""

    session_id: str = ""
    state: SandboxState = SandboxState.COMPLETED
    steps: List[ThoughtStep] = field(default_factory=list)
    final_output: Dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    error: Optional[str] = None
    snapshots: List[ThoughtSnapshot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "final_output": self.final_output,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "snapshot_count": len(self.snapshots),
        }


class ThoughtSandbox:
    """
    思维沙箱

    为 Agent 提供安全的思维实验环境，支持推理模拟、
    假设测试和状态回滚。

    使用示例:
        sandbox = ThoughtSandbox()
        result = sandbox.run(
            thought_type=ThoughtType.REASONING,
            content="如果用户说的是反话...",
            steps=[
                {"type": "reasoning", "content": "分析语气"},
                {"type": "hypothesis", "content": "假设用户不满"},
            ],
        )
    """

    def __init__(
        self,
        max_steps: int = 100,
        timeout_seconds: float = 30.0,
        max_snapshots: int = 10,
    ):
        """
        初始化思维沙箱

        Args:
            max_steps: 最大步骤数
            timeout_seconds: 超时时间
            max_snapshots: 最大快照数
        """
        self._max_steps = max_steps
        self._timeout_seconds = timeout_seconds
        self._max_snapshots = max_snapshots

        # 当前状态
        self._state = SandboxState.IDLE
        self._current_session_id: Optional[str] = None
        self._steps: List[ThoughtStep] = []
        self._snapshots: deque = deque(maxlen=max_snapshots)
        self._state_data: Dict[str, Any] = {}

        # 线程安全
        self._lock = threading.RLock()

        # 自定义步骤处理器
        self._step_handlers: Dict[str, Callable] = {}

        logger.info("ThoughtSandbox initialized")

    @property
    def state(self) -> SandboxState:
        """获取沙箱状态"""
        return self._state

    @property
    def step_count(self) -> int:
        """获取步骤数"""
        return len(self._steps)

    def register_handler(self, thought_type: str, handler: Callable):
        """
        注册步骤处理器

        Args:
            thought_type: 思维类型
            handler: 处理函数
        """
        self._step_handlers[thought_type] = handler

    def run(
        self,
        thought_type: ThoughtType = ThoughtType.REASONING,
        content: str = "",
        steps: Optional[List[Dict[str, Any]]] = None,
        initial_state: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> SandboxResult:
        """
        运行思维沙箱

        Args:
            thought_type: 思维类型
            content: 思维内容描述
            steps: 思维步骤列表
            initial_state: 初始状态
            context: 上下文信息

        Returns:
            执行结果
        """
        with self._lock:
            session_id = str(uuid.uuid4())
            self._current_session_id = session_id
            self._state = SandboxState.RUNNING
            self._steps = []
            self._state_data = initial_state or {}

            start_time = time.time()
            error = None

            try:
                # 执行初始思维
                initial_step = self._execute_step(
                    thought_type=thought_type,
                    content=content,
                    input_data=context or {},
                )
                self._steps.append(initial_step)

                # 执行步骤
                if steps:
                    for step_def in steps:
                        if len(self._steps) >= self._max_steps:
                            break

                        step_type = ThoughtType(step_def.get("type", "reasoning"))
                        step_content = step_def.get("content", "")
                        step_input = step_def.get("input", {})

                        # 检查超时
                        elapsed = time.time() - start_time
                        if elapsed > self._timeout_seconds:
                            self._state = SandboxState.TIMEOUT
                            error = f"Timeout after {elapsed:.1f}s"
                            break

                        step = self._execute_step(
                            thought_type=step_type,
                            content=step_content,
                            input_data=step_input,
                        )
                        self._steps.append(step)

                if self._state == SandboxState.RUNNING:
                    self._state = SandboxState.COMPLETED

            except Exception as e:
                self._state = SandboxState.FAILED
                error = str(e)
                logger.error("Sandbox execution failed: %s", e)

            total_duration = (time.time() - start_time) * 1000

            result = SandboxResult(
                session_id=session_id,
                state=self._state,
                steps=self._steps,
                final_output=self._state_data.copy(),
                total_duration_ms=total_duration,
                error=error,
                snapshots=list(self._snapshots),
            )

            self._state = SandboxState.IDLE
            return result

    def _execute_step(
        self,
        thought_type: ThoughtType,
        content: str,
        input_data: Dict[str, Any],
    ) -> ThoughtStep:
        """
        执行单个思维步骤

        Args:
            thought_type: 思维类型
            content: 内容
            input_data: 输入数据

        Returns:
            思维步骤
        """
        step = ThoughtStep(
            thought_type=thought_type,
            content=content,
            input_data=input_data,
        )

        start_time = time.time()

        try:
            # 检查是否有自定义处理器
            handler = self._step_handlers.get(thought_type.value)
            if handler:
                output = handler(content, input_data, self._state_data)
                step.output_data = output if isinstance(output, dict) else {"result": output}
            else:
                # 默认处理
                step.output_data = {
                    "thought": content,
                    "type": thought_type.value,
                    "processed": True,
                }

            # 更新状态数据
            self._state_data[f"step_{step.step_id}"] = step.output_data
            step.confidence = 0.8  # 默认置信度

        except Exception as e:
            step.output_data = {"error": str(e)}
            step.confidence = 0.0
            logger.warning("Step execution error: %s", e)

        step.duration_ms = (time.time() - start_time) * 1000
        return step

    def create_snapshot(self) -> ThoughtSnapshot:
        """
        创建当前状态快照

        Returns:
            快照对象
        """
        with self._lock:
            snapshot = ThoughtSnapshot(
                state=self._state_data.copy(),
                step_count=len(self._steps),
            )
            self._snapshots.append(snapshot)
            return snapshot

    def rollback_to_snapshot(self, snapshot_id: str) -> bool:
        """
        回滚到指定快照

        Args:
            snapshot_id: 快照 ID

        Returns:
            是否回滚成功
        """
        with self._lock:
            for snapshot in reversed(self._snapshots):
                if snapshot.snapshot_id == snapshot_id:
                    self._state_data = snapshot.state.copy()
                    self._steps = self._steps[: snapshot.step_count]
                    self._state = SandboxState.ROLLED_BACK
                    logger.info("Rolled back to snapshot %s", snapshot_id)
                    return True
            return False

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态数据"""
        with self._lock:
            return self._state_data.copy()

    def set_state(self, key: str, value: Any):
        """设置状态数据"""
        with self._lock:
            self._state_data[key] = value

    def get_steps(self) -> List[Dict[str, Any]]:
        """获取所有步骤"""
        with self._lock:
            return [step.to_dict() for step in self._steps]

    def clear(self):
        """清空沙箱状态"""
        with self._lock:
            self._state = SandboxState.IDLE
            self._steps.clear()
            self._state_data.clear()
            self._snapshots.clear()

    def __repr__(self) -> str:
        """字符串表示"""
        return f"ThoughtSandbox(state={self._state.value}, steps={len(self._steps)})"


# ============================================================
# 全局实例
# ============================================================

_global_sandbox: Optional[ThoughtSandbox] = None
_sandbox_lock = threading.Lock()


def get_thought_sandbox(
    max_steps: int = 100,
    timeout_seconds: float = 30.0,
) -> ThoughtSandbox:
    """
    获取全局思维沙箱

    Args:
        max_steps: 最大步骤数
        timeout_seconds: 超时时间

    Returns:
        全局沙箱实例
    """
    global _global_sandbox
    with _sandbox_lock:
        if _global_sandbox is None:
            _global_sandbox = ThoughtSandbox(
                max_steps=max_steps,
                timeout_seconds=timeout_seconds,
            )
        return _global_sandbox


def reset_thought_sandbox():
    """重置全局沙箱（用于测试）"""
    global _global_sandbox
    with _sandbox_lock:
        if _global_sandbox:
            _global_sandbox.clear()
        _global_sandbox = None
