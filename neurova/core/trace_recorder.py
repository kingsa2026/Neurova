"""
轨迹记录器

记录 Agent 执行过程中的所有关键事件，支持保存和回放。
"""

import json
from neurova.core.logger import get_logger
from neurova.core.trace_context import clear_trace_id, set_trace_id
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.trace_models import (
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventType,
    TrajectorySpan,
)

logger = get_logger(__name__)


class TrajectoryRecorder:
    """轨迹记录器（单例模式）

    记录 Agent 执行过程中的所有关键事件，支持保存和回放。
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._active_traces: Dict[str, Trajectory] = {}
        self._active_spans: Dict[str, TrajectorySpan] = {}
        self._storage_dir = Path("trajectories")
        self._storage_dir.mkdir(exist_ok=True)
        self._enabled = True
        self._auto_save = True
        self._max_traces_in_memory = 100
        self._saved_traces: List[Dict[str, Any]] = []
        self._load_saved_traces_index()

    def _load_saved_traces_index(self):
        """加载已保存的轨迹索引"""
        index_file = self._storage_dir / "index.json"
        if index_file.exists():
            try:
                with open(index_file, "r") as f:
                    self._saved_traces = json.load(f)
                logger.info("Loaded %s saved traces", len(self._saved_traces))
            except Exception as e:
                logger.error("Failed to load traces index: %s", e)

    def _save_traces_index(self):
        """保存轨迹索引"""
        index_file = self._storage_dir / "index.json"
        try:
            with open(index_file, "w") as f:
                json.dump(self._saved_traces, f, indent=2)
        except Exception as e:
            logger.error("Failed to save traces index: %s", e)

    def start_trace(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """开始一个新的轨迹"""
        if not self._enabled:
            return ""

        trace = Trajectory(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            metadata=metadata or {},
        )

        # 创建根 span
        root_span = TrajectorySpan(
            operation_name="session",
            operation_type="session",
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
        )
        trace.add_span(root_span)
        trace.root_span = root_span

        self._active_traces[trace.trace_id] = trace
        self._active_spans[root_span.span_id] = root_span

        # 按用户分组存储
        if not hasattr(self, "_active_traces_by_user"):
            self._active_traces_by_user = defaultdict(list)
        self._active_traces_by_user[user_id].append(trace.trace_id)

        logger.info("Started trace %s for session %s", trace.trace_id, session_id)
        # 当前上下文绑定 trace_id（logger 的 JSON 输出自动携带，补课 1.1）
        set_trace_id(trace.trace_id)
        return trace.trace_id

    def end_trace(self, trace_id: str) -> None:
        """结束一个轨迹"""
        if trace_id not in self._active_traces:
            logger.warning("Trace %s not found in active traces", trace_id)
            return

        trace = self._active_traces[trace_id]

        # 结束所有活跃的 span
        for span in list(trace.spans.values()):
            if span.status == "running":
                span.end(status="completed")

        trace.end()
        logger.info("Ended trace %s, duration: %.2fms", trace_id, trace.total_duration_ms)

        # 自动保存
        if self._auto_save:
            self.save_trace(trace_id)

        # 资源修复: end_trace 后立即从活动注册表移除。
        # 原实现只删文件不删内存, 每轮对话泄漏一个完整轨迹对象
        # (active_traces/active_spans/active_traces_by_user 三处都只增不减)。
        for span_id in list(trace.spans.keys()):
            self._active_spans.pop(span_id, None)
        self._active_traces.pop(trace_id, None)
        if hasattr(self, "_active_traces_by_user"):
            by_user = self._active_traces_by_user.get(trace.user_id)
            if by_user and trace_id in by_user:
                by_user.remove(trace_id)
                if not by_user:
                    self._active_traces_by_user.pop(trace.user_id, None)
        clear_trace_id()

    def start_span(
        self,
        trace_id: str,
        operation_name: str,
        operation_type: str,
        parent_span_id: Optional[str] = None,
    ) -> Optional[str]:
        """开始一个新的 span"""
        if not self._enabled:
            return None

        if trace_id not in self._active_traces:
            logger.warning("Trace %s not found", trace_id)
            return None

        trace = self._active_traces[trace_id]

        span = TrajectorySpan(
            operation_name=operation_name,
            operation_type=operation_type,
            parent_span_id=parent_span_id,
            session_id=trace.session_id,
            agent_id=trace.agent_id,
            user_id=trace.user_id,
        )

        trace.add_span(span)
        self._active_spans[span.span_id] = span

        logger.debug("Started span %s (%s)", span.span_id, operation_name)
        return span.span_id

    def end_span(
        self,
        span_id: str,
        status: str = "completed",
        error_message: Optional[str] = None,
    ) -> None:
        """结束一个 span"""
        if span_id in self._active_spans:
            span = self._active_spans[span_id]
            span.end(status=status, error_message=error_message)
            logger.debug("Ended span %s, status: %s", span_id, status)

    def record_event(
        self,
        trace_id: str,
        event_type: TrajectoryEventType,
        data: Optional[Dict[str, Any]] = None,
        span_id: Optional[str] = None,
    ) -> None:
        """记录一个事件"""
        if not self._enabled:
            return

        if trace_id not in self._active_traces:
            return

        trace = self._active_traces[trace_id]

        # 找到目标 span
        target_span = None
        if span_id and span_id in self._active_spans:
            target_span = self._active_spans[span_id]
        else:
            # 找到最近活跃的 span
            for span in reversed(list(trace.spans.values())):
                if span.status == "running":
                    target_span = span
                    break

        if target_span is None:
            return

        event = TrajectoryEvent(
            event_type=event_type,
            data=data or {},
            session_id=trace.session_id,
            agent_id=trace.agent_id,
            user_id=trace.user_id,
            trace_id=trace_id,
            span_id=target_span.span_id,
        )

        target_span.add_event(event)

    def record_llm_call(
        self,
        trace_id: str,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """记录 LLM 调用"""
        self.record_event(
            trace_id,
            TrajectoryEventType.LLM_CALL_END,
            data={
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    def record_tool_call(
        self,
        trace_id: str,
        tool_name: str,
        tool_source: str,
        parameters: Dict[str, Any],
        execution_time: float = 0.0,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> None:
        """记录工具调用"""
        event_type = TrajectoryEventType.TOOL_CALL_END if success else TrajectoryEventType.TOOL_CALL_ERROR
        self.record_event(
            trace_id,
            event_type,
            data={
                "tool_name": tool_name,
                "tool_source": tool_source,
                "parameters": parameters,
                "execution_time": execution_time,
                "success": success,
                "error_message": error_message,
            },
        )

    def save_trace(self, trace_id: str, file_path: Optional[str] = None) -> Optional[str]:
        """保存轨迹到文件"""
        if trace_id not in self._active_traces:
            logger.error("Trace %s not found", trace_id)
            return None

        trace = self._active_traces[trace_id]

        # 确定保存路径
        if file_path:
            save_path = Path(file_path)
        else:
            user_id = trace.user_id or "unknown"
            agent_id = trace.agent_id or "unknown"
            session_id = trace.session_id or "unknown"
            trace_dir = self._storage_dir / user_id / agent_id / session_id
            trace_dir.mkdir(parents=True, exist_ok=True)
            save_path = trace_dir / f"{trace_id}.json"

        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(trace.to_dict(), f, indent=2, ensure_ascii=False)

            # 更新索引
            self._saved_traces.append(
                {
                    "trace_id": trace_id,
                    "file_path": str(save_path),
                    "user_id": trace.user_id,
                    "agent_id": trace.agent_id,
                    "session_id": trace.session_id,
                    "created_at": trace.start_time,
                }
            )
            # 资源修复: _max_traces_in_memory 此前定义却无人消费,
            # 索引无限增长并每次全量重写 index.json。超限丢最老条目。
            if len(self._saved_traces) > self._max_traces_in_memory:
                self._saved_traces = self._saved_traces[-self._max_traces_in_memory:]
            self._save_traces_index()

            logger.info("Saved trace %s to %s", trace_id, save_path)
            return str(save_path)
        except Exception as e:
            logger.error("Failed to save trace %s: %s", trace_id, e)
            return None

    def load_trace(self, trace_id: str, user_id: Optional[str] = None) -> Optional[Trajectory]:
        """从文件加载轨迹"""
        # 检查内存缓存
        if trace_id in self._active_traces:
            trace = self._active_traces[trace_id]
            if user_id and trace.user_id != user_id:
                logger.warning("Trace %s belongs to user %s, not %s", trace_id, trace.user_id, user_id)
                return None
            return trace

        # 从文件加载
        if not self._storage_dir.exists():
            return None

        for dirpath in self._storage_dir.iterdir():
            if not dirpath.is_dir():
                continue
            for subpath in dirpath.rglob("*"):
                if subpath.is_dir():
                    trace_file = subpath / f"{trace_id}.json"
                    if trace_file.exists():
                        try:
                            with open(trace_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            trace = Trajectory.from_dict(data)
                            if user_id and trace.user_id != user_id:
                                logger.warning("Trace %s belongs to user %s, not %s", trace_id, trace.user_id, user_id)
                                return None
                            return trace
                        except Exception as e:
                            logger.error("Failed to load trace %s: %s", trace_id, e)
                            return None
        return None

    def list_traces(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出已保存的轨迹"""
        traces = []
        if not self._storage_dir.exists():
            return traces

        for dirpath in self._storage_dir.iterdir():
            if not dirpath.is_dir():
                continue
            for subpath in dirpath.rglob("*"):
                if subpath.is_dir():
                    for trace_file in subpath.glob("*.json"):
                        if trace_file.name == "index.json":
                            continue
                        try:
                            with open(trace_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            trace = Trajectory.from_dict(data)

                            # 过滤条件
                            if user_id and trace.user_id != user_id:
                                continue
                            if agent_id and trace.agent_id != agent_id:
                                continue
                            if session_id and trace.session_id != session_id:
                                continue

                            traces.append(
                                {
                                    "trace_id": trace.trace_id,
                                    "file_path": str(trace_file),
                                    "user_id": trace.user_id,
                                    "agent_id": trace.agent_id,
                                    "session_id": trace.session_id,
                                    "created_at": trace.start_time,
                                    "duration_ms": trace.total_duration_ms,
                                }
                            )

                            if len(traces) >= limit:
                                return traces
                        except Exception as e:
                            logger.error("Failed to read trace file %s: %s", trace_file, e)
        return traces

    def delete_trace(self, trace_id: str, user_id: Optional[str] = None) -> bool:
        """删除轨迹"""
        # 从活跃轨迹中删除
        if trace_id in self._active_traces:
            trace = self._active_traces[trace_id]
            if user_id and trace.user_id != user_id:
                logger.warning("Trace %s belongs to user %s, not %s", trace_id, trace.user_id, user_id)
                return False
            del self._active_traces[trace_id]

        # 从文件中删除
        trace_info = None
        for info in self._saved_traces:
            if info["trace_id"] == trace_id:
                trace_info = info
                break

        if trace_info:
            file_path = Path(trace_info["file_path"])
            if file_path.exists():
                try:
                    file_path.unlink()
                    logger.info("Deleted trace file %s", file_path)
                except Exception as e:
                    logger.error("Failed to delete trace file %s: %s", file_path, e)
                    return False

            self._saved_traces.remove(trace_info)
            self._save_traces_index()

        # 从用户索引中删除
        if hasattr(self, "_active_traces_by_user") and user_id:
            if user_id in self._active_traces_by_user:
                if trace_id in self._active_traces_by_user[user_id]:
                    self._active_traces_by_user[user_id].remove(trace_id)

        return True

    def replay_trace(
        self,
        trace_id: str,
        speed: float = 1.0,
        callback: Optional[callable] = None,
    ) -> None:
        """回放轨迹"""
        trace = self.load_trace(trace_id)
        if not trace:
            logger.error("Cannot load trace %s", trace_id)
            return

        logger.info("Replaying trace %s, %s spans", trace_id, len(trace.spans))

        # 收集所有事件并按时间排序
        all_events = []
        for span in trace.spans.values():
            for event in span.events:
                all_events.append(event)
        all_events.sort(key=lambda e: e.timestamp)

        # 回放事件
        for event in all_events:
            if callback:
                callback(event)
            # 模拟延迟（可选）
            if speed > 0:
                import time

                time.sleep(0.1 / speed)

    def set_enabled(self, enabled: bool) -> None:
        """设置启用状态"""
        self._enabled = enabled
        logger.info("Trajectory recorder %s", 'enabled' if enabled else 'disabled')

    def set_auto_save(self, auto_save: bool) -> None:
        """设置自动保存"""
        self._auto_save = auto_save

    def set_storage_dir(self, directory: str) -> None:
        """设置存储目录"""
        self._storage_dir = Path(directory)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Trajectory storage directory set to %s", self._storage_dir)

    def get_status(self) -> Dict[str, Any]:
        """获取状态信息"""
        return {
            "enabled": self._enabled,
            "auto_save": self._auto_save,
            "storage_dir": str(self._storage_dir),
            "active_traces": len(self._active_traces),
            "active_spans": len(self._active_spans),
            "saved_traces": len(self._saved_traces),
        }


def get_trajectory_recorder() -> TrajectoryRecorder:
    """获取 TrajectoryRecorder 单例"""
    return TrajectoryRecorder()


__all__ = [
    "TrajectoryRecorder",
    "get_trajectory_recorder",
]
