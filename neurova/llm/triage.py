"""
Neurova Small-Brain Triage Gate
轻量级 LLM 分类器，过滤无意义的 agent-to-agent 对话

"""

import json
import hashlib
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
            logger.warning(f"No conversation history found for {conversation_id}")
            return TriageResult(
                actionable=True,  # Default to actionable if no history
                reason="no_history",
                confidence=0.0,
                conversation_hash=conv_hash,
            )

        # Prepare messages for triage
        messages = self._prepare_triage_messages(conversation_history)

        # Call small model
        try:
            result = await self._call_triage_model(messages)

            # Parse result
            actionable = result.content.lower().startswith('{"actionable": true}') or \
                        'true' in result.content.lower()[:50]

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

        except Exception as e:
            logger.error(f"Triage failed for {conversation_id}: {e}")

            # On error, default to actionable (conservative)
            return TriageResult(
                actionable=True,
                reason=f"triage_error: {str(e)}",
                confidence=0.0,
                conversation_hash=conv_hash,
            )

    async def _call_triage_model(self, messages: List[Message]) -> CallResult:
        """Call small model for triage decision"""
        registry = get_provider_registry()

        # Create adapter instance
        adapter = registry.create_instance(
            provider_id="triage",
            provider_type=ProviderType.OPENAI,
            config=self.provider_config,
        )

        # Add system prompt
        full_messages = [
            Message(role="system", content=self.TRIAGE_PROMPT),
        ] + messages

        # Execute call
        result = await adapter.call(full_messages)

        return result

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
        """Fetch conversation history from database"""
        # This should query the actual database
        # Mock implementation for now

        # SQL:
        # SELECT role, content FROM messages
        # WHERE conversation_id = :convo_id
        # ORDER BY created_at DESC
        # LIMIT 50

        return []  # Mock

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
