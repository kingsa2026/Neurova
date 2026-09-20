"""
Agent Turn Coordinator
在 turn 执行前后应用协调规则，确保 multi-agent 协作的有序性
Neurova Style: Follows existing patterns (Singleton, Thread-safe, etc.)
"""

import time
import threading
from typing import Optional, Dict, Any
from datetime import datetime

from neurova.core.logger import get_logger
from neurova.collaboration.glance_yield_rules import (
    get_glance_yield_checker,
    YieldDecision,
    YieldReason,
)
from neurova.collaboration.seen_cursor import (
    get_seen_cursor_manager,
)
from neurova.collaboration.outbox_handler import (
    get_outbox_handler,
)

logger = get_logger(__name__)


class TurnCoordinator:
    """
    Coordinate agent turn execution
    
    Applies coordination rules before/during/after turn execution
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Get singleton instances
        self.yield_checker = get_glance_yield_checker()
        self.yield_checker.initialize()  # Initialize the checker
        
        self.cursor_manager = get_seen_cursor_manager()
        
        # Statistics
        self._stats = {
            "total_turns": 0,
            "yielded_turns": 0,
            "successful_turns": 0,
            "failed_turns": 0,
        }
        
        self._initialized = True
        
        logger.info("TurnCoordinator initialized")
    
    async def check_and_execute_turn(self, agent, turn) -> Any:
        """
        Check coordination rules and execute turn
        
        Args:
            agent: Agent instance
            turn: Turn object with id, session_id, etc.
        
        Returns:
            Turn result or skipped result
        """
        with self._lock:
            self._stats["total_turns"] += 1
            
            # Get context
            agent_id = agent.id
            model_name = getattr(agent, 'model_name', 'unknown')
            session_id = getattr(turn, 'session_id', None)
            
            logger.debug(
                f"Checking coordination for agent {agent_id}, "
                f"model {model_name}, turn {turn.id}"
            )
            
            # Register agent if not already registered
            self.yield_checker.register_agent(agent_id, model_name)
            
            # Create operation identifier
            op_hash = f"turn_{turn.id}_{int(time.time() * 1000)}"
            
            # Check yield rules
            decision = self.yield_checker.check_yield_rules(
                agent_id=agent_id,
                model_name=model_name,
                proposed_operations=[op_hash],
            )
            
            if decision.should_yield:
                logger.info(
                    f"Turn yielding for agent {agent_id}: "
                    f"{decision.reason.value} - "
                    f"wait {decision.wait_time_seconds}s"
                )
                
                self._stats["yielded_turns"] += 1
                
                # Wait and retry once
                if decision.wait_time_seconds > 0:
                    await asyncio.sleep(decision.wait_time_seconds)
                    
                    # Retry
                    decision = self.yield_checker.check_yield_rules(
                        agent_id=agent_id,
                        model_name=model_name,
                        proposed_operations=[op_hash],
                    )
                    
                    if decision.should_yield:
                        # Still yielding - skip this turn
                        logger.warning(
                            f"Skipping turn {turn.id} for agent {agent_id} "
                            f"after retry"
                        )
                        
                        self._publish_turn_skipped_event(
                            agent_id=agent_id,
                            turn=turn,
                            reason=decision.reason.value,
                        )
                        
                        return self._create_skipped_result(turn, decision)
            
            # Record operation start
            self.yield_checker.record_operation_start(agent_id, op_hash)
            
            try:
                # Execute turn
                logger.debug(f"Executing turn {turn.id} for agent {agent_id}")
                result = await agent.execute_turn(turn)
                
                # Record completion
                self.yield_checker.record_operation_complete(agent_id, op_hash, success=True)
                
                # Update stats
                self._stats["successful_turns"] += 1
                
                # Publish event
                self._publish_turn_completed_event(
                    agent_id=agent_id,
                    turn=turn,
                    result=result,
                )
                
                logger.debug(f"Turn {turn.id} completed successfully for agent {agent_id}")
                
                return result
                
            except Exception as e:
                # Record failure
                self.yield_checker.record_operation_complete(agent_id, op_hash, success=False)
                
                # Update stats
                self._stats["failed_turns"] += 1
                
                logger.error(f"Turn {turn.id} failed for agent {agent_id}: {e}")
                
                # Publish failure event
                self._publish_turn_failed_event(
                    agent_id=agent_id,
                    turn=turn,
                    error=str(e),
                )
                
                raise
    
    def _create_skipped_result(self, turn, decision: YieldDecision) -> dict:
        """Create skipped turn result"""
        return {
            "turn_id": turn.id,
            "status": "skipped",
            "reason": decision.reason.value,
            "details": decision.details,
            "timestamp": time.time(),
        }
    
    def _publish_turn_completed_event(
        self,
        agent_id: str,
        turn,
        result: Any,
    ) -> None:
        """Publish turn completed event to outbox"""
        try:
            outbox = get_outbox_handler()
            
            # Extract response length
            if isinstance(result, dict):
                response_text = str(result.get('content', ''))
            elif isinstance(result, str):
                response_text = result
            else:
                response_text = str(result)
            
            payload = {
                "turn_id": turn.id,
                "session_id": getattr(turn, 'session_id', None),
                "success": True,
                "response_length": len(response_text),
                "timestamp": time.time(),
            }
            
            outbox.publish(
                event_type="turn_completed",
                agent_id=agent_id,
                session_id=getattr(turn, 'session_id', None),
                payload=payload,
                priority=6,
                expiration_ttl=86400,  # 24 hours
            )
            
            logger.debug(f"Published turn_completed event for {turn.id}")
            
        except Exception as e:
            logger.warning(f"Failed to publish turn_completed event: {e}")
    
    def _publish_turn_skipped_event(
        self,
        agent_id: str,
        turn,
        reason: str,
    ) -> None:
        """Publish turn skipped event"""
        try:
            outbox = get_outbox_handler()
            
            payload = {
                "turn_id": turn.id,
                "session_id": getattr(turn, 'session_id', None),
                "status": "skipped",
                "reason": reason,
                "timestamp": time.time(),
            }
            
            outbox.publish(
                event_type="turn_skipped",
                agent_id=agent_id,
                session_id=getattr(turn, 'session_id', None),
                payload=payload,
                priority=4,
                expiration_ttl=86400,
            )
            
        except Exception as e:
            logger.warning(f"Failed to publish turn_skipped event: {e}")
    
    def _publish_turn_failed_event(
        self,
        agent_id: str,
        turn,
        error: str,
    ) -> None:
        """Publish turn failed event"""
        try:
            outbox = get_outbox_handler()
            
            payload = {
                "turn_id": turn.id,
                "session_id": getattr(turn, 'session_id', None),
                "success": False,
                "error": error,
                "timestamp": time.time(),
            }
            
            outbox.publish(
                event_type="turn_failed",
                agent_id=agent_id,
                session_id=getattr(turn, 'session_id', None),
                payload=payload,
                priority=3,
                expiration_ttl=86400,
            )
            
        except Exception as e:
            logger.warning(f"Failed to publish turn_failed event: {e}")
    
    def get_stats(self) -> dict:
        """Get coordinator statistics"""
        total = sum(self._stats.values())
        
        return {
            **self._stats,
            "success_rate": round(
                self._stats["successful_turns"] / max(total, 1), 3
            ),
            "yield_rate": round(
                self._stats["yielded_turns"] / max(total, 1), 3
            ),
        }
    
    def reset(self) -> None:
        """Reset statistics (for testing)"""
        with self._lock:
            self._stats = {
                "total_turns": 0,
                "yielded_turns": 0,
                "successful_turns": 0,
                "failed_turns": 0,
            }
            logger.info("TurnCoordinator stats reset")


# Global instance management
_turn_coordinator_instance: Optional[TurnCoordinator] = None
_turn_coordinator_lock = threading.Lock()


def get_turn_coordinator() -> TurnCoordinator:
    """Get global TurnCoordinator instance"""
    global _turn_coordinator_instance
    
    if _turn_coordinator_instance is None:
        with _turn_coordinator_lock:
            if _turn_coordinator_instance is None:
                _turn_coordinator_instance = TurnCoordinator()
    
    return _turn_coordinator_instance


def reset_turn_coordinator() -> None:
    """Reset TurnCoordinator instance (for testing)"""
    global _turn_coordinator_instance
    _turn_coordinator_instance = None
