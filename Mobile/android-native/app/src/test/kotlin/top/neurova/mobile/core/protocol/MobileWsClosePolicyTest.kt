package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 移动 WS 关闭码决策契约（手机客户端设计方案 §5.3 真竞态口径）：
 * 4001 → 先续签重试一次；续签再被拒（设备已解除）→ 终态 failed(device_deregistered)；
 * 4008（单用户连接超限）→ 不重连；closed(manual) 恒为终态，不得被 reconnecting 覆盖；
 * 传输层断流（1006 等）→ 预算内 RECONNECT，预算耗尽 GIVE_UP。
 * 红灯：MobileWsClosePolicy 尚未实现（桩恒返 null）。
 */
class MobileWsClosePolicyTest {

    @Test
    fun code4001AsksForRefreshRetry() {
        assertEquals(
            MobileWsClosePolicy.Decision.REFRESH_AND_RETRY,
            MobileWsClosePolicy.decide(4001, refreshAlreadyTried = false, manualClose = false),
        )
    }

    @Test
    fun code4001AfterRefreshRetryIsTerminalDeregistered() {
        assertEquals(
            MobileWsClosePolicy.Decision.TERMINAL_FAILED,
            MobileWsClosePolicy.decide(4001, refreshAlreadyTried = true, manualClose = false),
        )
    }

    @Test
    fun code4008NeverReconnects() {
        assertEquals(
            MobileWsClosePolicy.Decision.GIVE_UP,
            MobileWsClosePolicy.decide(4008, refreshAlreadyTried = false, manualClose = false),
        )
    }

    @Test
    fun manualCloseIsAlwaysTerminalAndCannotBeOverridden() {
        assertEquals(
            MobileWsClosePolicy.Decision.TERMINAL_CLOSED,
            MobileWsClosePolicy.decide(1000, refreshAlreadyTried = false, manualClose = true),
        )
        assertEquals(
            MobileWsClosePolicy.Decision.TERMINAL_CLOSED,
            MobileWsClosePolicy.decide(4001, refreshAlreadyTried = false, manualClose = true),
        )
    }

    @Test
    fun transportLossWithRetryBudgetLeftReconnects() {
        assertEquals(
            MobileWsClosePolicy.Decision.RECONNECT,
            MobileWsClosePolicy.decide(1006, refreshAlreadyTried = false, manualClose = false, reconnectCount = 0),
        )
    }

    @Test
    fun transportLossBeyondBudgetGivesUp() {
        assertEquals(
            MobileWsClosePolicy.Decision.GIVE_UP,
            MobileWsClosePolicy.decide(1006, refreshAlreadyTried = false, manualClose = false, reconnectCount = 10),
        )
    }
}
