# Bug Fix: 审批回复接收机制断裂修复

## 问题描述

`exec_approval` 通过 `ChannelManager.send_message()` 发送审批消息，但审批回复的接收机制存在断裂 — `approval_event`（asyncio.Event）没有被正确注册到 ChannelManager 的消息处理器中，导致审批节点会一直等待直到超时。

## 根因分析（3个问题）

### 问题1：跨事件循环 asyncio.Event 问题（核心问题）

飞书/钉钉/企业微信适配器在同步回调中创建新的事件循环来触发 `_emit_event`：

```python
# feishu.py:149-153
loop = asyncio.new_event_loop()
loop.run_until_complete(
    self._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
)
loop.close()
```

而 `exec_approval` 中的 `await approval_event.wait()` 运行在主事件循环中。`asyncio.Event` 绑定到特定事件循环，在另一个循环中调用 `set()` 无法唤醒原循环的 `wait()`。

### 问题2：全局单处理器覆盖问题

`ChannelManager.set_message_handler()` 是全局覆盖模式：

```python
def set_message_handler(self, handler: MessageHandler):
    self._message_handler = handler  # 直接覆盖
```

如果多个并发审批节点同时运行，后注册的处理器会覆盖前一个。

### 问题3：threading.Event 超时处理

`threading.Event.wait(timeout)` 返回 `False` 表示超时，但 `asyncio.wait_for` 包装后不会触发 `TimeoutError`，需要手动检查返回值。

## 修复方案

### 1. ChannelManager 多处理器支持（`manager.py`）

新增 `add_message_handler(handler, priority)` 和 `remove_message_handler(handler_id)` 方法，支持：
- 多个处理器同时存在
- 按优先级排序（数字越小优先级越高）
- 通过 handler_id 精确移除

`_on_channel_event` 方法更新为支持多处理器链模式：
- 优先使用多处理器链（`_message_handlers`）
- 回退到单处理器模式（`_message_handler`）

### 2. exec_approval 跨事件循环修复（`builtin.py`）

- `asyncio.Event` → `threading.Event`：线程安全，可跨线程触发
- `set_message_handler` → `add_message_handler(priority=10)`：避免覆盖其他处理器
- 添加 `remove_message_handler` 调用：成功/超时后清理处理器
- `threading.Event.wait(timeout)` 返回值检查：`False` 表示超时

### 3. 适配器事件循环修复（`feishu.py`, `dingtalk.py`, `wecom.py`）

```python
# 修复前
loop = asyncio.new_event_loop()
loop.run_until_complete(self._emit_event(...))
loop.close()

# 修复后
try:
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(self._emit_event(...), loop)
    else:
        loop.run_until_complete(self._emit_event(...))
except RuntimeError:
    loop = asyncio.new_event_loop()
    loop.run_until_complete(self._emit_event(...))
    loop.close()
```

优先使用主事件循环，仅在无事件循环时创建新的。

## 修改文件清单

1. **`neurova/channels/manager.py`** — 新增 `add_message_handler` / `remove_message_handler` / 多处理器链支持
2. **`neurova/collaboration/neurflow/builtin.py`** — `exec_approval` 使用 `threading.Event` + `add_message_handler`
3. **`neurova/channels/feishu.py`** — 事件循环修复
4. **`neurova/channels/dingtalk.py`** — 事件循环修复
5. **`neurova/channels/wecom.py`** — 事件循环修复

## 测试结果

- 36/36 测试全部通过（7旧 + 11新单元 + 8跨循环 + 10集成）
- 0 个 linter 错误

## 数据流（修复后）

```
exec_approval() → send_message(approval) → ChannelManager
  → add_message_handler(message_handler, priority=10)
  → approval_event.wait(timeout=3600)

用户回复 → Adapter._handle_message_event()
  → asyncio.run_coroutine_threadsafe(_emit_event(...))
  → ChannelManager._on_channel_event()
  → message_handler(message)
    → on_approval_reply(content)
    → approval_event.set()  ← 跨线程安全
  → approval_event.wait() 返回 True
  → 返回审批结果
```
