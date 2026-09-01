"""内核级执行沙箱 (exec_sandbox) 单元测试。

对齐升级方案 P0-1.1：跨平台 SandboxBackend 抽象、severity 四级、平台自动降级。
验收标准（方案 1.1）：沙箱能隔离一次越权文件访问（在支持的后端上验证包装语义）。
"""

import sys
import unittest
from unittest.mock import patch

from neurova.sandbox.exec_sandbox import (
    AppContainerSandbox,
    BubblewrapSandbox,
    ExecSandbox,
    ProcessSandbox,
    SandboxSeverity,
    SeatbeltSandbox,
    execute_in_sandbox,
    get_exec_sandbox,
    reset_exec_sandbox,
)


class TestSandboxSeverity(unittest.TestCase):
    """severity 等级定义（方案 1.1: none/network-off/read-only/full）。"""

    def test_four_levels_exist(self):
        self.assertEqual(SandboxSeverity.NONE.value, "none")
        self.assertEqual(SandboxSeverity.NETWORK_OFF.value, "network_off")
        self.assertEqual(SandboxSeverity.READ_ONLY.value, "read_only")
        self.assertEqual(SandboxSeverity.FULL.value, "full")


class TestBackendDetection(unittest.TestCase):
    """按 OS 自动选择后端；始终可降级。"""

    def setUp(self):
        reset_exec_sandbox()

    def tearDown(self):
        reset_exec_sandbox()

    def test_none_severity_uses_process_sandbox(self):
        sandbox = get_exec_sandbox(SandboxSeverity.NONE)
        self.assertIsInstance(sandbox, ProcessSandbox)

    @unittest.skipUnless(sys.platform == "win32", "Windows 专属")
    def test_windows_uses_restricted_token_or_process_honestly(self):
        """P1-7+P2：AppContainer 未实现；Windows 给 SAFER 受限令牌（特权剥离）
        或裸 ProcessSandbox（SAFER 不可达兜底），绝不返回说谎的 AppContainer"""
        sandbox = get_exec_sandbox(SandboxSeverity.READ_ONLY)
        from neurova.sandbox.exec_sandbox import AppContainerSandbox

        self.assertNotIsInstance(sandbox, AppContainerSandbox)
        self.assertIn(sandbox.backend_name(), ("restricted_token", "process"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux 专属")
    def test_linux_bubblewrap_when_available(self):
        from neurova.sandbox.exec_sandbox import BubblewrapSandbox

        if not BubblewrapSandbox().available():
            self.skipTest("bwrap 未安装")
        sandbox = get_exec_sandbox(SandboxSeverity.FULL)
        self.assertIsInstance(sandbox, BubblewrapSandbox)

    def test_cache_returns_same_instance(self):
        first = get_exec_sandbox(SandboxSeverity.READ_ONLY)
        second = get_exec_sandbox(SandboxSeverity.READ_ONLY)
        self.assertIs(first, second)

    def test_different_severity_gets_different_backend(self):
        none_sandbox = get_exec_sandbox(SandboxSeverity.NONE)
        ro_sandbox = get_exec_sandbox(SandboxSeverity.READ_ONLY)
        self.assertIsNot(none_sandbox, ro_sandbox)


class TestBubblewrapWrapSemantics(unittest.TestCase):
    """Linux 后端的命令包装语义（不要求本机安装 bwrap）。"""

    def test_wrap_adds_unshare_net_for_network_off(self):
        sandbox = BubblewrapSandbox(SandboxSeverity.NETWORK_OFF)
        wrapped = sandbox.wrap_argv("echo hi")
        self.assertIn("--unshare-net", wrapped)
        self.assertIn("echo hi", wrapped)

    def test_wrap_full_severity_isolates_network(self):
        sandbox = BubblewrapSandbox(SandboxSeverity.FULL)
        wrapped = sandbox.wrap_argv("cat /etc/passwd")
        self.assertIn("--unshare-net", wrapped)

    def test_wrap_read_only_keeps_network(self):
        sandbox = BubblewrapSandbox(SandboxSeverity.READ_ONLY)
        wrapped = sandbox.wrap_argv("echo hi")
        self.assertNotIn("--unshare-net", wrapped)

    def test_wrap_passes_command_as_single_argv_no_escaping_layer(self):
        """现行契约：command 作为单个 argv 传递（引号转义由 shell 内语义处理，
        argv 层不做转义——docstring 明确"消除引号转义层"）"""
        sandbox = BubblewrapSandbox(SandboxSeverity.NONE)
        wrapped = sandbox.wrap_argv('echo "hello world"')
        self.assertIn('echo "hello world"', wrapped)


class TestSeatbeltWrapSemantics(unittest.TestCase):
    """macOS 后端的命令包装语义。"""

    def test_profile_denies_network_when_network_off(self):
        sandbox = SeatbeltSandbox(SandboxSeverity.NETWORK_OFF)
        wrapped = sandbox.wrap_argv("curl https://x.example.com")
        self.assertIn("(deny network*)", " ".join(wrapped))

    def test_read_only_allows_network(self):
        sandbox = SeatbeltSandbox(SandboxSeverity.READ_ONLY)
        wrapped = sandbox.wrap_argv("ls")
        self.assertNotIn("(deny network*)", wrapped)


class TestExecution(unittest.TestCase):
    """执行结果契约：与 CLIToolExecutor 兼容的字典。"""

    def _assert_result_shape(self, result):
        self.assertIsInstance(result, dict)
        for key in ("success", "output", "error", "return_code", "sandbox"):
            self.assertIn(key, result)

    def test_process_sandbox_runs_echo(self):
        result = ProcessSandbox().execute("echo sandbox-ok")
        self._assert_result_shape(result)
        self.assertTrue(result["success"])
        self.assertIn("sandbox-ok", result["output"])

    def test_process_sandbox_timeout(self):
        result = ProcessSandbox().execute("sleep 5", timeout=1)
        self._assert_result_shape(result)
        self.assertFalse(result["success"])

    def test_execute_in_sandbox_convenience(self):
        result = execute_in_sandbox("echo via-convenience")
        self._assert_result_shape(result)
        self.assertTrue(result["success"])

    def test_result_tags_backend_name(self):
        result = ProcessSandbox().execute("echo hi")
        self.assertEqual(result["sandbox"], "process")

    def test_appcontainer_degrades_gracefully_on_windows(self):
        """方案风险对策: Windows 无内核隔离时降级为常规执行并标注后端。"""
        if sys.platform != "win32":
            self.skipTest("Windows 专属")
            return
        sandbox = AppContainerSandbox(SandboxSeverity.FULL)
        result = sandbox.execute("echo degraded")
        self._assert_result_shape(result)
        self.assertEqual(result["sandbox"], "appcontainer")


class TestBaseClassContract(unittest.TestCase):
    """ExecSandbox 基类契约。"""

    def test_base_execute_returns_contract_dict(self):
        result = ExecSandbox().execute("true")
        for key in ("success", "output", "error", "return_code", "sandbox"):
            self.assertIn(key, result)

    def test_base_default_backend_name(self):
        self.assertEqual(ExecSandbox().backend_name(), "process")


if __name__ == "__main__":
    unittest.main()
