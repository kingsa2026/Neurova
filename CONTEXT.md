# Neurova — 项目上下文

> "有温度的智能体" — 每一个 Agent 都是一颗善良的星星，而你就是守星人

## 项目概览

Neurova 是一个功能完整的 AI Agent 框架，核心特点是为每个 Agent 提供独特人格、持续记忆和自主成长能力。

| 维度 | 值 |
|------|-----|
| 后端语言 | Python 3.10+ |
| 前端框架 | Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue |
| Python 文件数 | 550+ |
| 测试文件数 | 532 |
| 前端页面组件 | 82 |
| API 端点 | 77+ |
| 通信渠道 | 14 种 |
| 版本 | Agent v4.0 (CogArch 2.0) |

## 核心架构

### Agent 核心 (`neurova/agent_core.py`)

Agent 类是系统的心脏，通过深度模块化模式逐步拆分：

```
Agent (1621 行, 37 方法)
├── MemCore (mem_core.py)              — 记忆检索/保存/温度管理
├── ContextOrchestrator                — 上下文构建/系统提示/工具描述
├── ToolExecutor (tool_executor.py)    — 工具调用解析/执行/后处理钩子
├── ChatPipeline (chat_pipeline.py)    — 对话流程管线 (6步)
├── PostChatPipeline                   — 后处理管线 (10+ 步骤)
├── MemoryAgent (memory_agent.py)      — 记忆管理深度模块
└── LLMRouter (llm/llm_router.py)     — 多模态自适应路由
```

**设计模式**: 所有深度模块通过 `agent_ref` 访问 Agent 属性，不反向导入 Agent，无循环依赖。

### ChatPipeline 对话管线 (`neurova/agent/chat_pipeline.py`, 706行)

从 `Agent.chat()` 提取的 6 步管线：

1. `_step_activity_tracking` — 空闲追踪 + 会话恢复
2. `_step_pre_llm_checks` — 工具记忆检查 + 技能获取
3. `_step_retrieve_and_build_context` — 记忆检索 + 上下文构建
4. `_step_evocate_injection` — Evocate 结构化推理注入
5. `_step_llm_call` — LLM 调用 + 自动续写
6. `_step_post_processing` — 后处理管线

### 记忆系统

17 维记忆分类体系，核心组件：

| 层级 | 组件 | 职责 |
|------|------|------|
| L1 | 肌肉记忆 | 工具使用模式自动执行 |
| L2 | 热缓存 | 高频访问记忆快速检索 |
| L3 | 工具记忆 | 工具使用经验闭环学习 |
| 向量 | UnifiedRetriever | 多通道语义检索 |
| 结晶 | PatternCrystallizer | 经验模式固化 |
| 时序 | TemporalKnowledgeGraph | 时序事实管理 |
| Hebb | NeuHebbManager | 结构化推理记忆 |

### LLM 路由 (`neurova/llm/`)

- **MultiModelLLMClient** — 多模型统一客户端
- **LLMRouter** — 多模态自适应路由器 (10种请求类型)
- **ProviderManager** — 服务商管理器 (OpenAI/Anthropic/Gemini/Ollama/OpenRouter)
- **Agent Loop 系统** — 抽象 LLM 调用接口，支持热切换

### 认知层 (`neurova/cognitive_layers/`)

- `emotion_context_layer/` — 情感上下文注入 (17种情感分类)
- `growth_layer/` — 成长分析
- `memory_layer/` — 记忆层核心 (安全/向量/冲突/缓存/工作记忆)
- `meta_cognition_layer/` — 元认知
- `model_adapter/` — 模型适配器

### 进化系统 (`neurova/evolution/`)

- PatternMiner — 序列模式挖掘
- ToolGeneticEngine — 工具遗传编程
- ToolLifecycleManager — 工具生命周期管理
- NLToolSynthesizer — 自然语言工具合成
- EvolutionOrchestrator — 统一进化引擎

### 多通道通信 (`neurova/channels/`)

支持 14 种平台接入：飞书、钉钉、企业微信、微信、Telegram、Discord、QQ、MQTT、WebSocket、SIP、Webhook、移动设备（QR码配对）

### 前端 (`neuUI/`)

Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue，82 个页面组件：

- **核心**: ChatPage (47KB), DashboardPage, SettingPage, WorkflowPage (50KB)
- **Agent 管理**: 15 个页面 (Form/List/Skill/Sleep/Channel/...)
- **运维**: Monitor, Health, Audit, Security, Firewall
- **知识**: Knowledge, KnowledgeGraph, ExperienceKnowledge
- **协作**: Collaboration, CollaborationInitiate, CollaborationTemplate
- **LLM 管理**: ModelPage, ProviderPage, ModelAdapterPage
- **Computer Use**: ComputerUsePage, BrowserManagerPage
- **移动设备**: MobilePairingPage, MobileDevicePage
- **分析**: AnalyticsPage, StatisticsPage, BenchmarkPage

## 依赖关系图

```
                    ┌──────────────┐
                    │  Agent Class │
                    │  (1520 LOC)  │
                    └──────┬───────┘
                           │ delegates
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ MemCore │      │ Context   │     │ ToolExecutor│
   └────┬────┘      │Orchestratr│     └──────┬──────┘
        │           └─────┬─────┘            │
        │                 │                  │
   ┌────▼────┐      ┌─────▼─────┐     ┌──────▼──────┐
   │ memory  │      │ChatPipeline│    │ PostChat   │
   │ manager │      │ (6 steps) │     │ Pipeline   │
   └─────────┘      └───────────┘     └─────────────┘
```

## 技术栈

### 后端
- **Web 框架**: FastAPI
- **数据库**: SQLite (threading.RLock 保护)
- **LLM**: 多服务商支持 (OpenAI/Anthropic/Gemini/Ollama/OpenRouter)
- **向量搜索**: TF-IDF / FAISS / ChromaDB
- **TTS**: Edge TTS / MOSS Nano / Mock

### 前端
- **框架**: Vue 3 + Composition API
- **状态管理**: Pinia
- **构建**: Vite
- **样式**: CSS + Liquid Glass UI

## 开发规范

- **深度模块模式**: 小接口，深实现，通过 `agent_ref` 依赖注入
- **线程安全**: 使用 `threading.RLock` 保护共享状态
- **异步**: 使用 `async/await` 进行异步操作
- **依赖检查**: 使用 `try/except` 处理可选依赖
- **单例管理**: 使用 `get_*()` / `reset_*()` 工厂函数
- **延迟导入**: `__getattr__` 避免循环依赖

## 当前重构状态

### 已完成
- [x] MemCore 提取 (记忆核心)
- [x] ContextOrchestrator 提取 (上下文构建)
- [x] ToolExecutor 提取 (工具执行)
- [x] PostChatPipeline 提取 (后处理管线)
- [x] ChatPipeline 提取 (对话管线, 6步)
- [x] 循环导入修复 (延迟导入)
- [x] debug_log 清理
- [x] Agent 类深度模块化重构 (2180→1621 行)
- [x] 浏览器自动化集成 (browser-skill)
- [x] 文档对齐 (README.md 更新)
- [x] 安全增强 (P2 安全问题修复)
- [x] 三层隔离机制统一 (IsolationContext)
- [x] 经验闭环修复 (结晶经验注入)
- [x] 情感闭环修复 (SQLite 持久化)
- [x] 睡眠闭环修复 (MemoryRecord 转换)
- [x] 工具记忆闭环修复 (match_by_query 接口)
- [x] 骨架文件实现 (140+ 文件)
- [x] 记忆检索通道插件化 (BaseChannel + Registry + 6内置通道 + MoE路由 + 结果处理)
- [x] Agent.__init__ 分解为 SubSystemContainer (427行→14行)

### 待办
- [x] Agent.__init__ 分解为 SubSystemContainer (P0) — 427行→14行，14个分组方法
- [x] 合并重复的 ContextOrchestrator (P2) — 删除2个死代码文件(744行)，保留 neurova/context/orchestrator.py
- [x] 合并重复的 AgentConfig (P3) — 删除死代码 agent/config.py（156行）
- [x] 移除过渡性委托方法 (P4) — 删除15个死代码方法(~200行)，内联1个调用
- [x] 清理进化模块空文件 (P5) — 验证全部19个文件均有实质实现，无需清理
