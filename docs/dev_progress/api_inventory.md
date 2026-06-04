# Neurova 前端UI所需API完整清单

> **生成时间**: 2026-05-14  
> **目的**: 为前端UI开发提供完整的API对接清单，找出缺失的API模块

---

## 📋 目录

1. [后端API端点清单](#后端api端点清单)
2. [前端API模块现状](#前端api模块现状)
3. [缺失API模块清单](#缺失api模块清单)
4. [SDK依赖清单](#sdk依赖清单)
5. [优先级建议](#优先级建议)

---

## 后端API端点清单

### 1. 认证模块 (Auth)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| POST | `/api/v1/auth/login` | 用户登录 | ❌ 缺失 |
| POST | `/api/v1/auth/refresh` | 刷新Token | ❌ 缺失 |
| GET | `/api/v1/auth/me` | 获取当前用户信息 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/auth.py`

---

### 2. 对话模块 (Chat)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| POST | `/api/v1/chat` | 普通对话 | ✅ 已实现 (console) |
| POST | `/api/v1/chat/stream` | 流式对话SSE | ✅ 已实现 (console) |
| DELETE | `/api/v1/chat/history` | 清空对话历史 | ❌ 缺失 |
| GET | `/api/v1/chat/history` | 获取对话历史 | ✅ 已实现 (console) |

**文件**: `neurova/api/endpoints/chat.py`

**注意**: 前端目前使用 Console API (`/console/chat`)，需要确认是否需要迁移到标准 Chat API。

---

### 3. 记忆模块 (Memory)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/memories` | 搜索记忆 | ❌ 缺失 |
| POST | `/api/v1/memories` | 添加记忆 | ❌ 缺失 |
| GET | `/api/v1/memories/{memory_id}` | 获取记忆详情 | ❌ 缺失 |
| DELETE | `/api/v1/memories/{memory_id}` | 删除记忆 | ❌ 缺失 |
| GET | `/api/v1/memories/hot` | 获取高温记忆 | ❌ 缺失 |
| GET | `/api/v1/memories/crystallized` | 获取固化记忆 | ❌ 缺失 |
| GET | `/api/v1/memories/stats` | 获取记忆统计 | ❌ 缺失 |
| GET | `/api/v1/memories/reflection/logs` | 获取反思日志 | ❌ 缺失 |
| POST | `/api/v1/memories/reflection/generate` | 生成反思 | ❌ 缺失 |
| PUT | `/api/v1/memories/reflection/{id}/validate` | 验证反思应用 | ❌ 缺失 |
| GET | `/api/v1/memories/questions/pending` | 获取待问问题 | ❌ 缺失 |
| POST | `/api/v1/memories/questions/ask` | 标记问题已问 | ❌ 缺失 |
| GET | `/api/v1/memories/emotion/{emotion_type}` | 按情绪查询记忆 | ❌ 缺失 |
| GET | `/api/v1/memories/emotion/summary` | 获取情绪统计摘要 | ❌ 缺失 |
| GET | `/api/v1/memories/emotion/distribution` | 获取情绪分布 | ❌ 缺失 |
| POST | `/api/v1/memories/emotion/analyze` | 分析文本情绪 | ❌ 缺失 |
| POST | `/api/v1/memories/classify` | 分类记忆内容 | ❌ 缺失 |
| POST | `/api/v1/memories/classify-and-remember` | 分类并记忆 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/memory.py`

**优先级**: ⭐⭐⭐⭐⭐ (P0 - 核心功能)

---

### 4. Agent管理模块 (Agent)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/agents` | 列出所有Agent | ✅ 已实现 |
| GET | `/api/v1/agents/{agent_id}` | 获取Agent详情 | ❌ 缺失 |
| POST | `/api/v1/agents` | 创建Agent | ✅ 已实现 |
| DELETE | `/api/v1/agents/{agent_id}` | 删除Agent | ✅ 已实现 |
| GET | `/api/v1/agents/{agent_id}/stats` | 获取Agent统计 | ❌ 缺失 |
| POST | `/api/v1/agents/{agent_id}/switch` | 切换Agent | ❌ 缺失 |
| GET | `/api/v1/agents/{agent_id}/constitution` | 获取宪法 | ❌ 缺失 |
| PUT | `/api/v1/agents/{agent_id}/constitution` | 更新宪法 | ❌ 缺失 |
| GET | `/api/v1/agents/{agent_id}/personality` | 获取个性 | ❌ 缺失 |
| PUT | `/api/v1/agents/{agent_id}/personality` | 更新个性 | ❌ 缺失 |
| GET | `/api/v1/agents/{agent_id}/personality/report` | 获取发展报告 | ❌ 缺失 |
| POST | `/api/v1/agents/{agent_id}/decide` | 自主决策 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/agent.py`

**注意**: 前端 `agent.ts` 只实现了部分功能（配置管理），需要补充完整。

---

### 5. 技能系统模块 (Skill)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/skills/patterns` | 获取行为模式 | ✅ 已实现 |
| POST | `/api/v1/skills/learn` | 从对话学习 | ✅ 已实现 |
| GET | `/api/v1/skills/tips` | 获取技能提示 | ✅ 已实现 |
| GET | `/api/v1/skills/evaluate` | 评估模式 | ✅ 已实现 |
| POST | `/api/v1/skills/pack` | 打包模式 | ✅ 已实现 |
| GET | `/api/v1/skills/packed` | 获取已打包技能 | ✅ 已实现 |
| POST | `/api/v1/skills/select` | 选择技能 | ✅ 已实现 |
| GET | `/api/v1/skills/recommend` | 推荐技能 | ✅ 已实现 |

**文件**: `neurova/api/endpoints/skill.py`

**状态**: ✅ 已完成

---

### 6. 技能市场模块 (Skill Market)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/skill-market/*` | 技能市场相关API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/skill_market.py`

---

### 7. 渠道管理模块 (Channel)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/channels` | 渠道列表 | ✅ 已实现 |
| GET | `/api/v1/channels/{channel}` | 渠道状态 | ✅ 已实现 |
| POST | `/api/v1/channels/{channel}` | 渠道配置 | ✅ 已实现 |
| POST | `/api/v1/channels/{channel}/enable` | 渠道启用 | ✅ 已实现 |
| POST | `/api/v1/channels/{channel}/disable` | 渠道禁用 | ✅ 已实现 |
| DELETE | `/api/v1/channels/{channel}` | 渠道删除 | ✅ 已实现 |
| POST | `/api/v1/channels/webhook/{channel}` | Webhook接收 | ❌ 缺失 |
| POST | `/api/v1/channels/{channel}/send` | 发送消息 | ❌ 缺失 |
| GET | `/api/v1/channels/capabilities` | 渠道能力描述 | ❌ 缺失 |
| POST | `/api/v1/channels/users/link` | 用户身份关联 | ❌ 缺失 |
| POST | `/api/v1/channels/{channel}/media/upload` | 媒体上传 | ❌ 缺失 |
| GET | `/api/v1/channels/{channel}/media/{media_id}` | 媒体下载 | ❌ 缺失 |
| POST | `/api/v1/channels/{channel}/media/send` | 发送媒体消息 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/channel.py`

**注意**: 前端 `channel.ts` 只实现了基础功能，需要补充完整。

---

### 8. LLM提供商模块 (Provider)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/providers` | 列出所有提供商 | ✅ 已实现 |
| POST | `/api/v1/providers` | 创建提供商 | ✅ 已实现 |
| GET | `/api/v1/providers/{provider_id}` | 获取提供商详情 | ✅ 已实现 |
| PUT | `/api/v1/providers/{provider_id}` | 更新提供商 | ✅ 已实现 |
| DELETE | `/api/v1/providers/{provider_id}` | 删除提供商 | ✅ 已实现 |
| POST | `/api/v1/providers/{provider_id}/test` | 测试提供商连接 | ❌ 缺失 |
| GET | `/api/v1/providers/{provider_id}/models` | 获取提供商的模型列表 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/provider.py`

---

### 9. 模型管理模块 (Model)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/api/v1/models` | 获取可用模型列表 | ❌ 缺失 |
| POST | `/api/v1/models/switch` | 切换当前模型 | ❌ 缺失 |
| GET | `/api/v1/models/current` | 获取当前模型信息 | ❌ 缺失 |
| GET | `/api/v1/models/stats` | 获取模型统计 | ❌ 缺失 |
| POST | `/api/v1/models/refresh` | 刷新模型客户端 | ❌ 缺失 |
| POST | `/api/v1/models/select` | 选择模型（负载均衡） | ❌ 缺失 |
| GET | `/api/v1/models/{provider_id}/{model}` | 获取模型详情 | ❌ 缺失 |
| POST | `/api/v1/models/record-usage` | 记录Token使用 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/model.py`

**优先级**: ⭐⭐⭐⭐⭐ (P0 - 核心功能)

---

### 10. 生成管理模块 (Generation)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/generations/*` | 生成管理相关API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/generation.py`

---

### 11. ACP Server模块 (ACP)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/acp/*` | ACP Server相关API | ✅ 已实现 (部分) |

**文件**: `neurova/core/acp_server.py`

---

### 12. 用户组管理模块 (User Group)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/user-groups/*` | 用户组管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/user_group_api.py`

---

### 13. 增强用户管理模块 (Enhanced User)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/enhanced-users/*` | 增强用户管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/enhanced_users_api.py`

---

### 14. 技能池管理模块 (Skill Pool)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/skill-pool/*` | 技能池管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/skill_pool_api.py`

---

### 15. 协作项目模块 (Collaboration)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| POST | `/api/v1/collaborations` | 创建项目 | ❌ 缺失 |
| GET | `/api/v1/collaborations` | 列出用户参与的项目 | ❌ 缺失 |
| GET | `/api/v1/collaborations/{project_id}` | 获取项目详情 | ❌ 缺失 |
| PUT | `/api/v1/collaborations/{project_id}` | 更新项目 | ❌ 缺失 |
| DELETE | `/api/v1/collaborations/{project_id}` | 删除项目 | ❌ 缺失 |
| POST | `/api/v1/collaborations/{project_id}/members` | 添加项目成员 | ❌ 缺失 |
| DELETE | `/api/v1/collaborations/{project_id}/members/{target_user_id}` | 移除项目成员 | ❌ 缺失 |
| PUT | `/api/v1/collaborations/{project_id}/members/{target_user_id}` | 更新成员角色 | ❌ 缺失 |
| POST | `/api/v1/collaborations/{project_id}/files` | 上传项目文件 | ❌ 缺失 |
| GET | `/api/v1/collaborations/{project_id}/files` | 列出项目文件 | ❌ 缺失 |
| GET | `/api/v1/collaborations/{project_id}/workflows` | 列出项目工作流 | ❌ 缺失 |
| POST | `/api/v1/collaborations/{project_id}/workflows` | 创建项目工作流 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/collaboration_api.py`

---

### 16. 项目管理模块 (Project - 旧版)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/projects/*` | 项目管理API（旧版） | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/projects_api.py`

---

### 17. 工作流管理模块 (Workflow - 旧版)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/workflows/*` | 工作流管理API（旧版） | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/workflows_api.py`

---

### 18. 文件流管理模块 (File Flow)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/file-flows/*` | 文件流管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/file_flows_api.py`

---

### 19. 团队管理模块 (Team - 旧版)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/teams/*` | 团队管理API（旧版） | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/teams_api.py`

---

### 20. 任务管理模块 (Task)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/tasks/*` | 任务管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/tasks_api.py`

---

### 21. 群组管理模块 (Group - 旧版)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/groups/*` | 群组管理API（旧版） | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/groups_api.py`

---

### 22. 日志管理模块 (Logs)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/logs/*` | 日志管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/logs_api.py`

---

### 23. 渠道上下文共享模块 (Channel Sharing)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/channel-sharing/*` | 渠道上下文共享API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/channel_sharing.py`

---

### 24. 媒体存储模块 (Media)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/media/*` | 媒体存储API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/media.py`

---

### 25. 成长系统模块 (Growth)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/growth/*` | 成长系统API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/growth.py`

---

### 26. 经验知识库模块 (Experience Knowledge)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/experience-knowledge/*` | 经验知识库API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/experience_knowledge_api.py`

---

### 27. 共享配置管理模块 (Shared Config)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/shared-config/*` | 共享配置管理API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/shared_config.py`

---

### 28. 技能版本管理模块 (Skill Version)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/skill-versions/*` | 技能版本管理API | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/skill_version_api.py`

---

### 29. Agent外部通信模块 (Agent Communication)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/agent-communication/*` | Agent外部通信API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/agent_communication_api.py`

---

### 30. Agent防火墙模块 (Firewall)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/firewall/*` | Agent防火墙API | ❌ 缺失 |

**文件**: `neurova/api/endpoints/firewall.py`

---

### 31. 系统设置模块 (Settings)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| (待确认) | `/api/v1/settings/*` | 系统设置API | ✅ 已实现 (部分) |

**文件**: `neurova/api/endpoints/settings.py`

---

### 32. Web Console模块 (Console)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| POST | `/console/chat` | 控制台对话 | ✅ 已实现 |
| POST | `/console/chat/stop` | 停止生成 | ✅ 已实现 |
| GET | `/console/chat/history` | 获取聊天历史 | ✅ 已实现 |
| POST | `/console/chat/new` | 创建新会话 | ✅ 已实现 |
| GET | `/console/chat/sessions` | 获取会话列表 | ✅ 已实现 |
| POST | `/console/upload` | 上传文件 | ✅ 已实现 |
| GET | `/console/upload/list` | 列出上传文件 | ✅ 已实现 |
| GET | `/console/upload/{file_id}` | 获取上传文件 | ✅ 已实现 |
| DELETE | `/console/upload/{file_id}` | 删除上传文件 | ✅ 已实现 |
| GET | `/console/debug/backend-logs` | 获取后端日志 | ❌ 缺失 |
| GET | `/console/debug/system-status` | 获取系统状态 | ❌ 缺失 |
| POST | `/console/debug/run-command` | 运行调试命令 | ❌ 缺失 |
| GET | `/console/push-messages` | 获取推送消息 | ❌ 缺失 |
| POST | `/console/push-messages` | 发送推送消息 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/console.py`

---

### 33. 上下文管理模块 (Context)

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| POST | `/api/v1/context/build` | 构建上下文 | ❌ 缺失 |
| GET | `/api/v1/context/stats` | 获取上下文统计 | ❌ 缺失 |
| GET | `/api/v1/context/{context_id}/preview` | 获取上下文预览 | ❌ 缺失 |
| GET | `/api/v1/context/inject/reflection` | 注入反思日志 | ❌ 缺失 |
| GET | `/api/v1/context/inject/memories` | 注入相关记忆 | ❌ 缺失 |
| GET | `/api/v1/context/inject/hot` | 注入高温记忆 | ❌ 缺失 |
| POST | `/api/v1/context/{context_id}/compress` | 压缩上下文 | ❌ 缺失 |
| GET | `/api/v1/context/budget` | 获取Token预算 | ❌ 缺失 |
| POST | `/api/v1/context/budget/set` | 设置Token预算 | ❌ 缺失 |
| GET | `/api/v1/context/{context_id}` | 获取缓存的上下文 | ❌ 缺失 |
| POST | `/api/v1/context/cache/clear` | 清除上下文缓存 | ❌ 缺失 |

**文件**: `neurova/api/endpoints/context.py`

---

### 34. 系统级API

| 方法 | 路径 | 功能 | 前端模块 |
|------|------|------|----------|
| GET | `/health` | 健康检查 | ❌ 缺失 |
| GET | `/api/stats` | 获取系统统计信息 | ❌ 缺失 |

**文件**: `neurova/api/app.py`

---

## 前端API模块现状

### ✅ 已实现的模块

| 模块名称 | 文件路径 | 实现状态 | 备注 |
|----------|----------|----------|------|
| Chat | `src/api/modules/chat.ts` | ✅ 完整 | 使用Console API |
| Agent | `src/api/modules/agent.ts` | ⚠️ 部分 | 只实现了配置管理 |
| Skill | `src/api/modules/skill.ts` | ✅ 完整 | |
| Provider | `src/api/modules/provider.ts` | ✅ 完整 | |
| Channel | `src/api/modules/channel.ts` | ⚠️ 部分 | 缺少Webhook、媒体上传等功能 |
| SkillVersion | `src/api/modules/skillVersion.ts` | ⚠️ 部分 | |
| Workflow | `src/api/modules/workflow.ts` | ⚠️ 部分 | 旧版API |
| Team | `src/api/modules/team.ts` | ⚠️ 部分 | 旧版API |
| Project | `src/api/modules/project.ts` | ⚠️ 部分 | 旧版API |
| Group | `src/api/modules/group.ts` | ⚠️ 部分 | 旧版API |
| Workspace | `src/api/modules/workspace.ts` | ⚠️ 部分 | |
| Tools | `src/api/modules/tools.ts` | ⚠️ 部分 | |
| ACP | `src/api/modules/acp.ts` | ⚠️ 部分 | |
| Settings | `src/api/modules/settings.ts` | ⚠️ 部分 | |
| CronJob | `src/api/modules/cronjob.ts` | ⚠️ 部分 | |
| AgentCommunication | `src/api/modules/agentCommunication.ts` | ⚠️ 部分 | |

---

## 缺失API模块清单

### ⭐ P0 - 核心功能（必须实现）

| 序号 | 模块名称 | 文件路径 | 优先级 | 备注 |
|------|----------|----------|--------|------|
| 1 | **Auth API** | `src/api/modules/auth.ts` | ⭐⭐⭐⭐⭐ | 认证系统必需 |
| 2 | **Memory API** | `src/api/modules/memory.ts` | ⭐⭐⭐⭐⭐ | 记忆管理核心功能 |
| 3 | **Model API** | `src/api/modules/model.ts` | ⭐⭐⭐⭐⭐ | 模型管理核心功能 |
| 4 | **Agent API (完整版)** | `src/api/modules/agent.ts` | ⭐⭐⭐⭐ | 补充完整Agent管理功能 |

---

### ⭐ P1 - 重要功能（应该实现）

| 序号 | 模块名称 | 文件路径 | 优先级 | 备注 |
|------|----------|----------|--------|------|
| 5 | **User Group API** | `src/api/modules/userGroup.ts` | ⭐⭐⭐⭐ | 多用户管理系统 |
| 6 | **Enhanced User API** | `src/api/modules/enhancedUser.ts` | ⭐⭐⭐⭐ | 增强用户管理 |
| 7 | **Skill Pool API** | `src/api/modules/skillPool.ts` | ⭐⭐⭐⭐ | 技能池管理 |
| 8 | **Generation API** | `src/api/modules/generation.ts` | ⭐⭐⭐ | 生成管理 |
| 9 | **Collaboration API** | `src/api/modules/collaboration.ts` | ⭐⭐⭐ | 协作项目（增强版） |
| 10 | **Skill Market API** | `src/api/modules/skillMarket.ts` | ⭐⭐⭐ | 技能市场 |

---

### ⭐ P2 - 协作功能（可以实现）

| 序号 | 模块名称 | 文件路径 | 优先级 | 备注 |
|------|----------|----------|--------|------|
| 11 | **Task API** | `src/api/modules/task.ts` | ⭐⭐ | 任务管理 |
| 12 | **File Flow API** | `src/api/modules/fileFlow.ts` | ⭐⭐ | 文件流管理 |
| 13 | **Media API** | `src/api/modules/media.ts` | ⭐⭐ | 媒体存储 |
| 14 | **Channel Sharing API** | `src/api/modules/channelSharing.ts` | ⭐⭐ | 渠道上下文共享 |

---

### ⭐ P3 - 高级功能（可选实现）

| 序号 | 模块名称 | 文件路径 | 优先级 | 备注 |
|------|----------|----------|--------|------|
| 15 | **Logs API** | `src/api/modules/logs.ts` | ⭐ | 日志管理 |
| 16 | **Growth API** | `src/api/modules/growth.ts` | ⭐ | 成长系统 |
| 17 | **Experience Knowledge API** | `src/api/modules/experienceKnowledge.ts` | ⭐ | 经验知识库 |
| 18 | **Shared Config API** | `src/api/modules/sharedConfig.ts` | ⭐ | 共享配置管理 |
| 19 | **Agent Communication API** | `src/api/modules/agentCommunication.ts` | ⭐ | Agent外部通信 |
| 20 | **Firewall API** | `src/api/modules/firewall.ts` | ⭐ | Agent防火墙 |
| 21 | **Context API** | `src/api/modules/context.ts` | ⭐ | 上下文管理 |
| 22 | **System API** | `src/api/modules/system.ts` | ⭐ | 系统级API（健康检查、统计） |

---

## SDK依赖清单

### 当前依赖 (package.json)

| 依赖名称 | 版本 | 用途 | 状态 |
|----------|------|------|------|
| `react` | ^18.3.1 | React框架 | ✅ 已安装 |
| `react-dom` | ^18.3.1 | React DOM渲染 | ✅ 已安装 |
| `react-router-dom` | ^7.13.0 | 路由管理 | ✅ 已安装 |
| `react-markdown` | ^10.1.0 | Markdown渲染 | ✅ 已安装 |
| `highlight.js` | ^11.11.1 | 代码高亮 | ✅ 已安装 |
| `rehype-highlight` | ^7.0.2 | Markdown代码高亮 | ✅ 已安装 |
| `antd` | ^5.29.1 | UI组件库 | ✅ 已安装 |
| `@ant-design/icons` | ^5.0.1 | Ant Design图标 | ✅ 已安装 |
| `i18next` | ^25.8.4 | 国际化 | ✅ 已安装 |
| `react-i18next` | ^16.5.4 | React国际化 | ✅ 已安装 |
| `dayjs` | ^1.11.13 | 日期处理 | ✅ 已安装 |
| `zustand` | ^5.0.3 | 状态管理 | ✅ 已安装 |

---

### 建议新增的SDK依赖

| 依赖名称 | 版本 | 用途 | 优先级 | 安装命令 |
|----------|------|------|--------|----------|
| **`@tanstack/react-query`** | ^5.0.0 | 数据请求缓存 | ⭐⭐⭐⭐⭐ | `npm install @tanstack/react-query` |
| **`axios`** | ^1.7.0 | HTTP客户端（可选，当前使用fetch） | ⭐⭐⭐ | `npm install axios` |
| **`recharts`** | ^2.12.0 | 图表可视化 | ⭐⭐⭐⭐ | `npm install recharts` |
| **`react-virtualized`** | ^9.22.0 | 虚拟滚动（长列表优化） | ⭐⭐⭐ | `npm install react-virtualized` |
| **`react-intersection-observer`** | ^9.13.0 | 懒加载（图片、组件） | ⭐⭐⭐ | `npm install react-intersection-observer` |
| **`i18next-browser-languagedetector`** | ^8.0.0 | 浏览器语言检测 | ⭐⭐ | `npm install i18next-browser-languagedetector` |
| **`react-hot-toast`** | ^2.4.0 | 消息提示 | ⭐⭐⭐⭐ | `npm install react-hot-toast` |
| **`react-helmet-async`** | ^2.0.0 | 动态修改页面头部 | ⭐⭐ | `npm install react-helmet-async` |

---

### 腾讯云相关SDK（可选）

| 依赖名称 | 版本 | 用途 | 优先级 | 安装命令 |
|----------|------|------|--------|----------|
| **`cos-js-sdk-v5`** | ^1.8.0 | 腾讯云对象存储 | ⭐⭐ | `npm install cos-js-sdk-v5` |
| **`tcb-js-sdk`** | ^2.1.0 | 腾讯云开发 | ⭐⭐ | `npm install tcb-js-sdk` |

---

## 优先级建议

### 第一阶段（P0 - 核心功能）

1. **创建 Auth API 模块** - 认证系统必需
2. **创建 Memory API 模块** - 记忆管理核心功能
3. **创建 Model API 模块** - 模型管理核心功能
4. **完善 Agent API 模块** - 补充完整Agent管理功能

---

### 第二阶段（P1 - 重要功能）

1. **创建 User Group API 模块** - 多用户管理系统
2. **创建 Enhanced User API 模块** - 增强用户管理
3. **创建 Skill Pool API 模块** - 技能池管理
4. **创建 Generation API 模块** - 生成管理
5. **创建 Collaboration API 模块** - 协作项目（增强版）
6. **创建 Skill Market API 模块** - 技能市场

---

### 第三阶段（P2 - 协作功能）

1. **创建 Task API 模块** - 任务管理
2. **创建 File Flow API 模块** - 文件流管理
3. **创建 Media API 模块** - 媒体存储
4. **创建 Channel Sharing API 模块** - 渠道上下文共享

---

### 第四阶段（P3 - 高级功能）

1. **创建 Logs API 模块** - 日志管理
2. **创建 Growth API 模块** - 成长系统
3. **创建 Experience Knowledge API 模块** - 经验知识库
4. **创建 Shared Config API 模块** - 共享配置管理
5. **创建 Agent Communication API 模块** - Agent外部通信
6. **创建 Firewall API 模块** - Agent防火墙
7. **创建 Context API 模块** - 上下文管理
8. **创建 System API 模块** - 系统级API

---

## 总结

### 统计数据

| 指标 | 数值 | 说明 |
|------|------|------|
| **后端API端点文件** | 27个 | 分布在 `neurova/api/endpoints/` 目录 |
| **后端API端点数量** | 397+ | 至少397个路由定义 |
| **前端API模块** | 17个 | 分布在 `neurova-ui/src/api/modules/` 目录 |
| **已实现的功能** | ~50个 | 约占12.6% |
| **缺失的功能** | ~347个 | 约占87.4% |

---

### 关键发现

1. **前端API模块严重缺失** - 只实现了约12.6%的后端API功能
2. **核心功能缺失** - Auth、Memory、Model等核心模块完全缺失
3. **部分模块需要实现** - Agent、Channel等模块只实现了部分功能
4. **SDK依赖需要补充** - 建议新增React Query、Recharts等依赖

---

### 下一步行动

1. **立即开始** - 创建P0级别的API模块（Auth、Memory、Model、Agent完整版）
2. **短期计划** - 创建P1级别的API模块（User Group、Enhanced User、Skill Pool等）
3. **长期计划** - 逐步完善所有API模块，补充SDK依赖

---

**文档版本**: v1.0  
**最后更新**: 2026-05-14  
**维护者**: Neurova开发团队
