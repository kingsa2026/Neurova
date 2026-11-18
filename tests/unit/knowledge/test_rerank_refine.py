"""P0#3 Rerank 精修四连测试。

四件纯函数：
1. clean_passage_for_rerank：重排前清洗——拆代码围栏/LaTeX（让代码/公式块
   在 rerank 模型下可被判相关，而非因非自然语言恒 0）、表格转逗号文本、
   链接→锚文本、图片移除、URL 去裸、markdown 标记剥离、空白压缩。
2. threshold_fallback：阈值降级重试——候选全低于阈值时按 0.7× 降档（floor
   给下限），返回生效阈值与被保留集；供 rerank 出口避免"全被阈值打死→空"。
3. composite_score：复合分 0.6*model + 0.3*base + 0.1*source，clamp [0,1]。
4. mmr_select：MMR λ 多样性选择（词法 Jaccard 相似度，无 embedding 依赖），
   抑制近重复候选霸榜 top-K。
"""

import pytest

from neurova.knowledge.rerank import refine


class TestCleanPassage:
    def test_code_fence_unwrapped(self):
        raw = "示例：\n```python\ndef f(): return 42\n```\n结束"
        out = refine.clean_passage_for_rerank(raw)
        assert "```" not in out
        assert "def f(): return 42" in out  # 代码内容保留，仅拆围栏标记

    def test_inline_math_unwrapped(self):
        out = refine.clean_passage_for_rerank("公式 $$E=mc^2$$ 说明")
        assert "$$" not in out
        assert "E=mc^2" in out

    def test_link_to_anchor(self):
        out = refine.clean_passage_for_rerank("见 [知识库文档](http://x.com/a) 详情")
        assert "http://x.com/a" not in out
        assert "知识库文档" in out

    def test_image_removed(self):
        out = refine.clean_passage_for_rerank("前 ![图注](http://i.png) 后")
        assert "http://i.png" not in out
        assert "![" not in out

    def test_table_to_comma(self):
        raw = "| 城市 | 人口 |\n|---|---|\n| 北京 | 2100 |"
        out = refine.clean_passage_for_rerank(raw)
        assert "|" not in out
        assert "北京" in out and "2100" in out

    def test_heading_and_blockquote_markers(self):
        out = refine.clean_passage_for_rerank("## 标题\n> 引用内容")
        assert out.lstrip().startswith("标题") or "标题" in out
        assert ">" not in out and "#" not in out

    def test_bold_italic_unwrapped(self):
        out = refine.clean_passage_for_rerank("**重要** 和 *强调* 与 `代码`")
        assert "**" not in out and "*" not in out and "`" not in out
        assert "重要" in out and "强调" in out and "代码" in out

    def test_empty_and_none_safe(self):
        assert refine.clean_passage_for_rerank("") == ""
        assert refine.clean_passage_for_rerank(None) == ""


class TestThresholdFallback:
    def test_all_above_threshold_kept(self):
        pairs = [("a", 0.9), ("b", 0.8)]
        kept, eff = refine.threshold_fallback(pairs, threshold=0.5, floor=0.3)
        assert kept == ["a", "b"] and eff == 0.5

    def test_none_pass_triggers_degrade(self):
        pairs = [("a", 0.5), ("b", 0.45)]
        kept, eff = refine.threshold_fallback(pairs, threshold=0.8, floor=0.3)
        assert kept == ["a", "b"]  # 降到 0.56 后都过？逐档降：0.8→0.56→a,b过
        assert eff < 0.8 and eff >= 0.3

    def test_floor_prevents_over_degrade(self):
        pairs = [("a", 0.2)]  # 低于 floor
        kept, eff = refine.threshold_fallback(pairs, threshold=0.9, floor=0.3)
        assert kept == [] and eff == 0.3  # 降到 floor 仍不过 → 空

    def test_threshold_zero_or_none_no_filter(self):
        pairs = [("a", 0.01)]
        kept, eff = refine.threshold_fallback(pairs, threshold=0, floor=0.3)
        assert kept == ["a"] and eff == 0


class TestCompositeScore:
    def test_weighted_blend(self):
        s = refine.composite_score(model=1.0, base=1.0, source=1.0)
        assert s == pytest.approx(1.0)

    def test_formula_exact(self):
        s = refine.composite_score(model=0.9, base=0.6, source=0.95)
        assert s == pytest.approx(0.6 * 0.9 + 0.3 * 0.6 + 0.1 * 0.95, abs=1e-6)

    def test_clamped(self):
        assert refine.composite_score(2.0, 2.0, 2.0) == 1.0
        assert refine.composite_score(-1.0, -1.0, -1.0) == 0.0


class TestMMRSelect:
    def test_diversity_promotes_novel(self):
        # a1/a2 近重复，b 独特。纯按分 a1,a2 占前二；MMR 应把 b 提进前二
        docs = {
            "a1": "知识库检索增强生成管线设计",
            "a2": "知识库检索增强生成管线架构",
            "b": "完全不同的量子计算主题内容",
        }
        scores = {"a1": 0.95, "a2": 0.9, "b": 0.8}
        selected = refine.mmr_select(
            query="知识库", candidate_ids=["a1", "a2", "b"],
            scores=scores, texts=docs, top_k=2, lambda_=0.7,
        )
        assert "b" in selected  # 多样性把独特文档拉进 top-2

    def test_topk_limits(self):
        docs = {"a": "x y", "b": "p q", "c": "m n"}
        sel = refine.mmr_select("q", ["a", "b", "c"], {"a": 1, "b": .9, "c": .8}, docs, top_k=2)
        assert len(sel) == 2

    def test_single_candidate(self):
        assert refine.mmr_select("q", ["a"], {"a": 1}, {"a": "x"}, top_k=3) == ["a"]

    def test_empty(self):
        assert refine.mmr_select("q", [], {}, {}, top_k=3) == []


class TestAPIWiring:
    """semantic-search hybrid 的 rerank 出口接线：默认关零回归、按配置开启。"""

    def _run(self, rerank_cfg):
        import asyncio
        from contextlib import ExitStack
        from unittest.mock import MagicMock, patch

        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, hybrid_search

        corpus = [
            {"id": "m1", "content": "机器学习原理与应用详解", "memory_type": "semantic"},
            {"id": "m2", "content": "机器学习进阶与实践手册", "memory_type": "semantic"},
        ]
        req = MagicMock()
        req.app.state.agents = {}
        mgr = MagicMock()
        mgr.get_all_memories.return_value = corpus
        ss = MagicMock()
        ss.compute_similarity.return_value = 0.5
        with ExitStack() as stack:
            stack.enter_context(
                patch("neurova.api.endpoints.semantic_search_api.get_memory_manager", return_value=mgr)
            )
            stack.enter_context(
                patch("neurova.api.endpoints.semantic_search_api.get_semantic_search", return_value=ss)
            )
            body = HybridSearchRequest(query="机器学习", top_k=2, rerank=rerank_cfg)
            return asyncio.run(hybrid_search(body, req, {"user_id": "1"}))

    def test_default_off_preserves_contract(self):
        data = self._run({"method": "weight"})["data"]
        assert data["results"]
        assert all("rerank_score" in r and "rerank_method" in r for r in data["results"])
        assert "threshold_effective" not in data["results"][0]

    def test_composite_enabled_changes_score_channel(self):
        data = self._run({"method": "weight", "composite": True})["data"]
        assert all("rerank_score" in r for r in data["results"])

    def test_top_k_applied(self):
        data = self._run({"method": "weight", "top_k": 1})["data"]
        assert len(data["results"]) == 1


class TestFinalizeReranked:
    def test_pipeline_composes_all(self):
        """finalize_reranked 串起清洗后复合分+MMR+阈值降级。"""
        reranked = [
            {"index": 0, "score": 0.95},
            {"index": 1, "score": 0.9},
            {"index": 2, "score": 0.3},  # 低分，若开 composite 会被 base 拉
        ]
        base = {0: 0.5, 1: 0.55, 2: 0.9}
        docs = [
            {"content": "知识库甲", "source": "owner"},
            {"content": "知识库乙", "source": "owner"},
            {"content": "量子计算丙", "source": "web"},
        ]
        out = refine.finalize_reranked(
            query="知识库", reranked=reranked, docs=docs, base_scores=base,
            top_k=3, mmr_lambda=0.7, use_composite=True,
        )
        assert [r["index"] for r in out][0] == 0
        # source=web 有 0.95 权重加持 + base 0.9 → index2 复合分被抬高
        assert all("composite" in r for r in out)

    def test_off_by_default_preserves_order(self):
        """不传 use_composite/mmr/threshold → 保持 runner 原序（零回归）。"""
        reranked = [{"index": 0, "score": 0.9}, {"index": 1, "score": 0.8}]
        out = refine.finalize_reranked(
            query="q", reranked=reranked, docs=[{}, {}], base_scores={}, top_k=None,
        )
        assert [r["index"] for r in out] == [0, 1]
