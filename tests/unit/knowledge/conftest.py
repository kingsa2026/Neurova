# -*- coding: utf-8 -*-
"""knowledge 目录的注册表隔离：进入 app lifespan 的用例必须把进程全局要回来（§6-118）。

缺陷形态不是本目录的用例算错，而是**它把一条全局留在了身后**：`api/app.py` 的
startup 经 `set_app_state` 把运行时对象（含 `agents`）写进
`neurova.api.endpoints._app_state`，关停路径不回收——生产进程随即退出，无所谓；
测试会话里同一进程要跑几百条用例，这条全局就一直留着。

本目录为证明"启动钩子真的跑了"有两条用例进入 lifespan
（`with TestClient(create_app())`），于是下游那些**自建 FastAPI app** 的用例在
`knowledge_ingestion._resolve_runtime_agents` 处命中的是注册表分支，而不是它
假定的"没有运行时 agent"分支。实测代价三格红（复算过程见 §6-118）：

- `test_ingest_endpoint::test_import_sync_default_unchanged`——导入路由因此去取
  `get_knowledge_repository()`，撞上 pytest 存储围栏 ⇒ 500；
- `test_rerank_refine_weknora::TestAPIWiring::{test_default_off_preserves_contract,
  test_top_k_applied}`——检索改走真 agent 那条空数据面 ⇒ `results` 为空。

复原（而不是无条件置 None）：用例若自己铺了注册表，不该被别人的夹具抹掉。
判据在 `test_appStateIsolation.py`，本夹具一旦被删它就红。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restoreEndpointsAppState():
    """每条用例进出各一次快照/复原 endpoints 的运行时注册表。"""
    from neurova.api import endpoints as ep

    before = ep.get_app_state()
    try:
        yield
    finally:
        ep.set_app_state(before)
