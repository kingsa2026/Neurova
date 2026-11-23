package top.neurova.mobile.core.accessibility

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * 手势/动作规划器（2026-11-23 计划卡 A4）：op 词表封闭、参数校验、越界拒绝、
 * 凭据目标拒绝——全部纯逻辑（JVM 单测钉住）；真正注入走无障碍服务的
 * dispatchGesture/performAction（真机验证）。
 */
data class GestureStep(
    val kind: String,
    val x: Float = 0f,
    val y: Float = 0f,
    val x2: Float = 0f,
    val y2: Float = 0f,
    val text: String = "",
    val ref: String = "",
)

sealed class GesturePlan {
    data class Plan(val steps: List<GestureStep>) : GesturePlan()
    data class Refusal(val code: String, val message: String) : GesturePlan()
}

object GesturePlanner {

    fun plan(
        op: String,
        payload: JsonObject,
        screenW: Int,
        screenH: Int,
        credentialRefs: Set<String> = emptySet(),
    ): GesturePlan {
        fun f(key: String): Float? =
            (payload[key] as? JsonPrimitive)?.content?.toFloatOrNull()

        fun s(key: String): String =
            (payload[key] as? JsonPrimitive)?.content.orEmpty()

        fun inBounds(x: Float, y: Float): Boolean =
            x >= 0f && y >= 0f && x <= screenW && y <= screenH

        fun pointPlan(kind: String, x: Float?, y: Float?): GesturePlan {
            if (x == null || y == null) {
                return GesturePlan.Refusal("missing_params", "$kind 缺 x/y 坐标")
            }
            if (!inBounds(x, y)) {
                return GesturePlan.Refusal("out_of_bounds", "坐标越界：($x, $y)")
            }
            return GesturePlan.Plan(listOf(GestureStep(kind = kind, x = x, y = y)))
        }

        return when (op) {
            "tap" -> pointPlan("tap", f("x"), f("y"))
            "long_click" -> pointPlan("long_click", f("x"), f("y"))
            "swipe" -> {
                val x1 = f("x1"); val y1 = f("y1"); val x2 = f("x2"); val y2 = f("y2")
                if (x1 == null || y1 == null || x2 == null || y2 == null) {
                    GesturePlan.Refusal("missing_params", "swipe 缺 x1/y1/x2/y2")
                } else if (!inBounds(x1, y1) || !inBounds(x2, y2)) {
                    GesturePlan.Refusal("out_of_bounds", "滑动坐标越界")
                } else {
                    GesturePlan.Plan(listOf(GestureStep("swipe", x = x1, y = y1, x2 = x2, y2 = y2)))
                }
            }
            "type" -> {
                val text = s("text")
                if (text.isEmpty()) {
                    GesturePlan.Refusal("missing_params", "type 缺 text")
                } else {
                    GesturePlan.Plan(listOf(GestureStep("type", text = text)))
                }
            }
            "back" -> GesturePlan.Plan(listOf(GestureStep("back")))
            "click_ref" -> {
                val ref = s("ref")
                if (ref.isEmpty()) {
                    GesturePlan.Refusal("missing_params", "click_ref 缺 ref")
                } else {
                    GesturePlan.Plan(listOf(GestureStep("click_ref", ref = ref)))
                }
            }
            "set_text" -> {
                val ref = s("ref")
                val text = s("text")
                if (ref.isEmpty() || text.isEmpty()) {
                    GesturePlan.Refusal("missing_params", "set_text 缺 ref/text")
                } else if (ref in credentialRefs) {
                    // M3 红线：凭据字段禁止注入文本（执行层对聚焦节点再查一道）
                    GesturePlan.Refusal("credential_field_blocked", "目标为密码/验证码字段，禁止注入")
                } else {
                    GesturePlan.Plan(listOf(GestureStep("set_text", text = text, ref = ref)))
                }
            }
            else -> GesturePlan.Refusal("unsupported_op", "未支持的手势操作：$op")
        }
    }
}
