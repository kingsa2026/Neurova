# 协作会话群聊（Collaboration Room Chat）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/collaboration/sessions` 的"打开"进入一个持久化的多 Agent 群聊房间（人可发言，@ 或默认应答者流式回应，重开可回看，多端实时同步）。

**Architecture:** 三个后端单一职责单元（`RoomStore` 持久 / `RoomBus` 实时 / `RoomTurnRouter` 调度）+ 前端 `CollaborationRoomPage`。持久复用 `SessionManager`（以 `room_id` 作 agent_id+session_id 键），实时复用 `session_sync_manager` 事件总线，调度复用既有 `turn_origin`/`actionability`/`group_leadership`。

**Tech Stack:** 后端 Python/FastAPI/pytest；前端 Vue3 + TS + Pinia + Ant Design Vue + vitest。

**Spec:** `docs/superpowers/specs/2026-09-19-collaboration-room-chat-design.md`

## Global Constraints

- 中文交流；代码注释/文档不引用任何第三方项目具名。
- TDD 红→绿→重构，一次一个行为；每任务末含 commit（但**本仓提交须用 `git commit --only 点名路径`**，防后台扫描器夹带；未获用户指示不推送）。
- 后端测试用项目 `.venv\Scripts\python.exe`（勿用全局 python）。
- 前端门：`npx vue-tsc --noEmit` 0 错、`npm run build` 绿、vitest 相关用例绿。
- 净 LOC 最小；不新增孤岛；不改 console chat 既有端点/存储语义。
- 关键既有契约（已核实）：
  - `get_session_repository()` → `SessionRepository`：`save_message(agent_id, session_id, role, content, metadata=None)->bool`、`get_history(agent_id, session_id, max_messages=0)->List[Dict]`（每条含 role/content/timestamp/metadata）。
  - `get_session_sync_manager()` → `register_or_create_session(session_id, user_id, agent_id='default', external_id=None, metadata=None)`、`async broadcast_event(session_id, event, exclude_channel=None)->int`、`get_history(session_id, limit=100, event_types=None)`。
  - `SessionEvent(event_type: EventType, session_id: str, source_channel: str, payload: dict, ...)`（seq 由 add_event 盖章；发送者归属放 payload）。
  - `get_agent_instance(agent_id)` → `agent.chat(message, session_id=..., stream=True, metadata=...)`（async）。
  - 协作路由前缀 `/v1/collaboration`（`endpoints/__init__.py` 动态清单 L226）；新文件加入该清单。

---

## 文件结构（新增/修改）

- 新建后端：`neurova/collaboration/room_store.py`、`room_bus.py`、`room_turn_router.py`、`api/endpoints/collaboration_room_api.py`。
- 改后端：`api/endpoints/__init__.py`（注册新路由）。
- 新建前端：`NeurUI/src/pages/CollaborationRoomPage.vue`、`NeurUI/src/api/modules/collaborationRoom.ts`、`NeurUI/src/composables/useCollaborationRoom.ts`。
- 改前端：`router/index.ts`（`collaboration/sessions/:roomId`）、`pages/CollaborationPage.vue`（"打开"改跳）、`i18n/locales/{zh-CN,en-US}.ts`。
- 测试：`tests/unit/collaboration/test_room_store.py`、`test_room_turn_router.py`、`test_room_bus.py`、`tests/integration/api/test_collaboration_room_api.py`；`NeurUI/src/**/__tests__/*`。

---

## Task 1: RoomStore（持久房间消息）

**Files:**
- Create: `neurova/collaboration/room_store.py`
- Test: `tests/unit/collaboration/test_room_store.py`

**Interfaces:**
- Consumes: `get_session_repository()`（`save_message`/`get_history`）。
- Produces:
  - `RoomStore.append(room_id: str, sender_type: str, sender_id: str, content: str, meta: dict | None = None) -> dict`（返回存下的消息 dict：`{role, content, timestamp, metadata{sender_type,sender_id,...}}`）
  - `RoomStore.history(room_id: str, limit: int = 200) -> list[dict]`（每条 `{sender_type, sender_id, role, content, ts, meta}`）
  - `get_room_store() -> RoomStore`（单例）/ `reset_room_store()`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/collaboration/test_room_store.py
from neurova.collaboration.room_store import RoomStore

class _FakeRepo:
    def __init__(self): self.saved = []
    def save_message(self, agent_id, session_id, role, content, metadata=None):
        self.saved.append({"agent_id": agent_id, "session_id": session_id, "role": role,
                           "content": content, "metadata": metadata or {}, "timestamp": 1}); return True
    def get_history(self, agent_id, session_id, max_messages=0): return self.saved

def test_append_stores_under_room_id_and_sender_in_metadata():
    repo = _FakeRepo(); store = RoomStore(repo=repo)
    store.append("project_x", "agent", "a1", "hello", {"model": "m"})
    m = repo.saved[0]
    assert m["agent_id"] == "project_x" and m["session_id"] == "project_x"
    assert m["role"] == "assistant"          # agent → assistant
    assert m["metadata"]["sender_id"] == "a1" and m["metadata"]["sender_type"] == "agent"

def test_history_restores_sender_attribution():
    repo = _FakeRepo(); store = RoomStore(repo=repo)
    store.append("project_x", "user", "u1", "hi")
    rows = store.history("project_x")
    assert rows[0]["sender_type"] == "user" and rows[0]["sender_id"] == "u1" and rows[0]["content"] == "hi"
```

- [ ] **Step 2: 跑测试确认失败** — `& '.venv\Scripts\python.exe' -m pytest tests/unit/collaboration/test_room_store.py -q`（ModuleNotFound / 类未定义）
- [ ] **Step 3: 最小实现**

```python
# neurova/collaboration/room_store.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from neurova.session_repository import get_session_repository

_ROLE = {"user": "user", "agent": "assistant", "system": "system"}

class RoomStore:
    def __init__(self, repo=None):
        self._repo = repo
    @property
    def repo(self):
        return self._repo or get_session_repository()
    def append(self, room_id, sender_type, sender_id, content, meta=None) -> Dict[str, Any]:
        md = {"sender_type": sender_type, "sender_id": sender_id}
        if meta: md.update(meta)
        self.repo.save_message(agent_id=room_id, session_id=room_id,
                               role=_ROLE.get(sender_type, "assistant"), content=content, metadata=md)
        return {"room_id": room_id, **md, "content": content}
    def history(self, room_id, limit=200) -> List[Dict[str, Any]]:
        rows = self.repo.get_history(agent_id=room_id, session_id=room_id, max_messages=0) or []
        out = [{"sender_type": (r.get("metadata") or {}).get("sender_type", ""),
                "sender_id": (r.get("metadata") or {}).get("sender_id", ""),
                "role": r.get("role", ""), "content": r.get("content", ""),
                "ts": r.get("timestamp"), "meta": {k: v for k, v in (r.get("metadata") or {}).items()
                                                   if k not in ("sender_type", "sender_id")}} for r in rows]
        return out[-limit:]

_store: Optional[RoomStore] = None
def get_room_store() -> RoomStore:
    global _store
    if _store is None: _store = RoomStore()
    return _store
def reset_room_store() -> None:
    global _store
    _store = None
```

- [ ] **Step 4: 跑测试确认通过** — 同上，2 passed
- [ ] **Step 5: 提交** — `git add ...; git commit --only -m "feat(collab): RoomStore 复用 SessionManager 持久房间消息" -- <paths>`

---

## Task 2: RoomBus（实时广播，薄封装 session_sync_manager）

**Files:** Create `neurova/collaboration/room_bus.py`；Test `tests/unit/collaboration/test_room_bus.py`

**Interfaces:**
- Produces: `RoomBus.ensure_room(room_id, user_id, members, owner)`；`RoomBus.publish(room_id, event_type: str, payload: dict) -> None`（async）；`get_room_bus()`/`reset_room_bus()`。
- Consumes: `get_session_sync_manager()`、`SessionEvent`、`EventType`。

- [ ] **Step 1: 写失败测试**（mock manager，断言 publish 调 `broadcast_event` 且 event_type/session_id/payload 正确；ensure_room 调 `register_or_create_session`）
```python
import asyncio
from unittest.mock import MagicMock
from neurova.collaboration.room_bus import RoomBus
from neurova.sync.session_sync_manager import EventType

def test_publish_broadcasts_event_with_sender_payload():
    mgr = MagicMock(); mgr.broadcast_event = asyncio.MagicMock(return_value=0)
    bus = RoomBus(manager=mgr)
    asyncio.run(bus.publish("project_x", EventType.AGENT_REPLY.value, {"sender_id": "a1", "content": "hi"}))
    args, _ = mgr.broadcast_event.call_args
    assert args[0] == "project_x" and args[1].event_type == EventType.AGENT_REPLY
    assert args[1].payload["sender_id"] == "a1"
```
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（`ensure_room`→`register_or_create_session(session_id=room_id, user_id, agent_id='collaboration', metadata={members,owner})`；`publish`→构造 `SessionEvent(event_type=EventType(event_type), session_id=room_id, source_channel='room', payload=payload)` 后 `await manager.broadcast_event(room_id, event)`）
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

## Task 3: RoomTurnRouter（@路由 + 默认应答者 + 门控 + 执行）

**Files:** Create `neurova/collaboration/room_turn_router.py`；Test `tests/unit/collaboration/test_room_turn_router.py`

**Interfaces:**
- Consumes: `RoomStore`、`RoomBus`、`get_agent_instance`、`agent.chat`、（可选）`actionability`/`group_leadership`。
- Produces:
  - `resolve_targets(text, members, responder_agent_id) -> list[str]`（纯函数：解析 `@name`→成员；无 @ → `[responder_agent_id or members[0]]`）
  - `RoomTurnRouter.handle_user_message(room_id, text, actor_user, members, responder_agent_id) -> None`（async：落 user 消息→广播→解析目标→逐个跑 agent→流式广播→落 assistant）

- [ ] **Step 1: 写失败测试（纯逻辑 resolve_targets 优先）**
```python
from neurova.collaboration.room_turn_router import resolve_targets
def test_at_mention_selects_named_member():
    assert resolve_targets("@凯蒂 看看", ["a1", "agent_kai"], "a1") == ["agent_kai"] or \
           resolve_targets("@凯蒂 看看", ["凯蒂"], "凯蒂") == ["凯蒂"]
def test_no_mention_falls_back_to_responder():
    assert resolve_targets("随便聊聊", ["a1", "a2"], "a2") == ["a2"]
def test_empty_members_no_target():
    assert resolve_targets("hi", [], "") == []
```
- [ ] **Step 2 失败 → Step 3 实现 resolve_targets（按成员 name/id 匹配 `@token`；无命中回落 responder/首个）→ Step 4 通过 → Step 5 提交**
- [ ] **Step 6: 追加 handle_user_message 测试**（mock RoomStore/RoomBus/`get_agent_instance` 返回带 `async chat` 的假 agent；断言 user 落库+广播、目标 agent 被调用、assistant 落库+AGENT_REPLY）→ 红→实现→绿→提交。实现要点：`agent.chat(text, session_id=room_id, stream=True, metadata={"turn_origin":"collaboration"})`；失败发 `AGENT_ERROR` 事件不抛。

---

## Task 4: 房间端点（GET 房间/历史 + POST 消息）

**Files:** Create `neurova/api/endpoints/collaboration_room_api.py`；Modify `api/endpoints/__init__.py`（清单加 `("neurova.api.endpoints.collaboration_room_api", "/v1/collaboration", "Collaboration Room API")`）；Test `tests/integration/api/test_collaboration_room_api.py`

**Interfaces:** Consumes RoomStore/RoomBus/RoomTurnRouter + `get_current_user` + collaboration manager（取 project 成员/owner）。Produces REST：`GET /rooms/{room_id}`、`GET /rooms/{room_id}/messages`、`POST /rooms/{room_id}/messages`。

- [ ] Step 1 失败测试（TestClient：POST messages → 200 且 RoomStore.append 被调、RoomTurnRouter.handle_user_message 被调度；GET messages 返回历史；非成员 403）
- [ ] Step 2 失败 → Step 3 实现端点（薄，调 Task1-3 单元；成员校验经 collaboration manager.get_project(room_id).members）→ Step 4 通过 → Step 5 提交

---

## Task 5: 前端房间页 + 路由 + "打开"改跳（示踪：拉历史只读渲染）

**Files:** Create `CollaborationRoomPage.vue`、`api/modules/collaborationRoom.ts`、`composables/useCollaborationRoom.ts`；Modify `router/index.ts`（`collaboration/sessions/:roomId`）、`CollaborationPage.vue`（`handleViewSession`→`router.push`）、i18n。

- [ ] Step 1 vitest 失败（api 归一 `toRoomMessage`；"打开"跳路由断言）
- [ ] Step 2 失败 → Step 3 实现 api + 房间页只读拉历史渲染（GlassCard 气泡按 sender 分组）+ 路由 + 改"打开" → Step 4 `vue-tsc` 0 错、vitest 绿 → Step 5 实机走查（打开真实房间看到历史）→ Step 6 提交

---

## Task 6: 前端发消息 + 实时订阅 + 乐观渲染

**Files:** Modify `CollaborationRoomPage.vue`、`useCollaborationRoom.ts`（接 session-sync WS/SSE 客户端，`session_id=room_id`）。

- [ ] TDD：输入框→`POST /rooms/{id}/messages`→乐观追加→订阅流把 AGENT_STREAM_CHUNK/AGENT_REPLY 落到对应 sender 气泡。实机：人发→成员 Agent 流式回应→双标签同步。提交。

---

## Task 7: 成员管理 + 成本环

**Files:** Modify 房间页头（成员列表/设默认应答者 `responder_agent_id`）；per-turn usage 接既有成本环组件（ChatPage 同款）。
- [ ] 测试 + 实现 + 实机 + 提交。

---

## Task 8: 自动讨论开关（coordinator/蜂群多轮 + 治理帽）

**Files:** Modify `room_turn_router.py`（`auto_discuss` 模式：coordinator 依 `agent/team.py::orchestrate` 或 swarm 派生多轮，受 `MAX_ACTIVE_CHILDREN`/预算/冷却约束）；房间页开关（默认关，持久到房间 metadata）。
- [ ] 测试（mock 多轮收敛/触顶停止）+ 实现 + 实机 + 提交。

---

## Self-Review（写完计划后）

- **Spec coverage**：§3 三单元=Task1-3；§5 端点=Task4；§4 数据流=Task4+6；§6 轮次=Task3；§8 验收1-5=Task5-8；§2 持久决策=Task1。全覆盖。
- **Placeholder**：Task5-8 前端步骤较概括（引用既有组件复用），实现时按 TDD 补具体测试代码；后端 Task1-4 含完整代码。
- **类型一致**：`RoomStore.append/history`、`RoomBus.publish/ensure_room`、`resolve_targets/handle_user_message` 签名跨任务一致。
