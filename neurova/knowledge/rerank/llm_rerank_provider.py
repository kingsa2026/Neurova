"""LLM 打分精排 provider（注入式调用器，不在导入期绑死任何客户端）。

调用方提供 `llmCall(prompt) -> str`（可包一层超时/降级），本模块只负责
prompt、JSON 契约与失败分类；输出长度/索引不符一律 RerankBackendError。
"""
from __future__ import annotations

import json
from typing import Callable, List

_PROMPT = """你是检索重排器。按与查询的相关性给候选打分（0-1）。
只输出 JSON：{{"scores":[{{"index":0,"score":0.9}}, ...]}}，必须覆盖全部候选。

查询：{query}
候选：
{docs}
"""


def buildLlmRerankProvider(
    llmCall: Callable[[str], str]
) -> Callable[[str, List[str]], List[float]]:
    from neurova.llm.rerank_client import RerankBackendError, RerankConfigError

    if not callable(llmCall):
        raise RerankConfigError("LLM 精排缺少可调用的 llmCall", reason="llm_call_missing")

    def provider(query: str, docTexts: List[str]) -> List[float]:
        docs = "\n".join(
            "%d. %s" % (index, str(text or "")[:500])
            for index, text in enumerate(docTexts)
        )
        try:
            raw = llmCall(_PROMPT.format(query=query, docs=docs))
        except Exception as exc:  # noqa: BLE001 - 调用面故障如实分类
            raise RerankBackendError("LLM 精排调用失败: %s" % exc, kind="network") from exc
        try:
            payload = json.loads(str(raw or ""))
            items = payload.get("scores")
        except (ValueError, AttributeError) as exc:
            raise RerankBackendError("LLM 精排输出不是合法 JSON 契约", kind="contract") from exc
        if not isinstance(items, list):
            raise RerankBackendError("LLM 精排 scores 字段缺失或非列表", kind="contract")
        scores: List[float] = [None] * len(docTexts)
        for item in items:
            try:
                index = int((item or {}).get("index"))
                score = float((item or {}).get("score"))
            except (TypeError, ValueError) as exc:
                raise RerankBackendError("LLM 精排 index/score 非法", kind="contract") from exc
            if not 0 <= index < len(docTexts) or scores[index] is not None:
                raise RerankBackendError("LLM 精排 index 越界或重复", kind="contract")
            scores[index] = score
        if any(score is None for score in scores):
            raise RerankBackendError(
                "LLM 精排返回 %d 个分数 vs %d 个候选"
                % (sum(1 for score in scores if score is not None), len(docTexts)),
                kind="contract",
            )
        return [float(score) for score in scores]

    return provider
