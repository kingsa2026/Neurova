# Neurova UI 框架使用指南

## 概述

Neurova UI 框架是一个统一的、模块化的前端框架，遵循严格的规范确保代码质量、可维护性和扩展性。

## 核心架构

```
┌────────────────────────────────────────────────────────────┐
│                    应用层 (Pages)                           │
│   chat.js | mem-list.js | settings.js | wishes.js ...      │
├────────────────────────────────────────────────────────────┤
│                    框架层 (Core)                            │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │NeurovaUI    │ │NeurovaPage   │ │NeurovaToast         │  │
│  │(组件库)     │ │(页面加载器)  │ │(通知系统)           │  │
│  └─────────────┘ └──────────────┘ └─────────────────────┘  │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────────────┐  │
│  │NeurovaState │ │NeurovaEvent  │ │NeurovaLogger        │  │
│  │(状态管理)   │ │Bus(事件总线) │ │(日志系统)           │  │
│  └─────────────┘ └──────────────┘ └─────────────────────┘  │
├────────────────────────────────────────────────────────────┤
│                    接口层 (API)                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  API.* (统一的 API 封装，所有后端交互必须通过此层)   │  │
│  └──────────────────────────────────────────────────────┘  │
├────────────────────────────────────────────────────────────┤
│                    后端服务 (Server)                        │
│  Flask RESTful API | 插件系统 | 记忆系统 | 渠道管理         │
└────────────────────────────────────────────────────────────┘
```

## 规范

### 1. API 调用规范
- **所有后端交互必须通过 `API.*` 进行**
- 禁止在页面中直接使用 `fetch()` 调用后端接口
- API 返回 Promise，使用 `.then().catch()` 或配合 async/await 使用

```javascript
// ✅ 正确：使用 API 层
API.memories.list({ tab: 'all' })
    .then(function(result) { ... })
    .catch(function(err) { ... });

// ❌ 错误：直接使用 fetch
fetch('/api/v1/memories')
    .then(function(res) { ... });
```

### 2. UI 组件规范
- **所有UI组件必须通过 `NeurovaUI.*` 创建**
- 禁止直接使用 HTML 标签拼接
- 所有样式通过 CSS 文件管理，禁止内联 style

```javascript
// ✅ 正确：使用组件库
var btn = NeurovaUI.createButton({
    text: '保存',
    icon: 'save',
    variant: 'primary',
    size: 'md',
    onClick: handleSave
});

// ❌ 错误：直接创建元素
var btn = document.createElement('button');
btn.innerHTML = '<i data-lucide="save"></i> 保存';
btn.style.cssText = '...';
```

### 3. 状态管理规范
- **所有UI状态必须通过 `NeurovaState.*` 管理**
- 禁止直接操作 DOM 存储状态
- 状态变更自动触发事件和 watch 回调

```javascript
// ✅ 正确：使用状态管理
NeurovaState.set('currentTab', 'all');
NeurovaState.watch('currentTab', function(newVal, oldVal) {
    console.log('Tab changed:', oldVal, '->', newVal);
});

// ❌ 错误：使用全局变量
var currentTab = 'all';
```

### 4. 事件总线规范
- **所有UI事件必须通过 `NeurovaEventBus.*` 发布**
- 禁止直接调用其他模块的方法
- 模块间通信只能通过事件总线

```javascript
// ✅ 正确：使用事件总线
NeurovaEventBus.emit('memory:updated', { count: 10, action: 'created' });

NeurovaEventBus.on('memory:updated', function(data) {
    updateMemoryCount(data.count);
});

// ❌ 错误：直接调用
otherModule.updateMemoryCount(10);
```

### 5. 日志规范
- **所有日志必须通过 `NeurovaLogger.*` 输出**
- 禁止使用 console.log
- 支持日志级别：debug, info, warn, error

```javascript
// ✅ 正确：使用日志系统
NeurovaLogger.info('[MemList] Loaded 10 memories');
NeurovaLogger.error('[MemList] Load failed:', err);

// ❌ 错误：直接使用 console
console.log('Loaded memories');
console.error('Load failed');
```

## 核心模块使用

### NeurovaUI 组件库

| 方法 | 说明 | 参数 |
|------|------|------|
| `createButton(options)` | 创建按钮 | `{text, icon, variant, size, disabled, onClick, className}` |
| `createCard(options)` | 创建卡片 | `{title, subtitle, content, className}` |
| `createInput(options)` | 创建输入框 | `{type, placeholder, value, label, required, onChange, className}` |
| `createSelect(options)` | 创建下拉框 | `{label, options, value, onChange}` |
| `createTable(options)` | 创建表格 | `{columns, data, onRowClick}` |
| `createLoading(text)` | 创建加载指示器 | `text: 加载文本` |
| `createEmpty(options)` | 创建空状态 | `{icon, title, description, action}` |
| `createTabs(options)` | 创建标签页 | `{tabs, onChange}` |
| `createBadge(options)` | 创建徽章 | `{text, variant, className}` |
| `createSwitch(options)` | 创建开关 | `{label, checked, onChange}` |

#### 示例

```javascript
// 创建表格
var table = NeurovaUI.createTable({
    columns: [
        { key: 'name', label: '名称' },
        { key: 'status', label: '状态' },
        { key: 'actions', label: '操作' }
    ],
    data: [
        { name: '记忆1', status: '<span class="badge">正常</span>', actions: '...' },
        { name: '记忆2', status: '<span class="badge">高温</span>', actions: '...' }
    ],
    onRowClick: function(row) {
        console.log('Row clicked:', row);
    }
});

// 创建标签页
var tabs = NeurovaUI.createTabs({
    tabs: [
        { id: 'all', label: '全部', active: true },
        { id: 'hot', label: '高温' },
        { id: 'cold', label: '低温' }
    ],
    onChange: function(tabId) {
        console.log('Tab switched to:', tabId);
        loadTab(tabId);
    }
});
```

### NeurovaPage 页面加载器

```javascript
// 创建页面实例
var page = NeurovaPage.create({
    name: 'my-page',
    title: '我的页面',
    breadcrumb: '分类名称',
    container: '#page-container', // 或 DOM 元素
    render: function(container) {
        // 渲染页面内容
        var card = NeurovaUI.createCard({
            title: '标题',
            content: '<p>内容</p>'
        });
        container.appendChild(card);
    },
    onReady: function() {
        // 页面渲染完成后的回调
        console.log('Page is ready');
    },
    onDestroy: function() {
        // 页面销毁前的回调
        console.log('Page is being destroyed');
    },
    cleanup: function() {
        // 清理定时器、事件监听等
        if (timer) clearInterval(timer);
    }
});

// 初始化页面
page.init();

// 销毁页面
page.destroy();

// 重新渲染
page.rerender();

// 监听事件
page.on('memory:updated', function(data) {
    console.log('Memory updated:', data);
});

// 监听状态变化
page.watch('currentPage', function(newVal, oldVal) {
    console.log('Page changed:', oldVal, '->', newVal);
});
```

### NeurovaState 状态管理

```javascript
// 设置状态
NeurovaState.set('currentAgent', 'Yiling');

// 获取状态
var agent = NeurovaState.get('currentAgent');

// 监听状态变化
var unwatch = NeurovaState.watch('currentAgent', function(newVal, oldVal) {
    console.log('Agent changed:', oldVal, '->', newVal);
});

// 取消监听
unwatch();

// 批量更新
NeurovaState.batch({
    currentAgent: 'Yiling',
    currentPage: 'chat',
    memoryCount: 128
});

// 重置状态
NeurovaState.reset();
```

### NeurovaEventBus 事件总线

```javascript
// 订阅事件
var unsubscribe = NeurovaEventBus.on('page:loaded', function(data) {
    console.log('Page loaded:', data.page);
});

// 发布事件
NeurovaEventBus.emit('page:loaded', { page: 'chat', title: '智能对话' });

// 一次性事件
NeurovaEventBus.once('api:ready', function() {
    console.log('API is ready');
});

// 取消订阅
unsubscribe();

// 清除所有订阅
NeurovaEventBus.clear();
```

### NeurovaToast 通知系统

```javascript
// 成功通知
NeurovaToast.success('操作成功');

// 错误通知
NeurovaToast.error('操作失败');

// 警告通知
NeurovaToast.warn('请注意');

// 信息通知
NeurovaToast.info('提示信息');
```

### NeurovaLogger 日志系统

```javascript
// 设置日志级别
NeurovaLogger.setLevel('debug'); // debug | info | warn | error

// 输出日志
NeurovaLogger.debug('调试信息');
NeurovaLogger.info('普通信息');
NeurovaLogger.warn('警告信息');
NeurovaLogger.error('错误信息');
```

## API 接口参考

### 记忆模块
```javascript
API.memories.list(params)           // 获取记忆列表
API.memories.get(id)                // 获取单个记忆
API.memories.add(content, metadata) // 添加记忆
API.memories.delete(id)             // 删除记忆
API.memories.search(query, params)  // 搜索记忆
API.memories.stats()                // 获取统计信息
API.memories.getConfig()            // 获取配置
API.memories.updateConfig(config)   // 更新配置
API.memories.graph()                // 获取记忆图谱
API.memories.stream(limit, type)    // 获取记忆流
API.memories.metaCognitionMonitor() // 元认知监控
API.memories.metaCognitionReflect() // 元认知反思
API.memories.metaCognitionOptimize()// 元认知优化
API.memories.versions(memoryId)     // 获取记忆版本
API.memories.temperatureConfig()    // 获取温度配置
```

### 配置模块
```javascript
API.config.getLLM()           // 获取 LLM 配置
API.config.updateLLM(config)  // 更新 LLM 配置
API.config.testLLM(config)    // 测试 LLM 配置
API.config.getSystem()        // 获取系统配置
API.config.updateSystem(config)// 更新系统配置
API.config.getHeartbeat()     // 获取心跳配置
API.config.saveHeartbeat(data)// 保存心跳配置
API.config.getSleep()         // 获取睡眠配置
API.config.saveSleep(data)    // 保存睡眠配置
```

### Agent 模块
```javascript
API.agents.list()            // 获取 Agent 列表
API.agents.get(id)           // 获取单个 Agent
API.agents.create(data)      // 创建 Agent
API.agents.update(id, data)  // 更新 Agent
API.agents.delete(id)        // 删除 Agent
```

### 插件模块
```javascript
API.plugins.list()            // 获取插件列表
API.plugins.get(id)           // 获取单个插件
API.plugins.enable(id)        // 启用插件
API.plugins.disable(id)       // 禁用插件
API.plugins.frontendConfig()  // 获取前端配置
```

## 页面开发模板

```javascript
/**
 * 我的页面 - 使用统一UI框架
 */
(function() {
    'use strict';

    var pageInstance = null;

    function renderPage(container) {
        // 使用 NeurovaUI 组件构建页面
        var card = NeurovaUI.createCard({
            title: '我的页面',
            subtitle: '页面描述',
            content: '<p>页面内容</p>'
        });
        container.appendChild(card);
    }

    function onReady() {
        NeurovaLogger.info('[MyPage] Page ready');
    }

    function onDestroy() {
        NeurovaLogger.info('[MyPage] Page destroyed');
    }

    function cleanup() {
        // 清理定时器、事件监听等
    }

    // 导出初始化函数
    window.initMyPage = function() {
        if (pageInstance) {
            pageInstance.destroy();
        }

        pageInstance = NeurovaPage.create({
            name: 'my-page',
            title: '我的页面',
            breadcrumb: '分类名称',
            render: renderPage,
            onReady: onReady,
            onDestroy: onDestroy,
            cleanup: cleanup
        });

        pageInstance.init();

        return {
            destroy: function() {
                if (pageInstance) {
                    pageInstance.destroy();
                    pageInstance = null;
                }
            }
        };
    };

})();
```

## 文件结构

```
static/
├── css/
│   ├── base.css              # 基础样式
│   ├── sidebar.css           # 侧边栏样式
│   ├── components.css        # 通用组件样式
│   ├── ui-components.css     # UI组件库样式 (新增)
│   ├── chat.css              # 聊天页面样式
│   ├── animations.css        # 动画样式
│   └── responsive.css        # 响应式样式
├── js/
│   ├── core/
│   │   ├── config.js         # 配置管理
│   │   ├── logger.js         # 日志系统
│   │   ├── event-bus.js      # 事件总线
│   │   ├── state-manager.js  # 状态管理
│   │   ├── toast.js          # 通知系统
│   │   ├── error-handler.js  # 错误处理
│   │   ├── page-loader.js    # 页面加载器 (新增)
│   │   └── ui-components.js  # UI组件库
│   ├── pages/
│   │   ├── chat.js           # 聊天页面
│   │   ├── mem-list.js       # 记忆列表 (已重构)
│   │   └── ...               # 其他页面
│   ├── api.js                # API封装层
│   ├── plugin-loader.js      # 插件加载器
│   ├── plugin-manager.js     # 插件管理器
│   └── app.js                # 应用入口
└── index.html                # 主页面
```

## 最佳实践

1. **使用组件库创建所有UI元素** - 不要直接使用 document.createElement
2. **所有API调用通过API层** - 不要直接使用 fetch
3. **使用状态管理存储状态** - 不要使用全局变量
4. **使用事件总线通信** - 不要直接调用其他模块方法
5. **使用日志系统输出日志** - 不要使用 console.log
6. **使用 NeurovaPage 管理页面生命周期** - 确保资源正确释放
7. **组件样式通过CSS文件管理** - 不要使用内联style
8. **使用 NeurovaToast 显示通知** - 不要使用 alert
9. **所有错误通过 error-handler 处理** - 统一错误处理
10. **页面导出 destroy 方法** - 确保可以正确清理

## 更新日志

### 2026-05-08
- 创建 UI 组件样式库 (ui-components.css)
- 创建页面基础加载器 (page-loader.js)
- 重构 mem-list.js 使用统一框架
- 增强 API.js 使用 ES5 语法
- 完善文档使用说明
