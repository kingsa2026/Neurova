"""情感标注语义化 + "好"字效应回归测试

背景: 旧关键词表 joy 含单字"好"/"棒"，导致 "你好"/"检查网页搜索功能" 被
机械标成 joy（实测 62 万行 99.997% 同一 joy，库被 e2e 回放数据灌爆）。

本次改造验证点:
  - 语义优先: SemanticEmotionClassifier（嵌入原型句 zero-shot，非词面命中）
  - 规则兜底: 修正词表（多字词 + 否定守卫 + ASCII 词边界）
  - 落库回读: set_emotion -> 新模块 get_emotion 从 DB 恢复
  - Manager 自动打标: remember() 非中性才写 emotion 行
"""
import os
import shutil
import tempfile
import unittest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
    EmotionModule,
    EmotionState,
    EmotionType,
)
from neurova.cognitive_layers.memory_layer.semantic_emotion import SemanticEmotionClassifier

# 8 维正交轴（与 PROTOTYPE_TEXTS 的 8 个情感键一一对应）
_AXIS_KEYS = ["joy", "sadness", "anger", "fear", "surprise", "disgust", "trust", "neutral"]


def _axis(emotion: str) -> list:
    vec = [0.0] * len(_AXIS_KEYS)
    vec[_AXIS_KEYS.index(emotion)] = 1.0
    return vec


def _fake_encoder(text: str) -> list:
    """确定性假编码器: 关键语句绑定到对应正交轴, 未知文本一律判 neutral 轴"""
    mapping = {
        # 原型句（与 PROTOTYPE_TEXTS 一致）
        "我今天特别开心，遇见了喜欢的事情，心情真的很好": "joy",
        "我很难过，心里很悲伤，很失落，十分沮丧": "sadness",
        "我非常生气，简直愤怒，无法容忍这么讨厌的事情": "anger",
        "我很害怕，非常担心，感到焦虑紧张不安": "fear",
        "太意外了！我完全没想到，真是惊讶极了": "surprise",
        "我太反感了，觉得很恶心，令人厌恶": "disgust",
        "我很信任他，完全相信，值得依靠": "trust",
        "今天天气不错，我去市场买了些日常用品，一切如常": "neutral",
        # 查询文本
        "我今天特别开心": "joy",
        "你好，请问现在几点": "neutral",
        "检查网页搜索功能": "neutral",
        "心情很不好，实在太糟了": "sadness",
    }
    return _axis(mapping.get(text, "neutral"))


class _BreakClassifier:
    """损坏的分类器: analyze 直接抛异常, 验证规则引擎兜底"""

    def analyze(self, text: str):
        raise RuntimeError("encoder broken")


class TestSemanticClassifier(unittest.TestCase):
    """语义分类器: zero-shot 原型分类 + 安全降级"""

    def _classifier(self, encoder=None):
        return SemanticEmotionClassifier(encoder=encoder or _fake_encoder)

    def test_semantic_positive(self):
        """语义明显正向 -> joy, 且强度 0-1"""
        res = self._classifier().analyze("我今天特别开心")
        self.assertIsNotNone(res)
        emotion, intensity = res
        self.assertEqual(emotion, "joy")
        self.assertGreaterEqual(intensity, 0.2)
        self.assertLessEqual(intensity, 1.0)

    def test_neutral_no_hao_effect(self):
        """'你好'/'检查网页搜索功能' 在语义路径下不产生情感标注（好字效应根除）"""
        c = self._classifier()
        self.assertIsNone(c.analyze("你好，请问现在几点"))
        self.assertIsNone(c.analyze("检查网页搜索功能"))

    def test_negative_via_semantics(self):
        """否定语境 '心情很不好' 判悲伤，而非 joy"""
        c = self._classifier()
        self.assertEqual(c.analyze("心情很不好，实在太糟了")[0], "sadness")

    def test_no_encoder_returns_none(self):
        """无编码器 -> None（调用方降级规则），不抛异常"""
        self.assertIsNone(SemanticEmotionClassifier().analyze("我今天特别开心"))

    def test_dim_mismatch_safe(self):
        """查询向量维度与原型不一致 -> None（防 TF-IDF 词表漂移误标）"""

        def wrong_dim(text):
            return [1.0] * 4

        self.assertIsNone(self._classifier(wrong_dim).analyze("我今天特别开心"))

    def test_zero_vector_safe(self):
        """零向量 -> 不可用 -> None"""

        def zero_vec(text):
            return [0.0] * 8

        self.assertIsNone(self._classifier(zero_vec).analyze("我今天特别开心"))


class TestEmotionModuleRules(unittest.TestCase):
    """无语义分类器时的规则兜底: 修正词表"""

    def _module(self):
        return EmotionModule()  # 不注入 semantic_classifier -> 纯规则

    def test_rules_no_single_char_hao(self):
        """单字'好/棒/烦'不再触发 joy/anger"""
        m = self._module()
        self.assertEqual(m.analyze_text_emotion("你好").primary_emotion, EmotionType.NEUTRAL)
        self.assertEqual(m.analyze_text_emotion("检查网页搜索功能").primary_emotion, EmotionType.NEUTRAL)
        self.assertEqual(m.analyze_text_emotion("麻烦你了").primary_emotion, EmotionType.NEUTRAL)
        self.assertEqual(m.analyze_text_emotion("goodbye").primary_emotion, EmotionType.NEUTRAL)

    def test_rules_positive_compound(self):
        """多字正向词仍可命中"""
        m = self._module()
        self.assertEqual(m.analyze_text_emotion("今天真的很开心！").primary_emotion, EmotionType.JOY)
        self.assertEqual(m.analyze_text_emotion("我非常高兴").primary_emotion, EmotionType.JOY)

    def test_rules_negative_keywords(self):
        """消极词表正常识别"""
        m = self._module()
        self.assertEqual(m.analyze_text_emotion("我很难过，非常伤心").primary_emotion, EmotionType.SADNESS)
        self.assertEqual(m.analyze_text_emotion("我特别生气").primary_emotion, EmotionType.ANGER)

    def test_rules_negation_guard(self):
        """否定守卫: '不好/不开心/不喜欢' 判悲伤，防被 joy 词表误标"""
        m = self._module()
        self.assertEqual(m.analyze_text_emotion("心情不好").primary_emotion, EmotionType.SADNESS)
        self.assertEqual(m.analyze_text_emotion("我不开心").primary_emotion, EmotionType.SADNESS)
        self.assertEqual(m.analyze_text_emotion("我不喜欢这样").primary_emotion, EmotionType.SADNESS)

    def test_rules_ascii_word_boundary(self):
        """英文词整词匹配: 'I feel sad' 命中, 'goodbye' 不因 good 误标"""
        m = self._module()
        self.assertEqual(m.analyze_text_emotion("I feel sad today").primary_emotion, EmotionType.SADNESS)


class TestSemanticFirstWithFallback(unittest.TestCase):
    """语义路径优先 + 损坏时规则兜底"""

    def test_semantic_first_used(self):
        m = EmotionModule(semantic_classifier=SemanticEmotionClassifier(encoder=_fake_encoder))
        res = m.analyze_text_emotion("我今天特别开心")
        self.assertEqual(res.primary_emotion, EmotionType.JOY)

    def test_fallback_on_classifier_error(self):
        m = EmotionModule(semantic_classifier=_BreakClassifier())
        self.assertEqual(m.analyze_text_emotion("今天真的很开心").primary_emotion, EmotionType.JOY)


class TestEmotionPersistence(unittest.TestCase):
    """情感标注落库并可从新实例回读"""

    def test_set_get_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        try:
            db = os.path.join(tmpdir, "emotion.db")
            m1 = EmotionModule(db_path=db)
            m1.set_emotion("mem_000001", EmotionState(
                primary_emotion=EmotionType.JOY,
                intensity=0.8, valence=0.8, arousal=0.6,
            ))
            m1.set_emotion("mem_000002", EmotionState(
                primary_emotion=EmotionType.SADNESS,
                intensity=0.5, valence=-0.6, arousal=0.3,
            ))
            self.assertEqual(len(m1._memory_emotions), 2)

            m2 = EmotionModule(db_path=db)
            self.assertEqual(m2.get_emotion("mem_000001").primary_emotion, EmotionType.JOY)
            self.assertEqual(m2.get_emotion("mem_000002").primary_emotion, EmotionType.SADNESS)
            self.assertIsNone(m2.get_emotion("mem_999999"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestManagerAutoTagging(unittest.TestCase):
    """MemoryManager.remember 自动打标: 非中性写入, 中性不写入（好字效应端到端）"""

    def _manager(self, tmpdir):
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager

        return MemoryManager(
            db_path=os.path.join(tmpdir, "test_tagging.db"),
            agent_id="test_agent",
            user_id="test_user",
        )

    def _remember(self, mgr, content):
        return mgr.remember(
            content,
            auto_analyze_emotion=False,
            auto_classify=False,
        )

    def test_emotional_memory_gets_emotion(self):
        tmpdir = tempfile.mkdtemp()
        try:
            mgr = self._manager(tmpdir)
            mem_id = self._remember(mgr, "我今天特别开心！终于等到这一天")
            emo = mgr.emotion_module.get_emotion(mem_id)
            self.assertIsNotNone(emo, "情感明确的内容应写入 emotion 行")
            self.assertEqual(emo.primary_emotion, EmotionType.JOY)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_hello_no_emotion_row(self):
        """'你好' 不再产生 emotion 行 —— 好字效应端到端回归"""
        tmpdir = tempfile.mkdtemp()
        try:
            mgr = self._manager(tmpdir)
            mem_id = self._remember(mgr, "你好，请问现在几点")
            self.assertIsNone(
                mgr.emotion_module.get_emotion(mem_id),
                "中性内容不应写入 emotion 行",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_remember_null_category_persists(self):
        """API 传 category=None 时不再炸 persist（'NoneType' has no attribute 'value'）"""
        import sqlite3

        tmpdir = tempfile.mkdtemp()
        try:
            mgr = self._manager(tmpdir)
            mem_id = mgr.remember(
                "发布一条新记录",
                category=None,
                auto_analyze_emotion=False,
                auto_classify=False,
            )
            conn = sqlite3.connect(os.path.join(tmpdir, "neurova_memories_persist.db"))
            row = conn.execute(
                "SELECT content, category FROM memories WHERE id=?", (mem_id,)
            ).fetchone()
            self.assertIsNotNone(row, "category=None 的记忆应正常持久化")
            self.assertEqual(row[1], "general")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
