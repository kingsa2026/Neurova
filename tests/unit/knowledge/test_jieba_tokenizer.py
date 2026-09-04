"""P0-1 jieba 真分词（Utopia 对标落地清单）。

契约（docs/Neurova_Utopia代码级对比_2026-09-04.md §4 P0-1）：
- knowledge.search.tokenize：安装 jieba 时用 jieba 词级切分（"量子计算" →
  ["量子","计算"]），未安装时回退旧 n-gram 规则（可选依赖纪律）；
- 英文按空格/词切分，标点剥离，单字噪声不进 token；
- knowledge.search.full_text_search：语义级查询词命中语义级文档（"量子计算"
  能命中含"量子计算"的文档，且得分严格高于只含"计算"的文档）；
- semantic_search_api._tokenize 与 knowledge.search.tokenize 同源（BM25 通道
  与 FTS 通道保持可比）。
"""

import pytest

from neurova.knowledge.search import full_text_search, tokenize


class TestTokenize:
    def test_chinese_splits_to_words_with_jieba(self):
        tokens = tokenize("量子计算在金融领域的应用")
        assert "量子" in tokens
        assert "计算" in tokens
        assert "金融" in tokens
        # 旧 n-gram 会产出 "量子计算" 4 字片段；jieba 词级切分不再有跨词粘连
        assert "量子计算" not in tokens

    def test_english_lowercased_word_split(self):
        tokens = tokenize("Machine Learning Guide")
        assert tokens == ["machine", "learning", "guide"]

    def test_punctuation_stripped(self):
        tokens = tokenize("什么是RAG？检索增强生成！")
        assert "rag" in tokens
        assert all("？" not in t and "！" not in t for t in tokens)

    def test_single_char_noise_dropped(self):
        tokens = tokenize("我 在 学 AI")
        assert "我" not in tokens
        assert "ai" in tokens

    def test_empty_and_none_safe(self):
        assert tokenize("") == []
        assert tokenize("   ") == []

    @pytest.mark.parametrize(
        "query,doc,expect_hit",
        [
            ("量子计算", "量子计算使用量子比特进行并行运算。", True),
            ("机器学习", "机器学习是人工智能的核心分支。", True),
            ("量子计算机", "今天天气不错。", False),
        ],
    )
    def test_real_phrase_pairs(self, query, doc, expect_hit):
        tokens = tokenize(doc)
        q_tokens = tokenize(query)
        hit = any(t in tokens for t in q_tokens)
        assert hit is expect_hit


class TestFullTextSearchJieba:
    def _corpus(self):
        return [
            {"id": "quantum", "content": "量子计算使用量子比特进行并行运算。"},
            {"id": "plain_compute", "content": "经典计算依赖二进制逻辑门。"},
            {"id": "weather", "content": "今天天气不错。"},
        ]

    def test_semantic_query_hits_semantic_doc(self):
        hits = full_text_search("量子计算", self._corpus(), top_k=10)
        ids = [h[0] for h in hits]
        assert "quantum" in ids
        assert "weather" not in ids

    def test_exact_doc_scores_higher_than_partial(self):
        hits = dict(full_text_search("量子计算", self._corpus(), top_k=10))
        assert hits["quantum"] > hits["plain_compute"]

    def test_no_hit_returns_empty(self):
        assert full_text_search("不存在的词组", self._corpus(), top_k=10) == []


class TestJiebaAbsentFallback:
    """P0-1 闭环审查：B 修复——缺席路径必须走 n-gram 且打 WARN。

    旧实现 search.py:79-91 静默 except 把 _jieba 置 False，CI 没装 jieba
    时所有用例全红；本次补 monkeypatch 强制缺席 + 验证回退行为。
    """

    def test_absent_jieba_falls_back_to_ngram(self, monkeypatch):
        import neurova.knowledge.search as search_mod

        monkeypatch.setattr(search_mod, "_jieba", False)
        tokens = search_mod.tokenize("量子计算")
        # n-gram 产 2-4 字片段（含跨词粘连）；明确"量子计算"必在
        assert "量子计算" in tokens
        # 且一定不会 jieba 词级切出"量子"+"计算"两个独立项
        assert not ({"量子", "计算"}.issubset(set(tokens)))

    def test_absent_jieba_logs_warning(self, monkeypatch, caplog):
        import logging

        import neurova.knowledge.search as search_mod

        monkeypatch.setattr(search_mod, "_jieba", False)
        # 强制 _get_jieba 重走 except 路径
        monkeypatch.setattr(search_mod, "_jieba", None)
        import builtins

        real_import = builtins.__import__

        def deny_jieba(name, *args, **kwargs):
            if name == "jieba" or name.startswith("jieba."):
                raise ImportError("simulated: jieba 缺席")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", deny_jieba)
        with caplog.at_level(logging.WARNING, logger="neurova.knowledge.search"):
            assert search_mod.tokenize("测试") == search_mod._ngram_tokenize("测试")
        assert any("jieba 不可用" in r.message for r in caplog.records)
