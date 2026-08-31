# Neurova 记忆系统升级技术文档（详细版）

> **基于 MEEM 基准测试的系统性升级方案**
> **设计日期**：2026年6月13日

---

## 1. 问题分析

### 1.1 MEEM 基准测试发现

| 任务 | 描述 | 现有系统准确率 | 瓶颈原因 |
|------|------|----------------|----------|
| **Cas (Cascade)** | 级联推理 | **3%** | 无依赖图谱 |
| **Abs (Absence)** | 缺失推理 | **1%** | 无"不存在"检测 |

### 1.2 根本原因

```python
# neurova/cognitive_layers/memory_layer/neurova_recall.py:906
def _channel_graph(self, query: str, limit: int) -> List[RecalledMemory]:
    """图通道（关系图谱）"""
    # ❌ 空实现
    logger.debug("图通道检索: %s", query)
    return []
```

---

## 2. 快速开始

### 2.1 安装依赖

```bash
# 进入项目目录
cd E:/项目/Neurova

# 安装Python依赖（如果尚未安装）
pip install -r requirements.txt

# 创建数据目录
mkdir -p data
```

### 2.2 初始化组件

```python
# quick_start.py
from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyGraph
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor

# 1. 初始化依赖图谱（SQLite持久化）
graph = DependencyGraph(db_path="data/dependency_graph.db")

# 2. 初始化级联推理引擎
cascade_engine = CascadeEngine(graph)

# 3. 初始化缺失推理器
absence_reasoner = AbsenceReasoner(graph)

# 4. 初始化MOE依赖提取器（运行时成本$0）
extractor = MOEDependencyExtractor()

print("NEURON组件初始化完成！")
```

### 2.3 运行示例

```bash
# 运行快速开始示例
python quick_start.py

# 运行测试
pytest tests/unit/test_neuron_components.py -v
```

### 2.4 验证安装

```python
# verify_installation.py
import asyncio
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor

async def verify():
    extractor = MOEDependencyExtractor()
    content = "测试文本：部署服务器需要数据库"
    dependencies = await extractor.extract_from_memory(
        memory_id="test_001",
        content=content
    )
    print(f"✓ 依赖提取器工作正常，提取到 {len(dependencies)} 个依赖关系")
    return True

if __name__ == "__main__":
    asyncio.run(verify())
```

---

## 3. 架构设计

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NEURON 架构 (整体视图)                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  用户输入     │───▶│  MOE 依赖    │───▶│  依赖图谱    │          │
│  │  (文本)      │    │  提取器      │    │  (SQLite)    │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                    │                    │                  │
│         ▼                    ▼                    ▼                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  实体提取    │    │  关系分类    │    │  图查询      │          │
│  │  (规则+MOE)  │    │  (规则+向量) │    │  (BFS/DFS)   │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                    │                    │                  │
│         ▼                    ▼                    ▼                  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  级联推理引擎 (CascadeEngine)                 │  │
│  │  正向级联: A变化 → 影响B → 影响C → ...                       │  │
│  │  反向级联: C变化 ← 受B影响 ← 受A影响 ← ...                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                  缺失推理器 (AbsenceReasoner)                 │  │
│  │  检测: 实体缺失? 关系缺失? 上下文依赖缺失?                    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│         │                                                          │
│         ▼                                                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              6通道记忆检索系统 (NeurovaRecallEngine)           │  │
│  │  温度 | 文本 | 分类 | 图谱 | 情感 | 语音                     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 组件依赖关系

```
MOEDependencyExtractor
    ├── EntityExtractor (实体提取)
    ├── RelationClassifier (关系分类)
    ├── DependencyGraph (依赖图谱)
    │   ├── SQLite 持久化
    │   ├── 内存索引
    │   └── 缓存机制
    └── VectorGatingNetwork (MOE向量门控 - 可选)

CascadeEngine
    └── DependencyGraph (依赖图谱)

AbsenceReasoner
    └── DependencyGraph (依赖图谱)

NeurovaRecallEngine
    ├── DependencyGraph (依赖图谱)
    ├── CascadeEngine (级联推理)
    ├── AbsenceReasoner (缺失推理)
    └── MOEDependencyExtractor (依赖提取)
```

### 3.3 数据流

```
存储阶段:
用户输入 → MOEDependencyExtractor.extract_from_memory()
  → EntityExtractor.extract() 提取实体
  → RelationClassifier.classify() 分类关系
  → DependencyGraph.add_entity() 添加实体
  → DependencyGraph.add_dependency() 添加依赖边
  → SQLite 持久化

检索阶段:
查询输入 → NeurovaRecallEngine.recall()
  → _channel_graph() 图通道检索
    → EntityExtractor.extract() 提取查询实体
    → DependencyGraph.get_downstream/upstream() 图查询
    → CascadeEngine.forward_cascade() 级联推理
  → AbsenceReasoner.detect_absence() 缺失检测
  → 多通道融合 → 返回结果
```

---

## 4. 配置说明

### 4.1 全局配置

```python
# neurova/config/neuron_config.py
NEURON_CONFIG = {
    # 依赖图谱配置
    "dependency_graph": {
        "db_path": "data/dependency_graph.db",
        "cache_ttl": 300,  # 缓存过期时间（秒）
        "max_cache_size": 1000,  # 最大缓存条目数
        "enable_wal": True,  # 启用WAL模式提升并发性能
    },
    
    # 级联推理配置
    "cascade_engine": {
        "max_depth": 5,  # 最大级联深度
        "confidence_decay": 0.2,  # 置信度衰减系数
        "timeout_seconds": 5.0,  # 超时时间
    },
    
    # 缺失推理配置
    "absence_reasoner": {
        "min_confidence": 0.3,  # 最小置信度阈值
        "check_context": True,  # 是否检查上下文依赖
    },
    
    # 依赖提取配置
    "dependency_extractor": {
        "use_moe": True,  # 是否使用MOE架构
        "min_entity_confidence": 0.7,  # 最小实体置信度
        "min_relation_confidence": 0.5,  # 最小关系置信度
        "enable_vector_gating": True,  # 是否启用向量门控
    },
    
    # 图通道配置
    "graph_channel": {
        "enabled": True,  # 是否启用图通道
        "weight": 0.10,  # 图通道权重
        "max_entities": 100,  # 最大实体数
    },
}
```

### 4.2 环境变量配置

```bash
# .env 文件
NEURON_DB_PATH=data/dependency_graph.db
NEURON_CACHE_TTL=300
NEURON_CASCADE_MAX_DEPTH=5
NEURON_LOG_LEVEL=INFO
```

### 4.3 动态配置

```python
# 运行时动态更新配置
from neurova.config.neuron_config import NEURON_CONFIG

# 更新级联深度
NEURON_CONFIG["cascade_engine"]["max_depth"] = 10

# 启用/禁用图通道
NEURON_CONFIG["graph_channel"]["enabled"] = False
```

---

## 5. 核心组件实现

### 5.1 DependencyGraph - 依赖图谱

**文件**: `neurova/cognitive_layers/memory_layer/dependency_graph.py`

```python
"""依赖图谱 - 存储实体及其依赖关系"""

import json
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DependencyType(Enum):
    CAUSAL = "causal"
    TEMPORAL = "temporal"
    CONDITIONAL = "conditional"
    HIERARCHICAL = "hierarchical"
    CONFLICT = "conflict"
    SUPPORT = "support"
    PREREQUISITE = "prerequisite"


@dataclass
class EntityNode:
    id: str
    name: str
    entity_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class DependencyEdge:
    id: str
    source_id: str
    target_id: str
    dep_type: DependencyType
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class DependencyGraph:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        self._lock = threading.RLock()
        self.entities: Dict[str, EntityNode] = {}
        self.edges: List[DependencyEdge] = []
        self.adjacency: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self.reverse_adjacency: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self._edge_index: Dict[str, DependencyEdge] = {}
        self._downstream_cache: Dict[str, tuple] = {}
        self._cache_ttl = 300
        
        if db_path:
            self._init_db()
            self._load_from_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, name TEXT, entity_type TEXT,
                metadata TEXT DEFAULT '{}', created_at REAL, updated_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
                dep_type TEXT, confidence REAL DEFAULT 1.0,
                evidence TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}', created_at REAL
            )
        """)
        conn.commit()
        conn.close()
    
    def _load_from_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM entities"):
            self.entities[row["id"]] = EntityNode(
                id=row["id"], name=row["name"], entity_type=row["entity_type"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"], updated_at=row["updated_at"],
            )
        for row in conn.execute("SELECT * FROM edges"):
            edge = DependencyEdge(
                id=row["id"], source_id=row["source_id"], target_id=row["target_id"],
                dep_type=DependencyType(row["dep_type"]), confidence=row["confidence"],
                evidence=json.loads(row["evidence"]), metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
            )
            self.edges.append(edge)
            self.adjacency[edge.source_id].append(edge)
            self.reverse_adjacency[edge.target_id].append(edge)
        conn.close()
    
    def add_entity(self, entity: EntityNode) -> None:
        with self._lock:
            self.entities[entity.id] = entity
            if self._db_path:
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?)",
                    (entity.id, entity.name, entity.entity_type,
                     json.dumps(entity.metadata), entity.created_at, entity.updated_at)
                )
                conn.commit()
                conn.close()
    
    def add_dependency(self, edge: DependencyEdge) -> None:
        with self._lock:
            self.edges.append(edge)
            self.adjacency[edge.source_id].append(edge)
            self.reverse_adjacency[edge.target_id].append(edge)
            if self._db_path:
                conn = sqlite3.connect(self._db_path)
                conn.execute(
                    "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?,?)",
                    (edge.id, edge.source_id, edge.target_id, edge.dep_type.value,
                     edge.confidence, json.dumps(edge.evidence),
                     json.dumps(edge.metadata), edge.created_at)
                )
                conn.commit()
                conn.close()
    
    def get_downstream(self, entity_id: str, max_depth: int = 5) -> List[str]:
        cache_key = f"down:{entity_id}:{max_depth}"
        if cache_key in self._downstream_cache:
            val, ts = self._downstream_cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return val
        
        if entity_id not in self.entities:
            return []
        
        visited = set()
        result = []
        queue = deque([(entity_id, 0)])
        
        while queue:
            current_id, depth = queue.popleft()
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            for edge in self.adjacency.get(current_id, []):
                if edge.target_id not in visited:
                    result.append(edge.target_id)
                    queue.append((edge.target_id, depth + 1))
        
        self._downstream_cache[cache_key] = (result, time.time())
        return result
    
    def get_upstream(self, entity_id: str, max_depth: int = 5) -> List[str]:
        if entity_id not in self.entities:
            return []
        visited = set()
        result = []
        queue = deque([(entity_id, 0)])
        while queue:
            current_id, depth = queue.popleft()
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            for edge in self.reverse_adjacency.get(current_id, []):
                if edge.source_id not in visited:
                    result.append(edge.source_id)
                    queue.append((edge.source_id, depth + 1))
        return result
    
    def find_cascade_paths(
        self, source_id: str, target_id: str, max_paths: int = 5
    ) -> List[List[str]]:
        if source_id not in self.entities or target_id not in self.entities:
            return []
        paths = []
        visited = set()
        
        def dfs(current_id: str, path: List[str]):
            if len(paths) >= max_paths:
                return
            if current_id == target_id:
                paths.append(path.copy())
                return
            if current_id in visited:
                return
            visited.add(current_id)
            for edge in self.adjacency.get(current_id, []):
                path.append(edge.target_id)
                dfs(edge.target_id, path)
                path.pop()
            visited.remove(current_id)
        
        dfs(source_id, [source_id])
        return paths
    
    def detect_circular_dependencies(self) -> List[List[str]]:
        visited = set()
        recursion_stack = set()
        cycles = []
        
        def dfs(node: str, path: List[str]):
            visited.add(node)
            recursion_stack.add(node)
            path.append(node)
            for edge in self.adjacency.get(node, []):
                if edge.target_id not in visited:
                    dfs(edge.target_id, path)
                elif edge.target_id in recursion_stack:
                    cycle_start = path.index(edge.target_id)
                    cycles.append(path[cycle_start:] + [edge.target_id])
            path.pop()
            recursion_stack.remove(node)
        
        for node in self.entities:
            if node not in visited:
                dfs(node, [])
        return cycles
```

---

### 5.2 CascadeEngine - 级联推理引擎

**文件**: `neurova/cognitive_layers/memory_layer/cascade_engine.py`

```python
"""级联推理引擎 - 实现 A→B→C 链式推理"""

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from .dependency_graph import DependencyGraph

logger = logging.getLogger(__name__)


class CascadeDirection(Enum):
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass
class CascadeEffect:
    entity_id: str
    effect_type: str
    confidence: float
    path: List[str]
    evidence: List[str] = field(default_factory=list)


@dataclass
class CascadeResult:
    source_entity: str
    direction: CascadeDirection
    effects: List[CascadeEffect]
    total_affected: int
    confidence: float
    reasoning_chain: List[str]


class CascadeEngine:
    def __init__(self, dependency_graph: DependencyGraph):
        self.graph = dependency_graph
        self._confidence_decay = 0.2
    
    def forward_cascade(self, changed_entity: str, max_depth: int = 5) -> CascadeResult:
        """正向级联：A变化 → 影响哪些实体"""
        if changed_entity not in self.graph.entities:
            return CascadeResult(
                source_entity=changed_entity, direction=CascadeDirection.FORWARD,
                effects=[], total_affected=0, confidence=0.0,
                reasoning_chain=[f"实体 '{changed_entity}' 不存在"],
            )
        
        effects = []
        visited = set()
        queue = [(changed_entity, 0, [changed_entity])]
        reasoning_chain = [f"正向级联: {changed_entity} 变化"]
        
        while queue:
            current_id, depth, path = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            
            if depth > 0:
                confidence = 1.0 / (1.0 + depth * self._confidence_decay)
                effect_type = "direct" if depth == 1 else "indirect"
                effects.append(CascadeEffect(
                    entity_id=current_id, effect_type=effect_type,
                    confidence=confidence, path=path.copy(),
                ))
                entity = self.graph.entities.get(current_id)
                entity_name = entity.name if entity else current_id
                reasoning_chain.append(
                    f"  {'→' * depth} {entity_name} ({effect_type}, 置信度={confidence:.2f})"
                )
            
            for edge in self.graph.adjacency.get(current_id, []):
                if edge.target_id not in visited:
                    queue.append((edge.target_id, depth + 1, path + [edge.target_id]))
        
        total_confidence = (
            sum(e.confidence for e in effects) / len(effects) if effects else 0.0
        )
        reasoning_chain.append(f"总计影响 {len(effects)} 个实体，平均置信度 {total_confidence:.2f}")
        
        return CascadeResult(
            source_entity=changed_entity, direction=CascadeDirection.FORWARD,
            effects=effects, total_affected=len(effects),
            confidence=total_confidence, reasoning_chain=reasoning_chain,
        )
    
    def backward_cascade(self, target_entity: str, max_depth: int = 5) -> CascadeResult:
        """反向级联：B变化 ← 受哪些实体影响"""
        if target_entity not in self.graph.entities:
            return CascadeResult(
                source_entity=target_entity, direction=CascadeDirection.BACKWARD,
                effects=[], total_affected=0, confidence=0.0,
                reasoning_chain=[f"实体 '{target_entity}' 不存在"],
            )
        
        effects = []
        visited = set()
        queue = [(target_entity, 0, [target_entity])]
        reasoning_chain = [f"反向级联: {target_entity} ← 受影响源"]
        
        while queue:
            current_id, depth, path = queue.pop(0)
            if current_id in visited or depth > max_depth:
                continue
            visited.add(current_id)
            
            if depth > 0:
                confidence = 1.0 / (1.0 + depth * self._confidence_decay)
                effect_type = "direct" if depth == 1 else "indirect"
                effects.append(CascadeEffect(
                    entity_id=current_id, effect_type=effect_type,
                    confidence=confidence, path=list(reversed(path)),
                ))
                entity = self.graph.entities.get(current_id)
                entity_name = entity.name if entity else current_id
                reasoning_chain.append(
                    f"  {'←' * depth} {entity_name} ({effect_type}, 置信度={confidence:.2f})"
                )
            
            for edge in self.graph.reverse_adjacency.get(current_id, []):
                if edge.source_id not in visited:
                    queue.append((edge.source_id, depth + 1, [edge.source_id] + path))
        
        total_confidence = (
            sum(e.confidence for e in effects) / len(effects) if effects else 0.0
        )
        reasoning_chain.append(f"总计 {len(effects)} 个影响源，平均置信度 {total_confidence:.2f}")
        
        return CascadeResult(
            source_entity=target_entity, direction=CascadeDirection.BACKWARD,
            effects=effects, total_affected=len(effects),
            confidence=total_confidence, reasoning_chain=reasoning_chain,
        )
    
    def would_affect(
        self, source_id: str, target_id: str, threshold: float = 0.5
    ) -> Dict[str, Any]:
        """判断source变化是否会影响target"""
        paths = self.graph.find_cascade_paths(source_id, target_id)
        if not paths:
            return {"would_affect": False, "confidence": 0.0, "paths": []}
        
        min_confidence = min(1.0 / (1.0 + (len(p) - 1) * self._confidence_decay) for p in paths)
        return {
            "would_affect": min_confidence >= threshold,
            "confidence": min_confidence, "paths": paths,
        }
```

---

### 5.3 AbsenceReasoner - 缺失推理器

**文件**: `neurova/cognitive_layers/memory_layer/absence_reasoner.py`

```python
"""缺失推理器 - 检测"应该存在但没有"的记忆"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .dependency_graph import DependencyGraph, DependencyType

logger = logging.getLogger(__name__)


@dataclass
class AbsenceResult:
    is_absent: bool
    entity_exists: bool
    relation_exists: bool
    context_has_dependency: bool
    confidence: float
    explanation: List[str]
    suggestions: List[str] = field(default_factory=list)


class AbsenceReasoner:
    def __init__(self, dependency_graph: DependencyGraph):
        self.graph = dependency_graph
    
    def detect_absence(
        self, expected_entity: str, expected_relation: DependencyType,
        context_entities: List[str],
    ) -> AbsenceResult:
        explanation = []
        suggestions = []
        
        entity_exists = expected_entity in self.graph.entities
        if not entity_exists:
            explanation.append(f"实体 '{expected_entity}' 不存在于依赖图谱中")
            suggestions.append(f"需要添加实体 '{expected_entity}'")
        
        relation_exists = False
        if entity_exists:
            for edge in self.graph.adjacency.get(expected_entity, []):
                if edge.dep_type == expected_relation:
                    relation_exists = True
                    break
            if not relation_exists:
                explanation.append(f"实体 '{expected_entity}' 没有 {expected_relation.value} 类型的关系")
                suggestions.append(f"需要为 '{expected_entity}' 添加 {expected_relation.value} 关系")
        
        context_has_dependency = False
        for ctx_entity in context_entities:
            for edge in self.graph.adjacency.get(ctx_entity, []):
                if edge.target_id == expected_entity:
                    context_has_dependency = True
                    break
            if context_has_dependency:
                break
        
        if not context_has_dependency and context_entities:
            explanation.append(f"上下文实体中没有指向 '{expected_entity}' 的依赖")
            suggestions.append("需要建立上下文实体与目标实体的关联")
        
        is_absent = not (entity_exists and relation_exists and context_has_dependency)
        confidence = min(0.9, 0.3 + sum([not entity_exists, not relation_exists, not context_has_dependency]) * 0.2) if is_absent else 0.1
        
        return AbsenceResult(
            is_absent=is_absent, entity_exists=entity_exists,
            relation_exists=relation_exists, context_has_dependency=context_has_dependency,
            confidence=confidence, explanation=explanation, suggestions=suggestions,
        )
```

---

### 5.4 MOEDependencyExtractor - 无LLM依赖提取器

**文件**: `neurova/cognitive_layers/memory_layer/moe_dependency_extractor.py`

```python
"""基于MOE架构的无LLM依赖关系提取器（运行时成本$0）"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .dependency_graph import (
    DependencyEdge, DependencyGraph, DependencyType, EntityNode,
)

logger = logging.getLogger(__name__)


class EntityExtractor:
    PATTERNS = {
        "date": r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
        "time": r"\d{1,2}:\d{2}(:\d{2})?",
        "number": r"\b\d+(\.\d+)?\b",
        "url": r"https?://\S+",
    }
    ENTITY_KEYWORDS = {
        "person": ["张三", "李四", "Alice", "Bob", "用户", "开发者"],
        "event": ["会议", "部署", "发布", "上线", "测试", "调试"],
        "concept": ["架构", "设计", "模式", "策略", "算法"],
        "object": ["数据库", "服务器", "API", "接口", "模块", "组件"],
        "task": ["任务", "需求", "功能", "优化", "修复", "重构"],
    }
    
    def extract(self, text: str) -> List[Dict[str, Any]]:
        entities = []
        seen = set()
        
        for entity_type, pattern in self.PATTERNS.items():
            for match in re.finditer(pattern, text):
                name = match.group()
                if name not in seen:
                    seen.add(name)
                    entities.append({
                        "id": f"{entity_type}_{hash(name) % 10000}",
                        "name": name, "type": entity_type, "confidence": 0.9,
                        "start": match.start(), "end": match.end(),
                    })
        
        for entity_type, keywords in self.ENTITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text.lower() and keyword not in seen:
                    seen.add(keyword)
                    idx = text.lower().find(keyword.lower())
                    entities.append({
                        "id": f"{entity_type}_{hash(keyword) % 10000}",
                        "name": keyword, "type": entity_type, "confidence": 0.8,
                        "start": idx, "end": idx + len(keyword),
                    })
        
        return entities


class RelationClassifier:
    CAUSAL_KEYWORDS = ["因为", "所以", "导致", "引起", "causes", "leads to"]
    TEMPORAL_KEYWORDS = ["之前", "之后", "然后", "接着", "before", "after"]
    CONDITIONAL_KEYWORDS = ["如果", "假如", "当", "只要", "if", "when"]
    PREREQUISITE_KEYWORDS = ["先", "后", "前提", "基础", "prerequisite"]
    
    def classify(
        self, entity1: Dict, entity2: Dict, context: str, similarity: float = 0.0
    ) -> Tuple[DependencyType, float]:
        ctx = context.lower()
        
        if any(kw in ctx for kw in self.CAUSAL_KEYWORDS):
            return DependencyType.CAUSAL, 0.8
        if entity1.get("end", 0) < entity2.get("start", 0) or any(kw in ctx for kw in self.TEMPORAL_KEYWORDS):
            return DependencyType.TEMPORAL, 0.7
        if any(kw in ctx for kw in self.CONDITIONAL_KEYWORDS):
            return DependencyType.CONDITIONAL, 0.7
        if any(kw in ctx for kw in self.PREREQUISITE_KEYWORDS):
            return DependencyType.PREREQUISITE, 0.7
        if similarity > 0.7:
            return DependencyType.SUPPORT, similarity
        
        return DependencyType.HIERARCHICAL, 0.5


@dataclass
class ExtractedDependency:
    source_entity: Dict[str, Any]
    target_entity: Dict[str, Any]
    dep_type: DependencyType
    confidence: float
    evidence_text: str


class MOEDependencyExtractor:
    def __init__(self, vector_gating_network=None, expert_retriever=None):
        self.entity_extractor = EntityExtractor()
        self.relation_classifier = RelationClassifier()
        self.dependency_graph = DependencyGraph()
        self.vector_gating = vector_gating_network
        self.expert_retriever = expert_retriever
        logger.info("MOEDependencyExtractor初始化完成")
    
    async def extract_from_memory(
        self, memory_id: str, content: str, metadata: Dict = None,
    ) -> List[ExtractedDependency]:
        entities = self.entity_extractor.extract(content)
        if len(entities) < 2:
            return []
        
        dependencies = []
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i + 1:]:
                similarity = await self._compute_similarity(entity1["name"], entity2["name"])
                dep_type, confidence = self.relation_classifier.classify(
                    entity1, entity2, content, similarity,
                )
                if confidence >= 0.5:
                    dependencies.append(ExtractedDependency(
                        source_entity=entity1, target_entity=entity2,
                        dep_type=dep_type, confidence=confidence,
                        evidence_text=content[:200],
                    ))
        
        await self._build_graph(memory_id, entities, dependencies)
        return dependencies
    
    async def _compute_similarity(self, text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
    
    async def _build_graph(
        self, memory_id: str, entities: List[Dict], dependencies: List[ExtractedDependency],
    ) -> None:
        for entity in entities:
            node = EntityNode(
                id=entity["id"], name=entity["name"],
                entity_type=entity["type"], metadata={"memory_id": memory_id},
            )
            self.dependency_graph.add_entity(node)
        
        for dep in dependencies:
            edge = DependencyEdge(
                id=f"{memory_id}_{dep.source_entity['id']}_{dep.target_entity['id']}",
                source_id=dep.source_entity["id"], target_id=dep.target_entity["id"],
                dep_type=dep.dep_type, confidence=dep.confidence, evidence=[memory_id],
            )
            self.dependency_graph.add_dependency(edge)
```

---

## 6. 系统集成

### 6.1 集成到图通道

**修改文件**: `neurova/cognitive_layers/memory_layer/neurova_recall.py`

```python
class NeurovaRecallEngine:
    def __init__(self, ...):
        # ... 现有初始化 ...
        
        # 新增：依赖图谱组件
        from .dependency_graph import DependencyGraph
        from .cascade_engine import CascadeEngine
        from .absence_reasoner import AbsenceReasoner
        from .moe_dependency_extractor import MOEDependencyExtractor
        
        self.dependency_graph = DependencyGraph(db_path="dependency_graph.db")
        self.cascade_engine = CascadeEngine(self.dependency_graph)
        self.absence_reasoner = AbsenceReasoner(self.dependency_graph)
        self.dependency_extractor = MOEDependencyExtractor()
    
    def _channel_graph(self, query: str, limit: int) -> List[RecalledMemory]:
        """图通道检索 - 基于依赖图谱"""
        entities = self.dependency_extractor.entity_extractor.extract(query)
        recalled_memories = []
        
        for entity in entities:
            downstream = self.dependency_graph.get_downstream(entity["id"])
            upstream = [
                edge.source_id
                for edge in self.dependency_graph.reverse_adjacency.get(entity["id"], [])
            ]
            
            for entity_id in downstream + upstream:
                entity_node = self.dependency_graph.entities.get(entity_id)
                if entity_node and "memory_id" in entity_node.metadata:
                    recalled_memories.append(RecalledMemory(
                        memory_id=entity_node.metadata["memory_id"],
                        content=entity_node.name, score=0.8,
                        channel=RecallChannel.GRAPH,
                    ))
        
        if entities:
            cascade_result = self.cascade_engine.forward_cascade(entities[0]["id"])
            for effect in cascade_result.effects:
                entity_node = self.dependency_graph.entities.get(effect.entity_id)
                if entity_node and "memory_id" in entity_node.metadata:
                    recalled_memories.append(RecalledMemory(
                        memory_id=entity_node.metadata["memory_id"],
                        content=entity_node.name, score=effect.confidence,
                        channel=RecallChannel.GRAPH,
                    ))
        
        unique_memories = {m.memory_id: m for m in recalled_memories}
        return list(unique_memories.values())[:limit]
```

### 6.2 记忆存储时提取依赖

**修改文件**: `neurova/cognitive_layers/memory_layer/manager.py`

```python
class MemoryManager:
    def __init__(self, ...):
        # ... 现有初始化 ...
        self._dependency_extractor = None
    
    @property
    def dependency_extractor(self):
        if self._dependency_extractor is None:
            from .moe_dependency_extractor import MOEDependencyExtractor
            self._dependency_extractor = MOEDependencyExtractor()
        return self._dependency_extractor
    
    async def remember(self, content: str, metadata: Dict = None) -> str:
        # ... 现有保存逻辑 ...
        
        # 新增：提取依赖关系
        try:
            deps = await self.dependency_extractor.extract_from_memory(
                memory_id=memory_id, content=content, metadata=metadata,
            )
        except Exception as e:
            logger.debug("依赖提取失败: %s", e)
        
        return memory_id
```

---

## 7. 测试用例

### 7.1 单元测试

```python
# tests/unit/test_neuron_components.py

import pytest
from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph, EntityNode, DependencyEdge, DependencyType,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import (
    CascadeEngine, CascadeDirection,
)
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import (
    MOEDependencyExtractor, EntityExtractor, RelationClassifier,
)


class TestDependencyGraph:
    def test_add_entity(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        assert "a" in graph.entities
    
    def test_add_dependency(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b",
            dep_type=DependencyType.CAUSAL,
        ))
        assert len(graph.edges) == 1
    
    def test_get_downstream(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL))
        graph.add_dependency(DependencyEdge(id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL))
        
        downstream = graph.get_downstream("a")
        assert "b" in downstream
        assert "c" in downstream
    
    def test_find_cascade_paths(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL))
        graph.add_dependency(DependencyEdge(id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL))
        
        paths = graph.find_cascade_paths("a", "c")
        assert len(paths) == 1
        assert paths[0] == ["a", "b", "c"]


class TestCascadeEngine:
    def test_forward_cascade(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL))
        graph.add_dependency(DependencyEdge(id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL))
        
        engine = CascadeEngine(graph)
        result = engine.forward_cascade("a")
        
        assert result.total_affected == 2
        assert len(result.effects) == 2
        assert result.direction == CascadeDirection.FORWARD
    
    def test_backward_cascade(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL))
        
        engine = CascadeEngine(graph)
        result = engine.backward_cascade("b")
        
        assert result.total_affected == 1
        assert result.direction == CascadeDirection.BACKWARD


class TestAbsenceReasoner:
    def test_detect_absence(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        
        reasoner = AbsenceReasoner(graph)
        result = reasoner.detect_absence(
            expected_entity="nonexistent",
            expected_relation=DependencyType.CAUSAL,
            context_entities=["a"],
        )
        
        assert result.is_absent == True
        assert result.entity_exists == False


class TestMOEDependencyExtractor:
    def test_entity_extractor(self):
        extractor = EntityExtractor()
        entities = extractor.extract("部署服务器需要数据库")
        assert len(entities) > 0
        names = [e["name"] for e in entities]
        assert "服务器" in names or "数据库" in names
    
    def test_relation_classifier(self):
        classifier = RelationClassifier()
        entity1 = {"name": "A", "end": 5}
        entity2 = {"name": "B", "start": 10}
        dep_type, confidence = classifier.classify(entity1, entity2, "A导致B")
        assert dep_type == DependencyType.CAUSAL
        assert confidence >= 0.7
```

---

## 8. 实施计划

### 8.1 五阶段实施（13天）

| 阶段 | 任务 | 时间 | 文件 |
|------|------|------|------|
| **Phase 1** | DependencyGraph | 2天 | dependency_graph.py |
| **Phase 2** | CascadeEngine + AbsenceReasoner | 3天 | cascade_engine.py, absence_reasoner.py |
| **Phase 3** | MOEDependencyExtractor | 3天 | moe_dependency_extractor.py |
| **Phase 4** | 系统集成 | 2天 | neurova_recall.py, manager.py |
| **Phase 5** | 测试 + 优化 | 3天 | test_neuron_components.py |

### 8.2 预期效果

| 任务 | 当前 | 预期 |
|------|------|------|
| **Cascade** | 3% | 60%+ |
| **Absence** | 1% | 50%+ |

**运行时成本**: $0（无LLM调用）

---

## 9. 使用示例

### 9.1 基础使用

```python
from neurova.cognitive_layers.memory_layer.dependency_graph import DependencyGraph
from neurova.cognitive_layers.memory_layer.cascade_engine import CascadeEngine
from neurova.cognitive_layers.memory_layer.absence_reasoner import AbsenceReasoner
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import MOEDependencyExtractor

# 初始化依赖图谱
graph = DependencyGraph(db_path="data/dependency_graph.db")

# 初始化组件
cascade_engine = CascadeEngine(graph)
absence_reasoner = AbsenceReasoner(graph)
extractor = MOEDependencyExtractor(vector_gating_network=None)

# 从记忆中提取依赖
import asyncio

async def example_extract():
    content = "部署服务器需要先安装数据库，然后配置API接口"
    dependencies = await extractor.extract_from_memory(
        memory_id="mem_001",
        content=content,
        metadata={"source": "用户对话"}
    )
    print(f"提取到 {len(dependencies)} 个依赖关系")
    return dependencies

# 执行提取
dependencies = asyncio.run(example_extract())

# 正向级联推理
result = cascade_engine.forward_cascade("服务器")
print(f"正向级联影响 {result.total_affected} 个实体")
for effect in result.effects:
    print(f"  - {effect.entity_id}: {effect.effect_type} (置信度={effect.confidence:.2f})")

# 缺失检测
absence_result = absence_reasoner.detect_absence(
    expected_entity="数据库",
    expected_relation="prerequisite",
    context_entities=["服务器", "API"]
)
if absence_result.is_absent:
    print(f"检测到缺失: {absence_result.explanation}")
    print(f"建议: {absence_result.suggestions}")
```

### 9.2 与记忆系统集成

```python
from neurova.cognitive_layers.memory_layer.manager import MemoryManager

# 初始化记忆管理器
memory_manager = MemoryManager(agent_id="agent_001", user_id="user_001")

# 存储记忆（自动提取依赖）
memory_id = memory_manager.remember(
    content="部署服务器需要先安装数据库，然后配置API接口",
    category="technical",
    importance=80.0,
    metadata={"project": "Neurova"}
)

# 检索记忆（包含图通道）
from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

recall_engine = NeurovaRecallEngine(memory_manager=memory_manager)
result = recall_engine.recall(
    query="服务器部署需要什么？",
    limit=10
)

print(f"检索到 {len(result.recalled_memories)} 条记忆")
for memory in result.recalled_memories:
    print(f"  - [{memory.channel.value}] {memory.content[:50]}...")
```

### 9.3 高级查询

```python
# 查询级联路径
paths = graph.find_cascade_paths("服务器", "用户")
print(f"找到 {len(paths)} 条级联路径")
for path in paths:
    print(f"  路径: {' → '.join(path)}")

# 检测循环依赖
cycles = graph.detect_circular_dependencies()
if cycles:
    print(f"检测到 {len(cycles)} 个循环依赖")
    for cycle in cycles:
        print(f"  循环: {' → '.join(cycle)}")

# 判断影响范围
would_affect = cascade_engine.would_affect("服务器", "用户", threshold=0.5)
if would_affect["would_affect"]:
    print(f"服务器变化会影响用户 (置信度={would_affect['confidence']:.2f})")
    print(f"影响路径: {would_affect['paths']}")
```

---

## 10. 性能考虑

### 10.1 性能指标

| 操作 | 目标性能 | 优化策略 |
|------|----------|----------|
| 实体提取 | < 10ms | 正则预编译、缓存模式 |
| 关系分类 | < 5ms | 关键词索引、规则缓存 |
| 图查询 | < 50ms | 邻接表索引、BFS优化 |
| 级联推理 | < 100ms | 深度限制、缓存结果 |
| 缺失检测 | < 20ms | 索引查找、提前终止 |
| 依赖提取 | < 100ms | 批量处理、异步执行 |

### 10.2 内存优化

```python
# 1. 缓存策略
dependency_graph._cache_ttl = 300  # 5分钟缓存
dependency_graph._downstream_cache = {}  # 下游缓存

# 2. 索引优化
# 实体索引: O(1) 查找
# 邻接表: O(degree) 遍历
# 反向邻接表: O(degree) 反向查询

# 3. 内存限制
max_entities = 10000  # 最大实体数
max_edges = 50000     # 最大边数
```

### 10.3 并发安全

```python
import threading

class DependencyGraph:
    def __init__(self):
        self._lock = threading.RLock()  # 可重入锁
        
    def add_entity(self, entity):
        with self._lock:  # 线程安全
            # ... 添加实体逻辑
    
    def add_dependency(self, edge):
        with self._lock:  # 线程安全
            # ... 添加依赖逻辑
```

### 10.4 数据库优化

```python
# SQLite WAL模式（提升并发性能）
conn.execute("PRAGMA journal_mode=WAL")

# 连接池（减少连接开销）
import sqlite3
from contextlib import contextmanager

@contextmanager
def get_db_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
    finally:
        conn.close()
```

---

## 11. 错误处理与边界情况

### 11.1 常见错误处理

```python
class DependencyGraph:
    def add_entity(self, entity: EntityNode) -> bool:
        """添加实体（带错误处理）"""
        try:
            with self._lock:
                # 验证输入
                if not entity.id or not entity.name:
                    logger.warning("实体ID或名称为空")
                    return False
                
                # 检查重复
                if entity.id in self.entities:
                    logger.debug("实体已存在: %s", entity.id)
                    return False
                
                # 添加实体
                self.entities[entity.id] = entity
                # ... 数据库操作
                return True
                
        except Exception as e:
            logger.error("添加实体失败: %s", e)
            return False
```

### 11.2 边界情况处理

```python
class CascadeEngine:
    def forward_cascade(self, changed_entity: str, max_depth: int = 5):
        """正向级联（带边界处理）"""
        # 边界1: 实体不存在
        if changed_entity not in self.graph.entities:
            return CascadeResult(
                source_entity=changed_entity,
                direction=CascadeDirection.FORWARD,
                effects=[], total_affected=0, confidence=0.0,
                reasoning_chain=[f"实体 '{changed_entity}' 不存在"],
            )
        
        # 边界2: 深度限制
        max_depth = min(max_depth, 10)  # 防止无限递归
        
        # 边界3: 循环检测
        visited = set()  # 防止循环引用
        
        # ... 正常逻辑
```

### 11.3 降级策略

```python
class NeurovaRecallEngine:
    def _channel_graph(self, query: str, limit: int):
        """图通道（带降级策略）"""
        try:
            # 正常逻辑
            return self._normal_graph_retrieval(query, limit)
            
        except Exception as e:
            logger.warning("图通道检索失败，降级到文本通道: %s", e)
            # 降级策略: 使用文本匹配
            return self._fallback_text_retrieval(query, limit)
```

---

## 12. 故障排除

### 12.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 图通道返回空结果 | 实体未提取 | 检查EntityExtractor模式 |
| 级联推理超时 | 图过大或深度过大 | 限制max_depth或启用缓存 |
| 依赖提取失败 | 内容格式异常 | 检查文本预处理 |
| 数据库连接失败 | SQLite文件权限 | 检查db_path和权限 |
| 内存占用过高 | 缓存未清理 | 降低cache_ttl或max_cache_size |

### 12.2 调试方法

```python
import logging

# 启用详细日志
logging.basicConfig(level=logging.DEBUG)

# 检查依赖图谱状态
graph = DependencyGraph()
print(f"实体数: {len(graph.entities)}")
print(f"边数: {len(graph.edges)}")
print(f"缓存大小: {len(graph._downstream_cache)}")

# 检查组件状态
cascade_engine = CascadeEngine(graph)
print(f"置信度衰减: {cascade_engine._confidence_decay}")
```

### 12.3 性能监控

```python
import time

def monitor_performance(func):
    """性能监控装饰器"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        duration = (time.time() - start) * 1000
        logger.info(f"{func.__name__} 耗时: {duration:.2f}ms")
        return result
    return wrapper

# 使用示例
@monitor_performance
def extract_dependencies(content):
    return extractor.extract_from_memory(...)
```

---

## 13. 最佳实践

### 13.1 设计原则

1. **单一职责**: 每个组件只负责一个功能
2. **开闭原则**: 对扩展开放，对修改关闭
3. **依赖倒置**: 依赖抽象而非具体实现
4. **接口隔离**: 小接口，深实现

### 13.2 编码规范

```python
# 1. 类型注解
def add_entity(self, entity: EntityNode) -> bool:
    """添加实体"""
    pass

# 2. 文档字符串
class DependencyGraph:
    """依赖图谱 - 存储实体及其依赖关系
    
    Features:
        - SQLite持久化
        - 内存索引
        - 缓存机制
        - 线程安全
    """
    pass

# 3. 错误处理
try:
    # 正常逻辑
except SpecificException as e:
    logger.error("特定错误: %s", e)
except Exception as e:
    logger.error("未知错误: %s", e)
    raise

# 4. 日志记录
logger.debug("详细调试信息")
logger.info("一般信息")
logger.warning("警告信息")
logger.error("错误信息")
```

### 13.3 测试策略

```python
# 1. 单元测试
class TestDependencyGraph:
    def test_add_entity(self):
        """测试添加实体"""
        graph = DependencyGraph()
        entity = EntityNode(id="a", name="A", entity_type="concept")
        graph.add_entity(entity)
        assert "a" in graph.entities
    
    def test_add_entity_duplicate(self):
        """测试重复添加实体"""
        graph = DependencyGraph()
        entity = EntityNode(id="a", name="A", entity_type="concept")
        graph.add_entity(entity)
        graph.add_entity(entity)  # 重复添加
        assert len(graph.entities) == 1

# 2. 集成测试
class TestCascadeIntegration:
    def test_forward_cascade_integration(self):
        """测试正向级联集成"""
        graph = DependencyGraph()
        # ... 设置测试数据
        engine = CascadeEngine(graph)
        result = engine.forward_cascade("a")
        assert result.total_affected > 0

# 3. 性能测试
class TestPerformance:
    def test_extraction_performance(self):
        """测试提取性能"""
        import time
        start = time.time()
        # ... 执行操作
        duration = time.time() - start
        assert duration < 0.1  # 100ms内完成
```

### 13.4 部署建议

1. **数据库初始化**: 首次运行时创建SQLite表
2. **缓存预热**: 启动时预加载常用查询
3. **监控告警**: 设置性能监控和异常告警
4. **备份策略**: 定期备份SQLite数据库
5. **版本管理**: 使用语义化版本号

---

## 14. 参考文献

### 14.1 论文

1. **MEEM Benchmark**: "MEEM: A Benchmark for Memory Evaluation in Emotional Machines" (arXiv:2605.12477v1)
2. **NEURON Architecture**: "Neural Entity-Understanding and Reasoning Ontology Network" (内部设计)
3. **Dependency Graph**: "Graph-based Memory Systems for AI Agents" (综合研究)

### 14.2 技术文档

1. SQLite WAL模式: https://www.sqlite.org/wal.html
2. Python类型注解: https://docs.python.org/3/library/typing.html
3. 线程安全编程: https://docs.python.org/3/library/threading.html

### 14.3 相关项目

1. Neurova记忆系统: 项目内部文档
2. MOE架构实现: 项目内部文档
3. 6通道检索系统: 项目内部文档

---

*文档版本: 5.0*
*最后更新: 2026-06-13*