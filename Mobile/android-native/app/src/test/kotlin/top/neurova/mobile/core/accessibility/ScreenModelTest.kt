package top.neurova.mobile.core.accessibility

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 无障碍读屏投影判据（2026-11-23 计划卡 A4/M3）：
 * - BFS 分配稳定 ref（e1、e2…）；
 * - 密码字段文本不出投影（M3 红线：凭据四可见面零明文）；
 * - 验证码类数字在命中关键词语境下打码；
 * - 节点数上限截断并如实标记 truncated。
 */
class ScreenModelTest {

    private fun node(
        role: String,
        label: String = "",
        text: String = "",
        isPassword: Boolean = false,
        clickable: Boolean = false,
        bounds: String = "0,0,100,40",
        children: List<ScreenNode> = emptyList(),
    ) = ScreenNode(
        role = role, label = label, text = text, isPassword = isPassword,
        clickable = clickable, bounds = bounds, children = children,
    )

    @Test
    fun project_assignsStableBfsRefs() {
        val root = node("window", children = listOf(
            node("button", label = "确定", clickable = true),
            node("text", label = "标题", children = listOf(node("input", label = "搜索"))),
        ))
        val projection = NodeProjector.project(root)
        assertEquals(
            listOf("e1", "e2", "e3", "e4"),
            projection.nodes.map { it.ref },
        )
        assertEquals("window", projection.nodes[0].role)
        assertEquals("确定", projection.nodes[1].label)
        assertEquals("搜索", projection.nodes[3].label)
        assertFalse(projection.truncated)
    }

    @Test
    fun project_passwordTextNeverLeavesTheDevice() {
        val root = node("window", children = listOf(
            node("input", label = "密码", text = "super-secret", isPassword = true),
        ))
        val projection = NodeProjector.project(root)
        val passwordNode = projection.nodes.first { it.label == "密码" }
        assertEquals("••••", passwordNode.text)
        assertFalse(passwordNode.text.contains("super-secret"))
    }

    @Test
    fun project_masksVerificationCodeDigitsInKeywordContext() {
        val root = node("window", children = listOf(
            node("text", label = "验证码", text = "您的验证码 987654，请勿泄露"),
            node("text", label = "订单号", text = "订单 12345678 已发货"),
        ))
        val projection = NodeProjector.project(root)
        assertEquals("您的验证码 ••••••，请勿泄露", projection.nodes[1].text)
        // 无关键词语境的数字不打码（金额/单号可读）
        assertEquals("订单 12345678 已发货", projection.nodes[2].text)
    }

    @Test
    fun project_truncatesBeyondMaxNodesAndMarksIt() {
        val children = (1..30).map { node("text", label = "n$it") }
        val root = node("window", children = children)
        val projection = NodeProjector.project(root, maxNodes = 10)
        assertEquals(10, projection.nodes.size)
        assertTrue(projection.truncated)
    }
}
