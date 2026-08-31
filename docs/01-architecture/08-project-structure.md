# Neurova 项目结构

## 项目概览

Neurova 是一个功能完整的 AI Agent 框架，版本 v1.0.0-beta1 (CogArch 2.0)。

| 维度 | 值 |
|------|-----|
| 后端语言 | Python 3.10+ |
| 前端框架 | Vue 3 + TypeScript + Vite + Pinia + Ant Design Vue |
| Python 文件数 | ~700 |
| 测试文件数 | 846 |
| 前端页面组件 | 60 |
| API 端点 | 82 |
| 通信渠道 | 14 种 |

## 当前项目结构

```
Neurova/
├── neurova/                          # 后端核心代码
│   ├── agent_core.py                 # Agent 核心类 (1621 行, 37 方法)
│   ├── mem_core.py                   # 记忆检索/保存/温度管理
│   ├── context_orchestrator.py       # 上下文构建/系统提示/工具描述
│   ├── tool_executor.py              # 工具调用解析/执行/后处理钩子
│   ├── post_chat_pipeline.py         # 后处理管线 (10+ 步骤)
│   ├── router.py                     # 消息路由器
│   ├── llm_client.py                 # LLM 客户端
│   ├── builtin_tools.py              # 内置工具注册器
│   ├── skill_system.py               # 技能系统
│   └── ... (更多核心模块)
│
├── neurova/agent/                    # Agent 深度模块
│   ├── __init__.py                   # 统一导出入口
│   ├── config.py                     # AgentConfig, AgentLLMClient
│   ├── memory_agent.py               # MemoryAgent (563行, 30个方法)
│   ├── context_orchestrator.py       # ContextOrchestrator (337行, 14个方法)
│   ├── tool_executor.py              # ToolExecutor (485行, 12个方法)
│   ├── chat_pipeline.py              # ChatPipeline (706行, 6步)
│   ├── loops/                        # Agent Loop 系统
│   ├── builder.py                    # Agent 构建器
│   └── scheduler.py                  # Agent 调度器
│
├── neurova/cognitive_layers/         # 认知层
│   ├── emotion_context_layer/        # 情感上下文注入 (17种情感分类)
│   ├── growth_layer/                 # 成长分析
│   ├── memory_layer/                 # 记忆层核心 (安全/向量/冲突/缓存/工作记忆)
│   ├── meta_cognition_layer/         # 元认知
│   └── model_adapter/                # 模型适配器
│
├── neurova/evolution/                # 进化系统
│   ├── pattern_miner.py              # 序列模式挖掘
│   ├── tool_genetic_engine.py        # 工具遗传编程
│   ├── tool_lifecycle_manager.py     # 工具生命周期管理
│   ├── nl_tool_synthesizer.py        # 自然语言工具合成
│   └── closed_loop.py                # 统一进化引擎
│
├── neurova/channels/                 # 多通道通信 (14种渠道)
│   ├── feishu.py                     # 飞书适配器
│   ├── dingtalk.py                   # 钉钉适配器
│   ├── wecom.py                      # 企业微信适配器
│   ├── wechat.py                     # 微信适配器
│   ├── telegram.py                   # Telegram 适配器
│   ├── discord.py                    # Discord 适配器
│   ├── qq.py                         # QQ 适配器
│   ├── mqtt.py                       # MQTT 适配器
│   ├── websocket.py                  # WebSocket 适配器
│   ├── sip.py                        # SIP 适配器
│   ├── webhook.py                    # Webhook 适配器
│   └── mobile_pairing.py            # 移动设备配对 (QR码)
│
├── neurova/llm/                      # LLM 路由系统
│   ├── llm_router.py                 # 多模态自适应路由器 (10种请求类型)
│   ├── multi_model_client.py         # 多模型统一客户端
│   ├── provider_manager.py           # 服务商管理器 (6+提供商)
│   └── providers/                    # LLM 提供商实现
│       ├── openai_provider.py        # OpenAI 提供商
│       ├── anthropic_provider.py     # Anthropic 提供商
│       ├── gemini_provider.py        # Gemini 提供商
│       ├── ollama_provider.py        # Ollama 提供商
│       ├── openrouter_provider.py    # OpenRouter 提供商
│       └── ... (更多提供商)
│
├── neurova/plugins/                  # 插件系统
├── neurova/skill_system/             # 技能系统
├── neurova/skills/                   # 技能实现
├── neurova/tts/                      # 语音合成 (Edge TTS / MOSS Nano / Mock)
├── neurova/asr/                      # 语音识别
├── neurova/computer_use/             # 计算机视觉/浏览器自动化
├── neurova/benchmark/                # 基准测试框架
├── neurova/execution_layers/         # 执行运行时和传输层
├── neurova/image_pipeline/           # 镜像管道管理器
├── neurova/tool_layers/              # 工具层模块
├── neurova/collaborate/              # 协作模块
├── neurova/knowledge/                # 知识管理
├── neurova/analytics/                # 分析模块
├── neurova/security/                 # 安全模块
├── neurova/admin/                    # 管理模块
├── neurova/auth/                     # 认证授权
├── neurova/api/                      # RESTful API (82 端点模块)
│   ├── app.py                        # FastAPI 应用
│   └── endpoints/                    # API 端点实现
│       ├── agent.py                  # Agent 管理
│       ├── memory.py                 # 记忆管理
│       ├── model.py                  # 模型管理
│       ├── provider.py               # 提供商管理
│       ├── channel.py                # 渠道管理
│       ├── skill.py                  # 技能管理
│       ├── plugin.py                 # 插件管理
│       ├── collaboration.py          # 协作管理
│       ├── security.py               # 安全管理
│       └── ... (更多端点)
│
├── neuUI/                            # 前端 (Vue 3 + TypeScript)
│   ├── src/
│   │   ├── pages/                    # 82 个页面组件
│   │   │   ├── ChatPage.vue          # 聊天页面 (47KB)
│   │   │   ├── DashboardPage.vue     # 仪表盘
│   │   │   ├── SettingPage.vue       # 设置页面
│   │   │   ├── WorkflowPage.vue      # 工作流页面 (50KB)
│   │   │   ├── ModelPage.vue         # 模型管理
│   │   │   ├── ProviderPage.vue      # 提供商管理
│   │   │   ├── AgentFormPage.vue     # Agent 表单
│   │   │   ├── AgentListPage.vue     # Agent 列表
│   │   │   ├── AgentSkillPage.vue    # Agent 技能
│   │   │   ├── AgentSleepPage.vue    # Agent 睡眠
│   │   │   ├── AgentChannelPage.vue  # Agent 渠道
│   │   │   ├── MonitorPage.vue       # 监控页面
│   │   │   ├── HealthPage.vue        # 健康检查
│   │   │   ├── AuditPage.vue         # 审计日志
│   │   │   ├── SecurityPage.vue      # 安全设置
│   │   │   ├── FirewallPage.vue      # 防火墙
│   │   │   ├── KnowledgePage.vue     # 知识管理
│   │   │   ├── KnowledgeGraphPage.vue # 知识图谱
│   │   │   ├── ExperienceKnowledgePage.vue # 经验知识
│   │   │   ├── CollaborationPage.vue # 协作管理
│   │   │   ├── CollaborationInitiatePage.vue # 发起协作
│   │   │   ├── CollaborationTemplatePage.vue # 协作模板
│   │   │   ├── ModelAdapterPage.vue  # 模型适配器
│   │   │   ├── ComputerUsePage.vue   # 计算机使用
│   │   │   ├── BrowserManagerPage.vue # 浏览器管理
│   │   │   ├── MobilePairingPage.vue # 移动设备配对
│   │   │   ├── MobileDevicePage.vue  # 移动设备管理
│   │   │   ├── AnalyticsPage.vue     # 分析页面
│   │   │   ├── StatisticsPage.vue    # 统计页面
│   │   │   └── BenchmarkPage.vue     # 基准测试
│   │   ├── components/               # 通用组件
│   │   ├── api/                      # API 模块
│   │   ├── stores/                   # Pinia 状态管理
│   │   ├── router/                   # Vue Router
│   │   └── utils/                    # 工具函数
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── tests/                            # 测试文件 (846 个)
│   ├── unit/                         # 单元测试
│   ├── integration/                  # 集成测试
│   └── fixtures/                     # 测试数据
│
├── docs/                             # 文档
│   ├── architecture/                 # 架构设计文档 (33 个)
│   ├── api/                          # API 文档
│   ├── dev_progress/                 # 开发进度
│   ├── guides/                       # 用户指南
│   └── ... (其他文档)
│
├── config/                           # 配置文件
├── scripts/                          # 脚本工具
├── deploy/                           # 部署配置
├── start.py                          # 启动脚本
├── requirements.txt                  # Python 依赖
├── CONTEXT.md                        # 项目上下文文档
└── README.md                         # 项目说明文档
```

## 核心模块说明

### Agent 核心 (`neurova/agent_core.py`)
Agent 类是系统的心脏，通过深度模块化模式逐步拆分：
- **MemCore** — 记忆检索/保存/温度管理
- **ContextOrchestrator** — 上下文构建/系统提示/工具描述
- **ToolExecutor** — 工具调用解析/执行/后处理钩子
- **ChatPipeline** — 对话流程管线 (6步)
- **PostChatPipeline** — 后处理管线 (10+ 步骤)
- **MemoryAgent** — 记忆管理深度模块
- **LLMRouter** — 多模态自适应路由

### 记忆系统
17 维记忆分类体系，核心组件：
- **L1 肌肉记忆** — 工具使用模式自动执行
- **L2 热缓存** — 高频访问记忆快速检索
- **L3 工具记忆** — 工具使用经验闭环学习
- **向量 UnifiedRetriever** — 多通道语义检索
- **结晶 PatternCrystallizer** — 经验模式固化
- **时序 TemporalKnowledgeGraph** — 时序事实管理
- **Hebb NeuHebbManager** — 结构化推理记忆

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
- **PatternMiner** — 序列模式挖掘
- **ToolGeneticEngine** — 工具遗传编程
- **ToolLifecycleManager** — 工具生命周期管理
- **NLToolSynthesizer** — 自然语言工具合成
- **EvolutionOrchestrator** — 统一进化引擎

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

### 待办
- [ ] Agent.__init__ 分解为 SubSystemContainer (P0)
- [ ] 合并重复的 ContextOrchestrator (P2)
- [ ] 合并重复的 AgentConfig (P3)
- [ ] 移除过渡性委托方法 (P4)
- [ ] 清理进化模块空文件 (P5)

---

**最后更新**: 2026-06-07
**版本**: v1.0.0-beta1 (CogArch 2.0)
**维护者**: Neurova Team