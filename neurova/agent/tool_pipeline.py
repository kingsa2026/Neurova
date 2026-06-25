"""
工具执行后处理管线

提供可配置的工具执行后处理Pipeline，支持：
- 可配置的处理步骤
- 并行/串行混合执行
- 详细的执行报告
- 错误分级处理

设计模式: Pipeline + Strategy
"""

from neurova.core.logger import get_logger
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = get_logger(__name__)


@dataclass
class ToolExecutionContext:
    """工具执行上下文"""
    tool_name: str
    params: Dict[str, Any]
    user_input: str
    success: bool
    tool_source: str = "skill_system"
    execution_time: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ToolExecutionReport:
    """工具执行后处理报告"""
    
    # 基本信息
    tool_name: str
    success: bool
    execution_time: float
    timestamp: float = field(default_factory=time.time)
    
    # 各步骤执行状态
    memory_recorded: bool = False
    lifecycle_updated: bool = False
    skill_observed: bool = False
    evolution_notified: bool = False
    
    # 错误信息
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # 性能指标
    total_processing_time: float = 0.0
    step_times: Dict[str, float] = field(default_factory=dict)
    
    # 附加信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_fully_successful(self) -> bool:
        """是否所有步骤都成功"""
        return (self.memory_recorded and 
                self.lifecycle_updated and 
                self.skill_observed and 
                self.evolution_notified and 
                len(self.errors) == 0)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "execution_time": self.execution_time,
            "memory_recorded": self.memory_recorded,
            "lifecycle_updated": self.lifecycle_updated,
            "skill_observed": self.skill_observed,
            "evolution_notified": self.evolution_notified,
            "errors": self.errors,
            "warnings": self.warnings,
            "total_processing_time": self.total_processing_time,
            "step_times": self.step_times,
        }


class ToolExecutionStep(ABC):
    """工具执行步骤基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """步骤名称"""
        pass
    
    @property
    def error_level(self) -> str:
        """错误级别：critical/warning/info"""
        return "warning"
    
    @abstractmethod
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        """执行步骤"""
        pass


class MemoryRecordingStep(ToolExecutionStep):
    """工具记忆记录步骤"""
    
    def __init__(self, tool_memory):
        self._tool_memory = tool_memory
    
    @property
    def name(self) -> str:
        return "memory_recording"
    
    @property
    def error_level(self) -> str:
        return "warning"  # 记录失败不影响主流程
    
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        if not self._tool_memory:
            return
        
        try:
            self._tool_memory.record_tool_usage(
                problem_text=context.user_input,
                tool_name=context.tool_name,
                tool_source=context.tool_source,
                tool_params=context.params,
                success=context.success,
                execution_time=context.execution_time,
            )
            report.memory_recorded = True
        except Exception as e:
            report.warnings.append(f"Memory recording failed: {e}")
            logger.warning("工具记忆记录失败: %s", e)


class LifecycleUpdateStep(ToolExecutionStep):
    """工具生命周期更新步骤"""
    
    def __init__(self, tool_lifecycle):
        self._tool_lifecycle = tool_lifecycle
    
    @property
    def name(self) -> str:
        return "lifecycle_update"
    
    @property
    def error_level(self) -> str:
        return "warning"
    
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        if not self._tool_lifecycle:
            return
        
        try:
            self._tool_lifecycle.touch(context.tool_name)
            report.lifecycle_updated = True
        except Exception as e:
            report.warnings.append(f"Lifecycle update failed: {e}")
            logger.warning("工具生命周期记录失败: %s", e)


class SkillObservationStep(ToolExecutionStep):
    """技能打包器观察步骤"""
    
    def __init__(self, skill_packer):
        self._skill_packer = skill_packer
    
    @property
    def name(self) -> str:
        return "skill_observation"
    
    @property
    def error_level(self) -> str:
        return "info"  # 观察失败不影响主流程
    
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        if not self._skill_packer:
            return
        
        try:
            self._skill_packer.observe(
                tool_sequence=[context.tool_name],
                context=context.user_input[:100],
                success=context.success,
            )
            report.skill_observed = True
        except Exception as e:
            report.warnings.append(f"Skill observation failed: {e}")
            logger.warning("技能打包器记录失败: %s", e)


class EvolutionFeedbackStep(ToolExecutionStep):
    """进化系统反馈步骤"""
    
    def __init__(self, evolution_orchestrator):
        self._evolution = evolution_orchestrator
    
    @property
    def name(self) -> str:
        return "evolution_feedback"
    
    @property
    def error_level(self) -> str:
        return "warning"
    
    def execute(self, context: ToolExecutionContext, report: ToolExecutionReport):
        if not self._evolution:
            return
        
        try:
            self._evolution.on_after_tool_execution(
                tool_name=context.tool_name,
                success=context.success,
                context=context.user_input[:100],
                latency=context.execution_time,
            )
            report.evolution_notified = True
        except Exception as e:
            report.warnings.append(f"Evolution feedback failed: {e}")
            logger.warning("进化系统反馈失败: %s", e)


@dataclass
class PipelineConfig:
    """Pipeline配置"""
    enable_memory_recording: bool = True
    enable_lifecycle_update: bool = True
    enable_skill_observation: bool = True
    enable_evolution_feedback: bool = True
    
    # 并行执行配置
    parallel_independent_steps: bool = True
    max_workers: int = 2
    
    # 错误处理配置
    continue_on_error: bool = True
    log_level: str = "warning"


class ToolExecutionPipeline:
    """
    工具执行后处理管线
    
    支持可配置的处理步骤，混合并行/串行执行。
    
    使用示例:
        pipeline = ToolExecutionPipeline(config)
        context = ToolExecutionContext(...)
        report = pipeline.execute(context)
        if report.is_fully_successful:
            print("所有步骤成功")
    """
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        """
        初始化Pipeline
        
        Args:
            config: Pipeline配置
        """
        self._config = config or PipelineConfig()
        self._steps: List[ToolExecutionStep] = []
    
    def add_step(self, step: ToolExecutionStep):
        """添加处理步骤"""
        self._steps.append(step)
    
    def execute(self, context: ToolExecutionContext) -> ToolExecutionReport:
        """
        执行Pipeline
        
        Args:
            context: 工具执行上下文
            
        Returns:
            ToolExecutionReport: 执行报告
        """
        start_time = time.time()
        
        report = ToolExecutionReport(
            tool_name=context.tool_name,
            success=context.success,
            execution_time=context.execution_time,
        )
        
        if not self._steps:
            logger.warning("Pipeline没有配置任何步骤")
            return report
        
        # 分离独立步骤和依赖步骤
        independent_steps = []
        dependent_steps = []
        
        for step in self._steps:
            # MemoryRecording和SkillObservation可以并行
            if step.name in ["memory_recording", "skill_observation"]:
                independent_steps.append(step)
            else:
                dependent_steps.append(step)
        
        # 并行执行独立步骤
        if self._config.parallel_independent_steps and len(independent_steps) > 1:
            with ThreadPoolExecutor(max_workers=self._config.max_workers) as executor:
                futures = {}
                for step in independent_steps:
                    step_start = time.time()
                    futures[executor.submit(step.execute, context, report)] = (step, step_start)
                
                for future in as_completed(futures):
                    step, step_start = futures[future]
                    try:
                        future.result()
                        report.step_times[step.name] = time.time() - step_start
                    except Exception as e:
                        report.step_times[step.name] = time.time() - step_start
                        if step.error_level == "critical":
                            report.errors.append(f"Critical: {step.name}: {e}")
                            logger.error("关键步骤失败: %s", e)
                        else:
                            report.warnings.append(f"{step.name}: {e}")
                            logger.warning("步骤失败: %s", e)
        else:
            # 串行执行所有步骤
            for step in independent_steps + dependent_steps:
                step_start = time.time()
                try:
                    step.execute(context, report)
                    report.step_times[step.name] = time.time() - step_start
                except Exception as e:
                    report.step_times[step.name] = time.time() - step_start
                    if step.error_level == "critical":
                        report.errors.append(f"Critical: {step.name}: {e}")
                        logger.error("关键步骤失败: %s", e)
                    else:
                        report.warnings.append(f"{step.name}: {e}")
                        logger.warning("步骤失败: %s", e)
        
        # 串行执行依赖步骤
        for step in dependent_steps:
            step_start = time.time()
            try:
                step.execute(context, report)
                report.step_times[step.name] = time.time() - step_start
            except Exception as e:
                report.step_times[step.name] = time.time() - step_start
                if step.error_level == "critical":
                    report.errors.append(f"Critical: {step.name}: {e}")
                    logger.error("关键步骤失败: %s", e)
                else:
                    report.warnings.append(f"{step.name}: {e}")
                    logger.warning("步骤失败: %s", e)
        
        report.total_processing_time = time.time() - start_time
        
        return report


def create_default_pipeline(
    tool_memory=None,
    tool_lifecycle=None,
    skill_packer=None,
    evolution=None,
    config: Optional[PipelineConfig] = None,
) -> ToolExecutionPipeline:
    """
    创建默认Pipeline
    
    Args:
        tool_memory: 工具记忆实例
        tool_lifecycle: 工具生命周期实例
        skill_packer: 技能打包器实例
        evolution: 进化系统实例
        config: Pipeline配置
        
    Returns:
        ToolExecutionPipeline: 配置好的Pipeline
    """
    pipeline = ToolExecutionPipeline(config)
    
    if tool_memory:
        pipeline.add_step(MemoryRecordingStep(tool_memory))
    
    if tool_lifecycle:
        pipeline.add_step(LifecycleUpdateStep(tool_lifecycle))
    
    if skill_packer:
        pipeline.add_step(SkillObservationStep(skill_packer))
    
    if evolution:
        pipeline.add_step(EvolutionFeedbackStep(evolution))
    
    return pipeline
