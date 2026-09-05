# Neurova UI - 前端界面

> **技术栈**: Vue 3 + Vite + TypeScript + Ant Design Vue + Pinia + Vue Router

## 🎨 设计风格

本前端项目严格遵循 Neurova 官网的设计风格：

- **配色方案**: 蓝紫渐变（`#3b82f6` 到 `#8b5cf6`）
- **背景**: 深色星空背景（`#0a0e27`）
- **毛玻璃效果**: `backdrop-filter: blur(20px)`
- **动画**: 星空粒子动画 + 渐入动画
- **设计原则**: 严格控制体积，按需引入，不安装额外依赖

## 📁 项目结构

```
neuUI/
├── src/
│   ├── api/              # API 调用封装
│   │   ├── auth.ts       # 认证相关 API
│   │   └── modules/     # 其他模块 API
│   ├── assets/           # 静态资源
│   ├── components/       # 公共组件
│   │   └── StarBackground.vue  # 星空背景组件
│   ├── router/           # 路由配置
│   │   └── index.ts
│   ├── stores/           # Pinia 状态管理
│   │   └── auth.ts      # 认证状态
│   ├── styles/           # 全局样式
│   │   └── global.css   # 全局样式（星空背景、毛玻璃效果）
│   ├── types/            # TypeScript 类型定义
│   │   └── auth.ts      # 认证相关类型
│   ├── views/            # 页面组件
│   │   ├── LoginView.vue      # 登录页面
│   │   ├── RegisterView.vue  # 注册页面
│   │   └── DashboardView.vue # 仪表板页面
│   ├── App.vue           # 根组件
│   └── main.ts          # 应用入口
├── index.html            # HTML 入口
├── package.json          # 项目依赖
├── tsconfig.json         # TypeScript 配置
├── vite.config.ts       # Vite 配置
└── README.md            # 项目说明
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd neuUI
pnpm install
```

> **注意**: 推荐使用 `pnpm` 以节省 40-60% 存储空间。如果未安装 pnpm，请先执行：
> ```bash
> npm install -g pnpm
> ```

### 2. 启动开发服务器

```bash
pnpm dev
```

开发服务器将在 `http://localhost:3000` 启动。

### 3. 构建生产版本

```bash
pnpm build
```

构建产物将输出到 `dist/` 目录。

### 4. 预览生产版本

```bash
pnpm preview
```

## 🔧 开发说明

### 后端 API 集成

前端通过 Vite 代理访问后端 API：

```typescript
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true
    }
  }
}
```

后端 API 需要实现以下端点：

- `POST /api/v1/auth/login` - 用户登录
- `POST /api/v1/auth/register` - 用户注册
- `POST /api/v1/auth/logout` - 用户登出
- `GET /api/v1/auth/me` - 获取当前用户信息

### 认证流程

1. 用户登录/注册成功后，后端返回 JWT Token
2. Token 存储在 `localStorage` 中
3. 每次 API 请求时，Token 通过 `Authorization` Header 发送到后端
4. 路由守卫检查 Token 是否存在，不存在则重定向到登录页

### 状态管理

使用 Pinia 管理全局状态：

```typescript
// stores/auth.ts
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(...)
  const user = ref<UserInfo | null>(...)
  
  // 登录、注册、登出等方法
  return { token, user, login, register, logout }
})
```

## 🎯 下一步开发计划

1. **实现后端认证 API** - 实现登录、注册、登出等接口
2. **完善 Dashboard 页面** - 添加 Agent 管理、对话界面等
3. **实现 Agent 管理页面** - 创建、编辑、删除 Agent
4. **实现聊天界面** - 集成流式输出、多模态支持
5. **实现文件管理页面** - 上传、下载、预览文件

## 📝 设计文档

详细的 UI 设计文档请参考：

- `docs/UI_DESIGN.md` - 完整的 UI 设计规范和页面布局

## ⚙️ 配置说明

### TypeScript 配置

- 严格模式已启用（`strict: true`）
- 路径别名：`@/*` 映射到 `src/*`

### Vite 配置

- 开发服务器端口：`3000`
- API 代理：`/api` → `http://localhost:8000`
- 路径别名：`@` → `src`

## 🐛 常见问题

### 1. 安装依赖失败

尝试清除缓存后重新安装：

```bash
rm -rf node_modules pnpm-lock.yaml
pnpm install
```

### 2. 开发服务器无法启动

检查端口 `3000` 是否被占用：

```bash
# Windows
netstat -ano | findstr :3000

# macOS/Linux
lsof -i :3000
```

### 3. 样式不生效

确保已安装 `ant-design-vue` 并正确引入样式：

```typescript
// main.ts
import 'ant-design-vue/dist/reset.css'
```

## 📄 许可证

MIT License

---

**Created with ❤️ by Neurova Team**
