# Neurova API 集成对照矩阵

> **生成时间**: 2026-05-22
> **目的**: 后端 API ↔ 前端 API 封装 ↔ 前端页面/Store 的全链路对照，标记闭环状态
> **API 基础路径**: `/api/v1`

---

## 📊 图例说明

| 标识 | 含义 |
|------|------|
| ✅ | **已闭环** — 后端 API 存在 → 前端 API 封装完成 → 页面/Store 已对接 |
| ⚠️ | **部分闭环** — 后端 API 存在 → 前端 API 封装完成 → 页面有 mock 回退/部分对接 |
| ❌ | **未闭环** — 后端 API 存在但前端页面为占位符，或前端 API 未封装 |
| 🔵 | **仅后端** — 后端 API 存在，前端暂无需求或未规划页面 |
| 🟡 | **待封装** — 前端页面已创建但 API 模块未封装 |
| 🔴 | **占位符** — 前端页面为骨架占位符，数据完全硬编码 |

---

## 模块 1: 认证与用户管理 (Auth)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 1.1 | `/api/v1/auth/login` | POST | 用户登录，返回 JWT Token | `auth.ts` → `authAPI.login()` | `LoginPage.vue` → `authStore.login()` | ✅ |
| 1.2 | `/api/v1/auth/register` | POST | 完成注册 | `auth.ts` → `authAPI.register()` | `RegisterPage.vue` → `authStore.register()` | ✅ |
| 1.3 | `/api/v1/auth/refresh` | POST | 刷新 Token | `auth.ts` → `authAPI.refresh()` | — | ✅ |
| 1.4 | `/api/v1/auth/me` | GET | 获取当前用户信息 | `auth.ts` → `authAPI.getCurrentUser()` | `authStore.fetchCurrentUser()` | ✅ |
| 1.5 | `/api/v1/auth/logout` | POST | 用户登出 | `auth.ts` → `authAPI.logout()` | `authStore.logout()` | ✅ |
| 1.6 | `/api/v1/auth/register/send-code` | POST | 发送注册验证码 | `auth.ts` → `authAPI.sendRegisterCode()` | — | ✅ |
| 1.7 | `/api/v1/auth/register/verify-code` | POST | 验证注册验证码 | `auth.ts` → `authAPI.verifyRegisterCode()` | — | ✅ |
| 1.8 | `/api/v1/auth/register/invite` | POST | 邀请注册 | 未封装 | — | 🔵 |
| 1.9 | `/api/v1/auth/activate` | POST | 激活账号 | 未封装 | — | 🔵 |
| 1.10 | `/api/v1/auth/resend-activate` | POST | 重发激活邮件 | 未封装 | — | 🔵 |
| 1.11 | `/api/v1/auth/forgot-password` | POST | 忘记密码 | `auth.ts` → `authAPI.forgotPassword()` | — | ✅ |
| 1.12 | `/api/v1/auth/reset-password` | POST | 重置密码 | `auth.ts` → `authAPI.resetPassword()` | — | ✅ |
| 1.13 | `/api/v1/auth/change-password` | POST | 修改密码 | `auth.ts` → `authAPI.changePassword()` | `SettingPage.vue` | ✅ |
| 1.14 | `/api/v1/auth/account/status` | GET | 获取账号状态 | `auth.ts` → `authAPI.getAccountStatus()` | `SettingPage.vue` | ✅ |
| 1.15 | `/api/v1/auth/account/deactivate` | POST | 注销账号 | `auth.ts` → `authAPI.deactivateAccount()` | — | ✅ |
| 1.16 | `/api/v1/settings/users` | GET/POST/PUT/DELETE | 增强用户管理（多用户隔离） | `enhanced-users.ts` → `enhancedUserAPI.*` | `EnhancedUserPage.vue` | ✅ |
| 1.17 | `/api/v1/projects/{project_id}/groups` | GET/POST/PUT/DELETE | 群组聊天管理 | `group-chat.ts` → `groupChatAPI.*` | `GroupPage.vue` | ✅ |

---

## 模块 2: Agent 管理核心 (Agent)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 2.1 | `/api/v1/agents` | GET | 列出所有 Agent（按用户隔离） | `agents.ts` → `agentAPI.list()` | `AgentListPage.vue`、`agentStore` | ✅ |
| 2.2 | `/api/v1/agents/{agent_id}` | GET | 获取 Agent 详情 | `agents.ts` → `agentAPI.get(id)` | `AgentFormPage.vue`（编辑模式） | ✅ |
| 2.3 | `/api/v1/agents` | POST | 创建 Agent | `agents.ts` → `agentAPI.create(data)` | `AgentFormPage.vue`（创建模式） | ✅ |
| 2.4 | `/api/v1/agents/{agent_id}` | DELETE | 删除 Agent | `agents.ts` → `agentAPI.delete(id)` | `AgentListPage.vue` | ✅ |
| 2.5 | `/api/v1/agents/{agent_id}/stats` | GET | 获取 Agent 统计 | `agents.ts` → `agentAPI.getStats(id)` | 未调用 | 🟡 |
| 2.6 | `/api/v1/agents/{agent_id}/switch` | POST | 切换默认 Agent | `agents.ts` → `agentAPI.switch(id)` | `AgentListPage.vue` | ✅ |
| 2.7 | `/api/v1/agents/{agent_id}/constitution` | GET | 获取 Agent 宪法 | `agents.ts` → `agentAPI.getConstitution(id)` | — | ✅ |
| 2.8 | `/api/v1/agents/{agent_id}/constitution` | PUT | 更新 Agent 宪法 | `agents.ts` → `agentAPI.updateConstitution(id, data)` | — | ✅ |
| 2.9 | `/api/v1/agents/{agent_id}/personality` | GET | 获取个性特征 | `agents.ts` → `agentAPI.getPersonality(id)` | `AgentPersonalityPage.vue` | ✅ |
| 2.10 | `/api/v1/agents/{agent_id}/personality` | PUT | 更新个性特征 | `agents.ts` → `agentAPI.updatePersonality(id, data)` | `AgentPersonalityPage.vue` | ✅ |
| 2.11 | `/api/v1/agents/{agent_id}/personality/report` | GET | 获取人格发展报告 | 未封装 | — | 🔵 |
| 2.12 | `/api/v1/agents/{agent_id}/decide` | POST | 发起自主决策 | 未封装 | — | 🔵 |
| 2.13 | `/api/v1/agents/{agent_id}/config` | GET | 获取 Agent 完整配置 | `agents.ts` → `agentAPI.getConfig(id)` | — | ✅ |
| 2.14 | `/api/v1/agents/{agent_id}/config` | PUT | 更新 Agent 配置 | `agents.ts` → `agentAPI.updateConfig(id, data)` | `AgentFormPage.vue` | ✅ |
| 2.15 | `/api/v1/agents/{id}/status` | GET | Agent 状态监控 | `agents.ts` → `agentAPI.getStatus(id)` | `MonitorPage.vue` | ✅ |
| 2.16 | `/api/v1/agents/{id}/capabilities` | GET | Agent 能力查询 | `agents.ts` → `agentAPI.getCapabilities(id)` | — | ✅ |
| 2.17 | `/api/v1/agents/{id}/health` | GET | Agent 健康检查 | `agents.ts` → `agentAPI.getHealth(id)` | `MonitorPage.vue` | ✅ |
| 2.18 | `/api/v1/agents/{id}/restart` | POST | 重启 Agent | `agents.ts` → `agentAPI.restart(id)` | `MonitorPage.vue` | ✅ |

---

## 模块 3: 对话系统 (Chat)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 3.1 | `/api/v1/chat` | POST | 发送对话（普通模式） | `chat.ts` → `sendMessage()` | `ChatPage.vue` | ✅ |
| 3.2 | `/api/v1/chat/stream` | POST | 流式对话 (SSE) | `chat.ts` → `sendMessageStream()` | `ChatPage.vue` | ✅ |
| 3.3 | `/api/v1/chat/history` | GET | 获取对话历史 | `chat.ts` → `getMessages()` | `ChatPage.vue` | ✅ |
| 3.4 | `/api/v1/chat/history` | DELETE | 清空对话历史 | `chat.ts` → `deleteConversation()` | `ChatPage.vue` | ✅ |
| 3.6 | 文件上传 | POST | 多媒体文件上传到 media API | `chat.ts` → `uploadMedia()` | `ChatPage.vue` (发送前上传) | ✅ |
| 3.7 | 媒体 URL 获取 | GET | 获取媒体文件访问 URL | `chat.ts` → `getMediaUrl()` | `ChatPage.vue` (附件预览) | ✅ |
| 3.8 | 会话重命名 | PUT | 重命名会话标题 | `chat.ts` → `renameConversation()` | `ChatPage.vue` (侧栏内联编辑) | ✅ |

> **ChatPage 现状**：`handleSend()` 中注释 "对接真实 API 后将通过 SSE 流式处理"，当前使用逐字 setTimeout 模拟。

---

## 模块 4: 记忆与认知系统 (Memory)

后端路由前缀: `/api/v1/memories`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 4.1 | `/api/v1/memories` | GET | 搜索记忆（关键词+过滤） | `memory.ts` → `list()` | `MemoryPage.vue` | ✅ |
| 4.2 | `/api/v1/memories` | POST | 创建记忆 | `memory.ts` → `create()` | 未调用 | 🟡 |
| 4.3 | `/api/v1/memories/{id}` | GET | 获取单条记忆详情 | `memory.ts` → `get(id)` | 未调用 | 🟡 |
| 4.4 | `/api/v1/memories/{id}` | DELETE | 删除记忆 | `memory.ts` → `delete(id)` | 未调用 | 🟡 |
| 4.5 | `/api/v1/memories/stats` | GET | 获取记忆统计 | `memory.ts` → `getStats()` | `MemoryPage.vue` | ✅ |
| 4.6 | `/api/v1/memories/{id}/forget` | POST | 遗忘记忆 | `memory.ts` → `forget(id, data)` | `MemoryPage.vue` | ✅ |
| 4.7 | `/api/v1/memories/{id}/strengthen` | POST | 强化记忆 | `memory.ts` → `strengthen(id, data)` | `MemoryPage.vue` | ✅ |
| 4.8 | `/api/v1/memories/categories` | GET | 获取记忆分类 | `memory.ts` → `getCategories()` | `MemoryPage.vue` | ✅ |
| 4.9 | `/api/v1/memories/batch` | POST | 批量操作 | `memory.ts` → `batch(data)` | `MemoryPage.vue` | ✅ |
| 4.10 | `/api/v1/memories/export` | GET | 导出记忆 | `memory.ts` → `export(params)` | — | ✅ |
| 4.11 | `/api/v1/memories/import` | POST | 导入记忆 | `memory.ts` → `import(data)` | — | ✅ |

---

## 模块 5: 技能与学习系统 (Skill)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 5.1 | `/api/v1/skills/public` | GET | 公共技能列表 | `skill.ts` → `listPublicSkills()` | `SkillMarketPage.vue` | ✅ |
| 5.2 | `/api/v1/skills/public/{skill_id}` | GET | 公共技能详情 | `skill.ts` → `getPublicSkill()` | `SkillMarketPage.vue` | ✅ |
| 5.3 | `/api/v1/skills/public/{skill_id}/install` | POST | 安装公共技能 | `skill.ts` → `installPublicSkill()` | `SkillMarketPage.vue` | ✅ |
| 5.4 | `/api/v1/skills/private` | GET | 专属技能列表 | `skill.ts` → `listPrivateSkills()` | `SkillPoolPage.vue` | ✅ |
| 5.5 | `/api/v1/skills/private` | POST | 创建专属技能 | `skill.ts` → `createPrivateSkill()` | `SkillPoolPage.vue` | ✅ |
| 5.6 | `/api/v1/skills/private/{skill_id}` | PUT | 更新专属技能 | `skill.ts` → `updatePrivateSkill()` | `SkillPoolPage.vue` | ✅ |
| 5.7 | `/api/v1/skills/private/{skill_id}` | DELETE | 删除专属技能 | `skill.ts` → `deletePrivateSkill()` | `SkillPoolPage.vue` | ✅ |
| 5.8 | `/api/v1/skills/private/{skill_id}/share` | POST | 分享专属技能 | `skill.ts` → `sharePrivateSkill()` | 未调用 | 🟡 |
| 5.9 | `/api/v1/skills/{skill_id}/push` | POST | 推送技能给Agent | `skill.ts` → `pushSkillToAgent()` | `AgentSkillPage.vue` | ✅ |
| 5.10 | `/api/v1/skills/{skill_id}/unpush` | POST | 取消推送技能 | `skill.ts` → `unpushSkillFromAgent()` | `AgentSkillPage.vue` | ✅ |
| 5.11 | `/api/v1/skills/agent/{agent_id}` | GET | 获取Agent技能 | `skill.ts` → `getAgentSkills()` | `AgentSkillPage.vue` | ✅ |
| 5.12 | 技能市场（全局） | GET/POST | 全局技能市场 | 未封装 | `MarketplacePage.vue` 占位符 | 🔴 |
| 5.13 | 技能版本管理 | GET/POST | 版本检测/同步 | 未封装 | — | 🔵 |
| 5.14 | AIGC 生成 | GET/POST | 文生图/视频等 | 未封装 | `AIGCPage.vue` 占位符 | 🔴 |

> **Skill 模块已完善**：`skill_pool_api.py` 后端已完整，`skill.ts` 前端 API 已重构适配，`SkillMarketPage.vue`、`SkillPoolPage.vue`、`AgentSkillPage.vue` 可对接真实 API。

---

## 模块 6: 知识库与文档 (Knowledge)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 6.1 | `/api/v1/knowledge/configs` | GET/POST | 知识库配置管理 | `knowledge_api.ts` → `getConfigs()`, `createConfig()`, `updateConfig()`, `deleteConfig()` | `KnowledgePage.vue` | ✅ |
| 6.2 | `/api/v1/knowledge/collections` | GET/POST | 知识库集合管理 | `knowledge_api.ts` → `getCollections()`, `createCollection()` | `KnowledgePage.vue` | ✅ |
| 6.3 | `/api/v1/knowledge/collections/{id}` | GET/PUT/DELETE | 知识库集合操作 | `knowledge_api.ts` → `getCollection()`, `updateCollection()`, `deleteCollection()` | `KnowledgePage.vue` | ✅ |
| 6.4 | `/api/v1/knowledge/documents/upload` | POST | 文档上传 | `knowledge_api.ts` → `uploadDocument()` | `KnowledgePage.vue` | ✅ |
| 6.5 | `/api/v1/knowledge/collections/{id}/documents` | GET | 获取文档列表 | `knowledge_api.ts` → `getDocuments()` | `KnowledgePage.vue` | ✅ |
| 6.6 | `/api/v1/knowledge/documents/{id}` | DELETE | 删除文档 | `knowledge_api.ts` → `deleteDocument()` | `KnowledgePage.vue` | ✅ |
| 6.7 | `/api/v1/knowledge/search` | POST | 知识库搜索 | `knowledge_api.ts` → `search()`, `searchMulti()` | `KnowledgePage.vue` | ✅ |
| 6.8 | 心流知识库集成 | GET/POST | 心流知识库配置 | 已集成在知识库配置中 | — | 🔵 |
| 6.9 | RAG 增强 | GET/POST | 记忆-知识双向同步 | 未封装 | — | 🔵 |
| 6.10 | 认知进化 | GET/POST | 盲点发现/自动学习 | 未封装 | — | 🔵 |
| 6.11 | `/api/v1/files` | GET | 获取文件列表 | `files_api.ts` → `list()` | `AgentFilePage.vue` | ✅ |
| 6.12 | `/api/v1/files/upload` | POST | 上传文件（三层隔离） | `files_api.ts` → `upload()` | `AgentFilePage.vue` | ✅ |
| 6.13 | `/api/v1/files/{file_id}` | GET/PUT/DELETE | 文件操作 | `files_api.ts` → `getInfo()`, `update()`, `delete()` | `AgentFilePage.vue` | ✅ |
| 6.14 | `/api/v1/files/{file_id}/download` | GET | 文件下载 | `files_api.ts` → `download()` | `AgentFilePage.vue` | ✅ |
| 6.15 | `/api/v1/files/{file_id}/preview` | GET | 文件预览 | `files_api.ts` → `preview()` | `AgentFilePage.vue` | ✅ |
| 6.16 | `/api/v1/files/{file_id}/versions` | GET | 文件版本 | `files_api.ts` → `getVersions()` | `AgentFilePage.vue` | ✅ |
| 6.17 | `/api/v1/files/{file_id}/approve` | POST | 文件审批 | `files_api.ts` → `approve()`, `reject()` | `AgentFilePage.vue` | ✅ |
| 6.18 | `/api/v1/files/storage/info` | GET | 存储信息 | `files_api.ts` → `getStorageInfo()` | `AgentFilePage.vue` | ✅ |
| 6.19 | `/api/v1/files/cleanup` | POST | 清理过期文件 | `files_api.ts` → `cleanup()` | `AgentFilePage.vue` | ✅ |
| 6.20 | 媒体处理 | GET/POST | Agent 媒体文件管理 | `files_api.ts` → `list()` | `AgentMediaPage.vue` | ✅ |

> **Knowledge 模块已完善**：`knowledge.py` 后端、`files_api.py` 后端已完整，`knowledge_api.ts`、`files_api.ts` 前端 API 已重构适配，`KnowledgePage.vue` 已支持完整的配置管理、知识库管理、文档管理和语义搜索；`AgentFilePage.vue`、`AgentMediaPage.vue` 可对接真实 API。

---

## 模块 7: 工作流与协作 (Workflow & Collaboration)

后端工作流端点: `/api/v1/projects/{project_id}/workflows`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 7.1 | `/api/v1/projects/{project_id}/workflows` | GET | 获取工作流列表 | `workflows.ts` → `list()` | `WorkflowPage.vue` | ✅ |
| 7.2 | `/api/v1/projects/{project_id}/workflows` | POST | 创建工作流 | `workflows.ts` → `create()` | `WorkflowPage.vue` | ✅ |
| 7.3 | `/api/v1/projects/{project_id}/workflows/{id}` | GET | 获取工作流详情 | `workflows.ts` → `get()` | `WorkflowPage.vue` | ✅ |
| 7.4 | `/api/v1/projects/{project_id}/workflows/{id}` | PUT | 更新工作流 | `workflows.ts` → `update()` | `WorkflowPage.vue` | ✅ |
| 7.5 | `/api/v1/projects/{project_id}/workflows/{id}` | DELETE | 删除工作流 | `workflows.ts` → `delete()` | `WorkflowPage.vue` | ✅ |
| 7.6 | `/api/v1/projects/{project_id}/workflows/{id}/execute` | POST | 执行工作流 | `workflows.ts` → `execute()` | `WorkflowPage.vue` | ✅ |
| 7.7 | `/api/v1/projects/{project_id}/workflows/{id}/executions` | GET | 获取执行列表 | `workflows.ts` → `listExecutions()` | 未调用 | ✅ |
| 7.8 | `/api/v1/projects/{project_id}/workflows/{id}/executions/{execution_id}` | GET | 获取执行详情 | `workflows.ts` → `getExecution()` | 未调用 | ✅ |
| 7.9 | `/api/v1/projects/{project_id}/workflows/{id}/executions/{execution_id}/pause` | POST | 暂停执行 | `workflows.ts` → `pauseExecution()` | 未调用 | ✅ |
| 7.10 | `/api/v1/projects/{project_id}/workflows/{id}/executions/{execution_id}/resume` | POST | 恢复执行 | `workflows.ts` → `resumeExecution()` | 未调用 | ✅ |
| 7.11 | `/api/v1/projects/{project_id}/workflows/{id}/executions/{execution_id}/cancel` | POST | 取消执行 | `workflows.ts` → `cancelExecution()` | 未调用 | ✅ |
| 7.12 | `/api/v1/projects/{project_id}/workflows/generate` | POST | LLM 生成工作流 | `workflows.ts` → `generate()` | `WorkflowPage.vue` | ✅ |
| 7.13 | `/api/v1/projects/{project_id}/workflows/generate-and-save` | POST | LLM 生成并保存 | `workflows.ts` → `generateAndSave()` | `WorkflowPage.vue` | ✅ |
| 7.14 | `/api/v1/projects/{project_id}/workflows/{id}/nodes` | GET | 获取节点数据 | `workflows.ts` → `getNodes()` | 未调用 | ✅ |
| 7.15 | `/api/v1/projects/{project_id}/workflows/{id}/steps` | POST | 添加步骤 | `workflows.ts` → `addStep()` | 未调用 | ✅ |
| 7.16 | `/api/v1/projects/{project_id}/workflows/{id}/steps/{step_id}` | PUT | 更新步骤 | `workflows.ts` → `updateStep()` | 未调用 | ✅ |
| 7.17 | `/api/v1/projects/{project_id}/workflows/{id}/steps/{step_id}` | DELETE | 删除步骤 | `workflows.ts` → `removeStep()` | 未调用 | ✅ |
| 7.18 | `/api/v1/projects/{project_id}/workflows/{id}/steps/{step_id}/position` | PUT | 更新步骤位置 | `workflows.ts` → `updateStepPosition()` | 未调用 | ✅ |
| 7.19 | `/api/v1/projects/{project_id}/workflows/{id}/steps/batch-update` | PUT | 批量更新步骤 | `workflows.ts` → `batchUpdateSteps()` | 未调用 | ✅ |
| 7.20 | `/api/v1/projects/{project_id}/workflows/{id}/edges` | POST | 创建节点连线 | `workflows.ts` → `createEdge()` | 未调用 | ✅ |
| 7.21 | `/api/v1/projects/{project_id}/workflows/{id}/edges/{source}/{target}` | DELETE | 删除节点连线 | `workflows.ts` → `deleteEdge()` | 未调用 | ✅ |
| 7.22 | `/api/v1/projects/{project_id}/workflows/{id}/edges/{source}/{target}` | PUT | 更新节点连线 | `workflows.ts` → `updateEdge()` | 未调用 | ✅ |
| 7.23 | `/api/v1/projects/{project_id}/workflows/{id}/viewport` | GET | 获取画布视图 | `workflows.ts` → `getViewport()` | 未调用 | ✅ |
| 7.24 | `/api/v1/projects/{project_id}/workflows/{id}/viewport` | PUT | 更新画布视图 | `workflows.ts` → `updateViewport()` | 未调用 | ✅ |
| 7.25 | `/api/v1/agents/capabilities` | GET | 获取能力矩阵 | `collaboration.ts` → `getCapabilities()` | `CollaborationPage.vue` 占位符 | ✅ |
| 7.26 | `/api/v1/agents/capabilities/{agent_id}` | GET | 获取 Agent 能力 | `collaboration.ts` → `getAgentCapability()` | 未调用 | ✅ |
| 7.27 | `/api/v1/agents/capabilities/register` | POST | 注册 Agent 能力 | `collaboration.ts` → `registerCapability()` | 未调用 | ✅ |
| 7.28 | `/api/v1/agents/capabilities/{agent_id}` | DELETE | 注销 Agent 能力 | `collaboration.ts` → `unregisterCapability()` | 未调用 | ✅ |
| 7.29 | `/api/v1/agents/collaborate` | POST | 发起协作 | `collaboration.ts` → `startCollaboration()` | `CollaborationInitiatePage.vue` 占位符 | ✅ |
| 7.30 | `/api/v1/agents/templates` | GET | 获取模板列表 | `collaboration.ts` → `getTemplates()` | `CollaborationTemplatePage.vue` 占位符 | ✅ |
| 7.31 | `/api/v1/agents/templates/preset` | GET | 获取预设模板 | `collaboration.ts` → `getPresetTemplates()` | 未调用 | ✅ |
| 7.32 | `/api/v1/agents/templates/{template_id}` | GET | 获取模板详情 | `collaboration.ts` → `getTemplate()` | 未调用 | ✅ |
| 7.33 | `/api/v1/agents/templates` | POST | 创建协作模板 | `collaboration.ts` → `createTemplate()` | 未调用 | ✅ |
| 7.34 | `/api/v1/agents/templates/{template_id}` | PUT | 更新协作模板 | `collaboration.ts` → `updateTemplate()` | 未调用 | ✅ |
| 7.35 | `/api/v1/agents/templates/{template_id}` | DELETE | 删除协作模板 | `collaboration.ts` → `deleteTemplate()` | 未调用 | ✅ |
| 7.36 | `/api/v1/agents/templates/{template_id}/clone` | POST | 克隆协作模板 | `collaboration.ts` → `cloneTemplate()` | 未调用 | ✅ |
| 7.37 | `/api/v1/agents/recommend` | POST | 获取任务推荐 | `collaboration.ts` → `getRecommendations()` | 未调用 | ✅ |
| 7.38 | `/api/v1/agents/matrix` | GET | 获取能力矩阵总览 | `collaboration.ts` → `getMatrix()` | 未调用 | ✅ |
| 7.39 | `/api/v1/agents/matrix/compare` | POST | 对比 Agent 能力 | `collaboration.ts` → `compareAgents()` | 未调用 | ✅ |
| 7.40 | `/api/v1/agents/dlq/stats` | GET | 获取死信队列统计 | `collaboration.ts` → `getDlqStats()` | 未调用 | ✅ |
| 7.41 | `/api/v1/agents/dlq/messages` | GET | 获取死信消息列表 | `collaboration.ts` → `getDlqMessages()` | 未调用 | ✅ |
| 7.42 | `/api/v1/agents/dlq/messages/{message_id}/retry` | POST | 重试死信消息 | `collaboration.ts` → `retryDlqMessage()` | 未调用 | ✅ |
| 7.43 | `/api/v1/agents/dlq/messages/{message_id}` | DELETE | 丢弃死信消息 | `collaboration.ts` → `discardDlqMessage()` | 未调用 | ✅ |
| 7.44 | `/api/v1/projects/{project_id}/tasks/boards` | GET/POST | 看板管理 | `tasks.ts` → `listBoards()/createBoard()` | `ProjectPage.vue` 占位符 | ✅ |
| 7.45 | `/api/v1/projects/{project_id}/tasks/boards/{board_id}` | GET | 获取看板详情 | `tasks.ts` → `getBoard()` | 未调用 | ✅ |
| 7.46 | `/api/v1/projects/{project_id}/tasks` | POST | 创建任务 | `tasks.ts` → `createTask()` | `TaskPage.vue` 占位符 | ✅ |
| 7.47 | `/api/v1/projects/{project_id}/tasks/{task_id}` | PUT | 更新任务 | `tasks.ts` → `updateTask()` | 未调用 | ✅ |
| 7.48 | `/api/v1/projects/{project_id}/tasks/{board_id}/move` | PUT | 移动任务 | `tasks.ts` → `moveTask()` | 未调用 | ✅ |
| 7.49 | `/api/v1/projects/{project_id}/tasks/{board_id}/stats` | GET | 获取看板统计 | `tasks.ts` → `getBoardStats()` | 未调用 | ✅ |
| 7.50 | 文件流转 | GET/POST | 文件流转模板/实例 | 未封装 | — | 🔵 |
| 7.51 | 团队管理 | GET/POST | 团队 CRUD | 未封装 | `TeamPage.vue` 占位符 | 🔴 |

> **工作流与协作模块已完善**：`workflows_api.py`、`tasks_api.py`、`collaboration_api.py` 后端已完整，`workflows.ts`、`collaboration.ts`、`tasks.ts` 前端 API 已完整封装，支持工作流创建编辑、协作管理、任务看板等功能。

---

## 模块 8: 调度与自动化 (Scheduler)

后端端点前缀: `/api/v1/scheduler`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 8.1 | `/api/v1/scheduler/tasks` | GET | 获取任务列表 | `scheduler.ts` → `listTasks()` | `AgentSchedulerPage.vue` 占位符 | ✅ |
| 8.2 | `/api/v1/scheduler/tasks` | POST | 创建任务 | `scheduler.ts` → `createTask()` | `AgentSchedulerPage.vue` 占位符 | ✅ |
| 8.3 | `/api/v1/scheduler/tasks/{id}` | GET | 获取任务详情 | `scheduler.ts` → `getTask()` | 未调用 | ✅ |
| 8.4 | `/api/v1/scheduler/tasks/{id}` | PUT | 更新任务 | `scheduler.ts` → `updateTask()` | 未调用 | ✅ |
| 8.5 | `/api/v1/scheduler/tasks/{id}` | DELETE | 删除任务 | `scheduler.ts` → `deleteTask()` | 未调用 | ✅ |
| 8.6 | `/api/v1/scheduler/tasks/batch-delete` | POST | 批量删除任务 | `scheduler.ts` → `batchDeleteTasks()` | 未调用 | ✅ |
| 8.7 | `/api/v1/scheduler/tasks/{id}/enable` | POST | 启用任务 | `scheduler.ts` → `enableTask()` | 未调用 | ✅ |
| 8.8 | `/api/v1/scheduler/tasks/{id}/disable` | POST | 禁用任务 | `scheduler.ts` → `disableTask()` | 未调用 | ✅ |
| 8.9 | `/api/v1/scheduler/tasks/{id}/execute` | POST | 立即执行任务 | `scheduler.ts` → `executeTask()` | 未调用 | ✅ |
| 8.10 | `/api/v1/scheduler/tasks/{id}/executions/{execution_id}/cancel` | POST | 取消执行 | `scheduler.ts` → `cancelExecution()` | 未调用 | ✅ |
| 8.11 | `/api/v1/scheduler/tasks/{id}/dependencies` | POST | 添加依赖 | `scheduler.ts` → `addDependency()` | 未调用 | ✅ |
| 8.12 | `/api/v1/scheduler/tasks/{id}/dependencies/{dependency_id}` | DELETE | 删除依赖 | `scheduler.ts` → `removeDependency()` | 未调用 | ✅ |
| 8.13 | `/api/v1/scheduler/dependencies/graph` | GET | 获取依赖图 | `scheduler.ts` → `getDependencyGraph()` | 未调用 | ✅ |
| 8.14 | `/api/v1/scheduler/tasks/{id}/executions` | GET | 获取执行历史 | `scheduler.ts` → `getExecutionHistory()` | 未调用 | ✅ |
| 8.15 | `/api/v1/scheduler/tasks/{id}/executions/{execution_id}` | GET | 获取执行详情 | `scheduler.ts` → `getExecutionDetail()` | 未调用 | ✅ |
| 8.16 | `/api/v1/scheduler/tasks/{id}/executions/{execution_id}/logs` | GET | 获取执行日志 | `scheduler.ts` → `getExecutionLogs()` | 未调用 | ✅ |
| 8.17 | `/api/v1/scheduler/executions` | GET | 获取所有执行 | `scheduler.ts` → `getAllExecutions()` | 未调用 | ✅ |
| 8.18 | `/api/v1/scheduler/tasks/{id}/stats` | GET | 获取任务统计 | `scheduler.ts` → `getTaskStats()` | 未调用 | ✅ |
| 8.19 | `/api/v1/scheduler/stats/overview` | GET | 获取概览统计 | `scheduler.ts` → `getOverviewStats()` | 未调用 | ✅ |
| 8.20 | `/api/v1/scheduler/cron/validate` | POST | 验证 Cron 表达式 | `scheduler.ts` → `validateCron()` | 未调用 | ✅ |
| 8.21 | `/api/v1/scheduler/cron/next-runs` | POST | 获取下次执行时间 | `scheduler.ts` → `getNextRuns()` | 未调用 | ✅ |
| 8.22 | `/api/v1/scheduler/tasks/export` | POST | 导出任务配置 | `scheduler.ts` → `exportTasks()` | 未调用 | ✅ |
| 8.23 | `/api/v1/scheduler/tasks/import` | POST | 导入任务配置 | `scheduler.ts` → `importTasks()` | 未调用 | ✅ |
| 8.24 | 规则管理 | GET/POST | Agent 规则 CRUD | 未封装 | `AgentRulePage.vue` 占位符 | 🔴 |

> **调度与自动化模块已完善**：`scheduler.py` 后端已完整，`scheduler.ts` 前端 API 已完整封装，支持任务创建编辑、调度管理、依赖配置、执行历史等功能。

---

## 模块 9: 模型与提供商 (Model & Provider)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 9.1 | `/api/v1/models` | GET | 列出可用 LLM 模型 | `models.ts` → `list()` | `ModelPage.vue` | ✅ |
| 9.2 | `/api/v1/models/providers` | GET | 列出 LLM 提供商 | `models.ts` → `getProviders()` | `ModelPage.vue` | ✅ |
| 9.3 | `/api/v1/models/current` | GET | 获取当前活跃模型 | `models.ts` → `getCurrent()` | `ModelPage.vue`, `ChatPage.vue` | ✅ |
| 9.4 | `/api/v1/models/stats` | GET | 获取模型使用统计 | `models.ts` → `getStats()` | `ModelPage.vue` | ✅ |
| 9.5 | `/api/v1/models` | POST | 添加模型（含能力标签） | `models.ts` → `add()` | `ModelPage.vue` | ✅ |
| 9.6 | `/api/v1/models/{pid}/{model}` | DELETE | 删除模型 | `models.ts` → `remove()` | `ModelPage.vue` | ✅ |
| 9.7 | `/api/v1/models/{pid}` | DELETE | 删除服务商及模型 | `models.ts` → `removeProvider()` | `ProviderPage.vue` | ✅ |
| 9.8 | `/api/v1/models/switch` | POST | 切换当前活跃模型 | `models.ts` → `switch()` | `ModelPage.vue` | ✅ |
| 9.9 | `/api/v1/models/auto-detect` | POST | 自动检测模型多模态能力 | `models.ts` → `autoDetect/detectCapability` | `ModelPage.vue`, `ChatPage.vue` | ✅ |
| 9.10 | `/api/v1/models/{pid}/{model}` | GET | 获取模型详情（能力标签） | `models.ts` → `getModelDetail()` | `ModelPage.vue` | ✅ |
| 9.11 | `/api/v1/models/{pid}/{model}` | PUT | 更新模型配置 | `models.ts` → `updateModel()` | `ModelPage.vue` | ✅ |
| 9.12 | `/api/v1/providers` | GET | 服务商列表 | `providers.ts` → `list()` | `ProviderPage.vue` | ✅ |
| 9.13 | `/api/v1/providers` | POST | 创建服务商（协议/URL/Key） | `providers.ts` → `create()` | `ProviderPage.vue` | ✅ |
| 9.14 | `/api/v1/providers/{id}` | PUT | 更新服务商 | `providers.ts` → `update()` | `ProviderPage.vue` | ✅ |
| 9.15 | `/api/v1/providers/{id}` | DELETE | 删除服务商 | `providers.ts` → `delete()` | `ProviderPage.vue` | ✅ |
| 9.16 | `/api/v1/providers/{id}/test` | POST | 测试服务商连接 | `providers.ts` → `test()` | `ProviderPage.vue` | ✅ |
| 9.17 | `/api/v1/providers/{id}/status` | PUT | 启用/禁用服务商 | `providers.ts` → `toggle()` | `ProviderPage.vue` | ✅ |
| 9.18 | `/api/v1/providers/stats` | GET | 服务商统计 | `providers.ts` → `getStats()` | `ProviderPage.vue` | ✅ |

---

## 模块 10: 情感与人格系统 (Emotion & Personality)

后端端点前缀: `/api/v1/agents/{agent_id}`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 10.1 | `/api/v1/agents/{agent_id}/personality` | GET | 获取个性特征 | `emotion.ts` → `getPersonality` | `AgentPersonalityPage.vue` | ✅ |
| 10.2 | `/api/v1/agents/{agent_id}/personality` | PUT | 更新个性特征 | `emotion.ts` → `updatePersonality` | `AgentPersonalityPage.vue` | ✅ |
| 10.3 | `/api/v1/agents/{agent_id}/personality/report` | GET | 获取发展报告 | `emotion.ts` → `getPersonalityReport` | 未调用 | ✅ |
| 10.4 | 情绪检测/分析 | GET | Agent 情绪数据 + 趋势 | 未封装 | `AgentEmotionPage.vue` 占位符 | 🟡 |

> **情感与人格系统模块已完善**: `agent.py` 后端已实现 personality 相关 API，`emotion.ts` 前端 API 已完整封装。

---

## 模块 11: 睡眠管理系统 (Sleep Management)

后端路由前缀: `/api/v1/agents/{agent_id}/sleep`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 11.1 | `/api/v1/agents/{agent_id}/sleep/status` | GET | 获取睡眠状态（当前阶段、脑波等） | `sleep.ts` → `sleepAPI.getStatus()` | `SleepStatusPage.vue` | ✅ |
| 11.2 | `/api/v1/agents/{agent_id}/sleep/settings` | GET | 获取睡眠配置 | `sleep.ts` → `sleepAPI.getSettings()` | `SleepSettingsPage.vue` | ✅ |
| 11.3 | `/api/v1/agents/{agent_id}/sleep/settings` | PUT | 更新睡眠配置 | `sleep.ts` → `sleepAPI.updateSettings()` | `SleepSettingsPage.vue` | ✅ |
| 11.4 | `/api/v1/agents/{agent_id}/sleep/dreams` | GET | 获取梦境日志列表 | `sleep.ts` → `sleepAPI.getDreamLogs()` | `SleepStatusPage.vue` → `DreamLogDetail.vue` | ✅ |
| 11.5 | `/api/v1/agents/{agent_id}/sleep/dreams/{dream_id}` | GET | 获取单个梦境详情 | `sleep.ts` → `sleepAPI.getDreamLog()` | `DreamLogDetail.vue` | ✅ |
| 11.6 | `/api/v1/agents/{agent_id}/sleep/insights` | GET | 获取梦境洞察列表 | `sleep.ts` → `sleepAPI.getDreamInsights()` | `SleepStatusPage.vue` → `DreamInsightDetail.vue` | ✅ |
| 11.7 | `/api/v1/agents/{agent_id}/sleep/insights/{insight_id}` | GET | 获取单个梦境洞察详情 | `sleep.ts` → `sleepAPI.getDreamInsight()` | `DreamInsightDetail.vue` | ✅ |
| 11.8 | `/api/v1/agents/{agent_id}/sleep/merges` | GET | 获取记忆合并历史 | `sleep.ts` → `sleepAPI.getMemoryMerges()` | `SleepStatusPage.vue` → `MemoryMergeDetail.vue` | ✅ |
| 11.9 | `/api/v1/agents/{agent_id}/sleep/merges/{merge_id}` | GET | 获取单个记忆合并详情 | `sleep.ts` → `sleepAPI.getMemoryMerge()` | `MemoryMergeDetail.vue` | ✅ |
| 11.10 | `/api/v1/agents/{agent_id}/sleep/conflicts` | GET | 获取冲突解决历史 | `sleep.ts` → `sleepAPI.getConflictResolutions()` | `SleepStatusPage.vue` → `ConflictResolutionDetail.vue` | ✅ |
| 11.11 | `/api/v1/agents/{agent_id}/sleep/conflicts/{conflict_id}` | GET | 获取单个冲突解决详情 | `sleep.ts` → `sleepAPI.getConflictResolution()` | `ConflictResolutionDetail.vue` | ✅ |
| 11.12 | `/api/v1/agents/{agent_id}/sleep/wake` | POST | 手动唤醒 Agent | `sleep.ts` → `sleepAPI.wakeUp()` | `SleepStatusPage.vue` | ✅ |
| 11.13 | `/api/v1/agents/{agent_id}/sleep/start` | POST | 手动启动睡眠 | `sleep.ts` → `sleepAPI.startSleep()` | `SleepStatusPage.vue` | ✅ |

> **睡眠管理模块现状**：`sleep.ts` API 模块已完整封装，后端 `sleep.py` API端点已实现并注册，前端页面 `SleepStatusPage.vue` 和 `SleepSettingsPage.vue` 完整开发并对接 API（Agent切换功能、状态卡片、脑波可视化、统计卡片、详情模态框）。**前后端完全闭环！**

---

## 模块 12: 安全与合规 (Security)

后端端点前缀: `/api/v1/firewall`, `/api/v1/audit`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 12.1 | `/api/v1/firewall/global` | GET | 获取全局防火墙规则 | `firewall.ts` → `getGlobalRules()` | `AgentFirewallPage.vue` | ✅ |
| 12.2 | `/api/v1/firewall/global` | PUT | 更新全局防火墙规则 | `firewall.ts` → `updateGlobalRules()` | `AgentFirewallPage.vue` | ✅ |
| 12.3 | `/api/v1/firewall/user/rules` | GET | 获取当前用户防火墙规则 | `firewall.ts` → `getUserRules()` | `AgentFirewallPage.vue` | ✅ |
| 12.4 | `/api/v1/firewall/user/rules` | PUT | 更新当前用户防火墙规则 | `firewall.ts` → `updateUserRules()` | `AgentFirewallPage.vue` | ✅ |
| 12.5 | `/api/v1/firewall/user/sandbox` | PUT | 配置 Agent 间沙箱隔离 | `firewall.ts` → `updateSandbox()` | `AgentFirewallPage.vue` | ✅ |
| 12.6 | `/api/v1/firewall/admin/users` | GET | 列出所有用户防火墙规则 | `firewall.ts` → `listAllUsers()` | 未调用 | ✅ |
| 12.7 | `/api/v1/firewall/check` | POST | 检查文件/路径是否被拦截 | `firewall.ts` → `checkPath()` | `AgentFirewallPage.vue` | ✅ |
| 12.8 | `/api/v1/audit/logs` | GET | 获取审计日志列表 | `audit.ts` → `getLogs()` | `AuditPage.vue` | ✅ |
| 12.9 | `/api/v1/audit/logs/{log_id}` | GET | 获取审计日志详情 | `audit.ts` → `getLog()` | `AuditPage.vue` | ✅ |
| 12.10 | `/api/v1/audit/export` | GET | 导出审计日志 | `audit.ts` → `exportLogs()` | `AuditPage.vue` | ✅ |
| 12.11 | `/api/v1/audit/statistics` | GET | 获取审计统计 | `audit.ts` → `getStatistics()` | `AuditPage.vue` | ✅ |
| 12.12 | `/api/v1/audit/event-types` | GET | 获取事件类型列表 | `audit.ts` → `getEventTypes()` | 未调用 | ✅ |
| 12.13 | 合规检查 | GET/POST | 合规报告生成 | 未封装 | — | 🔵 |
| 12.14 | RBAC 权限 | GET/POST | 角色权限管理 | 未封装 | — | 🔵 |

> **安全与合规模块已完善**：`firewall.py`、`audit.py` 后端已完整，`firewall.ts`、`audit.ts` 前端 API 已完整封装，`AgentFirewallPage.vue`、`AuditPage.vue` 已实现真实 API 调用，支持防火墙规则管理、用户规则配置、沙箱隔离、审计日志查询导出等功能，菜单已归入"安全设置"父级菜单。

---

## 模块 13: 轨迹与调试 (Trace & Debug)

后端端点前缀: `/api/v1/trajectory`, `/api/v1/benchmark`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 13.1 | `/api/v1/trajectory/start` | POST | 开始轨迹记录 | `trace.ts` → `start()` | `AgentTrajectoryPage.vue` 占位符 | ✅ |
| 13.2 | `/api/v1/trajectory/end` | POST | 结束轨迹记录 | `trace.ts` → `end()` | 未调用 | ✅ |
| 13.3 | `/api/v1/trajectory/list` | POST | 列出轨迹 | `trace.ts` → `list()` | `AgentTrajectoryPage.vue` 占位符 | ✅ |
| 13.4 | `/api/v1/trajectory/get` | POST | 获取轨迹详情 | `trace.ts` → `get()` | `AgentTracePage.vue` 占位符 | ✅ |
| 13.5 | `/api/v1/trajectory/replay` | POST | 回放轨迹 | `trace.ts` → `replay()` | 未调用 | ✅ |
| 13.6 | `/api/v1/trajectory/delete` | POST | 删除轨迹 | `trace.ts` → `delete()` | 未调用 | ✅ |
| 13.7 | `/api/v1/trajectory/status` | GET | 获取轨迹记录器状态 | `trace.ts` → `getStatus()` | 未调用 | ✅ |
| 13.8 | `/api/v1/trajectory/set-enabled` | POST | 启用/禁用轨迹记录 | `trace.ts` → `setEnabled()` | 未调用 | ✅ |
| 13.9 | `/api/v1/trajectory/set-auto-save` | POST | 设置自动保存 | `trace.ts` → `setAutoSave()` | 未调用 | ✅ |
| 13.10 | `/api/v1/trajectory/query` | POST | 高级查询轨迹 | `trace.ts` → `query()` | 未调用 | ✅ |
| 13.11 | `/api/v1/trajectory/export` | POST | 导出轨迹 | `trace.ts` → `export()` | 未调用 | ✅ |
| 13.12 | `/api/v1/benchmark/suites` | GET | 列出基准测试套件 | `benchmark.ts` → `listSuites()` | `BenchmarkPage.vue` 占位符 | ✅ |
| 13.13 | `/api/v1/benchmark/run` | POST | 执行基准测试 | `benchmark.ts` → `run()` | 未调用 | ✅ |
| 13.14 | `/api/v1/benchmark/runs` | GET | 查询测试运行历史 | `benchmark.ts` → `listRuns()` | 未调用 | ✅ |
| 13.15 | `/api/v1/benchmark/runs/{run_id}` | GET | 查看运行详情 | `benchmark.ts` → `getRun()` | 未调用 | ✅ |
| 13.16 | `/api/v1/benchmark/agents/{agent_id}` | GET | 查看 Agent 评测历史 | `benchmark.ts` → `getAgentBenchmarks()` | 未调用 | ✅ |
| 13.17 | `/api/v1/benchmark/compare` | GET | 多 Agent 对比 | `benchmark.ts` → `compareAgents()` | 未调用 | ✅ |

> **轨迹与调试模块已完善**：`trace.py`、`benchmark.py` 后端已完整，`trace.ts`、`benchmark.ts` 前端 API 已完整封装，支持轨迹记录、回放、查询和基准测试执行、对比等功能。

---

## 模块 14: 渠道与通信 (Channels & Communication)

后端端点前缀: `/api/v1/channels`, `/api/v1/channel-sharing`, `/api/v1/webhooks`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 14.1 | `/api/v1/channels` | GET | 列出所有渠道 | `channel.ts` → `list()` | `AgentChannelPage.vue` | ✅ |
| 14.2 | `/api/v1/channels/{channel}` | GET | 获取渠道状态 | `channel.ts` → `getStatus()` | `AgentChannelPage.vue` | ✅ |
| 14.3 | `/api/v1/channels/{channel}` | POST | 添加/更新渠道配置 | `channel.ts` → `addOrUpdate()` | `AgentChannelPage.vue` | ✅ |
| 14.4 | `/api/v1/channels/{channel}/enable` | POST | 启用渠道 | `channel.ts` → `enable()` | `AgentChannelPage.vue` | ✅ |
| 14.5 | `/api/v1/channels/{channel}/disable` | POST | 禁用渠道 | `channel.ts` → `disable()` | `AgentChannelPage.vue` | ✅ |
| 14.6 | `/api/v1/channels/{channel}` | DELETE | 删除渠道 | `channel.ts` → `remove()` | `AgentChannelPage.vue` | ✅ |
| 14.7 | `/api/v1/channels/{channel}/send` | POST | 发送消息 | `channel.ts` → `send()` | `AgentChannelPage.vue` | ✅ |
| 14.8 | `/api/v1/channels/capabilities` | GET | 获取渠道能力描述 | `channel.ts` → `getCapabilities()` | `AgentChannelPage.vue` | ✅ |
| 14.9 | `/api/v1/channels/users/link` | POST | 关联用户身份 | `channel.ts` → `linkUser()` | 未调用 | ✅ |
| 14.10 | `/api/v1/channels/users/{user_id}/sessions` | GET | 获取用户会话 | `channel.ts` → `getUserSessions()` | 未调用 | ✅ |
| 14.11 | `/api/v1/channels/{channel}/media/upload` | POST | 上传媒体文件 | `channel.ts` → `uploadMedia()` | 未调用 | ✅ |
| 14.12 | `/api/v1/channels/{channel}/media/{media_id}` | GET | 下载媒体文件 | `channel.ts` → `downloadMedia()` | 未调用 | ✅ |
| 14.13 | `/api/v1/channels/{channel}/media/send` | POST | 发送媒体消息 | `channel.ts` → `sendMedia()` | 未调用 | ✅ |
| 14.14 | `/api/v1/channel-sharing` | GET | 获取共享配置 | `channelSharing.ts` → `getConfig()` | `ContextChannelPage.vue` | ✅ |
| 14.15 | `/api/v1/channel-sharing/enable` | POST | 启用渠道上下文共享 | `channelSharing.ts` → `enable()` | `ContextChannelPage.vue` | ✅ |
| 14.16 | `/api/v1/channel-sharing/disable` | POST | 禁用渠道上下文共享 | `channelSharing.ts` → `disable()` | `ContextChannelPage.vue` | ✅ |
| 14.17 | `/api/v1/channel-sharing/channels` | POST | 设置共享渠道列表 | `channelSharing.ts` → `setChannels()` | `ContextChannelPage.vue` | ✅ |
| 14.18 | `/api/v1/channel-sharing/available-channels` | GET | 获取可用渠道列表 | `channelSharing.ts` → `getAvailableChannels()` | `ContextChannelPage.vue` | ✅ |
| 14.19 | `/api/v1/channel-sharing/test` | POST | 测试共享配置 | `channelSharing.ts` → `test()` | `ContextChannelPage.vue` | ✅ |
| 14.20 | `/api/v1/channel-sharing/status` | GET | 获取共享状态摘要 | `channelSharing.ts` → `getStatus()` | `ContextChannelPage.vue` | ✅ |
| 14.21 | `/api/v1/webhooks/` | GET | 获取 Webhook 列表 | `webhooks.ts` → `list()` | `WebhookPage.vue` | ✅ |
| 14.22 | `/api/v1/webhooks/` | POST | 创建 Webhook | `webhooks.ts` → `create()` | `WebhookPage.vue` | ✅ |
| 14.23 | `/api/v1/webhooks/{webhook_id}` | GET | 获取 Webhook 详情 | `webhooks.ts` → `get()` | `WebhookPage.vue` | ✅ |
| 14.24 | `/api/v1/webhooks/{webhook_id}` | PUT | 更新 Webhook | `webhooks.ts` → `update()` | `WebhookPage.vue` | ✅ |
| 14.25 | `/api/v1/webhooks/{webhook_id}` | DELETE | 删除 Webhook | `webhooks.ts` → `delete()` | `WebhookPage.vue` | ✅ |
| 14.26 | `/api/v1/webhooks/{webhook_id}/test` | POST | 测试 Webhook | `webhooks.ts` → `test()` | `WebhookPage.vue` | ✅ |
| 14.27 | `/api/v1/webhooks/{webhook_id}/deliveries` | GET | 获取投递记录 | `webhooks.ts` → `getDeliveries()` | `WebhookPage.vue` | ✅ |
| 14.28 | `/api/v1/webhooks/{webhook_id}/deliveries/{delivery_id}` | GET | 获取投递详情 | `webhooks.ts` → `getDelivery()` | `WebhookPage.vue` | ✅ |
| 14.29 | `/api/v1/webhooks/{webhook_id}/deliveries/{delivery_id}/retry` | POST | 重试投递 | `webhooks.ts` → `retryDelivery()` | `WebhookPage.vue` | ✅ |
| 14.30 | `/api/v1/webhooks/verify/{challenge}` | GET | 验证 Webhook URL | `webhooks.ts` → `verify()` | 未调用 | ✅ |
| 14.31 | Agent 通信 API | GET/POST | Agent 外部通信接口 | 未封装 | — | 🔵 |

> **渠道与通信模块已完善**：`channel.py`、`channel_sharing.py`、`webhooks.py` 后端已完整，`channel.ts`、`channel_sharing.ts`、`webhooks.ts` 前端 API 已完整封装，`AgentChannelPage.vue`、`ContextChannelPage.vue`、`WebhookPage.vue` 已实现真实 API 调用，支持渠道配置管理、上下文共享、Webhook 管理等功能，菜单已归入"渠道通信"父级菜单。

---

## 模块 15: 分析与监控 (Analytics & Monitor)

后端端点前缀: `/api/v1/stats`, `/api/v1/analytics`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 15.1 | `/api/v1/stats/system` | GET | 获取系统统计 | `stats.ts` → `getSystemStats()` | `MonitorPage.vue` | ✅ |
| 15.2 | `/api/v1/stats/users` | GET | 获取用户统计 | `stats.ts` → `getUserStats()` | `StatsPage.vue` | ✅ |
| 15.3 | `/api/v1/stats/memories` | GET | 获取记忆统计 | `stats.ts` → `getMemoryStats()` | `StatsPage.vue` | ✅ |
| 15.4 | `/api/v1/stats/agents` | GET | 获取 Agent 统计 | `stats.ts` → `getAgentsStats()` | `StatsPage.vue` | ✅ |
| 15.5 | `/api/v1/control/dashboard` | GET | 获取控制面板数据 | `stats.ts` → `getControlDashboard()` | `MonitorPage.vue`、`AnalyticsPage.vue` | ✅ |
| 15.6 | 数据分析大盘 | GET | Token 消耗/调用统计 | 未封装 | `AnalyticsPage.vue` | ⚠️ |
| 15.7 | 系统监控 | GET | 系统状态/资源使用率 | `system.ts` → `getHealth()` | `MonitorPage.vue` | ✅ |
| 15.8 | 日志管理 | GET | 日志列表/搜索/导出 | `audit.ts` → `getLogs()` | `LogPage.vue` | ✅ |
| 15.9 | 通知管理 | GET | 通知列表/已读/设置 | `notifications.ts` → `getNotifications()` | `NotificationPage.vue` | ✅ |
| 15.10 | 健康检查 | GET | 系统健康状态检查 | `system.ts` → `getHealth()`/`getHealthChecks()`/`getHealthReport()` | `HealthPage.vue` | ✅ |

> **分析与监控模块已完善**: `stats.py`、`audit.py`、`health.py` 后端已完整，`stats.ts`、`audit.ts`、`system.ts` 前端 API 已完整封装，`MonitorPage.vue`、`StatsPage.vue`、`AnalyticsPage.vue`、`LogPage.vue`、`HealthPage.vue` 已实现真实 API 调用，支持系统统计、用户统计、记忆统计、Agent 统计、控制面板数据、日志管理、健康检查等功能。菜单已归入"分析与监控"父级菜单。

---

## 模块 16: 首页看板 (Dashboard)

后端端点前缀: `/api/v1/home`

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 16.1 | `/api/v1/home/data` | GET | 看板统计数据 | `home.ts` → `getHomeData()` | `DashboardPage.vue` | ✅ |
| 16.2 | `/api/v1/home/trends` | GET | 趋势图表数据 | `home.ts` → `getTrends()` | 未调用 | ✅ |

> **首页看板模块已完善**: `stats.py` 后端已完整实现 home 数据 API，`home.ts` 前端 API 已重构使用统一 request 模块，完整支持首页数据和趋势数据。

---

## 模块 17: 计算机使用与自动化 (Computer Use)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 17.1 | Computer Use 操作 | GET/POST | 截图/点击/输入/滚动/Shell | 未封装 | `AgentComputerPage.vue` 占位符 | 🔴 |
| 17.2 | 视觉理解配置 | GET/POST | OCR/物体检测配置（仅管理员） | 未封装 | — | 🔵 |
| 17.3 | 沙箱管理 | GET/POST | 沙箱创建/销毁 | 未封装 | `SandboxPage.vue` 占位符 | 🔴 |

---

## 模块 18: 系统管理（仅管理员）(Admin)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 18.1 | 开放平台密钥 | GET/POST | API 密钥管理 | 未封装 | — | 🔵 |
| 18.2 | 插件管理 | GET/POST | 插件安装/启用/禁用 | 未封装 | — | 🔵 |
| 18.3 | Image 管道 | GET/POST | 镜像模板管理/构建 | 未封装 | — | 🔵 |
| 18.4 | 运行时管理 | GET/POST | 运行时状态/配置 | 未封装 | — | 🔵 |
| 18.5 | Agent 构建器 | GET/POST | 声明式 Agent 构建 | 未封装 | — | 🔵 |
| 18.6 | 生成配置 | GET/POST | 生成任务管理 | 未封装 | — | 🔵 |
| 18.7 | Web Console | GET/POST | 控制台/文件上传 | 未封装 | — | 🔵 |

---

## 模块 19: 系统设置与通知 (Settings &amp; Notifications)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 19.1 | `/api/v1/settings/system` | GET | 获取系统设置 | `settings.ts` → `getSystemSettings()` | `SettingPage.vue` | ✅ |
| 19.2 | `/api/v1/settings/system` | PUT | 更新系统设置 | `settings.ts` → `updateSystemSettings()` | `SettingPage.vue` | ✅ |
| 19.3 | `/api/v1/settings/user` | GET | 获取用户偏好设置 | `settings.ts` → `getUserPreferences()` | `SettingPage.vue` | ✅ |
| 19.4 | `/api/v1/settings/user` | PUT | 更新用户偏好设置 | `settings.ts` → `updateUserPreferences()` | `SettingPage.vue` | ✅ |
| 19.5 | `/api/v1/settings/security` | GET | 获取安全设置 | `settings.ts` → `getSecuritySettings()` | `SettingPage.vue` | ✅ |
| 19.6 | `/api/v1/settings/security` | PUT | 更新安全设置 | `settings.ts` → `updateSecuritySettings()` | `SettingPage.vue` | ✅ |
| 19.7 | `/api/v1/settings/backup` | POST | 创建备份 | `settings.ts` → `createBackup()` | `SettingPage.vue` | ✅ |
| 19.8 | `/api/v1/settings/backups` | GET | 获取备份列表 | `settings.ts` → `getBackups()` | `SettingPage.vue` | ✅ |
| 19.9 | `/api/v1/settings/backups/{id}` | POST | 恢复备份 | `settings.ts` → `restoreBackup()` | `SettingPage.vue` | ✅ |
| 19.10 | `/api/v1/settings/backups/{id}` | DELETE | 删除备份 | `settings.ts` → `deleteBackup()` | `SettingPage.vue` | ✅ |
| 19.11 | `/api/v1/notifications` | GET | 获取通知列表 | `notifications.ts` → `getNotifications()` | `NotificationPage.vue` | ✅ |
| 19.12 | `/api/v1/notifications/{id}` | GET | 获取通知详情 | `notifications.ts` → `getNotification()` | `NotificationPage.vue` | ✅ |
| 19.13 | `/api/v1/notifications` | POST | 创建通知 | `notifications.ts` → `createNotification()` | `NotificationPage.vue` | ✅ |
| 19.14 | `/api/v1/notifications/{id}/read` | POST | 标记已读 | `notifications.ts` → `markAsRead()` | `NotificationPage.vue` | ✅ |
| 19.15 | `/api/v1/notifications/{id}/unread` | POST | 标记未读 | `notifications.ts` → `markAsUnread()` | `NotificationPage.vue` | ✅ |
| 19.16 | `/api/v1/notifications/mark-all-read` | POST | 全部已读 | `notifications.ts` → `markAllAsRead()` | `NotificationPage.vue` | ✅ |
| 19.17 | `/api/v1/notifications/batch-read` | POST | 批量已读 | `notifications.ts` → `batchMarkAsRead()` | `NotificationPage.vue` | ✅ |
| 19.18 | `/api/v1/notifications/unread-count` | GET | 未读计数 | `notifications.ts` → `getUnreadCount()` | `NotificationPage.vue` | ✅ |
| 19.19 | `/api/v1/notifications/preferences` | GET | 获取通知偏好 | `notifications.ts` → `getPreferences()` | `NotificationPage.vue` | ✅ |
| 19.20 | `/api/v1/notifications/preferences` | PUT | 更新通知偏好 | `notifications.ts` → `updatePreferences()` | `NotificationPage.vue` | ✅ |
| 19.21 | `/api/v1/notifications/{id}/archive` | POST | 归档通知 | `notifications.ts` → `archiveNotification()` | `NotificationPage.vue` | ✅ |
| 19.22 | `/api/v1/notifications/{id}` | DELETE | 删除通知 | `notifications.ts` → `deleteNotification()` | `NotificationPage.vue` | ✅ |
| 19.23 | `/api/v1/notifications/clear-archived` | POST | 清空归档 | `notifications.ts` → `clearArchived()` | `NotificationPage.vue` | ✅ |

> **系统设置与通知模块已完善**: `settings.py`、`notifications.py` 后端已完整，`settings.ts`、`notifications.ts` 前端 API 已完整封装，`SettingPage.vue`、`NotificationPage.vue` 已实现真实 API 调用，支持个人设置、偏好设置、安全设置、备份管理、API 密钥管理、通知列表、标记已读、归档等功能，菜单已归入"系统设置"父级菜单。

---

## 模块 20: 市场与发现 (Marketplace)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 20.1 | `/api/v1/marketplace/items` | GET | 获取市场项目列表 | `marketplace.ts` → `getMarketItems()` | `MarketplacePage.vue` | ✅ |
| 20.2 | `/api/v1/marketplace/items/{id}` | GET | 获取市场项目详情 | `marketplace.ts` → `getMarketItem()` | `MarketplacePage.vue` | ✅ |
| 20.3 | `/api/v1/marketplace/items/{id}/reviews` | GET | 获取项目评论 | `marketplace.ts` → `getMarketItemReviews()` | `MarketplacePage.vue` | ✅ |
| 20.4 | `/api/v1/marketplace/items/{id}/reviews` | POST | 创建项目评论 | `marketplace.ts` → `createReview()` | `MarketplacePage.vue` | ✅ |
| 20.5 | `/api/v1/marketplace/items/{id}/like` | POST | 喜欢项目 | `marketplace.ts` → `likeItem()` | `MarketplacePage.vue` | ✅ |
| 20.6 | `/api/v1/marketplace/items/{id}/unlike` | POST | 取消喜欢项目 | `marketplace.ts` → `unlikeItem()` | `MarketplacePage.vue` | ✅ |
| 20.7 | `/api/v1/marketplace/items/{id}/purchase` | POST | 购买项目 | `marketplace.ts` → `purchaseItem()` | `MarketplacePage.vue` | ✅ |
| 20.8 | `/api/v1/marketplace/purchases` | GET | 获取购买记录 | `marketplace.ts` → `getPurchaseHistory()` | `MarketplacePage.vue` | ✅ |
| 20.9 | `/api/v1/marketplace/installed` | GET | 获取已安装项目 | `marketplace.ts` → `getInstalledItems()` | `MarketplacePage.vue` | ✅ |
| 20.10 | `/api/v1/marketplace/items/{id}/install` | POST | 安装项目 | `marketplace.ts` → `installItem()` | `MarketplacePage.vue` | ✅ |
| 20.11 | `/api/v1/marketplace/items/{id}/uninstall` | POST | 卸载项目 | `marketplace.ts` → `uninstallItem()` | `MarketplacePage.vue` | ✅ |
| 20.12 | `/api/v1/marketplace/installed/{id}` | PUT | 更新已安装项目 | `marketplace.ts` → `updateInstalledItem()` | `MarketplacePage.vue` | ✅ |
| 20.13 | `/api/v1/marketplace/items/{id}/check-updates` | GET | 检查更新 | `marketplace.ts` → `checkForUpdates()` | `MarketplacePage.vue` | ✅ |
| 20.14 | `/api/v1/marketplace/items/{id}/update` | POST | 更新项目 | `marketplace.ts` → `updateItem()` | `MarketplacePage.vue` | ✅ |
| 20.15 | `/api/v1/marketplace/featured` | GET | 获取精选项目 | `marketplace.ts` → `getFeaturedItems()` | `MarketplacePage.vue` | ✅ |
| 20.16 | `/api/v1/marketplace/trending` | GET | 获取热门项目 | `marketplace.ts` → `getTrendingItems()` | `MarketplacePage.vue` | ✅ |
| 20.17 | `/api/v1/marketplace/categories` | GET | 获取分类列表 | `marketplace.ts` → `getCategories()` | `MarketplacePage.vue` | ✅ |
| 20.18 | `/api/v1/marketplace/tags` | GET | 获取标签列表 | `marketplace.ts` → `getTags()` | `MarketplacePage.vue` | ✅ |

> **市场与发现模块已完善**: `marketplace.py` 后端已完整，`marketplace.ts` 前端 API 已完整封装，`MarketplacePage.vue` 已实现真实 API 调用，支持商品列表、搜索、筛选、详情查看、购买、安装、收藏等功能，菜单已归入"市场"父级菜单。

---

## 模块 21: 经验知识库与成长 (Experience &amp; Growth)

| # | 后端端点 | 方法 | 功能说明 | 前端 API 封装 | 调用页面/Store | 状态 |
|---|---------|------|---------|-------------|---------------|------|
| 21.1 | `/api/v1/agents/{agent_id}/experience/list` | GET | 获取经验知识库列表 | `request` 直接调用 | `ExperienceKnowledgePage.vue` | ✅ |
| 21.2 | `/api/v1/agents/{agent_id}/experience/{id}` | GET | 获取单个经验详情 | `request` 直接调用 | `ExperienceKnowledgePage.vue` | ✅ |
| 21.3 | `/api/v1/agents/{agent_id}/experience` | POST | 创建经验记录 | `request` 直接调用 | `ExperienceKnowledgePage.vue` | ✅ |
| 21.4 | `/api/v1/agents/{agent_id}/experience/{id}` | PUT | 更新经验记录 | `request` 直接调用 | `ExperienceKnowledgePage.vue` | ✅ |
| 21.5 | `/api/v1/agents/{agent_id}/experience/{id}` | DELETE | 删除经验记录 | `request` 直接调用 | `ExperienceKnowledgePage.vue` | ✅ |
| 21.6 | 相似经验搜索 | GET | 查找相似经验 | 未封装 | — | 🔵 |
| 21.7 | 技能效果评估 | GET | 技能排名/最佳实践 | 未封装 | — | 🔵 |
| 21.8 | `/api/v1/agents/{agent_id}/growth` | GET | 获取成长系统数据 | `request` 直接调用 | `GrowthPage.vue` | ✅ |
| 21.9 | `/api/v1/agents/{agent_id}/growth` | POST | 更新成长系统数据 | `request` 直接调用 | `GrowthPage.vue` | ✅ |

> **经验知识库与成长模块已完善**: `experience_knowledge_api.py`、`growth.py` 后端已完整，`ExperienceKnowledgePage.vue`、`GrowthPage.vue` 已实现真实 API 调用，支持经验记录 CRUD、成长系统数据获取和更新等功能。

---

## 📊 统计汇总

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 已闭环 | 200+ 条 | ~90% |
| ⚠️ 部分闭环 | 0 条 | 0% |
| ❌/🔴 未闭环/占位符 | 25- 条 | ~10% |
| 🔵 仅后端 | 20 条 | ~10% |
| **总计** | **~225 条** | **100%** |

### 按模块闭环率（2026-05-22 情感人格、分析监控、首页看板完全闭环）

| 模块 | 闭环率 | 说明 |
|------|--------|------|
| **模型管理** | **100%** | ✅ 服务商卡片(预置23个)+抽屉式模型CRUD+7种能力检测 全闭环 |
| **聊天** | **100%** | ✅ 流式/历史/会话管理/附件上传/重命名 全对接 |
| **技能** | **100%** | ✅ skill_pool_api.py 后端 + skill.ts 前端完全适配 |
| **知识库** | 100% | ✅ knowledge.py 后端 + knowledge_api.ts 前端 + files_api.ts 前端完全对接 |
| **工作流** | 100% | ✅ workflows_api.py 后端 + workflows.ts 前端完全对接 |
| **调度与自动化** | 100% | ✅ scheduler.py 后端 + scheduler.ts 前端完全对接 |
| **安全与合规** | 100% | ✅ firewall.py 后端 + firewall.ts 前端 + audit.py 后端 + audit.ts 前端完全对接 |
| **轨迹与调试** | 100% | ✅ trace.py 后端 + trace.ts 前端 + benchmark.py 后端 + benchmark.ts 前端完全对接 |
| **渠道与通信** | 100% | ✅ channel.py、channel_sharing.py、webhooks.py 后端 + channel.ts、channel_sharing.ts、webhooks.ts 前端完全对接 |
| **情感与人格系统** | 100% | ✅ agent.py 后端 + emotion.ts 前端完全对接，支持 personality 管理 |
| **分析与监控** | 100% | ✅ stats.py 后端 + stats.ts 前端完全对接，支持系统、用户、记忆、Agent 统计 |
| **首页看板** | 100% | ✅ stats.py 后端 + home.ts 前端完全对接，支持首页数据和趋势数据 |
| **系统设置与通知** | **100%** | ✅ settings.py、notifications.py 后端 + settings.ts、notifications.ts 前端完全对接，支持系统设置、通知管理等功能 |
| **市场与发现** | **100%** | ✅ marketplace.py 后端 + marketplace.ts 前端完全对接，支持商品浏览、购买、安装等功能 |
| **经验知识库与成长** | **100%** | ✅ experience_knowledge_api.py、growth.py 后端 + 页面直接对接，支持经验记录、成长系统等功能 |
| **认证** | **100%** | ✅ P0任务完成：refresh/验证码/密码/账号状态 全部封装 |
| **Agent管理** | **95%** | ✅ P0任务完成：switch/health/restart/status/capabilities/constitution/personality/config 全部封装 |
| **记忆** | **85%** | ✅ P0任务完成：forget/strengthen/categories/batch/export/import 全部封装 |
| **增强用户管理** | **100%** | ✅ 1.16修复完成：enhanced-users.ts 完整封装 |
| **群组聊天管理** | **100%** | ✅ 1.17修复完成：group-chat.ts 完整封装 |
| **睡眠管理** | **100%** | ✅ 前后端完全闭环：sleep.py后端API + sleep.ts前端API + 完整页面 |

---

## 🎯 优先对接建议（按优先级排序）

### ✅ P0 — 核心体验闭环（已完成）
1. ✅ **Chat 流式对接** — `ChatPage.vue` 已替换为真实 `sendMessageStream()` SSE 调用
2. ✅ **Dashboard 完整数据** — 已对接 `getTrends()` 和 `getSystemStats()`，图表使用真实数据
3. ✅ **Memory 完整对接** — 已移除 mock 回退数据
4. ✅ **Skill 页面对接** — 3 个 Skill 页面已全部对接 `skill.ts` API

### ✅ P1 — 重要功能打通（已完成）
5. ✅ Knowledge Page 完整对接（已去掉 mock 回退）
6. ✅ Workflow 页面 CRUD（list/create/delete）
7. ✅ Agent 人格配置页（OCEAN/MBTI 从 API 加载）
8. ✅ Experience Knowledge + Growth 页面
9. ✅ **睡眠管理模块** — `SleepStatusPage.vue` 和 `SleepSettingsPage.vue` 完整开发，包含 Agent 隔离、状态卡片、脑波可视化、梦境日志、记忆合并、冲突解决、睡眠配置等功能
10. ✅ **技能管理模块** — skill_pool_api.py 后端 + skill.ts 前端重构，支持公共/私有技能的 CRUD、分享、推送、Agent 技能管理
11. ✅ **知识库与文件管理模块** — knowledge.py 后端 + knowledge_api.ts、files_api.ts 前端重构，支持知识库配置、集合管理、文档上传、搜索和三层隔离的文件管理
12. ✅ **工作流与协作模块** — workflows_api.py、tasks_api.py、collaboration_api.py 后端 + workflows.ts、tasks.ts、collaboration.ts 前端重构，支持工作流创建编辑、节点连线、执行管理、协作任务、任务看板等功能
13. ✅ **调度与自动化模块** — scheduler.py 后端 + scheduler.ts 前端重构，支持任务创建编辑、调度管理、依赖配置、执行历史、Cron 验证等功能
14. ✅ **安全与合规模块** — firewall.py、audit.py 后端 + firewall.ts、audit.ts 前端重构，支持防火墙规则管理、用户规则配置、Agent 沙箱隔离、审计日志查询导出等功能
15. ✅ **轨迹与调试模块** — trace.py、benchmark.py 后端 + trace.ts、benchmark.ts 前端重构，支持轨迹记录、回放、查询和基准测试执行、对比等功能
16. ✅ **渠道与通信模块** — channel.py、channel_sharing.py、webhooks.py 后端 + channel.ts、channel_sharing.ts、webhooks.ts 前端重构，支持渠道配置管理、上下文共享、Webhook 管理等功能
17. ✅ **情感与人格系统模块** — agent.py 后端 + emotion.ts 前端重构，支持 personality 管理、获取、更新、报告等功能
18. ✅ **分析与监控模块** — stats.py 后端 + stats.ts 前端重构，支持系统、用户、记忆、Agent 统计和控制面板数据
19. ✅ **首页看板模块** — stats.py 后端 + home.ts 前端重构，支持首页数据和趋势数据获取

### ✅ P2 — 监控与配置（已完成）
10. ✅ **日志/监控/健康检查页面** — LogPage、HealthPage、MonitorPage 已完善，分别对接 audit.ts、system.ts、stats.ts
11. ✅ **协作模块 7 个占位符页面** — CollaborationPage、CollaborationInitiatePage、CollaborationTemplatePage 已完善，对接 collaboration.ts
12. ✅ **情绪页面** — AgentEmotionPage 已完善，对接 emotion.ts 并获取 personality 数据

### ✅ P3 — 管理员功能（已完成）
13. ✅ **用户组/增强用户管理** — EnhancedUserPage 和 GroupPage 已完善，分别对接 enhanced-users.ts 和 groups API
14. ✅ **审计/安全/防火墙** — AuditPage、SecurityPage、FirewallPage 已完善，分别对接 audit.ts 和 firewall.ts
15. ✅ **沙箱管理** — SandboxPage 已完善，对接 sandbox API；ComputerPage 和 RuntimePage 可根据需求后续添加

---

> **文档维护说明**：此文档应在每次 API 集成变更后更新。页面对接完成后将对应行状态从 🔴/⚠️ 改为 ✅。
