package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 配对三口（resolve/confirm/refresh）线上契约测试——样本取自后端
 * `neurova/api/endpoints/mobile_pairing.py` 的真实响应形状（蛇形命名）。
 *
 * 红灯（2026-11-16 模拟器 E2E 实证）：confirm 实际成功、设备已在服务端登记，
 * 但客户端按 `ws_token` 解码必填字段——后端回的是 `connect_ticket`，
 * MissingFieldException 被 UI 兜成误导性的「配对不可达」。
 */
class PairingWireTest {

    private fun decodeConfirmed(raw: String): ConfirmedWire = pairingJson.decodeFromString(raw)

    @Test
    fun confirmWireDecodesRealBackendPayload() {
        val payload = """
            {"success":true,"connect_ticket":"ticket-abc","ws_url":"ws://10.0.2.2:9527/api/v1/mobile/ws",
             "device_secret":"sec-xyz","pairing_id":"pair-0a8ce1afde5b","message":"配对成功","expires_in":60}
        """.trimIndent()
        val wire = decodeConfirmed(payload)
        assertEquals("ticket-abc", wire.connectTicket)
        assertEquals("sec-xyz", wire.deviceSecret)
        assertEquals("pair-0a8ce1afde5b", wire.pairingId)
        assertEquals("ws://10.0.2.2:9527/api/v1/mobile/ws", wire.wsUrl)
        assertEquals(60, wire.expiresIn)
    }

    @Test
    fun resolveWireDecodesRealBackendPayload() {
        val payload = """
            {"ws_url":"ws://10.0.2.2:9527/api/v1/mobile/ws","pairing_id":"pair-1",
             "expires_in":240,"status":"scanned"}
        """.trimIndent()
        val wire = pairingJson.decodeFromString<ResolvedWire>(payload)
        assertEquals("pair-1", wire.pairingId)
        assertEquals("scanned", wire.status)
        assertEquals(240, wire.expiresIn)
    }

    @Test
    fun refreshWireDecodesRealBackendPayload() {
        val payload = """
            {"connect_ticket":"ticket-refresh","pairing_id":"pair-1","expires_in":60}
        """.trimIndent()
        val wire = pairingJson.decodeFromString<RefreshedWire>(payload)
        assertEquals("ticket-refresh", wire.connectTicket)
        assertEquals("pair-1", wire.pairingId)
    }

    @Test
    fun sixDigitInputRoutesToCodePath() {
        assertEquals(PairingInput.Code("845973"), parsePairingInput("845973"))
        assertEquals(PairingInput.Code("845973"), parsePairingInput("  845973  "))
    }

    @Test
    fun refInputRoutesToRefPath() {
        assertEquals(
            PairingInput.Ref("CbdmFw5vbiaB9Fi8iDamXJ"),
            parsePairingInput("CbdmFw5vbiaB9Fi8iDamXJ"),
        )
    }

    @Test
    fun blankInputIsRejected() {
        assertNull(parsePairingInput(""))
        assertNull(parsePairingInput("   "))
    }

    @Test
    fun sixDigitsWithStrayLetterIsNotACode() {
        // 键盘误触混入字母后不得再按配对码口发送（E2E 中真实发生过的形态）
        assertEquals(PairingInput.Ref("964291y"), parsePairingInput("964291y"))
    }
}
