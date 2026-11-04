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
- **时间范围过滤**（2026-11-04）：`POST /knowledge/search` 支持 `source_modified_after/before`（repository 层过滤，无源时间条目如实排除）；recency 打分衰减在册未做（可配默认关）

## 三时间戳与时间感知消费面（2026-11-04）

- 条目契约只增：`source_created_at`/`source_modified_at`（源文档创建/修改时间，缺失留空不猜、不回退文件 mtime）；`created_at/updated_at` 语义不变＝**入库/条目更新时刻**
- 同源（`source_path`）且源修改时间更晚的重导入走**更新重入库**：覆盖旧版、旧值进 `revisions`、刷新入库时间、保留 `knowledge_id`
- 条目级冲突附 `time_context` 新者胜建议读数（`newer_side`＋`basis`），只建议不改判
- 详见[设计文档（含实施终态 §5）](../specs/2026-11-04-知识库三时间戳与时间感知消费面设计.md)

## 关键文件

```
neurova/knowledge/
├── repository.py        # 知识库 Repository（CRUD/权限/审批/去重与更新重入库/冲突时间读数）
├── storage.py           # 存储层（隔离 + 混合检索）
├── vector_index.py      # 向量索引
├── fts_index.py         # FTS5 全文索引
├── hybrid.py            # 加权 RRF 混合排序
├── document_pipeline.py # 文档管线（多格式解析＋源时间元数据抽取）
├── graph_bridge.py      # 知识图谱桥接（llm_call 可注入）
├── adapters.py          # 外部知识库适配器（iflow/feishu/ima/custom）
└── config.py            # 配置

neurova/api/endpoints/
├── knowledge.py            # 聚合器（挂载 core/sharing/remote/ingestion 等子 router＋兼容 re-export）
├── knowledge_common.py     # 共享层（请求/响应契约模型，含 source_* 时间字段）
├── knowledge_core.py       # CRUD / 搜索 / facts / audit
├── knowledge_sharing.py    # share/unshare / 公共库审批
├── knowledge_remote.py     # configs / collections / ingress-tasks
├── knowledge_ingestion.py  # /import 文件 + /import-url 网页（摄取边界，源时间接线）
└── knowledge_graph_api.py  # /api/v1/knowledge-graph
```

## 设计理念

知识库不是简单文件存储，而是"有权限的智能语义引擎"。四层可见性模型确保数据安全，混合检索保证回答质量，记忆同步实现持续学习。

## 用户指南

- [心流知识库功能使用指南](../03-user-guide/心流知识库功能使用指南.md)
