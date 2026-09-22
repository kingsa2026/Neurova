"""
PostChatPipeline — 对话后处理管线

从 agent_core.py 提取 (P1 拆分)，负责对话完成后的所有处理步骤：
- 步骤 6:  保存到 Session 文件
- 步骤 6.5: 保存对话记忆到数据库
- 步骤 7:   TTS 语音生成
- 步骤 8:   认知能力分析
- 步骤 8.5: 反思日志生成（P2 Phase 9）
- 步骤 9:   进化能力 - 经验记录
- 步骤 9.5: P0 工具生命周期评估
- 步骤 9.6: P0 PatternMiner 序列挖掘
- 步骤 9.7: P0 ToolGeneticEngine 基因进化
- 步骤 9.8: P0 ToolMarketplace 工具发布
- 步骤 9.9: P2 记忆冲突检测（Phase 10）
- 步骤 9.95: P2 记忆版本快照（Phase 10）
- 步骤 10:  P2 主动提问决策（Phase 10）

分层执行（P0 尾延迟优化）：
- **响应路径**（必须 await）：save_session / save_memory / TTS / 认知分析 /
  主动提问——它们的结果随本轮响应返回，或后续步骤依赖它们。
- **响应无关**（后台并发）：反思、经验记录、经验漏斗回写、Evocate、P0 后处理、
  冲突检测、版本快照、规则提取、动机观察、RSI 迭代——纯旁路写入，结果不进
  响应。经 _spawn_background() 起 asyncio task，任务登记在
  _background_tasks，可 drain_background() 等待。
- **并发**：互不依赖的响应路径步骤（save_session × 记忆温度衰减）走
  asyncio.gather，而非顺序 await。

设计原则：
- 依赖注入：通过 agent_ref 访问 Agent 实例
- 异步友好：核心方法为 async
- 可独立测试
- 可观测：每个步骤都出 neurova_pipeline_steps_total（计数，带 status）与
  neurova_pipeline_step_seconds（耗时直方图），整轮出
  neurova_pipeline_run_seconds——_safe_step/_safe_step_sync 是唯一埋点收口处
"""

from neurova.core.logger import get_logger
from neurova.cognitive_layers.growth_layer.analyzer import GrowthDimension
import asyncio
import collections
import contextvars
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionType
except ImportError:

    class ReflectionType(str, Enum):
        ERROR_ANALYSIS = "error_analysis"
        PROBLEM_SOLVING = "problem_solving"
        DECISION_MAKING = "decision_making"
        INTERACTION = "interaction"
        LEARNING = "learning"


logger = get_logger(__name__)

# RSI 降频巡检窗口（工单 008）：收敛或度量失明时，每 N 轮仍跑一次。
# 取 20 与收敛窗口（convergence_analyzer.window_size 默认 20）同量级 ——
# 一个窗口的证据过期之后就重新量一次，而不是永久停机。
_RSI_BACKOFF_EVERY_TURNS = 20


def _landedEvidenceRows(stepResults: List[Any], memoryManager: Any) -> List[Dict[str, Any]]:
    """本轮 `save_memory` 真实落地的证据行（从步骤读数取 id，再回库定位）。

    身份的唯一来源是**落库结果**，不是检测步骤自己编的 id：`save_memory` 步骤读数里的
    `user_memory_id` / `agent_memory_id` 是权威写入链的返回值，照读即可；回库再查一次
    拿内容（`get_memory` 读不到的行按"未落地"处理）。账上成员必须是能定位的行——
    说不清是谁的账无法被处置，只能停在纯观测（Issue #72 正文最后一条断链）。
    """
    ids: List[str] = []
    for result in stepResults or []:
        if getattr(result, "step_name", "") != "save_memory":
            continue
        data = getattr(result, "data", None) or {}
        for key in ("user_memory_id", "agent_memory_id"):
            memoryId = str(data.get(key) or "")
            if memoryId and memoryId not in ids:
                ids.append(memoryId)
    rows: List[Dict[str, Any]] = []
    for memoryId in ids:
        row = memoryManager.get_memory(memoryId, agent_wide=True)
        if isinstance(row, dict) and row.get("content"):
            rows.append(row)
    return rows


def _detectAgainstEvidenceRows(
    detector: Any, evidenceRows: List[Dict[str, Any]], earlierMemories: List[Any]
) -> List[Dict[str, Any]]:
    """逐条拿本轮证据行与已有记忆比对，返回带**可定位成员 id** 的信号。

    对比单位是"一句证据"，不是把整轮对话揉成一个字符串：合成文本经子句切分后与
    子句并看不出差别，但它**没有对应的行**——报出来的冲突指不出成员是谁。
    """
    from neurova.cognitive_layers.memory_layer.models import Memory

    found: List[Dict[str, Any]] = []
    for row in evidenceRows:
        newMemory = Memory(id=str(row["id"]), content=str(row["content"]))
        found.extend(detector.detect_conflict(
            newMemory, [m for m in earlierMemories if m.id != newMemory.id]
        ))
    return found


def _conflictsWithLocatableMembers(
    conflicts: List[Dict[str, Any]], locatable: Any
) -> List[Dict[str, Any]]:
    """只保留两个成员都能在库里定位的信号：说不清是谁的账无法被处置。"""
    kept: List[Dict[str, Any]] = []
    for conflict in conflicts or []:
        left = str(conflict.get("memory1_id") or "")
        right = str(conflict.get("memory2_id") or "")
        if left and right and left in locatable and right in locatable:
            kept.append(conflict)
    return kept


class StepStatus(str, Enum):
    """步骤执行状态"""

    PENDING = "pending"
    EXECUTED = "executed"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass
class StepResult:
    """步骤执行结果"""

    step_name: str
    status: StepStatus
    message: str = ""
    duration_ms: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)


def _elapsed_ms(started: float) -> float:
    """从 perf_counter 起点算毫秒（与步骤内 time.time() 口径一致）。"""
    return (time.perf_counter() - started) * 1000.0


def _pipeline_metrics():
    """管线埋点入口（惰性导入：prometheus_client 缺席时不拖垮整轮对话）。"""
    try:
        from neurova.core.metrics import get_metrics

        return get_metrics()
    except Exception:  # noqa: BLE001 - 观测面故障绝不影响业务
        return None


def _record_step_metric(step_name: str, status: str, duration_ms: float) -> None:
    """单步埋点（失败静默：观测是旁路，不能成为新的故障点）。"""
    metrics = _pipeline_metrics()
    if metrics is None:
        return
    try:
        metrics.record_pipeline_step(step_name, status, duration_ms)
    except Exception:  # noqa: BLE001
        logger.debug("pipeline step metric 记录失败: %s", step_name, exc_info=True)


def _record_run_metric(mode: str, duration_s: float) -> None:
    """整轮埋点（mode=blocking/background）。"""
    metrics = _pipeline_metrics()
    if metrics is None:
        return
    try:
        metrics.record_pipeline_run(mode, duration_s)
    except Exception:  # noqa: BLE001
        logger.debug("pipeline run metric 记录失败", exc_info=True)


def _consolidation_plan_store(skills_dir):
    """合并计划落盘仓（同一 agent 目录）。计划是**待审批件**，非技能库改动。"""
    from neurova.evolution.skill_consolidator import ConsolidationPlanStore

    return ConsolidationPlanStore(skills_dir)


async def run_skill_evolution_pass(
    *,
    improver,
    growth_log_manager,
    skill_registry,
    skill_service,
    skill_text_loader,
    reflection_type,
):
    """技能进化一轮：提案（含反射式文本改进）→ 应用回写 → 反思日志沉淀。

    从 _step_rsi_iteration 抽出（P1-4 队列化改造）：队列关闭时 post_chat 直调，
    队列开启时作为作业 handler 的 body——两条路径共用同一实现，无第二套。
    返回已处理提案数。
    """
    proposals = await improver.propose_pending_improvements_async(skill_text_loader)
    handled = 0
    for proposal in proposals[:3]:
        applied = False
        if skill_registry is not None:
            applied = improver.apply_improvement(
                proposal, skill_registry, skill_service=skill_service
            )
        if applied:
            logger.info("🔧 技能改进已应用: %s (%s)", proposal.skill_id, proposal.description or "")
            handled += 1
            continue
        logger.info("🔧 技能改进提案: %s - %s", proposal.skill_id, (proposal.description or "")[:50])
        if growth_log_manager:
            try:
                await growth_log_manager.generate_log(
                    type=reflection_type.IMPROVEMENT,
                    title=f"技能改进提案: {proposal.skill_id}",
                    content=proposal.description or proposal.reason,
                    insights=[proposal.reason] if proposal.reason else [],
                    confidence=min(1.0, max(0.0, float(proposal.expected_impact or 0.5))),
                )
            except Exception as pe:
                logger.debug("改进提案写入反思日志失败: %s", pe)
    return handled


class PostChatPipeline:
    """对话后处理管线

    通过 agent_ref 访问 Agent 实例的所有属性。
    支持依赖注入和步骤状态跟踪。
    """

    # Bug #6 fix: 使用 contextvar 隔离并发 process() 调用的 _step_results
    # 每个 async task 拥有独立的 context，避免并发请求互相覆盖步骤结果
    _step_results_ctx: contextvars.ContextVar = contextvars.ContextVar(
        "post_chat_step_results"
    )

    def __init__(self, agent_ref):
        self._agent = agent_ref
        # Bug #6 fix: _step_results_store 作为 fallback，供非 process() 场景下直接访问
        # （如 _safe_step 单元测试）。process() 调用时通过 contextvar 隔离。
        self._step_results_store: List[StepResult] = []
        self._dependencies: Dict[str, Any] = {}

        # 显式声明所有依赖组件
        self._conversation_buffer = None
        self._memory_manager = None
        self._tts_manager = None
        self._growth_analyzer = None
        self._growth_log_manager = None
        self._evolution = None
        self._neuHebb_manager = None
        self._tool_lifecycle = None
        self._pattern_miner = None
        self._genetic_engine = None
        self._tool_marketplace = None
        self._conflict_detector = None
        self._version_control = None
        self._proactive_question_manager = None
        self._rsi_orchestrator = None
        self._voice_memory_bridge = None
        self._skill_packer = None
        self._neurflow_executor = None
        self._voice_pipeline = None

        # 后台步骤任务表（响应无关步骤）。见 _bg_tasks / _bg_errors：
        # 惰性创建，兼容 PostChatPipeline.__new__ 构造（测试用）。
        self._background_tasks: Optional[set] = None
        self._background_errors = None

    @property
    def _agt(self):
        return self._agent

    # ── 后台步骤状态（惰性创建，兼容 __new__ 构造）──
    # 强引用 + done 回调摘除：既避免"asyncio 任务被 GC 回收"，也避免无界
    # 增长（完成即摘，无需上限）。实例级而非每轮重置——同一 pipeline 并发
    # 服务多轮时（Agent 单例语义），重置会把仍在跑的任务从表里摘掉，
    # drain_background 就漏等它们。
    @property
    def _bg_tasks(self) -> set:
        if self._background_tasks is None:
            self._background_tasks = set()
        return self._background_tasks

    # 后台任务的非取消异常（观测用；不向调用方抛——后台本就旁路）；
    # 有界（只留最近若干条），避免长期运行无界增长
    @property
    def _bg_errors(self) -> "collections.deque":
        if self._background_errors is None:
            self._background_errors = collections.deque(maxlen=100)
        return self._background_errors

    @property
    def _step_results(self) -> List[StepResult]:
        """Bug #6 fix: 从 contextvar 读取当前调用的步骤结果列表

        - process() 调用时：通过 contextvar 隔离，每个并发调用拥有独立列表
        - 非 process() 场景（如 _safe_step 单元测试）：回退到 _step_results_store
        """
        try:
            return self._step_results_ctx.get()
        except LookupError:
            return self._step_results_store

    @_step_results.setter
    def _step_results(self, value: List[StepResult]) -> None:
        """Bug #6 fix: 设置 contextvar，隔离并发调用的步骤结果"""
        self._step_results_ctx.set(value)

    def configure(
        self,
        conversation_buffer: Any = None,
        memory_manager: Any = None,
        tts_manager: Any = None,
        growth_analyzer: Any = None,
        growth_log_manager: Any = None,
        evolution: Any = None,
        neuHebb_manager: Any = None,
        tool_lifecycle: Any = None,
        pattern_miner: Any = None,
        genetic_engine: Any = None,
        tool_marketplace: Any = None,
        conflict_detector: Any = None,
        version_control: Any = None,
        proactive_question_manager: Any = None,
        rsi_orchestrator: Any = None,
        voice_memory_bridge: Any = None,
        skill_packer: Any = None,
        voice_pipeline: Any = None,
        neurflow_executor: Any = None,
    ) -> None:
        """注入依赖组件（延迟绑定）

        Args:
            conversation_buffer: 对话缓冲区实例
            memory_manager: 记忆管理器实例
            tts_manager: TTS管理器实例
            growth_analyzer: 成长分析器实例
            growth_log_manager: 成长日志管理器实例
            evolution: 进化引擎实例
            neuHebb_manager: NeuHebb管理器实例
            tool_lifecycle: 工具生命周期实例
            pattern_miner: 模式挖掘器实例
            genetic_engine: 遗传引擎实例
            tool_marketplace: 工具市场实例
            conflict_detector: 冲突检测器实例
            version_control: 版本控制实例
            proactive_question_manager: 主动提问管理器实例
            rsi_orchestrator: RSI编排器实例
            voice_memory_bridge: 语音记忆桥接器实例
            skill_packer: 技能打包器实例
        """
        if conversation_buffer is not None:
            self._conversation_buffer = conversation_buffer
        if memory_manager is not None:
            self._memory_manager = memory_manager
        if tts_manager is not None:
            self._tts_manager = tts_manager
        if growth_analyzer is not None:
            self._growth_analyzer = growth_analyzer
        if growth_log_manager is not None:
            self._growth_log_manager = growth_log_manager
        if evolution is not None:
            self._evolution = evolution
        if neuHebb_manager is not None:
            self._neuHebb_manager = neuHebb_manager
        if tool_lifecycle is not None:
            self._tool_lifecycle = tool_lifecycle
        if pattern_miner is not None:
            self._pattern_miner = pattern_miner
        if genetic_engine is not None:
            self._genetic_engine = genetic_engine
        if tool_marketplace is not None:
            self._tool_marketplace = tool_marketplace
        if conflict_detector is not None:
            self._conflict_detector = conflict_detector
        if version_control is not None:
            self._version_control = version_control
        if proactive_question_manager is not None:
            self._proactive_question_manager = proactive_question_manager
        if rsi_orchestrator is not None:
            self._rsi_orchestrator = rsi_orchestrator
        if voice_memory_bridge is not None:
            self._voice_memory_bridge = voice_memory_bridge
        if skill_packer is not None:
            self._skill_packer = skill_packer
        if voice_pipeline is not None:
            self._voice_pipeline = voice_pipeline
        if neurflow_executor is not None:
            self._neurflow_executor = neurflow_executor

        logger.info(
            "PostChatPipeline dependencies configured: "
            "conversation_buffer=%s, memory_manager=%s, tts_manager=%s, "
            "growth_analyzer=%s, growth_log_manager=%s, evolution=%s, "
            "neuHebb_manager=%s, tool_lifecycle=%s, pattern_miner=%s, "
            "genetic_engine=%s, tool_marketplace=%s, conflict_detector=%s, "
            "version_control=%s, proactive_question_manager=%s, rsi_orchestrator=%s, "
            "voice_pipeline=%s, neurflow_executor=%s",
            self._conversation_buffer is not None,
            self._memory_manager is not None,
            self._tts_manager is not None,
            self._growth_analyzer is not None,
            self._growth_log_manager is not None,
            self._evolution is not None,
            self._neuHebb_manager is not None,
            self._tool_lifecycle is not None,
            self._pattern_miner is not None,
            self._genetic_engine is not None,
            self._tool_marketplace is not None,
            self._conflict_detector is not None,
            self._version_control is not None,
            self._proactive_question_manager is not None,
            self._rsi_orchestrator is not None,
            self._voice_pipeline is not None,
            self._neurflow_executor is not None,
        )

    def _get_dependency(self, name: str) -> Any:
        """获取依赖组件，优先使用配置的依赖，降级到agent_ref"""
        # 检查配置的依赖
        if hasattr(self, f"_{name}"):
            dep = getattr(self, f"_{name}")
            if dep is not None:
                return dep

        # 降级到agent_ref
        return getattr(self._agent, name, None)

    # P0-C2 修复：编程错误不应被 _safe_step 吞没。
    # 原代码用 `except Exception` 捕获所有异常（含 TypeError/AttributeError/
    # NameError/ImportError/SyntaxError），导致真实 bug 被降级为 default 值，
    # pipeline 继续运行，bug 永不暴露。违反 bug-hunt 规则 #3 "Never bypass"。
    # 现将这些"编程错误"类型显式 re-raise，让调用方看到真实 bug；运营错误
    # （OSError/ValueError/RuntimeError/ConnectionError/TimeoutError 等）维持降级。
    # A-14 修复：ImportError 移出本集合——可选依赖缺失（ModuleNotFoundError ⊂
    # ImportError）会炸穿整轮 chat()，而导入错误极少是可恢复的编程错误信号，
    # 且这些步骤本就要求失败不影响整轮。ImportError 走专用分支：warning +
    # 步骤失败 + 跳过（见 _safe_step/_safe_step_sync）。
    _PROGRAMMING_ERRORS = (
        TypeError,
        AttributeError,
        NameError,
        SyntaxError,
        IndentationError,
    )

    async def _safe_step(self, step_name: str, coro, default=None):
        """P-1: 安全执行单个步骤,异常只记录不传播

        P0-C2 修复：编程错误（TypeError/AttributeError/NameError/SyntaxError）
        会 re-raise，让真实 bug 暴露给调用方；ImportError 按 A-14 降级为
        步骤失败+warning；运营错误（OSError/ValueError/
        RuntimeError 等）仍按原逻辑降级为 default 值。

        可观测性（P0）：本方法是异步步骤的唯一收口处，耗时在此测量并写入
        步骤结果（duration_ms）+ prometheus（计数×status、耗时直方图）。
        步骤内部自带 duration_ms 的记录（同步步骤）保持不变，不重复覆盖。
        """
        _started = time.perf_counter()
        try:
            result = await coro
            # 步骤内已记录结果（多数步骤自己 append）时只补埋点，不重复 append
            self._record_step_metric_if_unlogged(step_name, StepStatus.EXECUTED, _started)
            return result
        except ImportError as e:
            # A-14: 导入错误（含可选依赖缺失 ModuleNotFoundError）按步骤失败
            # 降级跳过，不 re-raise——炸穿整轮 chat() 的代价比漏一步高
            logger.warning(
                "Step '%s' failed with ImportError (skipping step): %s",
                step_name,
                e,
                exc_info=True,
            )
            self._append_failed_step(step_name, e, _started)
            _record_step_metric(step_name, StepStatus.FAILED.value, _elapsed_ms(_started))
            return default
        except self._PROGRAMMING_ERRORS:
            # P0-C2: 编程错误必须 re-raise，不能被吞没
            logger.error(
                "Step '%s' raised a programming error (re-raising, not degrading)",
                step_name,
                exc_info=True,
            )
            # 观测面要看得见"炸穿"，否则编程错误在指标里凭空消失
            _record_step_metric(step_name, "error_raised", _elapsed_ms(_started))
            raise
        except Exception as e:
            logger.error("Step '%s' failed: %s", step_name, e, exc_info=True)
            self._append_failed_step(step_name, e, _started)
            _record_step_metric(step_name, StepStatus.FAILED.value, _elapsed_ms(_started))
            return default

    def _append_failed_step(self, step_name: str, exc: BaseException, started: float) -> None:
        """记失败步骤（带真实耗时）。

        步骤名重复时也照记：失败次数本身是信号（同一轮同一名字多次失败
        不应被折叠成一条）。
        """
        self._step_results.append(
            StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(exc),
                duration_ms=_elapsed_ms(started),
            )
        )

    def _record_step_metric_if_unlogged(self, step_name: str, status: StepStatus, started: float) -> None:
        """步骤成功：把耗时补进步骤结果（该步未自行记录时 append 一条），并埋点。

        同步步骤 / 自带 start_time 的步骤已 append 过自己的 StepResult
        （含 duration_ms），此处只补 metrics，避免结果列表出现重复项。
        """
        elapsed = _elapsed_ms(started)
        if not any(r.step_name == step_name for r in self._step_results):
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=status,
                    message="completed",
                    duration_ms=elapsed,
                )
            )
        _record_step_metric(step_name, status.value, elapsed)

    def _safe_step_sync(self, step_name: str, func, default=None):
        """P-1: 安全执行同步步骤,异常只记录不传播

        P0-C2 修复：编程错误（TypeError/AttributeError/NameError/SyntaxError）
        会 re-raise，让真实 bug 暴露给调用方；ImportError 按 A-14 降级为
        步骤失败+warning；运营错误仍按原逻辑降级为 default 值。

        可观测性（P0）：同 _safe_step——同步步骤（含 asyncio.to_thread 派发
        的 update_memory_temperature）在此收口埋点。
        """
        _started = time.perf_counter()
        try:
            result = func()
            self._record_step_metric_if_unlogged(step_name, StepStatus.EXECUTED, _started)
            return result
        except ImportError as e:
            # A-14: 同 _safe_step——导入错误降级为步骤失败，不 re-raise
            logger.warning(
                "Step '%s' failed with ImportError (skipping step): %s",
                step_name,
                e,
                exc_info=True,
            )
            self._append_failed_step(step_name, e, _started)
            _record_step_metric(step_name, StepStatus.FAILED.value, _elapsed_ms(_started))
            return default
        except self._PROGRAMMING_ERRORS:
            # P0-C2: 编程错误必须 re-raise，不能被吞没
            logger.error(
                "Step '%s' raised a programming error (re-raising, not degrading)",
                step_name,
                exc_info=True,
            )
            _record_step_metric(step_name, "error_raised", _elapsed_ms(_started))
            raise
        except Exception as e:
            logger.error("Step '%s' failed: %s", step_name, e, exc_info=True)
            self._append_failed_step(step_name, e, _started)
            _record_step_metric(step_name, StepStatus.FAILED.value, _elapsed_ms(_started))
            return default

    # ── 后台任务（响应无关步骤）──
    # 默认开启：与响应无关的旁路写入（反思/经验/冲突/快照/规则/动机/RSI）
    # 不再占响应路径。NEUROVA_POSTCHAT_BACKGROUND=0 回退旧行为（全串行 await），
    # 用于排查/兼容；每次调用读环境变量，便于灰度与测试。
    _BACKGROUND_ENV = "NEUROVA_POSTCHAT_BACKGROUND"

    @staticmethod
    def background_enabled() -> bool:
        """后台化开关（默认开；显式 0/false/no/off 关）。"""
        raw = os.environ.get(PostChatPipeline._BACKGROUND_ENV, "1")
        return raw.strip().lower() not in ("0", "false", "no", "off")

    def _spawn_background(self, step_name: str, coro, after=None):
        """把响应无关步骤派发为后台任务（返回 asyncio.Task）。

        - 强引用保存在 self._background_tasks，完成后经
          _background_task_done 摘除——避免"任务被 GC 回收"与无界增长两个极端。
        - 单个后台步骤的异常语义与前台一致：走 _safe_step（编程错误仍
          re-raise，落到任务回调里由 _background_task_done 记日志 + 埋点，
          不静默丢失）。
        - after：可选"前驱任务"。后台步骤之间的真实依赖（9.95 快照 → 9.96
          规则提取）用它表达：各自仍是独立任务、各自经 _safe_step 收口，但
          执行顺序被钉住。用 asyncio.wait 等前驱结束——前驱失败/取消不阻断
          后继（旧实现里两步都各自失败降级，互不牵连）。
        - 整段耗时写 neurova_pipeline_run_seconds{mode="background"}，
          用于验证后台化收益。
        """
        _started = time.perf_counter()

        async def _runner():
            try:
                if after is not None:
                    await asyncio.wait([after])
                await self._safe_step(step_name, coro)
            finally:
                _record_run_metric("background", time.perf_counter() - _started)

        task = asyncio.create_task(_runner(), name=f"postchat:{step_name}")
        self._bg_tasks.add(task)
        task.add_done_callback(self._background_task_done)
        return task

    def _background_task_done(self, task: "asyncio.Task") -> None:
        """后台任务收尾：摘引用 + 记录非取消异常（不许静默丢失）。"""
        self._bg_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        self._bg_errors.append(exc)
        logger.error(
            "PostChatPipeline 后台步骤异常（不影响本轮响应）: %s",
            exc,
            exc_info=exc,
        )

    def _background_failures(self) -> list:
        """后台任务的非取消异常（测试/运维可读；不阻塞调用方）。"""
        return [e for e in self._bg_errors]

    async def drain_background(self, timeout: Optional[float] = None) -> int:
        """等待后台步骤收尾，返回已完成任务数。

        服务优雅关闭、测试断言、以及"需要本轮全部旁路写入落定"的调用方使用。
        timeout=None 表示等到全部完成。超时后剩余任务继续运行（不取消）。

        循环取快照：后台任务仍可能派发后继任务（当前实现是派发时一次性
        建好，循环只为防未来改动漏等）。
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        completed = 0
        while True:
            tasks = [t for t in list(self._bg_tasks) if not t.done()]
            if not tasks:
                return completed
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining == 0.0:
                return completed
            done, _pending = await asyncio.wait(tasks, timeout=remaining)
            completed += len(done)
            if not done and deadline is not None:
                # 超时且本轮无进展：不再空转（剩余任务继续跑，不取消）
                return completed

    async def process(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool,
        enable_tts: bool,
        metadata: Dict[str, Any],
        writer_claim=None,
    ) -> Dict[str, Any]:
        """
        执行对话后所有处理步骤，返回:
        {
            "actual_session_id": str,
            "audio_path": Optional[str],
            "audio_data": Optional[bytes],
            "cognitive_score": Optional[float],
            "proactive_question": Optional[str],
            "rsi_result": Optional[Dict],   # 后台化后恒为 None（原始迭代快照不进响应）
            "rsi": Optional[Dict],          # RSI 摘要（最近一次已完成迭代；见下）
            "duration_ms": float,           # 响应路径耗时（可观测）
        }

        关于 "rsi"：RSI 步骤已后台化，本轮结果赶不上响应组装，故这里给的是
        **该会话最近一次已完成**的迭代摘要——字段
        ``{status, applied_count, gain, phase_advanced, turn, stale}``
        （前四个对齐 RSIOrchestrator.run_iteration 的真实输出，由
        neurova.evolution.rsi.result_summary 统一裁剪，不再各自猜字段名）。
        从未跑过 RSI 时为 None。stale=True 表示摘要不是本轮的（后台仍在跑
        或本轮被 should_continue() 跳过）——宁可标注来源，也不虚报成本轮产物。

        执行分两层（P0 尾延迟优化）：
        - 响应路径（await）：save_session / 记忆温度衰减 / 认知分析 / 主动提问
          → save_memory / TTS。互不依赖的并发跑（gather），有依赖的串链
          （save_memory、TTS 依赖 save_session 产出的 session_id）。
        - 后台路径（asyncio.create_task）：反思、经验记录、工作流经验、技能
          漏斗回写、Evocate、P0 后处理、冲突检测、版本快照、规则提取、动机
          观察、RSI 迭代。它们只写旁路数据，结果不进响应。需等待时调
          drain_background()。
        """
        # Bug #6 fix: 每次调用创建新的步骤结果列表，通过 contextvar 隔离并发调用
        # 原 self._step_results.clear() 会修改共享列表，并发请求互相覆盖
        self._step_results = []
        _run_started = time.perf_counter()

        # ── 响应路径 · 第一波（互不依赖，并发）──────────────────────────
        # 1) save_session：产出 actual_session_id，后续两步依赖它
        # 2) 记忆温度衰减：同步阻塞重活（全量遍历 + SQLite），to_thread 移出事件循环
        # 3) 认知分析：纯计算 + 成长记录，独立于 session
        # 4) 主动提问决策：结果随响应返回，独立于 session
        actual_session_id, _temp_result, cognitive_score, proactive_question = await asyncio.gather(
            self._safe_step(
                "save_session",
                self._step_save_session(
                    user_input, reply, session_id, save_memory, metadata, writer_claim
                ),
                default=session_id,
            ),
            asyncio.to_thread(
                self._safe_step_sync,
                "update_memory_temperature",
                self._step_update_memory_temperature,
            ),
            self._safe_step(
                "cognitive_analysis", self._step_cognitive_analysis(user_input), default=0.0
            ),
            self._safe_step(
                "proactive_question",
                self._step_proactive_question(user_input, reply),
                default=None,
            ),
        )

        # ── 响应路径 · 第二波（依赖 session_id，彼此独立，并发）────────
        _memory_result, tts_result = await asyncio.gather(
            self._safe_step(
                "save_memory",
                self._step_save_memory(user_input, reply, actual_session_id, save_memory, metadata),
            ),
            self._safe_step(
                "generate_tts",
                self._step_generate_tts(reply, actual_session_id, enable_tts),
                default=(None, None),
            ),
        )
        audio_path, audio_data = tts_result if tts_result else (None, None)

        # ── 后台路径（响应无关的旁路写入）──────────────────────────────
        # save_memory 之后派发：冲突检测/版本快照按"新记忆已入库"召回相关记忆。

        # 每项 = (步骤名, 协程工厂, 前驱步骤名 or None)
        _background_steps = [
            ("reflection", lambda: self._step_reflection(user_input, reply), None),
            (
                "record_experience",
                lambda: self._step_record_experience(user_input, reply, save_memory),
                None,
            ),
            (
                "record_workflow_experience",
                lambda: self._step_record_workflow_experience(user_input, reply, actual_session_id),
                None,
            ),
            # 技能质量漏斗回写 + 信任观测（每回合一个独立 task 观测）
            (
                "skill_funnel_flush",
                lambda: self._step_skill_funnel_flush(reply, actual_session_id),
                None,
            ),
            (
                "evocate_generation",
                lambda: self._step_evocate_generation(user_input, reply, actual_session_id),
                None,
            ),
            # P0 后处理组（lifecycle → pattern_mining → genetic → marketplace，
            # 组内有序，故整组一个任务）
            ("p0_post_processing", lambda: self._step_p0_post_processing(save_memory), None),
            (
                "conflict_detection",
                lambda: self._step_conflict_detection(user_input, reply),
                None,
            ),
            # 9.95 → 9.96 有依赖（快照先落，规则提取再消费相关记忆）：
            # 两个独立任务，靠 after 钉住顺序。
            ("version_snapshot", lambda: self._step_version_snapshot(user_input), None),
            (
                "extract_conversation_rules",
                lambda: self._step_extract_conversation_rules(
                    user_input, reply, actual_session_id
                ),
                "version_snapshot",
            ),
            (
                "motivation_observations",
                lambda: self._step_motivation_observations(
                    user_input, reply, cognitive_score, proactive_question
                ),
                None,
            ),
            # RSI 迭代：内含技能进化/市场发布/LLM 裁决，最重的一步
            ("rsi_iteration", lambda: self._step_rsi_iteration(), None),
        ]

        if self.background_enabled():
            _spawned: Dict[str, Any] = {}
            for _name, _factory, _after_name in _background_steps:
                _spawned[_name] = self._spawn_background(
                    _name,
                    _factory(),
                    after=_spawned.get(_after_name) if _after_name else None,
                )
        else:
            # 兼容通道：环境变量显式关闭后台化时维持旧语义（全串行 await）
            for _name, _factory, _after_name in _background_steps:
                await self._safe_step(_name, _factory())

        # ── 观测收口 ──────────────────────────────────────────────────
        duration_s = time.perf_counter() - _run_started
        _record_run_metric("blocking", duration_s)

        executed = sum(1 for r in self._step_results if r.status == StepStatus.EXECUTED)
        skipped = sum(1 for r in self._step_results if r.status == StepStatus.SKIPPED)
        failed = sum(1 for r in self._step_results if r.status == StepStatus.FAILED)
        degraded = sum(1 for r in self._step_results if r.status == StepStatus.DEGRADED)

        logger.info(
            "PostChatPipeline completed: executed=%d, skipped=%d, failed=%d, degraded=%d, "
            "durations=%s",
            executed,
            skipped,
            failed,
            degraded,
            self._format_slowest_steps(),
        )
        logger.debug(
            "PostChatPipeline 响应路径耗时 %.1fms，后台任务 %d 个（background=%s）",
            duration_s * 1000.0,
            len(self._bg_tasks),
            self.background_enabled(),
        )

        # rsi_result 恒为 None：RSI 已后台化，原始迭代快照不进响应（旧字段保留兼容）；
        # 观测面走 "rsi" 摘要（字段名对齐 run_iteration，取最近一次已完成迭代）。
        return {
            "actual_session_id": actual_session_id,
            "audio_path": audio_path,
            "audio_data": audio_data,
            "cognitive_score": cognitive_score,
            "proactive_question": proactive_question,
            "rsi_result": None,
            "rsi": self._latest_rsi_summary(),
            "duration_ms": duration_s * 1000.0,
        }

    def _latest_rsi_summary(self) -> Optional[Dict[str, Any]]:
        """最近一次已完成 RSI 迭代的摘要（无法取到时返回 None，绝不阻断响应）。"""
        try:
            from neurova.core.turn_context import get_turn_count, get_turn_session_id
            from neurova.evolution.rsi.result_summary import get_latest_rsi_summary

            agent_id = getattr(getattr(self._agent, "config", None), "agent_id", None)
            session_id = get_turn_session_id() or getattr(self._agent, "session_id", None)
            return get_latest_rsi_summary(agent_id, session_id, current_turn=get_turn_count())
        except Exception as e:  # noqa: BLE001 - 观测字段不得拖垮响应
            logger.debug("RSI 摘要读取跳过: %s", e)
            return None

    def _format_slowest_steps(self, top: int = 5) -> str:
        """最慢的 top-N 步骤（"step=ms"），供日志快速定位尾延迟来源。"""
        timed = [
            (r.step_name, float(r.duration_ms or 0.0))
            for r in self._step_results
            if r.duration_ms
        ]
        timed.sort(key=lambda item: item[1], reverse=True)
        return ", ".join(f"{name}={ms:.1f}ms" for name, ms in timed[:top]) or "n/a"

    def _step_update_memory_temperature(self):
        """更新记忆温度（批量衰减）"""
        step_name = "update_memory_temperature"
        start_time = time.time()

        try:
            # 调用 Agent 的 _update_memory_temperature 方法
            if hasattr(self._agt, "_update_memory_temperature"):
                self._agt._update_memory_temperature()
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message="Memory temperature updated",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="Agent has no _update_memory_temperature method",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
        except Exception as e:
            logger.warning("记忆温度更新失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_save_session(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool,
        metadata: Dict[str, Any],
        writer_claim=None,
    ) -> str:
        """保存到 session 文件（备份机制）

        P1-10: writer_claim 随行透传给 _save_to_session，围栏失效时跳过落盘。
        """
        step_name = "save_session"
        start_time = time.time()
        # Bug #4 fix: 保留原始 session_id（包括 None），不通过 or "" 转为空字符串
        result_session_id = session_id

        if not save_memory:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="save_memory=False, skip session backup",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return result_session_id

        try:
            _tool_msgs = self._agt._collect_tool_messages()
            assistant_meta = {
                "reasoning_content": getattr(self._agt, "current_reasoning", None),
                "tool_calls": _tool_msgs or None,
            }
            # 产物卡片持久化（2026-09-08）：SSE artifact 事件只活在实时流，
            # 刷新/重开会话后卡片消失。此处把本轮 tool_result 提取的产物
            # 随 assistant_metadata.artifacts 落盘（注册幂等，与 SSE 出口
            # extract_tool_artifacts 同一判读：读形态不算产出）。注册失败
            # （路径越界/文件缺失）仅跳过该产物，不阻断会话保存。
            _artifacts = self._collect_round_artifacts(_tool_msgs)
            if _artifacts:
                assistant_meta["artifacts"] = _artifacts
            # P0a 注入留痕（效力闭环）：本轮进了 prompt 的反思日志 id 随消息
            # 落盘，/chat/feedback 赞踩据此裁决反思效力（session 跨重启可回溯）。
            from neurova.core.turn_context import get_turn_injected_reflections

            _injected = get_turn_injected_reflections()
            if _injected:
                assistant_meta["injected_reflections"] = list(_injected)
            # 过滤 None 值
            assistant_meta = {k: v for k, v in assistant_meta.items() if v is not None}

            result_session_id = self._agt._save_to_session(
                user_input,
                reply,
                session_id,
                metadata,
                assistant_meta if assistant_meta else None,
                writer_claim=writer_claim,
            )
            if not result_session_id:
                # P1-10 复审修正: 围栏拒绝（陈旧 writer）返回 ""——不能把 "" 当
                # actual_session_id 下传（Bug#4 修复会把它当回退值写脏记忆归属），
                # 回退原始 session_id 并把该步标 SKIPPED 以示未落盘
                logger.info("session 落盘被写入围栏拒绝（陈旧 writer），回退原 session_id")
                result_session_id = session_id
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="session save fenced out (stale writer claim)",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"session_id": result_session_id},
                    )
                )
                return result_session_id
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Session saved: {result_session_id}",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"session_id": result_session_id},
                )
            )
        except Exception as e:
            # Bug #1 fix: 编程错误（TypeError/AttributeError/NameError 等）必须 re-raise
            # 不能被降级为 FAILED 静默返回，否则 P0-C2 的 re-raise 机制失效
            if isinstance(e, self._PROGRAMMING_ERRORS):
                raise
            logger.warning("Session备份失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

        return result_session_id

    def _collect_round_artifacts(self, tool_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从本轮 tool_result 列表提取产物（落盘到 assistant_metadata.artifacts）。

        与 SSE 出口共用 extract_tool_artifacts（读形态判读+注册+事件形态），
        输出即 artifact SSE 事件形态（artifact_id/kind/name/size/path），
        前端历史回放按 artifactFromEvent 同构恢复。失败逐项跳过（artifact
        是增强能力，不阻断会话保存）。
        """
        events: List[Dict[str, Any]] = []
        try:
            from neurova.api.endpoints.artifacts_api import extract_tool_artifacts

            # A-03: Agent 无 agent_id 实例属性（在 config.agent_id，与
            # :1463/:1588/:1973 兄弟调用点一致）——原写法恒为空串
            agent_id = str(getattr(self._agt.config, "agent_id", "") or "")
            # B-5 契约注释：身份读取序与 tool_executor._agent_identity 一致——
            # 先读 _current_user_id（请求级显式身份），再回退 public 别名，
            # 防真值影子（如 MagicMock auto-attr）遮蔽显式身份
            user_id = str(
                getattr(self._agt, "_current_user_id", None)
                or getattr(self._agt, "current_user_id", None)
                or ""
            )
            for tm in tool_msgs or []:
                if not isinstance(tm, dict) or tm.get("type") != "tool_result":
                    continue
                result_text = tm.get("result")
                if not isinstance(result_text, str) or not result_text:
                    continue
                try:
                    events.extend(
                        extract_tool_artifacts(
                            str(tm.get("tool_name", "")),
                            result_text,
                            agent_id=agent_id,
                            user_id=user_id,
                        )
                    )
                except Exception as e:  # noqa: BLE001 - 单条产物失败不影响其余
                    logger.debug("产物提取跳过: %s", e)
        except Exception as e:  # noqa: BLE001 - 整体降级：产物缺失不影响会话
            logger.debug("产物收集降级: %s", e)
        return events

    async def _step_save_memory(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """保存对话记忆到记忆数据库"""
        step_name = "save_memory"
        start_time = time.time()

        # Bug 修复: save_memory=False 时跳过整个步骤 (与 _step_save_session:451 对齐)
        # 原代码无条件调用 _step_save_memory, 导致 save_memory=False 仍写入记忆
        if not save_memory:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="save_memory=False, 跳过记忆保存",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        # 获取依赖组件
        memory_manager = self._get_dependency("memory_manager")
        conversation_buffer = self._get_dependency("conversation_buffer")

        if not conversation_buffer and not memory_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="No memory_manager or conversation_buffer available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            # P-7: 初始化变量,避免仅 conversation_buffer 时 NameError
            user_memory_id = None
            agent_memory_id = None

            # 使用对话缓冲区
            if conversation_buffer:
                # Bug 修复: ConversationBuffer.add_user_message(self, message: str) 不接受
                # session_id 参数 (conversation_buffer.py:79)。session_id 已通过
                # memory_manager.remember(metadata={"session_id": ...}) 存储到长期记忆
                # (下方行 542), ConversationBuffer 只是快速上下文缓冲, 无 session 维度。
                # 与 mem_core.py:635-637 的正确用法对齐。
                conversation_buffer.add_user_message(user_input)
                conversation_buffer.add_agent_message(reply)
                logger.debug("对话已添加到缓冲区")

            # 使用记忆管理器
            if memory_manager:
                # 会话作用域打标：协作群轮 → room:<id>；其余 → direct（基线，跨会话共享）。
                from neurova.collaboration.memory_scope import scope_tag_for_turn

                _collab = isinstance(metadata, dict) and metadata.get("turn_origin") == "collaboration"
                _scope = scope_tag_for_turn(collab=_collab, room_id=session_id if _collab else "")
                # 保存用户消息记忆
                user_memory_id = memory_manager.remember(
                    content=f"用户: {user_input}",
                    memory_type="episodic",
                    metadata={"sender_type": "user", "session_id": session_id or "default", "chat_scope": _scope},
                    origin="owner",
                )
                # 保存助手回复记忆
                agent_memory_id = memory_manager.remember(
                    content=f"助手: {reply}",
                    memory_type="episodic",
                    metadata={"sender_type": "agent", "session_id": session_id or "default", "chat_scope": _scope},
                    origin="agent",
                )
                logger.debug("对话已直接写入记忆数据库")

                # 保存情感信息到记忆
                self._save_emotion_to_memory(memory_manager, user_input, user_memory_id)

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="Memory saved successfully",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"user_memory_id": user_memory_id, "agent_memory_id": agent_memory_id},
                )
            )
        except Exception as e:
            # Bug #1 fix: 编程错误（TypeError/AttributeError/NameError 等）必须 re-raise
            # 不能被降级为 FAILED 静默返回，否则 P0-C2 的 re-raise 机制失效
            if isinstance(e, self._PROGRAMMING_ERRORS):
                raise
            logger.warning("对话记忆保存失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    def _save_emotion_to_memory(self, memory_manager, user_input: str, memory_id: str):
        """将情感信息保存到记忆"""
        # Bug #7 fix: memory_id 为 None 或空字符串时不调用 set_emotion
        # 避免 emotion_module.set_emotion(None, ...) 导致下游 KeyError/AttributeError
        if not memory_id:
            logger.debug("跳过情感保存: memory_id 为空")
            return

        emotion_module = getattr(memory_manager, "emotion_module", None)
        if not emotion_module:
            return

        try:
            # 分析用户输入的情感
            emotion_state = emotion_module.analyze_text_emotion(user_input)
            if emotion_state and emotion_state.primary_emotion.value != "neutral":
                emotion_module.set_emotion(memory_id, emotion_state)
                logger.debug("情感已保存到记忆 %s: %s", memory_id, emotion_state.primary_emotion.value)
        except Exception as e:
            logger.debug("情感保存失败: %s", e)

    async def _step_generate_tts(
        self,
        reply: str,
        session_id: str,
        enable_tts: bool,
    ) -> tuple:
        """生成 TTS 语音（通过统一语音管线）"""
        step_name = "generate_tts"
        start_time = time.time()
        config = self._agt.config
        # P2-5 修复: Agent.chat(enable_tts=None) 的契约是 "None 表示使用配置"。
        # 原实现 `enable_tts and config.enable_tts` 对 None 恒 falsy，而 API 层从不传
        # enable_tts → 配置了 enable_tts=True 的 Agent 永远不生成 TTS。
        # 现: None → 按配置; 显式 bool → 覆盖配置（显式 True 时若语音管线不存在仍安全跳过）。
        if enable_tts is None:
            use_tts = bool(getattr(config, "enable_tts", False))
        else:
            use_tts = bool(enable_tts)

        # 优先使用统一语音管线
        voice_pipeline = self._get_dependency("voice_pipeline")
        if not use_tts or not voice_pipeline:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="TTS not enabled or voice_pipeline not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return None, None

        try:
            # 获取用户和Agent ID
            user_id = getattr(config, "user_id", "default")
            agent_id = getattr(config, "agent_id", "default")
            voice = getattr(config, "tts_voice", "default")

            # 通过统一语音管线处理 TTS
            pipeline_result = await voice_pipeline.process_tts(
                text=reply,
                user_id=user_id,
                agent_id=agent_id,
                voice=voice,
            )

            if pipeline_result.error:
                logger.warning("统一语音管线 TTS 失败: %s", pipeline_result.error)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.FAILED,
                        message=f"Voice pipeline TTS failed: {pipeline_result.error}",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
                return None, None

            # 保存音频到文件
            if pipeline_result.audio_data:
                timestamp = int(time.time())
                audio_filename = f"tts_{session_id or 'default'}_{timestamp}.wav"
                audio_path = Path(config.attachment_dir) / audio_filename
                audio_path.parent.mkdir(parents=True, exist_ok=True)

                with open(audio_path, "wb") as f:
                    f.write(pipeline_result.audio_data)
                logger.info("TTS语音已生成: %s", audio_path)

                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"TTS generated via voice pipeline: {audio_path}",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={
                            "audio_path": str(audio_path),
                            "audio_size": len(pipeline_result.audio_data),
                            "tts_engine": pipeline_result.tts_engine,
                            "tts_voice": pipeline_result.tts_voice,
                            "tts_duration_ms": pipeline_result.tts_duration_ms,
                            "context_injected": pipeline_result.context_injected,
                            "memory_recorded": pipeline_result.memory_recorded,
                        },
                    )
                )
                return str(audio_path), pipeline_result.audio_data
            else:
                logger.warning("统一语音管线 TTS 返回空音频数据")
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.FAILED,
                        message="Voice pipeline TTS returned empty audio data",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
                return None, None
        except Exception as e:
            logger.warning("TTS语音生成失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return None, None

    async def _step_cognitive_analysis(self, user_input: str) -> float:
        """P-6: 认知能力分析 — 实际计算分数而非硬编码"""
        step_name = "cognitive_analysis"
        start_time = time.time()

        growth_analyzer = self._get_dependency("growth_analyzer")
        if not growth_analyzer:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="growth_analyzer not available",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"score": 0.75},
                )
            )
            return 0.75  # P0-D1: 中性偏高默认值（与测试规约一致）

        try:
            w = user_input.replace("？", "").replace("?", "").replace("！", "").replace("!", "").strip()
            if not w:
                return 0.75

            # P-6: 中文分词改进 — 按标点和空格切分,再按字符类型聚合
            import re
            # 按标点/空格切分
            raw_parts = re.split(r'[,，。.!！?？;；\s]+', w)
            concepts = [p.strip() for p in raw_parts if len(p.strip()) > 1]

            if not concepts:
                # 对纯中文无标点的输入,按固定窗口切分
                concepts = [w[i:i+4] for i in range(0, len(w), 4) if len(w[i:i+4]) > 1]

            # 实际计算分数: 基于输入长度和概念数量
            length_score = min(1.0, len(w) / 200.0)  # 长度因子
            concept_score = min(1.0, len(concepts) / 10.0)  # 概念丰富度
            score = 0.3 + 0.4 * length_score + 0.3 * concept_score  # 0.3-1.0 范围

            if concepts:
                # 根因修复: record_learning 真实签名是 (dimension, score, ...)，
                # 此前传 concepts=..., context=... → TypeError 被吞，成长记录从未写入。
                growth_analyzer.record_learning(
                    dimension=GrowthDimension.LEARNING,
                    score=round(score * 100.0, 2),
                    task_type="conversation",
                    description="对话认知分析",
                    metadata={"concepts": concepts[:10]},
                )

            logger.info("🧠 认知能力分析完成: score=%.2f, concepts=%d", score, len(concepts))
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="Cognitive analysis completed",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"score": round(score, 3), "concepts": concepts[:5]},
                )
            )
            return score
        except Exception as e:
            logger.warning("认知能力分析失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

        return 0.75  # P0-D1: 异常降级默认值（与测试规约一致）

    # ============================================================
    # 反思相关常量和方法
    # ============================================================

    REFLECTION_CONFUSION_KEYWORDS = [
        "不明白",
        "不对",
        "错了",
        "不是这样",
        "搞错了",
        "再想想",
        "重新",
    ]
    REFLECTION_UNCERTAINTY_KEYWORDS = [
        "不确定",
        "可能",
        "也许",
        "大概",
        "或许",
        "估计",
        "不敢肯定",
    ]
    REFLECTION_TURN_INTERVAL = 10

    async def _step_reflection(self, user_input: str, reply: str):
        """Step 8.5: 交互后反思 — 生成反思日志

        触发条件（可配置）：
        1. 用户表达了困惑或不满意（关键词匹配）
        2. Agent 回复了不确定的内容（关键词匹配）
        3. 每 N 轮对话强制反思（REFLECTION_TURN_INTERVAL）
        """
        step_name = "reflection"
        start_time = time.time()

        growth_log_manager = self._get_dependency("growth_log_manager")
        if not growth_log_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="growth_log_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        should_reflect = self._should_reflect(user_input, reply)
        if not should_reflect:
            logger.debug("反思条件未满足，跳过 Step 8.5")
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="Reflection conditions not met",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            reflection_type = self._infer_reflection_type(user_input, reply)
            title = f"对话反思 - {reflection_type.value}"
            is_confusion = any(kw in user_input.lower() for kw in self.REFLECTION_CONFUSION_KEYWORDS)
            is_uncertain = any(kw in reply.lower() for kw in self.REFLECTION_UNCERTAINTY_KEYWORDS)
            # 根因修复（2026-09-15）：原 user_input[:200]/reply[:200] 在生成时
            # 就把正文切掉——反思日志落库即永久残缺（详情弹窗看到的半句即此）。
            # 全文只在存储层，截断收口到展示/注入侧（orchestrator 注入封顶 + 前端预览）。
            # P1 教训化：原 insights=[] 恒为空 → 注入进 prompt 的"反思"只是原始回声，
            # 无指导性。现确定性合成教训句，insights[0] 进注入（orchestrator/injector
            # 均优先取 insights[0]），全文对话仍完整保留在正文尾部（存储无损契约不变）。
            lesson, action = self._compose_reflection_lesson(user_input, reply, is_confusion, is_uncertain)
            content = f"{lesson}\n用户输入: {user_input}\nAgent 回复: {reply}"
            context = {
                "trigger": self._get_reflection_trigger_reason(user_input, reply),
                "source": "post_chat",
                "user_input_length": len(user_input),
                "reply_length": len(reply),
            }
            insights = [lesson]
            action_items = [action]
            confidence = 0.5

            # P0c 效力反馈：用户困惑 = 对本轮被注入的反思的负证据（注入了仍困惑）。
            # 只降不删：register_negative_feedback 跌破阈值转 rejected，脱离恒定注入
            # 但原文仍可语义召回。仅困惑降权——回复含不确定词是 Agent 自我怀疑，
            # 不构成对旧注入的否定。
            if is_confusion:
                from neurova.core.turn_context import get_turn_injected_reflections

                for rid in get_turn_injected_reflections() or []:
                    growth_log_manager.register_negative_feedback(rid)

            entry = await growth_log_manager.generate_log(
                type=reflection_type,
                title=title,
                content=content,
                context=context,
                insights=insights,
                action_items=action_items,
                confidence=confidence,
            )

            # 根因修复: QuestionQueueManager 此前零调用——反思检测到困惑/不确定时
            # 生成澄清型问题入队，形成 反思 → 问题队列 → 上下文注入/主动提问 的闭环
            question_manager = self._get_dependency("question_queue_manager")
            if question_manager and (is_confusion or is_uncertain):
                try:
                    from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionPriority

                    if is_confusion:
                        q_content = f"用户对「{user_input[:60]}」有困惑，主动询问具体哪里不清楚"
                        q_priority = QuestionPriority.HIGH
                    else:
                        q_content = f"回答「{user_input[:60]}」时存在不确定，主动确认是否需要补充信息"
                        q_priority = QuestionPriority.NORMAL

                    pending_contents = {q.content for q in question_manager.get_pending_questions()}
                    if q_content not in pending_contents:
                        question_manager.generate_question(
                            content=q_content,
                            priority=q_priority,
                            metadata={"source": "reflection", "reflection_id": entry.id if entry else ""},
                        )
                        logger.info("❓ 澄清型问题已入队: %s", q_content[:50])
                except Exception as qe:
                    logger.debug("生成澄清型问题失败: %s", qe)

            if entry:
                logger.info(
                    f"🧠 反思日志已生成: {entry.id} (类型: {reflection_type.value}, 触发: {context['trigger']})"
                )
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Reflection log generated: {entry.id}",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"reflection_id": entry.id, "type": reflection_type.value},
                    )
                )
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.FAILED,
                        message="Failed to generate reflection log",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
        except Exception as e:
            logger.warning("Step 8.5 反思日志生成失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    def _compose_reflection_lesson(
        self, user_input: str, reply: str, is_confusion: bool, is_uncertain: bool
    ) -> "tuple[str, str]":
        """确定性合成教训句与行动项（P1 教训化，零 LLM）。

        触发路径与 _should_reflect 的三分支一一对应；关键词取首个命中，
        让"下次怎么办"进注入（insights[0]），而不是原始对话回声。
        """
        if is_confusion:
            kw = next((k for k in self.REFLECTION_CONFUSION_KEYWORDS if k in user_input.lower()), "")
            return (
                f"用户对回答表示困惑或不满（命中「{kw}」）：下次先复述确认用户真正关心的点，再给出针对性回答",
                "回答前确认用户关注点，答后主动询问是否解决了疑问",
            )
        if is_uncertain:
            kw = next((k for k in self.REFLECTION_UNCERTAINTY_KEYWORDS if k in reply.lower()), "")
            return (
                f"回答中存在不确定表述（命中「{kw}」）：下次先补充信息来源或先向用户澄清所需信息",
                "对不确定结论标注依据，必要时先提问再作答",
            )
        return (
            "周期性反思：回顾本轮对话的信息缺口与用户反馈信号",
            "关注后续轮次用户反馈以校准回答风格",
        )

    def _should_reflect(self, user_input: str, reply: str) -> bool:
        """判断是否应该触发反思"""
        user_lower = user_input.lower()
        reply_lower = reply.lower()

        # 用户表达困惑
        if any(kw in user_lower for kw in self.REFLECTION_CONFUSION_KEYWORDS):
            return True

        # Agent 回复不确定
        if any(kw in reply_lower for kw in self.REFLECTION_UNCERTAINTY_KEYWORDS):
            return True

        # 周期性反思
        turn_count = getattr(self._agt, "turn_count", 0)
        # Mock/异常类型防御：非 int 视为 0
        if not isinstance(turn_count, int):
            turn_count = 0
        if turn_count > 0 and turn_count % self.REFLECTION_TURN_INTERVAL == 0:
            return True

        return False

    def _infer_reflection_type(self, user_input: str, reply: str) -> "ReflectionType":
        """根据对话内容推断反思类型

        映射关系:
        - 错误/失败 → ERROR
        - 问题/怎么 → IMPROVEMENT
        - 决定/选择 → STRATEGY
        - 不确定性 → PERFORMANCE
        - 默认 → INSIGHT
        """
        from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionType as RT

        user_lower = user_input.lower()
        reply_lower = reply.lower()

        if any(kw in user_lower for kw in ["错误", "失败", "出错", "bug"]):
            return RT.ERROR
        if any(kw in user_lower for kw in ["问题", "怎么", "如何", "为什么"]):
            return RT.IMPROVEMENT
        if any(kw in user_lower for kw in ["决定", "选择", "应该"]):
            return RT.STRATEGY
        if any(kw in reply_lower for kw in self.REFLECTION_UNCERTAINTY_KEYWORDS):
            return RT.PERFORMANCE

        return RT.INSIGHT

    def _get_reflection_trigger_reason(self, user_input: str, reply: str) -> str:
        """获取反思触发原因"""
        user_lower = user_input.lower()
        reply_lower = reply.lower()

        for kw in self.REFLECTION_CONFUSION_KEYWORDS:
            if kw in user_lower:
                return f"用户困惑关键词: {kw}"

        for kw in self.REFLECTION_UNCERTAINTY_KEYWORDS:
            if kw in reply_lower:
                return f"Agent 不确定性关键词: {kw}"

        turn_count = getattr(self._agt, "turn_count", 0)
        # Mock/异常类型防御：非 int 视为 0
        if not isinstance(turn_count, int):
            turn_count = 0
        if turn_count > 0 and turn_count % self.REFLECTION_TURN_INTERVAL == 0:
            return f"周期性反思 (turn={turn_count})"

        return "未知触发"

    @staticmethod
    def _turn_structure_key(ticket) -> str:
        """本轮的工具序列结构指纹——与咽喉票据的 `structure_key` 同函数产出。

        单源在同名函数 `creation_governance.structure_key`（票据写入侧也用它），
        这里只是把已解析出的 steps 再喂一次，**不另写第二份指纹算法**。
        """
        if not ticket.steps:
            return ""
        try:
            from neurova.skills.creation_governance import structure_key

            return structure_key([dict(step) for step in ticket.steps]) or ""
        except Exception:  # noqa: BLE001 - 指纹算不出就不落该键（不阻断沉淀）
            logger.debug("结构指纹计算跳过", exc_info=True)
            return ""

    async def _step_record_experience(
        self,
        user_input: str,
        reply: str,
        save_memory: bool,
    ):
        """通过统一进化引擎记录经验"""
        step_name = "record_experience"
        start_time = time.time()

        # Bug #3 fix: save_memory=False 时跳过经验记录，避免写入 evolution
        # 原代码无条件执行，导致 save_memory=False 仍触发 evolution 记录
        if not save_memory:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="save_memory=False, skip experience recording",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        evolution = self._get_dependency("evolution")
        if not evolution:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="evolution not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            tool_messages = self._agt._collect_tool_messages()
            tools_used = list(set(tm.get("tool_name", "unknown") for tm in tool_messages))

            # 记录经验到进化系统（只调用一次）
            if hasattr(evolution, "on_experience_recorded"):
                from neurova.evolution.evolution_facade import EvolutionFacade
                facade = EvolutionFacade(evolution)
                # P-5 → 工单 002 → 工单 010：成败来源改为服务端票据优先。
                # 002 让 `success` 位开始携带信息（只读 `tool_result`，无回执即
                # None），但它读的是本轮工具执行自己的回执；010 把它降为**旁路
                # 证据**：`creation_governance` 的票据口径更严（还要求结果非空、
                # 非策略拒绝、按独立任务算失败粘性），有结论即覆盖本轮回执。
                # 无票据 ⇒ 记录聚合继续决定成败位，但落库标 `unevidenced`（D1）。
                from neurova.evolution.objective_evidence import resolve_ticket_evidence

                ticket = resolve_ticket_evidence(self._agent, tool_messages)
                tool_success = ticket.outcome
                # agent 级隔离: 显式传本 agent 的结晶器。单例上的
                # evolution.crystallizer 会被多 agent 初始化 last-writer-wins
                # 覆盖,不传会把 A agent 的经验结晶进 B agent 的库
                facade.record_experience(
                    text=f"用户: {user_input}\n助手: {reply}",
                    task=user_input,
                    tools=tools_used,
                    success=tool_success,
                    crystallizer=getattr(self._agent, "crystallizer", None),
                )
                logger.info("📚 对话经验已记录 (工具: %s, 票据: %s)", tools_used, ticket.lookup)

                # EKB 写入闭环：同步沉淀到经验知识库（注入侧
                # context/injector._build_experience_context 的数据源）。
                # 此前 EKB 只读不写，"相关经验"注入永远查不到对话沉淀。
                adoption_writeback = 0
                try:
                    from neurova.skills.experience_knowledge_base import (
                        ExperienceKnowledgeBase,
                        ExperienceRecord,
                    )

                    skill_tag = ",".join(tools_used[:3]) if tools_used else "chat"
                    # 单例复用（复审残余点 B）：每轮 new 连接不 close 是连接 churn，
                    # 模块单例长期存在零成本
                    from neurova.skills.experience_knowledge_base import (
                        get_experience_knowledge_base,
                    )

                    ekb = get_experience_knowledge_base()
                    # 工单 009：置信度取四态语义（未测量 ⇒ NULL，不得由 success
                    # 二值折算）；耗时取咽喉累加的轮级聚合。两者此前在生产写侧
                    # 都无人写入（库实测 nonNULL 0/103）。
                    from neurova.core.turn_context import get_turn_tool_elapsed

                    ekb.add_experience_record(
                        skill_name=skill_tag,
                        exp=ExperienceRecord(
                            skill_name=skill_tag,
                            context={
                                "user_input": user_input,
                                # 结构身份（工具序列 + 参数形状的指纹，**只存
                                # 指纹不存参数明文**）：让"这串工具该怎么传参"
                                # 成为可查询的事实，同时不落敏感参数内容。
                                "structure_key": self._turn_structure_key(ticket),
                            },
                            result={"reply_excerpt": reply[:200]},
                            # 工单 004：`bool(None)` 把"本轮没有客观回执"折成失败，
                            # 于是库里三分变两分。三态原样落库（NULL=未测量）。
                            success=tool_success,
                            feedback=user_input[:100],
                        ),
                        # A-03 同根因命中点：Agent.agent_id 不存在（在 config 上），
                        # 原写法恒 None，EKB 沉淀记录永远归属不了 agent
                        agent_id=str(getattr(self._agent.config, "agent_id", "") or "") or None,
                        session_id=str(getattr(self._agent, "session_id", "") or "") or None,
                        execution_time=get_turn_tool_elapsed() or None,
                        # 置信度是"这条经验值多少"的读数：只有服务端票据带结论时
                        # 才有值，未测量保持 NULL（不写 0.5 之类占位）。
                        confidence_score=(
                            None if ticket.ticket is None else (1.0 if ticket.ticket else 0.0)
                        ),
                        # 工单 002→008→010：形成侧第三态走一等列 evidence_state。
                        # 等级只认服务端票据（`ticket.evidence`）——002 的记录聚合
                        # 在无票据时仍是成败位的来源，但它不再是"有证据"。
                        evidence=ticket.evidence,
                    )
                    # 工单 006：按本轮注入身份集回写采纳结果，成败取票据优先的
                    # 三态（None 记 unevidenced，不是"成功"也不是"失败"）。
                    # 未注入 ⇒ record_injection_adoption 直接返回 0，不写任何行。
                    from neurova.core.turn_context import get_turn_injected_experiences

                    adoption_writeback = ekb.record_injection_adoption(
                        get_turn_injected_experiences(), tool_success
                    )
                except Exception as ekb_error:  # noqa: BLE001 - 沉淀失败不阻断主流程
                    logger.debug("经验知识库写入失败（不阻断）: %s", ekb_error)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Experience recorded with {len(tools_used)} tools",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={
                            "tools_used": tools_used,
                            # 回写行数进观测面：008 的质量指标要能区分"没注入"与
                            # "注入了但回写通路断了"
                            "adoption_writeback": adoption_writeback,
                            # 工单 010：取证过程本身必须可观测——"查不到票"与
                            # "查不了票"在库里都是 unevidenced，只有在观测面分得开
                            # 才不会被误读成"这个 agent 从来没有客观回执"
                            "ticket_state": ticket.lookup,
                            "ticket_reason": ticket.verdict.reason,
                        },
                    )
                )
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="evolution has no on_experience_recorded method",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
        except Exception as e:
            logger.warning("经验记录失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_skill_funnel_flush(self, reply: str, actual_session_id: str = "") -> None:
        """Step 9.06: 技能质量漏斗 + 信任观测回写。

        读本轮 tool_executor 写入 turn_context 的技能派发账本，按
        compute_skill_funnel_update 归因（兜底完成不计功）写穿 manifest usage；
        再由 compute_trust_observations 派生每技能一个独立任务观测
        （task 身份 = session#turn，服务层按 task_id 去重）喂信任状态机。
        任务完成口径：post-chat 仅在回复成功生成后执行，reply 非空即视为
        本轮任务完成（空回复=未产出，不记 completion）。

        Wave H-W1 三层库：账本条目自带 (pool, owner_key) 归属，按库分组后
        经 library_service 路由回写各库实例——agent 副本记 agent 账、user
        副本记 user 账、public 副本记公共聚合账（缺 owner 的条目回退本
        agent 视图，与 Wave A/B 既有语义一致）。
        """
        from neurova.core.turn_context import get_turn_count, get_turn_skill_funnel
        from neurova.skills.skill_service import (
            compute_skill_funnel_update,
            compute_trust_observations,
        )

        entries = get_turn_skill_funnel()
        if not entries:
            return
        task_completed = bool(reply and reply.strip())
        agent_id = str(getattr(self._agent.config, "agent_id", "") or "")
        if not agent_id:
            return

        # 按 (pool, owner) 分组（默认 agent+本 agent——无库参数条目零变化）
        groups: dict = {}
        for e in entries:
            pool = str(e.get("pool") or "agent")
            owner = str(e.get("owner_key") or "") or agent_id
            groups.setdefault((pool, owner), []).append(e)

        from neurova.skills import library_service as lib

        task_id = f"{actual_session_id or 'anon'}#{get_turn_count()}"
        for (pool, owner), group in groups.items():
            updates = compute_skill_funnel_update(group, task_completed=task_completed)
            observations = compute_trust_observations(group, task_completed)
            if not updates and not observations:
                continue
            try:
                service = lib.get_library(pool, owner if pool != lib.POOL_USER else owner)
            except ValueError as route_err:
                logger.warning("技能账本路由失败（pool=%s owner=%s）: %s", pool, owner, route_err)
                continue
            for skill_id, delta in updates.items():
                service.record_skill_funnel(skill_id, **delta)
            for skill_id, outcome in observations.items():
                service.record_trust_observation(skill_id, outcome, task_id=task_id)

    async def _step_evocate_generation(
        self,
        user_input: str,
        reply: str,
        session_id: str,
    ):
        """Step 9.1: 从对话中生成 NeurovaHebb（Evocate 闭环生成端）

        数据流: 对话 → generate_from_conversation → 存储 NeurovaHebb → 下次检索注入
        """
        step_name = "evocate_generation"
        start_time = time.time()

        neuHebb_manager = self._get_dependency("neuHebb_manager")
        if not neuHebb_manager:
            logger.debug("NeuHebbManager 未初始化，跳过 Evocate 生成")
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="neuHebb_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            hebbs = neuHebb_manager.generate_from_conversation(
                user_input=user_input,
                reply=reply,
                session_id=session_id or "default",
            )
            if hebbs:
                logger.info(
                    f"🧠 Evocate: 从对话生成 %d 个 NeurovaHebb (session: %s)",
                    len(hebbs),
                    session_id,
                )
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Generated {len(hebbs)} NeurovaHebb",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"hebbs_count": len(hebbs), "session_id": session_id},
                    )
                )
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message="No NeurovaHebb generated",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"hebbs_count": 0},
                    )
                )
        except Exception as e:
            logger.warning("Evocate 生成失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_p0_post_processing(self, save_memory: bool):
        """P0: 执行所有 P0 接线模块的后处理"""
        # Bug #3 fix: save_memory=False 时跳过所有 P0 后处理步骤
        # 原代码无条件执行，导致 save_memory=False 仍触发 evolution/lifecycle 等模块
        if not save_memory:
            self._step_results.append(
                StepResult(
                    step_name="p0_post_processing",
                    status=StepStatus.SKIPPED,
                    message="save_memory=False, skip all P0 post-processing",
                )
            )
            return

        await self._step_lifecycle_evaluate()
        await self._step_pattern_mining()
        await self._step_genetic_evolution()
        await self._step_marketplace_publish()

    async def _step_lifecycle_evaluate(self):
        """9.5: 工具生命周期评估"""
        step_name = "lifecycle_evaluate"
        start_time = time.time()

        tool_lifecycle = self._get_dependency("tool_lifecycle")
        if not tool_lifecycle:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="tool_lifecycle not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            lifecycle_report = tool_lifecycle.evaluate()
            evolution = self._get_dependency("evolution")

            if "degraded" in lifecycle_report or "archived" in lifecycle_report:
                logger.info("🔄 工具生命周期评估: %s", lifecycle_report)

            # 对降级/归档的工具应用权重衰减
            # Bug #9 fix: 使用公开的 tool_weights API，而非直接访问 _tool_weights 私有属性
            # 原代码: if evolution and hasattr(evolution, "_tool_weights"):
            # evolution._tool_weights[tool_name].adaptive_multiplier *= factor
            # 修复后: 通过公开 API 操作
            # 融合修复（闭环审计 2026-09-04）：A/B 融合删除 tool_weights.py 后
            # get_tool_entry/record_failure 不存在，两处 hasattr 恒 False 静默
            # no-op；改用融合版公开 API get_weight + update_weight(False)
            tool_weights = getattr(evolution, "tool_weights", None) if evolution else None
            if tool_weights:
                decay = lifecycle_report.get("decay", {})
                if decay:
                    for tool_name, factor in decay.items():
                        # 降级/归档工具视为失败信号，记录真实失败
                        if tool_weights.get_weight(tool_name) is not None:
                            tool_weights.update_weight(tool_name, False)
                    logger.debug("📉 工具权重衰减: %s 个工具", len(decay))

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Lifecycle evaluation completed",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"report": lifecycle_report},
                )
            )
        except Exception as e:
            logger.warning("工具生命周期评估失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_pattern_mining(self):
        """9.6: PatternMiner 序列收集与挖掘"""
        step_name = "pattern_mining"
        start_time = time.time()

        evolution = self._get_dependency("evolution")
        pattern_miner = getattr(evolution, "pattern_miner", None) if evolution else None
        if not pattern_miner:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="pattern_miner not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            tool_messages = self._agt._collect_tool_messages()
            if not tool_messages:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="No tool messages to process",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
                return

            # 构建工具调用序列
            sequence = []
            for tm in tool_messages:
                sequence.append(tm.get("tool_name", "unknown"))

            # 添加序列并挖掘
            # 工单 013：台账只记服务端票据的三态（010 的 `TicketEvidence.ticket`）。
            # 本轮回执不是票据，无票就传 None —— 在这里判空兜底等于给模式自投成功票。
            from neurova.evolution.objective_evidence import resolve_ticket_evidence

            pattern_miner.add_sequence(
                sequence, success=resolve_ticket_evidence(self._agent, tool_messages).ticket)
            patterns = pattern_miner.mine()

            if patterns:
                logger.info("⛏️ PatternMiner 发现 %s 个频繁模式", len(patterns))

            # Historical frequency is not task success; only finish_task feeds skill evidence.

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Pattern mining completed: {len(patterns) if patterns else 0} patterns found",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"patterns_count": len(patterns) if patterns else 0, "sequence_length": len(sequence)},
                )
            )
        except Exception as e:
            logger.warning("PatternMiner 序列收集失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_genetic_evolution(self):
        """9.7: ToolGeneticEngine 种子种群并进化"""
        step_name = "genetic_evolution"
        start_time = time.time()

        evolution = self._get_dependency("evolution")
        if not evolution:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="evolution not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        genetic_engine = getattr(evolution, "genetic_engine", None)
        pattern_miner = getattr(evolution, "pattern_miner", None)
        if not genetic_engine or not pattern_miner:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="genetic_engine or pattern_miner not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            if pattern_miner.sequence_count == 0:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="No sequences to evolve",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
                return

            top_patterns = pattern_miner.get_top_patterns()

            # 从模式构建基因型种子
            from neurova.evolution.genetic_engine import ToolGenotype

            # 工单 013：成功率来自序列台账（010 的服务端票据），删掉 `or 0.5` 兜底。
            # 兜底把"没有证据"洗成"中性票"，而 0.5 在阈值 0.8 下的实际效果是永不注册
            # —— 于是遗传臂的静默被误读成"模式质量差"，看不见真正缺的是证据。
            # 无据一律不播种（无据不投票，与 002/005 同口径）。
            seeded = skipped_unevidenced = 0
            for pattern in top_patterns:
                if isinstance(pattern, dict):
                    seq = pattern.get("tools") or []
                    p_success = pattern.get("success_rate")
                else:
                    seq = getattr(pattern, "tools", [])
                    p_success = getattr(pattern, "success_rate", None)
                if p_success is None:
                    skipped_unevidenced += 1
                    continue
                genotype = ToolGenotype(
                    tool_sequence=seq,
                    success_rate=float(p_success),
                )
                genetic_engine.add_to_population(genotype)
                seeded += 1

            # 执行进化
            new_gen = genetic_engine.evolve()
            logger.info("🧬 ToolGeneticEngine 进化完成: 种群=%s, 新个体=%s", len(genetic_engine.population), len(new_gen))

            # 将进化结果反馈到工具权重
            # 融合修复（闭环审计 2026-09-04）：get_tool_entry 在融合版
            # AdaptiveToolWeights 上不存在，hasattr 恒 False 使遗传高适应度
            # 反哺静默失效；改用公开 API get_weight/update_weight
            tool_weights = getattr(evolution, "tool_weights", None)
            for genotype in new_gen:
                for tool_name in genotype.tools:
                    if tool_weights and tool_weights.get_weight(tool_name) is not None:
                        # 高适应度个体的工具应获得权重提升
                        if genotype.fitness > 0.5:
                            tool_weights.update_weight(tool_name, True)

            # Bug A-6 修复: 将高适应度进化工具注册到 SkillRegistry
            # 之前进化成果只停留在 genetic_engine 内部种群，下次对话时
            # chat_pipeline._check_nl_synthesis 仍因 has_tool=False 触发重复合成
            registered_to_registry = 0
            skill_registry = getattr(self._agt, "_skill_registry", None)
            if skill_registry is not None and hasattr(genetic_engine, "register_to_skill_registry"):
                try:
                    # 断点 #2 修复：与 _step_pattern_mining 的 skill_packer 路径对齐，
                    # 进化技能同步持久化 SkillService（SkillRegistry 纯内存，重启即丢）
                    skill_service = None
                    try:
                        from neurova.skills.skill_service import SkillService

                        agent_id = getattr(self._agt.config, "agent_id", "default")
                        skill_service = SkillService(agent_id=agent_id)
                    except Exception as svc_err:
                        logger.warning("创建 SkillService 失败, 进化技能仅写 registry: %s", svc_err)

                    registered_to_registry = genetic_engine.register_to_skill_registry(
                        skill_registry, skill_service=skill_service
                    )
                    if registered_to_registry > 0:
                        logger.info(
                            "🧬 已注册 %s 个进化工具到 SkillRegistry（避免下次对话重复合成）",
                            registered_to_registry,
                        )
                except Exception as reg_err:
                    logger.warning("进化工具注册到 SkillRegistry 失败: %s", reg_err)

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Genetic evolution completed: {len(new_gen)} new individuals, {registered_to_registry} registered to SkillRegistry",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={
                        "population_size": len(genetic_engine.population),
                        "new_individuals": len(new_gen),
                        "registered_to_skill_registry": registered_to_registry,
                        # 工单 013：无据不播种必须可观测 —— 否则"遗传臂没动静"与
                        # "这一轮根本没有客观证据"在观测面上分不开
                        "seeded": seeded,
                        "skipped_unevidenced": skipped_unevidenced,
                    },
                )
            )
        except Exception as e:
            logger.warning("ToolGeneticEngine 进化失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_marketplace_publish(self):
        """9.8: ToolMarketplace 工具发布"""
        step_name = "marketplace_publish"
        start_time = time.time()

        marketplace = self._get_dependency("tool_marketplace")
        if not marketplace:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="tool_marketplace not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            tool_messages = self._agt._collect_tool_messages()
            skill_registry = getattr(self._agt, "_skill_registry", None)
            published_tools = []

            for tm in tool_messages:
                tool_name = tm.get("tool_name", "")
                if not tool_name:
                    continue

                # 检查是否已存在
                was_success = tm.get("type", "") == "tool_result" and tm.get("success", False)
                if not was_success:
                    continue

                # 尝试从 skill_registry 获取信息
                skill = None
                # H12 修复: 用 `is not None` 替代 falsy 检查 — 空 registry 不应跳过查询
                if skill_registry is not None:
                    skill = skill_registry.get_skill(tool_name)

                # 构建市场工具
                try:
                    from neurova.tool_layers import MarketplaceTool

                    mkt_tool = MarketplaceTool(
                        tool_id=f"auto-{tool_name}",
                        name=tool_name,
                        description=skill.description if skill else f"auto-registered tool: {tool_name}",
                        # [BUGFIX] 真实 MarketplaceTool dataclass 无 schema/agent_id 字段，
                        # 且 tool_id 为必填位置参数。原实现传入 schema=/agent_id= 会抛
                        # TypeError 被 except 吞掉，导致市场发布静默失败。这里补 tool_id，
                        # 并把 schema/agent_id 作为授权元数据放入 metadata（to_dict 会序列化）。
                        author=self._agt.config.agent_id,
                        metadata={
                            "schema": skill.to_schema() if skill and hasattr(skill, "to_schema") else {},
                            "agent_id": self._agt.config.agent_id,
                            "source": "auto-register",
                        },
                    )
                    marketplace.add_tool(mkt_tool)
                    logger.info("🏪 工具已发布到市场: %s", tool_name)
                    published_tools.append(tool_name)
                except (ImportError, Exception) as e:
                    logger.warning("ToolMarketplace 发布失败: %s", e)

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Published {len(published_tools)} tools to marketplace",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"published_tools": published_tools},
                )
            )
        except Exception as e:
            logger.warning("ToolMarketplace 发布失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_conflict_detection(self, user_input: str, reply: str):
        """Step 9.9: 记忆冲突**纯观测**——只记录，不阻断、不回滚（工单 012 裁决）。

        本步跑在 `save_memory` 之后，且检测器只给信号、判不出"两条里哪条是
        错的"；据此否决会随机丢真实记忆（回滚本身有 Step 9.95 版本快照兜底，缺
        的是"以哪条为准"的判据）。故显式定性为观测：结论里 `blocking=False`
        与 message 一同自陈"不阻断"，不得再留"检出了冲突"这种读起来像已处置的表述。

        **成员身份由本步负责，检测器只负责信号**（Issue #72 第四轮）：账上每条
        冲突的两个成员都必须是**库里查得到的行**。此前本步用一个自造 id
        `pending_new_memory` 充当"新证据"——那个 id 在库里不存在，账上成员因此
        永远指不出是谁，下游连"哪条跟哪条打架"都无从下手，这条链停在纯观测、
        "判不出哪条为准"的现场根因就在这里。现在"新证据"取本轮 `save_memory`
        真实落地的行（从步骤读数取 id，再回库定位），逐行与已有记忆比对。
        无法定位成员的信号如实计进 `conflicts_unidentified`，不入账。

        **检出与可读分开、但不留断点**：本步把检出的冲突连同依据落进记忆侧的账
        （`memory_manager.record_conflicts`，source 自陈本步名），
        于是"检出过什么"在 `get_conflict_summary()` / `/memory/stats` 上读得到。
        依据缺失的条目按诚实边界拒绝入账，`conflicts_recorded` 如实反映差额。
        """
        step_name = "conflict_detection"
        start_time = time.time()

        conflict_detector = self._get_dependency("conflict_detector")
        if not conflict_detector:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="conflict_detector not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        memory_manager = self._get_dependency("memory_manager")
        if not memory_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="memory_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            recent_memories = memory_manager.recall(user_input, limit=5)

            # P2-9 修复: 真实 API 是
            # detect_conflict(new_memory: Memory, existing_memories: List[Memory]) -> List[Dict]。
            # 原实现调用不存在的 check_conflict()，并假设返回值有
            # has_conflict/conflicts/confidence/summary 结构 —— 依赖一旦注入必然
            # AttributeError 被 except 吞掉，冲突检测步骤恒 FAILED（从未真正运行）。
            from neurova.cognitive_layers.memory_layer.models import Memory

            evidence_rows = _landedEvidenceRows(self._step_results, memory_manager)
            evidence_ids = {row["id"] for row in evidence_rows}
            earlier_memories = [
                Memory(id=str(m.get("id", "")), content=str(m.get("content", "")))
                for m in recent_memories
                if isinstance(m, dict) and m.get("content") and str(m.get("id", "")) not in evidence_ids
            ]
            locatable = evidence_ids | {m.id for m in earlier_memories}

            if evidence_rows:
                raw_conflicts = _detectAgainstEvidenceRows(
                    conflict_detector, evidence_rows, earlier_memories
                )
                conflicts = _conflictsWithLocatableMembers(raw_conflicts, locatable)
            else:
                # 本轮没有落地的证据行：**不造合成对象**——那正是查不到的成员的旧写法。
                # 没有可定位的对象就如实报"无对象可比"，不假装检出、也不入账。
                raw_conflicts = []
                conflicts = []
            unidentified = len(raw_conflicts) - len(conflicts)

            if raw_conflicts:
                for conflict in conflicts:
                    logger.info(
                        "  冲突: %s (相似度=%.2f, 矛盾分=%.2f) - %s",
                        conflict.get("type"),
                        conflict.get("similarity", 0.0),
                        conflict.get("contradiction_score", 0.0),
                        conflict.get("basis") or conflict.get("description"),
                    )
                logger.warning("⚠️ 检测到 %s 处记忆冲突（可定位成员 %s 处）",
                               len(raw_conflicts), len(conflicts))
                # 落账：检出多少条、账上留下多少条要分得开。依据缺失的按诚实边界
                # 拒绝入账（宁可不记，也不记一条读不懂的账），返回值如实反映差额。
                # 此前这一步只写日志、不写账，`get_conflict_summary()` 因此全仓
                # 零调用方——检出了什么在读取侧看不见（Issue #72 登记的残余项）。
                recorded = 0
                recorder = getattr(memory_manager, "record_conflicts", None)
                if callable(recorder):
                    try:
                        recorded = int(recorder(conflicts, source=step_name))
                    except Exception as e:  # noqa: BLE001 - 记账失败不阻断观测
                        logger.warning("冲突入账失败（观测结果仍在步骤读数里）: %s", e)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=(
                            f"检测到 {len(raw_conflicts)} 处记忆冲突（纯观测，不阻断写入；"
                            f"入账 {recorded} 条）"
                        ),
                        duration_ms=(time.time() - start_time) * 1000,
                        data={
                            "conflicts_count": len(raw_conflicts),
                            "conflicts_recorded": recorded,
                            # 成员在库里定位不到的条数：这些信号如实报出但不入账
                            # （说不清是谁的账无法被处置）。
                            "conflicts_unidentified": unidentified,
                            "evidence_rows": len(evidence_rows),
                            "blocking": False,
                            "conflicts": raw_conflicts,
                        },
                    )
                )
            else:
                logger.debug("记忆冲突纯观测：未检出冲突（本轮证据行 %d 条）", len(evidence_rows))
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=(
                            "未检出记忆冲突（纯观测，不阻断写入）"
                            if evidence_rows
                            else "没有本轮落地的证据行，冲突无对象可比（纯观测，不阻断写入）"
                        ),
                        duration_ms=(time.time() - start_time) * 1000,
                        data={
                            "conflicts_count": 0,
                            "conflicts_recorded": 0,
                            "conflicts_unidentified": unidentified,
                            "evidence_rows": len(evidence_rows),
                            "blocking": False,
                        },
                    )
                )
        except Exception as e:
            logger.warning("Step 9.9 记忆冲突检测失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_version_snapshot(self, user_input: str):
        """Step 9.95: 为相关记忆创建版本快照（确保可回滚）"""
        step_name = "version_snapshot"
        start_time = time.time()

        version_control = self._get_dependency("version_control")
        if not version_control:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="version_control not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        memory_manager = self._get_dependency("memory_manager")
        if not memory_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="memory_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            related_memories = memory_manager.recall(user_input, limit=3)
            snapshot_count = 0

            for mem in related_memories:
                memory_id = mem.get("id", "") if isinstance(mem, dict) else getattr(mem, "id", "")
                if memory_id:
                    # 签名对齐（遗留事项 ②）：create_snapshot 真实签名是
                    # (memory_id, content, metadata, author, description)——
                    # 原调用传不存在的 source/triggered_by，依赖一旦注入必
                    # TypeError（依赖注入后的潜伏雷）
                    mem_content = (
                        mem.get("content", "") if isinstance(mem, dict) else str(getattr(mem, "content", ""))
                    )
                    version_control.create_snapshot(
                        memory_id=memory_id,
                        content=mem_content,
                        metadata={
                            "source": "pre_conversation_backup",
                            "triggered_by": "post_chat_pipeline",
                        },
                        author="post_chat_pipeline",
                        description="会话前版本快照（可回滚保障）",
                    )
                    snapshot_count += 1

            if snapshot_count > 0:
                logger.debug("📸 已为 %s 条相关记忆创建版本快照", snapshot_count)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Created {snapshot_count} snapshots",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"snapshot_count": snapshot_count},
                )
            )
        except Exception as e:
            logger.warning("Step 9.95 记忆版本快照失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_proactive_question(self, user_input: str, reply: str) -> Optional[str]:
        """Step 10: 分析对话后决定是否主动提问

        根因修复: 原依赖 proactive_question_manager 全仓无实例化（恒 None，
        步骤恒 SKIPPED 死路）。统一接入 mem_core 构造的 QuestionQueueManager：
        弹出最高优先级待提问问题并标记已提问（进入冷却期）。

        Returns:
            主动提问内容（如果没有则返回 None）
        """
        step_name = "proactive_question"
        start_time = time.time()

        question_manager = self._get_dependency("question_queue_manager")
        if not question_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="question_queue_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return None

        try:
            entry = question_manager.get_next_question()
            if entry:
                question_manager.mark_asked(entry.id)
                # 主动行为账本：提问是真实发生的主动行为（2026-09-15 真实化接线）
                engine = self._get_dependency("proactive_behavior_engine")
                if engine:
                    try:
                        engine.record_action(
                            action_type="communication",
                            trigger=f"proactive_question:{entry.id}",
                            content=entry.content,
                        )
                    except Exception as ae:
                        logger.debug("主动行为记录失败: %s", ae)
                logger.info("🤔 主动提问: %s", entry.content[:50])
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Proactive question: {entry.content[:50]}",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"question": entry.content, "question_id": entry.id},
                    )
                )
                return entry.content

            logger.debug("问题队列无待提问问题（或全部处于冷却期）")
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="No pending questions in queue",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
        except Exception as e:
            logger.warning("Step 10 主动提问决策失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

        return None

    async def _step_motivation_observations(
        self,
        user_input: str,
        reply: str,
        cognitive_score: float,
        proactive_question: Optional[str],
    ) -> None:
        """Step 10.5: 动机观察（2026-09-15 真实化）——把本轮真实信号灌入 MotivationLedger

        信号源（不造假）：
        - 能力感: 本轮步骤无 FAILED 即成功，难度按输入长度估算
        - 成长感: Step 8 认知分析分作为理解度，输入前 60 字作为概念
        - 自主性: 本轮主动提问发生即记录（satisfaction=0.7）
        - 使命感: 不在本步（信号源=用户对主动提问的回答，见 growth 端点回流）
        """
        step_name = "motivation_observations"
        start_time = time.time()

        ledger = self._get_dependency("intrinsic_motivation")
        if not ledger:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="intrinsic_motivation not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            failed_this_round = any(r.status == StepStatus.FAILED for r in self._step_results)
            difficulty = min(1.0, max(0.05, len(user_input) / 500.0))
            ledger.observe_competence(success=not failed_this_round, difficulty=difficulty)

            concept = user_input[:60].strip() or user_input[:60]
            if concept:
                ledger.observe_growth(concept=concept, understanding=round(float(cognitive_score or 0.5), 3))

            if proactive_question:
                ledger.observe_autonomy(choice=str(proactive_question)[:80], satisfaction=0.7)

            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="Motivation observations recorded",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"success": not failed_this_round, "difficulty": round(difficulty, 3)},
                )
            )
        except Exception as e:
            logger.warning("动机观察失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_rsi_iteration(self) -> Optional[Dict[str, Any]]:
        """Step 11: RSI 迭代（递归自我改进）

        如果 RSI 编排器可用且应该继续迭代，执行一次 RSI 迭代。

        Returns:
            RSI 迭代结果（如果执行了），否则 None
        """
        step_name = "rsi_iteration"
        start_time = time.time()
        # 本步内三个消费方（改进落盘的 SkillService、MetaLedger、归因台账）必须用
        # 同一个 agent_id —— 台账按 agent 分库，各算各的会把归因查成 "default"。
        agent_id = str(getattr(getattr(self._agent, "config", None), "agent_id", "") or "default")

        # 根因修复: AutoSkillImprover 此前零调用——每轮批量扫描技能使用数据，
        # 对失败率超阈值的技能提出改进提案，并沉淀为反思日志回流上下文。
        # 断点 #3 修复：提案先尝试 apply_improvement 回写技能本体（保守语义：
        # 修订留痕进 config.revisions + 版本递增，不改工具序列），已应用的
        # 提案不再重复刷反思日志；未应用的（registry 不可用等）保持原提案日志。
        # P1-4：NEUROVA_EVOLUTION_QUEUE=1
        # 时改道"入队 + 就地 drain"——作业持久化，崩溃/失败可重试（启动
        # recover_stale 释放租约）；默认关=现状直跑，行为零变化。
        try:
            from neurova.evolution.skill_improver import get_skill_improver
            from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
                ReflectionType as _RealReflectionType,
            )

            improver = get_skill_improver()
            growth_log_manager = self._get_dependency("growth_log_manager")
            skill_registry = getattr(self._agt, "_skill_registry", None)
            # 改进落盘最后一米（复审残余点 C）：SkillService 传给 apply_improvement，
            # 应用后 config+version 同步磁盘 manifest——否则改进重启即失
            skill_service = None
            try:
                from neurova.skills.skill_service import SkillService

                skill_service = SkillService(agent_id=agent_id)
            except Exception as svc_err:
                logger.debug("创建 SkillService 失败, 改进仅内存态: %s", svc_err)
            # 判据升级：开启文本进化时走反射式改进——
            # 把真实失败记录喂给 ReflectiveMutator 产出 improved_text；开关关闭/
            # 无正文时内部退回字典建议（零破坏）。
            skill_text_loader = None
            if skill_registry is not None:
                def skill_text_loader(skill_id, _reg=skill_registry):
                    try:
                        cfg = getattr(_reg.get_skill(skill_id), "config", None) or {}
                        text = str(cfg.get("context_template") or "")
                        return text or None
                    except Exception:
                        return None

            from neurova.evolution.job_queue import queue_enabled

            if not queue_enabled():
                await run_skill_evolution_pass(
                    improver=improver,
                    growth_log_manager=growth_log_manager,
                    skill_registry=skill_registry,
                    skill_service=skill_service,
                    skill_text_loader=skill_text_loader,
                    reflection_type=_RealReflectionType,
                )
            else:
                from neurova.core.turn_context import get_turn_count, get_turn_session_id
                from neurova.evolution.job_queue import get_evolution_job_queue

                queue = get_evolution_job_queue()
                _idem = f"sev:{agent_id}:{get_turn_session_id() or 'anon'}#{get_turn_count()}"
                queue.enqueue("skill_evolution_pass", {"agent_id": agent_id}, idempotency_key=_idem)
                processed = 0
                _tried: list = []
                queue.recover_stale()
                while processed < 3:
                    job = queue.claim(f"postchat-{id(self)}", exclude_ids=tuple(_tried))
                    if job is None:
                        break
                    _tried.append(job["id"])
                    processed += 1
                    try:
                        await run_skill_evolution_pass(
                            improver=improver,
                            growth_log_manager=growth_log_manager,
                            skill_registry=skill_registry,
                            skill_service=skill_service,
                            skill_text_loader=skill_text_loader,
                            reflection_type=_RealReflectionType,
                        )
                        queue.complete(job["id"])
                    except Exception as job_err:  # noqa: BLE001 - 单作业失败可重试
                        queue.fail(job["id"], str(job_err))
        except Exception as e:
            logger.debug("技能改进提案扫描跳过: %s", e)

        # 经验-定义分离维护：未合并 applied 记录攒够阈值
        # → 定期重建技能定义（先归档可回滚）；使用统计圈淘汰候选（自动禁用
        # 默认关，治理设置 skill_auto_retire_enabled 打开才执行）。
        try:
            from neurova.evolution.skill_experience import run_skill_experience_maintenance

            # 归因教训源：MetaLedger 的活跃工具级教训（SelfModelEngine 产出）
            _meta_ledger = None
            try:
                from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

                _meta_ledger = get_meta_ledger(agent_id)
            except Exception as ledger_err:
                logger.debug("MetaLedger 获取失败，归因跳过: %s", ledger_err)

            _mtn = run_skill_experience_maintenance(
                registry=skill_registry, skill_service=skill_service,
                ledger=_meta_ledger, agent_id=agent_id,
            )
            if _mtn.get("attributed") or _mtn.get("rebuilt") or _mtn.get("retired") or _mtn.get("retire_candidates"):
                logger.info(
                    "🔧 技能经验维护: attributed=%s rebuilt=%s retired=%s retire_candidates=%s",
                    len(_mtn.get("attributed") or []),
                    _mtn.get("rebuilt"),
                    _mtn.get("retired"),
                    _mtn.get("retire_candidates"),
                )
        except Exception as mtn_err:
            logger.debug("技能经验维护跳过: %s", mtn_err)

        # 重复技能合并计划（P1-2 接线）：前缀簇 + umbrella 质量选取，
        # **只产计划**——执行走审批面（skill_pool_api /consolidation/*）。
        # 绝不自动合并：合并是"改行为/改技能库结构"的产物，与评审闸同一哲学。
        try:
            from neurova.evolution.skill_consolidator import plan_from_service
            from neurova.skills.skill_service import SkillService as _CSvc

            _c_svc = _CSvc(agent_id=str(getattr(self._agt.config, "agent_id", "default") or "default"))
            _c_plans = plan_from_service(_c_svc)
            if _c_plans:
                _store = _consolidation_plan_store(_c_svc.skills_dir)
                _store.upsert([p.to_dict() for p in _c_plans])
                logger.info("🧩 技能合并计划: %d 簇（待审批）", len(_c_plans))
        except Exception as _ce:
            logger.debug("技能合并计划生成跳过: %s", _ce)

        # 技能生命周期扫描：确定性、零 LLM，
        # active→stale(14d)→archived(30d)；首次 seed 不动库；间隔自持
        # （.lifecycle_state.json），不借本步 RSI 成本闸——同下方法内
        # 结晶裁决的接线教训。设置文件 lifecycle_sweep=false 可关。
        try:
            from neurova.evolution.evolution_settings import load_settings
            from neurova.evolution.skill_lifecycle import run_sweep_if_due
            from neurova.skills.skill_service import SkillService as _Svc

            _evo_settings = load_settings()
            if _evo_settings.lifecycle_sweep:
                agent_id = getattr(self._agt.config, "agent_id", "default")
                _svc = _Svc(agent_id=agent_id)
                run_sweep_if_due(
                    _svc, _svc.skills_dir,
                    interval_hours=_evo_settings.lifecycle_interval_hours,
                )
        except Exception as lc_err:
            logger.debug("技能生命周期扫描跳过: %s", lc_err)

        # 结晶候选 LLM 裁决：规则预筛过的候选在此
        # 批量做可复用性裁决——仅当有待审候选时才消耗一次 LLM 调用（天然
        # 低频）；LLM 不可用时候选留队等下轮（48h 超龄自动放行，不丢数据）。
        # 注意：不挂在 _step_extract_conversation_rules——该步有 LLM 成本闸
        # 默认关，挂在那里裁决在默认配置下永不运行（复核抓出的断点）。
        try:
            _crystallizer = getattr(self._agt, "crystallizer", None)
            if (
                _crystallizer is not None
                and hasattr(_crystallizer, "review_pending_with_llm")
                and _crystallizer.list_pending()
            ):
                _llm_client = self._get_dependency("llm_client")
                if _llm_client:
                    _crystallizer.set_llm_judge(_llm_client)  # 幂等：注入后闸分流生效
                    _review = await _crystallizer.review_pending_with_llm()
                    if _review.get("reviewed"):
                        logger.info(
                            "🧊 结晶候选 LLM 裁决: approved=%s rejected=%s 留队=%s",
                            _review.get("approved"),
                            _review.get("rejected"),
                            _review.get("skipped"),
                        )
        except Exception as _ce:
            logger.debug("结晶候选裁决失败（候选留队）: %s", _ce)

        # 工单 017：结晶模式冷处理（闲置超期 ⇒ 降温 ⇒ 退出注入池）。与候选裁决同通道
        # 低频跑（每 50 轮一次），不逐轮扫库；淘汰路径必须有写入方，否则只是文档。
        try:
            _crystallizer = getattr(self._agt, "crystallizer", None)
            _turns = getattr(self._agt, "turn_count", 0)
            if (
                _crystallizer is not None
                and hasattr(_crystallizer, "reap_stale_patterns")
                and isinstance(_turns, int)
                and _turns > 0
                and _turns % 50 == 0
            ):
                _reaped = _crystallizer.reap_stale_patterns()
                if _reaped.get("decayed"):
                    logger.info("🧊 结晶模式冷处理: 降温 %s 条", _reaped["decayed"])
        except Exception as _reap_error:
            logger.debug("结晶模式冷处理失败（不阻断）: %s", _reap_error)

        # 根因修复: MetaCognition 认知负荷模块此前零调用——每轮用真实轮次指标
        # （工具步数/错误率/耗时/记忆规模）更新认知状态；低负荷且到达轮次间隔时
        # 触发记忆巩固（认知负荷 → 睡眠整理 闭环；高负荷不整合是模块自身契约）
        try:
            from neurova.cognitive_layers.memory_layer.meta_cognition import get_meta_cognition

            agent_id = str(getattr(getattr(self._agent, "config", None), "agent_id", "default") or "default")
            meta = get_meta_cognition(agent_id)

            results = list(self._step_results)
            total_steps = len(results)
            failed_steps = sum(
                1 for r in results if getattr(getattr(r, "status", None), "value", "") == "failed"
            )
            tool_steps = sum(1 for r in results if "tool" in str(getattr(r, "step_name", "")))
            response_ms = sum(float(getattr(r, "duration_ms", 0.0) or 0.0) for r in results)

            memory_count = 0
            memory_manager = self._get_dependency("memory_manager")
            if memory_manager is not None and hasattr(memory_manager, "get_memory_count"):
                memory_count = memory_manager.get_memory_count()

            meta.update_state(
                active_tasks=tool_steps,
                memory_usage=min(1.0, memory_count / 5000.0),
                response_time_ms=response_ms,
                error_rate=(failed_steps / total_steps) if total_steps else 0.0,
                metadata={"turn_steps": total_steps},
            )

            turn_count = int(getattr(self._agent, "turn_count", 0) or 0)
            if turn_count > 0 and turn_count % 10 == 0 and meta.should_consolidate():
                idle_tracker = getattr(self._agent, "idle_tracker", None)
                trigger = getattr(idle_tracker, "trigger_consolidation", None)
                if trigger:
                    consolidation_result = trigger()
                    logger.info(
                        "🧠 低负荷窗口触发记忆巩固: %s",
                        "完成" if consolidation_result else "依赖缺失",
                    )

            # V3 自模型：反思门控触发（洞察编译器，全确定性零 LLM；教训落台账）
            if turn_count > 0 and turn_count % 10 == 0:
                try:
                    from neurova.cognitive_layers.meta_cognition_layer.self_model import (
                        get_self_model_engine,
                    )

                    engine = get_self_model_engine(agent_id)
                    if engine.should_reflect():
                        report = engine.reflect(trigger="periodic_turn")
                        if report.get("lessons"):
                            logger.info(
                                "🪞 自模型反思产出 %d 条洞察: %s",
                                len(report["lessons"]),
                                report.get("summary", "")[:80],
                            )
                except Exception as re_err:
                    logger.debug("自模型反思触发跳过: %s", re_err)
        except Exception as e:
            logger.debug("认知负荷监控跳过: %s", e)

        rsi = self._get_dependency("rsi_orchestrator")
        if not rsi:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="rsi_orchestrator not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return None

        try:
            # 工单 008：派发层不再把 should_continue()==False 当作"本进程内永不进化"。
            # 原实现在此直接 SKIPPED，而收敛结论只对其依据的那份证据有效 ——
            # 参数会漂、代码会变，永久跳过等于进化一次性终止。
            # 现在按 cadence 决定频率：run 每轮跑；backoff（已收敛 / 评测集度量失明）
            # 降频巡检 —— 度量失明尤其不能停，它意味着测量坏了，需要持续被暴露。
            from neurova.core.turn_context import get_turn_count as _turn_count

            cadence = rsi.iteration_cadence()
            turn = _turn_count()
            due = cadence.mode != "backoff" or turn % _RSI_BACKOFF_EVERY_TURNS == 0

            if due:
                # A-13: run_iteration 含 SQLite 读写/参数寻优（同步重活），
                # 直接在事件循环内调用会卡死所有并发请求——移到工作线程。
                # to_thread 原样透传返回值与异常，外层 try/except 语义不变。
                result = await asyncio.to_thread(rsi.run_iteration)
                # convergence 是 dict；历史写法 result.get("convergence", {}).get("status")
                # 在 convergence 非 dict 时会炸，统一走摘要模块的取值口径。
                from neurova.evolution.rsi.result_summary import (
                    convergence_status,
                    record_rsi_summary,
                )

                status = convergence_status(result)
                logger.info("RSI 迭代完成: %s", status)
                # 真接线（Issue #55 后续）：把这次迭代压成响应面摘要落库——
                # 本步骤在后台 task 里跑，结果赶不上本轮响应组装，故由
                # process() 取"最近一次已完成摘要"随 ctx.result["rsi"] 返回。
                try:
                    from neurova.core.turn_context import get_turn_count, get_turn_session_id

                    record_rsi_summary(
                        getattr(getattr(self._agt, "config", None), "agent_id", None),
                        get_turn_session_id() or getattr(self._agt, "session_id", None),
                        result,
                        turn=get_turn_count(),
                    )
                except Exception as _sum_err:  # noqa: BLE001 - 摘要落库失败不影响迭代本身
                    logger.debug("RSI 摘要记录跳过: %s", _sum_err)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"RSI iteration completed: {status}",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"convergence_status": status},
                    )
                )
                return result
            else:
                # SKIPPED 不是"不再进化"，是本轮不跑：必须说清依据哪个判据、什么读数
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message=(
                            f"RSI 降频巡检（判据 {cadence.basis}：{cadence.evidence}；"
                            f"每 {_RSI_BACKOFF_EVERY_TURNS} 轮跑一次，当前轮次 {turn} 不在窗口）"
                        ),
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"cadence": cadence.mode, "basis": cadence.basis,
                              "evidence": cadence.evidence, "turn": turn,
                              "backoff_every": _RSI_BACKOFF_EVERY_TURNS},
                    )
                )
        except Exception as e:
            logger.warning("Step 11 RSI 迭代失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

        return None

    async def _step_record_workflow_experience(
        self,
        user_input: str,
        reply: str,
        session_id: str,
    ):
        """Step 9.05: 记录工作流执行经验到记忆系统

        从 Neurflow 执行引擎获取最近的执行记录，将成功的工作流执行经验
        存储到记忆系统中，以便后续对话中检索和复用。
        """
        step_name = "record_workflow_experience"
        start_time = time.time()

        # 获取工作流执行器
        neurflow_executor = self._get_dependency("neurflow_executor")
        if not neurflow_executor:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="neurflow_executor not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        memory_manager = self._get_dependency("memory_manager")
        if not memory_manager:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="memory_manager not available",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            # 获取最近的执行记录（5分钟内）
            recent_executions = neurflow_executor.get_recent_executions(
                agent_id=getattr(self._agt.config, "agent_id", None), limit=5
            )

            if not recent_executions:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="No recent workflow executions found",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )
                return

            # 记录每个成功执行的工作流经验
            recorded_count = 0
            for execution in recent_executions:
                # 只记录成功的执行
                if execution.status.value != "completed":
                    continue

                # 构建经验内容
                workflow_id = execution.workflow_id
                duration = execution.duration or 0
                outputs_summary = str(execution.outputs)[:200] if execution.outputs else "无输出"

                # 提取节点执行信息
                node_count = len(execution.node_results)
                successful_nodes = sum(
                    1 for node_result in execution.node_results.values() if node_result.status == "success"
                )

                experience_content = (
                    f"工作流 {workflow_id} 执行成功完成。"
                    f"包含 {node_count} 个节点，成功执行 {successful_nodes} 个。"
                    f"执行耗时 {duration:.2f} 秒。"
                    f"输出: {outputs_summary}"
                )

                # 存储到记忆系统
                metadata = {
                    "workflow_id": workflow_id,
                    "execution_id": execution.id,
                    "duration": duration,
                    "node_count": node_count,
                    "successful_nodes": successful_nodes,
                    "session_id": session_id,
                    "source": "neurflow_execution",
                    "execution_started_at": execution.started_at,
                    "execution_finished_at": execution.finished_at,
                }

                memory_id = memory_manager.remember(
                    content=experience_content,
                    memory_type="workflow_experience",
                    metadata=metadata,
                )

                if memory_id:
                    recorded_count += 1
                    logger.debug("工作流经验已记录: %s -> %s", workflow_id, memory_id)

            if recorded_count > 0:
                logger.info("🔄 已记录 %s 个工作流执行经验", recorded_count)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Recorded {recorded_count} workflow execution experiences",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={
                            "recorded_count": recorded_count,
                            "total_executions": len(recent_executions),
                            "workflow_ids": [e.workflow_id for e in recent_executions],
                        },
                    )
                )
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="No successful workflow executions to record",
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                )

        except Exception as e:
            logger.warning("Step 9.05 工作流经验记录失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )

    async def _step_extract_conversation_rules(
        self,
        user_input: str,
        reply: str,
        session_id: str,
    ):
        """Step 9.96: 从对话提取规则并关联经验记忆

        1. 使用 LLM 提取对话中的因果/条件关系
        2. 注入 DependencyGraph
        3. 关联经验记忆
        4. 更新模式挖掘器
        """
        step_name = "extract_conversation_rules"
        start_time = time.time()

        # LLM 成本门控（治理遗留收口 2026-09-05）：本步骤每轮消耗一次 LLM 调用。
        # 管理面：治理设置 conversation_rules_enabled（设置页高级选项卡），
        # 优先级：env 显式设 0 强制关 > 治理设置值 > 默认关。
        import os as _os

        env_val = _os.environ.get("NEUROVA_CONVERSATION_RULES")
        if env_val == "0":
            # 运维后门：env 显式设 0 强制关（优先级最高）
            rules_enabled = False
        elif env_val == "1":
            rules_enabled = True
        else:
            try:
                from neurova.security.governance_settings import (
                    load_governance_settings,
                )

                rules_enabled = bool(
                    load_governance_settings().get("conversation_rules_enabled")
                )
            except Exception as e:  # noqa: BLE001 - 设置不可用维持默认关
                logger.debug("治理设置读取失败，规则提取维持默认关: %s", e)
                rules_enabled = False

        if not rules_enabled:
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="conversation rules disabled (LLM cost gate, default off)",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
            return

        try:
            # 获取依赖组件
            dependency_graph = self._get_dependency("dependency_graph")
            rule_extractor = self._get_dependency("rule_extractor")
            
            if not rule_extractor:
                # 创建规则提取器
                from neurova.cognitive_layers.memory_layer.conversation_rule_extractor import (
                    ConversationRuleExtractor,
                )
                llm_client = self._get_dependency("llm_client")
                if not llm_client:
                    self._step_results.append(
                        StepResult(
                            step_name=step_name,
                            status=StepStatus.SKIPPED,
                            message="llm_client not available",
                            duration_ms=(time.time() - start_time) * 1000,
                        )
                    )
                    return
                
                # Bug #8 fix: dependency_graph=None 时不能传给 ConversationRuleExtractor 构造器
                # 原代码无条件传 dependency_graph（可能为 None），导致下游 AttributeError/TypeError
                if dependency_graph is None:
                    self._step_results.append(
                        StepResult(
                            step_name=step_name,
                            status=StepStatus.SKIPPED,
                            message="dependency_graph not available, cannot create rule_extractor",
                            duration_ms=(time.time() - start_time) * 1000,
                        )
                    )
                    return
                
                rule_extractor = ConversationRuleExtractor(llm_client, dependency_graph)
            
            # 1. 提取对话规则
            rules = await rule_extractor.extract(user_input, reply, session_id)
            logger.info("从对话提取到 %d 个规则", len(rules))
            
            # 2. 关联经验记忆（这个对话用到了什么工具？）
            tools_used = self._agt._collect_tool_messages()
            tool_names = list(set(tm.get("tool_name", "unknown") for tm in tools_used))
            
            # 3. 更新经验记忆融合器
            fusion = self._get_dependency("experience_fusion")
            # 工单 002 同根因命中点：这里曾无条件写 `"success": True`，
            # 等于给融合器与知识图谱投确证成功票。无客观回执时不投（宁缺毋伪）。
            from neurova.agent.turn_state import resolve_tool_outcome

            turn_outcome = resolve_tool_outcome(tools_used)
            if fusion and tool_names and turn_outcome is None:
                logger.debug("本轮无工具结果回执，跳过经验融合写入（不投成功票）")
            elif fusion and tool_names:
                for tool_name in tool_names:
                    fusion.fuse(
                        tool_result={
                            "tool_name": tool_name,
                            "success": turn_outcome,
                            "problem_text": user_input[:100],
                        },
                        graph_context={
                            "related_entities": [r.source_entity for r in rules],
                            "causal_chains": [f"{r.source_entity}→{r.target_entity}" for r in rules],
                        },
                    )
            
            # 4. 更新模式挖掘器
            # 工单 013：同上，只记服务端票据的三态（本步骤的 `turn_outcome` 是给
            # 融合器的旁路证据，不得在这里升格成模式的客观成功票）。
            pattern_miner = self._get_dependency("pattern_miner")
            if pattern_miner and len(tool_names) > 1:
                from neurova.evolution.objective_evidence import resolve_ticket_evidence

                pattern_miner.add_sequence(
                    tool_names,
                    success=resolve_ticket_evidence(self._agent, tools_used).ticket)
            
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Extracted {len(rules)} rules, {len(tool_names)} tools",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={
                        "rules_count": len(rules),
                        "tools_used": tool_names,
                    },
                )
            )

        except Exception as e:
            logger.warning("Step 9.96 对话规则提取失败: %s", e)
            self._step_results.append(
                StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message=str(e),
                    duration_ms=(time.time() - start_time) * 1000,
                )
            )
