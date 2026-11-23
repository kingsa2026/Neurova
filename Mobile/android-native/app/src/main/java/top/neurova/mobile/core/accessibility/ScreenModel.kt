package top.neurova.mobile.core.accessibility

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * 无障碍读屏的数据模型与投影（2026-11-23 计划卡 A4/M3）。
 *
 * ScreenNode 是无障碍树的**可测纯模型**（框架层把 AccessibilityNodeInfo 转成它，
 * 转换之外的全部逻辑——ref 分配、密码隐藏、验证码打码、截断——都在纯模型上
 * 完成，JVM 单测全覆盖）。
 */
data class ScreenNode(
    val role: String,
    val label: String = "",
    val text: String = "",
    val isPassword: Boolean = false,
    val clickable: Boolean = false,
    val bounds: String = "",
    val packageName: String = "",
    val children: List<ScreenNode> = emptyList(),
)

data class ProjectedNode(
    val ref: String,
    val role: String,
    val label: String,
    val text: String,
    val clickable: Boolean,
    val bounds: String,
)

data class ScreenProjection(
    val nodes: List<ProjectedNode>,
    val truncated: Boolean,
    val hidden: Boolean = false,
    val hiddenReason: String = "",
)

object NodeProjector {

    /** 单次投影节点上限（防超大树拖垮模型与账本） */
    const val MAX_NODES = 200

    fun project(root: ScreenNode, maxNodes: Int = MAX_NODES): ScreenProjection {
        val nodes = ArrayList<ProjectedNode>()
        var truncated = false
        val queue = ArrayDeque<ScreenNode>()
        queue.add(root)
        var index = 0
        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            index += 1
            if (nodes.size >= maxNodes) {
                truncated = true
                break
            }
            val ref = "e$index"
            val text = if (current.isPassword) "••••" else current.text
            nodes.add(
                ProjectedNode(
                    ref = ref,
                    role = current.role,
                    label = current.label,
                    text = CredentialGuard.maskCodeDigits(text, current.label),
                    clickable = current.clickable,
                    bounds = current.bounds,
                ),
            )
            for (child in current.children) {
                queue.add(child)
            }
        }
        return ScreenProjection(nodes = nodes, truncated = truncated)
    }

    /** 投影 → device:observe 回执 data 载荷 */
    fun toPayload(projection: ScreenProjection): JsonObject = JsonObject(
        mapOf(
            "nodes" to JsonArray(projection.nodes.map {
                JsonObject(
                    mapOf(
                        "ref" to JsonPrimitive(it.ref),
                        "role" to JsonPrimitive(it.role),
                        "label" to JsonPrimitive(it.label),
                        "text" to JsonPrimitive(it.text),
                        "clickable" to JsonPrimitive(it.clickable),
                        "bounds" to JsonPrimitive(it.bounds),
                    ),
                )
            }),
            "truncated" to JsonPrimitive(projection.truncated),
            "hidden" to JsonPrimitive(projection.hidden),
        ),
    )
}
