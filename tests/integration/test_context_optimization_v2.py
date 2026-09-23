"""
Neurova 上下文注入面 - 集成测试（记忆注入 / 预算调整 / 注入器辅助）

来源沿革（B6-10 批次 C）：本文件原含 7 个类锁定一份已退役的可插拔压缩实现
（`neurova/context_compressor.py` 的 `SmartContextCompressor`）——它的真实签名
与唯一调用点（`injector._compress_context`）双不符，TypeError 被 except 吞掉，
即"装配即弃"。压缩真通路是 `orchestrator` 的信封+历史确定性淘汰
（判据：`tests/unit/context/test_envelope.py` 的 20 条），故那些类随该实现
整模块退场。**仍然存活**的注入面契约保留在本文件，断言未删。
"""

import unittest
from typing import Dict, List, Tuple














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




def run_all_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    test_classes = [
        TestContextInjectorHelpers,
        TestMemoryInjector,
        TestMemoryContextBuilding,
        TestBudgetAdjustment,
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
