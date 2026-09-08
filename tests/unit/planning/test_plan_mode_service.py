# -*- coding: utf-8 -*-
"""Plan Mode 服务层测试（ZCode 计划模式对齐）。

覆盖：
1. PlanDocStore —— MD 计划文档落盘 agent 工作目录 docs/plan/（自动建目录、
   文件名=YYYYMMDD-HHMMSS-<标题slug>.md、同名冲突避让、路径穿越防护、
   按 agent 隔离、列表倒序）；
2. PlanSession 状态机 —— asking →（不限轮问答）→ awaiting_approval →
   approved/rejected；LLM JSON 容错（code fence）；空回答拒绝；补充追问；
   批准后 execute_prompt 含计划全文；
3. PlanSessionManager —— 归属隔离（非本人不可见）、TTL 过期、单例。
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from neurova.plan_mode import (
    PlanDocError,
    PlanDocStore,
    PlanError,
    PlanLLMError,
    PlanSession,
    PlanSessionManager,
    PlanStateError,
    get_plan_doc_store,
    get_plan_session_manager,
    reset_plan_doc_store,
    reset_plan_session_manager,
)

# ---------------------------------------------------------------------------
# 测试脚手架
# ---------------------------------------------------------------------------

QUESTIONS_R1 = {
    "done": False,
    "questions": [
        {
            "id": "q1",
            "question": "目标平台是什么？",
            "options": [
                {"label": "Web", "description": "浏览器端"},
                {"label": "桌面", "description": "Electron/Tauri"},
            ],
            "multi": False,
            "allow_custom": True,
        }
    ],
}

QUESTIONS_R2 = {
    "done": False,
    "questions": [
        {"id": "q2", "question": "预算范围？", "options": [], "multi": False, "allow_custom": True}
    ],
}

PLAN_RESULT = {
    "title": "重构登录模块",
    "markdown": "# 计划：重构登录模块\n\n## 步骤\n1. 梳理现状\n2. 实施重构\n",
}


def _llm_factory(script):
    """按调用次序回放脚本化 LLM 响应的假桥（dict 项自动序列化为 JSON）。"""
    import json as _json

    calls = {"n": 0, "prompts": []}

    async def fake_llm(prompt: str) -> str:
        calls["prompts"].append(prompt)
        idx = min(calls["n"], len(script) - 1)
        calls["n"] += 1
        item = script[idx]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return _json.dumps(item, ensure_ascii=False)
        return item

    fake_llm.calls = calls
    return fake_llm


def _new_session(llm, agent_id="default", user_id="u1", request="重构登录模块"):
    return PlanSession(
        session_id="sess-1",
        agent_id=agent_id,
        user_id=user_id,
        request=request,
        llm_call=llm,
    )


@pytest.fixture()
def store(tmp_path):
    return PlanDocStore(base_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# PlanDocStore
# ---------------------------------------------------------------------------


class TestPlanDocStore:
    def test_save_creates_missing_dirs_and_writes_file(self, store, tmp_path):
        """目录不存在 → 自动创建 agent_workspaces/<id>/docs/plan/。"""
        result = store.save(agent_id="default", title="重构登录模块", content=PLAN_RESULT["markdown"])
        rel = Path(result["rel_path"])
        assert rel == Path("docs/plan") / result["name"]
        abs_path = tmp_path / "default" / rel
        assert abs_path.exists()
        assert abs_path.read_text(encoding="utf-8") == PLAN_RESULT["markdown"]

    def test_filename_is_datetime_prefixed_with_title_slug(self, store, tmp_path):
        result = store.save(agent_id="a1", title="重构/登录:模块?", content="x")
        name = result["name"]
        # YYYYMMDD-HHMMSS-<slug>.md
        stem = name[:-3]
        parts = stem.split("-", 2)
        assert len(parts[0]) == 8 and parts[0].isdigit()
        assert len(parts[1]) == 6 and parts[1].isdigit()
        assert parts[2] == "重构-登录-模块"
        assert name.endswith(".md")

    def test_filename_empty_title_falls_back(self, store):
        result = store.save(agent_id="a1", title="///", content="x")
        stem = result["name"][:-3].split("-", 2)[2]
        assert stem == "plan"

    def test_same_second_collision_gets_suffix(self, store):
        r1 = store.save(agent_id="a1", title="计划", content="1")
        r2 = store.save(agent_id="a1", title="计划", content="2")
        assert r1["name"] != r2["name"]
        assert store.read("a1", r2["name"]) == "2"

    def test_read_rejects_traversal_and_bad_names(self, store):
        for bad in ("../x.md", "a/../b.md", "/abs.md", "x.txt", "..", "a/b.md"):
            with pytest.raises(PlanDocError):
                store.read("a1", bad)

    def test_read_missing_file_raises(self, store):
        with pytest.raises(PlanDocError):
            store.read("a1", "20260101-000000-ghost.md")

    def test_agents_are_isolated(self, store):
        store.save(agent_id="a1", title="甲的计划", content="A 内容")
        docs_b = store.list_documents("a2")
        assert docs_b == []

    def test_list_documents_newest_first(self, store):
        d1 = store.save(agent_id="a1", title="一", content="1")
        time.sleep(0.02)
        d2 = store.save(agent_id="a1", title="二", content="2")
        listed = store.list_documents("a1")
        assert [d["name"] for d in listed] == [d2["name"], d1["name"]]
        assert {"name", "rel_path", "size", "modified"} <= set(listed[0].keys())


# ---------------------------------------------------------------------------
# PlanSession 状态机
# ---------------------------------------------------------------------------


class TestPlanSessionStateMachine:
    def test_start_generates_first_round_questions(self):
        import json as _json

        llm = _llm_factory(["```json\n" + _json.dumps(QUESTIONS_R1, ensure_ascii=False) + "\n```"])
        sess = _new_session(llm)
        asyncio.run(sess.ensure_started())
        assert sess.status == PlanSession.STATUS_ASKING
        assert sess.rounds[0]["questions"][0]["id"] == "q1"
        # code fence 容错：原始 JSON 被解析而非报错
        assert llm.calls["n"] == 1

    def test_answers_advance_unlimited_rounds(self):
        llm = _llm_factory([QUESTIONS_R1, QUESTIONS_R2, QUESTIONS_R2])
        sess = _new_session(llm)
        asyncio.run(sess.ensure_started())
        for _ in range(3):  # 不限轮数：连续三轮问答均为出题而非强制收口
            asyncio.run(
                sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": ""}])
            )
        assert sess.status == PlanSession.STATUS_ASKING
        assert len(sess.rounds) == 4
        assert sess.rounds[0]["answers"][0]["selected"] == ["Web"]

    def test_done_generates_plan_document(self, store):
        llm = _llm_factory([QUESTIONS_R1, PLAN_RESULT])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": "补充"}]))
        assert sess.status == PlanSession.STATUS_AWAITING_APPROVAL
        assert sess.document["name"].endswith(".md")
        assert sess.document["title"] == "重构登录模块"
        assert "重构登录模块" in store.read("default", sess.document["name"])

    def test_supplement_only_submission_is_valid(self, store):
        llm = _llm_factory([QUESTIONS_R1, QUESTIONS_R2])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[], supplement="我还想支持移动端"))
        assert sess.status == PlanSession.STATUS_ASKING
        assert len(sess.rounds) == 2
        # supplement 透传给 LLM 提示词
        assert "移动端" in llm.calls["prompts"][-1]

    def test_empty_answers_and_supplement_rejected(self):
        llm = _llm_factory([QUESTIONS_R1])
        sess = _new_session(llm)
        asyncio.run(sess.ensure_started())
        with pytest.raises(PlanStateError):
            asyncio.run(sess.submit_answers(answers=[], supplement="  "))

    def test_decide_approve_builds_execute_prompt_with_full_plan(self, store):
        llm = _llm_factory([QUESTIONS_R1, PLAN_RESULT])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": ""}]))
        asyncio.run(sess.decide("approve"))
        assert sess.status == PlanSession.STATUS_APPROVED
        assert "重构登录模块" in sess.execute_prompt
        assert sess.document["rel_path"] in sess.execute_prompt
        assert "梳理现状" in sess.execute_prompt  # 计划全文注入执行提示

    def test_decide_reject(self, store):
        llm = _llm_factory([QUESTIONS_R1, PLAN_RESULT])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": ""}]))
        asyncio.run(sess.decide("reject", note="范围太大"))
        assert sess.status == PlanSession.STATUS_REJECTED

    def test_decide_invalid_action_and_state(self, store):
        llm = _llm_factory([QUESTIONS_R1])
        sess = _new_session(llm)
        asyncio.run(sess.ensure_started())
        with pytest.raises(PlanStateError):
            asyncio.run(sess.decide("approve"))  # asking 态无计划可批
        with pytest.raises(PlanStateError):
            asyncio.run(sess.decide("destroy"))

    def test_supplement_after_draft_returns_to_asking(self, store):
        """awaiting_approval 态继续补充 → 回到 asking 追加新一轮。"""
        llm = _llm_factory([QUESTIONS_R1, PLAN_RESULT, QUESTIONS_R2])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": ""}]))
        asyncio.run(sess.submit_answers(answers=[], supplement="补充：还要支持暗色主题"))
        assert sess.status == PlanSession.STATUS_ASKING
        assert len(sess.rounds) == 2

    def test_terminal_state_is_immutable(self, store):
        llm = _llm_factory([QUESTIONS_R1, PLAN_RESULT])
        sess = _new_session(llm)
        sess._doc_store = store
        asyncio.run(sess.ensure_started())
        asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["Web"], "custom": ""}]))
        asyncio.run(sess.decide("approve"))
        with pytest.raises(PlanStateError):
            asyncio.run(sess.submit_answers(answers=[{"id": "q1", "selected": ["x"], "custom": ""}]))

    def test_llm_garbage_raises_plan_llm_error(self):
        llm = _llm_factory(["这不是 JSON"])
        sess = _new_session(llm)
        with pytest.raises(PlanLLMError):
            asyncio.run(sess.ensure_started())

    def test_llm_failure_propagates(self):
        llm = _llm_factory([RuntimeError("llm down")])
        sess = _new_session(llm)
        with pytest.raises(RuntimeError):
            asyncio.run(sess.ensure_started())


# ---------------------------------------------------------------------------
# PlanSessionManager
# ---------------------------------------------------------------------------


class TestPlanSessionManager:
    def test_create_get_and_owner_isolation(self):
        mgr = PlanSessionManager(ttl_seconds=3600)
        sess = asyncio.run(
            mgr.create(
                agent_id="default",
                user_id="u1",
                request="需求",
                llm_call=_llm_factory([QUESTIONS_R1]),
            )
        )
        assert mgr.get(sess.session_id, "u1") is sess
        assert mgr.get(sess.session_id, "u2") is None  # 非 owner 不可见

    def test_ttl_expiry_evicts_session(self):
        mgr = PlanSessionManager(ttl_seconds=3600)
        sess = asyncio.run(
            mgr.create(
                agent_id="default",
                user_id="u1",
                request="需求",
                llm_call=_llm_factory([QUESTIONS_R1]),
                ensure_started=False,
            )
        )
        sess.updated_at -= 7200  # 人为拨快过期
        assert mgr.get(sess.session_id, "u1") is None

    def test_singleton_get_reset(self):
        reset_plan_session_manager()
        m1 = get_plan_session_manager()
        assert get_plan_session_manager() is m1
        reset_plan_session_manager()
        assert get_plan_session_manager() is not m1


# ---------------------------------------------------------------------------
# PlanDocStore 单例
# ---------------------------------------------------------------------------


class TestDocStoreSingleton:
    def test_singleton_get_reset(self):
        reset_plan_doc_store()
        s1 = get_plan_doc_store()
        assert get_plan_doc_store() is s1
        reset_plan_doc_store()
        assert get_plan_doc_store() is not s1


# ---------------------------------------------------------------------------
# 错误类型层级
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_subtypes_are_plan_error(self):
        assert issubclass(PlanStateError, PlanError)
        assert issubclass(PlanLLMError, PlanError)
        assert issubclass(PlanDocError, PlanError)
