"""S7 RED 测试 — 不应向 agent.chat() 注入 {"history": []}

Bug B-2 (#10): 多个调用点向 agent.chat() 传递 metadata={"history": []},
强制清空对话历史,导致 LLM 缺对话上下文,工具参数指代不清 ("搜一下他" 不知道 "他" 是谁),
且阻止 agent.chat() 从 session 恢复历史.

受影响文件 (BUG):
  1. neurova/agent/scheduler.py:385    — 定时任务应恢复会话历史
  2. neurova/router.py:304            — 消息路由应保留 metadata (条件注入仍丢字段)
  3. neurova/router.py:476            — 默认处理器不应注入空历史
  4. neurova/api/endpoints/agent.py:517 — Agent 执行应恢复会话历史
  5. neurova/api/endpoints/generation.py:89 — 文本生成应保留会话上下文
  6. neurova/api/endpoints/sandbox.py:120 — Sandbox 多步对话应保留步骤历史

已修复 (参考,不在本测试范围):
  - chat.py:132-136 (Bug V2-3)
  - console.py:422-424 (Bug V2-4, 以及 S1)

修复策略: 删除 metadata={"history": []} 注入,改为不传 metadata 或传真实 metadata,
让 agent.chat() 自行从 session 恢复历史.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


def _strip_comments(source: str) -> str:
    """剥离 Python 注释 (# 行注释),避免测试误匹配注释文本."""
    lines = source.splitlines()
    code_lines = []
    for line in lines:
        # 去掉 # 注释 (但不破坏字符串中的 #)
        # 简化:只剥离行首/行中 # 后的内容 (对测试足够)
        in_string = False
        quote_char = None
        stripped = []
        for i, ch in enumerate(line):
            if ch in ('"', "'"):
                if not in_string:
                    in_string = True
                    quote_char = ch
                elif ch == quote_char:
                    in_string = False
                    quote_char = None
            if ch == "#" and not in_string:
                break
            stripped.append(ch)
        code_lines.append("".join(stripped))
    return "\n".join(code_lines)


# 需要检查的文件 (相对路径)
BUGGY_FILES = [
    "neurova/agent/scheduler.py",
    "neurova/router.py",
    "neurova/api/endpoints/agent.py",
    "neurova/api/endpoints/generation.py",
    "neurova/api/endpoints/sandbox.py",
]


class TestS7NoEmptyHistoryInjection:
    """S7: agent.chat() 调用不应注入 metadata={"history": []}."""

    @pytest.mark.parametrize("rel_path", BUGGY_FILES)
    def test_no_empty_history_in_metadata(self, rel_path: str):
        """RED: 指定文件不应包含 metadata={"history": []} 注入模式."""
        file_path = PROJECT_ROOT / rel_path
        if not file_path.exists():
            pytest.skip(f"File not found: {rel_path}")

        source = file_path.read_text(encoding="utf-8")
        code_only = _strip_comments(source)

        # 危险模式 1: metadata={"history": []}
        # 危险模式 2: "history": [] 在 metadata 字典中 (作为 agent.chat 参数)
        # 匹配: metadata={"history": []} 或 metadata={..., "history": [], ...}
        patterns = [
            r'metadata\s*=\s*\{\s*"history"\s*:\s*\[\]\s*\}',
            r'metadata\s*=\s*\{[^}]*"history"\s*:\s*\[\][^}]*\}',
            r'else\s*\{\s*"history"\s*:\s*\[\]\s*\}',  # router.py:304 条件分支
        ]

        for pattern in patterns:
            matches = re.findall(pattern, code_only)
            assert not matches, (
                f"S7: {rel_path} 包含 metadata={{'history': []}} 注入模式. "
                f"匹配: {matches}. "
                "BUG: 强制空历史阻止 agent.chat() 从 session 恢复对话上下文. "
                "修复: 删除 metadata={{'history': []}}, 改为不传或传真实 metadata."
            )

    def test_scheduler_no_empty_history(self):
        """RED: scheduler.py 不应用空历史调用 agent.chat."""
        file_path = PROJECT_ROOT / "neurova/agent/scheduler.py"
        if not file_path.exists():
            pytest.skip("scheduler.py not found")
        source = file_path.read_text(encoding="utf-8")
        code_only = _strip_comments(source)
        assert '"history": []' not in code_only, (
            "S7: scheduler.py 不应包含 '\"history\": []' (代码中,非注释). "
            "BUG: 定时任务应从 session 恢复历史,而非强制空历史."
        )

    def test_router_no_empty_history(self):
        """RED: router.py 不应用空历史调用 agent.chat."""
        file_path = PROJECT_ROOT / "neurova/router.py"
        if not file_path.exists():
            pytest.skip("router.py not found")
        source = file_path.read_text(encoding="utf-8")
        code_only = _strip_comments(source)
        assert '"history": []' not in code_only, (
            "S7: router.py 不应包含 '\"history\": []' (代码中,非注释). "
            "BUG: 消息路由应保留 metadata,不应条件注入空历史."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
