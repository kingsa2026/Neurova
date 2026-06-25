"""
NEURON 系统 API 端点

提供依赖图谱、级联推理、缺失推理等 API 接口。
"""

from neurova.core.logger import get_logger
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(prefix="/neuron", tags=["neuron"])

# 共享的依赖图谱实例（线程安全）
_shared_graph = None
_shared_graph_lock = threading.Lock()


def get_shared_graph():
    """获取共享的依赖图谱实例（线程安全）"""
    global _shared_graph
    if _shared_graph is None:
        with _shared_graph_lock:
            if _shared_graph is None:
                from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyGraph
                _shared_graph = DependencyGraph()
    return _shared_graph


def reset_shared_graph():
    """重置共享图谱（用于测试）"""
    global _shared_graph
    with _shared_graph_lock:
        _shared_graph = None


# ============ 数据模型 ============

class EntityCreate(BaseModel):
    """创建实体请求"""
    name: str = Field(..., description="实体名称")
    entity_type: str = Field(..., description="实体类型")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class DependencyCreate(BaseModel):
    """创建依赖关系请求"""
    source_id: str = Field(..., description="源实体ID")
    target_id: str = Field(..., description="目标实体ID")
    dep_type: str = Field(..., description="依赖类型")
    confidence: float = Field(default=1.0, description="置信度")


class CascadeRequest(BaseModel):
    """级联推理请求"""
    entity_id: str = Field(..., description="实体ID")
    direction: str = Field(default="forward", description="方向: forward/backward")
    max_depth: int = Field(default=5, description="最大深度")


class AbsenceCheckRequest(BaseModel):
    """缺失检测请求"""
    expected_entity: str = Field(..., description="期望实体")
    expected_relation: str = Field(..., description="期望关系类型")
    context_entities: List[str] = Field(default_factory=list, description="上下文实体")


class DependencyExtractRequest(BaseModel):
    """依赖提取请求"""
    memory_id: str = Field(..., description="记忆ID")
    content: str = Field(..., description="文本内容")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


# ============ 依赖图谱 API ============

@router.get("/entities")
async def list_entities(
    entity_type: Optional[str] = Query(None, description="实体类型过滤"),
    limit: int = Query(100, description="返回数量限制"),
) -> Dict[str, Any]:
    """获取实体列表"""
    try:
        graph = get_shared_graph()
        entities = list(graph.entities.values())
        
        if entity_type:
            entities = [e for e in entities if e.entity_type == entity_type]
        
        # Ensure limit is an integer (handle Query object case)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 100
        
        return {
            "success": True,
            "data": [e.__dict__ for e in entities[:limit]],
            "total": len(entities),
        }
    except Exception as e:
        logger.error("获取实体列表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities")
async def create_entity(request: EntityCreate) -> Dict[str, Any]:
    """创建实体"""
    try:
        from neurova.cognitive_layers.memory_layer.dependency_graph import EntityNode
        
        graph = get_shared_graph()
        entity = EntityNode(
            id=f"entity_{hash(request.name) % 10000}",
            name=request.name,
            entity_type=request.entity_type,
            metadata=request.metadata,
        )
        graph.add_entity(entity)
        
        return {
            "success": True,
            "data": entity.__dict__,
            "message": f"实体 '{request.name}' 创建成功",
        }
    except Exception as e:
        logger.error("创建实体失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dependencies")
async def create_dependency(request: DependencyCreate) -> Dict[str, Any]:
    """创建依赖关系"""
    try:
        from neurova.cognitive_layers.memory_layer.dependency_graph import (
            DependencyEdge, DependencyType,
        )
        
        graph = get_shared_graph()
        edge = DependencyEdge(
            id=f"dep_{request.source_id}_{request.target_id}",
            source_id=request.source_id,
            target_id=request.target_id,
            dep_type=DependencyType(request.dep_type),
            confidence=request.confidence,
        )
        graph.add_dependency(edge)
        
        return {
            "success": True,
            "data": edge.__dict__,
            "message": "依赖关系创建成功",
        }
    except Exception as e:
        logger.error("创建依赖关系失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dependencies/{entity_id}")
async def get_entity_dependencies(
    entity_id: str,
    direction: str = Query("both", description="方向: downstream/upstream/both"),
    max_depth: int = Query(5, description="最大深度"),
) -> Dict[str, Any]:
    """获取实体的依赖关系"""
    try:
        graph = get_shared_graph()
        result = {"entity_id": entity_id, "downstream": [], "upstream": []}
        
        if direction in ("downstream", "both"):
            result["downstream"] = graph.get_downstream(entity_id, max_depth)
        
        if direction in ("upstream", "both"):
            result["upstream"] = graph.get_upstream(entity_id, max_depth)
        
        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        logger.error("获取依赖关系失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ 级联推理 API ============

@router.post("/cascade")
async def cascade_reasoning(request: CascadeRequest) -> Dict[str, Any]:
    """级联推理"""
    try:
        from neurova.cognitive_layers.memory_layer.cascade_engine import (
            CascadeEngine, CascadeDirection,
        )
        
        graph = get_shared_graph()
        engine = CascadeEngine(graph)
        
        if request.direction == "forward":
            result = engine.forward_cascade(request.entity_id, request.max_depth)
        else:
            result = engine.backward_cascade(request.entity_id, request.max_depth)
        
        return {
            "success": True,
            "data": {
                "source_entity": result.source_entity,
                "direction": result.direction.value,
                "total_affected": result.total_affected,
                "confidence": result.confidence,
                "effects": [
                    {
                        "entity_id": e.entity_id,
                        "effect_type": e.effect_type,
                        "confidence": e.confidence,
                    }
                    for e in result.effects
                ],
                "reasoning_chain": result.reasoning_chain,
            },
        }
    except Exception as e:
        logger.error("级联推理失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/would-affect")
async def would_affect(
    source_id: str = Query(..., description="源实体ID"),
    target_id: str = Query(..., description="目标实体ID"),
    threshold: float = Query(0.5, description="置信度阈值"),
) -> Dict[str, Any]:
    """判断源实体变化是否会影响目标实体"""
    try:
        from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
        
        graph = get_shared_graph()
        engine = CascadeEngine(graph)
        result = engine.would_affect(source_id, target_id, threshold)
        
        return {
            "success": True,
            "data": result,
        }
    except Exception as e:
        logger.error("判断影响失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ 缺失推理 API ============

@router.post("/absence/detect")
async def detect_absence(request: AbsenceCheckRequest) -> Dict[str, Any]:
    """检测缺失"""
    try:
        from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
        from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyType
        
        graph = get_shared_graph()
        reasoner = AbsenceReasoner(graph)
        result = reasoner.detect_absence(
            expected_entity=request.expected_entity,
            expected_relation=DependencyType(request.expected_relation),
            context_entities=request.context_entities,
        )
        
        return {
            "success": True,
            "data": {
                "is_absent": result.is_absent,
                "entity_exists": result.entity_exists,
                "relation_exists": result.relation_exists,
                "context_has_dependency": result.context_has_dependency,
                "confidence": result.confidence,
                "explanation": result.explanation,
                "suggestions": result.suggestions,
            },
        }
    except Exception as e:
        logger.error("缺失检测失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ 依赖提取 API ============

@router.post("/extract")
async def extract_dependencies(request: DependencyExtractRequest) -> Dict[str, Any]:
    """从记忆中提取依赖关系"""
    try:
        from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import (
            MOEDependencyExtractor,
        )
        
        graph = get_shared_graph()
        extractor = MOEDependencyExtractor(dependency_graph=graph)
        dependencies = await extractor.extract_from_memory(
            memory_id=request.memory_id,
            content=request.content,
            metadata=request.metadata,
        )
        
        return {
            "success": True,
            "data": [
                {
                    "source": dep.source_entity,
                    "target": dep.target_entity,
                    "dep_type": dep.dep_type.value,
                    "confidence": dep.confidence,
                    "evidence": dep.evidence_text,
                }
                for dep in dependencies
            ],
            "total": len(dependencies),
        }
    except Exception as e:
        logger.error("依赖提取失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ============ 统计 API ============

@router.get("/stats")
async def get_neuron_stats() -> Dict[str, Any]:
    """获取 NEURON 系统统计"""
    try:
        graph = get_shared_graph()
        
        return {
            "success": True,
            "data": {
                "total_entities": len(graph.entities),
                "total_edges": len(graph.edges),
                "entity_types": len(set(e.entity_type for e in graph.entities.values())),
                "dependency_types": len(set(e.dep_type.value for e in graph.edges)),
            },
        }
    except Exception as e:
        logger.error("获取统计失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def neuron_health() -> Dict[str, Any]:
    """NEURON 系统健康检查"""
    try:
        graph = get_shared_graph()
        
        return {
            "success": True,
            "status": "healthy",
            "components": {
                "dependency_graph": "ok",
                "cascade_engine": "ok",
                "absence_reasoner": "ok",
                "moe_extractor": "ok",
            },
            "stats": {
                "entities": len(graph.entities),
                "edges": len(graph.edges),
            },
        }
    except Exception as e:
        logger.error("健康检查失败: %s", e)
        return {
            "success": False,
            "status": "unhealthy",
            "error": str(e),
        }
