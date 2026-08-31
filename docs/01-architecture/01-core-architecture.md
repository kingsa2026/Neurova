# 智能体代理框架 - 核心架构设计

> **版本**: v1.0.0-beta1 (CogArch 2.0)  
> **最后更新**: 2026-06-07  
> **状态**: 生产就绪

## 1. 概述

### 1.1 项目名称
**Neurova** - 基于 Python 的智能体代理框架

### 1.2 设计目标
- **深度模块化**: 小接口，深实现，通过 `agent_ref` 依赖注入
- **多模态支持**: 文本、图像、音频、视频全面处理
- **多模型路由**: 自动选择最佳 LLM 提供商和模型
- **持续记忆**: 17 维记忆分类体系，支持长期记忆和经验学习
- **情感架构**: 四层 17 种情感分类，情感驱动的记忆检索
- **自主进化**: 模式挖掘、工具遗传编程、经验结晶

### 1.3 核心特性
1. **多 Agent 协作系统** - 矩阵式 Agent 协作，支持复杂任务分解
2. **17 维记忆系统** - 短期/长期/情感/工具/经验/反思等多维度记忆
3. **多模态 LLM 路由** - 6+ 提供商，10 种请求类型自动路由
4. **14 种通信渠道** - 飞书/钉钉/企业微信/Telegram/Discord 等
5. **情感架构** - 情感分析、情感记忆、情感驱动决策
6. **进化系统** - 模式挖掘、经验结晶、工具遗传编程
7. **深度模块化** - Agent 类从 2180 行重构为 1621 行 + 5 个深度模块
8. **生产级安全** - 三层隔离、加密存储、审计日志

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  (CLI, REST API, WebSocket, 14种通信渠道, 外部集成)         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Agent Layer                             │
│  (Agent Core, ChatPipeline, PostChatPipeline, 深度模块)     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                  Communication Layer                         │
│    (Message Router, Event Bus, 14种渠道适配器)               │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
│  (Memory System, Emotion Engine, LLM Router, 进化系统)      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                  Infrastructure Layer                        │
│    (SQLite, 向量存储, 文件系统, 安全, 监控)                 │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 分层职责

#### Core Layer (核心层)
- **Memory System**: 17 维记忆分类，温度管理，生命周期管理
- **Emotion Engine**: 四层 17 种情感分类，情感记忆检索
- **LLM Router**: 多模态自适应路由，6+ 提供商支持
- **Evolution System**: 模式挖掘，经验结晶，工具遗传编程

#### Communication Layer (通信层)
- **Message Router**: 智能消息路由，支持规则/内容路由
- **Event Bus**: 异步事件总线，支持优先级和过滤
- **Channels**: 14 种平台适配器，统一消息格式

#### Agent Layer (Agent 层)
- **Agent Core**: 主控 Agent，1621 行，37 个方法
- **ChatPipeline**: 6 步对话管线，支持流式响应
- **PostChatPipeline**: 10+ 步后处理，经验记录，记忆整合
- **深度模块**: MemCore, ContextOrchestrator, ToolExecutor, MemoryAgent

#### Application Layer (应用层)
- **CLI**: 命令行接口，支持交互式对话
- **REST API**: 82 端点模块，FastAPI 框架
- **WebSocket**: 实时通信，支持流式响应
- **通信渠道**: 飞书/钉钉/企业微信/Telegram/Discord/QQ/MQTT/SIP 等

## 3. 核心组件设计

### 3.1 Agent 核心 (`neurova/agent_core.py`)

```python
class Agent:
    """
    系统心脏，通过深度模块化模式拆分
    
    属性:
        mem_core: MemCore - 记忆检索/保存/温度管理
        context_orchestrator: ContextOrchestrator - 上下文构建
        tool_executor: ToolExecutor - 工具调用解析/执行
        memory_agent: MemoryAgent - 记忆管理深度模块
        llm_router: LLMRouter - 多模态自适应路由
        chat_pipeline: ChatPipeline - 6 步对话管线
        post_chat_pipeline: PostChatPipeline - 后处理管线
    """
    
    def chat(message: str, **kwargs) -> ChatResponse
    def rebuild_loop() -> bool
    def process_multimodal(content, media_type, model, metadata) -> str
    def shutdown() -> None
```

### 3.2 ChatPipeline 对话管线

```python
class ChatPipeline:
    """
    6 步对话管线
    
    步骤:
        1. _step_activity_tracking - 空闲追踪 + 会话恢复
        2. _step_pre_llm_checks - 工具记忆检查 + 技能获取
        3. _step_retrieve_and_build_context - 记忆检索 + 上下文构建
        4. _step_evocate_injection - Evocate 结构化推理注入
        5. _step_llm_call - LLM 调用 + 自动续写
        6. _step_post_processing - 后处理管线
    """
```

### 3.3 LLM 路由器 (`neurova/llm/llm_router.py`)

```python
class LLMRouter:
    """
    多模态自适应路由器
    
    支持 10 种请求类型:
        - CHAT: 文本聊天
        - IMAGE_UNDERSTANDING: 图像理解
        - AUDIO_UNDERSTANDING: 音频理解
        - VIDEO_UNDERSTANDING: 视频理解
        - TEXT_TO_IMAGE: 文生图
        - IMAGE_TO_IMAGE: 图生图
        - TEXT_TO_VIDEO: 文生视频
        - IMAGE_TO_VIDEO: 图生视频
        - TEXT_TO_SPEECH: 语音合成
        - SPEECH_TO_TEXT: 语音识别
    
    支持 6+ LLM 提供商:
        - OpenAI (GPT-4, GPT-4o, DALL-E, Whisper)
        - Anthropic (Claude 3.5 Sonnet, Claude 3 Opus)
        - Google Gemini (Gemini 1.5 Pro, Gemini 1.5 Flash)
        - Ollama (本地模型)
        - OpenRouter (聚合服务)
        - LiteLLM (统一接口)
    """
    
    def detect_request_type(message: str) -> RequestType
    def select_model(request_type: RequestType, capabilities: List[ModelCapability]) -> str
    def route_request(message: str, **kwargs) -> LLMResponse
```

### 3.4 记忆系统

```python
class MemoryManager:
    """
    17 维记忆分类管理器
    
    记忆维度:
        1. 短期记忆 (STM) - 当前对话上下文
        2. 长期记忆 (LTM) - 持久化存储
        3. 工作记忆 (WM) - 当前任务上下文
        4. 情节记忆 (EM) - 事件和经历
        5. 语义记忆 (SM) - 知识和概念
        6. 程序性记忆 (PM) - 技能和操作
        7. 情感记忆 (AM) - 情感体验
        8. 工具记忆 (TM) - 工具使用经验
        9. 反思记忆 (RM) - 自我反思
        10. 经验记忆 (ExM) - 经验总结
        11. 社交记忆 (SoM) - 人际关系
        12. 空间记忆 (SpM) - 位置和环境
        13. 时间记忆 (TeM) - 时间序列
        14. 创造性记忆 (CM) - 创意和灵感
        15. 元认知记忆 (MtM) - 对认知的认知
        16. 集体记忆 (CoM) - 群体知识
        17. 进化记忆 (EvM) - 进化历史
    """
    
    def remember(content: str, memory_type: MemoryType, **kwargs) -> Memory
    def recall(query: str, memory_type: Optional[MemoryType] = None) -> List[Memory]
    def consolidate(memories: List[Memory]) -> ConsolidationResult
```

### 3.5 通信渠道管理器

```python
class ChannelManager:
    """
    14 种通信渠道统一管理器
    
    支持渠道:
        - 飞书 (Feishu)
        - 钉钉 (DingTalk)
        - 企业微信 (WeCom)
        - 微信 (WeChat)
        - Telegram
        - Discord
        - QQ
        - MQTT
        - WebSocket
        - SIP
        - Webhook
        - 移动设备 (QR码配对)
        - CLI
        - API
    
    设计原则:
        - 统一消息格式 (ChannelMessage)
        - 适配器模式 (ChannelAdapter)
        - 生命周期管理 (connect/disconnect)
        - 消息路由 (MessageRouter)
    """
    
    def register_adapter(adapter: ChannelAdapter) -> None
    def connect_channel(channel_id: str) -> bool
    def send_message(message: ChannelMessage, channel_id: str) -> bool
    def route_message(message: Message) -> List[str]
```

## 4. 数据流

### 4.1 消息处理流程

```
外部消息 → 渠道适配器 → 消息路由器 → 事件总线 → Agent 处理
                                              ↓
                                        记忆系统存储
                                              ↓
                                        情感分析
                                              ↓
                                        LLM 路由选择
                                              ↓
                                        工具调用 (如有)
                                              ↓
                                        响应生成
                                              ↓
                                        经验记录
                                              ↓
                                        渠道适配器 → 外部
```

### 4.2 记忆访问流程

```
Agent 请求 → 记忆管理器 → 多通道检索
                          ↓
                    向量检索 (TF-IDF/FAISS/ChromaDB)
                          ↓
                    温度过滤 (活跃度排序)
                          ↓
                    情感匹配 (情感记忆优先)
                          ↓
                    时间衰减 (新鲜度加权)
                          ↓
                    结果合并 + 去重
                          ↓
                    返回给 Agent
```

### 4.3 经验闭环流程

```
对话完成 → PostChatPipeline._step_record_experience
          ↓
    EvolutionOrchestrator.on_experience_recorded
          ↓
    经验提取 → 工具洞察 → 权重更新 → 模式挖掘
          ↓
    PatternCrystallizer.observe → 模式积累
          ↓
    结晶存储 (CognitiveStorageEngine)
          ↓
    下次对话检索结晶经验
          ↓
    注入系统提示 "## 结晶经验" 区域
```

## 5. 接口设计

### 5.1 大模型接口

```python
class LLMProvider(ABC):
    """大模型提供商抽象基类"""
    
    @abstractmethod
    def generate_completion(prompt: str, **kwargs) -> Completion
    @abstractmethod
    def generate_chat(messages: List[Message], **kwargs) -> ChatResponse
    @abstractmethod
    def generate_stream(messages: List[Message], **kwargs) -> AsyncIterator[str]
    
class OpenAIProvider(LLMProvider):
    """OpenAI API 实现 - GPT-4, GPT-4o, DALL-E, Whisper"""
    
class AnthropicProvider(LLMProvider):
    """Anthropic API 实现 - Claude 3.5 Sonnet, Claude 3 Opus"""
    
class GeminiProvider(LLMProvider):
    """Google Gemini API 实现 - Gemini 1.5 Pro, Gemini 1.5 Flash"""
    
class OllamaProvider(LLMProvider):
    """Ollama 本地模型实现 - Llama, Mistral, Qwen"""
    
class OpenRouterProvider(LLMProvider):
    """OpenRouter 聚合服务实现 - 多模型统一访问"""
    
class LiteLLMProvider(LLMProvider):
    """LiteLLM 统一接口实现 - 100+ 模型支持"""
```

### 5.2 Skill 接口

```python
class Skill(ABC):
    """Skill 抽象基类"""
    
    @abstractmethod
    def execute(context: SkillContext, params: Dict) -> SkillResult
    @abstractmethod
    def get_metadata() -> SkillMetadata
    
class SkillManager:
    """Skill 管理器 - 支持动态加载和热更新"""
    
    def load_skill(skill_path: str) -> Skill
    def unload_skill(skill_id: str)
    def execute_skill(skill_id: str, params: Dict) -> SkillResult
    def hot_reload(skill_id: str) -> bool
```

### 5.3 渠道适配器接口

```python
class ChannelAdapter(ABC):
    """渠道适配器抽象基类"""
    
    @abstractmethod
    async def connect(self) -> bool
    @abstractmethod
    async def disconnect(self) -> None
    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> bool
    @abstractmethod
    async def receive_message(self) -> Optional[ChannelMessage]
    
class FeishuAdapter(ChannelAdapter):
    """飞书适配器 - 支持 Stream 和 Webhook 模式"""
    
class DingTalkAdapter(ChannelAdapter):
    """钉钉适配器 - 支持 Stream 和 Webhook 模式"""
    
class WeComAdapter(ChannelAdapter):
    """企业微信适配器 - 支持 WebSocket 和回调模式"""
```

## 6. 配置系统

### 6.1 配置文件结构

```yaml
# config.yaml - 多提供商配置示例
framework:
  name: "Neurova"
  version: "v1.0.0-beta1"
  
llm:
  providers:
    - name: "openai"
      api_key: "${OPENAI_API_KEY}"
      models: ["gpt-4", "gpt-4o", "gpt-4-vision-preview"]
      capabilities: ["text", "vision", "tool_use"]
      
    - name: "anthropic"
      api_key: "${ANTHROPIC_API_KEY}"
      models: ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229"]
      capabilities: ["text", "vision", "tool_use"]
      
    - name: "gemini"
      api_key: "${GEMINI_API_KEY}"
      models: ["gemini-1.5-pro", "gemini-1.5-flash"]
      capabilities: ["text", "vision", "audio", "video"]
      
    - name: "ollama"
      base_url: "http://localhost:11434"
      models: ["llama3", "mistral", "qwen2"]
      capabilities: ["text"]
      
  routing:
    default_provider: "openai"
    request_type_mapping:
      chat: ["openai", "anthropic", "gemini"]
      image_understanding: ["gemini", "openai", "anthropic"]
      audio_understanding: ["gemini"]
      video_understanding: ["gemini"]
      text_to_image: ["openai"]
      text_to_speech: ["openai"]
      speech_to_text: ["openai"]
      
memory:
  type: "sqlite"
  database: "data/memory.db"
  dimensions: 17
  temperature_decay: 0.95
  consolidation_interval: 3600
  
agents:
  - id: "assistant"
    name: "智能助手"
    llm:
      provider: "openai"
      model: "gpt-4"
    skills: ["search", "calculator", "code_execution"]
    
  - id: "analyst"
    name: "数据分析师"
    llm:
      provider: "anthropic"
      model: "claude-3-5-sonnet-20241022"
    skills: ["data_analysis", "chart", "statistical_analysis"]
    
  - id: "creative"
    name: "创意助手"
    llm:
      provider: "gemini"
      model: "gemini-1.5-pro"
    skills: ["image_generation", "video_generation", "creative_writing"]
    
channels:
  - type: "feishu"
    app_id: "${FEISHU_APP_ID}"
    app_secret: "${FEISHU_APP_SECRET}"
    mode: "stream"
    
  - type: "dingtalk"
    app_key: "${DINGTALK_APP_KEY}"
    app_secret: "${DINGTALK_APP_SECRET}"
    mode: "stream"
    
  - type: "telegram"
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    
  - type: "websocket"
    host: "0.0.0.0"
    port: 8765
    
routing:
  default_target: "assistant"
  rules:
    - pattern: ".*数据.*|.*分析.*"
      target: "analyst"
    - pattern: ".*图片.*|.*视频.*|.*创意.*"
      target: "creative"
    - pattern: ".*"
      target: "assistant"
```

## 7. 安全设计

### 7.1 三层隔离机制

```python
@dataclass(frozen=True)
class IsolationContext:
    """
    三层隔离上下文
    
    隔离层级:
        1. agent_id - Agent 隔离 (不同 Agent 数据隔离)
        2. neuser_id - 系统用户隔离 (不同用户数据隔离)
        3. user_id - 对话用户隔离 (同一用户不同对话隔离)
        4. shared - 跨 Agent 共享开关 (可控共享范围)
    """
    agent_id: str
    neuser_id: str
    user_id: str
    shared: bool = False
    
    def with_shared(self, shared: bool) -> 'IsolationContext':
        """创建共享上下文"""
        return IsolationContext(
            agent_id=self.agent_id,
            neuser_id=self.neuser_id,
            user_id=self.user_id,
            shared=shared
        )
```

### 7.2 安全机制
- **API Key 加密存储**: 使用 Fernet 对称加密
- **消息签名验证**: HMAC-SHA256 签名
- **输入验证和过滤**: 10 种内置敏感模式检测
- **权限控制**: RBAC 角色权限系统
- **审计日志**: 完整操作审计记录
- **沙箱环境**: Skill 执行沙箱，资源限制

## 8. 性能优化

### 8.1 缓存策略
- **记忆查询缓存**: L1 肌肉记忆，L2 热缓存
- **LLM 响应缓存**: 相似请求复用
- **配置缓存**: 启动时加载，运行时只读
- **向量索引缓存**: 增量同步，异步更新

### 8.2 并发处理
- **异步消息处理**: asyncio 事件循环
- **连接池管理**: LLM 客户端连接池
- **批量操作支持**: 记忆批量写入
- **线程安全**: threading.RLock 保护共享状态

## 9. 监控和日志

### 9.1 日志系统
- **结构化日志**: JSON 格式，便于分析
- **日志级别控制**: DEBUG/INFO/WARNING/ERROR/CRITICAL
- **日志轮转**: 按大小和时间轮转
- **轨迹记录**: TrajectoryRecorder 记录完整执行轨迹

### 9.2 监控指标
- **Agent 状态监控**: 在线状态、响应时间、错误率
- **消息处理延迟**: 端到端延迟监控
- **记忆系统性能**: 检索命中率、温度分布
- **LLM API 调用统计**: 调用次数、延迟、成本
- **进化系统指标**: 模式发现率、经验结晶率

## 10. 部署架构

### 10.1 单机部署
```
[Neurova Instance]
  ├── SQLite Database
  ├── Vector Store (FAISS/ChromaDB)
  ├── File Storage
  ├── Configuration
  └── Logs
```

### 10.2 Docker 部署
```yaml
version: '3.8'
services:
  neurova:
    build: .
    volumes:
      - ./data:/app/data
      - ./config:/app/config
      - ./logs:/app/logs
    ports:
      - "9527:9527"  # API 端口
      - "8765:8765"  # WebSocket 端口
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
```

### 10.3 集群部署
```
[Load Balancer]
      ↓
[Neurova-1] [Neurova-2] [Neurova-3]
      ↓           ↓           ↓
[Shared Database Cluster]
      ↓
[Shared Vector Store]
```

## 11. 扩展点

### 11.1 插件扩展
- **自定义 Skill**: 实现 Skill 接口，支持热加载
- **自定义消息渠道**: 实现 ChannelAdapter 接口
- **自定义 LLM 提供商**: 实现 LLMProvider 接口
- **自定义记忆存储**: 实现 MemoryStorage 接口
- **自定义进化策略**: 实现 EvolutionStrategy 接口

### 11.2 API 扩展
- **RESTful API**: 82 端点模块，FastAPI 框架
- **WebSocket API**: 实时通信，流式响应
- **gRPC API**: 高性能 RPC (未来)
- **GraphQL API**: 灵活查询 (未来)

## 12. 版本历史

### v1.0.0-beta1 (CogArch 2.0) - 当前版本
- 深度模块化重构 (Agent 2180→1621 行)
- 17 维记忆系统
- 多模态 LLM 路由 (6+ 提供商)
- 14 种通信渠道
- 情感架构 (17 种情感分类)
- 进化系统 (模式挖掘、经验结晶)
- 三层隔离安全机制
- 生产级部署支持

### v3.0 (CogArch 1.0)
- 多 Agent 协作系统
- 基础记忆系统 (11 维)
- 单 LLM 提供商支持
- 基础通信渠道 (5 种)
- 情感分析基础

### v2.0
- Agent 核心实现
- SQLite 记忆存储
- OpenAI/Anthropic 支持
- 基础 CLI

### v1.0 (MVP)
- 项目初始化
- 基础框架搭建
- 概念验证