"""
mcp_config 安全门红测（P0-1）

shell 拒绝表：stdio MCP server 的 command 是 argv[0]（无 shell 注入面），
但显式以 shell 作为 server 进程等于把任意命令执行敞开。解释器类
（npx/python 本身就能跑任意代码）不做白名单——那是安全剧场；
进程派生的权限边界由 API 层角色校验承担（stdio 仅限 admin）。
"""

import pytest

from neurova.tool_layers.mcp_config import validate_mcp_server_config


class TestShellDenylist:
    @pytest.mark.parametrize(
        "command",
        ["sh", "bash", "zsh", "fish", "csh", "tcsh", "ksh",
         "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "wsl", "wsl.exe"],
    )
    def test_shell_commands_rejected(self, command):
        with pytest.raises(ValueError, match="shell"):
            validate_mcp_server_config({"id": "s", "command": command, "args": ["-c", "id"]})

    def test_shell_absolute_path_rejected(self):
        with pytest.raises(ValueError, match="shell"):
            validate_mcp_server_config({"id": "s", "command": "/bin/bash", "args": ["-lc", "id"]})

    @pytest.mark.parametrize("command", ["npx", "node", "python", "python3", "uvx", "pipx", "bun", "deno"])
    def test_interpreters_still_allowed(self, command):
        cfg = validate_mcp_server_config({"id": "s", "command": command})
        assert cfg["command"] == command

    def test_windows_suffix_normalized(self):
        # bash.exe 在 Windows 上也是 shell，拒绝表按去后缀的 basename 匹配
        with pytest.raises(ValueError, match="shell"):
            validate_mcp_server_config({"id": "s", "command": "bash.exe"})

    def test_absolute_path_to_regular_binary_allowed(self, tmp_path):
        exe = tmp_path / "my-mcp-server.exe"
        exe.write_bytes(b"")
        cfg = validate_mcp_server_config({"id": "s", "command": str(exe)})
        assert cfg["command"] == str(exe)

    def test_url_only_config_unaffected(self):
        # 无 command 的 http 配置不触发 shell 检查（URL 私网门在 API 层按角色执行）
        cfg = validate_mcp_server_config({"id": "s", "url": "http://example.com/mcp"})
        assert cfg["transport"] == "http"

    def test_field_errors_still_surface_before_shell_check(self):
        # 类型错误优先于 shell 检查（保持既有 match= 契约）
        with pytest.raises(ValueError, match="args"):
            validate_mcp_server_config({"id": "s", "command": "bash", "args": "-c"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
