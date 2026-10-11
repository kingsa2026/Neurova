# -*- coding: utf-8 -*-
"""§6-158（工单 2026-10-12 批 13，裁定乙）：媒体面补齐「软删 ＋ 回收站」，默认语义一律不变。

## 这批为什么存在

退役的 `neurova/media/manager.py` 里有、REST 端点里没有的另一半就是软删与回收站
（sha256 校验位那半已按 §6-140 并入）。裁定乙：四件并进来——`?mode=trash` 软删、
`GET /trash` 读面、`POST /{id}/restore`、`?mode=permanent` 彻底删除——**默认仍是硬删**，
因为现役页面（`AgentMediaPage`）的「删了就没了」是对用户的既有承诺，
把它静默翻成"其实还在盘上、谁都捞得回来"属于隐私语义变更，不在本批的授权范围。

保留策略（同日人裁）：**回收站永久保留，直到用户显式彻底删除**——不设 TTL、不做自动过期。
媒体是用户内容，自动删＝替用户决定；这与渠道观察面那套 90 天窗口不是同一件事。

## 判据的靶

1. 默认删除、坏 mode、批量面、读面排除、恢复、彻底删除、重启复原，各自都要落在**真 HTTP 往返**
   与**真落盘**上（`_save_index()`/`_load_index()` 走真路径，否则"重启后回收站还在"就是内存字典自证）。
2. 现役读面一处都不能漏：`/list`、`/stats/{agent}`、`/memory/{id}` 三个列表口径，
   加 `GET /{media_id}`、`GET /download/{media_id}`、`GET /{media_id}/metadata` 三个取物口径
   ——只排前面三个，回收站条目照样能被人按 id 把字节捞走（本仓反复点名的"漏最后那一处排除"）。
3. 每格都带一枚反向对照：装载期"盘上文件已不在即剔行"这条既有巡检**不能被整个关掉**来给回收站让路。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user as authUser
from neurova.api.endpoints import media as media_module

AGENT = "a1"
# 媒体面按 `agent_id` 分账，不按登录用户（`router = APIRouter(dependencies=[Depends(get_current_user)])`
# 只证明"是谁在问"，不参与过滤）——回收站沿用同一口径，本批不动鉴权语义。
CALLER = {"user_id": "1", "username": "tester", "role": "user"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """真落盘、真索引：存储根与索引文件都指到 tmp，跑完即弃。"""
    root = tmp_path / "media_storage"
    root.mkdir()
    store: dict = {}
    monkeypatch.setattr(media_module, "_INDEX_FILE", str(tmp_path / "media_index.json"))
    monkeypatch.setattr(media_module, "_CONFIG_FILE", str(tmp_path / "media_config.json"))
    monkeypatch.setattr(media_module, "_media_store", store)
    monkeypatch.setitem(media_module._media_config, "storage_path", str(root))
    monkeypatch.setitem(media_module._media_config, "max_file_size", 10 * 1024 * 1024)

    app = FastAPI()
    app.include_router(media_module.router, prefix="/api/v1/media")
    app.dependency_overrides[authUser] = lambda: dict(CALLER)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.store = store
        yield test_client


def _upload(client, name="clip.png", content=b"\x89PNG-bytes", media_type="image",
            agent_id=AGENT, memory_id=None):
    data = {"media_type": media_type, "agent_id": agent_id}
    if memory_id is not None:
        data["memory_id"] = memory_id
    resp = client.post("/api/v1/media/save",
                       files={"file": (name, content, "image/png")}, data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _diskOf(client, media_id):
    return Path(client.store[media_id]["storage_path"])


class TestDefaultDeleteSemanticsDoNotSilentlyFlip:
    def test_deleteWithoutModeStillRemovesBytes(self, client):
        saved = _upload(client, content=b"to-be-gone")
        disk = _diskOf(client, saved["media_id"])
        assert disk.is_file()

        resp = client.delete(f"/api/v1/media/{saved['media_id']}")

        assert resp.status_code == 200, resp.text
        assert not disk.exists(), (
            "默认删除被改成软删——现役页面的「删了就没了」承诺被静默翻转，"
            "字节仍在盘上且谁都捞得回来，这是隐私语义变更，不在本批授权内")
        assert saved["media_id"] not in client.store

    def test_unrecognisedModeIsRejectedAndLeavesNoTrace(self, client):
        """坏 mode 不得被兜底成任何一种删除：拒就是拒，且不留半成品状态。"""
        saved = _upload(client, content=b"untouched")
        disk = _diskOf(client, saved["media_id"])

        resp = client.delete(f"/api/v1/media/{saved['media_id']}?mode=soft")

        assert resp.status_code == 400, resp.text
        assert disk.is_file(), "被拒的请求却动了盘"
        assert not client.store[saved["media_id"]].get("is_deleted"), "被拒的请求却落了软删标记"


class TestTrashWriteAndActiveReadSurfaces:
    def test_softDeleteRequiresExplicitModeAndKeepsBytes(self, client):
        saved = _upload(client, content=b"keep-for-a-while")

        resp = client.delete(f"/api/v1/media/{saved['media_id']}?mode=trash")

        assert resp.status_code == 200, resp.text
        rec = client.store[saved["media_id"]]
        assert rec.get("is_deleted") is True, f"显式回收站没落软删标记：{rec!r}"
        assert Path(rec["storage_path"]).is_file(), (
            "回收站却把盘上内容删了——那与直接删除无异，恢复也无从谈起")
        assert rec.get("deleted_at"), f"回收站行没带删除时间：{rec!r}"

    def test_trashedRowLeavesEveryListingSurface(self, client):
        saved = _upload(client, content=b"trashed", memory_id="mem-1")
        client.delete(f"/api/v1/media/{saved['media_id']}?mode=trash")

        listed = client.get("/api/v1/media/list", params={"agent_id": AGENT}).json()["data"]
        stats = client.get(f"/api/v1/media/stats/{AGENT}").json()["data"]
        memory = client.get("/api/v1/media/memory/mem-1").json()["data"]

        assert [m["media_id"] for m in listed["media"]] == [], f"list 还在出回收站条目：{listed!r}"
        assert stats["total_files"] == 0, f"stats 把回收站算进活文件数：{stats!r}"
        assert stats["total_size"] == 0, f"stats 的容量口径含回收站：{stats!r}"
        assert memory["total"] == 0, f"memory 关联面把回收站算进来：{memory!r}"

    def test_trashedRowIsUnreachableThroughEveryContentSurface(self, client):
        """三个取物口径一处都不能漏——只排列表面，条目照样能按 id 被捞走。"""
        saved = _upload(client, content=b"trashed-bytes")
        mid = saved["media_id"]
        client.delete(f"/api/v1/media/{mid}?mode=trash")

        for path in (f"/api/v1/media/{mid}", f"/api/v1/media/download/{mid}",
                     f"/api/v1/media/{mid}/metadata"):
            resp = client.get(path)
            assert resp.status_code == 404, f"{path} 仍可达（漏一处排除）：{resp.status_code}"

    def test_trashListReadsBackWhatWasSoftDeletedForTheSameAgent(self, client):
        """读面闭环：回收站必须**有人能读**，否则又是一处「只写不读」的断点。"""
        mine = _upload(client, name="mine.png", content=b"undo-able")
        theirs = _upload(client, name="theirs.png", content=b"other-agent", agent_id="a2")
        client.delete(f"/api/v1/media/{mine['media_id']}?mode=trash")
        client.delete(f"/api/v1/media/{theirs['media_id']}?mode=trash")

        body = client.get("/api/v1/media/trash", params={"agent_id": AGENT}).json()["data"]

        assert [m["media_id"] for m in body["media"]] == [mine["media_id"]], body
        assert body["total"] == 1, body
        assert body["media"][0].get("deleted_at"), f"回收站行没带删除时间：{body!r}"


class TestRestoreAndPermanentFollowUp:
    def testRestoreBringsTheSameBytesBack(self, client):
        content = b"restore-me"
        saved = _upload(client, content=content)
        mid = saved["media_id"]
        client.delete(f"/api/v1/media/{mid}?mode=trash")

        resp = client.post(f"/api/v1/media/{mid}/restore")

        assert resp.status_code == 200, resp.text
        assert client.store[mid].get("is_deleted") is False, f"恢复没清软删标记：{client.store[mid]!r}"
        listed = client.get("/api/v1/media/list", params={"agent_id": AGENT}).json()["data"]
        assert [m["media_id"] for m in listed["media"]] == [mid], listed
        assert client.get(f"/api/v1/media/{mid}").content == content, "恢复后取回的字节不是原物"

    def testRestoreOfUnknownIdIsFourOhFour(self, client):
        """反向对照：没这条就报没这条，不许把"恢复失败"折成成功。"""
        resp = client.post("/api/v1/media/media-does-not-exist/restore")

        assert resp.status_code == 404, resp.text

    def testRestoreOfAnActiveRowIsRejectedNotIdempotentSilent(self, client):
        """对活条目「恢复」是问错了对象：诚实拒绝，别把它做成一次静默 no-op 200。"""
        saved = _upload(client, content=b"never-trashed")

        resp = client.post(f"/api/v1/media/{saved['media_id']}/restore")

        assert resp.status_code == 409, resp.text
        assert saved["media_id"] in client.store and not client.store[saved["media_id"]].get(
            "is_deleted"), "被拒的请求改动了活条目"

    def testRestoreDoesNotResurrectMissingBytes(self, client):
        """盘上字节已被外部删掉的回收站行：恢复必须点名，不许造一条"活但取不到"的记录。"""
        saved = _upload(client, content=b"evaporated")
        mid = saved["media_id"]
        client.delete(f"/api/v1/media/{mid}?mode=trash")
        _diskOf(client, mid).unlink()

        resp = client.post(f"/api/v1/media/{mid}/restore")

        assert resp.status_code == 410, resp.text
        assert client.store[mid].get("is_deleted") is True, "恢复失败却把行转成活条目"

    def testPermanentDeleteFromTrashRemovesBytesAndRow(self, client):
        saved = _upload(client, content=b"finally-gone")
        mid = saved["media_id"]
        client.delete(f"/api/v1/media/{mid}?mode=trash")
        disk = _diskOf(client, mid)

        resp = client.delete(f"/api/v1/media/{mid}?mode=permanent")

        assert resp.status_code == 200, resp.text
        assert not disk.exists(), "彻底删除只摘了元数据，字节留在盘上"
        assert mid not in client.store

    def testBatchDeleteHonoursTheSameTwoModes(self, client):
        a = _upload(client, name="a.png", content=b"aaa")
        b = _upload(client, name="b.png", content=b"bbb")

        trashed = client.post("/api/v1/media/batch-delete",
                              json={"media_ids": [a["media_id"]], "mode": "trash"}).json()
        gone = client.post("/api/v1/media/batch-delete",
                           json={"media_ids": [b["media_id"]], "mode": "permanent"}).json()

        assert trashed["data"]["succeeded"] == [a["media_id"]], trashed
        assert client.store[a["media_id"]]["is_deleted"] is True
        assert _diskOf(client, a["media_id"]).is_file()
        assert gone["data"]["succeeded"] == [b["media_id"]], gone
        assert b["media_id"] not in client.store

    def testBatchDeleteWithoutModeKeepsHardDelete(self, client):
        """批量面的默认档同样不许翻：不带 mode 就是真删。"""
        saved = _upload(client, name="c.png", content=b"ccc")
        disk = _diskOf(client, saved["media_id"])

        client.post("/api/v1/media/batch-delete", json={"media_ids": [saved["media_id"]]})

        assert not disk.exists() and saved["media_id"] not in client.store

    def testUnknownIdIsStillReportedPerItemNotSwallowed(self, client):
        resp = client.post("/api/v1/media/batch-delete",
                           json={"media_ids": ["media-nope"], "mode": "trash"})

        assert resp.json()["data"]["failed"] == [
            {"media_id": "media-nope", "reason": "media not found"}], resp.text


class TestTrashSurvivesRestart:
    def _reloadInto(self, client):
        """用真 `_load_index()` 把索引读进一份**全新** store——模拟进程重启。"""
        fresh: dict = {}
        previous = media_module._media_store
        media_module._media_store = fresh
        try:
            media_module._load_index()
        finally:
            media_module._media_store = previous
        return fresh

    def test_softDeletedRowIsPersistedAndReloadedAsTrashed(self, client):
        saved = _upload(client, content=b"persist-me")
        client.delete(f"/api/v1/media/{saved['media_id']}?mode=trash")

        onDisk = json.loads(
            Path(media_module._INDEX_FILE).read_text(encoding="utf-8"))
        reloaded = self._reloadInto(client)

        assert reloaded[saved["media_id"]]["is_deleted"] is True, (
            "重启即复活成「活文件」——索引里没落软删标记："
            f"落盘行 {onDisk['media'][saved['media_id']]!r}／复原行 {reloaded[saved['media_id']]!r}")
        assert reloaded[saved["media_id"]].get("checksum") == saved["checksum"]

    def test_loadStillDropsRowsWhoseBytesAreGone(self, client):
        """反向对照：装载期"盘上文件已不在即剔行"这条既有巡检不能被关掉来给回收站让路。"""
        saved = _upload(client, content=b"orphan-bytes")
        _diskOf(client, saved["media_id"]).unlink()

        reloaded = self._reloadInto(client)

        assert saved["media_id"] not in reloaded, (
            "孤儿行被留进内存——「巡检为回收站让路」就是把外删文件当成仍在，"
            "读面从此指向不存在的字节")


class TestStorageRootIsNeverCwdRelative:
    """上传是回收站四件的前门——门自己坏了，后面四件在活 app 上一步都走不到（实测过）。

    模块默认值是 `"storage_path": "media_storage"`（裸相对名），而 `_storage_root()` 的注释
    写的是"未配置时落数据根下的 `media_storage/`"。默认值本身就是"已配置成一个相对名"，
    那句兜底从来进不去：于是 `is_relative_to(_storage_root())` 拿绝对路径比相对路径，
    **每一次** `POST /save` 都回 400「非法的存储路径」。修法落在根上（这一处解析），
    不在端点里加"看起来相对就当数据根"的兜底判断。
    """

    @pytest.fixture()
    def defaultConfigClient(self, tmp_path, monkeypatch):
        """只改数据根，**不动** `storage_path`——审的就是默认值那条路。"""
        dataRoot = tmp_path / "dataRoot"
        dataRoot.mkdir()
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(dataRoot))
        store: dict = {}
        monkeypatch.setattr(media_module, "_INDEX_FILE", str(dataRoot / "media_index.json"))
        monkeypatch.setattr(media_module, "_CONFIG_FILE", str(dataRoot / "media_config.json"))
        monkeypatch.setattr(media_module, "_media_store", store)
        monkeypatch.setattr(media_module, "_media_config",
                            dict(media_module._media_config))  # 默认值原样，只是不污染全局

        app = FastAPI()
        app.include_router(media_module.router, prefix="/api/v1/media")
        app.dependency_overrides[authUser] = lambda: dict(CALLER)
        with TestClient(app, raise_server_exceptions=False) as test_client:
            test_client.dataRoot = dataRoot
            yield test_client

    def test_defaultStorageRootIsAbsoluteAndAnchoredOnTheDataRoot(self, defaultConfigClient, tmp_path):
        root = media_module._storage_root()
        assert root.is_absolute(), f"存储根是 CWD 相对路径 {root}——落点随启动目录漂移"
        assert str(root).startswith(str(tmp_path / "dataRoot")), (
            f"相对配置没有锚到数据根，而是留给 CWD：{root}")

    def test_uploadSucceedsWithTheDefaultConfig(self, defaultConfigClient):
        saved = _upload(defaultConfigClient, content=b"front-door")
        disk = Path(saved["storage_path"])

        assert disk.is_file(), "上传返回成功却没落盘"
        assert str(disk).startswith(str(defaultConfigClient.dataRoot)), (
            f"内容写在数据根之外：{disk}")

    def test_absoluteConfiguredRootIsStillHonoured(self, defaultConfigClient, tmp_path, monkeypatch):
        elsewhere = tmp_path / "explicitRoot"
        elsewhere.mkdir()
        monkeypatch.setitem(media_module._media_config, "storage_path", str(elsewhere))

        saved = _upload(defaultConfigClient, content=b"explicit", name="e.png")

        assert Path(saved["storage_path"]).is_file()
        assert str(saved["storage_path"]).startswith(str(elsewhere)), saved["storage_path"]


class TestRouteOrderAnchorStaysHonoured:
    def test_newLiteralSegmentsResolveBeforeParamRoute(self, client):
        """/trash 是单段字面路由，必须注册在 GET /{media_id} 之前（台账 2026-09-11 ⑤）。"""
        from fastapi.routing import APIRoute

        specs = [(r.path, set(r.methods or ()))
                 for r in media_module.router.routes if isinstance(r, APIRoute)]
        trashAt = next(i for i, (p, _m) in enumerate(specs) if p == "/trash")
        paramAt = next(i for i, (p, m) in enumerate(specs) if p == "/{media_id}" and "GET" in m)

        assert trashAt < paramAt, "/trash 注册在 /{media_id} 之后，会被吞成 404"
        assert client.get("/api/v1/media/trash", params={"agent_id": AGENT}).status_code == 200

    def test_routeFreezeListCarriesTheNewSegments(self):
        """路由冻结清单（`EXPECTED_ROUTES`）必须与本批新面同步——否则它是个假锚。"""
        guard = Path(__file__).resolve().parents[2] / "tests/unit/api/test_media_route_order_guard.py"
        table = guard.read_text(encoding="utf-8").split("EXPECTED_ROUTES = [", 1)[1].split("]", 1)[0]

        assert '("/trash", {"GET"})' in table, "清单里没有 GET /trash"
        assert '("/{media_id}/restore", {"POST"})' in table, "清单里没有 POST /{media_id}/restore"
        assert table.index('("/trash", {"GET"})') < table.index('("/{media_id}", {"GET"})'), (
            "清单里的顺序与路由表不一致——那份锚就不再描述「字面段在前」这件事")
