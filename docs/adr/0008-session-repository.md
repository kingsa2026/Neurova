# ADR 0008: SessionRepository 统一会话存储接口

- **Status**: Accepted
- **Date**: 2026-06-28
- **Decision Maker**: 会话存储深化（候选 #3）

## Context

Neurova 存在 **5 套并行的会话存储**，删除任一套都会让其他套失效或转移 complexity：

| # | 存储 | 文件 | 类型 | 问题 |
|---|------|------|------|------|
| A | `_CHAT_SESSIONS` | `neurova/api/endpoints/console.py:72` | 内存字典 + `data/console_sessions.json` 持久化 | 与 B 并行，删除后 console 失效 |
| B | `SessionManager` | `neurova/session_manager.py` | 文件层（`sessions/<agent_id>/session_<sid>_<date>.json`） | 与 A 并行，删除后 chat_pipeline 恢复失效 |
| C | `agent.conversation_history` | `neurova/agent_core.py` | 裸 list 属性 | LLM 真实上下文，无 invariant |
| D | `SessionSyncManager` | `neurova/api/endpoints/session_sync.py` | 纯内存（`UnifiedSession.history`） | 进程重启即丢，跨渠道广播 |
| E | SQLite `sessions`/`session_messages` | `neurova/Storage/` | 孤儿表 | 无代码引用，dead schema |

**Deletion test 验证**：
- 删 A → complexity 转移到 B（console 失效）
- 删 B → complexity 转移到 A（chat_pipeline 恢复失效）
- 删 D → 跨渠道广播消失
- 删 E → complexity 不变（无引用）= pass-through，应删表

**6 个 `Session*` 类全是具体类**，无任何 ABC/Protocol，靠鸭子类型重复实现 save/load/list。第 6 套 `/v1/chat/sessions` API 因 `hasattr` 守卫永远 False 而瘫痪（`SessionManager` 无 `list_sessions` 方法）。

## Decision

定义 **`SessionRepository` ABC** 作为统一会话存储接口（deep module），所有 adapter 实现此接口，调用方通过 `get_session_repository()` 工厂获取实例。

### 接口契约

```python
class SessionRepository(ABC):
    @abstractmethod
    def create_session(self, agent_id: str, user_id: str = "", title: str = "") -> str: ...
    @abstractmethod
    def save_message(self, agent_id: str, session_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> bool: ...
    @abstractmethod
    def get_history(self, agent_id: str, session_id: str, max_messages: int = 0) -> List[Dict]: ...
    @abstractmethod
    def list_sessions(self, agent_id: str = "", user_id: str = "") -> List[Dict]: ...
    @abstractmethod
    def delete_session(self, agent_id: str, session_id: str) -> bool: ...
    @abstractmethod
    def rename_session(self, agent_id: str, session_id: str, title: str) -> bool: ...
    @abstractmethod
    def get_session(self, agent_id: str, session_id: str) -> Optional[Dict]: ...
```

### Adapter 规划

| Adapter | 状态 | 包裹对象 | 用途 |
|---------|------|----------|------|
| `FileSessionRepository` | ✅ 本 ADR 落地（= SessionManager） | SessionManager | 文件持久化 |
| `MemorySessionRepository` | 待落地（候选 #5） | SessionSyncManager | 跨渠道内存广播 |
| `SqliteSessionRepository` | 待落地（候选 #4） | SQLite sessions 表 | 激活孤儿表，或删表 |

### 落地范围（本 ADR）

1. **新建** [neurova/session_repository.py](file:///e:/项目/Neurova/neurova/session_repository.py)：定义 ABC + `get_session_repository()` / `reset_session_repository()` 工厂
2. **改造** [neurova/session_manager.py](file:///e:/项目/Neurova/neurova/session_manager.py)：
   - `SessionManager` 继承 `SessionRepository`
   - `SessionRecord` dataclass 添加 `title` / `user_id` 字段
   - `create_session(agent_id, user_id='', title='')` 改造：从仅返回 uuid 升级为**落盘空 session 文件**（修复 `list_sessions` 找不到的问题）
   - 新增 `save_message(单条)` — 与现有 `add_message(配对)` 共存
   - 新增 `get_history` — 聚合所有日期消息
   - 新增 `list_sessions` — 扫描目录，按 agent_id/user_id 过滤
   - 新增 `rename_session` — 写入所有日期文件
3. **保留** 现有 `get_session(date=None) -> SessionRecord` / `delete_session(date=None)` 签名不破坏（chat_pipeline.py:355 调用方依赖 `SessionRecord.messages` 字段访问）

### 不在本 ADR 范围

- ~~删除 `_CHAT_SESSIONS`（候选 #1）~~ — **已落地 (D1)**: S1 修复副产品,console.py 已接入 `get_session_repository()`,`_CHAT_SESSIONS` 字典+JSON 双写已删除
- ~~删除 SQLite 孤儿表（候选 #4）~~ — **已落地 (D4)**: `neurova/memory/scripts/init_db.py:76-79` 标注三张孤儿表 (sessions / session_messages / session_context_snapshots) 已删除 — 这三张表仅有 CREATE TABLE,无任何 INSERT/SELECT/UPDATE 代码引用,会话持久化由 SessionManager 文件层负责
- ~~`agent.conversation_history` 封装（候选 #6）~~ — **已落地 (D3)**: `ConversationContext` deep module (165 行,role 校验 + RLock + 自动 trim + 深拷贝) 已实现;`MemCore.update_history` 已优先走 ctx 路径,fallback 已删除 (显式 raise RuntimeError 要求 `init_conversation()`)
- `SessionSyncManager` 接入（候选 #5）— **永久 deferred**: S2 已落地 `register_or_create_session` (文件层与内存层 session_id 收敛);**完整 ABC 接入不推进**,理由:SessionSyncManager 核心 API (`broadcast_event` / `register_or_create_session` / `add_event_listener`) 与 SessionRepository ABC CRUD 契约 (`create_session` / `save_message` / `get_history` / `list_sessions` / `delete_session` / `rename_session` / `get_session`) 语义不匹配;ChatPipeline 当前架构职责分离清晰 — 文件持久化走 SessionRepository (SessionManager),跨渠道广播直接调 SessionSyncManager API;强行包裹为 `MemorySessionRepository` 会丢失广播语义变成假 ABC 实现
- ~~删除 `/v1/chat/sessions` 死端点（候选 #7）~~ — **已落地 (D4)**: chat.py 4 个 `/sessions` 端点 (GET/POST/PUT/DELETE) 已删除,前端已迁移到 `/api/v1/console/chat/sessions` (console.py + SessionRepository);`TestEmptyAgentId` 4 测试已标记 obsolete skip
- 前端 Pinia store（候选 #2）— 仍 deferred

## Consequences

### 正向

- **统一接口**：5 套存储收敛到 1 个 ABC，调用方依赖抽象不依赖具体
- **修复瘫痪 API**：`/v1/chat/sessions` 的 `hasattr` 守卫现在能通过（SessionManager 有 `list_sessions`）
- **测试通过**：18/18 GREEN，回归正向（29f→14f, 8err→0, 29p→54p）
- **未来切换容易**：`get_session_repository()` 单点切换 adapter

### 负向

- **SessionManager 双重身份**：既是文件层实现，又是 ABC 子类。若未来需要纯文件 adapter，可拆 `FileSessionRepository` wrapper
- **`get_session` 返回类型不一致**：ABC 契约 `Optional[Dict]`，SessionManager 实际返回 `SessionRecord`。Python ABC 不强制签名匹配，但类型注解不一致是设计气味。未来统一为 dict 返回时需修改 chat_pipeline.py:355 调用方
- **`save_message` 与 `add_message` 共存**：两个方法语义重叠（单条 vs 配对）。未来候选 #1 落地后可废弃 `add_message`

## Alternatives Considered

### A. 不引入 ABC，直接统一到 SessionManager

拒绝。`SessionSyncManager`（纯内存）和 SQLite（关系型）的存储语义与文件层差异大，强行统一到 SessionManager 会污染文件层实现。

### B. 用 Protocol 而非 ABC

拒绝。Protocol 是结构性子类，无法强制 adapter 显式声明实现，容易出现"看起来像但实际不一致"的伪实现。ABC 强制显式继承，更安全。

### C. 立即删除 `_CHAT_SESSIONS`

拒绝。`_CHAT_SESSIONS` 与 `SessionManager` 当前并行存在，删任一都会让另一套失效。需要先在 console.py 接入 `SessionRepository`（候选 #1），验证通过后再删 `_CHAT_SESSIONS`。

## References

- 改造报告：[docs/bugfix-history-load-bugs.md](../bugfix-history-load-bugs.md) §7 架构观察
- 测试文件：[tests/unit/test_session_repository.py](file:///e:/项目/Neurova/tests/unit/test_session_repository.py)
- 上游 ADR：[ADR 0003](./0003-memory-system-architecture.md) 分层架构 + 深度模块模式
