# 上下文管线 P1-1

> 状态: 🟡 部分实现 · 版本: v1.0.0-beta1 · 代码: `neurova/context/` + `context_pool.py`

## 概述

在活水上下文池基础上，P1-1 补齐了上下文窗口工程的核心短板，使上下文管理从"有骨架"到"有肌肉"。

## 补齐的六块短板

| 短板 | 修复方案 | 实现状态 |
|------|----------|----------|
| 轮次配对 | 对话视图与数据库视图的配对完整性校验 | ✅ |
| EXACT 计数 | 精确 token 级计数替代字符比例估算 | ✅ |
| 真摘要 | 生产级 LLM 摘要替代截断式伪摘要 | ✅ |
| FTS 台账 | 驱逐台账持久化，避免重启丢失 | ✅ |
| 溢出恢复 | 上下文超限时单次恢复重试机制 | ✅ |
| 写入侧轮次打标 | 对话轮次标记，支持精确回溯 | ✅ |

## 关键文件

```
neurova/context/
├── collector.py       # 上下文收集（优先级 + Token 预算）
├── compressor.py      # 上下文压缩（截断/摘要）
├── converter.py       # 格式转换（OpenAI ↔ Anthropic）
├── auto_tagger.py     # 自动标签
└── context_facade.py  # 上下文门面

neurova/
├── context_pool.py           # 活水上下文池（去重/语义匹配）
├── context_pool_registry.py  # 池注册表
├── context_cache.py          # 上下文缓存（LRU）
├── context_compressor.py     # 上下文压缩（会话完整性保护）
└── enhanced_context_builder.py  # 增强上下文构建器
```

## 与活水上下文池的关系

活水上下文池是"骨架"（去重/语义匹配/按需取水），P1-1 补齐了"肌肉"——溢出恢复、真摘要、持久化台账让上下文管理真正可用。

## 设计理念

上下文不是"死水"，而是"活水"——流动性、新鲜度、纯净性、语义性、按需性。

## 相关文档

- [living_context_pool_design.md](living_context_pool_design.md) — 活水上下文池设计
- [09-context-processing.md](09-context-processing.md) — 上下文处理
- [CONTEXT_CACHE_COMPRESSION.md](CONTEXT_CACHE_COMPRESSION.md) — 上下文缓存与压缩
