"""
TDD RED：暴露 NLToolSynthesizer 双实现契约不匹配问题（P0-B3）

验证 NLToolSynthesizer 的真实实现（neurova/evolution/nl_synthesizer.py）
与 agent_core.py 的调用契约一致：

1. NLToolSynthesizer 应接受 pattern_miner kwarg
   - agent_core.py:631 调用 NLToolSynthesizer(pattern_miner=a.pattern_miner)
   - 真实实现的 __init__ 之前不接受此参数 → TypeError → tool_synthesizer 永远为 None
2. NLToolSynthesizer 应能正常初始化（不抛异常）

根因：
    neurova/agent_core.py:631
        a.tool_synthesizer = NLToolSynthesizer(pattern_miner=a.pattern_miner)
    neurova/evolution/nl_synthesizer.py:136（修复前）
        def __init__(self, min_confidence=0.3, max_sequence_length=5, enable_pattern_mining=True):
        # 不接受 pattern_miner
    neurova/evolution/closed_loop.py:189（占位符实现）
        class NLToolSynthesizer:
            def __init__(self, pattern_miner=None):  # 接受 pattern_miner，但是另一个类
"""

import pytest


class TestNLToolSynthesizerContract:
    """测试 NLToolSynthesizer 调用契约"""

    def test_init_accepts_pattern_miner_kwarg(self):
        """P0-B3: NLToolSynthesizer 应接受 pattern_miner kwarg

        场景：调用 NLToolSynthesizer(pattern_miner=some_miner)
        期望：构造成功，不抛 TypeError
        当前：真实实现 __init__ 不接受 pattern_miner → TypeError
        """
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer

        # 不应抛 TypeError
        synthesizer = NLToolSynthesizer(pattern_miner=None)

        assert synthesizer is not None, "NLToolSynthesizer 应成功构造"

    def test_init_with_real_pattern_miner(self):
        """P0-B3: 应能传入真实的 PatternMiner 实例

        场景：构造 PatternMiner 并传给 NLToolSynthesizer
        期望：构造成功，且 pattern_miner 被保留
        当前：TypeError
        """
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer
        from neurova.evolution.pattern_miner import PatternMiner

        pattern_miner = PatternMiner()
        synthesizer = NLToolSynthesizer(pattern_miner=pattern_miner)

        # pattern_miner 应被保留（agent_core 期望此集成点）
        assert hasattr(synthesizer, "_pattern_miner"), (
            "NLToolSynthesizer 应保留 pattern_miner 引用为 _pattern_miner 属性"
        )
        assert synthesizer._pattern_miner is pattern_miner, (
            "_pattern_miner 应是传入的 PatternMiner 实例"
        )

    def test_agent_core_imports_real_implementation(self):
        """P0-B3: agent_core 应导入真实的 NLToolSynthesizer（非 closed_loop 占位符）

        场景：检查 from neurova.evolution import NLToolSynthesizer 导入的类
        期望：是 nl_synthesizer.py 中的真实实现，而非 closed_loop.py 的占位符
        """
        from neurova.evolution import NLToolSynthesizer as ImportedClass
        from neurova.evolution.nl_synthesizer import NLToolSynthesizer as RealClass

        assert ImportedClass is RealClass, (
            "from neurova.evolution import NLToolSynthesizer 应导入真实实现 "
            "(nl_synthesizer.py)，而非 closed_loop.py 的占位符"
        )
