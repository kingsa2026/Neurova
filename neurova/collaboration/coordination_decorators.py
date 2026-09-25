"""
Coordination Decorators - Integration of Freshness Preflight & GLANCE_YIELD_RULES
"""

import time
import functools
from typing import Callable, Any, Optional, Dict, List, Tuple
from functools import wraps

from neurova.core.logger import get_logger
from neurova.collaboration.seen_cursor import (
    get_seen_cursor_manager,
    SeenCursorManager,
)
from neurova.collaboration.glance_yield_rules import (
    get_glance_yield_checker,
    GlanceYieldChecker,
    YieldDecision,
)

logger = get_logger(__name__)

def freshness_preflight(
    agent_id: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
):
    """
    Freshness Preflight 装饰器

    在操作执行前检查是否新鲜 (未见过)

    Usage:
        @freshness_preflight(agent_id="default", session_id="sess_123")
        async def process_task(data):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cursor_manager = get_seen_cursor_manager()

            # Extract operation hashes from kwargs or compute from args
            operation_hashes = _extract_operation_hashes(kwargs)

            # Check freshness
            is_fresh, collision_reason = cursor_manager.check_freshness(
                agent_id=agent_id,
                expected_op_hashes=operation_hashes,
            )

            if not is_fresh:
                logger.warning(f"Freshness check failed for agent {agent_id}: {collision_reason}")

                # Return cached result or raise exception
                raise CollisionError(
                    f"Operation collision detected: {collision_reason}"
                )

            # Execute operation
            try:
                result = await func(*args, **kwargs)

                # Record operations after successful execution
                cursor_manager.record_operations(
                    agent_id=agent_id,
                    session_id=session_id or "unknown",
                    turn_id=turn_id or "unknown",
                    operation_hashes=operation_hashes,
                )

                return result

            except Exception as e:
                logger.error(f"Operation failed: {e}")
                raise

        return wrapper
    return decorator

def glance_yield_check(
    model_name: str,
    max_concurrent: int = 5,
    min_spawn_interval: float = 2.0,
):
    """
    GLANCE_YIELD_RULES 检查装饰器

    在操作执行前检查是否需要 yield (让出)

    Usage:
        @glance_yield_check(model_name="gpt-4", max_concurrent=3)
        async def heavy_computation(data):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            yield_checker = get_glance_yield_checker()

            # Get agent_id from context (could be passed in kwargs or extracted)
            agent_id = kwargs.get("agent_id", "unknown")

            # Extract proposed operations
            proposed_operations = _extract_proposed_operations(kwargs)

            # Check yield rules
            decision = yield_checker.check_yield_rules(
                agent_id=agent_id,
                model_name=model_name,
                proposed_operations=proposed_operations,
            )

            if decision.should_yield:
                logger.info(f"Yield decision for agent {agent_id}: {decision.reason.value}")

                # Wait for specified time
                if decision.wait_time_seconds > 0:
                    logger.info(f"Waiting {decision.wait_time_seconds}s before retry")
                    time.sleep(decision.wait_time_seconds)

                    # Retry once after waiting
                    decision = yield_checker.check_yield_rules(
                        agent_id=agent_id,
                        model_name=model_name,
                        proposed_operations=proposed_operations,
                    )

                    if decision.should_yield:
                        # Still need to yield - back off with exponential increase
                        backoff = decision.wait_time_seconds * 2
                        logger.warning(f"Still yielding after retry, backing off for {backoff}s")
                        time.sleep(backoff)

                        # Final attempt
                        decision = yield_checker.check_yield_rules(
                            agent_id=agent_id,
                            model_name=model_name,
                            proposed_operations=proposed_operations,
                        )

                        if decision.should_yield:
                            # Give up and raise error
                            raise YieldLimitExceededError(
                                f"Yield limit exceeded after retries: {decision.reason.value}"
                            )

            # Register agent if not already registered
            yield_checker.register_agent(agent_id, model_name)

            # Record operation start
            operation_hash = _compute_operation_hash(proposed_operations)
            yield_checker.record_operation_start(agent_id, operation_hash)

            try:
                # Execute operation
                result = await func(*args, **kwargs)

                # Record operation complete
                yield_checker.record_operation_complete(agent_id, operation_hash, success=True)

                return result

            except Exception as e:
                # Record failure
                yield_checker.record_operation_complete(agent_id, operation_hash, success=False)
                raise

        return wrapper
    return decorator

def coordinated_operation(
    agent_id: str,
    model_name: str,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
):
    """
    组合装饰器：同时应用 Freshness Preflight 和 GLANCE_YIELD_RULES

    Usage:
        @coordinated_operation(
            agent_id="default",
            model_name="gpt-4",
            session_id="sess_123"
        )
        async def multi_step_task(data):
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Apply both decorators
        fresh_decorator = freshness_preflight(agent_id, session_id, turn_id)
        yield_decorator = glance_yield_check(model_name)

        wrapped = yield_decorator(fresh_decorator(func))

        return wrapped

    return decorator

# ============================================================================
# Helper Functions
# ============================================================================

def _extract_operation_hashes(kwargs: Dict[str, Any]) -> List[str]:
    """从参数中提取操作哈希列表"""
    # Look for 'operation_hashes' or 'op_hashes' key
    hashes = kwargs.get("operation_hashes") or kwargs.get("op_hashes")

    if isinstance(hashes, list):
        return hashes

    # If single hash provided
    if isinstance(hashes, str):
        return [hashes]

    # Compute hash from data
    data = kwargs.get("data", {})
    return [_compute_operation_hash([str(data)])]

def _extract_proposed_operations(kwargs: Dict[str, Any]) -> List[str]:
    """提取提议的操作列表"""
    # Similar logic to _extract_operation_hashes
    return _extract_operation_hashes(kwargs)

def _compute_operation_hash(operations: List[str]) -> str:
    """计算操作集合的哈希"""
    import hashlib

    sorted_ops = sorted(operations)
    content = ",".join(sorted_ops)
    return hashlib.sha256(content.encode()).hexdigest()[:32]

# ============================================================================
# Custom Exceptions
# ============================================================================

class CoordinationError(Exception):
    """Base coordination error"""
    pass

class CollisionError(CoordinationError):
    """操作碰撞错误"""
    pass

class YieldLimitExceededError(CoordinationError):
    """Yield 限制超出错误"""
    pass

# ============================================================================
# Middleware Integration
# ============================================================================

async def coordination_middleware(
    request: Any,
    call_next: Callable,
) -> Any:
    """
    FastAPI 中间件：协调层检查

    用于 API 端点的统一协调检查
    """
    from fastapi import HTTPException, status

    # Extract agent_id from request
    agent_id = request.headers.get("x-agent-id", "unknown")
    model_name = request.headers.get("x-model-name", "unknown")

    try:
        # Create yield checker
        yield_checker = get_glance_yield_checker()

        # Check yield rules
        decision = yield_checker.check_yield_rules(
            agent_id=agent_id,
            model_name=model_name,
            proposed_operations=[],  # Will be populated from request body
        )

        if decision.should_yield:
            logger.warning(f"API rate limited for agent {agent_id}: {decision.reason.value}")

            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limited due to coordination constraints",
                    "reason": decision.reason.value,
                    "retry_after": decision.wait_time_seconds,
                },
            )

        # Continue processing
        response = await call_next(request)
        return response

    except CoordinationError as e:
        logger.error(f"Coordination error: {e}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Middleware error: {e}")
        raise
