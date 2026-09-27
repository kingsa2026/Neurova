# -*- coding: utf-8 -*-
"""逐字可核闸升为共享门（001）：同一类风险不许存在两套强度不同的门。

现状：`context/summarizing_compressor.py` 里已有一套正确且完整的
"摘要中出现的标识符必须逐字出现在证据里"判定，但它的调用方全仓只有摘要器自己。
三条会把文本回灌进后续决策的入库口一直绕过它：

1. 经验库（`skills/experience_knowledge_base.py`）——回复文本每轮都是新的模型输出；
2. 知识准入（`knowledge/foundation/admission.py`）——知识会被当事实注入；
3. 元认知教训（`cognitive_layers/meta_cognition_layer/self_model.py`）——教训会拦工具。

本文件先红后绿。红灯阶段断言的是**期望行为**，不是现状的形状。
"""

from __future__ import annotations

import pytest


class TestSharedGateIsSingleSource:
    """M1：搬家，不新造——提取域与判定实现全仓各只有一处。"""

    def testSharedGateExtractsFourIdentifierClasses(self):
        """四类标识符（URL / 多段路径 / semver / hex 片段）各一条正控。

        缺任何一类即红：搬家过程丢模式是最容易被忽略的失真。
        """
        from neurova.knowledge.verifiability import extract_identifiers

        url = "https://api.example.com/v2/health"
        path = "/etc/neurova/config.yaml"
        version = "2.3.1"
        digest = "9f2c1ab7de40"

        found = extract_identifiers(" ".join((url, path, version, digest)))

        assert url in found, "URL 类丢失"
        assert path in found, "多段路径类丢失"
        assert version in found, "semver 类丢失"
        assert digest in found, "hex 片段类丢失"

    def testGateDefinitionExistsExactlyOnce(self):
        """全仓 `find_violations` 定义有且仅有一处（教义第 6 条：不新造平行体系）。

        搬家若留下旧副本，两处就会各自漂移，而漂移没有任何红。
        """
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[3]
        pattern = re.compile(r"^(?:async )?def find_violations\s*\(", re.MULTILINE)
        hits = []
        for path in root.rglob("*.py"):
            text = str(path).replace("\\", "/")
            if any(skip in text for skip in ("/.venv/", "/.stash/", "src-tauri", "/node_modules/")):
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if pattern.search(body):
                hits.append(str(path.relative_to(root)))

        assert hits == ["neurova/knowledge/verifiability.py"], (
            "find_violations 定义处应恰为共享位一处，实测：%s" % hits
        )

    def testSummaryCallSiteImportsSharedGateInsteadOfRedefining(self):
        """摘要侧改为从共享位 import（行为不变的接口面反证）。"""
        from neurova.context import summarizing_compressor as summary_module
        from neurova.knowledge import verifiability

        assert summary_module.find_violations is verifiability.find_violations
        assert summary_module.extract_identifiers is verifiability.extract_identifiers


class TestSummaryCallSiteStillFailsClosed:
    """K2：摘要侧行为逐字节不变——本票一行都不动它的语义。"""

    @pytest.mark.asyncio
    async def testSummaryCallSiteStillFailsClosedOnUnrepairedViolation(self):
        """repair 后仍违规 ⇒ 保留旧摘要（fail-closed 语义保持不变）。"""
        from neurova.context.pool_models import ContextInput, ContextSource
        from neurova.context.summarizing_compressor import SummarizingCompressor

        replies = ["摘要引用了 https://hallucinated.example.com/v9", "依然是 https://hallucinated.example.com/v9"]

        async def llm_call(prompt):
            return replies.pop(0)

        chunk = ContextInput(
            source=ContextSource.CONVERSATION,
            content="我们把服务部署到了 https://api.example.com/v2",
            priority=50,
            metadata={"turn_id": 1, "role": "user"},
        )
        compressor = SummarizingCompressor(llm_call=llm_call, timeout_s=5)

        result = await compressor.summarize([chunk], previous_summary="旧摘要保持不动")

        assert result == "旧摘要保持不动", "repair 后仍违规必须 fail-closed 回旧摘要"


class TestExperienceIngestionGate:
    """M2-1：经验库违规 ⇒ 记违规标记 + 降权，不阻塞写入。"""

    def testExperienceRecordCarriesViolationMarkInsteadOfSilentAccept(self, tmp_path):
        from neurova.skills.experience_knowledge_base import (
            ExperienceKnowledgeBase,
            ExperienceRecord,
        )

        kb = ExperienceKnowledgeBase(str(tmp_path / "ekb.db"))
        try:
            clean_id = kb.add_experience_record(
                skill_name="deploy",
                exp=ExperienceRecord(
                    skill_name="deploy",
                    context={"user_input": "部署到 /etc/neurova/config.yaml"},
                    result={"reply_excerpt": "已按 /etc/neurova/config.yaml 部署完成"},
                    success=True,
                ),
                evidence=True,
                evidence_text="把服务部署到 /etc/neurova/config.yaml，已完成",
            )
            violated_id = kb.add_experience_record(
                skill_name="deploy",
                exp=ExperienceRecord(
                    skill_name="deploy",
                    context={"user_input": "帮我看看部署情况"},
                    result={"reply_excerpt": "已按 /opt/ghost/nowhere.yaml 部署完成"},
                    success=True,
                ),
                evidence=True,
                evidence_text="帮我看看部署情况",
            )

            clean = kb.get_record_by_id(clean_id)
            violated = kb.get_record_by_id(violated_id)

            # 判据单列一轴：`evidence_state` 记的是"本轮有没有服务端票据"，
            # `adoption_outcome` 记的是"被采纳后成没成"。逐字可核是第三件事，
            # 挤进任何一栏都会让那一栏的读数不再指它原本指的东西。
            assert clean["verifiability_state"] == "verified", "证据逐字对得上即通过"
            assert violated["verifiability_state"] == "violated", (
                "回复引用了原文里不存在的路径，必须留违规标记而不是静默采纳"
            )
            assert violated["evidence_state"] == "evidenced", (
                "违规与票据态正交：不能把违规写进 evidence_state 冒充'无票据'"
            )
        finally:
            kb.close()

    def testViolationIsNotFoldedIntoASingleBoolean(self):
        """三条口的处置差异必须在字段上可分辨，不能三条都写同一个布尔。"""
        from neurova.knowledge.verifiability import VERIFIABILITY_STATES, VIOLATION_OUTCOMES

        assert set(VIOLATION_OUTCOMES) == {"demoted", "rejected", "refused"}, (
            "三种代价必须各有名字：经验降权 / 知识拒断言 / 教训拒生成"
        )
        assert set(VERIFIABILITY_STATES) == {"unchecked", "verified", "violated"}, (
            "`unchecked` 必须自成一态：没提供证据文本 ≠ 核过且没问题"
        )

    def testViolatedRecordIsDemotedInRetrievalNotRemoved(self, tmp_path):
        """处置是降权而非剔除——经验是概率性资产，删掉会让检索面大面积失声。"""
        from neurova.skills.experience_knowledge_base import (
            ExperienceKnowledgeBase,
            ExperienceRecord,
        )

        kb = ExperienceKnowledgeBase(str(tmp_path / "ekb.db"))
        try:
            clean_id = kb.add_experience_record(
                skill_name="deploy",
                exp=ExperienceRecord(
                    skill_name="deploy",
                    context={"user_input": "把服务部署到生产环境，配置在 /etc/neurova/config.yaml"},
                    result={"reply_excerpt": "已按 /etc/neurova/config.yaml 部署完成"},
                    success=True,
                ),
                evidence=True,
                evidence_text="把服务部署到生产环境，按 /etc/neurova/config.yaml 完成",
            )
            violated_id = kb.add_experience_record(
                skill_name="deploy",
                exp=ExperienceRecord(
                    skill_name="deploy",
                    context={"user_input": "把服务部署到生产环境，配置在 /opt/ghost/nowhere.yaml"},
                    result={"reply_excerpt": "已按 /opt/ghost/nowhere.yaml 部署完成"},
                    success=True,
                ),
                evidence=True,
                evidence_text="把服务部署到生产环境",
            )

            hits = kb.find_similar_experiences(
                skill_name="deploy",
                context={"user_input": "把服务部署到生产环境"},
                limit=10,
            )
            by_id = {h["id"]: h for h in hits}

            assert violated_id in by_id, "违规条目仍须可见（降权不阻塞）"
            assert by_id[clean_id]["similarity_score"] > by_id[violated_id]["similarity_score"], (
                "引用不存在路径的条目排序必须往后掉"
            )
            assert by_id[violated_id]["verifiability_state"] == "violated"
        finally:
            kb.close()


class TestKnowledgeAdmissionGate:
    """M2-2：知识准入违规 ⇒ 拒该条断言，条目按现有诚实路径暴露。"""

    def testKnowledgeAssertionWithUnverifiableQuoteIsRejectedNotAdmitted(self, tmp_path):
        from neurova.knowledge.foundation.admission import (
            AdmissionRequest,
            AdmissionError,
            productionAdmissionGate,
        )
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        try:
            gate = productionAdmissionGate(store, toolVersion="unit-001")
            before = store.factCount()

            with pytest.raises(AdmissionError, match="逐字"):
                gate.admit(
                    AdmissionRequest(
                        agentId="default",
                        subjectLabel="部署清单",
                        predicateTermId="documented_as",
                        objectTerm="cfg",
                        content="配置在 /etc/neurova/config.yaml 与 /opt/ghost/nowhere.yaml",
                        sourceTurnId="turn:1",
                        evidenceText="配置在 /etc/neurova/config.yaml",
                        assertions=[{
                            "actorType": "user",
                            "actorId": "u1",
                            "mediumRef": "turn:1",
                            "statementText": "配置在 /etc/neurova/config.yaml",
                        }],
                    ),
                    allowPendingSegments=True,
                )

            assert store.factCount() == before, "被拒的断言不得留下任何事实行"
        finally:
            store.close()

    def testVerifiableAssertionStillPasses(self, tmp_path):
        """正控：证据齐备的断言照常入库——闸不能变成一刀切的封条。"""
        from neurova.knowledge.foundation.admission import (
            AdmissionRequest,
            productionAdmissionGate,
        )
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        try:
            gate = productionAdmissionGate(store, toolVersion="unit-001")
            receipt = gate.admit(
                AdmissionRequest(
                    agentId="default",
                    subjectLabel="部署清单",
                    predicateTermId="documented_as",
                    objectTerm="cfg",
                    content="配置在 /etc/neurova/config.yaml",
                    sourceTurnId="turn:1",
                    assertions=[{
                        "actorType": "user",
                        "actorId": "u1",
                        "mediumRef": "turn:1",
                        "statementText": "配置在 /etc/neurova/config.yaml",
                    }],
                ),
                allowPendingSegments=True,
            )

            assert receipt.factId, "证据齐备的断言必须照常落库"
        finally:
            store.close()


class TestMetaCogLessonGate:
    """M2-3：元认知教训违规 ⇒ 拒绝生成教训（代价最高，处置最严）。"""

    def testMetaCogLessonWithUnverifiableQuoteIsNotProduced(self):
        from neurova.cognitive_layers.meta_cognition_layer.self_model import (
            lessonViolations,
        )

        events = [
            {
                "subject": "web_search",
                "operator": "drift",
                "text": "工具 web_search 失败于 /opt/ghost/nowhere.yaml",
                "evidence": {"baseline": 0.9, "window_rate": 0.0},
            }
        ]

        violations = lessonViolations(events, evidence_text="工具 web_search 全部失败")

        assert violations, "教训引用了证据里不存在的路径，必须能被判出违规"

    def testMetaCogLessonWithoutIdentifiersIsNotBlocked(self):
        from neurova.cognitive_layers.meta_cognition_layer.self_model import (
            lessonViolations,
        )

        lessons = [
            {
                "subject": "web_search",
                "operator": "drift",
                "text": "工具 web_search 成功率从 90% 滑落至 0%，建议暂避",
                "evidence": {"baseline": 0.9, "window_rate": 0.0},
            }
        ]

        assert lessonViolations(lessons, evidence_text="工具 web_search 全败") == [], (
            "无标识符的教训不该被闸挡住——那会让元认知面整体失声"
        )


class TestCredibilityReplayabilityBonus:
    """M3：摘掉恒真的 +0.05。"""

    def testReplayabilityBonusIsNotAwardedForPointerWithoutRetrievableText(self, tmp_path):
        from neurova.knowledge.foundation.credibility import ConfidenceAggregator

        aggregator = ConfidenceAggregator()
        assertions = [{"actor_type": "user", "actor_id": "u1"}]

        with_pointer = {"source_turn_id": "entry:kb_1"}
        without_pointer = {"source_turn_id": ""}

        first = aggregator.aggregate(with_pointer, assertions)
        second = aggregator.aggregate(without_pointer, assertions)

        assert first["confidence"] == second["confidence"], (
            "`source_turn_id` 承载条目身份而非可回放现场指针，这一栏不携带可核信息"
        )
        assert "有现场可回放" not in first["basis"], "basis 不得再出现这一项"

    def testDefinitionNoLongerPromisesTheBonus(self):
        from neurova.knowledge.foundation.credibility import ConfidenceAggregator

        assert "可回放" not in ConfidenceAggregator.definition(), (
            "定义式与实现必须同源，摘了加分就要摘定义"
        )
