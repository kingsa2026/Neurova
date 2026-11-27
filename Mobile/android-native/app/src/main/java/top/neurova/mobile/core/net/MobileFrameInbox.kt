package top.neurova.mobile.core.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive

/** 有界持久帧队列：先落盘再消费，消费后确认；满时拒绝新帧并触发重同步，不静默丢帧。 */
class MobileFrameInbox(
    private val capacity: Int = 128,
    private val load: () -> String = { "" },
    private val save: (String) -> Unit = {},
) {
    private val frames = ArrayDeque<String>()

    init {
        runCatching {
            (Json.parseToJsonElement(load()) as? JsonArray)
                ?.mapNotNull { it as? JsonPrimitive }
                ?.map { it.content }
                ?.takeLast(capacity)
                ?.let { frames.addAll(it) }
        }
    }

    @Synchronized
    fun enqueue(raw: String): Boolean {
        if (frames.size >= capacity) return false
        frames.addLast(raw)
        persist()
        return true
    }

    @Synchronized
    fun peek(): String? = frames.firstOrNull()

    @Synchronized
    fun ack() {
        if (frames.removeFirstOrNull() != null) persist()
    }

    @Synchronized
    fun clear() {
        frames.clear()
        persist()
    }

    private fun persist() {
        val encoded = JsonArray(frames.map { JsonPrimitive(it) }).toString()
        runCatching { save(encoded) }
    }
}
