"""
Neurova 上下文注入面 - 单元测试（记忆注入 / 预算调整）

来源沿革（B6-10 批次 C）：本文件原含 2 个类锁定一份已退役的可插拔压缩实现
（`CompressionConfig` / `SmartContextCompressor`），该实现与唯一调用点双不符
（TypeError 被 except 吞掉），即"装配即弃"；压缩真通路是 `orchestrator` 的
信封+历史确定性淘汰（判据：`tests/unit/context/test_envelope.py`）。
仍然存活的注入面契约保留在本文件，断言未删。
"""

import unittest
from typing import Dict, List






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
