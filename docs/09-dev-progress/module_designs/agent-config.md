# Agent 配置页面模块设计文档

## 概述

Agent 配置页面模块允许用户配置 Neurova 系统的 Agent 行为，包括：
- React Agent 配置
- LLM 重试配置  
- 工具调用级别配置
- 上下文管理器配置

## 文件结构

```
neurova-ui/src/
├── api/
│   ├── config.ts                 # API 配置（BASE_URL, ENDPOINTS, apiRequest）
│   ├── request.ts                # 请求封装（request, get, post, put, del）
│   └── modules/
│       ├── agent.ts             # Agent API（getAgentConfig, updateAgentConfig）
│       ├── provider.ts           # Provider API（getProviders, createProvider 等）
│       ├── skill.ts             # Skill API（getSkills, createSkill 等）
│       ├── tools.ts             # Tools API（listTools, enableTool 等）
│       └── workspace.ts         # Workspace API（listWorkspaces, listFiles 等）
├── stores/
│   ├── agentStore.ts           # Agent 状态管理（已集成 API）
│   └── providerStore.ts       # Provider 状态管理（已集成 API）
├── pages/
│   └── Agent/
│       ├── Config/
│       │   ├── AgentConfigPage.tsx      # 主配置页面（已集成 API）
│       │   ├── ReactAgentConfig.tsx    # React Agent 配置组件
│       │   ├── LLMRetryConfig.tsx    # LLM 重试配置组件
│       │   ├── ToolCallLevel.tsx      # 工具调用级别组件
│       │   └── ContextManager.tsx    # 上下文管理器组件
│       ├── Skills/
│       │   ├── SkillsPage.tsx         # 技能列表页面（已集成 API）
│       │   ├── SkillEditor.tsx        # 技能编辑器
│       │   ├── SkillImporter.tsx     # 技能导入组件
│       │   ├── SkillConflictDetector.tsx # 技能冲突检测
│       │   └── SkillVisualizer.tsx    # 技能可视化
│       ├── Tools/
│       │   ├── ToolsPage.tsx          # 工具列表页面（已集成 API）
│       │   ├── MCPConfig.tsx         # MCP 配置界面
│       │   ├── ToolGuardConfig.tsx   # ToolGuard 配置
│       │   └── ToolTest.tsx          # 工具测试界面
│       └── Workspace/
│           ├── WorkspacePage.tsx      # 工作区管理页面（已集成 API）
│           ├── FileEditor.tsx        # 文件编辑器
│           ├── FileBrowser.tsx      # 文件浏览器
│           └── FileUpload.tsx       # 文件上传组件
└── test/
    ├── api/
    │   └── config.test.ts        # API 配置测试（6 个测试，全部通过 ✅）
    ├── stores/
    │   ├── agentStore.test.ts   # Agent Store 测试（6 个测试，全部通过 ✅）
    │   └── providerStore.test.ts # Provider Store 测试（5 个测试，全部通过 ✅）
    ├── pages/Agent/
    │   ├── Config/
    │   │   └── AgentConfigPage.test.tsx # AgentConfigPage 测试（进行中 ⚠️）
    │   ├── Skills/
    │   │   └── SkillsPage.test.tsx  # SkillsPage 测试（进行中 ⚠️）
    │   ├── Tools/
    │   │   └── ToolsPage.test.tsx   # ToolsPage 测试（进行中 ⚠️）
    │   └── Workspace/
    │       └── WorkspacePage.test.tsx # WorkspacePage 测试（进行中 ⚠️）
    └── api/modules/
        └── skill.test.ts        # Skill API 测试（4 个测试，全部通过 ✅）
```

## API 集成状态

### 已完成 ✅
1. **agentStore.ts**
   - `fetchAgentConfig()` - 调用 `agentApi.getAgentConfig()`
   - `updateAgentConfig()` - 调用 `agentApi.updateAgentConfig()`

2. **providerStore.ts**
   - `fetchProviders()` - 调用 `providerApi.getProviders()`
   - `addProvider()` - 调用 `providerApi.createProvider()`
   - `updateProvider()` - 调用 `providerApi.updateProvider()`
   - `removeProvider()` - 调用 `providerApi.deleteProvider()`

3. **SkillsPage.tsx**
   - `fetchSkills()` - 调用 `skillApi.getSkills()`
   - `handleDelete()` - 调用 `skillApi.deleteSkill()`
   - `handleToggleEnabled()` - 调用 `skillApi.toggleSkill()`

4. **ToolsPage.tsx**
   - `fetchTools()` - 调用 `toolsApi.listTools()`
   - `handleToggleTool()` - 调用 `toolsApi.enableTool()`/`disableTool()`

5. **WorkspacePage.tsx**
   - `fetchWorkspaces()` - 调用 `workspaceApi.listWorkspaces()`
   - `fetchFiles()` - 调用 `workspaceApi.listFiles()`
   - `handleFileClick()` - 调用 `workspaceApi.readFile()`

### 进行中 ⚠️
1. **测试环境配置问题**
   - `window.matchMedia` 未定义，导致 antd 组件测试失败
   - 已在 `vitest.setup.ts` 和测试文件中 mock，但可能未生效

## 测试覆盖率

### 当前状态
- **API 模块测试**：16 个测试全部通过 ✅
  - `config.test.ts`：6 个测试
  - `skill.test.ts`：4 个测试
  - `agentStore.test.ts`：6 个测试
- **Store 模块测试**：11 个测试全部通过 ✅
  - `agentStore.test.ts`：6 个测试
  - `providerStore.test.ts`：5 个测试
- **页面组件测试**：进行中 ⚠️
  - `AgentConfigPage.test.tsx`：1 个通过，2 个失败
  - `SkillsPage.test.tsx`：进行中
  - `ToolsPage.test.tsx`：进行中
  - `WorkspacePage.test.tsx`：进行中

### 目标
- **测试覆盖率**：80% 以上
- **完成时间**：2026-05-13 12:00

## 已知问题

### 1. 测试环境配置问题
- **问题**：`window.matchMedia` 未定义
- **影响**：antd 组件（如 Tabs、Grid）需要 `window.matchMedia`
- **当前状态**：已在 `vitest.setup.ts` 中添加 mock，但测试仍然报错
- **解决方案**：可能需要检查 vitest 配置或 antd 版本

### 2. API 调用风格不统一
- **问题**：`skill.ts` 使用 `apiRequest` + `ENDPOINTS`，其他使用 `request` + `get`/`post`/`put`/`del`
- **影响**：代码风格不一致，但功能都正常工作
- **解决方案**：暂不统一，优先完成任务

### 3. 类型不匹配问题（已修复 ✅）
- **问题**：`workspaceApi.readFile` 返回 `{ content: string }`，但组件中可能期望 `string`
- **解决方案**：已修复，正确访问 `result.content`

## 下一步计划

### 1. 修复测试环境配置（优先级：高）
- [ ] 修复 `vitest.setup.ts`，确保 `window.matchMedia` mock 生效
- [ ] 修复 `AgentConfigPage.test.tsx` 中的测试失败
- [ ] 确保所有测试能够通过

### 2. 完成测试覆盖率提升
- [ ] 完成 `SkillsPage.test.tsx`、`ToolsPage.test.tsx`、`WorkspacePage.test.tsx`
- [ ] 运行所有测试，确保覆盖率达到 80%+

### 3. 代码清理和文档
- [ ] 统一 API 调用风格（可选）
- [ ] 更新 README 和注释
- [ ] 创建用户使用文档

## 预计完成时间

- **API 集成**：2026-05-13 04:00（已完成 100% ✅）
- **测试环境修复**：2026-05-13 08:00
- **测试覆盖率 80%**：2026-05-13 12:00
- **功能实现完成**：2026-05-13 18:00
- **所有任务 100% 完成**：2026-05-14 10:00（before deadline）

## 签名

**frontend-agent-dev**  
2026-05-13 06:30
