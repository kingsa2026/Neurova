"""知识索引周期维护任务的启停闭环。"""
from fastapi.testclient import TestClient

import neurova.api.app as app_mod


def test_startupStoresAndShutdownCancelsKnowledgeIndexTask(monkeypatch):
    """启停必须成对：startup 留下句柄，关停把它取消并等待收敛。"""
    monkeypatch.delenv("NEUROVA_KB_INDEX_MAINTENANCE", raising=False)
    app = app_mod.create_app()

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        task = app_mod._app_state.kb_index_task
        assert task is not None, "周期维护任务句柄未保存，关停时无从收敛"
        assert not task.done()

    assert task.done(), "关停后周期维护任务仍在跑"
    assert task.cancelled(), "关停必须取消周期维护任务，而不是任其常驻"
    assert app_mod._app_state.kb_index_task is None
