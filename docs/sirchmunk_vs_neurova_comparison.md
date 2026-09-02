# Sirchmunk vs Neurova 记忆检索系统代码级对比

> **版本**: v1.0 | **日期**: 2026-06-08 | **方法**: improve-codebase-architecture 架构深度评估
> **Sirchmunk**: github.com/modelscope/sirchmunk (阿里 ModelScope 团队, 2026-02 开源)
> **Neurova**: E:/项目/Neurova (自主开发, 记忆检索模块 neurova/cognitive_layers/memory_layer/)

---

## 1. 引言

**Sirchmunk**（Search + Chipmunk，花栗鼠搜索引擎）是阿里 ModelScope 团队开发的无嵌入、Agentic 搜索引擎。核心理念：抛弃向量数据库和预索引，直接从原始数据中实时洞见。采用蒙特卡洛证据采样 + 自演化知识集群，实现"搜索即学习"。

**Neurova 记忆检索系统**是自主开发的多维融合记忆引擎，核心理念：不是"搜索"而是"浮现"——热的、情感的、相关的记忆自然浮现。采用 17 维分类 + 温度衰减 + 5 通道融合检索 + 意图驱动钻取。

两者代表了检索系统的两种范式：**Sirchmunk = 原始数据到自演化智能** vs **Neurova = 多维记忆浮现与钻取**。

---

## 2. 架构设计理念

### 2.1 Sirchmunk：无索引 Agentic 搜索

```
┌─ 集成层 ─────────────────────────────────────────┐
│  MCP / REST API / WebSocket / CLI / Web UI       │
├─ 编排层 ─────────────────────────────────────────┤
│  AgenticSearch 协调器                             │
│  ├── FAST 模式 (2-5s, 2 次 LLM 调用)            │
│  └── DEEP 模式 (10-30s, 完整管线)                │
├─ 智能层 ─────────────────────────────────────────┤
│  ├── GrepRetriever (ripgrep, 无索引全文搜索)     │
│  ├── EvidenceProcessor (蒙特卡洛证据采样)        │
│  ├── ReAct Agent (思考→行动→观察循环)            │
│  └── KnowledgeBase (知识集群管理)                │
├─ 存储层 ─────────────────────────────────────────┤
│  DuckDB (内存优先) → Parquet (磁盘持久化)        │
└──────────────────────────────────────────────────┘
```

### 2.2 Neurova：多维融合记忆引擎

```
┌─ Agent 层 ────────────────────────────────────────┐
│  Agent.chat() → ContextOrchestrator.build_context │
├─ 检索引擎层 ─────────────────────────────────────┤
│  NeurovaRecallEngine                              │
│  ├── Phase 1: 5 通道并行召回                      │
│  │   ├── Temperature (25%) 热记忆优先             │
│  │   ├── Text (30%) TF-IDF/FAISS 语义            │
│  │   ├── Category (15%) 同类别索引                │
│  │   ├── Graph (10%) 关系图谱遍历                 │
│  │   └── Emotion (10%) 情感相似度                 │
│  └── Phase 2: 5 种意图驱动钻取                    │
│      Explore / Deepen / Connect / Contrast /      │
│      Validate                                     │
├─ 记忆管理层 ─────────────────────────────────────┤
│  MemoryManager (EventBus 解耦, 12 个子模块)       │
│  ├── TemperatureEngine (贝叶斯遗忘曲线)           │
│  ├── TemporalKnowledgeGraph (时序知识图谱)        │
│  ├── EmotionModule (情感标注+保护)                │
│  ├── VectorSearchAdvanced (TF-IDF/FAISS/Chroma)  │
│  └── EKICognitiveOptimizer (集合卡尔曼反演)       │
├─ 存储层 ─────────────────────────────────────────┤
│  SQLite (零配置) + 内存缓存                       │
└──────────────────────────────────────────────────┘
```

### 2.3 理念差异

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **核心范式** | 无索引 Agentic 搜索 | 多维记忆浮现与钻取 |
| **知识组织** | 自演化知识集群 (KnowledgeCluster) | 17 维分类 + 温度层级 |
| **索引策略** | 无预索引，ripgrep 实时搜索 | TF-IDF/FAISS 预建索引 |
| **学习机制** | 每次搜索自动演化知识集群 | 贝叶斯遗忘 + 睡眠巩固 |
| **LLM 角色** | 证据合成 + ReAct 智能体 | 上下文构建 + 意图理解 |

---

## 3. 核心数据结构

### 3.1 Sirchmunk: KnowledgeCluster

```python
class KnowledgeCluster:
    """自演化知识集群 — Sirchmunk 核心数据结构"""
    id: str                  # SHA256 确定性身份
    evidences: List[Evidence]  # 蒙特卡洛采样提取的证据
    content: str             # LLM 合成的 Markdown 内容
    patterns: List[str]      # 3-5 个设计原则/机制
    confidence: float        # 置信度 (0-1)
    queries: List[str]       # 历史查询 (FIFO, 最多5个)
    hotness: float           # 活跃度分数
    embedding: List[float]   # 384 维语义向量
    # 存储：DuckDB (内存) → Parquet (磁盘)

class Evidence:
    """证据单元"""
    file_path: str           # 源文件路径
    summary: str             # 摘要
    raw_text: str            # 原始文本片段
    relevance_score: float   # 相关性评分
```

### 3.2 Neurova: Memory + RecalledMemory

```python
@dataclass
class Memory:
    """17 维记忆数据结构"""
    id: str; content: str
    memory_type: MemoryType        # 6 种: Semantic/Episodic/Procedural/Pattern/Emotional/Working
    category: MemoryCategory       # 7 种: General/Conversation/Knowledge/Experience/ToolUsage/Reflection/UserPreference
    lifecycle_stage: LifecycleStage # 5 种: Active/Consolidated/Archived/Forgotten/Crystallized
    emotion: EmotionType           # 9 种: Neutral/Joy/Sadness/Anger/Fear/Surprise/Disgust/Trust/Anticipation
    temperature: float             # 0-100°C (贝叶斯遗忘曲线)
    importance: float; recall_count: int
    agent_id: str; neuser_id: str; user_id: str  # 3 层隔离

@dataclass
class RecalledMemory:
    """召回的记忆"""
    memory_id: str; content: str; score: float
    channel: RecallChannel         # 6 种通道
    recalled_at: datetime

@dataclass
class TemporalFact:
    """时序事实 (基于 Zep/Graphiti)"""
    subject: str; predicate: str; object: str
    relation_type: RelationType    # 9 种关系
    status: FactStatus             # 4 种状态
    valid_from: datetime; valid_until: Optional[datetime]
```

### 3.3 数据结构对比

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **核心单元** | KnowledgeCluster（知识集群） | Memory（17 维记忆） |
| **身份机制** | SHA256 内容哈希 | UUID + 内容哈希 |
| **置信度** | 有 (0-1) | 有 (importance + temperature) |
| **活跃度** | hotness 分数 | temperature (0-100°C) |
| **向量嵌入** | 384 维 (历史查询集合) | TF-IDF 向量 / FAISS 可选 |
| **情感** | 无 | 9 种情感类型 |
| **时序** | 查询历史 (FIFO) | 时序知识图谱 (有效期窗口) |
| **生命周期** | 萌芽→稳定→弃用 | 5 阶段 (Active→Crystallized) |
| **隔离** | 无 | 3 层 (Agent/Neuser/User) |
| **可追溯性** | Evidence → 源文件 | source_memory_id → 源记忆 |

---

## 4. 检索机制

### 4.1 Sirchmunk: 蒙特卡洛证据采样

```python
# Sirchmunk 检索流程（实际架构）
class AgenticSearch:
    def search(self, query: str, mode: str = "FAST") -> Result:
        # 阶段 0: 知识集群复用（亚秒级）
        existing = self.knowledge_base.find_similar(query, threshold=0.85)
        if existing:
            existing.update_queries(query)
            existing.update_hotness()
            return existing.content  # 命中缓存，直接返回

        # 阶段 1: 并行探测
        keywords = llm.extract_keywords(query)      # LLM 关键词提取
        files = grep_retriever.search(keywords)      # ripgrep 全文搜索
        cached = knowledge_base.lookup(query)        # 知识缓存查找
        context = load_path_context(query)           # 路径上下文

        # 阶段 2: 检索与排序
        ranked = idf_ranking(files, keywords)        # IDF 加权评分
        structural = llm.rank_by_metadata(files)     # LLM 结构化排序

        # 阶段 3: 蒙特卡洛证据采样
        if mode == "DEEP":
            evidence = monte_carlo_sampling(ranked, query)
            # Phase 1: 撒网 — 模糊锚定 + 分层随机采样
            # Phase 2: 聚焦 — 高斯重要性采样 (sigma 递减)
            # Phase 3: 合成 — Top-K 片段 LLM 合成 ROI 摘要

        # 阶段 4: 知识集群构建
        cluster = KnowledgeCluster(
            evidences=evidence,
            content=llm.synthesize(evidence, query),
            patterns=llm.extract_patterns(evidence),
            confidence=calculate_confidence(evidence),
            embedding=compute_embedding(queries),
        )

        # 阶段 5: 持久化（自演化）
        knowledge_base.store(cluster)  # DuckDB + Parquet
        return cluster.content

        # 阶段 4b: 无证据时启动 ReAct Agent
        if not evidence:
            agent = ReActAgent(tools=[keyword_search, file_read, cache_query, dir_scan])
            return agent.run(query, token_budget=5000, max_loops=10)
```

### 4.2 Neurova: 5 通道融合检索

```python
# Neurova 检索流程（实际代码）
class NeurovaRecallEngine:
    def recall(self, query: str, intent: DrillIntent) -> RecallResult:
        # Phase 1: 5 通道并行召回
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._channel_temperature, query): TEMPERATURE,  # 热记忆
                executor.submit(self._channel_text, query): TEXT,                # TF-IDF/FAISS
                executor.submit(self._channel_category, query): CATEGORY,        # 同类别
                executor.submit(self._channel_graph, query): GRAPH,              # 关系图谱
                executor.submit(self._channel_emotion, query): EMOTION,          # 情感
            }
            results = collect_with_timeout(futures, timeout=10.0)

        # 多信号加权融合
        weights = {TEMPERATURE: 0.25, TEXT: 0.30, CATEGORY: 0.15, GRAPH: 0.10, EMOTION: 0.10}
        merged = deduplicate_and_fusion_score(results, weights)

        # Phase 2: 意图驱动钻取
        if intent == EXPLORE:   drilled = drill_explore(merged)    # 发现新知识
        elif intent == DEEPEN:  drilled = drill_deepen(merged)     # 深入理解
        elif intent == CONNECT: drilled = drill_connect(merged)    # 建立关联
        elif intent == CONTRAST:drilled = drill_contrast(merged)   # 寻找差异
        elif intent == VALIDATE:drilled = drill_validate(merged)   # 确认事实

        return RecallResult(recalled_memories=drilled, phase1_ms=..., phase2_ms=...)
```

### 4.3 检索机制对比

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **检索策略** | 蒙特卡洛采样 + ReAct 智能体 | 5 通道并行 + 意图钻取 |
| **索引方式** | 无预索引 (ripgrep 实时) | TF-IDF/FAISS 预建索引 |
| **缓存机制** | 知识集群复用 (cosine ≥0.85) | 无显式检索缓存 |
| **证据提取** | 蒙特卡洛 3 阶段采样 | 多通道加权排序 |
| **LLM 使用** | 关键词提取 + 证据合成 + ReAct | 上下文构建（检索阶段无 LLM） |
| **噪声过滤** | IDF 加权 + LLM 结构化排序 | 多信号加权融合 |
| **意图感知** | FAST/DEEP 两种模式 | 5 种钻取意图 |
| **情感检索** | 无 | 独立情感通道 |
| **温度感知** | hotness 分数 | 温度通道 (贝叶斯遗忘) |
| **响应时间** | 2-5s (FAST) / 10-30s (DEEP) | ~20ms (5 通道并行) |

---

## 5. 知识演化与记忆管理

### 5.1 Sirchmunk: 自演化知识集群

```python
# Sirchmunk 自演化机制
class KnowledgeBase:
    def store(self, cluster: KnowledgeCluster):
        # 确定性 ID（相同内容 → 相同 ID）
        cluster.id = sha256(cluster.content)
        # 持久化：DuckDB (内存) → Parquet (磁盘)
        self.db.insert(cluster)
        self.parquet.sync()

    def find_similar(self, query: str, threshold=0.85) -> Optional[KnowledgeCluster]:
        query_emb = compute_embedding(query)
        for cluster in self.db.all():
            sim = cosine_similarity(query_emb, cluster.embedding)
            if sim >= threshold:
                # 复用：更新查询历史、热度、嵌入
                cluster.queries.append(query)  # FIFO, max 5
                cluster.hotness = compute_hotness(cluster.queries)
                cluster.embedding = recompute_embedding(cluster.queries)
                return cluster
        return None
```

**演化特征**：
- 每次搜索自动创建/更新知识集群
- 查询历史拓宽语义覆盖面
- 热度分数反映访问频率
- 嵌入向量随查询演化

### 5.2 Neurova: 温度衰减 + 睡眠巩固

```python
# Neurova 记忆管理（实际代码）
class TemperatureEngine:
    def on_access(self, current_temp, importance, recall_count):
        # 访问升温
        return current_temp + 10*importance + min(recall_count*2, 20)

    def on_decay(self, current_temp, days_idle, importance, emotion_score):
        # 贝叶斯遗忘曲线
        curve_factor = 1 / (1 + days_idle * self.base_decay_rate)
        emotion_protection = 0.6 if emotion_score > 0.5 else 1.0
        saturation = 1.0 - (current_temp / 100.0) ** 2
        return current_temp * curve_factor * emotion_protection * saturation

class SleepConsolidation:
    def consolidate(self, memories, isolation_context):
        # 空闲时自动整理
        for memory in memories:
            memory.temperature = engine.on_decay(...)  # 温度衰减
            if memory.temperature < 20:
                memory.lifecycle_stage = ARCHIVED      # 归档
            if memory.temperature < 5:
                memory.lifecycle_stage = FORGOTTEN      # 遗忘
        # 合并相似记忆、结晶高频记忆
```

**管理特征**：
- 贝叶斯遗忘曲线模拟人类记忆衰减
- 情感保护（情感记忆衰减减缓 40%）
- 5 阶段生命周期管理
- 睡眠巩固（空闲时自动整理）

### 5.3 知识演化对比

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **学习方式** | 每次搜索自动演化 | 温度衰减 + 睡眠巩固 |
| **遗忘机制** | 无显式遗忘 | 贝叶斯遗忘曲线 |
| **情感保护** | 无 | 情感记忆衰减减缓 40% |
| **生命周期** | 萌芽→稳定→弃用 | 5 阶段 |
| **知识图谱** | 弱语义边 + 认知边 | 时序知识图谱 (9 种关系) |
| **冲突检测** | 无 | 时序事实冲突检测 |
| **多租户** | 无 | 3 层隔离 + 共享开关 |

---

## 6. 技术栈

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **语言** | Python 72.5% + TypeScript 26.3% | Python 100% |
| **搜索引擎** | ripgrep-all (Rust, 无索引) | TF-IDF/FAISS/ChromaDB |
| **存储** | DuckDB + Parquet | SQLite (零配置) |
| **LLM 接口** | OpenAI 兼容 (任何 LLM) | 多 Provider (OpenAI/Anthropic/Gemini/Ollama) |
| **API 框架** | FastAPI | FastAPI |
| **前端** | Next.js Web UI | Vue 3 + Vite |
| **协议** | MCP / REST / WebSocket / SSE | REST / WebSocket / SSE |
| **容器化** | Docker 镜像 | Docker Compose |
| **许可证** | Apache 2.0 | MIT |

---

## 7. 性能基准

| 维度 | Sirchmunk | Neurova |
|------|-----------|---------|
| **快速检索** | 2-5s (FAST 模式, 2 次 LLM) | ~20ms (5 通道并行, 0 次 LLM) |
| **深度检索** | 10-30s (DEEP 模式, 完整管线) | ~100ms (含意图钻取) |
| **缓存命中** | <100ms (知识集群复用) | ~5ms (内存缓存) |
| **LLM 依赖** | 检索阶段需要 LLM | 检索阶段无 LLM |
| **数据规模** | 文件级 (2 页 ~ 500 页) | 记忆级 (10 万+ 记录) |
| **实时性** | 实时 (无预索引) | 准实时 (索引需更新) |

---

## 8. 综合评分

权重：架构(15%) + 数据结构(10%) + 检索机制(15%) + 扩展性(10%) + 性能(10%) + 易用性(10%) + 文档(5%) + 测试(10%) + 创新性(10%) + 成熟度(5%)

| 维度 | 权重 | Sirchmunk | Neurova | 说明 |
|------|------|-----------|---------|------|
| 架构设计 | 15% | 9.0 | 9.0 | 各有特色：Agentic vs 多维融合 |
| 数据结构 | 10% | 7.5 | 9.0 | Neurova 17 维分类 + 情感更丰富 |
| 检索机制 | 15% | 9.0 | 8.5 | Sirchmunk 蒙特卡洛采样更创新 |
| 可扩展性 | 10% | 8.0 | 7.5 | Sirchmunk DuckDB+Parquet 更灵活 |
| 性能 | 10% | 7.5 | 9.0 | Neurova 无 LLM 依赖，20ms 响应 |
| 易用性 | 10% | 8.5 | 8.0 | Sirchmunk MCP + Web UI 更现代 |
| 文档 | 5% | 8.5 | 7.5 | Sirchmunk 技术深度报告更完善 |
| 测试 | 10% | 7.0 | 9.5 | Neurova 419 测试 99.8% 远超 |
| 创新性 | 10% | 9.5 | 8.0 | Sirchmunk 无索引+蒙特卡洛是范式突破 |
| 成熟度 | 5% | 7.0 | 8.5 | Neurova 生产就绪度更高 |
| **加权总分** | | **8.28** | **8.43** | |

---

## 9. 优劣势总结

### 9.1 Sirchmunk

#### 优势
1. **无索引范式突破** — ripgrep 实时搜索，无需预建向量索引，"拖放即搜索"
2. **蒙特卡洛证据采样** — 三阶段"探索-利用"策略，从 2 页到 500 页文档通用
3. **自演化知识集群** — 每次搜索自动学习，查询历史拓宽语义覆盖，实现"知识复利"
4. **ReAct 智能体** — 标准搜索未命中时自动启动，按成本梯度使用工具
5. **MCP 协议支持** — 与 Claude Desktop、Cursor IDE 等无缝集成

#### 劣势
1. **LLM 依赖较重** — 检索阶段需要 LLM（关键词提取、证据合成、ReAct），增加延迟和成本
2. **无情感/温度机制** — 缺乏情感记忆、遗忘曲线、温度衰减
3. **无多租户隔离** — 不支持多 Agent/多用户数据隔离
4. **实时性受限** — 2-5s (FAST) vs Neurova 的 20ms，差距 100 倍
5. **代码级测试覆盖** — 未公开测试数据

### 9.2 Neurova

#### 优势
1. **17 维记忆分类** — 6 种 MemoryType + 7 种 Category + 5 种 LifecycleStage + 9 种 EmotionType
2. **零 LLM 检索** — 5 通道并行检索完全不依赖 LLM，20ms 响应
3. **贝叶斯遗忘曲线** — 温度衰减模拟人类记忆，情感保护减缓 40% 衰减
4. **时序知识图谱** — 基于 Zep/Graphiti，支持事实有效期、冲突检测、历史查询
5. **工程化成熟** — 419 测试 99.8% 通过率，3 层隔离，零配置 SQLite

#### 劣势
1. **缺乏知识自演化** — 没有 Sirchmunk 的"搜索即学习"机制
2. **证据采样较弱** — 没有蒙特卡洛采样，依赖预建索引
3. **文档级检索缺失** — 面向记忆级数据，不支持原始文件搜索
4. **MCP 集成缺失** — 不支持 MCP 协议，无法与 Claude/Cursor 无缝集成
5. **ReAct 能力不足** — 检索未命中时缺乏自主探索机制

---

## 10. 结论与建议

### 10.1 评分结论

| 系统 | 总分 | 核心竞争力 |
|------|------|-----------|
| **Sirchmunk** | **8.28/10** | 无索引 Agentic 搜索、蒙特卡洛证据采样、自演化知识集群、MCP 集成 |
| **Neurova** | **8.43/10** | 17 维分类、贝叶斯遗忘曲线、5 通道融合检索、零 LLM 检索、工程成熟度 |

### 10.2 技术选型建议

**选 Sirchmunk 当**：
- 需要从原始文件（PDF/代码/文档）中实时检索
- 需要"搜索即学习"的自演化能力
- 已有 LLM 调用预算（每次搜索 2 次 LLM 调用）
- 需要 MCP 协议集成（Claude Desktop/Cursor IDE）
- 文档级知识管理场景

**选 Neurova 当**：
- 需要 Agent 长期记忆管理（对话/经验/情感/工具使用）
- 需要零 LLM 依赖的毫秒级检索
- 需要情感感知和遗忘曲线模拟
- 多租户 SaaS 场景（3 层隔离）
- 生产环境需要充分测试保障

### 10.3 互学互鉴

**Neurova 可向 Sirchmunk 学习**：
1. 引入蒙特卡洛证据采样增强 Graph 通道的证据提取能力
2. 实现知识集群复用机制（cosine ≥0.85 时直接返回缓存）
3. 添加 MCP 协议支持，与 Claude/Cursor 集成
4. 实现 ReAct Agent 作为检索未命中时的降级策略

**Sirchmunk 可向 Neurova 学习**：
1. 引入温度衰减和贝叶斯遗忘曲线替代简单 hotness 分数
2. 添加情感记忆和情感保护机制
3. 实现零 LLM 检索通道作为 FAST 模式的降级方案
4. 建立完善的测试体系（400+ 测试）

### 10.4 混合架构设想

```
HybridSystem
├── Sirchmunk Engine  ← 文档级知识管理
│   ├── ripgrep 无索引搜索 (原始文件)
│   ├── 蒙特卡洛证据采样 (深度分析)
│   ├── 自演化知识集群 (知识复利)
│   └── ReAct Agent (自主探索)
├── Neurova Memory Core  ← Agent 记忆管理
│   ├── 17-Dimension Classifier
│   ├── TemperatureEngine (遗忘曲线)
│   ├── EmotionHubEngine (情感共鸣)
│   └── TemporalKnowledgeGraph (时序事实)
└── Unified Recall Orchestrator
    ├── 知识集群复用 (Sirchmunk) → 文档类查询
    ├── 5-Channel Fusion (Neurova) → 记忆类查询
    └── Result Merger → 加权融合输出
```

> **结论**：Sirchmunk 和 Neurova 代表了检索系统的两个互补方向——Sirchmunk 是"文档知识引擎"（从原始数据到自演化智能），Neurova 是"Agent 记忆引擎"（多维浮现与钻取）。两者总分接近（8.28 vs 8.43），差异在于适用场景：Sirchmunk 适合文档级知识管理，Neurova 适合 Agent 长期记忆。理想方案是将 Sirchmunk 的无索引搜索和自演化能力与 Neurova 的温度衰减和情感保护相结合。