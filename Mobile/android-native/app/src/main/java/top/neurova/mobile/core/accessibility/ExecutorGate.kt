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

    @Volatile
    private var armedTaskId: String = ""

    @Volatile
    private var taskWindowExpiresAt: Long = 0

    fun arm(durationMs: Long = idleTimeoutMs) {
        armedUntil = clock() + durationMs
        armedTaskId = ""
    }

    /** 服务端确认的显式任务窗口：端上到期不得晚于服务端 expires_at。 */
    fun arm(taskId: String, expiresAt: Long) {
        if (taskId.isBlank() || expiresAt <= clock()) return
        armedTaskId = taskId
        taskWindowExpiresAt = expiresAt
        armedUntil = minOf(expiresAt, clock() + idleTimeoutMs)
    }

    /** 每次命令活动续期；外地任务不能续期当前窗口。 */
    fun onActivity(taskId: String? = null) {
        if (taskId == null) {
            arm()
        } else if (taskId == armedTaskId && isArmed(taskId)) {
            armedUntil = minOf(taskWindowExpiresAt, clock() + idleTimeoutMs)
        }
    }

    fun disarm() {
        armedUntil = 0
        armedTaskId = ""
    }

    fun isArmed(taskId: String? = null): Boolean =
        clock() <= armedUntil && (taskId == null || taskId == armedTaskId)

    companion object {
        const val DEFAULT_IDLE_TIMEOUT_MS = 60_000L
    }
}
