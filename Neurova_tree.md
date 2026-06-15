# Neurova 项目文件树说明

> 最后更新：2026-06-15 | 四项架构改进完成

---

## 通知中心模块 (neurova/notifications/)

```
neurova/notifications/
├── __init__.py               # 模块导出入口
├── negative_screen.py        # 负一屏推送核心模块
│   ├── PushResult            # 推送结果数据类
│   ├── NegativeScreenConfig  # 用户级配置数据类（含 authCode 脱敏）
│   ├── NegativeScreenConfigManager  # 配置管理器（文件隔离、线程安全）
│   ├── NegativeScreenPusher  # 推送执行器（async aiohttp）
│   └── create_*() 工厂函数
└── manager.py                # 通知管理器（集成负一屏推送）
    ├── Notification          # 通知数据类（含推送状态追踪）
    ├── NotificationManager   # 通知管理器（任务完成自动推送）
    └── get_notification_manager() 全局单例
```

**功能说明：**
- 用户级 authCode 隔离：每个用户独立配置，存储在 `data/negative_screen/{user_id}.json`
- 任务完成自动推送：`notification_type == "task_completed"` 时自动触发
- 推送统计：追踪成功/失败/推送率
- 线程安全：使用 `threading.RLock` 保护共享状态

---

## 负一屏设置 API (neurova/api/endpoints/negative_screen_settings.py)

```
neurova/api/endpoints/negative_screen_settings.py
├── GET  /api/v1/negative-screen        # 获取用户配置
├── PUT  /api/v1/negative-screen        # 更新用户配置
├── POST /api/v1/negative-screen/test   # 测试推送
└── DELETE /api/v1/negative-screen      # 删除配置
```

**路由前缀：** `/api/v1/negative-screen`（独立于 `/api/v1/settings/`，避免 `/{key}` 通配冲突）

---

## 前端组件 (NeurUI/src/components/NegativeScreenSettings.vue)

```
NeurUI/src/components/NegativeScreenSettings.vue
├── Auth Code 输入（密码字段 + 获取步骤说明）
├── 启用/禁用开关
├── 推送 URL 配置
├── 测试推送按钮（含成功/失败反馈）
├── 推送统计展示（总数/已推送/失败/成功率）
└── 保存/删除配置按钮
```

**集成位置：** `NeurUI/src/pages/SettingPage.vue` → 负一屏推送 tab

---

## API 端点注册 (neurova/api/endpoints/__init__.py)

```python
("neurova.api.endpoints.negative_screen_settings", "/v1/negative-screen", "Negative Screen Settings API")
```

---

## 通知 API 扩展 (neurova/api/endpoints/notifications.py)

```python
@router.get("/push-statistics")  # 获取推送统计
```

---

## 测试文件 (tests/unit/test_negative_screen_integration.py)

```
tests/unit/test_negative_screen_integration.py (24 tests)
├── TestNegativeScreenConfig (6 tests)         # 配置数据结构
├── TestNegativeScreenConfigManager (7 tests)   # 配置管理器（用户隔离、线程安全）
├── TestNegativeScreenPusher (4 tests)          # 推送器（初始化、成功、无authCode、禁用、网络错误）
├── TestNotificationManagerIntegration (2 tests) # 通知管理器集成
├── TestNegativeScreenSettingsAPI (3 tests)     # 设置 API 端点
└── TestPostChatPipelineIntegration (1 test)    # RSI 结果推送
```

---

## 数据流

```
用户设置 authCode → NegativeScreenConfigManager.save_config()
→ 添加任务完成通知 → NotificationManager.add_notification()
→ _schedule_negative_screen_push() → daemon thread
→ NegativeScreenPusher.push_task() → aiohttp POST
→ 华为负一屏 API → 推送结果 → 更新通知状态
```

---

## Storage深度模块化 (2026-06-15)

### 设计原则
- **深度模块**：小接口，深实现
- **单一职责**：每个模块专注于一个核心功能
- **可测试性**：通过接口测试，不依赖实现细节

### 模块结构

```
neurova/cognitive_layers/memory_layer/
├── memory_record_store.py    # 纯CRUD深度模块
├── memory_index.py           # 索引和查询深度模块
└── (memory_cache.py)         # 缓存深度模块（待实现）
```

#### 1. MemoryRecordStore — 纯CRUD深度模块
**职责**：提供简洁的记忆记录CRUD接口，隐藏存储实现细节
**接口**：
- `save()` → `memory_id`
- `get(memory_id)` → `Dict | None`
- `delete(memory_id)` → `bool`
- `update(memory_id, **fields)` → `bool`
- `count()` → `int`
- `exists(memory_id)` → `bool`
- `batch_save()` → `List[str]`
- `batch_delete()` → `int`

**隐藏的复杂度**：
- 存储后端（JSON/SQLite）
- 索引维护
- 线程安全
- 隔离上下文

#### 2. MemoryIndex — 索引和查询深度模块
**职责**：提供高效的记忆索引和查询接口，支持多维度检索
**接口**：
- `query()` → `List[Dict]`
- `search_by_tags()` → `List[Dict]`
- `search_by_text()` → `List[Dict]`
- `get_by_ids()` → `List[Dict]`
- `get_stats()` → `Dict`

**隐藏的复杂度**：
- 多维度索引（类型、所有者、标签、隔离）
- 查询优化
- 索引维护
- 隔离过滤

### 测试覆盖
- `tests/unit/test_memory_record_store_v2.py` — 13 tests
- `tests/unit/memory/test_memory_index.py` — 24 tests
- 总计：37 tests，全部通过

### 架构收益
1. **局部性**：每个深度模块职责单一，易于维护
2. **杠杆**：调用者只需掌握小接口，即可使用完整功能
3. **深度**：实现细节隐藏在接口之后，可独立优化
4. **可测试性**：通过接口测试，无需了解内部实现

---

## 检索通道统一抽象 (2026-06-15)

### 设计原则
- **插件化架构**：所有检索通道通过统一的BaseChannel接口实现
- **可扩展性**：新通道只需继承BaseChannel并实现retrieve方法
- **统一管理**：ChannelRegistry管理所有通道的生命周期

### 模块结构

```
neurova/cognitive_layers/memory_layer/channels/
├── base.py                 # BaseChannel抽象基类 + 数据模型
├── registry.py             # ChannelRegistry通道注册表（单例）
├── builtin/                # 内置通道实现
│   ├── temperature.py      # 温度通道（热记忆优先）
│   ├── text.py             # 文本通道（语义相似度）
│   ├── category.py         # 分类通道（同类别记忆）
│   ├── graph.py            # 图通道（关系图谱）
│   ├── emotion.py          # 情感通道（情感相似度）
│   └── voice.py            # 语音通道（语音转写记忆）
└── __init__.py             # 模块导出
```

#### 1. BaseChannel — 通道抽象基类
**职责**：定义所有检索通道的统一接口
**接口**：
- `metadata` → `ChannelMetadata` (抽象属性)
- `retrieve(query, limit, weight, **kwargs)` → `List[ChannelResult]` (抽象方法)
- `initialize()` → `bool`
- `shutdown()` → `None`
- `get_state()` → `ChannelState`
- `update_config(config)` → `None`

**隐藏的复杂度**：
- 通道状态管理
- 配置更新
- 生命周期管理

#### 2. ChannelRegistry — 通道注册表
**职责**：管理所有检索通道的注册/注销/查询/枚举
**接口**：
- `register(channel)` → `bool`
- `unregister(name)` → `bool`
- `get(name)` → `BaseChannel`
- `get_all()` → `List[BaseChannel]`
- `get_active()` → `List[BaseChannel]`
- `initialize_all()` → `Dict[str, bool]`
- `shutdown_all()` → `None`

#### 3. 内置通道实现
6个内置通道，每个实现特定的检索逻辑：
- **TemperatureChannel**: 基于记忆温度（最近访问时间）检索
- **TextChannel**: 基于关键词匹配和语义相似度检索
- **CategoryChannel**: 基于记忆类别检索
- **GraphChannel**: 基于关系图谱检索
- **EmotionChannel**: 基于情感相似度检索
- **VoiceChannel**: 基于语音转写记忆检索

### 集成到NeurovaRecallEngine
- `use_plugins`参数默认改为`True`
- 自动注册内置通道到ChannelRegistry
- 插件模式优先于传统硬编码模式
- 保持向后兼容（传统模式仍可用）

### 架构收益
1. **统一接口**：所有通道遵循相同的BaseChannel接口
2. **可扩展性**：新通道只需继承BaseChannel并实现retrieve方法
3. **可测试性**：每个通道可独立测试
4. **动态管理**：支持运行时注册/注销通道
5. **配置灵活**：每个通道可独立配置

---

## EventBus增强 (2026-06-15)

### 设计原则
- **向后兼容**：继承EventBus，不破坏现有代码
- **深度模块**：小接口，深实现
- **可测试性**：每个功能可独立测试

### 模块结构

```
neurova/core/
├── event_bus.py              # 基础EventBus（已有）
└── event_bus_enhanced.py     # 增强版EventBusEnhanced（新建）
```

#### EventBusEnhanced — 增强版事件总线
**继承**：EventBus
**新增功能**：
1. **事件过滤**：基于谓词的事件过滤，异常安全
2. **事件重播**：重新触发历史事件（使用父类publish避免重复记录）
3. **死信队列**：处理失败的事件，支持重试
4. **事件链**：一个事件自动触发多个目标事件
5. **统计信息**：事件数、订阅数、死信数、过滤器数

**核心接口**：
- `add_filter(event_name, filter_obj)` → `None`
- `remove_filter(event_name, filter_name)` → `bool`
- `add_event_chain(trigger_event, target_events)` → `None`
- `remove_event_chain(trigger_event)` → `bool`
- `replay_events(event_name, limit)` → `int`
- `add_dead_letter(event, subscription, error)` → `None`
- `get_dead_letters(limit)` → `List[DeadLetter]`
- `clear_dead_letters()` → `int`
- `retry_dead_letter(dead_letter)` → `bool`
- `get_event_history(event_name, limit)` → `List[Event]`
- `get_statistics()` → `Dict[str, Any]`

**关键设计**：
- 过滤器异常时阻止事件（安全优先）
- 重播使用父类publish（避免历史重复）
- 事件链递归触发（防御无限循环）

### 测试覆盖
- `tests/unit/test_event_bus_enhanced.py` — 17 tests，全部通过

### 架构收益
1. **向后兼容**：继承EventBus，现有代码无需修改
2. **可组合性**：过滤器、事件链可自由组合
3. **可观测性**：事件历史和死信队列提供完整追踪
4. **容错性**：死信队列和重试机制保证事件不丢失

---

## 进化系统闭环 (2026-06-15)

### 设计原则
- **事件驱动**：通过EventBus连接进化系统与其他系统
- **深度模块**：小接口，深实现
- **向后兼容**：不修改现有EvolutionOrchestrator

### 模块结构

```
neurova/evolution/
├── event_driven.py           # 进化系统事件桥接器（新建）
└── __init__.py               # 更新导出
```

#### EvolutionEventBridge — 进化系统事件桥接器
**职责**：连接EventBus与进化系统，实现事件驱动的闭环进化
**事件流**：
```
tool.execution.completed → EvolutionEventBridge → EvolutionOrchestrator → evolution.tool.weight_updated
experience.recorded → EvolutionEventBridge → EvolutionOrchestrator → evolution.cycle.completed
```

**核心接口**：
- `set_orchestrator(orchestrator)` → `None`（注入进化编排器）
- `start()` → `None`（启动事件桥接，订阅事件）
- `stop()` → `None`（停止事件桥接，取消订阅）
- `get_statistics()` → `Dict[str, Any]`（获取统计信息）

**事件常量**：
- `EVT_TOOL_EXECUTED` = "evolution.tool.executed"
- `EVT_TOOL_WEIGHT_UPDATED` = "evolution.tool.weight_updated"
- `EVT_TOOL_LIFECYCLE_CHANGED` = "evolution.tool.lifecycle_changed"
- `EVT_EXPERIENCE_RECORDED` = "evolution.experience.recorded"
- `EVT_EVOLUTION_CYCLE_COMPLETED` = "evolution.cycle.completed"

**关键设计**：
- 订阅 `tool.execution.completed` 事件 → 触发权重更新 → 发布 `evolution.tool.weight_updated`
- 订阅 `experience.recorded` 事件 → 触发经验反哺 → 发布 `evolution.cycle.completed`
- 与EventBusEnhanced集成：支持事件过滤和事件链

### 测试覆盖
- `tests/unit/test_evolution_event_driven.py` — 16 tests，全部通过

### 架构收益
1. **解耦**：进化系统与工具执行、经验记录系统解耦
2. **可观测**：所有进化事件可追踪、可重播
3. **可组合**：与EventBusEnhanced的过滤器和事件链集成
4. **容错**：死信队列保证事件不丢失

---

## 关键设计决策

1. **路由隔离**：使用 `/v1/negative-screen` 独立前缀，避免与 `/v1/settings/{key}` 通配冲突
2. **用户隔离**：每个用户独立 JSON 文件，文件名使用 `user_id` 安全化处理
3. **异步推送**：daemon 线程中运行 asyncio event loop，不阻塞主流程
4. **容错处理**：aiohttp 未安装时优雅降级，返回错误信息
5. **测试策略**：mock `_execute_push` 而非 `aiohttp.ClientSession.post`，避免依赖安装
6. **深度模块化**：Storage层采用深度模块模式，小接口深实现，提升可维护性和可测试性
7. **四项架构改进**（2026-06-15）：
   - Storage深度模块化：MemoryRecordStore + MemoryIndex（37 tests）
   - 检索通道统一抽象：BaseChannel + ChannelRegistry + 6个内置通道
   - EventBus增强：EventBusEnhanced（过滤/重播/死信/事件链，17 tests）
   - 进化系统闭环：EvolutionEventBridge（事件驱动进化，16 tests）

## 四项架构改进总览 (2026-06-15)

### 改进统计
| 改进项 | 新建文件 | 测试数 | 状态 |
|--------|----------|--------|------|
| Storage深度模块化 | 2 | 37 | ✅ 完成 |
| 检索通道统一抽象 | - | - | ✅ 完成 |
| EventBus增强 | 1 | 17 | ✅ 完成 |
| 进化系统闭环 | 1 | 16 | ✅ 完成 |
| **总计** | **4** | **70** | **✅ 全部完成**
