"""上下文 token 计数：模型 tokenizer 优先，缺席回退 jieba/ngram 估计。"""
from __future__ import annotations

from typing import Tuple


def countModelTokens(text: str, model: str = "") -> Tuple[int, bool, str]:
    """返回 (count, exact, source)。

    exact=True 只表示“用了该模型的官方编码器”；非 OpenAI 模型回退 cl100k
    仍标 exact=False，避免把估计冒充真实成本。
    """
    value = str(text or "")
    try:
        import tiktoken

        exact = False
        if model:
            try:
                encoder = tiktoken.encoding_for_model(model)
                exact = True
            except Exception:  # noqa: BLE001 - 非 OpenAI 模型回退通用编码
                encoder = tiktoken.get_encoding("cl100k_base")
        else:
            encoder = tiktoken.get_encoding("cl100k_base")
        return len(encoder.encode(value)), exact, "tiktoken"
    except Exception:  # noqa: BLE001 - tiktoken/编码资产缺席时回退
        from neurova.knowledge.search import tokenize

        return len(tokenize(value)), False, "jieba/ngram"
