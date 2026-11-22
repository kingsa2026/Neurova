# -*- coding: utf-8 -*-
"""U20 配套：write_pdf 产物属主登记（红→绿）。

契约（U20 配套小卡）：write_pdf 落产物目录时向生成账本登记属主——
``owner_user_id``=当前请求用户**原始 id**（与 browser_manager.
resolveBrowserOwnerKey 同取数口径，但不用池化键：登记池化键会使属主本人
403 的命名空间错位）、``session_id``=当前轮会话、``kind``="write_pdf"；
无用户上下文保持既有不登记行为（登录即可读，向后兼容）。

红（现网行为）：A 用户 write_pdf 产物未登记属主，B 用户经 serve 端
（GET /api/v1/generation/files/{name}）可读（200）。
绿：登记属主后 A 200、B 403（admin 200）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.core.identity_context import (  # noqa: E402
    clear_request_user_id,
    set_request_user_id,
)
from neurova.tool_executor import ToolExecutor  # noqa: E402

USER_A = "900101"
USER_B = "900202"


def _makeExecutor(user_id: str = "") -> ToolExecutor:
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id=user_id or "u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


def _serveClient(user_id: str, role: str = "user") -> TestClient:
    from neurova.api.deps import get_current_user
    from neurova.api.endpoints import generation

    app = FastAPI()
    app.include_router(generation.router, prefix="/api/v1/generation")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user_id, "username": f"u{user_id}", "role": role}
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def identityA():
    set_request_user_id(USER_A)
    yield USER_A
    clear_request_user_id()


@pytest.fixture
def writtenByA(identityA):
    """A 用户 write_pdf 一份产物（真实渲染落盘 + 账本登记）。"""
    executor = _makeExecutor(user_id=USER_A)
    result = asyncio_run(executor._execute_write_pdf({
        "content": "# 属主登记\n\n正文一段。",
        "title": "owner-probe",
    }))
    assert result.get("file_name"), f"write_pdf 应出件: {result}"
    return str(result["file_name"]), str(result["file_path"])


def asyncio_run(coro):
    import asyncio

    return asyncio.new_event_loop().run_until_complete(coro)


class TestWritePdfOwnerRegistration:
    @pytest.mark.asyncio
    async def test_write_pdfRegistersRawUidOwner(self, identityA):
        """绿判据：write_pdf 登记原始 uid 属主 + 会话 + kind。"""
        from neurova.llm.generators.task_ledger import get_generation_task_ledger

        executor = _makeExecutor(user_id=USER_A)
        result = await executor._execute_write_pdf({
            "content": "# t\n\nx", "title": "reg-probe"})
        name = result["file_name"]
        records = [t for t in get_generation_task_ledger().list()
                   if Path(t.local_path).name == name]
        assert records, f"产物应在生成账本登记: {result}"
        record = records[-1]
        assert record.owner_user_id == USER_A, (
            f"属主必须是原始 uid（非池化键）: {record.owner_user_id}")
        assert record.kind == "write_pdf", f"kind 应点名工具: {record.kind}"

    def test_serveOwnerCanReadStrangerForbidden(self, writtenByA):
        """绿判据：A 200、B 403（admin 200）。"""
        name, _path = writtenByA
        with _serveClient(USER_A) as client:
            assert client.get(f"/api/v1/generation/files/{name}").status_code == 200, (
                "属主本人必须可读（登记原始 uid 的意义所在）")
        with _serveClient(USER_B) as client:
            resp = client.get(f"/api/v1/generation/files/{name}")
            assert resp.status_code == 403, (
                f"非属主读取必须 403（登记前是 200）: {resp.status_code}")
        with _serveClient("900300", role="admin") as client:
            assert client.get(f"/api/v1/generation/files/{name}").status_code == 200, (
                "admin 仍可读")

    @pytest.mark.asyncio
    async def test_noUserContextKeepsLegacyUnregistered(self):
        """无用户上下文（agent 自主任务）保持既有不登记行为（登录即可读）。"""
        clear_request_user_id()
        from neurova.llm.generators.task_ledger import get_generation_task_ledger

        executor = _makeExecutor()
        result = await executor._execute_write_pdf({
            "content": "# legacy\n\nx", "title": "no-owner-probe"})
        name = result["file_name"]
        records = [t for t in get_generation_task_ledger().list()
                   if Path(t.local_path).name == name]
        assert not records, "无用户上下文不得登记属主（既有行为）"
        with _serveClient(USER_B) as client:
            assert client.get(f"/api/v1/generation/files/{name}").status_code == 200, (
                "无主存量产物保持登录即可读（向后兼容）")
