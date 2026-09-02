# Bug 修复：进化节点调用签名不匹配

## 摘要

**问题**：`voice_memory_bridge.py:260` 调用 `evolution.on_experience_recorded()` 时传入了不匹配的参数 `(experience_type, emotion_data, tool_name, user_id, agent_id)`，而方法签名期望 `(text, task, tools, success)`。由于 `try/except` 静默吞掉 `TypeError`，语音情感经验**永远不会被记录到进化系统**。

**用户报告位置有误**：用户报告 `builtin.py` 中 `exec_evolution` 存在此问题，但实际代码已正确解包字典。真实 bug 在 `voice_memory_bridge.py`。

**修复**：将错误参数映射为正确的 `(text, task, tools, success)` 签名。

---

## 根因分析

### 签名对比

| 参数 | `on_experience_recorded` 期望 | `voice_memory_bridge.py` 传入 |
|------|---------------------------|-------------------------------|
| `text` | 经验文本 | ❌ 未提供 |
| `task` | 任务描述 | ❌ 未提供 |
| `tools` | 工具列表 | ❌ 未提供 |
| `success` | 是否成功 | ❌ 未提供 |
| — | — | `experience_type="voice_emotion"` |
| — | — | `emotion_data=emotion_state` |
| — | — | `tool_name="asr_transcribe"` |
| — | — | `user_id=user_id` |
| — | — | `agent_id=agent_id` |

### 静默失败

```python
# voice_memory_bridge.py:259-269
try:
    self._evolution_orchestrator.on_experience_recorded(
        experience_type="voice_emotion",  # ❌ TypeError
        ...
    )
except Exception as e:
    logger.warning(f"语音情感进化记录失败: {e}")  # 静默吞掉
```

`TypeError` 被 `try/except` 捕获并仅记录 warning，导致：
1. 语音情感经验永远不进入进化系统
2. 进化系统的工具权重、模式挖掘、经验结晶均缺失语音情感数据
3. 问题被掩盖，难以发现

### 调用链审计

| 调用位置 | 签名 | 状态 |
|----------|------|------|
| `builtin.py:704` | `text=text, task=task, tools=tools, success=success` | ✅ 正确 |
| `post_chat_pipeline.py:795` | `text=..., task=..., tools=..., success=...` | ✅ 正确 |
| `pattern_crystallizer.py:130` | `(node.content, key, [primary_tool], True)` | ✅ 正确 |
| `voice_memory_bridge.py:260` | `experience_type=..., emotion_data=..., ...` | ❌ **修复前不匹配** |

## 修复内容

### 修改文件

**`neurova/voice_memory_bridge.py`** (lines 260-266)

将错误参数映射为正确签名：

| 旧参数 | 新映射 |
|--------|--------|
| `experience_type="voice_emotion"` | `task="voice_emotion"` |
| `emotion_data=emotion_state` | `text=f"[语音情感] {emotion_state}"` |
| `tool_name="asr_transcribe"` | `tools=["asr_transcribe"]` |
| `user_id=user_id` | *(移除，不在签名中)* |
| `agent_id=agent_id` | *(移除，不在签名中)* |
| *(缺失)* | `success=True` |

### 新增测试

**`tests/unit/test_evolution_signature_fix.py`** (5 tests)

| 测试 | 验证内容 |
|------|---------|
| `test_evolution_orchestrator_signature` | 方法签名包含 (text, task, tools, success) |
| `test_builtin_evolution_correctly_unpacked` | builtin.py 正确解包字典 |
| `test_post_chat_pipeline_correct_signature` | post_chat_pipeline 使用正确参数 |
| `test_voice_memory_bridge_passes_correct_signature` | voice_memory_bridge 不再使用 experience_type= |
| `test_voice_memory_bridge_evolution_call_mapped_correctly` | 映射后的调用参数正确 |

## 验证

```
tests/unit/test_evolution_signature_fix.py — 5/5 passed
Linter — 0 errors
```
