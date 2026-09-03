"""Governance API 端点测试（白名单 CRUD + 审批批准重放/拒绝）。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.governance import router
from neurova.security.approval_manager import ApprovalManager


def _make_client(tmpdir: str) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    return TestClient(app)


class GovernanceEndpointTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.approvals = ApprovalManager(self.tmp)
        self.client = _make_client(self.tmp)

        patcher_am = patch(
            "neurova.api.endpoints.governance._get_approvals",
            return_value=self.approvals,
        )
        patcher_am.start()
        self.addCleanup(patcher_am.stop)

    def _patch_agent_and_executor(self):
        """隔离 Agent / ToolEngine，让重放走内置文件工具。"""
        agent = MagicMock()
        agent.user_id = "u1"
        agent.agent_id = "a1"
        patcher_agent = patch(
            "neurova.api.endpoints.governance._get_agent", return_value=agent
        )
        patcher_agent.start()
        self.addCleanup(patcher_agent.stop)

        self._orig_prop = None  # noqa: F841


class TestWhitelistEndpoints(GovernanceEndpointTestBase):
    def test_add_list_delete_roundtrip(self):
        resp = self.client.post(
            "/api/v1/governance/whitelist",
            json={"pattern": "npm run test", "match_type": "prefix", "note": "测试"},
        )
        self.assertEqual(resp.status_code, 200)
        entry_id = resp.json()["data"]["entry"]["id"]

        listing = self.client.get("/api/v1/governance/whitelist").json()
        patterns = [e["pattern"] for e in listing["data"]["entries"]]
        self.assertIn("npm run test", patterns)

        dele = self.client.delete(f"/api/v1/governance/whitelist/{entry_id}")
        self.assertEqual(dele.status_code, 200)
        self.assertEqual(dele.json()["code"], 0)

    def test_invalid_match_type_rejected(self):
        resp = self.client.post(
            "/api/v1/governance/whitelist",
            json={"pattern": "x", "match_type": "bogus"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_delete_unknown_returns_404(self):
        resp = self.client.delete("/api/v1/governance/whitelist/nope")
        self.assertEqual(resp.status_code, 404)


class TestApprovalEndpoints(GovernanceEndpointTestBase):
    def _create_request(self) -> str:
        req = self.approvals.create_approval_request(
            agent_id="a1",
            user_id="u1",
            command="cat note.txt",
            description="测试请求",
            danger_reason="测试",
            metadata={
                "tool_name": "file_read",
                "params": {"file_path": str(self._note_path)},
            },
        )
        return req.request_id

    def setUp(self):
        super().setUp()
        # 待读取的临时文件（重放执行 file_read 的目标）
        fd = Path(self.tmp) / "note.txt"
        fd.write_text("approved-content-123", encoding="utf-8")
        self._note_path = fd
        self._patch_agent_and_executor()

    def test_pending_list_contains_created_request(self):
        request_id = self._create_request()
        data = self.client.get("/api/v1/governance/approvals/pending").json()
        ids = [r["request_id"] for r in data["data"]["requests"]]
        self.assertIn(request_id, ids)

    def test_detail_endpoint(self):
        request_id = self._create_request()
        data = self.client.get(f"/api/v1/governance/approvals/{request_id}").json()
        self.assertEqual(data["data"]["request"]["request_id"], request_id)

    def test_unknown_request_404(self):
        resp = self.client.get("/api/v1/governance/approvals/ghost")
        self.assertEqual(resp.status_code, 404)

    def test_approve_replays_stored_tool_call(self):
        """核心链路: 批准 → 按 metadata 重放执行 → 返回真实结果。"""
        from neurova.tool_executor import ToolExecutor

        request_id = self._create_request()

        orig_prop = ToolExecutor.__dict__.get("tool_engine")
        ToolExecutor.tool_engine = property(lambda self: None)  # type: ignore[assignment]
        try:
            resp = self.client.post(
                f"/api/v1/governance/approvals/{request_id}/approve",
                json={"note": "确认执行", "approved_by": "user"},
            )
        finally:
            if orig_prop is not None:
                ToolExecutor.tool_engine = orig_prop  # type: ignore[assignment]
            elif "tool_engine" in ToolExecutor.__dict__:
                del ToolExecutor.__dict__["tool_engine"]

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()["data"]
        self.assertTrue(payload["approved"])
        self.assertTrue(payload["executed"])
        self.assertIn("approved-content-123", payload["result"]["content"])

        # 审批状态已更新为 approved
        req = self.approvals.get_request(request_id)
        self.assertEqual(req.status.value, "approved")

    def test_double_approve_conflict(self):
        request_id = self._create_request()
        # 第一次批准（无可执行内容场景不适用；直接重复批准第二个请求）
        self.client.post(
            f"/api/v1/governance/approvals/{request_id}/approve", json={}
        )
        second = self.client.post(
            f"/api/v1/governance/approvals/{request_id}/approve", json={}
        )
        self.assertEqual(second.status_code, 409)

    def test_reject_flow(self):
        request_id = self._create_request()
        resp = self.client.post(
            f"/api/v1/governance/approvals/{request_id}/reject",
            json={"note": "不需要"},
        )
        self.assertEqual(resp.status_code, 200)
        req = self.approvals.get_request(request_id)
        self.assertEqual(req.status.value, "rejected")


if __name__ == "__main__":
    unittest.main()
