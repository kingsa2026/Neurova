package top.neurova.mobile.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

/**
 * Neurova 扩展色彩令牌（星穹玻璃）。
 * 事实源：安卓端界面布局规划 §01 设计系统（PC cosmic 皮肤令牌 --nr-primary 系）；
 * 深色为主基线，浅色主色沿用 PC cosmic #4d6bfe；品牌令牌锁定，不随 Monet 动态取色漂移。
 */
@Immutable
data class NeurovaColors(
    /** 卡片玻璃面（5.5% 叠加） */
    val glass: Color,
    /** 强玻璃面（9% 叠加，输入条/浮层） */
    val glassStrong: Color,
    /** 玻璃描边（11% 叠加） */
    val glassBorder: Color,
    /** 高对比正文 */
    val textHi: Color,
    /** 次级正文 */
    val textMid: Color,
    /** 弱化正文（时间戳/占位） */
    val textLow: Color,
    /** 青色强调（端点徽标/扫描线/图谱） */
    val accent: Color,
    /** 运行中 */
    val success: Color,
    /** 排队/告警 */
    val warn: Color,
    /** 中断/错误 */
    val danger: Color,
    /** 品牌三停渐变（135°） */
    val brandGradient: Brush,
    /** 屏幕氛围光（右上品牌晕 + 底部紫晕） */
    val screenGlow: Brush,
)

val LocalNeurovaColors = staticCompositionLocalOf {
    // 兜底取深色（正式装配点在 NeurovaTheme 内，此处仅防越级取用崩溃）
    darkNeurovaColors()
}

fun darkNeurovaColors() = NeurovaColors(
    glass = Color(0x0EFFFFFF),
    glassStrong = Color(0x17FFFFFF),
    glassBorder = Color(0x1CFFFFFF),
    textHi = Color(0xF2FFFFFF),
    textMid = Color(0xA3FFFFFF),
    textLow = Color(0x66FFFFFF),
    accent = Color(0xFF22D3EE),
    success = Color(0xFF34D399),
    warn = Color(0xFFFBBF24),
    danger = Color(0xFFF87171),
    brandGradient = Brush.linearGradient(
        0f to Color(0xFF6366F1),
        0.55f to Color(0xFF8B5CF6),
        1f to Color(0xFFA78BFA),
    ),
    screenGlow = Brush.radialGradient(
        colors = listOf(
            Color(0x4D6366F1),
            Color.Transparent,
        ),
        center = androidx.compose.ui.geometry.Offset(x = Float.POSITIVE_INFINITY, y = 0f),
        radius = 900f,
    ),
)

fun lightNeurovaColors() = NeurovaColors(
    glass = Color(0x0B10152C),
    glassStrong = Color(0x1410152C),
    glassBorder = Color(0x1C10152C),
    textHi = Color(0xF010152C),
    textMid = Color(0x9E10152C),
    textLow = Color(0x6B10152C),
    accent = Color(0xFF0E7490),
    success = Color(0xFF0C8F5E),
    warn = Color(0xFFB45309),
    danger = Color(0xFFDC2626),
    brandGradient = Brush.linearGradient(
        0f to Color(0xFF4D6BFE),
        0.55f to Color(0xFF7C3AED),
        1f to Color(0xFF6D28D9),
    ),
    screenGlow = Brush.radialGradient(
        colors = listOf(
            Color(0x1A6366F1),
            Color.Transparent,
        ),
        center = androidx.compose.ui.geometry.Offset(x = Float.POSITIVE_INFINITY, y = 0f),
        radius = 900f,
    ),
)
