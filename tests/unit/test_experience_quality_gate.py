# -*- coding: utf-8 -*-
"""009 · 真实语料基准 + 一条 CI 门禁（红绿灯 TDD）。

票面要回答的是"变好了"而不是"更严了"：门槛收紧前后，注入进 prompt 的经验
质量各是多少。本守卫钉住基准脚本 `scripts/ci/experience_quality_gate.py` 的
七件事：

1. **只读取证**——冻结语料来自生产库 `data/experience_knowledge.db`，基准脚本
   对它是只读的（写一次生产库就是污染运行数据，纪律 6）；
2. **语料必须是真实语料**——票面点名禁止 `rsi/eval_harness.py:255-265` 那种
   当场合成的 `f"使用 {tool} 成功完成"`，故载入时校验来源并拒绝模板句；
3. **读数算式只有一处**——两个读数一律取自 `EKB.quality_snapshot()`（008），
   基准不得另建 SQL；
4. **A/B 方向可比**——pre（无据即成功票 + 无闸）vs post（现行闸），
   差值方向必须可读出；
5. **反向锁**——拨 004 的旋钮（`ExperienceFeedback.crystallize_min_*` 经
   `attach_crystallizer` 桥推入结晶器）读数必须跟着变，否则是在测算术；
6. **自证不空转**——低质语料（全自述成功、零客观回执、同句反复）必红，
   正常语料全绿，两态都要有可复现的 exit code 证据；门禁脚本自身不进
   `protected_tests.txt`（000-索引 纪律 7）。

接线（双侧同命令、阻塞语义）由 `tests/unit/test_ci_parity_guard.py` 钉住——
它已常驻在 `protected_tests.txt` 里，本文件不重复一份映射表。

期望值来源：语料投影按 `experience_records` 列名逐个点名；判据阈值取自
008 的 `RSIMetrics.ALERT_THRESHOLDS`（复用而非另建）。
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3

import pytest

from tests.repo_paths import repo_path

GATE_PATH = repo_path("scripts", "ci", "experience_quality_gate.py")


def _gate():
    """按门禁脚本文件路径加载模块（脚本不在包内，CI 以文件方式直接执行）。"""
    assert GATE_PATH.is_file(), "scripts/ci/experience_quality_gate.py 缺失——009 基准无从执行"
    spec = importlib.util.spec_from_file_location("experience_quality_gate", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def source_db(tmp_path):
    """一个"生产库替身"：用真实写入路径造出的经验库，含同 context 重复与无据行。

    用 `ExperienceKnowledgeBase` 而不是手搓 SQL：投影要读的列（evidence_state /
    adoption_outcome / content_key）本身就是该类建的，手搓 schema 会让冻结函数
    在一个与生产不同形的库上变绿。
    """
    from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase, ExperienceRecord

    path = tmp_path / "experience_knowledge.db"
    ekb = ExperienceKnowledgeBase(db_path=str(path))
    try:
        # 同句重复 3 次（有票据）——011 之前这会落 3 行，之后合并为 seen_count=3
        for _ in range(3):
            ekb.add_experience_record(
                skill_name="chat",
                exp=ExperienceRecord(
                    skill_name="chat",
                    context={"user_input": "你好"},
                    result={"reply_excerpt": "你好呀"},
                    success=True,
                    timestamp="2026-09-19T10:00:00+00:00",
                ),
                agent_id="default",
                evidence=True,
            )
        # 无客观回执的自述成功（010 口径：evidence=None ⇒ unevidenced）
        ekb.add_experience_record(
            skill_name="unknown,weather",
            exp=ExperienceRecord(
                skill_name="unknown,weather",
                context={"user_input": "今天许昌天气怎么样"},
                result={"reply_excerpt": "晴"},
                success=True,
                timestamp="2026-09-19T11:00:00+00:00",
            ),
            agent_id=None,
            evidence=None,
        )
        # 有票据的失败（002 之后 success 位开始携带信息）
        ekb.add_experience_record(
            skill_name="web_search",
            exp=ExperienceRecord(
                skill_name="web_search",
                context={"user_input": "帮我查查关于deepseek v5的确切消息"},
                result={"reply_excerpt": "没查到"},
                success=False,
                timestamp="2026-09-19T12:00:00+00:00",
            ),
            agent_id="kai",
            evidence=True,
        )
        # 采纳回写（006 的唯一 UPDATE 通路）：成功 1 条、失败 1 条
        ekb.record_injection_adoption([1], True)
        ekb.record_injection_adoption([3], False)
    finally:
        ekb.close()
    return path


class TestReadonlyEvidence:
    """冻结生产库语料必须只读取证——写一次就是污染运行数据。"""

    def test_freeze_uses_a_write_refusing_connection(self, source_db):
        """冻结取证用的连接必须拒绝写入——只读是约束不是注释。"""
        gate = _gate()
        conn = gate.connect_readonly(str(source_db))
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO experience_records (skill_name, success) VALUES ('x', 1)")
        finally:
            conn.close()

    def test_freeze_leaves_source_db_byte_identical(self, source_db):
        gate = _gate()
        before = source_db.read_bytes()
        gate.freeze_corpus(str(source_db))
        assert source_db.read_bytes() == before, "冻结过程写了源库——生产运行数据被污染"


class TestCorpusProjection:
    """投影必须保住基准要读的那几格：票据态、采纳结果、真实重复次数。"""

    # 期望值按 `source_db` 的构造逐条手推（独立真相源），不由被测代码反算。
    EXPECTED_TURNS = [
        {
            "rowId": 1,
            "agentId": "default",
            "skillName": "chat",
            "userInput": "你好",
            "success": True,
            "timestamp": "2026-09-19T10:00:00+00:00",
            "seenCount": 3,
            "evidenceState": "evidenced",
            "adoptionOutcome": "success",
        },
        {
            "rowId": 2,
            "agentId": None,
            "skillName": "unknown,weather",
            "userInput": "今天许昌天气怎么样",
            "success": True,
            "timestamp": "2026-09-19T11:00:00+00:00",
            "seenCount": 1,
            "evidenceState": "unevidenced",
            "adoptionOutcome": None,
        },
        {
            "rowId": 3,
            "agentId": "kai",
            "skillName": "web_search",
            "userInput": "帮我查查关于deepseek v5的确切消息",
            "success": False,
            "timestamp": "2026-09-19T12:00:00+00:00",
            "seenCount": 1,
            "evidenceState": "evidenced",
            "adoptionOutcome": "failure",
        },
    ]

    def test_freeze_projects_the_fields_the_benchmark_reads(self, source_db):
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        assert corpus["turns"] == self.EXPECTED_TURNS

    def test_freeze_drops_reply_text(self, source_db):
        """回复正文既不进内容身份也不进读数，冻结它等于把对话抄进仓库。"""
        gate = _gate()
        blob = json.dumps(gate.freeze_corpus(str(source_db)), ensure_ascii=False)
        for leaked in ("你好呀", "没查到", "reply_excerpt", "晴"):
            assert leaked not in blob, f"冻结语料里还留着回复文本: {leaked}"

    def test_freeze_bounds_user_input_to_the_gate_window(self, tmp_path):
        """单条回合限长到结晶器自己的 200 字窗口。

        窗口之外对闸门不可见（`PatternCrystallizer.observe` 就按 `context[:200]`
        存），却在仓库里留下整篇对话正文——超出窗口的部分是纯负担。
        """
        from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase, ExperienceRecord

        path = tmp_path / "long.db"
        ekb = ExperienceKnowledgeBase(db_path=str(path))
        try:
            ekb.add_experience_record(
                skill_name="chat",
                exp=ExperienceRecord(
                    skill_name="chat",
                    context={"user_input": "开场白" + "长文" * 400},
                    result={"reply_excerpt": "r"},
                    success=True,
                    timestamp="2026-09-19T13:00:00+00:00",
                ),
                evidence=True,
            )
        finally:
            ekb.close()

        gate = _gate()
        turn = gate.freeze_corpus(str(path))["turns"][0]
        assert turn["userInput"] == ("开场白" + "长文" * 400)[: gate.USER_INPUT_WINDOW]
        assert len(turn["userInput"]) == gate.USER_INPUT_WINDOW


class TestCorpusProvenance:
    """基准吃的是真实语料——合成句混进来，读数就只是在测门槛算术。"""

    def test_load_rejects_a_corpus_without_real_source(self, tmp_path):
        gate = _gate()
        path = tmp_path / "corpus.json"
        path.write_text(
            json.dumps(
                {
                    "schema": gate.CORPUS_SCHEMA,
                    "source": {"kind": "handWritten", "rowCount": 1},
                    "turns": [
                        {
                            "rowId": 1,
                            "agentId": None,
                            "skillName": "chat",
                            "userInput": "你好",
                            "success": True,
                            "timestamp": "2026-09-19T10:00:00+00:00",
                            "seenCount": 1,
                            "evidenceState": "evidenced",
                            "adoptionOutcome": None,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with pytest.raises(gate.CorpusError) as exc:
            gate.load_corpus(path)
        assert "来源" in str(exc.value)

    def test_load_rejects_the_synthetic_template_sentences(self, tmp_path):
        """票面点名的禁地：`eval_harness.py:255-265` 当场合成的 "使用 X 完成任务"。"""
        gate = _gate()
        path = tmp_path / "corpus.json"
        turns = [
            {
                "rowId": idx,
                "agentId": None,
                "skillName": "chat",
                "userInput": "使用 pdf_export 成功完成",
                "success": True,
                "timestamp": "2026-09-19T10:00:00+00:00",
                "seenCount": 1,
                "evidenceState": "evidenced",
                "adoptionOutcome": None,
            }
            for idx in (1, 2, 3)
        ]
        path.write_text(
            json.dumps(
                {
                    "schema": gate.CORPUS_SCHEMA,
                    "source": {"kind": gate.REAL_SOURCE_KIND, "rowCount": 3},
                    "turns": turns,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with pytest.raises(gate.CorpusError) as exc:
            gate.load_corpus(path)
        assert "合成" in str(exc.value)

    def test_load_rejects_turns_without_a_user_input(self, tmp_path):
        """空回合进不了基准：结晶器的模式键就是从上下文文本算的，空文本无闸可过。"""
        gate = _gate()
        corpus = gate.load_corpus(gate.DEFAULT_CORPUS)
        corpus["turns"][0]["userInput"] = ""
        path = tmp_path / "corpus.json"
        path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(gate.CorpusError) as exc:
            gate.load_corpus(path)
        assert "userInput" in str(exc.value)

    def test_frozen_real_corpus_loads(self):
        """仓内冻结的真实语料必须读得动——读不动 = 门禁上线即红。"""
        gate = _gate()
        corpus = gate.load_corpus(gate.DEFAULT_CORPUS)
        assert corpus["turns"], "冻结语料为空，基准无从读数"

    def test_frozen_real_corpus_is_not_a_template_corpus(self):
        """冻结语料的反面证据：真实库里存在失败行与无据行，模板语料不会两样都有。"""
        gate = _gate()
        turns = gate.load_corpus(gate.DEFAULT_CORPUS)["turns"]
        assert any(not t["success"] for t in turns), "真实语料里一条失败都没有=success 位又恒真了"
        assert any(t["evidenceState"] == "unevidenced" for t in turns), "真实语料里一条无据都没有"
        assert any(t["adoptionOutcome"] for t in turns), "真实语料里零采纳回写=006 通路没进语料"


class TestArmReadings:
    """A/B 两臂的读数必须来自 008 的 `quality_snapshot()`，且随结晶闸变。

    期望值按 `source_db` 的三组回合手推（独立真相源，不由被测代码反算）：
      · 「你好」×3（有票据、成采纳回写 success）→ 现行闸（≥3 次 & 成功率>0.6）放行；
      · 「今天许昌天气怎么样」×1（无票据自述）→ 无票可投，现行闸不放行，无闸臂放行；
      · 「deepseek v5」×1（有票据但客观失败）→ 观察数不足，现行闸不放行。
    """

    SNAPSHOT_KEYS = {
        "rows",
        "unevidenced_ratio",
        "hit_rate",
        "adoption_decisions",
        "adoption_success_rate",
        "adoption_unevidenced",
    }

    def test_arm_readings_are_exactly_the_snapshot_fields(self, source_db):
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        arms = gate.measure_arms(corpus)["arms"]
        for name, arm in arms.items():
            assert set(arm["snapshot"]) == self.SNAPSHOT_KEYS, (
                f"{name} 臂读数掺进了 quality_snapshot 之外的字段——008 定的算式只有一处"
            )

    def test_current_gate_admits_only_the_repeated_evidenced_group(self, source_db):
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        arms = gate.measure_arms(corpus)["arms"]
        post = arms["postTightening"]["snapshot"]
        assert post == {
            "rows": 1,
            "unevidenced_ratio": 0.0,
            "hit_rate": 1.0,
            "adoption_decisions": 1,
            "adoption_success_rate": 1.0,
            "adoption_unevidenced": 0,
        }

    def test_pre_tightening_arm_admits_every_group_with_a_green_tick(self, source_db):
        """收紧前每条观察都盖成功章 ⇒ 三组全进库，其中一组压根没有客观回执。"""
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        pre = gate.measure_arms(corpus)["arms"]["preTightening"]["snapshot"]
        assert pre == {
            "rows": 3,
            "unevidenced_ratio": round(1 / 3, 4),
            "hit_rate": round(2 / 3, 4),
            "adoption_decisions": 2,
            "adoption_success_rate": 0.5,
            "adoption_unevidenced": 0,
        }

    def test_delta_is_signed_and_direction_is_stated(self, source_db):
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        result = gate.measure_arms(corpus)
        assert result["delta"] == {
            "rows": -2,
            "unevidencedRatio": round(0.0 - 1 / 3, 4),
            "adoptionSuccessRate": round(1.0 - 0.5, 4),
        }

    def test_readings_survive_a_second_run_identically(self, source_db):
        """同一语料两遍读数必须逐字相同，否则 CI 上的 diff 无从解释。"""
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        assert json.dumps(gate.measure_arms(corpus), sort_keys=True) == json.dumps(
            gate.measure_arms(corpus), sort_keys=True
        )


class TestDirectionOnRealCorpus:
    """票面验收一：在冻结的真实语料上，两个读数可比且方向明确。"""

    def test_tightening_does_not_raise_the_unevidenced_share(self):
        gate = _gate()
        result = gate.measure_arms(gate.load_corpus(gate.DEFAULT_CORPUS))
        pre = result["arms"]["preTightening"]["snapshot"]
        post = result["arms"]["postTightening"]["snapshot"]
        assert post["rows"] > 0 and pre["rows"] > 0, "两臂都得有可比的行数，0 对 0 不算可比"
        assert post["unevidenced_ratio"] < pre["unevidenced_ratio"], (
            f"收紧后无证据占比没有下降：{pre['unevidenced_ratio']} → {post['unevidenced_ratio']}"
        )
        assert result["delta"]["unevidencedRatio"] < 0

    def test_tightening_does_not_lower_the_post_hoc_success_rate(self):
        gate = _gate()
        result = gate.measure_arms(gate.load_corpus(gate.DEFAULT_CORPUS))
        pre = result["arms"]["preTightening"]["snapshot"]
        post = result["arms"]["postTightening"]["snapshot"]
        assert post["adoption_success_rate"] is not None, "post 臂读不到事后成功率，两个数字不可比"
        assert post["adoption_success_rate"] > pre["adoption_success_rate"]
        assert result["delta"]["adoptionSuccessRate"] > 0


class TestKnobReverseLock:
    """票面验收三：拨 004 的旋钮读数必须跟着变，否则基准只是在测算术。"""

    def test_sealing_the_gate_moves_the_reading(self, source_db):
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        default = gate.measure_arms(corpus)["arms"]["postTightening"]["snapshot"]["rows"]
        sealed = gate.measure_arms(corpus, min_observations=1000)["arms"]["postTightening"]["snapshot"]["rows"]
        assert (default, sealed) == (1, 0), "闸拧到不可能通过，读数却不动——测的不是语料"

    def test_opening_the_gate_moves_the_reading_the_other_way(self, source_db):
        """观察数与成功率两个旋钮同时放松，那条"有票据但客观失败"的组就进来了。"""
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        default = gate.measure_arms(corpus)["arms"]["postTightening"]["snapshot"]
        opened = gate.measure_arms(
            corpus, min_observations=1, min_success_rate=0.0
        )["arms"]["postTightening"]["snapshot"]
        assert (default["rows"], opened["rows"]) == (1, 2)
        # 放进来了失败经验 ⇒ 事后成功率必须被拉低，读数方向也要跟着动
        assert (default["adoption_success_rate"], opened["adoption_success_rate"]) == (1.0, 0.5)

    def test_knob_values_reach_the_crystallizer_through_the_bridge(self, source_db):
        """旋钮必须经 `attach_crystallizer` 桥推进闸，而不是脚本自己另设一份。"""
        gate = _gate()
        corpus = gate.freeze_corpus(str(source_db))
        arm = gate.measure_arms(corpus, min_observations=7)["arms"]["postTightening"]
        assert arm["gate"]["minObservations"] == 7

    def test_opening_the_knob_on_the_real_corpus_flips_the_verdict(self, capsys):
        """把现行闸拧到"来者不拒"，真实语料必须当场变红。

        这是反向锁的门禁级形态：读数与放行结论都得跟着旋钮动。只动读数不动结论，
        说明判据没吃到那格；纹丝不动，说明基准测的是算术不是语料。
        """
        gate = _gate()
        assert gate.main([]) == 0
        capsys.readouterr()
        assert gate.main(["--min-observations", "1", "--min-success-rate", "0"]) == 1
        out = capsys.readouterr().out
        assert "arm=postTightening" in out and "rows=79" in out
        assert "adoptionHurts" in out


def _measurement(pre_ratio=0.0595, pre_rows=84, post_rows=18, post_ratio=0.0,
                 post_decisions=1, post_rate=1.0):
    """手搓一份 measurement（judge 的入参形状），用于逐条点亮判据。"""
    return {
        "arms": {
            "preTightening": {"snapshot": {"rows": pre_rows, "unevidenced_ratio": pre_ratio}},
            "postTightening": {
                "snapshot": {
                    "rows": post_rows,
                    "unevidenced_ratio": post_ratio,
                    "adoption_decisions": post_decisions,
                    "adoption_success_rate": post_rate,
                }
            },
        }
    }


class TestVerdicts:
    """判据必须咬合：每条都要有一个让读数变红的反例，阈值取自 008 不是另建一套。"""

    def test_the_real_corpus_passes_clean(self):
        gate = _gate()
        measurement = gate.measure_arms(gate.load_corpus(gate.DEFAULT_CORPUS))
        assert gate.judge(measurement) == [], "真实语料被判红——要么质量真退了，要么判据写坏了"

    def test_majority_unevidenced_corpus_is_a_violation(self):
        gate = _gate()
        rules = [v["rule"] for v in gate.judge(_measurement(pre_ratio=0.9, post_ratio=0.9))]
        assert "corpusMostlyUnevidenced" in rules

    def test_low_post_hoc_success_rate_is_a_violation(self):
        gate = _gate()
        violations = gate.judge(_measurement(post_rows=40, post_decisions=10, post_rate=0.3))
        assert "adoptionHurts" in [v["rule"] for v in violations]

    def test_a_single_adoption_is_noise_not_a_trend(self):
        """008 口径：`decisions < 2` 不下结论——一次成败就报警是把噪声当趋势。"""
        gate = _gate()
        assert gate.judge(_measurement(post_decisions=1, post_rate=0.0)) == []

    def test_a_gate_that_admits_nothing_is_not_a_passing_grade(self):
        """读不到数就当没问题，正是 008 删掉的那种假观测面。"""
        gate = _gate()
        rules = [v["rule"] for v in gate.judge(_measurement(post_rows=0, post_decisions=0, post_rate=None))]
        assert "gateAdmitsNothing" in rules

    def test_a_gate_that_admits_more_than_no_gate_is_not_biting(self):
        gate = _gate()
        rules = [v["rule"] for v in gate.judge(_measurement(post_rows=100))]
        assert "gateNotTightening" in rules

    def test_thresholds_come_from_the_metrics_sheet(self, monkeypatch):
        """把 008 的告警阈值挪一下，判据必须跟着挪——否则就是脚本里私藏了第二份。"""
        from neurova.evolution.rsi.metrics import RSIMetrics

        gate = _gate()
        measurement = _measurement(pre_ratio=0.6, post_ratio=0.6)
        assert "corpusMostlyUnevidenced" in [v["rule"] for v in gate.judge(measurement)]
        monkeypatch.setitem(RSIMetrics.ALERT_THRESHOLDS, "experience_unevidenced_ratio_warning", 0.9)
        assert gate.judge(measurement) == []


class TestLowSignalProbe:
    """低质探针语料：全自述成功 + 零客观回执 + 同句反复（票面点名的三种病形态）。"""

    def test_probe_is_all_self_reported_and_has_no_ticket(self):
        gate = _gate()
        turns = gate.load_corpus(gate.LOW_SIGNAL_PROBE, allowed_kinds=(gate.PROBE_SOURCE_KIND,))["turns"]
        assert all(t["success"] for t in turns)
        assert all(t["evidenceState"] == "unevidenced" for t in turns), "探针里混进了有票据的回合"

    def test_probe_is_the_same_sentence_repeated(self):
        gate = _gate()
        turns = gate.load_corpus(gate.LOW_SIGNAL_PROBE, allowed_kinds=(gate.PROBE_SOURCE_KIND,))["turns"]
        assert len({t["userInput"] for t in turns}) == 1, "同句反复是这条探针的签名，散了就测不到去重"
        assert sum(t["seenCount"] for t in turns) >= 3

    def test_probe_is_judged_red(self):
        gate = _gate()
        probe = gate.load_corpus(gate.LOW_SIGNAL_PROBE, allowed_kinds=(gate.PROBE_SOURCE_KIND,))
        rules = [v["rule"] for v in gate.judge(gate.measure_arms(probe))]
        assert "corpusMostlyUnevidenced" in rules
        assert "gateAdmitsNothing" in rules

    def test_probe_cannot_masquerade_as_the_baseline(self):
        gate = _gate()
        with pytest.raises(gate.CorpusError) as exc:
            gate.load_corpus(gate.LOW_SIGNAL_PROBE)
        assert "来源" in str(exc.value)


class TestGateExitCodes:
    """门禁必须给出可复现的 exit code：0 绿、1 质量不达标、2 门禁自己不可信。"""

    def test_real_corpus_exits_zero(self, capsys):
        gate = _gate()
        assert gate.main([]) == 0
        out = capsys.readouterr().out
        assert "门禁通过" in out

    def test_low_signal_corpus_exits_nonzero(self, capsys):
        gate = _gate()
        code = gate.main(["--corpus", str(gate.LOW_SIGNAL_PROBE)])
        assert code == 1, "注入低质语料不报错的红——门禁在空转"
        out = capsys.readouterr().out
        assert "corpusMostlyUnevidenced" in out

    def test_missing_corpus_exits_two(self, capsys):
        gate = _gate()
        assert gate.main(["--corpus", str(gate.PROJECT_ROOT / "nope.json")]) == 2

    def test_probe_that_stops_failing_makes_the_gate_untrustworthy(self, monkeypatch, capsys):
        """探针不红 = 判据坏了，这种"全绿"比红更危险，按基础设施错误处理。"""
        gate = _gate()
        monkeypatch.setattr(gate, "judge", lambda measurement: [])
        assert gate.main([]) == 2
        assert "自证失败" in capsys.readouterr().err

    def test_report_prints_both_readings_at_fixed_precision(self, capsys):
        gate = _gate()
        gate.main([])
        out = capsys.readouterr().out
        assert "unevidencedRatio=0.0595" in out and "unevidencedRatio=0.0000" in out
        assert "adoptionSuccessRate=0.2000" in out and "adoptionSuccessRate=1.0000" in out
        assert "delta(post-pre)" in out

    def test_crystallization_write_gate_disabled_makes_the_gate_loud(self, monkeypatch, source_db):
        """`NEUROVA_CRYSTALLIZATION_LLM_GATE=0` 时没有可观测的过闸面——不许静默读数。"""
        gate = _gate()
        monkeypatch.setenv("NEUROVA_CRYSTALLIZATION_LLM_GATE", "0")
        with pytest.raises(gate.GateUnavailable):
            gate.measure_arms(gate.freeze_corpus(str(source_db)))

    def test_the_script_itself_stays_out_of_the_protected_list(self):
        """门禁脚本不进受保护清单，但钉它行为的测试必须进（000-索引 纪律 7）。

        清单是"跑哪些测试"，不是"跑哪些脚本"；把门禁脚本自身列进去会让它被
        pytest 当测试文件收集，空转一次还不出声。
        """
        listed = [
            line.strip()
            for line in repo_path("scripts", "ci", "protected_tests.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert "scripts/ci/experience_quality_gate.py" not in listed, (
            "scripts/ci/experience_quality_gate.py 被列进了受保护测试清单"
        )
        assert "tests/unit/test_experience_quality_gate.py" in listed, (
            "钉门禁行为的测试文件没进清单——它的绿就等于没跑过"
        )

    @pytest.mark.skipif(not _gate().PRODUCTION_DB.is_file(), reason="本地没有生产经验库，冻结模式无从取证")
    def test_freeze_mode_writes_where_told_and_touches_nothing_else(self, tmp_path):
        """`--freeze-corpus` 只准写调用点名的输出路径——默认覆盖冻结语料是维护者动作。"""
        gate = _gate()
        before = gate.PRODUCTION_DB.read_bytes()
        out = tmp_path / "corpus.json"
        assert gate.main(["--freeze-corpus", str(gate.PRODUCTION_DB), "--out", str(out)]) == 0
        assert gate.PRODUCTION_DB.read_bytes() == before, "冻结模式写了生产库——运行数据被污染"
        assert out.is_file()
