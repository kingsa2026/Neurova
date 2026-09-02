# 基于MOE架构的无LLM依赖关系提取方案

> **设计日期**：2026年6月13日
> **核心思想**：利用Neurova现有的MOE架构，通过规则引擎和向量相似度提取依赖关系，避免LLM调用

---

## 1. 现有MOE架构分析

### 1.1 已有组件

```
Neurova MOE架构
├── VectorGatingNetwork      # 向量门控网络（cosine相似度路由）
├── ExpertDrilldownRetriever # 多层下钻检索（L0-L3）
├── QueryTags                # 查询标签提取（含entities）
├── RelationMixin            # 关联管理（create_relation等）
└── UnifiedVectorStore       # 统一向量存储
```

### 1.2 关键能力

| 组件 | 能力 | 用于依赖提取 |
|------|------|--------------|
| **QueryTags.entities** | 实体提取 | ✅ 识别依赖主体 |
| **VectorGatingNetwork** | 向量路由 | ✅ 发现相关记忆 |
| **ExpertDrilldownRetriever** | 多层检索 | ✅ 发现潜在依赖 |
| **RelationMixin** | 关联管理 | ✅ 存储依赖关系 |
| **向量相似度** | 语义相似度 | ⚠️ 辅助，非核心 |

---

## 2. 依赖提取架构设计

### 2.1 架构概览

```
MOE依赖提取器 (MOEDependencyExtractor)
├── 实体提取层 (EntityExtractionLayer)
│   ├── QueryTags.entities     # 从查询提取实体
│   ├── 记忆内容实体提取       # 从记忆内容提取实体
│   └── 实体消歧与对齐         # 实体归一化
├── 关系发现层 (RelationDiscoveryLayer)
│   ├── 向量相似度发现         # 语义相关记忆
│   ├── 时间关系发现           # 时间先后关系
│   ├── 共现实体发现           # 共现实体关系
│   └── 模式匹配发现           # 因果/依赖模式
├── 关系分类层 (RelationClassificationLayer)
│   ├── 规则引擎分类           # 基于规则的关系类型
│   ├── 模式匹配分类           # 因果/依赖模式
│   └── 置信度计算             # 关系强度评估
└── 依赖图谱构建 (DependencyGraphBuilder)
    ├── 实体节点构建           # 创建实体节点
    ├── 依赖边构建             # 创建依赖边
    └── 图谱更新               # 增量更新依赖图谱
```

### 2.2 核心流程

```python
class MOEDependencyExtractor:
    """基于MOE架构的依赖关系提取器（无LLM）"""
    
    def __init__(self, moe_router: MoEMemoryRouter, relation_mixin: RelationMixin):
        self.moe_router = moe_router
        self.relation_mixin = relation_mixin
        self.entity_extractor = EntityExtractor()
        self.relation_classifier = RelationClassifier()
        self.dependency_graph = DependencyGraph()
    
    async def extract_dependencies(self, memory_id: str, content: str) -> List[Dependency]:
        """从记忆中提取依赖关系"""
        
        # Step 1: 实体提取
        entities = await self._extract_entities(content)
        
        # Step 2: 发现相关记忆（利用MOE路由）
        related_memories = await self._discover_related_memories(content, entities)
        
        # Step 3: 提取实体间关系
        dependencies = []
        for related_memory in related_memories:
            # 提取相关记忆的实体
            related_entities = await self._extract_entities(related_memory["content"])
            
            # 发现实体间关系
            deps = await self._discover_entity_relations(
                entities, related_entities, related_memory
            )
            dependencies.extend(deps)
        
        # Step 4: 分类关系类型
        classified_deps = self._classify_relations(dependencies)
        
        # Step 5: 构建依赖图谱
        await self._build_dependency_graph(memory_id, entities, classified_deps)
        
        return classified_deps
```

---

## 3. 核心组件实现

### 3.1 实体提取层 (EntityExtractionLayer)

**利用现有QueryTags.entities + 规则引擎**

```python
class EntityExtractor:
    """实体提取器（无LLM）"""
    
    def __init__(self):
        # 规则模式：基于正则表达式
        self.patterns = {
            # 人名模式
            "person": [
                r"([A-Z][a-z]+ [A-Z][a-z]+)",  # 英文名
                r"([\u4e00-\u9fa5]{2,4})",      # 中文名
                r"(负责人|经理|主管|领导|CEO|CTO|PM)\s*[:：]?\s*(\S+)",
            ],
            # 组织模式
            "organization": [
                r"([\u4e00-\u9fa5]+(?:公司|集团|团队|部门|组织))",
                r"([A-Z][A-Za-z]+ (?:Inc|Corp|LLC|Ltd|Team|Group))",
            ],
            # 技术模式
            "technology": [
                r"([\w\-\.]+(?:\.js|\.py|\.java|\.go|\.rs))",  # 文件
                r"([\w\-]+(?:DB|API|SDK|Framework|Library))",  # 技术
                r"(Redis|MySQL|PostgreSQL|MongoDB|Docker|K8s|Kubernetes)",
            ],
            # 时间模式
            "time": [
                r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",  # 日期
                r"(\d{1,2}:\d{2}(?::\d{2})?)",       # 时间
                r"(今天|昨天|明天|上周|下周|本月|下月)",
            ],
        }
        
        # 缓存已提取的实体
        self.entity_cache = {}
    
    async def extract(self, text: str) -> List[Entity]:
        """从文本提取实体"""
        entities = []
        
        # 1. 正则模式匹配
        for entity_type, patterns in self.patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    entity = Entity(
                        text=match.group(),
                        type=entity_type,
                        start=match.start(),
                        end=match.end(),
                        confidence=0.8  # 规则匹配置信度
                    )
                    entities.append(entity)
        
        # 2. 实体消歧与对齐
        entities = self._deduplicate_entities(entities)
        
        # 3. 实体归一化
        entities = self._normalize_entities(entities)
        
        return entities
```

### 3.2 关系发现层 (RelationDiscoveryLayer)

**利用MOE路由发现相关记忆**

```python
class RelationDiscoveryLayer:
    """关系发现层（基于MOE架构）"""
    
    def __init__(self, moe_router: MoEMemoryRouter):
        self.moe_router = moe_router
    
    async def discover_relations(self, source_entities: List[Entity], 
                                content: str) -> List[RelationCandidate]:
        """发现实体间关系"""
        
        candidates = []
        
        # 1. 向量相似度发现
        vector_candidates = await self._discover_by_vector_similarity(content)
        candidates.extend(vector_candidates)
        
        # 2. 时间关系发现
        time_candidates = await self._discover_by_temporal_relation(content)
        candidates.extend(time_candidates)
        
        # 3. 共现实体发现
        cooccurrence_candidates = await self._discover_by_cooccurrence(source_entities)
        candidates.extend(cooccurrence_candidates)
        
        # 4. 模式匹配发现
        pattern_candidates = await self._discover_by_patterns(content)
        candidates.extend(pattern_candidates)
        
        return candidates
    
    async def _discover_by_vector_similarity(self, content: str) -> List[RelationCandidate]:
        """基于向量相似度发现相关记忆"""
        candidates = []
        
        # 使用MOE路由获取相关记忆
        related_memories = await self.moe_router.retrieve(content, limit=5)
        
        for memory in related_memories:
            # 计算相似度作为关系强度
            similarity = memory.get("score", 0.0)
            
            if similarity > 0.3:  # 阈值
                candidate = RelationCandidate(
                    source_content=content,
                    target_content=memory["content"],
                    target_id=memory["id"],
                    relation_type="related",  # 默认类型
                    strength=similarity,
                    discovery_method="vector_similarity",
                    confidence=similarity * 0.8  # 置信度调整
                )
                candidates.append(candidate)
        
        return candidates
    
    async def _discover_by_temporal_relation(self, content: str) -> List[RelationCandidate]:
        """基于时间关系发现"""
        candidates = []
        
        # 提取时间信息
        time_entities = self._extract_time_entities(content)
        
        # 查找时间相关的记忆
        for time_entity in time_entities:
            # 使用MOE路由查找时间相关记忆
            time_query = f"时间: {time_entity.text}"
            related_memories = await self.moe_router.retrieve(time_query, limit=3)
            
            for memory in related_memories:
                # 检查时间先后关系
                relation = self._determine_temporal_relation(
                    time_entity, memory.get("timestamp")
                )
                
                if relation:
                    candidate = RelationCandidate(
                        source_content=content,
                        target_content=memory["content"],
                        target_id=memory["id"],
                        relation_type=relation,
                        strength=0.7,
                        discovery_method="temporal_relation",
                        confidence=0.6
                    )
                    candidates.append(candidate)
        
        return candidates
```

### 3.3 关系分类层 (RelationClassificationLayer)

**基于规则引擎的关系分类（无LLM）**

```python
class RelationClassifier:
    """关系分类器（规则引擎）"""
    
    def __init__(self):
        # 关系模式规则
        self.relation_patterns = {
            "causes": [
                # 因果关系模式
                (r"导致|引起|造成|引发", 0.9),
                (r"因为|由于|鉴于", 0.8),
                (r"结果是|以至于|因此", 0.8),
                (r"leads to|causes|results in", 0.9),
                (r"because|due to|since", 0.8),
            ],
            "requires": [
                # 依赖关系模式
                (r"需要|依赖|必须有", 0.9),
                (r"依赖于|基于|建立在", 0.8),
                (r"requires|depends on|needs", 0.9),
                (r"based on|built on|relies on", 0.8),
            ],
            "prevents": [
                # 阻止关系模式
                (r"阻止|防止|阻碍", 0.9),
                (r"避免|排除|禁止", 0.8),
                (r"prevents|blocks|stops", 0.9),
                (r"avoids|excludes|prohibits", 0.8),
            ],
            "enables": [
                # 使能关系模式
                (r"使得|能够|支持", 0.8),
                (r"启用|开启|允许", 0.7),
                (r"enables|allows|supports", 0.8),
                (r"activates|initiates|starts", 0.7),
            ],
            "part_of": [
                # 组成关系模式
                (r"属于|包含|组成", 0.8),
                (r"部分|组件|模块", 0.7),
                (r"part of|component of|member of", 0.8),
            ],
        }
        
        # 实体类型关系规则
        self.entity_type_rules = {
            ("person", "organization"): "works_for",
            ("technology", "organization"): "used_by",
            ("technology", "technology"): "depends_on",
            ("person", "technology"): "uses",
        }
    
    def classify(self, source_entities: List[Entity], 
                target_entities: List[Entity], 
                content: str) -> Tuple[str, float]:
        """分类关系类型"""
        
        # 1. 基于内容模式分类
        content_relation, content_confidence = self._classify_by_content(content)
        
        # 2. 基于实体类型分类
        entity_relation, entity_confidence = self._classify_by_entity_types(
            source_entities, target_entities
        )
        
        # 3. 融合分类结果
        if content_confidence > entity_confidence:
            return content_relation, content_confidence
        else:
            return entity_relation, entity_confidence
    
    def _classify_by_content(self, content: str) -> Tuple[str, float]:
        """基于内容模式分类"""
        best_relation = "related"
        best_confidence = 0.5
        
        for relation_type, patterns in self.relation_patterns.items():
            for pattern, confidence in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    if confidence > best_confidence:
                        best_relation = relation_type
                        best_confidence = confidence
        
        return best_relation, best_confidence
```

### 3.4 依赖图谱构建 (DependencyGraphBuilder)

**利用RelationMixin构建依赖图谱**

```python
class DependencyGraphBuilder:
    """依赖图谱构建器"""
    
    def __init__(self, relation_mixin: RelationMixin):
        self.relation_mixin = relation_mixin
        self.dependency_graph = DependencyGraph()
    
    async def build_graph(self, memory_id: str, entities: List[Entity], 
                         dependencies: List[Dependency]) -> None:
        """构建依赖图谱"""
        
        # 1. 创建实体节点
        for entity in entities:
            entity_id = f"{entity.type}:{entity.text}"
            self.dependency_graph.add_entity(
                entity_id=entity_id,
                memory_id=memory_id,
                metadata={
                    "type": entity.type,
                    "text": entity.text,
                    "confidence": entity.confidence,
                }
            )
            
            # 同步到RelationMixin
            self.relation_mixin.create_relation(
                source_memory_id=memory_id,
                target_memory_id=entity_id,
                relation_type="contains_entity",
                strength=entity.confidence,
                metadata={"entity_type": entity.type}
            )
        
        # 2. 创建依赖边
        for dep in dependencies:
            # 创建依赖关系
            self.dependency_graph.add_dependency(
                source_id=dep.source_entity_id,
                target_id=dep.target_entity_id,
                relation_type=dep.relation_type,
                strength=dep.strength
            )
            
            # 同步到RelationMixin
            self.relation_mixin.create_relation(
                source_memory_id=dep.source_memory_id,
                target_memory_id=dep.target_memory_id,
                relation_type=dep.relation_type,
                strength=dep.strength,
                metadata={
                    "discovery_method": dep.discovery_method,
                    "confidence": dep.confidence,
                }
            )
```

---

## 4. 集成到现有MOE架构

### 4.1 与ExpertDrilldownRetriever集成

```python
class DependencyAwareExpertDrilldown(ExpertDrilldownRetriever):
    """依赖感知的专家下钻检索器"""
    
    def __init__(self, expert_def, store, vector_store, dependency_extractor):
        super().__init__(expert_def, store, vector_store)
        self.dependency_extractor = dependency_extractor
    
    async def retrieve_with_dependencies(self, query: str, query_vec: List[float], 
                                        limit: int = 10) -> Tuple[List[Dict], List[Dependency]]:
        """检索记忆并提取依赖关系"""
        
        # 1. 正常检索
        memories = await self.retrieve(query, query_vec, limit)
        
        # 2. 提取依赖关系
        all_dependencies = []
        for memory in memories:
            deps = await self.dependency_extractor.extract_dependencies(
                memory["id"], memory["content"]
            )
            all_dependencies.extend(deps)
        
        return memories, all_dependencies
```

### 4.2 与MoEMemoryRouter集成

```python
class DependencyAwareMoERouter(MoEMemoryRouter):
    """依赖感知的MoE路由器"""
    
    def __init__(self, experts, storage, vector_store, dependency_extractor):
        super().__init__(experts, storage, vector_store)
        self.dependency_extractor = dependency_extractor
    
    async def retrieve_with_dependency_reasoning(self, query: str, 
                                                limit: int = 10) -> Tuple[List[Dict], DependencyGraph]:
        """检索并进行依赖推理"""
        
        # 1. 正常MoE检索
        memories = await self.retrieve(query, limit)
        
        # 2. 构建查询的依赖图谱
        query_entities = await self.dependency_extractor.entity_extractor.extract(query)
        
        # 3. 扩展检索：基于依赖关系
        extended_memories = await self._extend_by_dependencies(
            memories, query_entities, limit
        )
        
        # 4. 构建依赖图谱
        dependency_graph = await self._build_query_dependency_graph(
            query_entities, extended_memories
        )
        
        return extended_memories, dependency_graph
    
    async def _extend_by_dependencies(self, initial_memories: List[Dict], 
                                     query_entities: List[Entity], 
                                     limit: int) -> List[Dict]:
        """基于依赖关系扩展检索结果"""
        
        extended = list(initial_memories)
        seen_ids = {m["id"] for m in initial_memories}
        
        for memory in initial_memories:
            # 获取该记忆的依赖关系
            dependencies = self.dependency_extractor.dependency_graph.get_downstream(
                memory["id"]
            )
            
            # 添加依赖的记忆
            for dep_id in dependencies:
                if dep_id not in seen_ids:
                    # 从存储中获取依赖的记忆
                    dep_memory = await self._get_memory_by_id(dep_id)
                    if dep_memory:
                        extended.append(dep_memory)
                        seen_ids.add(dep_id)
        
        return extended[:limit]
```

---

## 5. 优势分析

### 5.1 相比LLM方案的优势

| 维度 | LLM方案 | MOE规则方案 | 优势 |
|------|---------|-------------|------|
| **成本** | 高（API调用） | 低（本地计算） | **MOE方案** |
| **延迟** | 高（100-500ms） | 低（1-10ms） | **MOE方案** |
| **可解释性** | 低（黑盒） | 高（规则透明） | **MOE方案** |
| **一致性** | 低（随机性） | 高（确定性） | **MOE方案** |
| **准确性** | 高（语义理解） | 中（规则覆盖） | **LLM方案** |
| **覆盖率** | 高（泛化能力） | 中（规则限制） | **LLM方案** |

### 5.2 混合策略（推荐）

```python
class HybridDependencyExtractor:
    """混合依赖提取器（规则优先 + LLM补充）"""
    
    def __init__(self, rule_extractor, llm_extractor):
        self.rule_extractor = rule_extractor
        self.llm_extractor = llm_extractor
        self.confidence_threshold = 0.7
    
    async def extract(self, memory_id: str, content: str) -> List[Dependency]:
        """混合提取策略"""
        
        # 1. 规则提取
        rule_deps = await self.rule_extractor.extract_dependencies(memory_id, content)
        
        # 2. 评估规则提取质量
        avg_confidence = self._calculate_avg_confidence(rule_deps)
        
        # 3. 如果置信度低，使用LLM补充
        if avg_confidence < self.confidence_threshold:
            llm_deps = await self.llm_extractor.extract_dependencies(memory_id, content)
            
            # 4. 融合结果
            merged_deps = self._merge_dependencies(rule_deps, llm_deps)
            return merged_deps
        
        return rule_deps
```

---

## 6. 实施计划

### 6.1 Phase 1：实体提取增强（2天）

**目标**：增强QueryTags.entities，支持更准确的实体提取

**任务**：
1. 扩展正则模式库
2. 实现实体消歧
3. 实现实体归一化
4. 添加缓存机制

### 6.2 Phase 2：关系发现层（3天）

**目标**：基于MOE架构实现关系发现

**任务**：
1. 实现向量相似度发现
2. 实现时间关系发现
3. 实现共现实体发现
4. 实现模式匹配发现

### 6.3 Phase 3：关系分类器（2天）

**目标**：基于规则引擎实现关系分类

**任务**：
1. 设计关系模式规则
2. 实现内容模式分类
3. 实现实体类型分类
4. 实现置信度计算

### 6.4 Phase 4：图谱构建（2天）

**目标**：构建依赖图谱并集成到检索流程

**任务**：
1. 实现DependencyGraphBuilder
2. 集成到ExpertDrilldownRetriever
3. 集成到MoEMemoryRouter
4. 测试端到端流程

### 6.5 Phase 5：优化与测试（2天）

**目标**：性能优化和测试验证

**任务**：
1. 性能优化（缓存、并行）
2. 准确性测试
3. 与MEEM任务对比
4. 文档编写

---

## 7. 预期效果

### 7.1 性能预测

| 指标 | LLM方案 | MOE规则方案 | 混合方案 |
|------|---------|-------------|----------|
| **提取延迟** | 200ms | 5ms | 10ms |
| **成本/提取** | $0.001 | $0.0001 | $0.0003 |
| **准确性** | 85% | 70% | 80% |
| **覆盖率** | 90% | 60% | 75% |

### 7.2 与MEEM任务的对应

| MEEM任务 | MOE规则方案支持 | 预期准确率提升 |
|----------|-----------------|----------------|
| **ER** (实体检索) | ✅ 实体提取 | +10% |
| **Agg** (聚合) | ✅ 共现实体 | +20% |
| **Tr** (转换) | ⚠️ 部分支持 | +10% |
| **Del** (删除) | ✅ 依赖图谱 | +30% |
| **Cas** (级联) | ✅ 依赖推理 | +40% |
| **Abs** (缺失) | ⚠️ 部分支持 | +15% |

---

## 8. 结论

### 8.1 核心洞察

Neurova的MOE架构**完全有能力**实现无LLM的依赖关系提取：

1. **实体提取**：QueryTags.entities + 规则引擎
2. **关系发现**：向量相似度 + 时间关系 + 共现分析
3. **关系分类**：规则引擎 + 模式匹配
4. **图谱构建**：RelationMixin + DependencyGraph

### 8.2 推荐策略

**混合策略**（规则优先 + LLM补充）：
- 80%情况使用规则提取（快速、低成本）
- 20%复杂情况使用LLM补充（高准确性）
- 综合成本降低70%，延迟降低90%

### 8.3 与NEURON架构的关系

MOE依赖提取器是NEURON架构的**核心组件**：
- 提供依赖图谱的数据来源
- 支持级联推理和缺失推理
- 与现有MOE架构无缝集成

---

**文档版本**：v1.0
**作者**：CodeBuddy
**最后更新**：2026年6月13日