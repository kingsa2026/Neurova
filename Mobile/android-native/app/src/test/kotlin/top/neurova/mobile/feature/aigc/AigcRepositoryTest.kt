package top.neurova.mobile.feature.aigc

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
 * AIGC 生成仓库契约（generation.py 事实源；对齐 SwarmFlowRepositoryTest 的
 * MockWebServer 形态）：Bearer 注入、信封解包、异步两段式（提交→轮询）、
 * 音频 code=-1 业务失败、超时/失败诚实抛出、媒体 url 解析。
 */
class AigcRepositoryTest {

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

    private fun newRepo(): AigcRepository {
        val profile = ServerProfile(
            id = "test",
            name = "test",
            baseUrl = server.url("/").toString().trimEnd('/'),
        )
        val http = HttpChannel({ profile }, FakeCredentials(), CoroutineScope(Dispatchers.Unconfined))
        return AigcRepository(http)
    }

    @Test
    fun submitImageParsesImagesAndInjectsBearer() = runTest {
        server.enqueue(MockResponse().setBody(IMAGE_ENVELOPE).setHeader("Content-Type", "application/json"))
        val result = newRepo().submitImage("一只赛博朋克猫", 768, 512)

        assertEquals("task-img-1", result.taskId)
        assertEquals(2, result.images.size)
        assertEquals("/api/v1/generation/files/task-img-1_0.png", result.images[0].url)
        assertEquals("", result.images[0].error)
        assertEquals("seed", result.ignoredParams)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/generation/image", recorded.path)
        assertEquals("Bearer jwt-test", recorded.getHeader("Authorization"))
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"prompt\":\"一只赛博朋克猫\""))
        assertTrue(body.contains("\"width\":768"))
        assertTrue(body.contains("\"height\":512"))
        assertTrue(body.contains("\"num_images\":1"))
    }

    @Test
    fun submitImageHttpErrorSurfacesDetail() {
        // 无可用图像服务商 → 服务端 400 + detail：必须以异常浮出，不吞不降级
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"未找到可用的图像生成服务商"}"""))
        val repo = newRepo()
        val thrown = assertThrows(ChannelHttpException::class.java) {
            runBlocking { repo.submitImage("p", 1024, 1024) }
        }
        assertEquals(400, thrown.code)
        assertTrue(thrown.detail.contains("未找到可用的图像生成服务商"))
    }

    @Test
    fun submitVideoReturnsTwoPhaseTaskId() = runTest {
        server.enqueue(MockResponse().setBody(VIDEO_SUBMIT_ENVELOPE).setHeader("Content-Type", "application/json"))
        val submitted = newRepo().submitVideo("城市夜景延时", 8, "1080p")

        assertEquals("task-video-1", submitted.taskId)
        assertEquals("submitted", submitted.status)
        assertEquals("wan", submitted.protocol)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/generation/video", recorded.path)
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"duration\":8"))
        assertTrue(body.contains("\"resolution\":\"1080p\""))
    }

    @Test
    fun submitMusicReturnsTwoPhaseTaskId() = runTest {
        server.enqueue(MockResponse().setBody(MUSIC_SUBMIT_ENVELOPE).setHeader("Content-Type", "application/json"))
        val submitted = newRepo().submitMusic("轻快的钢琴曲", 20)

        assertEquals("task-music-1", submitted.taskId)
        assertEquals("fal", submitted.protocol)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/generation/music", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"duration\":20"))
    }

    @Test
    fun submitAudioSuccessParsesUrl() = runTest {
        server.enqueue(MockResponse().setBody(AUDIO_SUCCESS_ENVELOPE).setHeader("Content-Type", "application/json"))
        val result = newRepo().submitAudio("你好，Neurova", "default", 1.0)

        assertEquals("/api/v1/generation/files/task-audio-1_0.wav", result.url)
        assertEquals("task-audio-1", result.taskId)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/generation/audio", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"text\":\"你好，Neurova\""))
    }

    @Test
    fun submitAudioBusinessFailureThrowsHonestly() {
        // 音频失败契约：HTTP 200 + code=-1 + message（与图像/视频非 2xx 不同），必须显式判 code
        server.enqueue(MockResponse().setBody(AUDIO_FAILURE_ENVELOPE).setHeader("Content-Type", "application/json"))
        val repo = newRepo()
        val thrown = assertThrows(GenerationSubmitFailed::class.java) {
            runBlocking { repo.submitAudio("文本", "default", 1.0) }
        }
        assertTrue(thrown.message!!.contains("TTS 引擎未就绪"))
    }

    @Test
    fun videoStatusParsesSucceededUrl() = runTest {
        server.enqueue(
            MockResponse().setBody(STATUS_ENVELOPE("video", "succeeded", ""","url":"/api/v1/generation/files/task-video-1_0.mp4""""))
                .setHeader("Content-Type", "application/json"),
        )
        val status = newRepo().videoStatus("task-video-1")

        assertEquals("succeeded", status.status)
        assertEquals("/api/v1/generation/files/task-video-1_0.mp4", status.url)

        val recorded = server.takeRequest()
        assertEquals("/api/v1/generation/video/status/task-video-1", recorded.path)
        assertEquals("Bearer jwt-test", recorded.getHeader("Authorization"))
    }

    @Test
    fun musicStatusParsesFailedWithError() = runTest {
        server.enqueue(
            MockResponse().setBody(STATUS_ENVELOPE("music", "failed", ""","error":"model runtime crashed""""))
                .setHeader("Content-Type", "application/json"),
        )
        val status = newRepo().musicStatus("task-music-1")

        assertEquals("failed", status.status)
        assertTrue(status.error.contains("model runtime crashed"))
    }

    @Test
    fun pollUntilDoneReturnsOnSucceeded() = runTest {
        server.enqueue(MockResponse().setBody(STATUS_ENVELOPE("video", "running", "")).setHeader("Content-Type", "application/json"))
        server.enqueue(MockResponse().setBody(STATUS_ENVELOPE("video", "running", "")).setHeader("Content-Type", "application/json"))
        server.enqueue(
            MockResponse().setBody(STATUS_ENVELOPE("video", "succeeded", ""","url":"/api/v1/generation/files/v.mp4""""))
                .setHeader("Content-Type", "application/json"),
        )
        var polls = 0
        val done = newRepo().pollUntilDone(AigcKind.VIDEO, "task-video-1", sleep = { polls++ })

        assertEquals("succeeded", done.status)
        assertEquals("/api/v1/generation/files/v.mp4", done.url)
        assertEquals(2, polls) // 前两次非终态各 sleep 一次
        assertEquals(3, server.requestCount)
    }

    @Test
    fun pollUntilDoneThrowsOnFailedWithError() {
        server.enqueue(
            MockResponse().setBody(STATUS_ENVELOPE("music", "failed", ""","error":"上游 402 余额不足""""))
                .setHeader("Content-Type", "application/json"),
        )
        val repo = newRepo()
        val thrown = assertThrows(GenerationTaskFailed::class.java) {
            runBlocking { repo.pollUntilDone(AigcKind.MUSIC, "task-music-1", sleep = { }) }
        }
        assertTrue(thrown.message!!.contains("上游 402 余额不足"))
    }

    @Test
    fun pollUntilDoneTimesOutHonestly() {
        server.enqueue(MockResponse().setBody(STATUS_ENVELOPE("music", "running", "")).setHeader("Content-Type", "application/json"))
        server.enqueue(MockResponse().setBody(STATUS_ENVELOPE("music", "running", "")).setHeader("Content-Type", "application/json"))
        val repo = newRepo()
        val thrown = assertThrows(GenerationTaskTimeout::class.java) {
            runBlocking { repo.pollUntilDone(AigcKind.MUSIC, "task-music-1", maxAttempts = 2, sleep = { }) }
        }
        assertTrue(thrown.message!!.contains("超时"))
        assertTrue(thrown.message!!.contains("running"))
    }

    @Test
    fun pollUntilDoneRejectsSyncKinds() {
        val repo = newRepo()
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { repo.pollUntilDone(AigcKind.IMAGE, "t", sleep = { }) }
        }
    }

    @Test
    fun resolveMediaUrlAppendsTokenOnlyForSameOriginRelative() {
        // 同源相对路径 → 补 baseUrl + access_token
        val relative = resolveMediaUrl("http://10.0.2.2:9527", "/api/v1/generation/files/a.mp4", "jwt-1")
        assertEquals("http://10.0.2.2:9527/api/v1/generation/files/a.mp4?access_token=jwt-1", relative)
        // 已带 query 的 url 用 & 追加
        val withQuery = resolveMediaUrl("http://10.0.2.2:9527/", "/api/v1/generation/files/a.mp4?x=1", "jwt-1")
        assertEquals("http://10.0.2.2:9527/api/v1/generation/files/a.mp4?x=1&access_token=jwt-1", withQuery)
        // 远程绝对 url 原样返回——不把本站 JWT 带去第三方 CDN
        val remote = resolveMediaUrl("http://10.0.2.2:9527", "https://cdn.fal.ai/out.mp3", "jwt-1")
        assertEquals("https://cdn.fal.ai/out.mp3", remote)
        // 空 url → 空串
        assertEquals("", resolveMediaUrl("http://10.0.2.2:9527", "", "jwt-1"))
    }

    @Test
    fun fetchMediaBytesStripsApiPrefixAndReturnsBytes() = runTest {
        server.enqueue(MockResponse().setBody("PNGDATA"))
        val bytes = newRepo().fetchMediaBytes("/api/v1/generation/files/a.png")

        assertTrue(String(bytes).contains("PNGDATA"))
        val recorded = server.takeRequest()
        // HttpChannel 的 apiBase 已含 /api/v1，仓库层须剥去前缀避免重复拼接
        assertEquals("/api/v1/generation/files/a.png", recorded.path)
        assertEquals("Bearer jwt-test", recorded.getHeader("Authorization"))
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
        private val IMAGE_ENVELOPE = """
            {"code":0,"message":"success","data":{
              "task_id":"task-img-1",
              "images":[
                {"url":"/api/v1/generation/files/task-img-1_0.png","path":"/data/generations/task-img-1_0.png"},
                {"url":"","error":"单图下载失败: timeout"}],
              "ignored_params":"seed"}}
        """.trimIndent()

        private val VIDEO_SUBMIT_ENVELOPE = """
            {"code":0,"message":"success","data":{"task_id":"task-video-1","status":"submitted","protocol":"wan"}}
        """.trimIndent()

        private val MUSIC_SUBMIT_ENVELOPE = """
            {"code":0,"message":"success","data":{"task_id":"task-music-1","status":"submitted","protocol":"fal"}}
        """.trimIndent()

        private val AUDIO_SUCCESS_ENVELOPE = """
            {"code":0,"message":"success","data":{"url":"/api/v1/generation/files/task-audio-1_0.wav",
             "path":"/data/generations/task-audio-1_0.wav","task_id":"task-audio-1","request_id":"req-1"}}
        """.trimIndent()

        private val AUDIO_FAILURE_ENVELOPE = """
            {"code":-1,"message":"TTS 引擎未就绪","data":{"request_id":"req-2"}}
        """.trimIndent()

        private fun STATUS_ENVELOPE(kind: String, status: String, extraJson: String): String =
            """{"code":0,"message":"success","data":{"task_id":"task-$kind-1","status":"$status"$extraJson}}"""
    }
}
