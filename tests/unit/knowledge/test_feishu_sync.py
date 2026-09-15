"""P1#9/P1#10 飞书空间同步测试。

契约（§7 #9/#10）：
- FeishuKBAdapter.list_space_nodes：wiki 节点分页枚举（page_token 循环）；
  某页失败 → 已列出的部分保留且 partial=True（残缺清单不得喂删除检测）。
- FeishuKBAdapter.fetch_doc_content：docx raw_content 取正文（修"只回标题"硬伤）。
- datasource_sync.run_feishu_sync：
  - 游标 = 完整快照 {obj_token: edit_sig}，写回 config settings._sync；
  - 变更判定 sig≠cursor → 拉正文落库（knowledge_id=feishu_<token> 稳定映射）；
 - 拉取失败不推进游标（保留旧 sig
    advance the cursor"）；
  - 删除检测仅在非 partial 时启用（远端消失 → 本地条目墓碑化）；
  - 同 config 并发互斥（第二次同步 SyncBusyError，对齐 HasRunningSync）。
"""

import threading

import pytest

from neurova.knowledge import datasource_sync
from neurova.knowledge.adapters import FeishuKBAdapter
from neurova.knowledge.datasource_sync import SyncBusyError, run_feishu_sync
from neurova.knowledge.repository import KnowledgeRepository


class FakeStorage:
    def __init__(self):
        self.cfgs = {}

    def add(self, cid, settings=None):
        self.cfgs[cid] = {"id": cid, "settings": dict(settings or {})}

    def get_config_by_id(self, cid):
        return self.cfgs.get(cid)

    def update_config(self, cid, **fields):
        if cid not in self.cfgs:
            return False
        self.cfgs[cid].update(fields)
        return True


def _adapter(script):
    """script: [(path_snippet, responses队列)] 的脚本化 raw_call。"""
    queues = {k: list(v) for k, v in script.items()}

    def call(method, path, token=None, json_body=None, timeout=30.0):
        for key, q in queues.items():
            if key in path:
                if not q:
                    raise RuntimeError("script exhausted: " + path)
                item = q.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError("unscripted path: " + path)

    a = FeishuKBAdapter(
        {"app_id": "a", "app_secret": "s", "space_id": "sp1"},
        raw_call=call, validate_url=lambda u: True,
    )
    return a


TOKEN = (200, {"tenant_access_token": "t", "expire": 7200})


def _script(nodes_pages=None, docs=None, fail_after_pages=None):
    script = {"/auth/v3/tenant_access_token": [TOKEN]}
    pages = list(nodes_pages or [])
    if fail_after_pages is not None:
        # 前 N 页成功，随后页抛错 → partial
        kept, pages_tail = pages[:fail_after_pages], pages[fail_after_pages:]
        script["/wiki/v2/spaces/sp1/nodes"] = kept + [RuntimeError("网络抖动")] * len(pages_tail)
    else:
        script["/wiki/v2/spaces/sp1/nodes"] = pages
    for tok, resp in (docs or {}).items():
        script[f"/docx/v1/documents/{tok}/raw_content"] = [resp]
    return script


def _nodes(items, has_more=False, page_token=None):
    body = {"data": {"items": items, "has_more": has_more}}
    if page_token:
        body["data"]["page_token"] = page_token
    return (200, body)


DOC1 = {"node_token": "n1", "obj_token": "D1", "obj_type": "docx", "title": "手册一", "obj_edit_time": "111"}
DOC2 = {"node_token": "n2", "obj_token": "D2", "obj_type": "docx", "title": "手册二", "obj_edit_time": "222"}
SUBTREE = {"node_token": "n3", "obj_token": "X3", "obj_type": "sheet", "title": "表格", "obj_edit_time": "333"}


@pytest.fixture
def env(tmp_path):
    repo = KnowledgeRepository(str(tmp_path))
    storage = FakeStorage()
    storage.add("kbc1", {"space_id": "sp1"})
    return repo, storage


class TestAdapterMethods:
    def test_list_nodes_paginates(self):
        a = _adapter(_script([_nodes([DOC1], True, "p2"), _nodes([DOC2], False)]))
        import asyncio

        out = asyncio.run(a.list_space_nodes("sp1"))
        assert not out["partial"]
        assert [n["id"] for n in out["nodes"]] == ["D1", "D2"]

    def test_partial_on_mid_traversal_failure(self):
        a = _adapter(_script(
            [_nodes([DOC1], True, "p2"), _nodes([DOC2], False)],
            fail_after_pages=1,
        ))
        import asyncio

        out = asyncio.run(a.list_space_nodes("sp1"))
        assert out["partial"] is True
        assert len(out["nodes"]) == 1

    def test_fetch_doc_content(self):
        a = _adapter(_script(docs={"D1": (200, {"data": {"content": "正文一"}})}))
        import asyncio

        assert asyncio.run(a.fetch_doc_content("D1")) == "正文一"


class TestFeishuSync:
    def _sync(self, adapter, repo, storage):
        import asyncio

        return asyncio.run(
            run_feishu_sync(adapter, repo, storage, config_id="kbc1", user_id="1", agent_id="default")
        )

    def test_first_sync_lands_body_not_titles(self, env):
        repo, storage = env
        a = _adapter(_script(
            [_nodes([DOC1, DOC2], False)],
            docs={"D1": (200, {"data": {"content": "正文一"}}),
                  "D2": (200, {"data": {"content": "正文二"}})},
        ))
        stats = self._sync(a, repo, storage)
        assert stats["upserted"] == 2 and stats["failed"] == 0
        item = repo.find_item("feishu_D1")[1]
        assert item["content"] == "正文一"
        assert item["title"] == "手册一" and item["source"] == "feishu"
        # 游标已持久化到 config settings
        assert storage.cfgs["kbc1"]["settings"]["_sync"]["cursor"] == {"D1": "111", "D2": "222"}

    def test_unchanged_skipped_changed_refetched(self, env):
        repo, storage = env
        a1 = _adapter(_script(
            [_nodes([DOC1, DOC2], False)],
            docs={"D1": (200, {"data": {"content": "正文一"}}),
                  "D2": (200, {"data": {"content": "正文二"}})},
        ))
        self._sync(a1, repo, storage)
        doc2_edit = dict(DOC2, obj_edit_time="999")
        a2 = _adapter(_script(
            [_nodes([DOC1, doc2_edit], False)],
            docs={"D2": (200, {"data": {"content": "正文二改版"}})},
        ))
        stats = self._sync(a2, repo, storage)
        assert stats["skipped"] == 1 and stats["upserted"] == 1
        assert repo.find_item("feishu_D2")[1]["content"] == "正文二改版"

    def test_failure_does_not_advance_cursor(self, env):
        repo, storage = env
        a1 = _adapter(_script(
            [_nodes([DOC1], False)],
            docs={"D1": (200, {"data": {"content": "正文一"}})},
        ))
        self._sync(a1, repo, storage)
        # D1 远端改版但拉取失败 → 游标保持旧 sig、本地保持旧文；下轮仍会重试
        edited = dict(DOC1, obj_edit_time="777")
        a2 = _adapter(_script([_nodes([edited], False)], docs={"D1": [RuntimeError("503")]}))
        stats = self._sync(a2, repo, storage)
        assert stats["failed"] == 1
        assert storage.cfgs["kbc1"]["settings"]["_sync"]["cursor"]["D1"] == "111"
        assert repo.find_item("feishu_D1")[1]["content"] == "正文一"
        a3 = _adapter(_script([_nodes([edited], False)], docs={"D1": (200, {"data": {"content": "正文一改版"}})}))
        stats3 = self._sync(a3, repo, storage)
        assert stats3["upserted"] == 1
        assert repo.find_item("feishu_D1")[1]["content"] == "正文一改版"

    def test_partial_suppresses_deletion_sync(self, env):
        repo, storage = env
        a1 = _adapter(_script(
            [_nodes([DOC1], False)],
            docs={"D1": (200, {"data": {"content": "正文一"}})},
        ))
        self._sync(a1, repo, storage)
        # 本轮清单残缺（一页都没列全且不含 D1）→ D1 不得被删
        a2 = _adapter(
            _script([_nodes([DOC2], True, "p2"), _nodes([DOC2], False)], fail_after_pages=1,
                    docs={"D2": (200, {"data": {"content": "正文二"}})}),
        )
        stats = self._sync(a2, repo, storage)
        assert stats["partial"] is True and stats["deleted"] == 0
        assert repo.find_item("feishu_D1") is not None

    def test_full_relisting_tombstones_vanished_doc(self, env):
        repo, storage = env
        a1 = _adapter(_script(
            [_nodes([DOC1, DOC2], False)],
            docs={"D1": (200, {"data": {"content": "正文一"}}),
                  "D2": (200, {"data": {"content": "正文二"}})},
        ))
        self._sync(a1, repo, storage)
        a2 = _adapter(_script([_nodes([DOC1], False)]))  # 全量清单只剩 D1，D2 已消失
        stats = self._sync(a2, repo, storage)
        assert stats["deleted"] == 1
        assert repo.find_item("feishu_D2") is None
        assert storage.cfgs["kbc1"]["settings"]["_sync"]["cursor"].get("D2") is None

    def test_non_doc_types_skipped(self, env):
        repo, storage = env
        a = _adapter(_script([_nodes([DOC1, SUBTREE], False)],
                             docs={"D1": (200, {"data": {"content": "正文一"}})}))
        stats = self._sync(a, repo, storage)
        assert stats["upserted"] == 1 and stats["skipped_type"] == 1
        assert repo.find_item("feishu_X3") is None

    def test_concurrent_sync_busy(self, env):
        repo, storage = env
        a = _adapter(_script([_nodes([DOC1], False)],
                             docs={"D1": (200, {"data": {"content": "正文一"}})}))
        lk = threading.Lock()
        assert lk.acquire()
        datasource_sync._ACTIVE_LOCKS["kbc1"] = lk  # 模拟另一路同步在跑
        try:
            with pytest.raises(SyncBusyError):
                self._sync(a, repo, storage)
        finally:
            lk.release()
            datasource_sync._ACTIVE_LOCKS.pop("kbc1", None)


class TestSyncSchedulerDue:
    """③ 后端定时循环：到期判定纯函数 + 循环单测（无网络）。"""

    def test_due_filter(self):
        from neurova.knowledge.datasource_sync import compute_due_configs

        now = 1_000_000.0
        configs = [
            # 到期：有间隔且从未同步
            {"id": "c1", "source_type": "feishu", "is_active": True,
             "settings": {"sync_interval_minutes": 30}},
            # 未到期间隔
            {"id": "c2", "source_type": "feishu", "is_active": True,
             "settings": {"sync_interval_minutes": 30, "_sync": {"last_sync_ts": now - 60}}},
            # 到期（超间隔）
            {"id": "c3", "source_type": "feishu", "is_active": True,
             "settings": {"sync_interval_minutes": 1, "_sync": {"last_sync_ts": now - 3600}}},
            # 未启用定时（间隔 0/缺失）
            {"id": "c4", "source_type": "feishu", "is_active": True, "settings": {}},
            # 非飞书/未激活
            {"id": "c5", "source_type": "iflow", "is_active": True,
             "settings": {"sync_interval_minutes": 30}},
            {"id": "c6", "source_type": "feishu", "is_active": False,
             "settings": {"sync_interval_minutes": 30}},
        ]
        due = [c["id"] for c in compute_due_configs(configs, now)]
        assert due == ["c1", "c3"]

    def test_loop_runs_due_sync_with_injected_factory(self, monkeypatch):
        import asyncio
        import types

        from neurova.knowledge import datasource_sync as ds

        calls = []

        class FakeStorage:
            def get_all_configs(self):
                return [
                    {"id": "c1", "user_id": "u1", "source_type": "feishu", "is_active": True,
                     "settings": {"sync_interval_minutes": 1, "space_id": "sp1"}},
                ]
            def get_config_by_id(self, cid):
                return {"id": cid, "settings": {}}
            def update_config(self, cid, **f):
                return True

        def fake_run(adapter, repo, storage, *, config_id, user_id, agent_id="default"):
            calls.append((config_id, user_id))

            async def _stats():
                return {"upserted": 0, "partial": False}
            return _stats()

        monkeypatch.setattr(ds, "run_feishu_sync", fake_run)
        monkeypatch.setattr(ds, "get_knowledge_storage", lambda: FakeStorage())
        monkeypatch.setattr(ds, "_default_repo", lambda: object())
        # 单次扫描函数（循环内核）可测
        stats = asyncio.run(ds.tick_feishu_sync(now=1_000_000.0))
        assert calls == [("c1", "u1")] and len(stats) == 1


class TestStorageListAll:
    def test_get_all_configs(self, tmp_path):
        from neurova.knowledge.storage import KnowledgeStorage

        st = KnowledgeStorage(str(tmp_path))
        st.create_config(user_id="u1", name="a", source_type="feishu", is_active=True)
        st.create_config(user_id="u2", name="b", source_type="iflow", is_active=False)
        alls = st.get_all_configs()
        assert {c["user_id"] for c in alls} == {"u1", "u2"}
