"""
AutoContextModule — 自动上下文模块

自动构建和管理对话上下文
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AutoContextModule:
    """
    自动上下文模块

    自动构建和管理对话上下文，支持：
    - 上下文压缩
    - 上下文摘要
    - 上下文切换
    """

    def __init__(
        self,
        max_context_length: int = 4000,
        compression_threshold: float = 0.8,
    ):
        """
        Args:
            max_context_length: 最大上下文长度
            compression_threshold: 压缩阈值
        """
        self._max_context_length = max_context_length
        self._compression_threshold = compression_threshold

        self._lock = threading.RLock()
        self._initialized = False

        # 当前上下文
        self._current_context: List[Dict[str, Any]] = []
        self._context_length: int = 0

        # 上下文历史
        self._context_history: List[Dict[str, Any]] = []

        # 摘要缓存
        self._summaries: Dict[str, str] = {}

    @property
    def name(self) -> str:
        """模块名称"""
        return "auto_context_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("AutoContextModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("AutoContextModule shutdown")

    def add_to_context(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        添加到上下文

        Args:
            role: 角色
            content: 内容
            metadata: 额外元数据

        Returns:
            是否添加成功
        """
        with self._lock:
            entry = {
                "role": role,
                "content": content,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }

            self._current_context.append(entry)
            self._context_length += len(content)

            # 检查是否需要压缩
            if self._context_length > self._max_context_length * self._compression_threshold:
                self._compress_context()

            return True

    def get_context(self, max_length: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取当前上下文

        Args:
            max_length: 最大长度限制

        Returns:
            上下文列表
        """
        with self._lock:
            if max_length is None:
                return list(self._current_context)

            # 返回最近的上下文
            result = []
            current_length = 0

            for entry in reversed(self._current_context):
                content_length = len(entry.get("content", ""))
                if current_length + content_length > max_length:
                    break
                result.insert(0, entry)
                current_length += content_length

            return result

    def get_context_string(self, max_length: Optional[int] = None) -> str:
        """获取上下文字符串"""
        context = self.get_context(max_length)
        return "\n".join(f"{entry['role']}: {entry['content']}" for entry in context)

    def clear_context(self) -> int:
        """清空上下文"""
        with self._lock:
            if self._current_context:
                self._context_history.append(
                    {
                        "context": list(self._current_context),
                        "cleared_at": time.time(),
                    }
                )

            count = len(self._current_context)
            self._current_context.clear()
            self._context_length = 0

            return count

    def summarize_context(self) -> str:
        """生成上下文摘要"""
        with self._lock:
            if not self._current_context:
                return ""

            # 简单摘要：提取关键信息
            user_messages = [entry["content"] for entry in self._current_context if entry["role"] == "user"]

            assistant_messages = [entry["content"] for entry in self._current_context if entry["role"] == "assistant"]

            summary_parts = []

            if user_messages:
                summary_parts.append(f"用户消息: {len(user_messages)} 条")
                # 最后一条用户消息
                last_user = user_messages[-1]
                if len(last_user) > 100:
                    last_user = last_user[:100] + "..."
                summary_parts.append(f"最新用户消息: {last_user}")

            if assistant_messages:
                summary_parts.append(f"助手回复: {len(assistant_messages)} 条")

            summary = "; ".join(summary_parts)

            # 缓存摘要
            cache_key = f"context_{int(time.time())}"
            self._summaries[cache_key] = summary

            return summary

    def switch_context(self, context_id: str) -> bool:
        """切换上下文"""
        with self._lock:
            # 保存当前上下文
            if self._current_context:
                self._context_history.append(
                    {
                        "context_id": context_id,
                        "context": list(self._current_context),
                        "saved_at": time.time(),
                    }
                )

            # 清空当前上下文
            self._current_context.clear()
            self._context_length = 0

            return True

    def restore_context(self, context_id: str) -> bool:
        """恢复上下文"""
        with self._lock:
            for entry in reversed(self._context_history):
                if entry.get("context_id") == context_id:
                    self._current_context = list(entry["context"])
                    self._context_length = sum(len(e.get("content", "")) for e in self._current_context)
                    return True

            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "current_length": self._context_length,
                "max_length": self._max_context_length,
                "utilization": self._context_length / self._max_context_length if self._max_context_length else 0,
                "message_count": len(self._current_context),
                "history_count": len(self._context_history),
                "summaries_count": len(self._summaries),
            }

    def _compress_context(self) -> None:
        """压缩上下文"""
        if len(self._current_context) <= 2:
            return

        # 保留最新的消息，压缩旧消息
        half = len(self._current_context) // 2
        old_context = self._current_context[:half]
        new_context = self._current_context[half:]

        # 生成旧上下文的摘要
        summary = self._summarize_entries(old_context)

        # 用摘要替换旧上下文
        self._current_context = [
            {"role": "system", "content": f"[历史摘要] {summary}", "timestamp": time.time()}
        ] + new_context

        # 重新计算长度
        self._context_length = sum(len(entry.get("content", "")) for entry in self._current_context)

    def _summarize_entries(self, entries: List[Dict[str, Any]]) -> str:
        """生成条目摘要"""
        if not entries:
            return ""

        user_count = sum(1 for e in entries if e["role"] == "user")
        assistant_count = sum(1 for e in entries if e["role"] == "assistant")

        return f"共 {len(entries)} 条消息（用户 {user_count} 条，助手 {assistant_count} 条）"
