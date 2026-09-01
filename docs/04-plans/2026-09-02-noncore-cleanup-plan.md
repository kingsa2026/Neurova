# 全方位补课清单细化实施计划（2026-09-02）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **来源**：`docs/Neurova_QwenPaw全方位对比_v4_2026-09-01.md` §19 合并补课清单（原 §12，前端功能篇 09-02 并入后重新编号）的细化。每项都经代码级落点核实（文件:行号），含计划撰写时的现场复核修正（见 §0）。
>
> **测试纪律**（用户长期规则）：临时验证脚本即用即删；正式测试放 `tests/unit/<域>/`。注意 `.gitignore:269` 有 `/tests/` 规则——**新增测试文件必须 `git add -f`**。
>
> **venv 注意**：项目解释器是 `venv/Scripts/python.exe`（3.12），跑 pytest 用它。

## §0 现场复核修正（计划撰写时推翻/修正 v4 文档的三处结论）

1. **P3-b 温度渐进索引：v4 文档结论错误，实际已实现**。`neurova/mem_core.py:285` `_background_index_memories`（daemon 线程 `moe-semantic-indexer`，mem_core.py:760 启动）：按温度降序 OFFSET 分页、批间 0.05s 让出、预算 `vector_search.moe_index_limit`（默认 20000）、游标无进展守卫、完成状态落盘 `data/moe_index_state_{md5}.json`（mem_core.py:248，下次启动跳过重扫）。**本计划 P3-b 改为"验证+补防回归测试"**，不再重复实现。
2. **BackupOrchestrator"孤儿"确认**：全仓调用方仅 `neurova/backup/__init__.py` 与自身。测试已有 `tests/unit/backup/test_orchestrator.py`。接线点=新增 API 端点模块 + `neurova/api/endpoints/__init__.py:179` `register_endpoint_routers` 的模块列表追加一行。
3. **admin 鉴权惯例**：`neurova/api/deps.py:345` `require_admin()`（内部 `require_role("admin")`，返回依赖工厂）。用法 `Depends(require_admin())`（参照 enhanced_users_api.py:164）。整路由级：`APIRouter(dependencies=[Depends(require_admin())])`（enhanced_users_api.py:28）。

---

## Task 1（P1-b）：修 docker-compose 前端挂载 + requirements hashes

**Files:**
- Modify: `docker-compose.yml:39`
- Modify: `requirements.txt`（可选增强，见 Step 3）

- [ ] **Step 1: 修挂载路径**

`docker-compose.yml:39` 一行：

```yaml
    volumes:
      - ./NeurUI:/app
```

（`./neuUI` → `./NeurUI`；目录实证为 `NeurUI/`）

- [ ] **Step 2: 验证 compose 配置合法**

```bash
docker compose config --quiet && echo OK
```
Expected: `OK`（无 docker 环境时跳过，人工 diff 确认）

- [ ] **Step 3: requirements hashes（可选，若 CI 有 pip-audit 联动需求）**

现状：`requirements.txt` 宽区间，`requirements-ci.lock`（323 行 uv 生成）已有精确 pin 但无 hashes。**最小动作**：不加 hashes（uv pip compile 重新生成带 hashes 会引入跨平台解析噪音），改为在 Dockerfile 顶部补一行注释指明 lock 文件用途偏差——**YAGNI：仅当用户要求供应链加固时做**。默认跳过本步。

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(deploy): compose frontend mount neuUI→NeurUI — dev profile 恢复可用"
```

---

## Task 2（P1-c）：database 健康检查换真连库

**Files:**
- Modify: `neurova/api/app.py:100-108`
- Test: `tests/unit/core/test_health_check_database.py`（新建）

背景：`_register_default_health_checks`（app.py:94）里 database 检查是 `lambda: (True, "SQLite OK")` 硬编码假检查。真检查用 `neurova.core.database.database_connection` 上下文（database.py:73，内部走连接池+WAL）。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/core/test_health_check_database.py
"""database 健康检查真连库防回归（原为硬编码 (True, "SQLite OK") 假检查）"""
from unittest.mock import patch

import pytest


def test_database_check_executes_real_query(tmp_path):
    from neurova.api.app import _make_database_health_check

    check = _make_database_health_check(str(tmp_path / "health.db"))
    ok, detail = check()
    assert ok is True
    assert "select" in detail.lower()  # 详情含真实探测语句语义，非静态 "SQLite OK"


def test_database_check_fails_when_conn_errors(tmp_path):
    from neurova.api.app import _make_database_health_check

    check = _make_database_health_check(str(tmp_path / "bad" / "x.db"))
    with patch("neurova.core.database.database_connection", side_effect=RuntimeError("db down")):
        ok, detail = check()
    assert ok is False
    assert "db down" in detail
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_health_check_database.py -v
```
Expected: FAIL `cannot import name '_make_database_health_check'`

- [ ] **Step 3: 实现**

app.py 的 `_register_default_health_checks` 中，database 注册改为：

```python
    # 数据库检查（真连库：SELECT 探测 + 失败上报，替代原硬编码假检查）
    health_checker.register(
        name="database",
        check_func=_make_database_health_check(),
        check_type=CheckType.READINESS,
        description="Database connectivity check",
        critical=True,
    )
```

并在 `_register_default_health_checks` 上方新增工厂函数：

```python
def _make_database_health_check(db_path: str = "neurova_memory.db"):
    """构造 database 健康检查闭包（可注入 db_path 供测试）。"""

    def check_database():
        try:
            from neurova.core.database import database_connection

            with database_connection(db_path) as conn:
                conn.execute("SELECT 1").fetchone()
            return True, "database reachable (SELECT 1 ok)"
        except Exception as exc:
            return False, f"database check failed: {exc}"

    return check_database
```

- [ ] **Step 4: 跑测试确认通过 + 不破坏既有健康检查**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_health_check_database.py -v
venv/Scripts/python.exe -m pytest tests/unit/core/ -k health -v
```
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add -f tests/unit/core/test_health_check_database.py
git add neurova/api/app.py
git commit -m "fix(health): database 检查真连库（SELECT 1 探测+失败上报）— 替换硬编码假检查"
```

---

## Task 3（P1-a）：BackupOrchestrator 接 admin API

**Files:**
- Create: `neurova/api/endpoints/backup_api.py`
- Modify: `neurova/api/endpoints/__init__.py`（endpoint_modules 列表追加一行）
- Test: `tests/unit/api/test_backup_api.py`（新建）

设计（对齐既有惯例）：
- 路由级 admin 门：`router = APIRouter(dependencies=[Depends(require_admin())])`（enhanced_users_api.py:28 模式）
- 单例 orchestrator：模块级 `get_backup_orchestrator()` 懒创建（DCL + RLock，对齐 singleton 收敛后的仓库规约；key 落 `data/backup_signing.key`，SigningKey 自带 0600/O_EXCL）
- create 的 sources 固定映射：`{"sessions": "sessions", "agent_workspaces": "agent_workspaces"}`（实证目录存在；`data/` 含运行态 DB 排除——SQLite 在线文件打包不一致，诚实边界写入 docstring）
- restore 用 `apply_fn` 把 files 写回原前缀目录（Zip Slip 防护：解析后路径必须仍在前缀目录内）
- 信封：沿用仓库标准 `{success, data, message}` 信封（对齐 notification 系统改造后的契约）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/api/test_backup_api.py
"""BackupOrchestrator admin API 接线测试（防孤儿代码回归）"""
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 隔离：key 与备份产物落 tmp；绕过真实鉴权（单测只验接线与编排语义）
    monkeypatch.setenv("NEUROVA_BACKUP_KEY_PATH", str(tmp_path / "key.bin"))
    monkeypatch.setenv("NEUROVA_BACKUP_WORK_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("NEUROVA_BACKUP_SOURCES", json.dumps({
        "sessions": str(tmp_path / "sessions"),
        "agent_workspaces": str(tmp_path / "ws"),
    }))

    from neurova.api.endpoints import backup_api

    app = FastAPI()
    app.include_router(backup_api.router, prefix="/v1/backups")
    return TestClient(app)


def _auth_override(monkeypatch):
    from neurova.api.deps import get_current_user
    return {"username": "admin", "role": "admin"}


@pytest.fixture()
def authed_client(client, monkeypatch):
    from neurova.api.deps import get_current_user
    client.app.dependency_overrides[get_current_user] = _auth_override(monkeypatch)
    yield client
    client.app.dependency_overrides.clear()


def test_create_backup_returns_zip_and_verifies(authed_client, tmp_path):
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / "a.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "ws" / "cfg.json").write_text('{"w": 2}', encoding="utf-8")

    resp = authed_client.post("/v1/backups/create")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    zip_path = Path(body["data"]["zip_path"])
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert "sessions/a.json" in zf.namelist()
        assert "meta.json" in zf.namelist()


def test_list_and_restore_roundtrip(authed_client, tmp_path):
    (tmp_path / "sessions").mkdir(exist_ok=True)
    (tmp_path / "sessions" / "b.json").write_text("x", encoding="utf-8")
    created = authed_client.post("/v1/backups/create").json()["data"]["zip_path"]

    listed = authed_client.get("/v1/backups").json()
    assert listed["success"] is True
    assert any(item["zip_path"] == created for item in listed["data"]["items"])

    # 破坏源文件后恢复
    (tmp_path / "sessions" / "b.json").unlink()
    resp = authed_client.post("/v1/backups/restore", json={"zip_path": created})
    assert resp.status_code == 200, resp.text
    assert (tmp_path / "sessions" / "b.json").read_text(encoding="utf-8") == "x"


def test_restore_rejects_untrusted_foreign(authed_client, tmp_path):
    # 构造一个他实例签名的 zip（FOREIGN）：用独立 key 签名
    from neurova.backup.trust import SigningKey, sign_backup
    other_key_dir = tmp_path / "other"
    other_key_dir.mkdir()
    foreign_zip = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign_zip, "w") as zf:
        zf.writestr("sessions/c.json", "y")
        zf.writestr("meta.json", json.dumps({"scheme": "hmac-sha256-v1", "backup_id": "x"}))
    sign_backup(foreign_zip, SigningKey(other_key_dir / "k.bin"))

    resp = authed_client.post("/v1/backups/restore", json={"zip_path": str(foreign_zip)})
    assert resp.status_code == 409  # TrustRequiredError → 409，绝不静默恢复


def test_unauthenticated_rejected(client):
    assert client.post("/v1/backups/create").status_code in (401, 403)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/unit/api/test_backup_api.py -v
```
Expected: FAIL/ERROR `No module named 'neurova.api.endpoints.backup_api'`

- [ ] **Step 3: 实现端点模块**

```python
# neurova/api/endpoints/backup_api.py
# -*- coding: utf-8 -*-
"""备份管理 API（BackupOrchestrator 系统接线）。

孤儿接线（v4 对比 P1-a）：orchestrator 能力完整但此前无 API/CLI 触达。
诚实边界：
- create 的 sources 固定为 sessions/agent_workspaces 目录映射（可用
  NEUROVA_BACKUP_SOURCES 覆盖）；data/ 运行态 SQLite 不入包（在线文件
  打包不一致，热备需 sqlite3 backup API，另行立项）。
- restore 的 apply_fn 把 files 写回原前缀目录，带 Zip Slip 防护。
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from neurova.api.deps import require_admin
from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(require_admin())])

_orchestrator = None
_orch_lock = threading.RLock()


def get_backup_orchestrator():
    """懒单例（DCL，对齐仓库 singleton 收敛规约）。"""
    global _orchestrator
    if _orchestrator is None:
        with _orch_lock:
            if _orchestrator is None:
                from neurova.backup.orchestrator import BackupOrchestrator
                from neurova.backup.trust import SigningKey

                sources = json.loads(
                    os.environ.get(
                        "NEUROVA_BACKUP_SOURCES",
                        json.dumps({"sessions": "sessions", "agent_workspaces": "agent_workspaces"}),
                    )
                )
                _orchestrator = BackupOrchestrator(
                    key=SigningKey(os.environ.get("NEUROVA_BACKUP_KEY_PATH", "data/backup_signing.key")),
                    work_dir=os.environ.get("NEUROVA_BACKUP_WORK_DIR", "data/backups"),
                )
                _orchestrator.default_sources = sources  # type: ignore[attr-defined]
    return _orchestrator


def _reset_backup_orchestrator() -> None:
    """测试/teardown 用。"""
    global _orchestrator
    with _orch_lock:
        _orchestrator = None


class RestoreRequest(BaseModel):
    zip_path: str
    trust: bool = False  # LEGACY 显式信任；FOREIGN 恒拒（orchestrator 语义）


def _safe_write_back(payload: Dict[str, Any]) -> Dict[str, int]:
    """apply_fn：按 `<前缀>/<相对路径>` 写回。Zip Slip 防护。"""
    written = 0
    skipped = 0
    sources: Dict[str, str] = getattr(get_backup_orchestrator(), "default_sources", {})
    for name, content in payload.get("files", {}).items():
        prefix, _, rel = name.partition("/")
        base = sources.get(prefix)
        if not base or not rel:
            skipped += 1
            continue
        base_p = Path(base).resolve()
        target = (base_p / rel).resolve()
        if base_p not in target.parents and target != base_p:
            skipped += 1  # Zip Slip：解析后越界
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    return {"written": written, "skipped": skipped}


@router.post("/create")
async def create_backup(admin: dict = Depends(require_admin())):
    orch = get_backup_orchestrator()
    sources = {k: Path(v) for k, v in orch.default_sources.items()}
    out = orch.create_backup(sources)
    return {"success": True, "data": {"zip_path": str(out), "created_by": admin.get("username")}, "message": "备份创建完成"}


@router.get("")
async def list_backups():
    work_dir = Path(get_backup_orchestrator().work_dir)
    items = [
        {"zip_path": str(p), "size": p.stat().st_size}
        for p in sorted(work_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    ]
    return {"success": True, "data": {"items": items}, "message": ""}


@router.post("/restore")
async def restore_backup(body: RestoreRequest):
    orch = get_backup_orchestrator()
    try:
        payload = orch.restore_backup(body.zip_path, _safe_write_back, trust=body.trust)
    except Exception as exc:
        from neurova.backup.orchestrator import TrustRequiredError

        if isinstance(exc, TrustRequiredError):
            raise HTTPException(status_code=409, detail=str(exc))
        raise HTTPException(status_code=400, detail=f"恢复失败: {exc}")
    return {
        "success": True,
        "data": {"mode": payload["mode"], "files": len(payload["files"]), "write_back": payload.get("write_back")},
        "message": "备份恢复完成",
    }
```

restore 的 `apply_fn` 挂回写统计需要在 orchestrator 里透出——orchestrator.restore_backup 的 payload 原样返回，改 `_safe_write_back` 为把统计写进 payload：

```python
def _safe_write_back(payload: Dict[str, Any]) -> Dict[str, int]:
    ...
    payload["write_back"] = {"written": written, "skipped": skipped}
    return stats
```

（apply_fn 收到 payload dict 引用，原地挂 `write_back` 键即可，无需改 orchestrator。）

- [ ] **Step 4: 注册路由**

`neurova/api/endpoints/__init__.py` 的 `endpoint_modules` 列表（`("neurova.api.endpoints.console", ...)` 行后）追加：

```python
        ("neurova.api.endpoints.backup_api", "/v1/backups", "Backup API"),
```

- [ ] **Step 5: 跑测试确认通过**

```bash
venv/Scripts/python.exe -m pytest tests/unit/api/test_backup_api.py -v
venv/Scripts/python.exe -m pytest tests/unit/backup/ -v
```
Expected: 新测试 4 用例 PASS；既有 backup 套件不回归

- [ ] **Step 6: Commit**

```bash
git add -f tests/unit/api/test_backup_api.py
git add neurova/api/endpoints/backup_api.py neurova/api/endpoints/__init__.py
git commit -m "feat(api): BackupOrchestrator admin 接线 — create/list/restore 三端点 + 信任门 409 语义"
```

---

## Task 4（P1-d）：README 拼写 + 根目录卫生

**Files:**
- Modify: `README.md:1402,1665`（bata1→beta1）
- Delete: 根目录未跟踪垃圾（实证清单见 Step 2；**逐个确认 untracked 再删，删错tracked文件是事故**）
- Modify: `.gitignore`（补漏规则防再生）

- [ ] **Step 1: 修 README 拼写**

```bash
grep -n "bata1" README.md   # 1402 与 1665 两处锚点
```
两处 `v1.0.0 bata1` → `v1.0.0 beta1`（含锚文本 `#v100-beta1-升级功能历史` 同步改）。

- [ ] **Step 2: 根目录垃圾清理（仅删 untracked，逐个 ls-files 校验）**

实证 untracked 可删（`git ls-files --error-unmatch` 已核）：
- 日志类：`_backend.log` `_backend_err.log` `_diag2_err.log` `_diag2_out.log` `_diag3_err.log` `_diag3_out.log` `_diag_chat.log` `_diag_chat2.log` `_tmp_server_err.log` `_tmp_server_out.log` `backend.log` `backend_err.log` `backend_live_output.log` `backend_output.log` `backend_stderr.log` `backend_stdout.log` `debug.log` `docker-build.log` `frontend_8100.log` `frontend_8100_err.log` `server_error.log` `server_test.log` `test_debt_full.log` `pytest_output.txt`
- 文本残片：`_r1.txt` `_r2.txt` `_em.txt` `_mp.txt` `_mp2.txt` `reachA_sse.txt` `webreach_sse2.txt` `yt_sse.txt` `yt2_sse.txt` `_cfg.json` `ai-news-2026-09-01.html`
- 二进制残片：`test_api_output.wav`（注意：此文件是 **tracked**，需 `git rm` 并确认无引用后删）
- 一次性脚本（先读内容确认无价值再删）：`evil.py` `chat.py` `weather_xuchang.py` `pdd_api.js` `pdd_docjs.js` `pdd_search.js` `AGENTS.md.bak`
- 临时目录（读一眼确认）：`tmp_test/` `tmp_workspace/` `backup_test_files/` `MagicMock/` `_i18n_scan/` `test_workspace/` `shots/` `temp/` `_w/`

**不删**（有主或疑似有主）：`code_patches/` `flow-kb-sdk/` `thought-retriever-src/` `audit-reports/` `other/`（执行时逐个 quick-look 再定，宁可留）。

- [ ] **Step 3: .gitignore 补漏**

`.gitignore` 追加：

```gitignore
# 根目录运行残片（2026-09 清理后防再生）
*_sse.txt
_r*.txt
_em.txt
_mp*.txt
_cfg.json
test_api_output.wav
```

- [ ] **Step 4: Commit**

```bash
git add README.md .gitignore
git rm --cached test_api_output.wav 2>/dev/null || true
git commit -m "chore(repo): README bata1→beta1 + 根目录运行残片清理 + gitignore 补漏"
```

---

## Task 5（P2-c）：JSON 日志注入 trace_id（logger↔trace 打通）

**Files:**
- Modify: `neurova/core/logger.py:56-77`（_JsonLogFormatter）
- Test: `tests/unit/core/test_json_log_trace_id.py`（新建）

设计：复用 `identity_context.py` 模式新增轻量 trace ContextVar（**不 import trace_recorder**——避免 logger→trace_recorder 循环依赖；trace_recorder 写入，logger 只读）。
- `neurova/core/trace_context.py` 新建：`_trace_id_var: ContextVar[str, None]` + set/get/clear 三函数（identity_context.py:15-32 同构）
- `trace_recorder.start_trace`（trace_recorder.py:71）成功建 trace 后 `set_trace_id(trace.trace_id)`；`end_trace`（:111）`clear_trace_id()`
- `_JsonLogFormatter.format` payload 加 `"trace_id": get_trace_id()`（None 时省略键）
- 文本格式器不动（本地开发无此需求，YAGNI）

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/core/test_json_log_trace_id.py
"""JSON 日志 trace_id 注入（logger↔trace_recorder 打通，P2-c）"""
import json
import logging


def test_json_log_contains_trace_id_when_set():
    from neurova.core.trace_context import set_trace_id, clear_trace_id
    from neurova.core.logger import _JsonLogFormatter

    token = set_trace_id("tr-123")
    try:
        record = logging.LogRecord("t", logging.INFO, "p", 1, "hello %s", ("x",), None)
        payload = json.loads(_JsonLogFormatter().format(record))
        assert payload["trace_id"] == "tr-123"
    finally:
        clear_trace_id()


def test_json_log_omits_trace_id_when_unset():
    from neurova.core.logger import _JsonLogFormatter

    record = logging.LogRecord("t", logging.INFO, "p", 1, "plain", None, None)
    payload = json.loads(_JsonLogFormatter().format(record))
    assert "trace_id" not in payload


def test_trace_recorder_sets_and_clears(tmp_path, monkeypatch):
    from neurova.core import trace_context
    from neurova.core.trace_recorder import TrajectoryRecorder

    monkeypatch.setattr(TrajectoryRecorder, "_load_saved_traces_index", lambda self: None)
    monkeypatch.setattr(TrajectoryRecorder, "_save_traces_index", lambda self: None)
    rec = TrajectoryRecorder()
    tid = rec.start_trace(session_id="s", agent_id="a", user_id="u")
    assert trace_context.get_trace_id() == tid
    rec.end_trace(tid)
    assert trace_context.get_trace_id() is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_json_log_trace_id.py -v
```
Expected: FAIL `No module named 'neurova.core.trace_context'`

- [ ] **Step 3: 实现 trace_context + logger 注入 + recorder 接线**

```python
# neurova/core/trace_context.py
"""请求级 trace_id ContextVar（对齐 identity_context 模式）。

logger 只读本模块——禁止反向 import trace_recorder（循环依赖）。
"""
from contextvars import ContextVar
from typing import Optional

_trace_id_var: ContextVar = ContextVar("neurova_trace_id", default=None)


def set_trace_id(trace_id: Optional[str]):
    return _trace_id_var.set(trace_id)


def get_trace_id() -> Optional[str]:
    return _trace_id_var.get()


def clear_trace_id() -> None:
    _trace_id_var.set(None)
```

`logger.py` 的 `_JsonLogFormatter.format` payload 构造后追加：

```python
        try:
            from neurova.core.trace_context import get_trace_id

            tid = get_trace_id()
            if tid:
                payload["trace_id"] = tid
        except Exception:
            pass  # trace 上下文不可用不阻塞日志
```

`trace_recorder.py`：`start_trace` 末尾（`self._active_traces[trace.trace_id] = trace` 后）加 `set_trace_id(trace.trace_id)`（顶部 `from neurova.core.trace_context import clear_trace_id, set_trace_id`）；`end_trace` 成功 pop 后加 `clear_trace_id()`。

- [ ] **Step 4: 跑测试确认通过 + trace 套件回归**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_json_log_trace_id.py tests/unit/core/ -k "trace" -v
```
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add -f tests/unit/core/test_json_log_trace_id.py
git add neurova/core/trace_context.py neurova/core/logger.py neurova/core/trace_recorder.py
git commit -m "feat(observability): JSON 日志注入 trace_id — trace_context ContextVar 打通 logger↔recorder"
```

---

## Task 6（P2-a）：SQLite 版本化迁移（PRAGMA user_version）

**Files:**
- Create: `neurova/core/db_migration.py`
- Modify: `neurova/core/connection_pool.py:66-75`（_create_connection 后挂钩，或在 get_connection 首次创建时调用）
- Test: `tests/unit/core/test_db_migration.py`（新建）

设计（轻量，对齐"最小改动"纪律）：
- 迁移注册表 `MIGRATIONS: list[tuple[int, str]]`——`(target_version, sql 或 callable)`；v0=空库基线
- `migrate(conn, db_label)`：读 `PRAGMA user_version`，按序执行未应用的迁移（每条包裹事务），写回 `PRAGMA user_version = N`
- 首个真实迁移先占位（v1：memories 表 IF NOT EXISTS 已有 schema.py 管，不重复——v1 迁移=空操作注释占位，确立机制）
- **接入点选择**：不在 connection_pool 全局挂（影响 28 个模块风险大），先只挂记忆持久库一条路径——`cognitive_storage_engine.py:252` WAL 开启处旁调 `migrate(conn, "memory")`。其余库渐进接入。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/core/test_db_migration.py
"""PRAGMA user_version 版本化迁移机制（P2-a）"""
import sqlite3

import pytest

from neurova.core.db_migration import migrate, register_migration


@pytest.fixture()
def fresh_conn(tmp_path):
    conn = sqlite3.connect(tmp_path / "m.db")
    yield conn
    conn.close()


def test_fresh_db_gets_baseline_version(fresh_conn):
    applied = migrate(fresh_conn, "test")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] >= 1
    assert isinstance(applied, list)


def test_migrations_run_in_order_once(fresh_conn):
    calls = []
    register_migration(101, lambda c: calls.append(101))
    register_migration(102, lambda c: calls.append(102))
    migrate(fresh_conn, "test-order")
    migrate(fresh_conn, "test-order")  # 第二次全跳过
    assert calls == [101, 102]
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] == 102


def test_failed_migration_rolls_back(fresh_conn):
    def boom(conn):
        conn.execute("CREATE TABLE t1(a)")
        raise RuntimeError("migration boom")

    register_migration(201, boom)
    with pytest.raises(RuntimeError):
        migrate(fresh_conn, "test-fail")
    assert fresh_conn.execute("PRAGMA user_version").fetchone()[0] < 201
    assert fresh_conn.execute("SELECT name FROM sqlite_master WHERE name='t1'").fetchone() is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_db_migration.py -v
```
Expected: FAIL `No module named 'neurova.core.db_migration'`

- [ ] **Step 3: 实现**

```python
# neurova/core/db_migration.py
# -*- coding: utf-8 -*-
"""SQLite 版本化迁移（PRAGMA user_version）。

替代"仅 IF NOT EXISTS"的无版本 schema 演进。规则：
- 版本号 int 严格递增，注册即排序；执行过的版本按 user_version 跳过
- 每条迁移独立事务：失败回滚并上抛（调用方决定启动失败/降级）
- 注册表模块级——迁移内容写死在本文件，不读外部 SQL（防注入/防漂移）
"""
import threading
from typing import Callable, List, Optional, Tuple, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MigrationStep = Tuple[int, Union[str, Callable]]
_MIGRATIONS: List[MigrationStep] = []
_lock = threading.RLock()


def register_migration(version: int, step: Union[str, Callable]) -> None:
    """注册迁移（版本号必须大于已注册最大版本，测试外勿乱序）。"""
    with _lock:
        _MIGRATIONS.append((version, step))
        _MIGRATIONS.sort(key=lambda t: t[0])


def migrate(conn, db_label: str = "db") -> List[int]:
    """执行未应用的迁移，返回本次应用的版本号列表。"""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    applied: List[int] = []
    with _lock:
        pending = [(v, s) for v, s in _MIGRATIONS if v > current]
    for version, step in pending:
        try:
            conn.execute("BEGIN")
            if isinstance(step, str):
                conn.executescript(step)
            else:
                step(conn)
            conn.execute(f"PRAGMA user_version = {int(version)}")
            conn.execute("COMMIT")
            applied.append(version)
            logger.info("迁移 %s: user_version → %d", db_label, version)
        except Exception:
            conn.execute("ROLLBACK")
            logger.error("迁移 %s 失败于 v%d（已回滚）", db_label, version)
            raise
    return applied
```

记忆库接入（`cognitive_storage_engine.py` WAL 行旁）：

```python
            try:
                from neurova.core.db_migration import migrate

                migrate(conn, "memory")
            except Exception as e:
                logger.warning("记忆库迁移失败（继续启动，schema 由 IF NOT EXISTS 兜底）: %s", e)
```

v1 占位（db_migration.py 尾部）：

```python
# v1：基线占位——既有表结构由 memory_layer/schema.py IF NOT EXISTS 管理，
# 本条仅确立版本起点，后续 schema 变更加 2/3/... 注册即可。
register_migration(1, "SELECT 1")
```

- [ ] **Step 4: 跑测试 + 记忆套件回归**

```bash
venv/Scripts/python.exe -m pytest tests/unit/core/test_db_migration.py -v
venv/Scripts/python.exe -m pytest tests/unit/memory/ -x -q
```
Expected: 迁移 3 用例 PASS；memory 套件无新增失败（对照预存基线 2 tie）

- [ ] **Step 5: Commit**

```bash
git add -f tests/unit/core/test_db_migration.py
git add neurova/core/db_migration.py neurova/cognitive_layers/memory_layer/cognitive_storage_engine.py
git commit -m "feat(db): PRAGMA user_version 版本化迁移 — 机制确立+记忆库首接"
```

---

## Task 7（P2-b）：CONTRIBUTING.md + SECURITY.md

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`

内容大纲（不写占位，直接成文）：
- CONTRIBUTING：快速开始（引 AGENTS.md 四命令）+ 分支/提交规约（conventional commits，仓库已有实践）+ 测试纪律（tests/unit|integration|e2e 结构、`git add -f` 规则、vitest 覆盖率阈值 30）+ i18n 11 语言 parity 守卫流程 + 深模块设计规则（agent_ref DI/单例工厂/懒导入，引 AGENTS.md）
- SECURITY：支持版本（1.0.0-beta1）+ 报告渠道（GitHub Security Advisory）+ 已知安全架构要点（治理三阶段/沙箱/AppContainer/url_guard/审批记忆——引 docs 编号分层）+ 密钥管理（.env/.env.example、nvk_ Token）

- [ ] **Step 1: 写两份文档**（按上述大纲，内容从 AGENTS.md/docs 提炼，禁止空节）
- [ ] **Step 2: 校验内链**（docs 路径用 `ls` 逐一确认存在）
- [ ] **Step 3: Commit**

```bash
git add CONTRIBUTING.md SECURITY.md
git commit -m "docs: CONTRIBUTING + SECURITY 补齐 — DX 补课 P2-b"
```

---

## Task 8（P3-b 修订）：温度渐进索引验证测试（v4 文档结论修正）

**Files:**
- Test: `tests/unit/memory/test_moe_background_index.py`（新建）
- Modify: `docs/Neurova_QwenPaw全方位对比_v4_2026-09-01.md`（§5/§12 P3-b 行加勘误注记）

- [ ] **Step 1: 写行为测试**（锁定既有实现，防未来回归）

```python
# tests/unit/memory/test_moe_background_index.py
"""MoE 后台渐进索引行为锁定（v4 对比文档误判"未实现"，实测已实现于 mem_core.py:285）"""
from unittest.mock import MagicMock

from neurova.mem_core import _background_index_memories, _moe_index_completed, _save_moe_index_state


class _FakeStore:
    """模拟 index_memories 去重语义：同 id 只进一次。"""

    def __init__(self):
        self.ids = []

    def index_memories(self, items, incremental=False):
        before = len(self.ids)
        for m in items:
            if m["id"] not in self.ids:
                self.ids.append(m["id"])
        return len(self.ids) - before


def test_background_index_respects_budget():
    store = _FakeStore()
    rows = [{"id": f"m{i}", "content": f"c{i}", "category": "general", "lifecycle_stage": "active"} for i in range(100)]

    def fetch_page(offset, size):
        return rows[offset:offset + size]

    added = _background_index_memories(store, fetch_page, index_limit=30, batch_size=20, batch_delay=0)
    assert added == 30
    assert len(store.ids) == 30


def test_background_index_stops_on_stale_cursor():
    store = _FakeStore()

    def fetch_page(offset, size):  # 恒返回同一批 → 游标无进展
        return [{"id": "same", "content": "c", "category": "g", "lifecycle_stage": "a"}]

    added = _background_index_memories(store, fetch_page, index_limit=100, batch_delay=0)
    assert added == 1  # 游标守卫提前终止，不死循环


def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("neurova.mem_core._moe_index_state_path", lambda scope: tmp_path / "st.json")
    store = _FakeStore()
    _save_moe_index_state(500, store, "scope")
    store.ids = [f"x{i}" for i in range(500)]
    assert _moe_index_completed(500, "scope") is True
    assert _moe_index_completed(1000, "scope") is False  # limit 变更不跳过
```

- [ ] **Step 2: 跑测试确认通过（锁定既有行为）**

```bash
venv/Scripts/python.exe -m pytest tests/unit/memory/test_moe_background_index.py -v
```
Expected: 3 PASS（若 FAIL，读实现修正测试对齐真实语义——本测试是行为锁定不是先红后绿）

- [ ] **Step 3: v4 文档勘误（✅ 已完成——09-02 两篇对比合并为一份文档时写入，本步跳过）**

勘误已落在 `docs/Neurova_QwenPaw全方位对比_v4_2026-09-01.md` §5 数据层段与 §11 评分表数据层行（NV 5→5.5）；P3-b 补课行见该文档 §19 合并补课清单。本 Task 仅剩 Step 1/2 的行为锁定测试与 Step 4 提交。

- [ ] **Step 4: Commit**

```bash
git add -f tests/unit/memory/test_moe_background_index.py
git add docs/Neurova_QwenPaw全方位对比_v4_2026-09-01.md
git commit -m "test(memory): MoE 后台渐进索引行为锁定 + v4 对比文档勘误（已实现非未实现）"
```

---

## Task 9（P3-c）：telegram inline_keyboard（独立切片，可后置）

**Files:**
- Modify: `neurova/channels/telegram_sender.py`（_send_text_message 旁加 keyboard 支持）
- Modify: `neurova/channels/models.py:56-74`（UnifiedMessage.metadata 约定，不加新字段）
- Test: `tests/unit/channels/test_telegram_inline_keyboard.py`（新建）

设计：不扩 UnifiedMessage 字段（YAGNI）——发消息方把 `reply_markup` dict 放 `message.metadata["reply_markup"]`，sender mixin 在 payload 组装时透传。Telegram Bot API 的 inline_keyboard 是纯 dict 结构，透传即可。

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/channels/test_telegram_inline_keyboard.py
"""telegram inline_keyboard 透传（metadata["reply_markup"] 约定，P3-c）"""
from unittest.mock import MagicMock, patch

from neurova.channels.models import ContentType, UnifiedMessage


def _msg(**meta):
    return UnifiedMessage(
        content_type=ContentType.TEXT,
        content="hello",
        chat_id="123",
        metadata=meta or None,
    )


def test_reply_markup_passthrough():
    from neurova.channels.telegram_sender import TelegramSenderMixin

    adapter = TelegramSenderMixin()
    adapter._ensure_initialized = MagicMock(return_value=True)
    adapter.show_typing = False
    captured = {}

    def fake_api(method, path, **kwargs):
        captured.update(kwargs.get("json") or {})
        return {"ok": True}

    adapter._api_request = fake_api

    markup = {"inline_keyboard": [[{"text": "点我", "callback_data": "cb:1"}]]}
    assert adapter.send_message(_msg(reply_markup=markup)) is True
    assert captured["reply_markup"] == markup


def test_no_markup_omits_field():
    from neurova.channels.telegram_sender import TelegramSenderMixin

    adapter = TelegramSenderMixin()
    adapter._ensure_initialized = MagicMock(return_value=True)
    adapter.show_typing = False
    captured = {}

    def fake_api(method, path, **kwargs):
        captured.update(kwargs.get("json") or {})
        return {"ok": True}

    adapter._api_request = fake_api
    assert adapter.send_message(_msg()) is True
    assert "reply_markup" not in captured
```

- [ ] **Step 2: 跑测试确认失败**

```bash
venv/Scripts/python.exe -m pytest tests/unit/channels/test_telegram_inline_keyboard.py -v
```
Expected: FAIL `reply_markup` not in captured

- [ ] **Step 3: 实现（telegram_sender._send_text_message payload 组装处）**

```python
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        # inline_keyboard 透传（metadata["reply_markup"] 约定，Bot API 原生 dict）
        reply_markup = (getattr(self, "_current_metadata", None) or {}).get("reply_markup")
        if reply_markup:
            payload["reply_markup"] = reply_markup
```

send_message 入口处挂 `_current_metadata`（实例临时态，发送后清理）：

```python
        self._current_metadata = message.metadata
        try:
            ...  # 原有分派
        finally:
            self._current_metadata = None
```

- [ ] **Step 4: 跑测试 + telegram 套件回归**

```bash
venv/Scripts/python.exe -m pytest tests/unit/channels/test_telegram_inline_keyboard.py tests/unit/channels/test_telegram_split.py -v
```
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add -f tests/unit/channels/test_telegram_inline_keyboard.py
git add neurova/channels/telegram_sender.py
git commit -m "feat(channels): telegram inline_keyboard 透传 — metadata reply_markup 约定"
```

---

## 任务依赖与执行顺序

```
Task 1 (compose)      ── 独立，5 分钟
Task 2 (health)       ── 独立，TDD
Task 3 (backup API)   ── 独立，最大项（建议单独会话/子代理）
Task 4 (repo hygiene) ── 独立，删除类操作需人工过目清单
Task 5 (trace_id log) ── 独立，TDD
Task 6 (migration)    ── 独立，TDD
Task 7 (docs)         ── 独立
Task 8 (MoE 勘误)     ── 独立，先行做（修正认知）
Task 9 (telegram)     ── 独立，可后置
```

无相互依赖，可任意顺序/并行。推荐批：**第一批**（认知修正+速赢）Task 8 → 1 → 2 → 4；**第二批** Task 5 → 6 → 3；**第三批** Task 7 → 9。

## 自审记录

- 覆盖检查：v4 文档 §12 清单 10 项 → P1-a=Task 3、P1-b=Task 1、P1-c=Task 2、P1-d=Task 4、P2-a=Task 6、P2-b=Task 7、P2-c=Task 5、P3-a（Tauri 桌面）**不入本计划**（v4 文档已定性"唯一大工程，排最后"，需独立立项）、P3-b=Task 8（勘误后改口）、P3-c=Task 9。全部有着落。
- 类型一致性：Task 3 测试用 `get_current_user` override + env 注入隔离，与实现的 `os.environ` 读取一致；Task 6 的 `register_migration(version, step)` 签名在测试与实现间一致。
- 占位扫描：无 TBD/TODO；Task 3 的 apply_fn 双形态已在正文收敛为"原地挂 write_back 键"一种。
- 风险点已标注：Task 3 restore 对 SQLite 在线文件不一致的诚实边界、Task 6 接入面刻意收窄到记忆库一条路径、Task 4 删除清单要求执行时逐个复核。
