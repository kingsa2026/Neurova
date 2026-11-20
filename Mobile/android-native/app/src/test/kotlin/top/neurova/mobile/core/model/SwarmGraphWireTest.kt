package top.neurova.mobile.core.model

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 蜂群协作投影线上契约（车道G）。
 * 事实源：neurova/agent/swarm_graph_projection.py、candidate_projection.py、
 * NeurUI/src/types/swarmGraph.ts（PC 端手抄对齐同一形状）。
 * 钉住三件事：
 * - epoch 秒/duration 是浮点（1e9 量级带小数），必须落 Double 而不是整型；
 * - 节点三态同构（nodeType=run|approval|candidate），边四类（spawn|dependency|approval|candidate），
 *   "from"/"to" 是字面键；
 * - 未知字段忽略、缺省字段回落默认（后端加字段不炸端上）。
 */
class SwarmGraphWireTest {

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Test
    fun graphProjectionDecodesRealBackendPayload() {
        val payload = """
            {"code":0,"message":"success","data":{"parent_session_id":"sess-1",
             "nodes":[
               {"id":"sa-root","nodeType":"run","run_id":"r-1","member_name":"atlas","kind":"internal",
                "executor_tool":"","status":"completed","depth":0,"team_id":"t-1",
                "started_at":1763644800.5,"finished_at":1763644860.25,"duration_ms":59750.0,
                "error_type":"","level":"","decision":"","decided_by":"","request_id":"",
                "candidate_id":"","artifact_keys":[],"base_revision":0,"note":"",
                "unknown_future_field":{"keep":"ignored"}},
               {"id":"sa-child","nodeType":"run","run_id":"r-2","member_name":"scout","kind":"external",
                "executor_tool":"browser","status":"running","depth":1,"team_id":"t-1",
                "started_at":1763644810.0,"finished_at":0.0,"duration_ms":0.0,"error_type":"",
                "level":"","decision":"","decided_by":"","request_id":"","candidate_id":"",
                "artifact_keys":[],"base_revision":0,"note":""},
               {"id":"approval:req-9","nodeType":"approval","run_id":"sa-root","member_name":"外发邮件",
                "kind":"","executor_tool":"","status":"approved","depth":0,"team_id":"",
                "started_at":1763644812.0,"finished_at":1763644820.0,"duration_ms":0.0,
                "error_type":"","level":"L1","decision":"approve","decided_by":"admin",
                "request_id":"req-9","candidate_id":"","artifact_keys":[],"base_revision":0,"note":""},
               {"id":"candidate:c-3","nodeType":"candidate","run_id":"sa-root","member_name":"report.md",
                "kind":"","executor_tool":"","status":"accepted","depth":0,"team_id":"",
                "started_at":1763644830.0,"finished_at":1763644840.0,"duration_ms":0.0,
                "error_type":"","level":"","decision":"","decided_by":"","request_id":"",
                "candidate_id":"c-3","artifact_keys":["report.md"],"base_revision":3,"note":""}
             ],
             "edges":[
               {"id":"spawn:sa-root->sa-child","type":"spawn","from":"sa-root","to":"sa-child",
                "level":"","status":"","decision":"","decided_by":""},
               {"id":"dep:sa-child->sa-root","type":"dependency","from":"sa-child","to":"sa-root",
                "level":"","status":"","decision":"","decided_by":""},
               {"id":"approval:req-9","type":"approval","from":"sa-root","to":"approval:req-9",
                "level":"L1","status":"approved","decision":"approve","decided_by":"admin"},
               {"id":"candidate:c-3","type":"candidate","from":"sa-root","to":"candidate:c-3",
                "level":"","status":"accepted","decision":"","decided_by":""}
             ],
             "meta":{"revision":3,"generated_at":1763644900.125,"truncated":false,
                     "candidates_incomplete":true,
                     "counts":{"nodes":4,"runNodes":2,"approvalCards":1,"candidateCards":1,
                               "edges":4,"danglingEdges":0,"spawn":1,"dependency":1,
                               "approval":1,"candidate":1}}}}
        """.trimIndent()
        val data = (json.parseToJsonElement(payload) as JsonObject)["data"] as JsonObject
        val projection = json.decodeFromJsonElement(SwarmGraphProjection.serializer(), data)

        assertEquals(4, projection.nodes.size)
        val run = projection.nodes[0]
        assertEquals("run", run.nodeType)
        assertEquals("sa-root", run.id)
        assertEquals("r-1", run.runId)
        assertEquals("atlas", run.memberName)
        assertEquals("internal", run.kind)
        assertEquals("completed", run.status)
        assertEquals(0, run.depth)
        assertEquals("t-1", run.teamId)
        assertEquals(1763644800.5, run.startedAt, 0.0001)
        assertEquals(1763644860.25, run.finishedAt, 0.0001)
        assertEquals(59750.0, run.durationMs, 0.0001)

        val external = projection.nodes[1]
        assertEquals("external", external.kind)
        assertEquals("browser", external.executorTool)
        assertEquals(1, external.depth)

        val approval = projection.nodes[2]
        assertEquals("approval", approval.nodeType)
        assertEquals("req-9", approval.requestId)
        assertEquals("L1", approval.level)
        assertEquals("approve", approval.decision)
        assertEquals("admin", approval.decidedBy)

        val candidate = projection.nodes[3]
        assertEquals("candidate", candidate.nodeType)
        assertEquals("c-3", candidate.candidateId)
        assertEquals(listOf("report.md"), candidate.artifactKeys)
        assertEquals(3, candidate.baseRevision)

        assertEquals(4, projection.edges.size)
        val spawn = projection.edges[0]
        assertEquals("spawn", spawn.type)
        assertEquals("sa-root", spawn.from)
        assertEquals("sa-child", spawn.to)
        assertEquals("dependency", projection.edges[1].type)
        val approvalEdge = projection.edges[2]
        assertEquals("approval", approvalEdge.type)
        assertEquals("L1", approvalEdge.level)
        assertEquals("approved", approvalEdge.status)
        assertEquals("candidate", projection.edges[3].type)
        assertEquals("accepted", projection.edges[3].status)

        assertEquals(3, projection.meta.revision)
        assertEquals(1763644900.125, projection.meta.generatedAt, 0.0001)
        assertFalse(projection.meta.truncated)
        assertTrue(projection.meta.candidatesIncomplete)
        assertEquals(4, projection.meta.counts["edges"])
        assertEquals(0, projection.meta.counts["danglingEdges"])
    }

    @Test
    fun candidateBoardDecodesRealBackendPayload() {
        val payload = """
            {"code":0,"message":"success","data":{"parent_session_id":"sess-1",
             "revision":7,
             "candidates":[
               {"candidate_id":"c-1","run_id":"sa-1","artifact_keys":["a.md","b.md"],
                "base_revision":2,"status":"submitted","conflict_with":["c-0"],
                "note":"","created_at":"2026-11-21T10:00:00","decided_at":""},
               {"candidate_id":"c-2","run_id":"sa-2","artifact_keys":[],
                "base_revision":0,"status":"reviseRequired","conflict_with":[],
                "note":"验收驳回","created_at":"2026-11-21T10:05:00",
                "decided_at":"2026-11-21T10:06:00"}],
             "conflicts":[
               {"candidate_id":"c-0","run_id":"sa-0","artifact_keys":["a.md"],
                "base_revision":1,"status":"accepted","conflict_with":[],
                "note":"","created_at":"2026-11-21T09:00:00","decided_at":"2026-11-21T09:01:00"}],
             "incomplete":false,"source":"replay","extra_unknown":"ignored"}}
        """.trimIndent()
        val data = (json.parseToJsonElement(payload) as JsonObject)["data"] as JsonObject
        val board = json.decodeFromJsonElement(SwarmCandidateBoard.serializer(), data)

        assertEquals(7, board.revision)
        assertEquals("replay", board.source)
        assertFalse(board.incomplete)
        assertEquals(2, board.candidates.size)
        val first = board.candidates[0]
        assertEquals("c-1", first.candidateId)
        assertEquals("sa-1", first.runId)
        assertEquals(listOf("a.md", "b.md"), first.artifactKeys)
        assertEquals(2, first.baseRevision)
        assertEquals("submitted", first.status)
        assertEquals(listOf("c-0"), first.conflictWith)
        assertEquals("", first.decidedAt)
        assertEquals("reviseRequired", board.candidates[1].status)
        assertEquals("验收驳回", board.candidates[1].note)
        assertEquals(1, board.conflicts.size)
        assertEquals("c-0", board.conflicts[0].candidateId)
    }

    @Test
    fun sparseNodePayloadFallsBackToDefaults() {
        // 后端字段缺省（或未来减字段）不炸端上：诚实降级为默认值
        val node = json.decodeFromJsonElement(
            SwarmGraphNode.serializer(),
            json.parseToJsonElement("""{"id":"sa-x","status":"running"}"""),
        )
        assertEquals("sa-x", node.id)
        assertEquals("run", node.nodeType)
        assertEquals("", node.memberName)
        assertEquals("internal", node.kind)
        assertEquals(0, node.depth)
        assertEquals(0.0, node.startedAt, 0.0)
        assertEquals(0.0, node.durationMs, 0.0)
        assertTrue(node.artifactKeys.isEmpty())
    }

    @Test
    fun runStatusToneMatchesPcVocabulary() {
        // 对齐 SwarmFlowPanel.vue RUN_STATUS_TONE（LEDGER_TO_WINDOW_STATUS 同源）：
        // queued/pending/parked/running/in_review → running；completed；failed/cancelled；未知落 running
        for (status in listOf("queued", "pending", "parked", "running", "in_review")) {
            assertEquals("status=$status", SwarmTone.RUNNING, SwarmStatusTone.fromRunStatus(status))
        }
        assertEquals(SwarmTone.COMPLETED, SwarmStatusTone.fromRunStatus("completed"))
        assertEquals(SwarmTone.FAILED, SwarmStatusTone.fromRunStatus("failed"))
        assertEquals(SwarmTone.FAILED, SwarmStatusTone.fromRunStatus("cancelled"))
        assertEquals(SwarmTone.RUNNING, SwarmStatusTone.fromRunStatus("some-new-state"))
    }

    @Test
    fun candidateAndApprovalTonesMatchPcVocabulary() {
        // CANDIDATE_STATUS_TONE：submitted→running，accepted→completed，rejected→failed，reviseRequired→warning
        assertEquals(SwarmTone.RUNNING, SwarmStatusTone.fromCandidateStatus("submitted"))
        assertEquals(SwarmTone.COMPLETED, SwarmStatusTone.fromCandidateStatus("accepted"))
        assertEquals(SwarmTone.FAILED, SwarmStatusTone.fromCandidateStatus("rejected"))
        assertEquals(SwarmTone.WARNING, SwarmStatusTone.fromCandidateStatus("reviseRequired"))
        assertEquals(SwarmTone.RUNNING, SwarmStatusTone.fromCandidateStatus(""))
        // APPROVAL_TONE：approved→completed，rejected→failed，pending/未知→running
        assertEquals(SwarmTone.COMPLETED, SwarmStatusTone.fromApprovalStatus("approved"))
        assertEquals(SwarmTone.FAILED, SwarmStatusTone.fromApprovalStatus("rejected"))
        assertEquals(SwarmTone.RUNNING, SwarmStatusTone.fromApprovalStatus("pending"))
    }
}
