"""C-22 回归测试：沙箱超时必须杀灭整棵进程树。

缺陷：subprocess.run(timeout=) 超时只杀直接子进程（sh/cmd），孙进程残留。
修复：POSIX 用 start_new_session=True + os.killpg(SIGKILL)；
Windows 用 taskkill /T /F 杀进程树。
"""

import subprocess
import sys
import time

import pytest

from neurova.sandbox.exec_sandbox import ExecSandbox

WINDOWS = sys.platform == "win32"

#: 系统查询件（`taskkill`／`tasklist`／`pgrep`）的预算唯一出处（§6-402 批 K 口径）。
#: 三枚落点此前都没有 `timeout=`＝无界等待：`tasklist` 在进程表拥挤时可慢，但真挂住时
#: 全局 30s 那道墙先到，Windows 侧 thread 法终止的是**整个跑测进程**——报出来是
#: "整场跑测没了"，而不是这条本该红在这里的断言。20s 留足系统件的正常返回窗口。
SYSTEM_TOOL_WALL_S = 20


def test_normal_command_still_returns_contract():
    sandbox = ExecSandbox()
    result = sandbox.execute("echo hello")
    assert result["success"] is True
    assert "hello" in result["output"]
    assert result["return_code"] == 0
    assert result["sandbox"] == "process"


@pytest.mark.skipif(not WINDOWS, reason="Windows 平台进程树用例")
def test_windows_timeout_kills_grandchild():
    # 预清理：确保起点无 ping 残留
    subprocess.run(["taskkill", "/F", "/IM", "ping.exe"], capture_output=True,
                   timeout=SYSTEM_TOOL_WALL_S)

    sandbox = ExecSandbox()
    # cmd /c 包一层 → ping.exe 是 Popen(cmd) 的孙进程；
    # 旧实现超时只杀 cmd，ping 会继续跑 ~30s
    result = sandbox.execute("ping -n 30 127.0.0.1 > NUL", timeout=2.0)

    assert result["success"] is False
    assert "timed out" in result["error"]
    assert result["return_code"] == -1

    time.sleep(0.5)
    # tasklist 输出为本地代码页（GBK），显式按字节读再解码，避免编码崩溃
    listing = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq ping.exe"],
        capture_output=True,
        timeout=SYSTEM_TOOL_WALL_S,
    ).stdout.decode("gbk", errors="replace").lower()
    assert "ping.exe" not in listing


@pytest.mark.skipif(WINDOWS, reason="POSIX 平台进程组用例")
def test_posix_timeout_kills_grandchild():
    sandbox = ExecSandbox()
    # sh -c 包一层 → sleep 是 Popen(sh) 的孙进程；
    # 旧实现超时只杀 sh，sleep 残留 30s
    result = sandbox.execute("sleep 30 & wait", timeout=1.5)

    assert result["success"] is False
    assert "timed out" in result["error"]

    time.sleep(0.5)
    probe = subprocess.run(
        ["pgrep", "-f", "sleep 30"], capture_output=True, text=True,
        timeout=SYSTEM_TOOL_WALL_S,
    )
    assert probe.stdout.strip() == ""
