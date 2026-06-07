# 文档对齐计划

## 审计日期: 2026-06-07

## 问题总结

### 1. README.md 严重过时
- [x] 前端技术栈错误: 写的 React，实际是 Vue 3
- [x] 启动命令错误: `python -m neurova.api.main` → 实际是 `python start.py`
- [x] 项目结构缺少大量子模块 (evolution/, plugins/, collaborate/, tts/, asr/ 等)
- [x] 测试数量过时 (419 → 实际更多)
- [x] 缺少 Console 目录说明
- [x] 更新技术栈描述（添加 Vue 3 生态详细说明）
- [x] 更新多平台连接（添加飞书、钉钉、企业微信等渠道）
- [x] 更新安全守护（添加 L3 审计守护和 L4 数据守护）
- [x] 更新用户隔离机制（添加三层隔离机制说明）
- [x] 更新记忆系统（添加 MemoryType、MemoryCategory、LifecycleStage、MemoryPerspective）
- [x] 更新 API 端点（从 8 个扩展到 30+ 个端点类别）
- [x] 更新文档导航（添加 CONTEXT.md 和更多文档链接）

### 2. API_REFERENCE.md 严重过时
- [x] 只覆盖 12 个端点类别，实际有 77+ 个路由
- [x] 缺少: growth, metacognition, knowledge_graph, marketplace, sleep, firewall, audit, stats, notifications, plugins, webhooks, mobile_pairing, computer_use, runtime, image, benchmark, sandbox, builder, tool_layers, model_adapter, context, synonym, memory_timeline, enhanced_memory_search, semantic_search, memory_enhancement, agent_enhancement, shared_config, openplatform, analytics, scheduler 等
- [x] 响应格式可能已变化

### 3. PRODUCT_GUIDE.md 部分过时
- [x] 与 README 内容高度重复
- [x] 需要与 README 统一
- [x] 更新以反映当前项目状态，同时与 README 区分定位

### 4. 架构文档 (docs/architecture/)
- [x] 检查 33 个文件的时效性
- [ ] 核心架构文档需要更新（01-core-architecture.md, 02-memory-system.md, 03-message-routing.md, 08-project-structure.md）
- [ ] 记忆系统文档需要更新以反映17维记忆分类
- [ ] 更新INDEX.md（最后更新2026-05-06，版本2.0.0）

#### 架构文档评估结果：

**严重过时（需要重写或大幅更新）：**
1. `08-project-structure.md` - 显示"KingPolo/"作为项目根目录，版本1.0.0，严重过时
2. `02-memory-system.md` - 显示11种记忆分类，实际有17种，数据库schema缺少temperature字段
3. `03-message-routing.md` - 只显示5种渠道适配器，实际有14种
4. `01-core-architecture.md` - 提到"支持 OpenAI 和 Anthropic API"（实际支持6+提供商）
5. `INDEX.md` - 最后更新2026-05-06，版本2.0.0，需要更新

**部分过时（需要更新特定部分）：**
1. `04-multi-agent-collaboration.md` - Agent配置可能过时
2. `05-skill-system.md` - 需要与当前skill_system实现对齐
3. `06-plugin-cli-system.md` - 需要检查插件系统实现
4. `07-implementation-plan.md` - 实现计划可能已过时

**可能仍然有效（需要验证）：**
1. `12-memory-temperature-mechanism.md` - 记忆温度机制，看起来仍然有效
2. `13-memory-intelligence-enhancements.md` - 记忆智能增强
3. `14-proactive-recall-mechanism.md` - 主动回忆机制
4. `15-emotion-resonance-engine.md` - 情感共鸣引擎
5. `16-vector-retrieval-system.md` - 向量检索系统
6. `17-memory-compression-mechanism.md` - 记忆压缩机制
7. `18-memory-security-privacy.md` - 安全隐私控制
8. `19-time-awareness-mechanism.md` - 时间感知模块
9. `20-retrieval-context-injection.md` - 检索与上下文注入

**其他文档（可能是历史/规划文档）：**
1. `architecture-review-20260606.md` - 架构审查报告
2. `channels.md` - 渠道文档
3. `closed-loop-analysis.md` - 闭环分析
4. `COMPLETE_MODULES.md` - 完成模块列表
5. `DESIGN_SUMMARY.md` - 设计总结
6. `FUNCTIONALITY_ANALYSIS.md` - 功能分析
7. `LONG_TERM_PLAN.md` - 长期计划
8. `MODULAR_ARCHITECTURE.md` - 模块化架构
9. `PHASE5_DEVELOPMENT_PLAN.md` - 阶段5开发计划
10. `POLOCODER_TASKS.md` - 开发任务
11. `UI_COMPLETION.md` - UI完成度

### 5. 进度文档 (docs/dev_progress/)
- [ ] 74 个文件，多为历史日报，可归档

## 执行顺序

1. **P0**: 修复 README.md (项目门面) ✅ 已完成
2. **P0**: 重写 API_REFERENCE.md (开发者必须) ✅ 已完成
3. **P1**: 更新 PRODUCT_GUIDE.md ✅ 已完成
4. **P1**: 检查架构文档时效性 ✅ 已完成
5. **P1**: 更新严重过时的架构文档（进行中）
6. **P2**: 归档旧进度文档

## 更新策略

### 优先级 1: 严重过时文档（立即更新）
1. **08-project-structure.md** - 显示错误的项目根目录"KingPolo/"，版本1.0.0
   - 更新为当前项目结构（从CONTEXT.md获取）
   - 更新版本信息为v4.0
   - 更新最后更新日期为2026-06-07

2. **02-memory-system.md** - 显示11种记忆分类，实际有17种
   - 更新记忆分类体系
   - 更新数据库schema（添加temperature字段等）
   - 添加三层隔离机制说明

3. **03-message-routing.md** - 只显示5种渠道适配器，实际有14种
   - 更新渠道适配器列表
   - 添加飞书、钉钉、企业微信等渠道说明

4. **01-core-architecture.md** - 提到"支持 OpenAI 和 Anthropic API"（实际支持6+提供商）
   - 更新LLM提供商支持信息
   - 更新架构图以反映当前实现

5. **INDEX.md** - 最后更新2026-05-06，版本2.0.0
   - 更新版本信息为v4.0
   - 更新最后更新日期为2026-06-07
   - 添加新文档链接

### 优先级 2: 部分过时文档（计划更新）
1. **04-multi-agent-collaboration.md** - Agent配置可能过时
2. **05-skill-system.md** - 需要与当前skill_system实现对齐
3. **06-plugin-cli-system.md** - 需要检查插件系统实现
4. **07-implementation-plan.md** - 实现计划可能已过时

### 优先级 3: 验证有效性文档（检查后决定）
1. **12-memory-temperature-mechanism.md** - 记忆温度机制
2. **13-memory-intelligence-enhancements.md** - 记忆智能增强
3. **14-proactive-recall-mechanism.md** - 主动回忆机制
4. **15-emotion-resonance-engine.md** - 情感共鸣引擎
5. **16-vector-retrieval-system.md** - 向量检索系统
6. **17-memory-compression-mechanism.md** - 记忆压缩机制
7. **18-memory-security-privacy.md** - 安全隐私控制
8. **19-time-awareness-mechanism.md** - 时间感知模块
9. **20-retrieval-context-injection.md** - 检索与上下文注入

### 优先级 4: 历史/规划文档（归档或保留）
1. **architecture-review-20260606.md** - 架构审查报告（保留）
2. **channels.md** - 渠道文档（更新或合并）
3. **closed-loop-analysis.md** - 闭环分析（保留）
4. **COMPLETE_MODULES.md** - 完成模块列表（更新）
5. **DESIGN_SUMMARY.md** - 设计总结（更新）
6. **FUNCTIONALITY_ANALYSIS.md** - 功能分析（更新）
7. **LONG_TERM_PLAN.md** - 长期计划（更新或归档）
8. **MODULAR_ARCHITECTURE.md** - 模块化架构（更新）
9. **PHASE5_DEVELOPMENT_PLAN.md** - 阶段5开发计划（归档）
10. **POLOCODER_TASKS.md** - 开发任务（归档）
11. **UI_COMPLETION.md** - UI完成度（更新）
