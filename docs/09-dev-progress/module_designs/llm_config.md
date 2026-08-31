# LLM 配置与渠道管理模块设计文档

## 1. 功能描述

本模块实现 Neurova 系统的 LLM（大语言模型）配置与渠道管理功能，包括：

1. **LLM Provider Manager（LLM 提供商管理器）**
   - 提供商注册、配置管理
   - 负载均衡（支持多种策略：轮询、加权随机、优先级优先、最少错误、最快响应）
   - 故障转移（自动切换到备用提供商）
   - 健康检查与状态管理

2. **Channel Manager（渠道管理器）**
   - 多渠道支持（飞书、钉钉、微信、Telegram、Discord、QQ 等）
   - 消息路由（统一消息模型，跨渠道身份关联）
   - 渠道优先级管理
   - 健康状态跟踪

3. **LLM Configuration Console（LLM 配置控制台）**
   - LLM 提供商配置界面 API
   - 模型选择与管理
   - 参数调优（temperature, top_p, max_tokens 等）
   - Token 使用统计

4. **API 接口**
   - LLM 提供商配置 API
   - 渠道管理 API
   - 模型调用 API
   - 使用统计 API

## 2. 架构设计

### 2.1 类设计

#### 2.1.1 LLM Provider Manager（`neurova/llm/provider_manager.py`）

```python
class LoadBalancingStrategy(str, Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"       # 轮询
    WEIGHTED_RANDOM = "weighted_random"  # 加权随机
    PRIORITY_FIRST = "priority_first"    # 优先级优先
    LEAST_ERRORS = "least_errors"      # 最少错误
    FASTEST_RESPONSE = "fastest_response"  # 最快响应

@dataclass
class ProviderConfig:
    """服务商配置"""
    id: str
    name: str
    provider: str
    base_url: str
    api_key: str = ""
    default_model: str = ""
    models: List[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 0
    is_builtin: bool = False
    icon: str = ""
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 健康检查和故障转移
    health_check_enabled: bool = True
    health_check_interval: int = 300  # 秒
    last_health_check: Optional[str] = None
    health_status: str = "unknown"  # unknown, healthy, degraded, failed
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    # 负载均衡
    weight: int = 100  # 权重 (0-100)
    current_requests: int = 0  # 当前请求数
    total_response_time: float = 0.0  # 总响应时间
    total_requests: int = 0  # 总请求数

class LLMProviderManager:
    """LLM 服务商配置管理器（单例模式）"""
    
    def add_provider(self, name: str, provider: str, base_url: str, 
                    api_key: str = "", default_model: str = "",
                    models: Optional[List[str]] = None,
                    priority: int = 0, icon: str = "",
                    description: str = "", 
                    metadata: Optional[Dict[str, Any]] = None) -> ProviderConfig:
        """添加自定义服务商"""
    
    def update_provider(self, provider_id: str, **kwargs) -> Optional[ProviderConfig]:
        """更新服务商配置"""
    
    def remove_provider(self, provider_id: str) -> bool:
        """删除服务商"""
    
    def health_check_provider(self, provider_id: str) -> bool:
        """检查服务商健康状态"""
    
    def mark_provider_success(self, provider_id: str, response_time: float = 0.0):
        """标记服务商请求成功"""
    
    def mark_provider_failure(self, provider_id: str):
        """标记服务商请求失败"""
    
    def get_healthy_providers(
        self, 
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST
    ) -> List[ProviderConfig]:
        """获取健康的服务商列表（按负载均衡策略排序）"""
    
    def select_provider(
        self, 
        model: Optional[str] = None,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST
    ) -> Optional[ProviderConfig]:
        """选择最佳服务商（支持负载均衡）"""
    
    def auto_failover(self, current_provider_id: str) -> Optional[ProviderConfig]:
        """自动故障转移到其他健康服务商"""
```

#### 2.1.2 MultiModel LLM Client（`neurova/llm/multi_model_client.py`）

```python
class ModelClient:
    """单个模型的客户端封装"""
    
    def __init__(self, client: LLMClient, provider: ProviderConfig, model: str):
        self.client = client
        self.provider = provider
        self.model = model
        self.request_count = 0
        self.error_count = 0
        self.last_used: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        """计算成功率"""

class MultiModelLLMClient:
    """多模型 LLM 客户端管理器（单例模式）"""
    
    def __init__(
        self, 
        provider_manager: Optional[LLMProviderManager] = None,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST
    ):
        """初始化多模型客户端"""
    
    def set_active_model(self, provider_id: str, model: str) -> bool:
        """设置当前活跃模型"""
    
    def get_current_client(self) -> Optional[ModelClient]:
        """获取当前活跃的客户端"""
    
    def chat(self, messages: List[Dict[str, str]], 
             model: Optional[str] = None,
             provider_id: Optional[str] = None, **kwargs) -> Any:
        """发送聊天请求（集成健康检查和故障转移）"""
    
    def chat_stream(self, messages: List[Dict[str, str]], 
                   model: Optional[str] = None,
                   provider_id: Optional[str] = None, **kwargs):
        """发送流式聊天请求（集成健康检查和故障转移）"""
    
    def list_available_models(self) -> List[Dict[str, Any]]:
        """列出所有可用的模型"""
    
    def refresh_provider(self, provider_id: str) -> bool:
        """刷新服务商的客户端"""
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
```

#### 2.1.3 LLM Config Console（`neurova/llm/config_console.py`）

```python
class LLMConfigConsole:
    """LLM 配置控制台"""
    
    def __init__(
        self,
        provider_manager: Optional[LLMProviderManager] = None,
        multi_model_client: Optional[MultiModelLLMClient] = None,
        config_path: Optional[str] = None,
    ):
        """初始化 LLM 配置控制台"""
    
    # 提供商配置 API
    def list_providers(self, enabled_only: bool = False, 
                       healthy_only: bool = False) -> List[Dict[str, Any]]:
        """列出所有提供商"""
    
    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """获取提供商配置"""
    
    def add_provider(self, name: str, provider: str, base_url: str, 
                     **kwargs) -> Dict[str, Any]:
        """添加自定义提供商"""
    
    def update_provider(self, provider_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """更新提供商配置"""
    
    def remove_provider(self, provider_id: str) -> bool:
        """删除提供商"""
    
    def test_provider_connection(self, provider_id: str) -> Dict[str, Any]:
        """测试提供商连接"""
    
    def set_default_provider(self, provider_id: str) -> bool:
        """设置默认提供商"""
    
    # 模型选择与管理
    def list_models(self, provider_id: Optional[str] = None, 
                    enabled_only: bool = False) -> List[Dict[str, Any]]:
        """列出所有模型"""
    
    def get_model_info(self, provider_id: str, model: str) -> Optional[Dict[str, Any]]:
        """获取模型信息"""
    
    def select_model(
        self, 
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST,
    ) -> Optional[Dict[str, Any]]:
        """选择模型（支持负载均衡）"""
    
    # 参数调优
    def get_default_params(self) -> Dict[str, Any]:
        """获取全局默认参数"""
    
    def update_default_params(self, **kwargs) -> Dict[str, Any]:
        """更新全局默认参数"""
    
    def get_provider_params(self, provider_id: str) -> Dict[str, Any]:
        """获取提供商参数配置"""
    
    def update_provider_params(self, provider_id: str, **kwargs) -> Dict[str, Any]:
        """更新提供商参数配置"""
    
    # Token 使用统计
    def record_token_usage(self, provider_id: str, model: str, 
                           input_tokens: int, output_tokens: int, 
                           cost: Optional[float] = None):
        """记录 Token 使用量"""
    
    def get_token_usage(self, provider_id: Optional[str] = None, 
                        model: Optional[str] = None,
                        start_date: Optional[datetime] = None,
                        end_date: Optional[datetime] = None) -> Dict[str, Any]:
        """获取 Token 使用统计"""
    
    def get_token_usage_summary(self, days: int = 7) -> Dict[str, Any]:
        """获取 Token 使用摘要（最近 N 天）"""
```

#### 2.1.4 Channel Manager（`neurova/channels/manager.py`）

```python
class ChannelManager:
    """消息渠道管理器"""
    
    def __init__(self, config_path: str = "data/channels.json", 
                 default_agent_id: str = "default"):
        """初始化渠道管理器"""
    
    # 渠道配置管理
    def add_channel(self, config: ChannelConfig) -> bool:
        """添加渠道配置"""
    
    def remove_channel(self, channel: MessageChannel) -> bool:
        """移除渠道"""
    
    def update_channel_config(self, channel: MessageChannel, 
                            config_updates: Dict) -> bool:
        """更新渠道配置"""
    
    def enable_channel(self, channel: MessageChannel) -> bool:
        """启用渠道"""
    
    def disable_channel(self, channel: MessageChannel) -> bool:
        """禁用渠道"""
    
    # 渠道优先级管理
    def set_channel_priority(self, channel: MessageChannel, priority: int) -> bool:
        """设置渠道优先级"""
    
    def get_channels_by_priority(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """按优先级获取渠道列表"""
    
    def get_preferred_channel(self, agent_id: str = None) -> Optional[MessageChannel]:
        """获取首选渠道（优先级最高且健康的）"""
    
    # 渠道健康状态管理
    def mark_channel_success(self, channel: MessageChannel, 
                            response_time: float = 0.0):
        """标记渠道请求成功"""
    
    def mark_channel_failure(self, channel: MessageChannel):
        """标记渠道请求失败"""
    
    def update_channel_health(self, channel: MessageChannel, success: bool, 
                               response_time: float = 0.0):
        """更新渠道健康状态"""
    
    def check_channel_health(self, channel: MessageChannel) -> bool:
        """检查渠道健康状态"""
    
    # 消息处理
    def process_incoming_message(self, raw_data: Any, 
                                 channel: MessageChannel,
                                 agent_id: str = None) -> bool:
        """处理收到的消息（集成健康状态跟踪）"""
    
    def send_message(self, channel: MessageChannel, chat_id: str, 
                     content: str, agent_id: str = "") -> bool:
        """发送消息到指定渠道（集成健康状态跟踪）"""
    
    def send_message_auto_channel(self, chat_id: str, content: str, 
                                 agent_id: str = "") -> Optional[MessageChannel]:
        """自动选择最优渠道发送消息"""
```

### 2.2 数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM 配置与渠道管理模块                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────────┐    ┌─────────────────────┐           │
│  │  LLM Provider      │    │  Channel Manager    │           │
│  │  Manager           │    │                     │           │
│  │  - 提供商注册      │    │  - 渠道配置        │           │
│  │  - 负载均衡        │    │  - 消息路由        │           │
│  │  - 故障转移        │    │  - 优先级管理      │           │
│  │  - 健康检查        │    │  - 健康状态        │           │
│  └─────────────────────┘    └─────────────────────┘           │
│               ↓                        ↓                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            MultiModelLLMClient                         │   │
│  │            - 多模型管理                               │   │
│  │            - 请求路由                                 │   │
│  │            - 健康状态集成                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│               ↓                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            LLMConfigConsole                            │   │
│  │            - 提供商配置 API                          │   │
│  │            - 模型选择与管理                          │   │
│  │            - 参数调优                                 │   │
│  │            - Token 使用统计                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│               ↓                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            API Endpoints                              │   │
│  │            - /api/v1/providers                      │   │
│  │            - /api/v1/models                         │   │
│  │            - /api/v1/channels                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 接口设计

### 3.1 API 接口

#### 3.1.1 LLM 提供商管理 API（`/api/v1/providers`）

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/api/v1/providers` | 获取提供商列表 | `enabled_only`, `builtin_only`, `custom_only` | 提供商列表 |
| GET | `/api/v1/providers/stats` | 获取统计信息 | - | 统计信息 |
| GET | `/api/v1/providers/search?q=xxx` | 搜索提供商 | `q` | 搜索结果 |
| GET | `/api/v1/providers/default` | 获取默认提供商 | - | 默认提供商 |
| GET | `/api/v1/providers/{provider_id}` | 获取提供商详情 | - | 提供商详情 |
| GET | `/api/v1/providers/{provider_id}/models` | 获取模型列表 | - | 模型列表 |
| POST | `/api/v1/providers` | 添加提供商 | `ProviderAddRequest` | 添加结果 |
| PUT | `/api/v1/providers/{provider_id}` | 更新提供商 | `ProviderUpdateRequest` | 更新结果 |
| DELETE | `/api/v1/providers/{provider_id}` | 删除提供商 | - | 删除结果 |
| POST | `/api/v1/providers/{provider_id}/default` | 设为默认 | - | 设置结果 |
| POST | `/api/v1/providers/{provider_id}/enable` | 启用/禁用 | `enabled` | 设置结果 |
| POST | `/api/v1/providers/{provider_id}/test` | 测试连接 | - | 测试结果 |
| POST | `/api/v1/providers/health-check` | 批量健康检查 | - | 检查结果 |
| GET | `/api/v1/providers/token-usage` | Token 使用统计 | `provider_id`, `days` | 统计结果 |
| GET | `/api/v1/providers/{provider_id}/params` | 获取参数 | - | 参数配置 |
| PUT | `/api/v1/providers/{provider_id}/params` | 更新参数 | `temperature`, `top_p`, etc. | 更新结果 |
| POST | `/api/v1/providers/{provider_id}/params/reset` | 重置参数 | - | 重置结果 |
| POST | `/api/v1/providers/reset` | 重置为内置 | - | 重置结果 |
| GET | `/api/v1/providers/export/config` | 导出配置 | - | 配置 JSON |
| POST | `/api/v1/providers/import/config` | 导入配置 | `config` | 导入结果 |

#### 3.1.2 LLM 模型管理 API（`/api/v1/models`）

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/api/v1/models` | 获取模型列表 | - | 模型列表 |
| GET | `/api/v1/models/current` | 获取当前模型 | - | 当前模型 |
| POST | `/api/v1/models/switch` | 切换模型 | `ModelSwitchRequest` | 切换结果 |
| POST | `/api/v1/models/select` | 选择模型（负载均衡） | `model`, `provider_id`, `strategy` | 选择结果 |
| GET | `/api/v1/models/{provider_id}/{model}` | 获取模型详情 | - | 模型详情 |
| GET | `/api/v1/models/stats` | 获取统计 | - | 统计信息 |
| POST | `/api/v1/models/refresh` | 刷新客户端 | `provider_id` | 刷新结果 |
| GET | `/api/v1/models/providers` | 获取提供商列表 | `enabled_only` | 提供商列表 |
| POST | `/api/v1/models/record-usage` | 记录 Token 使用 | `TokenUsageRequest` | 记录结果 |
| GET | `/api/v1/models/token-usage/summary` | Token 使用摘要 | `days` | 摘要结果 |
| POST | `/api/v1/models/token-usage/reset` | 重置 Token 统计 | `provider_id`, `model` | 重置结果 |

#### 3.1.3 渠道管理 API（`/api/v1/channels`）

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/api/v1/channels` | 获取渠道列表 | `enabled_only` | 渠道列表 |
| GET | `/api/v1/channels/{channel}` | 获取渠道详情 | - | 渠道详情 |
| POST | `/api/v1/channels` | 添加渠道 | `ChannelAddRequest` | 添加结果 |
| PUT | `/api/v1/channels/{channel}` | 更新渠道 | `ChannelUpdateRequest` | 更新结果 |
| DELETE | `/api/v1/channels/{channel}` | 删除渠道 | - | 删除结果 |
| POST | `/api/v1/channels/{channel}/enable` | 启用/禁用 | `enabled` | 设置结果 |
| POST | `/api/v1/channels/{channel}/test` | 测试连接 | - | 测试结果 |
| GET | `/api/v1/channels/priority` | 按优先级获取 | `enabled_only` | 渠道列表 |
| POST | `/api/v1/channels/{channel}/priority` | 设置优先级 | `priority` | 设置结果 |
| GET | `/api/v1/channels/preferred` | 获取首选渠道 | `agent_id` | 首选渠道 |

## 4. 实现细节

### 4.1 子任务清单

- [x] **任务 1**: 完善 LLM Provider Manager - 添加负载均衡和故障转移
  - [x] 添加 `LoadBalancingStrategy` 枚举（5 种策略）
  - [x] 增强 `ProviderConfig` 以支持健康检查和故障转移
  - [x] 实现 `health_check_provider()` 方法
  - [x] 实现 `mark_provider_success()` 和 `mark_provider_failure()` 方法
  - [x] 实现 `get_healthy_providers()` 方法（按负载均衡策略排序）
  - [x] 实现 `select_provider()` 方法（支持负载均衡）
  - [x] 实现 `auto_failover()` 方法（自动故障转移）

- [x] **任务 2**: 完善 Channel Manager - 添加渠道优先级管理
  - [x] 更新 `ChannelConfig` 以添加优先级和健康状态字段
  - [x] 实现 `set_channel_priority()` 方法
  - [x] 实现 `get_channels_by_priority()` 方法
  - [x] 实现 `get_preferred_channel()` 方法
  - [x] 实现 `mark_channel_success()` 和 `mark_channel_failure()` 方法
  - [x] 实现 `update_channel_health()` 方法
  - [x] 实现 `check_channel_health()` 方法
  - [x] 更新 `process_incoming_message()` 和 `send_message()` 以集成健康状态跟踪
  - [x] 实现 `send_message_auto_channel()` 方法（自动选择最优渠道）

- [x] **任务 3**: 实现 LLM Configuration Console (`config_console.py`)
  - [x] 实现 `LLMConfigConsole` 类
  - [x] 提供商配置 API（列出、获取、添加、更新、删除、测试连接、设置默认）
  - [x] 模型选择与管理（列出、获取详情、选择模型）
  - [x] 参数调优（获取/更新默认参数、获取/更新/重置提供商参数）
  - [x] Token 使用统计（记录、获取、获取摘要、重置）
  - [x] 配置持久化（保存/加载配置和 Token 使用统计）

- [x] **任务 4**: 创建完整的 API 接口
  - [x] 更新 `neurova/api/endpoints/provider.py` 添加缺失的端点
    - [x] 健康检查端点（`/api/v1/providers/{provider_id}/test`）
    - [x] 批量健康检查（`/api/v1/providers/health-check`）
    - [x] Token 使用统计（`/api/v1/providers/token-usage`）
    - [x] 提供商参数管理（`/api/v1/providers/{provider_id}/params`）
  - [x] 更新 `neurova/api/endpoints/model.py` 添加缺失的端点
    - [x] 模型选择（负载均衡）（`/api/v1/models/select`）
    - [x] 获取模型详情（`/api/v1/models/{provider_id}/{model}`）
    - [x] 记录 Token 使用（`/api/v1/models/record-usage`）
    - [x] Token 使用摘要（`/api/v1/models/token-usage/summary`）
    - [x] 重置 Token 统计（`/api/v1/models/token-usage/reset`）

- [ ] **任务 5**: 确保 Vue 前端集成
  - [ ] 检查现有 Vue 页面（`neurova/vue/pages/`）
  - [ ] 创建 LLM 配置页面（如果不存在）
  - [ ] 集成 API 端点
  - [ ] 测试前端功能

### 4.2 已实现文件

| 文件路径 | 功能描述 | 状态 |
|----------|----------|------|
| `neurova/llm/provider_manager.py` | LLM 提供商管理器 | ✅ 已完成 |
| `neurova/llm/multi_model_client.py` | 多模型客户端管理器 | ✅ 已完成 |
| `neurova/llm/config_console.py` | LLM 配置控制台 | ✅ 已完成 |
| `neurova/llm/__init__.py` | 模块导出 | ✅ 已完成 |
| `neurova/llm/presets.py` | LLM 预设配置 | ✅ 已完成（已有） |
| `neurova/channels/__init__.py` | 渠道模块初始化 | ✅ 已完成 |
| `neurova/channels/manager.py` | 渠道管理器 | ✅ 已完成 |
| `neurova/api/endpoints/provider.py` | 提供商管理 API | ✅ 已完成 |
| `neurova/api/endpoints/model.py` | 模型管理 API | ✅ 已完成 |
| `neurova/api/endpoints/channel.py` | 渠道管理 API | ⏳ 已有，需检查 |

## 5. 测试计划

### 5.1 单元测试

| 测试文件 | 测试内容 | 状态 |
|----------|----------|------|
| `tests/test_provider_manager.py` | 测试 LLMProviderManager | ⏳ 待创建 |
| `tests/test_multi_model_client.py` | 测试 MultiModelLLMClient | ⏳ 待创建 |
| `tests/test_config_console.py` | 测试 LLMConfigConsole | ⏳ 待创建 |
| `tests/test_channel_manager.py` | 测试 ChannelManager | ⏳ 待创建 |

### 5.2 集成测试

1. **负载均衡测试**
   - 测试各种负载均衡策略
   - 测试故障转移功能
   - 测试健康检查功能

2. **API 测试**
   - 测试所有 API 端点
   - 测试参数验证
   - 测试错误处理

3. **前端集成测试**
   - 测试 Vue 页面与 API 的集成
   - 测试用户界面交互

## 6. 变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-05-12 | 1.0 | 初始版本，实现 LLM 配置与渠道管理模块 | llm-config-dev |

## 7. 已知问题

1. **问题 1**: `provider.py` 中的 `LoadBalancingStrategy` 枚举与 `provider_manager.py` 中的重复
   - **影响**: 代码重复，维护困难
   - **解决方案**: 在 `provider.py` 中导入 `provider_manager.py` 中的枚举，而不是重新定义

2. **问题 2**: `model.py` 中的 `LoadBalancingStrategy` 枚举与 `provider_manager.py` 中的重复
   - **影响**: 代码重复，维护困难
   - **解决方案**: 在 `model.py` 中导入 `provider_manager.py` 中的枚举，而不是重新定义

3. **问题 3**: 前端页面可能缺少 LLM 配置界面
   - **影响**: 用户无法通过前端配置 LLM
   - **解决方案**: 创建 `neurova/vue/pages/agent-config/llm-config.html` 页面

## 8. 下一步计划

1. 修复已知问题（消除代码重复）
2. 创建单元测试
3. 检查并创建 Vue 前端页面
4. 进行集成测试
5. 更新进度跟踪表（`docs/dev_progress/progress_tracker.md`）
6. 创建每日进度报告（`docs/dev_progress/daily_reports/2026-05-12.md`）
7. 通知 team-lead 任务完成
