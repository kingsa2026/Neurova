package top.neurova.mobile.core.protocol

/**
 * 对话域大屏布局断点（安卓端界面布局规划 §P9）：
 * - compact (<600dp)：单栏——会话列表 Tab → 导航进聊天页（现状）；
 * - medium (600–839dp)：NavigationRail + 会话列表|聊天 双栏同屏；
 * - expanded (≥840dp)：三栏——会话列表|聊天|会话信息（Agent/进度），与 PC 右侧 Dock 对齐。
 * 断点数值与 Material3 WindowWidthSizeClass 口径一致。
 */
enum class ChatLayoutMode(
    val showSessionPane: Boolean,
    val showInfoPane: Boolean,
) {
    LIST_ONLY(showSessionPane = false, showInfoPane = false),
    LIST_PLUS_CHAT(showSessionPane = true, showInfoPane = false),
    THREE_PANE(showSessionPane = true, showInfoPane = true),
    ;

    companion object {
        fun fromWidthDp(widthDp: Int): ChatLayoutMode = when {
            widthDp >= 840 -> THREE_PANE
            widthDp >= 600 -> LIST_PLUS_CHAT
            else -> LIST_ONLY
        }
    }
}
