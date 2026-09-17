"""knowledge_integration 诚实性回归。

原缺陷：/gaps/analyze 与 /learn 两个 501 端点 raise HTTPException 但模块未
import 该类 → 被调用时 NameError 崩成 500，把"未实现"伪装成"内部错误"。
修复为补 import；本测试钉死"未实现必须如实 501"。

登记（统一收口待拍板， §9）：
- /rag/retrieve、/rag/batch 恒空 items——真实 RAG 路径是 chat MemoryRetrievalChain，
  本端点群属设计稿未接线；
- /sync/* 进程内 _sync_links 不落盘不可消费（storage.memory_links.json 才是正源）。
"""

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import knowledge_integration as ki


@pytest.mark.asyncio
async def test_gaps_analyze_honest_501_not_nameerror():
    with pytest.raises(HTTPException) as ei:
        await ki.analyze_knowledge_gaps(ki.AnalyzeGapsRequest(topic="某主题"), None)
    assert ei.value.status_code == 501
    assert "未实现" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_learn_honest_501_not_nameerror():
    with pytest.raises(HTTPException) as ei:
        await ki.learn_from_knowledge(ki.LearnRequest(topic="某主题"), None)
    assert ei.value.status_code == 501
    assert "未实现" in str(ei.value.detail)


# ── sync 端点薄层冒烟（业务在 test_feishu_sync 已全链覆盖）──────────────


def test_sync_kb_config_endpoint_guards(monkeypatch):
    """非属主/非飞书源 → 404/400；不触网。"""
    import asyncio
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from neurova.api.endpoints import knowledge as kmod
    from neurova.api.endpoints import knowledge_remote as kb_remote

    storage = MagicMock()
    storage.get_config_by_id.return_value = {
        "id": "kbc1", "user_id": "u9", "source_type": "custom", "settings": {},
    }
    # 拆分后真身在 knowledge_remote（2026-09-16 模块化），patch 聚合器无效
    monkeypatch.setattr(kb_remote, "_get_kb_storage", lambda: storage)
    req = MagicMock()
    req.query_params = {}
    try:
        asyncio.run(kmod.sync_kb_config(req, "kbc1", current_user={"user_id": "1", "role": "user"}))
        raise AssertionError("应 404（非属主不泄露存在性）")
    except HTTPException as exc:
        assert exc.status_code == 404

    storage.get_config_by_id.return_value = {
        "id": "kbc1", "user_id": "1", "source_type": "custom", "settings": {},
    }
    try:
        asyncio.run(kmod.sync_kb_config(req, "kbc1", current_user={"user_id": "1", "role": "user"}))
        raise AssertionError("应 400（非飞书不支持同步）")
    except HTTPException as exc:
        assert exc.status_code == 400
