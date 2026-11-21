package top.neurova.mobile.core.model

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P1-8 演化状态只读面线上契约——样本取自 governance.py 世代端点实出形状
 * （generation_ledger.py EvolutionGeneration.to_dict() / _generationSummary()）：
 *   - {code,data} 信封的 data 段由 HttpChannel.unwrapData 解出后进模型；
 *   - 门禁三态 verdicts 键为 g0..g4，state ∈ {passed, failed, unevidenced}；
 *   - 根代 parentNo=null、未回滚代 rolledBackTo=null，字段必须可空。
 */
class EvolutionWireTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun generationListDecodesEnvelopeData() {
        val payload = """
            {"generations":[
              {"generationNo":3,"parentNo":2,"status":"deployed",
               "decision":{"kind":"auto","approver":"","reason":""},
               "promotedAt":"2026-11-21T10:00:00+00:00"},
              {"generationNo":2,"parentNo":1,"status":"rolledBack",
               "decision":{"kind":"approval","approver":"admin","reason":""},
               "promotedAt":"2026-11-20T10:00:00+00:00"}
            ],"count":2}
        """.trimIndent()
        val list = json.decodeFromString(EvolutionGenerationList.serializer(), payload)
        assertEquals(2, list.count)
        assertEquals(2, list.generations.size)
        val first = list.generations[0]
        assertEquals(3L, first.generationNo)
        assertEquals(2L, first.parentNo)
        assertEquals("deployed", first.status)
        assertEquals("auto", first.decision?.kind)
        assertEquals("2026-11-21T10:00:00+00:00", first.promotedAt)
        // 审批人随行可见（approval 裁决必须能看出是谁批的）
        assertEquals("admin", list.generations[1].decision?.approver)
    }

    @Test
    fun generationDecodesFullArchiveWithThreeStateVerdicts() {
        val payload = """
            {"generationNo":3,"parentNo":2,"basisCommit":"abc1234",
             "createdAt":"2026-11-21T09:00:00+00:00",
             "signals":[{"kind":"lesson","ref":"lesson-7","summary":"web_fetch 连续失败"}],
             "changes":[{"targetId":"rsi_escalation_sleep","kind":"param","ref":"candidate-3","rationale":"提升决策档通过率"}],
             "verdicts":{"g0":{"state":"passed","reason":""},
                         "g2":{"state":"failed","reason":"决策档回退"},
                         "g3":{"state":"unevidenced","reason":"无 A/B 数据"}},
             "decision":{"kind":"approval","approver":"admin","reason":""},
             "deployment":{"promotedAt":"2026-11-21T10:00:00+00:00",
                           "canaryConclusion":"rollback: 错误率越界",
                           "rolledBackTo":2,
                           "canaryStartedAt":"2026-11-21T09:30:00+00:00"},
             "status":"rolledBack"}
        """.trimIndent()
        val gen = json.decodeFromString(EvolutionGeneration.serializer(), payload)
        assertEquals(3L, gen.generationNo)
        assertEquals("abc1234", gen.basisCommit)
        assertEquals(1, gen.signals.size)
        assertEquals("lesson", gen.signals[0].kind)
        assertEquals("web_fetch 连续失败", gen.signals[0].summary)
        assertEquals("rsi_escalation_sleep", gen.changes[0].targetId)
        // 三态逐门保真：passed / failed / unevidenced 不折叠
        assertEquals("passed", gen.verdicts["g0"]?.state)
        assertEquals("failed", gen.verdicts["g2"]?.state)
        assertEquals("决策档回退", gen.verdicts["g2"]?.reason)
        assertEquals("unevidenced", gen.verdicts["g3"]?.state)
        assertEquals("admin", gen.decision?.approver)
        assertEquals("rollback: 错误率越界", gen.deployment?.canaryConclusion)
        assertEquals(2L, gen.deployment?.rolledBackTo)
        assertEquals("rolledBack", gen.status)
    }

    @Test
    fun rootGenerationHasNullParentAndRolledBackTo() {
        val payload = """
            {"generationNo":1,"parentNo":null,"basisCommit":"r0","createdAt":"2026-11-19T09:00:00+00:00",
             "signals":[],"changes":[],"verdicts":{},"decision":null,"deployment":null,"status":"deployed"}
        """.trimIndent()
        val gen = json.decodeFromString(EvolutionGeneration.serializer(), payload)
        assertNull("根代 parentNo 必须可空", gen.parentNo)
        assertNull("未回滚代 rolledBackTo 必须可空", gen.deployment?.rolledBackTo)
        assertTrue(gen.verdicts.isEmpty())
        assertNull(gen.decision)
    }

    @Test
    fun lineageDecodesNestedChain() {
        val payload = """
            {"lineage":[
              {"generationNo":3,"parentNo":2,"basisCommit":"c3","createdAt":"","signals":[],"changes":[],
               "verdicts":{},"decision":null,"deployment":null,"status":"deployed"},
              {"generationNo":2,"parentNo":1,"basisCommit":"c2","createdAt":"","signals":[],"changes":[],
               "verdicts":{},"decision":null,"deployment":null,"status":"deployed"},
              {"generationNo":1,"parentNo":null,"basisCommit":"c1","createdAt":"","signals":[],"changes":[],
               "verdicts":{},"decision":null,"deployment":null,"status":"deployed"}
            ]}
        """.trimIndent()
        val lineage = json.decodeFromString(EvolutionLineage.serializer(), payload)
        assertEquals(3, lineage.lineage.size)
        assertEquals(3L, lineage.lineage[0].generationNo)
        assertEquals(1L, lineage.lineage[2].generationNo)
        assertNull(lineage.lineage[2].parentNo)
    }

    @Test
    fun summaryToleratesMissingOptionalFields() {
        // 后端对未部署代 promotedAt 出空串、decision 可缺——投影必须容缺不炸
        val payload = """
            {"generations":[{"generationNo":1,"parentNo":null,"status":"proposed","promotedAt":""}],"count":1}
        """.trimIndent()
        val list = json.decodeFromString(EvolutionGenerationList.serializer(), payload)
        assertEquals(1, list.count)
        assertNull(list.generations[0].decision)
        assertEquals("", list.generations[0].promotedAt)
    }
}
