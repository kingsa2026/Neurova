# Neurova 鸿蒙 App 设计文档（C 方案：纯 ArkTS 重写）

> 版本：v1.0 ｜ 日期：2026-06-25 ｜ 方案：C（纯 ArkTS/ArkUI 重写，不复用 Vue 代码）

---

## 1. 项目目标与范围

### 1.1 目标
将 Neurova Web 端（NeurUI，Vue 3 + 57 页面）转写为鸿蒙原生 App，使用 ArkTS + ArkUI 声明式范式，复用现有 Python 后端（FastAPI，端口 9527）的 80+ REST 端点与 3 个 WebSocket 端点。

### 1.2 范围
- **包含**：57 个页面的 ArkUI 重写、13 个统一库的 ArkTS 实现、移动端配对闭环、WebSocket 实时通信、11 种语言国际化、亮/暗主题、设计令牌迁移。
- **不包含**：后端改动（仅修复 WS URL 硬编码等阻断性 bug）、HarmonyOS Next 之外的 Android/iOS 适配、 Wearable/TV 设备形态。

### 1.3 成功标准
1. 57 个页面全部可在 HarmonyOS 5.0+ 真机运行；
2. 核心页（Dashboard、Chat）冷启动 ≤ 1.5s，首帧 ≤ 800ms；
3. 移动端配对→WS 连接→收发消息全链路打通；
4. 通过用户规则中的"统一库"合规审计（13 个库全部建立且无绕过调用）。

---

## 2. 技术栈

| 层 | 技术 | 版本 | 说明 |
|---|---|---|---|
| 语言 | ArkTS | HarmonyOS 5.0+ | 强类型 TS 超集 |
| UI | ArkUI 声明式 | API 12+ | @Component / @Builder / @Provide |
| 状态 | AppStorage / PersistentStorage / LocalStorage | 原生 | 替代 Pinia |
| 网络 | @ohos.net.http | API 12+ | REST 客户端 |
| WebSocket | @ohos.net.websocket | API 12+ | 实时通信 |
| 存储 | @ohos.data.preferences / relationalStore | API 12+ | 替代 localStorage |
| 路由 | Navigation + NavPathStack | API 12+ | 原生路由，替代 vue-router |
| 国际化 | @ohos.i18n + 自建资源包 | API 12+ | 11 语言 |
| 构建 | DevEco Studio 5.0+ | — | Hvigor 构建系统 |
| 测试 | Hypium（单元）+ UiTest（UI） | — | 鸿蒙官方测试框架 |
| 最低 SDK | HarmonyOS 5.0 (API 12) | — | 覆盖 2024 年后设备 |

---

## 3. 整体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────┐
│  表现层 (Pages)  — 57 个 ArkUI 页面             │
├─────────────────────────────────────────────────┤
│  组件层 (Components)  — Glass* 系列 ArkUI 组件   │
├─────────────────────────────────────────────────┤
│  统一库层 (Unified Libraries)  — 13 个库         │
│  ┌──────┬──────┬──────┬──────┬──────┬─────────┐ │
│  │ API  │ Bus  │State │Config│Logger│ Error   │ │
│  ├──────┼──────┼──────┼──────┼──────┼─────────┤ │
│  │Style │Anim  │Layout│Inter │Msg   │ Module  │ │
│  └──────┴──────┴──────┴──────┴──────┴─────────┘ │
├─────────────────────────────────────────────────┤
│  适配层 (Adapters)  — 平台能力封装               │
│  HTTP / WS / Storage / Haptics / Clipboard      │
├─────────────────────────────────────────────────┤
│  HarmonyOS Runtime (ArkUI / ArkTS)              │
└─────────────────────────────────────────────────┘
         │ REST /api/v1/*  │ WS /api/v1/mobile/ws
         ▼                 ▼
┌─────────────────────────────────────────────────┐
│  Neurova Backend (FastAPI :9527)                │
└─────────────────────────────────────────────────┘
```

### 3.2 工程结构

```
NeurovaHarmony/                          # 鸿蒙工程根（独立于 NeurUI/）
├── entry/                               # 主模块
│   └── src/main/ets/
│       ├── entryability/                # UIAbility 入口
│       │   └── EntryAbility.ets
│       ├── pages/                       # 57 个页面
│       │   ├── auth/                    # LoginPage / RegisterPage
│       │   ├── core/                    # DashboardPage / ChatPage
│       │   ├── agent/                   # Agent 管理与作用域页（21 个）
│       │   ├── knowledge/               # 知识/技能/AIGC（4 个）
│       │   ├── model/                   # 模型/工具层（2 个）
│       │   ├── workflow/                # 工作流（1 个）
│       │   ├── collaboration/           # 协作（6 个）
│       │   ├── channel/                 # 渠道集成（3 个）
│       │   ├── system/                  # 监控+管理（13 个）
│       │   └── neuron/                  # NEURON 系统（1 个）
│       ├── components/                  # Glass* ArkUI 组件
│       │   ├── GlassPanel.ets
│       │   ├── GlassCard.ets
│       │   ├── GlassButton.ets
│       │   ├── GlassInput.ets
│       │   ├── GlassNav.ets
│       │   ├── GlassNavItem.ets
│       │   ├── GlassStatCard.ets
│       │   ├── AgentSwitcher.ets
│       │   └── StarBackground.ets
│       ├── libs/                        # 13 个统一库
│       │   ├── api/                     # 统一函数调用库
│       │   ├── bus/                     # 统一事件总线
│       │   ├── state/                   # 统一状态管理库
│       │   ├── config/                  # 统一配置库
│       │   ├── logger/                  # 统一日志库
│       │   ├── error/                   # 统一错误库
│       │   ├── style/                   # 统一样式库（设计令牌）
│       │   ├── animation/               # 统一动画库
│       │   ├── layout/                  # 统一布局库
│       │   ├── interaction/             # 统一交互库
│       │   ├── message/                 # 统一提示库
│       │   ├── module/                  # 统一模块库
│       │   └── types/                   # 共享类型定义
│       ├── adapters/                    # 平台适配层
│       │   ├── HttpAdapter.ets
│       │   ├── WebSocketAdapter.ets
│       │   ├── StorageAdapter.ets
│       │   └── PlatformAdapter.ets
│       ├── i18n/                        # 国际化资源
│       │   ├── zh-CN.json
│       │   ├── en-US.json
│       │   └── ... (共 11 个)
│       └── resources/                   # 静态资源
├── hvigorfile.ts
└── build-profile.json5
```

---

## 4. 统一库设计（核心）

> 严格遵循用户规则："所有 X 必须通过这个库来调用，不能直接 Y"。每个库都是单例 + 类型安全 + 可审计。

### 4.1 统一函数调用库 (`libs/api/`)

**职责**：所有后端调用的唯一入口，禁止页面/组件直接 `import http`。

**结构**：
```
libs/api/
├── HttpClient.ets          # HTTP 客户端单例（@ohos.net.http 封装）
├── interceptor.ets         # 请求/响应拦截器（auth、logging、error）
├── ApiClient.ets           # 对外门面：get/post/put/delete/upload
├── modules/                # 55 个业务模块（与 NeurUI/src/api/modules 一一对应）
│   ├── auth.ets
│   ├── agents.ets
│   ├── chat.ets
│   ├── memory.ets
│   ├── mobile.ets          # 移动端配对
│   └── ... (共 55 个)
├── index.ets               # 统一导出
└── types.ets               # ApiResponse<T> / PaginatedResponse<T>
```

**核心 API**：
```typescript
// ApiClient.ets
export class ApiClient {
  private static instance: ApiClient;
  static getInstance(): ApiClient;

  get<T>(url: string, config?: RequestConfig): Promise<ApiResponse<T>>;
  post<T>(url: string, data?: object, config?: RequestConfig): Promise<ApiResponse<T>>;
  put<T>(url: string, data?: object, config?: RequestConfig): Promise<ApiResponse<T>>;
  delete<T>(url: string, config?: RequestConfig): Promise<ApiResponse<T>>;
  upload<T>(url: string, fileUri: string, fieldName: string, extraData?: object): Promise<ApiResponse<T>>;
}
```

**拦截器链**：
1. 请求拦截：注入 `Authorization: Bearer <token>`（从 StorageAdapter 读取）、生成 `X-Request-ID`（UUID）、记录出站日志（调 `logger.info`）。
2. 响应拦截：成功返回 `response.data`；401 → 清 token + 跳登录页 + `bus.emit('user:logout')`；429 → `bus.emit('api:rate-limited')`；5xx → `errorHandler.handle()`。

**配置**：
- `baseURL`：从 `config.apiBaseUrl` 读取（默认 `http://192.168.10.132:9527/api/v1`）。
- `timeout`：300000ms（与 NeurUI 一致）。
- `maxRetries`：3（指数退避）。

### 4.2 统一事件总线 (`libs/bus/`)

**职责**：所有跨组件/跨模块通信的唯一通道，禁止 props 透传超过 2 层。

**结构**：
```
libs/bus/
├── EventBus.ets            # 事件总线单例
├── events.ets              # AppEvents 类型定义
└── index.ets
```

**核心 API**：
```typescript
export class EventBus {
  private static instance: EventBus;
  static getInstance(): EventBus;

  on<T>(event: string, handler: (payload: T) => void): string;  // 返回订阅 ID
  off(subscriptionId: string): void;
  emit<T>(event: string, payload: T): void;
  once<T>(event: string, handler: (payload: T) => void): string;
  clear(): void;
}
```

**预定义事件**（与 NeurUI `bus/index.ts` 对齐）：
- `memory:created` / `memory:archived`
- `user:login` / `user:logout`
- `notification:show`（{ type, message }）
- `api:rate-limited`（{ requestId, retryAfter, message }）
- `agent:switched`（{ agentId }）
- `ws:connected` / `ws:disconnected` / `ws:message`

**命名规范**：`domain:action`，如 `memory:created`。

### 4.3 统一状态管理库 (`libs/state/`)

**职责**：所有 UI 状态的唯一来源，禁止直接操作组件状态做跨页共享。

**结构**：
```
libs/state/
├── stores/
│   ├── AppStore.ets        # 主题/语言/侧边栏/全局 loading
│   ├── AuthStore.ets       # token/user/isAuthenticated
│   ├── AgentStore.ets      # agents/currentAgentId/isolationContext
│   ├── HealthStore.ets     # 健康监控
│   ├── NotificationStore.ets  # 通知中心
│   └── PairingStore.ets    # 移动端配对状态（新增）
├── StoreRegistry.ets       # Store 注册中心
└── index.ets
```

**实现方式**：基于 `AppStorage`（全局共享）+ `PersistentStorage`（持久化）+ `@Observed/@ObjectLink`（响应式）。

```typescript
// AppStore.ets
@Observed
export class AppStore {
  theme: ThemeMode = ThemeMode.DARK;        // PersistentStorage 持久化
  locale: string = 'zh-CN';                  // PersistentStorage 持久化
  sidebarCollapsed: boolean = false;
  currentAgentId: string = '';
  globalLoading: boolean = false;
  loadingText: string = '';

  setTheme(t: ThemeMode): void;
  toggleTheme(): void;
  setLocale(l: string): void;
  init(): void;
}
```

**持久化映射**（对应 NeurUI 的 `secureStorage`）：
| Store 字段 | 持久化方式 | 说明 |
|---|---|---|
| AppStore.theme | PersistentStorage.PersistProps | 主题 |
| AppStore.locale | PersistentStorage.PersistProps | 语言 |
| AppStore.sidebarCollapsed | PersistentStorage.PersistProps | 侧边栏 |
| AuthStore.token | preferences（加密） | access token |
| AuthStore.refreshToken | preferences（加密） | refresh token |
| AuthStore.user | preferences | 用户信息 |
| AgentStore.currentAgentId | preferences | 当前 Agent |

### 4.4 统一配置库 (`libs/config/`)

**职责**：集中管理应用配置，禁止散落的硬编码。

```typescript
export interface AppConfig {
  apiBaseUrl: string;        // http://192.168.10.132:9527/api/v1
  wsBaseUrl: string;         // ws://192.168.10.132:9527/api/v1/mobile/ws
  apiTimeout: number;        // 300000
  appName: string;           // 'Neurova'
  appVersion: string;        // '1.0.0'
  isDev: boolean;
  pairingCodeTtl: number;    // 300 秒
  wsReconnectInterval: number;  // 5 秒
  wsReconnectMaxAttempts: number;  // 0 = 无限
}

export class ConfigManager {
  private static instance: ConfigManager;
  static getInstance(): ConfigManager;
  get(): AppConfig;
  update(patch: Partial<AppConfig>): void;
}
```

**配置来源优先级**：构建时 `build-profile.json5` > 运行时 `preferences` > 默认值。

### 4.5 统一日志库 (`libs/logger/`)

**职责**：四级日志，内存收集最近 100 条，error 级触发 `bus.emit('notification:show')`。

```typescript
export enum LogLevel { DEBUG, INFO, WARN, ERROR }

export class Logger {
  private static instance: Logger;
  static getInstance(): Logger;

  setLevel(level: LogLevel): void;
  debug(tag: string, message: string, context?: object): void;
  info(tag: string, message: string, context?: object): void;
  warn(tag: string, message: string, context?: object): void;
  error(tag: string, message: string, error?: Error, context?: object): void;
  getLogs(): LogEntry[];     // 深拷贝
  clear(): void;
}
```

- 开发环境默认 DEBUG，生产环境默认 INFO。
- 内存环形缓冲区，容量 100，FIFO。
- ERROR 级自动 `bus.emit('notification:show', { type: 'error', message })`。

### 4.6 统一错误库 (`libs/error/`)

**职责**：错误归一化与边界保护，禁止裸 `try/catch` 后静默。

```typescript
export type ErrorSeverity = 'low' | 'medium' | 'high';

export class AppError extends Error {
  code: string;
  severity: ErrorSeverity;
  context?: object;
}

export class ErrorHandler {
  private static instance: ErrorHandler;
  static getInstance(): ErrorHandler;

  handle(error: Error | AppError, context?: object): AppError;  // 归一化 + logger + bus
  wrap<T>(fn: () => T, context?: object): T;                    // 同步边界
  wrapAsync<T>(fn: () => Promise<T>, context?: object): Promise<T>;  // 异步边界
}
```

### 4.7 统一样式库 (`libs/style/`)

**职责**：设计令牌的唯一来源，禁止页面内硬编码颜色/尺寸。

**迁移自** `NeurUI/src/styles/variables.css` + `tokens.ts`。

```typescript
// style/tokens.ets
export const tokens = {
  colors: {
    primary: '#6366F1',
    accent: '#22D3EE',
    bgDeep: '#0A0E1A',
    bgBase: '#0F1424',
    bgSurface: '#161B2E',
    bgElevated: '#1E2440',
    bgOverlay: '#000000CC',
    glassBg: '#FFFFFF0D',
    glassBorder: '#FFFFFF1A',
    textPrimary: '#FFFFFF',
    textSecondary: '#FFFFFFB3',
    textTertiary: '#FFFFFF66',
    textMuted: '#FFFFFF40',
    success: '#10B981',
    warning: '#F59E0B',
    error: '#EF4444',
    info: '#3B82F6',
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48 },
  radius: { sm: 6, md: 12, lg: 16, xl: 24, full: 9999 },
  transitions: {
    fast: '150ms cubic-bezier(0.4, 0, 0.2, 1)',
    normal: '250ms cubic-bezier(0.4, 0, 0.2, 1)',
    slow: '400ms cubic-bezier(0.4, 0, 0.2, 1)',
  },
  shadows: {
    sm: '0 1px 2px #00000040',
    md: '0 4px 6px #00000060',
    lg: '0 10px 15px #00000080',
  },
  typography: {
    display: '24vp',
    body: '14vp',
    mono: '14vp',
  },
} as const;
```

**主题切换**：通过 `@Provide/@Consume` 注入 `themeMode`，组件根据 `themeMode` 选择 light/dark 令牌子集。ArkUI 不支持 CSS 变量，需在组件内用三元选择令牌值。

### 4.8 统一动画库 (`libs/animation/`)

**职责**：动画预设，禁止页面内手写 `animateTo` 参数。

```typescript
export interface AnimationPreset {
  duration: number;
  curve: Curve;
  iterations?: number;
}

export const animations = {
  fade: { duration: 250, curve: Curve.EaseInOut },
  fadeSlide: { duration: 300, curve: Curve.EaseOut },
  scale: { duration: 200, curve: Curve.EaseOut },
  slideUp: { duration: 300, curve: Curve.EaseOut },
  slideDown: { duration: 300, curve: Curve.EaseIn },
  slideLeft: { duration: 300, curve: Curve.EaseOut },
  slideRight: { duration: 300, curve: Curve.EaseIn },
} as const;

export class AnimationManager {
  static fade(element: any): void;
  static fadeSlide(element: any): void;
  // ...
}
```

### 4.9 统一布局库 (`libs/layout/`)

**职责**：布局原语，禁止页面直接堆砌 Flex/Column/Row 参数。

```typescript
export class Layout {
  static page(content: () => void): void;           // 标准页布局（含安全区）
  static section(title: string, content: () => void): void;  // 分区
  static card(content: () => void): void;           // 卡片容器
  static list<T>(items: T[], itemBuilder: (item: T) => void): void;  // 列表
  static grid<T>(items: T[], columns: number, itemBuilder: (item: T) => void): void;  // 网格
  static splitSidebar(sidebar: () => void, main: () => void): void;  // 侧边栏+主区
  static safeArea(content: () => void): void;       // 安全区包裹
}
```

### 4.10 统一交互库 (`libs/interaction/`)

**职责**：交互反馈封装（点击波纹、长按、拖拽、震动反馈）。

```typescript
export class Interaction {
  static haptic(level: HapticFeedbackLevel): void;  // 震动反馈
  static ripple(node: any): void;                   // 点击波纹
  static longPress(node: any, callback: () => void): void;
  static swipe(node: any, onLeft: () => void, onRight: () => void): void;
}
```

### 4.11 统一提示库 (`libs/message/`)

**职责**：UI 提示唯一入口，禁止直接调用 `promptAction`。

```typescript
export class UiMessage {
  private static instance: UiMessage;
  static getInstance(): UiMessage;

  success(content: string, duration?: number): void;
  error(content: string, duration?: number): void;
  warning(content: string, duration?: number): void;
  info(content: string, duration?: number): void;
  loading(content: string): string;     // 返回 toast ID
  dismiss(toastId: string): void;
  confirm(title: string, content: string): Promise<boolean>;  // 模态确认
}
```

- 默认 duration 3000ms，maxCount 3。
- 内置 1 秒去重（与 NeurUI `message.ts` 一致）。
- 每次调用 `bus.emit('notification:show', ...)`。

### 4.12 统一模块库 (`libs/module/`)

**职责**：核心模块的动态加载/卸载/通信，禁止直接 `import` 业务模块到页面。

```typescript
export interface ModuleInterface {
  name: string;
  version: string;
  onLoad(context: ModuleContext): Promise<void>;
  onUnload(): Promise<void>;
  onMessage(message: ModuleMessage): void;
}

export class ModuleRegistry {
  private static instance: ModuleRegistry;
  static getInstance(): ModuleRegistry;

  register(module: ModuleInterface): void;
  unregister(name: string): void;
  load(name: string): Promise<void>;
  unload(name: string): Promise<void>;
  send(target: string, message: ModuleMessage): void;
  broadcast(message: ModuleMessage): void;
  list(): string[];
}
```

**模块清单**（21 个，对应 Agent 作用域 + 全局业务）：
- 认知模块组：MemoryModule、ExperienceModule、KnowledgeGraphModule、MetacognitionModule、ReflectionModule、GrowthModule
- 能力模块组：SkillModule、RuleModule、FileModule、MediaModule
- 运行时模块组：SchedulerModule、ChannelModule、ComputerModule、TraceModule、TrajectoryModule、FirewallModule、SleepModule
- 个性模块组：EmotionModule、PersonalityModule
- 全局模块组：ChatModule、DashboardModule

### 4.13 共享类型库 (`libs/types/`)

迁移自 `NeurUI/src/types/`，包含 `Agent`、`ApiResponse<T>`、`Auth`、`Model`、`Response` 类型定义。

---

## 5. 后端 API 对接

### 5.1 端点映射（80+ 端点 → 55 个 ArkTS 模块）

每个 `NeurUI/src/api/modules/*.ts` 对应一个 `libs/api/modules/*.ets`，函数签名保持一致，仅语法转换。

| 业务域 | 后端前缀 | ArkTS 模块 | 端点数 |
|---|---|---|---|
| 认证 | /auth | auth.ets | 8 |
| Agent | /agents | agents.ets | ~12 |
| 聊天 | /chat | chat.ets | ~6 |
| 记忆 | /memory + /memory-* | memory.ets | ~15 |
| 模型 | /models + /providers | models.ets | ~10 |
| 技能 | /skills + /skill-pool + /skill-market | skills.ets | ~12 |
| 知识 | /knowledge + /knowledge-graph | knowledge.ets | ~8 |
| 移动端 | /mobile | mobile.ets | 7 |
| 渠道 | /channels + /channel-adapters | channels.ets | ~10 |
| 协作 | /collaboration + /projects + /teams + /tasks | collaboration.ets | ~15 |
| 系统 | /health + /stats + /monitor + /logs + /audit | system.ets | ~12 |
| ... | （共 55 个模块） | ... | 80+ |

### 5.2 WebSocket 端点对接

| 端点 | 用途 | ArkTS 客户端 |
|---|---|---|
| /api/v1/mobile/ws | 移动端实时通信 | `adapters/WebSocketAdapter.ets` |
| /api/v1/console/ws/{client_id} | 控制台实时 | ConsolePage 内嵌 |
| /api/v1/sync/ws/{session_id} | 会话同步 | SessionSyncPage 内嵌 |

### 5.3 后端阻断性 bug（需先修）

> 这些 bug 会导致鸿蒙端无法跑通，必须在后端修复（不在本方案范围，但需列入前置任务）。

1. **WS URL 硬编码** `ws://localhost:8000/mobile/ws` → 应改为从 `Host` header 推导，使用实际端口 9527。
2. **JWT 鉴权占位** `_get_current_user_id` 永远返回 `default-user` → 需实现真正的 JWT 解析。
3. **WS_SECRET 默认弱密钥** → 生产环境强制配置。
4. **双实现未互通** `channels/mobile_pairing.py` 与 `api/endpoints/mobile_pairing.py` 应合并。

---

## 6. 页面与路由映射

### 6.1 路由设计

使用 ArkUI `Navigation` + `NavPathStack`，替代 vue-router。

```typescript
// entryability/EntryAbility.ets
@Entry
@Component
struct Index {
  @Provide('navStack') navStack: NavPathStack = new NavPathStack();

  build() {
    Navigation(this.navStack) {
      // 初始页：根据 AuthStore.isAuthenticated 决定 Login 或 MainLayout
    }
    .navDestination(this.pageMap)
  }

  @Builder pageMap(name: string) {
    if (name === 'login') LoginPage();
    else if (name === 'main') MainLayout();
    else if (name === 'dashboard') DashboardPage();
    else if (name === 'chat') ChatPage();
    // ... 57 个页面
  }
}
```

**路由守卫**：在 `navStack.push` 前拦截，检查 `AuthStore.isAuthenticated`，未认证跳 `login`。

### 6.2 页面映射表（57 个）

| 分组 | Vue 页面 | ArkUI 页面 | 优先级 | 说明 |
|---|---|---|---|---|
| 认证 | LoginPage | pages/auth/LoginPage.ets | P0 | 首屏入口 |
| 认证 | RegisterPage | pages/auth/RegisterPage.ets | P1 | |
| **核心** | DashboardPage | pages/core/DashboardPage.ets | **P0** | 默认首页 |
| **核心** | ChatPage | pages/core/ChatPage.ets | **P0** | 最高频 |
| Agent | AgentListPage | pages/agent/AgentListPage.ets | P0 | |
| Agent | AgentFormPage | pages/agent/AgentFormPage.ets | P1 | 创建/编辑共用 |
| 认知 | MemoryPage | pages/agent/MemoryPage.ets | P1 | |
| 认知 | ExperienceKnowledgePage | pages/agent/ExperienceKnowledgePage.ets | P2 | |
| 认知 | KnowledgeGraphPage | pages/agent/KnowledgeGraphPage.ets | P2 | 含图谱可视化 |
| 认知 | MetacognitionPage | pages/agent/MetacognitionPage.ets | P2 | |
| 认知 | ReflectionPage | pages/agent/ReflectionPage.ets | P2 | |
| 认知 | GrowthPage | pages/agent/GrowthPage.ets | P2 | |
| 能力 | AgentSkillPage | pages/agent/AgentSkillPage.ets | P1 | |
| 能力 | AgentRulePage | pages/agent/AgentRulePage.ets | P2 | |
| 能力 | AgentFilePage | pages/agent/AgentFilePage.ets | P2 | |
| 能力 | AgentMediaPage | pages/agent/AgentMediaPage.ets | P2 | |
| 运行时 | AgentSchedulerPage | pages/agent/AgentSchedulerPage.ets | P2 | |
| 运行时 | AgentChannelPage | pages/agent/AgentChannelPage.ets | P1 | |
| 运行时 | ContextChannelPage | pages/agent/ContextChannelPage.ets | P2 | |
| 运行时 | AgentComputerPage | pages/agent/AgentComputerPage.ets | P2 | |
| 运行时 | AgentTracePage | pages/agent/AgentTracePage.ets | P2 | |
| 运行时 | AgentTrajectoryPage | pages/agent/AgentTrajectoryPage.ets | P2 | |
| 运行时 | SleepStatusPage | pages/agent/SleepStatusPage.ets | P2 | |
| 运行时 | SleepSettingsPage | pages/agent/SleepSettingsPage.ets | P2 | |
| 运行时 | AgentFirewallPage | pages/agent/AgentFirewallPage.ets | P2 | |
| 个性 | AgentEmotionPage | pages/agent/AgentEmotionPage.ets | P2 | |
| 个性 | AgentPersonalityPage | pages/agent/AgentPersonalityPage.ets | P2 | |
| 知识 | KnowledgePage | pages/knowledge/KnowledgePage.ets | P1 | |
| 知识 | SkillPoolPage | pages/knowledge/SkillPoolPage.ets | P2 | |
| 知识 | SkillMarketPage | pages/knowledge/SkillMarketPage.ets | P2 | |
| 知识 | AIGCPage | pages/knowledge/AIGCPage.ets | P2 | |
| 模型 | ModelPage | pages/model/ModelPage.ets | P1 | |
| 模型 | ToolLayerPage | pages/model/ToolLayerPage.ets | P2 | |
| 工作流 | WorkflowPage | pages/workflow/WorkflowPage.ets | P2 | |
| 协作 | CollaborationPage | pages/collaboration/CollaborationPage.ets | P2 | |
| 协作 | CollaborationTemplatePage | pages/collaboration/CollaborationTemplatePage.ets | P3 | |
| 协作 | CollaborationHistoryPage | pages/collaboration/CollaborationHistoryPage.ets | P3 | |
| 协作 | ProjectPage | pages/collaboration/ProjectPage.ets | P2 | |
| 协作 | TeamPage | pages/collaboration/TeamPage.ets | P2 | |
| 协作 | TaskPage | pages/collaboration/TaskPage.ets | P2 | |
| 渠道 | ChannelIntegrationPage | pages/channel/ChannelIntegrationPage.ets | P2 | |
| 渠道 | SessionSyncPage | pages/channel/SessionSyncPage.ets | P2 | |
| 渠道 | WebhookPage | pages/channel/WebhookPage.ets | P3 | |
| 监控 | StatsPage | pages/system/StatsPage.ets | P2 | |
| 监控 | MonitorPage | pages/system/MonitorPage.ets | P2 | |
| 监控 | LogPage | pages/system/LogPage.ets | P2 | |
| 监控 | HealthPage | pages/system/HealthPage.ets | P1 | |
| 监控 | AuditPage | pages/system/AuditPage.ets | P3 | |
| 监控 | BenchmarkPage | pages/system/BenchmarkPage.ets | P3 | |
| 监控 | SandboxPage | pages/system/SandboxPage.ets | P3 | |
| 监控 | FirewallPage | pages/system/FirewallPage.ets | P3 | |
| 管理 | SettingPage | pages/system/SettingPage.ets | P1 | |
| 管理 | NotificationPage | pages/system/NotificationPage.ets | P2 | |
| 管理 | GroupPage | pages/system/GroupPage.ets | P3 | |
| 管理 | EnhancedUserPage | pages/system/EnhancedUserPage.ets | P3 | |
| 管理 | FilePage | pages/system/FilePage.ets | P2 | |
| 市场 | MarketplacePage | pages/system/MarketplacePage.ets | P3 | |
| NEURON | NeuronPage | pages/neuron/NeuronPage.ets | P2 | |

**优先级定义**：
- **P0**（4 个）：MVP 必备，首期交付 — Login、Dashboard、Chat、AgentList
- **P1**（8 个）：核心功能，第二期 — Register、AgentForm、Memory、Knowledge、Model、Health、Setting、AgentChannel
- **P2**（30 个）：完整功能，第三期
- **P3**（15 个）：增强功能，第四期

### 6.3 布局适配

| Vue 布局 | ArkUI 布局 | 说明 |
|---|---|---|
| MainLayout（侧边栏+顶栏+内容） | Navigation(Split) + 自定义 TopBar | 折叠屏/平板用双栏，手机用抽屉 |
| ChatLayout（未启用） | — | 不迁移 |
| 侧边栏动态切换（全局/Agent） | 根据 AgentStore.currentAgent 切换菜单数据源 | 复用 MainLayout 逻辑 |

**响应式断点**：
- `< 600vp`（手机）：抽屉式侧边栏，单栏
- `600-840vp`（折叠屏）：可折叠侧边栏
- `> 840vp`（平板）：固定侧边栏 + 双栏

---

## 7. 移动端配对与 WebSocket

### 7.1 配对流程（鸿蒙端作为手机端）

```
[鸿蒙 App]                        [后端 :9527]                    [PC Web]
    |                                 |                              |
    |                                 | POST /mobile/pairing/generate|
    |                                 |<-----------------------------|
    |                                 | 生成 6 位 code + 二维码       |
    |                                 |--------------------------->  |
    |                                 |                              |
    | 扫码得到 code（或手动输入）      |                              |
    | POST /mobile/pairing/confirm    |                              |
    |  {code, device_name:'HarmonyOS',|                              |
    |   device_id: ohos.udid}         |                              |
    |-------------------------------->|                              |
    |                                 | 校验 + 颁发 ws_token         |
    |<--------------------------------|                              |
    |  {ws_token, ws_url}             |                              |
    |                                 |                              |
    | WS 连接 ws_url?token=ws_token   |                              |
    |<===============================>|                              |
    |                                 |                              |
    | {type:"ping"}                   |                              |
    |-------------------------------->|                              |
    | {type:"pong", timestamp}        |                              |
    |<--------------------------------|                              |
```

### 7.2 WebSocket 适配器

```typescript
// adapters/WebSocketAdapter.ets
export class WebSocketAdapter {
  private static instance: WebSocketAdapter;
  private ws: websocket.WebSocket | null = null;
  private reconnectAttempts: number = 0;

  static getInstance(): WebSocketAdapter;

  connect(url: string, token: string): Promise<void>;
  disconnect(): void;
  send(message: object): void;

  onMessage(handler: (data: any) => void): void;
  onOpen(handler: () => void): void;
  onClose(handler: (code: number, reason: string) => void): void;
  onError(handler: (error: Error) => void): void;

  startHeartbeat(): void;    // 每 30s 发 {type:"ping"}
  stopHeartbeat(): void;
  reconnect(): void;         // 指数退避，max 5 次
}
```

**心跳**：30 秒发 `{type:"ping"}`，10 秒无 `pong` 则重连。

**重连策略**：指数退避（5s/10s/20s/40s/60s），最多 5 次，重连成功后 `bus.emit('ws:connected')`。

### 7.3 PairingStore（新增状态）

```typescript
@Observed
export class PairingStore {
  pairingCode: string = '';
  pairingStatus: 'idle' | 'pending' | 'confirmed' | 'expired' = 'idle';
  wsToken: string = '';
  wsConnected: boolean = false;
  pairedDevices: PairedDevice[] = [];

  generatePairing(): Promise<void>;     // 调 API + 展示二维码
  confirmPairing(code: string): Promise<void>;  // 鸿蒙端扫码确认
  connectWs(): Promise<void>;
  disconnectWs(): void;
  revokePairing(pairingId: string): Promise<void>;
  loadPairedDevices(): Promise<void>;
}
```

### 7.4 扫码能力

使用 `@ohos.multimedia.camera` + `@ohos.scan`（HarmonyOS 5.0 扫码 Kit），扫描二维码后提取 `code`，调 `confirmPairing`。

---

## 8. 国际化与主题

### 8.1 国际化

迁移 NeurUI 的 11 种语言资源（`zh-CN` / `en-US` / `ja-JP` / `ko-KR` / `fr-FR` / `de-DE` / `es-ES` / `ru-RU` / `ar-SA` / `hi-IN` / `it-IT`）。

**实现**：
- 资源文件：`i18n/<locale>.json`，53 个顶层 key（与 `zh-CN.ts` 对齐）。
- 运行时：`@ohos.i18n` 获取系统语言，结合 `AppStore.locale` 用户偏好（用户优先）。
- 切换：`AppStore.setLocale()` → 触发全局 `@Provide('locale')` 更新 → 所有页面 `@Consume` 响应。
- RTL：`ar-SA` 启用 `direction: Direction.Rtl`。

### 8.2 主题

迁移 NeurUI 的亮/暗双主题。

**实现**：
- `AppStore.theme` 持久化到 `PersistentStorage`。
- 切换：`AppStore.setTheme()` → `@Provide('themeMode')` 更新。
- 组件内：`@Consume('themeMode') themeMode` → 根据值选择 `tokens.colors` 子集（ArkUI 无 CSS 变量，需在组件内三元选择）。
- 跟随系统：`theme === 'auto'` 时读取 `@ohos.app.ability.configurationConstant.ColorMode`。

### 8.3 Glass* 组件迁移

| Vue 组件 | ArkUI 组件 | 迁移要点 |
|---|---|---|
| GlassPanel | GlassPanel.ets | SVG 滤镜 → ArkUI `backgroundBlurStyle` + `backgroundEffect` |
| GlassCard | GlassCard.ets | 三段式插槽 → `@BuilderParam` |
| GlassButton | GlassButton.ets | 鼠标光斑 → 触摸涟漪；4 变体保留 |
| GlassInput | GlassInput.ets | `TextInput` 封装，prefix/suffix 用 `@BuilderParam` |
| GlassNav | GlassNav.ets | `Navigation(Split)` + 自定义侧边栏 |
| GlassNavItem | GlassNavItem.ets | 高亮当前路由用 `navStack.getParamByName` |
| GlassStatCard | GlassStatCard.ets | sparkline 用 `Canvas` 绘制 |
| StarBackground | StarBackground.ets | `Canvas` 粒子动画 |
| AgentSwitcher | AgentSwitcher.ets | `Select` 组件封装 |
| TopNavMenu | TopNavMenu.ets | `Menu` + `MenuItem` 下拉 |

---

## 9. 安全与持久化

### 9.1 安全存储

| 数据 | 存储方式 | 加密 |
|---|---|---|
| access_token / refresh_token | `preferences` + `@ohos.security.cryptoFramework` AES-256 | 是 |
| 用户信息 | `preferences` | 否（非敏感） |
| 主题/语言/侧边栏 | `PersistentStorage` | 否 |
| ws_token | `preferences` + AES-256 | 是 |
| 配对设备列表 | `relationalStore`（SQLite） | 否 |

### 9.2 输入校验

迁移 `NeurUI/src/utils/security.ts`：
- `validateUsername`：3-20 字符，字母数字下划线
- `validateEmail`：邮箱格式，≤254 字符
- `validatePasswordStrength`：返回 `{ valid, score(0-4), feedback }`
- `sanitizeHtml`：剥离 script/事件处理器/javascript:/iframe/data:

### 9.3 网络安全

- 生产环境强制 HTTPS（`http` 仅开发环境）。
- WebSocket 生产环境用 `wss://`。
- 证书校验：`@ohos.net.http` 的 `certVerification` 开启。
- 防中间人：后端公钥指纹内置（可选）。

---

## 10. 性能优化

### 10.1 启动性能
- **冷启动目标**：≤ 1.5s（P0 页面可交互）
- **首帧目标**：≤ 800ms
- **措施**：
  - 延迟加载非 P0 页面（`LazyForEach` + 按需 `import`）
  - EntryAbility 只初始化 13 个统一库 + AuthStore，其余按需
  - 启动页用静态资源，避免网络请求阻塞

### 10.2 运行时性能
- **列表**：所有长列表用 `LazyForEach`（内存只保留可视项 + 缓冲）
- **图表**：Dashboard 的 sparkline 用 `Canvas` 离屏渲染
- **WebSocket**：消息批量处理，避免高频 UI 刷新（50ms 节流）
- **图片**：`@ohos.request` + 本地缓存，避免重复下载
- **内存**：页面 `aboutToDisappear` 清理订阅和定时器

### 10.3 包体积
- 目标：≤ 30MB（不含动态资源）
- 措施：按 ABI 分包、资源压缩、未使用 API tree-shaking

---

## 11. 测试策略

### 11.1 测试框架

| 层 | 框架 | 范围 |
|---|---|---|
| 单元测试 | Hypium | 13 个统一库的纯逻辑测试 |
| 组件测试 | UiTest | Glass* 组件交互 |
| 页面测试 | UiTest | P0/P1 页面关键流程 |
| 集成测试 | UiTest + mock 后端 | 配对→WS→聊天全链路 |
| 性能测试 | SmartPerf | 启动/内存/帧率 |

### 11.2 测试覆盖目标
- 统一库：≥ 90% 行覆盖
- P0 页面：≥ 80% 关键路径
- P1 页面：≥ 60% 关键路径
- 配对+WS 链路：100%（阻断性功能）

### 11.3 TDD 流程（遵循用户规则）

每个统一库和 P0 页面采用红绿灯 TDD：
1. **红**：先写测试，运行失败
2. **绿**：最小实现使测试通过
3. **重构**：优化代码，测试保持绿色

测试文件位置：`entry/src/ohosTest/ets/`，与生产代码 1:1 镜像目录结构。

---

## 12. 开发计划

### 12.1 里程碑

| 阶段 | 内容 | 交付物 |
|---|---|---|
| M0：前置 | 修复后端 4 个阻断性 bug；搭建鸿蒙工程骨架 | 可编译的空工程 + 后端修复 PR |
| M1：基础设施 | 13 个统一库 + 适配层 + Glass* 组件 | 统一库单测全绿 + 组件 Demo |
| M2：MVP（P0） | Login + Dashboard + Chat + AgentList | 4 页面可跑 + 配对闭环 |
| M3：核心（P1） | 8 个 P1 页面 + 移动端 WS 业务消息 | 12 页面可跑 |
| M4：完整（P2） | 30 个 P2 页面 | 42 页面可跑 |
| M5：增强（P3） | 15 个 P3 页面 + 性能优化 | 57 页面全量 + 上架准备 |

### 12.2 并行开发策略（遵循用户规则）

利用 `Task` 工具并行开发：
- M1 阶段：13 个统一库可并行（无依赖）
- M2-M5：按页面优先级分组，每组 3-5 个页面并行
- 每个模块完成后：**主动调用审计 agent 检查统一库合规** + **主动调用单元测试 agent 跑测试**

### 12.3 审计检查点

每个里程碑结束前，审计 agent 检查：
1. 是否有页面直接 `import http`（违反统一 API 库）
2. 是否有组件直接操作 DOM 等价物（违反统一状态库）
3. 是否有页面硬编码颜色/尺寸（违反统一样式库）
4. 是否有裸 `try/catch`（违反统一错误库）
5. 是否有 `console.log`（违反统一日志库）

---

## 13. 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| ArkUI 无 CSS 变量，主题切换复杂 | 高 | 在统一样式库封装 `getThemeColor(key)` 函数，组件统一调用 |
| Glass 拟态效果在 ArkUI 实现差异大 | 高 | 用 `backgroundBlurStyle` + `backgroundEffect` 替代 SVG 滤镜，视觉验收对比 |
| WebSocket 在鸿蒙后台被杀 | 高 | 申请长驻通知权限 + 前台服务；退而求其次用推送 |
| 57 页面全量重写工作量大 | 高 | 严格按 P0-P3 优先级分批，P3 可降级为 H5 嵌入 |
| 后端 JWT 占位导致多用户隔离失效 | 高 | M0 必须修复，否则配对功能不可用 |
| 鸿蒙 API 12 与 13 差异 | 中 | 锁定 API 12，新 API 谨慎使用 |
| 国际化 53 个 key 迁移遗漏 | 中 | 脚本对比 `zh-CN.ts` 与 `zh-CN.json` 的 key 差异 |
| 测试设备不足 | 中 | 优先真机测试 P0 页面，P3 用模拟器 |
| 后端 `ws_url` 硬编码 localhost | 中 | M0 修复，从 `Host` header 推导 |
| 包体积超标 | 低 | 按 ABI 分包，资源压缩 |

---

## 14. 附录

### 14.1 文件使用说明

本文件：`docs/HARMONYOS_DESIGN.md`
- **路径**：`e:\项目\Neurova\docs\HARMONYOS_DESIGN.md`
- **内容**：鸿蒙 App C 方案（纯 ArkTS 重写）完整设计文档
- **功能**：作为鸿蒙端开发的唯一设计依据，涵盖架构、统一库、页面映射、路由、配对、国际化、安全、性能、测试、计划、风险
- **维护**：每次架构调整需同步更新本文档；每个里程碑结束记录实际偏差

### 14.2 关键调研依据

- 后端路由：`neurova/api/endpoints/__init__.py`（80+ 端点注册）
- 前端架构：`NeurUI/src/{api,bus,stores,components,styles,utils,config,animations}/`
- 移动端配对：`neurova/api/endpoints/mobile_pairing.py` + `NeurUI/src/api/modules/mobile.ts`
- 路由配置：`NeurUI/src/router/index.ts`（57 页面，9 个逻辑组）
- 设计令牌：`NeurUI/src/styles/variables.css` + `tokens.ts`

### 14.3 术语表

| 术语 | 含义 |
|---|---|
| ArkTS | HarmonyOS 强类型 TS 超集 |
| ArkUI | HarmonyOS 声明式 UI 框架 |
| UIAbility | 鸿蒙应用的能力载体（类似 Activity） |
| Navigation | ArkUI 路由容器（替代 vue-router） |
| NavPathStack | 路由栈管理 |
| AppStorage | 全局状态存储（类似 Pinia 的全局 store） |
| PersistentStorage | 持久化存储（自动同步 AppStorage 到磁盘） |
| preferences | 轻量 KV 存储（类似 localStorage） |
| relationalStore | SQLite 封装 |
| Hypium | 鸿蒙单元测试框架 |
| UiTest | 鸿蒙 UI 自动化测试框架 |
