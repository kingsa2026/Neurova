"""
高危安全审计修复回归测试（对应）

覆盖本次修复项:
- H3: 工作流/数据转换 eval() 沙箱逃逸 → safe_expr AST 白名单
- L3: 技能包/市场解包 Zip Slip / Tar Slip → safe_archive 成员校验
- M1: JWT 密钥强度校验 + .jwt_secret 权限收紧
- M2: 密码哈希不再回退无盐 SHA-256（既有实现，回归钉死）
"""

import io
import os
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest

from neurova.security.safe_archive import (
    UnsafeArchiveError,
    safe_extract_tar,
    safe_extract_zip,
)
from neurova.security.safe_expr import (
    SafeExprError,
    is_safe_expression,
    safe_eval,
)


# ── H3: safe_expr ────────────────────────────────────────


class TestSafeExprBlocksSandboxEscape:
    """eval() 沙箱逃逸载荷必须被拒绝。"""

    @pytest.mark.parametrize(
        "expression",
        [
            "(1).__class__.__mro__[1].__subclasses__()",  # 经典逃逸链
            "__import__('os').system('id')",
            "().__class__.__bases__[0].__subclasses__()",
            "input.__class__",
            "input.__globals__",
            "''.join.__self__",
            "x._module",
        ],
    )
    def test_escape_payloads_rejected(self, expression):
        with pytest.raises(SafeExprError):
            safe_eval(expression, {"input": "a", "x": 1})

    @pytest.mark.parametrize(
        "expression",
        [
            "lambda: 1",
            "[i for i in range(3)]",
            "{k: 1 for k in []}",
            "(x := 1)",
            "import os",
            "open('/etc/passwd')",
            "exec('1')",
        ],
    )
    def test_dangerous_syntax_rejected(self, expression):
        assert not is_safe_expression(expression)
        with pytest.raises(SafeExprError):
            safe_eval(expression, {"x": 1})

    def test_length_limit(self):
        with pytest.raises(SafeExprError):
            safe_eval("1" + "+1" * 2000)


class TestSafeExprPreservesSemantics:
    """白名单内的正常表达式语义不变。"""

    def test_arithmetic_and_builtins(self):
        assert safe_eval("len(input) + 1", {"input": [1, 2, 3]}) == 4
        assert safe_eval("int(x) * 2", {"x": "21"}) == 42
        assert safe_eval("max(a, b) - min(a, b)", {"a": 5, "b": 2}) == 3

    def test_method_call_allowed(self):
        # 现有 exec_transform 测试依赖 input.upper()
        assert safe_eval("input.upper()", {"input": "hello"}) == "HELLO"
        assert safe_eval("'a,b'.split(',')[1]") == "b"

    def test_container_and_compare(self):
        assert safe_eval("[1, 2, 3][0]") == 1
        assert safe_eval("x > 3 and y", {"x": 5, "y": True}) is True

    def test_reject_underscore_variable(self):
        with pytest.raises(SafeExprError):
            safe_eval("_secret", {"_secret": "leak"})


# ── L3: safe_archive ─────────────────────────────────────


def _make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf


def _make_tar(entries, symlink=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in entries.items():
            payload = data.encode("utf-8") if isinstance(data, str) else data
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            t.addfile(info, io.BytesIO(payload))
        if symlink:
            info = tarfile.TarInfo(symlink[0])
            info.type = tarfile.SYMTYPE
            info.linkname = symlink[1]
            t.addfile(info)
    buf.seek(0)
    return buf


class TestSafeExtractZip:
    def test_normal_extract(self, tmp_path):
        buf = _make_zip({"a/b.txt": "hi"})
        safe_extract_zip(buf.getvalue(), tmp_path)
        assert (tmp_path / "a" / "b.txt").read_text() == "hi"

    def test_zip_slip_rejected(self, tmp_path):
        buf = _make_zip({"../../evil.txt": "x"})
        with pytest.raises(UnsafeArchiveError):
            safe_extract_zip(buf.getvalue(), tmp_path)
        assert not (tmp_path.parent.parent / "evil.txt").exists()

    def test_absolute_path_rejected(self, tmp_path):
        buf = _make_zip({"/tmp/evil_abs.txt": "x"})
        with pytest.raises(UnsafeArchiveError):
            safe_extract_zip(buf.getvalue(), tmp_path)

    def test_existing_zipfile_object(self, tmp_path):
        zf = zipfile.ZipFile(_make_zip({"ok.txt": "1"}))
        safe_extract_zip(zf, tmp_path)
        assert (tmp_path / "ok.txt").read_text() == "1"


class TestSafeExtractTar:
    def test_normal_extract(self, tmp_path):
        buf = _make_tar({"x/y.txt": "hello"})
        safe_extract_tar(buf, tmp_path)
        assert (tmp_path / "x" / "y.txt").read_text() == "hello"

    def test_tar_slip_rejected(self, tmp_path):
        buf = _make_tar({"../../evil2.txt": "x"})
        with pytest.raises(UnsafeArchiveError):
            safe_extract_tar(buf, tmp_path)

    def test_symlink_member_rejected(self, tmp_path):
        buf = _make_tar({"ok.txt": "1"}, symlink=("link", "/etc/passwd"))
        with pytest.raises(UnsafeArchiveError):
            safe_extract_tar(buf, tmp_path)


# ── M1: JWT 密钥强度 ─────────────────────────────────────


class TestJwtSecretHardening:
    @pytest.fixture
    def auth_mod(self, monkeypatch, tmp_path):
        import importlib

        import neurova.api.auth as auth

        monkeypatch.chdir(tmp_path)
        return auth

    def test_short_secret_rejected_in_prod(self, monkeypatch, tmp_path):
        import neurova.api.auth as auth

        monkeypatch.delenv("NEUROVA_DEBUG", raising=False)
        monkeypatch.setenv("NEUROVA_ENV", "production")
        with pytest.raises(RuntimeError):
            auth._validate_secret("short")

    def test_default_secret_rejected_in_prod(self, monkeypatch):
        import neurova.api.auth as auth

        monkeypatch.delenv("NEUROVA_DEBUG", raising=False)
        monkeypatch.setenv("NEUROVA_ENV", "production")
        with pytest.raises(RuntimeError):
            auth._validate_secret("your-secret-key-change-in-production")

    def test_strong_secret_ok(self, monkeypatch):
        import neurova.api.auth as auth

        monkeypatch.setenv("NEUROVA_DEBUG", "1")
        strong = "a" * 40
        assert auth._validate_secret(strong) == strong

    def test_secret_file_permissions_0600(self, monkeypatch, tmp_path):
        # NTFS 无 POSIX 权限位（os.chmod 仅切只读位，st_mode 恒 0o666），
        # 本断言仅在 Linux/macOS 有意义；Windows 环境性跳过（生产 chmod 尽力而为）。
        import pytest

        if os.name != "posix":
            pytest.skip("POSIX mode bits not enforced on NTFS")
        import neurova.api.auth as auth

        monkeypatch.chdir(tmp_path)
        auth._write_secret_file("x" * 40)
        mode = os.stat(tmp_path / ".jwt_secret").st_mode
        assert stat.S_IMODE(mode) == 0o600

    def test_short_secret_allowed_in_dev(self, monkeypatch):
        import neurova.api.auth as auth

        monkeypatch.setenv("NEUROVA_DEBUG", "1")
        monkeypatch.delenv("NEUROVA_ENV", raising=False)
        assert auth._validate_secret("short") == "short"


# ── M2: 密码哈希不回退无盐 SHA-256 ───────────────────────


class TestPasswordHashNoUnsaltedFallback:
    def test_unsalted_sha256_rejected(self):
        import hashlib

        from neurova.api.auth import verify_password

        salted_hash = hashlib.sha256(b"password123").hexdigest()
        # 无盐 SHA-256 摘要不得通过校验
        assert verify_password("password123", salted_hash) is False

    def test_unknown_format_rejected(self):
        from neurova.api.auth import verify_password

        assert verify_password("x", "sha256:deadbeef") is False
        assert verify_password("x", "") is False
