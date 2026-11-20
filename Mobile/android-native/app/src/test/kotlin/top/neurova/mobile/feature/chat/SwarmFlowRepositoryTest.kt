package top.neurova.mobile.feature.chat

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import top.neurova.mobile.core.model.ServerProfile
import top.neurova.mobile.core.net.ChannelHttpException
import top.neurova.mobile.core.net.HttpChannel
import top.neurova.mobile.core.store.CredentialStore

/**
 * 车道G 网络层契约：getSwarmRunGraph / getSwarmRunCandidates 走既有 HttpChannel
 * （Bearer 注入 + 401 续签 + 信封解包），端点与 console.py 同源：
 *   GET /api/v1/console/chat/runs/{parent_session_id}/graph
 *   GET /api/v1/console/chat/runs/{parent_session_id}/candidates
 * 失败面诚实：非 2xx 抛 ChannelHttpException，不吞不降级。
 */
class SwarmFlowRepositoryTest {

    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        // MockWebServer 必须收口，否则线程泄漏拖垮后续测试（仓内既有惯例）
        runCatching { server.shutdown() }
    }

    private fun newRepo(): ChatRepository {
        val profile = ServerProfile(
            id = "test",
            name = "test",
            baseUrl = server.url("/").toString().trimEnd('/'),
        )
        val http = HttpChannel({ profile }, FakeCredentials(), CoroutineScope(Dispatchers.Unconfined))
        return ChatRepository(http)
    }

    @Test
    fun getSwarmRunGraphParsesEnvelopeAndInjectsBearer() = runTest {
        server.enqueue(MockResponse().setBody(GRAPH_ENVELOPE).setHeader("Content-Type", "application/json"))
        val graph = newRepo().getSwarmRunGraph("sess-1")

        assertEquals(2, graph.nodes.size)
        assertEquals("sa-root", graph.nodes[0].id)
        assertEquals("atlas", graph.nodes[0].memberName)
        assertEquals(1763644800.5, graph.nodes[0].startedAt, 0.0001)
        assertEquals("running", graph.nodes[1].status)
        assertEquals(1, graph.edges.size)
        assertEquals("spawn", graph.edges[0].type)
        assertEquals("sa-root", graph.edges[0].from)
        assertEquals("sa-child", graph.edges[0].to)
        assertTrue(graph.meta.truncated)
        assertEquals(5, graph.meta.counts["edges"])

        val recorded = server.takeRequest()
        assertEquals("/api/v1/console/chat/runs/sess-1/graph", recorded.path)
        assertEquals("Bearer jwt-test", recorded.getHeader("Authorization"))
    }

    @Test
    fun getSwarmRunCandidatesParsesBoard() = runTest {
        server.enqueue(MockResponse().setBody(CANDIDATES_ENVELOPE).setHeader("Content-Type", "application/json"))
        val board = newRepo().getSwarmRunCandidates("sess-1")

        assertEquals(7, board.revision)
        assertEquals("replay", board.source)
        assertTrue(board.incomplete)
        assertEquals(1, board.candidates.size)
        assertEquals("c-1", board.candidates[0].candidateId)
        assertEquals("submitted", board.candidates[0].status)
        assertEquals(listOf("report.md"), board.candidates[0].artifactKeys)
        assertEquals(1, board.conflicts.size)
        assertEquals("c-0", board.conflicts[0].candidateId)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/console/chat/runs/sess-1/candidates", recorded.path)
    }

    @Test
    fun graphHttpErrorSurfacesHonestly() {
        // run 台账关闭（NEUROVA_RUN_GATE=off）→ 503：必须以异常浮出，不得静默当空图
        server.enqueue(MockResponse().setResponseCode(503).setBody("""{"detail":"run ledger off"}"""))
        val repo = newRepo()
        val thrown = assertThrows(ChannelHttpException::class.java) {
            runBlocking { repo.getSwarmRunGraph("sess-1") }
        }
        assertEquals(503, thrown.code)
    }

    private class FakeCredentials : CredentialStore {
        override fun accessToken(): String = "jwt-test"
        override fun refreshToken(): String = ""
        override fun deviceSecret(): String = ""
        override fun pairedIdentity(): Pair<String, String>? = null
        override fun pairedWsUrl(): String = ""
        override fun saveTokens(access: String, refresh: String) = Unit
        override fun savePairedIdentity(pairingId: String, deviceSecret: String) = Unit
        override fun savePairedWsUrl(url: String) = Unit
        override fun clearAuth() = Unit
    }

    private companion object {
        private val GRAPH_ENVELOPE = """
            {"code":0,"message":"success","data":{"parent_session_id":"sess-1",
             "nodes":[
               {"id":"sa-root","nodeType":"run","run_id":"r-1","member_name":"atlas","kind":"internal",
                "executor_tool":"","status":"completed","depth":0,"team_id":"t-1",
                "started_at":1763644800.5,"finished_at":1763644860.25,"duration_ms":59750.0,
                "error_type":"","level":"","decision":"","decided_by":"","request_id":"",
                "candidate_id":"","artifact_keys":[],"base_revision":0,"note":""},
               {"id":"sa-child","nodeType":"run","run_id":"r-2","member_name":"scout","kind":"external",
                "executor_tool":"browser","status":"running","depth":1,"team_id":"t-1",
                "started_at":1763644810.0,"finished_at":0.0,"duration_ms":0.0,"error_type":"",
                "level":"","decision":"","decided_by":"","request_id":"","candidate_id":"",
                "artifact_keys":[],"base_revision":0,"note":""}],
             "edges":[
               {"id":"spawn:sa-root->sa-child","type":"spawn","from":"sa-root","to":"sa-child",
                "level":"","status":"","decision":"","decided_by":""}],
             "meta":{"revision":2,"generated_at":1763644900.125,"truncated":true,
                     "candidates_incomplete":false,
                     "counts":{"nodes":2,"runNodes":2,"approvalCards":0,"candidateCards":0,
                               "edges":5,"danglingEdges":0,"spawn":1}}}}
        """.trimIndent()

        private val CANDIDATES_ENVELOPE = """
            {"code":0,"message":"success","data":{"parent_session_id":"sess-1",
             "revision":7,
             "candidates":[{"candidate_id":"c-1","run_id":"sa-1","artifact_keys":["report.md"],
                "base_revision":2,"status":"submitted","conflict_with":[],
                "note":"","created_at":"2026-11-21T10:00:00","decided_at":""}],
             "conflicts":[{"candidate_id":"c-0","run_id":"sa-0","artifact_keys":["report.md"],
                "base_revision":1,"status":"accepted","conflict_with":["c-1"],
                "note":"","created_at":"2026-11-21T09:00:00","decided_at":"2026-11-21T09:01:00"}],
             "incomplete":true,"source":"replay"}}
        """.trimIndent()
    }
}
