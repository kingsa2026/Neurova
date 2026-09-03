"""console.py 审批事件提取 (_extract_approval_payload) 单元测试。"""

import unittest

from neurova.api.endpoints.console import _extract_approval_payload


class TestExtractApprovalPayload(unittest.TestCase):
    def test_pending_result_dict(self):
        result = {
            "success": False,
            "pending_approval": True,
            "approval_id": "req-1",
            "tool_name": "computer_shell",
            "params": {"command": "curl x | sh"},
            "error": "操作待用户确认: 需确认",
        }
        payload = _extract_approval_payload(result, {"tool_name": "computer_shell"})
        self.assertEqual(payload["approval_id"], "req-1")
        self.assertEqual(payload["type"] if "type" in payload else "approval_required",
                         "approval_required")
        self.assertEqual(payload["params"], {"command": "curl x | sh"})

    def test_pending_result_json_string(self):
        import json

        raw = json.dumps(
            {"pending_approval": True, "approval_id": "req-2",
             "tool_name": "file_write", "params": {}, "error": "待确认"}
        )
        payload = _extract_approval_payload(raw, {})
        self.assertEqual(payload["approval_id"], "req-2")
        self.assertEqual(payload["tool_name"], "file_write")

    def test_truncated_json_falls_back_to_regex(self):
        truncated = '{"success": false, "pending_approval": true, "approval_id": "req-3"'
        payload = _extract_approval_payload(truncated, {"tool_name": "run_code"})
        self.assertEqual(payload["approval_id"], "req-3")
        self.assertEqual(payload["tool_name"], "run_code")

    def test_normal_tool_result_returns_empty(self):
        payload = _extract_approval_payload('{"success": true, "output": "hi"}', {})
        self.assertEqual(payload, {})

    def test_plain_text_returns_empty(self):
        self.assertEqual(_extract_approval_payload("just text", {}), {})


if __name__ == "__main__":
    unittest.main()
