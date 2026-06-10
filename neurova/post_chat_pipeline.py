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

import time
import logging
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any, Set
from dataclasses import dataclass, field

try:
    from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionType
except ImportError:
    class ReflectionType(str, Enum):
        ERROR_ANALYSIS = "error_analysis"
        PROBLEM_SOLVING = "problem_solving"
        DECISION_MAKING = "decision_making"
        INTERACTION = "interaction"
        LEARNING = "learning"

logger = logging.getLogger(__name__)


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

    def __init__(self, agent_ref):
        self._agent = agent_ref
        self._step_results: List[StepResult] = []
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

    @property
    def _agt(self):
        return self._agent

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

        logger.info(
            "PostChatPipeline dependencies configured: "
            "conversation_buffer=%s, memory_manager=%s, tts_manager=%s, "
            "growth_analyzer=%s, growth_log_manager=%s, evolution=%s, "
            "neuHebb_manager=%s, tool_lifecycle=%s, pattern_miner=%s, "
            "genetic_engine=%s, tool_marketplace=%s, conflict_detector=%s, "
            "version_control=%s, proactive_question_manager=%s, rsi_orchestrator=%s",
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

    async def process(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool,
        enable_tts: bool,
        metadata: Dict[str, Any],
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
        # 清空步骤结果
        self._step_results.clear()
        
        # 步骤 6: 保存到 session 文件
        actual_session_id = await self._step_save_session(
            user_input, reply, session_id, save_memory, metadata
        )

        # 步骤 6.5: 保存对话记忆到数据库
        await self._step_save_memory(user_input, reply, actual_session_id)

        # 步骤 6.6: 更新记忆温度（批量衰减）
        self._step_update_memory_temperature()

        # 步骤 7: TTS 语音生成
        audio_path, audio_data = await self._step_generate_tts(
            reply, actual_session_id, enable_tts
        )

        # 步骤 8: 认知能力分析
        cognitive_score = await self._step_cognitive_analysis(user_input)

        # 步骤 8.5: 反思日志生成
        await self._step_reflection(user_input, reply)

        # 步骤 9: 经验记录
        await self._step_record_experience(user_input, reply, save_memory)

        # 步骤 9.1: Evocate 生成（从对话中提取结构化推理记忆）
        await self._step_evocate_generation(user_input, reply, actual_session_id)

        # 步骤 9.5-9.8: P0 后处理
        await self._step_p0_post_processing(save_memory)

        # 步骤 9.9: 记忆冲突检测
        await self._step_conflict_detection(user_input, reply)

        # 步骤 9.95: 记忆版本快照
        await self._step_version_snapshot(user_input)

        # 步骤 10: 主动提问决策
        proactive_question = await self._step_proactive_question(user_input, reply)

        # 步骤 11: RSI 迭代（递归自我改进）
        rsi_result = await self._step_rsi_iteration()
        
        # 记录步骤统计
        executed = sum(1 for r in self._step_results if r.status == StepStatus.EXECUTED)
        skipped = sum(1 for r in self._step_results if r.status == StepStatus.SKIPPED)
        failed = sum(1 for r in self._step_results if r.status == StepStatus.FAILED)
        degraded = sum(1 for r in self._step_results if r.status == StepStatus.DEGRADED)
        
        logger.info(
            "PostChatPipeline completed: executed=%d, skipped=%d, failed=%d, degraded=%d",
            executed, skipped, failed, degraded
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
            if hasattr(self._agt, '_update_memory_temperature'):
                self._agt._update_memory_temperature()
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="Memory temperature updated",
                    duration_ms=(time.time() - start_time) * 1000
                ))
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="Agent has no _update_memory_temperature method",
                    duration_ms=(time.time() - start_time) * 1000
                ))
        except Exception as e:
            logger.warning(f"记忆温度更新失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_save_session(
        self,
        user_input: str,
        reply: str,
        session_id: str,
        save_memory: bool,
        metadata: Dict[str, Any],
    ) -> str:
        """保存到 session 文件（备份机制）"""
        step_name = "save_session"
        start_time = time.time()
        result_session_id = session_id or ""

        if not save_memory:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="save_memory=False, skip session backup",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return result_session_id

        try:
            assistant_meta = {
                "reasoning_content": getattr(self._agt, "_current_reasoning", None),
                "tool_calls": self._agt._collect_tool_messages()
                if self._agt._collect_tool_messages()
                else None,
            }
            # 过滤 None 值
            assistant_meta = {k: v for k, v in assistant_meta.items() if v is not None}

            result_session_id = self._agt._save_to_session(
                user_input,
                reply,
                session_id,
                metadata,
                assistant_meta if assistant_meta else None,
            )
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Session saved: {result_session_id}",
                duration_ms=(time.time() - start_time) * 1000,
                data={"session_id": result_session_id}
            ))
        except Exception as e:
            logger.warning(f"Session备份失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

        return result_session_id

    async def _step_save_memory(
        self,
        user_input: str,
        reply: str,
        session_id: str,
    ):
        """保存对话记忆到记忆数据库"""
        step_name = "save_memory"
        start_time = time.time()
        
        # 获取依赖组件
        memory_manager = self._get_dependency("memory_manager")
        conversation_buffer = self._get_dependency("conversation_buffer")
        
        if not conversation_buffer and not memory_manager:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="No memory_manager or conversation_buffer available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return
        
        try:
            # 使用对话缓冲区
            if conversation_buffer:
                conversation_buffer.add_user_message(user_input, session_id=session_id or "default")
                conversation_buffer.add_agent_message(reply, session_id=session_id or "default")
                logger.debug("对话已添加到缓冲区")

            # 使用记忆管理器
            if memory_manager:
                # 保存用户消息记忆
                user_memory_id = memory_manager.remember(
                    content=f"用户: {user_input}",
                    memory_type="conversation",
                    metadata={"sender_type": "user", "session_id": session_id or "default"},
                )
                # 保存助手回复记忆
                agent_memory_id = memory_manager.remember(
                    content=f"助手: {reply}",
                    memory_type="conversation",
                    metadata={"sender_type": "agent", "session_id": session_id or "default"},
                )
                logger.debug("对话已直接写入记忆数据库")
                
                # 保存情感信息到记忆
                self._save_emotion_to_memory(memory_manager, user_input, user_memory_id)
            
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message="Memory saved successfully",
                duration_ms=(time.time() - start_time) * 1000,
                data={"user_memory_id": user_memory_id, "agent_memory_id": agent_memory_id}
            ))
        except Exception as e:
            logger.warning(f"对话记忆保存失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    def _save_emotion_to_memory(self, memory_manager, user_input: str, memory_id: str):
        """将情感信息保存到记忆"""
        emotion_module = getattr(memory_manager, "emotion_module", None)
        if not emotion_module:
            return
        
        try:
            # 分析用户输入的情感
            emotion_state = emotion_module.analyze_text_emotion(user_input)
            if emotion_state and emotion_state.primary_emotion.value != "neutral":
                emotion_module.set_emotion(memory_id, emotion_state)
                logger.debug(f"情感已保存到记忆 {memory_id}: {emotion_state.primary_emotion.value}")
        except Exception as e:
            logger.debug(f"情感保存失败: {e}")

    async def _step_generate_tts(
        self,
        reply: str,
        session_id: str,
        enable_tts: bool,
    ) -> tuple:
        """生成 TTS 语音"""
        step_name = "generate_tts"
        start_time = time.time()
        config = self._agt.config
        use_tts = enable_tts and getattr(config, "enable_tts", False)

        tts_manager = self._get_dependency("tts_manager")
        if not use_tts or not tts_manager:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="TTS not enabled or tts_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return None, None

        try:
            if not tts_manager.is_initialized:
                tts_manager.initialize()

            timestamp = int(time.time())
            audio_filename = f"tts_{session_id or 'default'}_{timestamp}.wav"
            audio_path = Path(config.attachment_dir) / audio_filename
            audio_path.parent.mkdir(parents=True, exist_ok=True)

            # TTSManager.synthesize() 只接受文本参数，返回音频字节数据
            audio_start_time = time.time()
            audio_data = await tts_manager.synthesize(reply)
            duration_ms = int((time.time() - audio_start_time) * 1000)
            
            # 将音频数据保存到文件
            if audio_data:
                with open(audio_path, "wb") as f:
                    f.write(audio_data)
                logger.info(f"TTS语音已生成: {audio_path}")
                
                # 记录TTS使用统计到语音记忆桥接器
                voice_memory_bridge = self._get_dependency("voice_memory_bridge")
                if voice_memory_bridge:
                    try:
                        tts_result = {
                            "text_length": len(reply),
                            "engine": getattr(tts_manager, "engine_name", "unknown"),
                            "voice": getattr(config, "tts_voice", "default"),
                            "duration_ms": duration_ms,
                            "success": True,
                            "audio_size_bytes": len(audio_data),
                        }
                        # 获取用户和Agent ID
                        user_id = getattr(config, "user_id", "default")
                        agent_id = getattr(config, "agent_id", "default")
                        
                        await voice_memory_bridge.record_tts_usage(
                            tts_result=tts_result,
                            user_id=user_id,
                            agent_id=agent_id,
                        )
                        logger.debug("TTS使用统计已记录到语音记忆桥接器")
                    except Exception as e:
                        logger.warning(f"记录TTS使用统计失败: {e}")
                
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"TTS generated: {audio_path}",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"audio_path": str(audio_path), "audio_size": len(audio_data)}
                ))
                return str(audio_path), audio_data
            else:
                logger.warning("TTS合成返回空数据")
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message="TTS synthesis returned empty data",
                    duration_ms=(time.time() - start_time) * 1000
                ))
                return None, None
        except Exception as e:
            logger.warning(f"TTS语音生成失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))
            return None, None

    async def _step_cognitive_analysis(self, user_input: str) -> float:
        """认知能力分析"""
        step_name = "cognitive_analysis"
        start_time = time.time()
        
        growth_analyzer = self._get_dependency("growth_analyzer")
        if not growth_analyzer:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="growth_analyzer not available, using default score 0.75",
                duration_ms=(time.time() - start_time) * 1000,
                data={"score": 0.75}
            ))
            return 0.75

        try:
            w = user_input.replace("？", "").replace("?", "")
            if len(w) > 0:
                concepts = w.split()
                growth_analyzer.record_learning(
                    concepts=concepts,
                    context="conversation",
                )
                logger.info("🧠 认知能力分析完成")
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="Cognitive analysis completed",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"score": 0.75, "concepts": concepts}
                ))
                return 0.75
        except Exception as e:
            logger.warning(f"认知能力分析失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

        return 0.75

    # ============================================================
    # 反思相关常量和方法
    # ============================================================

    REFLECTION_CONFUSION_KEYWORDS = [
        "不明白", "不对", "错了", "不是这样", "搞错了", "再想想", "重新",
    ]
    REFLECTION_UNCERTAINTY_KEYWORDS = [
        "不确定", "可能", "也许", "大概", "或许", "估计", "不敢肯定",
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
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="growth_log_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        should_reflect = self._should_reflect(user_input, reply)
        if not should_reflect:
            logger.debug("反思条件未满足，跳过 Step 8.5")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="Reflection conditions not met",
                duration_ms=(time.time() - start_time) * 1000
            ))
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
            if entry:
                logger.info(
                    f"🧠 反思日志已生成: {entry.id} (类型: {reflection_type.value}, 触发: {context['trigger']})"
                )
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Reflection log generated: {entry.id}",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"reflection_id": entry.id, "type": reflection_type.value}
                ))
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.FAILED,
                    message="Failed to generate reflection log",
                    duration_ms=(time.time() - start_time) * 1000
                ))
        except Exception as e:
            logger.warning(f"Step 8.5 反思日志生成失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

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
        turn_count = getattr(self._agt, "_turn_count", 0)
        if turn_count > 0 and turn_count % self.REFLECTION_TURN_INTERVAL == 0:
            return True

        return False

    def _infer_reflection_type(self, user_input: str, reply: str) -> 'ReflectionType':
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

        turn_count = getattr(self._agt, "_turn_count", 0)
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
        
        evolution = self._get_dependency("evolution")
        if not evolution:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="evolution not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            tool_messages = self._agt._collect_tool_messages()
            tools_used = list(set(
                tm.get("tool_name", "unknown") for tm in tool_messages
            ))

            # 记录经验到进化系统（只调用一次）
            if hasattr(evolution, "on_experience_recorded"):
                evolution.on_experience_recorded(
                    text=f"用户: {user_input}\n助手: {reply}",
                    task=user_input,
                    tools=tools_used,
                    success=len(tool_messages) > 0,
                )
                logger.info(f"📚 对话经验已记录 (工具: {tools_used})")
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Experience recorded with {len(tools_used)} tools",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"tools_used": tools_used}
                ))
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="evolution has no on_experience_recorded method",
                    duration_ms=(time.time() - start_time) * 1000
                ))
        except Exception as e:
            logger.warning(f"经验记录失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

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
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="neuHebb_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
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
                    len(hebbs), session_id,
                )
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Generated {len(hebbs)} NeurovaHebb",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"hebbs_count": len(hebbs), "session_id": session_id}
                ))
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="No NeurovaHebb generated",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"hebbs_count": 0}
                ))
        except Exception as e:
            logger.warning(f"Evocate 生成失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_p0_post_processing(self, save_memory: bool):
        """P0: 执行所有 P0 接线模块的后处理"""
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
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="tool_lifecycle not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            lifecycle_report = tool_lifecycle.evaluate()
            evolution = self._get_dependency("evolution")

            if "degraded" in lifecycle_report or "archived" in lifecycle_report:
                logger.info(
                    f"🔄 工具生命周期评估: {lifecycle_report}"
                )

            # 对降级/归档的工具应用权重衰减
            if evolution and hasattr(evolution, "_tool_weights"):
                decay = lifecycle_report.get("decay", {})
                if decay:
                    for tool_name, factor in decay.items():
                        if tool_name in evolution._tool_weights:
                            evolution._tool_weights[tool_name] *= factor
                    logger.debug(f"📉 工具权重衰减: {len(decay)} 个工具")
            
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Lifecycle evaluation completed",
                duration_ms=(time.time() - start_time) * 1000,
                data={"report": lifecycle_report}
            ))
        except Exception as e:
            logger.warning(f"工具生命周期评估失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_pattern_mining(self):
        """9.6: PatternMiner 序列收集与挖掘"""
        step_name = "pattern_mining"
        start_time = time.time()
        
        evolution = self._get_dependency("evolution")
        pattern_miner = getattr(evolution, "pattern_miner", None) if evolution else None
        if not pattern_miner:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="pattern_miner not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            tool_messages = self._agt._collect_tool_messages()
            if not tool_messages:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="No tool messages to process",
                    duration_ms=(time.time() - start_time) * 1000
                ))
                return

            # 构建工具调用序列
            sequence = []
            for tm in tool_messages:
                sequence.append(tm.get("tool_name", "unknown"))

            # 添加序列并挖掘
            pattern_miner.add_sequence(sequence)
            patterns = pattern_miner.mine()

            if patterns:
                logger.info(f"⛏️ PatternMiner 发现 {len(patterns)} 个频繁模式")

            # 将模式反馈给 skill_packer
            skill_packer = self._get_dependency("skill_packer")
            if skill_packer and patterns:
                templates = pattern_miner.to_skill_template_list()
                for tmpl in templates:
                    skill_packer.observe(tools=tmpl["tools"], support=tmpl["support"], auto_registered=True)
            
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Pattern mining completed: {len(patterns) if patterns else 0} patterns found",
                duration_ms=(time.time() - start_time) * 1000,
                data={"patterns_count": len(patterns) if patterns else 0, "sequence_length": len(sequence)}
            ))
        except Exception as e:
            logger.warning(f"PatternMiner 序列收集失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_genetic_evolution(self):
        """9.7: ToolGeneticEngine 种子种群并进化"""
        step_name = "genetic_evolution"
        start_time = time.time()
        
        evolution = self._get_dependency("evolution")
        if not evolution:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="evolution not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        genetic_engine = getattr(evolution, "genetic_engine", None)
        pattern_miner = getattr(evolution, "pattern_miner", None)
        if not genetic_engine or not pattern_miner:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="genetic_engine or pattern_miner not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            if pattern_miner.sequence_count == 0:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="No sequences to evolve",
                    duration_ms=(time.time() - start_time) * 1000
                ))
                return

            top_patterns = pattern_miner.get_top_patterns()

            # 从模式构建基因型种子
            from neurova.evolution.genetic_engine import ToolGenotype
            for pattern in top_patterns:
                genotype = ToolGenotype(
                    tool_sequence=pattern.tools,
                    success_rate=0.5,
                )
                genetic_engine.add_to_population(genotype)

            # 执行进化
            new_gen = genetic_engine.evolve()
            logger.info(f"🧬 ToolGeneticEngine 进化完成: 种群={len(genetic_engine.population)}, 新个体={len(new_gen)}")

            # 将进化结果反馈到工具权重
            for genotype in new_gen:
                for tool_name in genotype.tools:
                    if tool_name in evolution._registered_tools:
                        # 高适应度个体的工具应获得权重提升
                        if genotype.fitness > 0.5:
                            evolution.tool_weights.update_weight(tool_name, True)
            
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Genetic evolution completed: {len(new_gen)} new individuals",
                duration_ms=(time.time() - start_time) * 1000,
                data={"population_size": len(genetic_engine.population), "new_individuals": len(new_gen)}
            ))
        except Exception as e:
            logger.warning(f"ToolGeneticEngine 进化失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_marketplace_publish(self):
        """9.8: ToolMarketplace 工具发布"""
        step_name = "marketplace_publish"
        start_time = time.time()
        
        marketplace = self._get_dependency("tool_marketplace")
        if not marketplace:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="tool_marketplace not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
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
                if skill_registry:
                    skill = skill_registry.get_skill(tool_name)

                # 构建市场工具
                try:
                    from neurova.tool_layers import MarketplaceTool
                    mkt_tool = MarketplaceTool(
                        name=tool_name,
                        description=skill.description if skill else f"auto-registered tool: {tool_name}",
                        schema=skill.to_schema() if skill and hasattr(skill, "to_schema") else {},
                        agent_id=self._agt.config.agent_id,
                    )
                    marketplace.add_tool(mkt_tool)
                    logger.info(f"🏪 工具已发布到市场: {tool_name}")
                    published_tools.append(tool_name)
                except (ImportError, Exception) as e:
                    logger.warning(f"ToolMarketplace 发布失败: {e}")
            
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Published {len(published_tools)} tools to marketplace",
                duration_ms=(time.time() - start_time) * 1000,
                data={"published_tools": published_tools}
            ))
        except Exception as e:
            logger.warning(f"ToolMarketplace 发布失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_conflict_detection(self, user_input: str, reply: str):
        """Step 9.9: 新记忆写入后自动检测冲突"""
        step_name = "conflict_detection"
        start_time = time.time()
        
        conflict_detector = self._get_dependency("conflict_detector")
        if not conflict_detector:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="conflict_detector not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        memory_manager = self._get_dependency("memory_manager")
        if not memory_manager:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="memory_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            recent_memories = memory_manager.recall(user_input, limit=5)
            new_memory_content = f"用户: {user_input}\n助手: {reply}"

            result = conflict_detector.check_conflict(
                existing_memories=recent_memories,
                new_memory=new_memory_content,
            )

            if result and result.has_conflict:
                logger.warning(
                    f"⚠️ 检测到 {len(result.conflicts)} 处记忆冲突 (置信度: {result.confidence:.2f}): {result.summary}"
                )
                # 标记为待处理
                result.status = "pending"
                for conflict in result.conflicts:
                    logger.info(
                        f"  冲突: {conflict.conflict_type.value} ({conflict.conflict_level}) - {conflict.description}"
                    )
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"Detected {len(result.conflicts)} conflicts",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"conflicts_count": len(result.conflicts), "confidence": result.confidence}
                ))
            else:
                logger.debug("记忆冲突检测通过，无冲突")
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message="No conflicts detected",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"conflicts_count": 0}
                ))
        except Exception as e:
            logger.warning(f"Step 9.9 记忆冲突检测失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_version_snapshot(self, user_input: str):
        """Step 9.95: 为相关记忆创建版本快照（确保可回滚）"""
        step_name = "version_snapshot"
        start_time = time.time()
        
        version_control = self._get_dependency("version_control")
        if not version_control:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="version_control not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        memory_manager = self._get_dependency("memory_manager")
        if not memory_manager:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="memory_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return

        try:
            related_memories = memory_manager.recall(user_input, limit=3)
            snapshot_count = 0

            for mem in related_memories:
                memory_id = mem.get("id", "") if isinstance(mem, dict) else getattr(mem, "id", "")
                if memory_id:
                    version_control.create_snapshot(
                        memory_id=memory_id,
                        source="pre_conversation_backup",
                        triggered_by="post_chat_pipeline",
                    )
                    snapshot_count += 1

            if snapshot_count > 0:
                logger.debug(f"📸 已为 {snapshot_count} 条相关记忆创建版本快照")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.EXECUTED,
                message=f"Created {snapshot_count} snapshots",
                duration_ms=(time.time() - start_time) * 1000,
                data={"snapshot_count": snapshot_count}
            ))
        except Exception as e:
            logger.warning(f"Step 9.95 记忆版本快照失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

    async def _step_proactive_question(self, user_input: str, reply: str) -> Optional[str]:
        """Step 10: 分析对话后决定是否主动提问

        Returns:
            主动提问内容（如果没有则返回 None）
        """
        step_name = "proactive_question"
        start_time = time.time()
        
        proactive_manager = self._get_dependency("proactive_question_manager")
        if not proactive_manager:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="proactive_question_manager not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return None

        try:
            context = f"用户: {user_input}\n助手: {reply}"
            should_ask, reason = proactive_manager.should_ask_question(context)

            if should_ask:
                if hasattr(proactive_manager, "generate_question"):
                    question = proactive_manager.generate_question(context)
                    if question:
                        logger.info(f"🤔 主动提问: {question} (原因: {reason})")
                        self._step_results.append(StepResult(
                            step_name=step_name,
                            status=StepStatus.EXECUTED,
                            message=f"Proactive question generated: {question[:50]}...",
                            duration_ms=(time.time() - start_time) * 1000,
                            data={"question": question, "reason": reason}
                        ))
                        return question
                    else:
                        logger.debug(f"主动提问条件满足但未生成问题: {reason}")
                        self._step_results.append(StepResult(
                            step_name=step_name,
                            status=StepStatus.SKIPPED,
                            message=f"Should ask but no question generated: {reason}",
                            duration_ms=(time.time() - start_time) * 1000
                        ))
                else:
                    self._step_results.append(StepResult(
                        step_name=step_name,
                        status=StepStatus.SKIPPED,
                        message="proactive_manager has no generate_question method",
                        duration_ms=(time.time() - start_time) * 1000
                    ))
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message=f"Proactive question conditions not met: {reason}",
                    duration_ms=(time.time() - start_time) * 1000
                ))
        except Exception as e:
            logger.warning(f"Step 10 主动提问决策失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

        return None

    async def _step_rsi_iteration(self) -> Optional[Dict[str, Any]]:
        """Step 11: RSI 迭代（递归自我改进）

        如果 RSI 编排器可用且应该继续迭代，执行一次 RSI 迭代。

        Returns:
            RSI 迭代结果（如果执行了），否则 None
        """
        step_name = "rsi_iteration"
        start_time = time.time()
        
        rsi = self._get_dependency("rsi_orchestrator")
        if not rsi:
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.SKIPPED,
                message="rsi_orchestrator not available",
                duration_ms=(time.time() - start_time) * 1000
            ))
            return None

        try:
            if rsi.should_continue():
                result = rsi.run_iteration()
                logger.info(f"RSI 迭代完成: {result.get('convergence', {}).get('status', 'unknown')}")
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.EXECUTED,
                    message=f"RSI iteration completed: {result.get('convergence', {}).get('status', 'unknown')}",
                    duration_ms=(time.time() - start_time) * 1000,
                    data={"convergence_status": result.get('convergence', {}).get('status')}
                ))
                return result
            else:
                self._step_results.append(StepResult(
                    step_name=step_name,
                    status=StepStatus.SKIPPED,
                    message="RSI should_continue returned False",
                    duration_ms=(time.time() - start_time) * 1000
                ))
        except Exception as e:
            logger.warning(f"Step 11 RSI 迭代失败: {e}")
            self._step_results.append(StepResult(
                step_name=step_name,
                status=StepStatus.FAILED,
                message=str(e),
                duration_ms=(time.time() - start_time) * 1000
            ))

        return None
