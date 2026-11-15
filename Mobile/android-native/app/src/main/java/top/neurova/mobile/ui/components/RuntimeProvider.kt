package top.neurova.mobile.ui.components

import androidx.compose.runtime.staticCompositionLocalOf
import top.neurova.mobile.core.AppRuntime

/** 运行时组合供给：屏内统一经 LocalAppRuntime 取通道与仓 */
val LocalAppRuntime = staticCompositionLocalOf<AppRuntime> {
    error("AppRuntime 未装配：必须在 MainActivity setContent 外层提供")
}
