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

import asyncio
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


def judgeToolOutcome(result: Any) -> Optional[bool]:
    """工具执行器给出的成败判据：True 成功 / False 失败 / None 未给出。

    `ToolExecutor` 自己带一份 `_result_is_success`（`{"error": …}` 或
    `success=False` 即失败），它是"这次执行算不算成功"的**候选唯一出处**。
    这里只做一次属性取用，取不到就返回 `None` —— 由调用方按"判据缺失"处理，
    **不在这里补一份平行实现**（教义第 6 条：判据只允许一处定义）。

    为什么要报到执行管理器这一层：`ToolExecutionContext.status` 曾被消费方
    当成成败判据，但 `COMPLETED` 说的是"这次调用跑完了"，而不是"工具成功了"
    （返回 `{"error": …}` 的工具同样是 COMPLETED）。判据要么由生产端随
    `status` 一起给出，要么消费端只能自己猜——而猜出来的默认值是"成功"，
    正是构建 cnb-1h8-1k341hkm9 里失败被静默吞掉的那条路。
    """
    if isinstance(result, dict):
        if isinstance(result.get("success"), bool):
            return result["success"]
        if isinstance(result.get("ok"), bool):
            return result["ok"]
        if result.get("status") in ("success", "failure"):
            return result["status"] == "success"
        if "error" in result:
            # `{"error": …}` 是**声明式失败**：不管执行器是谁，这一份结果自己说了失败。
            # 只有它能被无判据地判红；其余形状要靠执行器的判据，缺判据就不猜。
            return False
        tool_executor = getattr(result, "tool_executor", None)
        judge = getattr(tool_executor, "_result_is_success", None)
        if callable(judge):
            try:
                return bool(judge(result))
            except Exception as e:  # noqa: BLE001 - 判据自身异常时不得伪装成成功
                logger.warning("执行器的成败判据抛异常，按未知处置: %s", e, exc_info=True)
                return None
    # 判据缺席：不猜。诚实标成"未知"，让调用方按失败处置并报出原因。
    return None


# ADR 0009/0010: ExecutionStatus / TimeoutStrategy / ToolExecutionContext
# 的单一规范定义位于 neurova.tool_layers.types，本模块 re-export 以保持
# 既有 import 路径（from neurova.agent.tool_execution_manager import ...）可用。
from neurova.tool_layers.types import (
    ExecutionStatus,
    TimeoutStrategy,
    ToolExecutionContext,
)


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
        # Bug 9 修复: 添加 _lock 保护 _contexts 的并发访问(cleanup/遍历/删除)
        self._lock = threading.RLock()
        # 资源修复: 终态上下文保留硬上限(超出按完成时间淘汰最老)
        self._MAX_CONTEXTS = 500

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
            logger.info("Tool execution cancelled: %s", tool_name)
            self._set_status(context_id, ExecutionStatus.CANCELLED, "Execution cancelled")

        except Exception as e:
            logger.error("Tool execution failed: %s, error: %s", tool_name, e)
            self._set_status(context_id, ExecutionStatus.FAILED, f"Execution failed: {str(e)}")
            context.error = str(e)

        finally:
            # 设置完成时间
            context.completed_at = datetime.now(timezone.utc)
            # 清理任务引用
            self._running_tasks.pop(context_id, None)
            # 判据随结果一起产出：成败是**工具执行器**的判据，不是调用状态
            # （COMPLETED 只说明"跑完了"）。放在 finally 是为了让 TIMEOUT /
            # CANCELLED 也拿到 `success=False`——超时不是成功，这一点不需要
            # 任何调用方再猜一次。
            self._attach_outcome_verdict(context)
            # 资源修复: 终态上下文只增不减曾是无界泄漏, 每次执行结束后触发淘汰
            self._evict_over_capacity()

        return context

    @staticmethod
    def _attach_outcome_verdict(context: ToolExecutionContext) -> None:
        """把工具执行的成败判据落到 `context.result` 上，供消费方单源读取。

        - 非终态（PENDING / RUNNING）：不动 result，避免写入半成品；
        - 终态但无结果（TIMEOUT / CANCELLED / FAILED）：补一份带 error 的结果，
          让消费方的判据恒有物可判——超时被读成成功，同样是失败被静默吞掉。

        只做"补判据"，不改 `context.status`：状态语义仍是"调用生命周期"，
        两个维度各自单源，消费方不再用其中一个去推另一个。
        """
        if context.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
            return

        if context.result is None:
            if context.status in (ExecutionStatus.TIMEOUT, ExecutionStatus.CANCELLED):
                reason = "timeout" if context.status == ExecutionStatus.TIMEOUT else "cancelled"
                context.result = {"success": False, "error": f"工具执行{'超时' if reason == 'timeout' else '被取消'}"}
            else:
                context.result = {"success": False, "error": context.error or "工具执行失败"}
            return

        if not isinstance(context.result, dict) or "success" in context.result:
            return

        verdict = judgeToolOutcome(context.result)
        if verdict is None:
            # 判据缺席 ⇒ 不动结果形状，让消费方看见"未知"并按失败报出原因；
            # 补一个 `success: False` 会把"判据没给出"伪装成"工具报错了"。
            return
        result = dict(context.result)
        result["success"] = verdict is True
        context.result = result

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
            logger.warning("Context not found: %s", context_id)
            return False

        if context.status not in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]:
            logger.warning("Cannot cancel context in status: %s", context.status)
            return False

        # 取消异步任务
        task = self._running_tasks.get(context_id)
        if task and not task.done():
            task.cancel()
            # Bug 10 修复: await task 避免 pending 警告(原代码注释"不在此处 await"是 bug)
            try:
                await task
            except asyncio.CancelledError:
                pass

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

        # Bug 9 修复: cleanup 遍历+删除 _contexts 必须持锁,防止与并发 execute 竞态
        with self._lock:
            for context_id, context in list(self._contexts.items()):
                if context.status in [
                    ExecutionStatus.COMPLETED,
                    ExecutionStatus.FAILED,
                    ExecutionStatus.TIMEOUT,
                    ExecutionStatus.CANCELLED,
                ]:
                    if context.completed_at:
                        age = (now - context.completed_at).total_seconds()
                        if age > max_age_seconds:
                            del self._contexts[context_id]
                            cleaned += 1

        return cleaned

    def _evict_over_capacity(self) -> None:
        """资源修复: 终态上下文只增不减曾是无界泄漏。
        先淘汰超过 5 分钟的终态上下文, 仍超出硬上限时按完成时间淘汰最老终态。"""
        try:
            self.cleanup_completed_contexts(max_age_seconds=300)
            if len(self._contexts) > self._MAX_CONTEXTS:
                with self._lock:
                    terminal = [
                        (c.completed_at, cid)
                        for cid, c in self._contexts.items()
                        if c.status
                        in [
                            ExecutionStatus.COMPLETED,
                            ExecutionStatus.FAILED,
                            ExecutionStatus.TIMEOUT,
                            ExecutionStatus.CANCELLED,
                        ]
                        and c.completed_at is not None
                    ]
                    terminal.sort()
                    for _, cid in terminal[: len(self._contexts) - self._MAX_CONTEXTS]:
                        self._contexts.pop(cid, None)
        except Exception as e:
            logger.debug("Context eviction failed: %s", e)

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
                logger.error("Status change callback error: %s", e)

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
            logger.warning("Tool execution timeout: %s (>%ss)", context.tool_name, context.timeout)
            self._set_status(context.context_id, ExecutionStatus.TIMEOUT, f"Timeout after {context.timeout}s")
            # Bug 7 修复: 超时后取消后台 task,避免资源泄漏(原代码注释"任务仍在后台运行"是 bug)
            task = self._running_tasks.get(context.context_id)
            if task and not task.done():
                task.cancel()

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

                # Bug 8 修复: 重试前 cancel 旧 task,避免覆盖 _running_tasks 导致旧 task 泄漏
                old_task = self._running_tasks.get(context.context_id)
                if old_task and not old_task.done():
                    old_task.cancel()

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
                self._set_status(
                    context.context_id, ExecutionStatus.COMPLETED, f"Execution completed after {retry_count} retries"
                )
                return

            except asyncio.TimeoutError:
                retry_count += 1
                context.retries = retry_count

                if retry_count > context.max_retries:
                    logger.warning("Tool execution timeout after %s retries: %s", retry_count, context.tool_name)
                    self._set_status(
                        context.context_id, ExecutionStatus.TIMEOUT, f"Timeout after {retry_count} retries"
                    )
                    return

                logger.info("Tool execution retry %s/%s: %s", retry_count, context.max_retries, context.tool_name)
                self._set_status(
                    context.context_id, ExecutionStatus.RUNNING, f"Retrying ({retry_count}/{context.max_retries})"
                )

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
            logger.error("Tool execution failed: %s, error: %s", context.tool_name, e)
            self._set_status(context.context_id, ExecutionStatus.FAILED, f"Execution failed: {str(e)}")
            # Bug 11 修复: 不在此处赋值 error 字段,由 execute() 统一处理避免双重赋值

    def __repr__(self) -> str:
        """字符串表示"""
        total = len(self._contexts)
        active = sum(1 for ctx in self._contexts.values() if ctx.status == ExecutionStatus.RUNNING)
        return f"ToolExecutionManager(total={total}, active={active})"
