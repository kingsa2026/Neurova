# -*- coding: utf-8 -*-
"""契约快照 + verify-diff 门与前端路径守卫的判据测试（实施计划项 5）。

门的两条红线：
1. 后端 API 形状变了而 `contracts/openapi.snapshot.json` 没同步
   → `scripts/check_openapi_snapshot.py` 必须红；
2. 前端引用了后端不存在的请求路径 → `scripts/check_frontend_api_paths.py` 必须红。

测试全部走 tmp_path + monkeypatch：重导出被钉成固定快照，不触碰仓库真快照，
也不真起 `create_app()`（全量装配实测约 37s，属脚本与 CI 的职责，不进单测预算）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.check_frontend_api_paths as check_frontend_api_paths
import scripts.check_openapi_snapshot as check_openapi_snapshot
import scripts.export_openapi as export_openapi

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 固定快照：测的是门的判据，不是真实装配结果。
FIXED_SNAPSHOT = {
    "generator": "scripts/export_openapi.py",
    "mode": "openapi",
    "routeCount": 3,
    "websocketPaths": [],
    "openapi": {
        "openapi": "3.1.0",
        "info": {"title": "Neurova API", "version": "test"},
        "paths": {
            "/api/v1/agents": {"get": {"operationId": "listAgents"}},
            "/api/v1/agents/{agent_id}": {"get": {"operationId": "getAgent"}},
            "/api/v1/console/sessions/{session_id}": {
                "get": {"operationId": "getConsoleSession"}
            },
        },
    },
}


@pytest.fixture()
def snapshotFile(tmp_path, monkeypatch):
    """把「重新导出」钉成固定快照，并把它落到 tmp 快照文件——门比对的对象。"""
    monkeypatch.setattr(
        export_openapi, "buildSnapshot", lambda: json.loads(json.dumps(FIXED_SNAPSHOT))
    )
    path = tmp_path / "openapi.snapshot.json"
    path.write_text(export_openapi.serializeSnapshot(FIXED_SNAPSHOT), encoding="utf-8")
    return path


class TestOpenapiSnapshotGate:
    """快照 verify-diff 门：一致绿、漂移红、序列化字节稳定。"""

    def test_serializationIsByteStableRegardlessOfKeyOrder(self):
        left = {"b": 1, "a": {"y": [1, 2], "x": None}}
        right = {"a": {"x": None, "y": [1, 2]}, "b": 1}
        assert export_openapi.serializeSnapshot(left) == export_openapi.serializeSnapshot(right)

    def test_consistentSnapshotStaysGreen(self, snapshotFile, capsys):
        assert check_openapi_snapshot.main(["--snapshot", str(snapshotFile)]) == 0
        assert "一致" in capsys.readouterr().out

    def test_tamperedSnapshotTurnsGateRed(self, snapshotFile, capsys):
        """红 a：篡改仓库快照（删路由 + 改 operationId）→ 门必须红并点名差异路径。"""
        tampered = json.loads(snapshotFile.read_text(encoding="utf-8"))
        del tampered["openapi"]["paths"]["/api/v1/agents/{agent_id}"]
        tampered["openapi"]["paths"]["/api/v1/agents"]["get"]["operationId"] = "renamed"
        snapshotFile.write_text(export_openapi.serializeSnapshot(tampered), encoding="utf-8")

        assert check_openapi_snapshot.main(["--snapshot", str(snapshotFile)]) == 1
        out = capsys.readouterr().out
        assert "/api/v1/agents/{agent_id}" in out, "被删路由必须被点名"
        assert "operationId" in out, "operationId 漂移必须被点名"

    def test_newRouteWithoutSnapshotUpdateTurnsGateRed(self, tmp_path, monkeypatch, snapshotFile):
        """红 a 另一形态：现网新增了一条端点而快照未更新 → 门红。"""
        drifted = json.loads(json.dumps(FIXED_SNAPSHOT))
        drifted["openapi"]["paths"]["/api/v1/brand-new"] = {"post": {"operationId": "newThing"}}
        monkeypatch.setattr(export_openapi, "buildSnapshot", lambda: drifted)
        assert check_openapi_snapshot.main(["--snapshot", str(snapshotFile)]) == 1

    def test_diffNamesDeepLeafPaths(self):
        expected = {"a": {"b": {"c": 1}}, "keep": [1, {"k": "v"}]}
        actual = {"a": {"b": {"c": 2}}, "keep": [1, {"k": "x"}]}
        diffs = check_openapi_snapshot.diffPaths(expected, actual)
        assert any("a.b.c" in d for d in diffs)
        assert any("keep[1].k" in d for d in diffs)


class TestFrontendPathGate:
    """前端路径守卫：引用存在的路径绿、引用不存在的路径红。"""

    @staticmethod
    def _makeProject(tmp_path: Path, moduleText: str, snapshot: dict) -> Path:
        modules = tmp_path / "NeurUI" / "src" / "api" / "modules"
        modules.mkdir(parents=True)
        (modules / "probe.ts").write_text(moduleText, encoding="utf-8")
        barrel = tmp_path / "NeurUI" / "src" / "api" / "index.ts"
        barrel.write_text("export const api = {}\n", encoding="utf-8")
        snap = tmp_path / "contracts" / "openapi.snapshot.json"
        snap.parent.mkdir(parents=True, exist_ok=True)
        snap.write_text(export_openapi.serializeSnapshot(snapshot), encoding="utf-8")
        return tmp_path

    def test_unknownPathTurnsGateRed(self, tmp_path, capsys):
        """红 b：前端引用后端不存在的路径 → 门红并点名路径与文件。"""
        root = self._makeProject(
            tmp_path, "export const x = () => api.get('/zzz/does-not-exist')\n", FIXED_SNAPSHOT
        )
        assert check_frontend_api_paths.main(["--project-root", str(root)]) == 1
        out = capsys.readouterr().out
        assert "/zzz/does-not-exist" in out
        assert "probe.ts" in out

    def test_knownPathAndParamTemplateStayGreen(self, tmp_path):
        """绿 c：字面路径、参数模板、模块 BASE 前缀都能对上 → 绿。"""
        text = (
            "const BASE = '/console'\n"
            "export const a = () => api.get('/agents')\n"
            "export const b = (id: string) => api.get(`/agents/${id}/memory`)\n"
            "export const c = (sid: string) => api.get(`${BASE}/sessions/${sid}`)\n"
        )
        snapshot = json.loads(json.dumps(FIXED_SNAPSHOT))
        snapshot["openapi"]["paths"]["/api/v1/agents/{agent_id}/memory"] = {
            "get": {"operationId": "agentMemory"}
        }
        root = self._makeProject(tmp_path, text, snapshot)
        assert check_frontend_api_paths.main(["--project-root", str(root)]) == 0

    def test_baseUrlPrefixAndQueryAreStripped(self, tmp_path):
        """baseURL（/api/v1）前缀与查询串不参与比对。"""
        text = (
            "const base = config.apiBaseUrl\n"
            "export const a = () => api.get('/agents?full=1')\n"
            "export const b = () => fetch(`${base}/agents/stream`)\n"
        )
        snapshot = json.loads(json.dumps(FIXED_SNAPSHOT))
        snapshot["openapi"]["paths"]["/api/v1/agents/stream"] = {
            "get": {"operationId": "agentStream"}
        }
        root = self._makeProject(tmp_path, text, snapshot)
        assert check_frontend_api_paths.main(["--project-root", str(root)]) == 0


class TestFrontendPathExtraction:
    """抽取器单元判据：引号/模板字面量、BASE 常量、参数段归一。"""

    def test_extractsQuotedAndTemplatePaths(self):
        text = (
            "const BASE = '/console'\n"
            "api.get('/agents')\n"
            "api.post(`/agents/${id}/switch`, data)\n"
            "api.get(`${BASE}/sessions`)\n"
        )
        paths = check_frontend_api_paths.extractFrontendPaths(text)
        assert "/agents" in paths
        assert "/agents/*/switch" in paths
        assert "/console/sessions" in paths

    def test_ignoresAbsoluteUrlsCommentsAndBareSlashes(self):
        text = (
            "// api.get('/commented/out')\n"
            "const url = 'https://example.com/api/x'\n"
            "const sep = '/'\n"
            "api.get('/real/path')\n"
        )
        paths = check_frontend_api_paths.extractFrontendPaths(text)
        assert paths == {"/real/path"}

    def test_snapshotPathSetStripsApiV1AndNormalizesParams(self):
        snapshot = {
            "mode": "openapi",
            "websocketPaths": ["/api/v1/console/ws/{client_id}"],
            "openapi": {
                "paths": {
                    "/api/v1/agents/{agent_id}": {},
                    "/health": {},
                }
            },
        }
        assert check_frontend_api_paths.snapshotPathSet(snapshot) == {
            "/agents/*",
            "/health",
            "/console/ws/*",
        }

    def test_missingPathsAreSortedAndNamed(self):
        missing = check_frontend_api_paths.missingPaths(
            {"/b/missing", "/a/missing", "/agents"}, {"/agents"}
        )
        assert missing == ["/a/missing", "/b/missing"]


class TestShippedSnapshotShape:
    """仓库真快照的存在性与基本形状——门当场可跑的前提。"""

    def test_snapshotIsPresentAndShaped(self):
        path = PROJECT_ROOT / "contracts" / "openapi.snapshot.json"
        assert path.is_file(), "contracts/openapi.snapshot.json 不存在——门没有可比对象"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("mode") == "openapi"
        paths = data.get("openapi", {}).get("paths", {})
        assert len(paths) > 150, f"快照只覆盖 {len(paths)} 条路径，疑似导出失败"
        assert "/api/v1/auth/login" in paths
        assert "/api/v1/chat" in paths
        assert "/api/v1/chat/stream" in paths

    def test_frontendRealPathsAllExistInSnapshot(self):
        """真仓绿门：前端 api 模块的每一条路径字面量都必须能在真快照里找到。"""
        snapshot = json.loads(
            (PROJECT_ROOT / "contracts" / "openapi.snapshot.json").read_text(encoding="utf-8")
        )
        known = check_frontend_api_paths.snapshotPathSet(snapshot)
        missing = check_frontend_api_paths.collectMissingPaths(PROJECT_ROOT, known)
        assert not missing, (
            "前端引用了快照里不存在的请求路径（必 404）：\n"
            + "\n".join(f"  {path} ← {', '.join(files)}" for path, files in sorted(missing.items()))
        )
