# Neurova 模块化架构文档

> **创建日期**: 2026-05-07  
> **目的**: 记录模块化重构后的架构设计  
> **状态**: 已完成

---

## 一、重构背景

原有 `neurova-ui.html` 单文件已超 250KB，存在以下问题：
- 编辑器卡顿，查找/修改困难
- 多人协作容易冲突
- 无法按需加载，首屏加载慢
- 不符合 `coremodule need.md` 的模块化要求

## 二、新架构设计

### 2.1 目录结构

```
static/
├── index.html              # 主框架文件 (~10KB)
├── css/                    # CSS 样式 (6个文件)
│   ├── base.css           # CSS变量 + 全局重置 + 背景层 + 布局基础
│   ├── sidebar.css        # 侧边栏 + 导航 + 悬浮Agent切换器
│   ├── components.css     # 卡片/按钮/表单/徽章/表格等通用组件
│   ├── chat.css           # 聊天框相关样式
│   ├── animations.css     # 动画相关样式
│   └── responsive.css     # 响应式媒体查询
├── js/                     # JavaScript 逻辑
│   ├── api.js             # API 封装层 (统一后端调用)
│   ├── app.js             # 主应用加载器 (页面加载/导航/事件)
│   └── pages/             # 页面模块脚本 (按需加载)
│       ├── chat.js        # 聊天页面功能
│       ├── agents.js      # Agent管理功能
│       ├── skillhub.js    # 公共技能库功能
│       ├── mem-overview.js    # 记忆总览
│       ├── mem-list.js        # 记忆列表
│       ├── mem-temperature.js # 温度配置
│       ├── mem-emotion.js     # 情感引擎
│       ├── llm.js         # LLM配置
│       ├── stats.js       # 系统统计
│       ├── logs.js        # 日志查看
│       └── settings.js    # 系统设置
└── pages/                  # 页面 HTML 片段 (按需加载)
    ├── chat.html
    ├── wishes.html
    ├── agents.html
    ├── skillhub.html
    ├── llm.html
    ├── mem-overview.html
    ├── mem-list.html
    ├── mem-temperature.html
    ├── mem-graph.html
    ├── mem-maintenance.html
    ├── mem-emotion.html
    ├── mem-association.html
    ├── metacognition.html
    ├── mem-scheduler.html
    ├── mem-version.html
    ├── sleep-status.html
    ├── sleep-config.html
    ├── dream-insight.html
    ├── dream-log.html
    ├── channels.html
    ├── skills.html
    ├── heartbeat.html
    ├── task-scheduler.html
    ├── router.html
    ├── context.html
    ├── collaboration.html
    ├── plugins.html
    ├── modules.html
    ├── events.html
    ├── token-stats.html
    ├── stats.html
    ├── security.html
    ├── logs.html
    ├── settings.html
    └── cli-tools.html
```

### 2.2 文件统计

| 类别 | 文件数 | 说明 |
|------|--------|------|
| HTML 页面 | 26+1 | 主框架 + 26个页面片段 |
| CSS 样式 | 6 | 按功能模块拆分 |
| JavaScript | 2+11 | 核心库 + 11个页面脚本 |
| 总计 | ~45 | 模块化架构 |

### 2.3 对比

| 指标 | 重构前 | 重构后 | 改善 |
|------|--------|--------|------|
| 主文件大小 | 250KB+ | ~10KB | 96% 减少 |
| 首次加载资源 | 250KB | ~30KB | 88% 减少 |
| 编辑器性能 | 卡顿 | 流畅 | ✅ |
| 多人协作 | 冲突 | 独立 | ✅ |
| 按需加载 | 不支持 | 支持 | ✅ |
| 模块化 | 单文件 | 完整模块 | ✅ |

---

## 三、核心模块说明

### 3.1 API 封装层 (`api.js`)

**职责**: 统一的 API 调用接口，所有后端交互必须通过此层

**核心方法**:
```javascript
// 通用请求
API.request(method, path, data)

// HTTP 方法
API.get(path, params)
API.post(path, data)
API.put(path, data)
API.delete(path)

// 流式请求 (SSE)
API.stream(path, data, onMessage, onError, onDone)

// 认证
API.setToken(token)
API.clearToken()
```

**业务 API**:
```javascript
// 对话
API.chat.send(message, agentId)
API.chat.stream(message, agentId, onMessage, onError, onDone)

// 记忆
API.memories.list(params)
API.memories.add(content, metadata)
API.memories.delete(id)
API.memories.search(query, params)
API.memories.stats()

// Agent
API.agents.list()
API.agents.create(data)
API.agents.update(id, data)
API.agents.delete(id)

// 技能
API.skills.list()
API.skills.execute(id, params)
API.skills.import(data)

// 渠道
API.channels.list()
API.channels.create(data)
API.channels.update(id, data)
API.channels.toggle(id)

// 配置
API.config.getLLM()
API.config.updateLLM(config)
API.config.testLLM(config)
API.config.getSystem()
API.config.updateSystem(config)

// 系统
API.system.health()
API.system.stats()
```

**符合规范**:
- ✅ 统一 API 接口标准
- ✅ 不直接调用后端接口
- ✅ 统一错误处理
- ✅ 支持流式输出

### 3.2 主应用加载器 (`app.js`)

**职责**: 页面加载、导航管理、侧边栏控制、Agent 弹出层

**核心类**: `NeurovaApp`

**核心方法**:
```javascript
// 初始化
app.init()

// 页面加载
app.loadPage(pageName)

// Agent 管理
app.switchAgent(agentId)

// UI 控制
app.initNavigation()
app.initSidebar()
app.initAgentPopup()
app.initLucide()
```

**页面加载流程**:
1. 点击导航链接 → 触发 `loadPage(pageName)`
2. 更新导航激活状态
3. 更新页面标题和面包屑
4. 销毁当前页面模块（调用 destroy）
5. 显示加载状态
6. 动态加载 `static/pages/{pageName}.html`
7. 动态加载 `static/js/pages/{pageName}.js`
8. 执行页面初始化函数 `init{PageName}()`
9. 重新渲染 Lucide 图标

**符合规范**:
- ✅ 模块动态加载
- ✅ 不直接操作 HTML（通过容器）
- ✅ 统一事件处理
- ✅ 支持页面生命周期（init/destroy）

### 3.3 页面模块规范

每个页面模块应遵循以下结构：

```javascript
// static/js/pages/example.js

function initExample() {
    // 初始化
    let state = {};
    
    async function load() {
        try {
            // 调用 API
            const data = await API.example.list();
            state.data = data;
            render();
        } catch (error) {
            console.error('加载失败:', error);
            showError(error.message);
        }
    }
    
    function render() {
        // 渲染页面内容
    }
    
    function bindEvents() {
        // 绑定事件监听
    }
    
    function destroy() {
        // 清理资源
    }
    
    // 初始化
    bindEvents();
    load();
    
    // 返回公共接口
    return { load, destroy };
}

// 暴露给全局
window.initExample = initExample;
```

---

## 四、Flask 服务器配置

### 4.1 路由更新

```python
@app.route('/')
def index():
    """首页 - 模块化 WebUI 面板"""
    return send_from_directory(str(project_root / 'static'), 'index.html')
```

### 4.2 静态文件服务

Flask 自动服务 `static/` 目录下的所有文件：
- `/static/css/*.css` - CSS 样式
- `/static/js/*.js` - JavaScript 脚本
- `/static/pages/*.html` - 页面 HTML 片段

---

## 五、使用指南

### 5.1 开发新页面

1. 创建 HTML 页面: `static/pages/newpage.html`
2. 创建 JS 模块: `static/js/pages/newpage.js`
3. 在 `index.html` 导航菜单添加链接
4. JS 模块导出初始化函数: `window.initNewpage = initNewpage`

### 5.2 添加 API 接口

在 `api.js` 中添加业务方法：

```javascript
API.newmodule = {
    list() {
        return API.get('/newmodule');
    },
    create(data) {
        return API.post('/newmodule', data);
    },
};
```

### 5.3 页面间通信

通过事件总线（可扩展）：

```javascript
// 发送事件
window.dispatchEvent(new CustomEvent('neurova:page:loaded', { 
    detail: { page: 'chat' } 
}));

// 监听事件
window.addEventListener('neurova:page:loaded', (e) => {
    console.log('页面加载:', e.detail.page);
});
```

---

## 六、规范符合性

| 规范要求 | 实现状态 | 说明 |
|----------|----------|------|
| 统一模块接口 | ✅ | `NeurovaApp.loadPage()` 统一加载 |
| 模块动态加载 | ✅ | `fetch()` 按需加载 HTML/JS |
| 不直接调用后端 | ✅ | 所有调用通过 `API` 层 |
| 统一事件总线 | ⚠️ | 可扩展实现 |
| 统一状态管理 | ⚠️ | 可扩展实现 |
| 统一组件库 | ⚠️ | 可扩展实现 |
| 统一样式库 | ✅ | CSS 模块化拆分 |
| 不直接操作 DOM | ⚠️ | 部分页面仍需改进 |
| 统一日志库 | ⚠️ | 可扩展实现 |
| 统一错误库 | ⚠️ | 可扩展实现 |
| 统一配置库 | ⚠️ | 可扩展实现 |

---

## 七、后续优化

1. **事件总线**: 实现完整的事件发布-订阅系统
2. **状态管理**: 引入统一状态树（类似 Vuex/Redux）
3. **组件库**: 创建可复用 UI 组件库
4. **错误处理**: 统一错误码和错误页面
5. **日志系统**: 前端日志收集和上报
6. **类型检查**: 引入 TypeScript 进行类型检查
7. **打包工具**: 使用 Vite/Rollup 进行生产打包
8. **单元测试**: 为每个页面模块编写测试

---

**星光不灭 ✨**  
**Neurova 已完成模块化重构，为后续开发奠定基础！**
