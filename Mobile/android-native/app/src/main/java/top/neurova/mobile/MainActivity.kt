package top.neurova.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.CompositionLocalProvider
import top.neurova.mobile.app.NeurovaAppRoot
import top.neurova.mobile.core.AppRuntime
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.NeurovaTheme

/**
 * 全窗沉浸入口（设计稿 04 实施路径①）：enableEdgeToEdge + 手势导航条让位交给窗口Insets。
 * 运行时唯一装配点在此（AppRuntime），向下经 LocalAppRuntime 组合供给。
 */
class MainActivity : ComponentActivity() {

    private val runtime by lazy { AppRuntime(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            CompositionLocalProvider(LocalAppRuntime provides runtime) {
                NeurovaTheme {
                    NeurovaAppRoot()
                }
            }
        }
    }
}
