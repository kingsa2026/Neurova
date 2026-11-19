# Neurova 前端 API 调用规范

> **版本**: v1.0.0 | **日期**: 2026-05-13 | **适用**: Neurova 1.0.0-beta1

---

## 1. 快速开始

### 1.1 基础配置

```typescript
// 环境变量 (.env)（2026-11-19 核对：后端默认端口 9527，见 start_server.py:92 与 .env.example:8）
VITE_API_BASE_URL=/api/v1        # 直连后端时用 http://localhost:9527/api/v1

// 代码中使用（axios 实例，baseURL 默认 /api/v1，见 NeurUI/src/config/index.ts:32）
import api from '@/api';
const { data } = await api.get('/agents');
```

### 1.2 API 前缀

| 类型 | 前缀 | 示例 |
|------|------|------|
| RESTful API | `/api/v1` | `/api/v1/agents` |
| Console API | `/api/v1/console` | `/api/v1/console/chat` |
| WebSocket | `/api/v1/console/ws/{client_id}` | `ws://localhost:9527/api/v1/console/ws/{client_id}` |

> （2026-11-19 核对）Console 路由挂载在 `/v1/console`（`neurova/api/endpoints/__init__.py`
> 端点注册表），WebSocket 端点为 `/v1/console/ws/{client_id}`（`console.py:2570`）。
> 前端 axios `baseURL=/api/v1`（`NeurUI/src/api/index.ts:81`、`NeurUI/src/config/index.ts:32`），
> 因此页面代码里只写 `/console/...` 相对路径。

---

## 2. 调用方式

### 方式一：使用 axios 实例（2026-11-19 核对）

```typescript
import api from '@/api';

// GET
const data = await api.get<ResponseType>('/endpoint');

// POST
const data = await api.post<ResponseType>('/endpoint', body);

// PUT
const data = await api.put<ResponseType>('/endpoint', body);

// DELETE
const data = await api.delete<ResponseType>('/endpoint');
```

### 方式二：使用模块 API

```typescript
// 各模块用具名函数导出（2026-11-19 核对，无 agentApi/skillApi 命名空间对象）
import { listAgents } from '@/api/modules/agents';
import { sendConsoleMessage } from '@/api/modules/console';

const agents = await listAgents();
await sendConsoleMessage(agentId, '你好', sessionId);
```

---

## 3. 核心接口

### 3.1 聊天 API

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/console/chat` | SSE 流式聊天 |
| GET | `/console/chat/history` | 获取历史 |
| POST | `/console/chat/new` | 创建会话 |
| GET | `/console/chat/sessions` | 会话列表 |

**SSE 调用说明**（2026-11-19 核对）：

SSE 流式聊天没有 `chatApi.streamChat` 封装；实际由 `NeurUI/src/pages/ChatPage.vue`
以 `fetch('/console/chat')` 发起请求并经 `response.body.getReader()` 逐块读取
（见 ChatPage.vue:1644、:1044）。页面内相对路径会自动拼在 axios `baseURL=/api/v1` 语义下。

### 3.2 Agent API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/agents` | 列表 |
| POST | `/api/v1/agents` | 创建 |
| GET | `/api/v1/agents/{agent_id}` | 详情 |
| PUT | `/api/v1/agents/{agent_id}` | 更新基础信息 |
| DELETE | `/api/v1/agents/{agent_id}` | 删除 |
| GET | `/api/v1/growth/constitution?agent_id=` | 读取宪法配置 |
| PUT | `/api/v1/growth/constitution?agent_id=` | 整表更新宪法配置 |
| GET | `/api/v1/growth/personality?agent_id=` | 读取人格配置 |
| PUT | `/api/v1/growth/personality?agent_id=` | 更新人格配置 |

> （2026-11-19 核对）原文档的 `GET/PUT /api/v1/agents/:id/config` 端点不存在。
> Agent 的配置面实际是宪法（`neurova/api/endpoints/constitution_router.py:32-60`）
> 与人格（`neurova/api/endpoints/personality_router.py:27-68`）两组路由，
> 均以 `agent_id` 查询参数定位 Agent，挂载在 `/api/v1/growth` 前缀下。

### 3.3 技能 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 技能列表 |
| GET | `/api/v1/skills/stats` | 技能统计 |
| GET | `/api/v1/skills/tips` | 技能提示 |
| POST | `/api/v1/skills/learn` | 学习新技能 |
| GET | `/api/v1/skills/{skill_id}` | 技能详情 |
| POST | `/api/v1/skills/{skill_id}/execute` | 执行技能 |
| PUT | `/api/v1/skills/{skill_id}/enable` | 启用技能 |
| PUT | `/api/v1/skills/{skill_id}/disable` | 禁用技能 |

> （2026-11-19 核对）技能没有"创建/更新/删除/toggle"端点；技能来源是 `POST /learn`
> 学习与技能池安装，启停用走 `enable`/`disable`
>（`neurova/api/endpoints/skill.py:232-502`）。

---

## 4. 新增多用户管理 API

### 4.1 用户组管理

> （2026-11-19 核对）原 `/api/v1/user-groups` 前缀不存在；用户组功能的实际挂载点是
> `/api/v1/groups`（`neurova/api/endpoints/groups_api.py:114-368`，
> 前端模块 `NeurUI/src/api/modules/groups.ts`）。

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/groups` | 群组列表 |
| POST | `/api/v1/groups` | 创建群组 |
| GET | `/api/v1/groups/{group_id}` | 群组详情 |
| PUT | `/api/v1/groups/{group_id}` | 更新群组 |
| DELETE | `/api/v1/groups/{group_id}` | 删除群组 |
| GET | `/api/v1/groups/{group_id}/members` | 成员列表 |
| POST | `/api/v1/groups/{group_id}/members` | 添加成员 |
| DELETE | `/api/v1/groups/{group_id}/members/{username}` | 移除成员 |

### 4.2 增强用户管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/enhanced-users` | 用户列表 |
| POST | `/api/v1/enhanced-users` | 创建用户 |
| PUT | `/api/v1/enhanced-users/{user_id}` | 更新用户 |
| PUT | `/api/v1/enhanced-users/{user_id}/password` | 修改密码 |
| DELETE | `/api/v1/enhanced-users/{user_id}` | 删除用户 |
| GET | `/api/v1/enhanced-users/backup` | 用户数据备份 |

> （2026-11-19 核对）原 `GET /api/v1/enhanced-users/:id` 单用户详情端点不存在；
> 实际路由见 `neurova/api/endpoints/enhanced_users_api.py:87-187`。

### 4.3 技能池管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/skill-pool/public` | 公共技能池列表 |
| GET | `/api/v1/skill-pool/public/{skill_id}` | 公共技能详情 |
| POST | `/api/v1/skill-pool/public/{skill_id}/install` | 安装公共技能 |
| GET | `/api/v1/skill-pool/private` | 我的私有技能列表 |
| POST | `/api/v1/skill-pool/private` | 新建私有技能 |
| PUT | `/api/v1/skill-pool/private/{skill_id}` | 更新私有技能 |
| DELETE | `/api/v1/skill-pool/private/{skill_id}` | 删除私有技能 |
| POST | `/api/v1/skill-pool/private/{skill_id}/share` | 分享到公共池 |
| GET | `/api/v1/skill-pool/me/skills` | 当前用户技能列表 |
| POST | `/api/v1/skill-pool/me/skills` | 添加当前用户技能 |
| PUT | `/api/v1/skill-pool/me/skills/{skill_id}` | 更新当前用户技能 |
| DELETE | `/api/v1/skill-pool/me/skills/{skill_id}` | 移除当前用户技能 |

> （2026-11-19 核对）技能池不按路径中的 `user_id` 寻址，当前用户由鉴权态解析；
> 另有 `/agent/{agent_id}/pending-skills`、`/install-from-url`、`/transfers` 等管理面
>（`neurova/api/endpoints/skill_pool_api.py:170-662`）。

---

## 5. 错误处理

```typescript
import { ApiError } from '../../api/config';

try {
  const data = await api.call();
} catch (error) {
  if (error instanceof ApiError) {
    console.error(`${error.status}: ${error.message}`);
    
    if (error.status === 404) { /* 未找到 */ }
    else if (error.status === 401) { /* 未授权 */ }
    else if (error.status === 500) { /* 服务器错误 */ }
  }
}
```

---

## 6. 前端模块结构

```
NeurUI/src/api/          #（2026-11-19 核对：前端目录为 NeurUI/，原 neurova-ui/ 从未入库）
├── index.ts          # axios 实例、拦截器与 api 聚合导出
├── auth.ts           # 鉴权 API
├── neuron.ts         # NEURON 子系统 API（baseURL=/api/neuron）
├── contracts/        # 契约类型
└── modules/          # 按域拆分的 API 模块（70+）
    ├── agents.ts
    ├── console.ts
    ├── knowledge.ts
    ├── skill-pool.ts
    ├── collaboration.ts
    ├── enhanced-users.ts
    ├── groups.ts
    └── ...
```

---

## 7. 待完成工作

### 7.1 前端模块现状（2026-11-19 核对）

原"待创建"清单中的模块均已落地于 `NeurUI/src/api/modules/`：

- [x] `groups.ts` - 用户组（群组）管理
- [x] `enhanced-users.ts` - 增强用户管理
- [x] `skill-pool.ts` - 技能池管理
- [x] `collaboration.ts` - 协作项目管理

> 命名以实际文件为准：`enhanced-users.ts`/`skill-pool.ts` 用连字符小写，
> 没有 `userGroup.ts`（用户组能力在 `groups.ts`）。

### 7.2 需要创建的类型定义

- [ ] `api/types/UserGroup.ts`
- [ ] `api/types/EnhancedUser.ts`
- [ ] `api/types/SkillPool.ts`
- [ ] `api/types/Collaboration.ts`

### 7.3 需要创建的页面

- [ ] 用户组管理页面
- [ ] 增强用户管理页面
- [ ] 技能池管理页面
- [ ] 协作项目管理页面

---

## 8. 示例代码

### 完整调用示例

```typescript
// 1. 导入（2026-11-19 核对：具名函数导入；技能面暂无独立 skills.ts 模块，直接走 api 实例）
import api from '@/api';
import { listAgents } from '@/api/modules/agents';

// 2. 调用 API
async function example() {
  try {
    // 获取 Agent 列表
    const agents = await listAgents();

    // 技能启停用
    await api.put(`/skills/${skillId}/enable`);

    // 流式聊天见 §3.1：ChatPage.vue 以 fetch 读取 /console/chat 的 SSE 流
  } catch (error) {
    console.error(error);
  }
}
```

---

## 9. 相关文档

- 后端 API 文档：`neurova/api/README.md` 从未入库，接口事实源为 [API_REFERENCE.md](API_REFERENCE.md)
- 前端开发指南：`neurova-ui/README.md` 从未入库，前端代码在 `NeurUI/`，目录说明见 [07-implementation-plan.md](../01-architecture/07-implementation-plan.md)
- [架构设计文档](../01-architecture/NEUROVA_CogArch_2.0.md)

---

**维护者**: Neurova 开发团队  
**更新日期**: 2026-11-19
