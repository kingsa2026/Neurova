"""协作中心 /stats 与 /sessions 端点测试。

修复前端 CollaborationHubPage 报告的两类问题：
- GET /api/v1/collaboration/stats 404 → 后端补齐真实统计
- GET /sessions（前端会话列表页调用）404 → 后端补齐
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _project(pid="p1", name="项目A", status_value="active", workflows=2):
    p = MagicMock()
    p.project_id = pid
    p.name = name
    p.description = "desc"
    status = MagicMock()
    status.value = status_value
    p.status = status
    p.created_at = 1700000000
    p.updated_at = 1700000001
    p.members = {"u1": "owner"}
    p.owner_id = "u1"
    p.metadata = {}
    return p


def _manager(projects):
    m = MagicMock()
    items = list(projects)

    def _list_projects(limit=None, offset=0, include_deleted=False):
        result = items[offset:]
        if limit is not None:
            result = result[:limit]
        return result

    m.list_projects.side_effect = _list_projects

    def _workflows(project_id, user_id=None):
        for proj in projects:
            if proj.project_id == project_id:
                return [MagicMock() for _ in range(getattr(proj, "_wf_count", 0))]
        return []

    m.list_project_workflows.side_effect = _workflows
    return m


class CollabEndpointsBase(unittest.TestCase):
    def setUp(self):
        from neurova.api.endpoints import collaboration_api

        self.module = collaboration_api
        self.client = TestClient(FastAPI())
        self.client.app.include_router(
            collaboration_api.router, prefix="/api/v1/collaboration"
        )


class TestStats(CollabEndpointsBase):
    def test_stats_returns_counts(self):
        active = _project("p1", status_value="active")
        active._wf_count = 2
        done = _project("p2", status_value="completed")
        done._wf_count = 3

        manager = _manager([active, done])
        with patch.object(self.module, "get_collaboration_manager", return_value=manager):
            resp = self.client.get("/api/v1/collaboration/stats")

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual(data["projects"], 2)
        self.assertEqual(data["templates"], 2)
        self.assertEqual(data["sessions"], 1)      # 仅 active 项目视为进行中的协作
        self.assertEqual(data["workflows"], 5)     # 各项目 workflow 总和

    def test_stats_empty_manager(self):
        with patch.object(self.module, "get_collaboration_manager",
                          return_value=_manager([])):
            resp = self.client.get("/api/v1/collaboration/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["projects"], 0)


class TestSessions(CollabEndpointsBase):
    def test_sessions_returns_array_data(self):
        """前端 store 直接把 data 当数组使用，必须是 JSON 数组。"""
        projects = [_project("p1"), _project("p2", status_value="completed")]
        with patch.object(self.module, "get_collaboration_manager",
                          return_value=_manager(projects)):
            resp = self.client.get("/api/v1/collaboration/sessions")

        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], "p1")
        self.assertIn("status", data[0])

    def test_sessions_respects_limit(self):
        manager = _manager([_project(f"p{i}") for i in range(5)])
        with patch.object(self.module, "get_collaboration_manager", return_value=manager):
            resp = self.client.get("/api/v1/collaboration/sessions?limit=3")
        self.assertEqual(len(resp.json()["data"]), 3)
        manager.list_projects.assert_called_with(limit=3, offset=0)


if __name__ == "__main__":
    unittest.main()
