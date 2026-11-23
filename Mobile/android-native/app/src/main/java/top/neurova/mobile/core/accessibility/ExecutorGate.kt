package top.neurova.mobile.core.accessibility

/**
 * 无障碍执行器按需开关（2026-11-23 计划卡 A4；红线 2：绝不常开）。
 *
 * 三方应用无法编程启停系统无障碍开关（需用户在系统设置授权一次）；
 * 本闸控的是"武装窗口"——仅在任务窗口内接受命令，闲置 60s 自动解除，
 * 每次命令活动续期。解除后执行器必须拒绝命令。
 */
class ExecutorGate(
    private val idleTimeoutMs: Long = DEFAULT_IDLE_TIMEOUT_MS,
    private val clock: () -> Long = System::currentTimeMillis,
) {

    @Volatile
    private var armedUntil: Long = 0

    fun arm(durationMs: Long = idleTimeoutMs) {
        armedUntil = clock() + durationMs
    }

    /** 每次命令活动续期（任务连续执行时不被闲置超时打断） */
    fun onActivity() {
        arm()
    }

    fun disarm() {
        armedUntil = 0
    }

    fun isArmed(): Boolean = clock() <= armedUntil

    companion object {
        const val DEFAULT_IDLE_TIMEOUT_MS = 60_000L
    }
}
