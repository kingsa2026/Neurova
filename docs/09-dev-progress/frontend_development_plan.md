# Neurova 前端开发计划

> **文档版本**: v2.0  
> **创建日期**: 2026-05-13  
> **作者**: AI Agent (CodeBuddy)  
> **参考文档**: FRONTEND_PLAN.md (Vue 蓝本), frontend_architecture_guide.md

---

## 📋 目录

1. [设计风格指南](#1-设计风格指南)
2. [性能优化方案](#2-性能优化方案)
3. [开发优先级](#3-开发优先级)
4. [API 清单](#4-api-清单)
5. [技术栈](#5-技术栈)
6. [开发规范](#6-开发规范)
7. [测试要求](#7-测试要求)
8. [附录](#8-附录)

---

## 1. 设计风格指南

### 1.1 设计原则

#### 核心原则
- **简洁大方**: 去除冗余元素，突出核心功能
- **统一风格**: 所有页面遵循相同的设计语言
- **配色合理**: 使用统一的色彩系统
- **响应式设计**: 适配桌面端、平板、移动端
- **无障碍访问**: 符合 WCAG 2.1 AA 标准

#### 设计语言
```
风格定位: 科技感 + 简约 + 专业
视觉层次: 清晰的信息架构，合理的留白
交互反馈: 即时的操作反馈，流畅的动画过渡
```

---

### 1.2 色彩系统

#### 主色调（从 Vue 蓝本提取并优化）

```css
/* === 核心色彩变量 === */
:root {
  /* 主题色 - 蓝色系（科技感） */
  --primary-color: #0066FF;        /* Neurova 蓝 - 主操作按钮 */
  --primary-hover: #0052CC;        /* 悬停状态 */
  --primary-active: #003D99;       /* 激活状态 */
  --primary-light: #E6F0FF;       /* 浅色背景 */
  
  /* 强调色 - 青色系（活力感） */
  --accent-color: #00CCFF;         /* Nova 亮色 - 高亮元素 */
  --accent-hover: #00A3D9;        /* 悬停状态 */
  
  /* 点缀色 - 金色系（高级感） */
  --highlight-color: #FFD700;      /* 突触金 - 重要提示 */
  --highlight-light: #FFF4CC;     /* 浅色背景 */
  
  /* 背景色 - 深色系（太空主题） */
  --bg-primary: #060A14;          /* 主背景 - Deep Space */
  --bg-secondary: #0B1224;        /* 次级背景 */
  --bg-glass: rgba(11, 18, 36, 0.6); /* 玻璃态背景 */
  --bg-card: #111827;             /* 卡片背景 */
  
  /* 文本色 */
  --text-primary: #FFFFFF;         /* 主文本 */
  --text-secondary: #B0BEC5;      /* 次级文本 */
  --text-disabled: #546E7A;       /* 禁用文本 */
  
  /* 边框色 */
  --border-color: rgba(0, 102, 255, 0.2);  /* 默认边框 */
  --border-hover: rgba(0, 102, 255, 0.4);  /* 悬停边框 */
  
  /* 功能色 */
  --success-color: #00C853;        /* 成功 */
  --warning-color: #FFD740;       /* 警告 */
  --error-color: #FF5252;         /* 错误 */
  --info-color: #448AFF;          /* 信息 */
}
```

#### 色彩使用规范

| 用途 | 颜色 | 使用场景 |
|------|------|----------|
| **主操作** | `--primary-color` | 主要按钮、链接、图标 |
| **高亮元素** | `--accent-color` | 选中状态、进度条、加载动画 |
| **重要提示** | `--highlight-color` | 徽章、标签、重要通知 |
| **背景** | `--bg-primary` | 页面背景、侧边栏 |
| **卡片** | `--bg-card` | 内容卡片、对话框 |
| **成功状态** | `--success-color` | 成功提示、完成状态 |
| **警告状态** | `--warning-color` | 警告提示、待处理状态 |
| **错误状态** | `--error-color` | 错误提示、删除操作 |

---

### 1.3 排版系统

#### 字体规范

```css
/* === 字体变量 === */
:root {
  /* 中文字体 */
  --font-family-zh: -apple-system, BlinkMacSystemFont, "Segoe UI", 
                     "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", 
                     sans-serif;
  
  /* 等宽字体（代码） */
  --font-family-mono: "JetBrains Mono", "Fira Code", "Consolas", 
                       "Monaco", monospace;
  
  /* 字体大小 */
  --font-size-xs: 12px;           /* 辅助文本 */
  --font-size-sm: 14px;           /* 正文小字 */
  --font-size-base: 16px;         /* 正文 */
  --font-size-lg: 18px;           /* 小标题 */
  --font-size-xl: 24px;           /* 中标题 */
  --font-size-2xl: 32px;          /* 大标题 */
  --font-size-3xl: 48px;         /* 页面标题 */
  
  /* 行高 */
  --line-height-tight: 1.25;      /* 标题 */
  --line-height-base: 1.5;        /* 正文 */
  --line-height-loose: 1.75;      /* 长文本 */
  
  /* 字重 */
  --font-weight-normal: 400;      /* 常规 */
  --font-weight-medium: 500;      /* 中等 */
  --font-weight-semibold: 600;    /* 半粗 */
  --font-weight-bold: 700;        /* 粗体 */
}
```

#### 排版层次

```typescript
// 标题层次
export const typography = {
  h1: {
    fontSize: '32px',
    fontWeight: 700,
    lineHeight: 1.25,
    color: 'var(--text-primary)',
  },
  h2: {
    fontSize: '24px',
    fontWeight: 600,
    lineHeight: 1.3,
    color: 'var(--text-primary)',
  },
  h3: {
    fontSize: '18px',
    fontWeight: 600,
    lineHeight: 1.4,
    color: 'var(--text-primary)',
  },
  body: {
    fontSize: '16px',
    fontWeight: 400,
    lineHeight: 1.5,
    color: 'var(--text-primary)',
  },
  caption: {
    fontSize: '12px',
    fontWeight: 400,
    lineHeight: 1.5,
    color: 'var(--text-secondary)',
  },
};
```

---

### 1.4 组件风格

#### 卡片设计

```css
/* === 卡片组件规范 === */
.neurova-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  backdrop-filter: blur(10px);  /* 玻璃态效果 */
  box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1),
              0 0 30px rgba(0, 102, 255, 0.1);  /* 蓝色光晕 */
  transition: all 0.3s ease;
}

.neurova-card:hover {
  border-color: var(--border-hover);
  box-shadow: 0 8px 12px rgba(0, 0, 0, 0.15),
              0 0 40px rgba(0, 102, 255, 0.2);
  transform: translateY(-2px);
}
```

#### 按钮设计

```css
/* === 按钮组件规范 === */
.neurova-btn-primary {
  background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
  color: white;
  border: none;
  border-radius: 8px;
  padding: 12px 24px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 2px 8px rgba(0, 102, 255, 0.3);
}

.neurova-btn-primary:hover {
  background: linear-gradient(135deg, var(--primary-hover), var(--accent-hover));
  box-shadow: 0 4px 12px rgba(0, 102, 255, 0.4);
  transform: translateY(-1px);
}

.neurova-btn-primary:active {
  transform: translateY(0);
}
```

#### 输入框设计

```css
/* === 输入框组件规范 === */
.neurova-input {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 12px 16px;
  color: var(--text-primary);
  font-size: 16px;
  transition: all 0.3s ease;
}

.neurova-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(0, 102, 255, 0.1);
  outline: none;
}
```

---

### 1.5 布局规范

#### 间距系统

```css
/* === 间距变量 === */
:root {
  --spacing-xs: 4px;              /* 最小间距 */
  --spacing-sm: 8px;              /* 小间距 */
  --spacing-md: 16px;             /* 中间距 */
  --spacing-lg: 24px;             /* 大间距 */
  --spacing-xl: 32px;             /* 超大间距 */
  --spacing-2xl: 48px;            /* 页面间距 */
  
  /* 布局尺寸 */
  --sidebar-width: 240px;         /* 侧边栏宽度 */
  --header-height: 64px;          /* 顶栏高度 */
  --content-max-width: 1200px;    /* 内容最大宽度 */
}
```

#### 响应式断点

```css
/* === 响应式断点 === */
:root {
  --breakpoint-sm: 576px;         /* 手机横屏 */
  --breakpoint-md: 768px;         /* 平板 */
  --breakpoint-lg: 992px;         /* 桌面 */
  --breakpoint-xl: 1200px;       /* 大屏 */
}

/* 使用示例 */
@media (max-width: 768px) {
  .neurova-sidebar {
    width: 100%;
    position: fixed;
    z-index: 1000;
  }
}
```

---

### 1.6 动画规范

#### 过渡动画

```css
/* === 动画变量 === */
:root {
  --transition-fast: 0.15s ease;
  --transition-base: 0.3s ease;
  --transition-slow: 0.5s ease;
}

/* 使用示例 */
.neurova-fade-in {
  animation: fadeIn var(--transition-base);
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

#### 加载动画

```css
/* === 加载动画 === */
.neurova-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border-color);
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
```

---

## 2. 性能优化方案

### 2.1 模块化加载策略

#### 核心原则
- **按需加载**: 只加载当前页面需要的代码
- **代码分割**: 将大型库拆分为小块
- **懒加载**: 延迟加载非关键资源
- **预加载**: 预测用户行为，提前加载

---

### 2.2 路由级代码分割

#### 实现方案（React.lazy + Suspense）

```typescript
// src/App.tsx
import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import LoadingSpinner from '@/components/LoadingSpinner';

// ✅ 路由级懒加载 - 每个页面独立打包
const ChatPage = lazy(() => import('@/pages/Chat/ChatPage'));
const AgentPage = lazy(() => import('@/pages/Agent/AgentPage'));
const SettingsPage = lazy(() => import('@/pages/Settings/SettingsPage'));
const ControlPage = lazy(() => import('@/pages/Control/ControlPage'));
const MemoryPage = lazy(() => import('@/pages/Memory/MemoryPage'));  // 新增
const SkillMarketPage = lazy(() => import('@/pages/SkillMarket/SkillMarketPage'));  // 新增

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingSpinner />}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/agent" element={<AgentPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/control" element={<ControlPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/skill-market" element={<SkillMarketPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
```

#### 打包结果
```
dist/
├── assets/
│   ├── index-abc123.js           # 主包（~50KB）
│   ├── ChatPage-def456.js        # Chat 页面（~80KB）
│   ├── AgentPage-ghi789.js       # Agent 页面（~120KB）
│   ├── SettingsPage-jkl012.js    # Settings 页面（~60KB）
│   ├── ControlPage-mno345.js     # Control 页面（~90KB）
│   ├── MemoryPage-pqr678.js      # Memory 页面（~70KB）
│   └── SkillMarketPage-stu901.js # Skill 市场（~100KB）
```

**优势**:
- ✅ 首屏加载仅需 `~50KB`（主包）
- ✅ 每个页面独立加载，避免一次性加载所有代码
- ✅ 页面切换时按需加载对应 chunk

---

### 2.3 组件级懒加载

#### 实现方案（动态 import）

```typescript
// src/pages/Chat/ChatPage.tsx
import { lazy, Suspense } from 'react';
import { Tabs } from 'antd';

// ✅ 组件级懒加载 - 重型组件独立打包
const MessageList = lazy(() => import('./components/MessageList'));
const ModelSelector = lazy(() => import('./components/ModelSelector'));
const SettingsPanel = lazy(() => import('./components/SettingsPanel'));

export default function ChatPage() {
  return (
    <div className="chat-page">
      <Tabs>
        <TabPane tab="消息" key="messages">
          <Suspense fallback={<Spin />}>
            <MessageList />
          </Suspense>
        </TabPane>
        <TabPane tab="模型" key="model">
          <Suspense fallback={<Spin />}>
            <ModelSelector />
          </Suspense>
        </TabPane>
        <TabPane tab="设置" key="settings">
          <Suspense fallback={<Spin />}>
            <SettingsPanel />
          </Suspense>
        </TabPane>
      </Tabs>
    </div>
  );
}
```

---

### 2.4 第三方库按需引入

#### Ant Design 按需引入

```typescript
// ❌ 错误做法 - 全量引入（~500KB）
import Antd from 'antd';
import 'antd/dist/antd.css';

// ✅ 正确做法 - 按需引入（~50KB）
import Button from 'antd/es/button';
import Input from 'antd/es/input';
import Select from 'antd/es/select';
import 'antd/es/button/style/css';
import 'antd/es/input/style/css';
import 'antd/es/select/style/css';
```

#### Lodash 按需引入

```typescript
// ❌ 错误做法 - 全量引入（~70KB）
import _ from 'lodash';

// ✅ 正确做法 - 按需引入（~5KB）
import debounce from 'lodash/debounce';
import throttle from 'lodash/throttle';
```

#### ECharts 按需引入

```typescript
// ❌ 错误做法 - 全量引入（~800KB）
import * as echarts from 'echarts';

// ✅ 正确做法 - 按需引入（~200KB）
import * as echarts from 'echarts/core';
import { LineChart, BarChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer]);
```

---

### 2.5 动态导入 API 模块

#### 实现方案

```typescript
// src/api/index.ts
// ❌ 错误做法 - 一次性加载所有 API 模块
export * from './modules/chat';
export * from './modules/memory';
export * from './modules/agent';
export * from './modules/skill';
// ... 20+ 模块

// ✅ 正确做法 - 按需加载 API 模块
export const chatApi = {
  streamChat: (request: ChatRequest) =>
    import('./modules/chat').then(module => module.streamChat(request)),
};

export const memoryApi = {
  getMemories: (params: MemoryQuery) =>
    import('./modules/memory').then(module => module.getMemories(params)),
};
```

#### 使用示例

```typescript
// src/pages/Memory/MemoryPage.tsx
import { memoryApi } from '@/api';

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([]);

  useEffect(() => {
    // ✅ API 模块按需加载
    memoryApi.getMemories({ page: 1, limit: 20 }).then(setMemories);
  }, []);

  return (
    // ...
  );
}
```

---

### 2.6 预加载策略

#### 实现方案（预测用户行为）

```typescript
// src/utils/preload.ts
export function preloadPage(pageName: string) {
  switch (pageName) {
    case 'chat':
      import('@/pages/Chat/ChatPage');
      break;
    case 'agent':
      import('@/pages/Agent/AgentPage');
      break;
    case 'memory':
      import('@/pages/Memory/MemoryPage');
      break;
    // ...
  }
}

// src/components/Sidebar.tsx
import { preloadPage } from '@/utils/preload';

export default function Sidebar() {
  return (
    <nav>
      <Link 
        to="/chat"
        onMouseEnter={() => preloadPage('chat')}  // 鼠标悬停时预加载
      >
        聊天
      </Link>
      <Link 
        to="/agent"
        onMouseEnter={() => preloadPage('agent')}
      >
        Agent
      </Link>
    </nav>
  );
}
```

---

### 2.7 虚拟滚动（长列表优化）

#### 实现方案（react-window）

```typescript
// src/pages/Chat/components/MessageList.tsx
import { FixedSizeList } from 'react-window';
import AutoSizer from 'react-virtualized-auto-sizer';

export default function MessageList({ messages }: { messages: Message[] }) {
  return (
    <AutoSizer>
      {({ height, width }) => (
        <FixedSizeList
          height={height}
          width={width}
          itemCount={messages.length}
          itemSize={100}  // 每条消息高度
        >
          {({ index, style }) => (
            <div style={style}>
              <MessageItem message={messages[index]} />
            </div>
          )}
        </FixedSizeList>
      )}
    </AutoSizer>
  );
}
```

**优势**:
- ✅ 只渲染可见区域的消息（例如只渲染 20 条，而不是 1000 条）
- ✅ 内存占用从 `~500MB` 降低到 `~50MB`
- ✅ 滚动流畅，无卡顿

---

### 2.8 图片懒加载

#### 实现方案（Intersection Observer）

```typescript
// src/components/LazyImage.tsx
import { useRef, useEffect, useState } from 'react';

interface LazyImageProps {
  src: string;
  placeholder: string;
  alt: string;
}

export default function LazyImage({ src, placeholder, alt }: LazyImageProps) {
  const [isLoaded, setIsLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setIsLoaded(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 }
    );

    if (imgRef.current) {
      observer.observe(imgRef.current);
    }

    return () => observer.disconnect();
  }, []);

  return (
    <img
      ref={imgRef}
      src={isLoaded ? src : placeholder}
      alt={alt}
      className="lazy-image"
    />
  );
}
```

---

### 2.9 Webpack/Vite 配置优化

#### Vite 配置（vite.config.ts）

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // ✅ 手动分包 - 将大型库独立打包
        manualChunks: {
          'antd': ['antd'],
          'echarts': ['echarts'],
          'react': ['react', 'react-dom'],
          'react-router': ['react-router-dom'],
        },
      },
    },
    // ✅ 开启 Gzip 压缩
    compress: 'gzip',
    // ✅ 去除 console 和 debugger
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      },
    },
  },
  // ✅ 依赖预构建 - 提升开发体验
  optimizeDeps: {
    include: ['antd', 'echarts', 'react-window'],
  },
});
```

#### 打包结果

```
dist/
├── assets/
│   ├── index-abc123.js           # 主包（~50KB）
│   ├── antd-vendor-def456.js     # Ant Design（~150KB）
│   ├── echarts-vendor-ghi789.js  # ECharts（~200KB）
│   ├── react-vendor-jkl012.js    # React（~50KB）
│   └── ...                       # 其他页面 chunks
```

**优势**:
- ✅ 大型库独立打包，利用浏览器缓存
- ✅ 用户更新代码后，只需重新下载主包，无需下载 vendor 包
- ✅ Gzip 压缩后，总体积减少 `~60%`

---

### 2.10 性能监控

#### 实现方案（Performance API）

```typescript
// src/utils/performance.ts
export function measurePageLoad(pageName: string) {
  const startTime = performance.now();

  return {
    end: () => {
      const endTime = performance.now();
      const duration = endTime - startTime;
      
      console.log(`[Performance] ${pageName} 加载耗时: ${duration.toFixed(2)}ms`);
      
      // 发送到监控系统
      if (duration > 3000) {
        reportSlowPage(pageName, duration);
      }
    },
  };
}

// 使用示例
const measure = measurePageLoad('ChatPage');
// ... 页面加载逻辑
measure.end();
```

---

## 3. 开发优先级

### P0 - 核心功能（必须完成）

#### P0.1: 完善 Agent 主页面
- **描述**: 将 `AgentPage.tsx` 从 "Under development" 改为完整页面
- **任务**:
  - [ ] 集成 Config、Skills、Tools、Workspace 子页面
  - [ ] 实现 Agent 列表展示
  - [ ] 实现 Agent 创建/编辑/删除功能
- **API 依赖**: `agent.ts`
- **设计风格**: 遵循 1.4 组件风格规范

---

#### P0.2: 开发认证系统
- **描述**: 实现登录、注册、权限管理页面
- **任务**:
  - [ ] 登录页面（LoginPage.tsx）
  - [ ] 注册页面（RegisterPage.tsx）
  - [ ] 权限管理页面（PermissionPage.tsx）
  - [ ] Token 刷新机制
- **API 依赖**: `auth.ts`（需要新建）
- **设计风格**: 简洁大方的表单设计，参考 1.3 排版系统

---

#### P0.3: 开发记忆管理页面
- **描述**: 实现记忆查看、搜索、编辑、删除功能
- **任务**:
  - [ ] 记忆列表页面（MemoryListPage.tsx）
  - [ ] 记忆详情页面（MemoryDetailPage.tsx）
  - [ ] 记忆搜索功能
  - [ ] 记忆编辑功能
- **API 依赖**: `memory.ts`（需要新建）
- **性能优化**: 使用虚拟滚动（react-window）优化长列表

---

#### P0.4: 补充核心 API 模块
- **描述**: 开发缺失的核心 API 模块
- **任务**:
  - [ ] `memory.ts` - 记忆管理 API
  - [ ] `auth.ts` - 认证 API
  - [ ] `model.ts` - 模型管理 API
- **API 清单**: 参考第 4 章
- **性能优化**: 使用动态导入（2.5 节）

---

### P1 - 重要功能（建议完成）

#### P1.1: 开发 Skill 市场页面
- **描述**: 实现 Skill 浏览、搜索、安装、更新功能
- **任务**:
  - [ ] Skill 市场首页（SkillMarketPage.tsx）
  - [ ] Skill 详情页面（SkillDetailPage.tsx）
  - [ ] Skill 搜索功能
  - [ ] Skill 安装/卸载功能
- **API 依赖**: `skill_market.ts`（需要新建）
- **设计风格**: 卡片式布局，参考 1.4 卡片设计

---

#### P1.2: 开发模型管理页面
- **描述**: 实现模型配置、切换、测试功能
- **任务**:
  - [ ] 模型列表页面（ModelListPage.tsx）
  - [ ] 模型配置页面（ModelConfigPage.tsx）
  - [ ] 模型测试功能
- **API 依赖**: `model.ts`
- **性能优化**: 使用路由级代码分割（2.2 节）

---

#### P1.3: 开发生成管理页面
- **描述**: 实现生成任务管理、结果查看功能
- **任务**:
  - [ ] 生成任务列表（GenerationListPage.tsx）
  - [ ] 生成结果查看（GenerationResultPage.tsx）
- **API 依赖**: `generation.ts`（需要新建）

---

#### P1.4: 开发 Console API 前端
- **描述**: 实现 Console 页面，对接 console API
- **任务**:
  - [ ] Console 首页（ConsolePage.tsx）
  - [ ] 实时监控面板
  - [ ] 日志查看功能
- **API 依赖**: `console.ts`（需要新建）

---

### P2 - 协作功能（可选完成）

#### P2.1: 开发项目管理页面
- **描述**: 实现项目创建、编辑、删除功能
- **API 依赖**: `projects.ts`（需要新建）

---

#### P2.2: 开发工作流管理页面
- **描述**: 实现工作流设计、执行、监控功能
- **API 依赖**: `workflows.ts`（需要新建）
- **性能优化**: 使用组件级懒加载（2.3 节）

---

#### P2.3: 开发文件流管理页面
- **描述**: 实现文件上传、下载、分享功能
- **API 依赖**: `file_flows.ts`（需要新建）

---

#### P2.4: 开发团队管理页面
- **描述**: 实现团队成员管理、权限分配功能
- **API 依赖**: `teams.ts`（需要新建）

---

#### P2.5: 开发任务管理页面
- **描述**: 实现任务创建、分配、跟踪功能
- **API 依赖**: `tasks.ts`（需要新建）

---

#### P2.6: 开发群组管理页面
- **描述**: 实现群组创建、管理、消息发送功能
- **API 依赖**: `groups.ts`（需要新建）

---

### P3 - 高级功能（远期完成）

#### P3.1: 开发日志管理页面
- **描述**: 实现日志查看、搜索、导出功能
- **API 依赖**: `logs.ts`（需要新建）

---

#### P3.2: 开发成长系统页面
- **描述**: 实现成长跟踪、成就展示功能
- **API 依赖**: `growth.ts`（需要新建）

---

#### P3.3: 开发媒体存储页面
- **描述**: 实现媒体文件管理功能
- **API 依赖**: `media.ts`（需要新建）
- **性能优化**: 使用图片懒加载（2.8 节）

---

#### P3.4: 开发上下文管理页面
- **描述**: 实现上下文配置、优化功能
- **API 依赖**: `context.ts`（需要新建）

---

#### P3.5: 开发 Agent 增强页面
- **描述**: 实现 Agent 增强功能配置
- **API 依赖**: `agent_enhancement.ts`（需要新建）

---

#### P3.6: 开发记忆增强页面
- **描述**: 实现记忆增强功能配置
- **API 依赖**: `memory_enhancement.ts`（需要新建）

---

## 4. API 清单

### 4.1 认证接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/auth/login` | POST | 登录 | `auth.ts` |
| 2 | `/auth/register` | POST | 注册 | `auth.ts` |
| 3 | `/auth/refresh` | POST | 刷新 Token | `auth.ts` |
| 4 | `/auth/logout` | POST | 登出 | `auth.ts` |
| 5 | `/auth/me` | GET | 获取当前用户信息 | `auth.ts` |

---

### 4.2 对话接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/chat/stream` | POST | SSE 流式对话 | `chat.ts` |
| 2 | `/chat/conversations` | GET | 获取会话列表 | `chat.ts` |
| 3 | `/chat/conversations/:id` | DELETE | 删除会话 | `chat.ts` |
| 4 | `/chat/conversations/:id/rename` | POST | 重命名会话 | `chat.ts` |
| 5 | `/chat/messages` | GET | 获取消息列表 | `chat.ts` |

---

### 4.3 记忆接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/memories` | GET | 获取记忆列表 | `memory.ts` |
| 2 | `/memories/:id` | GET | 获取记忆详情 | `memory.ts` |
| 3 | `/memories` | POST | 创建记忆 | `memory.ts` |
| 4 | `/memories/:id` | PUT | 更新记忆 | `memory.ts` |
| 5 | `/memories/:id` | DELETE | 删除记忆 | `memory.ts` |
| 6 | `/memories/search` | GET | 搜索记忆 | `memory.ts` |
| 7 | `/memories/:id/temperature` | PUT | 调整记忆温度 | `memory.ts` |
| 8 | `/memories/consolidate` | POST | 记忆巩固 | `memory.ts` |
| 9 | `/memories/forget` | POST | 记忆遗忘 | `memory.ts` |

---

### 4.4 Agent 接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/agents` | GET | 获取 Agent 列表 | `agent.ts` |
| 2 | `/agents/:id` | GET | 获取 Agent 详情 | `agent.ts` |
| 3 | `/agents` | POST | 创建 Agent | `agent.ts` |
| 4 | `/agents/:id` | PUT | 更新 Agent | `agent.ts` |
| 5 | `/agents/:id` | DELETE | 删除 Agent | `agent.ts` |
| 6 | `/agents/:id/start` | POST | 启动 Agent | `agent.ts` |
| 7 | `/agents/:id/stop` | POST | 停止 Agent | `agent.ts` |

---

### 4.5 技能接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/skills` | GET | 获取技能列表 | `skill.ts` |
| 2 | `/skills/:id` | GET | 获取技能详情 | `skill.ts` |
| 3 | `/skills` | POST | 创建技能 | `skill.ts` |
| 4 | `/skills/:id` | PUT | 更新技能 | `skill.ts` |
| 5 | `/skills/:id` | DELETE | 删除技能 | `skill.ts` |

---

### 4.6 渠道接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/channels` | GET | 获取渠道列表 | `channel.ts` |
| 2 | `/channels/:id` | GET | 获取渠道详情 | `channel.ts` |
| 3 | `/channels` | POST | 创建渠道 | `channel.ts` |
| 4 | `/channels/:id` | PUT | 更新渠道 | `channel.ts` |
| 5 | `/channels/:id` | DELETE | 删除渠道 | `channel.ts` |
| 6 | `/channels/:id/qrcode` | GET | 获取渠道二维码 | `channel.ts` |

---

### 4.7 系统配置接口

| 序号 | 接口路径 | 方法 | 说明 | 前端模块 |
|------|----------|------|------|----------|
| 1 | `/config` | GET | 获取系统配置 | `settings.ts` |
| 2 | `/config` | PUT | 更新系统配置 | `settings.ts` |
| 3 | `/config/llm` | GET | 获取 LLM 配置 | `settings.ts` |
| 4 | `/config/llm` | PUT | 更新 LLM 配置 | `settings.ts` |

---

## 5. 技术栈

### 5.1 核心技术

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.x | UI 框架 |
| TypeScript | 5.8+ | 类型安全 |
| Vite | 6.3+ | 构建工具 |
| React Router DOM | 6.x | 路由管理 |
| Zustand | 5.0+ | 状态管理 |
| Ant Design | 5.29+ | UI 组件库 |
| @agentscope-ai/design | 1.0+ | 设计系统 |
| i18next | 25.8+ | 国际化 |
| Vitest | 4.1+ | 单元测试 |
| @testing-library/react | 16.3+ | 组件测试 |

---

### 5.2 辅助工具

| 工具 | 版本 | 用途 |
|------|------|------|
| Axios | 1.8+ | HTTP 请求 |
| SSE.js | 0.6+ | SSE 流式响应 |
| react-window | 1.8+ | 虚拟滚动 |
| echarts | 5.6+ | 数据可视化 |
| dayjs | 1.11+ | 日期处理 |
| zod | 3.24+ | 运行时类型校验 |

---

## 6. 开发规范

### 6.1 文件命名

```
✅ 正确示例:
- ChatPage.tsx              # 页面组件（PascalCase）
- MessageList.tsx           # 子组件（PascalCase）
- useChat.ts                # Hook（camelCase + use 前缀）
- chatStore.ts              # Store（camelCase + Store 后缀）
- chatApi.ts                # API 模块（camelCase + Api 后缀）
- ChatPage.test.tsx         # 测试文件（与原文件同名 + .test 后缀）

❌ 错误示例:
- chat-page.tsx             # 错误：使用 kebab-case
- Chat_page.tsx             # 错误：使用下划线
- use_chat.ts              # 错误：使用下划线
```

---

### 6.2 代码组织

```
src/
├── api/                    # API 层
│   ├── config.ts           # API 配置
│   ├── index.ts            # API 导出
│   └── modules/            # API 模块（按功能拆分）
│       ├── chat.ts
│       ├── memory.ts
│       └── ...
├── components/             # 通用组件
│   ├── Button/
│   │   ├── index.tsx
│   │   └── index.test.tsx
│   └── ...
├── pages/                  # 页面组件（按功能拆分）
│   ├── Chat/
│   │   ├── index.tsx       # 入口文件
│   │   ├── ChatPage.tsx    # 主页面
│   │   ├── components/     # 子组件
│   │   └── __tests__/      # 测试文件
│   └── ...
├── stores/                 # 状态管理（按功能拆分）
│   ├── chatStore.ts
│   ├── memoryStore.ts
│   └── ...
├── styles/                 # 样式文件
│   ├── variables.css       # CSS 变量
│   ├── global.css          # 全局样式
│   └── components/         # 组件样式
├── utils/                  # 工具函数（按功能拆分）
│   ├── request.ts          # HTTP 请求
│   ├── storage.ts          # 本地存储
│   └── ...
└── types/                  # TypeScript 类型定义
    ├── chat.ts
    ├── memory.ts
    └── ...
```

---

### 6.3 代码规范

#### TypeScript 规范

```typescript
// ✅ 正确示例：完整的类型定义
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  metadata?: Record<string, unknown>;
}

// ✅ 正确示例：使用泛型
function fetchData<T>(url: string): Promise<T> {
  return fetch(url).then(res => res.json());
}

// ❌ 错误示例：使用 any
function fetchData(url: string): Promise<any> {
  return fetch(url).then(res => res.json());
}
```

#### React 规范

```typescript
// ✅ 正确示例：使用函数组件 + TypeScript
interface ChatPageProps {
  conversationId: string;
  onMessageSend: (message: string) => void;
}

export default function ChatPage({ 
  conversationId, 
  onMessageSend 
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  
  return (
    // JSX
  );
}

// ❌ 错误示例：使用类组件（新项目不推荐）
export default class ChatPage extends React.Component {
  // ...
}
```

---

## 7. 测试要求

### 7.1 单元测试覆盖率

| 模块类型 | 覆盖率要求 | 说明 |
|----------|-----------|------|
| 页面组件 | ≥ 80% | 每个页面至少一个测试文件 |
| 通用组件 | ≥ 90% | 每个组件至少一个测试文件 |
| Hook | ≥ 90% | 每个 Hook 至少一个测试文件 |
| Store | ≥ 85% | 每个 Store 至少一个测试文件 |
| API 模块 | ≥ 80% | 每个 API 模块至少一个测试文件 |

---

### 7.2 测试示例

```typescript
// src/pages/Chat/__tests__/ChatPage.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import ChatPage from '../ChatPage';

describe('ChatPage', () => {
  it('should render correctly', () => {
    render(<ChatPage />);
    expect(screen.getByText('Neurova Chat')).toBeInTheDocument();
  });

  it('should send message when click send button', () => {
    render(<ChatPage />);
    const input = screen.getByPlaceholderText('输入消息...');
    const button = screen.getByText('发送');
    
    fireEvent.change(input, { target: { value: 'Hello' } });
    fireEvent.click(button);
    
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });
});
```

---

## 8. 附录

### 8.1 Vue 蓝本 API 代码示例

```javascript
// 从 Vue 蓝本提取的 API 客户端代码
// 文件位置: neurova/vue_old_backup_20260510_033048/js/app.js

const apiClient = {
  baseUrl: '/api/v1',
  token: null,
  refreshToken: null,
  
  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };
    
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }
    
    const response = await fetch(url, {
      ...options,
      headers,
    });
    
    if (response.status === 401 && this.refreshToken) {
      await this.refresh();
      return this.request(endpoint, options);
    }
    
    return response.json();
  },
  
  async refresh() {
    const response = await fetch(`${this.baseUrl}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refreshToken: this.refreshToken }),
    });
    
    const data = await response.json();
    this.token = data.accessToken;
    this.refreshToken = data.refreshToken;
  },
};
```

**翻译为 TypeScript（src/api/request.ts）**:

```typescript
// src/api/request.ts
import { message } from 'antd';

const BASE_URL = '/api/v1';

export interface ApiClient {
  request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;
  refresh: () => Promise<void>;
}

export const apiClient: ApiClient = {
  async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${BASE_URL}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };
    
    const token = localStorage.getItem('token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(url, {
      ...options,
      headers,
    });
    
    if (response.status === 401) {
      await this.refresh();
      return this.request<T>(endpoint, options);
    }
    
    if (!response.ok) {
      const error = await response.json();
      message.error(error.message || '请求失败');
      throw new Error(error.message);
    }
    
    return response.json();
  },
  
  async refresh(): Promise<void> {
    const refreshToken = localStorage.getItem('refreshToken');
    const response = await fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refreshToken }),
    });
    
    const data = await response.json();
    localStorage.setItem('token', data.accessToken);
    localStorage.setItem('refreshToken', data.refreshToken);
  },
};
```

---

### 8.2 CSS 变量完整清单

```css
/* === 从 Vue 蓝本提取并优化的 CSS 变量 === */
/* 文件位置: src/styles/variables.css */

:root {
  /* 主题色 */
  --primary-color: #0066FF;
  --primary-hover: #0052CC;
  --primary-active: #003D99;
  --primary-light: #E6F0FF;
  
  /* 强调色 */
  --accent-color: #00CCFF;
  --accent-hover: #00A3D9;
  
  /* 点缀色 */
  --highlight-color: #FFD700;
  --highlight-light: #FFF4CC;
  
  /* 背景色 */
  --bg-primary: #060A14;
  --bg-secondary: #0B1224;
  --bg-glass: rgba(11, 18, 36, 0.6);
  --bg-card: #111827;
  
  /* 文本色 */
  --text-primary: #FFFFFF;
  --text-secondary: #B0BEC5;
  --text-disabled: #546E7A;
  
  /* 边框色 */
  --border-color: rgba(0, 102, 255, 0.2);
  --border-hover: rgba(0, 102, 255, 0.4);
  
  /* 功能色 */
  --success-color: #00C853;
  --warning-color: #FFD740;
  --error-color: #FF5252;
  --info-color: #448AFF;
  
  /* 字体 */
  --font-family-zh: -apple-system, BlinkMacSystemFont, "Segoe UI", 
                     "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", 
                     sans-serif;
  --font-family-mono: "JetBrains Mono", "Fira Code", "Consolas", 
                       "Monaco", monospace;
  
  /* 字体大小 */
  --font-size-xs: 12px;
  --font-size-sm: 14px;
  --font-size-base: 16px;
  --font-size-lg: 18px;
  --font-size-xl: 24px;
  --font-size-2xl: 32px;
  --font-size-3xl: 48px;
  
  /* 行高 */
  --line-height-tight: 1.25;
  --line-height-base: 1.5;
  --line-height-loose: 1.75;
  
  /* 字重 */
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-semibold: 600;
  --font-weight-bold: 700;
  
  /* 间距 */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 32px;
  --spacing-2xl: 48px;
  
  /* 布局尺寸 */
  --sidebar-width: 240px;
  --header-height: 64px;
  --content-max-width: 1200px;
  
  /* 响应式断点 */
  --breakpoint-sm: 576px;
  --breakpoint-md: 768px;
  --breakpoint-lg: 992px;
  --breakpoint-xl: 1200px;
  
  /* 过渡动画 */
  --transition-fast: 0.15s ease;
  --transition-base: 0.3s ease;
  --transition-slow: 0.5s ease;
}
```

---

### 8.3 性能优化检查清单

```markdown
## 性能优化检查清单

### 代码分割
- [ ] 路由级代码分割（React.lazy + Suspense）
- [ ] 组件级懒加载（动态 import）
- [ ] 第三方库按需引入（Ant Design、Lodash、ECharts）
- [ ] API 模块动态导入

### 加载优化
- [ ] 预加载策略（预测用户行为）
- [ ] 图片懒加载（Intersection Observer）
- [ ] 虚拟滚动（react-window）

### 打包优化
- [ ] 手动分包（Webpack/Vite manualChunks）
- [ ] Gzip 压缩
- [ ] 去除 console 和 debugger
- [ ] 依赖预构建（Vite optimizeDeps）

### 运行时优化
- [ ] 防抖（debounce）和节流（throttle）
- [ ] 记忆化（React.memo、useMemo、useCallback）
- [ ] 性能监控（Performance API）

### 缓存策略
- [ ] 浏览器缓存（Cache-Control）
- [ ] Service Worker 缓存
- [ ] 本地存储（localStorage、sessionStorage）
```

---

## 📝 总结

本文档提供了完整的 Neurova 前端开发计划，包括：

1. **设计风格指南**（第 1 章）
   - ✅ 统一的设计语言（简洁大方）
   - ✅ 合理的配色方案（蓝色系 + 金色点缀）
   - ✅ 完整的排版系统
   - ✅ 组件风格规范

2. **性能优化方案**（第 2 章）
   - ✅ 模块化加载（路由级 + 组件级代码分割）
   - ✅ 按需加载（动态 import）
   - ✅ 第三方库优化（Ant Design、Lodash、ECharts）
   - ✅ 虚拟滚动（长列表优化）
   - ✅ 图片懒加载
   - ✅ 打包优化（手动分包、Gzip 压缩）

3. **开发优先级**（第 3 章）
   - ✅ P0 - 核心功能（4 个任务）
   - ✅ P1 - 重要功能（5 个任务）
   - ✅ P2 - 协作功能（7 个任务）
   - ✅ P3 - 高级功能（7 个任务）

4. **API 清单**（第 4 章）
   - ✅ 完整的后端 API 接口梳理（从 Vue 蓝本提取）

5. **技术栈和开发规范**（第 5-6 章）
   - ✅ 技术栈选型
   - ✅ 文件命名规范
   - ✅ 代码组织规范
   - ✅ 代码规范（TypeScript + React）

6. **测试要求**（第 7 章）
   - ✅ 单元测试覆盖率要求
   - ✅ 测试示例

7. **附录**（第 8 章）
   - ✅ Vue 蓝本 API 代码示例
   - ✅ CSS 变量完整清单
   - ✅ 性能优化检查清单

---

**下一步行动**:

1. **验证已完成模块的实际进度**（运行单元测试，检查覆盖率）
2. **开始 P0 任务**（完善 Agent 主页面、补充核心 API 模块）
3. **应用设计风格指南**（统一所有页面的设计风格）
4. **实施性能优化方案**（模块化加载、按需加载）

---

**文档维护**:

- 本文档应随项目进展持续更新
- 每次完成一个任务后，更新对应的状态码
- 发现新的优化点时，添加到对应章节

---

**参考文档**:

- [FRONTEND_PLAN.md](neurova/vue_old_backup_20260510_033048/FRONTEND_PLAN.md)（Vue 蓝本）
- [frontend_architecture_guide.md](docs/dev_progress/architecture/frontend_architecture_guide.md)
- [React 官方文档](https://react.dev/)
- [Vite 官方文档](https://vitejs.dev/)
- [Ant Design 官方文档](https://ant.design/)
