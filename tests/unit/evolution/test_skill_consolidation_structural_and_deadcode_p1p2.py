"""Issue #46 收口 P1/P2 回归——结构身份聚类 / 审批面归属 / 死代码真删。

三条链各自"旧实现为什么不对"的锚点：

P1-1 合并能力是"前半程"
    consolidator 只按**名字前缀**聚簇。P1-1 已判定的"同一技能被封装成
    多条"（同工具序列、异名形态：`skill_<fp16>` / `genetic_<tools>` /
    `synth_*`）**聚不到同一簇**——重复被判出来了、却合并不了。已改为按
    结构身份（工具序列族）聚类，并标注本簇是"真重复"还是"跨意图收编"。

P1-2 合并审批面未校验 agent 归属
    `{umbrella}/approve|reject` 是**写操作**（归档被吸收技能），却只按路径
    参数 `agent_id` 取库——任何登录用户知道 id 就能批准任意 agent 的合并。
    已补 owner 校验（与 agent 写口同一判据单源 `api/agent_access.py`）。

P2 死代码"标注保留"而非真删
    `SkillPacker` / `skill_packer` 模块、`create_default_pipeline` + 四个旧
    Step 类、`PipelineConfig` 里 6 个从未被读取的开关——审计报告写着"保留
    待清理"，实际是把"还有调用方"的错觉留给后来者。已迁移测试引用后真删。
"""

import os

import pytest

pytestmark = pytest.mark.timeout(60)


# ══════════════════════════════════════════════════════════════
# P1-1：结构身份聚类（旧实现只按名字前缀聚）
# ══════════════════════════════════════════════════════════════

STEP_A = [{"tool": "file_read", "params": {"path": "a.txt"}},
          {"tool": "file_write", "params": {"path": "b.txt"}}]
STEP_B = [{"tool": "http_get", "params": {"url": "x"}},
          {"tool": "file_write", "params": {}}]


def _facts(**overrides):
    from neurova.evolution.skill_consolidator import _entry_fact

    out = {}
    for sid, fact in overrides.items():
        out[sid] = _entry_fact({}, {"manifest": {"config": {"tool_sequence": fact[0],
                                                            "task_purpose": fact[1]}},
                                   "description": fact[1]})
    return out


class TestStructuralClustering:
    def test_same_sequence_different_names_clusters_together(self):
        """**旧实现的核心失效点**：同序列、异名形态聚不到一起。

        三条写入臂各造一个名字（`skill_<fp16>` / `genetic_<tools>` /
        `synth_*`），但工具序列与业务意图相同——是同一技能的三条重复条目。
        旧 `find_prefix_clusters` 把它们分进三个前缀组（`skill` / `genetic`
        / `synth`），每组成员数 1 < min_size=2，**一个簇都不产出**：重复
        被判出来了却合并不了。
        """
        from neurova.evolution.skill_consolidator import find_structural_clusters

        facts = _facts(**{
            "skill_9ba147ea7f1bc6bf": (STEP_A, "report"),
            "genetic_file_read_file_write": (STEP_A, "report"),
            "synth_deadbeef": (STEP_A, "report"),
        })
        clusters = find_structural_clusters(facts)
        assert len(clusters) == 1, "同序列三条必须聚成一簇（旧实现聚出 0 簇）"
        assert sorted(clusters[0].members) == sorted(facts)
        assert clusters[0].basis == "identity", "序列+意图全同 = 真重复"

    def test_same_sequence_different_intent_is_marked_cross_intent(self):
        """同序列不同业务：仍聚簇（同族），但 basis 标 structure 供审批判风险。

        这是与"真重复"的**关键区分**：合并跨意图条目 = 把一个宽 umbrella
        覆盖多个业务，风险高于合并真重复，审批人必须能看出来。
        """
        from neurova.evolution.skill_consolidator import find_structural_clusters

        facts = _facts(**{
            "skill_a": (STEP_A, "发票汇总"),
            "genetic_b": (STEP_A, "pdf 转换"),
        })
        clusters = find_structural_clusters(facts)
        assert len(clusters) == 1
        assert clusters[0].basis == "structure"
        assert len(set(clusters[0].intents.values())) == 2, "两个不同业务身份"

    def test_different_sequences_do_not_merge(self):
        from neurova.evolution.skill_consolidator import find_structural_clusters

        facts = _facts(**{"a_x": (STEP_A, "report"), "b_y": (STEP_B, "抓取")})
        assert find_structural_clusters(facts) == [], "不同序列不得误合"

    def test_parameter_variants_are_same_family(self):
        """参数不同、工具序列相同 = 同族不同实例（参数是调用时绑定，不是身份）。

        旧实现按名字前缀聚时这批能聚上纯属巧合（名字里嵌了 md5 前缀）；
        真正的口径应是"工具名序列相同即同族"，参数差异留给业务身份标注。
        """
        from neurova.evolution.skill_consolidator import sequence_family

        loaded = [{"tool": "read", "params": {"i": 0}}, {"tool": "write", "params": {}}]
        other = [{"tool": "read", "params": {"i": 7}}, {"tool": "write", "params": {"p": 1}}]
        assert sequence_family(loaded) == sequence_family(other) == "read → write"

    def test_entries_without_sequence_fall_back_to_name_prefix(self):
        """无工具序列的存量条目（手工/用户技能）走名字前缀兜底，且如实标注。

        它们本来就没有结构可依——但 basis 必须标 "name_prefix"，不能冒充
        "结构身份判定"，否则审批人会以为簇是结构聚出来的。
        """
        from neurova.evolution.skill_consolidator import find_structural_clusters

        facts = _facts(**{"deploy-helper-a": ([], "部署辅助"),
                          "deploy-helper-b": ([], "部署辅助")})
        clusters = find_structural_clusters(facts)
        assert len(clusters) == 1
        assert clusters[0].basis == "name_prefix"
        assert clusters[0].structure == ""


class TestPlanFromServiceUsesStructure:
    def _service(self, tmp_path):
        os.environ["NEUROVA_SKILL_REVIEW_GATE"] = "1"
        from neurova.skills.skill_service import SkillService

        return SkillService(agent_id="consol-t", skills_dir=str(tmp_path / "skills"))

    def _seed(self, svc, sid, steps, purpose):
        """直接写 manifest 造**存量重复库态**。

        为什么不走 `register_auto_skill`：P1-1 修复后服务端指纹判重会把
        "同序列同意图"的第二条收敛掉（那正是修复本身），这里**造不出**重复。
        但 consolidator 要面对的恰恰是**修复之前就已积累**的旧库——那时的
        三条臂各写各的 ID，库里真有多条同身份条目。合并能力的存在意义就是
        收拾这种存量；用真实落盘路径造这个态，测试才有意义。
        """
        import json

        svc._load_skills()
        svc._skills[sid] = {
            "id": sid, "name": sid, "version": "1.0.0",
            "description": f"处理 {purpose}",
            "enabled": True, "installed_at": "2026-01-01T00:00:00",
            "path": "", "pool_type": "agent", "owner_user_id": svc.agent_id,
            "manifest": {"source": "auto",
                         "config": {"tool_sequence": steps, "task_purpose": purpose}},
        }
        assert svc._save_manifest(), "存量库态落盘失败"
        return True

    def test_plan_covers_cross_named_duplicates(self, tmp_path):
        """端到端：三条臂异名同序列 → 计划必须覆盖（旧实现产出空计划）。"""
        from neurova.evolution.skill_consolidator import plan_from_service

        svc = self._service(tmp_path)
        self._seed(svc, "skill_aaaa", STEP_A, "report")
        self._seed(svc, "genetic_file_read_file_write", STEP_A, "report")
        self._seed(svc, "synth_bbbb", STEP_A, "report")
        plans = plan_from_service(svc)
        assert len(plans) == 1, "异名同序列必须产出合并计划"
        assert plans[0].basis == "identity"
        assert len(plans[0].absorbed) == 2
        assert plans[0].structure == "file_read → file_write"

    def test_plan_is_zero_side_effect_and_serialisable(self, tmp_path):
        from neurova.evolution.skill_consolidator import plan_from_service

        svc = self._service(tmp_path)
        self._seed(svc, "skill_aaaa", STEP_A, "report")
        self._seed(svc, "synth_bbbb", STEP_A, "report")
        before = sorted(s["id"] for s in svc.list_skills())
        plans = plan_from_service(svc)
        assert sorted(s["id"] for s in svc.list_skills()) == before, "计划段零副作用"
        d = plans[0].to_dict()
        assert d["basis"] == "identity" and d["structure"] and d["intents"]

    def test_plan_never_merges_across_sequences(self, tmp_path):
        from neurova.evolution.skill_consolidator import plan_from_service

        svc = self._service(tmp_path)
        self._seed(svc, "skill_aaaa", STEP_A, "report")
        self._seed(svc, "synth_bbbb", STEP_A, "report")
        self._seed(svc, "http_helper", STEP_B, "抓取")
        self._seed(svc, "http_other", STEP_B, "抓取")
        plans = plan_from_service(svc)
        groupings = {frozenset(p.absorbed + [p.umbrella]) for p in plans}
        assert frozenset({"skill_aaaa", "synth_bbbb"}) in groupings
        assert frozenset({"http_helper", "http_other"}) in groupings
        assert len(groupings) == 2, "两族各一簇，不得跨族合并"


# ══════════════════════════════════════════════════════════════
# P1-2：合并审批面 agent 归属校验
# ══════════════════════════════════════════════════════════════

BASE = "/api/v1/skill-pool"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离库目录到 tmp，并把 victim agent 的属主登记为别人。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import skill_pool_api
    from neurova.skills.skill_service import SkillService

    real = SkillService

    class _Tmp(real):
        def __init__(self, agent_id, skills_dir=None):
            super().__init__(agent_id=agent_id, skills_dir=str(tmp_path / f"agent-{agent_id}"))

    monkeypatch.setattr(skill_pool_api, "_pool_service", lambda agent_id: _Tmp(agent_id=agent_id))

    class _CM:
        def get_agent(self, aid):
            return {"owner_user_id": "victim_owner"} if aid == "victim" else None

    import neurova.api.endpoints.agent as agent_mod

    monkeypatch.setattr(agent_mod, "get_agent_config_manager", lambda: _CM())
    monkeypatch.setattr(agent_mod, "get_agent_from_state", lambda aid: None)

    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix=BASE)
    client = TestClient(app, raise_server_exceptions=False)
    return client, _Tmp, tmp_path


def _as(client, user_id, role="user"):
    from neurova.api.deps import get_current_user

    client.app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user_id, "username": user_id, "role": role}
    return client


def _seed_plan(svc):
    from neurova.evolution.skill_consolidator import ConsolidationPlanStore

    ConsolidationPlanStore(svc.skills_dir).upsert(
        [{"umbrella": "u1", "absorbed": ["a", "b"]}])


class TestConsolidationOwnership:
    def test_non_owner_cannot_read_plans(self, env):
        """他 agent 的合并计划含技能清单与用量——读面不放宽。"""
        client, Svc, _ = env
        _seed_plan(Svc(agent_id="victim"))
        _as(client, "attacker")
        assert client.get(f"{BASE}/agent/victim/consolidation/plans").status_code == 403

    def test_non_owner_cannot_approve(self, env):
        """**旧实现的真漏**：approve 是写操作（归档技能），却只按路径取库。

        旧实现下本用例返回 200 且 victim 的技能被归档——任何登录用户知道
        agent_id 就能批别人的合并。
        """
        client, Svc, _ = env
        _seed_plan(Svc(agent_id="victim"))
        _as(client, "attacker")
        r = client.post(f"{BASE}/agent/victim/consolidation/u1/approve")
        assert r.status_code == 403, f"非属主批准必须被拒，实际 {r.status_code}"

    def test_non_owner_cannot_reject(self, env):
        client, Svc, _ = env
        _seed_plan(Svc(agent_id="victim"))
        _as(client, "attacker")
        assert client.post(f"{BASE}/agent/victim/consolidation/u1/reject").status_code == 403

    def test_owner_can_read_and_approve(self, env):
        """属主本人不受影响（校验不能把正常路径也堵了）。"""
        client, Svc, _ = env
        _seed_plan(Svc(agent_id="victim"))
        _as(client, "victim_owner")
        assert client.get(f"{BASE}/agent/victim/consolidation/plans").status_code == 200
        assert client.post(f"{BASE}/agent/victim/consolidation/u1/approve").status_code == 200

    def test_admin_can_operate_any_agent(self, env):
        """admin 全量（既有口径）：无主/他人 agent 都可管。"""
        client, Svc, _ = env
        _seed_plan(Svc(agent_id="victim"))
        _as(client, "root", role="admin")
        assert client.get(f"{BASE}/agent/victim/consolidation/plans").status_code == 200

    def test_ownership_checked_before_plan_lookup(self, env):
        """越权请求不得因"计划不存在"而返回 404——否则 404/403 可被用来探测。

        先鉴权后取件：非属主对**不存在**的 umbrella 也必须 403（不泄露
        "该 agent 有无这个计划"）。
        """
        client, Svc, _ = env
        Svc(agent_id="victim")  # 不 seed：计划仓为空
        _as(client, "attacker")
        assert client.post(f"{BASE}/agent/victim/consolidation/ghost/approve").status_code == 403

    def test_plan_failure_returns_empty_not_500(self, env, monkeypatch):
        """审批面故障仍降级为空列（既有契约保持）。"""
        client, Svc, _ = env
        _as(client, "victim_owner")

        import neurova.evolution.skill_consolidator as sc

        class _Boom:
            def __init__(self, *_a, **_k):
                raise RuntimeError("disk down")

        monkeypatch.setattr(sc, "ConsolidationPlanStore", _Boom)
        assert client.get(f"{BASE}/agent/victim/consolidation/plans").status_code == 200


# ══════════════════════════════════════════════════════════════
# P2：死代码真删（不是标注保留）
# ══════════════════════════════════════════════════════════════

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


class TestDeadCodeReallyRemoved:
    def test_legacy_skill_packer_module_deleted(self):
        """旧 SkillPacker 模块必须**不存在**（不是"标注保留待清理"）。"""
        assert not os.path.exists(os.path.join(_REPO, "neurova", "skill", "skill_packer.py"))

    def test_legacy_skill_packer_not_importable(self):
        with pytest.raises(ModuleNotFoundError):
            import importlib

            importlib.import_module("neurova.skill.skill_packer")

    def test_legacy_skill_packer_tests_deleted(self):
        """专用测试随模块删除——留着测一个已不存在的模块才是真死代码。"""
        assert not os.path.exists(os.path.join(_REPO, "tests", "skill", "test_skill_packer.py"))
        assert not os.path.exists(os.path.join(_REPO, "tests", "skill", "conftest.py"))

    def test_dead_pipeline_facade_deleted(self):
        """零生产调用的旧四步门面与四个 Step 类必须真删。

        保留的代价不是"多几行"——是让后来者把它当新增接线的模板，而那条
        通道**不经过证据闸**（`creation_governance` 的 ContextVar 采集器才是）。
        """
        import neurova.agent.tool_pipeline as tp

        for symbol in ("create_default_pipeline", "MemoryRecordingStep",
                       "LifecycleUpdateStep", "SkillObservationStep",
                       "EvolutionFeedbackStep"):
            assert not hasattr(tp, symbol), f"{symbol} 已确认死代码，应删除"

    def test_live_observer_gateway_is_intact(self):
        """删的是死的那半，活的那半（result 观察者门面）必须还在。

        生产消费方：`security/tool_circuit_breaker.py` 经它挂熔断观察者、
        `ToolExecutor.on_tool_executed` 经它发通知。

        **口径迁移（T-09 死码处置批，Issue #174 / #310）**：本条原先点名六个符号
        都「是活接线」——那是 **T-01 建判据之前**的目测口径。T-01 的机器取数
        证明 `ToolExecutionPipeline` 生产侧**零引用**，T-09 据此裁定五段框架
        （`ToolExecutionPipeline` / `PipelineConfig` / `PipelineGuardAdapter` /
        `ToolExecutionStep` / `PipelineReject` / `ToolExecutionContext` 兼容子类）
        整体退场。故「活接线」的名单收窄为**真有生产消费方**的四条；
        原六个符号的逐条论证见 `scripts/ci/toolLoopDeadlines.txt` 与
        `tests/unit/tools/test_t09_pipeline_face_ruling.py`。
        """
        import neurova.agent.tool_pipeline as tp

        for symbol in ("ToolExecutionReport", "get_pipeline_observers",
                       "notify_tool_result", "PipelineObserversRegistry"):
            assert hasattr(tp, symbol), f"{symbol} 是活接线，不得误删"

    def test_pipeline_frame_is_gone_not_merely_deprecated(self):
        """五段框架（含 `PipelineConfig` 的开关）必须**整段消失**，不是标注保留。

        本条是原 `test_unread_pipeline_config_flags_deleted` 的等价强化：那条问
        「6 个没被读的开关删了没」，收窄了讨论面（好像类本身该留）。T-09 的裁定是
        **类本身也没有生产消费方**——四条注册入口（`add_pre_step` / `add_guard` /
        `add_execute_wrapper` / `add_post_step`）全仓零调用。故判据升到「整段没了」。
        """
        import neurova.agent.tool_pipeline as tp

        for symbol in ("PipelineConfig", "ToolExecutionPipeline",
                       "PipelineGuardAdapter", "ToolExecutionStep", "PipelineReject"):
            assert not hasattr(tp, symbol), (
                f"{symbol} 是五段框架的一部分，四条注册入口生产侧零调用——"
                f"应随 T-09 整段退场，而不是标注保留"
            )

    def test_review_gate_docstring_no_longer_claims_dead_arm(self):
        """评审闸的覆盖面说明不得再提已删的 SkillPacker 臂（否则文档撒谎）。"""
        import io

        with io.open(os.path.join(_REPO, "neurova", "evolution", "skill_review_gate.py"),
                     encoding="utf-8") as f:
            src = f.read()
        assert "- SkillPacker 打包技能" not in src, "已删的臂不该还挂在覆盖面清单里"

    def test_audit_regressions_still_green(self):
        """死代码删除不得打断审计回归套件（CI 受保护子集成员）。"""
        from neurova.skills.creation_governance import canonical_skill_id

        assert canonical_skill_id(STEP_A, "report").startswith("skill_")
