"""RSI 递归自进化 skill 闭环收口（Issue #46）——P0 门控 + P1 统一指纹回归。

修的三件事（每条先红后绿的锚点都写清"旧实现为什么会漏"）：

P0-1 「比上一版本优秀」门控缺失
    `update_auto_skill` 原文对 config/正文/版本号**零内容校验**：正文写空串
    照样落盘成功、版本由提案方自增、落盘不重走评审闸（先批准一次 → 之后
    任意改写全程无门）。

P0-2 「零增益放行」
    `LLMJudge` 在 LLM 不可用时前后都返回中性 0.5，而 `min_improvement`
    默认 0.0 + 判据 `after <= before + min + eps` 在浮点相等时为假
    → 判分完全没跑起来，变体照样通过。

P1-1 重复封装漏洞（同一工具序列写成两条技能）
    `fingerprint` 只在"所有步骤 params 为空"时吸收 purpose，于是同一业务
    意图的两种真实形态（带参步 / 裸工具名）产出两个身份。

P1-2 重复技能合并能力未接线
    `SkillConsolidator` 生产零引用、umbrella 按"描述最长"选、
    输出 plan-only 无审批面。
"""

import os

import pytest

from tests.unit.skills.creation_helpers import register_proven_skill

STEPS = [{"tool": "file_read", "params": {"path": "report.txt"}},
         {"tool": "file_write", "params": {"path": "out.txt"}}]


def _service(tmp_path, gate="1"):
    from neurova.skills.skill_service import SkillService

    os.environ["NEUROVA_SKILL_REVIEW_GATE"] = gate
    return SkillService(agent_id="gate-t", skills_dir=str(tmp_path / "skills"))


# ══════════════════════════════════════════════════════════════
# P0-1：update_auto_skill 的「优秀门控」
# ══════════════════════════════════════════════════════════════


class TestUpdateQualityGate:
    def test_empty_body_rewrite_is_rejected(self, tmp_path):
        """正文写成空串必须被拒（旧实现：照样落盘成功=True）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk1", name="sk1", description="报告处理")
        svc.update_auto_skill("sk1", config={"tool_sequence": STEPS, "context_template": "有内容"})
        ok = svc.update_auto_skill(
            "sk1", config={"tool_sequence": [], "context_template": ""}, description="",
            enforce_quality=True,
        )
        assert ok is False, "清空式改写不得落盘"
        assert svc.get_skill_info("sk1")["manifest"]["config"]["context_template"] == "有内容"

    def test_version_must_not_go_backwards(self, tmp_path):
        """版本只升不降：提案方不能把旧版当新版写回。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk2", name="sk2", description="报告处理")
        assert svc.update_auto_skill("sk2", version="2.0.0", enforce_quality=True) is True
        assert svc.update_auto_skill("sk2", version="1.0.0", enforce_quality=True) is False
        assert svc.update_auto_skill("sk2", version="2.0.0", enforce_quality=True) is False, "重复版本不算升级"
        assert svc.get_skill_info("sk2")["version"] == "2.0.0"

    def test_unparsable_version_rejected(self, tmp_path):
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk3", name="sk3", description="报告处理")
        assert svc.update_auto_skill("sk3", version="next", enforce_quality=True) is False

    def test_new_description_must_pass_routing_sanity(self, tmp_path):
        """新增/改写描述要过路由自检（名述脱钩 = 死技能）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk4", name="pdf-converter", description="把扫描文档转成 PDF")
        assert svc.update_auto_skill(
            "sk4", name="pdf-converter", description="播放无损音乐合集", enforce_quality=True
        ) is False, "名述脱钩的描述不得落盘"
        assert svc.get_skill_info("sk4")["description"] == "把扫描文档转成 PDF"

    def test_rewrite_reenters_review_gate(self, tmp_path):
        """改写落盘重走评审闸：批准一次 ≠ 永久免疫。"""
        svc = _service(tmp_path)
        # 名述自洽的描述才能过路由自检（否则连"改写"都进不了门）
        register_proven_skill(svc, "report-helper", name="report-helper",
                              description="report-helper 整理报告并产出摘要")
        assert svc.enable_skill("report-helper")["success"]
        assert svc.get_skill_info("report-helper")["enabled"] is True
        assert svc.update_auto_skill(
            "report-helper", version="1.0.1",
            config={"tool_sequence": STEPS, "context_template": "改进后的正文"},
            description="report-helper 整理报告并产出摘要 已改进", enforce_quality=True,
        ) is True
        assert svc.get_skill_info("report-helper")["enabled"] is False, "改写后必须回到待审"

    def test_maintenance_channel_still_can_write_back_old_version(self, tmp_path):
        """回滚/重建等维护通道显式豁免：版本回退仍可落盘。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk6", name="sk6", description="报告处理")
        assert svc.update_auto_skill("sk6", version="2.0.0", enforce_quality=True) is True
        from neurova.skills.skill_service import SkillService

        assert SkillService.apply_maintenance_update(
            svc, "sk6", version="1.0.0", config={"tool_sequence": STEPS}) is True
        assert svc.get_skill_info("sk6")["version"] == "1.0.0"


# ══════════════════════════════════════════════════════════════
# P0-2：「零增益放行」与判分不可用
# ══════════════════════════════════════════════════════════════


class TestZeroGainPassThrough:
    def test_min_improvement_default_is_positive(self):
        from neurova.evolution.eval.config import EvolutionConfig

        assert EvolutionConfig().min_improvement > 0.0, "默认 0.0 会让零增益在浮点相等时放行"

    @pytest.mark.asyncio
    async def test_judge_unavailable_rejects_instead_of_neutral_pass(self):
        """判分完全跑不起来 → 拒绝（judge_unavailable），不拿 0.5 当分。"""
        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.dataset import EvalDataset, EvalExample
        from neurova.evolution.eval.fitness import FitnessScore
        from neurova.evolution.eval.runner import SkillEvolutionRunner

        class _DeadJudge:
            async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
                return FitnessScore(correctness=0.5, procedure_following=0.5, conciseness=0.5,
                                    feedback="judge 调用失败", judge_available=False)

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return skill_text

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nCHANGED"

        ds = EvalDataset(
            train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(4)],
            val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
            holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        )
        runner = SkillEvolutionRunner(
            EvolutionConfig(iterations=1), judge=_DeadJudge(), mutate=mutate, agent=_Agent(),
        )
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=ds)
        assert result.rejected
        assert result.reject_reason == "judge_unavailable"
        assert result.judge_available is False

    @pytest.mark.asyncio
    async def test_llm_judge_marks_failure_as_unavailable(self):
        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.fitness import LLMJudge

        async def dead_call(messages, model):
            return {"success": False, "error": "rate limited"}

        judge = LLMJudge(EvolutionConfig(), llm_call=dead_call)
        score = await judge.score(task_input="t", expected_behavior="e", output="o", skill_text="s")
        assert score.judge_available is False, "判分失败必须可区分于真实中等水平"
        assert score.correctness == pytest.approx(0.5), "退回中性分不改（只加可用性标注）"


class TestBenchGateHonesty:
    def test_gate_without_apply_fn_is_explicitly_neutral(self):
        from neurova.evolution.eval.bench_gate import make_eval_harness_gate

        gate = make_eval_harness_gate(live_params_provider=lambda: {})
        assert gate("a", "b") == 0.0
        assert getattr(gate, "neutral", False) is True, "纯文本候选必须显式标注中性（不许假装测过）"
        assert getattr(gate, "neutral_reason", "") == "no_apply_fn"

    def test_gate_with_apply_fn_is_not_neutral(self):
        from neurova.evolution.eval.bench_gate import make_eval_harness_gate

        gate = make_eval_harness_gate(live_params_provider=lambda: {}, apply_fn=lambda text: (lambda: None))
        gate("a", "b")
        assert getattr(gate, "neutral", True) is False


# ══════════════════════════════════════════════════════════════
# P1-1：统一指纹（结构 / 业务双身份）
# ══════════════════════════════════════════════════════════════


class TestUnifiedIdentity:
    def test_purpose_is_always_part_of_business_identity(self):
        from neurova.skills.creation_governance import fingerprint

        # 带参步也要吸收 purpose（旧实现只在"全无参数"时才吸收）
        assert fingerprint(STEPS, "pdf 转换") != fingerprint(STEPS, "发票汇总")
        # 归一化：大小写/空白折叠后同身份
        assert fingerprint(STEPS, " Report ") == fingerprint(STEPS, "report")

    def test_structure_identity_ignores_purpose(self):
        from neurova.skills.creation_governance import structure_key

        assert structure_key(STEPS) == structure_key(STEPS), "结构身份与意图无关"

    def test_same_sequence_cannot_be_encapsulated_twice(self, tmp_path):
        """同一工具序列换 ID / 换名字 → 收敛到既有条目，不新写第二条。"""
        svc = _service(tmp_path)
        for i in range(3):
            svc.creation_evidence.record(f"task-{i}", STEPS, "report", True)
        first = svc.create_automatic_skill("skill_a", "skill_a", "报告处理", {"tool_sequence": STEPS})
        assert first["success"] and first["skill_id"] == "skill_a"
        second = svc.create_automatic_skill("genetic_file_read", "genetic_rename",
                                            "完全不同的名字", {"tool_sequence": STEPS})
        assert second.get("duplicate") is True
        assert second["skill_id"] == "skill_a"
        assert len(svc.list_skills()) == 1, "同一工具序列只能有一条技能"
        # 别名收敛：两个命名方案都解析到同一条
        assert svc.get_skill_info("genetic_file_read")["id"] == "skill_a"

    def test_canonical_skill_id_is_deterministic(self):
        from neurova.skills.creation_governance import canonical_skill_id

        assert canonical_skill_id(STEPS, "report") == canonical_skill_id(STEPS, "report")
        assert canonical_skill_id(STEPS, "report") != canonical_skill_id(STEPS, "invoice")
        assert canonical_skill_id(STEPS, "report").startswith("skill_")

    def test_alias_table_never_leaks_into_skill_listings(self, tmp_path):
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk7", name="sk7", description="报告处理")
        svc.register_skill_alias("sk7", "legacy-name")
        ids = [s["id"] for s in svc.list_skills()]
        assert ids == ["sk7"]
        assert all(not str(i).startswith("_") for i in ids), "别名索引不得混进技能列表"

    def test_evidence_counts_across_business_identities(self, tmp_path):
        """同一结构不同意图的证据都计入该序列的成功数（旧实现恒查不回）。"""
        svc = _service(tmp_path)
        for i in range(3):
            svc.creation_evidence.record(f"t-{i}", STEPS, "report", True)
        assert svc.creation_evidence.eligible(STEPS), "结构口径必须能查到证据"


# ══════════════════════════════════════════════════════════════
# P1-2：合并迭代接线
# ══════════════════════════════════════════════════════════════


class TestConsolidationWiring:
    def test_rsi_step_produces_plans_without_touching_library(self, tmp_path):
        from neurova.evolution.skill_consolidator import ConsolidationPlanStore, plan_from_service

        svc = _service(tmp_path)
        for idx in range(3):
            sid = f"report-helper-{idx}"
            register_proven_skill(svc, sid, name=sid, description=f"报告处理 {idx}",
                                  config={"tool_sequence": [{"tool": "read", "params": {"i": idx}}]})
        plans = plan_from_service(svc)
        assert plans, "前缀簇应产出合并计划"
        store = ConsolidationPlanStore(svc.skills_dir)
        store.upsert([p.to_dict() for p in plans])
        assert store.load()[0]["status"] == "pending"
        assert len(svc.list_skills()) == 3, "计划段零副作用：技能库不动"

    def test_approve_archives_absorbed_and_keeps_umbrella(self, tmp_path):
        from neurova.evolution.skill_consolidator import (
            ConsolidationApproval,
            ConsolidationPlanStore,
            plan_from_service,
        )

        svc = _service(tmp_path)
        for idx in range(3):
            sid = f"report-helper-{idx}"
            register_proven_skill(svc, sid, name=sid, description=f"报告处理 {idx}",
                                  config={"tool_sequence": [{"tool": "read", "params": {"i": idx}}]})
        plans = plan_from_service(svc)
        store = ConsolidationPlanStore(svc.skills_dir)
        store.upsert([p.to_dict() for p in plans])
        result = ConsolidationApproval(svc, store).approve(plans[0].umbrella, plans[0].absorbed)
        assert result["failed"] == []
        for absorbed in result["archived"]:
            assert svc.get_skill_info(absorbed)["usage"].get("state") == "archived"
        assert svc.get_skill_info(plans[0].umbrella)["usage"].get("state") != "archived", "umbrella 必须留下"
        assert store.load()[0]["status"] == "approved"

    def test_consolidation_endpoints_registered(self):
        """审批面端点必须在路由上（plan-only 模块此前无任何执行通道）。"""
        from neurova.api.endpoints import skill_pool_api

        paths = {r.path for r in skill_pool_api.router.routes}
        assert "/agent/{agent_id}/consolidation/plans" in paths
        assert "/agent/{agent_id}/consolidation/{umbrella}/approve" in paths
        assert "/agent/{agent_id}/consolidation/{umbrella}/reject" in paths
