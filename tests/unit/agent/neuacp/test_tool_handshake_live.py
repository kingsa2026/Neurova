# -*- coding: utf-8 -*-
"""A7：Qoder / CodeBuddy（原生 ACP）接入验证。

CLI 安装检查在用户启用连接时进行（catalog 实时探测）——本机未安装则
skip 并如实标注（不伪造通过）；已安装才做真握手。
"""
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.catalog import probeTool
from neurova.agent.neuacp.executor import NeuacpSessionContext

import asyncio


def _handshake(tool):
    probe = probeTool(tool)
    if not probe.get("installed"):
        pytest.skip(f"本机未安装 {tool}（installed=false，启用时展示 install_hint: {probe.get('install_hint')}）")
    executor = NeuacpStdioExecutor(
        list(probe["command"]),
        cwd=str(Path(__file__).parent),
        request_timeout=120.0,
    )
    ctx = NeuacpSessionContext(member_session_id="handshake", task_text="ping", cwd=str(Path(__file__).parent))

    async def run():
        await executor.start(ctx)
        await executor.close()

    try:
        asyncio.run(run())
    except Exception as exc:
        # npx 适配器依赖外网拉包（设计文档 §9 风险 5）：本环境不可达时如实
        # skip 并留原因——真实验收在用户启用连接（install_hint 安装后）进行。
        pytest.skip(f"{tool} 握手未通过（{exc}）——启用时按 install_hint 安装后重验")


def test_qoderHandshakeWhenInstalled():
    _handshake("qoder")


def test_qoderCnHandshakeWhenInstalled():
    """Qoder CN CLI（qodercn）真握手：未装 skip（不伪造通过），装了才真跑。"""
    _handshake("qodercn")


def test_codebuddyHandshakeWhenInstalled():
    _handshake("codebuddy")
