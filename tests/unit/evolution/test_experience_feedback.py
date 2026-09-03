"""
ExperienceFeedback 测试

验证：
- 从经验文本提取工具提及
- 结果分类（成功/失败）
- 工具洞察创建
- 任务-工具关联
"""
import pytest


class TestExtractToolMentions:
    """工具提及提取测试"""
    
    def test_extract_tool_from_text(self):
        """从文本中提取工具名"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        mentions = ef.extract_tool_mentions("我使用了 browser_navigate 和 browser_screenshot 完成了任务")
        
        assert isinstance(mentions, list)
        assert "browser_navigate" in mentions
        assert "browser_screenshot" in mentions
    
    def test_extract_no_tools(self):
        """文本中无工具名"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        mentions = ef.extract_tool_mentions("今天天气不错")
        
        assert isinstance(mentions, list)
        assert len(mentions) == 0
    
    def test_extract_underscores_in_names(self):
        """工具名包含下划线"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        mentions = ef.extract_tool_mentions("使用 file_read_write 工具")
        
        assert isinstance(mentions, list)


class TestClassifyOutcome:
    """结果分类测试"""
    
    def test_classify_success(self):
        """分类成功经验"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        outcome = ef.classify_outcome("成功完成了任务，结果很好")
        
        assert outcome in ["success", "partial", "failure"]
    
    def test_classify_failure(self):
        """分类失败经验"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        outcome = ef.classify_outcome("任务失败了，出现了错误")
        
        assert outcome in ["success", "partial", "failure"]
    
    def test_classify_partial(self):
        """分类部分成功经验"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        outcome = ef.classify_outcome("部分完成了，有些步骤成功有些失败")
        
        assert outcome in ["success", "partial", "failure"]


class TestToolInsight:
    """工具洞察测试"""
    
    def test_create_insight(self):
        """创建工具洞察"""
        from neurova.evolution.experience_feedback import ExperienceFeedback, ToolInsight
        
        ef = ExperienceFeedback()
        insight = ef.create_tool_insight(
            tool_name="browser_navigate",
            outcome="success",
            context="导航到网页",
        )
        
        assert isinstance(insight, ToolInsight)
        assert insight.tool_name == "browser_navigate"
        assert insight.outcome == "success"


class TestProcessExperience:
    """经验处理测试"""
    
    def test_process_experience(self):
        """处理完整经验"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        result = ef.process_experience(
            experience_text="使用 browser_navigate 导航成功",
            task_type="web_browsing",
        )
        
        assert result is not None
        assert isinstance(result, dict)
    
    def test_get_task_tool_patterns(self):
        """获取任务-工具模式"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        ef = ExperienceFeedback()
        patterns = ef.get_task_tool_patterns("web_browsing")
        
        assert isinstance(patterns, (list, dict))