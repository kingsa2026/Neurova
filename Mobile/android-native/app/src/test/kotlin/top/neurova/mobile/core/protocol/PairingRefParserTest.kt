package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 配对深链解析契约（两端同一事实源：neurova://pair?ref=…，《中继方案》§3.4）。
 * 红灯：PairingRefParser 尚未实现（桩恒返 null）。
 */
class PairingRefParserTest {

    @Test
    fun plainRefWithoutHostIsAccepted() {
        assertEquals("AbCdEf123456", PairingRefParser.parseRef("neurova://pair?ref=AbCdEf123456"))
    }

    @Test
    fun refWithHostSuffixIsAccepted() {
        assertEquals("R1", PairingRefParser.parseRef("neurova://pair?ref=R1&host=www.neurova.top"))
    }

    @Test
    fun nonPairSchemeIsRejected() {
        assertNull(PairingRefParser.parseRef("https://example.com/pair?ref=X"))
    }

    @Test
    fun missingRefParameterIsRejected() {
        assertNull(PairingRefParser.parseRef("neurova://pair"))
        assertNull(PairingRefParser.parseRef("neurova://pair?host=only"))
    }

    @Test
    fun garbageInputIsRejected() {
        assertNull(PairingRefParser.parseRef(""))
        assertNull(PairingRefParser.parseRef("not a uri"))
    }
}
