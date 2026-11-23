package top.neurova.mobile

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.CompositionLocalProvider
import androidx.core.content.ContextCompat
import top.neurova.mobile.app.NeurovaAppRoot
import top.neurova.mobile.core.AppRuntime
import top.neurova.mobile.core.capability.AppStateTracker
import top.neurova.mobile.core.service.DeviceBridgeService
import top.neurova.mobile.ui.components.LocalAppRuntime
import top.neurova.mobile.ui.theme.NeurovaTheme

/**
 * 全窗沉浸入口（设计稿 04 实施路径①）：enableEdgeToEdge + 手势导航条让位交给窗口Insets。
 * 运行时唯一装配点在此（AppRuntime），向下经 LocalAppRuntime 组合供给。
 */
class MainActivity : ComponentActivity() {

    // 进程级单例（DCL）：设备桥前台服务与 UI 共用同一份装配
    private val runtime by lazy { AppRuntime.instance(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // 设备桥（2026-11-23 计划卡 A1）：前台服务承载应用级 WS 常连
        ContextCompat.startForegroundService(this, Intent(this, DeviceBridgeService::class.java))
        setContent {
            CompositionLocalProvider(LocalAppRuntime provides runtime) {
                NeurovaTheme {
                    NeurovaAppRoot()
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        AppStateTracker.foreground()
    }

    override fun onPause() {
        AppStateTracker.background()
        super.onPause()
    }
}
