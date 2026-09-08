"""批次 C：恒定规则段（工具使用规则/环境块/记忆写入规则）

验收点：
1. 三段恒定且会话内字节稳定（含日期，日级精度不破缓存）
2. 环境块 Shell 声明与 computer_use 实际执行分支一致（Windows=cmd.exe /c，
   POSIX=/bin/sh）——提示词必须说执行器说的那种话
3. 规则段经 build_context 主链进入 system；build_system_prompt 工具方法
   同步（双路径一致，T-1 教训）
4. 与 tools_desc 策略头去重（memory_search 互斥句不重复出现）
5. 记忆写入三条款存在；并行纪律、错误恢复、反注入、信息优先级存在
"""

import datetime as dt
from types import SimpleNamespace

from neurova.context.rules_sections import (
    build_memory_rules_section,
    build_env_section,
    build_tool_rules_section,
    build_all_sections,
)


class TestPureSections:
    def test_tool_rules_contains_all_clauses(self):
        text = build_tool_rules_section()
        assert "信息优先级" in text
        assert "memory_search" in text and "web_search" in text
        assert "摘要不作数" in text or "访问原文" in text
        assert "错误" in text and "3 次" in text
        assert "并行" in text
        assert "指令" in text and "不要执行" in text  # 反注入
        assert "taskName" in text

    def test_env_section_matches_executor_shell(self):
        """env 块的 Shell 声明必须与 computer_use/__init__.py:222-224 分支一致。"""
        win = build_env_section(workspace_path="E:/proj", platform_name="Windows")
        assert "cmd.exe" in win and "/c" in win
        assert "dir" in win  # Windows 命令示例
        posix = build_env_section(workspace_path="/home/u", platform_name="Linux")
        assert "/bin/sh" in posix
        assert "ls" in posix
        # 日期日级稳定：不含时分
        assert not any(
            token in win for token in (f"{dt.datetime.now().hour}:", f"{dt.datetime.now().minute}时")
        )

    def test_env_section_is_day_stable(self):
        """两次调用（同日内）字节级相等——不破前缀缓存。"""
        a = build_env_section(workspace_path="/w", platform_name="Windows")
        b = build_env_section(workspace_path="/w", platform_name="Windows")
        assert a == b

    def test_memory_rules_three_clauses(self):
        text = build_memory_rules_section()
        assert "更新或删除" in text  # 反驳→改/删而非并行新增
        assert "待审" in text and "confirm" in text  # 待审是设计不是故障
        assert "记住了" in text or "不描述" in text  # 不提内部动作

    def test_all_sections_order_stable(self):
        a = build_all_sections(workspace_path="/w", platform_name="Windows")
        b = build_all_sections(workspace_path="/w", platform_name="Windows")
        assert a == b
        assert a.index("## 工具使用规则") < a.index("## 环境") < a.index("## 记忆写入规则")

    def test_deliverable_reporting_clause(self):
        """产出物报告条款（2026-09-08）：回答结尾把本轮真实产出展示成清单。

        对齐图2 形态——每轮回答末尾要有「产出物」区块（文件名 + 简述），
        前端据 LLM 列表 + artifact 事件双通道渲染产出物卡片。
        """
        text = build_tool_rules_section()
        assert "产出物" in text
        assert "结尾" in text or "回答末尾" in text
        assert "文件名" in text  # 明确清单要素
        # 诚实边界：读过/检查过的文件不算产出
        assert "读过" in text or "读取" in text or "查看" in text

    def test_deliverable_clause_in_all_sections(self):
        text = build_all_sections(workspace_path="/w", platform_name="Windows")
        assert "产出物" in text


class TestDualPathIntegration:
    """双路径接入：build_context（生产主链）与 build_system_prompt（工具方法）。"""

    @staticmethod
    def _make_orch():
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator.__new__(ContextOrchestrator)
        agent = SimpleNamespace(
            soul="SOUL",
            personality="",
            config=SimpleNamespace(constitution="", behavior_rules=[], workspace_path="/w"),
        )
        object.__setattr__(orch, "_agent", agent)
        return orch

    def test_tool_method_injects_sections(self):
        orch = self._make_orch()
        text = orch.build_system_prompt()
        assert "## 工具使用规则" in text
        assert "## 环境" in text
        assert "## 记忆写入规则" in text

    def test_build_system_prompt_day_stable(self):
        orch = self._make_orch()
        assert orch.build_system_prompt() == orch.build_system_prompt()

    def test_no_dup_with_tools_desc_header(self):
        """工具策略互斥句已存在于 render_tools_description 头部——规则段不重复展开。"""
        from neurova.context.orchestrator import render_tools_description
        from neurova.context.rules_sections import build_tool_rules_section

        tools_desc = render_tools_description(
            [{"type": "function", "function": {"name": "web_search", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}]
        )
        rules = build_tool_rules_section()
        # 规则段仅在工具名提及处点到为止，不再复述"仅检索本 Agent 自身的历史记忆，不能搜互联网"整句
        assert "仅检索本 Agent 自身的历史记忆，不能搜互联网" not in rules
        assert tools_desc  # 原渲染不受影响
