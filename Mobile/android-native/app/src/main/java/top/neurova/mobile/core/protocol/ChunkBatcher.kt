package top.neurova.mobile.core.protocol

/**
 * 流式分块批处理器（M5.2.1 同源语义，鸿蒙 ChunkBatcher 移植）：
 * chat:chunk 每 token 一次直达 UI 会造成渲染风暴，按时间窗（默认 60ms）批量追加。
 * 纯逻辑无 Android 依赖，契约测试直接覆盖。
 */
class ChunkBatcher(private val windowMs: Long = DEFAULT_WINDOW_MS) {

    private val buffer = StringBuilder()
    private var lastFlushAt = 0L

    /** 累积一个分块（保持到达顺序） */
    fun push(content: String) {
        buffer.append(content)
    }

    /** 缓冲非空且距上次 flush 已过窗口 ⇒ 该批量落 UI 了 */
    fun shouldFlush(nowMs: Long): Boolean =
        buffer.isNotEmpty() && nowMs - lastFlushAt >= windowMs

    /** 取走累积内容并清空缓冲，同时记录窗口锚点 */
    fun flush(nowMs: Long): String {
        val out = buffer.toString()
        buffer.setLength(0)
        lastFlushAt = nowMs
        return out
    }

    /** 流终态（done/cancelled/error）强制取走剩余缓冲；不推进窗口锚点 */
    fun forceFlush(): String {
        val out = buffer.toString()
        buffer.setLength(0)
        return out
    }

    /** 会话切换/出错丢弃：清空缓冲与锚点 */
    fun reset() {
        buffer.setLength(0)
        lastFlushAt = 0L
    }

    companion object {
        const val DEFAULT_WINDOW_MS = 60L
    }
}
