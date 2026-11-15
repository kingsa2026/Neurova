package top.neurova.mobile.core.protocol

/**
 * 移动 WS 关闭码决策（手机客户端设计方案 §5.3 真竞态口径，与鸿蒙 WebSocketAdapter 同规）：
 * - manual 关闭恒为终态（TERMINAL_CLOSED），任何关闭码不得把它覆盖成重连；
 * - 4001（ticket 失效）→ 未续签过则续签重试一次；续签后再被拒 = 设备已解除，终态 failed；
 * - 4008（单用户连接超限）→ 不重连；
 * - 其余（传输层断流 1006 等）→ 预算内指数退避重连，预算耗尽放弃。
 */
object MobileWsClosePolicy {

    enum class Decision { REFRESH_AND_RETRY, TERMINAL_FAILED, GIVE_UP, TERMINAL_CLOSED, RECONNECT }

    const val MAX_RECONNECT = 10

    fun decide(
        closeCode: Int,
        refreshAlreadyTried: Boolean,
        manualClose: Boolean,
        reconnectCount: Int = 0,
    ): Decision = when {
        manualClose -> Decision.TERMINAL_CLOSED
        closeCode == CLOSE_DEVICE_TICKET_INVALID ->
            if (refreshAlreadyTried) Decision.TERMINAL_FAILED else Decision.REFRESH_AND_RETRY
        closeCode == CLOSE_USER_CONNECTION_LIMIT -> Decision.GIVE_UP
        reconnectCount >= MAX_RECONNECT -> Decision.GIVE_UP
        else -> Decision.RECONNECT
    }

    private const val CLOSE_DEVICE_TICKET_INVALID = 4001
    private const val CLOSE_USER_CONNECTION_LIMIT = 4008
}
