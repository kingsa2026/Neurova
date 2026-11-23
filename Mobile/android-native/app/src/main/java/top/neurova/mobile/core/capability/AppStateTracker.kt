package top.neurova.mobile.core.capability

/**
 * 端上运行态（能力协商的端侧事实源）：App 前台/后台。
 * MainActivity 生命周期钩子写入；设备桥派发器据此执行后台闸，
 * device:hello 据此上报 app_state。缺省 foreground（保守放行面最小化——
 * 仅在真实退后台后收窄）。
 */
object AppStateTracker {
    @Volatile
    var current: String = "foreground"
        private set

    fun foreground() {
        current = "foreground"
    }

    fun background() {
        current = "background"
    }
}
