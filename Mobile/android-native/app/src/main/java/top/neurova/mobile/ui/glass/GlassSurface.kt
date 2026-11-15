package top.neurova.mobile.ui.glass

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp
import top.neurova.mobile.ui.theme.LocalNeurovaColors

/**
 * 星穹玻璃面：品牌玻璃底色 + 顶部高光 + 玻璃描边，单容器多层绘制。
 *
 * 深度说明：真实背景实时模糊（设计稿注解 RenderEffect / API 31+）需要捕获底层内容做 backdrop blur，
 * Compose 1.7 尚无开箱 backdrop blur 原语；本组件先以半透明玻璃底呈现，
 * 悬浮 chrome 的 backdrop blur 列入大屏适配批（P9）一并处理，不在此处伪装。
 */
@Composable
fun GlassSurface(
    modifier: Modifier = Modifier,
    shape: Shape,
    borderColor: Color? = null,
    content: @Composable BoxScope.() -> Unit,
) {
    val palette = LocalNeurovaColors.current
    val resolvedBorder = borderColor ?: palette.glassBorder
    Box(
        modifier = modifier
            .clip(shape)
            .background(palette.glass, shape)
            .background(
                Brush.verticalGradient(
                    0f to Color(0x1FFFFFFF),
                    0.42f to Color(0x00FFFFFF),
                ),
                shape,
            )
            .border(
                width = 1.dp,
                brush = Brush.verticalGradient(
                    listOf(resolvedBorder, resolvedBorder.copy(alpha = 0.55f)),
                ),
                shape = shape,
            ),
        content = content,
    )
}
