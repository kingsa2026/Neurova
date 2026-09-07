"""单元测试：测试 LLMConfigConsole（对齐 dict API 真实签名，2026-09-07 重写）

实现口径：
- add_provider(data: dict) -> str（必需 name/provider_type；返回 pid）
- update_provider(pid, fields: dict) -> bool / remove_provider(pid) -> bool
- update_default_params(fields) -> bool / get_default_params() -> dict
- get_provider_params(pid) / update_provider_params(pid, fields) / reset_provider_params(pid)
- record_token_usage(provider_id, model, prompt_tokens, completion_tokens, cost)
- get_token_usage_summary(provider_id=None) / reset_token_usage(provider_id=None) -> int
- get_stats() -> {providers, models, default_provider_id, selected_model, token}
"""

import os
import tempfile
import unittest

from neurova.llm.config_console import LLMConfigConsole


class TestLLMConfigConsole(unittest.TestCase):
    """测试 LLMConfigConsole（dict API 口径）"""

    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        )
        self.temp_path = self.temp_file.name
        self.temp_file.close()
        self.console = LLMConfigConsole(config_path=self.temp_path)

    def tearDown(self):
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)

    def _add(self, name="Test Provider", provider_type="openai", **extra):
        data = {"name": name, "provider_type": provider_type}
        data.update(extra)
        return self.console.add_provider(data)

    def test_list_providers(self):
        providers = self.console.list_providers()
        self.assertGreaterEqual(len(providers), 0)

    def test_add_provider(self):
        pid = self._add(name="Test Provider", base_url="https://api.openai.com/v1")
        record = self.console.get_provider(pid)
        self.assertIsNotNone(record)
        self.assertEqual(record["name"], "Test Provider")
        self.assertEqual(record["provider_type"], "openai")

    def test_add_provider_missing_required_raises(self):
        with self.assertRaises(ValueError):
            self.console.add_provider({"name": "NoType"})

    def test_update_provider(self):
        pid = self._add()
        ok = self.console.update_provider(pid, {"name": "Updated", "enabled": False})
        self.assertTrue(ok)
        record = self.console.get_provider(pid)
        self.assertEqual(record["name"], "Updated")
        self.assertFalse(record["enabled"])

    def test_remove_provider(self):
        pid = self._add()
        self.assertTrue(self.console.remove_provider(pid))
        self.assertIsNone(self.console.get_provider(pid))

    def test_get_default_params(self):
        params = self.console.get_default_params()
        self.assertIn("temperature", params)
        self.assertIn("top_p", params)
        self.assertIn("max_tokens", params)
        self.assertEqual(params["temperature"], 0.7)

    def test_update_default_params(self):
        ok = self.console.update_default_params({"temperature": 0.9, "max_tokens": 4096})
        self.assertTrue(ok)
        params = self.console.get_default_params()
        self.assertEqual(params["temperature"], 0.9)
        self.assertEqual(params["max_tokens"], 4096)

    def test_get_provider_params_defaults(self):
        pid = self._add()
        params = self.console.get_provider_params(pid)
        self.assertEqual(params["temperature"], 0.7)

    def test_update_provider_params(self):
        pid = self._add()
        ok = self.console.update_provider_params(pid, {"temperature": 0.5, "top_p": 0.8})
        self.assertTrue(ok)
        params = self.console.get_provider_params(pid)
        self.assertEqual(params["temperature"], 0.5)
        self.assertEqual(params["top_p"], 0.8)

    def test_reset_provider_params(self):
        pid = self._add()
        self.console.update_provider_params(pid, {"temperature": 0.5})
        self.console.reset_provider_params(pid)
        params = self.console.get_provider_params(pid)
        self.assertEqual(params["temperature"], 0.7)

    def test_record_token_usage_and_summary(self):
        pid = self._add()
        self.console.record_token_usage(
            provider_id=pid, model="gpt-4o",
            prompt_tokens=100, completion_tokens=50, cost=0.003,
        )
        summary = self.console.get_token_usage_summary(provider_id=pid)
        self.assertEqual(summary["total_requests"], 1)
        self.assertEqual(summary["total_prompt_tokens"], 100)

    def test_reset_token_usage(self):
        pid = self._add()
        self.console.record_token_usage(
            provider_id=pid, model="gpt-4o",
            prompt_tokens=10, completion_tokens=5,
        )
        removed = self.console.reset_token_usage(provider_id=pid)
        self.assertGreaterEqual(removed, 1)
        summary = self.console.get_token_usage_summary(provider_id=pid)
        self.assertEqual(summary["total_requests"], 0)

    def test_get_stats_shape(self):
        pid = self._add()
        stats = self.console.get_stats()
        for key in ("providers", "models", "default_provider_id", "selected_model", "token"):
            self.assertIn(key, stats)


if __name__ == "__main__":
    unittest.main()
