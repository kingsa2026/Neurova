"""
Neurova Small-Brain Triage Gate
轻量级 LLM 分类器，过滤无意义的 agent-to-agent 对话

"""

import json
import hashlib
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import time

from neurova.core.logger import get_logger
from neurova.llm.interfaces.provider_interface import (
    ProviderConfig,
    Message,
    CallResult,
    ProviderType,
)
from neurova.llm.registry.provider_registry import get_provider_registry

logger = get_logger(__name__)


class TriageGateError(RuntimeError):
    """分诊门不可用/输入不可判定。

    P1-10 纪律：无历史、凭据缺失、模型输出不可解析等基础设施性失败一律
    以本异常诚实上抛，不再吞成 actionable=True 无凭据放行（fail-open）。
    """


@dataclass
class TriageResult:
    """Triage gate result"""
    actionable: bool
    reason: str
    confidence: float = 0.0
    conversation_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionable": self.actionable,
            "reason": self.reason,
            "confidence": self.confidence,
            "conversation_hash": self.conversation_hash,
        }

class SmallBrainTriageGate:
    """
    Small-brain triage gate using cheap model

    PRINCIPLES:
    - A human involved OR waiting → ALWAYS actionable
    - Pure agent-to-agent chatter WITHOUT open work → NOT actionable
    - When unsure → actionable=true (conservative)

    SIGNALS:
    - Active worklog claims → actionable
    - Human message/reaction/read → actionable
    - Agent loop detected (>20 messages since human attention) → NOT actionable

    Usage:
      triage = await get_small_brain_triage_gate()

      # Check if conversation is actionable
      result = await triage.triage_message(conversation_id="conv_123")

      if not result.actionable:
          logger.info(f"Skipping non-actionable conversation: {result.reason}")
          return {"status": "skipped", "reason": result.reason}

      # Proceed with agent turn
    """

    # Triage prompt - principle-only, no scenario enumeration
    TRIAGE_PROMPT = """
You are a gatekeeper that decides if an agent turn is actionable.

PRINCIPLES:
1. A human involved OR waiting → ALWAYS actionable
2. Pure agent-to-agent chatter WITHOUT open work → NOT actionable
3. When unsure → actionable=true (conservative default)

SIGNALS FOR ACTIONABLE:
- Human message, reaction, or read receipt in last 10 messages
- Agent claims active work on something
- Task explicitly assigned to agent
- Deadline or time-sensitive context
- Human has been waiting >5 minutes for agent response

SIGNALS FOR NOT ACTIONABLE:
- Agent-to-agent loop (>20 messages without human attention)
- Repetitive coordination without progress
- Agents talking past each other with no resolution path
- Self-congratulatory or status-check chatter with no action items

OUTPUT FORMAT:
Return JSON: {"actionable": boolean, "reason": "string"}

EXAMPLES:
Human: "Hey agent, check this file"
Agent: "Looking at the file now..."
→ {"actionable": true, "reason": "human involved"}

Agent: "I think we should do X"
Agent: "Yes, let's do X"
Agent: "Okay doing X now"
→ {"actionable": false, "reason": "agent loop without human involvement"}

Agent: "Starting task Y with deadline tomorrow"
→ {"actionable": true, "reason": "active work claim with deadline"}
"""

    # Price table for cheap models (USD per 1K tokens)
    PRICE_TABLE = {
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
        "gemini-1.5-flash": {"input": 0.000375, "output": 0.00075},
    }

    def __init__(self, provider_config: Optional[ProviderConfig] = None):
        self.provider_config = provider_config or ProviderConfig(
            api_key="",  # Will use default from registry
            model_name="gpt-4o-mini",  # Cheap model
            timeout_seconds=30.0,
        )

        # Cache for recent results
        self._cache: Dict[str, TriageResult] = {}
        self._cache_ttl = 300  # 5 minutes

        # Statistics
        self._stats = {
            "total_tries": 0,
            "actionable_count": 0,
            "non_actionable_count": 0,
        }

        logger.info(f"SmallBrainTriageGate initialized with model {self.provider_config.model_name}")

    async def triage_message(self, conversation_id: str) -> TriageResult:
        """
        Main entry point: Triage a conversation

        Returns TriageResult indicating whether conversation is actionable

        P1-10 纪律：基础设施性失败（无历史/无凭据/输出不可解析/调用异常）
        一律以 TriageGateError 诚实上抛——不再吞成 actionable=True 无凭据放行。
        "When unsure → actionable" 只属于模型对内容的保守判断，不属于故障兜底。
        """
        self._stats["total_tries"] += 1

        # Generate conversation hash for caching
        conv_hash = self._generate_conversation_hash(conversation_id)

        # Check cache first
        cached_result = self._get_from_cache(conv_hash)
        if cached_result:
            logger.debug(f"Cache hit for conversation {conversation_id}")
            return cached_result

        # Fetch conversation history
        conversation_history = await self._fetch_conversation_history(conversation_id)

        if not conversation_history:
            raise TriageGateError(
                f"conversation '{conversation_id}' 无可分诊的消息历史"
                f"（会话不存在或尚无消息事件）——拒绝无凭据放行"
            )

        # Prepare messages for triage
        messages = self._prepare_triage_messages(conversation_history)

        # Call small model（异常不吞，如实上抛）
        result = await self._call_triage_model(messages)

        # Parse result——只认 JSON 的 actionable 布尔字段，解析不了就报错
        actionable = self._parse_actionable(result.content)

        # Extract reason
        reason_match = self._extract_reason(result.content)

        # Update stats
        if actionable:
            self._stats["actionable_count"] += 1
        else:
            self._stats["non_actionable_count"] += 1

        triage_result = TriageResult(
            actionable=actionable,
            reason=reason_match or "general_assessment",
            confidence=self._estimate_confidence(result),
            conversation_hash=conv_hash,
        )

        # Cache result
        self._cache_to_cache(conv_hash, triage_result)

        logger.info(
            f"Triage result for {conversation_id}: "
            f"actionable={actionable}, reason={reason_match}"
        )

        return triage_result

    def _resolve_provider_config(self) -> ProviderConfig:
        """解析分诊模型的真实凭据（P1-10 接真客户端的凭据面）。

        显式注入且带 api_key 的 provider_config 优先；api_key 为空时回落
        LLMProviderManager 的默认服务商（全仓凭据单源，不造第二份配置面）。
        都没有则原样返回空凭据配置——由 OpenAIAdapter 如实报错，不伪造。
        """
        cfg = self.provider_config
        if cfg.api_key:
            return cfg
        try:
            from neurova.llm.provider_manager import get_provider_manager

            default_provider = get_provider_manager().get_default_provider()
        except Exception as e:  # noqa: BLE001 - 凭据面不可用降级为空凭据，由调用侧诚实报错
            logger.warning("分诊门解析默认服务商失败: %s", e)
            default_provider = None
        if default_provider is not None and getattr(default_provider, "api_key", ""):
            return ProviderConfig(
                api_key=default_provider.api_key,
                base_url=getattr(default_provider, "base_url", None) or cfg.base_url,
                model_name=getattr(default_provider, "default_model", "") or cfg.model_name,
                timeout_seconds=cfg.timeout_seconds,
                temperature=cfg.temperature,
            )
        return cfg

    async def _call_triage_model(self, messages: List[Message]) -> CallResult:
        """Call small model for triage decision

        P1-10：凭据缺失/适配器故障等基础设施性失败一律以 TriageGateError
        诚实上抛（本类 docstring 的既定契约），不裸传底层异常类型。
        """
        registry = get_provider_registry()

        # Create adapter instance
        adapter = registry.create_instance(
            provider_id="triage",
            provider_type=ProviderType.OPENAI,
            config=self._resolve_provider_config(),
        )

        # Add system prompt
        full_messages = [
            Message(role="system", content=self.TRIAGE_PROMPT),
        ] + messages

        # Execute call
        try:
            return await adapter.call(full_messages)
        except TriageGateError:
            raise
        except Exception as exc:  # noqa: BLE001 - 基础设施性失败统一为门语义
            raise TriageGateError(f"分诊模型调用失败: {exc}") from exc

    def _prepare_triage_messages(self, conversation_history: List[Dict]) -> List[Message]:
        """Prepare conversation history for triage"""
        messages = []

        # Take last 20 messages to keep context manageable
        recent_messages = conversation_history[-20:]

        for msg in recent_messages:
            messages.append(Message(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
            ))

        return messages

    def _generate_conversation_hash(self, conversation_id: str) -> str:
        """Generate hash for conversation"""
        return hashlib.md5(conversation_id.encode()).hexdigest()[:16]

    def _get_from_cache(self, conv_hash: str) -> Optional[TriageResult]:
        """Get result from cache if valid"""
        if conv_hash in self._cache:
            result, timestamp = self._cache[conv_hash]
            if time.time() - timestamp < self._cache_ttl:
                return result
            else:
                del self._cache[conv_hash]

        return None

    def _cache_to_cache(self, conv_hash: str, result: TriageResult) -> None:
        """Cache result with timestamp"""
        self._cache[conv_hash] = (result, time.time())

        # Clean old entries if cache too large
        if len(self._cache) > 1000:
            # Remove oldest 10%
            sorted_items = sorted(
                self._cache.items(),
                key=lambda x: x[1][1],
            )
            for key, _ in sorted_items[:100]:
                del self._cache[key]

    def _extract_reason(self, content: str) -> Optional[str]:
        """Extract reason from model response"""
        try:
            # Try to parse JSON
            data = json.loads(content)
            return data.get("reason", "unknown")
        except json.JSONDecodeError:
            # Fallback: extract from text
            if "human" in content.lower():
                return "human_involved"
            elif "loop" in content.lower():
                return "agent_loop"
            elif "work" in content.lower():
                return "active_work"
            else:
                return "general_assessment"

    def _estimate_confidence(self, result: CallResult) -> float:
        """Estimate confidence of triage decision"""
        # Simple heuristic based on response length and clarity
        content = result.content.lower()

        if "false" in content and "true" not in content:
            return 0.8  # Clear negative
        elif "true" in content and "false" not in content:
            return 0.8  # Clear positive
        elif "true" in content and "false" in content:
            return 0.5  # Ambiguous
        else:
            return 0.3  # Unclear

    async def _fetch_conversation_history(self, conversation_id: str) -> List[Dict]:
        """从现役会话事实源取最近消息事件（P1-10 断链接通）。

        SessionSyncManager 是全仓会话事件的单一事实源（chat_pipeline 的
        AGENT_REPLY 广播、渠道 manager 的 USER_MESSAGE/AGENT_REPLY 都写这里），
        `get_messages` 只回 USER_MESSAGE + AGENT_REPLY 两类消息事件，
        role/content 形态与本类 `_prepare_triage_messages` 直接咬合。
        纯内存读（锁内快照），事件循环内直调无阻塞。
        """
        from neurova.sync.session_sync_manager import get_session_sync_manager

        return get_session_sync_manager().get_messages(conversation_id, limit=50)

    def _parse_actionable(self, content: str) -> bool:
        """解析分诊结论——只认 JSON 的 actionable 布尔字段，解析不了就报错。

        此前 `'true' in content.lower()[:50]` 会把 "not actionable"/"truly"
        这类前缀误判成放行（P1-10 第三重脆弱点）。
        """
        data = None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = None
        if isinstance(data, dict) and isinstance(data.get("actionable"), bool):
            return data["actionable"]
        raise TriageGateError(
            f"分诊模型输出不可解析（缺 actionable 布尔字段）: {content[:200]!r}"
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get triage statistics"""
        total = self._stats["total_tries"]
        actionable_rate = (
            self._stats["actionable_count"] / total * 100
            if total > 0 else 0
        )

        return {
            **self._stats,
            "actionable_rate": round(actionable_rate, 1),
            "cache_size": len(self._cache),
            "cache_ttl_seconds": self._cache_ttl,
        }

    def clear_cache(self) -> None:
        """Clear triage cache"""
        self._cache.clear()
        logger.debug("Cleared triage cache")

# Global instance management
_triage_gate_instance: Optional[SmallBrainTriageGate] = None
_triage_gate_lock = __import__('threading').Lock()

def get_small_brain_triage_gate() -> SmallBrainTriageGate:
    """Get global SmallBrainTriageGate instance"""
    global _triage_gate_instance

    if _triage_gate_instance is None:
        with _triage_gate_lock:
            if _triage_gate_instance is None:
                _triage_gate_instance = SmallBrainTriageGate()

    return _triage_gate_instance

def reset_small_brain_triage_gate() -> None:
    """Reset SmallBrainTriageGate instance (for testing)"""
    global _triage_gate_instance
    _triage_gate_instance = None
