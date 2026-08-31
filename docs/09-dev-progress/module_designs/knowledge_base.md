# Neurova 认知知识库模块设计文档

> 版本: 1.0.0
> 日期: 2025-05-14
> 状态: 设计完成

## 1. 概述

### 1.1 模块目标

认知知识库（Cognitive Knowledge Base, CKB）模块是 Neurova 的核心扩展模块，旨在：

1. **接入外部知识源**：通过适配器模式接入心流知识库（iflow）
2. **知识与记忆融合**：实现知识库与记忆系统的双向同步
3. **驱动自我进化**：基于知识盲点分析和反思日志促进 Agent 能力成长

### 1.2 设计原则

| 原则 | 描述 |
|------|------|
| **插件化架构** | 知识源通过适配器接入，支持扩展其他知识库 |
| **双向同步** | 知识 ↔ 记忆 实时关联，互为补充 |
| **渐进式进化** | 基于访问频率和反思日志自动发现并填补知识盲点 |
| **RAG 增强** | 为 Agent 提供结合记忆和知识的增强上下文 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                           Cognitive Knowledge Base (CKB)                       │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    Knowledge Source Layer (知识源层)                        │ │
│  │                                                                             │ │
│  │  ┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐  │ │
│  │  │  FlowKB Adapter      │  │  LocalDocs Adapter  │  │  Future Adapters │  │ │
│  │  │  (心流知识库)        │  │  (本地文档)          │  │  (飞书/百炼等)   │  │ │
│  │  └──────────────────────┘  └──────────────────────┘  └──────────────────┘  │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                          │                                       │
│                                          ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                    Knowledge Integration Layer (知识集成层)                   │ │
│  │                                                                             │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐    │ │
│  │  │ MemorySync       │  │ EvolutionHub     │  │ EnhancedRetrieval     │    │ │
│  │  │ (记忆双向同步)   │  │ (进化中枢)       │  │ (RAG 增强检索)       │    │ │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘    │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                          │                                       │
│                                          ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────────────┐ │
│  │                         Application Layer                                   │ │
│  │                                                                             │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐    │ │
│  │  │ Agent Context     │  │ Reflection Log   │  │ Skill Execution        │    │ │
│  │  │ Enhancement       │  │ Processing       │  │ Knowledge Lookup       │    │ │
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘    │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
neurova/knowledge/
├── __init__.py                    # 模块导出
├── config.py                      # 配置管理
├── storage.py                     # 用户级 API Key 存储
├── adapters/
│   ├── __init__.py
│   └── flow_kb.py                # 心流知识库适配器
├── integration/
│   ├── __init__.py
│   ├── memory_sync.py            # 记忆同步器
│   ├── evolution_hub.py          # 进化中枢
│   └── cognitive_loop.py         # 认知闭环协调器 ⭐
└── rag/
    ├── __init__.py
    └── enhanced_retrieval.py     # RAG 增强检索
```

---

## 3. 核心模块

### 3.1 心流知识库适配器 (FlowKBAdapter)

#### 功能
- 封装 iflow API 的所有操作
- 提供同步的 Python API
- 管理知识库、文档、检索

#### 核心 API

```python
class FlowKBAdapter:
    # 知识库管理
    async def create_knowledge_base(name, description) -> str
    async def list_knowledge_bases() -> List[Dict]
    async def get_knowledge_base(collection_id) -> Dict
    async def delete_knowledge_base(collection_id) -> bool

    # 文档管理
    async def add_document(collection_id, source, name=None) -> str
    async def list_documents(collection_id) -> List[Dict]
    async def delete_document(document_id) -> bool

    # 语义检索
    async def search(query, collection_id=None, limit=10) -> List[KnowledgeItem]
    async def search_multi_collection(query, collection_ids=None) -> List[KnowledgeItem]

    # 联网搜索
    async def web_search(query, collection_id=None) -> List[KnowledgeItem]
```

#### 配置

```python
class FlowKBConfig:
    api_key: Optional[str] = None           # 心流 API Key
    base_url: str = "https://platform.iflow.cn"
    timeout: int = 30
    max_retries: int = 3
```

---

### 3.2 记忆同步器 (MemorySync)

#### 功能
- 实现知识库与记忆系统的双向同步
- 维护记忆-知识关联
- 智能去重和相似度检测

#### 同步机制

```
┌─────────────────────────────────────────────────────────────────┐
│                     双向同步流程                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  【知识 → 记忆】                                                   │
│                                                                  │
│  1. RAG 检索返回知识条目                                           │
│  2. 检查相似记忆是否存在                                           │
│  3. 存在 → 更新关联                                               │
│  4. 不存在 → 创建新记忆 + 建立关联                                 │
│                                                                  │
│  【记忆 → 知识】                                                   │
│                                                                  │
│  1. 发现高温记忆 (访问频率 > 阈值)                                 │
│  2. 或用户主动标记同步                                             │
│  3. 提取记忆内容                                                   │
│  4. 同步到知识库                                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 关联类型

| 类型 | 描述 |
|------|------|
| `derived` | 知识由记忆衍生 |
| `from` | 知识来源自记忆 |
| `explains` | 知识解释记忆 |
| `supports` | 知识支持记忆 |
| `contradicts` | 知识矛盾记忆 |

---

### 3.3 进化中枢 (EvolutionHub)

#### 功能
- 分析知识盲点
- 从知识库主动学习
- 反思驱动自我改进

#### 进化机制

```
┌─────────────────────────────────────────────────────────────────┐
│                       认知进化流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  【触发条件】                                                     │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ 知识盲点发现 │  │ 反思日志完成 │  │ 空闲周期    │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                     │
│         └────────────────┼────────────────┘                     │
│                          ▼                                       │
│                  ┌───────────────┐                               │
│                  │  进化中枢      │                               │
│                  └───────┬───────┘                               │
│                          │                                       │
│         ┌────────────────┼────────────────┐                     │
│         ▼                ▼                ▼                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │ 分析盲点     │  │ 知识库学习   │  │ 反思进化    │            │
│  │ - 访问频率  │  │ - 提取概念  │  │ - 提取改进  │            │
│  │ - 证据收集  │  │ - 同步记忆  │  │ - 更新能力  │            │
│  └─────────────┘  └─────────────┘  └─────────────┘            │
│                          │                                       │
│                          ▼                                       │
│                  ┌───────────────┐                               │
│                  │ 能力模型更新   │                               │
│                  └───────────────┘                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### 知识盲点优先级

| 优先级 | 条件 | 说明 |
|--------|------|------|
| `CRITICAL` | 访问次数 ≥ 10 | 急需学习 |
| `HIGH` | 访问次数 ≥ 7 | 优先学习 |
| `MEDIUM` | 访问次数 ≥ 4 | 计划学习 |
| `LOW` | 访问次数 < 4 | 观察中 |

---

### 3.4 RAG 增强检索 (EnhancedRetrieval)

#### 功能
- 结合记忆系统和知识库进行语义检索
- 自动计算相关性分数
- 生成增强上下文

#### 检索流程

```python
async def retrieve(query, user_id=None) -> RAGContext:
    # 1. 并行检索
    kb_items = await _retrieve_knowledge(query)
    mem_items = await _retrieve_memory(query, user_id)

    # 2. 计算分数
    scores = _calculate_scores(kb_items, mem_items)

    # 3. 合并上下文
    context = _combine_context(kb_items, mem_items)

    # 4. 可选同步到记忆
    if sync_to_memory:
        await memory_sync.sync_knowledge_to_memory(kb_items)

    return RAGContext(...)
```

#### 权重配置

```python
class RetrievalConfig:
    max_knowledge_items: int = 5       # 最大知识库条目
    max_memory_items: int = 3         # 最大记忆条目
    knowledge_weight: float = 0.6     # 知识库权重
    memory_weight: float = 0.4        # 记忆权重
    score_threshold: float = 0.3      # 分数阈值
    sync_to_memory: bool = True       # 是否同步到记忆
```

---

## 4. API 设计

### 4.1 知识库配置 API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/v1/knowledge/configs` | 创建知识库配置（API Key） |
| GET | `/v1/knowledge/configs` | 获取配置列表 |
| GET | `/v1/knowledge/configs/{id}` | 获取配置详情 |
| PUT | `/v1/knowledge/configs/{id}` | 更新配置 |
| DELETE | `/v1/knowledge/configs/{id}` | 删除配置 |

### 4.2 知识库 API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/v1/knowledge/collections` | 创建知识库 |
| GET | `/v1/knowledge/collections` | 列出知识库 |
| GET | `/v1/knowledge/collections/{id}` | 获取知识库详情 |
| PUT | `/v1/knowledge/collections/{id}` | 更新知识库 |
| DELETE | `/v1/knowledge/collections/{id}` | 删除知识库 |
| POST | `/v1/knowledge/documents/upload` | 上传文档 |
| GET | `/v1/knowledge/collections/{id}/documents` | 列出文档 |
| POST | `/v1/knowledge/search` | 语义检索 |
| POST | `/v1/knowledge/search/multi` | 多知识库检索 |
| POST | `/v1/knowledge/web-search` | 联网搜索 |

### 4.3 记忆同步 API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/v1/knowledge/memory/sync` | 同步知识到记忆 |
| POST | `/v1/knowledge/memory/sync-to-kb` | 同步记忆到知识库 |
| GET | `/v1/knowledge/memory/links` | 获取关联列表 |

### 4.4 RAG API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/v1/knowledge/rag` | RAG 增强检索 |
| POST | `/v1/knowledge/rag/batch` | 批量 RAG 检索 |

### 4.5 进化系统 API

| 方法 | 端点 | 描述 |
|------|------|------|
| POST | `/v1/evolution/analyze-gaps` | 分析知识盲点 |
| POST | `/v1/evolution/learn` | 从知识库学习 |
| GET | `/v1/evolution/progress` | 获取进化进度 |
| GET | `/v1/evolution/gaps` | 获取盲点列表 |
| GET | `/v1/evolution/learnings` | 获取学习记录 |

### 4.6 用户隔离机制

所有 API 均基于 JWT Token 进行用户隔离：

```python
# 从 Token 中提取用户信息
user = get_current_user()  # FastAPI Depends

# user 包含:
# - user_id: 对话用户标识
# - neuser_id: 多用户管理标识
# - username: 用户名

# 存储查询均添加用户过滤
configs = storage.get_configs_by_user(user_id=user["user_id"])
```

---

## 5. 前端集成

### 5.1 API 封装

```typescript
// 知识库模块
export * from './modules/knowledge'

// 核心类型
interface KnowledgeItem {
  id: string
  content: string
  title: string
  source: 'iflow' | 'local' | 'memory'
  metadata: Record<string, any>
  memory_links: string[]
}

interface RAGContext {
  query: string
  knowledge_items: KnowledgeItem[]
  memory_context: any[]
  combined_context: string
  sources: string[]
  relevance_scores: Record<string, number>
}
```

### 5.2 使用示例

```typescript
import {
  createCollection,
  uploadDocument,
  searchKnowledge,
  ragRetrieve,
  learnFromKnowledge,
} from '@/api/modules/knowledge'

// 创建知识库
const kb = await createCollection('我的知识库', '描述')

// 上传文档
await uploadDocument(kb.id, file, (e) => {
  console.log(`上传进度: ${e.progress}%`)
})

// 语义检索
const results = await searchKnowledge('如何实现 Python 装饰器')

// RAG 增强检索
const context = await ragRetrieve('装饰器是什么', userId)

// 从知识库学习
const record = await learnFromKnowledge('Python 装饰器')
```

---

## 6. 数据库设计

### 6.1 新增表

```sql
-- 知识库配置
CREATE TABLE knowledge_sources (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,               -- flow/dashscope/feishu/ima/local
    name TEXT,
    config JSON,                      -- API密钥等配置
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- 知识-记忆关联表
CREATE TABLE memory_knowledge_links (
    memory_id TEXT,
    knowledge_id TEXT,
    link_type TEXT,                   -- derived/from/explains/supports/contradicts
    confidence REAL DEFAULT 1.0,
    bidirectional BOOLEAN DEFAULT true,
    created_at TIMESTAMP,
    PRIMARY KEY (memory_id, knowledge_id)
);

-- 学习记录表
CREATE TABLE learning_records (
    id TEXT PRIMARY KEY,
    topic TEXT,
    source_type TEXT,                -- knowledge_base/reflection/manual
    status TEXT,                     -- pending/learning/completed/failed
    knowledge_items JSON,            -- 关联的知识ID列表
    memory_ids JSON,                 -- 关联的记忆ID列表
    insights JSON,
    result JSON,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- 知识盲点表
CREATE TABLE knowledge_gaps (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 1,      -- 1-4
    status TEXT DEFAULT 'open',      -- open/resolved
    evidence JSON,                    -- 支持证据
    learned_from_kb BOOLEAN DEFAULT false,
    created_at TIMESTAMP,
    resolved_at TIMESTAMP
);
```

---

## 7. 配置管理

### 7.1 知识库配置

```python
# neurova/knowledge/config.py

class KnowledgeBaseConfig(BaseModel):
    """知识库总配置"""

    # 心流知识库配置
    flow_kb: FlowKBConfig = FlowKBConfig(
        api_key=None,
        base_url="https://platform.iflow.cn",
        timeout=30,
        max_retries=3,
        sync_on_import=True,
        sync_on_retrieval=True,
        max_memory_links=10
    )

    # 通用配置
    enable_auto_sync: bool = True
    sync_interval_minutes: int = 60
    max_cache_items: int = 1000
```

### 7.2 环境变量

```bash
# 心流知识库 API Key
IFLOW_API_KEY=your_api_key_here

# 或在 Neurova 配置系统中设置
neurova config set knowledge_base.flow_kb.api_key "your_key"
```

---

## 8. 后续扩展

### 8.1 认知闭环系统

三大系统（记忆 ↔ 知识库 ↔ 成长）可形成独立的认知闭环：

```
┌─────────────────────────────────────────────────────────────┐
│                 认知闭环协调器 (CognitiveLoopCoordinator)    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│    记忆系统 ◄────────────────────────────► 心流知识库        │
│        ▲                                  │                  │
│        │                                  │                  │
│        │    ┌─────────────────────────────┘                  │
│        │    │                                               │
│        │    ▼                                               │
│        └───────────► 成长系统 ◄──────────┘                  │
│                                                              │
│                        三位一体闭环                           │
└─────────────────────────────────────────────────────────────┘
```

**闭环模式**

| 模式 | 触发源 | 行为 |
|------|--------|------|
| `KNOWLEDGE_DRIVEN` | 知识检索/同步 | 知识 → 记忆 → 进化 |
| `PROBLEM_DRIVEN` | 记忆未命中 | 触发检索 → 发现盲点 → 学习 |
| `REFLECTION_DRIVEN` | 反思触发 | 全面分析 → 学习 → 反馈 |
| `FULL_LOOP` | 所有 | 启用全部闭环路径 |

**触发类型**

| 触发 | 来源 | 闭环动作 |
|------|------|----------|
| `knowledge_retrieved` | 知识库 | 同步到记忆，记录进化 |
| `memory_miss` | 记忆 | 触发知识库检索，发现盲点 |
| `gap_discovered` | 进化 | 触发学习，记录反馈 |
| `reflection_triggered` | 外部 | 执行完整反思流程 |

### 8.2 计划接入的知识库

| 知识库 | 优先级 | 备注 |
|--------|--------|------|
| 飞书知识库 | P2 | 等待飞书开放 API |
| 阿里百炼 | P2 | 通义千问 + 向量服务 |
| Ima 知识库 | P3 | 微信生态 |
| 本地文档库 | P1 | PDF/Markdown/Word |

### 8.3 计划功能

1. **知识图谱**：基于实体关系构建知识网络
2. **增量学习**：持续从对话中学习新知识
3. **知识评估**：自动评估知识质量和可信度
4. **多语言支持**：跨语言知识检索和迁移
5. **认知闭环可视化**：用户可观察闭环运行状态

---

## 9. 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2025-05-14 | 1.0.0 | 初始版本，完成心流知识库适配器、记忆同步、进化中枢、RAG 检索 |
