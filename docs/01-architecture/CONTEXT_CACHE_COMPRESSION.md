# 上下文缓存与压缩系统使用说明

## 核心特性

### 1. 智能上下文缓存 (`context_cache.py`)
- **优先读缓存**: 减少磁盘IO，提高响应速度
- **批量写入**: 定期刷新到磁盘，减少写入频率
- **LRU淘汰**: 自动清理最少使用的缓存
- **内存限制**: 防止内存溢出

### 2. 智能压缩 (`context_compressor.py`)
- **会话完整性保护**: 不截断user/assistant对话对
- **分层压缩策略**: 从低优先级记忆开始压缩
- **Token预算管理**: 精确控制上下文长度
- **摘要生成**: 对压缩部分生成有意义的摘要

### 3. 记忆读写管理 (`memory_rw_manager.py`)
- **缓冲写入**: 减少数据库操作
- **批量提交**: 定期刷新到存储
- **温度衰减**: 定期执行记忆温度更新

### 4. 增强版上下文构建器 (`enhanced_context_builder.py`)
- 整合缓存、压缩和记忆管理
- 统一的上下文构建接口

## 快速开始

### 基本使用

```python
from neurova.enhanced_context_builder import EnhancedContextBuilder
from neurova.memory.core.manager import MemoryManager

# 1. 初始化
mem_mgr = MemoryManager(db_path="data/memory.db")
builder = EnhancedContextBuilder(
    cache_config={
        'max_entries': 100,           # 最大缓存条目
        'max_memory_mb': 512,         # 最大内存占用
        'batch_write_interval': 30,   # 批量写入间隔(秒)
    },
    memory_manager=mem_mgr
)

# 2. 构建上下文
result = builder.build_context(
    session_id="session_001",
    agent_id="kai",
    system_prompt="你是Kai，友好的AI助手",
    user_input="你好，今天天气怎么样？",
    conversation_history=[],
    channel="wechat"
)

# 3. 获取LLM上下文
context = result['context']
# 发送给LLM...

# 4. 添加对话到会话
builder.add_message_to_session(
    session_id="session_001",
    agent_id="kai",
    role="assistant",
    content="今天天气晴朗！"
)

# 5. 创建记忆
builder.create_memory(
    content="用户关心天气",
    category="interest",
    is_important=True
)
```

### 缓存管理

```python
# 查看缓存统计
stats = builder.get_stats()
print(f"缓存命中率: {stats['cache']['hit_rate']:.0%}")

# 强制刷新所有缓存
builder.flush_all()

# 查看缓存摘要
cache_summary = builder.get_cache_summary()
for entry in cache_summary:
    print(f"会话: {entry['session_id']}, 访问: {entry['access_count']}次")
```

### 压缩配置

```python
from neurova.context_compressor import CompressionConfig

config = CompressionConfig(
    max_context_tokens=8000,      # 最大上下文token数
    system_prompt_budget=1000,    # 系统提示预算
    memory_budget=2000,           # 记忆预算
    history_budget=5000,          # 历史对话预算
    min_recent_turns=3            # 最少保留最近对话轮次
)

builder = EnhancedContextBuilder(
    compression_config=config
)
```

## 工作原理

### 上下文构建流程

```
用户输入
  ↓
1. 检索相关记忆 (优先缓存)
  ↓
2. 智能压缩 (如超过token预算)
  - 保留固化记忆
  - 保留最近N轮完整对话
  - 压缩旧对话为摘要
  ↓
3. 缓存上下文 (标记dirty)
  ↓
4. 返回LLM上下文
```

### 缓存策略

```
写入: 
  用户消息 → 写入缓存 (dirty=True) → 定期批量写入磁盘

读取:
  1. 尝试从缓存读取 (命中)
  2. 缓存未命中 → 从磁盘加载 → 放入缓存

淘汰:
  超过max_entries → 淘汰最少使用的 (LRU)
  如果dirty → 先写入磁盘再淘汰
```

### 压缩策略

```
记忆压缩:
  - 固化记忆: 100%保留
  - 高温记忆(>70): 保留
  - 中温记忆(40-70): 压缩为摘要
  - 低温记忆(<40): 移除

历史压缩:
  - 最近N轮: 完整保留
  - 较早对话: 压缩为摘要
  - 保证user/assistant对话对完整
```

## 测试

运行测试脚本验证功能：

```bash
python tests/test_context_cache_compression.py
```

测试包括：
1. 上下文缓存管理
2. 智能压缩（保护会话完整性）
3. 记忆读写管理
4. 增强版构建器集成

## 最佳实践

1. **缓存大小**: 根据服务器内存调整 `max_entries` 和 `max_memory_mb`
2. **批量间隔**: 生产环境建议 `batch_write_interval=30-60秒`
3. **Token预算**: 根据LLM上下文窗口调整 `max_context_tokens`
4. **最小轮次**: `min_recent_turns=3-5` 保证对话连贯性
5. **定期刷新**: 服务关闭前调用 `builder.flush_all()`

## 文件列表

| 文件 | 说明 |
|------|------|
| `neurova/context_cache.py` | 上下文缓存管理器 |
| `neurova/context_compressor.py` | 智能上下文压缩器 |
| `neurova/memory_rw_manager.py` | 记忆读写管理器 |
| `neurova/enhanced_context_builder.py` | 增强版上下文构建器 |
| `neurova/context_persistence.py` | 上下文持久化引擎（已更新） |
| `tests/test_context_cache_compression.py` | 测试脚本 |
