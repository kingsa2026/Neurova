"""红灯④：「写了没人读」的断点必须接线或删除（协作红线第 4 条）。

`history.latency_stats()` 后端算了按模型 p50/p95/max 并存进
usage-overview 的 `latency_stats` 字段，但前端类型与页面都不认它——
全仓 `grep latency_stats NeurUI/src` 为空。于是这段计算每次请求都白跑，
报表在契约里悬空。
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_SRC = REPO_ROOT / "NeurUI" / "src"


def test_latency_stats_has_a_frontend_consumer():
    """契约里有的字段必须有人读，否则它就不该在契约里。"""
    hits = [p for p in FRONTEND_SRC.rglob("*.ts") if "latency_stats" in p.read_text(encoding="utf-8")]
    hits += [p for p in FRONTEND_SRC.rglob("*.vue") if "latency_stats" in p.read_text(encoding="utf-8")]
    assert hits, (
        "usage-overview 契约声明了 latency_stats，前端却零消费——"
        "要么接线到使用统计页，要么从契约里删掉并停止计算"
    )
