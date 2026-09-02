# Neurova 后端 API 问题文档

> **创建日期**: 2026-05-13  
> **创建人**: AI Agent (CodeBuddy)  
> **目的**: 记录后端 API 不完善、不合理、缺失的问题

---

## 📋 目录

1. [前端 API 模块缺失清单](#1-前端-api-模块缺失清单)
2. [后端 API 端点清单](#2-后端-api-端点清单)
3. [问题详情](#3-问题详情)
4. [建议行动](#4-建议行动)

---

## 1. 前端 API 模块缺失清单

### 1.1 当前前端 API 模块（10 个）

| 序号 | 模块名称 | 文件路径 | 状态 |
|------|----------|----------|------|
| 1 | ACP | `src/api/modules/acp.ts` | ✅ 已实现 |
| 2 | Agent | `src/api/modules/agent.ts` | ✅ 已实现 |
| 3 | Channel | `src/api/modules/channel.ts` | ✅ 已实现 |
| 4 | Chat | `src/api/modules/chat.ts` | ✅ 已实现 |
| 5 | CronJob | `src/api/modules/cronjob.ts` | ✅ 已实现 |
| 6 | Provider | `src/api/modules/provider.ts` | ✅ 已实现 |
| 7 | Settings | `src/api/modules/settings.ts` | ✅ 已实现 |
| 8 | Skill | `src/api/modules/skill.ts` | ✅ 已实现 |
| 9 | Tools | `src/api/modules/tools.ts` | ✅ 已实现 |
| 10 | Workspace | `src/api/modules/workspace.ts` | ✅ 已实现 |

---

### 1.2 缺失的前端 API 模块（18 个）

| 序号 | 模块名称 | 后端端点 | 优先级 | 说明 |
|------|----------|----------|--------|------|
| 1 | `memory.ts` | `/memories/*` | **P0** | 记忆管理 API - 核心功能 |
| 2 | `auth.ts` | `/auth/*` | **P0** | 认证 API - 核心功能 |
| 3 | `model.ts` | `/models/*` | **P1** | 模型管理 API - 重要功能 |
| 4 | `generation.ts` | `/generation/*` | **P1** | 生成管理 API - 重要功能 |
| 5 | `skill_market.ts` | `/skill-market/*` | **P1** | 技能市场 API - 重要功能 |
| 6 | `user_group.ts` | `/user-groups/*` | **P2** | 用户组管理 API - 协作功能 |
| 7 | `enhanced_users.ts` | `/enhanced-users/*` | **P2** | 增强用户管理 API - 协作功能 |
| 8 | `skill_pool.ts` | `/skill-pool/*` | **P2** | 技能池管理 API - 协作功能 |
| 9 | `collaboration.ts` | `/collaboration/*` | **P2** | 协作项目 API - 协作功能 |
| 10 | `projects.ts` | `/projects/*` | **P2** | 项目管理 API - 协作功能 |
| 11 | `workflows.ts` | `/workflows/*` | **P2** | 工作流管理 API - 协作功能 |
| 12 | `file_flows.ts` | `/file-flows/*` | **P2** | 文件流管理 API - 协作功能 |
| 13 | `teams.ts` | `/teams/*` | **P2** | 团队管理 API - 协作功能 |
| 14 | `tasks.ts` | `/tasks/*` | **P2** | 任务管理 API - 协作功能 |
| 15 | `groups.ts` | `/groups/*` | **P2** | 群组管理 API - 协作功能 |
| 16 | `logs.ts` | `/logs/*` | **P3** | 日志管理 API - 高级功能 |
| 17 | `growth.ts` | `/growth/*` | **P3** | 成长系统 API - 高级功能 |
| 18 | `media.ts` | `/media/*` | **P3** | 媒体存储 API - 高级功能 |

---

## 2. 后端 API 端点清单

### 2.1 核心功能路由（9 个）

| 序号 | 路由名称 | 端点前缀 | 前端模块状态 |
|------|----------|----------|---------------|
| 1 | `chat_router` | `/chat` | ✅ `chat.ts` |
| 2 | `memory_router` | `/memories` | ❌ **缺失 `memory.ts`** |
| 3 | `agent_router` | `/agents` | ✅ `agent.ts` |
| 4 | `skill_router` | `/skills` | ✅ `skill.ts` |
| 5 | `skill_market_router` | `/skill-market` | ❌ **缺失 `skill_market.ts`** |
| 6 | `channel_router` | `/channels` | ✅ `channel.ts` |
| 7 | `provider_router` | `/providers` | ✅ `provider.ts` |
| 8 | `model_router` | `/models` | ❌ **缺失 `model.ts`** |
| 9 | `generation_router` | `/generation` | ❌ **缺失 `generation.ts`** |

---

### 2.2 多用户管理系统路由（4 个）

| 序号 | 路由名称 | 端点前缀 | 前端模块状态 |
|------|----------|----------|---------------|
| 1 | `user_group_router` | `/user-groups` | ❌ **缺失 `user_group.ts`** |
| 2 | `enhanced_users_router` | `/enhanced-users` | ❌ **缺失 `enhanced_users.ts`** |
| 3 | `skill_pool_router` | `/skill-pool` | ❌ **缺失 `skill_pool.ts`** |
| 4 | `collaboration_router` | `/collaboration` | ❌ **缺失 `collaboration.ts`** |

---

### 2.3 ACP 协议路由（1 个）

| 序号 | 路由名称 | 端点前缀 | 前端模块状态 |
|------|----------|----------|---------------|
| 1 | `acp_router` | `/acp` | ✅ `acp.ts` |

---

### 2.4 其他可能的路由（根据项目文档）

根据项目文档 `NEUROVA_CogArch_2.0.md`，可能还有以下 API 端点：

| 序号 | 可能端点 | 说明 | 前端模块状态 |
|------|----------|------|---------------|
| 1 | `/auth/*` | 认证 API | ❌ **缺失 `auth.ts`** |
| 2 | `/projects/*` | 项目管理 | ❌ **缺失 `projects.ts`** |
| 3 | `/workflows/*` | 工作流管理 | ❌ **缺失 `workflows.ts`** |
| 4 | `/file-flows/*` | 文件流管理 | ❌ **缺失 `file_flows.ts`** |
| 5 | `/teams/*` | 团队管理 | ❌ **缺失 `teams.ts`** |
| 6 | `/tasks/*` | 任务管理 | ❌ **缺失 `tasks.ts`** |
| 7 | `/groups/*` | 群组管理 | ❌ **缺失 `groups.ts`** |
| 8 | `/logs/*` | 日志管理 | ❌ **缺失 `logs.ts`** |
| 9 | `/growth/*` | 成长系统 | ❌ **缺失 `growth.ts`** |
| 10 | `/console/*` | 控制台 API | ❌ **缺失 `console.ts`** |
| 11 | `/channel-sharing/*` | 渠道共享 | ❌ **缺失 `channel_sharing.ts`** |
| 12 | `/media/*` | 媒体存储 | ❌ **缺失 `media.ts`** |
| 13 | `/context/*` | 上下文管理 | ❌ **缺失 `context.ts`** |
| 14 | `/agent-enhancement/*` | Agent 增强 | ❌ **缺失 `agent_enhancement.ts`** |
| 15 | `/memory-enhancement/*` | 记忆增强 | ❌ **缺失 `memory_enhancement.ts`** |

---

## 3. 问题详情

### 3.1 问题 1：前端 API 模块严重缺失

**问题描述**：
- 后端有 **25+ 个 API 端点**
- 前端只实现了 **10 个 API 模块**
- 缺失 **15+ 个 API 模块**

**影响**：
- 前端无法调用后端的大部分 API
- 无法完成记忆管理、认证、模型管理等核心功能
- 协作系统（项目、工作流、团队、任务）完全无法使用

**建议**：
- 按优先级补充缺失的 API 模块
- P0：补充 `memory.ts`、`auth.ts`
- P1：补充 `model.ts`、`generation.ts`、`skill_market.ts`
- P2：补充协作相关 API 模块
- P3：补充高级功能 API 模块

---

### 3.2 问题 2：部分后端 API 可能未实现或不完善

**问题描述**：
- 根据 `app.py` 的代码，部分路由使用 `try...except ImportError` 导入
- 如果后端模块不存在，API 端点就不会注册
- 前端可能无法调用这些 API

**可能未实现的后端模块**：
1. `neurova.api.endpoints.user_group_api`
2. `neurova.api.endpoints.enhanced_users_api`
3. `neurova.api.endpoints.skill_pool_api`
4. `neurova.api.endpoints.collaboration_api`

**影响**：
- 即使前端实现了 API 模块，也无法调用后端 API
- 需要检查后端模块是否真实存在 and 可用

**建议**：
- 检查后端 API 端点是否真实存在
- 运行后端服务，访问 `/docs` 查看 Swagger 文档
- 确认所有 API 端点都可用的

---

### 3.3 问题 3：前端页面缺失

**问题描述**：
- 根据开发计划，前端需要 **11 个新页面**
- 当前只完成了 **4 个页面**（Chat、Agent、Control、Settings）
- 缺失 **7 个页面**（Memory、SkillMarket、Model、Generation、Project、Workflow、Team 等）

**影响**：
- 即使 API 模块实现了，也没有对应的页面来使用这些 API
- 用户无法使用记忆管理、技能市场、模型管理等功能

**建议**：
- 按优先级开发缺失的页面
- P0：开发 MemoryPage、AuthPage
- P1：开发 SkillMarketPage、ModelPage、GenerationPage
- P2：开发协作相关页面
- P3：开发高级功能页面

---

### 3.4 问题 4：性能优化不足

**问题描述**：
- 当前前端代码可能没有进行代码分割
- 可能一次性加载所有 JS 文件
- 可能导致页面响应卡顿

**影响**：
- 首屏加载时间过长
- 页面切换卡顿
- 用户体验差

**建议**：
- 实施路由级代码分割（`React.lazy + Suspense`）
- 实施组件级懒加载（动态 `import()`）
- 按需引入第三方库（Ant Design、Lodash、ECharts）
- 配置 Vite 手动分包和 Gzip 压缩

---

## 4. 建议行动

### 4.1 立即行动（P0）

1. **检查后端 API 端点是否真实存在**
   - 运行后端服务
   - 访问 `http://localhost:8000/docs` 查看 Swagger 文档
   - 确认所有 API 端点都可用

2. **补充核心 API 模块**
   - 创建 `src/api/modules/memory.ts`
   - 创建 `src/api/modules/auth.ts`
   - 创建 `src/api/modules/model.ts`

3. **开发核心页面**
   - 完善 AgentPage（当前只有 "Under development"）
   - 开发 MemoryPage
   - 开发 AuthPage（登录、注册）

---

### 4.2 短期计划（1-2 周）

1. **补充 P1 API 模块**
   - 创建 `src/api/modules/skill_market.ts`
   - 创建 `src/api/modules/generation.ts`
   - 创建 `src/api/modules/console.ts`

2. **开发 P1 页面**
   - 开发 SkillMarketPage
   - 开发 ModelPage
   - 开发 GenerationPage

3. **实施性能优化**
   - 路由级代码分割
   - 组件级懒加载
   - 第三方库按需引入

---

### 4.3 长期计划（1-3 个月）

1. **补充 P2 API 模块**
   - 创建协作相关 API 模块
   - 创建团队、任务、群组相关 API 模块

2. **开发 P2 页面**
   - 开发协作相关页面
   - 开发团队、任务、群组相关页面

3. **补充 P3 API 模块**
   - 创建高级功能 API 模块

4. **开发 P3 页面**
   - 开发高级功能页面

---

## 📝 总结

### 关键问题

1. **前端 API 模块严重缺失**（缺失 15+ 个）
2. **部分后端 API 可能未实现或不完善**
3. **前端页面缺失**（缺失 7+ 个）
4. **性能优化不足**（未实施代码分割和懒加载）

### 下一步行动

1. **验证后端 API 端点**（运行后端服务，查看 Swagger 文档）
2. **补充核心 API 模块**（P0：memory.ts、auth.ts、model.ts）
3. **开发核心页面**（P0：MemoryPage、AuthPage）
4. **实施性能优化**（路由级代码分割、组件级懒加载）

---

**文档维护**：

- 本文档应随项目进展持续更新
- 每解决一个问题后，更新对应的状态码
- 发现新的问题时，添加到对应章节

---

**参考文档**：

- [frontend_development_plan.md](docs/dev_progress/frontend_development_plan.md)
- [NEUROVA_CogArch_2.0.md](docs/NEUROVA_CogArch_2.0.md)
- [app.py](../neurova/api/app.py)
