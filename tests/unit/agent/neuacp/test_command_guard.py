# -*- coding: utf-8 -*-
"""命令行守卫（CodeQL py/command-line-injection 处置）单元测试。

守卫语义：外部代理启动命令是管理员配置的 argv（名册本地直配层），经
subprocess.Popen（无 shell）拉起。argv 形态下真正的注入面是「命令头选
谁」——shell 解释器作头（bash -c / cmd /c / powershell -Command）等价于
把任意 shell 交到配置面手上，守卫必须在拉起前拒绝；直接指向目标 CLI
可执行文件（含自定义路径）的本地直配能力保留。
"""
import pytest

from neurova.agent.neuacp.command_guard import refuseCommandArgv


def test_emptyArgvRefused():
    assert refuseCommandArgv([]), "空 argv 必须拒绝"
    assert refuseCommandArgv(["  "]), "全空白 argv 必须拒绝"


def test_shellInterpreterHeadsRefused():
    for argv in (
        ["bash", "-c", "echo hi"],
        ["sh", "-c", "x"],
        ["zsh", "-c", "x"],
        ["cmd", "/c", "x"],
        ["powershell", "-Command", "x"],
        ["pwsh", "-Command", "x"],
        ["bash.exe", "-c", "x"],
        ["C:/Windows/System32/cmd.exe", "/c", "x"],
        ["wsl", "bash", "-c", "x"],
    ):
        assert refuseCommandArgv(argv), f"shell 解释器头必须拒绝: {argv}"


def test_directCliHeadsPass():
    assert not refuseCommandArgv(["opencode", "acp"])
    assert not refuseCommandArgv(["/usr/local/bin/my-agent", "--acp"])
    assert not refuseCommandArgv(["npx", "@tencent-ai/codebuddy-code", "--acp"])
    assert not refuseCommandArgv(["ssh", "host", "opencode"]), "ssh 不是 shell 解释器"


def test_nulByteRefused():
    assert refuseCommandArgv(["opencode\x00"]), "NUL 字节必须拒绝"


def test_reasonsNameTheHead():
    reasons = refuseCommandArgv(["bash", "-c", "x"])
    assert any("bash" in r for r in reasons)
