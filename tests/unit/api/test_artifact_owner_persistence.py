# -*- coding: utf-8 -*-
"""导入产物的属主与注册表持久化（Issue #81 断点③，用户拍板与断点②同批做）。

红灯依据（真链路实测，取证见设计 §7.7 断点③）：`intake._artifact_info` 产出的条目
**不带 `user_id`**，而读端 `_get_owned_artifact` 按 `user_id` 精确判归属 → 任何已登录
用户请求 `/v1/artifacts/{id}/content` 一律 404；产物注册表 `_artifacts_store` 亦无持久化
（`app.py` 只水合 `files_api`），跨进程与重启都不共享。两处一起修才有可读的媒体。

**会话属主与产物属主的关系（本批定下）**：两者在同一批导入里**取值同源**——都取
`apply --owner-user-id` 那一个值（这段历史是同一个人的，它的证据文件当然也是他的）。
但它们不是同一个判据：会话属主落在会话文件 `user_id` 上（运行期会话写入口维护），
产物属主落在条目 `user_id` 上（运行期产物来自请求身份，与"批次属主"无关）。
所以不合并成一个字段、也不互相推导，只保证导入这一条路上两处取同一来源。

共享语义显式化：批次没给属主（共享批次）时，条目落 `shared=True` 而不是留空串——
读端据此放行任何已登录用户。**既无 `user_id` 又无 `shared` 标记的条目一律 404**：
漏写属主这件事不许被静默放行成"共享"，报错以诚实形态暴露。

判据（先红后绿）：
1. 写侧：导入媒体的条目带属主，值与批次的 `owner_user_id` 同源；
2. 共享批次：条目落 `shared=True`（不是留空）；
3. 读端：属主可读内容；非属主 404；共享条目任何已登录用户可读；
4. 漏写（既无属主又无共享标记）仍 404——不放行越权；
5. 持久化：注册后重新水合仍在（跨进程/重启可见），丢盘文件的行被清理，坏库不阻塞。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import artifacts_api


def _make_workspace_file(root: Path, name: str = "shot.png") -> Path:
    agent_dir = root / "media-agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / name
    path.write_bytes(b"PNG")
    return path


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    # 元数据库落点也要隔离：不隔离就写进仓库 data/，跨用例互相看见彼此的条目
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    artifacts_api._artifacts_store.clear()
    yield tmp_path / "workspaces"
    artifacts_api._artifacts_store.clear()


def _client(monkeypatch, user_id: str) -> TestClient:
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(artifacts_api.router, prefix="/v1/artifacts")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": user_id, "username": user_id, "role": "user", "neuser_id": user_id,
    }
    return TestClient(app)


class TestOwnerLandsOnTheArtifactEntry:
    def test_ingest_entry_carries_the_batch_owner(self, workspace, tmp_path, monkeypatch):
        entry = _ingest_media_entry(workspace, tmp_path, monkeypatch, owner="u_alice")

        assert entry.get("user_id") == "u_alice", (
            f"导入媒体条目没有属主：{entry}——读端按 user_id 判归属，任何人请求都 404"
        )
        assert not entry.get("shared")

    def test_shared_batch_marks_the_entry_shared_explicitly(self, workspace, tmp_path, monkeypatch):
        entry = _ingest_media_entry(workspace, tmp_path, monkeypatch, owner="")

        assert entry.get("shared") is True, (
            f"共享批次的产物既没有属主也没有共享标记：{entry}——"
            "读端只能一律 404（诚实拒绝），用户仍看不到自己导入的图"
        )


class TestReadingSurfaceHonoursTheOwner:
    def test_owner_reads_the_content_and_others_get_404(self, workspace, monkeypatch):
        path = _make_workspace_file(workspace)
        info = artifacts_api.register_artifact(str(path), agent_id="media-agent", user_id="u_alice")

        assert _client(monkeypatch, "u_alice").get(
            f"/v1/artifacts/{info['artifact_id']}/content").status_code == 200
        assert _client(monkeypatch, "u_bob").get(
            f"/v1/artifacts/{info['artifact_id']}/content").status_code == 404

    def test_shared_entry_is_readable_by_any_signed_in_user(self, workspace, monkeypatch):
        path = _make_workspace_file(workspace)
        info = artifacts_api.register_artifact(
            str(path), agent_id="media-agent", shared=True)

        assert _client(monkeypatch, "u_bob").get(
            f"/v1/artifacts/{info['artifact_id']}/content").status_code == 200

    def test_entry_without_owner_or_shared_flag_stays_404(self, workspace, monkeypatch):
        """漏写属主不许被静默放行：既无属主又无共享标记 → 诚实 404。"""
        path = _make_workspace_file(workspace)
        info = artifacts_api.register_artifact(str(path), agent_id="media-agent")

        assert _client(monkeypatch, "u_bob").get(
            f"/v1/artifacts/{info['artifact_id']}/content").status_code == 404


class TestRegistryPersistence:
    def test_registered_entry_survives_a_rehydrate(self, workspace, tmp_path):
        path = _make_workspace_file(workspace)
        db = str(tmp_path / "users.db")
        info = artifacts_api.register_artifact(
            str(path), agent_id="media-agent", user_id="u_alice", db_path=db)

        artifacts_api._artifacts_store.clear()
        loaded = artifacts_api.hydrate_artifacts_store(db_path=db)

        assert info["artifact_id"] in loaded, "注册表没有持久化：重启后条目消失、预览与读端全 404"
        assert artifacts_api._artifacts_store[info["artifact_id"]]["user_id"] == "u_alice"

    def test_rehydrate_drops_rows_whose_file_is_gone(self, workspace, tmp_path):
        path = _make_workspace_file(workspace)
        db = str(tmp_path / "users.db")
        artifacts_api.register_artifact(str(path), agent_id="media-agent", user_id="u_alice",
                                        db_path=db)
        path.unlink()

        loaded = artifacts_api.hydrate_artifacts_store(db_path=db)

        assert loaded == {}, "磁盘文件已丢的行没被清理——留下读端必 404 的僵尸条目"

    def test_corrupt_db_does_not_raise(self, workspace, tmp_path):
        db = tmp_path / "corrupt.db"
        db.write_bytes(b"not a sqlite db")

        assert artifacts_api.hydrate_artifacts_store(db_path=str(db)) == {}


def _ingest_media_entry(workspace, tmp_path: Path, monkeypatch, owner: str) -> dict:
    """端到端：真 intake 落一条带媒体的导入，取出会话消息里的产物条目。"""
    import base64

    from neurova.core.agent_workspaces import get_agent_workspace_dir
    from neurova.memory_ingest.bundle.media import MediaSink
    from neurova.memory_ingest.intake import apply_bundle
    from neurova.session_manager import SessionManager

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
        "IQAAAABJRU5ErkJggg==")
    bundle = tmp_path / "bundle-owner"
    bundle.mkdir(exist_ok=True)
    ref = dict(MediaSink(bundle, name_hint="shot.png").put(png), type="image")
    (bundle / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "generated_at": "2026-09-20T00:00:00+00:00",
        "agent_name": "media-agent", "source": {"converter": "test", "version": "1"},
        "counts": {"transcripts": 1, "memories": 0, "relations": 0},
        "dropped": [], "stores": []}), encoding="utf-8")
    (bundle / "transcripts.jsonl").write_text(json.dumps({
        "session_id": "sA", "seq": 1, "kind": "user_message",
        "ts": "2026-05-01T10:00:01+00:00", "identity_key": "e1", "role": "user",
        "content_blocks": [{"type": "text", "text": "看图"}, ref]}, ensure_ascii=False) + "\n",
        encoding="utf-8")

    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    SessionManager._instance = None
    sessions = SessionManager()
    try:
        apply_bundle(bundle, agent_id="media-agent", manager=None, sessions=sessions,
                     owner_user_id=owner)
        messages = sessions.import_session_messages  # noqa: F841 - 保持装配点可读
        path = sessions._get_session_file("media-agent", "sA", "2026-05-01")
        data = sessions._read_session_file(path) or {}
        return data["messages"][0]["metadata"]["artifacts"][0]
    finally:
        SessionManager._instance = None
        get_agent_workspace_dir("media-agent")   # 收口：路径推导同源
