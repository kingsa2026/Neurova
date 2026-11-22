package top.neurova.mobile.core.protocol

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 工具事件 → 确认/审批卡 view-model（卡 C）：
 * - computer_action 载荷：needs_host_confirmation / pending_approval 两类卡面；
 * - 移动 WS 现行派生帧：chat:approval_required 与 chat:tool_result 内容透传。
 * 载荷形状以后端 `tool_executor._emit_computer_event` 与
 * `console._extract_approval_payload` 实际字段为准（host/port/fingerprint/key_type/
 * agent_id；approval_id/tool_name/params/governance/reason）。
 */
class ToolActionEventsTest {

    @Test
    fun computerActionHostConfirmationPayloadParsesToCard() {
        // 形状照抄 tool_executor._handleSshHostConfirmation 的广播载荷（卡 A 补 agent_id）
        val frame = Json.parseToJsonElement(
            """
            {"type":"computer_action","session_id":"s-1","payload":{
              "tool":"computer_ssh_exec","success":false,
              "needs_host_confirmation":true,
              "host":"10.0.0.9","port":2222,
              "fingerprint":"SHA256:CAFEBABE","key_type":"ssh-ed25519",
              "agent_id":"agent-9",
              "error":"主机 10.0.0.9:2222 首次连接，公钥指纹 SHA256:CAFEBABE，请在确认卡中核对后确认"
            }}
            """.trimIndent(),
        ).jsonObject
        val payload = ToolActionEvents.payloadOf(frame)
        assertNotNull(payload)
        val card = ToolActionEvents.parseHostConfirmation("s-1", payload!!)
        assertNotNull(card)
        assertEquals("10.0.0.9", card!!.host)
        assertEquals(2222, card.port)
        assertEquals("SHA256:CAFEBABE", card.fingerprint)
        assertEquals("ssh-ed25519", card.keyType)
        assertEquals("agent-9", card.agentId)
        assertEquals("s-1", card.sessionId)
        assertTrue(card.message.orEmpty().contains("首次连接"))
    }

    @Test
    fun computerActionPendingApprovalPayloadParsesToApprovalCard() {
        val frame = Json.parseToJsonElement(
            """
            {"type":"computer_action","session_id":"s-2","payload":{
              "tool":"file_delete","success":false,
              "pending_approval":true,"approval_id":"req-777",
              "tool_name":"file_delete",
              "params":{"path":"/tmp/keep.txt"},
              "governance":{"rule":"permanent_delete"},
              "error":"永久删除语义命中治理门，等待审批"
            }}
            """.trimIndent(),
        ).jsonObject
        val payload = ToolActionEvents.payloadOf(frame)
        val card = ToolActionEvents.parseApproval("s-2", payload!!)
        assertNotNull(card)
        assertEquals("req-777", card!!.approvalId)
        assertEquals("file_delete", card.toolName)
        assertEquals("/tmp/keep.txt", card.params?.get("path")?.toString()?.trim('"'))
        assertEquals("permanent_delete", card.governance?.get("rule")?.toString()?.trim('"'))
        assertTrue(card.reason.orEmpty().contains("审批"))
    }

    @Test
    fun chatApprovalRequiredFrameParsesToApprovalCard() {
        // console._extract_approval_payload 派生形状（移动 WS chat:approval_required.data）
        val frame = Json.parseToJsonElement(
            """
            {"type":"chat:approval_required","session_id":"s-3","data":{
              "approval_id":"req-1001","tool_name":"computer_ssh_exec",
              "params":{"host":"h1"},"reason":"动态干预：目标主机首次出现",
              "governance":{"kind":"dynamic_intervention"},"fingerprint_tail":"a1b2"
            }}
            """.trimIndent(),
        ).jsonObject
        val data = frame["data"]?.jsonObject
        assertNotNull(data)
        val card = ToolActionEvents.parseApproval("s-3", data!!)
        assertNotNull(card)
        assertEquals("req-1001", card!!.approvalId)
        assertEquals("computer_ssh_exec", card.toolName)
        assertEquals("动态干预：目标主机首次出现", card.reason)
    }

    @Test
    fun toolResultContentCarryingHostConfirmationParsesToCard() {
        // chat:tool_result 的 content 是结果 JSON 字符串（needs_host_confirmation 随内容透传）
        val frame = Json.parseToJsonElement(
            """
            {"type":"chat:tool_result","session_id":"s-4","data":{
              "tool_call_id":"call-1","name":"computer_ssh_exec",
              "content":"{\n  \"success\": false,\n  \"needs_host_confirmation\": true,\n  \"host\": \"h1\",\n  \"port\": 22,\n  \"fingerprint\": \"SHA256:XY\",\n  \"error\": \"等待主机 h1 公钥确认超时，命令未执行\"\n}"
            }}
            """.trimIndent(),
        ).jsonObject
        val card = ToolActionEvents.parseHostConfirmationFromToolResult("s-4", frame["data"]!!.jsonObject)
        assertNotNull(card)
        assertEquals("h1", card!!.host)
        assertEquals(22, card.port)
        assertEquals("SHA256:XY", card.fingerprint)
    }

    @Test
    fun nonCardPayloadsReturnNull() {
        // 无 needs_host_confirmation / approval_id 的普通动作事件不成卡
        val plain = Json.parseToJsonElement(
            """{"tool":"computer_click","success":true,"summary":"点击按钮"}""",
        ).jsonObject
        assertNull(ToolActionEvents.parseHostConfirmation("s", plain))
        assertNull(ToolActionEvents.parseApproval("s", plain))
        // 缺 host 的确认载荷不成卡（防半截载荷）
        val noHost = Json.parseToJsonElement(
            """{"needs_host_confirmation":true,"fingerprint":"SHA256:X"}""",
        ).jsonObject
        assertNull(ToolActionEvents.parseHostConfirmation("s", noHost))
        // 缺 approval_id 的审批载荷不成卡
        val noId = Json.parseToJsonElement("""{"pending_approval":true,"tool_name":"x"}""").jsonObject
        assertNull(ToolActionEvents.parseApproval("s", noId))
    }

    @Test
    fun payloadOfToleratesWrapperShapes() {
        val direct = Json.parseToJsonElement(
            """{"type":"computer_action","tool":"t","needs_host_confirmation":true,"host":"h"}""",
        ).jsonObject
        assertEquals("h", ToolActionEvents.payloadOf(direct)?.get("host")?.toString()?.trim('"'))
        val wrapped = Json.parseToJsonElement(
            """{"type":"computer_action","data":{"tool":"t","needs_host_confirmation":true,"host":"h"}}""",
        ).jsonObject
        assertEquals("h", ToolActionEvents.payloadOf(wrapped)?.get("host")?.toString()?.trim('"'))
        val unrelated = Json.parseToJsonElement("""{"type":"computer_action","seq":3}""").jsonObject
        assertNull(ToolActionEvents.payloadOf(unrelated))
    }
}
