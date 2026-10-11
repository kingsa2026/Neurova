# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-12 批 13，裁定乙）：媒体回收站四件在**活 app** 上真走一遍。

判据档（`tests/media/test_mediaTrashLifecycle.py`）挂的是手搭的 `FastAPI()`；这一支要证的是
另一件事——`/trash` 与 `/{media_id}/restore` 在 `create_app()` 的真实路由表里真的可达、
真受同一道鉴权门管、真的把字节留在盘上又真的能删掉。手搭 app 全绿而活 app 挂不到，
正是本仓插件面那次「`routes_mounted` 恒 false」的同族形态。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/mediaTrash_batch13.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaMediaTrash13")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import get_current_user as authUser  # noqa: E402
from neurova.api.endpoints import media as media_ep  # noqa: E402

failures: list[str] = []
BASE = "/api/v1/media"
CALLER = {"user_id": "1", "username": "tester", "role": "user"}
AGENT = "live-b13"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _upload(client, content: bytes, name="clip.png"):
    resp = client.post(f"{BASE}/save",
                       files={"file": (name, content, "image/png")},
                       data={"media_type": "image", "agent_id": AGENT})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    app = create_app(enable_memory=False, enable_channels=False)
    app.dependency_overrides[authUser] = lambda: dict(CALLER)

    with TestClient(app, raise_server_exceptions=False) as client:
        # ── [1] 活 app 上两档新路由真可达（不是手搭 app 里才存在）────────
        saved = _upload(client, b"live-trash-bytes")
        mid = saved["media_id"]
        check("[1a] GET /trash 在活 app 上是 200 而不是被 /{media_id} 吞掉的 404",
              client.get(f"{BASE}/trash", params={"agent_id": AGENT}).status_code == 200,
              str(client.get(f"{BASE}/trash", params={"agent_id": AGENT}).status_code))

        # ── [2] 软删：字节留盘、行离开全部现役读面 ─────────────────────
        disk = Path(media_ep.Path(saved["storage_path"]))
        trashed = client.delete(f"{BASE}/{mid}?mode=trash")
        listed = client.get(f"{BASE}/list", params={"agent_id": AGENT}).json()["data"]
        stats = client.get(f"{BASE}/stats/{AGENT}").json()["data"]
        trashBody = client.get(f"{BASE}/trash", params={"agent_id": AGENT}).json()["data"]
        check("[2a] ?mode=trash 回 200 且字节仍在盘上",
              trashed.status_code == 200 and disk.is_file(),
              f"{trashed.status_code} 盘上存在={disk.is_file()}")
        check("[2b] 三个列表面都不再带出它，/trash 恰好带出它",
              [m["media_id"] for m in listed["media"]] == []
              and stats["total_files"] == 0
              and [m["media_id"] for m in trashBody["media"]] == [mid],
              f"list={listed['total']} stats={stats['total_files']} trash={trashBody['total']}")
        check("[2c] 三个取物口径都 404（漏一处就等于条目还捞得回来）",
              all(client.get(p).status_code == 404 for p in
                  (f"{BASE}/{mid}", f"{BASE}/download/{mid}", f"{BASE}/{mid}/metadata")),
              str({p: client.get(p).status_code for p in
                   (f"{BASE}/{mid}", f"{BASE}/download/{mid}", f"{BASE}/{mid}/metadata")}))

        # ── [3] 恢复：原字节、原 id、回到 /list ─────────────────────────
        restored = client.post(f"{BASE}/{mid}/restore")
        fetched = client.get(f"{BASE}/{mid}")
        check("[3a] restore 200 且取回的字节与上传的逐字节相等",
              restored.status_code == 200 and fetched.content == b"live-trash-bytes",
              f"{restored.status_code} 内容={fetched.content[:18]!r}")
        check("[3b] 恢复后 /list 带出它、/trash 不再带出它",
              [m["media_id"] for m in
               client.get(f"{BASE}/list", params={"agent_id": AGENT}).json()["data"]["media"]]
              == [mid]
              and client.get(f"{BASE}/trash", params={"agent_id": AGENT}).json()["data"]["total"] == 0,
              "读写两面都跟着变了")

        # ── [4] 坏 mode 与重复动作都诚实拒绝，且不改状态 ────────────────
        badMode = client.delete(f"{BASE}/{mid}?mode=soft")
        check("[4a] 未知 mode 回 400（不许兜底成任何一种删除）",
              badMode.status_code == 400, f"{badMode.status_code} {badMode.text[:60]}")
        check("[4b] 坏 mode 之后条目仍是活的、字节仍在",
              client.get(f"{BASE}/{mid}").status_code == 200 and disk.is_file(),
              f"内容面={client.get(f'{BASE}/{mid}').status_code} 盘上={disk.is_file()}")
        restoreAgain = client.post(f"{BASE}/{mid}/restore")
        check("[4c] 对活条目「恢复」回 409 而不是静默 200",
              restoreAgain.status_code == 409, f"{restoreAgain.status_code} {restoreAgain.text[:60]}")

        # ── [5] 重启复原：索引里的标记跨装载仍是回收站行 ─────────────────
        client.delete(f"{BASE}/{mid}?mode=trash")
        fresh: dict = {}
        previous = media_ep._media_store
        media_ep._media_store = fresh
        try:
            media_ep._load_index()
        finally:
            media_ep._media_store = previous
        check("[5] 用真 `_load_index()` 读回后该行仍带 is_deleted（重启不复活成活文件，也不被巡检误剔）",
              fresh.get(mid, {}).get("is_deleted") is True,
              f"复原行={fresh.get(mid)!r}")

        # ── [6] 彻底删除与默认档：都删字节，语义没被翻转 ─────────────────
        gone = client.delete(f"{BASE}/{mid}?mode=permanent")
        check("[6a] ?mode=permanent 同时删掉字节与行",
              gone.status_code == 200 and not disk.exists() and mid not in media_ep._media_store,
              f"{gone.status_code} 盘上={disk.is_file()}")
        defSave = _upload(client, b"default-hard", name="d.png")
        defDisk = Path(media_ep.Path(defSave["storage_path"]))
        client.delete(f"{BASE}/{defSave['media_id']}")
        check("[6b] 不带 mode 仍是硬删（现役页面「删了就没了」的承诺没翻）",
              not defDisk.exists(), f"盘上存在={defDisk.is_file()}")

        # ── [7] 批量面两档与鉴权门 ─────────────────────────────────────
        a = _upload(client, b"batch-a", name="a.png")
        b = _upload(client, b"batch-b", name="b.png")
        batch = client.post(f"{BASE}/batch-delete",
                            json={"media_ids": [a["media_id"], b["media_id"], "media-nope"],
                                  "mode": "trash"})
        check("[7a] batch 的 trash 档逐个落标记，未知 id 逐条报 media not found",
              batch.json()["data"]["succeeded"] == [a["media_id"], b["media_id"]]
              and batch.json()["data"]["failed"] == [
                  {"media_id": "media-nope", "reason": "media not found"}],
              batch.text[:120])
        client.post(f"{BASE}/batch-delete", json={"media_ids": [a["media_id"]]})
        client.post(f"{BASE}/batch-delete", json={"media_ids": [b["media_id"]], "mode": "permanent"})
        check("[7b] batch 不带 mode 仍旧硬删；permanent 也硬删",
              not Path(media_ep.Path(a["storage_path"])).exists()
              and not Path(media_ep.Path(b["storage_path"])).exists(),
              "两档都把字节清掉了")

        app.dependency_overrides.clear()
        unauth = TestClient(app).delete(f"{BASE}/{a['media_id']}?mode=trash")
        check("[8] 摘掉身份覆盖后回收站写口回到 401（新面没绕过既有鉴权门）",
              unauth.status_code == 401, str(unauth.status_code))

    print()
    if failures:
        print("LIVE-VERIFY FAILED / 批 13 媒体回收站：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / 工单 2026-10-12 批 13（媒体软删＋回收站四件，默认档不变）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
