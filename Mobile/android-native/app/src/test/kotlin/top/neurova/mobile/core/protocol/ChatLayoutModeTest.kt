package top.neurova.mobile.core.protocol

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 对话域大屏布局断点（安卓端界面布局规划 §P9：A 直板机 compact <600dp 单栏导航；
 * C 折叠屏展开 medium 600–839dp NavigationRail + 列表|聊天双栏；
 * E 桌面模式/外接屏 expanded ≥840dp 三栏——会话列表|聊天|会话信息）。
 * 断点数值与 Material3 WindowWidthSizeClass 口径一致。
 */
class ChatLayoutModeTest {

    @Test
    fun compactPhonesStaySinglePane() {
        assertEquals(ChatLayoutMode.LIST_ONLY, ChatLayoutMode.fromWidthDp(0))
        assertEquals(ChatLayoutMode.LIST_ONLY, ChatLayoutMode.fromWidthDp(359))
        assertEquals(ChatLayoutMode.LIST_ONLY, ChatLayoutMode.fromWidthDp(599))
    }

    @Test
    fun mediumFoldablesGetListPlusChat() {
        assertEquals(ChatLayoutMode.LIST_PLUS_CHAT, ChatLayoutMode.fromWidthDp(600))
        assertEquals(ChatLayoutMode.LIST_PLUS_CHAT, ChatLayoutMode.fromWidthDp(720))
        assertEquals(ChatLayoutMode.LIST_PLUS_CHAT, ChatLayoutMode.fromWidthDp(839))
    }

    @Test
    fun expandedDesktopGetsThreePane() {
        assertEquals(ChatLayoutMode.THREE_PANE, ChatLayoutMode.fromWidthDp(840))
        assertEquals(ChatLayoutMode.THREE_PANE, ChatLayoutMode.fromWidthDp(1280))
    }

    @Test
    fun panesVisiblePerMode() {
        assertEquals(false, ChatLayoutMode.LIST_ONLY.showSessionPane)
        assertEquals(false, ChatLayoutMode.LIST_ONLY.showInfoPane)
        assertEquals(true, ChatLayoutMode.LIST_PLUS_CHAT.showSessionPane)
        assertEquals(false, ChatLayoutMode.LIST_PLUS_CHAT.showInfoPane)
        assertEquals(true, ChatLayoutMode.THREE_PANE.showSessionPane)
        assertEquals(true, ChatLayoutMode.THREE_PANE.showInfoPane)
    }
}
