"""
工具执行协调器（P1-2，对标 QP tool_calls/_coordinator 的 offload 语义）

- per-tool 超时注册表：元数据声明制（对标 QP shell 60s/grep 30s）
- 超时转后台不取消：执行超时的任务转入后台继续跑并持有独立引用，
  立即返回 background 信封（{"status":"background","task_id",...}），
  后台完成后结果/错误落入 pending hints，供下一轮注入 LLM 上下文
- 并行安全声明制：is_concurrency_safe 只对声明的只读工具为 True
  （并行 gather 的白名单依据；未知工具保守串行）
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# per-tool 超时（秒）：只读/轻工具短超时，浏览器/重 IO 长超时
TOOL_TIMEOUTS_S: Dict[str, float] = {
    "calculator": 5,
    "memory_search": 10,
    "recall_history": 10,
    "web_search": 30,
    "web_fetch": 30,
    "weather": 15,
    "browser_navigate": 90,
    "browser_click": 60,
    "browser_type": 60,
    "browser_screenshot": 60,
    "browser_extract_text": 60,
    "dom_snapshot": 45,
}

TOOL_DEFAULT_TIMEOUT_S = 60.0

# 并行安全声明清单：只读/无共享可变状态的工具（P1-2 并行 gather 白名单）
_CONCURRENCY_SAFE_TOOLS = {
    "calculator",
    "memory_search",
    "recall_history",
    "web_search",
    "web_fetch",
    "weather",
    "get_time",
    "time_now",
}


def get_tool_timeout(tool_name: str, default: Optional[float] = None) -> float:
    """per-tool 超时；未知工具回落默认（大小写不敏感）。"""
    name = (tool_name or "").strip().lower()
    return TOOL_TIMEOUTS_S.get(name, default if default is not None else TOOL_DEFAULT_TIMEOUT_S)


def is_concurrency_safe(tool_name: str) -> bool:
    """并行安全声明制：只读清单内的工具可并行，其余（含未知）保守串行。"""
    return (tool_name or "").strip().lower() in _CONCURRENCY_SAFE_TOOLS


class ToolCoordinator:
    """工具执行协调：per-tool 超时 + 超时转后台 + pending hints。"""

    def __init__(self):
        # task_id → {"task", "tool_name", "result", "error", "success"}
        self._background: Dict[str, Dict[str, Any]] = {}
        self._pending_hints: List[Dict[str, Any]] = []

    async def run_with_timeout(
        self,
        tool_name: str,
        awaitable_or_factory: Any,
        timeout: Optional[float] = None,
    ) -> Any:
        """带超时执行；超时不取消——同一任务继续在后台跑完，返回 background 信封。

        语义（对标 QP offload）：转后台的必须是**同一个**任务——工厂重建会
        让副作用工具双执行。本方法持有任务引用防止 GC 静默吞掉；观察者协程
        在任务完成后把结果/错误推入 pending hints。

        Args:
            tool_name: 工具名（查超时注册表）
            awaitable_or_factory: 协程/可等待对象，或返回协程的零参工厂
            timeout: 显式超时；None 用注册表

        Returns:
            工具结果；或 background 信封 dict（{"status":"background","task_id",...}）
        """
        effective = timeout if timeout is not None else get_tool_timeout(tool_name)
        aw = awaitable_or_factory() if callable(awaitable_or_factory) else awaitable_or_factory
        task = asyncio.ensure_future(aw)
        done, pending = await asyncio.wait({task}, timeout=effective)

        if not pending:
            return task.result()

        # 超时 → 转后台：同一任务继续（持有引用防 GC 静默吞掉），观察者投递 hint
        task_id = f"bg_{uuid.uuid4().hex[:12]}"
        self._background[task_id] = {
            "task": task,
            "tool_name": tool_name,
            "result": None,
            "error": None,
            "success": None,
        }
        asyncio.ensure_future(self._observe_background(tool_name, task_id, task))
        logger.info(
            "工具 %s 超时（%.0fs），转后台继续（task_id=%s）", tool_name, effective, task_id
        )
        return {
            "status": "background",
            "task_id": task_id,
            "tool_name": tool_name,
            "message": (
                f"工具 {tool_name} 执行超时，已转入后台继续运行；"
                f"完成后结果将注入后续上下文（task_id={task_id}）"
            ),
        }

    async def _observe_background(self, tool_name: str, task_id: str, task: asyncio.Future) -> None:
        entry = self._background.get(task_id)
        if entry is None:
            return
        try:
            entry["result"] = await task
            entry["success"] = True
            self._pending_hints.append({
                "task_id": task_id,
                "tool_name": tool_name,
                "success": True,
                "result": entry["result"],
            })
        except asyncio.CancelledError:
            entry["success"] = False
            entry["error"] = "cancelled"
        except Exception as e:
            entry["error"] = str(e)
            entry["success"] = False
            self._pending_hints.append({
                "task_id": task_id,
                "tool_name": tool_name,
                "success": False,
                "error": str(e),
            })
            logger.warning("后台工具 %s (%s) 失败: %s", tool_name, task_id, e)
        finally:
            entry["task"] = None

    def pop_pending_hints(self) -> List[Dict[str, Any]]:
        """取走全部已完成的后台提示（清空）——注入下一轮 LLM 上下文。"""
        hints = self._pending_hints
        self._pending_hints = []
        return hints

    def get_background_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询后台任务状态（运行中/已完成/未知）。"""
        entry = self._background.get(task_id)
        if entry is None:
            return None
        return {
            "task_id": task_id,
            "tool_name": entry["tool_name"],
            "running": entry["task"] is not None,
            "success": entry["success"],
        }
