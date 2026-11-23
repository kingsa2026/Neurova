package top.neurova.mobile.core.accessibility

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 手势/动作规划判据（2026-11-23 计划卡 A4）：op 词表封闭、参数校验、
 * 越界拒绝——规划纯逻辑，执行仍走无障碍服务（真机验证）。
 */
class GesturePlannerTest {

    private fun payload(raw: String) = Json.parseToJsonElement(raw).jsonObject

    private fun plan(op: String, raw: String = "{}", w: Int = 1080, h: Int = 2400) =
        GesturePlanner.plan(op, payload(raw), screenW = w, screenH = h)

    @Test
    fun plan_tapWithInRange() {
        val result = plan("tap", """{"x":100,"y":200}""")
        assertTrue(result is GesturePlan.Plan)
        val step = (result as GesturePlan.Plan).steps.single()
        assertEquals("tap", step.kind)
        assertEquals(100f, step.x)
        assertEquals(200f, step.y)
    }

    @Test
    fun plan_swipeCarriesBothPoints() {
        val result = plan("swipe", """{"x1":10,"y1":20,"x2":300,"y2":400}""")
        val step = (result as GesturePlan.Plan).steps.single()
        assertEquals("swipe", step.kind)
        assertEquals(300f, step.x2)
        assertEquals(400f, step.y2)
    }

    @Test
    fun plan_typeCarriesText_backNeedsNothing_clickRefCarriesRef() {
        val type = plan("type", """{"text":"你好"}""") as GesturePlan.Plan
        assertEquals("type", type.steps.single().kind)
        assertEquals("你好", type.steps.single().text)

        val back = plan("back") as GesturePlan.Plan
        assertEquals("back", back.steps.single().kind)

        val clickRef = plan("click_ref", """{"ref":"e7"}""") as GesturePlan.Plan
        assertEquals("click_ref", clickRef.steps.single().kind)
        assertEquals("e7", clickRef.steps.single().ref)
    }

    @Test
    fun plan_unknownOpIsRefused() {
        val result = plan("unlock_bootloader")
        assertTrue(result is GesturePlan.Refusal)
        assertEquals("unsupported_op", (result as GesturePlan.Refusal).code)
    }

    @Test
    fun plan_missingParamsAreRefused() {
        assertTrue(plan("tap", """{"x":1}""") is GesturePlan.Refusal)
        assertTrue(plan("type", """{}""") is GesturePlan.Refusal)
        assertTrue(plan("click_ref", """{}""") is GesturePlan.Refusal)
    }

    @Test
    fun plan_outOfBoundsCoordinatesAreRefused() {
        val result = plan("tap", """{"x":5000,"y":200}""", w = 1080, h = 2400)
        assertTrue(result is GesturePlan.Refusal)
        assertEquals("out_of_bounds", (result as GesturePlan.Refusal).code)
    }

    @Test
    fun plan_credentialTargetsAreRefused() {
        // set_text 到密码字段：规划层即拒（M3 红线，双保险——执行层再查节点）
        val result = GesturePlanner.plan(
            "set_text",
            payload("""{"ref":"e3","text":"secret"}"""),
            screenW = 1080, screenH = 2400,
            credentialRefs = setOf("e3"),
        )
        assertTrue(result is GesturePlan.Refusal)
        assertEquals("credential_field_blocked", (result as GesturePlan.Refusal).code)
    }
}
