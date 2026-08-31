# Neurova 前端架构指南
# 为 frontend-chat-dev 提供的技术参考文档

**版本**: 1.0  
**日期**: 2026-05-13  
**作者**: frontend-arch-dev  
**受众**: frontend-chat-dev, 所有前端开发者  

---

## 📋 目录

1. [项目架构概览](#1-项目架构概览)
2. [路由系统](#2-路由系统)
3. [状态管理（Zustand）](#3-状态管理zustand)
4. [国际化（i18n）](#4-国际化i18n)
5. [主题切换](#5-主题切换)
6. [Chat页面架构](#6-chat页面架构)
7. [API集成](#7-api集成)
8. [开发指南](#8-开发指南)
9. [常见问题](#9-常见问题)

---

## 1. 项目架构概览

### 1.1 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **路由**: React Router DOM v6
- **状态管理**: Zustand
- **UI组件库**: Ant Design 5.x
- **国际化**: i18next + react-i18next
- **样式**: CSS Modules + Less
- **HTTP客户端**: Axios (通过自定义API模块)

### 1.2 目录结构

```
neurova-ui/src/
├── api/                    # API集成层
│   ├── modules/           # API模块（chat.ts, agent.ts等）
│   ├── types/             # TypeScript类型定义
│   └── request.ts         # Axios实例配置
├── components/            # 通用组件
├── contexts/              # React Context（Theme, Language）
├── layouts/               # 布局组件
├── locales/               # i18n翻译文件（11种语言）
├── pages/                 # 页面组件
│   ├── Chat/             # Chat页面
│   ├── Agent/            # Agent配置页面
│   ├── Control/          # Control页面
│   └── Settings/         # Settings页面
├── stores/                # Zustand状态管理
├── styles/                # 全局样式
├── types/                 # 全局类型定义
├── utils/                 # 工具函数
├── App.tsx               # 路由配置
└── main.tsx              # 应用入口
```

---

## 2. 路由系统

### 2.1 路由配置位置

**文件**: `src/App.tsx`

### 2.2 路由结构

```typescript
// src/App.tsx
import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import ChatPage from './pages/Chat/ChatPage';
import AgentPage from './pages/Agent/AgentPage';
import ControlPage from './pages/Control/ControlPage';
import SettingsPage from './pages/Settings/SettingsPage';

const App: React.FC = () => {
  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="agent/*" element={<AgentPage />} />
        <Route path="control/*" element={<ControlPage />} />
        <Route path="settings/*" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
};

export default App;
```

### 2.3 路由说明

| 路径 | 组件 | 说明 |
|------|------|------|
| `/` | - | 重定向到 `/chat` |
| `/chat` | ChatPage | Chat页面（主功能） |
| `/agent/*` | AgentPage | Agent配置页面（支持子路由） |
| `/control/*` | ControlPage | Control页面（支持子路由） |
| `/settings/*` | SettingsPage | Settings页面（支持子路由） |

### 2.4 布局系统

**文件**: `src/layouts/MainLayout.tsx`

**特性**:
- 左侧固定侧边栏（Sider）
- 顶部Header（语言选择器 + 主题切换）
- 主内容区使用 `<Outlet />` 渲染子路由

**导航菜单**:
```typescript
const menuItems = [
  { key: '/chat', icon: <MessageOutlined />, label: 'Chat' },
  { key: '/agent', icon: <RobotOutlined />, label: 'Agent' },
  { key: '/control', icon: <ControlOutlined />, label: 'Control' },
  { key: '/settings', icon: <SettingOutlined />, label: 'Settings' },
];
```

### 2.5 添加新路由

**步骤**:

1. 在 `src/pages/` 创建新页面目录
2. 在 `src/App.tsx` 添加路由配置
3. 在 `src/layouts/MainLayout.tsx` 添加菜单项

**示例**:

```typescript
// 1. 创建页面
// src/pages/NewPage/NewPage.tsx
const NewPage: React.FC = () => {
  return <div>New Page</div>;
};

export default NewPage;

// 2. 添加路由
// src/App.tsx
import NewPage from './pages/NewPage/NewPage';
<Route path="new" element={<NewPage />} />

// 3. 添加菜单项
// src/layouts/MainLayout.tsx
{
  key: '/new',
  icon: <SomeOutlined />,
  label: 'New',
}
```

---

## 3. 状态管理（Zustand）

### 3.1 为什么选择Zustand？

- **轻量级**: 无Boilerplate代码
- **TypeScript友好**: 完整的类型推断
- **高性能**: 自动优化重渲染
- **易于测试**: 不依赖React上下文

### 3.2 Store文件位置

**目录**: `src/stores/`

**现有Store**:
- `chatStore.ts` - Chat页面状态管理
- `useChatStore.ts` - Chat Store的另一个实现 ⚠️ **需要统一**
- `agentStore.ts` - Agent配置状态
- `providerStore.ts` - Provider管理状态
- `settingsStore.ts` - 设置状态（主题、语言、侧边栏）
- `controlStore.ts` - Control页面状态
- `channelStore.ts` - 频道管理状态

### 3.3 Store编写规范

**标准模板**:

```typescript
/**
 * [功能] 状态管理
 * 使用 Zustand 管理 [功能] 相关的状态
 */

import { create } from 'zustand';
import type { [DataType] } from '../api/types/[DataType]';

/**
 * [功能] Store 接口
 */
interface [Feature]Store {
  // 状态
  [stateName]: [StateType];
  loading: boolean;
  error: string | null;

  // 方法
  fetch[Data]: () => Promise<void>;
  create[Data]: ([params]) => Promise<void>;
  update[Data]: (id: string, [params]) => Promise<void>;
  delete[Data]: (id: string) => Promise<void>;
  clearError: () => void;
}

/**
 * 创建 [功能] Store
 */
export const use[Feature]Store = create<[Feature]Store>()((set, get) => ({
  // 初始状态
  [stateName]: [initialValue],
  loading: false,
  error: null,

  /**
   * 获取[数据]
   */
  fetch[Data]: async () => {
    set({ loading: true, error: null });
    try {
      const data = await [apiModule].[apiMethod]();
      set({ [stateName]: data, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch [data]',
        loading: false,
      });
    }
  },

  /**
   * 创建[数据]
   */
  create[Data]: async ([params]) => {
    set({ loading: true, error: null });
    try {
      const newData = await [apiModule].[createMethod]([params]);
      set((state) => ({
        [stateName]: [...state.[stateName], newData],
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to create [data]',
        loading: false,
      });
    }
  },

  /**
   * 更新[数据]
   */
  update[Data]: async (id: string, [params]) => {
    set({ loading: true, error: null });
    try {
      const updatedData = await [apiModule].[updateMethod](id, [params]);
      set((state) => ({
        [stateName]: state.[stateName].map((item) =>
          item.id === id ? updatedData : item
        ),
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update [data]',
        loading: false,
      });
    }
  },

  /**
   * 删除[数据]
   */
  delete[Data]: async (id: string) => {
    set({ loading: true, error: null });
    try {
      await [apiModule].[deleteMethod](id);
      set((state) => ({
        [stateName]: state.[stateName].filter((item) => item.id !== id),
        loading: false,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete [data]',
        loading: false,
      });
    }
  },

  /**
   * 清除错误
   */
  clearError: () => {
    set({ error: null });
  },
}));
```

### 3.4 在组件中使用Store

**示例**:

```typescript
import { useChatStore } from '../../stores/chatStore';

const ChatPage: React.FC = () => {
  const {
    conversations,
    currentConversationId,
    loading,
    fetchConversations,
    createConversation,
  } = useChatStore();

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  return (
    <div>
      {/* 使用状态和方法 */}
    </div>
  );
};
```

### 3.5 ⚠️ 重要：Chat Store重复问题

**问题**: 存在2个Chat Store实现
- `src/stores/chatStore.ts` (529行，功能完整)
- `src/stores/useChatStore.ts` (138行，简化版本)

**解决方案**: 

选择其中一个作为标准实现（建议使用 `chatStore.ts`，因为功能更完整），然后：
1. 删除 `useChatStore.ts`
2. 更新所有导入语句
3. 确保API集成正确

**Action Item**: frontend-chat-dev需要在开发前统一Chat Store

---

## 4. 国际化（i18n）

### 4.1 i18n配置位置

**主配置**: `src/contexts/LanguageContext.tsx`

**翻译文件目录**: `src/locales/`

### 4.2 支持的语言

| 语言代码 | 语言名称 | 文件名 |
|---------|---------|--------|
| zh-CN | 简体中文 | zh-CN.json |
| en-US | English | en-US.json |
| ja-JP | 日本語 | ja-JP.json |
| ko-KR | 한국어 | ko-KR.json |
| fr-FR | Français | fr-FR.json |
| de-DE | Deutsch | de-DE.json |
| es-ES | Español | es-ES.json |
| ru-RU | Русский | ru-RU.json |
| pt-PT | Português | pt-PT.json |
| it-IT | Italiano | it-IT.json |
| th-TH | ไทย | th-TH.json |

### 4.3 i18n初始化

**文件**: `src/contexts/LanguageContext.tsx`

```typescript
import i18n from 'i18next';
import { useTranslation, initReactI18next } from 'react-i18next';

// 导入语言资源
import zhCN from '@/locales/zh-CN.json';
import enUS from '@/locales/en-US.json';
// ... 其他语言

const resources = {
  'zh-CN': { translation: zhCN },
  'en-US': { translation: enUS },
  // ... 其他语言
};

// 初始化i18next
i18n.use(initReactI18next).init({
  resources,
  lng: localStorage.getItem('language') || 'zh-CN',
  fallbackLng: 'en-US',
  interpolation: {
    escapeValue: false,
  },
});
```

### 4.4 在组件中使用i18n

**方法1: 使用 useTranslation Hook (推荐)**

```typescript
import { useTranslation } from 'react-i18next';

const MyComponent: React.FC = () => {
  const { t } = useTranslation();
  
  return (
    <div>
      <h1>{t('common.welcome')}</h1>
      <button>{t('common.save')}</button>
    </div>
  );
};
```

**方法2: 使用 LanguageContext**

```typescript
import { useLanguage } from '../../contexts/LanguageContext';

const MyComponent: React.FC = () => {
  const { t, language, setLanguage } = useLanguage();
  
  return (
    <div>
      <h1>{t('common.welcome')}</h1>
      <span>当前语言: {language}</span>
      <button onClick={() => setLanguage('en-US')}>
        切换到英文
      </button>
    </div>
  );
};
```

### 4.5 翻译文件格式

**文件**: `src/locales/zh-CN.json`

```json
{
  "common": {
    "welcome": "欢迎",
    "save": "保存",
    "cancel": "取消",
    "delete": "删除",
    "edit": "编辑"
  },
  "chat": {
    "title": "Neurova Chat",
    "inputPlaceholder": "输入消息...",
    "sendButton": "发送",
    "newConversation": "新建会话"
  }
}
```

### 4.6 添加新翻译

**步骤**:

1. 在 `src/locales/` 的所有JSON文件中添加对应的翻译键值
2. 在组件中使用 `t('key.path')` 引用翻译

**示例**:

```json
// zh-CN.json
{
  "chat": {
    "newFeature": "新功能"
  }
}

// en-US.json
{
  "chat": {
    "newFeature": "New Feature"
  }
}
```

```typescript
// 在组件中使用
const { t } = useTranslation();
return <div>{t('chat.newFeature')}</div>;
```

---

## 5. 主题切换

### 5.1 主题配置位置

**主配置**: `src/contexts/ThemeContext.tsx`

**全局样式**: `src/styles/global.css`

### 5.2 支持的主题模式

| 模式 | 说明 |
|------|------|
| `light` | 浅色模式 |
| `dark` | 深色模式 |
| `auto` | 自动（跟随系统） |

### 5.3 ThemeContext实现

**文件**: `src/contexts/ThemeContext.tsx`

```typescript
interface ThemeContextType {
  theme: 'light' | 'dark' | 'auto';
  setTheme: (theme: 'light' | 'dark' | 'auto') => void;
  isDark: boolean;
}

const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { theme, setTheme } = useSettingsStore();
  const [isDark, setIsDark] = useState(false);
  
  useEffect(() => {
    const updateTheme = () => {
      if (theme === 'auto') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        setIsDark(prefersDark);
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
      } else {
        setIsDark(theme === 'dark');
        document.documentElement.setAttribute('data-theme', theme);
      }
    };
    
    updateTheme();
    
    // 监听系统主题变化
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = () => {
      if (theme === 'auto') {
        updateTheme();
      }
    };
    
    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [theme]);
  
  return (
    <ThemeContext.Provider value={{ theme, setTheme, isDark }}>
      {children}
    </ThemeContext.Provider>
  );
};
```

### 5.4 在组件中使用主题

**使用 ThemeContext**:

```typescript
import { useTheme } from '../../contexts/ThemeContext';

const MyComponent: React.FC = () => {
  const { theme, setTheme, isDark } = useTheme();
  
  return (
    <div>
      <span>当前主题: {theme}</span>
      <span>是否深色: {isDark ? '是' : '否'}</span>
      <button onClick={() => setTheme('dark')}>切换到深色</button>
    </div>
  );
};
```

**使用 SettingsStore**:

```typescript
import { useSettingsStore } from '../../stores/useSettingsStore';

const MyComponent: React.FC = () => {
  const { theme, setTheme, toggleTheme } = useSettingsStore();
  
  return (
    <div>
      <button onClick={toggleTheme}>切换主题</button>
    </div>
  );
};
```

### 5.5 主题样式定制

**方法1: CSS Modules + data-theme**

```css
/* src/pages/Chat/ChatPage.module.css */
.chatPage {
  background-color: #ffffff;
  color: #000000;
}

[data-theme='dark'] .chatPage {
  background-color: #1f1f1f;
  color: #ffffff;
}
```

**方法2: 使用Ant Design主题**

```typescript
import { ConfigProvider, theme } from 'antd';

const MyApp: React.FC = () => {
  const { isDark } = useTheme();
  
  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
      }}
    >
      {/* 应用内容 */}
    </ConfigProvider>
  );
};
```

---

## 6. Chat页面架构

### 6.1 Chat页面目录结构

```
src/pages/Chat/
├── components/                # 子组件
│   ├── MessageBubble.tsx     # 消息气泡
│   ├── MessageBubble.module.css
│   ├── MessageInput.tsx      # 消息输入框
│   ├── MessageInput.module.css
│   ├── MessageList.tsx       # 消息列表
│   ├── ModelSelector.tsx     # 模型选择器
│   ├── ModelSelector.module.css
│   ├── SessionList.tsx       # 会话列表
│   ├── SessionList.module.css
│   └── TypingIndicator.tsx   # 输入指示器（流式响应）
├── ChatPage.tsx              # Chat页面主组件
└── ChatPage.module.css       # 主组件样式
```

### 6.2 ChatPage主组件

**文件**: `src/pages/Chat/ChatPage.tsx`

**核心功能**:
1. **会话管理**: 创建、删除、重命名、选择会话
2. **消息发送**: 支持文本 + 附件
3. **SSE流式响应**: 实时显示AI回复
4. **消息搜索**: 本地搜索 + 全局搜索
5. **模型选择**: 选择AI模型

**状态管理**: 使用 `useChatStore`

```typescript
const {
  conversations,              // 会话列表
  currentConversationId,      // 当前会话ID
  messages,                   // 消息列表
  loading,                    // 加载状态
  sending,                    // 发送状态
  error,                      // 错误信息
  isStreaming,               // 是否正在流式响应
  streamingMessage,          // 流式消息内容
  searchQuery,               // 搜索查询
  searchResults,             // 搜索结果
  isSearching,               // 搜索状态
  fetchConversations,        // 获取会话列表
  createConversation,        // 创建会话
  deleteConversation,        // 删除会话
  renameConversation,        // 重命名会话
  selectConversation,        // 选择会话
  sendMessage,               // 发送消息
  stopGeneration,            // 停止生成
  setSearchQuery,            // 设置搜索查询
  searchMessages,            // 搜索消息
  clearSearch,               // 清除搜索
} = useChatStore();
```

### 6.3 子组件说明

#### MessageList - 消息列表

**功能**:
- 显示当前会话的所有消息
- 支持加载状态
- 支持搜索高亮

**Props**:
```typescript
interface MessageListProps {
  messages: ChatMessage[];
  isSearching?: boolean;
  searchQuery?: string;
}
```

#### MessageBubble - 消息气泡

**功能**:
- 显示单条消息
- 区分用户/助手/系统消息
- 支持Markdown渲染
- 支持附件显示

**Props**:
```typescript
interface MessageBubbleProps {
  message: ChatMessage;
  isStreaming?: boolean;
}
```

#### MessageInput - 消息输入框

**功能**:
- 文本输入
- 附件上传
- 发送按钮
- 停止生成按钮（流式响应时）

**Props**:
```typescript
interface MessageInputProps {
  onSend: (content: string, attachments?: File[]) => void;
  disabled?: boolean;
  onStop?: () => void;
}
```

#### SessionList - 会话列表

**功能**:
- 显示所有会话
- 创建新会话
- 删除会话
- 重命名会话
- 搜索会话

**Props**:
```typescript
interface SessionListProps {
  visible: boolean;
  onClose: () => void;
  conversations: Conversation[];
  currentConversationId: string | null;
  loading?: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}
```

#### ModelSelector - 模型选择器

**功能**:
- 选择AI模型
- 显示可用模型列表
- 保存用户选择

**Props**:
```typescript
interface ModelSelectorProps {
  // 可能不需要props，直接从store读取
}
```

#### TypingIndicator - 输入指示器

**功能**:
- 显示AI正在输入
- 实时显示流式响应内容
- 停止生成按钮

**Props**:
```typescript
interface TypingIndicatorProps {
  content: string;
  onStop: () => void;
}
```

### 6.4 Chat页面布局

```
┌─────────────────────────────────────────────┐
│  Toolbar                                     │
│  [菜单] [标题]     [模型选择器/搜索栏]    [搜索][新建] │
├─────────────────────────────────────────────┤
│                                              │
│  MessageList                                 │
│  - MessageBubble (user)                      │
│  - MessageBubble (assistant)                 │
│  - MessageBubble (user)                      │
│  - TypingIndicator (streaming)               │
│                                              │
│                                              │
├─────────────────────────────────────────────┤
│  MessageInput                                │
│  [附件] [文本输入...]              [发送]   │
└─────────────────────────────────────────────┘
```

### 6.5 ⚠️ Chat页面当前状态

**Team-lead报告**: Chat页面进度 0%

**实际检查**: Chat页面已有基本框架实现

**已实现**:
- ✅ ChatPage主组件
- ✅ MessageList组件
- ✅ MessageInput组件
- ✅ SessionList组件
- ✅ ModelSelector组件
- ✅ TypingIndicator组件
- ✅ Zustand Store (chatStore.ts)
- ✅ 会话管理功能（模拟数据）
- ✅ 消息发送功能（模拟数据）
- ✅ SSE流式响应（模拟）

**待实现**:
- ⏳ 集成真实API（当前使用模拟数据）
- ⏳ Markdown渲染优化
- ⏳ 代码高亮
- ⏳ 附件上传到服务器
- ⏳ 消息搜索后端API
- ⏳ 错误处理优化
- ⏳ 性能优化（虚拟滚动大数据量消息）
- ⏳ 单元测试

**结论**: Chat页面进度实际约 **40-50%**，不是0%。frontend-chat-dev可以直接在现有基础上继续开发。

---

## 7. API集成

### 7.1 API模块目录

**目录**: `src/api/`

**结构**:
```
src/api/
├── modules/              # API模块
│   ├── chat.ts          # Chat API
│   ├── agent.ts         # Agent API
│   ├── provider.ts     # Provider API
│   ├── control.ts      # Control API
│   └── settings.ts     # Settings API
├── types/               # TypeScript类型定义
│   ├── ChatMessage.ts  # 聊天相关类型
│   ├── Agent.ts        # Agent相关类型
│   └── ...
└── request.ts           # Axios实例配置
```

### 7.2 Axios实例配置

**文件**: `src/api/request.ts`

```typescript
import axios from 'axios';

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 添加认证token
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 统一错误处理
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

export default request;
```

### 7.3 API模块编写规范

**标准模板**:

```typescript
/**
 * [功能] API 模块
 */

import request from '../request';
import type { [RequestType], [ResponseType] } from '../types/[TypeName]';

/**
 * 获取[数据]列表
 */
export const get[Data] = async (): Promise<[ResponseType][]> => {
  return request.get('/[endpoint]');
};

/**
 * 获取单个[数据]
 */
export const get[Data]ById = async (id: string): Promise<[ResponseType]> => {
  return request.get(`/[endpoint]/${id}`);
};

/**
 * 创建[数据]
 */
export const create[Data] = async (data: [RequestType]): Promise<[ResponseType]> => {
  return request.post('/[endpoint]', data);
};

/**
 * 更新[数据]
 */
export const update[Data] = async (id: string, data: Partial<[RequestType]>): Promise<[ResponseType]> => {
  return request.put(`/[endpoint]/${id}`, data);
};

/**
 * 删除[数据]
 */
export const delete[Data] = async (id: string): Promise<void> => {
  return request.delete(`/[endpoint]/${id}`);
};

export const [feature]Api = {
  get[Data],
  get[Data]ById,
  create[Data],
  update[Data],
  delete[Data],
};
```

### 7.4 Chat API示例

**文件**: `src/api/modules/chat.ts`

```typescript
import request from '../request';
import type { ChatMessage, Conversation, SendMessageRequest } from '../types/ChatMessage';

/**
 * 获取会话列表
 */
export const getConversations = async (): Promise<Conversation[]> => {
  return request.get('/chat/conversations');
};

/**
 * 获取单个会话
 */
export const getConversation = async (id: string): Promise<Conversation> => {
  return request.get(`/chat/conversations/${id}`);
};

/**
 * 创建会话
 */
export const createConversation = async (data: { title?: string }): Promise<Conversation> => {
  return request.post('/chat/conversations', data);
};

/**
 * 更新会话
 */
export const updateConversation = async (id: string, data: { title?: string }): Promise<Conversation> => {
  return request.put(`/chat/conversations/${id}`, data);
};

/**
 * 删除会话
 */
export const deleteConversation = async (id: string): Promise<void> => {
  return request.delete(`/chat/conversations/${id}`);
};

/**
 * 获取消息列表
 */
export const getMessages = async (conversationId: string): Promise<ChatMessage[]> => {
  return request.get(`/chat/conversations/${conversationId}/messages`);
};

/**
 * 发送消息（SSE流式）
 */
export const sendMessageStream = (conversationId: string, content: string): EventSource => {
  return new EventSource(`/api/chat/stream?conversationId=${conversationId}&content=${encodeURIComponent(content)}`);
};

/**
 * 发送消息（非流式）
 */
export const sendMessage = async (conversationId: string, data: SendMessageRequest): Promise<ChatMessage> => {
  return request.post(`/chat/conversations/${conversationId}/messages`, data);
};

/**
 * 搜索消息
 */
export const searchMessages = async (conversationId: string, query: string): Promise<ChatMessage[]> => {
  return request.get(`/chat/conversations/${conversationId}/messages/search`, {
    params: { q: query },
  });
};

export const chatApi = {
  getConversations,
  getConversation,
  createConversation,
  updateConversation,
  deleteConversation,
  getMessages,
  sendMessageStream,
  sendMessage,
  searchMessages,
};
```

### 7.5 在Store中集成API

**示例**: 更新 chatStore.ts 使用真实API

```typescript
import { create } from 'zustand';
import type { ChatMessage, Conversation } from '../api/types/ChatMessage';
import { chatApi } from '../api/modules/chat';  // 导入API模块

interface ChatStore {
  // ... 状态定义
  fetchConversations: () => Promise<void>;
  // ... 其他方法
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  // ... 初始状态
  
  /**
   * 获取会话列表（真实API）
   */
  fetchConversations: async () => {
    set({ loading: true, error: null });
    try {
      const conversations = await chatApi.getConversations();  // 调用API
      set({ conversations, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch conversations',
        loading: false,
      });
    }
  },
  
  // ... 其他方法
}));
```

### 7.6 SSE流式响应实现

**方法1: 使用EventSource (推荐用于GET请求)**

```typescript
sendMessage: async (content: string, attachments?: File[]) => {
  const { currentConversationId } = get();
  if (!currentConversationId) {
    throw new Error('No conversation selected');
  }

  set({ sending: true, error: null, isStreaming: true, streamingMessage: '' });

  // 添加用户消息到列表
  const userMessage: ChatMessage = {
    id: `msg_${Date.now()}`,
    conversationId: currentConversationId,
    role: 'user',
    content,
    timestamp: new Date().toISOString(),
  };

  set((state) => ({
    messages: [...state.messages, userMessage],
  }));

  try {
    // 创建EventSource for SSE
    const eventSource = new EventSource(
      `/api/chat/stream?conversationId=${currentConversationId}&content=${encodeURIComponent(content)}`
    );

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.done) {
        // 流式响应完成
        eventSource.close();
        
        const completedMessage: ChatMessage = {
          id: `msg_${Date.now() + 1}`,
          conversationId: currentConversationId,
          role: 'assistant',
          content: get().streamingMessage,
          timestamp: new Date().toISOString(),
          metadata: {
            model: data.model,
            tokens: data.tokens,
            latency: data.latency,
          },
        };

        set((state) => ({
          messages: [...state.messages, completedMessage],
          streamingMessage: '',
          isStreaming: false,
          sending: false,
        }));
      } else {
        // 接收流式数据
        set((state) => ({
          streamingMessage: state.streamingMessage + data.content,
        }));
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE Error:', error);
      eventSource.close();
      set({
        error: 'Failed to receive streaming response',
        isStreaming: false,
        sending: false,
      });
    };
  } catch (error) {
    set({
      error: error instanceof Error ? error.message : 'Failed to send message',
      isStreaming: false,
      sending: false,
    });
  }
},
```

**方法2: 使用Fetch API (推荐用于POST请求)**

```typescript
sendMessage: async (content: string, attachments?: File[]) => {
  const { currentConversationId } = get();
  if (!currentConversationId) {
    throw new Error('No conversation selected');
  }

  set({ sending: true, error: null, isStreaming: true, streamingMessage: '' });

  // 添加用户消息
  const userMessage: ChatMessage = {
    id: `msg_${Date.now()}`,
    conversationId: currentConversationId,
    role: 'user',
    content,
    timestamp: new Date().toISOString(),
  };

  set((state) => ({
    messages: [...state.messages, userMessage],
  }));

  try {
    const response = await fetch(`/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`,
      },
      body: JSON.stringify({
        conversationId: currentConversationId,
        content,
        attachments: attachments?.map(f => f.name),
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Failed to get response reader');
    }

    let done = false;
    while (!done) {
      const { value, done: readerDone } = await reader.read();
      done = readerDone;
      
      if (value) {
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            
            if (data.done) {
              // 完成
              const completedMessage: ChatMessage = {
                id: `msg_${Date.now() + 1}`,
                conversationId: currentConversationId,
                role: 'assistant',
                content: get().streamingMessage,
                timestamp: new Date().toISOString(),
              };

              set((state) => ({
                messages: [...state.messages, completedMessage],
                streamingMessage: '',
                isStreaming: false,
                sending: false,
              }));
            } else {
              // 接收数据
              set((state) => ({
                streamingMessage: state.streamingMessage + data.content,
              }));
            }
          }
        }
      }
    }
  } catch (error) {
    set({
      error: error instanceof Error ? error.message : 'Failed to send message',
      isStreaming: false,
      sending: false,
    });
  }
},
```

---

## 8. 开发指南

### 8.1 开发流程

1. **拉取最新代码**
   ```bash
   git pull origin main
   ```

2. **安装依赖**
   ```bash
   cd neurova-ui
   npm install
   ```

3. **启动开发服务器**
   ```bash
   npm run dev
   ```

4. **实现功能**
   - 编写组件
   - 集成API
   - 添加样式
   - 国际化

5. **测试**
   - 手动测试
   - 单元测试（如果有）

6. **提交代码**
   ```bash
   git add .
   git commit -m "feat(chat): implement message sending"
   git push origin feature/chat-page
   ```

### 8.2 代码规范

**命名规范**:
- **组件**: PascalCase (e.g., `MessageBubble.tsx`)
- **CSS Modules**: CamelCase (e.g., `MessageBubble.module.css`)
- **工具函数**: camelCase (e.g., `formatTime.ts`)
- **常量**: UPPER_SNAKE_CASE (e.g., `API_BASE_URL`)

**文件结构**:
```typescript
// 1. 导入React
import React, { useState, useEffect, useCallback } from 'react';

// 2. 导入第三方库
import { Button, Input } from 'antd';
import { SomeOutlined } from '@ant-design/icons';

// 3. 导入本地模块
import { useChatStore } from '../../stores/chatStore';
import { useTranslation } from 'react-i18next';

// 4. 导入样式
import styles from './ComponentName.module.css';

// 5. 定义接口/类型
interface ComponentNameProps {
  prop1: string;
  prop2?: number;
}

// 6. 定义组件
const ComponentName: React.FC<ComponentNameProps> = ({ prop1, prop2 }) => {
  // 组件逻辑
  return (
    <div className={styles.container}>
      {/* JSX */}
    </div>
  );
};

// 7. 导出
export default ComponentName;
```

**注释规范**:
```typescript
/**
 * 组件描述
 * 详细说明组件的功能和用法
 */

import React from 'react';

/**
 * Props接口定义
 */
interface MyComponentProps {
  /** 属性1说明 */
  prop1: string;
  /** 属性2说明（可选） */
  prop2?: number;
}

/**
 * MyComponent - 组件名称
 * 
 * @param prop1 - 参数1说明
 * @param prop2 - 参数2说明
 * @returns React组件
 */
const MyComponent: React.FC<MyComponentProps> = ({ prop1, prop2 = 0 }) => {
  /**
   * 处理函数描述
   */
  const handleClick = useCallback(() => {
    // 处理逻辑
  }, []);

  return (
    <div>{prop1}</div>
  );
};

export default MyComponent;
```

### 8.3 调试技巧

**1. 使用React DevTools**
   - 安装React DevTools浏览器扩展
   - 查看组件树和Props
   - 调试Hooks状态

**2. 使用Zustand DevTools**
   ```typescript
   // 在Store中添加devtools支持
   import { devtools } from 'zustand/middleware';
   
   export const useChatStore = create<ChatStore>()(
     devtools(
       (set, get) => ({
         // ... store实现
       }),
       { name: 'ChatStore' }
     )
   );
   ```

**3. 使用浏览器Network Tab**
   - 查看API请求和响应
   - 调试SSE流式响应

**4. 添加日志**
   ```typescript
   const handleSendMessage = useCallback(async (content: string) => {
     console.log('[ChatPage] Sending message:', content);
     try {
       await sendMessage(content);
       console.log('[ChatPage] Message sent successfully');
     } catch (error) {
       console.error('[ChatPage] Failed to send message:', error);
     }
   }, [sendMessage]);
   ```

### 8.4 性能优化

**1. 使用React.memo**
   ```typescript
   export default React.memo(MessageBubble);
   ```

**2. 使用useCallback和useMemo**
   ```typescript
   const handleSend = useCallback((content: string) => {
     // 处理逻辑
   }, [dependencies]);
   
   const sortedMessages = useMemo(() => {
     return messages.sort((a, b) => 
       new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
     );
   }, [messages]);
   ```

**3. 虚拟滚动（大数据量列表）**
   ```typescript
   import { FixedSizeList } from 'react-window';
   
   const MessageList: React.FC<{ messages: ChatMessage[] }> = ({ messages }) => {
     const Row = ({ index, style }: { index: number; style: React.CSSProperties }) => (
       <div style={style}>
         <MessageBubble message={messages[index]} />
       </div>
     );
     
     return (
       <FixedSizeList
         height={600}
         itemCount={messages.length}
         itemSize={100}
         width="100%"
       >
         {Row}
       </FixedSizeList>
     );
   };
   ```

**4. 代码分割（懒加载）**
   ```typescript
   import { lazy, Suspense } from 'react';
   
   const ChatPage = lazy(() => import('./pages/Chat/ChatPage'));
   
   const App: React.FC = () => {
     return (
       <Suspense fallback={<div>Loading...</div>}>
         <Routes>
           <Route path="chat" element={<ChatPage />} />
         </Routes>
       </Suspense>
     );
   };
   ```

---

## 9. 常见问题

### 9.1 Chat Store重复问题

**Q**: 为什么有2个Chat Store文件？
**A**: 可能是开发过程中的重复实现。需要统一为一个。

**解决方案**:
1. 比较 `chatStore.ts` 和 `useChatStore.ts`
2. 选择功能更完整的版本（建议 `chatStore.ts`）
3. 删除另一个文件
4. 更新所有导入语句

### 9.2 API集成问题

**Q**: 如何从模拟数据切换到真实API？
**A**: 
1. 确保后端API已启动
2. 更新 `src/api/modules/chat.ts` 中的API函数
3. 在Store中调用API函数（替换模拟数据逻辑）
4. 测试API请求和响应

**Q**: SSE流式响应不工作？
**A**: 
1. 检查后端SSE端点是否正确
2. 检查CORS配置
3. 使用浏览器Network Tab查看SSE流
4. 检查前端EventSource或Fetch API实现

### 9.3 国际化问题

**Q**: 添加新翻译后不生效？
**A**: 
1. 确保更新了**所有**语言文件
2. 重启开发服务器
3. 检查翻译键路径是否正确
4. 使用 `t('key.path')` 而不是 `t('key.path', { returnNull: false })`

**Q**: 如何动态切换语言？
**A**: 
```typescript
const { i18n } = useTranslation();
i18n.changeLanguage('en-US');
```

### 9.4 主题切换问题

**Q**: 主题切换不生效？
**A**: 
1. 检查 `ThemeContext` 是否正确提供
2. 检查 `data-theme` 属性是否应用到 `document.documentElement`
3. 检查CSS中是否正确使用了 `[data-theme='dark']` 选择器
4. 确保Ant Design的 `ConfigProvider` 正确配置了 `theme.algorithm`

**Q**: 如何自定义主题颜色？
**A**: 
```typescript
// src/styles/global.css
:root {
  --primary-color: #1890ff;
  --bg-color: #ffffff;
  --text-color: #000000;
}

[data-theme='dark'] {
  --primary-color: #177ddc;
  --bg-color: #1f1f1f;
  --text-color: #ffffff;
}
```

### 9.5 路由问题

**Q**: 添加新页面后路由不生效？
**A**: 
1. 确保在 `App.tsx` 中添加了路由配置
2. 确保在 `MainLayout.tsx` 中添加了菜单项
3. 检查路由路径是否正确
4. 使用 `<Navigate />` 设置默认路由

**Q**: 子路由如何配置？
**A**: 
```typescript
// App.tsx
<Route path="settings" element={<SettingsPage />}>
  <Route path="profile" element={<ProfilePage />} />
  <Route path="security" element={<SecurityPage />} />
</Route>

// SettingsPage.tsx
<div>
  <h1>Settings</h1>
  <Outlet />  {/* 子路由渲染在这里 */}
</div>
```

---

## 📝 总结

本指南涵盖了Neurova前端架构的核心内容，包括：

1. ✅ **路由系统** - react-router-dom配置
2. ✅ **状态管理** - Zustand使用规范
3. ✅ **国际化** - i18next集成
4. ✅ **主题切换** - ThemeContext实现
5. ✅ **Chat页面架构** - 组件结构和功能
6. ✅ **API集成** - Axios配置和SSE流式响应
7. ✅ **开发指南** - 代码规范和调试技巧
8. ✅ **常见问题** - 故障排除

**下一步**:

1. frontend-chat-dev应该：
   - 阅读本指南
   - 检查Chat页面现有实现
   - 统一Chat Store（解决重复问题）
   - 集成真实API（替换模拟数据）
   - 优化现有功能（Markdown渲染、代码高亮等）
   - 添加单元测试

2. frontend-arch-dev将：
   - 每4小时检查frontend-chat-dev的进度
   - 提供技术支持和代码审查
   - 协助解决架构问题

---

**文档版本历史**:

- v1.0 (2026-05-13) - 初始版本，为frontend-chat-dev准备
  - 作者: frontend-arch-dev
  - 审核: pending
  - 批准: pending

---

**联系信息**:

如有问题或需要澄清，请联系：
- **frontend-arch-dev** (前端架构师)
- **team-lead** (团队负责人)

---

**祝开发顺利！** 🚀
