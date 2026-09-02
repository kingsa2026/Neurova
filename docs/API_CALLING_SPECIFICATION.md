# Neurova 前端 API 调用规范

> **版本**: v1.0.0 | **日期**: 2026-05-13 | **适用**: Neurova 2.0+

---

## 1. 快速开始

### 1.1 基础配置

```typescript
// 环境变量 (.env)
VITE_API_BASE_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000/ws

// 代码中使用
import { getApiUrl } from '../../api/config';
const url = getApiUrl('/agents');
```

### 1.2 API 前缀

| 类型 | 前缀 | 示例 |
|------|------|------|
| RESTful API | `/api/v1` | `/api/v1/agents` |
| Console API | `/console` | `/console/chat` |
| WebSocket | `/ws` | `ws://localhost:8000/ws` |

---

## 2. 调用方式

### 方式一：使用封装函数

```typescript
import { request, get, post, put, del } from '../../api/request';

// GET
const data = await get<ResponseType>('/endpoint');

// POST
const data = await post<ResponseType>('/endpoint', JSON.stringify(body));

// PUT
const data = await put<ResponseType>('/endpoint', JSON.stringify(body));

// DELETE
const data = await del<ResponseType>('/endpoint');
```

### 方式二：使用模块 API

```typescript
import { agentApi, skillApi, chatApi } from '../../api';

// Agent
const agents = await agentApi.listAgents();

// Skill
const skills = await skillApi.getSkills();

// Chat
await chatApi.streamChat(request, callbacks);
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

**SSE 调用示例**:

```typescript
import { chatApi } from '../../api';

await chatApi.streamChat(
  { message: '你好', session_id: 'xxx' },
  {
    onMessage: (data) => console.log(data),
    onDone: () => console.log('完成'),
    onError: (error) => console.error(error),
  }
);
```

### 3.2 Agent API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/agents` | 列表 |
| POST | `/api/v1/agents` | 创建 |
| GET | `/api/v1/agents/:id/config` | 获取配置 |
| PUT | `/api/v1/agents/:id/config` | 更新配置 |
| DELETE | `/api/v1/agents/:id` | 删除 |

### 3.3 技能 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 列表 |
| POST | `/api/v1/skills` | 创建 |
| GET | `/api/v1/skills/:id` | 详情 |
| PUT | `/api/v1/skills/:id` | 更新 |
| DELETE | `/api/v1/skills/:id` | 删除 |
| POST | `/api/v1/skills/:id/toggle` | 启用/禁用 |

---

## 4. 新增多用户管理 API

### 4.1 用户组管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/user-groups` | 创建用户组 |
| GET | `/api/v1/user-groups` | 列表 |
| GET | `/api/v1/user-groups/:id` | 详情 |
| PUT | `/api/v1/user-groups/:id` | 更新 |
| DELETE | `/api/v1/user-groups/:id` | 删除 |
| POST | `/api/v1/user-groups/:id/members` | 添加成员 |

### 4.2 增强用户管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/v1/enhanced-users` | 创建用户 |
| GET | `/api/v1/enhanced-users` | 列表 |
| GET | `/api/v1/enhanced-users/:id` | 详情 |
| PUT | `/api/v1/enhanced-users/:id` | 更新 |
| DELETE | `/api/v1/enhanced-users/:id` | 删除 |

### 4.3 技能池管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/v1/skill-pool/public` | 公共技能池 |
| GET | `/api/v1/skill-pool/:user_id` | 用户专属池 |
| POST | `/api/v1/skill-pool/:user_id` | 添加技能 |
| DELETE | `/api/v1/skill-pool/:user_id/:skill_id` | 移除技能 |

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
neurova-ui/src/api/
├── index.ts          # 导出所有模块
├── config.ts         # 配置
├── request.ts        # 请求封装
├── modules/          # API 模块
│   ├── agent.ts
│   ├── skill.ts
│   ├── chat.ts
│   └── ...
└── types/            # 类型定义
    ├── Agent.ts
    ├── Skill.ts
    └── ...
```

---

## 7. 待完成工作

### 7.1 需要创建的前端模块

- [ ] `api/modules/userGroup.ts` - 用户组管理
- [ ] `api/modules/enhancedUser.ts` - 增强用户管理
- [ ] `api/modules/skillPool.ts` - 技能池管理
- [ ] `api/modules/collaboration.ts` - 协作项目管理

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
// 1. 导入
import { agentApi, skillApi, chatApi } from '../../api';
import { ApiError } from '../../api/config';

// 2. 调用 API
async function example() {
  try {
    // 获取 Agent 列表
    const agents = await agentApi.listAgents();
    
    // 创建 Skill
    const skill = await skillApi.createSkill({
      name: 'NewSkill',
      description: '描述',
    });
    
    // SSE 流式聊天
    await chatApi.streamChat(
      { message: '你好' },
      {
        onMessage: (data) => updateUI(data),
        onDone: () => console.log('完成'),
        onError: (error) => console.error(error),
      }
    );
  } catch (error) {
    if (error instanceof ApiError) {
      console.error(`${error.status}: ${error.message}`);
    }
  }
}
```

---

## 9. 相关文档

- [后端 API 文档](../neurova/api/README.md)
- [前端开发指南](../neurova-ui/README.md)
- [架构设计文档](./NEUROVA_CogArch_2.0.md)

---

**维护者**: Neurova 开发团队  
**更新日期**: 2026-05-13
