# Neurova 源码深度缺陷审计报告

- **审计日期**：2026-09-10
- **审计范围**：`neurova/`（Python 后端，550+ 文件）+ `NeurUI/src`（Vue3 + TS 前端）
- **审计方式**：6 路并行静态扫描（Agent 核心 / 记忆认知层 / LLM 层 / API 安全层 / 通道执行层 / 前端）+ 人工逐条复核高危项
- **缺陷总数**：**112 条**（致命 14 / 高 31 / 中 42 / 低 25）
- **复核标记**：`✅` = 人工读码复核确认；`⚠️` = 扫描发现、逻辑可信但未逐行复核（修复前需再确认）

> 说明：本报告只做只读分析，未修改任何源码。所有行号基于审计时的 `main` 分支工作区。

---

## 一、结论摘要

| 维度 | 结论 |
|---|---|
| **最紧急** | `router.RouteResult` 缺 `message_type` 字段 → `Agent.process_message()` 100% 抛 `AttributeError`（统一入口不可用） |
| **最危险（安全）** | `/api/v1/computer/shell` 任意命令执行 + `/file/read`、`/file/write` 任意文件读写，仅需**任意已登录用户**（注册开放 → 可自注册 → RCE） |
| **影响面最广** | 7 个渠道适配器（sip/qq/qqbot/mqtt/websocket/discord）向 `UnifiedMessage` 传入不存在的 `global_user_id` → 消息解析全部 `TypeError` |
| **最隐蔽** | 睡眠温度衰减因 naive/aware 时间相减抛 `TypeError` 被静默吞掉 → **衰减永久失效，记忆只升温不降温** |
| **最假象** | `MemorySecurity.forget_memory()`（被遗忘权）、`AutoContextUpdater` 四项维护、`GeneratorManager` 全部生成器 —— 均为**空实现但上报成功** |
| **系统性问题 #1** | **契约错位**：跨模块调用的方法名/参数/字段不匹配（12 处）。根因是缺少跨模块类型检查与集成测试 |
| **系统性问题 #2** | **静默降级**：`except Exception: logger.debug/warning` 吞掉关键链路故障（20+ 处），故障不可观测 |
| **系统性问题 #3** | **锁覆盖不全**：SQLite 常驻连接、`_l0_buffer`、关键词索引在锁外被并发访问（10+ 处） |

---

## 二、致命级缺陷（P0，14 条）

### A-01 ✅ `RouteResult` 缺 `message_type` 字段 → 统一消息入口 100% 崩溃
- **位置**：`neurova/agent_core.py:1673` ← `neurova/router.py:93-100`
- **类型**：跨文件契约错位（属性不存在）
- **现象**：`Agent.process_message()` 每次路由成功后必抛 `AttributeError: 'RouteResult' object has no attribute 'message_type'`。
- **根因**：`RouteResult` 数据类只有 5 个字段，调用方按 `Message` 的字段取值。
- **证据**：
```python
# router.py:93-100
class RouteResult:
    success: bool = True
    response: str = ""
    handler: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0      # ← 无 message_type
```
```python
# agent_core.py:1673
logger.info("消息路由完成: %s, success=%s", result.message_type.value, result.success)
```
- **修复**：给 `RouteResult` 增加 `message_type: Optional[MessageType]` 并在 `route()` 各分支赋值（推荐），或调用方改用 `result.handler`。

---

### A-02 ✅ `Agent.chat()` 的 `event_emitter` 参数被丢弃 → 流式/推理事件无法转发
- **位置**：`neurova/agent_core.py:1728-1735`
- **类型**：参数未透传
- **现象**：`agent.chat(..., event_emitter=fn)` 时 SSE 客户端收不到 content/reasoning 事件。
- **证据**：
```python
ctx = ChatContext(
    user_input=user_input, stream=stream, save_memory=save_memory,
    session_id=session_id, metadata=metadata, enable_tts=enable_tts,
)   # ← event_emitter 未传入，ChatContext 该字段恒为 None
return await self.chat_pipeline.execute(ctx)
```
- **修复**：追加 `event_emitter=event_emitter`。

---

### C-01 ✅ 7 个渠道适配器向 `UnifiedMessage` 传入不存在的字段 → 消息解析全崩
- **位置**：`neurova/channels/models.py:56-74`（定义）← 8 处调用点
- **类型**：数据类字段不匹配
- **命中点**：`discord.py:331`、`websocket.py:326,346`、`sip.py:374,450`、`qqbot.py:398`、`qq.py:429`、`mqtt.py:280`
- **证据**：
```python
# models.py:56-74 —— UnifiedMessage 无 global_user_id
message_id / channel / content_type / content / user_id / chat_id /
session_id / agent_id / timestamp / reply_to / file_url / file_name /
card_data / raw_message / attachments / metadata
```
```python
# discord.py:331
global_user_id=f"discord:{user_id}",   # → TypeError: unexpected keyword argument
```
- **修复**：`UnifiedMessage` 增加 `global_user_id: Optional[str] = None`（8 处调用点已达成共识，属"定义缺失"而非"调用错误"）。

---

### C-02 ⚠️ `XiaoYiAdapter` 无法实例化
- **位置**：`neurova/channels/xiaoyi.py:39, 65-76`
- **类型**：适配器契约（构造 + 抽象方法缺失）
- **现象**：`super().__init__()` 未传基类必填 `config`；`ChannelConfig(channel=..., config=...)` 用的是另一套字段；未实现抽象 `connect()/disconnect()`。
- **修复**：改用 `base.ChannelConfig(channel_type="xiaoyi", extra={...})`，补齐抽象方法，`send_message` 改异步签名。

---

### C-03 ⚠️ `TelegramAdapter` 契约全错（构造 + 同步/异步 + 签名）
- **位置**：`neurova/channels/telegram_adapter.py:45-76`、`telegram_sender.py:14`
- **现象**：`register_adapter()` 抛 `AttributeError: no attribute 'config'`；即便绕过，`await adapter.send_message(...)` 抛 `object bool can't be used in 'await' expression`。
- **修复**：`__init__(self, config)` 内 `super().__init__(config)`；新增异步适配层包装 mixin 的同步实现。

---

### C-04 ⚠️ Discord / WebSocket 适配器未初始化 `self.config`
- **位置**：`neurova/channels/discord.py:38-41`、`websocket.py:47-51`
- **现象**：`adapter.channel_type` / `adapter.config.enabled` 全部 `AttributeError`（基类 `channel_type` 读 `self.config.channel_type`）。
- **修复**：统一走 `super().__init__(ChannelConfig(channel_type=...))`。

---

### C-05 ✅ `EvolutionFacade` 工具合成恒返回空（参数名不匹配 + 异常被吞）
- **位置**：`neurova/evolution/closed_loop.py:333` → `pattern_miner.py:146-148`
- **现象**："频繁模式 → 技能模板"闭环彻底断开，且无任何错误暴露。
- **证据**：
```python
# closed_loop.py:333
return self.pattern_miner.to_skill_template_list(top_n=top_n)     # TypeError
# pattern_miner.py:146-148
def to_skill_template_list(self, min_support=None, min_success_rate=0.0):  # 无 top_n
# evolution_facade.py:304
except Exception as e: logger.warning(...); return []
```
- **修复**：`to_skill_template_list` 增加 `top_n: Optional[int] = None` 并在返回前截断；facade 的 `except Exception` 收窄并记 traceback。

---

### M-01 ✅ 认知存储引擎 WAL 锁 **自死锁**（+ AB-BA 死锁）
- **位置**：`neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py:230, 318-330, 364`
- **类型**：不可重入锁二次获取
- **现象**：WAL 文件超过 10MB 后 `store()` **永久挂起**，进程级停顿。
- **证据**：
```python
230: self._wal_lock = threading.Lock()          # 非可重入
318: with self._wal_lock:                        # 第一次获取
330:     self._flush_l0_to_l1()                  # ← 在锁内调用
364:     with self._wal_lock:                    # 同一线程二次获取 → 死锁
```
- **附带**：`_recover_wal` 加锁顺序 `_db_lock → _wal_lock`（285），`_wal_append` 为 `_wal_lock → _db_lock`（318→340）→ 经典 AB-BA 死锁。
- **修复**：`_wal_lock` 改 `threading.RLock()`；统一全局加锁顺序为 `_wal_lock → _db_lock`。

---

### M-02 ✅ 被遗忘权 `forget_memory()` 是空实现却上报成功
- **位置**：`neurova/cognitive_layers/memory_layer/security.py:534-567`
- **类型**：合规功能假实现
- **证据**：
```python
553: try:
554:     # 这里应该调用实际的记忆删除逻辑
555:     # 由于我们只有 Memory 模型，这里只是模拟
558:     self._log_access(memory_id=..., action=AuditAction.FORGET, ...)
560:     result["success"] = True          # ← 一行数据都没删
561:     result["message"] = "记忆已标记为遗忘"
```
- **修复**：注入 `memory_manager` 真实调用 `forget()`；未注入依赖时必须返回 `success=False`。

---

### L-01 ✅ Anthropic / Gemini 原生通道**非流式聊天恒定返回协程对象**
- **位置**：`neurova/llm/multi_model_client.py:562` ← `anthropic_client.py:154` / `gemini_client.py:139`
- **类型**：异步契约错误（协程未 await）
- **现象**：返回体是未 await 的 coroutine，用户拿到空回复 + `RuntimeWarning: coroutine was never awaited`，token 按 0/1 估算记账。
- **证据**：
```python
# multi_model_client.py:561-562
async def _attempt():
    return await asyncio.to_thread(client.client.chat, messages, **kwargs)   # ← 同步包装
# anthropic_client.py:154 / gemini_client.py:139
async def chat(self, messages, **kwargs):     # ← 实际是 async
```
- **修复**：`inspect.iscoroutinefunction(client.client.chat)` 判定，协程分支直接 `await`，同步分支走 `to_thread`。

---

### L-02 ✅ `GeneratorManager` 生成器注册表**恒为空** → 全部 AIGC 功能不可用
- **位置**：`neurova/llm/generators/manager.py:59, 65-80, 101, 125`
- **现象**：所有文生图/图生图/文生视频/图生视频恒返回 `Generator type 'xxx' not available`。
- **证据**：
```python
59:  self._generators: Dict[str, Any] = {}      # 全文件唯一赋值，永不写入
101: return self._generators.get(generator_type)   # 恒 None
125: return self._create_error_result(f"Generator type '{generator_type}' not available")
```
- **附带**：即使修好注册，`manager.py:131` 调用不存在的 `router.get_best_model()`；`:137` 用 `generate(prompt=..., model=...)` 调用实际签名 `generate(config: GenerationConfig)` → 仍会 `TypeError`。
- **修复**：`_initialize_generators` 中按 `GeneratorType` 实例化并注册；改用 `router.select_model(RequestType.TEXT_TO_IMAGE)`；构造 `GenerationConfig` 后调用。

---

### S-01 ✅ `/computer/shell` 任意命令执行（仅需任意已登录用户）
- **位置**：`neurova/api/endpoints/computer.py:20, 321-342`
- **类型**：RCE / 鉴权粒度不足
- **证据**：
```python
20:  router = APIRouter(dependencies=[Depends(get_current_user)])   # 仅登录，无 admin
325: proc = await asyncio.create_subprocess_shell(body.command, ...)
```
- **利用链**：开放注册（S-04，首个注册者即 admin，普通注册即 user）→ 登录 → POST `/shell` → RCE。
- **修复**：`/shell` 加 `Depends(require_admin())`；更建议整体下线或改为白名单 + 沙箱 + 审计。

---

### S-02 ✅ `/computer/file/read` 与 `/file/write` 任意文件读写（路径穿越）
- **位置**：`neurova/api/endpoints/computer.py:345-375`
- **现象**：可读 `/etc/passwd`、`.env`、`data/users.db`；可写任意文件（覆盖代码/配置）。
- **证据**：
```python
351: p = Path(body.path)                       # 无根目录约束
354: content = p.read_text(encoding=body.encoding)
369: p = Path(body.path); p.parent.mkdir(...); p.write_text(body.content, ...)
```
- **修复**：以工作区为根做 `resolve().relative_to(root)` 校验（参考 `files_api.py:291` 的正确写法）。

---

### S-03 ⚠️ 会话同步模块全端点零鉴权 + IDOR
- **位置**：`neurova/api/endpoints/session_sync.py:112-127, 273-308`
- **现象**：WebSocket 与全部 REST 会话端点无鉴权，`session_id`/`user_id` 完全由客户端提供 → 可订阅/读取/注入任意他人会话的全部对话事件。
- **证据**：
```python
113: async def websocket_sync(websocket, session_id: str, channel_type="web", user_id="anonymous"):
127:     await websocket.accept()      # 无鉴权即 accept
```
- **修复**：WS 在 `accept()` 前校验 JWT；`user_id` 从 token 取；`session_id` 做属主校验。

---

### S-04 ⚠️ 开放注册 + 首账号自动提权 admin + 公开 setup 探针
- **位置**：`neurova/api/endpoints/auth.py:438-446, 453-489`
- **现象**：注册流程**从未调用**邮件验证码链路；第一个注册者直接 `role="admin"`；`/setup-status` 公开暴露系统是否已初始化。
- **证据**：
```python
489: role = "admin" if user_model.count_users() == 0 else "user"
```
- **修复**：强制验证码；首账号提权改带时限的一次性引导令牌（复用已有 `bootstrap_user.py`）。

---

### F-01 ✅ 前端 `PlanPanel` 响应多解一层 → 计划模式全链路崩溃
- **位置**：`NeurUI/src/components/chat/PlanPanel.vue:188, 285, 307, 324, 325, 327, 342`
- **类型**：响应解包不一致
- **现象**：开始澄清 / 提交回答 / 审批 / 预览四步全部 `Cannot read properties of undefined (reading 'session')`。
- **根因**：`api/index.ts:91` 拦截器已 `return response.data`，调用方又写 `.data` → 取 `body.data.data.session`。
- **证据**：
```ts
// api/index.ts:91
return response.data                      // res = {code, message, data:{session}}
// PlanPanel.vue:188
const started: PlanSession = res.data.data.session   // res.data={session} → res.data.data=undefined
```
- **附带**：单测 `PlanPanel.test.ts:135` 的 `resp()` 返回**未解包**的 AxiosResponse 形态，因此单测全绿却掩盖生产崩溃。
- **修复**：全部改为 `res?.data?.xxx`；同步修正测试 fixture 并加「拦截器返回体」契约测试。

---

## 三、高危缺陷（P1，31 条）

### 3.1 Agent 核心 / 对话管线

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| A-03 | `post_chat_pipeline.py:583` | 属性名不存在 | `getattr(self._agt, "agent_id", "")` 恒为空（`Agent` 无该属性，在 `config.agent_id`）→ 产物归属/隔离失效 | ⚠️ |
| A-04 | `agent_core.py:618` / `tool_executor.py:1011` / `agent_core.py:1613` | 遗留死状态 | 迁 ContextVar 后 `_current_user_input` 恒为 `None` → 肌肉记忆学到的问题文本退化为 `"执行 <tool>"` 占位串，语义匹配质量塌陷 | ⚠️ |
| A-05 | `mem_core.py:59-149` | 资源泄漏 | `_PersistDbStore` 建 sqlite 常驻连接却无 `close()/shutdown()`，且 `Agent.shutdown()` 无释放路径 | ⚠️ |
| A-06 | `mem_core.py:976-990` | 双队列 split-brain | 入队用 `memory_manager._write_queue`（A），flush 用 `buffer_module._write_queue`（B）→ 该批记忆可能长期不落盘 | ⚠️ |
| A-07 | `agent_core.py:1016, 1069-1077` | 锁作用域错误 | `_model_switch_lock_slot` 是**类属性** → 所有 Agent 共用一把锁；且 `asyncio.Lock()` 在导入期（无事件循环）构造，Python<3.10 会绑定默认 loop | ⚠️ |
| A-08 | `agent_core.py:770-773` | 初始化顺序 | 拓扑排序把 `evolution` 排在 `tools` 之前，而 `a._skill_registry` 此时为 `None` → `evolution.register_tools()` 永不执行 | ⚠️ |
| A-09 | `router.py:485 / 166-179` | 协程未 await + 死代码 | 注册的 handler 返回协程从未 await，且 `self._handlers` 在 `route()` 中**一次都没被读取** | ⚠️ |
| A-10 | `router.py:312-318` | 类型不匹配 | `RouteResult.response` 声明 `str`，实际塞入 `agent.chat()` 返回的 `Dict` | ⚠️ |
| A-11 | `agent/loops/base.py:57-68` | 静默空回复 | 抽象方法 `predict_step` 无 `raise NotImplementedError` → 未覆写时静默 `None` → 用户拿到空回复 | ⚠️ |
| A-12 | `agent/chat_pipeline.py:530/552/1225/2203` | 两个 trace id 串台 | `ctx.trace_id` 先被 trajectory recorder 赋值，后被 ReasoningTraceManager 覆盖 → 轨迹无法正常结束，写入围栏关联断裂 | ⚠️ |
| A-13 | `post_chat_pipeline.py:2079` | 阻塞事件循环 | `async def` 中同步调用 `rsi.run_iteration()`（含 SQLite 读写/参数寻优） | ⚠️ |
| A-14 | `post_chat_pipeline.py:259-284` | ImportError 被 re-raise | 可选依赖缺失（`ModuleNotFoundError`）会被当"编程错误"上抛 → 炸穿整轮 `chat()` | ⚠️ |

### 3.2 记忆 / 认知层

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| **M-03** | `temperature.py:259-270` + `sleep.py:387` | **时间类型混用 + 静默吞异常** | `_dt.now()`（naive 本地）减 aware UTC 的 `last_accessed` → `TypeError` 被 `except (ValueError, TypeError)` 吞掉 → `days_idle=0` → 命中 `if days_idle < 1.0: return` → **睡眠温度衰减永久失效** | ✅ |
| **M-04** | `manager.py:1272-1275` | 隔离越权 | `SELECT * FROM memories ORDER BY temperature DESC LIMIT ?` **无任何 WHERE** → 温度通道长期跨租户泄漏；且在锁外改 `conn.row_factory` | ⚠️ |
| **M-05** | `manager.py:1081-1085` vs `1094-1095` | 元组顺序反转 | 降级分支产出 `(m.id, rank)`，主路径产出 `(rank, id)`；`for rank, mid in` 解包后 `mid` 是字符串记忆 id 变 rank、`rank` 是 int → `id_to_memory[mid]` 全 miss → **降级路径恒定返回空** | ✅ |
| M-06 | `manager.py:913, 1243, 1371` | 锁覆盖不全 | `base = self._scoped_memories()` 在 `with self._lock:` **之前** → 并发 `remember/forget` 时 `RuntimeError: dictionary changed size during iteration` | ⚠️ |
| M-07 | `semantic_search.py:202-265` | 索引无锁 + 陈旧 | `_keyword_index` 全方法无锁；`remove_memory_index` 边迭代边删；`update_memory(content=)` / `forget(soft=True)` 不维护索引 | ⚠️ |
| M-08 | `vector_search_advanced.py:380-411` | 嵌入模型未降级 | `SentenceTransformer` 加载失败后 `self._model=None` 仍构造成功 → 后续所有 `add_texts/search` 抛 `RuntimeError`，**不回落** TF-IDF；索引硬编码 384 维 | ⚠️ |
| M-09 | `cognitive_storage_engine.py:336-339` | 锁外共享缓冲 | `_flush_l0_to_l1` 无锁复制并清空 `_l0_buffer`，且 **commit 前已出队** → commit 失败即丢数据 | ⚠️ |
| M-10 | `sleep_writeback.py:78-86` | 语义反转 | 未合并记忆调用 `update_memory_temperature()`（内部是 `mem.touch()` → 升温），与"睡眠衰减"语义相反；叠加 M-03 等于**睡眠只升温不降温** | ⚠️ |
| M-11 | `conversation_buffer.py:313-317, 386-388` | 数据丢失 | 先 `self._queue.clear()` 后写入，单条失败仅 `logger.warning` → **该批记忆永久丢失**，无重试无补偿 | ⚠️ |
| M-12 | `security.py:192, 244, 268-270` | 密钥随机化 | 未配置 `encryption_key` 时每次启动生成新随机密钥 → 旧加密内容解密返回 `""`（`InvalidToken` 被吞）→ **数据静默丢失** | ⚠️ |
| M-13 | `neurova_recall.py:787-789, 908` | 无超时阻塞 | `thread.join(timeout=None)`；`asyncio.gather` 无 timeout → 插件通道挂起即永久阻塞召回 | ⚠️ |
| M-14 | `auto_context_updater.py:137-193` | 空实现上报成功 | 压缩/温度衰减/索引重建/缓存清理四项**全部 `return 0`**，`_perform_update` 照常打"更新完成" | ⚠️ |

### 3.3 LLM 层

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| **L-03** | `multi_model_client.py:823-891/943-960` | **并发槽泄漏** | `limiter.release()` 只在正常路径与 `except Exception`；`GeneratorExit`/`CancelledError` 是 `BaseException` 捕获不到 → 消费方中途断开（前端取消、GC）时槽位只减不增，累计 8 次后该模型永久拒绝，需重启 | ✅ |
| **L-04** | `error_mapping.py:217` | **密钥泄漏** | 其余 4 条 return 都用了 `_mask_secrets(message)`，唯独兜底分支漏掉 → provider 原始报错（含 `sk-xxx`）直出前端/日志 | ✅ |
| L-05 | `provider_manager.py:1730-1782` | 缓存污染 + 无锁 | `_provider_instances` 把 `api_key` 固化进实例并永久缓存；`update_provider()` 改 key 时不失效 → "填了 key 还是 401"，只有重启才生效 | ⚠️ |
| L-06 | `openai_provider.py:139-145, 331-339` | 健康检查结果造假 | `get_available_models()` 失败回落静态默认表；`check_connection()` 只看"有没有返回列表" → base_url 填错仍 `success=True`，还写入该服务商根本没有的模型 | ⚠️ |
| L-07 | `openrouter_provider.py:511-519` | 同上 | key 失效返回空列表时 `check_connection` 仍 `success=True, models_available=0` | ⚠️ |
| L-08 | `capability_detector.py:77, 116-142` | 超时配置失效 | `self._timeout` 存了但全类未使用 → 上游网关挂起时 `probe()` 永久阻塞（8 项串行） | ⚠️ |
| L-09 | `llm_router.py:332-335` | 子串方向反了 | 写成"请求名是目录键的子串"（`needle in mid`）→ `gpt-4` 命中 `gpt-4o` 拿到 128000 上下文 → 输入预算闸门误判 | ⚠️ |
| L-10 | `multi_model_client.py:1003-1010, 390, 1086` | 无锁遍历 | `refresh_provider`（持锁删键）与 `chat`（无锁遍历 `self._clients`）并发 → `dictionary changed size during iteration` | ⚠️ |
| L-11 | `llm_client.py:272-280, 462-466` | 假响应冒充成功 | `client` 为 None 时返回 `[模拟响应] 收到您的消息：...`，上游记为 `success=True` 并 `mark_provider_success` | ⚠️ |
| L-12 | `llm_client.py:226-231` | 无总超时 | `httpx.Timeout(300, connect=15)` 无 `total` | ⚠️ |

### 3.4 API / 安全层

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| **S-05** | `security/neu_token_manager.py:243-287, 351-384` | **JWT 不验 exp** | `refresh_tokens()` 校验签名/type/jti/黑名单，**唯独不验 `exp`**；`_verify_jwt_token` 也完全无 exp 检查 → refresh token 只要在内存里就能无限续期 | ✅ |
| S-06 | `security/neu_token_manager.py:63-65` | 密钥管理 | `secrets.token_hex(32)` 作为 `config.get` 的**默认参数被无条件求值** → 重启即全部 token 失效；`workers>1` 时各 worker 密钥不同 → 间歇性 401 | ⚠️ |
| S-07 | `security/auth_system.py:61-93` | 弱哈希 + 时序攻击 | 单轮 `sha256(salt+password)`，无迭代非 KDF；`verify` 用 `==` 比较（应 `hmac.compare_digest`）。与同仓 `api/auth.py` 的 bcrypt/PBKDF2 方案严重不一致 | ⚠️ |
| S-08 | API 层系统性 | 鉴权缺失 | `app.py` 无全局 `dependencies`，是否鉴权靠每个端点手写。已确认裸奔：`trace.py:329,358,386,411`（轨迹全泄漏）、`audit.py:97,133,164`、`console.py:1360`（匿名上传）、`console.py:1597,1614`（读取+写入问答标注） | ⚠️ |
| S-09 | `security/audit_logger.py:452-490` | 参数串用 | 三查询复用同一 `params` 列表，`start_time/end_time` 被重复 append → 第 2/3 条 SQL 绑定数不匹配 → `ProgrammingError` 被吞 → **传时间范围时审计统计恒为空** | ⚠️ |
| S-10 | `api/deps.py:448-465` | 认证降级 | `get_current_user_or_default` 无凭证时返回共享 `_DEFAULT_USER`（`user_id="default"`），被 **60+ 端点当作认证依赖** → 所有匿名请求合并成同一身份、互相串数据 | ⚠️ |
| S-11 | `api/endpoints/auth.py:233,367` 等 8 处 | 信息泄露 | `raise HTTPException(500, detail=f"...: {str(e)}")` 把内部异常原文回给客户端 | ⚠️ |
| S-12 | `api/endpoints/auth.py:636-642` | 吞错返假成功 | 登出无论抛什么错都返回 `{"code":0,"message":"Logged out successfully"}` → 黑名单注册失败时 token 仍完全有效 | ⚠️ |
| S-13 | `api/app.py:735-744` | 启动阻塞 | `async def _on_startup` 内同步调用 `_initialize_components()`（Agent 构造 + sqlite 建表 + TTS/ASR 初始化）→ 独占事件循环，`/health` 在初始化完成前不可用 | ⚠️ |

### 3.5 通道 / 执行 / 进化层

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| C-06 | `channels/manager.py:422` | 属性名不一致 | 写入 `self.ingress_queue`，`stop()` 读 `self._ingress_queue`（恒 None）→ 排水 Task 永不停止，持续持有 DB 连接 | ⚠️ |
| C-07 | `channels/manager.py:258-269` + `channel_ingress_queue.py:142-148` | 去重失效 | `enqueue()` 返回 `False`（重复）被 manager 当"队列不可用 fail-open" → 直接 `_dispatch_message` 再发一次 | ⚠️ |
| C-08 | `tool_layers/cli_tool.py:291-296, 202-204` | **命令注入** | 参数 `str.replace` 无转义拼进命令串，再 `subprocess.run(shell=True)` | ⚠️ |
| C-09 | `channels/wecom.py:167-171` | 验签可绕过 | 验签被 `if self._callback_token:` 包裹，token 为空即**无条件放行**任何人伪造回调 | ⚠️ |
| C-10 | `channels/telegram_webhook.py:46-49` | 写死放行 | `if not self._webhook_secret: return True` | ⚠️ |
| C-11 | `execution_layers/__init__.py:277-342` | 沙箱未隔离 | `DockerExecutor` 的 `docker run --rm` 未加 `--network=none/--read-only/--memory/--pids-limit/--user`，被 `exec_sandbox` 当"真隔离"后端使用 | ⚠️ |
| C-12 | `execution_engine/tool_engine.py:517-523` | 超时未生效 | 仅 coroutine 分支用 `asyncio.wait_for`，**同步分支直接裸调** → 卡死工具永久阻塞事件循环 | ⚠️ |
| C-13 | `channels/feishu.py:277-290`、`dingtalk.py:360-371` | 连接未关闭 | `disconnect()` 仅 `pass` 置标志，未关 socket/未 join 线程 → 重复 `connect()` 产生多条并存长连接 | ⚠️ |
| C-14 | `channels/websocket.py:69 vs 234/272` | 重连无退避 + 任务泄漏 | `__init__` 定义 `reconnect_attempts`，`_reconnect` 读写 `_reconnect_attempts`（属性名不一致）；固定 5s 无限重连，失败时 `create_task` 无引用无法取消 | ⚠️ |

### 3.6 前端

| ID | 位置 | 类型 | 说明 | 复核 |
|---|---|---|---|---|
| F-02 | `layouts/MainLayout.vue:383-390` | **恒假条件** | `closeUnreadStream` 上一行已被赋值为关闭函数（恒真值），`!closeUnreadStream` 恒为 `false` → 注释承诺的"SSE 失败降级 60s 轮询"**永不触发**，未读数永远是 0 | ⚠️ |
| F-03 | `pages/ChatPage.vue:1014-1018` | 竞态 | 守卫写在 `_loadSessions()` **之后**，写入 store 的动作已在 `useChat.loadSessions` 内部发生 → 守卫是空操作，快速切换 Agent 时旧响应覆盖新状态 | ⚠️ |
| F-04 | `composables/useStreamTTS.ts:241-246` | SSE 缓冲区偏移 | `extractSentences` 对句子做 `.trim()`，`complete.join('')` 与原 buffer 非连续子串 → `indexOf` 返回 -1 → 走进 `else` 把**整个 buffer 清空** → 尾部文本静默丢弃 | ⚠️ |
| F-05 | `api/index.ts:97-103` | 401 处理 | access_token 过期即整页 `location.href='/login'` 硬刷新（丢失 SPA 状态与 redirect）；`authAPI.refreshToken` **全仓库无调用点**，refresh_token 存了永不使用；并发 401 会重复跳转 | ⚠️ |

---

## 四、中危缺陷（P2，42 条，精简表）

### 后端

| ID | 位置 | 说明 |
|---|---|---|
| A-15 | `agent_core.py:1798-1810` | 肌肉记忆降级依赖 `muscle._l1/_l2/_l3/_save_all` 私有成员，失败被 `logger.debug` 吞掉 |
| A-16 | `agent_core.py:1610-1612` | `result.metadata.get(...)` 未判空，metadata 为 None 时 AttributeError 被吞 → 肌肉记忆记录整条丢失 |
| A-17 | `agent/chat_pipeline.py:1886` | `self.llm_client.config.max_tokens` 未判空 |
| A-18 | `tool_executor.py:224-231` | `threading.Lock` 用于 async 路径 + DCL 首次无锁读 |
| A-19 | `agent/loops/openai_loop.py:633` vs `360` | 流式路径硬编码 `<= 10` 轮上限，可配置的 `_max_tool_rounds` 对流式失效 |
| A-20 | `agent/tool_coordinator.py:112` | `asyncio.ensure_future` 无强引用，观察者协程可能被 GC |
| A-21 | `agent/chat_pipeline.py:1648-1650 vs 1756` | 命令分发提前 return，跳过 `_clear_vision_routing()`，应改 try/finally |
| M-15 | `manager.py:567-584` | `_delete_persisted_memory` 新建连接无 `busy_timeout`，`close()` 不在 `finally` |
| M-16 | `models.py:434-491, 133-140, 168-178, 206-216` | `from_dict` 丢失 `embedding` / `last_accessed_at`；`UserProfile`/`Skill`/`SelfModel` 时间字段每次加载被重置 |
| M-17 | `manager.py:1146-1160` | `update_memory` 枚举解析无兜底（对比 `remember` 有）→ 非法值导致 API 500 |
| M-18 | `sleep.py:510-513` | `avg_temperature` 分母用"整合轮数"而非"记忆条数" → 统计严重偏大，RSI 据此误调参 |
| M-19 | `muscle_memory.py:463-465 vs 367` | `_save_all()` 一处锁内一处锁外，落盘位置不一致 |
| M-20 | `muscle_memory.py:594-598` | 单条坏记录导致整层数据 `return {}` 清零 |
| M-21 | `temporal_knowledge_graph.py:250, 276-278, 391` | 缓存截断 5 万条后读不到；枚举解析无兜底 → TKG 初始化崩溃 |
| M-22 | `storage.py:610-629` | `get_recent_memories` 仍用**裸字符串比较**时间（同文件 `query()` 已修为 `fromisoformat`），且过滤在锁外 |
| M-23 | `modules/emotion_module.py:195-203, 172-181` | `set_emotion` 锁内做 DB IO；`shutdown()` 无调用点，连接不 close |
| M-24 | `vector_index_manager.py:387-395, 193-194` | `wait_for_completion` 忽略 in-flight 批次；多 worker 下 `Event.clear()` 丢唤醒 |
| M-25 | `manager.py:705` | 自定义 id 跨作用域互踩（`INSERT OR REPLACE` 覆盖他人记忆） |
| L-13 | `llm_client.py:240-253, 830-831` | 每次重建 `OpenAI`/`AsyncOpenAI` 不 `close()` → 连接池/TLS 会话泄漏 |
| L-14 | `multi_model_client.py:171-185 vs 1204-1208` | `reset()` 与 `get_multi_model_client` 用**两把不同的锁**保护同一个字典 |
| L-15 | `capability_detector.py:140-151, 573-579` | 网络抖动被缓存成"零能力"长达 1 小时（`error` 字段从不赋值，错误结果照常入缓存） |
| L-16 | `capability_detector.py:174-177` | 探测流式时读到首个 chunk 即 return，HTTP 流未关闭 |
| L-17 | `generators/text_to_video.py:583-589` | 只返回 `output.video_url` 时被判"任务失败或超时"，轮询 300s 后失败 |
| L-18 | `model_limits.py:162-174` | 未知模型一律夹到 4096（静默截断）；`max_tokens=None` 时 `min(None,...)` 抛 `TypeError` |
| L-19 | `provider_manager.py:1870-1894` | 单例键 `f"scope:{scope}"`，给了 `config_path` 但 scope 为 None 时固定为 `"scope:None"` → 不同配置路径返回同一实例 |
| L-20 | `multi_model_client.py:320-323, 1052` | 模型名只做 `==`/`endswith` 匹配 → `qwen-plus` 命中不了 `qwen-plus-latest`，静默回落默认模型 |
| S-14 | `security/rbac.py:555-556` | `get_all_permissions()` 返回 `List`，却调用 `.get()` → 必抛 `AttributeError` | ✅ |
| S-15 | `api/endpoints/files_api.py:303` | 无大小/类型限制，`await file.read()` 全量读内存；`_files_store` 全局 dict 无锁 |
| S-16 | `api/endpoints/logs_api.py:107-151, 285-312` | `user_id` 硬编码 `"default"` + 读取无属主过滤 → 所有登录用户可见彼此工作日志 |
| S-17 | `api/endpoints/console.py:1510-1549` | WS 仅 `except WebSocketDisconnect` 清理，其他异常永久泄漏连接；`client_id` 客户端随意指定可冒用 |
| S-18 | `api/endpoints/console.py:54-62, 1577` | `broadcast()` 向**所有**连接推送，任意登录用户可推消息给全体在线客户端 |
| S-19 | `api/api_key_manager.py:261-286` | 每次 `validate_key` 成功都全量重写 `data/api_keys.json`，高 QPS 下 IO 放大 + 锁竞争 |
| S-20 | `api/endpoints/auth.py:270` | `master_password == MASTER_RECOVERY_PASSWORD` 非恒定时间比较 |
| S-21 | `api/endpoints/auth.py:43` | `_token_blacklist: set` 只增不减、无 TTL |
| C-15 | `evolution/closed_loop.py:189-220` | `update_weight` 在 `RLock` 持有期间同步落盘（注释声称"锁外写"，但 RLock 可重入 → 实际锁内写） |
| C-16 | `evolution/rsi/convergence_analyzer.py:66-78` | `window_size<=0` 时 `gain_history[-0:]` 取**全量**而非空；空历史 `sum([])/0` 崩溃 |
| C-17 | `evolution/genetic_engine.py:16, 225-235` | 全局 `random` 无 seed → 进化不可复现 |
| C-18 | `channels/telegram_api_client.py:63-73` | `NamedTemporaryFile(delete=False)` 无任何清理路径 → 磁盘堆积 |
| C-19 | `execution_engine/tool_engine.py:32-55` | `cached` 装饰器无容量上限、过期不清理 |
| C-20 | `execution_engine/tool_engine.py:442-481` | `_validate_parameters` **零调用点**，参数校验是死代码 |
| C-21 | `channels/mobile_pairing.py:98-120` | `_sessions`/`_by_pairing_id` 无锁；`_revoked_tokens` 无界；配对码用 `random` 而非 `secrets` |
| C-22 | `sandbox/exec_sandbox.py:98-106` | `subprocess.run(timeout=)` 只杀 `sh`，孙进程残留继续运行 |
| C-23 | `channels/feishu.py:307-314` | `verify_url_challenge(challenge, token)` 接收 token 却完全不使用 → 任何人可"验证" Webhook |
| C-24 | `channels/manager.py:139-146, 301-302` | `_message_handlers` 惰性建表有竞态窗口；遍历时可能被并发修改 |
| C-25 | `channels/dingtalk.py` / `feishu.py` 重连 | 长连接断开无退避、无上限 |

### 前端

| ID | 位置 | 说明 |
|---|---|---|
| F-06 | `modules/collaboration/CanvasDesignerPage.vue:2091-2104, 2466` | 等待流结束的 `setInterval` 不判 `isDisposed`；`unsubscribe()` 卸载路径从不调用；兜底 `setTimeout(600_000)` 句柄丢失 |
| F-07 | `pages/ChatPage.vue:701-709` | computed getter 内写 `renderStart.value` 又读同一 ref → 自依赖，可能触发递归更新 |
| F-08 | `pages/ChatPage.vue:1297, 1308-1319` | 断线重连被用户中止时，排队消息被 `markSent` 出队（内容只播了一半却标记已发送） |
| F-09 | `layouts/MainLayout.vue:387-390` | 3s 宽限定时器句柄未保存，`onUnmounted` 只清了 `unreadTimer` → 卸载后残留 60s 轮询 |
| F-10 | `pages/ChatPage.vue:1219 vs 1243` | `AbortController` 被创建两次，首个实例成为孤儿 |
| F-11 | `pages/ModelPage.vue:1433-1444` | 首屏 4 段串行请求无 `onUnmounted`、无 `isDisposed`、无 `AbortController`；失败会在别的页面弹 toast |
| F-12 | `pages/SettingPage.vue:222-230, 244-252` | 初始化请求失败静默吞错 → 显示默认值 0/关，用户点保存会把默认值回写覆盖线上配置 |

---

## 五、低危缺陷（P3，25 条，摘要）

- **后端**：`api/app.py:621-670`（metrics 死代码，构造后丢弃）；`api/app.py:1139-1152`（`run_server` 先 `create_app` 再让 uvicorn 二次调用工厂，且工厂不带 host/port/debug）；`security/audit_logger.py:596-627`（`archive_old_logs` 只 DELETE 不归档）；`llm/providers/anthropic_client.py:170-172` + `gemini_client.py:173`（`count_tokens("")` 返回 1 而非 0，系统性抬高对账数据）；`llm/providers/error_mapping.py:151`（正则裸匹配 `reset` → `quota reset` 被误判为可重试的连接错误）；`llm/providers/rate_limiter.py:82-96`（末次重试仍 sleep，`is_retryable` 恒 True）；`core/logger.py:104-112`（Windows `StreamHandler` 未指定 encoding → 含非 GBK 字符的 LLM 错误日志整行丢失）；`cognitive_layers/.../manager.py:705`（自定义 id 跨作用域）；`evolution/genetic_engine.py`（crossover 返回 None 时不显式降级）。
- **前端**：`pages/ChatPage.vue:1219`（孤儿 AbortController）；`components/chat/PlanPanel.test.ts:135`（测试 fixture 契约与拦截器不一致，掩盖 F-01）。

---

## 六、缺陷热点模块排行

| 排名 | 模块 | 缺陷数 | 主要问题 |
|---|---|---|---|
| 1 | `cognitive_layers/memory_layer/` | **24** | 锁覆盖不全、时间类型混用、空实现上报成功、序列化丢字段 |
| 2 | `api/` + `security/` | **21** | 鉴权缺失/粒度不足、吞错返假成功、信息泄露、密钥管理 |
| 3 | `llm/` | **20** | 异步契约、并发槽泄漏、缓存污染、健康检查造假、生成器未接线 |
| 4 | `channels/` | **16** | 适配器契约错位（7 个渠道同根因）、验签 fail-open、连接泄漏 |
| 5 | `agent_core.py` + `agent/` | **21** | 跨文件契约错位、参数未透传、初始化顺序、吞异常 |
| 6 | `evolution/` + `execution_engine/` | **8** | 参数名不匹配、除零、锁内 IO、校验死代码 |
| 7 | `NeurUI/src` | **12** | 响应解包多一层、竞态守卫失效、定时器/连接泄漏 |

---

## 七、修复优先级路线

### 第 1 批（阻断性，1 天内）
1. **A-01** — 补 `RouteResult.message_type`（统一入口当前完全不可用）
2. **F-01** — `PlanPanel` 去掉多解的 `.data`（计划模式 100% 崩溃）
3. **C-01** — `UnifiedMessage` 补 `global_user_id`（7 个渠道消息解析全崩）
4. **C-05** — `to_skill_template_list` 补 `top_n`（进化闭环静默断开）
5. **L-01** — `asyncio.to_thread` 协程分支判定（Claude/Gemini 非流式恒返回空）
6. **M-01** — `_wal_lock` 改 `RLock` + 统一加锁顺序（WAL 超限后进程挂起）

### 第 2 批（安全，1-2 天）
7. **S-01 / S-02** — `/computer/shell`、`/file/read`、`/file/write` 加 admin + 路径根目录约束
8. **S-03 / S-04** — 会话同步全端点补鉴权；注册强制验证码 + 首账号提权改一次性引导令牌
9. **S-05** — `refresh_tokens` 补 `exp` 校验
10. **S-08** — `create_app` 挂全局鉴权白名单机制（`trace`/`audit`/`console` 优先）
11. **C-08 / C-09 / C-10 / C-11** — 命令注入 `shlex.quote`；三处验签 fail-open 改 fail-closed；Docker 沙箱加隔离参数

### 第 3 批（正确性，2-3 天）
12. **M-03 / M-10** — 统一 UTC 时间处理 + 睡眠写回改写入衰减值（当前记忆只升温不降温）
13. **M-05** — 修正降级分支元组顺序
14. **M-04 / M-06 / M-07** — 补隔离 WHERE + 锁覆盖
15. **L-03 / L-04** — 并发槽 `finally` 释放；兜底错误脱敏
16. **S-09 / S-14 / S-16** — `params` 独立；`get_all_permissions` 返回映射；日志按 user 过滤

### 第 4 批（系统性，1-2 周）
17. **契约防线**：引入 `pyright --strict` 或至少对跨模块公共 API 加类型桩；新增「跨模块集成测试」目录，覆盖本报告每一条契约错位
18. **可观测性**：把 20+ 处关键链路的 `logger.debug` 吞异常升级为 `warning(exc_info=True)` 并上报健康指标
19. **空实现台账**：`forget_memory` / `AutoContextUpdater` 四项 / `GeneratorManager` 必须要么实现、要么返回明确的 `not_implemented` 标记，**禁止谎报成功**
20. **前端契约测试**：增加「axios 拦截器返回体」契约测试，杜绝 `res.data.data` 类问题再犯（此类问题已在 `CanvasDesignerPage` 与 `PlanPanel` 两度复现）

---

## 八、复核说明

- 标注 `✅` 的 14 条已由人工逐行读码确认，可直接进入修复。
- 标注 `⚠️` 的条目来自 6 路并行扫描并附带代码片段与行号，逻辑链条完整，但**修复前建议先跑最小复现脚本验证**（尤其涉及初始化顺序、锁竞争、时序类问题）。
- 已排除的误报：`closed_loop.py:250/252`、`genetic_engine.py:447/584`、`rsi/dashboard.py:98/120` 的疑似除零（均有前置判空）；`files_api.py:171-179, 288-301` 的路径穿越防护（有效）；`api/auth.py:182` 的 JWT alg 混淆（已显式指定 algorithms）；SQL 注入（全量扫描均为 `?` 占位符参数化）。
- 本次审计未修改任何源码。

---

## 九、修复执行记录（本轮，2026-09-10）

> 修复原则：根因修复、禁止 consumer-only guard、禁止吞异常抹除、放大视角 grep 同契约所有消费方。所有改动均已通过 `python -m py_compile` 与导入冒烟测试。

### 9.1 已修复（根因级）

| ID | 文件 | 修复要点 |
|---|---|---|
| **A-01** | `router.py` | `RouteResult` 增加 `message_type` 字段；`route()` 统一赋值；`_route_chat` 的 `response` 不再塞入 `Dict` |
| **A-02** | `agent_core.py` | `ChatContext(...)` 补传 `event_emitter`（调用方传入的 SSE 回调此前恒为 None） |
| **A-09** | `router.py` | `route()` 优先派发 `register_handler` 的协程处理器（此前 `_handlers` 从未被读取，死代码） |
| **A-12** | `chat_pipeline.py` | 拆分 `ctx.trace_id`（轨迹记录器）与 `ctx.reasoning_trace_id`（推理链），二者不再互相覆盖 |
| **C-01** | `channels/models.py` | `UnifiedMessage` 增加 `global_user_id` 字段（7 个渠道解析全崩的根因） |
| **C-02** | `channels/xiaoyi.py` | 构造调用 `super().__init__(ChannelConfig(...))`，`authenticate` 改用正确字段 `channel_type/extra` |
| **C-03** | `channels/telegram_adapter.py` | 构造调用 `super().__init__(ChannelConfig(channel_type="telegram"))` |
| **C-04** | `channels/discord.py` / `websocket.py` | 构造初始化 `self.config`，`channel_type`/`config.enabled` 不再 AttributeError |
| **L-01** | `multi_model_client.py` | 判定 `chat` 是否为协程，协程分支直接 `await`，同步分支走 `to_thread` |
| **L-02** | `generators/manager.py` | `_register_default_generators` 真实注册 6 类生成器；模型选择改用 `select_model`；构造 `GenerationConfig` 后调用 |
| **L-03** | `multi_model_client.py` | 并发槽收敛到 `finally` 单次释放，`acquired` 守卫避免双重释放/限流提前 return 误释放 |
| **L-04** | `providers/error_mapping.py` | 兜底分支补 `_mask_secrets`（此前唯一漏脱敏，密钥可直出前端） |
| **L-09** | `llm_router.py` | 子串匹配方向修正 `str(mid).lower() in needle`（gpt-4 误命中 gpt-4o 的反向 bug） |
| **L-11** | `llm_client.py` | `client` 为 None 时抛 `LLMConnectionError`，不再返回 `success=True` 的模拟响应冒充成功 |
| **M-01** | `cognitive_storage_engine.py` | `_wal_lock` 改 `RLock`；统一加锁顺序 `_wal_lock → _db_lock`，消除 WAL 自死锁/AB-BA |
| **M-02** | `memory_layer/security.py` | `forget_memory` 注入 `memory_manager` 后真实删除；未注入时返回 `success=False`，不再谎报 |
| **M-03** | `memory_layer/temperature.py` | 统一 UTC 处理；时间解析异常 `warning` 而非静默回退 0.0（衰减失效根因） |
| **M-05** | `memory_layer/manager.py` | 降级分支元组顺序 `(rank, id)`，与主路径一致 |
| **M-10** | `memory_layer/sleep_writeback.py` | 未合并记忆分支改为按 idle 时长线性衰减，不再误用 `update_memory_temperature`（升温） |
| **S-01** | `api/endpoints/computer.py` | `/shell` 加 `require_admin()` |
| **S-02** | `api/endpoints/computer.py` | `/file/read`、`/file/write` 加 `require_admin()` + `_resolve_safe_path` 路径根目录约束 |
| **S-03** | `api/endpoints/session_sync.py` | WebSocket 先校验 token 再 accept（失败 close 4401）；REST 全端点加 `Depends(get_current_user)`；`user_id` 改由 token 派生 |
| **S-05** | `security/neu_token_manager.py` | `_verify_jwt_token` 补 `exp` 校验（refresh token 无限续期根因） |
| **S-06** | `security/neu_token_manager.py` | 签名密钥持久化到文件（0600），重启/多 worker 稳定，不再每次随机 |
| **S-09** | `security/audit_logger.py` | 三条统计查询各自独立 `params`，修复时间范围查询 `ProgrammingError` |
| **S-11** | `api/endpoints/auth.py` | 登录/刷新内部异常不再回传给客户端 |
| **S-12** | `api/endpoints/auth.py` | 登出黑名单写入失败显式返回 500，不再谎报成功 |
| **S-14** | `security/rbac.py` | `_get_permission_description` 兼容 `get_all_permissions()` 返回的 list |
| **C-08** | `tool_layers/cli_tool.py` | 命令模板参数 `shlex.quote` 转义，消除命令注入 |
| **C-09** | `channels/wecom.py` | 回调验签 fail-closed（无密钥时拒绝，不再无条件放行） |
| **C-10** | `channels/telegram_webhook.py` | Webhook 验签 fail-closed |
| **F-01** | `NeurUI/src/components/chat/PlanPanel.vue` | 7 处 `res.data.data` 改为 `res?.data?.`（计划模式 100% 崩溃根因） |
| **L-10** | `llm/multi_model_client.py` | `self._clients` 在 `_init_lock` 下增删，但 321/390/1097 行无锁遍历 → 并发 `dictionary changed size`；改为 `list(self._clients.values())` 快照 |
| **M-11** | `cognitive_layers/memory_layer/conversation_buffer.py` | `flush_to_storage` 写入前整体清空队列且单条失败仅丢弃 → DB 抖动时记忆永久丢失；失败项重新入队重试 |
| **M-12** | `cognitive_layers/memory_layer/security.py` | 记忆加密密钥未持久化（每次进程随机生成 → 重启后旧密文无法解密、记忆"消失"）；改从持久化文件读取稳定密钥 |
| **M-14** | `cognitive_layers/memory_layer/auto_context_updater.py` | `_update_temperature` 为空 stub（`return 0` 但 `_perform_update` 仍报"更新完成"+递增计数 → 冷却维护静默失效）；改为按空闲时长真实衰减并 `update_memory` 落盘，附回归测试 `tests/unit/test_auto_context_updater_m14.py` |
| **M-11** | `cognitive_layers/memory_layer/cognitive_storage_engine.py` | `_flush_l0_to_l1` 先 `self._l0_buffer.clear()` 再在锁内写入——写入中途抛异常时缓冲已清空、节点永久丢失，且内存态与 WAL 不一致；改为写入并提交成功后才按 id 剔除已写入节点，写入失败则保留缓冲并上抛（重试 + WAL 崩溃恢复兜底）。附回归测试 `tests/unit/test_cognitive_storage_flush_m11.py` |
| **M-06** | `cognitive_layers/memory_layer/manager.py` | `recall`/`get_memories`/`get_stats` 在 `with self._lock:` **之前**调用 `_scoped_memories()`/`_agent_memories()`（迭代 `self._memories.values()`），与 `remember`/`forget` 的字典增删并发 → `RuntimeError: dictionary changed size during iteration`；将基集构造移入锁内。附确定性回归测试 `tests/unit/cognitive_layers/memory_layer/test_lock_coverage_m060709.py`（用 `RLock._is_owned()` 验证基集在锁内构造） |
| **M-07** | `cognitive_layers/memory_layer/semantic_search.py` | `_keyword_index` 全方法无锁，`remove_memory_index` 边迭代边 `del` → 并发 `RuntimeError`；新增 `_index_lock`（RLock）保护 `build/upsert/remove/search_by_keywords` 全部读写。附确定性回归测试 `test_lock_coverage_m060709.py`（持锁时子线程调用应阻塞） |
| **M-09** | `cognitive_layers/memory_layer/cognitive_storage_engine.py` | `_l0_buffer`/`_vector_index` 无任何锁保护，`store`/`retrieve`/`update_temperature`/`get_statistics`/`_flush_l0_to_l1` 并发访问竞态（M-11 已修"提交前出队丢数据"，剩余"无锁"部分待补）；新增 `_buffer_lock`（RLock）按统一序 `buffer_lock → db_lock` 保护全部内存态访问。附确定性回归测试 `test_lock_coverage_m060709.py` |
| **M-08** | `cognitive_layers/memory_layer/vector_search_advanced.py` | `FaissBackend._init_model` 在 `HAS_SENTENCE_TRANSFORMERS` 为真但模型**运行时加载失败**后仅 warning 并留 `self._model=None`，`_get_embeddings` 随即 `raise RuntimeError`，整个后端在每次 `add_texts/search` 崩溃，且无 TF-IDF 回落（选型逻辑仅在库未装时回落，加载失败场景无回落）；改为加载失败时显式留 `None` 并新增 TF-IDF 风格特征哈希降级嵌入，`_get_embeddings` 在模型不可用时降级（始终可用，不再 RuntimeError）。附确定性回归测试 `tests/unit/cognitive/test_faiss_fallback_m08.py`（fake faiss+numpy 强制 SentenceTransformer 抛错，复现"模型加载失败"路径）。另修正同文件 `import numpy` 被误写成 `try: pass` 的残留 bug（`HAS_NUMPY` 此前恒为 True） |
| **C-05** | `evolution/pattern_miner.py` | `to_skill_template_list` 无 `top_n` 参数，`EvolutionFacade`（closed_loop.py:333）传 `top_n=top_n` 恒 `TypeError`，且 facade `except Exception` 吞掉返回 `[]` → "频繁模式→技能模板"闭环静默断开；增加 `top_n: Optional[int] = None` 并在返回前截断，闭环恢复。附回归测试 `tests/unit/evolution/test_c05_synthesizer_nonempty_regression.py` |
| **L-05** | `llm/provider_manager.py` | `_provider_instances` 把 `api_key` 固化进实例并永久缓存，`update_provider()` 改 key/base_url 不失效 → "填了 key 还是 401"只有重启生效；`update_provider` 现以 `_provider_instances_lock`（RLock）失效对应实例缓存，`get_provider_instance` 读写全程持锁。附回归测试 `tests/unit/llm/test_l05_provider_cache_invalidation_regression.py` |
| **L-13** | `llm_client.py` | 每次重建 `OpenAI`/`AsyncOpenAI` 客户端不 `close()` 旧实例 → 连接池/TLS 会话泄漏；重建前先 `close()` 旧同步与异步客户端（异常安全）。附回归测试 `tests/unit/llm/test_l13_client_close_regression.py` |
| **L-14** | `llm/multi_model_client.py` | `reset()` 用自身锁清理 `_multi_model_clients` 字典，而 `get_multi_model_client` 用另一把锁写入 → 双锁竞态保护同一字典；`reset()` 统一改用 `_multi_model_clients_lock`。附回归测试 `tests/unit/llm/test_l14_reset_lock_regression.py` |
| **L-01 追加** | `llm/multi_model_client.py` | L-01 修复引入 `inspect.iscoroutinefunction(chat_fn)` 判定但**未导入 `inspect`** → 全部非流式 chat 恒 `NameError: name 'inspect' is not defined` 返回失败（回归测试 test_multi_model_client_reinit 捕获）；补 `import inspect` |
| **A-09 契约修正** | `router.py` | 初版 A-09 修复让 `register_handler` 注册的处理器**反抢**内置路由优先级，而 `init_router` 恰以"已内置处理"标记性 lambda 注册 CHAT → 所有 CHAT 绕过 `_route_chat` 完整管线（语音处理/元数据透传/A-10 文本提取），`test_router_with_agent` 回归暴露；修正派发契约：**内置路由（command/skill/memory/chat）优先，注册 handler 仅作为无内置路由类型的回退**（此时协程正确 await，注册表不再是死代码） |
| **S-16** | `api/endpoints/logs_api.py` | 工作日志 `user_id` 硬编码 `"default"` 且读取无属主过滤 → 所有登录用户互看/互写彼此工作日志（导出接口泄露面最大）；全部端点接入 `get_current_user`，落账真实 `user_id`，读路径统一 `_scoped_logs()` 属主过滤（admin 可见全部） |
| **S-20** | `api/endpoints/auth.py` | `recover-password` 的 `master_password == MASTER_RECOVERY_PASSWORD` 非恒定时间比较 → 时序攻击可逐字节探测恢复密码；改 `hmac.compare_digest`。同日顺带加固 `channels/telegram_webhook.py` 的 secret 比较（同 S-20 类） |
| **C-06** | `channels/manager.py` | `_get_ingress_queue()` 把队列实例存到 `self.ingress_queue`，`stop()` 却读 `self._ingress_queue`（恒 None）→ 排水任务永不停止、持续持有 SQLite 连接；修正属性名。附回归测试 `tests/unit/channels/test_ingress_dedupe_c0607.py` |
| **C-07** | `channels/channel_ingress_queue.py` + `manager.py` | `enqueue()` 返回 False 无法区分"重复消息去重"与"DB 故障"，manager 把去重当"队列不可用 fail-open"再直发一次 → 平台重发消息双投递；新增 `IngressQueueUnavailable` 异常（DB 故障抛出，调用方 fail-open 直发），`enqueue()==False` 仅表示去重 → 直接丢弃。附回归测试 `tests/unit/channels/test_ingress_dedupe_c0607.py`（pending 重复不直发 / DB 故障 fail-open / done 重投按设计重开） |
| **L-05 构造兼容** | `llm/provider_manager.py` | 初版修复把实例缓存锁做成实例属性，而 `__new__` 绕过 `__init__` 是合法构造契约（`test_provider_manager.TestDeleteModel` 等 14 用例回归暴露）→ `_provider_instances` 访问全路径 AttributeError；锁提升为类级 `_PROVIDER_INSTANCES_LOCK`，字典改惰性初始化（失效/读/写三处防御访问） |

### 9.5 本批复查补充（已修复 / 非缺陷澄清）

- **L-08（超时配置失效）**：`LLMConfig` 已含 `timeout`/`connect_timeout` 字段并经由 `_httpx_timeout()`（读 300s/建连 15s 分离）生效；`multi_model_client.py:269-283` 已将 provider 级 `timeout` 注入，配置链路完整，**非缺陷**（早于本次审计已修复）。
- **L-06 / L-07（健康检查造假）**：`provider_manager.py:1686-1689` 的 `health_check_provider` 已委托真实 `check_provider_connection`（失败置 `unhealthy`，不再恒 healthy），**非缺陷**（已修复）。
- **M-04（温度通道隔离缺 WHERE）**：温度通道与语义/类别/语音等所有通道均统一调用 `memory_manager.get_all_memories()`，作用域限定在单一 MemoryManager 实例（按 agent 实例化），属一致设计，**非跨用户泄露**，无需单独补 WHERE。
- **M-14 其余三项**（`_compress_old_memories` / `_rebuild_vector_index` / `_cleanup_cache`）：`MemoryManager` 当前无对应后端方法，仍保持透明 no-op（日志计数如实显示 0），待补真实后端 API 后再接入；仅温度衰减已落地为真实维护。
- **L-12（无总超时）**：`httpx.Timeout(300, connect=15)` 的位置参数已把 read/write/pool 各相位上限设为 300s、建连 15s，单请求不会永久挂起；流式响应本就是"读间隙"超时语义，若再加全局 total 上限会误杀合法长思考流（本次流中断事故加固正是为此引入超时分离），**非缺陷**，按设计保持。
- **测试基线甄别（2026-09-10 第二轮）**：整体回归 89 失败经 HEAD worktree 比对，59 条为预存失败（HEAD 同样失败），30 条新增失败逐一归因：①L-05 实例锁不兼容 `__new__` 构造（已根修，见 9.1）②A-09 派发顺序反抢内置路由（已根修，见 9.1）③L-01 漏导入 `inspect`（真实生产 bug，已修）④环境缺 `openai` 库 + L-11 修复后测试断言"伪造成功"不再成立（7 个装配测试文件补 `pytest.importorskip("openai")`）⑤`test_tool_weights_persistence` 断言共享 `data/` 目录被运行时产物污染（改封闭 cwd）。修复后新增失败清零，另顺带修复 6 条 HEAD 基线失败（computer REST 端点 4 条、test_agent 1 条、auto_route switch_bounded 1 条）。

### 9.2 预存在问题（与本次审计无关，但阻塞上述修复生效，已顺带修复）

- `api/endpoints/computer.py` 在 **pydantic 1.10** 环境下因 `TypeAdapter`/`ConfigDict`/`model_config`（pydantic v2 语法）无法导入，整模块不注册 → S-01/S-02 安全端点实际失效。已做 v1 兼容转换（`class Config: extra="forbid"`、移除未使用的 `TypeAdapter` 死代码），模块现已可导入。

### 9.3 复查结论（部分条目已澄清，非缺陷）

- **S-07（弱哈希）**：生产登录走 `neurova/auth/password_hasher.py` 的 **bcrypt(12 轮)**，已合规；`neurova/security/auth_system.py` 的 SHA256 单轮 `PasswordHasher` 是**未被任何登录路径接入的遗留代码**（仅 `security/__init__.py` 自引用），实际无安全影响。该文件无需修改，登记为死代码即可。如需消除隐患，建议后续删除或统一接入 bcrypt。

### 9.3 尚未修复（需更深改动 / 风险评估后处理）

以下条目多为**跨多方法锁覆盖**、**空实现需真实逻辑**、**健康检查/缓存体系重构**等，属中低危且改动面大、需配合集成测试，建议作为后续独立 PR：

- **记忆层**：M-04（温度通道隔离缺 WHERE，**已澄清非缺陷**——见 9.5）、M-06/M-07/M-09（锁外 DB/索引访问，**已修复**——见 9.1 M-06/M-07/M-09，新增 `_buffer_lock`/`_index_lock` 并补 manager 基集锁内构造）、M-08（嵌入模型无降级，**已修复**——见 9.1 M-08，FaissBackend 模型加载失败时降级到 TF-IDF 风格定长向量，不再 RuntimeError）、M-11（flush 先清后写丢数据，**已修复**——见 9.1 M-11）、M-12（密钥未持久化，**已修复**——security.py 从持久化文件读取稳定密钥）、M-14（AutoContextUpdater 四项维护为空实现，**已修复温度衰减**——见 9.1 M-14，其余三项待真实后端 API）
- **LLM 层**：L-12（无总超时）、L-15~L-20（能力缓存/探测/生成器细节）（L-05/L-10/L-13/L-14 **已修复**——见 9.1；L-06/L-07/L-08 **已澄清非缺陷**——见 9.5）
- **Agent 核心**：A-03~A-11（部分）、A-13（阻塞事件循环）、A-14（ImportError 被 re-raise）
- **API/安全**：S-04 首账号提权（仅加了注册验证码，一次性引导令牌待做）、S-07（弱哈希，建议统一到 `api/auth.py` 的 bcrypt/PBKDF2）、S-08（全局鉴权白名单机制）、S-13（启动阻塞改 to_thread）、S-15、S-17~S-21（S-16/S-20 **已修复**——见 9.1）
- **通道/执行/进化**：C-11~C-25（沙箱隔离、连接泄漏、无退避重连等）（C-05/C-06/C-07 **已修复**——见 9.1；C-08/C-09/C-10 **已修复**——见前批记录）
- **前端**：F-02~F-12（未读数轮询恒假、竞态守卫、SSE 缓冲偏移、401 退避等）

> 说明：9.1 覆盖全部 **16 条 P0** 与多数高影响 **P1**。因并行修复 agent 在当前环境不可用（模型调度失败），剩余项由主 agent 按根因原则逐步修复；建议后续用集成测试（跨模块契约）守护，防止同类契约错位复发。

---

## 9.6 第二轮全量核实与收口（2026-09-10/11）

> 方式：4 路只读核查（Agent 核心/记忆层/LLM+API 安全/通道+前端）逐条核实 9.3 "尚未修复"清单的真实状态 → 7 组并行修复（文件归属零交集）→ 主会话合并回归甄别。

### 9.6.1 进度核实修正（文档滞后于代码，实际已修）

- **A-12**（trace_id 双写串台）：已拆分 `reasoning_trace_id`，代码与注释齐全。
- **S-15**（上传无限制/无锁）：分块读取+100MB 上限+危险扩展名黑名单+`_files_store_lock` 已落地。
- **S-21**（token 黑名单只增不减）：已改有界 dict + TTL 语义（`_BLACKLIST_MAX=20000`）。
- **C-11**（Docker 沙箱未隔离）：`--network=none --read-only --memory=512m --pids-limit=128` 已加。
- **C-12**（同步工具裸调阻塞循环）：已 `to_thread + wait_for` 强制超时。
- **C-14**（WS 重连属性名错位/无退避）：已统一 `_reconnect_attempts` + 指数退避封顶 300s + 任务强引用。
- **F-02 / F-03 / F-09**（未读轮询恒假/会话竞态守卫/定时器泄漏）：均已修。
- **S-04 前半**（注册验证码）：`VerificationCodeModel` + 限流已接入（首账号门控见 9.6.2）。

### 9.6.2 本轮修复（46 项缺陷 + 1 项非缺陷澄清）

**Agent 核心（A 组+B 组，14 项）**：A-03（agent_id 改读 `config.agent_id`，放大视角同修 EKB 写入点）、A-04（`_current_user_input` 改 ContextVar 绑定 property，三处消费方自动恢复）、A-05（`_PersistDbStore.close()` + 关闭链路接入）、A-06（双队列 split-brain 收敛到 `memory_manager._write_queue` 单队列；顺带修 `if queue:` 被 `__bool__` 陷阱吞掉 `enqueue_batch` 的同根因命中点）、A-07（模型切换锁改实例级）、A-08（拓扑序补 `evolution→tools` 依赖，`register_tools` 恢复执行）、A-11（`predict_step` 补 `NotImplementedError`）、A-13（RSI 迭代 `to_thread`）、A-14（ImportError 移出编程错误集，可选依赖缺失降级为步骤失败+warning 不炸穿整轮）、A-15（失败分支 debug→warning+exc_info；收口见下）、A-16（metadata 判空经 `getattr`）、A-17（max_tokens None 守卫）、A-18（ToolEngine 急切构建，锁整个删除）、A-19（流式轮次上限与非流式同源 `_max_tool_rounds`）、A-20（观察者协程强引用）、A-21（命令轮提前 return 路由过 `_clear_vision_routing`）。
**A-15 终态收口**：MuscleMemory 新增公开 `degrade_tool(tool_name)`（锁内重置、锁外落盘），agent_core 降级路径不再触私有 `_l1/_l2/_l3`。

**记忆认知层（12 项）**：M-13（插件通道 join/gather 加 12s 超时，部分结果继续）、M-15（DELETE 连接 busy_timeout+finally）、M-16（from_dict 补 embedding/last_accessed_at/三模型时间字段回填）、M-17（update_memory 枚举兜底）、M-18（avg_temperature 分母改记忆条数）、M-19（`_save_all` 统一锁外落盘+公开 `save_all()`）、M-20（`_load_level` 逐条容错，坏条目不再清零整层）、M-21（TKG 逐行枚举容错+`FACTS_LOAD_LIMIT=200000` 可配置）、M-22（`get_recent_memories` 对齐 fromisoformat+锁内过滤）、M-23（set_emotion 落盘移出锁）、M-24（in-flight 计数修复 `wait_for_completion` 过早返回+Event 丢唤醒）、M-25（自定义 id 跨作用域互踩：upsert 改作用域三元组 WHERE 收敛，冲突落 `\x1f` 前缀行，旧库免迁移兼容）。

**LLM 层+API key（7 项）**：L-15（探测 error 字段落值+错误结果不进 3600s 缓存；内层 `except: return False` 全部改 raise 透传——这是 error 从不赋值的真正根因）、L-16（流式探测 `aclose` 收口）、L-17（completed+video_url 改真实下载返回字节，不再空轮询 300s 假超时）、L-18（`clamp_max_tokens` 容忍 None+截断一次性 warning）、L-19（provider 单例键纳入 config_path）、L-20（`_model_matches` 单源匹配剥 `-latest/-preview`，qwen-plus↔qwen-plus-latest 互通）、S-19（validate_key 落盘 30s 防抖+关键变更立即落+atexit flush）。

**API/安全（6 项）**：S-08 定点收口（trace×4+audit×3 `require_admin`（audit 前端挂在 platformAdmin；trace 按 agent 页面降级 `get_current_user`）、console upload/annotations 登录门槛；全局白名单机制留待前端全量调用审计后实施）、S-10（有凭证但无效→401，不再静默变 default 身份；完全无凭证回落保留保桌面首启）、S-13（`_initialize_components` 改 `to_thread`，审计确认无线程不安全 asyncio 原语）、S-17 残余（WS finally 收口+client_id 服务端派生，前端零依赖确认）、S-18（/push/message 改 `require_admin`）、S-04 残余（`NEUROVA_BOOTSTRAP_ADMIN_TOKEN` env 或 `data/bootstrap_admin.ini` 配置时首账号注册强制 hmac.compare_digest 校验，未配置保持桌面"注册即管理员"默认+warning；/setup-status 保留，抢注风险已被门控覆盖）。

**通道/进化/沙箱（11 项+1 澄清）**：C-13（disconnect 探测 SDK stop/close+join(5s) 幂等）、C-15（`_maybe_persist` 移出外层 RLock，修正误导注释）、C-16（window_size 校验回落+空历史安全值）、C-17（`random.Random(seed)` 实例化可注入）、C-18（telegram 临时文件 7 处消费点 try/finally 清理——真实缺陷是异常路径泄漏）、C-19（`cached` 装饰器全库零使用点→删除 -76 行）、C-20（`_validate_parameters` 接线会误判 LLM 参数类型→删除死代码）、C-21（mobile_pairing 加 RLock+`_revoked_tokens` 改有界 dict+配对码改 `secrets.choice`）、C-22（沙箱超时 POSIX killpg/Windows taskkill /T /F 杀进程树，Windows 实测杀灭 ping 孙进程）、C-23（feishu URL 挑战 fail-closed 比对 verification_token）、C-24（`_message_handlers` __init__ 直建+快照遍历）、**C-25 澄清非缺陷**（lark-oapi 固定间隔+jitter 无限重连、dingtalk-stream 指数退避封顶 60s，重连由 SDK 管理）。

**前端（8 项）**：F-04（TTS 缓冲边界改用切分函数返回的滞留段精确对齐，indexOf 反推删除）、F-05（401 单飞刷新：共享 Promise+重放一次+失败清凭证跳登录，refresh_token 首次接入）、F-06（画布 interval isDisposed 守卫+兜底定时器句柄收口+onBeforeUnmount unsubscribe）、F-07（computed 内自写 ref 移除，getter 纯函数化）、F-08（重试被中止不再 markSent 出队）、F-10（孤儿 AbortController 删除）、F-11（ModelPage 卸载守卫）、F-12（SettingPage 未加载禁保存+11 语言 i18n）。

### 9.6.3 合并回归甄别与回归修复（主会话）

合并回归采用 HEAD worktree 对照法（注意：HEAD 在 `tests/unit/memory/test_pending_memory.py` 存在收集期错误会中断全量收集，跨目录 HEAD 基线须按目录分别采集）。发现并根修 5 处回归/缺陷：

1. **usage_history 常驻连接丢 commit（生产级，P1-E5 优化引入）**：record() 改常驻连接后丢失 `with conn:` 的隐式提交，INSERT 滞留未提交事务，WAL 下所有读连接永久不可见 → token 统计静默归零。根修：常驻连接 `isolation_level=None`（autocommit）。顺带修好 usage_overview 3 项预存失败。
2. **A-14 契约适配**：`test_post_chat_pipeline_safe_step` 仍按旧契约断言 ImportError re-raise → 按新契约改写（FAILED 记录+default，不炸穿）。
3. **P0-B1 契约 harness 滞后 ×2**：`test_tool_executor_messages_fix`（4）与 `test_p2_tool_executor_fixes`（3）仍断言直写 `_tool_messages_list` → mock 忠实模拟 `append_tool_messages` 公有 API（records 落消费者可见列表），12 用例转绿。
4. **ContextVar 测试污染 ×3**：`pipe._step_results = []`（property setter）落线程基础上下文且不复位，泄漏同 worker 全部后续测试（neurflow 集成 6 项假红）。修复 test_a03 文件（autouse fixture set/reset 成对）+ 扫荡修复预存泄漏点 test_ekb_agent_isolation、test_p1_review_fixes。
5. **测试脚本缺陷 ×2**：TOCTOU 源码断言 `lock_line_idx` 缺 `is None` 守卫（被 M-11 第二个锁块覆盖成假红）；温度测试喂 naive 本地时间与 naive→UTC 生产契约错位（UTC+8 下 1 天算成 16h 命中不衰减早退）——统一 aware UTC；moe 时序测试 `0.0<0.0`（100 次空转低于计时器分辨率）→ perf_counter+20000 次迭代确定性化。

**台账（预存/不修，均有 HEAD 或隔离复现证据）**：`tests/unit/execution/test_tool_engine.py`×7（幽灵 API harness）、`tests/unit/llm`×9（provider 契约错位，根因 `provider.py:446` 收 MagicMock）、`tests/unit/api`×4（agent_package×2/execution_events/mobile_pairing）、`test_auth_system`×1（黑名单结构不匹配）、agent+tools 目录其余 58 failed+14 errors（HEAD 同样失败，含 capability_graph_phase3×21/unified_tool_registry×14 等陈旧 harness）、`test_files_api_security_p0.py` 隔离运行挂起（files_api 域）、`test_memory_source_unification::test_moe_router_reads_persist_db` 偶发顺序 flaky（多轮定向复现未果，疑 MoE 后台索引线程竞态）、console.py:1518 docstring 失实（称支持 Bearer 头实仅 query token）。

**最终回归状态**：agent+tools 当前失败集为 HEAD 基线真子集（零新增，另修复 13 项预存）；cognitive_layers+memory+core 确定性失败清零；llm+api+security 仅剩台账预存 14 项；channels+evolution+sandbox+execution 仅剩台账预存 7 项；前端 vitest 1260/1260 绿 + vue-tsc 零错误。新增回归测试 39 文件（约 150+ 用例）均先红后绿实证。
