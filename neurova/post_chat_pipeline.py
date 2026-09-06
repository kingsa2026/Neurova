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

设计原则：
- 依赖注入：通过 agent_ref 访问 Agent 实例
- 异步友好：核心方法为 async
- 可独立测试
"""

from neurova.core.logger import get_logger
from neurova.cognitive_layers.growth_layer.analyzer import GrowthDimension
import asyncio
import contextvars
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

    @property
    def _agt(self):
        return self._agent

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
    _PROGRAMMING_ERRORS = (
        TypeError,
        AttributeError,
        NameError,
        ImportError,
        SyntaxError,
        IndentationError,
    )

    async def _safe_step(self, step_name: str, coro, default=None):
        """P-1: 安全执行单个步骤,异常只记录不传播

        P0-C2 修复：编程错误（TypeError/AttributeError/NameError/ImportError/SyntaxError）
        会 re-raise，让真实 bug 暴露给调用方；运营错误（OSError/ValueError/
        RuntimeError 等）仍按原逻辑降级为 default 值。
        """
        try:
            return await coro
        except self._PROGRAMMING_ERRORS:
            # P0-C2: 编程错误必须 re-raise，不能被吞没
            logger.error(
                "Step '%s' raised a programming error (re-raising, not degrading)",
                step_name,
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error("Step '%s' failed: %s", step_name, e, exc_info=True)
            self._step_results.append(
                StepResult(step_name=step_name, status=StepStatus.FAILED, message=str(e))
            )
            return default

    def _safe_step_sync(self, step_name: str, func, default=None):
        """P-1: 安全执行同步步骤,异常只记录不传播

        P0-C2 修复：编程错误（TypeError/AttributeError/NameError/ImportError/SyntaxError）
        会 re-raise，让真实 bug 暴露给调用方；运营错误仍按原逻辑降级为 default 值。
        """
        try:
            return func()
        except self._PROGRAMMING_ERRORS:
            # P0-C2: 编程错误必须 re-raise，不能被吞没
            logger.error(
                "Step '%s' raised a programming error (re-raising, not degrading)",
                step_name,
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.error("Step '%s' failed: %s", step_name, e, exc_info=True)
            self._step_results.append(
                StepResult(step_name=step_name, status=StepStatus.FAILED, message=str(e))
            )
            return default

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
            "rsi_result": Optional[Dict],
            "step_results": List[StepResult],
        }
        """
        # Bug #6 fix: 每次调用创建新的步骤结果列表，通过 contextvar 隔离并发调用
        # 原 self._step_results.clear() 会修改共享列表，并发请求互相覆盖
        self._step_results = []

        # P-1: 每个步骤用 _safe_step 包裹,异常只记录不传播
        # 步骤 6: 保存到 session 文件
        # Bug #4 fix: save_session 失败时回退到原始 session_id（而非 session_id or ""）
        # 避免 None 袝转为空字符串，导致记忆存到 "default" session
        actual_session_id = await self._safe_step(
            "save_session",
            self._step_save_session(user_input, reply, session_id, save_memory, metadata, writer_claim),
            default=session_id,
        )

        # 步骤 6.5: 保存对话记忆到数据库
        await self._safe_step("save_memory", self._step_save_memory(user_input, reply, actual_session_id, save_memory))

        # 步骤 6.6: 更新记忆温度（批量衰减）
        # 性能修复(2026-08-28): run_decay_cycle 全量遍历海量记忆 + SQLite 持久化是同步阻塞操作，
        # 直接在事件循环执行会导致 HTTP 对话请求超时/无响应。
        # 通过 asyncio.to_thread 移到工作线程，避免卡死事件循环。
        await asyncio.to_thread(
            self._safe_step_sync, "update_memory_temperature", self._step_update_memory_temperature
        )

        # 步骤 7: TTS 语音生成
        tts_result = await self._safe_step(
            "generate_tts",
            self._step_generate_tts(reply, actual_session_id, enable_tts),
            default=(None, None),
        )
        audio_path, audio_data = tts_result if tts_result else (None, None)

        # 步骤 8: 认知能力分析
        cognitive_score = await self._safe_step(
            "cognitive_analysis", self._step_cognitive_analysis(user_input), default=0.0
        )

        # 步骤 8.5: 反思日志生成
        await self._safe_step("reflection", self._step_reflection(user_input, reply))

        # 步骤 9: 经验记录
        await self._safe_step("record_experience", self._step_record_experience(user_input, reply, save_memory))

        # 步骤 9.05: 记录工作流执行经验
        await self._safe_step(
            "record_workflow_experience",
            self._step_record_workflow_experience(user_input, reply, actual_session_id),
        )

        # 步骤 9.1: Evocate 生成
        await self._safe_step(
            "evocate_generation", self._step_evocate_generation(user_input, reply, actual_session_id)
        )

        # 步骤 9.5-9.8: P0 后处理
        await self._safe_step("p0_post_processing", self._step_p0_post_processing(save_memory))

        # 步骤 9.9: 记忆冲突检测
        await self._safe_step("conflict_detection", self._step_conflict_detection(user_input, reply))

        # 步骤 9.95: 记忆版本快照
        await self._safe_step("version_snapshot", self._step_version_snapshot(user_input))

        # 步骤 9.96: 从对话提取规则并关联经验记忆
        await self._safe_step(
            "extract_conversation_rules",
            self._step_extract_conversation_rules(user_input, reply, actual_session_id),
        )

        # 步骤 10: 主动提问决策
        proactive_question = await self._safe_step(
            "proactive_question", self._step_proactive_question(user_input, reply), default=None
        )

        # 步骤 11: RSI 迭代
        rsi_result = await self._safe_step("rsi_iteration", self._step_rsi_iteration(), default=None)

        # 记录步骤统计
        executed = sum(1 for r in self._step_results if r.status == StepStatus.EXECUTED)
        skipped = sum(1 for r in self._step_results if r.status == StepStatus.SKIPPED)
        failed = sum(1 for r in self._step_results if r.status == StepStatus.FAILED)
        degraded = sum(1 for r in self._step_results if r.status == StepStatus.DEGRADED)

        logger.info(
            "PostChatPipeline completed: executed=%d, skipped=%d, failed=%d, degraded=%d",
            executed,
            skipped,
            failed,
            degraded,
        )

        return {
            "actual_session_id": actual_session_id,
            "audio_path": audio_path,
            "audio_data": audio_data,
            "cognitive_score": cognitive_score,
            "proactive_question": proactive_question,
            "rsi_result": rsi_result,
        }

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

    async def _step_save_memory(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool = False,
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
                # 保存用户消息记忆
                user_memory_id = memory_manager.remember(
                    content=f"用户: {user_input}",
                    memory_type="episodic",
                    metadata={"sender_type": "user", "session_id": session_id or "default"},
                    origin="owner",
                )
                # 保存助手回复记忆
                agent_memory_id = memory_manager.remember(
                    content=f"助手: {reply}",
                    memory_type="episodic",
                    metadata={"sender_type": "agent", "session_id": session_id or "default"},
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
            content = f"用户输入: {user_input[:200]}\nAgent 回复: {reply[:200]}"
            context = {
                "trigger": self._get_reflection_trigger_reason(user_input, reply),
                "source": "post_chat",
                "user_input_length": len(user_input),
                "reply_length": len(reply),
            }
            insights = []
            action_items = []
            confidence = 0.5

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
            is_confusion = any(kw in user_input.lower() for kw in self.REFLECTION_CONFUSION_KEYWORDS)
            is_uncertain = any(kw in reply.lower() for kw in self.REFLECTION_UNCERTAINTY_KEYWORDS)
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
                # P-5: success 基于工具实际成败,而非"是否调用了工具"
                tool_success = any(tm.get("success", True) for tm in tool_messages) if tool_messages else True
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
                logger.info("📚 对话经验已记录 (工具: %s)", tools_used)

                # EKB 写入闭环：同步沉淀到经验知识库（注入侧
                # context/injector._build_experience_context 的数据源）。
                # 此前 EKB 只读不写，"相关经验"注入永远查不到对话沉淀。
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
                    ekb.add_experience_record(
                        skill_name=skill_tag,
                        exp=ExperienceRecord(
                            skill_name=skill_tag,
                            context={"user_input": user_input},
                            result={"reply_excerpt": reply[:200]},
                            success=tool_success,
                            feedback=user_input[:100],
                        ),
                        agent_id=str(getattr(self._agent, "agent_id", "") or "") or None,
                        session_id=str(getattr(self._agent, "session_id", "") or "") or None,
                    )
                except Exception as ekb_error:  # noqa: BLE001 - 沉淀失败不阻断主流程
                    logger.debug("经验知识库写入失败（不阻断）: %s", ekb_error)
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Experience recorded with {len(tools_used)} tools",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"tools_used": tools_used},
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
            #         evolution._tool_weights[tool_name].adaptive_multiplier *= factor
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
            pattern_miner.add_sequence(sequence)
            patterns = pattern_miner.mine()

            if patterns:
                logger.info("⛏️ PatternMiner 发现 %s 个频繁模式", len(patterns))

            # 将模式反馈给 skill_packer
            skill_packer = self._get_dependency("skill_packer")
            if skill_packer and patterns:
                templates = pattern_miner.to_skill_template_list()
                for tmpl in templates:
                    # 修复 P0-6：observe 签名是 (tool_sequence, context, success, duration, metadata)
                    # 原错误签名 observe(tools=, support=, auto_registered=) 会抛 TypeError 被外层 except 吞没
                    skill_packer.observe(
                        tool_sequence=tmpl["tools"],
                        context="自动挖掘模式",
                        success=True,
                        duration=0.0,
                        metadata={"support": tmpl.get("support", 0), "auto_registered": True},
                    )

                # 修复 P0-1：将封装的技能注册到 SkillRegistry
                # 死实例修复（闭环审计 2026-09-04）：原代码 `SkillRegistry()` 新建
                # 一次性对象注册即丢弃，运行时 LLM 永远看不到 pattern 封装技能；
                # 必须注册进 agent 的真实 registry（与 genetic 路径对齐）。
                # registry 不可用时传 None：packer 内部 register 失败会跳过，
                # SkillService 持久化副作用保留（冷启动经 restore 恢复）。
                try:
                    skill_registry = getattr(self._agt, "_skill_registry", None)
                    if hasattr(skill_packer, "register_to_skill_registry"):
                        # s3 P0 #2: 同时持久化到 SkillService, 使前端 GET /private 可见
                        skill_service = None
                        try:
                            from neurova.skills.skill_service import SkillService

                            agent_id = getattr(self._agt.config, "agent_id", "default")
                            skill_service = SkillService(agent_id=agent_id)
                        except Exception as svc_err:
                            logger.warning("创建 SkillService 失败, 自动技能仅写 registry: %s", svc_err)

                        registered = skill_packer.register_to_skill_registry(
                            skill_registry, skill_service=skill_service
                        )
                        if registered > 0:
                            logger.info("📋 自动注册 %s 个技能到 SkillRegistry (并持久化到 SkillService)", registered)
                except Exception as reg_err:
                    logger.warning("自动技能注册失败: %s", reg_err)

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

            for pattern in top_patterns:
                # 用真实成功率替换硬编码 0.5：
                # 否则 fitness 恒 ≤ 0.5×1 + 0 = 0.5，永远达不到注册阈值 0.8，
                # 遗传进化产物永远无法注册为可复用技能（闭环断裂根因之一）
                if isinstance(pattern, dict):
                    seq = pattern.get("tools") or []
                    p_success = pattern.get("success_rate") or 0.5
                else:
                    seq = getattr(pattern, "tools", [])
                    p_success = getattr(pattern, "success_rate", None) or 0.5
                genotype = ToolGenotype(
                    tool_sequence=seq,
                    success_rate=float(p_success),
                )
                genetic_engine.add_to_population(genotype)

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
        """Step 9.9: 新记忆写入后自动检测冲突"""
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
            new_memory_content = f"用户: {user_input}\n助手: {reply}"

            # P2-9 修复: 真实 API 是
            # detect_conflict(new_memory: Memory, existing_memories: List[Memory]) -> List[Dict]。
            # 原实现调用不存在的 check_conflict()，并假设返回值有
            # has_conflict/conflicts/confidence/summary 结构 —— 依赖一旦注入必然
            # AttributeError 被 except 吞掉，冲突检测步骤恒 FAILED（从未真正运行）。
            from neurova.cognitive_layers.memory_layer.models import Memory

            existing_memories = [
                Memory(id=str(m.get("id", "")), content=str(m.get("content", "")))
                for m in recent_memories
                if isinstance(m, dict) and m.get("content")
            ]
            new_memory = Memory(id="pending_new_memory", content=new_memory_content)

            conflicts = conflict_detector.detect_conflict(new_memory, existing_memories)

            if conflicts:
                logger.warning("⚠️ 检测到 %s 处记忆冲突", len(conflicts))
                for conflict in conflicts:
                    logger.info(
                        "  冲突: %s (相似度=%.2f, 矛盾分=%.2f) - %s",
                        conflict.get("type"),
                        conflict.get("similarity", 0.0),
                        conflict.get("contradiction_score", 0.0),
                        conflict.get("description"),
                    )
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"Detected {len(conflicts)} conflicts",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"conflicts_count": len(conflicts), "conflicts": conflicts},
                    )
                )
            else:
                logger.debug("记忆冲突检测通过，无冲突")
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message="No conflicts detected",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"conflicts_count": 0},
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

    async def _step_rsi_iteration(self) -> Optional[Dict[str, Any]]:
        """Step 11: RSI 迭代（递归自我改进）

        如果 RSI 编排器可用且应该继续迭代，执行一次 RSI 迭代。

        Returns:
            RSI 迭代结果（如果执行了），否则 None
        """
        step_name = "rsi_iteration"
        start_time = time.time()

        # 根因修复: AutoSkillImprover 此前零调用——每轮批量扫描技能使用数据，
        # 对失败率超阈值的技能提出改进提案，并沉淀为反思日志回流上下文。
        # 断点 #3 修复：提案先尝试 apply_improvement 回写技能本体（保守语义：
        # 仅追加 config.improvements 记录+版本递增，不改工具序列），已应用的
        # 提案不再重复刷反思日志；未应用的（registry 不可用等）保持原提案日志。
        try:
            from neurova.evolution.skill_improver import get_skill_improver
            from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
                ReflectionType as _RealReflectionType,
            )

            improver = get_skill_improver()
            proposals = improver.propose_pending_improvements()
            growth_log_manager = self._get_dependency("growth_log_manager")
            skill_registry = getattr(self._agt, "_skill_registry", None)
            # 改进落盘最后一米（复审残余点 C）：SkillService 传给 apply_improvement，
            # 应用后 config+version 同步磁盘 manifest——否则改进重启即失
            skill_service = None
            try:
                from neurova.skills.skill_service import SkillService

                agent_id = getattr(self._agt.config, "agent_id", "default")
                skill_service = SkillService(agent_id=agent_id)
            except Exception as svc_err:
                logger.debug("创建 SkillService 失败, 改进仅内存态: %s", svc_err)
            for proposal in proposals[:3]:
                applied = False
                if skill_registry is not None:
                    applied = improver.apply_improvement(
                        proposal, skill_registry, skill_service=skill_service
                    )
                if applied:
                    logger.info(
                        "🔧 技能改进已应用: %s (%s)", proposal.skill_id, proposal.description or ""
                    )
                    continue
                logger.info("🔧 技能改进提案: %s - %s", proposal.skill_id, (proposal.description or "")[:50])
                if growth_log_manager:
                    try:
                        await growth_log_manager.generate_log(
                            type=_RealReflectionType.IMPROVEMENT,
                            title=f"技能改进提案: {proposal.skill_id}",
                            content=proposal.description or proposal.reason,
                            insights=[proposal.reason] if proposal.reason else [],
                            confidence=min(1.0, max(0.0, float(proposal.expected_impact or 0.5))),
                        )
                    except Exception as pe:
                        logger.debug("改进提案写入反思日志失败: %s", pe)
        except Exception as e:
            logger.debug("技能改进提案扫描跳过: %s", e)

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
            if rsi.should_continue():
                result = rsi.run_iteration()
                logger.info("RSI 迭代完成: %s", result.get('convergence', {}).get('status', 'unknown'))
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.EXECUTED,
                        message=f"RSI iteration completed: {result.get('convergence', {}).get('status', 'unknown')}",
                        duration_ms=(time.time() - start_time) * 1000,
                        data={"convergence_status": result.get("convergence", {}).get("status")},
                    )
                )
                return result
            else:
                self._step_results.append(
                    StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="RSI should_continue returned False",
                        duration_ms=(time.time() - start_time) * 1000,
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
            if fusion and tool_names:
                for tool_name in tool_names:
                    fusion.fuse(
                        tool_result={
                            "tool_name": tool_name,
                            "success": True,
                            "problem_text": user_input[:100],
                        },
                        graph_context={
                            "related_entities": [r.source_entity for r in rules],
                            "causal_chains": [f"{r.source_entity}→{r.target_entity}" for r in rules],
                        },
                    )
            
            # 4. 更新模式挖掘器
            pattern_miner = self._get_dependency("pattern_miner")
            if pattern_miner and len(tool_names) > 1:
                pattern_miner.add_sequence(tool_names)
            
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
