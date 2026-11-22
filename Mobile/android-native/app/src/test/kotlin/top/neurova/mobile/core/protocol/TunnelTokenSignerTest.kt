package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * nv1 准入令牌信封对拍（U9/U16）：期望值由后端单源
 * `neurova/tunnel/protocol.py::signTunnelToken` 生成（固定 issuedAt/nonce 消除随机性），
 * Kotlin 侧 `TunnelTokenSigner` 必须逐字节产出同一信封——两端 HMAC 口径一致才算接通。
 *
 * python 侧生成命令（本仓根目录）：
 * ```python
 * from neurova.tunnel.protocol import signTunnelToken
 * signTunnelToken('nv-relay-secret-1', 'agent', issuedAt=1700000000, nonce='aabbccddeeff0011')
 * # -> nv1:agent:1700000000:aabbccddeeff0011:84a2c7885e6d5781a893f8264f4b53e54c582da72c8e156342a4c8b41ee0f19a
 * ```
 */
class TunnelTokenSignerTest {

    @Test
    fun signMatchesPythonSignTunnelTokenAgentCase1() {
        val token = TunnelTokenSigner.signTunnelToken(
            secret = "nv-relay-secret-1",
            tokenType = TunnelTokenSigner.TYPE_AGENT,
            issuedAtSeconds = 1_700_000_000L,
            nonce = "aabbccddeeff0011",
        )
        assertEquals(
            "nv1:agent:1700000000:aabbccddeeff0011:" +
                "84a2c7885e6d5781a893f8264f4b53e54c582da72c8e156342a4c8b41ee0f19a",
            token,
        )
    }

    @Test
    fun signMatchesPythonSignTunnelTokenAgentCase2() {
        val token = TunnelTokenSigner.signTunnelToken(
            secret = "another-key-42",
            tokenType = TunnelTokenSigner.TYPE_AGENT,
            issuedAtSeconds = 1_600_000_000L,
            nonce = "0123456789abcdef",
        )
        assertEquals(
            "nv1:agent:1600000000:0123456789abcdef:" +
                "e07db0ccabf2921e0551857a1e8411172ff34973bfa5c368455a944223a76e32",
            token,
        )
    }

    @Test
    fun signMatchesPythonSignTunnelTokenServiceCase() {
        val token = TunnelTokenSigner.signTunnelToken(
            secret = "nv-relay-secret-1",
            tokenType = TunnelTokenSigner.TYPE_SERVICE,
            issuedAtSeconds = 1_700_000_000L,
            nonce = "aabbccddeeff0011",
        )
        assertEquals(
            "nv1:service:1700000000:aabbccddeeff0011:" +
                "c0d9cd6187ce29e56895d7dffb82226a05fbf0b0d9c31bad4df989fadc4746dd",
            token,
        )
    }

    @Test
    fun defaultNonceIsSixteenHexCharsLikePythonTokenHex8() {
        val token = TunnelTokenSigner.signTunnelToken("s", issuedAtSeconds = 1L)
        val parts = token.split(":")
        assertEquals(5, parts.size)
        assertEquals("agent", parts[1])
        assertEquals("1", parts[2])
        assertTrue(
            "nonce 须为 16 位十六进制（secrets.token_hex(8) 同形）: ${parts[3]}",
            parts[3].length == 16 && parts[3].all { it.isDigit() || it in 'a'..'f' },
        )
    }

    @Test
    fun envelopeDetection() {
        assertTrue(TunnelTokenSigner.isEnveloped("nv1:agent:1:aa:bb"))
        assertFalse(TunnelTokenSigner.isEnveloped("raw-secret"))
        assertFalse(TunnelTokenSigner.isEnveloped(""))
        assertFalse(TunnelTokenSigner.isEnveloped(null))
    }

    @Test(expected = IllegalArgumentException::class)
    fun blankSecretRejected() {
        TunnelTokenSigner.signTunnelToken("", issuedAtSeconds = 1L)
    }

    @Test(expected = IllegalArgumentException::class)
    fun unknownTypeRejected() {
        TunnelTokenSigner.signTunnelToken("s", tokenType = "root", issuedAtSeconds = 1L)
    }
}
