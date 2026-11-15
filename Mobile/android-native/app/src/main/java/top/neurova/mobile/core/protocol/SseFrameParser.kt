package top.neurova.mobile.core.protocol

/**
 * SSE 文本帧解析（契约事实源：neurova/api/endpoints/chat.py 事件流）：
 * - 空行分帧；event:/data: 成对；仅 data 行时事件名回落 message；
 * - ": ping" 注释心跳行忽略（chat.py 15s 心跳）；
 * - CRLF/LF 均容；data 行剥一个前导空格，多行 data 以 \n 连接；
 * - 尾部无空行的残帧不产出，留在 carry 待下次喂入。
 */
class SseFrameParser {

    data class SseFrame(val event: String, val data: String)

    private var carry = ""

    /** 增量喂入：返回本次完整帧，尾部残帧留待下次 */
    fun feed(chunk: String): List<SseFrame> {
        if (chunk.isNotEmpty()) carry += chunk
        val segments = carry.split(FRAME_DELIMITER)
        carry = segments.last()
        return segments.dropLast(1).mapNotNull(::frameOf)
    }

    private fun frameOf(frameText: String): SseFrame? {
        var event = ""
        val dataLines = mutableListOf<String>()
        for (rawLine in frameText.lines()) {
            val line = rawLine.trimEnd('\r')
            when {
                line.startsWith(":") -> Unit // 注释/心跳行（": ping"）
                line.startsWith("event:") -> event = line.substring(EVENT_PREFIX.length).removePrefix(" ").trim()
                line.startsWith("data:") -> dataLines.add(line.substring(DATA_PREFIX.length).removePrefix(" "))
            }
        }
        if (dataLines.isEmpty()) return null
        return SseFrame(event.ifBlank { DEFAULT_EVENT }, dataLines.joinToString("\n"))
    }

    companion object {
        private val FRAME_DELIMITER = Regex("\r?\n\r?\n")
        private const val EVENT_PREFIX = "event:"
        private const val DATA_PREFIX = "data:"
        private const val DEFAULT_EVENT = "message"

        /** 一次性全文解析（语义与逐段 feed 等价：尾部残帧不产出） */
        fun parse(raw: String): List<SseFrame> = SseFrameParser().feed(raw)
    }
}
