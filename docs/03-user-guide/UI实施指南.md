# Neurova UI 实施指南

## 一、快速开始

### 1.1 安装依赖
```bash
cd neuUI

# 图表库
npm install echarts apexcharts vue-apexcharts

# 图标库
npm install heroicons lucide-vue-next

# 图谱库（可选）
npm install d3 vis-network

# 代码高亮
npm install highlight.js
```

### 1.2 字体引入
在 `index.html` 中添加：
```html
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=Open+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

### 1.3 设计系统配置
在 `tailwind.config.js` 中添加：
```javascript
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#F5F3FF',
          100: '#EDE9FE',
          200: '#DDD6FE',
          300: '#C4B5FD',
          400: '#A78BFA',
          500: '#818CF8',
          600: '#6366F1',
          700: '#4F46E5',
          800: '#4338CA',
          900: '#3730A3',
        },
        cta: {
          50: '#ECFDF5',
          100: '#D1FAE5',
          200: '#A7F3D0',
          300: '#6EE7B7',
          400: '#34D399',
          500: '#10B981',
          600: '#059669',
          700: '#047857',
          800: '#065F46',
          900: '#064E3B',
        }
      },
      fontFamily: {
        heading: ['Poppins', 'sans-serif'],
        body: ['Open Sans', 'sans-serif'],
      },
    },
  },
}
```

## 二、组件开发示例

### 2.1 Dashboard 图表组件
**位置**: `src/components/charts/`

**已创建示例**:
- `TokenConsumptionChart.vue` - Token 消耗趋势图

**待创建组件**:
1. `AgentActivityHeatmap.vue` - Agent 活跃度热力图
2. `MemoryGrowthChart.vue` - 记忆增长曲线
3. `ToolUsageChart.vue` - 工具使用频率柱状图
4. `ModelPerformanceChart.vue` - 模型性能对比图

### 2.2 多模态输入组件
**位置**: `src/components/multimodal/`

**待创建组件**:
1. `VoiceInputButton.vue` - 语音输入按钮
2. `FileUploadPreview.vue` - 文件上传预览
3. `CodeSnippetInput.vue` - 代码片段输入
4. `RichMediaOutput.vue` - 富媒体输出

### 2.3 实时协作组件
**位置**: `src/components/collaboration/`

**待创建组件**:
1. `OnlineUsersList.vue` - 在线用户列表
2. `RealTimeCursors.vue` - 实时光标显示
3. `CollaborationTools.vue` - 协作工具面板
4. `VersionHistory.vue` - 版本历史查看

## 三、页面增强示例

### 3.1 DashboardPage 增强
**当前状态**: 基础统计卡片
**增强内容**:

```vue
<template>
  <div class="dashboard-page">
    <!-- 欢迎区域 -->
    <div class="welcome-section glass-effect">
      <!-- 现有内容 -->
    </div>

    <!-- 新增：实时数据图表 -->
    <div class="charts-section">
      <TokenConsumptionChart />
      <AgentActivityHeatmap />
      <MemoryGrowthChart />
    </div>

    <!-- 新增：个性化推荐 -->
    <div class="recommendations-section">
      <h3>为您推荐</h3>
      <div class="recommendation-cards">
        <!-- Agent 推荐 -->
        <!-- 技能推荐 -->
        <!-- 最近对话 -->
      </div>
    </div>

    <!-- 新增：快速操作 -->
    <div class="quick-actions">
      <a-button type="primary" @click="createAgent">
        <PlusOutlined /> 创建 Agent
      </a-button>
      <a-button @click="startChat">
        <MessageOutlined /> 开始对话
      </a-button>
      <a-button @click="switchModel">
        <SwapOutlined /> 切换模型
      </a-button>
    </div>
  </div>
</template>
```

### 3.2 ChatPage 多模态增强
**当前状态**: 完整聊天界面
**增强内容**:

```vue
<template>
  <div class="chat-page">
    <!-- 现有内容 -->

    <!-- 新增：多模态输入区域 -->
    <div class="input-area">
      <div class="input-actions">
        <VoiceInputButton @voice-input="handleVoiceInput" />
        <FileUploadPreview @file-upload="handleFileUpload" />
        <CodeSnippetInput @code-input="handleCodeInput" />
      </div>
      
      <a-textarea
        v-model:value="message"
        placeholder="输入消息..."
        @press-enter="sendMessage"
      />
      
      <a-button type="primary" @click="sendMessage">
        <SendOutlined />
      </a-button>
    </div>

    <!-- 新增：富媒体输出 -->
    <div class="message-output">
      <!-- 图片预览 -->
      <!-- 音频播放器 -->
      <!-- 代码高亮 -->
      <!-- 表格可视化 -->
    </div>
  </div>
</template>
```

## 四、API 集成示例

### 4.1 创建 API 模块
**位置**: `src/api/modules/analytics.ts`

```typescript
import api from '@/api'

export interface TokenUsage {
  date: string
  tokens: number
  cost: number
}

export interface AgentActivity {
  agentId: string
  agentName: string
  activity: number
  lastActive: string
}

export const analyticsApi = {
  // 获取 Token 使用趋势
  getTokenUsageTrend(days: number = 7): Promise<TokenUsage[]> {
    return api.get(`/analytics/token-usage?days=${days}`)
  },

  // 获取 Agent 活跃度
  getAgentActivity(): Promise<AgentActivity[]> {
    return api.get('/analytics/agent-activity')
  },

  // 获取模型性能对比
  getModelPerformance(): Promise<any[]> {
    return api.get('/analytics/model-performance')
  },

  // 获取使用统计
  getUsageStats(): Promise<any> {
    return api.get('/analytics/usage-stats')
  }
}
```

### 4.2 创建 Pinia Store
**位置**: `src/stores/analytics.ts`

```typescript
import { defineStore } from 'pinia'
import { analyticsApi } from '@/api/modules/analytics'

export const useAnalyticsStore = defineStore('analytics', {
  state: () => ({
    tokenUsage: [],
    agentActivity: [],
    modelPerformance: [],
    usageStats: null,
    loading: false,
    error: null
  }),

  actions: {
    async fetchTokenUsage(days: number = 7) {
      this.loading = true
      try {
        this.tokenUsage = await analyticsApi.getTokenUsageTrend(days)
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },

    async fetchAgentActivity() {
      this.loading = true
      try {
        this.agentActivity = await analyticsApi.getAgentActivity()
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    },

    async fetchModelPerformance() {
      this.loading = true
      try {
        this.modelPerformance = await analyticsApi.getModelPerformance()
      } catch (error) {
        this.error = error.message
      } finally {
        this.loading = false
      }
    }
  }
})
```

## 五、路由配置示例

### 5.1 新增路由
在 `src/router/index.ts` 中添加：

```typescript
const routes = [
  // 现有路由...

  // 新增：分析仪表板
  {
    path: '/analytics',
    name: 'Analytics',
    component: () => import('@/pages/AnalyticsDashboard.vue'),
    meta: { title: '分析仪表板', icon: 'ChartBarIcon' }
  },

  // 新增：插件市场
  {
    path: '/plugins',
    name: 'Plugins',
    component: () => import('@/pages/PluginMarket.vue'),
    meta: { title: '插件市场', icon: 'PuzzleIcon' }
  },

  // 新增：渠道管理
  {
    path: '/channels',
    name: 'Channels',
    component: () => import('@/pages/ChannelDashboard.vue'),
    meta: { title: '渠道管理', icon: 'ShareIcon' }
  }
]
```

## 六、样式指南

### 6.1 玻璃效果样式
```css
.glass-effect {
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 12px;
}

.glass-effect-dark {
  background: rgba(30, 27, 75, 0.8);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
}
```

### 6.2 卡片悬停效果
```css
.card-hover {
  transition: all 0.2s ease;
}

.card-hover:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.1);
}
```

### 6.3 按钮样式
```css
.btn-primary {
  background: linear-gradient(135deg, #6366F1, #818CF8);
  border: none;
  color: white;
  font-weight: 600;
  transition: all 0.2s ease;
}

.btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
}

.btn-cta {
  background: linear-gradient(135deg, #10B981, #34D399);
  border: none;
  color: white;
  font-weight: 600;
  transition: all 0.2s ease;
}

.btn-cta:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}
```

## 七、测试策略

### 7.1 组件测试
```typescript
// tests/unit/components/TokenConsumptionChart.spec.ts
import { mount } from '@vue/test-utils'
import TokenConsumptionChart from '@/components/charts/TokenConsumptionChart.vue'

describe('TokenConsumptionChart', () => {
  it('renders correctly', () => {
    const wrapper = mount(TokenConsumptionChart)
    expect(wrapper.find('.chart-title').text()).toBe('Token 消耗趋势')
  })

  it('updates chart when time range changes', async () => {
    const wrapper = mount(TokenConsumptionChart)
    await wrapper.find('.ant-select').setValue('30d')
    // 验证图表更新
  })
})
```

### 7.2 E2E 测试
```typescript
// tests/e2e/dashboard.spec.ts
describe('Dashboard', () => {
  it('displays token consumption chart', () => {
    cy.visit('/dashboard')
    cy.get('.token-consumption-chart').should('be.visible')
    cy.get('.chart-title').should('contain', 'Token 消耗趋势')
  })

  it('allows time range selection', () => {
    cy.visit('/dashboard')
    cy.get('.ant-select').click()
    cy.contains('最近 30 天').click()
    // 验证图表更新
  })
})
```

## 八、性能优化

### 8.1 图表懒加载
```typescript
// 使用动态导入
const TokenConsumptionChart = defineAsyncComponent(() =>
  import('@/components/charts/TokenConsumptionChart.vue')
)
```

### 8.2 数据虚拟化
```typescript
// 使用虚拟滚动处理大量数据
import { VirtualList } from 'vue-virtual-scroll-list'

<VirtualList
  :data-source="largeDataset"
  :item-height="50"
  :buffer="10"
>
  <template #default="{ item }">
    <div class="list-item">{{ item.name }}</div>
  </template>
</VirtualList>
```

### 8.3 图表数据采样
```typescript
// 对于大数据集，使用数据采样
const sampleData = (data: any[], maxPoints: number) => {
  if (data.length <= maxPoints) return data
  
  const step = Math.ceil(data.length / maxPoints)
  return data.filter((_, index) => index % step === 0)
}
```

## 九、部署和监控

### 9.1 性能监控
```typescript
// 添加性能监控
import { onCLS, onFID, onLCP } from 'web-vitals'

onCLS(console.log)
onFID(console.log)
onLCP(console.log)
```

### 9.2 错误监控
```typescript
// 添加错误监控
import * as Sentry from '@sentry/vue'

Sentry.init({
  app,
  dsn: 'your-dsn',
  integrations: [
    new Sentry.BrowserTracing(),
    new Sentry.Replay()
  ],
  tracesSampleRate: 1.0,
  replaysSessionSampleRate: 0.1,
  replaysOnErrorSampleRate: 1.0,
})
```

## 十、下一步行动

### 本周可以开始
1. **安装依赖** - 运行 npm install 命令
2. **引入字体** - 在 index.html 中添加字体链接
3. **配置设计系统** - 更新 tailwind.config.js
4. **创建图表组件** - 使用已创建的 TokenConsumptionChart.vue

### 第一周目标
1. **完成 DashboardPage 增强** - 添加 3 个图表组件
2. **完成 ChatPage 多模态输入** - 集成语音输入
3. **创建设计系统文档** - 记录颜色、字体、组件规范

### 资源准备
1. **前端开发环境** - Node.js 18+, npm/yarn
2. **设计工具** - Figma/Sketch（可选）
3. **测试环境** - Jest + Cypress
4. **文档工具** - Storybook（可选）

## 十一、常见问题

### Q1: 如何处理图表性能问题？
A1: 使用数据采样、虚拟滚动、懒加载等技术。

### Q2: 如何实现实时数据更新？
A2: 使用 WebSocket 或轮询 API，结合 Pinia store 更新。

### Q3: 如何保证移动端兼容性？
A3: 使用响应式设计、触摸手势、PWA 支持。

### Q4: 如何测试图表组件？
A4: 使用 Vue Test Utils 单元测试 + Cypress E2E 测试。

## 十二、参考资源

### 官方文档
- [Vue 3 文档](https://vuejs.org/)
- [ECharts 文档](https://echarts.apache.org/)
- [Ant Design Vue](https://antdv.com/)
- [Pinia 文档](https://pinia.vuejs.org/)

### 设计资源
- [Heroicons](https://heroicons.com/)
- [Lucide Icons](https://lucide.dev/)
- [Google Fonts](https://fonts.google.com/)

### 工具推荐
- [Vue DevTools](https://devtools.vuejs.org/)
- [Storybook](https://storybook.js.org/)
- [Figma](https://www.figma.com/)