package top.neurova.mobile.feature.aigc

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** AIGC 生成类型（与 generation 端点族 kind 口径一致；image/audio 同步回产物，video/music 两段式轮询） */
enum class AigcKind(val label: String, val apiKind: String) {
    IMAGE("图像", "image"),
    VIDEO("视频", "video"),
    AUDIO("音频", "audio"),
    MUSIC("音乐", "music"),
}

/** POST /generation/image 响应 data（generation.py 图像成功契约：images + task_id） */
@Serializable
data class ImageGenerationResult(
    @SerialName("task_id") val taskId: String = "",
    val images: List<GeneratedImage> = emptyList(),
    @SerialName("ignored_params") val ignoredParams: String = "",
)

/** images 元素：单图产物 url/path；单图下载失败的项只带 error（诚实呈现，不伪造空 url 可用） */
@Serializable
data class GeneratedImage(
    val url: String = "",
    val path: String = "",
    val error: String = "",
)

/** POST /generation/audio 响应 data（TTS 合成落盘 url） */
@Serializable
data class AudioGenerationResult(
    val url: String = "",
    val path: String = "",
    @SerialName("task_id") val taskId: String = "",
)

/** POST /generation/video|music 提交响应 data（两段式：先拿 task_id，再轮询 status） */
@Serializable
data class GenerationTaskSubmitted(
    @SerialName("task_id") val taskId: String = "",
    val status: String = "",
    val protocol: String = "",
)

/** GET /generation/video|music/status/{id} 响应 data（url/error/warning 仅非空时下发，缺省兜空） */
@Serializable
data class GenerationTaskStatus(
    @SerialName("task_id") val taskId: String = "",
    val status: String = "",
    val url: String = "",
    val error: String = "",
    val warning: String = "",
)

/** 音频 code=-1 等业务失败（HTTP 200 但非成功契约）——诚实抛出，页面原样显示 */
class GenerationSubmitFailed(message: String) : RuntimeException(message)

/** 轮询到 failed 终态：带服务端 error 原文 */
class GenerationTaskFailed(message: String) : RuntimeException(message)

/** 轮询达到上限仍未终态：任务可能仍在后台进行，不伪造失败/成功 */
class GenerationTaskTimeout(message: String) : RuntimeException(message)
