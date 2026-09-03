"""
BE-CORE-011 (P0) 修复测试: CLI 工具命令注入漏洞

问题: neurova/tool_executor.py:375,376 将用户输入直接拼接到 shell 命令字符串，
未用 shlex.quote() 转义。manager.shell() 使用 subprocess.run(shell=True)，
导致 shell 元字符（; && | 等）被解释执行，构成命令注入漏洞。

攻击示例:
  args = {"query": "foo; rm -rf /"}
  拼接后: command --query=foo; rm -rf /
  shell=True 会执行两条命令: command --query=foo  和  rm -rf /

TDD RED 阶段: 本测试在 buggy 代码下应失败（恶意输入未转义）。
TDD GREEN 阶段: 修复后应通过。
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from neurova.tool_executor import ToolExecutor


def _make_executor():
    """构造一个 ToolExecutor 实例用于测试。"""
    mock_agent = MagicMock()
    return ToolExecutor(mock_agent)


def _capture_shell_command(executor, command, args):
    """执行 execute_cli_tool 并捕获传给 manager.shell() 的命令字符串。

    返回 (captured_command, result_dict)。
    """
    captured = {}

    def fake_shell(cmd, timeout=30):
        captured["command"] = cmd
        return {"returncode": 0, "stdout": "", "stderr": ""}

    mock_manager = MagicMock()
    mock_manager.shell = fake_shell

    with patch("neurova.computer_use.get_computer_use_manager", return_value=mock_manager):
        result = asyncio.run(executor.execute_cli_tool(command, args))

    return captured.get("command", ""), result


def test_shell_metacharacter_in_value_is_escaped():
    """args 值中的 shell 元字符应被转义，不能构成命令注入。"""
    executor = _make_executor()
    malicious_value = "foo; echo PWNED"

    captured_cmd, _ = _capture_shell_command(
        executor, "search", {"query": malicious_value}
    )

    # 恶意载荷不应以未转义形式出现（即不应有裸露的 "; echo PWNED"）
    # 修复后 shlex.quote 会将其包裹为单引号: 'foo; echo PWNED'
    assert "echo PWNED" in captured_cmd, "命令中应包含用户输入内容"
    # 关键断言: 不应存在未转义的命令分隔符导致注入
    # buggy 代码: search --query=foo; echo PWNED  （; 裸露，会执行 echo）
    # 修复代码: search --query='foo; echo PWNED' （; 被单引号包裹，安全）
    assert captured_cmd.count("'foo; echo PWNED'") == 1 or \
           captured_cmd.count('"foo; echo PWNED"') == 1, \
        f"恶意值应被引号包裹转义，实际命令: {captured_cmd}"


def test_command_injection_via_semicolon_in_command():
    """command 参数中的 shell 元字符应被转义。"""
    executor = _make_executor()
    malicious_command = "ls; rm -rf /"

    captured_cmd, _ = _capture_shell_command(
        executor, malicious_command, None
    )

    # buggy 代码: ls; rm -rf /  （直接执行，rm 会被运行）
    # 修复代码: 'ls; rm -rf /'  （整体作为一个命令名，安全）
    assert captured_cmd == "'ls; rm -rf /'" or \
           captured_cmd == '"ls; rm -rf /"', \
        f"恶意命令应被引号包裹转义，实际: {captured_cmd}"


def test_command_injection_via_pipe_in_value():
    """管道符注入也应被阻止。"""
    executor = _make_executor()
    malicious_value = "test | cat /etc/passwd"

    captured_cmd, _ = _capture_shell_command(
        executor, "tool", {"input": malicious_value}
    )

    # 管道符不应裸露执行
    assert "'test | cat /etc/passwd'" in captured_cmd or \
           '"test | cat /etc/passwd"' in captured_cmd, \
        f"管道注入应被转义，实际命令: {captured_cmd}"


def test_command_injection_via_backticks_in_value():
    """反引号命令替换注入应被阻止。"""
    executor = _make_executor()
    malicious_value = "test`whoami`"

    captured_cmd, _ = _capture_shell_command(
        executor, "tool", {"input": malicious_value}
    )

    # 反引号不应被解释执行
    assert "'test`whoami`'" in captured_cmd or \
           '"test`whoami`"' in captured_cmd, \
        f"反引号注入应被转义，实际命令: {captured_cmd}"


def test_normal_args_still_work_after_escape():
    """正常参数在转义后仍应正确传递。"""
    executor = _make_executor()
    captured_cmd, result = _capture_shell_command(
        executor, "search", {"query": "hello world", "limit": 5}
    )

    # 正常值应出现在命令中
    assert "hello world" in captured_cmd
    assert "5" in captured_cmd
    # 结果应正常返回
    assert result["success"] is True
    assert result["returncode"] == 0


def test_bool_args_preserved_after_escape():
    """布尔参数应保持 --flag 形式。"""
    executor = _make_executor()
    captured_cmd, _ = _capture_shell_command(
        executor, "tool", {"verbose": True, "quiet": False}
    )

    # True 的布尔参数应生成 --verbose
    assert "--verbose" in captured_cmd
    # False 的布尔参数不应出现
    assert "--quiet" not in captured_cmd
