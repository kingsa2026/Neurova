# Supermemory vs Neurova 记忆系统代码级对比分析

> 分析日期：2026-06-07  
> 分析范围：架构设计、核心功能、技术实现、性能特征

---

## 1. 项目概览

| 维度 | Supermemory | Neurova |
|------|-------------|---------|
| **定位** | AI 记忆与上下文 API 服务 | 有温度的 AI Agent 框架 |
| **开源协议** | MIT | 项目内部 |
| **GitHub Stars** | 25.9k | — |
| **核心语言** | TypeScript (64.1%) + Python (6.2%) | Python (100%) |
| **运行时** | Bun + Cloudflare Workers | Python 3.10+ + FastAPI |
| **数据库** | PostgreSQL (Drizzle ORM) | SQLite (threading.RLock) |
| **向量存储** | 云端托管 (未公开) | TF-IDF / FAISS / ChromaDB |
| **部署模式** | SaaS (api.supermemory.ai) | 自托管 (本地/私有云) |
| **基准测试** | LongMemEval #1, LoCoMo #1, ConvoMem #1 | 无公开基准 |

---

## 2. 架构设计对比

### 2.1 Supermemory 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    客户端层 (Client Layer)                    │
├─────────────────┬───────────────┬──────────────┬────────────┤
│   Web App       │  MCP Server   │  Browser Ext │  SDK/Tools │
│   (Next.js)     │  (Workers)    │  (WXT)       │  (TS/Py)   │
└────────┬────────┴───────┬───────┴──────┬───────┴─────┬──────┘
         │                │              │             │
         ▼                ▼              ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│              统一 REST API (api.supermemory.ai)              │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ Memory   │ │ Profile  │ │ Hybrid   │ │ Connectors   │   │
│  │ Engine   │ │ System   │ │ Search   │ │ (GDrive/...) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────┐   │
│  │              记忆图 (Memory Graph)                    │   │
│  │  实体 + 记忆 + 上下文 + 时间戳 + 冲突检测            │   │
│  └──────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL │ 向量DB │ Cloudflare KV │ 对象存储              │
└─────────────────────────────────────────────────────────────┘
```

**设计特点**：
- **SaaS 架构**：所有核心逻辑在云端，客户端轻量化
- **协议适配**：MCP Server 作为协议转换层
- **外部数据集成**：Connectors 支持 Google Drive/Gmail/Notion/GitHub 实时同步
- **多模态处理**：PDF/图片(OCR)/视频(转录)/代码(AST分块)

### 2.2 Neurova 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent 核心 (agent_core.py)                │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────┐  │
│  │ MemCore  │ │ ChatPipeline │ │ ToolExec │ │ Evolution │  │
│  │ 记忆核心 │ │ 6步对话管线  │ │ 工具执行 │ │ 进化系统  │  │
│  └──────────┘ └──────────────┘ └──────────┘ └───────────┘  │
├─────────────────────────────────────────────────────────────┤
│              统一记忆检索引擎 (NeurovaRecallEngine)          │
├─────────────────────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│  │温度通道│ │文本通道│ │分类通道│ │图通道  │ │情感通道│   │
│  │(热优先)│ │(语义)  │ │(类别)  │ │(关系)  │ │(情感)  │   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │
├─────────────────────────────────────────────────────────────┤
│              认知层 (Cognitive Layers)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ 情感上下文层 │ │ 成长层      │ │ 元认知层            │   │
│  │ (17种情感)   │ │ (经验分析)  │ │ (自我反思)          │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  SQLite + 向量索引 + 时序知识图谱 + 肌肉记忆                 │
└─────────────────────────────────────────────────────────────┘
```

**设计特点**：
- **自托管架构**：完整 Agent 运行在本地/私有云
- **认知分层**：5层认知架构 (记忆/情感/知识/成长/元认知)
- **多维检索**：5通道并行召回 + 意图驱动钻取
- **自主进化**：工具遗传编程 + 模式挖掘 + 自然语言工具合成

---

## 3. 记忆系统核心功能对比

### 3.1 记忆结构

| 功能 | Supermemory | Neurova |
|------|-------------|---------|
| **记忆类型** | 事实(Fact) + 对话(Conversation) | 17维分类 (事实/对话/情感/经验/...) |
| **时间感知** | ✅ 自动遗忘过期信息 | ✅ 温度衰减曲线 (0-100°C) |
| **矛盾检测** | ✅ 新旧事实冲突处理 | ✅ 冲突检测器 + 时序知识图谱 |
| **增量更新** | ✅ 动态扩展 | ✅ 温度更新 + 生命周期管理 |
| **记忆分层** | 静态事实 + 动态上下文 | L1肌肉记忆 + L2热缓存 + L3工具记忆 |
| **用户画像** | ✅ profile() API (~50ms) | ✅ 情感分析 + 人格模板 |

### 3.2 检索机制

| 功能 | Supermemory | Neurova |
|------|-------------|---------|
| **检索模式** | 混合搜索 (RAG + Memory) | 5通道并行召回 + 意图钻取 |
| **语义搜索** | ✅ 向量相似度 | ✅ TF-IDF / FAISS / ChromaDB |
| **温度检索** | ❌ | ✅ 热记忆优先浮现 |
| **情感检索** | ❌ | ✅ 情感相似度匹配 |
| **图谱检索** | ✅ Memory Graph | ✅ 时序知识图谱 (9种关系) |
| **意图理解** | ❌ | ✅ 5种钻取意图 (探索/深化/连接/对比/验证) |
| **检索准确率** | 95% Recall@15 (LongMemEval) | 未公开基准 |

### 3.3 记忆安全

| 功能 | Supermemory | Neurova |
|------|-------------|---------|
| **敏感信息检测** | 未公开 | ✅ 8种内置模式 (手机/身份证/邮箱/...) |
| **加密存储** | 未公开 | ✅ Fernet 对称加密 + 回退加密器 |
| **匿名化** | 未公开 | ✅ 自动匿名化导出 |
| **被遗忘权** | 未公开 | ✅ GDPR 合规删除 |
| **访问审计** | 未公开 | ✅ 完整审计日志 |
| **数据隔离** | containerTag 标签 | agent_id + user_id 隔离 |

---

## 4. 技术实现对比

### 4.1 代码规模

| 模块 | Supermemory | Neurova |
|------|-------------|---------|
| **总代码量** | ~50k 行 (TS) | ~80k 行 (Python) |
| **记忆核心** | 未公开 (云端) | ~3,500 行 |
| **检索引擎** | 未公开 (云端) | ~1,200 行 (NeurovaRecallEngine) |
| **时序图谱** | 未公开 (云端) | ~800 行 (TemporalKnowledgeGraph) |
| **安全模块** | 未公开 (云端) | ~500 行 (MemorySecurity) |
| **测试覆盖** | 未公开 | 364 测试文件 |

### 4.2 核心算法

#### Supermemory 核心算法

```
1. 记忆提取 (Memory Extraction)
   输入: 对话文本
   处理: LLM 提取事实 → 去重/冲突检测 → 时间标注
   输出: 结构化事实 (subject-predicate-object)

2. SMFS 文件系统抽象
   概念: 将记忆抽象为文件系统
   结构: /users/{id}/memories/ → 文件 = 记忆
   优势: 令牌使用减少 3x (Claude)

3. 混合检索 (Hybrid Search)
   流程: 并行 RAG 检索 + Memory 检索 → 融合排序
   结果: 通用知识 + 个人上下文
```

#### Neurova 核心算法

```
1. 温度衰减曲线 (Temperature Decay)
   公式: T(t) = T₀ × e^(-λt) × (1 + log₂(n+1))
   参数: T₀=初始温度, λ=衰减率, n=回忆次数
   效果: 热记忆优先，冷记忆自然遗忘

2. 5通道并行召回 (Multi-Channel Recall)
   通道: 温度 + 文本 + 分类 + 图谱 + 情感
   权重: 动态计算，根据查询意图调整
   融合: 多信号加权排序

3. 意图驱动钻取 (Intent-Driven Drill)
   意图: 探索/深化/连接/对比/验证
   路径: 从种子记忆沿关系路径定向深入
   优势: 可解释、有方向的记忆探索

4. Hebb 学习 (Hebbian Learning)
   公式: Δw = η × activation_i × activation_j
   应用: 经验模式固化，工具使用学习
   成本: 比 LLM 调用低 97%
```

### 4.3 数据模型

#### Supermemory 数据模型

```typescript
// 记忆 (Memory)
interface Memory {
  id: string;
  content: string;          // 记忆内容
  containerTag: string;     // 作用域标签 (user/project)
  createdAt: Date;
  updatedAt: Date;
  metadata: Record<string, any>;
}

// 用户画像 (Profile)
interface Profile {
  static: Fact[];           // 静态事实 (长期偏好)
  dynamic: Context[];       // 动态上下文 (近期活动)
}

// 事实 (Fact)
interface Fact {
  subject: string;
  predicate: string;
  object: string;
  confidence: number;
  validFrom: Date;
  validUntil?: Date;
}
```

#### Neurova 数据模型

```python
# 记忆 (Memory)
@dataclass
class Memory:
    id: str
    content: str
    category: MemoryCategory    # 17维分类
    memory_type: MemoryType     # episodic/semantic/procedural
    temperature: float          # 0-100°C
    lifecycle_stage: LifecycleStage
    emotion: EmotionType        # 17种情感
    agent_id: str
    user_id: str
    created_at: datetime
    accessed_at: datetime
    access_count: int
    importance: float
    
# 时序事实 (TemporalFact)
@dataclass
class TemporalFact:
    id: str
    subject: str
    predicate: str
    object: str
    relation_type: RelationType  # 9种关系
    confidence: float
    status: FactStatus           # active/expired/conflicted/superseded
    valid_from: datetime
    valid_until: Optional[datetime]
    source_memory_id: str
```

---

## 5. 集成方式对比

### 5.1 Supermemory 集成

```typescript
// TypeScript SDK
import Supermemory from 'supermemory';

const client = new Supermemory({ apiKey: 'xxx' });

// 存储记忆
await client.add({
  content: '用户喜欢 TypeScript',
  containerTag: 'user_123'
});

// 获取用户画像
const profile = await client.profile({ containerTag: 'user_123' });

// 混合搜索
const results = await client.search({
  query: '编程偏好',
  containerTag: 'user_123'
});
```

```python
# Python SDK
from supermemory import Supermemory

client = Supermemory(api_key="xxx")

# 存储记忆
client.add(content="用户喜欢 Python", container_tag="user_123")

# 获取画像
profile = client.profile(container_tag="user_123")

# 搜索
results = client.search(query="编程偏好", container_tag="user_123")
```

### 5.2 Neurova 集成

```python
# 直接使用 Agent
from neurova.agent_core import Agent

agent = Agent(agent_id="my_agent", user_id="user_123")

# 对话 (自动记忆存取)
response = await agent.chat("我喜欢用 Python 写代码")

# 手动记忆操作
from neurova.cognitive_layers.memory_layer.manager import MemoryManager

manager = MemoryManager(agent_id="my_agent", user_id="user_123")

# 保存记忆
memory = manager.remember(
    content="用户喜欢 Python",
    category="preference",
    importance=0.8
)

# 检索记忆
results = manager.recall(
    query="编程偏好",
    top_k=5
)

# 情感检索
emotional_memories = manager.get_memories_by_emotion(
    emotion="happy",
    limit=10
)
```

---

## 6. 优劣势分析

### 6.1 Supermemory 优势

| 优势 | 说明 |
|------|------|
| **开箱即用** | SaaS 服务，无需部署，5 分钟集成 |
| **基准领先** | LongMemEval/LoCoMo/ConvoMem 三项第一 |
| **外部集成** | Connectors 支持 Google/GitHub/Notion 等 |
| **多模态** | PDF/图片/视频/代码自动处理 |
| **低延迟** | profile() ~50ms，云端优化 |
| **MCP 支持** | 一键集成 Claude/Cursor/VS Code |
| **SMFS 创新** | 记忆文件系统化，令牌减少 3x |

### 6.2 Supermemory 劣势

| 劣势 | 说明 |
|------|------|
| **数据主权** | 数据存储在云端，无法自控 |
| **隐私风险** | 敏感数据需上传至第三方 |
| **定制限制** | 无法深度定制记忆逻辑 |
| **成本** | SaaS 订阅费用，大规模使用成本高 |
| **离线不可用** | 依赖网络连接 |
| **Agent 集成** | 仅提供记忆层，无完整 Agent 框架 |

### 6.3 Neurova 优势

| 优势 | 说明 |
|------|------|
| **完全自托管** | 数据完全在本地，隐私可控 |
| **完整 Agent** | 不仅是记忆层，是完整 Agent 框架 |
| **认知分层** | 5层认知架构，模拟人类认知 |
| **温度衰减** | 独创温度曲线，模拟人类遗忘 |
| **多维检索** | 5通道并行 + 意图钻取 |
| **情感记忆** | 17种情感分类，情感驱动检索 |
| **安全合规** | 敏感检测/加密/匿名化/被遗忘权 |
| **自主进化** | 工具遗传编程 + 模式挖掘 |
| **多通道** | 10+ 平台接入 (微信/飞书/钉钉/...) |

### 6.4 Neurova 劣势

| 劣势 | 说明 |
|------|------|
| **部署复杂** | 需要自行部署和维护 |
| **无基准** | 未在公开基准测试中验证 |
| **性能未知** | 未公开延迟/吞吐量数据 |
| **生态较小** | 社区和第三方集成较少 |
| **文档不足** | 相比 Supermemory 文档较少 |
| **TypeScript 缺失** | 无 JS/TS SDK，前端集成需额外开发 |

---

## 7. 设计理念对比

### 7.1 Supermemory 设计理念

```
核心理念: Memory ≠ RAG
├── RAG: 无状态文档检索 (通用知识)
├── Memory: 有状态事实追踪 (个人上下文)
└── 混合: 一次查询同时获取两者

设计原则:
1. API-First: 一切通过 REST API
2. 轻量客户端: 客户端只做 UI
3. 云端智能: 核心逻辑在云端
4. 开发者友好: 简洁 SDK，5分钟集成
```

### 7.2 Neurova 设计理念

```
核心理念: 有温度的智能体
├── 温度: 记忆有热度，热的自然浮现
├── 情感: 记忆有情感，情感驱动检索
├── 成长: Agent 能自主学习和进化
└── 人格: 每个 Agent 有独特人格

设计原则:
1. 深度模块: 小接口，深实现
2. 认知分层: 模拟人类认知架构
3. 本地优先: 数据完全本地化
4. 自主演化: 工具/技能/模式自主进化
```

---

## 8. 适用场景对比

### 8.1 Supermemory 最佳场景

| 场景 | 原因 |
|------|------|
| **SaaS 应用** | 快速集成，无需运维 |
| **个人 AI 助手** | 浏览器插件 + MCP 一键使用 |
| **多平台记忆同步** | Connectors 支持多数据源 |
| **快速原型** | 5 分钟集成，快速验证 |
| **团队协作** | containerTag 支持多用户隔离 |
| **RAG 增强** | 混合搜索提升检索质量 |

### 8.2 Neurova 最佳场景

| 场景 | 原因 |
|------|------|
| **私有化部署** | 数据完全本地，隐私合规 |
| **企业 Agent** | 完整 Agent 框架，可深度定制 |
| **多平台接入** | 10+ 平台原生支持 |
| **情感交互** | 情感分析 + 情感记忆检索 |
| **自主学习** | 进化系统 + 模式挖掘 |
| **安全敏感** | 敏感检测 + 加密 + 审计 |
| **长期运行** | 温度衰减 + 睡眠整理 + 遗忘曲线 |

---

## 9. 互操作性建议

### 9.1 能否结合使用？

**理论上可以，但需要适配层：**

```
方案 A: Supermemory 作为 Neurova 的外部记忆源
┌──────────────┐     适配器     ┌──────────────────┐
│   Neurova    │ ◄───────────► │   Supermemory    │
│  (本地Agent) │               │  (云端记忆)      │
└──────────────┘               └──────────────────┘
- Neurova 处理 Agent 逻辑
- Supermemory 处理跨平台记忆同步
- 通过 SDK 适配器桥接

方案 B: Neurova 记忆系统替代 Supermemory
┌──────────────────────────────────────┐
│           Neurova 记忆系统            │
│  (本地部署，完整功能)                │
│  + 新增 REST API 暴露                │
│  + 新增 containerTag 概念            │
└──────────────────────────────────────┘
- 完全自主可控
- 需要开发 API 层
```

### 9.2 从 Supermemory 学习的改进点

| 改进方向 | Supermemory 做法 | Neurova 可借鉴 |
|----------|------------------|----------------|
| **基准测试** | LongMemEval/LoCoMo/ConvoMem | 建立标准化评测框架 |
| **SDK 设计** | 简洁 TS/Python SDK | 提供多语言 SDK |
| **MCP 集成** | 一键安装 MCP Server | 支持 MCP 协议 |
| **外部连接器** | Google/GitHub/Notion | 实现数据源适配器 |
| **文档质量** | 详细的集成指南 | 完善开发者文档 |
| **SMFS 抽象** | 记忆文件系统化 | 考虑文件系统接口 |

### 9.3 从 Neurova 学习的改进点

| 改进方向 | Neurova 做法 | Supermemory 可借鉴 |
|----------|--------------|---------------------|
| **温度衰减** | 热度曲线模拟遗忘 | 添加时间衰减机制 |
| **情感记忆** | 17种情感分类 | 情感驱动检索 |
| **安全合规** | 敏感检测/加密/审计 | 增强数据安全 |
| **认知分层** | 5层认知架构 | 更丰富的认知模型 |
| **自主进化** | 工具遗传编程 | 学习型记忆系统 |
| **多通道接入** | 10+ 平台支持 | 更多客户端适配 |

---

## 10. 总结

### 10.1 核心差异

| 维度 | Supermemory | Neurova |
|------|-------------|---------|
| **本质** | 记忆 API 服务 | 完整 Agent 框架 |
| **架构** | SaaS 云端 | 自托管本地 |
| **优势** | 开箱即用、基准领先 | 隐私可控、功能完整 |
| **劣势** | 数据外流、定制受限 | 部署复杂、生态较小 |
| **创新** | SMFS 文件系统抽象 | 温度衰减 + 情感记忆 |

### 10.2 选择建议

| 需求 | 推荐 |
|------|------|
| **快速集成 AI 记忆** | Supermemory |
| **私有化 Agent 部署** | Neurova |
| **跨平台记忆同步** | Supermemory |
| **多平台接入 Agent** | Neurova |
| **数据安全合规** | Neurova |
| **情感交互 Agent** | Neurova |
| **自主学习进化** | Neurova |
| **SaaS 应用增强** | Supermemory |

### 10.3 未来趋势

1. **融合趋势**: 记忆层与 Agent 框架的边界将逐渐模糊
2. **标准化**: MCP 协议可能成为 AI 记忆集成的标准
3. **本地化**: 隐私法规推动本地化记忆方案
4. **多模态**: 图片/视频/代码的记忆处理将成为标配
5. **自主进化**: 记忆系统将具备自我优化能力

---

## 附录 A: 代码片段对比

### A.1 记忆存储

**Supermemory:**
```typescript
await client.add({
  content: '用户喜欢 Python',
  containerTag: 'user_123',
  metadata: { source: 'chat' }
});
```

**Neurova:**
```python
memory = manager.remember(
    content="用户喜欢 Python",
    category=MemoryCategory.PREFERENCE,
    importance=0.8,
    emotion=EmotionType.POSITIVE
)
```

### A.2 记忆检索

**Supermemory:**
```typescript
const results = await client.search({
  query: '编程偏好',
  containerTag: 'user_123',
  limit: 5
});
```

**Neurova:**
```python
results = manager.recall(
    query="编程偏好",
    top_k=5,
    channels=[RecallChannel.TEMPERATURE, RecallChannel.TEXT]
)
```

### A.3 用户画像

**Supermemory:**
```typescript
const profile = await client.profile({ 
  containerTag: 'user_123' 
});
// profile.static: ['喜欢 TypeScript', '住在北京']
// profile.dynamic: ['正在处理 API 集成']
```

**Neurova:**
```python
# 通过情感分析获取用户状态
emotion = emotion_analyzer.analyze("我今天很开心")
# emotion: EmotionState(joy=0.9, excitement=0.7)

# 通过记忆获取用户偏好
preferences = manager.get_memories_by_category(
    category=MemoryCategory.PREFERENCE,
    limit=10
)
```

---

## 附录 B: 性能对比 (推测)

| 指标 | Supermemory | Neurova |
|------|-------------|---------|
| **首次响应** | ~50ms (云端) | ~100-500ms (本地) |
| **检索延迟** | ~100ms | ~50-200ms (本地向量) |
| **存储延迟** | ~50ms | ~10-50ms (SQLite) |
| **并发能力** | 高 (云端弹性) | 中 (单机限制) |
| **离线能力** | ❌ | ✅ |
| **数据量** | 理论无限 | 受限于本地存储 |

---

*本文档基于公开信息和代码分析生成，性能数据为推测值，实际表现可能因部署环境和配置而异。*
