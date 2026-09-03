"""
测试：from-nl 端点三层隔离权限（R-8/R-9 合规补丁）

契约:
  1. JWT 用户无该 agent 权限（非 owner 且非 admin）→ 403
  2. 有权限 → 走 generate_canvas_from_nl 并透传 agent_id
  3. prompt 为空 → 400
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import collaboration_api as mod


class TestFromNlIsolation:
    def _run(self, body, current_user):
        async def coro():
            request = type("R", (), {})()
            return await mod.canvas_from_nl(request, body, current_user=current_user)

        return asyncio.run(coro())

    def test_no_permission_403(self):
        """非 owner 且非 admin 指定他人 agent → 403。"""
        user = {"user_id": "u-999", "role": "user"}
        with patch("neurova.api.endpoints.chat._user_can_access_agent", return_value=False):
            with pytest.raises(HTTPException) as excinfo:
                self._run({"prompt": "设计", "agent_id": "kai"}, user)
        assert excinfo.value.status_code == 403

    def test_owner_allowed(self):
        """owner 权限 → generate 执行并透传 agent_id。"""
        user = {"user_id": "u-1", "role": "user"}
        with patch("neurova.api.endpoints.chat._user_can_access_agent", return_value=True):
            with patch(
                "neurova.collaboration.neurflow.nl_designer.generate_canvas_from_nl",
                new=AsyncMock(
                    return_value={
                        "status": "success",
                        "data": {"nodes": [], "edges": [], "name": "x", "description": ""},
                    }
                ),
            ) as gen:
                res = self._run({"prompt": "设计流程", "agent_id": "default", "model": "glm-4"}, user)
        gen.assert_called_once_with("设计流程", agent_id="default", model="glm-4")
        assert res["code"] == 0

    def test_prompt_empty_400(self):
        with patch("neurova.api.endpoints.chat._user_can_access_agent", return_value=True):
            with pytest.raises(HTTPException) as excinfo:
                self._run(
                    {"prompt": "  ", "agent_id": "default"},
                    {"user_id": "u-1", "role": "user"},
                )
        assert excinfo.value.status_code == 400
