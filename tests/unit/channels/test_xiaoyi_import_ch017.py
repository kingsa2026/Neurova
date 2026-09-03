"""
BUG CH-017 (P0): xiaoyi.py hmac 未导入测试

TDD RED phase: 验证小艺适配器正确导入 hmac 标准库。

问题: line 129 使用 `hmac.new(...)` 但文件头无 `import hmac`。
       调用 _build_auth_headers() 时会抛 NameError: name 'hmac' is not defined。
修复方向: 在文件头添加 `import hmac`。
"""

import importlib
import sys


def _reload_xiaoyi_module():
    """重新导入 xiaoyi 模块以获取最新状态"""
    mods_to_remove = [k for k in sys.modules if k.startswith("neurova.channels.xiaoyi")]
    for k in mods_to_remove:
        del sys.modules[k]
    return importlib.import_module("neurova.channels.xiaoyi")


def test_xiaoyi_module_imports_successfully():
    """模块必须能成功导入。"""
    xiaoyi_mod = _reload_xiaoyi_module()
    assert xiaoyi_mod is not None


def test_xiaoyi_has_hmac_module_in_namespace():
    """模块命名空间必须包含 hmac（用于 _build_auth_headers 的 HMAC-SHA256 签名）。

    BUG CH-017 核心：line 129 使用 hmac.new(...) 但未 import hmac，
    调用签名方法时会抛 NameError。
    """
    xiaoyi_mod = _reload_xiaoyi_module()

    assert hasattr(xiaoyi_mod, "hmac"), (
        "模块缺少 hmac 导入，_build_auth_headers() 调用 hmac.new() 会抛 NameError"
    )
    # 确认是真正的 hmac 标准库
    assert xiaoyi_mod.hmac.__name__ == "hmac"


def test_xiaoyi_hmac_is_callable_for_signing():
    """hmac 模块必须可用于生成签名（验证 hmac.new 可调用）。"""
    xiaoyi_mod = _reload_xiaoyi_module()

    if hasattr(xiaoyi_mod, "hmac"):
        import hashlib

        # 模拟 line 129 的调用：hmac.new(key, msg, hashlib.sha256).hexdigest()
        signature = xiaoyi_mod.hmac.new(
            b"test_secret",
            b"test_message",
            hashlib.sha256,
        ).hexdigest()
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA-256 hex digest 长度
