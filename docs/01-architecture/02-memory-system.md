# 记忆系统架构设计

> **版本**: v1.0.0-beta1 (CogArch 2.0)  
> **最后更新**: 2026-06-07  
> **状态**: 生产就绪

## 1. 概述

### 1.1 设计目标

记忆系统是 Neurova 的核心组件，采用 CogArch 2.0 架构，通过 MemoryBus 事件总线将 1814 行 God Object 重构为 ~500 行 Facade + 12 个独立模块。

### 1.2 记忆分类体系

系统使用多维度分类，涵盖 **6 种记忆类型** × **7 种记忆分类** × **5 种生命周期阶段** × **4 种视角** × **9 种情感** = 多维记忆空间。

#### 记忆类型 (MemoryType) — 6 种

| 类型 | 说明 | 示例 |
|------|------|------|
| `semantic` | 语义记忆（事实知识） | "Python 是解释型语言" |
| `episodic` | 情景记忆（事件经历） | "昨天我们讨论了部署方案" |
| `procedural` | 程序记忆（技能操作） | "如何配置 Docker 部署" |
| `pattern` | 模式记忆（行为模式） | "用户总是在周一查看报表" |
| `emotional` | 情感记忆 | "那次失败让我很沮丧" |
| `working` | 工作记忆（临时上下文） | "当前正在处理的任务" |

#### 记忆分类 (MemoryCategory) — 7 种

| 分类 | 说明 |
|------|------|
| `general` | 通用 |
| `conversation` | 对话记录 |
| `knowledge` | 知识信息 |
| `experience` | 经验教训 |
| `tool_usage` | 工具使用 |
| `reflection` | 反思总结 |
| `user_preference` | 用户偏好 |

#### 生命周期阶段 (LifecycleStage) — 5 种

```
ACTIVE → CONSOLIDATED → ARCHIVED → FORGOTTEN
                    ↘ CRYSTALLIZED (永久)
```

| 阶段 | 说明 | 温度范围 |
|------|------|----------|
| `active` | 活跃使用中 | > 60 |
| `consolidated` | 已巩固到长期记忆 | 30-60 |
| `archived` | 不常用但保留 | 10-30 |
| `forgotten` | 标记为遗忘 | < 10 |
| `crystallized` | 结晶经验（永久） | 固定 100 |

#### 记忆视角 (MemoryPerspective) — 4 种

| 视角 | 说明 |
|------|------|
| `first_person` | 用户视角（"我觉得…"） |
| `second_person` | 交互视角（"你说过…"） |
| `third_person` | 客观视角（"根据文档…"） |
| `system` | 系统生成 |

#### 情感类型 (EmotionType) — 9 种

`neutral`, `joy`, `sadness`, `anger`, `fear`, `surprise`, `disgust`, `trust`, `anticipation`

## 2. 存储架构

### 2.1 LSM-Tree 五层架构

认知图谱统一存储引擎替代了旧版 mem_core.py + conversation_buffer.py + unified_vector_store.py：

| 层级 | 存储 | 时效 | 用途 |
|------|------|------|------|
| L0 Buffer | WAL 缓冲区 (内存 + JSONL) | 秒级 | 实时写入缓冲 |
| L1 Hot | SQLite 热存储 | 分钟级 | 高频访问 |
| L2 Warm | JSON 温存储 | 小时级 | NeurovaHebb 专用 |
| L3 Cold | 压缩冷存储 | 天级 | 低频访问 |
| L4 Crystal | 结晶经验 | 永久 | 重要经验固化 |

### 2.2 统一记忆节点

```python
@dataclass
class UnifiedMemoryNode:
    id: str
    content: str
    memory_type: MemoryType
    category: str = "general"
    temperature: float = 100.0    # 0-100 scale
    layer: StorageLayer = StorageLayer.L1_HOT
    metadata: Dict[str, Any]
    embedding: Optional[List[float]]
    access_count: int = 0
    trace_id: Optional[str] = None  # 推理链溯源
```

## 3. MemoryManager — Facade 模式

### 3.1 架构变更

```
旧: 1814 行 God Object，直接管理 13 个子系统，try/except 吞异常
新: ~500 行 Facade，通过 MemoryBus 注册 12 个独立模块
```

每个模块实现 `MemoryModule` 协议：
- 只依赖 `EventBus`，不直接引用其他模块
- 通过 `on(event_type, handler)` 订阅事件
- 通过 `emit(event)` 发布事件

### 3.2 子模块列表

| 模块 | 职责 |
|------|------|
| Storage | SQLite 持久化存储 |
| EmotionAnalyzer | 情感分析与标注 |
| AutoClassifier | 自动分类推断 |
| ConversationBuffer | 对话缓冲区 |
| ConflictDetector | 事实冲突检测 |
| RelationManager | 记忆关联管理 |
| SleepConsolidation | 睡眠整合/结晶 |
| ExplainabilityManager | 可解释性管理 |
| ForgettingRecovery | 遗忘恢复机制 |
| EmotionConduction | 情感传导 |
| WriteQueue | 异步写入队列 |
| EmotionModule | 情感模块 (SQLite 持久化) |

### 3.3 核心接口

```python
class MemoryManager:
    def remember(content: str, **kwargs) -> Memory
    def recall(query: str, **kwargs) -> List[Memory]
    def get_all_memories() -> List[Dict]
    def update_memory(memory_id: str, **kwargs) -> bool
    def get_memories_by_emotion(emotion_type: str) -> List[Memory]
    def consolidate(memories: List[Memory]) -> ConsolidationResult
    def shutdown() -> None
```

## 4. 三层隔离机制

使用 `IsolationContext` 不可变数据类作为三层隔离的单一事实源：

```python
@dataclass(frozen=True)
class IsolationContext:
    agent_id: str    # Agent 隔离
    neuser_id: str   # 系统用户隔离
    user_id: str     # 对话用户隔离
    shared: bool = False  # 跨 Agent 共享开关
```

### 隔离层级

| 层级 | 字段 | 说明 |
|------|------|------|
| Agent 隔离 | `agent_id` | 不同 Agent 数据隔离 |
| 系统用户隔离 | `neuser_id` | 不同用户数据隔离 |
| 对话用户隔离 | `user_id` | 同一用户不同对话隔离 |
| 共享开关 | `shared` | 跨 Agent 共享，可控范围 |

`shared=True` 时记忆不受 `agent_id` 约束，但仍受 `neuser_id` 和 `user_id` 隔离。

## 5. 多通道检索引擎

### 5.1 检索通道

| 通道 | 方法 | 权重 |
|------|------|------|
| 向量检索 | TF-IDF / FAISS / ChromaDB | 主要 |
| 关键词检索 | FTS5 全文搜索 | 辅助 |
| 情感检索 | 情感类型匹配 | 专用 |
| 时间检索 | 时间范围过滤 | 辅助 |
| 温度排序 | 活跃度加权 | 排序 |

### 5.2 向量搜索后端

```python
# 自动选择最佳后端
search = create_vector_search(mode="auto")
# 可选: TF-IDFBackend, FaissBackend, ChromaDBBackend
```

### 5.3 检索流程

```
查询 → 同义词扩展 → 向量化 → 多通道检索 → 合并去重 → 温度加权 → 情感匹配 → 结果排序
```

## 6. 温度管理机制

### 6.1 温度公式

```
访问时: temperature = min(100, temperature + 10)
衰减时: temperature = max(0, temperature - rate * hours)
```

### 6.2 生命周期转换

| 条件 | 转换 |
|------|------|
| 温度 > 60 | → `ACTIVE` |
| 温度 30-60 | → `CONSOLIDATED` |
| 温度 < 30 | → `ARCHIVED` |
| 超过保留期限 | → `FORGOTTEN` |
| 重要经验 | → `CRYSTALLIZED` |

## 7. 记忆整合系统

### 7.1 睡眠整合流程

```
用户空闲 → IdleTimeTracker.check_and_update_phase() → 阶段变更
  → _trigger_consolidation() → get_all_memories()
  → MemoryRecord.from_dict() 转换 → run_sleep_cycle()
  → consolidate() → _write_back_consolidated_memories()
  → 更新 MemoryManager (合并/归档/温度更新)
```

### 7.2 经验结晶流程

```
对话完成 → on_experience_recorded
  → ExperienceFeedback.process_experience (提取工具洞察)
  → tool_weights.update_weight (自适应权重)
  → pattern_miner.add_sequence (频繁模式挖掘)
  → crystallizer.observe (观察工具使用模式)
  → 模式积累 (≥3次 + 成功率>60%)
  → PatternCrystallizer._try_crystallize
  → CognitiveStorageEngine.store (PATTERN 类型)
```

### 7.3 梦境回放

```python
# 睡眠状态下随机选取重要记忆进行重组
result = sleep_consolidation.dream_replay()
# 产物存入 STM，记录梦境日志
```

## 8. 安全机制

### 8.1 敏感信息检测

8 个内置敏感模式：手机号、身份证、邮箱、银行卡、密码、API 密钥、IP、信用卡。

### 8.2 加密存储

- Fernet 对称加密（首选）
- Base64 + XOR 回退加密器

### 8.3 被遗忘权

支持删除指定记忆及其所有关联数据。

## 9. 核心文件

| 文件 | 职责 |
|------|------|
| `cognitive_layers/memory_layer/models.py` | 数据模型 (Memory, MemoryType 等) |
| `cognitive_layers/memory_layer/manager.py` | MemoryManager Facade |
| `cognitive_layers/memory_layer/storage.py` | SQLite 存储引擎 |
| `cognitive_layers/memory_layer/sleep.py` | 睡眠整合 |
| `cognitive_layers/memory_layer/neurova_recall.py` | 多通道检索引擎 |
| `cognitive_layers/memory_layer/isolation.py` | 三层隔离上下文 |
| `cognitive_layers/memory_layer/muscle_memory.py` | 肌肉记忆 (工具模式) |
| `cognitive_layers/memory_layer/cognitive_storage_engine.py` | LSM-Tree 存储引擎 |
| `cognitive_layers/memory_layer/vector_search_advanced.py` | 高级向量搜索 |
| `cognitive_layers/memory_layer/temporal_knowledge_graph.py` | 时序知识图谱 |
| `cognitive_layers/memory_layer/security.py` | 安全模块 |
| `cognitive_layers/memory_layer/bayesian_eki/cognitive_optimizer.py` | 贝叶斯认知优化器 |