"""
Neurova 上下文系统优化 - 全面单元测试
覆盖所有核心方法和边界条件
"""

import unittest
from typing import Dict, List, Tuple


class TestSmartContextCompressorCore(unittest.TestCase):
    """测试 SmartContextCompressor 核心方法"""

    def setUp(self):
        """测试前准备"""
        from neurova.context_compressor import SmartContextCompressor, CompressionConfig
        self.compressor = SmartContextCompressor()
        self.config = CompressionConfig()

    def test_count_tokens_chinese(self):
        """测试中文字符token计数"""
        text = "这是一段中文文本"
        tokens = self.compressor._count_tokens(text)
        self.assertGreater(tokens, 0)
        self.assertEqual(tokens, len(text) * self.config.chinese_token_ratio)

    def test_count_tokens_english(self):
        """测试英文字符token计数"""
        text = "This is English text"
        tokens = self.compressor._count_tokens(text)
        self.assertGreater(tokens, 0)

    def test_count_tokens_empty(self):
        """测试空文本"""
        tokens = self.compressor._count_tokens("")
        self.assertEqual(tokens, 0)

    def test_count_tokens_mixed(self):
        """测试中英混合文本"""
        text = "Hello你好World世界"
        tokens = self.compressor._count_tokens(text)
        self.assertGreater(tokens, 0)

    def test_group_into_turns(self):
        """测试对话分组"""
        history = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好'},
            {'role': 'user', 'content': '今天天气'},
            {'role': 'assistant', 'content': '天气不错'},
        ]
        turns = self.compressor._group_into_turns(history)
        self.assertEqual(len(turns), 2)
        self.assertEqual(len(turns[0]), 2)
        self.assertEqual(len(turns[1]), 2)

    def test_group_into_turns_incomplete(self):
        """测试不完整对话分组"""
        history = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好'},
            {'role': 'user', 'content': '最后一个问题'},
        ]
        turns = self.compressor._group_into_turns(history)
        self.assertEqual(len(turns), 2)
        self.assertEqual(len(turns[1]), 1)

    def test_group_into_turns_empty(self):
        """测试空对话"""
        turns = self.compressor._group_into_turns([])
        self.assertEqual(len(turns), 0)

    def test_summarize_turns(self):
        """测试轮次摘要生成"""
        turns = [
            [{'role': 'user', 'content': '第一个问题是什么'}],
            [{'role': 'user', 'content': '第二个问题是什么'}],
        ]
        summary = self.compressor._summarize_turns(turns)
        self.assertIsNotNone(summary)
        self.assertIsInstance(summary, str)

    def test_summarize_turns_empty(self):
        """测试空轮次摘要"""
        summary = self.compressor._summarize_turns([])
        self.assertEqual(summary, "")

    def test_estimate_total_tokens(self):
        """测试总token估算"""
        system = "系统提示"
        memories = [{'content': '记忆内容'}]
        history = [{'role': 'user', 'content': '用户输入'}]
        user_input = "当前输入"
        
        tokens = self.compressor._estimate_total_tokens(
            system, memories, history, user_input
        )
        self.assertGreater(tokens, 0)

    def test_count_context_tokens(self):
        """测试上下文token计数"""
        context = [
            {'role': 'system', 'content': '系统提示'},
            {'role': 'user', 'content': '用户输入'},
        ]
        tokens = self.compressor._count_context_tokens(context)
        self.assertGreater(tokens, 0)

    def test_count_context_tokens_empty(self):
        """测试空上下文"""
        tokens = self.compressor._count_context_tokens([])
        self.assertEqual(tokens, 0)


class TestProgressiveCompression(unittest.TestCase):
    """测试渐进式压缩功能"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_progressive_compress_recent_full(self):
        """测试最近轮次完整保留"""
        history = []
        for i in range(5):
            history.extend([
                {'role': 'user', 'content': f'用户第{i}轮'},
                {'role': 'assistant', 'content': f'助手第{i}轮'}
            ])
        
        compressed, stats = self.compressor._progressive_compress_history(history, budget=1000)
        
        self.assertGreater(len(compressed), 0)
        self.assertEqual(stats['mode'], 'progressive')

    def test_progressive_compress_early_compressed(self):
        """测试早期轮次压缩"""
        history = []
        for i in range(10):
            history.extend([
                {'role': 'user', 'content': f'用户第{i}轮提问，内容很长需要压缩'},
                {'role': 'assistant', 'content': f'助手第{i}轮回复，内容也很长'}
            ])
        
        compressed, stats = self.compressor._progressive_compress_history(history, budget=500)
        
        self.assertLess(len(compressed), len(history))

    def test_progressive_compress_empty(self):
        """测试空历史"""
        compressed, stats = self.compressor._progressive_compress_history([], budget=1000)
        self.assertEqual(len(compressed), 0)
        self.assertEqual(stats['original'], 0)

    def test_simple_compress_history(self):
        """测试简单压缩"""
        history = [
            {'role': 'user', 'content': '测试1'},
            {'role': 'assistant', 'content': '测试2'}
        ]
        compressed, stats = self.compressor._simple_compress_history(history, budget=100)
        self.assertGreater(len(compressed), 0)
        self.assertEqual(stats['mode'], 'simple')

    def test_smart_truncate_multiple_separators(self):
        """测试多种分隔符截断"""
        text = "第一句！第二句？第三句。第四句"
        result = self.compressor._smart_truncate(text, 0.5)
        self.assertIsNotNone(result)
        self.assertLess(len(result), len(text))

    def test_smart_truncate_no_separator(self):
        """测试无分隔符截断"""
        text = "这是一段没有句号的文本"
        result = self.compressor._smart_truncate(text, 0.3)
        self.assertTrue(result.endswith('...'))


class TestDynamicBudget(unittest.TestCase):
    """测试动态预算计算"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_dynamic_budget_short_conversation(self):
        """测试短对话预算"""
        history = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好'}
        ]
        budget = self.compressor._calculate_dynamic_budget(history)
        self.assertLess(budget, self.compressor.config.history_budget)

    def test_dynamic_budget_long_conversation(self):
        """测试长对话预算"""
        history = []
        for i in range(100):
            history.extend([
                {'role': 'user', 'content': f'用户第{i}轮'},
                {'role': 'assistant', 'content': f'助手第{i}轮'}
            ])
        budget = self.compressor._calculate_dynamic_budget(history)
        self.assertGreater(budget, self.compressor.config.history_budget)

    def test_dynamic_budget_empty(self):
        """测试空对话预算"""
        budget = self.compressor._calculate_dynamic_budget([])
        self.assertEqual(budget, self.compressor.config.history_budget)


class TestMemoryCompression(unittest.TestCase):
    """测试记忆压缩功能"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_compress_memories_crystallized(self):
        """测试固化记忆保留"""
        memories = [
            {'content': '固化记忆', 'temperature': 80, 'is_crystallized': True},
            {'content': '普通记忆', 'temperature': 50, 'is_crystallized': False}
        ]
        compressed, stats = self.compressor._compress_memories(memories)
        self.assertGreater(len(compressed), 0)
        self.assertEqual(stats['critical'], 1)

    def test_compress_memories_high_temp(self):
        """测试高温记忆保留"""
        memories = [
            {'content': '高温记忆', 'temperature': 80, 'is_crystallized': False},
            {'content': '低温记忆', 'temperature': 30, 'is_crystallized': False}
        ]
        compressed, stats = self.compressor._compress_memories(memories)
        self.assertGreaterEqual(stats['important'], 1)

    def test_compress_memories_empty(self):
        """测试空记忆"""
        compressed, stats = self.compressor._compress_memories([])
        self.assertEqual(len(compressed), 0)
        self.assertEqual(stats['original'], 0)

    def test_summarize_memories(self):
        """测试记忆摘要生成"""
        memories = [
            {'content': '记忆1'},
            {'content': '记忆2'},
            {'content': '记忆3'}
        ]
        summarized = self.compressor._summarize_memories(memories)
        self.assertEqual(len(summarized), 1)
        self.assertTrue(summarized[0].get('is_summary'))


class TestContextBuilding(unittest.TestCase):
    """测试上下文构建"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_build_system_prompt_empty(self):
        """测试空系统提示构建"""
        result = self.compressor._build_system_prompt("", [])
        self.assertEqual(result, "")

    def test_build_system_prompt_with_memories(self):
        """测试带记忆的系统提示"""
        memories = [
            {'content': '记忆1', 'is_crystallized': True},
            {'content': '记忆2', 'is_important': True}
        ]
        result = self.compressor._build_system_prompt("基础提示", memories)
        self.assertIn("相关记忆", result)
        self.assertIn("记忆1", result)

    def test_build_context(self):
        """测试完整上下文构建"""
        context = self.compressor._build_context(
            system_prompt="系统",
            memories=[],
            conversation_history=[],
            user_input="用户"
        )
        self.assertEqual(len(context), 2)
        self.assertEqual(context[0]['role'], 'system')
        self.assertEqual(context[1]['role'], 'user')


class TestCompressContextIntegration(unittest.TestCase):
    """测试压缩上下文集成"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_compress_within_budget(self):
        """测试未超出预算"""
        result = self.compressor.compress_context(
            system_prompt="短提示",
            memories=[{'content': '短记忆'}],
            conversation_history=[],
            user_input="短输入"
        )
        self.assertFalse(result['stats']['compressed'])
        self.assertEqual(result['stats']['compression_ratio'], 1.0)

    def test_compress_exceed_budget(self):
        """测试超出预算"""
        long_system = "系统" * 1000
        result = self.compressor.compress_context(
            system_prompt=long_system,
            memories=[],
            conversation_history=[],
            user_input="输入"
        )
        self.assertIsNotNone(result['context'])

    def test_generate_compression_summary(self):
        """测试压缩摘要生成"""
        summary = self.compressor._generate_compression_summary(
            original_tokens=1000,
            compressed_tokens=500,
            memory_stats={'kept': 5, 'compressed': 2, 'removed': 1},
            history_stats={'recent_turns_kept': 3, 'old_turns_compressed': 5}
        )
        self.assertIsInstance(summary, str)
        self.assertIn("压缩完成", summary)


class TestContextInjectorHelpers(unittest.TestCase):
    """测试 UnContextInjector 辅助方法"""

    def test_token_count_chinese_ratio(self):
        """测试中文token比例"""
        from neurova.context import TokenBudget
        budget = TokenBudget()
        self.assertEqual(budget.chinese_ratio, 1.5)
        self.assertEqual(budget.english_ratio, 0.25)

    def test_context_priority_enum(self):
        """测试优先级枚举"""
        from neurova.context import ContextPriority
        self.assertEqual(ContextPriority.CRITICAL.value, 100)
        self.assertEqual(ContextPriority.HIGH.value, 80)
        self.assertEqual(ContextPriority.NORMAL.value, 50)
        self.assertEqual(ContextPriority.LOW.value, 20)

    def test_context_entry_to_dict(self):
        """测试上下文条目转换"""
        from neurova.context import ContextEntry, ContextPriority
        entry = ContextEntry(
            id="test_001",
            content="测试内容",
            priority=ContextPriority.HIGH,
            category="test"
        )
        result = entry.to_dict()
        self.assertEqual(result['id'], "test_001")
        self.assertEqual(result['priority'], 80)


class TestMemoryInjector(unittest.TestCase):
    """测试记忆注入器"""

    def test_extract_keywords_empty(self):
        """测试空文本关键词提取"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        keywords = injector._extract_keywords("")
        self.assertEqual(len(keywords), 0)

    def test_extract_keywords_single_char(self):
        """测试单字符关键词"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        text = "你好世界"
        keywords = injector._extract_keywords(text, top_k=5)
        self.assertIsInstance(keywords, list)

    def test_extract_keywords_english(self):
        """测试英文关键词提取"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        text = "hello world"
        keywords = injector._extract_keywords(text)
        self.assertIsInstance(keywords, list)

    def test_category_priority_all(self):
        """测试所有分类优先级"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        
        categories = [
            ('profile', 50),
            ('core_command', 50),
            ('task', 45),
            ('identity', 40),
            ('skill', 40),
            ('reflection_log', 30),
            ('lesson', 35),
            ('experience', 30),
            ('fact', 25),
            ('relationship', 20),
            ('emotional', 20),
            ('conversation', 15),
            ('creative', 15),
            ('unknown', 10)
        ]
        
        for cat, expected_priority in categories:
            self.assertEqual(
                injector._get_category_priority(cat), 
                expected_priority,
                f"Category {cat} priority mismatch"
            )

    def test_category_emoji_all(self):
        """测试所有分类emoji"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        
        emojis = [
            'profile', 'task', 'skill', 'identity', 'core_command',
            'lesson', 'experience', 'fact', 'relationship',
            'emotional', 'conversation', 'reflection_log', 'creative'
        ]
        
        for cat in emojis:
            emoji = injector._get_category_emoji(cat)
            self.assertIsNotNone(emoji)
            self.assertIsInstance(emoji, str)


class TestMemoryContextBuilding(unittest.TestCase):
    """测试记忆上下文构建"""

    def test_build_memory_empty(self):
        """测试空记忆构建"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        result = injector._build_memory_context([], "测试")
        self.assertEqual(result, "")

    def test_build_memory_with_crystallized(self):
        """测试固化记忆优先"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        
        memories = [
            {'content': '普通记忆', 'category': 'conversation', 'temperature': 50},
            {'content': '固化记忆', 'category': 'profile', 'temperature': 80, 'is_crystallized': True}
        ]
        
        result = injector._build_memory_context(memories, "测试")
        self.assertIn('固化记忆', result)

    def test_build_memory_with_emoji(self):
        """测试记忆emoji标记"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        
        memories = [
            {'content': 'profile记忆', 'category': 'profile', 'temperature': 80}
        ]
        
        result = injector._build_memory_context(memories, "测试")
        self.assertIn('👤', result)

    def test_build_memory_relevance(self):
        """测试话题相关性"""
        from neurova.context import UnifiedContextInjector
        injector = UnifiedContextInjector(memory_manager=None)
        
        memories = [
            {'content': '天气相关记忆', 'category': 'fact', 'temperature': 50},
            {'content': '无关记忆', 'category': 'fact', 'temperature': 50}
        ]
        
        result = injector._build_memory_context(memories, "今天天气很好")
        self.assertIn('天气相关', result)


class TestBudgetAdjustment(unittest.TestCase):
    """测试预算调整"""

    def test_adjust_budget_sufficient(self):
        """测试充足预算"""
        from neurova.context import UnifiedContextInjector, TokenBudget
        injector = UnifiedContextInjector(memory_manager=None)
        
        history = [{'role': 'user', 'content': '短'}]
        memories = []
        
        result = injector._adjust_budget(history, memories, max_tokens=4000)
        self.assertIsInstance(result, TokenBudget)

    def test_adjust_budget_insufficient(self):
        """测试不足预算"""
        from neurova.context import UnifiedContextInjector, TokenBudget
        injector = UnifiedContextInjector(memory_manager=None)
        
        history = [{'role': 'user', 'content': '长' * 1000}]
        memories = [{'content': '记忆' * 100}]
        
        result = injector._adjust_budget(history, memories, max_tokens=500)
        self.assertIsInstance(result, TokenBudget)
        self.assertLess(result.conversation_history, 4000)


class TestBoundaryConditions(unittest.TestCase):
    """测试边界条件"""

    def setUp(self):
        from neurova.context_compressor import SmartContextCompressor
        self.compressor = SmartContextCompressor()

    def test_truncate_very_long_text(self):
        """测试超长文本截断"""
        text = "内容" * 10000
        result = self.compressor._smart_truncate(text, 0.1)
        self.assertLess(len(result), len(text))

    def test_group_turns_single_message(self):
        """测试单条消息分组"""
        history = [{'role': 'user', 'content': '单独消息'}]
        turns = self.compressor._group_into_turns(history)
        self.assertEqual(len(turns), 1)

    def test_group_turns_assistant_only(self):
        """测试只有助手消息"""
        history = [{'role': 'assistant', 'content': '助手消息'}]
        turns = self.compressor._group_into_turns(history)
        self.assertEqual(len(turns), 1)

    def test_compress_single_turn(self):
        """测试单轮压缩"""
        history = [
            {'role': 'user', 'content': '问题'},
            {'role': 'assistant', 'content': '回答'}
        ]
        compressed, stats = self.compressor._progressive_compress_history(history, budget=100)
        self.assertGreater(len(compressed), 0)


def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        TestSmartContextCompressorCore,
        TestProgressiveCompression,
        TestDynamicBudget,
        TestMemoryCompression,
        TestContextBuilding,
        TestCompressContextIntegration,
        TestContextInjectorHelpers,
        TestMemoryInjector,
        TestMemoryContextBuilding,
        TestBudgetAdjustment,
        TestBoundaryConditions
    ]
    
    for test_class in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    print(f"总测试数: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print("=" * 60)
    
    return result


if __name__ == '__main__':
    print("=" * 60)
    print("Neurova 上下文系统优化 - 全面单元测试")
    print("=" * 60)
    run_all_tests()
