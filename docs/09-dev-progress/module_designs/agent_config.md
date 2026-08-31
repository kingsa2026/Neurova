# Agent 配置页面模块设计文档

**模块名称**: Agent 配置页面  
**负责人**: frontend-agent-dev  
**设计时间**: 2026-05-12  
**最后更新**: 2026-05-12 23:59  

## 1. 模块概述

Agent 配置页面是 Neurova Web Console 的重要组成部分，提供用户配置 Agent 行为、管理技能、工具和工区的界面。

### 1.1 功能范围

- Agent 配置管理（语言、时区、模型选择等）
- 技能管理（创建、编辑、删除、启用/禁用、导入、导出）
- 工具管理（启用/禁用、测试、MCP 配置、ToolGuard 配置）
- 工作区管理（文件浏览、编辑、上传、下载）

### 1.2 技术栈

- **框架**: React 18 + TypeScript
- **UI 组件库**: Ant Design 5.x
- **状态管理**: Zustand
- **路由**: React Router 7.x
- **构建工具**: Vite 6.x
- **测试框架**: Vitest + Testing Library
- **国际化**: react-i18next

## 2. 架构设计

### 2.1 目录结构

```
neurova-ui/src/
├── pages/
│   └── Agent/
│       ├── index.tsx                    # 模块导出
│       ├── Config/                      # 配置管理页面
│       │   ├── AgentConfigPage.tsx      # 主配置页面
│       │   ├── ReactAgentConfig.tsx     # React Agent 配置
│       │   ├── LLMRetryConfig.tsx      # LLM 重试配置
│       │   ├── ToolCallLevel.tsx        # 工具调用级别配置
│       │   ├── ContextManager.tsx       # 上下文管理器配置
│       │   └── AgentConfigPage.test.tsx
│       ├── Skills/                     # 技能管理页面
│       │   ├── SkillsPage.tsx          # 技能列表页面
│       │   ├── SkillEditor.tsx         # 技能编辑器
│       │   ├── SkillImporter.tsx      # 技能导入组件
│       │   ├── SkillConflictDetector.tsx # 技能冲突检测
│       │   ├── SkillVisualizer.tsx     # 技能可视化
│       │   └── SkillsPage.test.tsx
│       ├── Tools/                      # 工具管理页面
│       │   ├── ToolsPage.tsx           # 工具列表页面
│       │   ├── MCPConfig.tsx           # MCP 配置界面
│       │   ├── ToolGuardConfig.tsx     # ToolGuard 配置
│       │   ├── ToolTest.tsx            # 工具测试界面
│       │   └── ToolsPage.test.tsx
│       └── Workspace/                  # 工作区管理页面
│           ├── WorkspacePage.tsx       # 工作区管理页面
│           ├── FileEditor.tsx          # 文件编辑器
│           ├── FileBrowser.tsx         # 文件浏览器
│           ├── FileUpload.tsx         # 文件上传组件
│           └── WorkspacePage.test.tsx
├── api/                              # API 模块
│   ├── config.ts                     # API 配置
│   ├── request.ts                    # 请求封装
│   ├── authHeaders.ts                # 认证头处理
│   ├── index.ts                     # API 模块导出
│   └── modules/
│       ├── skill.ts                  # Skill API
│       ├── provider.ts               # Provider API
│       ├── workspace.ts              # Workspace API
│       ├── tools.ts                  # Tools API
│       ├── agent.ts                  # Agent API
│       └── skill.test.ts            # Skill API 测试
├── stores/                          # 状态管理
│   ├── agentStore.ts                # Agent 状态管理
│   ├── providerStore.ts             # Provider 状态管理
│   ├── settingsStore.ts             # Settings 状态管理
│   ├── index.ts                    # Store 模块导出
│   └── agentStore.test.ts          # Agent Store 测试
└── types/                          # 类型定义
    ├── skill.ts                     # Skill 类型
    ├── agent.ts                     # Agent 类型
    ├── workspace.ts                 # Workspace 类型
    ├── tools.ts                     # Tools 类型
    ├── provider.ts                  # Provider 类型
    └── index.ts                    # 类型定义导出
```

### 2.2 组件层次结构

```
AgentConfigPage (主配置页面)
├── ReactAgentConfig (React Agent 配置)
├── LLMRetryConfig (LLM 重试配置)
├── ToolCallLevel (工具调用级别配置)
└── ContextManager (上下文管理器配置)

SkillsPage (技能列表页面)
├── SkillEditor (技能编辑器)
├── SkillImporter (技能导入组件)
├── SkillConflictDetector (技能冲突检测)
└── SkillVisualizer (技能可视化)

ToolsPage (工具列表页面)
├── MCPConfig (MCP 配置界面)
├── ToolGuardConfig (ToolGuard 配置)
└── ToolTest (工具测试界面)

WorkspacePage (工作区管理页面)
├── FileEditor (文件编辑器)
├── FileBrowser (文件浏览器)
└── FileUpload (文件上传组件)
```

### 2.3 数据流

```
用户操作 → 组件 → Store (Zustand) → API 模块 → 后端 API
                ↓
            状态更新 → 组件重新渲染
```

## 3. 详细设计

### 3.1 Agent Config 页面

#### 3.1.1 AgentConfigPage 组件

**功能**: 主配置页面，包含多个配置选项卡

**状态**:
- `activeTab`: 当前激活的选项卡
- `form`: Form 实例
- `loading`: 加载状态
- `saving`: 保存状态
- `error`: 错误信息

**方法**:
- `handleSave()`: 保存配置
- `handleReset()`: 重置配置

**选项卡**:
1. React Agent 配置
2. LLM 重试配置
3. 工具调用级别配置
4. 上下文管理器配置

#### 3.1.2 ReactAgentConfig 组件

**功能**: 配置 React Agent 的语言、时区、模型等

**Props**:
- `config`: AgentConfig 对象
- `onConfigChange`: 配置变更回调

**表单项**:
- 语言选择 (`language`)
- 时区选择 (`timezone`)
- 模型输入 (`model`)
- 启用推理开关 (`enable_reasoning`)

#### 3.1.3 LLMRetryConfig 组件

**功能**: 配置 LLM 重试和速率限制

**Props**:
- `config`: AgentConfig 对象
- `onConfigChange`: 配置变更回调

**表单项**:
- 启用 LLM 重试开关 (`llm_retry_enabled`)
- 最大重试次数 (`llm_retry_max_attempts`)
- 重试延迟 (`llm_retry_delay`)
- 启用 LLM 速率限制开关 (`llm_rate_limiter_enabled`)
- 每分钟请求数 (`llm_rate_limiter_requests_per_minute`)

#### 3.1.4 ToolCallLevel 组件

**功能**: 配置工具调用的级别（自动、确认、拒绝）

**Props**:
- `config`: AgentConfig 对象
- `onConfigChange`: 配置变更回调

**选项**:
- `auto`: 自动执行工具调用
- `confirm`: 需要用户确认
- `deny`: 拒绝所有工具调用

#### 3.1.5 ContextManager 组件

**功能**: 配置上下文管理器的后端和参数

**Props**:
- `config`: AgentConfig 对象
- `onConfigChange`: 配置变更回调

**表单项**:
- 上下文管理器后端选择 (`context_manager_backend`)
- 最大输入长度 (`max_input_length`)
- 内存管理器后端选择 (`memory_manager_backend`)

### 3.2 Skills 页面

#### 3.2.1 SkillsPage 组件

**功能**: 技能列表页面，支持创建、编辑、删除、启用/禁用等

**状态**:
- `skills`: 技能列表
- `loading`: 加载状态
- `searchText`: 搜索文本
- `selectedSkill`: 选中的技能
- `drawerVisible`: 抽屉可见性
- `importModalVisible`: 导入模态框可见性

**方法**:
- `fetchSkills()`: 获取技能列表
- `handleCreate()`: 创建技能
- `handleEdit(skill)`: 编辑技能
- `handleDelete(skill)`: 删除技能
- `handleToggleEnabled(skill, e)`: 切换技能启用状态
- `handleUpload()`: 上传技能
- `handleFileChange(e)`: 处理文件选择

#### 3.2.2 SkillEditor 组件

**功能**: 技能编辑器，用于创建和编辑 Skill

**Props**:
- `skill`: 要编辑的技能（null 表示创建新技能）
- `onSave(skill)`: 保存回调
- `onCancel()`: 取消回调

**表单项**:
- 技能名称 (`name`)
- 启用状态 (`enabled`)
- 标签 (`tags`)
- 技能内容 (`content`)

#### 3.2.3 SkillImporter 组件

**功能**: 从 Hub 或其他来源导入 Skill

**Props**:
- `visible`: 模态框可见性
- `onImport(skills)`: 导入回调
- `onCancel()`: 取消回调

**步骤**:
1. 搜索 Hub Skill
2. 选择要导入的 Skill
3. 导入选中的 Skill

#### 3.2.4 SkillConflictDetector 组件

**功能**: 检测 Skill 之间的冲突

**Props**:
- `skills`: 技能列表
- `onResolveConflict(skillName, action)`: 解决冲突回调

**冲突类型**:
- `name`: 名称冲突
- `function`: 函数冲突
- `resource`: 资源冲突
- `dependency`: 依赖冲突

**严重程度**:
- `high`: 高
- `medium`: 中
- `low`: 低

#### 3.2.5 SkillVisualizer 组件

**功能**: 可视化 Skill 之间的关系和依赖

**Props**:
- `skills`: 技能列表
- `onSelectSkill(skill)`: 选择技能回调

**可视化元素**:
- 技能节点
- 依赖关系边
- 冲突标记

### 3.3 Tools 页面

#### 3.3.1 ToolsPage 组件

**功能**: 工具列表页面，支持查看、启用/禁用、测试工具

**状态**:
- `tools`: 工具列表
- `loading`: 加载状态
- `mcpConfigVisible`: MCP 配置抽屉可见性
- `toolGuardVisible`: ToolGuard 配置抽屉可见性
- `testDrawerVisible`: 测试抽屉可见性
- `selectedTool`: 选中的工具

**方法**:
- `fetchTools()`: 获取工具列表
- `handleToggleTool(tool)`: 切换工具启用状态
- `handleTestTool(tool)`: 测试工具

#### 3.3.2 MCPConfig 组件

**功能**: 配置 Model Context Protocol 服务器

**Props**:
- `config`: MCP 配置
- `onSave(config)`: 保存回调
- `onCancel()`: 取消回调

**表单项**:
- 启用 MCP 开关 (`enabled`)
- MCP 服务器列表 (`servers`)
  - 服务器名称 (`name`)
  - 服务器命令 (`command`)
  - 服务器参数 (`args`)
  - 环境变量 (`env`)

#### 3.3.3 ToolGuardConfig 组件

**功能**: 配置工具保护规则

**Props**:
- `config`: ToolGuard 配置
- `onSave(config)`: 保存回调
- `onCancel()`: 取消回调

**表单项**:
- 启用 ToolGuard 开关 (`enabled`)
- 规则列表 (`rules`)
  - 工具名称 (`tool_name`)
  - 动作 (`action`: allow/deny/confirm)
  - 条件 (`conditions`)

#### 3.3.4 ToolTest 组件

**功能**: 测试工具的调用和返回结果

**Props**:
- `tool`: 要测试的工具
- `onTest(toolName, params)`: 测试回调
- `onClose()`: 关闭回调

**表单项**:
- 测试参数 (`params`): JSON 格式

**显示**:
- 测试结果 (`testResult`)
- 测试错误 (`testError`)

### 3.4 Workspace 页面

#### 3.4.1 WorkspacePage 组件

**功能**: 管理工作区，支持文件浏览、编辑、上传等

**状态**:
- `workspaces`: 工作区列表
- `selectedWorkspace`: 选中的工作区
- `files`: 文件列表
- `currentPath`: 当前路径
- `loading`: 加载状态
- `fileContent`: 文件内容
- `selectedFile`: 选中的文件

**方法**:
- `fetchWorkspaces()`: 获取工作区列表
- `fetchFiles(workspaceId, path)`: 获取文件列表
- `handleWorkspaceSelect(workspaceId)`: 选择工作区
- `handleFileClick(file)`: 点击文件
- `handlePathClick(path)`: 点击路径导航
- `handleUpload()`: 上传文件
- `handleCreate()`: 创建文件/目录

#### 3.4.2 FileEditor 组件

**功能**: 使用代码编辑器编辑文件

**Props**:
- `filePath`: 文件路径
- `content`: 文件内容
- `onChange(content)`: 内容变更回调
- `onSave()`: 保存回调

**功能**:
- 编辑模式
- 预览模式
- 保存功能

#### 3.4.3 FileBrowser 组件

**功能**: 浏览文件和目录

**Props**:
- `workspaceId`: 工作区 ID
- `onFileSelect(file)`: 选择文件回调
- `onFileDelete(file)`: 删除文件回调
- `onFileRename(file)`: 重命名文件回调
- `onUpload()`: 上传文件回调

**功能**:
- 树形文件浏览
- 文件操作（重命名、删除）
- 上传文件

#### 3.4.4 FileUpload 组件

**功能**: 上传文件到工作区

**Props**:
- `visible`: 模态框可见性
- `workspaceId`: 工作区 ID
- `currentPath`: 当前路径
- `onUploadSuccess()`: 上传成功回调
- `onCancel()`: 取消回调

**功能**:
- 拖拽上传
- 点击上传
- 上传进度显示

## 4. API 模块设计

### 4.1 skillApi

**功能**: 封装所有 Skill 相关的 API 调用

**方法**:
- `listSkills(agentId?)`: 列出所有 Skill
- `listSkillWorkspaces()`: 列出 Skill 工作区
- `listSkillPoolSkills()`: 列出 Skill Pool 中的 Skill
- `refreshSkills(agentId?)`: 刷新 Skill 列表
- `refreshSkillPool()`: 刷新 Skill Pool
- `searchHubSkills(q, limit?)`: 搜索 Hub Skill
- `createSkill(skillName, content, config?, enable?)`: 创建 Skill
- `saveSkill(payload)`: 保存 Skill
- `enableSkill(skillName)`: 启用 Skill
- `disableSkill(skillName)`: 禁用 Skill
- `deleteSkill(skillName)`: 删除 Skill
- `getSkillConfig(skillName)`: 获取 Skill 配置
- `updateSkillConfig(skillName, config)`: 更新 Skill 配置
- `deleteSkillConfig(skillName)`: 删除 Skill 配置
- `uploadSkill(file, options?)`: 上传 Skill Zip 文件

### 4.2 providerApi

**功能**: 封装所有 Provider 相关的 API 调用

**方法**:
- `listProviders()`: 列出所有 Provider
- `getProvider(providerId)`: 获取单个 Provider
- `createProvider(provider)`: 创建 Provider
- `updateProvider(providerId, provider)`: 更新 Provider
- `deleteProvider(providerId)`: 删除 Provider
- `testProvider(providerId)`: 测试 Provider 连接

### 4.3 workspaceApi

**功能**: 封装所有 Workspace 相关的 API 调用

**方法**:
- `listWorkspaces()`: 列出所有工作区
- `getWorkspace(workspaceId)`: 获取工作区信息
- `createWorkspace(workspace)`: 创建工作区
- `updateWorkspace(workspaceId, workspace)`: 更新工作区
- `deleteWorkspace(workspaceId)`: 删除工作区
- `listFiles(workspaceId, path?)`: 获取文件列表
- `readFile(workspaceId, filePath)`: 读取文件内容
- `writeFile(workspaceId, filePath, content)`: 写入文件内容
- `createFile(workspaceId, filePath, isDirectory?)`: 创建文件或目录
- `deleteFile(workspaceId, filePath)`: 删除文件或目录
- `uploadFile(workspaceId, filePath, file)`: 上传文件

### 4.4 toolsApi

**功能**: 封装所有 Tools 相关的 API 调用

**方法**:
- `listTools()`: 列出所有工具
- `getTool(toolName)`: 获取工具信息
- `enableTool(toolName)`: 启用工具
- `disableTool(toolName)`: 禁用工具
- `testTool(toolName, params)`: 测试工具
- `getMCPConfig()`: 获取 MCP 配置
- `updateMCPConfig(config)`: 更新 MCP 配置
- `getToolGuardConfig()`: 获取 ToolGuard 配置
- `updateToolGuardConfig(config)`: 更新 ToolGuard 配置

### 4.5 agentApi

**功能**: 封装所有 Agent 相关的 API 调用

**方法**:
- `getAgentConfig(agentId)`: 获取 Agent 配置
- `updateAgentConfig(agentId, config)`: 更新 Agent 配置
- `listAgents()`: 获取 Agent 列表
- `createAgent(agent)`: 创建 Agent
- `deleteAgent(agentId)`: 删除 Agent

## 5. 状态管理设计

### 5.1 useAgentStore

**功能**: Agent 状态管理

**状态**:
- `selectedAgent`: 选中的 Agent
- `agentConfig`: Agent 配置
- `loading`: 加载状态
- `saving`: 保存状态
- `error`: 错误信息

**方法**:
- `setSelectedAgent(agentId)`: 设置选中的 Agent
- `fetchAgentConfig(agentId)`: 获取 Agent 配置
- `updateAgentConfig(agentId, config)`: 更新 Agent 配置
- `resetAgentConfig(agentId)`: 重置 Agent 配置

### 5.2 useProviderStore

**功能**: Provider 状态管理

**状态**:
- `providers`: Provider 列表
- `loading`: 加载状态
- `error`: 错误信息

**方法**:
- `fetchProviders()`: 获取 Provider 列表
- `addProvider(provider)`: 添加 Provider
- `updateProvider(providerId, updates)`: 更新 Provider
- `removeProvider(providerId)`: 删除 Provider

### 5.3 useSettingsStore

**功能**: Settings 状态管理

**状态**:
- `theme`: 主题（light/dark）
- `language`: 语言
- `sidebarCollapsed`: 侧边栏折叠状态

**方法**:
- `toggleTheme()`: 切换主题
- `setTheme(theme)`: 设置主题
- `setLanguage(language)`: 设置语言
- `toggleSidebar()`: 切换侧边栏
- `setSidebarCollapsed(collapsed)`: 设置侧边栏折叠状态

## 6. 类型定义设计

### 6.1 SkillSpec

**字段**:
- `name`: Skill 名称
- `content`: Skill 内容
- `enabled`: 是否启用
- `config`: Skill 配置
- `tags`: 标签列表
- `channels`: 渠道列表
- `created_at`: 创建时间
- `updated_at`: 更新时间

### 6.2 AgentConfig

**字段**:
- `language`: 语言
- `timezone`: 时区
- `model`: 模型
- `llm_retry_enabled`: 是否启用 LLM 重试
- `llm_retry_max_attempts`: 最大重试次数
- `llm_retry_delay`: 重试延迟
- `llm_rate_limiter_enabled`: 是否启用 LLM 速率限制
- `llm_rate_limiter_requests_per_minute`: 每分钟请求数
- `tool_execution_level`: 工具执行级别
- `context_manager_backend`: 上下文管理器后端
- `max_input_length`: 最大输入长度
- `memory_manager_backend`: 内存管理器后端

### 6.3 FileInfo

**字段**:
- `name`: 文件名称
- `path`: 文件路径
- `size`: 文件大小
- `is_directory`: 是否是目录
- `modified_at`: 修改时间

### 6.4 ToolInfo

**字段**:
- `name`: 工具名称
- `description`: 工具描述
- `enabled`: 是否启用
- `config`: 工具配置

## 7. 测试计划

### 7.1 单元测试

**目标**: 测试覆盖率 > 80%

**测试文件**:
- `AgentConfigPage.test.tsx`: 测试 AgentConfigPage 组件
- `SkillsPage.test.tsx`: 测试 SkillsPage 组件
- `ToolsPage.test.tsx`: 测试 ToolsPage 组件
- `WorkspacePage.test.tsx`: 测试 WorkspacePage 组件
- `agentStore.test.ts`: 测试 useAgentStore
- `skill.test.ts`: 测试 skillApi

**测试用例**:
- 组件渲染测试
- 用户交互测试
- API 调用测试
- 状态管理测试
- 错误处理测试

### 7.2 集成测试

**目标**: 测试组件之间的集成

**测试场景**:
- 创建 Skill 并编辑
- 上传 Skill 并启用
- 配置 Agent 并保存
- 浏览工作区并编辑文件

## 8. 依赖关系

### 8.1 外部依赖

- `react`: 18.3.1
- `react-dom`: 18.3.1
- `antd`: 5.29.1
- `zustand`: 5.0.3
- `react-router-dom`: 7.13.0
- `react-i18next`: 16.5.4
- `i18next`: 25.8.4
- `dayjs`: 1.11.13
- `@ant-design/icons`: 5.0.1

### 8.2 开发依赖

- `typescript`: 5.8.3
- `vite`: 6.3.5
- `@vitejs/plugin-react`: 4.4.1
- `vitest`: 4.1.4
- `@testing-library/react`: 16.3.2
- `@testing-library/jest-dom`: 6.9.1
- `jsdom`: 29.0.2
- `eslint`: 9.25.0
- `prettier`: 3.0.0

### 8.3 内部依赖

- `frontend-arch-dev`: 前端基础架构（路由、布局等）
- `console-api-dev`: 后端 API（Skill、Provider、Workspace、Tools、Agent）

## 9. 开发进度

### 9.1 已完成 ✅

1. 前端目录结构创建
2. API 模块实现
3. 类型定义实现
4. 状态管理实现
5. Agent Config 页面组件
6. Skills 页面组件
7. Tools 页面组件
8. Workspace 页面组件
9. 单元测试（6 个测试文件）
10. 索引文件
11. 测试配置
12. 每日报告
13. 进度跟踪表更新

### 9.2 进行中 🔄

1. 等待 `frontend-arch-dev` 完成前端基础架构
2. 等待 `console-api-dev` 完成后端 API

### 9.3 待完成 ⏳

1. 集成前端基础架构
2. 集成后端 API
3. 完善单元测试（目标：> 80% 覆盖率）
4. 创建模块设计文档（本文档）
5. 代码审查

## 10. 风险和问题

### 10.1 风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 前端基础架构延迟 | 高 | 中 | 使用 Mock 数据先开发组件 |
| 后端 API 延迟 | 高 | 中 | 使用 Mock API 先开发组件 |
| 测试用例不足 | 中 | 低 | 增加测试用例，目标 > 80% 覆盖率 |

### 10.2 问题

| 问题 | 状态 | 解决方案 |
|------|------|----------|
| 前端基础架构尚未完成 | 进行中 | 等待 `frontend-arch-dev` 完成 |
| 后端 API 尚未完成 | 进行中 | 等待 `console-api-dev` 完成 |

## 11. 附录

### 11.1 参考资料

- [React 官方文档](https://react.dev/)
- [Ant Design 官方文档](https://ant.design/)
- [Zustand 官方文档](https://docs.pmnd.rs/zustand/getting-started/introduction)
- [Vitest 官方文档](https://vitest.dev/)
- [React Testing Library 官方文档](https://testing-library.com/docs/react-testing-library/intro/)
- [QwenPaw 参考实现](e:/项目/Neurova/QwenPaw-1.1.6/)

### 11.2 变更日志

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|--------|
| 2026-05-12 | 1.0 | 初始版本 | frontend-agent-dev |

---

**签名**: frontend-agent-dev  
**日期**: 2026-05-12 23:59
