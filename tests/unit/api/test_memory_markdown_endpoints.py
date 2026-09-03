"""记忆 Markdown 导出/导入端点测试（P1-2.2 前端闭环的后端部分）。

GET  /api/v1/memory/markdown        → 可读 Markdown
POST /api/v1/memory/markdown        → 解析编辑后的 Markdown，版本化 diff 写回文本层
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _memory(mid="mem-001", content="用户喜欢简洁的回复", category="preference"):
    m = MagicMock()
    m.id = mid
    m.content = content
    m.category = category
    m.importance = 0.8
    m.temperature = 0.5
    m.lifecycle_stage = "active"
    m.created_at = "2026-08-01T10:00:00"
    m.updated_at = "2026-08-02T11:00:00"
    m.access_count = 3
    return m


def _make_manager():
    manager = MagicMock()
    manager.get_memories.return_value = [_memory()]
    current = _memory()
    manager.get_memory.return_value = current

    def _update(memory_id, **kwargs):
        current.content = kwargs.get("content", current.content)
        return True

    manager.update_memory.side_effect = _update
    return manager, current


def _make_client(manager) -> TestClient:
    from neurova.api.auth import get_current_user_or_default
    from neurova.api.endpoints.memory import router as memory_router

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/v1/memory")
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "neuser_id": "ne-test",
        "user_id": "u-test",
    }
    client = TestClient(app)
    return client


class TestMemoryMarkdownEndpoints(unittest.TestCase):
    def setUp(self):
        self.manager, self.current = _make_manager()
        self._patcher = patch(
            "neurova.api.endpoints.memory.markdown.get_memory_manager",
            return_value=self.manager,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.client = _make_client(self.manager)

    def test_get_markdown_returns_readable_export(self):
        resp = self.client.get("/api/v1/memory/markdown")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        md = data["markdown"]
        self.assertIn("# Neurova 记忆导出", md)
        self.assertIn("mem-001", md)
        self.assertIn("用户喜欢简洁的回复", md)

    def test_get_markdown_supports_category_and_limit(self):
        resp = self.client.get("/api/v1/memory/markdown?category=work&limit=5")
        self.assertEqual(resp.status_code, 200)
        self.manager.get_memories.assert_called_with(category="work", limit=5)

    def test_post_edited_markdown_updates_text_layer_only(self):
        # 先取导出，再模拟用户编辑正文
        export = self.client.get("/api/v1/memory/markdown").json()["data"]["markdown"]
        edited = export.replace("用户喜欢简洁的回复", "用户偏好要点式回复")

        resp = self.client.post(
            "/api/v1/memory/markdown", json={"markdown": edited}
        )
        self.assertEqual(resp.status_code, 200)
        stats = resp.json()["data"]["stats"]
        self.assertEqual(stats["updated"], 1)
        # 关键约束：只写 content 文本层，不触碰向量/embedding
        _, kwargs = self.manager.update_memory.call_args
        self.assertEqual(kwargs.get("content"), "用户偏好要点式回复")
        self.assertNotIn("embedding", kwargs)

    def test_post_unmodified_returns_zero_updates(self):
        export = self.client.get("/api/v1/memory/markdown").json()["data"]["markdown"]
        resp = self.client.post("/api/v1/memory/markdown", json={"markdown": export})
        stats = resp.json()["data"]["stats"]
        self.assertEqual(stats["updated"], 0)
        self.assertEqual(stats["unchanged"], 1)

    def test_post_strict_version_detects_conflict(self):
        export = self.client.get("/api/v1/memory/markdown").json()["data"]["markdown"]
        edited = export.replace("用户喜欢简洁的回复", "并发编辑内容")
        # 模拟另一端已更新该记忆（updated_at 变化）
        newer = _memory(content="已被其他会话修改")
        newer.updated_at = "2026-08-09T00:00:00"
        self.manager.get_memory.return_value = newer

        resp = self.client.post(
            "/api/v1/memory/markdown",
            json={"markdown": edited, "strict_version": True},
        )
        stats = resp.json()["data"]["stats"]
        self.assertEqual(stats.get("conflicts"), 1)
        self.assertEqual(stats.get("updated", 0), 0)


if __name__ == "__main__":
    unittest.main()
