"""§6-4 观测面持久化 — 红灯先行的契约测试(2026-10-06)。

旧契约自认"存储是进程内的……不承担持久化职责"(result_summary.py 模块
文档)——重启后响应面摘要为空、规范指标无时序留痕。本文件钉住新契约:

- 摘要随 record 落 jsonl,attach 时按 (agent, session) 恢复最新一条;
- 规范指标快照随迭代追加进同一审计流(时序留痕);
- 落盘失败不影响内存读数(观测面故障不阻断进化);
- 文件有界(attach 时压实),防长进程无界增长;
- 未挂载零 IO(与 PersistedStateMixin 同约定)。
"""

import json

import pytest

from neurova.evolution.rsi import result_summary as rs


@pytest.fixture(autouse=True)
def _isolated():
    rs.clear_rsi_summaries()
    rs.detach_persistence()
    yield
    rs.clear_rsi_summaries()
    rs.detach_persistence()


def _result(**over):
    base = {
        "convergence": {"status": "converged"},
        "applied_count": 1,
        "gain": 0.02,
        "phase_advanced": False,
    }
    base.update(over)
    return base


class TestSummaryPersistence:
    def test_record_appends_jsonl(self, tmp_path):
        path = tmp_path / "rsi_summaries.jsonl"
        assert rs.attach_persistence(path) is True
        rs.record_rsi_summary("agent-a", "sess-1", _result(), turn=7)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["agent_id"] == "agent-a"
        assert record["session_id"] == "sess-1"
        assert record["turn"] == 7
        assert record["summary"]["applied_count"] == 1

    def test_summary_survives_reattach(self, tmp_path):
        """重启模拟:内存清空 + 重新挂载同一文件 → 摘要按 (agent, session) 恢复。"""
        path = tmp_path / "rsi_summaries.jsonl"
        rs.attach_persistence(path)
        rs.record_rsi_summary("agent-a", "sess-1", _result(), turn=7)
        rs.record_rsi_summary("agent-a", "sess-2", _result(gain=0.05), turn=8)

        rs.clear_rsi_summaries()
        assert rs.get_latest_rsi_summary("agent-a", "sess-1") is None

        rs.attach_persistence(path)
        restored = rs.get_latest_rsi_summary("agent-a", "sess-1")
        assert restored is not None
        assert restored["turn"] == 7
        assert restored["applied_count"] == 1
        other = rs.get_latest_rsi_summary("agent-a", "sess-2")
        assert other is not None and other["turn"] == 8

    def test_latest_wins_on_repeated_records(self, tmp_path):
        path = tmp_path / "rsi_summaries.jsonl"
        rs.attach_persistence(path)
        rs.record_rsi_summary("a", "s", _result(gain=0.01), turn=1)
        rs.record_rsi_summary("a", "s", _result(gain=0.02), turn=2)
        rs.clear_rsi_summaries()
        rs.attach_persistence(path)
        assert rs.get_latest_rsi_summary("a", "s")["turn"] == 2

    def test_persistence_failure_is_soft(self, tmp_path):
        """落盘不可用(路径是目录)→ 内存读数照常返回,不抛不吞摘要。"""
        rs.attach_persistence(tmp_path)
        summary = rs.record_rsi_summary("a", "s", _result(), turn=1)
        assert summary is not None
        assert rs.get_latest_rsi_summary("a", "s")["turn"] == 1

    def test_compaction_bounds_file(self, tmp_path):
        """attach 对超长历史压实(有界),防长进程无界增长。"""
        path = tmp_path / "rsi_summaries.jsonl"
        junk = [
            {"agent_id": "x", "session_id": f"s{i}", "turn": i,
             "summary": {"status": "converged"}}
            for i in range(3000)
        ]
        path.write_text(
            "\n".join(json.dumps(j) for j in junk), encoding="utf-8")
        rs.attach_persistence(path)
        line_count = len(path.read_text(encoding="utf-8").strip().splitlines())
        assert line_count <= 2000


class TestMetricsSnapshot:
    def test_snapshot_appends_to_stream(self, tmp_path):
        path = tmp_path / "rsi_summaries.jsonl"
        rs.attach_persistence(path)
        assert rs.record_metrics_snapshot({"rsi_cycles_total": 3}, agent_id="agent-a") is True
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "metrics"
        assert record["agent_id"] == "agent-a"
        assert record["metrics"]["rsi_cycles_total"] == 3

    def test_snapshot_without_persistence_is_noop(self):
        """未挂载零 IO:不落盘、不抛(与 PersistedStateMixin 同约定)。"""
        assert rs.record_metrics_snapshot({"k": 1}, agent_id="a") is False

    def test_orchestrator_persists_snapshot_each_iteration(
            self, rsi_probe_factory, tmp_path, monkeypatch):
        """每轮迭代把规范指标快照写进审计流(时序留痕)。"""
        path = tmp_path / "rsi_summaries.jsonl"
        monkeypatch.setenv("NEUROVA_EVOLUTION_RSI_SUMMARIES", str(path))
        rs.attach_persistence()
        probe = rsi_probe_factory(rsi_phase=0)
        probe.run(1)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert lines, "指标快照未落盘"
        assert any(json.loads(l).get("type") == "metrics" for l in lines)


class TestSummariesLandingAnchor:
    """审计流落点必须由数据根推导——env 值与兜底名都不得直接进 `Path`。

    原写法 `Path(os.environ.get(ENV, get_data_root() / ...))` 有两个洞：
    env 被设成**空串**时 `get` 返回 `""` 而不走默认值，`Path("")` 即进程 CWD；
    env 被设成**相对名**时落点跟着启动目录漂（§6-26/§6-29 同一根因）。
    """

    def test_unsetEnvLandsUnderDataRoot(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_EVOLUTION_RSI_SUMMARIES", raising=False)
        monkeypatch.chdir(tmp_path)          # 换 CWD 证明不漂
        from neurova.core.data_root import get_data_root
        target = rs.default_rsi_summaries_path()
        assert target == get_data_root() / "evolution" / "rsi_summaries.jsonl", target
        assert target.is_absolute(), target

    def test_emptyEnvDoesNotFallBackToProcessCwd(self, monkeypatch):
        """`os.environ.get(K, default)` 遇空串返回 ""，`Path("")` 就是进程 CWD。"""
        monkeypatch.setenv("NEUROVA_EVOLUTION_RSI_SUMMARIES", "")
        target = rs.default_rsi_summaries_path()
        assert target != type(target)("."), "空串 env 让审计流落到进程 CWD：%s" % target
        assert target.is_absolute() and str(target) != ".", target

    def test_relativeEnvLandsUnderDataRootNotCwd(self, tmp_path, monkeypatch):
        """相对值归数据根：运维写相对名不意味着"跟着启动目录漂"。"""
        monkeypatch.setenv("NEUROVA_EVOLUTION_RSI_SUMMARIES", "rsi_custom.jsonl")
        monkeypatch.chdir(tmp_path)
        target = rs.default_rsi_summaries_path()
        assert target.is_absolute(), "env 相对值未经数据根归一：%s" % target
        assert tmp_path not in target.parents and target.parent != tmp_path, target
        assert target.name == "rsi_custom.jsonl", target

    def test_absoluteEnvIsHonoredVerbatim(self, tmp_path, monkeypatch):
        """显式绝对路径（测试隔离与部署重定位都用它）必须原样生效。"""
        wanted = tmp_path / "elsewhere" / "stream.jsonl"
        monkeypatch.setenv("NEUROVA_EVOLUTION_RSI_SUMMARIES", str(wanted))
        assert rs.default_rsi_summaries_path() == wanted
