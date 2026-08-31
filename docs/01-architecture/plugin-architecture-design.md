# Neurova 插件化架构设计文档

> 版本: 1.0.0
> 作者: Neurova 架构团队
> 日期: 2026-05-08
> 状态: 设计中

---

## 目录

1. [概述](#1-概述)
2. [现有架构分析](#2-现有架构分析)
3. [目标架构设计](#3-目标架构设计)
4. [核心组件详细设计](#4-核心组件详细设计)
5. [文件结构设计](#5-文件结构设计)
6. [前端插件集成设计](#6-前端插件集成设计)
7. [后端插件集成设计](#7-后端插件集成设计)
8. [实施阶段规划](#8-实施阶段规划)
9. [迁移计划](#9-迁移计划)
10. [示例插件实现](#10-示例插件实现)
11. [风险评估与应对](#11-风险评估与应对)
12. [总结](#12-总结)

---

## 1. 概述

### 1.1 背景

Neurova 是一个基于 Flask/FastAPI 的 AI Agent 系统，具备记忆管理、多渠道通信、Skill 执行等核心能力。当前系统已有一定的模块化基础（如 `core/` 目录下已实现了事件总线、模块库、状态管理等基础设施），但尚未形成完整的插件化架构。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **动态扩展** | 支持运行时加载/卸载插件，无需重启服务 |
| **接口标准化** | 所有插件遵循统一接口（`BaseModule`）和 API 标准 |
| **松耦合** | 插件间通过事件总线通信，不直接互相依赖 |
| **安全性** | 插件权限声明、路径验证、沙箱隔离 |
| **前后端统一** | 前端 UI 插件和后端功能插件使用相同的生命周期模型 |
| **可观测性** | 统一的日志、错误、状态、配置管理 |

### 1.3 设计约束

严格遵循项目规则文件：
- `coremodule need.md` — 统一模块库、事件总线、状态管理、配置管理
- `uineed.md` — 统一 UI 组件库、样式库、交互库、动画库
- `mustdo.md` — 统一标准、接口规范、高效实现

---

## 2. 现有架构分析

### 2.1 当前系统全景

```
┌──────────────────────────────────────────────────────────────────┐
│                        前端 (static/)                             │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐ │
│  │ app.js  │  │ api.js   │  │ pages/*.js│  │ ui/framework.js  │ │
│  │(页面路由)│  │(API封装) │  │(页面逻辑) │  │(UI组件/状态/事件)│ │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  └────────┬─────────┘ │
│       │            │              │                  │           │
│       └────────────┴──────────────┴──────────────────┘           │
│                            │ HTTP                                 │
├────────────────────────────┼────────────────────────────────────┤
│                        后端 (neurova/)                           │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────────┐  │
│  │ api/app.py  │    │neurova_server│    │ plugins/            │  │
│  │ (FastAPI)   │    │  (Flask)     │    │ plugin_manager.py   │  │
│  │             │    │              │    │ plugin_manifest.py  │  │
│  │ ┌─────────┐ │    │ ┌──────────┐ │    │ plugin_lifecycle.py │  │
│  │ │channels/│ │    │ │ channels/│ │    └─────────────────────┘  │
│  │ │memory/  │ │    │ │ memory/  │ │                              │
│  │ │skills/  │ │    │ │ agent.py │ │    ┌─────────────────────┐  │
│  │ │api/     │ │    │ │ router.py│ │    │ core/               │  │
│  │ └─────────┘ │    │ └──────────┘ │    │ event_bus.py        │  │
│  └─────────────┘    └──────────────┘    │ module_lib.py       │  │
│                                         │ state_manager.py    │  │
│                                         │ config_manager.py   │  │
│                                         │ error_handler.py    │  │
│                                         │ base_module.py      │  │
│                                         │ logger.py           │  │
│                                         └─────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 现有基础设施评估

系统已具备以下**核心基础设施**（位于 `neurova/core/`）：

| 模块 | 文件 | 功能 | 成熟度 |
|------|------|------|--------|
| BaseModule | `base_module.py` | 模块抽象基类，定义生命周期 | ✅ 完善 |
| EventBus | `event_bus.py` | 发布-订阅事件系统 | ✅ 完善 |
| ModuleLib | `module_lib.py` | 模块注册/加载/卸载 | ✅ 完善 |
| StateManager | `state_manager.py` | 状态树/快照/回滚 | ✅ 完善 |
| ConfigManager | `config_manager.py` | 分层配置管理 | ✅ 完善 |
| ErrorHandler | `error_handler.py` | 错误码/恢复策略 | ✅ 完善 |
| LogManager | `logger.py` | 统一日志管理 | ✅ 完善 |

**Plugin 框架**（位于 `neurova/plugins/`）：

| 模块 | 文件 | 功能 | 成熟度 |
|------|------|------|--------|
| PluginManager | `plugin_manager.py` | 插件发现/安装/加载/卸载 | ✅ 完善 |
| PluginManifest | `plugin_manifest.py` | 语义化版本/权限/依赖 | ✅ 完善 |
| PluginLifecycle | `plugin_lifecycle.py` | 生命周期钩子管理 | ✅ 完善 |

**前端 UI 框架**（位于 `neurova/ui/`）：

| 模块 | 文件 | 功能 | 成熟度 |
|------|------|------|--------|
| NeurovaUI | `framework.js` | UI 框架入口 | 🟡 基础完成 |
| EventEmitter | `event-bus.js` | 前端事件总线 | ✅ 完善 |
| StateManager | `state-manager.js` | 前端状态管理 | 🟡 基础完成 |
| ComponentRegistry | `component-registry.js` | 组件注册中心 | 🟡 基础完成 |
| 组件库 | `components/*.js` | 基础 UI 组件 | 🟡 部分完成 |

### 2.3 现有架构存在的问题

| 问题编号 | 问题描述 | 影响 |
|----------|----------|------|
| P1 | **双后端并存**: `neurova_server.py` (Flask) 和 `api/app.py` (FastAPI) 同时存在，路由不统一 | 维护成本高，功能重复 |
| P2 | **插件未实际集成**: PluginManager 存在但未在应用启动流程中使用，核心组件未作为插件加载 | 插件架构形同虚设 |
| P3 | **前后端插件不统一**: 前端页面通过 `app.js` 直接 fetch HTML，不走 UI 框架的组件系统 | 违反 uineed.md 规范 |
| P4 | **缺少前端插件标准**: 没有定义前端插件的清单格式、生命周期、打包规范 | 无法实现前端动态扩展 |
| P5 | **API 未插件化**: 所有 API 端点硬编码在 `api/endpoints/` 中，不能由插件动态注册 | 扩展能力受限 |
| P6 | **缺少插件间通信标准**: 虽然 EventBus 存在，但没有定义标准的事件命名空间和通信协议 | 通信混乱 |

---

## 3. 目标架构设计

### 3.1 架构分层

```
┌────────────────────────────────────────────────────────────────────┐
│                     展示层 (Presentation Layer)                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    前端插件系统                                │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │  │
│  │  │Chat插件  │ │Memory插件│ │Agent插件 │ │Channel插件   │    │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │  │
│  │  ┌──────────────────────────────────────────────────────┐    │  │
│  │  │              NeurovaUI 前端框架                        │    │  │
│  │  │  (组件库 / 状态管理 / 事件总线 / 样式系统 / 布局系统)   │    │  │
│  │  └──────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                     业务层 (Business Layer)                          │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    后端插件系统                                │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐    │  │
│  │  │Channel   │ │Skill     │ │Memory    │ │Agent         │    │  │
│  │  │Plugins   │ │Plugins   │ │Plugins   │ │Plugins       │    │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘    │  │
│  │  ┌──────────────────────────────────────────────────────┐    │  │
│  │  │              PluginManager + ModuleLib                 │    │  │
│  │  │  (插件发现/安装/加载/卸载/依赖解析/版本控制)             │    │  │
│  │  └──────────────────────────────────────────────────────┘    │  │
│  └──────────────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────────────┤
│                     核心层 (Core Layer)                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │EventBus  │ │StateMgr  │ │ConfigMgr │ │ErrorHdlr │ │LogManager│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
├────────────────────────────────────────────────────────────────────┤
│                     基础设施层 (Infrastructure)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ FastAPI  │ │ SQLite   │ │ LLM API  │ │ Channel  │ │ File I/O │ │
│  │ /Flask   │ │ /向量DB  │ │ 客户端   │ │ SDKs     │ │ 网络     │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心架构原则

| 原则 | 说明 |
|------|------|
| **统一接口** | 所有插件必须继承 `BaseModule`，实现 `on_initialize / on_start / on_stop / on_destroy` |
| **事件驱动** | 插件间通信仅通过 EventBus，禁止直接方法调用 |
| **状态隔离** | 每个插件通过 StateManager 管理自己的命名空间状态 |
| **配置分层** | 插件配置通过 ConfigManager 管理，支持热更新 |
| **动态注册** | 后端 API 端点由插件在 `on_start` 时动态注册到路由器 |
| **前后端对称** | 前端插件遵循与后端相同的生命周期模型 |
| **安全沙箱** | 插件权限通过 Manifest 声明，路径访问受限制 |

### 3.3 插件分类体系

```
                    Plugin (BaseModule)
                         │
          ┌──────────────┼──────────────┐
          │              │              │
   BackendPlugin   FrontendPlugin   HybridPlugin
          │              │              │
    ┌─────┼─────┐   ┌───┼───┐     ┌────┼────┐
    │     │     │   │   │   │     │    │    │
  Channel Skill API Page Widget  Component  │
  Plugin Plugin Plugin Plugin Plugin  Plugin │
                                             │
                                    (同时包含前后端)
```

| 插件类型 | 说明 | 部署位置 | 示例 |
|----------|------|----------|------|
| **Channel Plugin** | 消息渠道适配器 | 后端 `plugins/channels/` | 微信、Telegram、飞书 |
| **Skill Plugin** | 技能执行器 | 后端 `plugins/skills/` | 天气查询、翻译、代码执行 |
| **API Plugin** | API 端点提供者 | 后端 `plugins/api/` | 自定义 REST 端点 |
| **Page Plugin** | 完整页面 | 前端 `static/plugins/pages/` | 数据大屏、管理面板 |
| **Widget Plugin** | UI 组件 | 前端 `static/plugins/widgets/` | 聊天窗口、状态卡片 |
| **Hybrid Plugin** | 前后端一体 | 后端 + 前端目录 | 带管理面板的渠道插件 |

---

## 4. 核心组件详细设计

### 4.1 插件基类设计

#### 4.1.1 后端插件基类 (`BasePlugin`)

```python
class BasePlugin(BaseModule):
    """
    所有后端插件的基础抽象类
    
    扩展了 BaseModule，增加了:
    - API 端点注册能力
    - 前后端资源声明
    - 插件元数据扩展
    """
    
    # 子类必须声明的元数据
    plugin_type: PluginType  # 插件类型
    api_endpoints: List[APIEndpoint]  # 提供的 API 端点
    frontend_resources: List[str]  # 前端静态资源
    required_permissions: List[PluginPermission]  # 需要的权限
    
    async def on_initialize(self) -> None:
        """初始化: 注册事件监听器、加载配置"""
        ...
    
    async def on_start(self) -> None:
        """启动: 注册 API 端点、启动后台任务"""
        # 自动注册声明的 API 端点到路由器
        for endpoint in self.api_endpoints:
            self._register_api_endpoint(endpoint)
        ...
    
    async def on_stop(self) -> None:
        """停止: 注销 API 端点、清理后台任务"""
        ...
    
    async def on_destroy(self) -> None:
        """销毁: 释放资源"""
        ...
```

#### 4.1.2 前端插件基类 (`BaseUIPlugin`)

```javascript
class BaseUIPlugin {
  /**
   * 前端插件基类
   * 所有前端插件必须继承此类
   */
  constructor(pluginManifest) {
    this.manifest = pluginManifest;  // plugin.json 内容
    this.id = pluginManifest.plugin_id;
    this.state = 'pending';
    this.eventBus = null;
    this.stateManager = null;
    this.ui = null;
  }

  // === 生命周期 (必须实现) ===
  async initialize(neurovaUI) { }
  async start() { }
  async stop() { }
  async destroy() { }

  // === 便捷方法 ===
  createComponent(name, props, container) { }
  emit(event, data) { }
  on(event, callback) { }
  getState(key) { }
  setState(key, value) { }
}
```

### 4.2 插件清单规范

每个插件目录必须包含 `plugin.json`：

```json
{
  "plugin_id": "wechat-channel",
  "name": "微信渠道插件",
  "version": "1.0.0",
  "description": "支持微信消息接收和发送的渠道插件",
  "author": "Neurova Team",
  "plugin_type": "channel",
  
  "dependencies": {
    "neurova-core": ">=1.0.0"
  },
  "optional_dependencies": {},
  "neurova_min_version": "1.0.0",
  
  "entry_point": "wechat_plugin.py",
  "module_class": "WeChatChannelPlugin",
  
  "permissions": [
    "read:events",
    "emit:events",
    "http:request"
  ],
  
  "config_schema": {
    "type": "object",
    "properties": {
      "app_id": { "type": "string" },
      "app_secret": { "type": "string" }
    }
  },
  "default_config": {
    "app_id": "",
    "app_secret": ""
  },
  
  "api_endpoints": [
    {
      "method": "POST",
      "path": "/api/v1/plugins/wechat/webhook",
      "description": "微信回调端点"
    }
  ],
  
  "frontend": {
    "enabled": false
  },
  
  "tags": ["channel", "wechat"],
  "homepage": "",
  "license": "MIT"
}
```

### 4.3 事件总线 — 事件命名规范

```
事件命名格式: {领域}.{实体}.{动作}

示例:
  plugin.installed         — 插件已安装
  plugin.started           — 插件已启动
  plugin.stopped           — 插件已停止
  
  chat.message.sent        — 聊天消息已发送
  chat.message.received    — 聊天消息已接收
  chat.stream.chunk        — 流式输出片段
  
  memory.saved             — 记忆已保存
  memory.recalled          — 记忆已检索
  memory.decayed           — 记忆温度衰减
  
  channel.message          — 渠道消息
  channel.connected        — 渠道已连接
  channel.disconnected     — 渠道已断开
  
  ui.page.loaded           — 页面已加载
  ui.component.mounted     — 组件已挂载
  ui.theme.changed         — 主题已变更
```

### 4.4 API 端点动态注册机制

```python
# 插件在 on_start() 中注册 API 端点
class MyAPIPlugin(BasePlugin):
    api_endpoints = [
        APIEndpoint("GET", "/api/v1/plugins/my-plugin/status", "get_status"),
        APIEndpoint("POST", "/api/v1/plugins/my-plugin/action", "do_action"),
    ]
    
    async def on_start(self):
        router = self._get_router()  # 获取主路由器
        for ep in self.api_endpoints:
            handler = getattr(self, ep.handler_name)
            router.add_route(ep.method, ep.path, handler, plugin_id=self.module_id)
    
    async def on_stop(self):
        router = self._get_router()
        for ep in self.api_endpoints:
            router.remove_route(ep.path, plugin_id=self.module_id)
```

### 4.5 状态管理 — 命名空间隔离

```
状态树结构:
├── plugins
│   ├── wechat-channel
│   │   ├── status: "running"
│   │   ├── message_count: 1523
│   │   └── last_error: null
│   ├── weather-skill
│   │   ├── status: "running"
│   │   └── cache_size: 42
│   └── chat-page
│       ├── current_agent: "Yiling"
│       └── theme: "dark"
├── system
│   ├── uptime: 3600
│   └── memory_usage: "256MB"
└── ui
    ├── sidebar_collapsed: false
    └── active_page: "chat"
```

### 4.6 配置管理 — 插件配置隔离

```python
# 插件获取自己的配置
config = self._get_config_manager()
app_id = config.get(f"plugin.{self.module_id}.app_id")

# 插件配置变更监听
def on_config_change(key, old_value, new_value):
    self._reconfigure(new_value)

config.on_change(on_config_change)
```

---

## 5. 文件结构设计

### 5.1 目标文件结构

```
e:\项目\Neurova\
├── neurova/                          # 后端核心代码
│   ├── __init__.py
│   ├── app.py                        # ★ 新的统一应用入口 (取代 api/app.py + neurova_server.py)
│   ├── core/                         # 核心基础设施
│   │   ├── __init__.py
│   │   ├── base_module.py            # 模块基类
│   │   ├── event_bus.py              # 事件总线
│   │   ├── module_lib.py             # 模块库
│   │   ├── state_manager.py          # 状态管理
│   │   ├── config_manager.py         # 配置管理
│   │   ├── error_handler.py          # 错误处理
│   │   ├── logger.py                 # 日志管理
│   │   ├── api_standard.py           # API 标准 (从 interfaces 合并)
│   │   └── api_router.py             # ★ 新增: 动态 API 路由器
│   │
│   ├── plugins/                      # 插件框架
│   │   ├── __init__.py
│   │   ├── plugin_manager.py         # 插件管理器
│   │   ├── plugin_manifest.py        # 插件清单
│   │   ├── plugin_lifecycle.py       # 生命周期管理
│   │   ├── base_plugin.py            # ★ 新增: 后端插件基类
│   │   └── plugin_api_registry.py    # ★ 新增: 插件 API 注册器
│   │
│   ├── builtin_plugins/              # ★ 新增: 内置插件 (原 core 模块插件化)
│   │   ├── __init__.py
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   ├── plugin.json           # 记忆插件清单
│   │   │   └── memory_plugin.py      # 记忆插件实现
│   │   ├── agent/
│   │   │   ├── plugin.json
│   │   │   └── agent_plugin.py
│   │   ├── channel/
│   │   │   ├── plugin.json
│   │   │   └── channel_plugin.py
│   │   └── skill/
│   │       ├── plugin.json
│   │       └── skill_plugin.py
│   │
│   ├── memory/                       # 记忆系统 (保持现有结构)
│   │   └── core/
│   │
│   ├── channels/                     # 渠道适配器 (保持现有结构)
│   │
│   ├── skills/                       # 技能系统 (保持现有结构)
│   │
│   └── agent.py                      # Agent 核心 (简化，委托给插件)
│
├── static/                           # 前端静态文件
│   ├── index.html                    # 单页应用入口
│   ├── css/
│   ├── js/
│   │   ├── app.js                    # 主应用加载器
│   │   ├── api.js                    # API 封装
│   │   ├── plugin-loader.js          # ★ 新增: 前端插件加载器
│   │   └── pages/                    # 传统页面 (逐步迁移到插件)
│   │
│   └── plugins/                      # ★ 新增: 前端插件目录
│       ├── chat/
│       │   ├── plugin.json
│       │   ├── chat-page.js
│       │   └── chat-page.css
│       ├── memory/
│       │   ├── plugin.json
│       │   └── memory-dashboard.js
│       └── agents/
│           ├── plugin.json
│           └── agents-page.js
│
├── plugins/                          # 外部插件安装目录
│   └── (用户安装的插件放在这里)
│
├── data/                             # 数据目录
│   ├── channels.json
│   └── plugins/                      # 插件数据存储
│
└── docs/                             # 文档
    └── plugin-architecture-design.md
```

### 5.2 与现有结构的对比

| 现有路径 | 目标路径 | 变更说明 |
|----------|----------|----------|
| `api/app.py` | `neurova/app.py` | 合并为统一入口 |
| `neurova_server.py` | `neurova/app.py` | 合并为统一入口 |
| `neurova/interfaces/api_standard.py` | `neurova/core/api_standard.py` | 合并到 core |
| — | `neurova/plugins/base_plugin.py` | 新增插件基类 |
| — | `neurova/plugins/plugin_api_registry.py` | 新增 API 注册器 |
| — | `neurova/builtin_plugins/` | 新增内置插件目录 |
| — | `neurova/core/api_router.py` | 新增动态路由器 |
| — | `static/js/plugin-loader.js` | 新增前端插件加载器 |
| — | `static/plugins/` | 新增前端插件目录 |

---

## 6. 前端插件集成设计

### 6.1 前端插件加载流程

```
页面加载
    │
    ▼
[1] 加载 NeurovaUI 框架 (framework.js)
    │
    ▼
[2] 加载 plugin-loader.js
    │
    ▼
[3] 扫描 /static/plugins/ 目录
    │  (通过 manifest.json 索引文件)
    │
    ▼
[4] 解析每个插件的 plugin.json
    │
    ▼
[5] 检查依赖和兼容性
    │
    ▼
[6] 按依赖顺序加载插件 JS
    │
    ▼
[7] 调用插件 initialize(uiFramework)
    │
    ▼
[8] 调用插件 start()
    │
    ▼
[9] 插件注册路由 / 组件 / 导航项
    │
    ▼
[10] 插件 UI 挂载到页面
```

### 6.2 前端插件加载器 (`plugin-loader.js`)

```javascript
/**
 * 前端插件加载器
 * 负责发现、加载、初始化前端插件
 */
class PluginLoader {
  constructor(uiFramework) {
    this.ui = uiFramework;
    this.plugins = new Map();
    this.manifestUrl = '/static/plugins/manifest.json';
  }

  /**
   * 加载所有插件
   */
  async loadAll() {
    // 1. 获取插件清单索引
    const manifest = await this.fetchManifest();
    
    // 2. 依赖解析 (拓扑排序)
    const loadOrder = this.resolveDependencies(manifest.plugins);
    
    // 3. 按顺序加载
    for (const pluginMeta of loadOrder) {
      await this.loadPlugin(pluginMeta);
    }
    
    console.log(`[PluginLoader] ${this.plugins.size} 插件已加载`);
  }

  /**
   * 加载单个插件
   */
  async loadPlugin(meta) {
    const { plugin_id, entry_point, version } = meta;
    
    if (this.plugins.has(plugin_id)) {
      return this.plugins.get(plugin_id);
    }

    // 动态加载 JS
    await this.importScript(`/static/plugins/${entry_point}`);
    
    // 获取插件类 (约定: window.NeurovaPlugins[plugin_id])
    const PluginClass = window.NeurovaPlugins?.[plugin_id];
    if (!PluginClass) {
      throw new Error(`Plugin class not found for ${plugin_id}`);
    }

    const plugin = new PluginClass(meta);
    
    // 注入框架依赖
    plugin.eventBus = this.ui.eventBus;
    plugin.stateManager = this.ui.stateManager;
    plugin.ui = this.ui;
    
    // 初始化
    await plugin.initialize(this.ui);
    await plugin.start();
    
    this.plugins.set(plugin_id, plugin);
    return plugin;
  }

  /**
   * 卸载插件
   */
  async unloadPlugin(pluginId) {
    const plugin = this.plugins.get(pluginId);
    if (!plugin) return false;
    
    await plugin.stop();
    await plugin.destroy();
    this.plugins.delete(pluginId);
    return true;
  }
}
```

### 6.3 前端插件示例结构

```
static/plugins/chat/
├── plugin.json          # 插件清单
├── chat-page.js         # 页面逻辑
└── chat-page.css        # 页面样式

plugin.json:
{
  "plugin_id": "chat-page",
  "name": "聊天页面",
  "version": "1.0.0",
  "plugin_type": "page",
  "entry_point": "chat-page.js",
  "dependencies": {},
  "neurova_min_version": "1.0.0",
  "permissions": ["read:events", "emit:events"],
  "frontend": {
    "enabled": true,
    "route": "/chat",
    "nav_item": {
      "icon": "message-square",
      "label": "聊天",
      "section": "core"
    }
  }
}
```

---

## 7. 后端插件集成设计

### 7.1 统一应用入口 (`neurova/app.py`)

```python
"""
Neurova 统一应用入口

取代原有的 neurova_server.py 和 api/app.py，
基于插件架构重新设计。
"""

from neurova.core.event_bus import EventBus, get_event_bus
from neurova.core.state_manager import StateManager, get_state_manager
from neurova.core.config_manager import ConfigManager, get_config_manager
from neurova.core.error_handler import ErrorHandler, get_error_handler
from neurova.core.logger import LogManager, get_log_manager
from neurova.core.module_lib import ModuleLib, get_module_lib
from neurova.plugins.plugin_manager import PluginManager, get_plugin_manager


class NeurovaApp:
    """
    统一应用实例
    
    所有功能通过插件加载，包括:
    - 记忆系统 (作为内置插件)
    - Agent 核心 (作为内置插件)
    - 渠道管理 (作为内置插件)
    - 技能系统 (作为内置插件)
    """
    
    def __init__(self, config_path: str = None):
        # 初始化核心服务
        self.event_bus = get_event_bus()
        self.state_manager = get_state_manager()
        self.config_manager = get_config_manager()
        self.error_handler = get_error_handler()
        self.log_manager = get_log_manager()
        self.module_lib = get_module_lib()
        
        # 初始化插件管理器
        self.plugin_manager = PluginManager(
            event_bus=self.event_bus,
            state_manager=self.state_manager,
            config_manager=self.config_manager,
            log_manager=self.log_manager,
            error_handler=self.error_handler,
            module_lib=self.module_lib,
        )
        
        self._fastapi_app = None
    
    async def startup(self):
        """
        应用启动流程:
        1. 启动核心服务
        2. 发现并加载内置插件
        3. 发现并加载外部插件
        4. 解析依赖并按顺序启动
        5. 创建 FastAPI 应用并注册所有插件端点
        """
        # 1. 启动事件总线
        await self.event_bus.start()
        
        # 2. 扫描并发现所有插件
        all_plugins = self.plugin_manager.discover_plugins()
        builtin_plugins = self.plugin_manager.discover_plugins(
            directory=Path(__file__).parent / "builtin_plugins"
        )
        
        # 3. 安装发现的插件
        for manifest in builtin_plugins + all_plugins:
            await self.plugin_manager.install_plugin(
                directory=manifest.directory,
                manifest=manifest,
            )
        
        # 4. 解析加载顺序并加载
        all_ids = list(self.plugin_manager._records.keys())
        load_order = self.plugin_manager.resolve_load_order(all_ids)
        
        for plugin_id in load_order:
            await self.plugin_manager.load_plugin(plugin_id)
            await self.plugin_manager.enable_plugin(plugin_id)
        
        # 5. 创建 FastAPI 应用
        self._fastapi_app = self._create_fastapi_app()
        
        self.event_bus.publish("app.started", data={"timestamp": datetime.now().isoformat()})
    
    async def shutdown(self):
        """应用关闭流程"""
        # 1. 停止所有插件 (逆序)
        enabled = self.plugin_manager.get_enabled_plugins()
        for plugin in reversed(enabled):
            await self.plugin_manager.disable_plugin(plugin.manifest.plugin_id)
        
        # 2. 卸载所有插件
        await self.plugin_manager.unload_all()
        
        # 3. 停止核心服务
        await self.event_bus.stop()
    
    def _create_fastapi_app(self) -> FastAPI:
        """
        创建 FastAPI 应用
        所有 API 端点由插件动态注册
        """
        app = FastAPI(
            title="Neurova Plugin API",
            version="1.0.0",
        )
        
        # 注册插件提供的端点
        api_router = self.module_lib.get_module("api-router")
        if api_router:
            app.include_router(api_router.router)
        
        # 健康检查
        @app.get("/health")
        async def health():
            return {"status": "ok", "plugins": len(self.plugin_manager.get_enabled_plugins())}
        
        # 插件管理端点
        @app.get("/api/v1/plugins")
        async def list_plugins():
            return self.plugin_manager.get_status()
        
        return app
```

### 7.2 API 路由器 (`core/api_router.py`)

```python
"""
动态 API 路由器

允许插件在运行时注册/注销 API 端点。
所有端点注册通过此路由器管理，确保:
- 路径冲突检测
- 插件生命周期关联 (插件卸载自动注销端点)
- 统一的中间件处理
"""

from fastapi import APIRouter, Request
from neurova.core.base_module import BaseModule


class APIEndpoint:
    """API 端点描述符"""
    def __init__(self, method: str, path: str, handler_name: str, 
                 description: str = "", tags: List[str] = None):
        self.method = method
        self.path = path
        self.handler_name = handler_name
        self.description = description
        self.tags = tags or []


class DynamicAPIRouter:
    """动态 API 路由器"""
    
    def __init__(self):
        self.router = APIRouter(prefix="/api/v1")
        self._endpoints: Dict[str, List[APIEndpoint]] = {}  # plugin_id -> endpoints
        self._path_registry: Dict[str, str] = {}  # path -> plugin_id
    
    def register(self, plugin_id: str, endpoint: APIEndpoint, handler: Callable):
        """注册端点"""
        # 路径冲突检测
        if endpoint.path in self._path_registry:
            existing = self._path_registry[endpoint.path]
            raise ValueError(
                f"Path conflict: {endpoint.path} already registered by {existing}"
            )
        
        # 注册到 FastAPI Router
        self._add_route(endpoint, handler)
        
        # 记录
        self._endpoints.setdefault(plugin_id, []).append(endpoint)
        self._path_registry[endpoint.path] = plugin_id
    
    def unregister(self, plugin_id: str):
        """注销插件的所有端点"""
        if plugin_id in self._endpoints:
            for ep in self._endpoints[plugin_id]:
                if ep.path in self._path_registry:
                    del self._path_registry[ep.path]
            del self._endpoints[plugin_id]
    
    def get_endpoints_by_plugin(self, plugin_id: str) -> List[APIEndpoint]:
        """获取插件注册的所有端点"""
        return self._endpoints.get(plugin_id, [])
```

### 7.3 内置插件示例: 记忆插件

```python
# neurova/builtin_plugins/memory/memory_plugin.py

from neurova.plugins.base_plugin import BasePlugin, PluginType
from neurova.plugins.plugin_manifest import PluginPermission
from neurova.memory.core.manager import MemoryManager


class MemoryPlugin(BasePlugin):
    """
    记忆系统插件
    
    将记忆系统作为插件加载，提供:
    - 记忆管理 API
    - 事件监听 (message.received → 自动记忆)
    """
    
    plugin_type = PluginType.CORE
    api_endpoints = [
        APIEndpoint("GET", "/memories", "list_memories"),
        APIEndpoint("POST", "/memories", "add_memory"),
        APIEndpoint("GET", "/memories/search", "search_memories"),
        APIEndpoint("DELETE", "/memories/{memory_id}", "delete_memory"),
        APIEndpoint("GET", "/memories/stats", "get_stats"),
    ]
    
    async def on_initialize(self) -> None:
        # 加载配置
        db_path = self._get_config_manager().get(
            f"plugin.{self.module_id}.db_path", 
            "data/yi_ling_memory.db"
        )
        
        # 初始化记忆管理器
        self.memory_manager = MemoryManager(db_path)
        
        # 注册事件监听
        self.subscribe_event("chat.message.received", self._auto_remember)
        self.subscribe_event("chat.message.sent", self._auto_remember)
    
    async def on_start(self) -> None:
        # 注册 API 端点
        await super().on_start()
        self.log_info("Memory plugin started")
    
    async def _auto_remember(self, event) -> None:
        """自动记忆对话"""
        data = event.data
        self.memory_manager.remember(
            content=f"{data.get('sender')}: {data.get('content')}",
            category="conversation",
        )
```

---

## 8. 实施阶段规划

### 8.1 阶段概览

```
Phase 0: 基础设施完善          (2 周)
Phase 1: 后端插件框架集成       (2 周)  
Phase 2: 核心模块插件化         (3 周)
Phase 3: 前端插件框架           (2 周)
Phase 4: 页面迁移到插件         (3 周)
Phase 5: 统一应用入口           (1 周)
Phase 6: 测试与优化             (2 周)
                              ─────────
                              总计: 15 周
```

### 8.2 详细阶段计划

#### Phase 0: 基础设施完善 (第 1-2 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 合并 `interfaces/api_standard.py` 到 `core/` | `core/api_standard.py` | P0 |
| 创建 `core/api_router.py` 动态路由器 | 支持插件动态注册端点 | P0 |
| 创建 `plugins/base_plugin.py` 后端插件基类 | 扩展 BaseModule | P0 |
| 创建 `plugins/plugin_api_registry.py` API 注册器 | 端点注册/注销 | P0 |
| 完善前端 UI 框架的组件注册和状态绑定 | 组件系统可工作 | P1 |

#### Phase 1: 后端插件框架集成 (第 3-4 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 修改 PluginManager 集成到应用启动流程 | 应用启动时自动发现插件 | P0 |
| 实现 DynamicAPIRouter 与 FastAPI 的集成 | 插件端点可访问 | P0 |
| 创建应用启动/关闭生命周期管理 | startup/shutdown 事件 | P0 |
| 实现插件热加载/热卸载 | 无需重启加载新插件 | P1 |
| 编写插件管理 API | GET/POST/DELETE 插件 | P1 |

#### Phase 2: 核心模块插件化 (第 5-7 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 将记忆系统迁移为内置插件 | `builtin_plugins/memory/` | P0 |
| 将 Agent 核心迁移为内置插件 | `builtin_plugins/agent/` | P0 |
| 将渠道管理迁移为内置插件 | `builtin_plugins/channel/` | P0 |
| 将技能系统迁移为内置插件 | `builtin_plugins/skill/` | P0 |
| 确保插件间通过事件总线通信 | 无直接依赖 | P0 |
| 创建 `neurova/app.py` 统一入口 (基础版) | 可启动的插件化应用 | P0 |

#### Phase 3: 前端插件框架 (第 8-9 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 创建 `static/js/plugin-loader.js` | 前端插件加载器 | P0 |
| 定义前端 `plugin.json` 格式规范 | 前后端统一的清单格式 | P0 |
| 创建前端插件基类 `BaseUIPlugin` | 前端插件标准 | P0 |
| 创建 `static/plugins/manifest.json` 索引 | 插件发现机制 | P0 |
| 实现前端插件路由注册 | 插件自动添加导航项 | P1 |

#### Phase 4: 页面迁移到插件 (第 10-12 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 聊天页面迁移为插件 | `static/plugins/chat/` | P0 |
| 记忆管理页面迁移为插件 | `static/plugins/memory/` | P0 |
| Agent 管理页面迁移为插件 | `static/plugins/agents/` | P1 |
| 渠道管理页面迁移为插件 | `static/plugins/channels/` | P1 |
| Skill 市场页面迁移为插件 | `static/plugins/skillhub/` | P1 |
| 设置页面迁移为插件 | `static/plugins/settings/` | P2 |
| 删除旧版 `static/pages/` 目录 | 清理遗留代码 | P2 |

#### Phase 5: 统一应用入口 (第 13 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 完善 `neurova/app.py` 为最终版 | 完整插件化应用 | P0 |
| 弃用 `neurova_server.py` | 标记 deprecated | P0 |
| 弃用 `api/app.py` | 标记 deprecated | P0 |
| 更新 CLI 启动命令 | 指向新入口 | P0 |

#### Phase 6: 测试与优化 (第 14-15 周)

| 任务 | 输出 | 优先级 |
|------|------|--------|
| 编写插件框架单元测试 | 测试覆盖率 > 80% | P0 |
| 编写插件框架集成测试 | 端到端测试 | P0 |
| 性能基准测试 | 性能报告 | P1 |
| 编写插件开发文档 | 开发者指南 | P1 |
| 示例插件模板 | 快速开始模板 | P1 |

---

## 9. 迁移计划

### 9.1 迁移策略: 渐进式迁移

采用**双轨运行**策略，确保迁移过程中系统可用：

```
阶段 A: 基础设施准备 (Phase 0-1)
  ├─ 新插件框架就位
  ├─ 旧系统继续运行
  └─ 新系统可并行启动
  
阶段 B: 核心模块迁移 (Phase 2)
  ├─ 记忆/Agent/渠道/技能 → 内置插件
  ├─ 旧代码保留但标记 @deprecated
  └─ 新入口可通过配置切换
  
阶段 C: 前端迁移 (Phase 3-4)
  ├─ 页面 → 前端插件
  ├─ 旧页面仍可通过路由访问
  └─ 新插件页面逐步替换
  
阶段 D: 切换与清理 (Phase 5-6)
  ├─ 默认使用新入口
  ├─ 旧入口保留兼容一段时间
  └─ 最终移除旧代码
```

### 9.2 兼容性保证

| 兼容项 | 策略 | 时间窗口 |
|--------|------|----------|
| 旧 API 路由 | 保留原有路由，内部转发到新插件 | 6 个月 |
| 旧前端页面 | 保留 `static/pages/`，但推荐用插件 | 3 个月 |
| 旧配置文件 | 自动迁移到插件配置格式 | 1 个月 |
| 旧插件 API | 提供兼容层 | 3 个月 |
| 数据库格式 | 保持不变 | 永久 |

### 9.3 回滚方案

每个阶段完成后保留回滚点：

```
if 新系统异常:
    1. 切换环境变量 NEUROVA_USE_PLUGIN_ARCH=false
    2. 重启服务 (回退到旧入口)
    3. 数据库/配置无需回滚 (兼容保证)
```

---

## 10. 示例插件实现

### 10.1 后端插件示例: 天气查询技能

```
plugins/weather-skill/
├── plugin.json
├── weather_skill.py
└── requirements.txt
```

**plugin.json:**
```json
{
  "plugin_id": "weather-skill",
  "name": "天气查询技能",
  "version": "1.0.0",
  "description": "查询实时天气和天气预报",
  "author": "Neurova Team",
  "plugin_type": "skill",
  "dependencies": {"neurova-core": ">=1.0.0"},
  "neurova_min_version": "1.0.0",
  "entry_point": "weather_skill.py",
  "module_class": "WeatherSkillPlugin",
  "permissions": ["http:request", "read:config"],
  "config_schema": {
    "type": "object",
    "properties": {
      "api_key": { "type": "string" },
      "default_city": { "type": "string", "default": "北京" }
    }
  },
  "default_config": {
    "api_key": "",
    "default_city": "北京"
  },
  "tags": ["skill", "weather", "utility"]
}
```

**weather_skill.py:**
```python
"""天气查询技能插件"""

import httpx
from neurova.plugins.base_plugin import BasePlugin, PluginType, APIEndpoint
from neurova.plugins.plugin_manifest import PluginPermission


class WeatherSkillPlugin(BasePlugin):
    """天气查询技能"""
    
    plugin_type = PluginType.SKILL
    required_permissions = [PluginPermission.HTTP_REQUEST]
    
    api_endpoints = [
        APIEndpoint("GET", "/plugins/weather/current", "get_current_weather"),
        APIEndpoint("GET", "/plugins/weather/forecast", "get_forecast"),
    ]
    
    async def on_initialize(self) -> None:
        config_mgr = self._get_config_manager()
        self.api_key = config_mgr.get(f"plugin.{self.module_id}.api_key", "")
        self.default_city = config_mgr.get(f"plugin.{self.module_id}.default_city", "北京")
        
        # 注册为 Skill 到技能注册中心
        self.subscribe_event("skill.register", self._register_self)
        # 监听天气查询意图
        self.subscribe_event("intent.weather_query", self._handle_weather_query)
    
    async def on_start(self) -> None:
        await super().on_start()
        self.log_info("Weather skill plugin started")
    
    async def _register_self(self, event) -> None:
        """向 SkillRegistry 注册自己"""
        self.emit_event("skill.registered", {
            "skill_id": self.module_id,
            "name": "天气查询",
            "description": "查询实时天气和预报",
            "triggers": ["天气", "weather", "气温"],
        })
    
    async def _handle_weather_query(self, event) -> None:
        """处理天气查询意图"""
        city = event.data.get("city", self.default_city)
        weather = await self._fetch_weather(city)
        
        self.emit_event("skill.weather_response", {
            "city": city,
            "weather": weather,
            "skill_id": self.module_id,
        })
    
    async def get_current_weather(self, request) -> dict:
        """API 端点: 获取当前天气"""
        city = request.query_params.get("city", self.default_city)
        weather = await self._fetch_weather(city)
        return {"city": city, "weather": weather}
    
    async def _fetch_weather(self, city: str) -> dict:
        """调用天气 API"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.weather.com/v3/weather/conditions",
                params={"location": city, "apiKey": self.api_key},
            )
            resp.raise_for_status()
            return resp.json()
```

### 10.2 前端插件示例: 天气 Widget

```
static/plugins/weather-widget/
├── plugin.json
├── weather-widget.js
└── weather-widget.css
```

**plugin.json:**
```json
{
  "plugin_id": "weather-widget",
  "name": "天气小组件",
  "version": "1.0.0",
  "description": "在侧边栏显示当前天气",
  "plugin_type": "widget",
  "entry_point": "weather-widget.js",
  "dependencies": {},
  "neurova_min_version": "1.0.0",
  "permissions": ["read:events"],
  "frontend": {
    "enabled": true,
    "widget_position": "sidebar-bottom",
    "size": "compact"
  }
}
```

**weather-widget.js:**
```javascript
/**
 * 天气 Widget 插件
 */
(function() {
  class WeatherWidgetPlugin extends BaseUIPlugin {
    async initialize(ui) {
      this.widget = null;
      this.weatherData = null;
    }

    async start() {
      // 创建 Widget
      this.widget = this.ui.createComponent('card', {
        id: 'weather-widget',
        title: '天气',
        icon: 'cloud',
      }, document.querySelector('#sidebar-bottom'));
      
      // 订阅天气数据事件
      this.on('skill.weather_response', (data) => {
        this.updateWeather(data);
      });
      
      // 定时刷新
      this._refreshInterval = setInterval(() => {
        this.emit('intent.weather_query', { city: '北京' });
      }, 30 * 60 * 1000); // 每 30 分钟
      
      // 首次加载
      this.emit('intent.weather_query', { city: '北京' });
    }

    updateWeather(data) {
      this.weatherData = data.weather;
      if (this.widget) {
        this.widget.update({
          content: `${data.city}: ${data.weather.temperature}°C, ${data.weather.condition}`,
        });
      }
    }

    async stop() {
      if (this._refreshInterval) {
        clearInterval(this._refreshInterval);
      }
      if (this.widget) {
        this.ui.destroyComponent(this.widget.id);
      }
    }

    async destroy() {
      this.widget = null;
      this.weatherData = null;
    }
  }

  // 注册到全局插件命名空间
  window.NeurovaPlugins = window.NeurovaPlugins || {};
  window.NeurovaPlugins['weather-widget'] = WeatherWidgetPlugin;
})();
```

---

## 11. 风险评估与应对

### 11.1 技术风险

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|----------|
| 插件加载导致启动时间延长 | 用户体验下降 | 中 | 插件按需加载，支持延迟初始化 |
| 插件间循环依赖 | 系统无法启动 | 低 | 启动前循环依赖检测，拓扑排序 |
| 内存泄漏 (插件卸载不彻底) | 长期运行内存增长 | 中 | 严格的 destroy 生命周期，内存检测 |
| 前端插件加载失败 | 页面功能缺失 | 低 | 降级方案，核心功能作为内置插件 |
| API 端点路径冲突 | 部分功能不可用 | 低 | 注册时冲突检测，报错阻止启动 |

### 11.2 迁移风险

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|----------|
| 迁移期间数据不一致 | 记忆/配置丢失 | 低 | 数据库格式不变，渐进式迁移 |
| 旧 API 兼容性问题 | 第三方集成断裂 | 低 | 6 个月兼容窗口，明确通知 |
| 用户自定义页面不兼容 | 用户需重新开发 | 中 | 提供迁移工具和文档 |

### 11.3 运维风险

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|----------|
| 插件版本管理复杂 | 升级困难 | 中 | 语义化版本，依赖约束检查 |
| 插件安全性 (恶意插件) | 系统被攻击 | 低 | 权限声明 + 路径沙箱 + 代码审计 |
| 调试困难 (插件化后) | 排查问题耗时 | 中 | 统一日志 + 插件诊断 API |

---

## 12. 总结

### 12.1 核心发现

1. **现有基础扎实**: 系统已经实现了完善的 `core/` 基础设施（事件总线、模块库、状态管理、配置管理等），以及 `plugins/` 插件框架（PluginManager、Manifest、Lifecycle）。这些组件代码质量高，可以直接复用。

2. **关键缺口**: 插件框架存在但未实际集成到应用启动流程中；缺少后端插件基类（`BasePlugin`）和前端插件加载器（`PluginLoader`）；前后端插件标准不统一。

3. **架构演进路线清晰**: 从当前的"单体 + 模块化"架构，通过渐进式迁移，演进为"插件化"架构，所有功能（包括核心记忆/Agent/渠道）都作为插件加载。

### 12.2 架构优势

| 优势 | 说明 |
|------|------|
| **可扩展性** | 新功能以插件形式开发，不影响现有系统 |
| **可维护性** | 每个插件独立开发、测试、部署 |
| **灵活性** | 支持运行时加载/卸载，按需启用功能 |
| **标准化** | 统一接口、事件、状态、配置管理 |
| **安全性** | 权限声明、路径沙箱、依赖检查 |

### 12.3 关键成功因素

1. **渐进式迁移**: 不一次性推翻现有系统，而是逐步替换
2. **双轨运行**: 新旧系统并行，确保平滑过渡
3. **测试覆盖**: 每个阶段完成后进行充分的测试
4. **文档完善**: 为插件开发者提供清晰的开发指南
5. **向后兼容**: 保留足够的兼容期，不强制用户迁移

### 12.4 下一步行动

1. 召开架构评审会议，确认设计方案
2. 开始 Phase 0 实施: 合并 api_standard、创建 api_router 和 base_plugin
3. 创建第一个示例插件（天气查询），验证框架可行性
4. 编写插件开发指南文档

---

*文档结束*
