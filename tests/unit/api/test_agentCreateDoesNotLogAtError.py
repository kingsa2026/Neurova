"""成功路径不得记 ERROR 级日志（§6-151 顺带发现的缺陷，任务 #38）。

实况一枚：`api/endpoints/neurflow_api.py` 的 `POST /agents` 在校验通过之后、创建之前写着
`logger.error("DEBUG: name=%s, role=%s, manager=%s", ...)`——每次建 Agent 都记一条 ERROR 级
调试行。它不是"日志太吵"这么轻：错误日志面（`core/error_logger` 与告警读判据）按级别取数，
一条从不失败的调试行挂在 ERROR 上，就会把"这条链路真出过事"的读数永久泡脏。

判据两面：
- 行为面（真端点真请求）：一次成功创建必须回 201 且**不产生任何 ERROR 及以上的记录**。
  取数走生产 logger 自己的 handler 链（挂一只临时收集 handler），不 monkeypatch 调用点，
  也不依赖 propagate（`get_logger()` 造的记录器是否向祖先传播不由本档假设）。
- 防再生面（AST）：全仓生产包内不得有"ERROR 级却承载调试内容"的日志调用。按 AST 形态判，
  不用文本正则——正则会同时造出假红（注释里的 DEBUG 字样）与放过（换一行的调用）。
"""

import ast
import logging
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import ast_scan as _astScan

REPO = pathlib.Path(__file__).resolve().parents[3]
PKG = REPO / "neurova"
PREFIX = "/api/v1/neurflow"
DEBUG_MARKERS = ("DEBUG", "debug:", "调试", "TEST:", "TODO", "FIXME", "临时")


class _Collector(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture()
def agentsApi():
    from neurova.api.endpoints import neurflow_api as NF
    from neurova.collaboration.neurflow.agent_manager import reset_agent_manager

    reset_agent_manager()
    app = FastAPI()
    app.include_router(NF.router, prefix=PREFIX)

    collector = _Collector()
    NF.logger.addHandler(collector)
    priorLevel = NF.logger.level
    NF.logger.setLevel(logging.DEBUG)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, collector
    finally:
        NF.logger.removeHandler(collector)
        NF.logger.setLevel(priorLevel)
        reset_agent_manager()


class TestAgentCreateLoggingHonesty:
    def test_successfulCreateEmitsNoErrorRecord(self, agentsApi):
        client, collector = agentsApi
        resp = client.post(f"{PREFIX}/agents", json={"name": "编码助手", "role": "coder"})
        assert resp.status_code == 201, resp.text

        loud = [
            r for r in collector.records
            if r.levelno >= logging.ERROR
        ]
        assert loud == [], "成功创建 Agent 却记了 ERROR 级日志：" + "; ".join(
            f"{r.levelname}:{r.getMessage()[:120]}" for r in loud
        )

    def test_rejectedCreateStaysHonestFourHundred(self, agentsApi):
        """缺必填字段：诚实 400 + 不写 ERROR（拒绝请求不是故障）。"""
        client, collector = agentsApi
        resp = client.post(f"{PREFIX}/agents", json={"name": "缺角色"})
        assert resp.status_code == 400, resp.text
        assert [r for r in collector.records if r.levelno >= logging.ERROR] == []


class TestNoErrorLevelDebugAnywhere:
    def test_productionPackagesHaveNone(self):
        """取数走共享解析预算 `tests/ast_scan`。

        私有 `rglob + ast.parse` 会把"解析量"绑成"代码总量"（Issue #148），
        与其余受保护文件共享机器时撞 30s 墙钟。本格只扫一遍且不跨用例复用，
        故走**一次性**入口 `transientNodes`（不留常驻节点表）。文本预筛词是
        判据的**充分条件**：`_errorLevelDebugHits` 只认首参为字符串常量的
        `error/exception/critical` 调用，而这类调用的首参必然落在
        `DEBUG_MARKERS` 里——连这些词都没出现的文件不可能命中。
        """
        hits = []
        for path, node in _astScan.transientNodes(PKG, hints=DEBUG_MARKERS):
            for line in _errorLevelDebugHits(node):
                hits.append(f"{path.relative_to(REPO).as_posix()}:{line}")
        hits = sorted(set(hits))
        assert hits == [], f"ERROR 级承载调试内容的日志调用仍在位：{hits}"

    def test_detectorItselfIsNotBlind(self):
        """反向对照：探测器不是恒绿——同一棵 AST 上换个级别就必须不命中。"""
        loud = ast.parse('logger.error("DEBUG: x=%s", x)')
        quiet = ast.parse('logger.debug("DEBUG: x=%s", x)')
        assert _errorLevelDebugHits(loud) == [1]
        assert _errorLevelDebugHits(quiet) == []


def _errorLevelDebugHits(tree: ast.Module) -> list[int]:
    """按与主判据同一式子取命中行号——供反向对照格自证探测器有牙。"""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in ("error", "exception", "critical")):
            continue
        head = node.args[0]
        if not (isinstance(head, ast.Constant) and isinstance(head.value, str)):
            continue
        text = head.value.strip()
        if text.startswith(DEBUG_MARKERS) or "DEBUG:" in text:
            hits.append(node.lineno)
    return hits
