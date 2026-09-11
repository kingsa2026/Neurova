# -*- coding: utf-8 -*-
"""P1-9 防回归：整工作区 zip 打包不得阻塞事件循环。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md RES-P1-9）：
``GET /workspace/{agent}/files/zip`` 的 rglob 遍历 + ZIP_DEFLATE 压缩
整段同步跑在事件循环线程上，大工作区（几百 MB）时全站请求/SSE/WS 卡顿
数十秒；内存峰值 ≈ 原大小 + 压缩包大小（StreamingResponse 只是壳）。

修复：rglob+压缩段抽成模块级同步函数 ``_zip_directory``，
``await asyncio.to_thread(...)`` 执行；StreamingResponse 契约不变。
本测试以线程身份断言打包运行在事件循环线程之外，并锁定 zip 内容契约。
"""

import asyncio
import io
import threading
import zipfile

import pytest
from fastapi.responses import StreamingResponse

from neurova.api.endpoints import workspace_files as wf


@pytest.fixture
def ws_env(tmp_path, monkeypatch):
    """工作区根锚定 tmp_path（防污染真实 agent_workspaces）。"""
    root = tmp_path / "agent_workspaces"
    root.mkdir()
    monkeypatch.setattr(wf, "_WORKSPACES_ROOT", root)
    return root


def _make_workspace(root, agent_id="w1"):
    agent_dir = root / agent_id
    (agent_dir / "sub").mkdir(parents=True)
    (agent_dir / "a.txt").write_text("hello", encoding="utf-8")
    (agent_dir / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")
    (agent_dir / ".hidden").write_text("secret", encoding="utf-8")
    return agent_dir


def test_zip_directory_contract(ws_env):
    """_zip_directory 内容契约：arcname 相对、隐藏文件剔除、zip 可解。"""
    agent_dir = _make_workspace(ws_env)

    buf = wf._zip_directory(agent_dir)

    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
    assert names == {"a.txt", "sub/b.bin"}, f"zip 条目契约被破坏: {names}"


def test_download_zip_offloads_compression_from_event_loop(ws_env, monkeypatch):
    """打包段必须经 to_thread 在工作线程执行（原缺陷：整段跑在事件循环上）。"""
    agent_dir = _make_workspace(ws_env)
    main_thread = threading.get_ident()
    seen = {}
    real = wf._zip_directory

    def spy(target):
        seen["thread"] = threading.get_ident()
        return real(target)

    monkeypatch.setattr(wf, "_zip_directory", spy)

    async def main():
        return await wf.download_workspace_zip(
            agent_id="w1", subdir="", current_user={"user_id": "u1"}
        )

    resp = asyncio.run(main())

    assert seen["thread"] != main_thread, (
        "zip 打包（rglob+DEFLATE）仍在事件循环线程执行（P1-9 未修复）"
    )
    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert "w1" in resp.headers["content-disposition"]

    # StreamingResponse 背后就是打包好的 BytesIO：内容契约不变
    async def drain(resp):
        return b"".join([chunk async for chunk in resp.body_iterator])

    body = asyncio.run(drain(resp))
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert set(zf.namelist()) == {"a.txt", "sub/b.bin"}
    assert agent_dir.is_dir(), "打包不得改动工作区本身"
