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
        """**提案方（提交了版本）**改写描述要过路由自检（名述脱钩 = 死技能）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk4", name="pdf-converter", description="把扫描文档转成 PDF")
        assert svc.update_auto_skill(
            "sk4", version="1.0.1",
            name="pdf-converter", description="播放无损音乐合集", enforce_quality=True
        ) is False, "名述脱钩的描述不得落盘"
        assert svc.get_skill_info("sk4")["description"] == "把扫描文档转成 PDF"

    def test_editor_chain_description_is_not_routing_gated(self, tmp_path):
        """**编辑链**（PUT/share/开关，version=None）改描述不咬路由自检。

        历史误杀（本用例是回归锚点）：`PUT /private/{id}` 改个名字描述、`share`
        打个标记，全走 update_auto_skill(version=None)。旧实现拿提案门槛
        （名述自洽）去咬它们，用户自述文本与技能名天然无 token 交集 →
        接口 500，落盘失败。编辑链不声称"更优"，无"更优"可核。
        """
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk4b", name="pdf-converter", description="把扫描文档转成 PDF")
        assert svc.update_auto_skill(
            "sk4b", name="pdf-converter", description="播放无损音乐合集", enforce_quality=True
        ) is True, "编辑链的描述是用户备注，不是提案名述，不咬路由自检"
        assert svc.get_skill_info("sk4b")["description"] == "播放无损音乐合集"

    def test_editor_chain_on_bare_description_entry_is_not_blocked(self, tmp_path):
        """编辑链在**存量空描述**条目上改配置/开关不得被 content_non_empty 拦。

        历史误杀：`POST /private`、`POST /me/skills` 创建条目时 description
        默认空串（前端大多数调用不传）。旧实现把"生效描述为空"判成清空式
        改写 → `PUT` 改 enabled、`share` 打标记恒 500。
        """
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk4c", name="", description="")
        assert svc.update_auto_skill(
            "sk4c", config={"tool_sequence": STEPS, "category": "工具"}, enforce_quality=True
        ) is True, "存量空描述是编辑链一等公民，字段编辑不得被门拦"
        assert svc.update_auto_skill("sk4c", config={"tool_sequence": STEPS, "shared": True},
                                     enforce_quality=True) is True

    # ── 本轮补：门必须看到**旧值**（快照时序） ──────────────────

    def test_gate_sees_pre_mutation_snapshot(self, tmp_path):
        """门拿到的必须是**改动前**的条目，否则所有"本次提交了什么"的判据全瞎。

        这是本轮的根因锚点：`update_auto_skill` 原先在把 name/description/
        version/config 写进 entry **之后**才取 `_prev` 快照，再把它当"旧条目"
        传给门。于是门里的 `_submitted_change(entry, ...)` 比较的是
        "改完的自己 vs 改完的自己"——恒 False。后果：同版本字段编辑被判成
        空更新（version_not_ascending），`_naming_submitted_changed` 恒 False
        又让名述自检恒不咬合。快照必须在赋值之前取。
        """
        svc = _service(tmp_path)
        register_proven_skill(svc, "snap1", name="snap1", description="snap1 处理报告")
        # 同版本 + 有字段变化 = 原地改进（放行）；若门看到的是"改后的自己"，
        # _submitted_change 恒 False → 会被 version_not_ascending 误杀。
        assert svc.update_auto_skill(
            "snap1", version="1.0.0", description="snap1 处理报告并产出摘要", enforce_quality=True
        ) is True, "门必须看到旧值才能认出'本次确有变化'，否则原地改进被误杀"

    def test_rejected_update_leaves_entry_untouched(self, tmp_path):
        """被拒时条目必须原样（旧实现：门在赋值之后跑，被拒也已被写脏）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "snap2", name="snap2", description="snap2 处理报告")
        assert svc.update_auto_skill(
            "snap2", version="3.0.0", description="snap2 处理报告并产出摘要", enforce_quality=True
        ) is True
        # 降级被拒：version/description 都不得改动
        assert svc.update_auto_skill(
            "snap2", version="1.0.0", description="被拒的描述", enforce_quality=True
        ) is False
        after = svc.get_skill_info("snap2")
        assert after["version"] == "3.0.0", "被拒的版本不得落盘"
        assert after["description"] == "snap2 处理报告并产出摘要", "被拒的描述不得落盘"

    def test_editor_chain_cannot_blank_the_body(self, tmp_path):
        """编辑链也**不得把描述清空**（避免"清空式改写"从编辑链绕过）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk4d", name="sk4d", description="有描述")
        assert svc.update_auto_skill("sk4d", description="", enforce_quality=True) is False
        assert svc.get_skill_info("sk4d")["description"] == "有描述"

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


class TestInPlaceUpgradeJudgement:
    """P0 门控判据修正（2026-09-17 二审）：同版本原地升级不得被误杀。

    旧判据 `order <= current` 把「同版本」一律判 version_not_ascending。
    真路径里"同版本 + 内容确有变化"是**正常语义**：
    - `library_service.apply_transfer` 同源再流转 eff_version 就是源版本；
    - `skill_experience` 经验重建写回原版本号。
    而这些路径此前**根本没经门**（门默认关），所以这个语义冲突在旧代码里
    被"门不存在"掩盖着——门一开就被审计逮到（test_library_wave_h1 实测红）。
    """

    def test_same_version_with_content_change_is_allowed(self, tmp_path):
        """同版本 + 工具序列确有变化 → 放行（原地升级的真实形态）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk7", name="sk7", description="报告处理")
        assert svc.update_auto_skill(
            "sk7", version="1.0.0", config={"tool_sequence": STEPS}, enforce_quality=True
        ) is True, "同版本原地改进不得被 version_not_ascending 误杀"

    def test_same_version_without_change_is_rejected(self, tmp_path):
        """同版本 + 内容零变化 = 空更新（重放噪声）→ 仍拦下。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk8", name="sk8", description="报告处理")
        assert svc.update_auto_skill("sk8", version="1.0.0", enforce_quality=True) is False

    def test_version_regression_still_rejected(self, tmp_path):
        """显式降级仍拒（真回滚走 apply_maintenance_update 豁免）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk9", name="sk9", description="报告处理")
        assert svc.update_auto_skill("sk9", version="3.0.0", enforce_quality=True) is True
        assert svc.update_auto_skill("sk9", version="2.0.0", enforce_quality=True) is False

    def test_renaming_without_quality_name_is_gated(self, tmp_path):
        """**提案方改写名述**（带版本）仍咬路由自检（门只放过"重复提交同一名述"）。"""
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk10", name="pdf-converter", description="把扫描文档转成 PDF")
        assert svc.update_auto_skill(
            "sk10", version="1.0.1",
            name="pdf-converter", description="播放无损音乐合集", enforce_quality=True
        ) is False

    def test_same_name_and_description_resubmit_is_not_gated(self, tmp_path):
        """名述与旧值逐字相同（库内流转把源侧现值回填）→ 不咬路由自检。

        旧实现对任何非空 description 都跑 routing_sanity，把
        `apply_transfer` 这类"原样回填源名述"的正常搬运判成名述脱钩而拒绝。
        """
        svc = _service(tmp_path)
        register_proven_skill(svc, "sk11", name="s", description="d")
        assert svc.update_auto_skill(
            "sk11", version="1.0.0", config={"tool_sequence": STEPS},
            name="s", description="d", enforce_quality=True,
        ) is True, "重复提交同一名述不是名述提案，不该被路由自检咬"

    def test_gate_defaults_on(self, tmp_path):
        """门默认开：不设环境变量时未显式传参的写入也要过门。

        旧默认关 = 门形同不存在（"批准一次 → 任意改写"的旧洞原样保留），
        这是本门存在的意义所在。
        """
        import os

        from neurova.skills.skill_service import SkillService

        prev = os.environ.pop("NEUROVA_SKILL_UPDATE_GATE", None)
        try:
            assert SkillService._update_gate_enabled() is True
            svc = SkillService(agent_id="gate-default", skills_dir=str(tmp_path / "s"))
            register_proven_skill(svc, "sk12", name="sk12", description="报告处理")
            assert svc.update_auto_skill("sk12", version="2.0.0") is True
            assert svc.update_auto_skill("sk12", version="1.0.0") is False, "默认态必须真的在咬"
        finally:
            if prev is not None:
                os.environ["NEUROVA_SKILL_UPDATE_GATE"] = prev


class TestTransferPathCoexistence:
    """库内同源流转与 P0 门控共存（门默认开后不得把真路径打红）。"""

    def test_same_source_transfer_upgrades_in_place(self, tmp_path, monkeypatch):
        from neurova.skills import library_service as lib

        monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
        lib.reset_libraries_for_tests()
        agent = lib.get_library("agent", "a1")
        user = lib.get_library("user", "u:7")
        register_proven_skill(agent, "s1", name="S", description="d", version="1.0.0")
        cfg = agent.get_skill_info("s1")["manifest"]["config"]
        for i in range(3):
            user.creation_evidence.record(str(i), cfg["tool_sequence"], "d", True)
        assert lib.apply_transfer("user", "u:7", "agent", "a1", "s1")["action"] == "created"
        agent.update_auto_skill("s1", version="2.0.0")
        r = lib.apply_transfer("user", "u:7", "agent", "a1", "s1")
        assert r["ok"] and r["action"] == "upgraded", r
        assert user.get_skill_info("s1")["version"] == "2.0.0"

    def test_repeat_transfer_same_version_is_noop_not_rejected(self, tmp_path, monkeypatch):
        """无新内容可搬 → 幂等 noop（不再提交一次注定被门拒的空更新）。"""
        from neurova.skills import library_service as lib

        monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
        lib.reset_libraries_for_tests()
        agent = lib.get_library("agent", "a2")
        user = lib.get_library("user", "u:8")
        register_proven_skill(agent, "s2", name="S2", description="d2", version="1.0.0")
        cfg = agent.get_skill_info("s2")["manifest"]["config"]
        for i in range(3):
            user.creation_evidence.record(str(i), cfg["tool_sequence"], "d2", True)
        assert lib.apply_transfer("user", "u:8", "agent", "a2", "s2")["action"] == "created"
        r = lib.apply_transfer("user", "u:8", "agent", "a2", "s2")
        assert r["ok"] is True, r
        assert r.get("noop") is True


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
        """**真有读数**的一轮必须不再自报中性（本用例的判据对象已修正）。

        原断言写作"提供了 apply_fn ⇒ neutral 为 False"。Issue #46 收口复核
        实测证伪：`live_params_provider` 返回空参数时 harness 自报
        `measurement_blind`（score=None），门按中性返回 0.0——此种情形下
        `neutral=False` 是**假咬合**，与"真咬合且零增益"对外一模一样，恰好
        抹掉 `neutral_reason` 存在的意义。故判据对象由"调用方提供了什么"
        改为"这一轮的结果是不是中性放行"，并补齐两个方向。
        """
        from neurova.evolution.eval.bench_gate import (
            NEUTRAL_REASON_MEASUREMENT_BLIND,
            make_eval_harness_gate,
        )

        def engaged_provider():
            return {"tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                                    "decay_rate": 0.1, "muscle_memory_threshold": 0.6}}

        gate = make_eval_harness_gate(live_params_provider=engaged_provider,
                                      apply_fn=lambda text: (lambda: None))
        gate("a", "b")
        assert getattr(gate, "neutral", True) is False, "有读数的一轮不得自称中性"

        # 反向：同一门在"取不到读数"的一轮必须如实自报中性，且理由可审计。
        blind = make_eval_harness_gate(live_params_provider=lambda: {},
                                       apply_fn=lambda text: (lambda: None))
        blind("a", "b")
        assert getattr(blind, "neutral", False) is True
        assert getattr(blind, "neutral_reason", "") == NEUTRAL_REASON_MEASUREMENT_BLIND


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


# ══════════════════════════════════════════════════════════════
# P0 收口：统一命名**真正**实现（canonical_skill_id 接线）
#
# 旧实现的漏洞不是"没有 canonical_skill_id"，而是"有函数、零调用"：
# 三条写入臂各写各的 ID（skill_<md5> / genetic_<tools> / synth_*），
# 服务端按 ID 判重永不命中，"统一命名"名不副实。
# ══════════════════════════════════════════════════════════════


class _FakeRegistry:
    """最小 SkillRegistry 替身：只关心注册名，不关心执行。"""

    def __init__(self):
        self.registered = {}

    def register_skill(self, skill, _path=None):
        self.registered[skill.name] = skill
        return True

    def set_skill_enabled(self, name, enabled):
        self.enabled = getattr(self, "enabled", {})
        self.enabled[name] = enabled


def _arm_manifest(arm, sequence, purpose, steps=None):
    """构造三条写入臂各自"历史上的"manifest（ID 命名方案各不同）。"""
    from types import SimpleNamespace

    steps = steps or [{"tool": t, "params": {}} for t in sequence]
    if arm == "builder":
        return SimpleNamespace(id="skill_pat_abc123", name="file_read_file_write_skill_abc123",
                               description="自动封装的技能：执行 文件读写",
                               config={"tool_sequence": steps, "context_template": purpose})
    if arm == "genetic":
        sid = "genetic_" + "_".join(sequence)
        return SimpleNamespace(id=sid, name=sid,
                               description="遗传进化工具组合", 
                               config={"tool_sequence": steps, "task_purpose": purpose})
    sid = "synth_deadbeef"
    return SimpleNamespace(id=sid, name="synth_tool", description="NL 合成工具",
                           config={"tool_sequence": steps, "task_purpose": purpose})


class TestUnifiedNamingIsActuallyWired:
    def test_canonical_skill_id_has_production_callers(self):
        """canonical_skill_id 必须有生产调用方（旧实现只有定义 + 测试调用）。

        这是"名不副实"的直接判据：函数存在不等于统一命名存在。
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3] / "neurova"
        hits = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "canonical_skill_id" in text and path.name != "creation_governance.py":
                hits.append(str(path.relative_to(root)))
        assert hits, "canonical_skill_id 仍无生产调用方（统一命名未接线）"

    def test_three_write_arms_land_on_the_same_skill_id(self, tmp_path):
        """三条臂写同一工具序列 → 库里只有一条，且 ID 是规范 ID。"""
        from neurova.skills.creation_governance import canonical_skill_id, publish_automatic

        svc = _service(tmp_path, gate="0")
        sequence = ["file_read", "file_write"]
        steps = [{"tool": t, "params": {"path": t + ".txt"}} for t in sequence]
        for i in range(3):
            svc.creation_evidence.record(f"task-{i}", steps, "报告汇总", True)

        expected = canonical_skill_id(steps, "报告汇总")
        ids = []
        for arm in ("builder", "genetic", "synth"):
            result = publish_automatic(svc, _FakeRegistry(), _arm_manifest(arm, sequence, "报告汇总", steps))
            assert result.get("success"), f"{arm} 臂发布失败: {result}"
            ids.append(svc.resolve_skill_alias(result["skill_id"]))

        assert len(set(ids)) == 1, f"三条臂落到了不同 ID: {ids}"
        assert ids[0] == expected, f"落盘 ID 不是规范 ID: {ids[0]} != {expected}"
        lib = [s["id"] for s in svc.list_skills()]
        assert lib == [expected], f"同一序列只能有一条技能: {lib}"

    def test_original_arm_ids_resolve_to_canonical(self, tmp_path):
        """被归一掉的原 ID 必须登记为别名——否则统一命名制造新的孤儿入口。"""
        from neurova.skills.creation_governance import publish_automatic

        svc = _service(tmp_path, gate="0")
        steps = [{"tool": "file_read", "params": {"path": "a.txt"}}]
        for i in range(3):
            svc.creation_evidence.record(f"t{i}", steps, "报告汇总", True)
        manifest = _arm_manifest("genetic", ["file_read"], "报告汇总", steps)
        result = publish_automatic(svc, _FakeRegistry(), manifest)
        assert result.get("success")
        canonical = svc.resolve_skill_alias(result["skill_id"])
        assert canonical != manifest.id, "遗传臂的旧 ID 应当已被归一"
        assert svc.get_skill_info(manifest.id) is not None, "旧 ID 必须仍可解析到技能"
        assert svc.get_skill_info(manifest.id)["id"] == canonical

    def test_prefix_reflects_arm_without_changing_identity(self, tmp_path):
        """前缀标明来源臂（可读性），但身份仍是同一个 fingerprint。"""
        from neurova.skills.creation_governance import canonical_skill_id, publish_automatic

        svc = _service(tmp_path, gate="0")
        steps = [{"tool": "file_read", "params": {"path": "a.txt"}}]
        for i in range(3):
            svc.creation_evidence.record(f"t{i}", steps, "报告汇总", True)
        result = publish_automatic(svc, _FakeRegistry(),
                                   _arm_manifest("genetic", ["file_read"], "报告汇总", steps))
        expected = canonical_skill_id(steps, "报告汇总", prefix="genetic")
        assert svc.resolve_skill_alias(result["skill_id"]) == expected

    def test_no_sequence_keeps_caller_id(self, tmp_path):
        """无工具序列（无身份可推导）不被改名——统一命名只约束身份产物。

        这条用 `canonical_skill_id` 的直接语义断言：无序列 → 空规范 ID，
        归一逻辑必须原样放行调用方 ID，而不是造一个 `skill_<空指纹>`。
        """
        from neurova.skills.creation_governance import canonical_skill_id

        assert canonical_skill_id([], "手工技能") == ""
        assert canonical_skill_id(None, "") == ""

    def test_manifest_helpers_accept_object_manifests(self):
        """三条臂传的是对象 manifest（SimpleNamespace/Skill），不是 dict。

        旧实现 manifest_purpose/manifest_fingerprint 只按 dict 取值，
        用对象 manifest 调 publish_automatic 会 AttributeError——"统一命名"
        接上去的第一步就会崩，所以这条是接线的必要条件。
        """
        from types import SimpleNamespace

        from neurova.skills.creation_governance import manifest_fingerprint, manifest_purpose

        obj = SimpleNamespace(id="genetic_x", name="genetic_x", description="d",
                              config={"tool_sequence": STEPS, "task_purpose": "报告汇总"})
        assert manifest_purpose(obj) == "报告汇总"
        assert manifest_fingerprint(obj) is not None
        assert manifest_fingerprint(obj) == manifest_fingerprint(
            {"id": "genetic_x", "description": "d",
             "config": {"tool_sequence": STEPS, "task_purpose": "报告汇总"}})

    def test_builder_template_id_is_canonical(self, tmp_path):
        """AutoSkillBuilder 的内存模板 ID 必须是规范 ID。

        旧实现模板自造 `skill_<pattern_id>`，而落盘已归一到规范 ID，
        重启后按落盘 ID 恢复的 pending 模板与内存模板对不上（批准断链）。
        """
        import os as _os

        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.creation_governance import canonical_skill_id

        _os.environ["NEUROVA_SKILL_REVIEW_GATE"] = "1"
        svc = _service(tmp_path, gate="1")
        builder = AutoSkillBuilder(evidence_store=svc.creation_evidence)
        steps = [{"tool": "file_read", "params": {"path": "a.txt"}},
                 {"tool": "file_write", "params": {"path": "b.txt"}}]
        for i in range(3):
            svc.creation_evidence.record(f"b-{i}", steps, "报告汇总", True)
            builder.observe(steps, context="报告汇总", metadata={"source_key": f"b-{i}"},
                            success=True)
        templates = builder.get_all_templates()
        assert templates, "三次独立成功应封装出模板"
        template = templates[0]
        expected = canonical_skill_id(steps, "报告汇总")
        assert template.template_id == expected, (
            f"模板 ID 未归一: {template.template_id} != {expected}")

    def test_pending_branch_does_not_bypass_canonical_naming(self, tmp_path):
        """待审分支（is_active=False）不得绕过 ID 归一。

        旧实现在这里直接调 create_automatic_skill(template_id...)，
        于是"待审期"库里是旧 ID、"批准后"库里变规范 ID，同一条技能两个 ID。
        """
        import os as _os

        from neurova.evolution.skill_encapsulation import AutoSkillBuilder
        from neurova.skills.creation_governance import canonical_skill_id

        _os.environ["NEUROVA_SKILL_REVIEW_GATE"] = "1"
        svc = _service(tmp_path, gate="1")
        builder = AutoSkillBuilder(evidence_store=svc.creation_evidence)
        steps = [{"tool": "file_read", "params": {"path": "a.txt"}},
                 {"tool": "file_write", "params": {"path": "b.txt"}}]
        for i in range(3):
            svc.creation_evidence.record(f"p-{i}", steps, "报告汇总", True)
            builder.observe(steps, context="报告汇总", metadata={"source_key": f"p-{i}"},
                            success=True)
        from neurova.skill_system import SkillRegistry

        builder.register_to_skill_registry(SkillRegistry(), svc)
        template = builder.get_all_templates()[0]
        assert template.is_active is False, "评审闸开启时产物应先进 pending"
        # 待审条目在库里的 ID 就是规范 ID（不是 template 的旧命名）
        info = svc.get_skill_info(template.template_id)
        assert info is not None, "待审条目必须可查"
        assert info["id"] == canonical_skill_id(steps, "报告汇总")
        assert info["enabled"] is False
