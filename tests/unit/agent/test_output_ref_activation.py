"""OutputRef env 门控激活单元测试。

锁定契约：ensure_output_ref_installed_from_env()
- NEUROVA_TOOL_OUTPUT_REF 未设或 != "0" → 装配（幂等）；
- =="0" → 不装配（卸载既有句柄）。
"""

import unittest
from unittest import mock

from neurova.agent import tool_output_ref


class TestOutputRefEnvActivation(unittest.TestCase):
    def tearDown(self):
        tool_output_ref.uninstall_tool_output_ref(force=True)

    def test_default_on(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            tool_output_ref.ensure_output_ref_installed_from_env()
            self.assertIsNotNone(tool_output_ref.get_installed_output_ref())

    def test_explicit_off(self):
        with mock.patch.dict("os.environ", {"NEUROVA_TOOL_OUTPUT_REF": "0"}):
            tool_output_ref.ensure_output_ref_installed_from_env()
            self.assertIsNone(tool_output_ref.get_installed_output_ref())

    def test_explicit_on(self):
        with mock.patch.dict("os.environ", {"NEUROVA_TOOL_OUTPUT_REF": "1"}):
            tool_output_ref.ensure_output_ref_installed_from_env()
            self.assertIsNotNone(tool_output_ref.get_installed_output_ref())


if __name__ == "__main__":
    unittest.main()
