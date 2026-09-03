"""
Neurova 上下文系统优化 - 单元测试
测试智能压缩和记忆注入功能
"""

import unittest
from typing import Dict, List


class TestCompressionConfig(unittest.TestCase):
    """测试 CompressionConfig 配置"""

    def test_config_defaults(self):
        """测试默认配置"""
        from neurova.context_compressor import CompressionConfig

        config = CompressionConfig()
        self.assertEqual(config.max_context_tokens, 8000)
        self.assertEqual(config.memory_budget, 2000)
        self.assertEqual(config.conversation_history_budget, 5000)
        self.assertTrue(config.enable_progressive_compression)
        self.assertEqual(config.recent_turns_full, 2)

    def test_config_custom(self):
        """测试自定义配置"""
        from neurova.context_compressor import CompressionConfig

        config = CompressionConfig(
            enable_progressive_compression=False,
            recent_turns_full=3
        )
        self.assertFalse(config.enable_progressive_compression)
        self.assertEqual(config.recent_turns_full, 3)


class TestSmartContextCompressor(unittest.TestCase):
    """测试 SmartContextCompressor 压缩器"""

    def setUp(self):
        """测试前的准备工作"""
        from neurova.context_compressor import SmartContextCompressor

        self.compressor = SmartContextCompressor()

    def test_smart_truncate(self):
        """测试智能截断功能"""
        text = "这是一段很长的中文文本。我们需要看看它会如何被截断。句号是很重要的。"

        result = self.compressor._smart_truncate(text, 0.5)

        # 应该包含部分文本
        self.assertIsNotNone(result)
        self.assertLess(len(result), len(text))
        # 应该在自然断点截断
        self.assertIn('。', result[:-3] if result.endswith('...') else result)

    def test_smart_truncate_short_text(self):
        """测试短文本不需要截断"""
        text = "这是短文本。"

        result = self.compressor._smart_truncate(text, 0.5)

        # 短文本应该原样返回
        self.assertEqual(result, text)

    def test_calculate_dynamic_budget(self):
        """测试动态预算计算"""
        # 创建一个短对话
        history_short = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好，有什么可以帮你'}
        ]

        # 创建一个长对话
        history_long = []
        for i in range(100):
            history_long.append({'role': 'user', 'content': f'第{i}轮对话'})
            history_long.append({'role': 'assistant', 'content': f'回复第{i}轮'})

        # 短对话预算应该较低
        budget_short = self.compressor._calculate_dynamic_budget(history_short)

        # 长对话预算应该较高
        budget_long = self.compressor._calculate_dynamic_budget(history_long)

        self.assertLessEqual(budget_short, budget_long)


class TestUnifiedContextInjectorMemory(unittest.TestCase):
    """测试记忆注入和分类"""

    def test_extract_keywords(self):
        """测试关键词提取"""
        from neurova.context import UnifiedContextInjector

        injector = UnifiedContextInjector(memory_manager=None)

        text = "今天天气很好，我想去公园散步。"
        keywords = injector._extract_keywords(text, top_k=3)

        # 应该提取到关键词
        self.assertTrue(isinstance(keywords, list))

    def test_get_category_priority(self):
        """测试记忆分类优先级"""
        from neurova.context import UnifiedContextInjector

        injector = UnifiedContextInjector(memory_manager=None)

        # 高优先级分类
        self.assertEqual(injector._get_category_priority('profile'), 50)
        self.assertEqual(injector._get_category_priority('core_command'), 50)

        # 中等优先级
        self.assertEqual(injector._get_category_priority('task'), 45)
        self.assertEqual(injector._get_category_priority('lesson'), 35)

        # 低优先级
        self.assertEqual(injector._get_category_priority('conversation'), 15)

        # 未知分类默认优先级
        self.assertEqual(injector._get_category_priority('unknown'), 10)

    def test_get_category_emoji(self):
        """测试分类emoji"""
        from neurova.context import UnifiedContextInjector

        injector = UnifiedContextInjector(memory_manager=None)

        # 应该返回对应emoji
        self.assertEqual(injector._get_category_emoji('profile'), '👤')
        self.assertEqual(injector._get_category_emoji('task'), '📋')

        # 未知分类默认emoji
        self.assertEqual(injector._get_category_emoji('unknown'), '📌')


class TestMemoryContextBuilding(unittest.TestCase):
    """测试记忆上下文构建"""

    def test_memory_sorting(self):
        """测试记忆排序功能"""
        from neurova.context import UnifiedContextInjector

        injector = UnifiedContextInjector(memory_manager=None)

        # 创建测试记忆
        memories = [
            {'content': '高优先级记忆', 'category': 'profile', 'temperature': 80, 'is_crystallized': True},
            {'content': '中优先级记忆', 'category': 'task', 'temperature': 60, 'is_important': True},
            {'content': '低优先级记忆', 'category': 'conversation', 'temperature': 30}
        ]

        # 构建上下文
        context = injector._build_memory_context(memories, '测试输入')

        # 应该包含记忆内容
        self.assertIn('高优先级', context)

    def test_empty_memories(self):
        """测试空记忆情况"""
        from neurova.context import UnifiedContextInjector

        injector = UnifiedContextInjector(memory_manager=None)

        context = injector._build_memory_context([], '测试输入')

        # 空记忆应该返回空字符串
        self.assertEqual(context, '')


class TestBudgetAdjustment(unittest.TestCase):
    """测试预算调整功能"""

    def test_adjust_budget(self):
        """测试预算调整"""
        from neurova.context import UnifiedContextInjector, TokenBudget

        injector = UnifiedContextInjector(memory_manager=None)

        # 创建测试数据
        history = [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好'}]
        memories = [{'content': '测试记忆'}]

        # 调整预算
        adjusted = injector._adjust_budget(history, memories, max_tokens=4000)

        # 应该返回TokenBudget对象
        self.assertTrue(hasattr(adjusted, 'max_total'))
        self.assertTrue(hasattr(adjusted, 'system_prompt'))
        self.assertTrue(hasattr(adjusted, 'memories'))
        self.assertTrue(hasattr(adjusted, 'conversation_history'))


def create_test_data():
    """创建测试数据"""
    test_messages = []

    # 创建10轮对话
    for i in range(10):
        test_messages.extend([
            {
                'role': 'user',
                'content': f'用户第{i}轮提问：这是一个测试问题，我们来测试一下对话上下文压缩功能。'
            },
            {
                'role': 'assistant',
                'content': f'AI第{i}轮回复：好的，我会尽力回答您的问题。这是回复内容。'
            }
        ])

    return test_messages


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加所有测试
    suite.addTests(loader.loadTestsFromTestCase(TestCompressionConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartContextCompressor))
    suite.addTests(loader.loadTestsFromTestCase(TestUnifiedContextInjectorMemory))
    suite.addTests(loader.loadTestsFromTestCase(TestMemoryContextBuilding))
    suite.addTests(loader.loadTestsFromTestCase(TestBudgetAdjustment))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == '__main__':
    print("=" * 60)
    print("Neurova 上下文系统优化 - 单元测试")
    print("=" * 60)
    run_tests()
