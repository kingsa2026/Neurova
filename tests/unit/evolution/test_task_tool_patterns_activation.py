"""TaskToolAssociation 死查询激活回归测试（遗留事项 ③）

断点：ExperienceFeedback._associations 每轮经验记录都在写入（活数据），但唯一
查询 API get_task_tool_patterns 全仓零消费方——"任务→工具"模式沉淀了永不用于
决策。
修复：get_feedback（RSI 唯一消费入口）扩展 top_task_tool_patterns 字段——
跨任务类型聚合前 N 个高成功率模式（观察≥2 次），随反馈信号进入 RSI 的
system_performance 估算。零新表、零新端点，纯激活既有数据面。
"""

from neurova.evolution.experience_feedback import ExperienceFeedback


class TestFeedbackExposesTaskToolPatterns:
    def test_get_feedback_includes_top_patterns(self):
        ef = ExperienceFeedback()
        # 同一任务类型多次成功使用同一工具 → 高置信模式
        for _ in range(3):
            ef.create_task_tool_association("web_browsing", "web_search", "success")
        for _ in range(2):
            ef.create_task_tool_association("web_browsing", "bad_tool", "failure")

        feedback = ef.get_feedback()

        assert "top_task_tool_patterns" in feedback, (
            "get_feedback 必须暴露任务-工具模式（死查询激活）"
        )
        patterns = feedback["top_task_tool_patterns"]
        assert patterns, "有沉淀数据时不得为空"
        first = patterns[0]
        assert first["task_type"] == "web_browsing"
        assert first["tool_name"] == "web_search"  # 成功率排序：成功的在前
        assert first["success_rate"] == 1.0

    def test_low_observation_patterns_filtered(self):
        """观察 <2 次的单次记录不进 top 模式（防噪声）"""
        ef = ExperienceFeedback()
        ef.create_task_tool_association("one_off", "tool_x", "success")
        feedback = ef.get_feedback()
        assert feedback["top_task_tool_patterns"] == []

    def test_empty_state_returns_empty_list(self):
        ef = ExperienceFeedback()
        feedback = ef.get_feedback()
        assert feedback["top_task_tool_patterns"] == []

    def test_patterns_capped(self):
        """有界输出：最多 5 条，防反馈信号膨胀"""
        ef = ExperienceFeedback()
        for i in range(8):
            task = f"task_{i}"
            for _ in range(2):
                ef.create_task_tool_association(task, f"tool_{i}", "success")
        patterns = ef.get_feedback()["top_task_tool_patterns"]
        assert len(patterns) <= 5
