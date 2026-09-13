# -*- coding: utf-8 -*-
"""P0-5 审批缓存 key 规范化（命令规范化 canonicalize）。

Codex 对齐（docs/Neurova_Codex代码级对比_2026-09-14.md §2.6/P0-5）：
- shell 包装（bash -lc/-c、sh -c、cmd /c、powershell -Command）剥离出内层命令
- 可执行名去路径（/usr/bin/python3 → python3、C:\Python311\python.exe → python）
- 空白折叠
- EXACT 审批记忆按规范化 key 记与查：同一命令换包装/换绝对路径不重复审批
- 危险命令语义不变：SIMILAR 泛化依旧豁免危险命令
"""
import pytest


@pytest.fixture()
def manager(tmp_path):
    from neurova.security.approval_manager import ApprovalManager, ApprovalLevel

    return ApprovalManager(str(tmp_path / "ws"), approval_level=ApprovalLevel.SMART)


class TestCanonicalizeCommand:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("git push origin main", "git push origin main"),
            ("bash -lc 'git push origin main'", "git push origin main"),
            ('/bin/bash -lc "git push origin main"', "git push origin main"),
            ("sh -c 'npm run build'", "npm run build"),
            ("cmd /c dir", "dir"),
            ('powershell -Command "Get-ChildItem"', "Get-ChildItem"),
            ("C:\\Python311\\python.exe -m pytest -q", "python -m pytest -q"),
            ("/usr/bin/python3 script.py", "python3 script.py"),
            ("git   push   origin   main", "git push origin main"),
            # 无 shell 包装 flag 的 bash 调用不是包装，保持原样（仅折叠空白/去路径）
            ("bash script.sh", "bash script.sh"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_canonical_shapes(self, manager, raw, expected):
        assert manager.canonicalize_command(raw) == expected

    def test_nested_wrapper_single_level_enough(self, manager):
        """嵌套包装剥一层后仍是可匹配形态（多层嵌套属罕见，不强求递归全剥）。"""
        inner = manager.canonicalize_command('bash -lc "sh -c \'echo hi\'"')
        assert "echo hi" in inner


class TestCanonicalKeyBehavior:
    def _make_pending(self, mgr, command, request_id="req-1"):
        from neurova.security.approval_manager import ApprovalRequest

        req = ApprovalRequest(
            request_id=request_id, command=command, agent_id="a1", user_id="u1"
        )
        mgr._requests[request_id] = req
        return req

    def test_exact_memory_hits_across_wrapper(self, manager):
        """批准 bash -lc 包装形态，裸命令直接放行（规范化 key 命中）。"""
        self._make_pending(manager, "bash -lc 'git push origin main'")
        assert manager.approve_request("req-1", approved_by="u1", remember="exact")

        verdict = manager.check_command("git push origin main")
        assert verdict["needs_approval"] is False
        assert "exact" in (verdict.get("reason") or "")

    def test_exact_memory_hits_across_abs_path(self, manager):
        self._make_pending(manager, "/usr/bin/python3 -m pytest -q")
        assert manager.approve_request("req-1", approved_by="u1", remember="exact")

        verdict = manager.check_command("C:\\Python311\\python.exe -m pytest -q")
        assert verdict["needs_approval"] is False

    def test_similar_memory_still_generalizes_canonical(self, manager):
        self._make_pending(manager, "bash -lc 'git push origin feature-x'")
        assert manager.approve_request("req-1", approved_by="u1", remember="similar")

        verdict = manager.check_command("git push origin feature-y")
        assert verdict["needs_approval"] is False

    def test_dangerous_similar_still_blocked_after_canonical(self, manager):
        """包装里的危险命令不能借泛化放行（规范化后仍过危险检测）。"""
        self._make_pending(manager, "bash -lc 'rm -rf /tmp/build-cache'")
        assert manager.approve_request("req-1", approved_by="u1", remember="similar")

        verdict = manager.check_command("rm -rf /home/user/data")
        assert verdict["needs_approval"] is True

    def test_dangerous_exact_canonical_still_allowed(self, manager):
        self._make_pending(manager, "bash -lc 'rm -rf /tmp/build-cache'")
        assert manager.approve_request("req-1", approved_by="u1", remember="exact")

        verdict = manager.check_command("rm -rf /tmp/build-cache")
        assert verdict["needs_approval"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
