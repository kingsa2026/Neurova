# 知识库隔离共享与 RAG 演进

> 状态: ✅ 已实现 · 版本: v1.0.0-beta1 · 代码: `neurova/knowledge/`

## 概述

知识库模块支持多用户、多知识库的隔离共享模型，叠加混合检索与智能 RAG 增强。

## 四层可见性模型

| 可见性 | 说明 | 适用场景 |
|--------|------|----------|
| **public** | 公开，所有人可见 | 公共知识库 |
| **private** | 仅创建者可见（默认） | 个人知识库 |
| **shared_with** | 指定用户/用户组可见 | 团队协作 |
| **审批制** | 申请访问需审批 | 敏感知识库 |

## RAG 检索管道

```
用户问题 → 混合检索（向量 + FTS5 全文 + RRF 融合）
    ↓
知识库命中 → 权限过滤（strict 401）
    ↓
记忆同步 → 上下文融合 → 生成回答
```

## 混合检索策略

- **向量检索**（主）：基于语义相似度（`vector_index.py`）
- **FTS5 全文检索**（辅）：关键词精确匹配（知识库恒占位）
- **RRF 混合排序**：Reciprocal Rank Fusion 融合结果
- **Adaptive Retrieval**：根据查询复杂度动态调整（默认关）

## 关键文件

```
neurova/knowledge/
├── repository.py       # 知识库 Repository（CRUD/权限/审批）
├── storage.py          # 存储层（隔离 + 混合检索）
├── vector_index.py     # 向量索引
├── graph_bridge.py     # 知识图谱桥接（llm_call 可注入）
├── adapters.py         # 适配器
└── config.py           # 配置

neurova/api/endpoints/
├── knowledge.py        # /api/v1/knowledge（隔离共享 + RAG）
└── knowledge_graph_api.py  # /api/v1/knowledge-graph
```

## 设计理念

知识库不是简单文件存储，而是"有权限的智能语义引擎"。四层可见性模型确保数据安全，混合检索保证回答质量，记忆同步实现持续学习。

## 用户指南

- [心流知识库功能使用指南](../03-user-guide/心流知识库功能使用指南.md)
