"""
ToolExecutionManager 深度模块 - 异步工具执行管理

提供统一的工具执行管理接口，包括：
1. 执行上下文管理
2. 超时策略（严格、弹性、无限）
3. 优雅取消
4. 状态查询和回调

设计原则：
- 深度模块：小接口，深实现
- 状态机：清晰的状态转换
- 可测试：接口清晰，易于 mock
"""

import logging
import asyncio
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Coroutine
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)


class TimeoutStrategy(Enum):
    """超时策略枚举"""
    STRICT = "strict"      # 严格超时
    ELASTIC = "elastic"    # 弹性超时（自动续时）
    INFINITE = "infinite"  # 无限等待


class ExecutionStatus(Enum):
    """执行状态枚举"""
    PENDING = "pending"        # 等待执行
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 执行完成
    TIMEOUT = "timeout"        # 执行超时
    CANCELLED = "cancelled"    # 已取消
    FAILED = "failed"          # 执行失败


@dataclass
class ToolExecutionContext:
    """工具执行上下文"""
    context_id: str
    tool_name: str
    params: Dict[str, Any]
    user_input: str
    timeout: float = 30.0
    strategy: TimeoutStrategy = TimeoutStrategy.STRICT
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "context_id": self.context_id,
            "tool_name": self.tool_name,
            "params": self.params,
            "user_input": self.user_input,
            "timeout": self.timeout,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }


@dataclass
class ExecutionEvent:
    """执行状态变更事件"""
    context_id: str
    old_status: ExecutionStatus
    new_status: ExecutionStatus
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "context_id": self.context_id,
            "old_status": self.old_status.value,
            "new_status": self.new_status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class ToolExecutionManager:
    """
    工具执行管理器
    
    提供统一的工具执行管理接口，支持：
    1. 多种超时策略
    2. 优雅取消
    3. 状态监控和回调
    4. 并发执行管理
    
    使用示例：
        manager = ToolExecutionManager()
        
        # 执行工具
        context = await manager.execute(
            tool_name="search_tool",
            params={"query": "test"},
            user_input="search for test",
            executor=tool_executor,
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        # 获取状态
        status = manager.get_context(context.context_id)
        print(f"Status: {status.status}")
        
        # 取消执行
        await manager.cancel(context.context_id)
    """
    
    def __init__(self):
        """初始化 ToolExecutionManager"""
        self._contexts: Dict[str, ToolExecutionContext] = {}
        self._status_callbacks: List[Callable[[ExecutionEvent], None]] = []
        self._running_tasks: Dict[str, asyncio.Task] = {}
        
        logger.debug("ToolExecutionManager initialized")
    
    def get_context(self, context_id: str) -> Optional[ToolExecutionContext]:
        """
        获取执行上下文
        
        参数:
            context_id: 上下文ID
        
        返回:
            ToolExecutionContext 实例，如果不存在则返回 None
        """
        return self._contexts.get(context_id)
    
    def get_all_contexts(self) -> List[ToolExecutionContext]:
        """
        获取所有执行上下文
        
        返回:
            所有执行上下文列表
        """
        return list(self._contexts.values())
    
    def get_health(self) -> Dict[str, Any]:
        """
        获取健康信息
        
        返回:
            包含状态统计信息的字典
        """
        total = len(self._contexts)
        active = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.RUNNING)
        completed = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.COMPLETED)
        failed = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.FAILED)
        timeout = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.TIMEOUT)
        
        return {
            "total_contexts": total,
            "active_contexts": active,
            "completed_contexts": completed,
            "failed_contexts": failed,
            "timeout_contexts": timeout,
        }
    
    async def execute(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user_input: str,
        executor: Any,
        timeout: float = 30.0,
        strategy: TimeoutStrategy = TimeoutStrategy.STRICT,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[ExecutionEvent], None]] = None,
    ) -> ToolExecutionContext:
        """
        执行工具
        
        参数:
            tool_name: 工具名称
            params: 工具参数
            user_input: 用户输入
            executor: 工具执行器（需要有 execute_tool 方法）
            timeout: 超时时间（秒）
            strategy: 超时策略
            max_retries: 最大重试次数（仅弹性策略）
            metadata: 元数据
            callback: 状态变更回调
        
        返回:
            ToolExecutionContext 实例
        """
        # 生成唯一的上下文ID
        context_id = str(uuid.uuid4())
        
        # 创建执行上下文
        context = ToolExecutionContext(
            context_id=context_id,
            tool_name=tool_name,
            params=params,
            user_input=user_input,
            timeout=timeout,
            strategy=strategy,
            max_retries=max_retries,
            metadata=metadata,
        )
        
        # 注册回调
        if callback:
            self.on_status_change(callback)
        
        # 保存上下文
        self._contexts[context_id] = context
        
        # 设置初始状态
        self._set_status(context_id, ExecutionStatus.PENDING, "Execution queued")
        
        try:
            # 设置状态为运行中
            self._set_status(context_id, ExecutionStatus.RUNNING, "Execution started")
            
            # 根据策略执行
            if strategy == TimeoutStrategy.STRICT:
                await self._execute_strict(context, executor)
            elif strategy == TimeoutStrategy.ELASTIC:
                await self._execute_elastic(context, executor)
            elif strategy == TimeoutStrategy.INFINITE:
                await self._execute_infinite(context, executor)
            else:
                raise ValueError(f"Unknown timeout strategy: {strategy}")
        
        except asyncio.CancelledError:
            # 任务被取消
            logger.info(f"Tool execution cancelled: {tool_name}")
            self._set_status(context_id, ExecutionStatus.CANCELLED, "Execution cancelled")
        
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}, error: {e}")
            self._set_status(context_id, ExecutionStatus.FAILED, f"Execution failed: {str(e)}")
            context.error = str(e)
        
        finally:
            # 设置完成时间
            context.completed_at = datetime.now(timezone.utc)
            # 清理任务引用
            self._running_tasks.pop(context_id, None)
        
        return context
    
    async def cancel(self, context_id: str) -> bool:
        """
        取消执行
        
        参数:
            context_id: 上下文ID
        
        返回:
            True 表示取消成功，False 表示失败
        """
        context = self._contexts.get(context_id)
        if not context:
            logger.warning(f"Context not found: {context_id}")
            return False
        
        if context.status not in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]:
            logger.warning(f"Cannot cancel context in status: {context.status}")
            return False
        
        # 取消异步任务
        task = self._running_tasks.get(context_id)
        if task and not task.done():
            task.cancel()
            # 注意：不在此处 await task，因为 execute 方法会处理 CancelledError
        
        # 更新状态
        self._set_status(context_id, ExecutionStatus.CANCELLED, "Execution cancelled")
        
        return True
    
    def on_status_change(self, callback: Callable[[ExecutionEvent], None]) -> None:
        """
        注册状态变更回调
        
        参数:
            callback: 回调函数，接收 ExecutionEvent 参数
        """
        if callback not in self._status_callbacks:
            self._status_callbacks.append(callback)
    
    def remove_status_change_callback(self, callback: Callable[[ExecutionEvent], None]) -> None:
        """
        移除状态变更回调
        
        参数:
            callback: 要移除的回调函数
        """
        if callback in self._status_callbacks:
            self._status_callbacks.remove(callback)
    
    def cleanup_completed_contexts(self, max_age_seconds: float = 3600) -> int:
        """
        清理已完成的上下文
        
        参数:
            max_age_seconds: 最大保留时间（秒）
        
        返回:
            清理的上下文数量
        """
        now = datetime.now(timezone.utc)
        cleaned = 0
        
        for context_id, context in list(self._contexts.items()):
            if context.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, 
                                 ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED]:
                if context.completed_at:
                    age = (now - context.completed_at).total_seconds()
                    if age > max_age_seconds:
                        del self._contexts[context_id]
                        cleaned += 1
        
        return cleaned
    
    # ================================================================
    # 内部方法
    # ================================================================
    
    def _set_status(self, context_id: str, new_status: ExecutionStatus, message: str = "") -> None:
        """
        设置状态并触发回调
        
        参数:
            context_id: 上下文ID
            new_status: 新状态
            message: 状态变更消息
        """
        context = self._contexts.get(context_id)
        if not context:
            return
        
        old_status = context.status
        if old_status == new_status:
            return
        
        context.status = new_status
        
        # 创建事件
        event = ExecutionEvent(
            context_id=context_id,
            old_status=old_status,
            new_status=new_status,
            message=message,
        )
        
        # 触发回调
        for callback in self._status_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Status change callback error: {e}")
    
    async def _execute_strict(self, context: ToolExecutionContext, executor: Any) -> None:
        """
        严格超时执行
        
        参数:
            context: 执行上下文
            executor: 工具执行器
        """
        try:
            # 创建异步任务并存储引用
            task = asyncio.create_task(
                executor.execute_tool(
                    context.tool_name,
                    context.params,
                    context.user_input,
                )
            )
            self._running_tasks[context.context_id] = task
            
            # 等待任务完成或超时
            result = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=context.timeout,
            )
            
            context.result = result
            self._set_status(context.context_id, ExecutionStatus.COMPLETED, "Execution completed")
        
        except asyncio.TimeoutError:
            logger.warning(f"Tool execution timeout: {context.tool_name} (>{context.timeout}s)")
            self._set_status(context.context_id, ExecutionStatus.TIMEOUT, f"Timeout after {context.timeout}s")
            # 注意：任务仍在后台运行，但超时后我们不再等待
    
    async def _execute_elastic(self, context: ToolExecutionContext, executor: Any) -> None:
        """
        弹性超时执行（自动续时）
        
        参数:
            context: 执行上下文
            executor: 工具执行器
        """
        retry_count = 0
        base_timeout = context.timeout
        
        while retry_count <= context.max_retries:
            try:
                # 弹性超时：每次重试增加超时时间
                current_timeout = base_timeout * (1 + retry_count * 0.5)
                
                # 创建异步任务并存储引用
                task = asyncio.create_task(
                    executor.execute_tool(
                        context.tool_name,
                        context.params,
                        context.user_input,
                    )
                )
                self._running_tasks[context.context_id] = task
                
                result = await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=current_timeout,
                )
                
                context.result = result
                self._set_status(context.context_id, ExecutionStatus.COMPLETED, 
                               f"Execution completed after {retry_count} retries")
                return
            
            except asyncio.TimeoutError:
                retry_count += 1
                context.retries = retry_count
                
                if retry_count > context.max_retries:
                    logger.warning(f"Tool execution timeout after {retry_count} retries: {context.tool_name}")
                    self._set_status(context.context_id, ExecutionStatus.TIMEOUT, 
                                   f"Timeout after {retry_count} retries")
                    return
                
                logger.info(f"Tool execution retry {retry_count}/{context.max_retries}: {context.tool_name}")
                self._set_status(context.context_id, ExecutionStatus.RUNNING, 
                               f"Retrying ({retry_count}/{context.max_retries})")
    
    async def _execute_infinite(self, context: ToolExecutionContext, executor: Any) -> None:
        """
        无限等待执行
        
        参数:
            context: 执行上下文
            executor: 工具执行器
        """
        try:
            # 创建异步任务并存储引用
            task = asyncio.create_task(
                executor.execute_tool(
                    context.tool_name,
                    context.params,
                    context.user_input,
                )
            )
            self._running_tasks[context.context_id] = task
            
            result = await task
            
            context.result = result
            self._set_status(context.context_id, ExecutionStatus.COMPLETED, "Execution completed")
        
        except Exception as e:
            logger.error(f"Tool execution failed: {context.tool_name}, error: {e}")
            self._set_status(context.context_id, ExecutionStatus.FAILED, f"Execution failed: {str(e)}")
            context.error = str(e)
    
    def __repr__(self) -> str:
        """字符串表示"""
        total = len(self._contexts)
        active = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.RUNNING)
        return f"ToolExecutionManager(total={total}, active={active})"