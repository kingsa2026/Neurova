"""P1-5：`POST /api/v1/frontend/errors` 必须真落盘、状态与事实一致（红→绿）

修复前实测缺陷：
- 端点只 `logger.warning(...)` 就回 `{"status": "logged"}`，**从不调**
  `neurova/error_logger.write_frontend_errors`（那才是既有的 JSONL sink，且自带读/清/统计
  与 `tests/unit/core/test_error_logger.py` 覆盖，但生产零调用方）——客户端被告知"已记录"，
  实际什么都没存；
- 解析失败走 `except Exception` 分支，回 **200** 且把 `str(e)` 原样吐给这个**免鉴权**端点
  的调用方（内部异常文本外泄，且状态码说谎）；
- 载荷无任何上限：免鉴权 + 白名单 = 任何人可无限堆这个 JSONL 文件。

不做的事：不在端点里再造一套限流。全链路唯一的额度执行点是
`RateLimitMiddleware`（`api/middleware.py:279` 全局装载，匿名请求按 client IP 记额，
`_quotaKey`），本端点已在它覆盖范围内——活体里用连打验证。
"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import neurova.error_logger as errLog
from neurova.api.app import _register_frontend_error_log

ROUTE = "/api/v1/frontend/errors"


def _client(tmp_path, monkeypatch):
    """sink 落点指到本用例目录：不借仓内 data/，也不受模块常量的导入期绑定影响。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    app = FastAPI()
    _register_frontend_error_log(app)  # 生产注册函数本身，不是复刻
    return TestClient(app)


def _written(tmp_path):
    path = tmp_path / "error_logs" / "all_errors.log"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def testWellFormedErrorIsActuallyPersisted(tmp_path, monkeypatch):
    """回 'logged' 之前必须真的写进 sink。"""
    client = _client(tmp_path, monkeypatch)

    resp = client.post(ROUTE, json={"type": "js", "message": "boom", "url": "/chat"})

    assert resp.status_code == 200, resp.text
    rows = _written(tmp_path)
    assert len(rows) == 1, f"自称已记录，盘上却有 {len(rows)} 条：{rows}"
    assert rows[0]["message"] == "boom"
    assert rows[0]["source"] == "frontend"


def testMalformedBodyIsRejectedNotSwallowed(tmp_path, monkeypatch):
    """坏请求体是客户端错误：400，而不是 200 带一句 'error'。"""
    client = _client(tmp_path, monkeypatch)

    resp = client.post(ROUTE, content=b"not json at all",
                       headers={"Content-Type": "application/json"})

    assert resp.status_code == 400, f"{resp.status_code} {resp.text}"
    assert _written(tmp_path) == []


def testInternalFailureDoesNotEchoDetailToAnonymousCaller(tmp_path, monkeypatch):
    """sink 写失败要 500 点名，但不能把内部异常文本交给免鉴权调用方。"""
    client = _client(tmp_path, monkeypatch)

    def _boom(*args, **kwargs):
        raise RuntimeError("traceback-ish /E:/项目/Neurova/data/... internal path")

    monkeypatch.setattr(errLog, "write_frontend_errors", _boom)
    resp = client.post(ROUTE, json={"message": "x"})

    assert resp.status_code == 500, f"{resp.status_code} {resp.text}"
    assert "internal path" not in resp.text, "把内部异常原样回给匿名调用方 = 信息外泄"


def testPayloadLimitsEnforced(tmp_path, monkeypatch):
    """免鉴权写盘面必须有上限：单条字段长度与整批条数，超限拒收且不落盘。"""
    client = _client(tmp_path, monkeypatch)

    huge = client.post(ROUTE, json={"message": "M" * 200000, "stack": "S" * 200000})
    assert huge.status_code in (413, 422), f"超大载荷被照收：{huge.status_code}"

    many = client.post(ROUTE, json=[{"message": f"e{i}"} for i in range(500)])
    assert many.status_code in (413, 422), f"整批条数不设限：{many.status_code}"

    assert _written(tmp_path) == [], "被拒的载荷仍落了盘"


def testSinkLandingResolvesPerCall(tmp_path, monkeypatch):
    """sink 目录不得在导入期定死：换数据根要跟着换（否则换启动目录就换一份日志）。

    本用例全程只设 `NEUROVA_DATA_DIR`（不改 `log_dir` 参数），写不进 tmp 就是
    导入期绑定还留着——判据因此不会恒真。
    """
    client = _client(tmp_path, monkeypatch)
    resp = client.post(ROUTE, json={"message": "after env change"})

    assert resp.status_code == 200, resp.text
    assert _written(tmp_path), "NEUROVA_DATA_DIR 换了落点却没跟着换——日志仍写在旧目录"
