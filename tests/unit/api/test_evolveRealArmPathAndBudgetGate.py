"""进化主路径切真臂：请求级开关、预算前置闸、臂来源外露（P1-C 线）。

票面出处：`docs/08-research/designer_rsi_paper_vs_neurova_rsi_comparison_2026-10-08.md` §4 P1-C，
节奏沿用同仓 `/ab` 的既有裁定——**默认仍模拟面，真臂由请求显式开**；因此
`probeRealTrajectoryExecutor`（RSI 自动晋升档的第四条前置否决）在本批之后**仍应是 False**，
这条蕴涵格写在下面第一格里：安全档不因"能开真臂"而被动过。

本档最硬的一格是 `testBudgetRefusesBeforeSpendingAnyTurn`：拒绝必须发生在**第一个回合之前**，
否则闸只是事后账单。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import text_evolution_api as api
from neurova.evolution.eval.dataset import EvalDataset, EvalExample

BASE = "/api/v1/evolution"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "u1", "username": "admin", "role": "admin", "neuser_id": "u1"}

SKILL_ID = "s1"
BASELINE = "基线技能正文。" * 10
CANDIDATE = "基线技能正文。改进版。" * 10


class _AgentStub:
    """真 agent 替身：留下 chat 收到的正文，本身也用来证明"拒绝前一个回合都没花"。"""

    def __init__(self):
        self.calls = []

    async def chat(self, user_input, **kwargs):
        self.calls.append({"user_input": user_input, **kwargs})
        return {"text": f"out::{user_input}", "audio_path": None, "audio_data": None}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setenv("NEUROVA_EVAL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    ds = EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        heldout=[EvalExample(task_input=f"HELD{i}", expected_behavior="r") for i in range(2)],
    )
    from neurova.evolution.eval.dataset import dataset_dir_for

    ds.save(dataset_dir_for(SKILL_ID))
    return tmp_path


@pytest.fixture
def offline(monkeypatch):
    """把判分、模拟臂与变异器都钉成离线：本档量的是装配与闸，不是模型。"""
    import neurova.evolution.eval.fitness as fitness
    import neurova.evolution.eval.mutator as mutator
    import neurova.evolution.eval.service as service

    async def fakeScore(self, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        value = 0.9 if "改进版" in kw.get("skill_text", "") else 0.2
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")

    async def fakeSimRun(self, *, skill_text, task_input):
        return f"sim::{task_input}"

    async def fakeMutate(self, *, artifact_text, artifact_type, failures, **kw):
        """离线变异：候选正文必须与基线不同，否则进化轮整个 no-op（走不到候选评测）。"""
        return artifact_text + "改进版。"

    monkeypatch.setattr(fitness.LLMJudge, "score", fakeScore, raising=False)
    monkeypatch.setattr(service.SimulatedAgent, "run", fakeSimRun, raising=False)
    monkeypatch.setattr(mutator.ReflectiveMutator, "mutate", fakeMutate, raising=False)


def _skillInfo(monkeypatch):
    import neurova.skills.skill_service as ss

    monkeypatch.setattr(ss.SkillService, "get_skill_info",
                        lambda self, sid: {
                            "id": sid, "name": SKILL_ID,
                            "manifest": {"config": {"context_template": BASELINE}},
                            "description": "",
                        })


def _client():
    app = FastAPI()
    app.include_router(api.router, prefix=BASE)
    c = TestClient(app, raise_server_exceptions=False)
    c.app.dependency_overrides[get_current_user] = lambda: USER
    c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
    return c


def _postEvolve(client, agent_id, payload):
    return client.post(f"{BASE}/skills/{agent_id}/evolve", json=payload)


class TestEvolveArmSwitch:
    def testDefaultRequestPrefersRealArmAndFallsBackWhenAgentOffline(
        self, env, offline, monkeypatch
    ):
        """默认 auto：在线走真臂；离线回落模拟面，但必须显式标注回落原因。"""
        import neurova.api.endpoints as endpoints
        import neurova.evolution.eval.service as service
        from neurova.evolution.rsi.automation_prerequisites import probeRealTrajectoryExecutor

        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": None,
                            raising=False)
        _skillInfo(monkeypatch)
        monkeypatch.setattr(service.SimulatedAgent, "declaresRealAgentTrajectory",
                            lambda self: True, raising=False)
        client = _client()
        r = _postEvolve(client, "a1", {"skill_id": SKILL_ID, "iterations": 1})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "simulated", data
        assert data["executor_requested"] == "auto", data
        assert data["real_trajectory_fallback"] == "agent_offline", data
        assert data["agent_turns_used"] is None, data
        assert data["planned_agent_turns"] is None, data
        # 上面那行 monkeypatch 是反证：给模拟臂硬塞一个"真回合"声明也不许翻旗标
        # （能力由结构推导：没有 agent_ref 就不是真臂）
        assert probeRealTrajectoryExecutor() is False

    def testDefaultRequestUsesRealArmWhenAgentOnline(self, env, offline, monkeypatch):
        import neurova.api.endpoints as endpoints
        from neurova.evolution.rsi.automation_prerequisites import probeRealTrajectoryExecutor

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        client = _client()
        r = _postEvolve(client, "a1", {"skill_id": SKILL_ID, "iterations": 1})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "real_agent", data
        assert data["executor_requested"] == "auto", data
        assert data.get("real_trajectory_fallback", "") == "", data
        assert agent.calls, "默认 auto 在 agent 在线时必须跑真回合"
        # 默认 auto 只改请求面；RSI 自动晋升的第四条前置仍按生产装配点推导，不因本端点翻真。
        assert probeRealTrajectoryExecutor() is False

    def testDefaultAutoFallsBackWhenBudgetExceeded(self, env, offline, monkeypatch):
        """auto 档遇预算不足：不花回合，回落到模拟面并标注 budget_exceeded。"""
        import neurova.api.endpoints as endpoints

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        client = _client()
        r = _postEvolve(client, "a1", {"skill_id": SKILL_ID, "iterations": 10})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "simulated", data
        assert data["executor_requested"] == "auto", data
        assert data["real_trajectory_fallback"] == "budget_exceeded", data
        assert agent.calls == [], "回退也必须发生在第一个回合之前"

    def testRealArmFlagReachesTheAgentAndReportsTurns(self, env, offline, monkeypatch):
        import neurova.api.endpoints as endpoints

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        client = _client()
        r = _postEvolve(client, "a1",
                        {"skill_id": SKILL_ID, "iterations": 1, "real_trajectory": True})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "real_agent", data
        # 计划是**上界**（装配体里还有约束闸/泄漏闸会跳过候选），所以真实数只许 ≤ 计划数；
        # 反向（used > planned）才是漂移信号，由 budget_plan_exceeded 外露。
        assert data["planned_agent_turns"] == 17, data
        assert data["agent_turns_used"] <= data["planned_agent_turns"], data
        assert data["budget_plan_exceeded"] is False, data
        assert agent.calls, "真臂根本没跑 agent 回合"
        assert {c.get("save_memory") for c in agent.calls} == {False}, agent.calls

    def testAgentMissingIs409NeverSilentDowngrade(self, env, offline, monkeypatch):
        """拿不到 agent ⇒ 409；绝不静默回落模拟面（教义第 2 条，与 /ab 同一条接缝）。"""
        import neurova.api.endpoints as endpoints

        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": None,
                            raising=False)
        _skillInfo(monkeypatch)
        client = _client()
        r = _postEvolve(client, "a1",
                        {"skill_id": SKILL_ID, "iterations": 1, "real_trajectory": True})
        assert r.status_code == 409, r.text
        assert "真轨迹" in r.json()["detail"] or "不在线" in r.json()["detail"], r.json()


class TestBudgetGateBeforeSpending:
    def testBudgetRefusesBeforeSpendingAnyTurn(self, env, offline, monkeypatch):
        """默认整轮进化的计划数远超默认预算 ⇒ 422，且**一个回合都没花**。"""
        import neurova.api.endpoints as endpoints

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        # train2+holdout2+heldout2、iterations=10 ⇒ 计划数 = 1+2+2+10*(2+2)+2+2+4 = 53 > 40
        client = _client()
        r = _postEvolve(client, "a1",
                        {"skill_id": SKILL_ID, "iterations": 10, "real_trajectory": True})
        assert r.status_code == 422, r.text
        assert agent.calls == [], "闸在花钱之后才判，那就不是预算闸"
        detail = r.json()["detail"]
        assert "53" in detail and "40" in detail, detail
        assert "candidateEvaluations" in detail, detail

    def testRaisedBudgetLetsTheSameRequestThrough(self, env, offline, monkeypatch):
        import neurova.api.endpoints as endpoints
        from neurova.evolution.evolution_settings import update_settings

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        update_settings(real_arm_max_agent_turns=60)
        client = _client()
        r = _postEvolve(client, "a1",
                        {"skill_id": SKILL_ID, "iterations": 10, "real_trajectory": True})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["planned_agent_turns"] == 53, r.json()["data"]

    def testSimulatedArmIsNeverBoundedByTheRealArmBudget(self, env, offline, monkeypatch):
        """预算只管真臂：把键压到 1，模拟面照跑（闸不得变成第二套降级路径）。"""
        from neurova.evolution.evolution_settings import update_settings

        update_settings(real_arm_max_agent_turns=1)
        _skillInfo(monkeypatch)
        client = _client()
        r = _postEvolve(client, "a1",
                        {"skill_id": SKILL_ID, "iterations": 2, "real_trajectory": False})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["executor_kind"] == "simulated", data
        assert data["executor_requested"] == "simulated", data
        assert data["planned_agent_turns"] is None, data

    def testAbPathSharesTheSameGate(self, env, offline, monkeypatch):
        """同根因扫荡：双臂侧的真臂走的是同一道预算闸，不是一边有闸一边没有。"""
        import neurova.api.endpoints as endpoints
        from neurova.evolution.evolution_settings import update_settings

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        update_settings(real_arm_max_agent_turns=1)
        client = _client()
        r = client.post(f"{BASE}/skills/a1/ab",
                        json={"skill_id": SKILL_ID, "candidate_text": CANDIDATE,
                              "real_trajectory": True})
        assert r.status_code == 422, r.text
        assert agent.calls == [], r.text
        assert r.json()["detail"].startswith("真臂预算不足")


class TestArmKindReachesTheApproverFace:
    """审批人不必回查文件：臂来源已随提案详情同一次取数出街（§6-95 后半那条读路径）。

    这一格是给**上一笔我自己写重的话**收口的：台账 §6-265 原写"提案面看不见臂来源、
    要回查运行文件"，复算后发现提案详情端点本来就把那次运行的审计内容嵌进同一条响应
    （`evolution_run`），臂来源因此就在审批人点开提案的那一屏里。 claim 要么被测着成立，
    要么就是 prose——所以这里补的是判据，不是文档。
    """

    def testProposalDetailEmbedsTheArmKindAndTurnCost(self, env, offline, monkeypatch):
        import neurova.api.endpoints as endpoints

        agent = _AgentStub()
        monkeypatch.setattr(endpoints, "get_agent_instance", lambda agent_id="": agent,
                            raising=False)
        _skillInfo(monkeypatch)
        # 本档的候选正文是"基线 + 一句改进"：增长闸（+57%）与语义闸（0.714 < 0.75）
        # 都会先把它拦在预评测，提案因此压根不产生——那是闸在按设计工作，
        # 与本档要验的"臂来源进提案详情"无关。两闸自身有专档
        # `tests/unit/evolution/eval/test_constraints.py` 双向钉住，这里只让它们不参与裁决。
        from neurova.evolution.eval import config as evalConfig

        realConfig = evalConfig.EvolutionConfig

        def relaxedConfig(*args, **kwargs):
            cfg = realConfig(*args, **kwargs)
            cfg.semantic_similarity_threshold = 0.0
            cfg.max_prompt_growth = 10.0
            return cfg

        monkeypatch.setattr(evalConfig, "EvolutionConfig", relaxedConfig)
        client = _client()
        posted = _postEvolve(client, "a1",
                             {"skill_id": SKILL_ID, "iterations": 1, "real_trajectory": True})
        assert posted.status_code == 200, posted.text
        proposalId = (posted.json()["data"].get("proposal") or {}).get("proposal_id")
        assert proposalId, "这条链没出提案，详情面无可验"

        r = client.get(f"{BASE}/skills/a1/proposals/{proposalId}")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["evolution_run_status"] == "attached", data["evolution_run_status"]
        run = data["evolution_run"]
        assert run["executor_kind"] == "real_agent", run
        assert run["model_under_test"] == "agent_routed", run
        # 计划与真实花费同时出街：审批人看得见这条证据花了多少回合、上限算的是多少。
        # 17 = 本夹具那份集（train2/holdout2/heldout2、iterations=1、锚定地板开）；
        # 两面必须给同一个数——运行审计与响应各算一遍就是第二份口径。
        assert run["planned_agent_turns"] == 17, run
        assert run["planned_agent_turns"] == posted.json()["data"]["planned_agent_turns"], run
        assert run["agent_turns_used"] <= run["planned_agent_turns"], run
        assert run["budget_plan_exceeded"] is False, run


    def testPutReachesTheNewKeyAndTheThreeLaggingRsiKnobs(self, env, monkeypatch):
        """可达性那一半（覆盖性的守卫在 `test_adminPutWhitelistCoversConfigSingleSource.py`，
        同一族病一档收口，不在这里再判一遍字段集合）。"""
        from neurova.evolution.evolution_settings import load_settings

        client = _client()
        r = client.put(f"{BASE}/settings", json={
            "real_arm_max_agent_turns": 123,
            "rsi_event_throttle_seconds": 5.0,
            "rsi_backoff_every_turns": 3,
            "rsi_ratchet_candidates": [10, 5],
        })
        assert r.status_code == 200, r.text
        settings = load_settings()
        assert settings.real_arm_max_agent_turns == 123, settings
        assert settings.rsi_event_throttle_seconds == 5.0, settings
        assert settings.rsi_backoff_every_turns == 3, settings
        assert settings.rsi_ratchet_candidates == [10, 5], settings
