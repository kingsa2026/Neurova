# Neurova 完整功能模块文档

> **最后更新**: 2026-05-07  
> **基于**: 实际代码扫描结果  
> **目的**: 补充文档中缺失的实际已实现功能

---

## 一、核心基础设施模块 (Phase 5 新增)

### 1.1 模块库系统

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `module_lib.py` | `neurova/core/` | `ModuleLib` | 模块库（动态加载/卸载/依赖管理） |
| `event_bus.py` | `neurova/core/` | `EventBus`, `EventPriority` | 统一事件总线（发布-订阅/优先级/异步队列） |
| `state_manager.py` | `neurova/core/` | `StateManager`, `StateChange` | 统一状态管理（状态树/变更追踪/快照回滚） |
| `config_manager.py` | `neurova/core/` | `ConfigManager` | 统一配置管理（分层配置/环境变量/验证器） |
| `logger.py` | `neurova/core/` | `Logger`, `LogEntry`, `LogLevel` | 统一日志管理（结构化日志/分级/导出） |
| `error_handler.py` | `neurova/core/` | `ErrorHandler`, `ErrorCode`, `NeurovaError` | 统一错误处理（30+ 错误码/恢复策略/安全执行） |
| `base_module.py` | `neurova/core/` | `BaseModule`, `ModuleState` | 基础模块接口（生命周期管理/6 种状态） |
| `api_standard.py` | `neurova/core/` | `APIInterface`, `APIResponse`, `APIRequest` | 统一 API 标准（请求/响应格式/错误码规范） |

### 1.2 模块间通信

- **事件总线**: 支持同步/异步事件分发，5 种优先级（CRITICAL/HIGH/NORMAL/LOW/BACKGROUND）
- **状态同步**: 集中管理应用状态，支持监听器机制
- **依赖解析**: 模块依赖关系解析，循环依赖检测

---

## 二、前端 UI 框架 (Phase 5 新增)

### 2.1 UI 组件库

| 文件 | 路径 | 说明 |
|------|------|------|
| `framework.js` | `neurova/ui/` | 前端框架入口（组件注册/状态绑定/事件总线） |
| `event-bus.js` | `neurova/ui/` | 统一事件总线（发布-订阅/优先级/日志追踪） |
| `state-manager.js` | `neurova/ui/` | 统一状态管理库（状态树/变更追踪/持久化/回滚） |
| `component-registry.js` | `neurova/ui/` | 组件注册表（注册/创建/销毁/生命周期） |
| `ui-manager.js` | `neurova/ui/` | UI 管理器（统一调用入口/事件路由） |

### 2.2 组件集合

| 组件 | 路径 | 说明 |
|------|------|------|
| `base.js` | `ui/components/` | 组件基类（生命周期/属性管理/状态同步） |
| `button.js` | `ui/components/` | 按钮组件 |
| `card.js` | `ui/components/` | 卡片组件 |
| `input.js` | `ui/components/` | 输入框组件 |
| `list.js` | `ui/components/` | 列表组件 |
| `list-item.js` | `ui/components/` | 列表项组件 |

### 2.3 样式系统

| 文件 | 路径 | 说明 |
|------|------|------|
| `theme.js` | `ui/styles/` | 主题管理系统（多主题/CSS 变量/响应式断点） |
| `base.css.js` | `ui/styles/` | 基础样式库 |

### 2.4 布局系统

| 文件 | 路径 | 说明 |
|------|------|------|
| `grid.js` | `ui/layout/` | 网格布局系统（12 列网格/响应式） |
| `grid-row.js` | `ui/layout/` | 网格行组件 |
| `flex.js` | `ui/layout/` | Flexbox 布局系统 |

### 2.5 交互系统

| 文件 | 路径 | 说明 |
|------|------|------|
| `click.js` | `ui/interaction/` | 点击交互处理器（防抖/节流/长按） |
| `drag.js` | `ui/interaction/` | 拖拽交互处理器（拖拽/放置/边界限制） |
| `scroll.js` | `ui/interaction/` | 滚动交互处理器（惯性滚动/捕捉滚动） |

### 2.6 动画系统

| 文件 | 路径 | 说明 |
|------|------|------|
| `transition.js` | `ui/animation/` | 过渡动画库（批量/序列动画） |
| `keyframes.js` | `ui/animation/` | 关键帧动画库（预定义动画） |

### 2.7 通知系统

| 文件 | 路径 | 说明 |
|------|------|------|
| `toast.js` | `ui/notification/` | Toast 通知组件（四种类型/自动关闭） |
| `alert.js` | `ui/notification/` | Alert 对话框组件 |
| `modal.js` | `ui/notification/` | Modal 对话框组件 |

---

## 三、API 端点完整清单

### 3.1 认证 API (`/api/auth/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录 |
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/refresh` | POST | Token 刷新 |

### 3.2 Agent API (`/api/agent/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agent/` | GET | Agent 列表 |
| `/api/agent/<agent_id>` | GET | Agent 详情 |
| `/api/agent/<agent_id>` | POST | 创建 Agent |
| `/api/agent/<agent_id>` | PUT | 更新 Agent |
| `/api/agent/<agent_id>` | DELETE | 删除 Agent |
| `/api/agent/<agent_id>/identity` | GET | Agent 身份 |
| `/api/agent/<agent_id>/stats` | GET | Agent 统计 |
| `/api/agent/<agent_id>/restart` | POST | 重启 Agent |
| `/api/agent/<agent_id>/reset` | POST | 重置 Agent |
| `/api/agent/<agent_id>/llm/presets` | GET | LLM 预设列表 |
| `/api/agent/<agent_id>/llm/presets/<preset_name>` | POST | 切换 LLM 预设 |
| `/api/agent/<agent_id>/llm` | GET | LLM 配置 |
| `/api/agent/<agent_id>/llm` | PUT | 更新 LLM 配置 |

### 3.3 聊天 API (`/api/chat/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送消息 |
| `/api/chat/stream` | POST | 流式对话 |
| `/api/chat/history` | GET | 对话历史 |
| `/api/chat/typing` | POST | 打字指示器 |
| `/api/chat/stop` | POST | 停止生成 |

### 3.4 记忆 API (`/api/memory/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/memory/` | GET | 记忆列表 |
| `/api/memory/` | POST | 添加记忆 |
| `/api/memory/search` | GET | 搜索记忆 |
| `/api/memory/<memory_id>` | GET | 记忆详情 |
| `/api/memory/<memory_id>` | PUT | 更新记忆 |
| `/api/memory/<memory_id>` | DELETE | 删除记忆 |
| `/api/memory/stats` | GET | 记忆统计 |
| `/api/memory/recall` | POST | 记忆召回 |
| `/api/memory/crystallize/<memory_id>` | POST | 固化记忆 |
| `/api/memory/decay` | POST | 温度衰减 |
| `/api/memory/conflict` | GET | 记忆冲突检测 |
| `/api/memory/conflict/<memory_id>` | POST | 解决记忆冲突 |
| `/api/memory/sleep` | POST | 触发睡眠巩固 |
| `/api/memory/sleep/stats` | GET | 睡眠统计 |
| `/api/memory/sleep/manual` | POST | 手动睡眠 |
| `/api/memory/compress` | POST | 记忆压缩 |
| `/api/memory/relations` | GET | 记忆关系 |
| `/api/memory/relations` | POST | 添加记忆关联 |
| `/api/memory/proactive` | POST | 主动回忆 |
| `/api/memory/time/context` | GET | 时间上下文 |
| `/api/memory/security/scan` | POST | 安全扫描 |
| `/api/memory/security/quarantine` | POST | 隔离记忆 |
| `/api/memory/context/<memory_id>` | POST | 注入上下文 |
| `/api/memory/version/<memory_id>` | GET | 版本历史 |
| `/api/memory/version/<memory_id>/rollback` | POST | 版本回滚 |
| `/api/memory/version/compare` | POST | 版本对比 |
| `/api/memory/cache/stats` | GET | 缓存统计 |
| `/api/memory/cache/clear` | POST | 清除缓存 |
| `/api/memory/batch/stats` | GET | 批量写入统计 |
| `/api/memory/batch/flush` | POST | 强制刷写 |

### 3.5 渠道 API (`/api/channels/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/channels/` | GET | 渠道列表 |
| `/api/channels/<channel>` | GET | 渠道状态 |
| `/api/channels/<channel>` | POST | 添加/更新渠道 |
| `/api/channels/<channel>/config` | PATCH | 更新渠道配置 |
| `/api/channels/<channel>/enable` | POST | 启用渠道 |
| `/api/channels/<channel>/disable` | POST | 禁用渠道 |
| `/api/channels/<channel>` | DELETE | 移除渠道 |
| `/api/channels/users/link` | POST | 关联用户身份 |
| `/api/channels/users/<global_user_id>/sessions` | GET | 获取用户会话 |
| `/api/channels/<channel>/send` | POST | 发送消息 |
| `/api/channels/webhook/<channel>` | POST | Webhook 端点 |
| `/api/channels/capabilities` | GET | 渠道能力描述 |

### 3.6 技能 API (`/api/skills/`)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/skills/list` | GET | 技能列表 |
| `/api/skills/<skill_name>` | GET | 技能信息 |
| `/api/skills/<skill_name>/execute` | POST | 执行技能 |
| `/api/skills/market/import` | POST | 从市场导入技能 |
| `/api/skills/market/history` | GET | 导入历史 |
| `/api/skills/market/list` | GET | 已安装技能 |
| `/api/skills/market/list-all` | GET | 所有技能市场 |
| `/api/skills/public/list` | GET | 公共技能列表 |
| `/api/skills/public/search` | GET | 搜索公共技能 |
| `/api/skills/public/<skill_name>/push` | POST | 推送到 Agent |
| `/api/skills/public/stats` | GET | 公共技能统计 |
| `/api/skills/agent/local` | GET | Agent 本地技能 |
| `/api/skills/agent/<skill_name>` | POST | 添加本地技能 |
| `/api/skills/agent/<skill_name>/disable` | POST | 禁用本地技能 |
| `/api/skills/agent/<skill_name>/enable` | POST | 启用本地技能 |
| `/api/skills/agent/<skill_name>/remove` | POST | 移除本地技能 |
| `/api/skills/agent/<skill_name>/share` | POST | 共享到公共库 |
| `/api/skills/agent/<skill_name>/pull` | POST | 从公共库拉取 |

---

## 四、枚举类型完整清单

### 4.1 消息渠道类型

```python
MessageChannel (neurova/channels/__init__.py)
  FEISHU, DINGTALK, WECHAT, TELEGRAM, QQ, QQBOT, 
  DISCORD, SIP, XIAOYI, MQTT, WEBSOCKET, WEB, CLI, API, UNKNOWN
```

### 4.2 消息内容类型

```python
ContentType (neurova/channels/__init__.py)
  TEXT, IMAGE, VOICE, VIDEO, FILE, CARD, LOCATION, CONTACT, SYSTEM
```

### 4.3 消息类型

```python
MessageType (neurova/router.py)
  CHAT, COMMAND, QUESTION, SKILL_REQUEST, MEMORY_REQUEST, SYSTEM, UNKNOWN
```

### 4.4 技能状态

```python
SkillStatus (neurova/skill.py)
  ACTIVE, INACTIVE, ERROR
```

### 4.5 事件优先级

```python
EventPriority (neurova/core/event_bus.py)
  CRITICAL, HIGH, NORMAL, LOW, BACKGROUND
```

### 4.6 模块状态

```python
ModuleState (neurova/core/base_module.py)
  PENDING, INITIALIZING, INITIALIZED, STARTING, RUNNING, STOPPING, STOPPED, ERROR, DESTROYED
```

### 4.7 记忆系统枚举

```python
MemoryType (neurova/memory/core/models.py)
  EPISODIC, SEMANTIC, PROCEDURAL, EMOTIONAL

MemoryCategory (neurova/memory/core/models.py)
  PROFILE, PREFERENCE, MEMORY, EXPERIENCE, KNOWLEDGE, EMOTION, PLAN, REFLECTION

LifecycleStage (neurova/memory/core/models.py)
  NEW, ACTIVE, FADING, CRYSTALLIZED, FORGOTTEN

MemoryPerspective (neurova/memory/core/models.py)
  USER_PERSPECTIVE, AGENT_PERSPECTIVE, SHARED_PERSPECTIVE

EmotionType (neurova/memory/core/models.py)
  JOY, SADNESS, ANGER, FEAR, SURPRISE, NEUTRAL, HOPE
```

### 4.8 日志级别

```python
LogLevel (neurova/core/logger.py)
  DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### 4.9 错误码

```python
ErrorCode (neurova/core/error_handler.py)
  SUCCESS = 0
  INTERNAL_ERROR = 1000
  INVALID_PARAMETER = 1001
  RESOURCE_NOT_FOUND = 1002
  # ... 30+ 错误码定义
```

---

## 五、数据模型完整清单

### 5.1 渠道消息模型

| 模型 | 路径 | 说明 |
|------|------|------|
| `UnifiedMessage` | `channels/__init__.py` | 统一消息模型（跨渠道标准化） |
| `UserIdentity` | `channels/__init__.py` | 用户身份映射（跨渠道身份关联） |
| `SessionContext` | `channels/__init__.py` | 会话上下文（按 Agent 隔离） |
| `ChannelConfig` | `channels/__init__.py` | 渠道配置 |
| `ChannelAdapter` | `channels/__init__.py` | 渠道适配器基类 |
| `UserIdentityManager` | `channels/__init__.py` | 用户身份管理器 |
| `SessionManager` | `channels/__init__.py` | 会话管理器 |
| `CrossChannelRouter` | `channels/__init__.py` | 跨渠道消息路由器 |

### 5.2 路由与技能模型

| 模型 | 路径 | 说明 |
|------|------|------|
| `Message` | `router.py` | 消息对象 |
| `RouteResult` | `router.py` | 路由结果 |
| `SkillResult` | `skill.py` | 技能执行结果 |
| `SkillInfo` | `skill.py` | 技能信息 |
| `SkillEvent` | `skill.py` | 技能事件常量 |

### 5.3 LLM 模型

| 模型 | 路径 | 说明 |
|------|------|------|
| `LLMResponse` | `llm_client.py` | LLM 响应数据 |
| `LLMConfig` | `llm_client.py` | LLM 配置 |
| `ModelPreset` | `llm/presets.py` | 模型预设 |
| `LLMPresetRegistry` | `llm/presets.py` | LLM 预设注册表 |

### 5.4 记忆系统模型

| 模型 | 路径 | 说明 |
|------|------|------|
| `Memory` | `memory/core/models.py` | 记忆数据模型 |
| `MemoryRelation` | `memory/core/models.py` | 记忆关联模型 |
| `StateChange` | `core/state_manager.py` | 状态变更记录 |
| `LogEntry` | `core/logger.py` | 日志条目 |

### 5.5 核心框架模型

| 模型 | 路径 | 说明 |
|------|------|------|
| `APIRequest` | `core/api_standard.py` | 统一 API 请求 |
| `APIResponse` | `core/api_standard.py` | 统一 API 响应 |
| `AuthToken` | `core/api_standard.py` | 认证令牌 |
| `PageRequest` | `core/api_standard.py` | 分页请求 |
| `PageResponse` | `core/api_standard.py` | 分页响应 |
| `BaseModule` | `core/base_module.py` | 模块基类 |
| `ModuleInstance` | `core/module_lib.py` | 模块实例 |

---

## 六、事件定义完整清单

### 6.1 技能事件 (SkillEvent)

| 事件 | 触发时机 |
|------|----------|
| `skill.pre_execute` | 技能执行前 |
| `skill.post_execute` | 技能执行后 |
| `skill.register` | 技能注册 |
| `skill.unregister` | 技能注销 |
| `skill.error` | 技能错误 |

### 6.2 记忆事件 (MemoryEventBus)

| 事件 | 触发时机 |
|------|----------|
| `memory.created` | 记忆创建 |
| `memory.updated` | 记忆更新 |
| `memory.deleted` | 记忆删除 |
| `memory.recalled` | 记忆召回 |
| `memory.crystallized` | 记忆固化 |
| `memory.forgotten` | 记忆遗忘 |
| `memory.conflict` | 记忆冲突 |
| `memory.consolidated` | 记忆巩固 |

### 6.3 模块事件 (EventBus)

| 事件类型 | 说明 |
|----------|------|
| 自定义事件 | 支持任意事件的注册和分发 |
| 事件优先级 | CRITICAL/HIGH/NORMAL/LOW/BACKGROUND |
| 异步事件 | 支持异步事件队列处理 |
| 一次性订阅 | 支持 once=true 一次性订阅 |

---

## 七、LLM 预设完整清单

### 7.1 本地模型 (3个)

| 预设名 | 说明 |
|--------|------|
| `ollama` | Ollama 本地模型 |
| `lm-studio` | LM Studio 本地模型 |
| `qwenpaw-local` | QwenPaw 本地模型 |

### 7.2 国内模型 (11个)

| 预设名 | 说明 |
|--------|------|
| `dashscope` | 阿里 DashScope |
| `aliyun-coding-cn` | 阿里云通义千问 |
| `kimi-china` | Kimi (国内) |
| `deepseek` | DeepSeek |
| `zhipu-bigmodel` | 智谱 BigModel |
| `zhipu-zai` | 智谱 GLM |
| `siliconflow-cn` | SiliconFlow (国内) |
| `minimax-cn` | MiniMax (国内) |
| `modelscope` | ModelScope |
| `dashscope-qwen` | DashScope Qwen |
| `baidu-qianfan` | 百度千帆 |

### 7.3 国际模型 (7个)

| 预设名 | 说明 |
|--------|------|
| `openai` | OpenAI GPT |
| `azure-openai` | Azure OpenAI |
| `anthropic` | Anthropic Claude |
| `google-gemini` | Google Gemini |
| `kimi-intl` | Kimi (国际) |
| `minimax-intl` | MiniMax (国际) |
| `siliconflow-intl` | SiliconFlow (国际) |

### 7.4 聚合平台 (3个)

| 预设名 | 说明 |
|--------|------|
| `openrouter` | OpenRouter |
| `sambanova` | SambaNova |
| `opencode` | OpenCode |

---

## 八、渠道适配器完整清单

| 渠道 | 文件路径 | 类/函数 | 说明 |
|------|----------|---------|------|
| 飞书 | `channels/feishu.py` | `FeishuAdapter`, `create_feishu_adapter` | 完整飞书适配器（Webhook/签名验证/多类型消息） |
| 钉钉 | `channels/dingtalk.py` | `create_dingtalk_adapter` | 钉钉适配器 |
| 企业微信 | `channels/wechat.py` | `WeChatWecomAdapter`, `create_wechat_wecom_adapter` | 企业微信适配器（access_token/消息收发） |
| 微信个人号 | `channels/wechat.py` | `WeChatILinkAdapter`, `create_wechat_ilink_adapter` | iLink 个人号适配器（扫码登录/Token 持久化） |
| 微信公众号 | `channels/wechat.py` | `WeChatOfficialAdapter`, `create_wechat_official_adapter` | 公众号适配器（access_token/客服消息） |
| Telegram | `channels/telegram.py` | `TelegramAdapter`, `create_telegram_adapter` | 完整 Telegram 适配器（长轮询/Webhook/命令处理/代理） |
| QQ 频道 | `channels/qq.py` | `create_qq_adapter` | QQ 频道适配器 |
| QQ 个人号 | `channels/qqbot.py` | `create_qqbot_adapter` | QQ 个人号适配器 |
| Discord | `channels/discord.py` | `create_discord_adapter` | Discord 适配器 |
| SIP 语音 | `channels/sip.py` | `create_sip_adapter` | SIP 语音适配器 |
| 小艺(华为) | `channels/xiaoyi.py` | `create_xiaoyi_adapter` | 小艺适配器 |
| MQTT | `channels/mqtt.py` | `create_mqtt_adapter` | MQTT 适配器 |
| WebSocket | `channels/websocket.py` | `create_websocket_adapter` | WebSocket 适配器 |

### 8.1 渠道管理器

| 类 | 路径 | 说明 |
|----|------|------|
| `ChannelManager` | `channels/manager.py` | 渠道管理器（配置 CRUD/适配器创建/用户身份关联/会话管理） |
| `CrossChannelRouter` | `channels/__init__.py` | 跨渠道消息路由器 |
| `UserIdentityManager` | `channels/__init__.py` | 用户身份管理器 |
| `SessionManager` | `channels/__init__.py` | 会话管理器 |

---

## 九、核心类完整清单

### 9.1 根包核心类

| 类名 | 路径 | 说明 |
|------|------|------|
| `AgentConfig` | `agent.py` | Agent 配置类 |
| `Agent` | `agent.py` | Agent 核心（记忆检索/上下文构建/LLM 调用/Router 集成） |
| `NeurovaCLI` | `cli.py` | 命令行交互界面（15+ 命令） |
| `ContextBuilder` | `context.py` | 上下文构建器 |
| `SmartContextCompressor` | `context_compressor.py` | 智能上下文压缩器 |
| `ContextCacheManager` | `context_cache.py` | 上下文缓存管理器 |
| `ContextPersistence` | `context_persistence.py` | 上下文持久化 |
| `EnhancedContextBuilder` | `enhanced_context_builder.py` | 增强版上下文构建器 |
| `MemoryReadWriteManager` | `memory_rw_manager.py` | 记忆读写管理器（写缓冲/批量提交） |
| `LLMClient` | `llm_client.py` | LLM 客户端（OpenAI 兼容/流式输出/重试） |
| `MessageRouter` | `router.py` | 消息路由器（类型识别/路由分发/Skill 集成） |
| `Skill` | `skill.py` | 技能基类 |
| `MemorySkill` | `skill.py` | 记忆管理技能 |
| `WebSearchSkill` | `skill.py` | 网络搜索技能 |
| `FileOperationSkill` | `skill.py` | 文件操作技能 |
| `SkillRegistry` | `skill.py` | 技能注册中心 |

### 9.2 核心框架类

| 类名 | 路径 | 说明 |
|------|------|------|
| `BaseModule` | `core/base_module.py` | 模块基类（生命周期管理） |
| `APIInterface` | `core/api_standard.py` | API 标准接口 |
| `EventBus` | `core/event_bus.py` | 事件总线 |
| `StateManager` | `core/state_manager.py` | 状态管理器 |
| `ConfigManager` | `core/config_manager.py` | 配置管理器 |
| `Logger` | `core/logger.py` | 日志管理器 |
| `ErrorHandler` | `core/error_handler.py` | 错误处理器 |
| `ModuleLib` | `core/module_lib.py` | 模块库 |

### 9.3 记忆系统核心类

| 类名 | 路径 | 说明 |
|------|------|------|
| `MemoryStorage` | `memory/core/storage.py` | 记忆存储引擎（SQLite/WAL/FTS5） |
| `TemperatureEngine` | `memory/core/temperature.py` | 温度引擎（遗忘曲线/升温/衰减/固化） |
| `MemoryManager` | `memory/core/manager.py` | 记忆管理器（统一入口） |
| `VectorSearch` | `memory/core/vector_search.py` | 向量搜索引擎（TF-IDF/余弦相似度） |
| `EmotionAnalyzer` | `memory/core/emotion.py` | 情感分析器（7 种情感维度） |
| `ConflictDetector` | `memory/core/conflict.py` | 记忆冲突检测器（5 种冲突类型） |
| `SleepConsolidation` | `memory/core/sleep.py` | 睡眠记忆巩固 |
| `MemoryCompressor` | `memory/core/compression.py` | 记忆压缩器（3 层压缩） |
| `ProactiveRecall` | `memory/core/proactive_recall.py` | 主动回忆（4 种触发器） |
| `TimeAwareness` | `memory/core/time_awareness.py` | 时间感知 |
| `MemorySecurity` | `memory/core/security.py` | 记忆安全 |
| `ContextInjector` | `memory/core/context_injector.py` | 上下文注入器 |
| `MemoryCache` | `memory/core/cache.py` | 记忆缓存 |
| `BatchWriter` | `memory/core/cache.py` | 批量写入器 |
| `MemoryVersionControl` | `memory/core/version_control.py` | 记忆版本控制 |
| `MemoryEventBus` | `memory/core/memory_bus.py` | 记忆事件总线 |

### 9.4 技能系统类

| 类名 | 路径 | 说明 |
|------|------|------|
| `Skill` | `skills/public_library.py` | 技能基类 |
| `PublicSkillLibrary` | `skills/public_library.py` | 公共技能库 |
| `AgentSkillLibrary` | `skills/agent_library.py` | Agent 本地技能库 |
| `SkillMarketImporter` | `skills/market_importer.py` | 技能市场导入器 |
| `SkillMarketAdapter` | `skills/market_adapters.py` | 技能市场适配器基类 |
| `SkillsShAdapter` | `skills/market_adapters.py` | Skills.sh 适配器 |
| `ClawHubAdapter` | `skills/market_adapters.py` | ClawHub 适配器 |
| `SkillsMPAdapter` | `skills/market_adapters.py` | SkillsMP 适配器 |
| `LobeHubAdapter` | `skills/market_adapters.py` | LobeHub 适配器 |
| `GitHubMarketAdapter` | `skills/market_adapters.py` | GitHub 适配器 |
| `ModelScopeAdapter` | `skills/market_adapters.py` | ModelScope 适配器 |
| `SkillMarketRegistry` | `skills/market_adapters.py` | 技能市场注册表 |

### 9.5 API 路由类

| 类/蓝图 | 路径 | 说明 |
|---------|------|------|
| `app` | `api/app.py` | Neurova Server 主入口 |
| `api_bp` | `api/app.py` | 主 API Blueprint |
| `auth_bp` | `api/auth.py` | 认证 Blueprint |
| `agent_bp` | `api/endpoints/agent.py` | Agent 管理 Blueprint |
| `auth_ep_bp` | `api/endpoints/auth.py` | 认证端点 Blueprint |
| `channel_bp` | `api/endpoints/channel.py` | 渠道配置 Blueprint |
| `chat_bp` | `api/endpoints/chat.py` | 聊天端点 Blueprint |
| `memory_bp` | `api/endpoints/memory.py` | 记忆管理 Blueprint |
| `skill_bp` | `api/endpoints/skill.py` | 技能管理 Blueprint |
| `TokenManager` | `api/auth.py` | Token 管理器 |
| `AuthMiddleware` | `api/middleware.py` | 认证中间件 |

---

## 十、数据库完整清单

### 10.1 主表

| 表名 | 说明 | 字段数 |
|------|------|--------|
| `memories` | 记忆主表 | 30+ |
| `sessions` | 会话主表 | 15+ |
| `agents` | Agent 配置表 | - |
| `tasks` | 任务表 | - |
| `plugins` | 插件表 | - |

### 10.2 副表

| 表名 | 说明 |
|------|------|
| `memory_emotions` | 记忆情感副表 |
| `memory_relations` | 记忆关联副表 |
| `memory_keywords` | 记忆关键词副表 |
| `session_messages` | 会话消息副表 |
| `session_context_snapshots` | 会话上下文快照副表 |
| `memory_conflicts` | 记忆冲突副表 |
| `memory_associations` | 记忆联想副表 |
| `memory_merge_history` | 记忆合并历史副表 |
| `memory_provenance` | 记忆来源副表 |
| `memory_embeddings` | 记忆嵌入副表 |
| `memory_versions` | 记忆版本副表 |
| `social_entities` | 社交实体表 |
| `social_relationships` | 社交关系表 |
| `memory_social_links` | 记忆社交链接表 |
| `sensitive_info_records` | 敏感信息记录表 |
| `privacy_logs` | 隐私日志表 |
| `time_patterns` | 时间模式表 |
| `time_event_reminders` | 时间事件提醒表 |
| `memory_feedback` | 记忆反馈表 |

### 10.3 索引

- **主索引**: 35+ 个索引，覆盖所有查询路径
- **FTS5 虚拟表**: `memories_fts` 全文检索虚拟表
- **部分索引**: 针对特定查询场景优化的部分索引

---

## 十一、测试覆盖清单

### 11.1 单元测试

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| `tests/unit/memory/core/test_temperature.py` | 25+ | 温度引擎 |
| `tests/unit/memory/core/test_vector_search.py` | 20+ | 向量搜索 |
| `tests/unit/memory/core/test_emotion.py` | 20+ | 情感分析 |
| `tests/unit/memory/core/test_storage.py` | 20+ | 存储层 |
| `tests/unit/memory/core/test_manager.py` | 20+ | 记忆管理器 |
| `tests/unit/memory/core/test_compression.py` | 15+ | 压缩引擎 |
| `tests/unit/test_router.py` | 25+ | 消息路由器 |
| `tests/unit/test_skill.py` | 25+ | Skill 系统 |
| `tests/unit/test_agent.py` | 25+ | Agent 核心 |

### 11.2 集成测试

| 测试文件 | 测试数 | 覆盖场景 |
|----------|--------|----------|
| `tests/integration/test_agent_router_skill.py` | 25 | Agent → Router → Skill 调用链 |
| `tests/integration/test_full_chain.py` | 15+ | 完整流程测试 |

### 11.3 总计

- **总测试数**: 336+
- **测试通过率**: 100%
- **核心模块覆盖率**: 80%+

---

## 十三、服务器与 WebUI 模块

### 13.1 Neurova Server

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `neurova_server.py` | `neurova/` | `create_app`, `run_server` | Neurova Server（REST API/静态文件/健康检查/记忆管理/渠道Webhook） |
| `server.py` | `neurova/` | - | 服务器启动入口 |
| `start.py` | `neurova/` | - | 启动脚本 |

### 13.2 Neurova API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页（加载 neurova-ui.html） |
| `/channels-ui.html` | GET | 渠道管理页面 |
| `/stats.html` | GET | 统计页面 |
| `/health` | GET | 健康检查 |
| `/api/stats` | GET | 系统统计（记忆/渠道状态） |
| `/api/chat` | POST | 对话接口 |
| `/api/remember` | POST | 添加记忆 |
| `/api/memories` | GET | 搜索记忆 |
| `/api/channels/webhook/<channel>` | POST | 渠道 Webhook 接收 |

### 13.3 WebUI 控制台

| 文件 | 路径 | 框架 | 说明 |
|------|------|------|------|
| `webui.py` | `neurova/` | Streamlit | 忆灵控制台（Agent管理/记忆查看/对话测试/配置管理） |
| `neurova-ui.html` | 根目录 | 原生HTML/CSS/JS | 现代化 WebUI 面板（左侧导航/悬浮Agent切换/响应式布局） |

### 13.4 Streamlit 页面功能

| 页面 | 说明 |
|------|------|
| Agent 管理 | 创建/编辑/删除 Agent，查看状态 |
| 记忆查看 | 搜索/浏览/管理记忆，温度可视化 |
| 对话测试 | 实时对话测试，上下文查看 |
| 配置管理 | Agent 配置/LLM 配置/渠道配置 |
| 统计信息 | 系统运行统计/记忆统计/对话统计 |

---

## 十四、上下文处理增强模块

### 14.1 上下文缓存

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `context_cache.py` | `neurova/` | `ContextCacheManager`, `CacheEntry` | 上下文缓存管理器（LRU淘汰/批量写入/会话完整性保护/Token估算） |

### 14.2 缓存核心特性

| 特性 | 说明 |
|------|------|
| 优先读缓存 | 减少磁盘 IO，提高响应速度 |
| 批量写入 | 定期刷新 dirty 缓存到磁盘（默认 30 秒） |
| 会话完整性保护 | 不截断对话轮次，保证上下文完整 |
| LRU 淘汰策略 | 自动清理最少使用的缓存 |
| 内存限制 | 最大 100 条目，512MB 内存占用 |
| Token 估算 | 中文 1.5 token/字符，英文 0.25 token/字符 |

### 14.3 上下文持久化

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `context_persistence.py` | `neurova/` | `ContextPersistence` | 上下文持久化存储（JSON 文件/按 Agent 和 Session 分类） |

### 14.4 上下文压缩

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `context_compressor.py` | `neurova/` | `SmartContextCompressor` | 智能上下文压缩器（3 层压缩/去重/摘要生成） |

### 14.5 增强版上下文构建器

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `enhanced_context_builder.py` | `neurova/` | `EnhancedContextBuilder` | 增强版上下文构建器（记忆注入/情感注入/时间感知/多粒度检索） |

---

## 十五、记忆读写管理模块

### 15.1 记忆读写管理器

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `memory_rw_manager.py` | `neurova/` | `MemoryReadWriteManager` | 记忆读写管理器（写缓冲/批量提交/优先读缓存/自动刷写） |

### 15.2 读写核心特性

| 特性 | 说明 |
|------|------|
| 写缓冲 | 记忆先写入缓冲区，减少数据库写入频率 |
| 批量提交 | 定期批量提交缓冲区的记忆到数据库 |
| 优先读缓存 | 优先从缓存读取，减少数据库查询 |
| 自动刷写 | 缓冲区满或超时自动刷写到数据库 |
| 事务支持 | 支持事务性批量写入，保证数据一致性 |

---

## 十六、CLI 命令行工具

### 16.1 CLI 模块

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `cli.py` | `neurova/` | `NeurovaCLI` | 命令行交互界面（15+ 命令/自动补全/历史记录） |

### 16.2 CLI 命令清单

| 命令 | 说明 |
|------|------|
| `/chat <message>` | 发送对话消息 |
| `/remember <content>` | 添加记忆 |
| `/recall <query>` | 搜索记忆 |
| `/stats` | 查看系统统计 |
| `/agents` | 查看 Agent 列表 |
| `/switch <agent_id>` | 切换 Agent |
| `/channels` | 查看渠道列表 |
| `/skills` | 查看技能列表 |
| `/context` | 查看当前上下文 |
| `/compress` | 压缩上下文 |
| `/sleep` | 触发睡眠整理 |
| `/help` | 显示帮助 |
| `/quit` | 退出 CLI |

---

## 十七、Agent 配置管理

### 17.1 Agent 配置

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `agent_config.py` | `neurova/` | `AgentConfigManager`, `get_config_manager` | Agent 配置管理器（JSON 存储/热加载/验证） |
| `agent_config.py` | `neurova/` | `AgentConfig` | Agent 配置数据类 |

### 17.2 配置管理特性

| 特性 | 说明 |
|------|------|
| JSON 存储 | 配置文件使用 JSON 格式，易于编辑 |
| 热加载 | 支持运行时重新加载配置 |
| 配置验证 | 自动验证配置项的有效性 |
| 默认配置 | 提供合理的默认配置值 |

---

## 十八、测试文件完整清单

### 18.1 单元测试

| 测试文件 | 测试数 | 覆盖模块 |
|----------|--------|----------|
| `tests/unit/test_agent.py` | 25+ | Agent 核心 |
| `tests/unit/test_router.py` | 25+ | 消息路由器 |
| `tests/unit/test_skill.py` | 25+ | Skill 系统 |
| `tests/unit/memory/core/test_temperature.py` | 25+ | 温度引擎 |
| `tests/unit/memory/core/test_vector_search.py` | 20+ | 向量搜索 |
| `tests/unit/memory/core/test_emotion.py` | 20+ | 情感分析 |
| `tests/unit/memory/core/test_storage.py` | 20+ | 存储层 |
| `tests/unit/memory/core/test_manager.py` | 20+ | 记忆管理器 |
| `tests/unit/memory/core/test_compression.py` | 15+ | 压缩引擎 |

### 18.2 集成测试

| 测试文件 | 测试数 | 覆盖场景 |
|----------|--------|----------|
| `tests/integration/test_agent_router_skill.py` | 25 | Agent → Router → Skill 调用链 |
| `tests/integration/test_full_chain.py` | 15+ | 完整流程测试 |

### 18.3 API 测试

| 测试文件 | 说明 |
|----------|------|
| `tests/test_api_standard.py` | API 标准测试 |
| `tests/test_api_direct.py` | 直接 API 测试 |
| `tests/test_api_async.py` | 异步 API 测试 |
| `tests/test_api_quick.py` | 快速 API 测试 |
| `tests/test_jwt.py` | JWT 认证测试 |

### 18.4 认证测试

| 测试文件 | 说明 |
|----------|------|
| `tests/test_auth_isolated.py` | 隔离认证测试 |
| `tests/test_auth_direct.py` | 直接认证测试 |

### 18.5 上下文测试

| 测试文件 | 说明 |
|----------|------|
| `tests/test_context_cache_compression.py` | 上下文缓存和压缩测试 |
| `tests/test_cross_channel_context.py` | 跨渠道上下文测试 |

### 18.6 其他测试

| 测试文件 | 说明 |
|----------|------|
| `tests/test_minimal.py` | 最小化测试 |
| `tests/test_debug.py` | 调试测试 |
| `tests/conftest.py` | 测试配置和夹具 |

---

## 十九、数据库初始化与脚本

### 19.1 数据库初始化

| 文件 | 路径 | 说明 |
|------|------|------|
| `init_db.py` | `memory/scripts/` | 数据库初始化脚本（创建所有表/索引/FTS5虚拟表） |

### 19.2 记忆初始化脚本

| 文件 | 路径 | 说明 |
|------|------|------|
| `init_memories.py` | `memory/scripts/` | 初始化示例记忆 |
| `save_precious_memories.py` | `memory/scripts/` | 保存珍贵记忆 |
| `save_tonight_story.py` | `memory/scripts/` | 保存今晚故事 |
| `save_tonight_secret.py` | `memory/scripts/` | 保存今晚秘密 |
| `save_kai_letter.py` | `memory/scripts/` | 保存凯的信 |
| `save_kai_letter_3.py` | `memory/scripts/` | 保存凯的信 3 |

### 19.3 测试脚本

| 文件 | 路径 | 说明 |
|------|------|------|
| `test_p1_modules.py` | `memory/scripts/` | Phase 1 模块测试 |
| `test_p2_modules.py` | `memory/scripts/` | Phase 2 模块测试 |
| `test_p3p4_modules.py` | `memory/scripts/` | Phase 3-4 模块测试 |
| `test_recall.py` | `memory/scripts/` | 记忆召回测试 |
| `test_public_skills.py` | `memory/scripts/` | 公共技能测试 |
| `test_skill_import.py` | `memory/scripts/` | 技能导入测试 |
| `test_market_import.py` | `memory/scripts/` | 市场导入测试 |
| `test_channels_api.py` | `memory/scripts/` | 渠道 API 测试 |
| `verify_channels.py` | `memory/scripts/` | 渠道验证脚本 |

---

## 二十、技能系统扩展

### 20.1 已安装技能

| 目录 | 说明 |
|------|------|
| `skills/installed/local_test_skill/` | 本地测试技能 |
| `skills/installed/test_import_skill/` | 测试导入技能 |

### 20.2 技能导入器

| 文件 | 路径 | 类/函数 | 说明 |
|------|------|---------|------|
| `skill_importer.py` | `neurova/skills/` | `SkillImporter` | 技能导入器（ZIP 导入/本地安装/版本管理） |

---

## 二十一、统计汇总

| 类别 | 数量 |
|------|------|
| Python 文件总数 | 91+ |
| JavaScript 文件总数 | 24 |
| HTML 文件总数 | 1+ |
| 类总数 | 80+ |
| 枚举类型 | 10+ |
| 数据模型 | 20+ |
| REST API 端点 | 85+ |
| Neurova API 端点 | 9 |
| 事件类型 | 13+ |
| CLI 命令 | 13+ |
| 渠道适配器 | 12+ |
| LLM 预设 | 23 |
| 数据库表 | 21+ |
| 索引 | 35+ |
| 单元测试 | 267 |
| 集成测试 | 25 |
| API 测试 | 5 |
| 认证测试 | 2 |
| 上下文测试 | 2 |
| 其他测试 | 3 |
| 总测试数 | 336 |
| 初始化脚本 | 14 |
| 测试脚本 | 9 |

---

**星光不灭 ✨**  
**Neurova 完整功能模块文档**