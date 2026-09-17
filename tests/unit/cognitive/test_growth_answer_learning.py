"""Isolated growth teaching persistence and real reader regressions."""
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neurova.api.endpoints import growth
from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager, QuestionStatus


class DiskMemory:
    """Small durable store implementing the queue's actual memory contract."""
    def __init__(self, path):
        self.path = path
        self.fail = False
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT)")

    def get_memories(self, **kwargs):
        with sqlite3.connect(self.path) as db:
            return [dict(id=r[0], content=r[1]) for r in db.execute("SELECT * FROM memories")]

    def remember(self, content, **kwargs):
        if self.fail:
            raise OSError("disk full")
        mid = json.loads(content)["id"]
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO memories VALUES (?, ?)", (mid, content))
        return mid

    def update_memory(self, mid, content):
        if self.fail:
            raise OSError("disk full")
        with sqlite3.connect(self.path) as db:
            return db.execute("UPDATE memories SET content=? WHERE id=?", (content, mid)).rowcount > 0


@pytest.fixture
def stores(tmp_path, monkeypatch):
    import neurova.skills.experience_knowledge_base as mod
    path = str(tmp_path / "ekb.db")
    monkeypatch.setenv("NEUROVA_EKB_DB", path)
    monkeypatch.setattr(mod, "_DEFAULT_DB_PATH", path)
    kb = mod.ExperienceKnowledgeBase(path)
    monkeypatch.setattr(mod, "_experience_kb", kb)
    monkeypatch.setattr(growth, "_get_experience_knowledge_base", lambda: kb)
    memory = DiskMemory(tmp_path / "questions.db")
    yield QuestionQueueManager(memory), memory, kb
    kb.close()


def test_failed_reanswer_preserves_previous_record(stores):
    queue, memory, _ = stores
    q = queue.generate_question("report export")
    assert queue.mark_answered(q.id, "old answer")
    before = json.loads(json.dumps(q.to_dict()))
    memory.fail = True
    assert not queue.mark_answered(q.id, "new answer", allow_correction=True)
    assert q.to_dict() == before
    assert queue.get_questions_by_status(QuestionStatus.ANSWERED) == [q]
    assert not queue.mark_answered(q.id, "new answer")


def test_answer_and_lesson_are_one_durable_record(stores):
    queue, memory, _ = stores
    q = queue.generate_question("report export")
    lesson = {"agent_id": "agent-a", "answerer_id": "user-a", "question_id": q.id, "answer": "do not export", "publication": "pending"}
    assert queue.mark_answered(q.id, "do not export", lesson=lesson, require_durable=True)
    restored = QuestionQueueManager(DiskMemory(memory.path)).get_question(q.id)
    assert restored.metadata["lesson"] == lesson
    assert restored.metadata["answer"] == "do not export"


def test_standalone_supported_but_http_requires_durable():
    queue = QuestionQueueManager()
    q = queue.generate_question("report export")
    assert not queue.mark_answered(q.id, "answer", require_durable=True)
    assert q.status is QuestionStatus.PENDING
    assert queue.mark_answered(q.id, "answer")


def test_duplicate_answer_is_idempotent_and_empty_rejected(stores):
    queue, _, _ = stores
    q = queue.generate_question("report export")
    assert queue.mark_answered(q.id, "answer")
    before = q.to_dict().copy()
    for _ in range(3):
        assert queue.mark_answered(q.id, "answer")
    assert q.to_dict() == before
    assert queue.get_questions_by_status(QuestionStatus.ANSWERED) == [q]
    assert not queue.mark_answered(q.id, "  ")
    assert q.to_dict() == before


def test_answered_question_normalized_duplicate_not_regenerated(stores):
    queue, _, _ = stores
    q = queue.generate_question("Report  Export", metadata={"user_id": "user-a"})
    queue.mark_answered(q.id, "answer")
    assert queue.generate_question(" report export ", metadata={"user_id": "user-a"}).id == q.id
    assert queue.generate_question("report export", metadata={"user_id": "user-b"}).id != q.id


@pytest.fixture
def http(stores, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from neurova.api.auth import get_current_user
    queue, memory, kb = stores
    agent = SimpleNamespace(config=SimpleNamespace(agent_id="agent-a", owner_user_id="user-a"),
                            question_queue_manager=queue, intrinsic_motivation=Mock(),
                            proactive_behavior_engine=Mock())
    agent.intrinsic_motivation.snapshot.return_value = {}
    agent.proactive_behavior_engine.get_recent_actions.return_value = []
    monkeypatch.setattr(growth, "_load_personality_data", lambda _: {})
    monkeypatch.setattr(growth, "_load_constitution_rules", lambda _: [])
    monkeypatch.setattr(growth, "_get_agent", lambda _: agent)
    app = FastAPI()
    app.include_router(growth.router, prefix="/growth")
    identity = {"user_id": "user-a", "neuser_id": "tenant-a", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: identity.copy()
    with TestClient(app) as client:
        yield client, identity, agent, app


def answer_http(client, qid, answer="do not export", agent_id="agent-a"):
    return client.put(f"/growth/questions/{qid}/answer", params={"answer": answer, "agent_id": agent_id,
                                                               "answerer_id": "spoofed"})


def test_http_failed_save_has_no_live_experience(http, stores):
    client, _, agent, _ = http
    queue, memory, kb = stores
    q = queue.generate_question("report export")
    memory.fail = True
    assert answer_http(client, q.id).status_code == 503
    assert kb.get_experience_records() == []
    assert q.status is QuestionStatus.PENDING
    assert "lesson" not in q.metadata
    agent.intrinsic_motivation.observe_purpose.assert_not_called()


def test_http_persists_identity_retries_and_correction(http, stores):
    client, _, agent, _ = http
    queue, memory, kb = stores
    q = queue.generate_question("report export")  # legacy metadata is allowed
    assert answer_http(client, q.id).status_code == 200
    lesson = q.metadata["lesson"].copy()
    assert lesson["answerer_id"] == "user-a"
    assert lesson["neuser_id"] == "tenant-a"
    before = q.answered_at
    for _ in range(3):
        assert answer_http(client, q.id).status_code == 200
    assert q.answered_at == before
    assert agent.intrinsic_motivation.observe_purpose.call_count == 1
    assert len(kb.find_growth_lessons("report export", "agent-a", "user-a")) == 1
    assert answer_http(client, q.id, "ask before export").status_code == 200
    restored = QuestionQueueManager(DiskMemory(memory.path)).get_question(q.id)
    assert restored.metadata["lesson"]["answer"] == "ask before export"
    hits = kb.find_growth_lessons("report export", "agent-a", "user-a")
    assert len(hits) == 1 and hits[0]["answer"] == "ask before export"
    assert hits[0]["revision"] != lesson["revision"]
    assert kb.get_experience_records() == [], "guidance is not an execution success or generic shared experience"


def test_ekb_failure_keeps_durable_outbox_and_retry(http, stores, monkeypatch):
    client, _, agent, _ = http
    queue, memory, kb = stores
    q = queue.generate_question("report export")
    original = kb.publish_growth_lesson
    monkeypatch.setattr(kb, "publish_growth_lesson", Mock(side_effect=OSError("index full")))
    response = answer_http(client, q.id)
    assert response.status_code == 503
    assert response.json()["detail"]["answer_saved"] is True
    assert QuestionQueueManager(DiskMemory(memory.path)).get_question(q.id).metadata["lesson"]["answer"] == "do not export"
    agent.intrinsic_motivation.observe_purpose.assert_not_called()
    monkeypatch.setattr(kb, "publish_growth_lesson", original)
    assert answer_http(client, q.id).status_code == 200
    assert len(kb.find_growth_lessons("report export", "agent-a", "user-a")) == 1


@pytest.mark.parametrize("kind,expected", [("empty", 422), ("missing", 404), ("memory", 503),
                                          ("other_agent", 404), ("other_user", 404), ("permission", 403)])
def test_http_validation_permissions(http, stores, kind, expected):
    client, identity, agent, _ = http
    queue, _, kb = stores
    q = queue.generate_question("report export")
    text = "do not export"
    qid = q.id
    if kind == "empty":
        text = "  "
    elif kind == "missing":
        qid = "absent"
    elif kind == "memory":
        queue._memory_manager = None
    elif kind == "other_agent":
        q.metadata["agent_id"] = "agent-b"
    elif kind == "other_user":
        q.metadata["user_id"] = "user-b"
    elif kind == "permission":
        identity["user_id"] = "user-b"
    assert answer_http(client, qid, text).status_code == expected
    assert kb.get_experience_records() == []


def test_http_real_auth_dependency_rejects_missing_credentials(http):
    client, _, _, app = http
    app.dependency_overrides.clear()
    assert answer_http(client, "missing").status_code in (401, 403)


def test_scoped_question_reads_and_answerer_binding(http, stores, monkeypatch):
    client, identity, agent, _ = http
    queue, _, _ = stores
    own = queue.generate_question("own report")
    foreign = queue.generate_question("private report", metadata={"user_id": "user-b"})
    for path in ("/growth/questions", "/growth/questions/next", "/growth"):
        response = client.get(path, params={"agent_id": "agent-a"})
        assert response.status_code == 200
        assert foreign.id not in response.text
    assert answer_http(client, own.id).status_code == 200
    identity.update(user_id="admin", role="admin")
    assert answer_http(client, own.id, "override private teaching").status_code == 404
    assert own.id not in client.get("/growth/questions", params={"agent_id": "agent-a"}).text


def read_pipeline(agent, text="report export", user="user-a"):
    from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = agent
    ctx = ChatContext(user_input=text, metadata={"user_id": user})
    pipeline._retrieve_ekb_experience(ctx)
    return pipeline, ctx


def test_real_reader_restart_scoping_complete_guidance(http, stores):
    client, _, agent, _ = http
    queue, memory, kb = stores
    q = queue.generate_question("report export")
    text = "Check all report details. " * 8 + "Do NOT export without approval."
    assert answer_http(client, q.id, text).status_code == 200
    agent.question_queue_manager = QuestionQueueManager(DiskMemory(memory.path))
    pipeline, ctx = read_pipeline(agent)
    assert len(ctx.experience_items) == 1
    item = ctx.experience_items[0]
    assert text in item["content"] and q.id in item["content"]
    assert "用户指导" in item["content"] and "未经执行验证" in item["content"]
    assert item["status"] == "retrieved" and item.get("success") is not True
    assert not read_pipeline(agent, user="user-b")[1].experience_items
    assert not read_pipeline(agent, user=None)[1].experience_items
    agent.config.agent_id = "agent-b"
    assert not read_pipeline(agent)[1].experience_items


def test_reader_retries_pending_index_and_never_uses_stale_correction(http, stores, monkeypatch):
    client, _, agent, _ = http
    queue, memory, kb = stores
    q = queue.generate_question("report export")
    assert answer_http(client, q.id, "old guidance").status_code == 200
    publish = kb.publish_growth_lesson
    monkeypatch.setattr(kb, "publish_growth_lesson", Mock(side_effect=OSError("index full")))
    assert answer_http(client, q.id, "new guidance").status_code == 503
    assert not read_pipeline(agent)[1].experience_items
    agent.question_queue_manager = QuestionQueueManager(DiskMemory(memory.path))
    monkeypatch.setattr(kb, "publish_growth_lesson", publish)
    items = read_pipeline(agent)[1].experience_items
    assert len(items) == 1 and "new guidance" in items[0]["content"]
    assert "old guidance" not in items[0]["content"]


def test_real_memory_manager_failed_write_preserves_live_and_disk(stores, tmp_path, monkeypatch):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    memory = MemoryManager(db_path=str(tmp_path / "real-memory.db"), enable_buffer=False)
    try:
        queue = QuestionQueueManager(memory)
        q = queue.generate_question("report export")
        assert queue.mark_answered(q.id, "old answer", require_durable=True)
        before = memory._memories[queue._memory_ids[q.id]].content
        monkeypatch.setattr(memory, "_persist_upsert", Mock(side_effect=OSError("full")))
        assert not queue.mark_answered(q.id, "new answer", require_durable=True)
        assert memory._memories[queue._memory_ids[q.id]].content == before
        assert q.metadata["answer"] == "old answer"
        assert QuestionQueueManager(memory).get_question(q.id).metadata["answer"] == "old answer"
    finally:
        memory._dependency_executor.shutdown(wait=True)
        if memory._persist_conn:
            memory._persist_conn.close()


@pytest.mark.asyncio
async def test_actual_pipeline_injects_private_guidance_without_archiving(http, stores, monkeypatch):
    from unittest.mock import AsyncMock
    client, _, agent, _ = http
    queue, _, _ = stores
    q = queue.generate_question("report export")
    answer = "Check everything first. " * 8 + "Do NOT export."
    assert answer_http(client, q.id, answer).status_code == 200
    pipeline, ctx = read_pipeline(agent)
    monkeypatch.setattr(pipeline, "_retrieve_memories", AsyncMock())
    monkeypatch.setattr(pipeline, "_retrieve_crystallized_patterns", AsyncMock())
    builder = AsyncMock(return_value=[{"role": "system", "content": "base"},
                                     {"role": "user", "content": "report export"}])
    agent.context_orchestrator = SimpleNamespace(build_context=builder)
    await pipeline._step_retrieve_and_build_context(ctx)
    assert answer in json.dumps(ctx.context, ensure_ascii=False)
    assert q.id in json.dumps(ctx.context)
    assert ctx.experience_items[0]["status"] == "injected"
    assert builder.call_args.kwargs["experience_items"] == [], "private corrections must not enter persistent pool"
    assert ctx.context[-1]["role"] == "user"

    # Execute the real context builder too; no filesystem-backed ledger or LLM.
    from neurova.context.orchestrator import ContextOrchestrator
    from neurova.context_pool import ContextPool
    agent.config.constitution = None
    agent.config.behavior_rules = []
    agent.config.llm_model = "gpt-4"
    agent.config.workspace_path = ""
    agent.soul = "test soul"
    agent.personality = None
    agent.conversation_history = []
    agent.memory_manager = None
    agent.tool_router = None
    agent.growth_log_manager = None
    agent.context_builder = Mock()
    agent.context_orchestrator = ContextOrchestrator(agent, use_pool=False)
    agent.context_orchestrator.use_pool = True
    agent.context_orchestrator.context_pool = ContextPool(user_id="user-a", agent_id="agent-a")
    monkeypatch.setattr(agent.context_orchestrator, "get_tools_description", AsyncMock(return_value=""))
    monkeypatch.setattr(agent.context_orchestrator, "_workspace_docs_section", lambda: "")
    monkeypatch.setattr(agent.context_orchestrator, "_skill_catalog_section", lambda: "")
    ctx.context = []
    await pipeline._step_retrieve_and_build_context(ctx)
    assert answer in json.dumps(ctx.context, ensure_ascii=False)
    _, other = read_pipeline(agent, user="user-b")
    await pipeline._step_retrieve_and_build_context(other)
    assert answer not in json.dumps(other.context, ensure_ascii=False)
    assert answer_http(client, q.id, "Corrected report guidance").status_code == 200
    _, corrected = read_pipeline(agent)
    await pipeline._step_retrieve_and_build_context(corrected)
    assert "Corrected report guidance" in json.dumps(corrected.context)
    assert answer not in json.dumps(corrected.context, ensure_ascii=False)
