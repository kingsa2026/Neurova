"""
TDD RED-GREEN: pycryptodome 依赖的显式 fail-fast 机制

背景:
    secret_store.py 是 pycryptodome (Crypto 模块) 的唯一消费者,但使用懒导入
    (在 _aes_gcm_encrypt / _aes_gcm_decrypt 函数体内 `from Crypto.Cipher import AES`)。
    pycryptodome 缺失时:
      1. decrypt_api_key 抛 ValueError("AES-GCM decryption failed: No module named 'Crypto'")
      2. ProviderConfig.from_dict catch 后 logger.warning (非 ERROR,易被忽略)
      3. 静默创建 api_key=None 的 ProviderConfig
      4. 整个 LLM 链路瘫痪,但服务器日志显示 "Loaded 5 providers" (误导性成功)

测试目标:
    - RED:   验证当前实现没有 fail-fast 机制 (测试失败)
    - GREEN: 修改 secret_store.py + provider_manager.py 后所有测试通过

测试用例:
    1. test_has_crypto_flag_set_when_installed: Crypto 可导入时 HAS_CRYPTO=True
    2. test_has_crypto_flag_false_when_missing:        mock Crypto 不可导入时 HAS_CRYPTO=False
    3. test_decrypt_raises_runtime_error_when_no_crypto: mock HAS_CRYPTO=False, decrypt_api_key 抛 RuntimeError
    4. test_encrypt_raises_runtime_error_when_no_crypto: mock HAS_CRYPTO=False, encrypt_api_key 抛 RuntimeError
    5. test_fail_fast_message_includes_install_hint:     错误消息包含 "pip install pycryptodome"
    6. test_provider_manager_logs_error_on_decrypt_failure: 验证 provider_manager 解密失败时用 ERROR 级别

运行:
    cd e:\\项目\\Neurova
    python -m unittest tests.unit.llm.test_pycryptodome_failfast -v
"""

import importlib
import logging
import sys
import unittest
from unittest.mock import patch


# -----------------------------------------------------------------------------
# 辅助函数
# -----------------------------------------------------------------------------


def _reload_secret_store():
    """重新加载 secret_store 模块,以便 HAS_CRYPTO 标志按当前环境重新计算"""
    import neurova.llm.providers.secret_store as ss
    importlib.reload(ss)
    return ss


# -----------------------------------------------------------------------------
# 测试类
# -----------------------------------------------------------------------------


class TestPycryptodomeFailFast(unittest.TestCase):
    """pycryptodome 缺失时的 fail-fast 行为测试"""

    def setUp(self):
        """每个测试前确保 secret_store 处于真实环境状态"""
        # 重新加载一次,避免前面测试的 mock 状态残留
        self.ss = _reload_secret_store()

    # -------------------------------------------------------------------------
    # 1. HAS_CRYPTO 标志存在性
    # -------------------------------------------------------------------------

    def test_has_crypto_flag_exists(self):
        """模块必须暴露 HAS_CRYPTO 布尔标志(无论 True 或 False)"""
        self.assertTrue(
            hasattr(self.ss, "HAS_CRYPTO"),
            "secret_store 必须暴露 HAS_CRYPTO 模块级标志",
        )

    def test_has_crypto_flag_set_when_installed(self):
        """当 Crypto 可导入时,HAS_CRYPTO 应为 True"""
        # 试图导入 Crypto.Cipher.AES,判断本机是否安装了 pycryptodome
        crypto_available = True
        try:
            import Crypto.Cipher.AES  # noqa: F401
        except ImportError:
            crypto_available = False

        if crypto_available:
            self.assertTrue(
                self.ss.HAS_CRYPTO,
                "pycryptodome 已安装但 HAS_CRYPTO=False,标志计算错误",
            )
        else:
            self.skipTest("本机未安装 pycryptodome,跳过 HAS_CRYPTO=True 验证")

    # -------------------------------------------------------------------------
    # 2. encrypt_api_key 在 HAS_CRYPTO=False 时 fail-fast
    # -------------------------------------------------------------------------

    def test_encrypt_raises_runtime_error_when_no_crypto(self):
        """mock HAS_CRYPTO=False 时,encrypt_api_key 应抛 RuntimeError"""
        with patch.object(self.ss, "HAS_CRYPTO", False):
            with self.assertRaises(RuntimeError) as ctx:
                self.ss.encrypt_api_key("sk-test-key", master_key="mk")
            self.assertIn("pycryptodome", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 3. decrypt_api_key 在 HAS_CRYPTO=False 时 fail-fast
    # -------------------------------------------------------------------------

    def test_decrypt_raises_runtime_error_when_no_crypto(self):
        """mock HAS_CRYPTO=False 时,decrypt_api_key (v2 密文) 应抛 RuntimeError

        注:严格 fail-fast 要求根因不被包装为 ValueError,因为
        "依赖缺失" 与 "解密失败" 是不同层级的问题。
        """
        # 构造一个 v2 格式的密文(虽然内容无效,但 _aes_gcm_decrypt 必须先检查 HAS_CRYPTO)
        v2_ciphertext = "enc:v2:YWFh:YmJi:Y2Nj:ZGRk"

        with patch.object(self.ss, "HAS_CRYPTO", False):
            with self.assertRaises(RuntimeError) as ctx:
                self.ss.decrypt_api_key(v2_ciphertext, master_key="mk")
            self.assertIn("pycryptodome", str(ctx.exception).lower())

    # -------------------------------------------------------------------------
    # 4. 错误消息包含安装提示
    # -------------------------------------------------------------------------

    def test_fail_fast_message_includes_install_hint(self):
        """错误消息必须包含安装提示 'pip install pycryptodome'"""
        with patch.object(self.ss, "HAS_CRYPTO", False):
            with self.assertRaises(RuntimeError) as ctx:
                self.ss.encrypt_api_key("sk-test-key", master_key="mk")
            self.assertIn(
                "pip install pycryptodome",
                str(ctx.exception),
                "fail-fast 错误消息必须包含安装提示 'pip install pycryptodome'",
            )

    # -------------------------------------------------------------------------
    # 5. provider_manager 在解密失败时用 ERROR 级别日志
    # -------------------------------------------------------------------------

    def test_provider_manager_logs_error_on_decrypt_failure(self):
        """ProviderConfig.from_dict 解密失败时必须用 ERROR 级别日志(非 WARNING)"""
        from neurova.llm.provider_manager import ProviderConfig

        data = {
            "id": "test-provider",
            "name": "TestProvider",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "encrypted_api_key": "enc:v2:invalid:invalid:invalid:invalid",
        }

        # patch provider_manager 中已经 import 进来的 decrypt_api_key 引用
        # (provider_manager 顶部 `from neurova.llm.providers.secret_store import decrypt_api_key`)
        err = RuntimeError(
            "pycryptodome not installed — run: pip install pycryptodome"
        )
        with patch("neurova.llm.provider_manager.decrypt_api_key", side_effect=err):
            # 捕获 logger 输出,断言 level >= ERROR
            with self.assertLogs("neurova.llm.provider_manager", level="ERROR") as cm:
                try:
                    ProviderConfig.from_dict(data, decrypt=True)
                except Exception:
                    # from_dict 内部 catch 异常,不应抛出
                    pass

            # 验证 ERROR 日志包含 "Failed to decrypt API key"
            joined = "\n".join(cm.output)
            self.assertIn(
                "Failed to decrypt API key",
                joined,
                f"ERROR 日志应包含 'Failed to decrypt API key',实际: {cm.output}",
            )


if __name__ == "__main__":
    # 使用 TextTestRunner 直接运行,避免 pytest 在某些情况下的 hang
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPycryptodomeFailFast)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
