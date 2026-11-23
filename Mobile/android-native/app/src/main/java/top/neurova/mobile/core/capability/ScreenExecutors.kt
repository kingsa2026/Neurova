package top.neurova.mobile.core.capability

import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.serialization.json.JsonObject
import top.neurova.mobile.core.accessibility.ExecutorAccessibilityService
import top.neurova.mobile.core.accessibility.ExecutorGate
import top.neurova.mobile.core.accessibility.GesturePlan
import top.neurova.mobile.core.accessibility.GesturePlanner
import top.neurova.mobile.core.accessibility.NodeProjector

/**
 * 屏幕执行器（2026-11-23 计划卡 A4 的能力层出口）：
 * - screen_observe：无障碍树投影（编号 ref + 验证码打码 + 密码文本隐藏）；
 * - screen_gesture：tap/long_click/swipe/type/back/click_ref/set_text 规划后经
 *   无障碍服务注入；
 * - 武装纪律：命令到达即武装（闲置 60s 自动解除，红线 2 绝不常开）；
 * - 凭据防线（M3）：密码/验证码字段禁止注入与出文本，双保险（规划层 + 执行层）。
 */
object ScreenExecutors {

    val gate = ExecutorGate()

    private class GateCheck(val service: ExecutorAccessibilityService?, val refusal: ExecuteOutcome?)

    private fun serviceOrRefusal(): GateCheck {
        val service = ExecutorAccessibilityService.active
            ?: return GateCheck(
                null,
                ExecuteOutcome.error("not_initialized", "无障碍服务未连接（请先在系统设置开启无障碍）"),
            )
        if (!gate.isArmed()) {
            return GateCheck(
                null,
                ExecuteOutcome.error("accessibility_disarmed", "执行器未武装（闲置超时或未开任务窗口）"),
            )
        }
        return GateCheck(service, null)
    }

    class ScreenObserveExecutor : DeviceActionExecutor {
        override val action = "screen_observe"

        override suspend fun execute(payload: JsonObject): ExecuteOutcome {
            val check = serviceOrRefusal()
            val service = check.service
            if (service == null) return check.refusal ?: ExecuteOutcome.error("executor_error", "未武装")
            gate.onActivity()
            val projection = service.snapshot()
            return ExecuteOutcome.ok(NodeProjector.toPayload(projection))
        }
    }

    class ScreenGestureExecutor : DeviceActionExecutor {
        override val action = "screen_gesture"

        override suspend fun execute(payload: JsonObject): ExecuteOutcome {
            val check = serviceOrRefusal()
            val service = check.service
            if (service == null) return check.refusal ?: ExecuteOutcome.error("executor_error", "未武装")
            gate.onActivity()

            val op = payload["op"]?.toString()?.trim('"').orEmpty()
            val plan = GesturePlanner.plan(
                op, payload,
                screenW = service.resources.displayMetrics.widthPixels,
                screenH = service.resources.displayMetrics.heightPixels,
                credentialRefs = service.credentialRefs(),
            )
            return when (plan) {
                is GesturePlan.Refusal -> ExecuteOutcome.error(plan.code, plan.message)
                is GesturePlan.Plan -> executeSteps(service, plan)
            }
        }

        private fun executeSteps(service: ExecutorAccessibilityService, plan: GesturePlan.Plan): ExecuteOutcome {
            for (step in plan.steps) {
                gate.onActivity()
                when (step.kind) {
                    "tap" -> if (!service.dispatchTap(step.x, step.y)) {
                        return ExecuteOutcome.error("executor_error", "点击注入失败")
                    }
                    "long_click" -> if (!service.dispatchTap(step.x, step.y, longClick = true)) {
                        return ExecuteOutcome.error("executor_error", "长按注入失败")
                    }
                    "swipe" -> if (!service.dispatchSwipe(step.x, step.y, step.x2, step.y2)) {
                        return ExecuteOutcome.error("executor_error", "滑动注入失败")
                    }
                    "back" -> if (!service.pressBack()) {
                        return ExecuteOutcome.error("executor_error", "返回键执行失败")
                    }
                    "click_ref" -> {
                        val node = service.nodeByRef(step.ref)
                            ?: return ExecuteOutcome.error("ref_not_found", "屏幕已变化，请重新读屏")
                        if (!node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                            return ExecuteOutcome.error("element_not_clickable", "该节点不可点击")
                        }
                    }
                    "type" -> {
                        val failure = typeIntoFocused(service, step.text)
                        if (failure != null) return failure
                    }
                    "set_text" -> {
                        val node = service.nodeByRef(step.ref)
                            ?: return ExecuteOutcome.error("ref_not_found", "屏幕已变化，请重新读屏")
                        if (node.isPassword) {
                            return ExecuteOutcome.error("credential_field_blocked", "目标为密码字段，禁止注入")
                        }
                        val args = Bundle().apply {
                            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, step.text)
                        }
                        if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                            return ExecuteOutcome.error("executor_error", "文本注入失败")
                        }
                    }
                }
            }
            return ExecuteOutcome.ok()
        }

        /** type 注入到焦点节点；密码/验证码焦点字段拒绝（M3 双保险第二道） */
        private fun typeIntoFocused(service: ExecutorAccessibilityService, text: String): ExecuteOutcome? {
            val focused = service.rootInActiveWindow
                ?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
                ?: return ExecuteOutcome.error("no_focused_field", "当前无焦点输入框")
            if (focused.isPassword) {
                return ExecuteOutcome.error("credential_field_blocked", "目标为密码字段，禁止注入")
            }
            val args = Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
            }
            if (!focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                return ExecuteOutcome.error("executor_error", "文本注入失败")
            }
            return null
        }
    }
}
