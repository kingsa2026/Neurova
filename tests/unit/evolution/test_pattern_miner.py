"""
Phase 2 P2-1: PatternMiner 测试

验证 PrefixSpan 序列模式挖掘 + AutoSkillBuilder 联动。
"""

import pytest
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ============================================================
# 测试夹具
# ============================================================


@dataclass
class MockToolEntry:
    """模拟 ToolExecutionEntry"""
    tool_name: str
    source: str = "BUILTIN"
    success: bool = True
    timestamp: str = field(default_factory=lambda: str(time.time()))
    agent_id: Optional[str] = None
    params: Dict = field(default_factory=dict)


def make_sequence(tool_names: List[str]) -> List[MockToolEntry]:
    """快速创建工具序列"""
    return [
        MockToolEntry(tool_name=name)
        for name in tool_names
    ]


# ============================================================
# P2-1.1 PrefixSpan 核心算法
# ============================================================


class TestPrefixSpanCore:
    """PrefixSpan 频繁序列挖掘核心算法"""

    def test_mine_single_frequent_pattern(self):
        """挖掘单个频繁模式"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=2)

        # 3 个包含 browser_navigate → browser_screenshot 的序列
        sequences = [
            make_sequence(["browser_navigate", "browser_screenshot", "browser_click"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_type"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_extract_text"]),
        ]

        for seq in sequences:
            miner.add_sequence(seq)

        patterns = miner.mine()
        assert isinstance(patterns, list)
        assert len(patterns) > 0

        # 检查 browser_navigate → browser_screenshot 是否被挖掘
        nav_screenshot_pattern = None
        for p in patterns:
            if "browser_navigate" in p.tools and "browser_screenshot" in p.tools:
                nav_screenshot_pattern = p
                break

        assert nav_screenshot_pattern is not None
        assert nav_screenshot_pattern.support >= 3  # 出现在 3 个序列中

    def test_mine_length_filtered(self):
        """按最小长度过滤模式"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=2, min_length=3)

        sequences = [
            make_sequence(["a", "b", "c", "d"]),
            make_sequence(["a", "b", "c", "d"]),
            make_sequence(["a", "b", "e"]),
        ]

        for seq in sequences:
            miner.add_sequence(seq)

        patterns = miner.mine()

        # 所有模式长度应 >= 3
        for p in patterns:
            assert len(p.tools) >= 3, f"Pattern {p.tools} length {len(p.tools)} < 3"

    def test_mine_empty_input(self):
        """空输入不崩溃"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner()
        patterns = miner.mine()
        assert patterns == []

    def test_mine_below_support_threshold(self):
        """低于支持度阈值的模式不被返回"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=3)

        # 只有 2 个序列包含 "x"，低于 min_support=3
        sequences = [
            make_sequence(["a", "b", "x"]),
            make_sequence(["a", "b", "x"]),
        ]

        for seq in sequences:
            miner.add_sequence(seq)

        patterns = miner.mine()

        # "x" 的支持度为 2 < 3，不应出现在模式中
        for p in patterns:
            assert all(t != "x" for t in p.tools) or p.support < 3, (
                f"Low support pattern found: {p.tools} support={p.support}"
            )

    def test_mine_real_world_browser_sequence(self):
        """模拟真实的浏览器操作序列挖掘"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=3, min_length=2)

        # 模拟 5 次用户任务
        sequences = [
            make_sequence(["browser_navigate", "browser_screenshot", "browser_click", "browser_screenshot"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_type", "browser_click"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_click", "browser_extract_text"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_click", "browser_screenshot"]),
            make_sequence(["browser_navigate", "browser_screenshot", "browser_scroll", "browser_click"]),
        ]

        for seq in sequences:
            miner.add_sequence(seq)

        patterns = miner.mine()

        # browser_navigate → browser_screenshot 应被挖掘（5/5 序列）
        for p in patterns:
            if p.tools == ["browser_navigate", "browser_screenshot"]:
                assert p.support >= 3
                break
        else:
            # 可能以不同长度出现
            found = any(
                "browser_navigate" in p.tools and "browser_screenshot" in p.tools
                for p in patterns
            )
            assert found, "browser_navigate + browser_screenshot 未被挖掘"


# ============================================================
# P2-1.2 PatternMiner 统计功能
# ============================================================


class TestPatternMinerStats:
    """PatternMiner 统计接口"""

    def test_sequence_count(self):
        """记录序列总数"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner()
        for _ in range(5):
            miner.add_sequence(make_sequence(["a", "b"]))

        assert miner.sequence_count == 5

    def test_unique_tools_count(self):
        """统计唯一工具数"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner()
        miner.add_sequence(make_sequence(["a", "b", "c"]))
        miner.add_sequence(make_sequence(["b", "c", "d"]))
        miner.add_sequence(make_sequence(["c", "d", "e"]))

        assert miner.unique_tools_count == 5  # a,b,c,d,e

    def test_get_top_patterns(self):
        """获取 Top-K 模式（按支持度排序）"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=2)

        # a,b 出现在 5 个序列中，c,d 出现在 3 个
        for _ in range(5):
            miner.add_sequence(make_sequence(["a", "b", "c"]))
        for _ in range(3):
            miner.add_sequence(make_sequence(["c", "d", "e"]))

        top = miner.get_top_patterns(k=5)
        assert len(top) <= 5
        # 第一个应该支持度最高
        if len(top) >= 2:
            assert top[0].support >= top[1].support


# ============================================================
# P2-1.3 与 AutoSkillBuilder 联动
# ============================================================


class TestPatternMinerAutoSkill:
    """PatternMiner → AutoSkillBuilder 联动"""

    def test_export_to_skill_builder(self):
        """将挖掘出的高频模式导出为 AutoSkillBuilder 可用的格式"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=3, min_length=2)

        for _ in range(4):
            miner.add_sequence(make_sequence([
                "browser_navigate", "browser_screenshot", "browser_click"
            ]))

        patterns = miner.mine()
        export = miner.to_skill_template_list(min_support=3, min_success_rate=0.0)

        assert isinstance(export, list)
        # 应该有至少一个模式被导出
        # browser_navigate → browser_screenshot 或 browser_screenshot → browser_click 等
        assert len(export) >= 1

        # 导出格式应包含 tools 字段
        for item in export:
            assert "tools" in item
            assert "context" in item
            assert isinstance(item["tools"], list)

    def test_auto_feed_to_skill_builder(self):
        """自动将挖掘结果喂给 AutoSkillBuilder"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=2)

        for _ in range(3):
            miner.add_sequence(make_sequence([
                "screenshot", "visual_parse", "smart_click"
            ]))

        # 模拟: AutoSkillBuilder 接收挖掘结果
        created_count = 0
        for template in miner.to_skill_template_list():
            # 每个 template 应该可以封装为 Skill
            if len(template["tools"]) >= 2:
                created_count += 1

        assert created_count >= 1, f"应至少创建 1 个技能，实际创建 {created_count}"


# ============================================================
# P2-1.4 边界条件
# ============================================================


class TestPatternMinerEdgeCases:
    """边界条件测试"""

    def test_single_tool_sequence(self):
        """单工具序列"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=2)
        miner.add_sequence(make_sequence(["a"]))
        miner.add_sequence(make_sequence(["a"]))
        miner.add_sequence(make_sequence(["a"]))

        patterns = miner.mine()
        # 单工具模式也应被挖掘（但可能被 min_length 过滤）
        assert isinstance(patterns, list)

    def test_large_sequence_batch(self):
        """大批量序列处理"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner(min_support=5)
        for i in range(20):
            seq = ["tool_a", "tool_b", f"tool_{i % 3}"]  # tool_0, tool_1, tool_2 变化
            miner.add_sequence(make_sequence(seq))

        patterns = miner.mine()
        assert isinstance(patterns, list)
        # tool_a → tool_b 应该出现在所有 20 个序列中
        ab_pattern = None
        for p in patterns:
            if "tool_a" in p.tools and "tool_b" in p.tools:
                ab_pattern = p
                break
        assert ab_pattern is not None

    def test_reset_clears_all(self):
        """reset() 清空所有数据"""
        from neurova.evolution.pattern_miner import PatternMiner

        miner = PatternMiner()
        miner.add_sequence(make_sequence(["a", "b", "c"]))
        miner.add_sequence(make_sequence(["d", "e", "f"]))

        miner.reset()

        assert miner.sequence_count == 0
        assert miner.unique_tools_count == 0
        assert miner.mine() == []
