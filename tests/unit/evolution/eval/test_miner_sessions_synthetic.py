"""Wave 核验 — 会话挖掘真实数据源与合成评测集生成。"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.miner import messages_from_sessions
from neurova.evolution.eval.synthetic import SyntheticDatasetBuilder, _extract_json_array


class _FakeRepo:
    def __init__(self, sessions, histories):
        self._sessions = sessions
        self._histories = histories

    def list_sessions(self, agent_id="", user_id=""):
        return self._sessions

    def get_history(self, agent_id, session_id, max_messages=0):
        return self._histories.get(session_id, [])


class TestMessagesFromSessions:
    def test_pairs_user_with_next_assistant(self):
        repo = _FakeRepo(
            [{"session_id": "s1"}],
            {"s1": [
                {"role": "user", "content": "帮我写个快排"},
                {"role": "tool", "content": "中间工具"},
                {"role": "assistant", "content": "这是快排实现: ..."},
                {"role": "user", "content": "再解释一下复杂度"},
                {"role": "assistant", "content": "平均 O(n log n)"},
            ]},
        )
        msgs = messages_from_sessions("agent-x", repo=repo)
        assert len(msgs) == 2
        assert msgs[0]["task_input"] == "帮我写个快排"
        assert msgs[0]["assistant_response"].startswith("这是快排")
        assert msgs[1]["assistant_response"] == "平均 O(n log n)"

    def test_user_without_response_pair_skipped(self):
        repo = _FakeRepo([{"session_id": "s1"}],
                         {"s1": [{"role": "user", "content": "问题"},
                                 {"role": "user", "content": "追问"}]})
        msgs = messages_from_sessions("a", repo=repo)
        assert all(m["assistant_response"] == "" for m in msgs)

    def test_repo_failure_degrades_to_empty(self):
        class _Bad:
            def list_sessions(self, **kw):
                raise RuntimeError("db down")

        assert messages_from_sessions("a", repo=_Bad()) == []

    def test_history_error_one_session_does_not_kill_batch(self):
        class _Repo:
            def list_sessions(self, **kw):
                return [{"session_id": "bad"}, {"session_id": "good"}]

            def get_history(self, agent_id, sid, max_messages=0):
                if sid == "bad":
                    raise RuntimeError("坏会话")
                return [{"role": "user", "content": "正常问题"},
                        {"role": "assistant", "content": "正常回答"}]

        msgs = messages_from_sessions("a", repo=_Repo())
        assert len(msgs) == 1

    def test_missing_session_id_skipped(self):
        repo = _FakeRepo([{"nope": 1}], {})
        assert messages_from_sessions("a", repo=repo) == []


class TestExtractJsonArray:
    def test_clean_json(self):
        assert _extract_json_array('[{"a":1}]') == [{"a": 1}]

    def test_fenced(self):
        assert _extract_json_array('```json\n[1,2]\n```') == [1, 2]

    def test_wrapped_text(self):
        assert _extract_json_array('好的:[{"x":1}] 完毕') == [{"x": 1}]

    def test_garbage(self):
        assert _extract_json_array("不是 JSON") is None


class TestSyntheticBuilder:
    @pytest.mark.asyncio
    async def test_generates_split_dataset(self):
        async def fake_call(messages, model):
            assert "评测" in str(messages)
            cases = [{"task_input": f"任务{i}", "expected_behavior": f"细则{i}",
                      "difficulty": "medium", "category": "gen"} for i in range(8)]
            import json as _json
            return {"success": True, "response": _json.dumps(cases, ensure_ascii=False)}

        b = SyntheticDatasetBuilder(EvolutionConfig(eval_dataset_size=8), llm_call=fake_call)
        ds = await b.generate("技能正文", "skill")
        assert len(ds.all_examples) == 8
        assert ds.holdout, "留出集必须非空"
        assert all(e.source == "synthetic" for e in ds.all_examples)

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        async def fake_call(messages, model):
            return {"success": False, "error": "boom"}

        b = SyntheticDatasetBuilder(EvolutionConfig(), llm_call=fake_call)
        ds = await b.generate("技能正文", "skill")
        assert ds.all_examples == []

    @pytest.mark.asyncio
    async def test_unparseable_returns_empty(self):
        async def fake_call(messages, model):
            return {"success": True, "response": "抱歉我无法生成"}

        b = SyntheticDatasetBuilder(EvolutionConfig(), llm_call=fake_call)
        ds = await b.generate("技能正文", "skill")
        assert ds.all_examples == []

    @pytest.mark.asyncio
    async def test_incomplete_cases_filtered(self):
        async def fake_call(messages, model):
            return {"success": True, "response": (
                '[{"task_input":"t1","expected_behavior":"r1"},'
                '{"task_input":"","expected_behavior":"r2"},'
                '{"task_input":"t3"}]'
            )}

        b = SyntheticDatasetBuilder(EvolutionConfig(), llm_call=fake_call)
        ds = await b.generate("技能正文", "skill")
        assert len(ds.all_examples) == 1
