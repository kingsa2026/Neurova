package top.neurova.mobile.core.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * 无障碍执行器服务（2026-11-23 计划卡 A4）——框架胶水层。
 *
 * 职责边界：本类只做 AccessibilityNodeInfo ↔ ScreenNode 转换、手势注入与
 * 全局动作；投影/打码/凭据防线/按需开关全部在纯模型层（ScreenModel、Guards、
 * ExecutorGate、GesturePlanner，JVM 单测覆盖）。
 *
 * 武装纪律（红线 2）：系统无障碍开关由用户在设置里授权一次（三方应用无法
 * 编程启停）；本服务的按需开关是"武装窗口"——仅任务窗口内接受命令，闲置
 * 60s 自动解除（ExecutorGate）。
 */
class ExecutorAccessibilityService : AccessibilityService() {

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // 仅记录前台包名变化供敏感应用隐身判定；不做任何主动采集
        if (event?.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            currentWindowPackage = event.packageName?.toString().orEmpty()
        }
    }

    override fun onInterrupt() {
        // 无中断恢复动作；下一命令自然重试
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        active = this
    }

    override fun onUnbind(intent: Intent?): Boolean {
        if (active === this) {
            active = null
        }
        return super.onUnbind(intent)
    }

    /** 当前前台窗口包名（敏感应用隐身判定输入） */
    var currentWindowPackage: String = ""
        private set

    // ── 读屏 ─────────────────────────────────────────────────────────

    fun currentPackageName(): String = currentWindowPackage

    private fun convert(node: AccessibilityNodeInfo?, depth: Int): ScreenNode? {
        if (node == null || depth > MAX_DEPTH) return null
        val rect = android.graphics.Rect()
        node.getBoundsInScreen(rect)
        val children = ArrayList<ScreenNode>()
        for (i in 0 until node.childCount) {
            convert(node.getChild(i), depth + 1)?.let { children.add(it) }
        }
        val className = node.className?.toString().orEmpty()
        return ScreenNode(
            role = roleOf(className),
            label = node.contentDescription?.toString()
                ?: node.text?.toString().orEmpty(),
            text = node.text?.toString().orEmpty(),
            isPassword = node.isPassword,
            clickable = node.isClickable,
            bounds = "${rect.left},${rect.top},${rect.right},${rect.bottom}",
            packageName = node.packageName?.toString().orEmpty(),
            children = children,
        )
    }

    /** 读屏投影；应用隐身时返回 hidden 投影（无元素无文本） */
    fun snapshot(): ScreenProjection {
        if (SensitiveAppGuard.isHidden(currentWindowPackage)) {
            return ScreenProjection(nodes = emptyList(), truncated = false,
                hidden = true, hiddenReason = "sensitive_app")
        }
        val root = rootInActiveWindow ?: return ScreenProjection(
            nodes = emptyList(), truncated = false, hidden = false)
        val converted = convert(root, 0) ?: return ScreenProjection(
            nodes = emptyList(), truncated = false, hidden = false)
        return NodeProjector.project(converted)
    }

    /** 按投影 ref 取活动窗口节点（ref = BFS 序 e{n}；每次重走保证树新鲜） */
    fun nodeByRef(ref: String): AccessibilityNodeInfo? {
        val index = ref.removePrefix("e").toIntOrNull() ?: return null
        if (index <= 0) return null
        val root = rootInActiveWindow ?: return null
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var counter = 0
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            counter += 1
            if (counter == index) return node
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { queue.add(it) }
            }
        }
        return null
    }

    /** 凭据字段 refs（BFS 序与投影一致）：set_text 规划预检的输入（M3 双保险） */
    fun credentialRefs(): Set<String> {
        val root = rootInActiveWindow ?: return emptySet()
        val refs = HashSet<String>()
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        var counter = 0
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            counter += 1
            if (node.isPassword) {
                refs.add("e$counter")
            }
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { queue.add(it) }
            }
        }
        return refs
    }

    // ── 手势/动作执行 ─────────────────────────────────────────────────

    fun dispatchTap(x: Float, y: Float, longClick: Boolean = false): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val duration = if (longClick) 600L else 80L
        val stroke = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, duration))
            .build()
        return dispatchGesture(stroke, null, null)
    }

    fun dispatchSwipe(x1: Float, y1: Float, x2: Float, y2: Float): Boolean {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val stroke = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 300))
            .build()
        return dispatchGesture(stroke, null, null)
    }

    fun pressBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    companion object {
        const val MAX_DEPTH = 30

        @Volatile
        var active: ExecutorAccessibilityService? = null
            private set

        private fun roleOf(className: String): String {
            if (className.isEmpty()) return "node"
            val simple = className.substringAfterLast('.')
            return when {
                simple.contains("Button", ignoreCase = true) -> "button"
                simple.contains("EditText", ignoreCase = true) -> "input"
                simple.contains("Image", ignoreCase = true) -> "image"
                simple.contains("Switch", ignoreCase = true) ||
                    simple.contains("Toggle", ignoreCase = true) -> "switch"
                simple.contains("CheckBox", ignoreCase = true) -> "checkbox"
                else -> "text"
            }
        }
    }
}
