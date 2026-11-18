# -*- coding: utf-8 -*-
"""outcome 契约词三元组的单源收口（fullrepo 审计 2026-11-18 G6）。

skills.models 是三态词汇的唯一定义处（OUTCOME_MARKS/STATES 已在此）；
knowledge_core 的 OpenAPI Literal 此前手抄同一三元组——收口为引用单源
别名，防止契约词在第二处漂移。
"""
import inspect

from neurova.skills.models import OUTCOME_WORDS, OutcomeLiteral


def test_outcome_words_single_source():
    assert OUTCOME_WORDS == frozenset({"success", "failure", "unevidenced"})


def test_knowledge_core_uses_the_alias_not_a_hand_copy():
    from neurova.api.endpoints import knowledge_core

    src = inspect.getsource(knowledge_core)
    assert "OutcomeLiteral" in src, "FactAdoptionRequest.outcome 未引用单源别名"
    assert 'Literal["success", "failure", "unevidenced"]' not in src, (
        "knowledge_core 仍手抄契约词三元组"
    )
