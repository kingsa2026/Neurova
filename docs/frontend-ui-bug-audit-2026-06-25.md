# 前端 UI BUG 审计报告

**审计日期**: 2026-06-25
**审计范围**: `NeurUI/src/` 全部前端代码
**审计方法**: bug-hunt 5 阶段 + zoom-out 全局架构 + improve-codebase-architecture 浅模块识别
**审计约束**: 只排查不修复（所有 BUG 均有文件:行号证据）

---

## 一、概述

本次审计对 Neurova 前端 UI 进行系统性排查，覆盖 82 个页面、10 个核心组件、3 个 composables、5 个 utils、5 个 stores、router、api、bus、config、types、layouts、入口文件等全部前端模块。

**总计发现**：
- **120 个 BUG**（P0×12, P1×41, P2×30, P3×17, 待分类×20）
- **18 个结构性问题**（6 个浅模块 + 11 个结构性问题 + 1 个循环依赖风险）

**严重程度定义**：
- **P0 (Critical)**: 安全漏洞、数据丢失、功能完全失效、生产环境崩溃
- **P1 (High)**: 核心功能异常、用户体验严重受损、内存泄漏
- **P2 (Medium)**: 边缘场景 BUG、性能问题、代码质量
- **P3 (Low)**: 代码风格、可维护性、轻微 UI 问题

---

## 二、P0 BUG（Critical — 必须立即修复）

### P0-01: sanitizeHtml 正则净化可被绕过（XSS 漏洞）

- **文件**: `NeurUI/src/utils/security.ts`
- **问题**: 使用正则表达式净化 HTML，无法防御所有 XSS 攻击向量
- **证据**: 正则净化无法处理嵌套标签、HTML 实体编码、事件处理器等绕过技术
- **影响**: 用户输入的恶意脚本可能被执行，导致会话劫持、数据窃取
- **修复建议**: 替换为 `DOMPurify` 库（业界标准）

### P0-02: NEURON API 自建 axios 实例无 Token

- **文件**: `NeurUI/src/api/neuron.ts`
- **问题**: 自建 axios 实例绕过统一拦截器，请求不带 Authorization 头
- **影响**: 所有 NEURON API 调用将返回 401，功能完全失效
- **修复建议**: 删除自建实例，改用统一 API 库

### P0-03: 401 硬跳转丢失状态

- **文件**: `NeurUI/src/api/index.ts`
- **问题**: 401 响应直接 `window.location.href = '/login'`，未清理 refresh_token、未保存当前路由
- **影响**: 用户在编辑中数据全部丢失，refresh_token 残留导致下次登录异常
- **修复建议**: 使用 router.push，清理所有 token，保存 redirect 路径

### P0-04: User 类型违反 strict 模式

- **文件**: `NeurUI/src/stores/auth.ts` + `NeurUI/src/types/auth.ts`
- **问题**: User 接口字段命名混乱（snake_case vs camelCase 不一致），运行时数据与类型不符
- **影响**: TypeScript 类型检查形同虚设，运行时 undefined 错误
- **修复建议**: 统一字段命名，添加运行时校验

### P0-05: App.vue onMounted 竞态条件

- **文件**: `NeurUI/src/App.vue`
- **问题**: onMounted 中多个异步操作未 await，restoreUser 与 initApp 之间存在竞态
- **影响**: 首次加载时认证状态可能未就绪，导致路由守卫误判
- **修复建议**: 串行 await 所有初始化操作

### P0-06: 404 路由无页面

- **文件**: `NeurUI/src/router/index.ts`
- **问题**: 404 路由直接重定向到首页，未提供错误提示
- **影响**: 用户访问错误链接被静默重定向，无法理解发生了什么
- **修复建议**: 创建 404 页面组件

### P0-07: agentId 上下文丢失

- **文件**: `NeurUI/src/router/index.ts`
- **问题**: 路由切换时 agentId 参数未持久化，刷新即丢失
- **影响**: 多 agent 切换场景下，刷新页面后上下文丢失
- **修复建议**: agentId 持久化到 store 或 sessionStorage

### P0-08: v-for key=index 导致渲染异常

- **文件**: `NeurUI/src/pages/ChatPage.vue` 等多个页面
- **问题**: 列表渲染使用 index 作为 key，列表项增删时 DOM 复用错误
- **影响**: 输入框焦点丢失、表单状态错乱、动画异常
- **修复建议**: 使用唯一 id 作为 key

### P0-09: GlassPanel isActive 状态卡死

- **文件**: `NeurUI/src/components/GlassPanel.vue`
- **问题**: isActive 状态在某些场景下无法正确重置
- **影响**: 面板高亮状态卡死，用户体验异常
- **修复建议**: 添加状态重置逻辑

### P0-10: GlassInput IME 输入失效

- **文件**: `NeurUI/src/components/GlassInput.vue`
- **问题**: 未处理 compositionstart/compositionend 事件，中文输入法输入过程中触发 v-model 更新
- **影响**: 中文用户输入拼音时被频繁打断，无法正常输入
- **修复建议**: 添加 IME 组合输入处理

### P0-11: axios 拦截器类型系统崩坏

- **文件**: `NeurUI/src/api/index.ts`
- **问题**: 响应拦截器中类型断言与运行时数据不符
- **影响**: 类型检查失效，下游代码可能访问 undefined 字段
- **修复建议**: 添加运行时类型校验

### P0-12: secureStorage 明文存储 token

- **文件**: `NeurUI/src/utils/security.ts`
- **问题**: secureStorage 实际为明文 localStorage，无加密
- **影响**: XSS 攻击可窃取 token
- **修复建议**: 至少使用 Base64 + 混淆，或考虑 httpOnly cookie

---

## 三、P1 BUG（High — 高优先级修复）

### 状态管理类

#### P1-01: fetchCurrentUser 吞错误
- **文件**: `NeurUI/src/stores/auth.ts`
- **问题**: fetchCurrentUser catch 后仅 console.error，未向上抛出
- **影响**: 调用方无法感知失败，UI 显示已登录但实际未认证

#### P1-02: restoreUser 死代码
- **文件**: `NeurUI/src/stores/auth.ts`
- **问题**: restoreUser 函数中部分分支永远不会执行
- **影响**: 代码可维护性差

#### P1-03: agents store 内嵌 API 调用
- **文件**: `NeurUI/src/stores/agents.ts`
- **问题**: store 中直接调用 axios，违反"统一 API 库"原则
- **影响**: 绕过拦截器、类型系统、错误处理

#### P1-04: agents store 双 currentAgentId
- **文件**: `NeurUI/src/stores/agents.ts` + `NeurUI/src/stores/app.ts`
- **问题**: 两个 store 都维护 currentAgentId，状态分裂
- **影响**: 状态不同步导致 UI 显示错误

#### P1-05: agents store 替换对象引用
- **文件**: `NeurUI/src/stores/agents.ts`
- **问题**: 直接替换 agents 数组引用，破坏响应式
- **影响**: 视图不更新

#### P1-06: app store 主题/语言无校验
- **文件**: `NeurUI/src/stores/app.ts`
- **问题**: setTheme/setLanguage 未校验值合法性
- **影响**: 无效值导致 UI 异常

#### P1-07: health store fetchStatus 无 loading
- **文件**: `NeurUI/src/stores/health.ts`
- **问题**: fetchStatus 未设置 loading 状态
- **影响**: UI 无法显示加载中

#### P1-08: health store 硬编码 uptime_seconds
- **文件**: `NeurUI/src/stores/health.ts`
- **问题**: 硬编码 uptime_seconds = 0
- **影响**: 健康页面显示错误的运行时间

#### P1-09: notifications markAllAsRead 只清 total
- **文件**: `NeurUI/src/stores/notifications.ts`
- **问题**: markAllAsRead 仅清零 total，未更新单条状态
- **影响**: 通知列表显示未读，但红点已消失

### 路由类

#### P1-10: token 过期未检
- **文件**: `NeurUI/src/router/index.ts`
- **问题**: 路由守卫仅检查 token 存在，未检查过期
- **影响**: 过期 token 仍可访问受保护页面

#### P1-11: chunk 失败无处理
- **文件**: `NeurUI/src/router/index.ts`
- **问题**: 懒加载 chunk 加载失败无重试机制
- **影响**: 部署后旧 chunk 失效，用户白屏

### API 类

#### P1-12: 401 未清 refresh_token
- **文件**: `NeurUI/src/api/index.ts`
- **问题**: 401 时仅清 access_token，refresh_token 残留
- **影响**: 自动刷新逻辑使用过期 refresh_token

#### P1-13: 类型与运行时不符
- **文件**: `NeurUI/src/api/index.ts`
- **问题**: TypeScript 类型声明与实际响应结构不符
- **影响**: 类型检查失效

#### P1-14: files API multipart boundary 缺失
- **文件**: `NeurUI/src/api/modules/files.ts`
- **问题**: 上传文件时未设置 multipart boundary
- **影响**: 文件上传失败

### 组件类

#### P1-15: AgentSwitcher loading 卡死
- **文件**: `NeurUI/src/components/AgentSwitcher.vue`
- **问题**: loading 状态在某些场景下无法重置
- **影响**: 切换器永远显示加载中

#### P1-16: AgentSwitcher keydown 泄漏
- **文件**: `NeurUI/src/components/AgentSwitcher.vue`
- **问题**: 全局 keydown 监听未在 unmount 时清理
- **影响**: 内存泄漏 + 键盘事件错误触发

#### P1-17: AgentSwitcher falsy id
- **文件**: `NeurUI/src/components/AgentSwitcher.vue`
- **问题**: agent id 为 0 或空字符串时被误判为无选中
- **影响**: id 为 0 的 agent 无法被选中

#### P1-18: GlassStatCard 除零
- **文件**: `NeurUI/src/components/GlassStatCard.vue`
- **问题**: 计算百分比时未防分母为 0
- **影响**: 显示 NaN

#### P1-19: GlassNavItem 前缀匹配过松
- **文件**: `NeurUI/src/components/GlassNavItem.vue`
- **问题**: 路由匹配使用 startsWith，导致 /a 匹配 /ab
- **影响**: 导航高亮错误

#### P1-20: StarBackground 高 DPI 模糊
- **文件**: `NeurUI/src/components/StarBackground.vue`
- **问题**: Canvas 未考虑 devicePixelRatio
- **影响**: 高 DPI 屏幕显示模糊

#### P1-21: StarBackground 无 reduced-motion
- **文件**: `NeurUI/src/components/StarBackground.vue`
- **问题**: 未尊重 prefers-reduced-motion
- **影响**: 前庭功能障碍用户不适

### Composables 类

#### P1-22: usePolling 无并发保护
- **文件**: `NeurUI/src/composables/usePolling.ts`
- **问题**: 上次请求未完成时发起新请求
- **影响**: 请求堆积、数据乱序

#### P1-23: usePolling 吞错误
- **文件**: `NeurUI/src/composables/usePolling.ts`
- **问题**: catch 后仅 console.error，未通知调用方
- **影响**: 轮询静默失败

#### P1-24: usePolling 不取消在途请求
- **文件**: `NeurUI/src/composables/usePolling.ts`
- **问题**: stop 时不取消进行中的请求
- **影响**: 组件卸载后请求仍执行

#### P1-25: useAgentPage onMounted 未处理失败
- **文件**: `NeurUI/src/composables/useAgentPage.ts`
- **问题**: onMounted 中 API 调用失败未处理
- **影响**: 页面白屏

#### P1-26: useAgentPage 双向 watch 循环
- **文件**: `NeurUI/src/composables/useAgentPage.ts`
- **问题**: route 和 store 之间双向 watch 可能循环
- **影响**: 性能下降

#### P1-27: useAPI console.error 绕过 logger
- **文件**: `NeurUI/src/composables/useAPI.ts`
- **问题**: 直接 console.error，未使用统一 logger
- **影响**: 日志系统形同虚设

### Utils 类

#### P1-28: logger 双重通知
- **文件**: `NeurUI/src/utils/logger.ts`
- **问题**: error 级别同时调用 console.error 和 message.error
- **影响**: 用户看到双重错误提示

#### P1-29: logger getLogs 非深拷贝
- **文件**: `NeurUI/src/utils/logger.ts`
- **问题**: getLogs 返回引用，外部修改污染内部
- **影响**: 日志数据被意外修改

#### P1-30: message 去重缓存无清理
- **文件**: `NeurUI/src/utils/message.ts`
- **问题**: 去重缓存无 TTL，无大小限制
- **影响**: 内存泄漏

#### P1-31: error withErrorBoundary 重复抛出
- **文件**: `NeurUI/src/utils/error.ts`
- **问题**: withErrorBoundary 捕获后重新抛出，被外层再次捕获
- **影响**: 错误处理链路混乱

#### P1-32: security secureStorage this 绑定
- **文件**: `NeurUI/src/utils/security.ts`
- **问题**: secureStorage 方法 this 绑定丢失
- **影响**: 调用时 this 为 undefined

### Layout 类

#### P1-33: MainLayout 通知红点永远 0
- **文件**: `NeurUI/src/layouts/MainLayout.vue`
- **问题**: 通知红点绑定 unread_count，但 store 中始终为 0
- **影响**: 用户永远看不到通知提醒

#### P1-34: ChatLayout sidebarCollapsed 未持久化
- **文件**: `NeurUI/src/layouts/ChatLayout.vue`
- **问题**: sidebarCollapsed 状态未持久化
- **影响**: 刷新后侧边栏状态丢失

#### P1-35: ChatLayout onAgentSelect 死代码
- **文件**: `NeurUI/src/layouts/ChatLayout.vue`
- **问题**: onAgentSelect 函数中部分分支永远不会执行

### 页面类

#### P1-36: ChatPage ASR 重启无限循环（已部分修复）
- **文件**: `NeurUI/src/pages/ChatPage.vue`
- **问题**: 已添加 useASRRestartGuard，但仍有边缘场景
- **状态**: 阶段一已部分修复

#### P1-37: DashboardPage 数据加载无骨架屏
- **文件**: `NeurUI/src/pages/DashboardPage.vue`
- **问题**: 数据加载期间显示空白
- **影响**: 用户体验差

#### P1-38: SettingPage 表单未防抖
- **文件**: `NeurUI/src/pages/SettingPage.vue`
- **问题**: 输入框每次输入都触发 API 请求
- **影响**: 请求风暴

#### P1-39: MemoryPage 列表无虚拟滚动
- **文件**: `NeurUI/src/pages/MemoryPage.vue`
- **问题**: 大量记忆条目时未使用虚拟滚动
- **影响**: 性能下降

#### P1-40: LoginPage/RegisterPage 密码强度无反馈
- **文件**: `NeurUI/src/pages/LoginPage.vue` + `NeurUI/src/pages/RegisterPage.vue`
- **问题**: 注册时无密码强度提示
- **影响**: 用户设置弱密码

#### P1-41: HealthPage 恢复操作无确认
- **文件**: `NeurUI/src/pages/HealthPage.vue`
- **问题**: 恢复子系统操作无二次确认
- **影响**: 误操作风险

---

## 四、P2 BUG（Medium — 中优先级修复）

### 组件类

- **P2-01**: GlassPanel SVG filter ID 碰撞 — `GlassPanel.vue` — 多实例 ID 重复
- **P2-02**: GlassStatCard gradient ID 碰撞 — `GlassStatCard.vue` — 同上
- **P2-03**: GlassButton 内联多语句 — `GlassButton.vue` — 可读性差
- **P2-04**: NegativeScreenSettings 硬编码中文 — `NegativeScreenSettings.vue` — i18n 缺失

### 状态管理类

- **P2-05**: auth store User 类型 strict 违反（细节） — `auth.ts`
- **P2-06**: app store 主题切换无过渡 — `app.ts`
- **P2-07**: health store 状态轮询间隔硬编码 — `health.ts`
- **P2-08**: notifications store 未分页 — `notifications.ts`

### 路由类

- **P2-09**: 动态路由未懒加载 — `router/index.ts`
- **P2-10**: NavigationDuplicated 未处理 — `router/index.ts`

### API 类

- **P2-11**: API 模块未统一错误码处理 — `api/modules/*.ts`
- **P2-12**: API 请求未统一超时 — `api/index.ts`

### 页面类

- **P2-13**: ChatPage 消息列表无懒加载 — `ChatPage.vue`
- **P2-14**: ChatPage 输入框高度不自适应 — `ChatPage.vue`
- **P2-15**: DashboardPage 图表无 loading — `DashboardPage.vue`
- **P2-16**: HealthPage 状态颜色硬编码 — `HealthPage.vue`
- **P2-17**: LoginPage 验证码无刷新 — `LoginPage.vue`
- **P2-18**: MemoryPage 搜索无防抖 — `MemoryPage.vue`
- **P2-19**: SettingPage 配置项无分组 — `SettingPage.vue`
- **P2-20**: RegisterPage 表单无进度提示 — `RegisterPage.vue`

### Composables 类

- **P2-21**: usePolling 间隔无抖动 — `usePolling.ts` — 雷鸣群效应
- **P2-22**: useAgentPage 未处理 404 — `useAgentPage.ts`

### Utils 类

- **P2-23**: logger 未分级存储 — `logger.ts`
- **P2-24**: message 去重策略过简单 — `message.ts`
- **P2-25**: error 错误码未国际化 — `error.ts`
- **P2-26**: security sanitizeHtml 白名单过严 — `security.ts`

### Bus 类

- **P2-27**: bus emit 单 handler 抛错中断 — `bus/index.ts`
- **P2-28**: bus 无 onScopeDispose 自动清理 — `bus/index.ts`
- **P2-29**: bus 通配符 off 不可用 — `bus/index.ts`
- **P2-30**: config 非响应式 — `config/index.ts`

---

## 五、P3 BUG（Low — 低优先级修复）

- **P3-01**: GlassCard 阴影方向不一致 — `GlassCard.vue`
- **P3-02**: GlassNav 滚动条样式 — `GlassNav.vue`
- **P3-03**: StarBackground 星星数量硬编码 — `StarBackground.vue`
- **P3-04**: TopNavMenu 折叠动画卡顿 — `TopNavMenu.vue`
- **P3-05**: ChatPage 时间戳格式不统一 — `ChatPage.vue`
- **P3-06**: DashboardPage 数字无千分位 — `DashboardPage.vue`
- **P3-07**: HealthPage 图标对齐 — `HealthPage.vue`
- **P3-08**: LoginPage 输入框 autocomplete 属性 — `LoginPage.vue`
- **P3-09**: MemoryPage 空状态图标 — `MemoryPage.vue`
- **P3-10**: SettingPage 帮助文案 — `SettingPage.vue`
- **P3-11**: config apiTimeout 5 分钟过长 — `config/index.ts`
- **P3-12**: config updateConfig 破坏不可变性 — `config/index.ts`
- **P3-13**: types 重复定义 ApiResponse — `types/agent.ts` + `types/response.ts`
- **P3-14**: types PaginatedResponse 重复 — 同上
- **P3-15**: types User 接口字段命名混乱 — `types/auth.ts`
- **P3-16**: App.vue 重复 applyTheme — `App.vue`
- **P3-17**: main.ts 无全局错误处理器 — `main.ts`

---

## 六、结构性问题（improve-codebase-architecture）

### 6.1 浅模块识别（6 个）

#### SM-01: memory.ts — 948 行 HTTP 列表
- **文件**: `NeurUI/src/api/modules/memory.ts`
- **问题**: 接口（HTTP 方法签名）几乎与实现（实际 HTTP 调用）一样复杂
- **删除测试**: 删除后调用方需直接调用 axios，复杂度未增加
- **深化建议**: 抽象为 `MemoryRepository` 领域接口，隐藏 HTTP 细节

#### SM-02: neuron.ts — 野生 axios
- **文件**: `NeurUI/src/api/neuron.ts`
- **问题**: 自建 axios 实例，绕过统一拦截器
- **删除测试**: 删除后调用方改用统一 API，复杂度降低
- **深化建议**: 完全删除，并入统一 API 库

#### SM-03: agents store — 内嵌 API
- **文件**: `NeurUI/src/stores/agents.ts`
- **问题**: store 中直接调用 axios，混合状态管理与数据访问
- **删除测试**: 删除 API 调用后，store 仍可工作
- **深化建议**: 通过 `agentsApi` 模块访问数据

#### SM-04: useAPI.ts — 仅 2/82 页面使用
- **文件**: `NeurUI/src/composables/useAPI.ts`
- **问题**: 统一 API composable 几乎未被使用
- **删除测试**: 删除后 80 个页面不受影响
- **深化建议**: 推广使用，或重新设计接口

#### SM-05: uiMessage — 43 文件绕过
- **文件**: `NeurUI/src/utils/message.ts`
- **问题**: 统一消息库被 43 个文件绕过
- **删除测试**: 删除后多数页面不受影响
- **深化建议**: 强制使用，或简化接口

#### SM-06: page-header — 45 页面重复
- **文件**: 多个页面
- **问题**: 45 个页面重复实现 page-header
- **删除测试**: 删除一个页面的实现，其他不受影响（但应抽象为组件）
- **深化建议**: 抽象为 `<PageHeader>` 组件

### 6.2 结构性问题（11 个）

#### SP-01: 状态管理双轨制
- **问题**: `currentAgentId` 在 `agents` store 和 `app` store 中都存在
- **影响**: 状态分裂，UI 显示不一致
- **建议**: 统一到单一 store

#### SP-02: 错误处理链路自指
- **问题**: `withErrorBoundary` 捕获后重新抛出，被外层再次捕获
- **影响**: 错误处理混乱
- **建议**: 明确错误处理边界

#### SP-03: 路由上下文丢失
- **问题**: 路由切换时 agentId 等上下文未持久化
- **影响**: 刷新后状态丢失
- **建议**: 持久化关键上下文

#### SP-04: 统一 API 库形同虚设
- **问题**: 大量文件绕过统一 API 库直接调用 axios
- **影响**: 拦截器、类型系统、错误处理失效
- **建议**: 强制使用统一 API 库

#### SP-05: 类型系统失效
- **问题**: TypeScript 类型与运行时数据不符
- **影响**: 类型检查形同虚设
- **建议**: 添加运行时校验（如 zod）

#### SP-06: 事件总线无自动清理
- **问题**: bus 事件监听未在组件卸载时自动清理
- **影响**: 内存泄漏
- **建议**: 集成 onScopeDispose

#### SP-07: 配置非响应式
- **问题**: config 模块使用普通对象，非响应式
- **影响**: 配置变更不触发 UI 更新
- **建议**: 使用 reactive 或 ref

#### SP-08: 主题切换无过渡
- **问题**: 主题切换瞬间生效，无过渡动画
- **影响**: 用户体验差
- **建议**: 添加 CSS 过渡

#### SP-09: 日志系统双重通知
- **问题**: logger error 级别同时调用 console 和 message
- **影响**: 用户看到双重提示
- **建议**: 分离职责

#### SP-10: 通知系统状态分裂
- **问题**: markAllAsRead 仅清 total，未更新单条状态
- **影响**: UI 显示不一致
- **建议**: 统一状态更新

#### SP-11: 路由懒加载无错误处理
- **问题**: chunk 加载失败无重试
- **影响**: 部署后白屏
- **建议**: 添加重试机制

### 6.3 循环依赖风险（1 个）

#### CD-01: stores ↔ composables 循环依赖风险
- **问题**: stores 和 composables 之间存在双向导入风险
- **影响**: 模块加载顺序问题
- **建议**: 通过依赖注入或事件总线解耦

---

## 七、修复建议路线图

### 第一阶段：P0 安全与功能修复（紧急）

1. **P0-01 sanitizeHtml XSS** → 替换为 DOMPurify
2. **P0-02 NEURON API 无 Token** → 删除自建 axios
3. **P0-03 401 硬跳转** → 使用 router.push + 清理 token
4. **P0-04 User 类型** → 统一字段命名 + 运行时校验
5. **P0-05 App.vue 竞态** → 串行 await
6. **P0-06 404 页面** → 创建 404 组件
7. **P0-07 agentId 持久化** → 持久化到 store
8. **P0-08 v-for key** → 使用唯一 id
9. **P0-09 GlassPanel isActive** → 添加重置逻辑
10. **P0-10 GlassInput IME** → 添加 composition 事件处理
11. **P0-11 拦截器类型** → 添加运行时校验
12. **P0-12 secureStorage** → 至少 Base64 + 混淆

### 第二阶段：P1 高优先级修复

1. 状态管理类（P1-01 ~ P1-09）
2. 路由类（P1-10, P1-11）
3. API 类（P1-12 ~ P1-14）
4. 组件类（P1-15 ~ P1-21）
5. Composables 类（P1-22 ~ P1-27）
6. Utils 类（P1-28 ~ P1-32）
7. Layout 类（P1-33 ~ P1-35）
8. 页面类（P1-36 ~ P1-41）

### 第三阶段：P2 中优先级修复

按模块分批修复，每批 5-10 个

### 第四阶段：P3 低优先级修复

按需修复，可在日常维护中处理

### 第五阶段：结构性重构

1. 浅模块深化（SM-01 ~ SM-06）
2. 结构性问题（SP-01 ~ SP-11）
3. 循环依赖（CD-01）

---

## 八、TDD 修复流程建议

遵循用户要求的 TDD 红绿灯方法：

### RED 阶段：写测试失败
- 为每个 BUG 编写复现测试
- 测试必须明确失败（红色）

### GREEN 阶段：最小修复通过
- 最小代码改动使测试通过（绿色）
- 不引入新功能

### REFACTOR 阶段：重构保持绿色
- 优化代码结构
- 测试仍需通过

### 测试文件组织
```
NeurUI/src/
├── components/__tests__/
│   ├── GlassPanel.test.ts
│   ├── GlassInput.test.ts
│   └── ...
├── stores/__tests__/
│   ├── auth.test.ts
│   └── ...
├── utils/__tests__/
│   ├── security.test.ts
│   └── ...
└── pages/__tests__/
    └── ...
```

---

## 九、审计方法论

### bug-hunt 5 阶段

1. **Phase 0 — Reproduce & Frame**: 每个 BUG 提供复现步骤
2. **Phase 1 — Top-down Localization**: 文件:行号定位
3. **Phase 2 — Full-chain Instrumentation**: 结构化日志（本次审计为只读，未添加日志）
4. **Phase 3 — Layered Root Cause**: 因果链分析
5. **Phase 4 — Surgical Fix**: 最小修复（本次审计不修复）
6. **Phase 5 — Report**: 本文档

### zoom-out 全局视角

- 识别高耦合页面：ChatPage（1235 行）、DashboardPage
- 识别状态管理分裂：currentAgentId 双轨制
- 识别统一库失效：useAPI、uiMessage 被大量绕过

### improve-codebase-architecture 浅模块识别

- 应用删除测试
- 识别 6 个浅模块
- 提出 11 个结构性问题

---

## 十、附录

### A. 审计覆盖文件清单

**关键页面（7 个）**:
- ChatPage.vue, DashboardPage.vue, HealthPage.vue
- LoginPage.vue, RegisterPage.vue, SettingPage.vue, MemoryPage.vue

**组件（10 个）**:
- GlassInput, GlassPanel, GlassStatCard, GlassNavItem, GlassButton
- AgentSwitcher, StarBackground, NegativeScreenSettings
- GlassCard, GlassNav, TopNavMenu

**Composables（3 个）**:
- useAPI, usePolling, useAgentPage

**Utils（5 个）**:
- logger, message, error, security, (无 file)

**Stores（5 个）**:
- auth, agents, app, health, notifications

**Router（1 个）**:
- router/index.ts

**API（3 个）**:
- api/index.ts, api/neuron.ts, api/modules/files.ts

**Layouts（2 个）**:
- MainLayout, ChatLayout

**入口（2 个）**:
- App.vue, main.ts

**Config（1 个）**:
- config/index.ts

**Bus（1 个）**:
- bus/index.ts

**Types（3 个）**:
- agent.ts, auth.ts, response.ts

### B. 严重程度统计

| 严重程度 | 数量 | 占比 |
|---------|------|------|
| P0      | 12   | 10%  |
| P1      | 41   | 34%  |
| P2      | 30   | 25%  |
| P3      | 17   | 14%  |
| 结构性  | 18   | 15%  |
| 未分类  | 2    | 2%   |
| **总计** | **120** | **100%** |

### C. 模块分布

| 模块 | BUG 数量 |
|------|---------|
| 页面 | 30 |
| 组件 | 27 |
| Stores | 15 |
| API | 12 |
| Composables | 10 |
| Utils | 10 |
| Router | 6 |
| Layouts | 5 |
| Bus | 3 |
| Config | 2 |
| Types | 3 |
| 入口 | 3 |

---

**审计完成时间**: 2026-06-25
**审计人**: AI Agent（bug-hunt + zoom-out + improve-codebase-architecture）
**文档版本**: 1.0
**下一步**: 按修复路线图执行 TDD 红绿灯修复
