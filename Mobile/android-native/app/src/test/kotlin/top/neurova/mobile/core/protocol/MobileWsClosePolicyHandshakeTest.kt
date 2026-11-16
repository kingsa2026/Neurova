package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 握手被 HTTP 状态拒绝的分类（2026-11-16 实机实证的断链）：
 * ticket 一次性消费后，掉线重连复用旧票会被服务端在**升级前**以 HTTP 403 拒绝——
 * OkHttp 走 onFailure（无 close 帧），旧逻辑误判 1006 普通重连，永不续签直至 FAILED。
 * 401/403 必须映射 4001 语义（续签重试一次），其余状态/无响应仍走 1006。
 */
class MobileWsClosePolicyHandshakeTest {

    @Test
    fun consumedTicketRejectionMapsToRefreshPath() {
        val code = MobileWsClosePolicy.closeCodeForHandshakeRejection(403)
        assertEquals(4001, code)
        assertEquals(
            MobileWsClosePolicy.Decision.REFRESH_AND_RETRY,
            MobileWsClosePolicy.decide(code!!, refreshAlreadyTried = false, manualClose = false),
        )
    }

    @Test
    fun unauthorizedMapsToRefreshPathToo() {
        assertEquals(4001, MobileWsClosePolicy.closeCodeForHandshakeRejection(401))
    }

    @Test
    fun serverErrorsAndMissingResponseStayOnTransportPath() {
        assertNull(MobileWsClosePolicy.closeCodeForHandshakeRejection(502))
        assertNull(MobileWsClosePolicy.closeCodeForHandshakeRejection(null))
    }
}
