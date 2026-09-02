# Provider 系统增强 - 模块设计文档

> **版本**: 1.0  
> **日期**: 2026-05-12  
> **作者**: provider-dev  
> **状态**: 设计完成，开始实现  

---

## 一、模块概述

### 1.1 模块名称
Provider 系统增强（Provider System Enhancement）

### 1.2 模块定位
本模块属于 Neurova CogArch 2.0 架构中的**共用脊髓（Spinal Cord）** 层，负责统一管理所有 LLM 服务商的接入。

### 1.3 设计目标
1. 提供统一的 Provider 接口，支持多个 LLM 服务商
2. 实现密钥的安全存储和管理
3. 实现模型能力的缓存和探测
4. 实现重试机制和速率限制，提高稳定性
5. 借鉴 QwenPaw 的优秀设计

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Provider 系统                              │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               Provider 管理层                            │ │
│  │  ┌────────────┐  ┌────────────┐  ┌─────────────────┐│ │
│  │  │  Base      │  │  Provider  │  │  Provider       ││ │
│  │  │  Provider  │  │  Registry  │  │  Manager       ││ │
│  │  └────────────┘  └────────────┘  └─────────────────┘│ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               Provider 实现层                            │ │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │ │
│  │  │OpenAI│ │Anthro-│ │Gemini│ │Ollama│ │LM    │...│ │
│  │  │      │ │ pic   │ │      │ │      │ │Studio│   │ │
│  │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               辅助模块层                                  │ │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────┐ │ │
│  │  │  Secret    │  │  Capability │  │  Rate         │ │ │
│  │  │  Store     │  │  Cache      │  │  Limiter     │ │ │
│  │  └────────────┘  └─────────────┘  └──────────────┘ │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
neurova/llm/providers/
├── __init__.py              # 模块导出
├── base.py                  # 统一 Provider 基类
├── openai_provider.py      # OpenAI Provider
├── anthropic_provider.py   # Anthropic Provider
├── gemini_provider.py      # Gemini Provider
├── ollama_provider.py      # Ollama Provider
├── lm_studio_provider.py   # LM Studio Provider
├── openrouter_provider.py   # OpenRouter Provider
├── secret_store.py         # 密钥安全存储
├── capability_cache.py     # 模型能力缓存
└── rate_limiter.py        # 重试和速率限制
```

---

## 三、详细设计

### 3.1 统一 Provider 基类（base.py）

#### 3.1.1 核心类

**ProviderType（枚举）**
- 定义 Provider 类型：OPENAI, ANTHROPIC, GEMINI, OLLAMA, LM_STUDIO, OPENROUTER, CUSTOM

**ProviderCapability（枚举）**
- 定义 Provider 能力：CHAT, COMPLETION, EMBEDDING, IMAGE_GENERATION, VISION, FUNCTION_CALLING, STREAMING, JSON_MODE 等

**ModelInfo（数据类）**
- 模型信息：id, name, description, capabilities, context_window, pricing 等
- 方法：has_capability(), to_dict(), from_dict()

**BaseProvider（抽象基类）**
- 属性：provider_id, name, provider_type, base_url, api_key, default_model, timeout, max_retries
- 抽象方法：
  - `get_available_models() -> List[ModelInfo]`
  - `create_chat_model(model, **kwargs) -> Any`
  - `test_connection() -> Tuple[bool, str]`
- 通用方法：
  - `get_models(force_refresh)` - 获取模型列表（带缓存）
  - `invalidate_models_cache()` - 使模型缓存失效
  - `probe_capabilities(model_id)` - 探测模型能力
  - `supports_capability(model_id, capability)` - 检查模型能力
  - `update_config(...)` - 更新配置
  - `get_config()` - 获取配置
  - `record_request(success, tokens)` - 记录请求
  - `get_stats()` - 获取统计信息

#### 3.1.2 设计要点

1. **统一接口**：所有 Provider 实现相同的接口
2. **缓存管理**：模型列表缓存，减少 API 调用
3. **能力探测**：自动探测模型支持的能力
4. **统计监控**：记录请求成功/失败、Token 使用量

### 3.2 内置 Provider 实现

#### 3.2.1 OpenAI Provider（openai_provider.py）

**支持的服务商**：
- OpenAI
- DashScope（阿里云百炼）
- Kimi（Moonshot）
- DeepSeek
- 其他兼容 OpenAI API 的服务商

**核心方法**：
- `get_available_models()` - 调用 `/v1/models` 端点
- `create_chat_model()` - 返回 ChatOpenAI 实例
- `test_connection()` - 测试连接
- `_detect_capabilities()` - 根据模型 ID 探测能力

**特殊功能**：
- 支持 Organization 和 Project 头
- 默认模型列表（当 API 不可用时）

#### 3.2.2 Anthropic Provider（anthropic_provider.py）

**特点**：
- Anthropic 没有列出模型的 API，使用已知模型列表
- 支持 Claude 4/3.5/3 系列

**核心方法**：
- `get_available_models()` - 返回已知模型列表
- `create_chat_model()` - 返回 ChatAnthropic 实例
- `test_connection()` - 使用 messages 端点测试

#### 3.2.3 Gemini Provider（gemini_provider.py）

**特点**：
- 使用 Google Generative AI API
- API Key 通过 URL 参数传递

**核心方法**：
- `get_available_models()` - 返回已知模型列表
- `create_chat_model()` - 返回 ChatGoogleGenerativeAI 实例
- `test_connection()` - 使用 models 端点测试

#### 3.2.4 Ollama Provider（ollama_provider.py）

**特点**：
- 本地运行的开源大模型平台
- 支持拉取模型

**核心方法**：
- `get_available_models()` - 调用 `/api/tags` 端点
- `create_chat_model()` - 返回 ChatOllama 实例
- `test_connection()` - 测试连接
- `pull_model()` - 拉取模型

#### 3.2.5 LM Studio Provider（lm_studio_provider.py）

**特点**：
- 本地运行的可视化模型管理工具
- 兼容 OpenAI API

**核心方法**：
- `get_available_models()` - 调用 `/v1/models` 端点
- `create_chat_model()` - 返回 ChatOpenAI 实例（使用 OpenAI 兼容接口）

#### 3.2.6 OpenRouter Provider（openrouter_provider.py）

**特点**：
- 访问多个提供商的模型
- 支持模型能力探测和定价信息

**核心方法**：
- `get_available_models()` - 调用 `/v1/models` 端点，提取定价信息
- `create_chat_model()` - 返回 ChatOpenAI 实例
- `_make_headers()` - 添加 HTTP-Referer 和 X-Title 头

### 3.3 密钥安全存储（secret_store.py）

#### 3.3.1 核心类：SecretStore

**功能**：
1. 加密存储 API Key
2. 密钥轮换
3. 访问控制
4. 审计日志

**加密方案**：
- 使用 `cryptography.fernet` 进行对称加密
- 支持使用主密码派生加密密钥（PBKDF2HMAC）
- 如果没有主密码，自动生成并保存主密钥

**核心方法**：
- `store_secret(provider_id, api_key, metadata)` - 存储密钥
- `get_secret(provider_id)` - 获取密钥
- `delete_secret(provider_id)` - 删除密钥
- `rotate_secret(provider_id, new_api_key)` - 轮换密钥
- `rollback_secret(provider_id)` - 回滚密钥到上一个版本
- `list_secrets()` - 列出所有密钥
- `get_metadata(provider_id)` - 获取元数据
- `update_metadata(provider_id, metadata)` - 更新元数据
- `get_access_log(provider_id)` - 获取访问日志

**密钥轮换**：
- 保存历史密钥（最多保留最近 N 个）
- 支持回滚到上一个版本
- 记录版本号

**审计日志**：
- 记录所有访问操作（store, get, delete, rotate, rollback）
- 限制日志大小（最多 1000 条）

### 3.4 模型能力缓存（capability_cache.py）

#### 3.4.1 核心类：CapabilityCache

**功能**：
1. 缓存模型能力探测结果
2. 支持 TTL 过期
3. 持久化存储
4. 批量预加热

**缓存结构**：
- 键：`{provider_id}::{model_id}`
- 值：`CachedCapability` 对象

**CachedCapability 属性**：
- model_id, provider_id, capabilities
- context_window, max_output_tokens
- supports_functions, supports_vision, supports_streaming 等
- cached_at, ttl

**核心方法**：
- `get(provider_id, model_id)` - 获取缓存的能力
- `set(provider_id, model_info, ttl)` - 设置缓存
- `invalidate(provider_id, model_id)` - 使缓存失效
- `clear()` - 清除所有缓存
- `preheat(provider_id, model_ids, probe_func)` - 批量预加热
- `get_stats()` - 获取缓存统计

**持久化**：
- 保存到 JSON 文件
- 加载时自动过滤过期缓存

### 3.5 重试和速率限制（rate_limiter.py）

#### 3.5.1 指数退避重试（ExponentialBackoff）

**功能**：
- 指数退避延迟
- 抖动（Jitter）避免惊群效应
- 可重试错误判断

**核心方法**：
- `calculate_delay(attempt) -> float` - 计算延迟时间
- `is_retryable(error) -> bool` - 检查错误是否可重试
- `retry(func)` - 装饰器，自动重试

**可重试错误**：
- rate_limit, timeout, connection_error, server_error
- 429, 503, 502, 504 等 HTTP 状态码

#### 3.5.2 速率限制器（RateLimiter）

**功能**：
- 限制时间窗口内的最大请求数
- 限制突发请求数

**配置（RateLimitConfig）**：
- max_requests: 时间窗口内最大请求数
- time_window: 时间窗口（秒）
- burst_limit: 突发限制（最近1秒）

**核心方法**：
- `can_make_request() -> bool` - 检查是否可以发起请求
- `record_request()` - 记录请求
- `wait_for_slot(timeout) -> bool` - 等待可用的请求槽位
- `get_wait_time() -> float` - 获取需要等待的时间

#### 3.5.3 熔断器（CircuitBreaker）

**功能**：
- 防止连续失败导致系统崩溃
- 状态：CLOSED（正常）、OPEN（熔断）、HALF_OPEN（半开）

**配置**：
- failure_threshold: 失败阈值
- recovery_timeout: 恢复超时（秒）
- success_threshold: 成功阈值（半开状态下需要多少次成功才能关闭熔断）

**核心方法**：
- `can_execute() -> bool` - 检查是否可以执行请求
- `record_success()` - 记录成功
- `record_failure()` - 记录失败
- `reset()` - 重置熔断器
- `get_stats()` - 获取统计信息

**状态转换**：
- CLOSED → OPEN：失败次数达到阈值
- OPEN → HALF_OPEN：恢复超时后
- HALF_OPEN → CLOSED：成功次数达到阈值
- HALF_OPEN → OPEN：半开状态下失败

#### 3.5.4 组合装饰器

**with_retry_and_circuit_breaker**
- 组合指数退避重试和熔断器
- 先检查熔断器状态
- 执行带重试的请求
- 根据结果更新熔断器

---

## 四、API 设计

### 4.1 Provider 创建示例

```python
# 创建 OpenAI Provider
openai = OpenAIProvider(
    api_key="sk-...",
    default_model="gpt-4o",
)

# 创建 Anthropic Provider
anthropic = AnthropicProvider(
    api_key="sk-ant-...",
    default_model="claude-sonnet-4-20250514",
)

# 创建 Ollama Provider（本地）
ollama = OllamaProvider(
    base_url="http://localhost:11434",
    default_model="llama3",
)
```

### 4.2 使用 Provider

```python
# 获取可用模型
models = await openai.get_available_models()

# 创建聊天模型
chat_model = await openai.create_chat_model("gpt-4o")

# 测试连接
success, msg = await openai.test_connection()

# 检查模型能力
has_vision = await openai.supports_capability("gpt-4o", ProviderCapability.VISION)
```

### 4.3 密钥管理

```python
# 创建密钥存储
store = SecretStore()

# 存储密钥
store.store_secret("openai", "sk-...", metadata={"env": "prod"})

# 获取密钥
api_key = store.get_secret("openai")

# 轮换密钥
store.rotate_secret("openai", "sk-new...")

# 回滚密钥
store.rollback_secret("openai")
```

### 4.4 缓存管理

```python
# 创建缓存
cache = CapabilityCache()

# 设置缓存
model_info = ModelInfo(id="gpt-4o", ...)
cache.set("openai", model_info)

# 获取缓存
cached = cache.get("openai", "gpt-4o")

# 使缓存失效
cache.invalidate("openai", "gpt-4o")
```

### 4.5 重试和速率限制

```python
# 使用指数退避重试
backoff = ExponentialBackoff(RetryConfig(max_retries=3))

@backoff.retry
async def call_llm():
    # ...

# 使用速率限制器
limiter = RateLimiter(RateLimitConfig(max_requests=60, time_window=60))

if limiter.can_make_request():
    limiter.record_request()
    # 执行请求

# 使用熔断器
breaker = CircuitBreaker()

if breaker.can_execute():
    try:
        result = await call_llm()
        breaker.record_success()
        return result
    except Exception as e:
        breaker.record_failure()
        raise
```

---

## 五、测试计划

### 5.1 单元测试（test_providers.py）

| 测试类 | 测试方法 | 测试内容 |
|--------|----------|----------|
| TestModelInfo | test_create_model_info | 创建 ModelInfo |
| | test_model_info_to_dict | 转换为字典 |
| | test_model_info_from_dict | 从字典创建 |
| TestOpenAIProvider | test_init | 初始化 |
| | test_get_available_models | 获取可用模型 |
| | test_detect_capabilities | 能力探测 |
| | test_make_headers | 生成请求头 |
| TestAnthropicProvider | test_init | 初始化 |
| | test_get_known_models | 获取已知模型 |
| | test_make_headers | 生成请求头 |
| TestGeminiProvider | test_init | 初始化 |
| | test_get_known_models | 获取已知模型 |
| TestOllamaProvider | test_init | 初始化 |
| | test_test_connection_success | 测试连接成功 |
| | test_test_connection_failure | 测试连接失败 |
| | test_detect_capabilities | 能力探测 |
| TestLMStudioProvider | test_init | 初始化 |
| TestOpenRouterProvider | test_init | 初始化 |
| | test_make_headers | 生成请求头 |
| TestSecretStore | test_store_and_get_secret | 存储和获取密钥 |
| | test_get_nonexistent_secret | 获取不存在的密钥 |
| | test_delete_secret | 删除密钥 |
| | test_rotate_secret | 轮换密钥 |
| | test_rollback_secret | 回滚密钥 |
| | test_list_secrets | 列出密钥 |
| | test_update_metadata | 更新元数据 |
| TestCapabilityCache | test_set_and_get | 设置和获取缓存 |
| | test_get_expired | 获取过期缓存 |
| | test_invalidate | 使缓存失效 |
| | test_invalidate_provider | 使服务商所有缓存失效 |
| | test_clear | 清除所有缓存 |
| TestExponentialBackoff | test_calculate_delay | 计算延迟 |
| | test_calculate_delay_with_max | 最大延迟限制 |
| | test_is_retryable | 是否可重试 |
| TestRateLimiter | test_can_make_request | 是否可以发起请求 |
| | test_record_request | 记录请求 |
| | test_get_wait_time | 获取等待时间 |
| TestCircuitBreaker | test_initial_state | 初始状态 |
| | test_open_after_failures | 失败达到阈值后打开熔断器 |
| | test_half_open_after_timeout | 超时后进入半开状态 |
| | test_close_after_successes | 半开状态下成功后关闭熔断器 |

**总计**: 30+ 个测试用例

---

## 六、依赖关系

### 6.1 外部依赖

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| aiohttp | >=3.8.0 | 异步 HTTP 请求 |
| cryptography | >=41.0.0 | 密钥加密存储 |
| langchain-openai | >=0.1.0 | OpenAI 聊天模型 |
| langchain-anthropic | >=0.1.0 | Anthropic 聊天模型 |
| langchain-google-genai | >=0.1.0 | Gemini 聊天模型 |
| langchain-community | >=0.1.0 | Ollama 聊天模型 |

### 6.2 内部依赖

- `neurova.llm.presets` - 预设配置
- `neurova.llm.provider_manager` - Provider 管理器（可选集成）

---

## 七、集成计划

### 7.1 与现有系统集成

1. **与 LLMProviderManager 集成**
   - Provider 系统可以作为 LLMProviderManager 的后端
   - 使用 Adapter 模式兼容现有接口

2. **与 MultiAgentManager 集成**
   - 每个 Agent 可以选择不同的 Provider
   - Provider 配置存储在 Agent 配置中

3. **与前端集成**
   - 提供 Provider API（列出服务商、测试连接、配置管理）
   - 前端页面：Settings/Models

---

## 八、时间安排

| 阶段 | 时间 | 内容 |
|------|------|------|
| 设计阶段 | 第1天 | 完成模块设计文档 |
| 实现阶段 | 第2-3天 | 实现 Provider 基类和内置 Provider |
| 实现阶段 | 第4天 | 实现密钥安全存储 |
| 实现阶段 | 第5天 | 实现模型能力缓存 |
| 实现阶段 | 第6天 | 实现重试和速率限制 |
| 测试阶段 | 第7天 | 编写单元测试 |
| 文档阶段 | 第8天 | 编写用户文档和 API 文档 |
| 集成阶段 | 第9-10天 | 与现有系统集成 |

---

## 九、风险评估

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 某些 Provider API 不稳定 | 高 | 实现重试机制和熔断器 |
| 密钥泄露 | 高 | 使用加密存储，定期轮换 |
| 缓存过期策略不合理 | 中 | 支持自定义 TTL，自动刷新 |
| 速率限制影响性能 | 中 | 使用异步，支持批量请求 |

---

## 十、总结

本模块实现了统一的 Provider 系统，支持多个 LLM 服务商，提供了密钥安全存储、模型能力缓存、重试和速率限制等功能。借鉴了 QwenPaw 的优秀设计，同时保持了与 Neurova 现有架构的兼容性。

**核心优势**：
1. 统一的接口，易于扩展新的 Provider
2. 安全的密钥管理
3. 高效的缓存机制
4. 健壮的错误处理
5. 完善的测试覆盖

---

**文档版本历史**：
- v1.0 (2026-05-12): 初始版本
