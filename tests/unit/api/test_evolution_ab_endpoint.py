"""P1-7b 双臂试评端点 — /skills/{agent_id}/ab 契约测试。

双臂 = 基线正文 vs 候选正文，同一任务集（heldout 优先，真留出未被搜索
消耗）+ 同判分器对照；只读评测：不产提案、不写技能、不入台账。
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import text_evolution_api as api
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.runner import SkillEvolutionRunner

BASE = "/api/v1/evolution"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "u1", "username": "admin", "role": "admin", "neuser_id": "u1"}

SKILL_ID = "s1"
BASELINE = "基线技能正文。" * 10
CANDIDATE = "基线技能正文。改进版。" * 10


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("NEUROVA_EVAL_DATASETS_DIR", str(tmp_path / "datasets"))
    ds = EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        heldout=[EvalExample(task_input=f"HELD{i}", expected_behavior="r") for i in range(2)],
    )
    from neurova.evolution.eval.dataset import dataset_dir_for

    ds.save(dataset_dir_for(SKILL_ID))
    return tmp_path


@pytest.fixture
def client(env, monkeypatch):
    import neurova.skills.skill_service as ss

    monkeypatch.setattr(
        ss.SkillService, "get_skill_info",
        lambda self, sid: {
            "manifest": {"config": {"context_template": BASELINE}},
            "description": "",
        },
    )
    # 离线判分：按正文标记给分（基线 0.2 / 含"改进版" 0.9）
    async def fake_evaluate(self, skill_text, examples, artifact_type):
        score = 0.9 if "改进版" in skill_text else 0.2
        details = [(ex, score, "", "", False) for ex in examples]
        return sum(s for _ex, s, _o, _f, _failed in details) / len(details), details

    monkeypatch.setattr(SkillEvolutionRunner, "_evaluate", fake_evaluate)

    app = FastAPI()
    app.include_router(api.router, prefix=BASE)
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
        yield c


class TestAbEndpoint:
    def test_dual_matrix_contract(self, client):
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["task_split"] == "heldout"  # 真留出集优先
        assert data["n"] == 2
        assert data["baseline_avg"] == pytest.approx(0.2)
        assert data["candidate_avg"] == pytest.approx(0.9)
        assert data["delta"] == pytest.approx(0.7)
        assert len(data["per_task"]) == 2
        assert set(data["per_task"][0]) == {"task_input", "baseline", "candidate"}
        assert data["per_task"][0]["task_input"].startswith("HELD")

    def test_falls_back_to_selection_split(self, client, env):
        from neurova.evolution.eval.dataset import dataset_dir_for

        ds = EvalDataset(holdout=[EvalExample(task_input="h0", expected_behavior="r")])
        ds.save(dataset_dir_for("s2"))  # 独立目录：无 heldout 残留
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": "s2", "candidate_text": CANDIDATE})
        assert r.status_code == 200
        assert r.json()["data"]["task_split"] == "selection"

    def test_read_only_no_side_effects(self, client, tmp_path):
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE})
        assert r.status_code == 200
        evo_dir = tmp_path / "agents" / "a1" / "evolution"
        assert not (evo_dir / "proposals.json").exists()
        assert not (evo_dir / "history").exists()

    def test_missing_skill_404(self, client, monkeypatch):
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(ss.SkillService, "get_skill_info", lambda self, sid: None)
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": "nope", "candidate_text": CANDIDATE})
        assert r.status_code == 404

    def test_empty_candidate_422(self, client):
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": "   "})
        assert r.status_code == 422

    def test_non_admin_forbidden(self, client):
        # 移除 admin 替身、只留普通用户：admin 闸必须拦住
        client.app.dependency_overrides[get_current_user] = lambda: USER
        client.app.dependency_overrides.pop(api._admin_dep, None)
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE})
        assert r.status_code in (401, 403)


class TestAbCompareService:
    @pytest.mark.asyncio
    async def test_prefers_heldout_and_read_only(self, tmp_path, monkeypatch):
        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.service import SkillEvolutionService

        svc = SkillEvolutionService("a1", base_dir=tmp_path / "evo")
        ds = EvalDataset(
            holdout=[EvalExample(task_input="h0", expected_behavior="r")],
            heldout=[EvalExample(task_input="HELD0", expected_behavior="r"),
                     EvalExample(task_input="HELD1", expected_behavior="r")],
        )

        async def fake_evaluate(self, skill_text, examples, artifact_type):
            score = 0.9 if "改进版" in skill_text else 0.2
            return score, [(ex, score, "", "", False) for ex in examples]

        monkeypatch.setattr(SkillEvolutionRunner, "_evaluate", fake_evaluate)
        report = await svc.ab_compare(baseline_text="旧", candidate_text="新改进版",
                                      dataset=ds, config=EvolutionConfig())
        assert report["task_split"] == "heldout"
        assert report["n"] == 2
        assert report["delta"] == pytest.approx(0.7)
        assert not (tmp_path / "evo" / "proposals.json").exists()


class _AgentStub:
    """真 agent 替身：留下 chat 收到的参数，以及**当时**本轮覆盖槽的读数。"""

    def __init__(self):
        self.calls = []
        self.overrideSeen = []

    async def chat(self, user_input, **kwargs):
        from neurova.core import turn_context

        self.calls.append({"user_input": user_input, **kwargs})
        self.overrideSeen.append(turn_context.get_turn_skill_text_override("s1"))
        return {"text": f"out::{user_input}", "audio_path": None, "audio_data": None}


class TestAbExecutorFace:
    """执行面来源必须一路到 HTTP 之外（票面 Task 4：写了必须有人读，且不靠端点自己猜）。"""

    def test_simulatedArmIsLabelledOnTheWire(self, client):
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE})
        assert r.status_code == 200
        assert r.json()["data"]["executor_kind"] == "simulated", r.json()

    def test_realArmRunsWithTheAgent(self, env, monkeypatch):
        """真臂：端点在装配点注入执行器，评测回合真经过 agent.chat(save_memory=False)。"""
        import neurova.api.endpoints as endpoints
        import neurova.evolution.eval.fitness as fitness
        import neurova.skills.skill_service as ss

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance",
                            lambda agent_id="": agent, raising=False)
        monkeypatch.setattr(ss.SkillService, "get_skill_info",
                            lambda self, sid: {
                                "name": "s1",
                                "manifest": {"config": {"context_template": BASELINE}},
                                "description": "",
                            })

        async def fakeScore(self, **kw):
            from neurova.evolution.eval.fitness import FitnessScore

            value = 0.9 if "改进版" in kw.get("skill_text", "") else 0.2
            return FitnessScore(correctness=value, procedure_following=value,
                                conciseness=value, feedback="")

        monkeypatch.setattr(fitness.LLMJudge, "score", fakeScore, raising=False)

        app = FastAPI()
        app.include_router(api.router, prefix=BASE)
        with TestClient(app, raise_server_exceptions=False) as c:
            c.app.dependency_overrides[get_current_user] = lambda: USER
            c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
            r = c.post(f"{BASE}/skills/a1/ab",
                       json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE,
                             "real_trajectory": True})

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "real_agent", data
        assert agent.calls, "真臂根本没跑 agent 回合"
        assert {call.get("save_memory") for call in agent.calls} == {False}, agent.calls
        assert all("$s1" in call["user_input"] for call in agent.calls), agent.calls

        # 票面 Task 5 Step 5 的活体格：候选正文**经覆盖槽经到 agent 那一侧**，
        # 且两臂各拿自己那一份（基线臂读基线正文、候选臂读候选正文），
        # 请求结束后本轮不再有残留覆盖。
        from neurova.core import turn_context

        assert agent.overrideSeen == [BASELINE, BASELINE, CANDIDATE, CANDIDATE], agent.overrideSeen
        assert turn_context.get_turn_skill_text_override("s1") is None, (
            "回合结束后覆盖槽没复位，正文会续进下一轮")

    def test_realArmRefusedWhenAgentMissing(self, client, monkeypatch):
        """拿不到 agent ⇒ 409 点名原因；**绝不静默回落成模拟面**（教义第 2 条）。"""
        import neurova.api.endpoints as endpoints

        monkeypatch.setattr(endpoints, "get_agent_instance",
                            lambda agent_id="": None, raising=False)
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE,
                              "real_trajectory": True})
        assert r.status_code == 409, r.text
        assert "不在线" in r.json()["detail"], r.json()

    def test_realArmRefusedWhenSkillNameCannotBeMentioned(self, client, monkeypatch):
        """名字组不出 $mention ⇒ 候选正文进不了本轮 ⇒ 两臂同文的假 0 差，必须当场拒。"""
        import neurova.api.endpoints as endpoints
        import neurova.skills.skill_service as ss

        monkeypatch.setattr(endpoints, "get_agent_instance",
                            lambda agent_id="": _AgentStub(), raising=False)
        monkeypatch.setattr(ss.SkillService, "get_skill_info",
                            lambda self, sid: {
                                "name": "web search",
                                "manifest": {"config": {"context_template": BASELINE}},
                                "description": "",
                            })
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE,
                              "real_trajectory": True})
        assert r.status_code == 422, r.text
        assert "mention" in r.json()["detail"], r.json()

