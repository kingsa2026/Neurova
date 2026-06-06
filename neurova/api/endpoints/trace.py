from __future__ import annotations

"""
轨迹追踪接口 - Trace Endpoint

功能:
1. 获取轨迹列表 (GET /api/v1/trace)
2. 获取轨迹详情 (GET /api/v1/trace/{id})
3. 获取轨迹事件 (GET /api/v1/trace/{id}/events)
4. 获取轨迹统计 (GET /api/v1/trace/stats)
"""

import logging
import time
import threading
import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class TraceItem(BaseModel):
    """轨迹条目"""
    trace_id: str
    agent_id: str
    session_id: Optional[str] = None
    start_time: float
    end_time: Optional[float] = None
    duration: float = 0.0
    status: str = "active"
    event_count: int = 0
    span_count: int = 0


@dataclass
class TraceData:
    """轨迹数据结构"""
    trace_id: str
    agent_id: str
    session_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration: float = 0.0
    status: str = "active"
    events: List[Dict[str, Any]] = field(default_factory=list)
    spans: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TraceManager:
    """轨迹管理器（内存存储）"""
    
    def __init__(self):
        """初始化轨迹管理器"""
        self._traces: Dict[str, TraceData] = {}
        self._agent_traces: Dict[str, List[str]] = {}  # agent_id -> trace_ids
        self._lock = threading.RLock()
    
    def start_trace(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceData:
        """开始一个轨迹"""
        with self._lock:
            trace_id = str(uuid.uuid4())
            trace = TraceData(
                trace_id=trace_id,
                agent_id=agent_id,
                session_id=session_id,
                start_time=time.time(),
                status="active",
                metadata=metadata or {},
            )
            
            self._traces[trace_id] = trace
            
            # 添加到agent索引
            if agent_id not in self._agent_traces:
                self._agent_traces[agent_id] = []
            self._agent_traces[agent_id].append(trace_id)
            
            return trace
    
    def add_event(
        self,
        trace_id: str,
        event_type: str = "info",
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """添加事件到轨迹"""
        with self._lock:
            trace = self._traces.get(trace_id)
            if not trace:
                return False
            
            event = {
                "event_id": str(uuid.uuid4()),
                "trace_id": trace_id,
                "timestamp": time.time(),
                "event_type": event_type,
                "message": message,
                "data": data or {},
            }
            
            trace.events.append(event)
            return True
    
    def add_span(
        self,
        trace_id: str,
        span_name: str,
        start_time: float,
        end_time: float,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """添加跨度到轨迹"""
        with self._lock:
            trace = self._traces.get(trace_id)
            if not trace:
                return False
            
            span = {
                "span_id": str(uuid.uuid4()),
                "trace_id": trace_id,
                "name": span_name,
                "start_time": start_time,
                "end_time": end_time,
                "duration": end_time - start_time,
                "data": data or {},
            }
            
            trace.spans.append(span)
            return True
    
    def finish_trace(self, trace_id: str) -> bool:
        """完成轨迹"""
        with self._lock:
            trace = self._traces.get(trace_id)
            if not trace:
                return False
            
            trace.end_time = time.time()
            trace.duration = trace.end_time - trace.start_time
            trace.status = "completed"
            return True
    
    def get_trace(self, trace_id: str) -> Optional[TraceData]:
        """获取轨迹"""
        return self._traces.get(trace_id)
    
    def get_agent_traces(
        self,
        agent_id: str,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[TraceData]:
        """获取agent的轨迹"""
        with self._lock:
            trace_ids = self._agent_traces.get(agent_id, [])
            traces = []
            
            for tid in trace_ids:
                if tid in self._traces:
                    trace = self._traces[tid]
                    
                    # 应用状态过滤
                    if status and trace.status != status:
                        continue
                    
                    traces.append(trace)
            
            # 按开始时间倒序排序
            traces.sort(key=lambda t: t.start_time, reverse=True)
            
            # 应用分页
            return traces[offset:offset + limit]
    
    def get_trace_events(
        self,
        trace_id: str,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取轨迹事件"""
        with self._lock:
            trace = self._traces.get(trace_id)
            if not trace:
                return []
            
            events = trace.events
            
            # 应用事件类型过滤
            if event_type:
                events = [e for e in events if e["event_type"] == event_type]
            
            # 按时间排序
            events.sort(key=lambda e: e["timestamp"])
            
            # 应用限制
            return events[:limit]
    
    def get_trace_stats(self, agent_id: str) -> Dict[str, Any]:
        """获取轨迹统计"""
        with self._lock:
            trace_ids = self._agent_traces.get(agent_id, [])
            traces = [self._traces[tid] for tid in trace_ids if tid in self._traces]
            
            if not traces:
                return {
                    "total_traces": 0,
                    "active_traces": 0,
                    "average_duration": 0,
                    "total_events": 0,
                    "event_types": {},
                }
            
            # 计算统计
            total_traces = len(traces)
            active_traces = sum(1 for t in traces if t.status == "active")
            completed_traces = [t for t in traces if t.status == "completed"]
            
            # 计算平均时长
            if completed_traces:
                avg_duration = sum(t.duration for t in completed_traces) / len(completed_traces)
            else:
                avg_duration = 0
            
            # 计算事件总数和类型
            total_events = 0
            event_types = {}
            
            for trace in traces:
                total_events += len(trace.events)
                for event in trace.events:
                    event_type = event["event_type"]
                    event_types[event_type] = event_types.get(event_type, 0) + 1
            
            return {
                "total_traces": total_traces,
                "active_traces": active_traces,
                "average_duration": avg_duration,
                "total_events": total_events,
                "event_types": event_types,
            }


# 全局轨迹管理器单例
_trace_manager: Optional[TraceManager] = None
_manager_lock = threading.Lock()


def get_trace_manager() -> TraceManager:
    """获取全局轨迹管理器单例"""
    global _trace_manager
    if _trace_manager is None:
        with _manager_lock:
            if _trace_manager is None:
                _trace_manager = TraceManager()
    return _trace_manager


def reset_trace_manager() -> None:
    """重置全局轨迹管理器（用于测试）"""
    global _trace_manager
    with _manager_lock:
        _trace_manager = None


class TraceEvent(BaseModel):
    """轨迹事件"""
    event_id: str
    trace_id: str
    timestamp: float
    event_type: str = "info"
    message: str = ""
    data: Dict[str, Any] = {}


class TraceStats(BaseModel):
    """轨迹统计"""
    total_traces: int = 0
    active_traces: int = 0
    average_duration: float = 0
    total_events: int = 0
    event_types: Dict[str, int] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance
    return get_agent_instance(agent_id)


def _convert_trace_data_to_item(trace: TraceData) -> TraceItem:
    """将TraceData转换为API响应格式"""
    return TraceItem(
        trace_id=trace.trace_id,
        agent_id=trace.agent_id,
        session_id=trace.session_id,
        start_time=trace.start_time,
        end_time=trace.end_time,
        duration=trace.duration,
        status=trace.status,
        event_count=len(trace.events),
        span_count=len(trace.spans),
    )


@router.get("", response_model=List[TraceItem])
async def get_traces(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取轨迹列表"""
    try:
        # 获取轨迹管理器
        manager = get_trace_manager()
        
        # 获取轨迹列表
        traces = manager.get_agent_traces(
            agent_id=agent_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        
        # 转换为API格式
        return [_convert_trace_data_to_item(trace) for trace in traces]
        
    except Exception as e:
        logger.exception(f"Failed to get traces: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get traces: {str(e)}"
        )


@router.get("/stats", response_model=TraceStats)
async def get_trace_stats(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取轨迹统计"""
    try:
        # 获取轨迹管理器
        manager = get_trace_manager()
        
        # 获取轨迹统计
        stats = manager.get_trace_stats(agent_id)
        
        return TraceStats(
            total_traces=stats["total_traces"],
            active_traces=stats["active_traces"],
            average_duration=stats["average_duration"],
            total_events=stats["total_events"],
            event_types=stats["event_types"],
        )
        
    except Exception as e:
        logger.exception(f"Failed to get trace stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trace stats: {str(e)}"
        )


@router.get("/{trace_id}", response_model=TraceItem)
async def get_trace(
    request: Request,
    trace_id: str = Path(..., description="轨迹ID"),
):
    """获取单个轨迹详情"""
    try:
        # 获取轨迹管理器
        manager = get_trace_manager()
        
        # 获取轨迹
        trace = manager.get_trace(trace_id)
        
        if not trace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trace '{trace_id}' not found"
            )
        
        return _convert_trace_data_to_item(trace)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get trace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trace: {str(e)}"
        )


@router.get("/{trace_id}/events", response_model=List[TraceEvent])
async def get_trace_events(
    request: Request,
    trace_id: str = Path(..., description="轨迹ID"),
    event_type: Optional[str] = Query(default=None, description="事件类型筛选"),
    limit: int = Query(default=50, ge=1, le=500, description="数量限制"),
):
    """获取轨迹事件"""
    try:
        # 获取轨迹管理器
        manager = get_trace_manager()
        
        # 检查轨迹是否存在
        trace = manager.get_trace(trace_id)
        if not trace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trace '{trace_id}' not found"
            )
        
        # 获取事件
        events = manager.get_trace_events(
            trace_id=trace_id,
            event_type=event_type,
            limit=limit,
        )
        
        # 转换为API格式
        result = []
        for event in events:
            trace_event = TraceEvent(
                event_id=event["event_id"],
                trace_id=event["trace_id"],
                timestamp=event["timestamp"],
                event_type=event["event_type"],
                message=event["message"],
                data=event["data"],
            )
            result.append(trace_event)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get trace events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trace events: {str(e)}"
        )
