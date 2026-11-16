package top.neurova.mobile.feature.chat

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import top.neurova.mobile.core.model.ChatMessage
import top.neurova.mobile.core.net.MobileWsChannel
import top.neurova.mobile.core.protocol.ChunkBatcher
import top.neurova.mobile.feature.pairing.PairingStore

/**
 * 对话域控制器（F5 聊天页的单一状态源，鸿蒙 ChatPage 同源语义）：
 * - 历史回放来自 REST（ChatRepository，与 PC 同一份记录）；
 * - 流式事件走配对 WS 通道（chat:send 下发，chat:chunk/done/cancelled/error 回达）；
 * - chunk 按 60ms 时间窗批量落 UI（ChunkBatcher），避免逐 token 重渲染。
 * 单例挂在 AppRuntime——跨屏（列表/聊天/抽屉）共享同一连接与在流状态。
 */
class ChatSessionController(
    private val scope: kotlinx.coroutines.CoroutineScope,
    private val ws: MobileWsChannel,
    private val pairing: PairingStore,
    private val repository: ChatRepository,
) {

    var sessionId by mutableStateOf("")
        private set
    var sessionTitle by mutableStateOf("")
        private set
    var agentId by mutableStateOf("")
        private set
    var messages by mutableStateOf<List<ChatMessage>>(emptyList())
        private set
    var isGenerating by mutableStateOf(false)
        private set
    var sendError by mutableStateOf<String?>(null)
        private set
    var historyLoading by mutableStateOf(false)
        private set

    /** 排队位（ledger queued）；null=不在排队 */
    var queuePosition by mutableStateOf<Int?>(null)
        private set

    /** 排队/让位原因（让位闸 onWait 的 reason） */
    var queueReason by mutableStateOf<String?>(null)
        private set

    /** 思考流片段（管线 reasoning 事件；内容开始后清空） */
    var reasoningSnippet by mutableStateOf<String?>(null)
        private set

    /** 本轮已接收的流式分段数（生成中进度读数） */
    var chunkCount by mutableStateOf(0)
        private set

    private val batcher = ChunkBatcher()
    private var eventsJob: Job? = null
    private var collecting = false

    /** 进会话：切会话即重置流状态，回放历史，开始收集 WS 事件 */
    suspend fun enter(targetSessionId: String, title: String = "", fallbackAgentId: String? = null) {
        if (sessionId != targetSessionId) {
            batcher.reset()
            isGenerating = false
            sendError = null
            queuePosition = null
            queueReason = null
            reasoningSnippet = null
            chunkCount = 0
        }
        sessionId = targetSessionId
        if (title.isNotBlank()) sessionTitle = title
        agentId = fallbackAgentId.orEmpty()
        startEventCollection()
        historyLoading = true
        runCatching { repository.history(targetSessionId) }
            .onSuccess { loaded ->
                // 流式回合若先到，历史不覆盖在流消息
                if (!isGenerating) messages = loaded
            }
            .onFailure { sendError = it.message ?: "历史加载失败" }
        historyLoading = false
    }

    fun leave() {
        batcher.reset()
        isGenerating = false
    }

    /** 发送：先落 user + assistant 占位，WS 就绪后下发 chat:send */
    fun send(text: String) {
        val content = text.trim()
        if (content.isEmpty() || isGenerating) return
        val stamp = System.currentTimeMillis()
        messages = messages + ChatMessage(id = "u-$stamp", role = "user", content = content)
        messages = messages + ChatMessage(id = "a-$stamp", role = "assistant", content = "", status = "streaming")
        isGenerating = true
        sendError = null
        queuePosition = null
        queueReason = null
        reasoningSnippet = null
        chunkCount = 0
        scope.launch {
            runCatching { ensureConnected() }
                .onFailure { failure ->
                    markStreamingFailure(failure.message ?: "连接失败")
                    return@launch
                }
            if (!ws.sendChat(content, sessionId, agentId.ifBlank { "default" })) {
                markStreamingFailure("通道未就绪，请稍后重试")
            }
        }
    }

    /** 停止生成：下发 chat:cancel，服务端回 chat:cancelled 收尾 */
    fun cancel() {
        if (sessionId.isNotEmpty()) ws.cancelChat(sessionId)
    }

    /** F5 头部切换 Agent：后续 chat:send 使用新 agent_id（会话已存记录的归属不改写） */
    fun useAgent(agentId: String) {
        if (agentId.isNotBlank()) this.agentId = agentId
    }

    /**
     * 确保配对 WS 通道就绪：ticket 仅内存，连接前自动续签（§5.3）。
     * 已在连/重连中则直接等待其收敛。
     */
    private suspend fun ensureConnected() {
        when (ws.state.value) {
            MobileWsChannel.State.AUTHED -> return
            MobileWsChannel.State.CONNECTING,
            MobileWsChannel.State.RECONNECTING,
            MobileWsChannel.State.REAUTHING,
            -> { awaitAuthedOrFail(); return }
            else -> {}
        }
        if (pairing.ticket.isBlank()) pairing.refreshTicket()
        ws.connect()
        awaitAuthedOrFail()
    }

    private suspend fun awaitAuthedOrFail() {
        val deadline = System.currentTimeMillis() + READY_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            when (ws.state.value) {
                MobileWsChannel.State.AUTHED -> return
                MobileWsChannel.State.FAILED, MobileWsChannel.State.CLOSED -> break
                else -> delay(100)
            }
        }
        if (ws.state.value != MobileWsChannel.State.AUTHED) {
            throw IllegalStateException("WS 通道未就绪（${ws.state.value}）")
        }
    }

    private fun startEventCollection() {
        if (collecting) return
        collecting = true
        eventsJob = scope.launch {
            ws.events.collect { event ->
                when (event) {
                    is MobileWsChannel.Event.Chunk -> if (event.sessionId == sessionId) {
                        batcher.push(event.content)
                        chunkCount += 1
                        reasoningSnippet = null
                        if (batcher.shouldFlush(System.currentTimeMillis())) applyBatchedFlush()
                    }
                    is MobileWsChannel.Event.Done -> if (event.sessionId == sessionId) {
                        finishStreaming(status = "done")
                    }
                    is MobileWsChannel.Event.Cancelled -> if (event.sessionId == sessionId) {
                        finishStreaming(status = "cancelled")
                    }
                    is MobileWsChannel.Event.Error -> {
                        batcher.reset()
                        isGenerating = false
                        sendError = event.message.ifBlank { event.code }
                        queuePosition = null
                        queueReason = null
                        reasoningSnippet = null
                        markLastAssistant("error")
                    }
                    is MobileWsChannel.Event.AgentSwitched -> {
                        // Agent 切换属 F7/F5 头部联动，P6 接线
                    }
                    is MobileWsChannel.Event.Queued -> if (event.sessionId == sessionId) {
                        queuePosition = event.position ?: queuePosition
                        queueReason = event.reason ?: queueReason
                    }
                    is MobileWsChannel.Event.Reasoning -> if (event.sessionId == sessionId) {
                        reasoningSnippet = event.content.ifBlank { reasoningSnippet }
                    }
                }
            }
        }
    }

    /** 60ms 窗：把缓冲追加到最后一条 assistant 消息 */
    private fun applyBatchedFlush() {
        val chunk = batcher.flush(System.currentTimeMillis())
        appendToLastAssistant(chunk)
    }

    private fun finishStreaming(status: String) {
        val rest = batcher.forceFlush()
        if (rest.isNotEmpty()) appendToLastAssistant(rest)
        markLastAssistant(status)
        isGenerating = false
        queuePosition = null
        queueReason = null
        reasoningSnippet = null
    }

    private fun appendToLastAssistant(chunk: String) {
        if (chunk.isEmpty()) return
        val list = messages.toMutableList()
        val index = list.indexOfLast { it.role == "assistant" && it.status == "streaming" }
        if (index < 0) return
        list[index] = list[index].copy(content = list[index].content + chunk)
        messages = list
    }

    private fun markLastAssistant(status: String) {
        val list = messages.toMutableList()
        val index = list.indexOfLast { it.role == "assistant" && it.status == "streaming" }
        if (index < 0) return
        list[index] = list[index].copy(status = status)
        messages = list
    }

    private fun markStreamingFailure(reason: String) {
        batcher.reset()
        isGenerating = false
        sendError = reason
        queuePosition = null
        queueReason = null
        reasoningSnippet = null
        markLastAssistant("error")
    }

    private companion object {
        const val READY_TIMEOUT_MS = 8_000L
    }
}
