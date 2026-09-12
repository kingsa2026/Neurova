#!/usr/bin/env python3
"""
Token 估算计算对比脚本
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from neurova.context_compressor import Message
from neurova.context_pool import ContextPoolUtils


def count_tokens_injector(text: str) -> int:
    """
    模拟 injector.py 的 _count_tokens 方法
    
    使用 TokenBudget 的默认值:
    - chinese_ratio = 1.5
    - english_ratio = 0.25
    """
    if not text:
        return 0
    
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    
    return int(
        chinese_chars * 1.5 +  # TokenBudget.chinese_ratio
        other_chars * 0.25     # TokenBudget.english_ratio
    )


def test_text(text: str, label: str):
    """测试单个文本"""
    print(f"\n{'='*60}")
    print(f"测试文本: {label}")
    print(f"文本内容: {text}")
    print(f"文本长度: {len(text)} 字符")
    
    # 方法1: injector.py - _count_tokens
    injector_tokens = count_tokens_injector(text)
    
    # 方法2: context_pool.py - ContextPoolUtils.estimate_tokens
    pool_tokens = ContextPoolUtils.estimate_tokens(text)
    
    # 方法3: context_compressor.py - Message.estimate_tokens
    message = Message(role="user", content=text)
    compressor_tokens = message.estimate_tokens()
    
    # 方法4: context_compressor.py - len() // 4
    rough_tokens = len(text) // 4
    
    print(f"\nToken 估算结果:")
    print(f"  1. injector.py (_count_tokens):      {injector_tokens:6d} tokens")
    print(f"  2. context_pool.py (estimate_tokens): {pool_tokens:6d} tokens")
    print(f"  3. context_compressor.py (Message):   {compressor_tokens:6d} tokens")
    print(f"  4. len() // 4 (粗略估算):             {rough_tokens:6d} tokens")
    
    # 计算统计
    tokens = [injector_tokens, pool_tokens, compressor_tokens, rough_tokens]
    max_token = max(tokens)
    min_token = min(tokens)
    avg_token = sum(tokens) / len(tokens)
    
    if min_token > 0:
        ratio = max_token / min_token
    else:
        ratio = float('inf')
    
    print(f"\n统计:")
    print(f"  最大值: {max_token}")
    print(f"  最小值: {min_token}")
    print(f"  平均值: {avg_token:.1f}")
    print(f"  差异倍数: {ratio:.2f}x")
    
    if ratio > 1.5:
        print(f"  ⚠️  问题存在: 差异倍数 > 1.5x")
    else:
        print(f"  ✅ 问题不明显: 差异倍数 ≤ 1.5x")
    
    return ratio


def main():
    """主函数"""
    print("Token 估算不一致性分析")
    print("="*60)
    
    # 测试用例
    test_cases = [
        ("中文文本", "这是一个测试文本，包含中文字符。"),
        ("英文文本", "This is a test text with English words."),
        ("混合文本", "Hello 你好 World 世界 Test 测试"),
        ("长中文文本", "神经网络是一种受人脑启发的计算模型，它由大量相互连接的节点（神经元）组成，能够处理复杂的信息。通过学习训练数据中的模式，神经网络可以执行图像识别、自然语言处理、语音识别等任务。"),
        ("长英文文本", "Neural networks are computing systems inspired by the biological neural networks that constitute animal brains. They are based on a collection of connected units or artificial neurons, which loosely model the neurons in a biological brain."),
        ("代码文本", "def calculate_tokens(text): return len(text) // 4"),
        ("标点符号多", "你好！世界。测试？结束。"),
        ("数字多", "12345 67890 11111 22222 33333"),
        ("空格多", "Hello   World   Test   Spaces"),
    ]
    
    ratios = []
    for label, text in test_cases:
        ratio = test_text(text, label)
        ratios.append(ratio)
    
    # 总结
    print("\n" + "="*60)
    print("总结")
    print("="*60)
    
    max_ratio = max(ratios)
    min_ratio = min(ratios)
    avg_ratio = sum(ratios) / len(ratios)
    
    print(f"最大差异倍数: {max_ratio:.2f}x")
    print(f"最小差异倍数: {min_ratio:.2f}x")
    print(f"平均差异倍数: {avg_ratio:.2f}x")
    
    # 问题诊断
    print("\n问题诊断:")
    print("1. injector.py: 使用 chinese_ratio=1.5, english_ratio=0.25")
    print("2. context_pool.py: 使用中文字符*1.5 + 英文单词*0.25")
    print("3. context_compressor.py Message: 使用中文字符*2 + 英文单词*1")
    print("4. len() // 4: 粗略估算，不区分语言")
    
    print("\n影响:")
    print("- 预算控制不可预测")
    print("- 压缩行为不一致")
    print("- 同段文本可能被过度压缩或不足压缩")
    
    print("\n建议修复方案:")
    print("1. 创建统一的 TokenEstimator 类")
    print("2. 所有文件使用相同的估算算法")
    print("3. 使用 tiktoken 或类似的库进行精确估算")
    print("4. 提供可配置的估算策略")


if __name__ == "__main__":
    main()