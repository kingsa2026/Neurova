"""对照批 B5：File Guard 凭据后缀清单对齐。

参照系 FilePathGuardian 的凭据面含 .pem/.key/.ppk/.p12/.kdbx 等**后缀**；
本仓 `_SENSITIVE_FILES` 只按精确文件名/stem 判——`keys/server.pem`、
`backups/db.kdbx` 这类「正当目录下的凭据后缀文件」现网不拦（红灯）。

同时补路径展开规范化（%~$VAR$）：展开后的真实路径一并过敏感判定。
误报回归：`design_tokens.json` 这类同名前缀的正当资产不得被误拦
（skill_scanner 侧踩过的坑，两侧清单口径对齐后同样要守住）。
"""

from neurova.security.tool_guard import FilePathGuardian, ToolGuardEngine


def _guard() -> ToolGuardEngine:
    return ToolGuardEngine()


class TestCredentialSuffixes:

    def test_pem_file_is_blocked(self):
        result = _guard().guard("file_write", {"file_path": "keys/server.pem"})
        assert result.should_block, \
            f"凭据后缀 .pem 应拦截，实际 findings：{[f.rule_id for f in result.findings]}"

    def test_kdbx_file_is_blocked(self):
        result = _guard().guard("file_write", {"file_path": "backups/db.kdbx"})
        assert result.should_block

    def test_git_credentials_file_is_blocked(self):
        result = _guard().guard("file_read", {"file_path": "ops/.git-credentials"})
        assert result.should_block

    def test_key_suffix_in_subdir_is_blocked(self):
        result = _guard().guard("file_write", {"file_path": "%APPDATA%\\evil\\token.key"})
        assert result.should_block, "展开与否都应按 .key 后缀拦截"


class TestFalsePositiveRegression:

    def test_normal_assets_stay_allowed(self):
        guard = _guard()
        for path in ("assets/design_tokens.json", "docs/password-hash.json",
                     "src/main.py", "report.final.txt"):
            result = guard.guard("file_write", {"file_path": path})
            assert not result.should_block, f"{path} 被误拦：{[f.rule_id for f in result.findings]}"
