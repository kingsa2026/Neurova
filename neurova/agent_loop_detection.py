"""内容循环检测工具

从 agent_core.py 提取的纯函数，用于检测对话内容是否陷入循环。
"""

import re
from typing import List


def calculate_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度

    使用简化的字符级相似度计算，基于共同字符的比例。
    """
    if not text1 or not text2:
        return 0.0

    # 转换为小写并去除标点符号
    clean1 = re.sub(r"[^\w\s]", "", text1.lower())
    clean2 = re.sub(r"[^\w\s]", "", text2.lower())

    # 计算共同字符数
    set1 = set(clean1)
    set2 = set(clean2)

    if not set1 or not set2:
        return 0.0

    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))

    return intersection / union if union > 0 else 0.0


def has_repeated_patterns(contents: List[str]) -> bool:
    """
    检测是否有重复的句子或段落模式

    将内容分割成句子，检查是否有重复的句子序列。
    """
    # 将每个内容分割成句子
    all_sentences = []
    for content in contents:
        # 简单的句子分割（按句号、问号、感叹号）
        sentences = re.split(r"[。！？.!?]", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        all_sentences.extend(sentences)

    # 检查是否有重复的句子
    if len(all_sentences) > 3:
        # 检查最后几个句子是否与前面的句子重复
        recent_sentences = all_sentences[-3:]
        earlier_sentences = all_sentences[:-3]

        for recent in recent_sentences:
            if len(recent) > 20:  # 只检查长度足够的句子
                for earlier in earlier_sentences:
                    # 计算句子相似度
                    similarity = calculate_similarity(recent, earlier)
                    if similarity > 0.9:  # 句子相似度阈值更高
                        return True

    return False


def detect_content_loop(contents: List[str], threshold: float = 0.8) -> bool:
    """
    检测内容循环

    通过比较最近 N 次内容的相似度，判断是否陷入循环。
    使用简单的字符级相似度计算，避免复杂的 NLP 处理。

    Args:
        contents: 最近的内容列表
        threshold: 相似度阈值，超过此值认为是循环

    Returns:
        True 表示检测到循环，False 表示未检测到
    """
    if len(contents) < 2:
        return False

    # 计算相邻内容的相似度
    similarities = []
    for i in range(1, len(contents)):
        prev = contents[i - 1]
        curr = contents[i]

        # 简单的字符级相似度计算
        similarity = calculate_similarity(prev, curr)
        similarities.append(similarity)

    # 如果所有相邻内容的相似度都超过阈值，认为是循环
    if similarities and all(s > threshold for s in similarities):
        return True

    # 检查是否有重复的句子或段落
    if has_repeated_patterns(contents):
        return True

    return False
