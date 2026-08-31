# NeurFlow 工作流引擎

> 状态: ✅ 已实现 · 版本: v1.0.0-beta1 · 代码: `neurova/collaboration/neurflow/`（20+ 文件）

## 概述

NeurFlow 是 Neurova 的可视化工作流引擎，将工作流从"配置文件"升级为"可视化 IDE"——设计、调试、发布、回滚全生命周期覆盖。

## 核心能力

| 能力 | 说明 | 实现状态 |
|------|------|----------|
| 可视化画布 | 拖拽式节点编排，六种节点（开始/结束/任务/条件/并行/子流程） | ✅ |
| 调试走查器 | 外挂式 Mock 引擎，单步/跳过执行，局部变量查看 | ✅ |
| 版本快照与回滚 | 内容指纹 + 保留 status + 回滚入史（工作流定义级） | ✅ |
| 触发器系统 | Cron 定时触发 + Webhook 入站触发（HMAC-SHA256 + token bucket 限流） | ✅ |
| 子工作流 Subflow | 嵌套工作流，深度 ≤ 5 + 防环检测 | ✅ |
| Agent 编译 | 工作流 → AgentManifest 编译（纯函数 + deps 注入） | ✅ |
| 安全审计 | Webhook 投递审计记录、历史回溯 | ✅ |

## 关键文件

```
neurova/collaboration/neurflow/
├── dag.py                    # 工作流 DAG 定义与校验
├── execution_engine.py       # 执行引擎（节点编排、状态机）
├── subflow.py                # 子工作流（深度限制 + 防环）
├── storage.py                # 工作流存储（定义级版本快照）
├── triggers.py               # 触发器（Cron + Webhook）
├── webhook_security.py       # Webhook HMAC-SHA256 签名验证
├── agent_manager.py          # Agent 编译与派发
├── adapters.py               # 适配器
├── nl_designer.py            # 自然语言设计（DSL 解析）
├── node_registry.py          # 节点注册表
├── builtin.py                # 内置节点（60+ 类型）
├── comfyui_*/custom_nodes.py # ComfyUI / 自定义节点集成
└── external_api.py           # 外部 API 对接
```

## 工作流节点类型

```
[开始] → [任务A] → [条件判断] ─┬─ 是 → [任务B] → [子流程] → [结束]
                                │
                                └─ 否 → [任务C] → [结束]
```

## 调试 IDE 特性

- 断点设置：在任意节点暂停执行
- Mock 值注入：跳过实际执行，返回预设值测试下游
- 版本抽屉：历史版本对比与回滚
- 触发器配置抽屉：Cron 表达式 / Webhook 签名配置
- 执行轨迹：每次运行的完整节点级记录（投递审计）

## 设计理念

NeurFlow 不是简单的工作流引擎，而是"Agent 的 IDE"。开发者能用可视化方式编排 AI 工作流，像调试代码一样调试 Agent 行为。

## 用户指南

- [工作流调试指南](../03-user-guide/工作流调试指南.md)
- [触发器配置指南](../03-user-guide/触发器配置指南.md)
