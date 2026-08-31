# Neurova 文档索引

快速访问所有设计文档的索引。

## 📖 文档导航

### 入门文档

| 文档 | 描述 | 适合人群 |
|------|------|----------|
| [README.md](../README.md) | 项目概述、快速开始、核心特性 | 所有人 |
| [CONTEXT.md](../CONTEXT.md) | 项目上下文、架构概览、技术栈 | 所有人 |
| [API_REFERENCE.md](../API_REFERENCE.md) | API 端点参考、请求/响应格式 | 开发者 |
| [PRODUCT_GUIDE.md](../PRODUCT_GUIDE.md) | 产品指南、使用场景、最佳实践 | 用户/开发者 |

### 架构设计文档 (按阅读顺序)

| # | 文档 | 核心内容 | 建议阅读时间 |
|---|------|----------|-------------|
| 1 | [01-core-architecture.md](01-core-architecture.md) | 整体架构、分层设计、核心组件 | 30 分钟 |
| 2 | [02-memory-system.md](02-memory-system.md) | 记忆系统、17维分类、LSM-Tree存储 | 40 分钟 |
| 3 | [03-message-routing.md](03-message-routing.md) | 消息路由、14种渠道适配、事件总线 | 40 分钟 |
| 4 | [04-multi-agent-collaboration.md](04-multi-agent-collaboration.md) | 多 Agent 协作、任务分配、工作流 | 45 分钟 |
| 5 | [05-skill-system.md](05-skill-system.md) | Skill 系统、协议兼容、沙箱执行 | 35 分钟 |
| 6 | [06-plugin-cli-system.md](06-plugin-cli-system.md) | 插件系统、CLI 工具、插件开发 | 30 分钟 |
| 7 | [07-implementation-plan.md](07-implementation-plan.md) | 实现计划、API 规范、部署方案 | 25 分钟 |
| 8 | [08-project-structure.md](08-project-structure.md) | 项目结构、开发规范、资源需求 | 20 分钟 |
| 9 | [09-context-processing.md](09-context-processing.md) | 上下文处理、窗口管理、压缩策略 | 35 分钟 |
| 10 | [10-cache-mechanism.md](10-cache-mechanism.md) | 读写缓存、批量写入、会话完整性 | 40 分钟 |
| 11 | [11-database-architecture.md](11-database-architecture.md) | 数据库主副表、关联索引、查询优化 | 45 分钟 |
| 12 | [12-memory-temperature-mechanism.md](12-memory-temperature-mechanism.md) | 记忆温度、遗忘曲线、重要/固化记忆 | 40 分钟 |
| 13 | [13-memory-intelligence-enhancements.md](13-memory-intelligence-enhancements.md) | 冲突检测、睡眠整理、联想、元认知、记忆合并 | 50 分钟 |
| 14 | [14-proactive-recall-mechanism.md](14-proactive-recall-mechanism.md) | 主动回忆、上下文触发、联想链式 | 35 分钟 |
| 14a | [14a-version-control-evolution.md](14a-version-control-evolution.md) | 版本快照、演变追踪、版本回滚 | 30 分钟 |
| 15 | [15-emotion-resonance-engine.md](15-emotion-resonance-engine.md) | Agent情感、共鸣回复、情感演变 | 35 分钟 |
| 16 | [16-vector-retrieval-system.md](16-vector-retrieval-system.md) | 语义嵌入、RRF混合检索、FAISS | 40 分钟 |
| 17 | [17-memory-compression-mechanism.md](17-memory-compression-mechanism.md) | 层级压缩、语义压缩、记忆聚合 | 35 分钟 |
| 18 | [18-memory-security-privacy.md](18-memory-security-privacy.md) | 敏感检测、AES加密、被遗忘权 | 35 分钟 |
| 19 | [19-time-awareness-mechanism.md](19-time-awareness-mechanism.md) | 模式识别、事件预测、季节偏好 | 35 分钟 |
| 20 | [20-retrieval-context-injection.md](20-retrieval-context-injection.md) | 语义理解、混合检索、上下文构建 | 45 分钟 |
| 21 | [21-recursive-self-improvement.md](21-recursive-self-improvement.md) | 递归自我进化（RSI）、元参数优化、棘轮机制、递归剪枝、工具层RSI、集成矩阵、收敛性分析、监控体系、渐进部署 | 90 分钟 |
| 22 | [02-memory-system.md](02-memory-system.md) 第12章 | 意图图谱、反馈闭环、梦境整理、自我进化 | 50 分钟 |

### 开发规范

| 文档 | 内容 | 必读 |
|------|------|------|
| [../CONTEXT.md](../CONTEXT.md) | 项目上下文、架构概览、技术栈 | ✅ 开发者必读 |
| [DOCS_ALIGNMENT_PLAN.md](../DOCS_ALIGNMENT_PLAN.md) | 文档对齐计划、更新策略 | 开发者参考 |

## 🎯 按角色推荐阅读

### 项目经理/产品负责人
1. [README.md](../README.md) - 了解项目概况
2. [CONTEXT.md](../CONTEXT.md) - 理解核心架构
3. [07-implementation-plan.md](07-implementation-plan.md) - 掌握实现计划

### 架构师/技术负责人
1. [01-core-architecture.md](01-core-architecture.md) - 整体架构
2. [02-memory-system.md](02-memory-system.md) - 记忆架构（17维分类）
3. [03-message-routing.md](03-message-routing.md) - 通信架构（14种渠道）
4. [08-project-structure.md](08-project-structure.md) - 项目结构

### 后端开发工程师
1. [01-core-architecture.md](01-core-architecture.md) - 核心架构
2. [02-memory-system.md](02-memory-system.md) - 数据模型
3. [04-multi-agent-collaboration.md](04-multi-agent-collaboration.md) - 业务逻辑
4. [API_REFERENCE.md](../API_REFERENCE.md) - API 规范
5. [CONTEXT.md](../CONTEXT.md) - 开发规范

### 测试工程师
1. [07-implementation-plan.md](07-implementation-plan.md) - 测试策略
2. [01-core-architecture.md](01-core-architecture.md) - 了解架构
3. [CONTEXT.md](../CONTEXT.md) - 测试规范

### 插件/Skill 开发者
1. [05-skill-system.md](05-skill-system.md) - Skill 开发指南
2. [06-plugin-cli-system.md](06-plugin-cli-system.md) - 插件开发指南
3. [API_REFERENCE.md](../API_REFERENCE.md) - API 规范

### 运维工程师
1. [07-implementation-plan.md](07-implementation-plan.md) - 部署方案
2. [01-core-architecture.md](01-core-architecture.md) - 系统架构
3. [08-project-structure.md](08-project-structure.md) - 资源需求

## 📚 按主题分类

### 架构设计
- [01-core-architecture.md](01-core-architecture.md) - 核心架构
- [08-project-structure.md](08-project-structure.md) - 项目结构

### 核心系统
- [02-memory-system.md](02-memory-system.md) - 记忆系统 (含温度机制、进阶增强)
- [03-message-routing.md](03-message-routing.md) - 消息路由（14种渠道）
- [04-multi-agent-collaboration.md](04-multi-agent-collaboration.md) - 多 Agent 协作
- [09-context-processing.md](09-context-processing.md) - 上下文处理
- [10-cache-mechanism.md](10-cache-mechanism.md) - 缓存机制
- [11-database-architecture.md](11-database-architecture.md) - 数据库架构
- [12-memory-temperature-mechanism.md](12-memory-temperature-mechanism.md) - 记忆温度机制
- [13-memory-intelligence-enhancements.md](13-memory-intelligence-enhancements.md) - 记忆智能增强
- [14-proactive-recall-mechanism.md](14-proactive-recall-mechanism.md) - 主动回忆机制
- [14a-version-control-evolution.md](14a-version-control-evolution.md) - 版本控制与演进
- [15-emotion-resonance-engine.md](15-emotion-resonance-engine.md) - 情感共鸣引擎
- [16-vector-retrieval-system.md](16-vector-retrieval-system.md) - 向量检索系统
- [17-memory-compression-mechanism.md](17-memory-compression-mechanism.md) - 记忆压缩机制
- [18-memory-security-privacy.md](18-memory-security-privacy.md) - 安全隐私控制
- [19-time-awareness-mechanism.md](19-time-awareness-mechanism.md) - 时间感知模块
- [20-retrieval-context-injection.md](20-retrieval-context-injection.md) - 检索与上下文注入
- [21-recursive-self-improvement.md](21-recursive-self-improvement.md) - 递归自我进化（RSI）架构设计

### 扩展系统
- [05-skill-system.md](05-skill-system.md) - Skill 系统
- [06-plugin-cli-system.md](06-plugin-cli-system.md) - 插件系统

### 实现部署
- [07-implementation-plan.md](07-implementation-plan.md) - 实现计划和部署

### 规范指南
- [../README.md](../README.md) - 项目概述
- [../CONTEXT.md](../CONTEXT.md) - 项目上下文
- [../API_REFERENCE.md](../API_REFERENCE.md) - API 参考
- [../PRODUCT_GUIDE.md](../PRODUCT_GUIDE.md) - 产品指南

## 🔍 快速查找

### 想了解整体架构？
👉 [01-core-architecture.md](01-core-architecture.md)

### 想了解记忆系统（17维分类）？
👉 [02-memory-system.md](02-memory-system.md) 或 👉 [12-memory-temperature-mechanism.md](12-memory-temperature-mechanism.md)

### 想了解消息路由（14种渠道）？
👉 [03-message-routing.md](03-message-routing.md)

### 想了解多 Agent 协作？
👉 [04-multi-agent-collaboration.md](04-multi-agent-collaboration.md)

### 想开发 Skill？
👉 [05-skill-system.md](05-skill-system.md)

### 想开发插件？
👉 [06-plugin-cli-system.md](06-plugin-cli-system.md)

### 想了解实现计划？
👉 [07-implementation-plan.md](07-implementation-plan.md)

### 想了解项目结构？
👉 [08-project-structure.md](08-project-structure.md)

### 想了解上下文处理？
👉 [09-context-processing.md](09-context-processing.md)

### 想了解缓存机制？
👉 [10-cache-mechanism.md](10-cache-mechanism.md)

### 想了解数据库架构？
👉 [11-database-architecture.md](11-database-architecture.md)

### 想了解记忆温度机制？
👉 [12-memory-temperature-mechanism.md](12-memory-temperature-mechanism.md)

### 想了解记忆智能增强（冲突检测/睡眠整理/联想/元认知/记忆合并）？
👉 [13-memory-intelligence-enhancements.md](13-memory-intelligence-enhancements.md)

### 想了解主动回忆机制？
👉 [14-proactive-recall-mechanism.md](14-proactive-recall-mechanism.md)

### 想了解版本控制与演进？
👉 [14a-version-control-evolution.md](14a-version-control-evolution.md)

### 想了解情感共鸣引擎？
👉 [15-emotion-resonance-engine.md](15-emotion-resonance-engine.md)

### 想了解向量检索系统？
👉 [16-vector-retrieval-system.md](16-vector-retrieval-system.md)

### 想了解记忆压缩机制？
👉 [17-memory-compression-mechanism.md](17-memory-compression-mechanism.md)

### 想了解安全隐私控制？
👉 [18-memory-security-privacy.md](18-memory-security-privacy.md)

### 想了解时间感知模块？
👉 [19-time-awareness-mechanism.md](19-time-awareness-mechanism.md)

### 想了解检索与上下文注入？
👉 [20-retrieval-context-injection.md](20-retrieval-context-injection.md)

### 想了解递归自我进化（RSI）架构？
👉 [21-recursive-self-improvement.md](21-recursive-self-improvement.md)

### 想了解进阶增强机制（意图图谱/反馈闭环/梦境整理/自我进化）？
👉 [02-memory-system.md](02-memory-system.md) 第12章

### 想看开发规范？
👉 [../CONTEXT.md](../CONTEXT.md)

### 想快速开始？
👉 [../README.md](../README.md)

## 📊 文档统计

| 类别 | 文档数 | 总字数 (约) |
|------|--------|------------|
| 架构设计 | 20 | 180,000+ |
| 项目概述 | 4 | 15,000+ |
| 开发规范 | 1 | 10,000+ |
| **总计** | **25** | **205,000+** |

## 🔄 更新记录

| 日期 | 文档 | 更新内容 |
|------|------|----------|
| 2026-06-07 | 03-message-routing.md | 更新为 14 种渠道支持，添加飞书/钉钉/企业微信适配器 |
| 2026-06-07 | 02-memory-system.md | 更新为 17 维记忆分类，添加 LSM-Tree 存储架构 |
| 2026-06-07 | 01-core-architecture.md | 更新为 v4.0，添加 6+ LLM 提供商支持 |
| 2026-06-07 | 08-project-structure.md | 更新为当前项目结构，版本 v4.0 |
| 2026-06-07 | INDEX.md | 更新版本为 v4.0，添加新文档链接 |
| 2026-05-06 | 02-memory-system.md | 新增第12章：进阶增强机制（意图图谱/反馈闭环/梦境整理/自我进化） |
| 2026-06-08 | 21-recursive-self-improvement.md | 新增：递归自我进化（RSI）架构设计 |
| 2026-06-08 | 21-recursive-self-improvement.md | 更新：添加递归棘轮剪枝器和工具层RSI |
| 2026-06-08 | 21-recursive-self-improvement.md | 更新v1.3：新增RSI集成矩阵、收敛性数学分析、监控可观测性、渐进式部署策略、综合架构总览 |
| 2026-05-05 | 20-retrieval-context-injection.md | 新增：检索与上下文注入（六层架构） |
| 2026-05-05 | 19-time-awareness-mechanism.md | 新增：时间感知模块 |
| 2026-05-05 | 18-memory-security-privacy.md | 新增：安全隐私控制 |
| 2026-05-05 | 17-memory-compression-mechanism.md | 新增：记忆压缩机制 |
| 2026-05-05 | 16-vector-retrieval-system.md | 新增：向量检索系统 |
| 2026-05-05 | 15-emotion-resonance-engine.md | 新增：情感共鸣引擎 |
| 2026-05-05 | 14a-version-control-evolution.md | 新增：版本控制与演进 |
| 2026-05-05 | 14-proactive-recall-mechanism.md | 新增：主动回忆机制 |
| 2026-05-05 | 13-memory-intelligence-enhancements.md | 新增：记忆智能增强（9大机制） |
| 2026-05-05 | 11-database-architecture.md | 更新：加入智能增强副表和索引 |
| 2026-05-05 | 12-memory-temperature-mechanism.md | 新增：记忆温度机制、重要/固化记忆 |
| 2026-05-05 | 02-memory-system.md | 更新：新增第9-11章（温度/智能增强/分层架构） |
| 2026-05-05 | 所有文档 | 初始版本完成 |

## 📞 反馈和建议

如果您发现文档有任何问题或有改进建议，请:
- 提交 Issue: https://github.com/neurova/neurova/issues
- 发起讨论：https://github.com/neurova/neurova/discussions

---

**最后更新**: 2026-06-07  
**维护者**: Neurova Team  
**版本**: 4.0