"""进程环境配置助手回归测试。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neurova.core.config import get, get_bool, get_int, get_list, loadEnvFile, proxyUvicornArgs


class TestEnvironmentConfig(unittest.TestCase):
    def test_get_and_default(self):
        with patch.dict(os.environ, {"NEUROVA_TEST_VALUE": "configured"}, clear=True):
            self.assertEqual(get("NEUROVA_TEST_VALUE"), "configured")
            self.assertEqual(get("NEUROVA_TEST_MISSING", "fallback"), "fallback")

    def test_typed_values(self):
        with patch.dict(
            os.environ,
            {
                "NEUROVA_TEST_INT": "42",
                "NEUROVA_TEST_BAD_INT": "not-an-int",
                "NEUROVA_TEST_BOOL": "YES",
                "NEUROVA_TEST_LIST": " alpha, beta ,, gamma ",
            },
            clear=True,
        ):
            self.assertEqual(get_int("NEUROVA_TEST_INT"), 42)
            self.assertEqual(get_int("NEUROVA_TEST_BAD_INT", 7), 7)
            self.assertTrue(get_bool("NEUROVA_TEST_BOOL"))
            self.assertEqual(get_list("NEUROVA_TEST_LIST"), ["alpha", "beta", "gamma"])

    def test_proxy_args_use_forwarded_allowlist(self):
        with patch.dict(
            os.environ,
            {"NEUROVA_FORWARDED_ALLOW_IPS": "127.0.0.1, 10.0.0.1"},
            clear=True,
        ):
            args = proxyUvicornArgs()
            self.assertTrue(args["proxy_headers"])
            self.assertEqual(args["forwarded_allow_ips"], "127.0.0.1,10.0.0.1")

    def test_load_env_file(self):
        if loadEnvFile() is False:
            self.skipTest("python-dotenv 未安装")
        with tempfile.TemporaryDirectory() as directory:
            envPath = Path(directory) / ".env"
            envPath.write_text("NEUROVA_TEST_DOTENV=loaded\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(loadEnvFile(envPath))
                self.assertEqual(os.environ.get("NEUROVA_TEST_DOTENV"), "loaded")


if __name__ == "__main__":
    unittest.main()
