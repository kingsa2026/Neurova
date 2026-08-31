# LLM 服务商管理

> 状态: ✅ 已实现 · 版本: v1.0.0-beta1 · 代码: `neurova/llm/`

## 概述

LLM 服务商管理是 Neurova 的模型基础设施：统一管理多家 LLM 供应商，元数据驱动、自动发现、智能路由与用户隔离。

## 核心能力

| 能力 | 说明 | 实现状态 |
|------|------|----------|
| 元数据化 | 每个服务商携带 capability / series / priority / scope 等元数据 | ✅ |
| 自动发现 | 三级探测链（元数据 → 模型列表 → 能力探测） | ✅ |
| 智能过滤 | 按能力（VISION / AUDIO / TTS / STT 等）、系列、供应商多维度筛选 | ✅ |
| 候选合并 | 幂等合并逻辑，避免重复配置 | ✅ |
| OpenCode 供应商 | 新增 OpenCode 兼容供应商 | ✅ |
| 流式原生异步化 | 所有 Provider 方法 async 化 | ✅ |
| 用户隔离 | scope 级隔离（admin scopes 入口），API Key 按用户独立管理 | ✅ |
| 11 语言 i18n | 前端筛选面板支持 11 种语言 | ✅ |

## 关键文件

```
neurova/llm/
├── provider_manager.py      # 服务商管理（元数据/发现/合并/隔离）
├── multi_model_client.py    # 多模型客户端（流式/异步）
├── llm_router.py            # LLM Router（请求类型检测 + 模型选择）
├── client.py                # 客户端基类
├── config_resolver.py       # 配置解析
├── config_console.py        # 配置控制台
├── model_limits.py          # 模型限制
└── providers/
    ├── openrouter_provider.py   # OpenRouter
    ├── opencode_provider.py     # OpenCode
    └── types.py                 # Provider 类型定义
```

## 智能路由

```
请求类型检测（CHAT / VISION / TTS / STT / IMAGE_GENERATION ...）
    ↓
能力匹配 → 健康检查 → 优先级排序 → 响应时间优化 → 权重评分
    ↓
最佳模型选择
```

## 设计理念

LLM 不是"一个 API 密钥"，而是"一个生态"。元数据化让系统自动理解每个模型的能力，智能路由确保每次请求都使用最合适的模型。

## 相关文档

- [API 供应商端点](../02-api/API_REFERENCE.md)
- [LLM 配置模块设计](../09-dev-progress/module_designs/llm_config.md)
