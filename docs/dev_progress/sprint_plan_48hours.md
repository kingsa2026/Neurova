# 🚀 Neurova 48小时冲刺计划

**制定人**: team-lead  
**制定时间**: 2026-05-13 01:00  
**冲刺周期**: 2026-05-13 01:00 → 2026-05-14 16:00（48小时）  
**目标**: 所有滞后模块100%完成

---

## 📊 冲刺目标

### 必须完成（MUST）

| 任务 | 负责人 | 当前进度 | 目标进度 | 截止时间 |
|------|--------|----------|----------|----------|
| Agent 配置页面 | frontend-agent-dev | 25-30% | 100% | 2026-05-14 16:00 |
| Web Console后端API | console-api-dev | 70-75% | 100% | 2026-05-14 16:00 |
| Provider系统增强 | provider-dev | 70% | 100% | 2026-05-14 10:00 |
| WorkflowEngine增强 | workflow-dev | 60% | 100% | 2026-05-14 16:00 |

### 应该完成（SHOULD）

| 任务 | 负责人 | 当前进度 | 目标进度 | 截止时间 |
|------|--------|----------|----------|----------|
| Chat页面 | frontend-chat-dev | 0% | 100% | 2026-05-15 00:00 |

### 可以完成（COULD）

| 任务 | 负责人 | 说明 |
|------|--------|------|
| 集成测试 | integration-dev | 等待其他任务完成 |
| 文档完善 | docs-dev | 等待其他任务完成 |

---

## ⏰ 详细时间线

### 第一阶段：紧急修复（01:00 - 10:00，9小时）

#### 🔴 关键任务：修复速率限制中间件bug

**负责人**: console-api-dev（协助：cognition-dev）  
**截止时间**: 2026-05-13 02:00（1小时内）

**具体步骤**:
1. **01:00-01:15**: cognition-dev协助定位bug
   - 文件：`neurova/api/middleware.py` 第230行
   - 问题：`await self.limiter.is_allowed(client_ip)` 误用await
   - 解决：移除await，或改为`asyncio.to_thread()`

2. **01:15-01:45**: console-api-dev修复bug
   - 修改`is_allowed()`方法为异步，或使用线程池
   - 将`threading.Lock()`改为`asyncio.Lock()`
   - 测试修复结果

3. **01:45-02:00**: 运行测试，确认修复
   - 运行 `pytest tests/test_console_api.py -v`
   - 确认无运行时错误

**交付物**: 修复后的 `neurova/api/middleware.py`

---

#### ⚠️ 重要任务：Agent配置页面API集成

**负责人**: frontend-agent-dev（协助：frontend-control-dev）  
**截止时间**: 2026-05-13 06:00（5小时内）

**具体步骤**:
1. **01:00-02:00**: 替换SkillsPage的mock数据
   - 文件：`neurova-ui/src/pages/Agent/Skills/SkillsPage.tsx`
   - 删除mock数据，调用真实的API
   - 测试API调用

2. **02:00-03:00**: 替换ToolsPage的mock数据
   - 文件：`neurova-ui/src/pages/Agent/Tools/ToolsPage.tsx`
   - 删除mock数据，调用真实的API
   - 测试API调用

3. **03:00-04:00**: 替换WorkspacePage的mock数据
   - 文件：`neurova-ui/src/pages/Agent/Workspace/WorkspacePage.tsx`
   - 删除mock数据，调用真实的API
   - 实现文件上传功能

4. **04:00-05:00**: 对接agentStore与API
   - 文件：`neurova-ui/src/stores/agentStore.ts`
   - 实现`fetchAgentConfig()`调用真实API
   - 实现`updateAgentConfig()`调用真实API

5. **05:00-06:00**: 测试所有API集成
   - 运行前端开发服务器
   - 测试所有页面的数据加载和保存

**交付物**: 所有组件对接真实API，无mock数据

---

#### 📝 必要任务：补充每日报告

**负责人**: provider-dev, workflow-dev, acp-dev  
**截止时间**: 2026-05-13 10:00

**具体要求**:
- provider-dev: 提交 `docs/dev_progress/daily_reports/2026-05-13-provider-dev.md`
- workflow-dev: 提交 `docs/dev_progress/daily_reports/2026-05-13-workflow-dev.md`
- acp-dev: 提交 `docs/dev_progress/daily_reports/2026-05-13-acp-dev.md`

**报告内容**:
1. 完成的工作（附代码证据）
2. 遇到的问题（附错误信息）
3. 下一步计划（附具体时间）
4. 需要的帮助（明确说明）

---

### 第二阶段：功能完成（10:00 - 16:00，6小时）

#### 🎯 中期检查点：2026-05-13 10:00

**必须完成**:
- [ ] console-api-dev修复速率限制中间件bug ✅
- [ ] frontend-agent-dev完成API集成 ✅
- [ ] 所有开发者提交至少一次每日报告 ✅
- [ ] provider-dev进度>80% ✅
- [ ] workflow-dev进度>70% ✅

**检查方式**:
1. 读取 `docs/dev_progress/daily_reports/` 下的报告
2. 运行测试，检查通过率
3. 代码审查，检查代码质量

**未完成的后果**:
- 第一次警告 🟡
- 给予额外12小时
- 如果仍无法完成，移除任务

---

#### 🚀 冲刺任务：完成所有功能

**Agent 配置页面 - frontend-agent-dev**:
1. **10:00-12:00**: 完成未完成功能
   - 实现Workspace文件上传
   - 实现MCP配置界面
   - 实现Tool Guard配置
   - 实现工具测试界面

2. **12:00-14:00**: 编写单元测试
   - 目标：测试覆盖率>80%
   - 至少20个测试用例
   - 测试所有用户交互

3. **14:00-16:00**: 创建模块设计文档
   - 文件：`docs/dev_progress/module_designs/agent_config.md`
   - 包含：模块概述、架构设计、API设计、测试计划

---

**Web Console后端API - console-api-dev**:
1. **10:00-12:00**: 完成4个TODO功能
   - 集成MemoryManager到聊天历史接口
   - 集成SessionManager到会话管理接口
   - 实现文件下载功能
   - 实现消息存储和检索

2. **12:00-14:00**: 更新测试代码
   - 使用pytest-asyncio重写测试
   - 运行所有测试，确保100%通过
   - 测试覆盖率>80%

3. **14:00-16:00**: 添加API文档
   - 为所有endpoint添加docstring
   - 创建API文档：`docs/api/console_api.md`

---

**Provider系统增强 - provider-dev**:
1. **10:00-12:00**: 完成剩余30%功能
2. **12:00-14:00**: 编写单元测试，覆盖率>80%
3. **14:00-16:00**: 创建模块设计文档

---

**WorkflowEngine增强 - workflow-dev**:
1. **10:00-12:00**: 完成剩余40%功能
2. **12:00-14:00**: 编写单元测试，覆盖率>80%
3. **14:00-16:00**: 创建模块设计文档（补交）

---

### 第三阶段：测试与文档（16:00 - 10:00+1，18小时）

#### 📅 检查点：2026-05-13 16:00

**必须完成**:
- [ ] console-api-dev完成所有TODO功能 ✅
- [ ] frontend-agent-dev完成所有功能实现 ✅
- [ ] provider-dev完成任务（或进度>90%） ✅
- [ ] workflow-dev进度>85% ✅

---

#### 🧪 测试与文档阶段

**所有开发者**:
1. **16:00-18:00**: 编写单元测试
   - 测试覆盖率必须>80%
   - 包含边界条件测试
   - 包含异常处理测试

2. **18:00-20:00**: 创建/完善模块设计文档
   - 文件：`docs/dev_progress/module_designs/<module_name>.md`
   - 包含：模块概述、架构设计、API设计、测试计划

3. **20:00-22:00**: 代码自我审查
   - 检查代码是否符合PEP 8（Python）/ TypeScript严格模式（前端）
   - 检查是否有完整的类型注解和文档字符串
   - 修复所有lint警告

4. **22:00-00:00**: 更新进度跟踪表
   - 文件：`docs/dev_progress/progress_tracker.md`
   - 更新任务状态为100%完成

---

### 第四阶段：代码审查与合并（10:00+1 - 16:00+1，6小时）

#### 📅 最终截止时间：2026-05-14 16:00

**所有任务必须100%完成**:
- ✅ Agent配置页面 - frontend-agent-dev
- ✅ Web Console后端API - console-api-dev
- ✅ Provider系统增强 - provider-dev
- ✅ WorkflowEngine增强 - workflow-dev

---

#### 🔍 代码审查流程

**审查者**:
- frontend-agent-dev ← frontend-control-dev
- console-api-dev ← cognition-dev
- provider-dev ← tool-engine-dev
- workflow-dev ← monitor-dev

**审查流程**:
1. **16:00-18:00**: 审查者审查代码
   - 检查代码质量
   - 检查测试覆盖率
   - 检查文档完整性

2. **18:00-20:00**: 开发者修复审查问题
   - 根据审查意见修改代码
   - 重新提交审查

3. **20:00-22:00**: 审查通过，合并到主分支
   - 所有测试通过
   - 文档完整
   - 代码符合规范

---

## 📋 角色与责任

### Team-Lead（我）

**责任**:
1. 制定冲刺计划
2. 跟踪进度（每4小时更新一次）
3. 协调资源（协助开发者解决问题）
4. 做出决策（警告、移除任务等）

**工作产品**:
- `docs/dev_progress/sprint_plan_48hours.md`（本文档）
- `docs/dev_progress/progress_tracker.md`（每日更新2次）
- `docs/dev_progress/daily_reports/2026-05-13-team-lead.md`（每日报告）

---

### 开发者责任

**所有开发者必须**:
1. 每4小时提交一次进度报告（滞后任务开发者）
2. 每天至少提交一次进度报告（其他开发者）
3. 遇到问题立即求助（不要憋着）
4. 代码完成后，通知审查者

**滞后任务开发者额外要求**:
- frontend-agent-dev: 必须在48小时内完成
- console-api-dev: 必须在48小时内完成

---

### 审查者责任

**所有审查者必须**:
1. 在2小时内响应开发者的求助
2. 在4小时内完成代码审查
3. 提供具体、可操作的审查意见
4. 审查通过后，立即合并代码

**审查标准**:
- ✅ 代码符合PEP 8（Python）/ TypeScript严格模式（前端）
- ✅ 测试覆盖率 > 80%
- ✅ 所有API有完整文档
- ✅ 所有模块有设计文档

---

## 🚨 风险管理

### 风险1：开发者无法按时完成任务

**概率**: 高  
**影响**: 高  
**缓解措施**:
1. 每4小时检查一次进度
2. 第一次警告（给予额外12小时）
3. 第二次移除任务，分配给其他开发者

---

### 风险2：代码质量不达标

**概率**: 中  
**影响**: 高  
**缓解措施**:
1. 严格的代码审查制度
2. 审查者必须在2小时内响应
3. 审查不通过，打回修改

---

### 风险3：测试覆盖率不足

**概率**: 中  
**影响**: 中  
**缓解措施**:
1. 明确测试覆盖率要求（>80%）
2. 提供测试编写指南
3. 审查者检查测试覆盖率

---

## ✅ 冲刺完成标准

### 功能完整性
- [ ] Agent配置页面所有功能可正常使用
- [ ] Web Console后端API所有endpoint可正常访问
- [ ] Provider系统增强所有功能已实现
- [ ] WorkflowEngine增强所有功能已实现

### 代码质量
- [ ] 所有模块通过单元测试（覆盖率 > 80%）
- [ ] 代码符合PEP 8规范（Python）/ TypeScript严格模式（前端）
- [ ] 所有API有完整文档

### 文档完整性
- [ ] 所有模块有设计文档
- [ ] API文档完整
- [ ] 开发者指南完整

---

## 📎 附件

### 参考文档
- `docs/dev_progress/team_restructure_plan.md` - 团队重组计划
- `docs/dev_progress/team_restructure_announcement.md` - 团队重组公告
- `docs/dev_progress/progress_tracker.md` - 进度跟踪表

### 模板文档
- `docs/dev_progress/daily_reports/TEMPLATE.md` - 每日报告模板
- `docs/dev_progress/module_designs/TEMPLATE.md` - 模块设计文档模板

---

**制定人**: team-lead  
**制定时间**: 2026-05-13 01:00  
**冲刺周期**: 2026-05-13 01:00 → 2026-05-14 16:00  
**下次更新**: 2026-05-13 04:00
