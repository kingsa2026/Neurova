"""P2 标注闭环（TDD — Dify Annotation Reply 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.7/§4 P2）：
- AnnotationStore：人工修正的问答固化为"精准回复"命中表
  （query 指纹 → 精准回复文本 + 元数据），SQLite 持久化
- 固化入口：feedback=like 且提供 corrected_answer 时沉淀为标注；
  纯点赞（无修正文本）不落表（避免同义反复噪声）
- 命中面：match_annotation(store, user_input, threshold)——归一化
  查询指纹精确命中 + 归一化子串兜底，命中即返回精准回复（绕过模型重抽）
- 重训练化集：export_training_set()——点赞对（用户输入→采纳回答）
  JSONL 输出，供后续 SFT/微调集
- 消费钩子：chat 管线检索前查询命中表（可选开关，缺省开）
"""

import pytest

from neurova.core.annotation_store import AnnotationStore, match_annotation


@pytest.fixture
def store(tmp_path):
    return AnnotationStore(str(tmp_path / "annotations.db"))


class TestAnnotationStore:
    def test_add_and_exact_match(self, store):
        ann_id = store.add(
            question="你们的退款政策是什么？",
            answer="7 天无理由退款，联系 support@x.com 处理。",
            source="manual",
        )
        assert ann_id
        hit = match_annotation(store, "你们的退款政策是什么？")
        assert hit is not None
        assert "7 天无理由" in hit["answer"]

    def test_match_normalizes_whitespace_and_case(self, store):
        store.add(question="How to reset API key?", answer="Via settings page.")
        hit = match_annotation(store, "  how to   RESET api  key?  ")
        assert hit is not None
        assert "settings page" in hit["answer"]

    def test_substring_fallback(self, store):
        """归一化子串兜底：长标注答案命中短查询的包含形态"""
        store.add(question="如何重置 API 密钥", answer="在设置页操作。")
        hit = match_annotation(store, "请问如何重置 api 密钥？")
        assert hit is not None

    def test_no_match_returns_none(self, store):
        store.add(question="q1", answer="a1")
        assert match_annotation(store, "完全无关的问题") is None

    def test_disabled_annotation_not_matched(self, store):
        ann_id = store.add(question="q2", answer="a2", enabled=True)
        store.set_enabled(ann_id, False)
        assert match_annotation(store, "q2") is None

    def test_update_answer(self, store):
        ann_id = store.add(question="q3", answer="旧答案")
        store.update_answer(ann_id, "新答案")
        assert "新答案" in match_annotation(store, "q3")["answer"]

    def test_delete(self, store):
        ann_id = store.add(question="q4", answer="a4")
        store.delete(ann_id)
        assert match_annotation(store, "q4") is None

    def test_list_and_count(self, store):
        store.add(question="q5", answer="a5")
        store.add(question="q6", answer="a6")
        assert store.count() >= 2
        assert len(store.list_annotations()) >= 2

    def test_hit_count_tracked(self, store):
        """命中计数（标注价值度量）"""
        ann_id = store.add(question="q7", answer="a7")
        match_annotation(store, "q7")
        match_annotation(store, "q7 ")
        assert store.get(ann_id)["hit_count"] == 2


class TestFeedbackIntegration:
    def test_like_with_correction_creates_annotation(self, tmp_path):
        """点赞 + 修正文本 → 固化为精准回复（在既有 feedback 链路上挂）"""
        from neurova.api.endpoints.console import _maybe_crystallize_annotation

        store = AnnotationStore(str(tmp_path / "a.db"))
        created = _maybe_crystallize_annotation(
            store,
            feedback="like",
            user_input="怎么导出记忆？",
            agent_response="旧回答",
            corrected_answer="在记忆页右上角点导出按钮。",
        )
        assert created is True
        hit = match_annotation(store, "怎么导出记忆？")
        assert hit is not None and "导出按钮" in hit["answer"]

    def test_plain_like_no_annotation(self, tmp_path):
        """纯点赞（无修正文本）不落标注表"""
        from neurova.api.endpoints.console import _maybe_crystallize_annotation

        store = AnnotationStore(str(tmp_path / "a.db"))
        assert _maybe_crystallize_annotation(
            store, feedback="like", user_input="q", agent_response="a", corrected_answer=None
        ) is False
        assert store.count() == 0

    def test_dislike_never_creates(self, tmp_path):
        from neurova.api.endpoints.console import _maybe_crystallize_annotation

        store = AnnotationStore(str(tmp_path / "a.db"))
        assert _maybe_crystallize_annotation(
            store, feedback="dislike", user_input="q", agent_response="a",
            corrected_answer="修正也不行——点踩走抑制",
        ) is False

    def test_duplicate_question_updates_instead_of_dup(self, tmp_path):
        """同问重复修正 → 更新答案（单条目，不堆积）"""
        from neurova.api.endpoints.console import _maybe_crystallize_annotation

        store = AnnotationStore(str(tmp_path / "a.db"))
        _maybe_crystallize_annotation(store, "like", "q8", "a", "答案一")
        _maybe_crystallize_annotation(store, "like", "q8", "a", "答案二")
        assert store.count() == 1
        assert "答案二" in match_annotation(store, "q8")["answer"]


class TestTrainingSetExport:
    def test_export_jsonl(self, tmp_path):
        """点赞对 → JSONL 重训练化集（输入/输出对）"""
        from neurova.api.endpoints.console import _maybe_crystallize_annotation

        store = AnnotationStore(str(tmp_path / "a.db"))
        _maybe_crystallize_annotation(store, "like", "输入甲", "旧", "输出甲")
        _maybe_crystallize_annotation(store, "like", "输入乙", "旧", "输出乙")
        store.add(question="禁用条目", answer="不应导出", enabled=False)

        import json

        lines = store.export_training_set()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert set(first.keys()) >= {"input", "output"}
