"""模型 tokenizer 计数与回退口径。"""
from neurova.knowledge.token_count import countModelTokens


def test_count_uses_tiktoken_when_available_and_marks_exact():
    count, exact, source = countModelTokens("hello world", model="gpt-4")
    assert count > 0
    assert source in ("tiktoken", "jieba/ngram")
    if source == "tiktoken":
        assert exact is True


def test_count_unknown_model_falls_back_estimated():
    count, exact, source = countModelTokens("hello world", model="not-a-real-model")
    assert count > 0
    assert exact is False


def test_empty_text_zero():
    count, _exact, _source = countModelTokens("", model="gpt-4")
    assert count == 0


def test_chat_pipeline_counts_with_runtime_model(monkeypatch):
    """检索 token 必须拿当轮运行模型去分词，而不是空模型名退回通用编码。"""
    import neurova.knowledge.token_count as token_count

    seen_models = []

    def fakeCount(text, model=""):
        seen_models.append(model)
        return 3, True, "fake"

    monkeypatch.setattr(token_count, "countModelTokens", fakeCount)

    from neurova.agent.chat_pipeline import ChatPipeline

    class _Pipeline:
        def _current_model_name(self):
            return "gpt-runtime"

    class _Context:
        metadata = {}
        relevant_memories = [
            {"knowledge_id": "k-1", "lineage_id": "fact-1", "content": "证据正文", "score": 0.8},
            {"knowledge_id": "k-2", "content": "文档命中没有 fact 可摊", "score": 0.4},
            {"memory_id": "m-1", "content": "普通记忆不进知识成本", "score": 0.9},
        ]

    context = _Context()
    ChatPipeline._recordKnowledgeCostInputs(_Pipeline(), context)

    assert seen_models == ["gpt-runtime", "gpt-runtime"]
    assert context.metadata["knowledge_retrieval_tokens"] == {"fact-1": 3}
    assert context.metadata["knowledge_retrieval_tokens_total"] == 6
    assert context.metadata["knowledge_retrieval_tokens_estimated"] is False
    assert context.metadata["knowledge_retrieval_tokens_model"] == "gpt-runtime"
