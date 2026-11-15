package top.neurova.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color

/**
 * 星穹玻璃主题装配点。
 * M3 语义色与 NeurovaColors 扩展令牌双层供给；深浅色跟随系统（跟随系统深浅色，见设计稿 §01）。
 */
private val darkScheme: ColorScheme = darkColorScheme(
    primary = Color(0xFF6366F1),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFF272D52),
    onPrimaryContainer = Color(0xFFC7CCFF),
    secondary = Color(0xFF8B5CF6),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFF2E2755),
    onSecondaryContainer = Color(0xFFC4B5FD),
    tertiary = Color(0xFF22D3EE),
    onTertiary = Color(0xFF06222B),
    tertiaryContainer = Color(0xFF0E3E4C),
    onTertiaryContainer = Color(0xFFB4ECF7),
    error = Color(0xFFF87171),
    onError = Color(0xFF2B0B0B),
    errorContainer = Color(0xFF4A1414),
    onErrorContainer = Color(0xFFFCA5A5),
    background = Color(0xFF0A0E1D),
    onBackground = Color(0xFFEDEFFA),
    surface = Color(0xFF0D1122),
    onSurface = Color(0xFFEDEFFA),
    surfaceVariant = Color(0xFF161B30),
    onSurfaceVariant = Color(0xFFA8ADC2),
    surfaceContainerLowest = Color(0xFF0B0F1F),
    surfaceContainerLow = Color(0xFF0F1425),
    surfaceContainer = Color(0xFF121728),
    surfaceContainerHigh = Color(0xFF171C33),
    surfaceContainerHighest = Color(0xFF1B2040),
    outline = Color(0xFF3A4060),
    outlineVariant = Color(0xFF2A3050),
    inverseSurface = Color(0xFFEDEFFA),
    inverseOnSurface = Color(0xFF12152A),
    scrim = Color(0xE6040614),
)

private val lightScheme: ColorScheme = lightColorScheme(
    primary = Color(0xFF4D6BFE),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDCE1FF),
    onPrimaryContainer = Color(0xFF1A2AA0),
    secondary = Color(0xFF6D28D9),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE9DEFF),
    onSecondaryContainer = Color(0xFF3B1788),
    tertiary = Color(0xFF0E7490),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFCFF1FA),
    onTertiaryContainer = Color(0xFF083748),
    error = Color(0xFFDC2626),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFCD9D9),
    onErrorContainer = Color(0xFF7F1010),
    background = Color(0xFFF5F6FB),
    onBackground = Color(0xFF10152C),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF10152C),
    surfaceVariant = Color(0xFFE9EBF4),
    onSurfaceVariant = Color(0xFF5A607C),
    surfaceContainerLowest = Color(0xFFFFFFFF),
    surfaceContainerLow = Color(0xFFF2F4FA),
    surfaceContainer = Color(0xFFEFF1F8),
    surfaceContainerHigh = Color(0xFFEAEDF5),
    surfaceContainerHighest = Color(0xFFE4E7F1),
    outline = Color(0xFFC3C7DB),
    outlineVariant = Color(0xFFD8DBE8),
    inverseSurface = Color(0xFF10152C),
    inverseOnSurface = Color(0xFFF2F4FA),
    scrim = Color(0x6610152C),
)

@Composable
fun NeurovaTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val neurovaColors = if (darkTheme) darkNeurovaColors() else lightNeurovaColors()
    CompositionLocalProvider(LocalNeurovaColors provides neurovaColors) {
        MaterialTheme(
            colorScheme = if (darkTheme) darkScheme else lightScheme,
            content = content,
        )
    }
}
