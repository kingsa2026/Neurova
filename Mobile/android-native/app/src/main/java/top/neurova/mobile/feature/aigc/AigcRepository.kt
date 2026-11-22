package top.neurova.mobile.feature.aigc

import java.net.URLEncoder
import kotlinx.coroutines.delay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import top.neurova.mobile.core.net.HttpChannel

/**
 * AIGC 生成仓库（neurova/api/endpoints/generation.py 事实源，Bearer JWT 走 HttpChannel）：
 *   POST /generation/image|video|audio|music         提交（image/audio 同步回产物；video/music 异步两段式）
 *   GET  /generation/video/status/{id}·music/status  异步任务轮询（submitted/running/succeeded/failed）
 * 产物 url 形如相对路径 /api/v1/generation/files/...；媒体标签播放走 ?access_token=
 * （后端为 <img>/<video>/<audio> 开的凭证通道），同源二进制拉取走 Bearer。
 */
class AigcRepository(private val http: HttpChannel) {

    private val json = Json { ignoreUnknownKeys = true }

    /** 图像生成（model 缺省由服务端按能力路由；显式 width/height/num_images） */
    suspend fun submitImage(prompt: String, width: Int, height: Int, numImages: Int = 1): ImageGenerationResult {
        val data = http.unwrapData(
            http.postJson(
                "/generation/image",
                JsonObject(
                    mapOf(
                        "prompt" to JsonPrimitive(prompt),
                        "width" to JsonPrimitive(width),
                        "height" to JsonPrimitive(height),
                        "num_images" to JsonPrimitive(numImages),
                    ),
                ),
            ),
        )
        return json.decodeFromJsonElement(ImageGenerationResult.serializer(), data)
    }

    /** 音频生成（TTS）。失败契约特殊：HTTP 200 + code=-1 + message，必须显式判 code，不可当成功解包 */
    suspend fun submitAudio(text: String, voice: String, speed: Double): AudioGenerationResult {
        val raw = http.postJson(
            "/generation/audio",
            JsonObject(
                mapOf(
                    "text" to JsonPrimitive(text),
                    "voice" to JsonPrimitive(voice),
                    "speed" to JsonPrimitive(speed),
                ),
            ),
        )
        val obj = raw as? JsonObject
        val code = (obj?.get("code") as? JsonPrimitive)?.intOrNull ?: 0
        if (code != 0) {
            val message = (obj?.get("message") as? JsonPrimitive)?.content ?: "音频生成失败"
            throw GenerationSubmitFailed(message)
        }
        return json.decodeFromJsonElement(AudioGenerationResult.serializer(), http.unwrapData(raw))
    }

    /** 视频生成提交（wan/seedance2/veo 异步协议，服务端落任务账本） */
    suspend fun submitVideo(prompt: String, durationSeconds: Int, resolution: String): GenerationTaskSubmitted =
        submitAsyncTask(
            "/generation/video",
            JsonObject(
                mapOf(
                    "prompt" to JsonPrimitive(prompt),
                    "duration" to JsonPrimitive(durationSeconds),
                    "resolution" to JsonPrimitive(resolution),
                ),
            ),
        )

    /** 音乐生成提交（fal Queue 异步协议） */
    suspend fun submitMusic(prompt: String, durationSeconds: Int): GenerationTaskSubmitted =
        submitAsyncTask(
            "/generation/music",
            JsonObject(
                mapOf(
                    "prompt" to JsonPrimitive(prompt),
                    "duration" to JsonPrimitive(durationSeconds),
                ),
            ),
        )

    suspend fun videoStatus(taskId: String): GenerationTaskStatus =
        taskStatus("/generation/video/status/$taskId")

    suspend fun musicStatus(taskId: String): GenerationTaskStatus =
        taskStatus("/generation/music/status/$taskId")

    /**
     * 轮询至终态：succeeded 返回带 url 的状态；failed 诚实抛 GenerationTaskFailed；
     * 达到 maxAttempts 仍未终态抛 GenerationTaskTimeout。sleep 可注入（测试免真等）。
     */
    suspend fun pollUntilDone(
        kind: AigcKind,
        taskId: String,
        intervalMs: Long = POLL_INTERVAL_MS,
        maxAttempts: Int = MAX_POLL_ATTEMPTS,
        onPoll: (GenerationTaskStatus) -> Unit = {},
        sleep: suspend (Long) -> Unit = { delay(it) },
    ): GenerationTaskStatus {
        require(kind == AigcKind.VIDEO || kind == AigcKind.MUSIC) { "同步类型「${kind.label}」无需轮询" }
        var lastStatus = ""
        for (attempt in 0 until maxAttempts) {
            val status = if (kind == AigcKind.VIDEO) videoStatus(taskId) else musicStatus(taskId)
            lastStatus = status.status
            when (status.status) {
                STATUS_SUCCEEDED -> return status
                STATUS_FAILED -> throw GenerationTaskFailed(status.error.ifBlank { "生成任务失败（服务端未给出原因）" })
            }
            onPoll(status)
            if (attempt < maxAttempts - 1) sleep(intervalMs)
        }
        throw GenerationTaskTimeout("生成超时：轮询 $maxAttempts 次后仍为「$lastStatus」，任务可能仍在后台进行")
    }

    /** 同源产物二进制（Bearer 鉴权走 HttpChannel；图像预览解码用）。入参为端点原样相对 url */
    suspend fun fetchMediaBytes(relativeUrl: String): ByteArray =
        http.getBytes(relativeUrl.trim().removePrefix(API_PREFIX))

    private suspend fun submitAsyncTask(path: String, body: JsonObject): GenerationTaskSubmitted {
        val data = http.unwrapData(http.postJson(path, body))
        return json.decodeFromJsonElement(GenerationTaskSubmitted.serializer(), data)
    }

    private suspend fun taskStatus(path: String): GenerationTaskStatus {
        val data = http.unwrapData(http.getJson(path))
        return json.decodeFromJsonElement(GenerationTaskStatus.serializer(), data)
    }

    companion object {
        /** 轮询节奏 3s；上限 200 次 ≈ 10 分钟（视频类生成常规上限，超时诚实上报不静默） */
        const val POLL_INTERVAL_MS = 3000L
        const val MAX_POLL_ATTEMPTS = 200
        private const val API_PREFIX = "/api/v1"
        private const val STATUS_SUCCEEDED = "succeeded"
        private const val STATUS_FAILED = "failed"
    }
}

/**
 * 产物 url → 可访问绝对地址（顶层纯函数，链接行/播放器共用）。
 * 仅同源相对路径追加 access_token（后端媒体标签凭证通道）；
 * 远程绝对 url 原样返回——不把本站 JWT 带去第三方 CDN。
 */
fun resolveMediaUrl(baseUrl: String, url: String, accessToken: String): String {
    val trimmed = url.trim()
    if (trimmed.isEmpty()) return ""
    if (!trimmed.startsWith("/")) return trimmed
    val absolute = baseUrl.trimEnd('/') + trimmed
    if (accessToken.isBlank()) return absolute
    val separator = if (absolute.contains('?')) "&" else "?"
    return absolute + separator + "access_token=" + URLEncoder.encode(accessToken, "UTF-8")
}
