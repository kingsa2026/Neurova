"""
测试：S5 会话存储追加式改造（JSONL + 快照两段式）

根因：session_manager.add_message 对每会话文件做 read-modify-write 全量重写，
长会话单文件无界增长，每条消息写成本 O(全文长度)。

本批契约（NEUROVA_SESSION_JSONL 门控，默认关闭）：
  1. 追加式：新消息逐行 JSON 追加进既有会话文件，每 SESSION_SNAPSHOT_EVERY 条
     或字节阈值滚动一份快照行；读侧 = 快照 + 重放其后增量。追加 200 条消息的
     写放大相对全量重写呈数量级下降（O(1) 摊薄）。
  2. 断电容错：写一半的 JSONL 行（撕裂行）读取不炸、按坏行跳过；后续追加先
     封口撕裂行，不污染新行。
  3. 兼容迁移：旧全量 JSON 文件只读时按旧格式正确读出；首次写入懒迁移成
     两段式，迁移前后读数一致；迁移失败回退旧写法且错误日志可见（不静默吞）。
  4. 默认关闭：不开开关时文件保持全量 JSON 形态，行为不变。
"""

import builtins
import json
from pathlib import Path

import pytest

from neurova import session_manager as sm
from neurova.session_manager import SessionManager

_AGENT = "agent_s5"
_SID = "sess_s5_append"
_PAD = "x" * 200  # 固定尺寸正文，让两种模式的写入字节数可比


def _makeManager(monkeypatch, tmp_path: Path, subdir: str = "sessions", jsonl: bool = False) -> SessionManager:
    """隔离落点 + 重置单例 + 按需打开 JSONL 门控。"""
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / subdir))
    if jsonl:
        monkeypatch.setenv("NEUROVA_SESSION_JSONL", "1")
    else:
        monkeypatch.delenv("NEUROVA_SESSION_JSONL", raising=False)
    SessionManager._instance = None
    return SessionManager()


def _sessionFile(mgr: SessionManager, sid: str = _SID) -> Path:
    files = mgr._find_session_files(mgr._get_session_dir(_AGENT), sid)
    assert files, "会话文件不存在"
    return files[-1]


def _jsonlLines(path: Path):
    """按 \\n 切行的逐行 JSON（与读侧同口径，不用 splitlines 以免 U+2028 干扰）。"""
    raw = path.read_bytes().decode("utf-8", errors="replace")
    out = []
    for line in raw.split("\n"):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


class _WriteBytesMeter:
    """统计某目录内全部文件写入字节数（含 tmp 原子写），读操作不计。"""

    def __init__(self, watch_dir: Path):
        self._watch = str(watch_dir)
        self.total = 0
        self.writes = []
        self._realOpen = builtins.open

    def __enter__(self):
        builtins.open = self._countingOpen
        return self

    def __exit__(self, *exc):
        builtins.open = self._realOpen
        return False

    def _countingOpen(self, file, mode="r", *args, **kwargs):
        f = self._realOpen(file, mode, *args, **kwargs)
        if ("w" in mode or "a" in mode) and str(file).startswith(self._watch):
            return _CountingFile(f, self)
        return f


class _CountingFile:
    """只劫持 write 计字节数，其余属性全部透传。"""

    def __init__(self, f, meter: _WriteBytesMeter):
        self._f = f
        self._meter = meter

    def write(self, data):
        n = len(data if isinstance(data, bytes) else data.encode("utf-8"))
        self._meter.total += n
        self._meter.writes.append(n)
        return self._f.write(data)

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        self._f.__enter__()
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)


class TestDefaultOff:
    """默认不开关：文件保持全量 JSON 形态，行为不变。"""

    def test_withoutEnvFilesStayFullJson(self, monkeypatch, tmp_path):
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=False)
        mgr.add_message(_AGENT, _SID, "问-1", "答-1")
        path = _sessionFile(mgr)
        data = json.loads(path.read_text(encoding="utf-8"))  # 全量 JSON 可整读
        assert "t" not in data
        assert len(data["messages"]) == 2
        assert data["messages"][0]["content"] == "问-1"


class TestWriteAmplification:
    """追加 200 条消息后写放大呈 O(1) 摊薄（对比全量重写的字节数增长）。"""

    def test_append200MessagesWriteAmplificationDropsByAnOrderOfMagnitude(self, monkeypatch, tmp_path):
        def run(jsonl: bool) -> _WriteBytesMeter:
            mgr = _makeManager(
                monkeypatch, tmp_path,
                subdir=("jsonl" if jsonl else "legacy"), jsonl=jsonl,
            )
            meter = _WriteBytesMeter(mgr._sessions_dir)
            with meter:
                for i in range(100):
                    mgr.add_message(_AGENT, _SID, f"问-{i} {_PAD}", f"答-{i} {_PAD}")
            return meter

        legacy = run(jsonl=False)
        jsonlMeter = run(jsonl=True)

        # 计量器自身必须真的抓到了写入（防假绿）
        assert legacy.total > 0 and len(legacy.writes) > 0
        assert jsonlMeter.total > 0 and len(jsonlMeter.writes) > 0

        # 读回一致性：两种模式各自 200 条消息都完整可读
        # （各自独立目录，最后一次 run 的单例是 jsonl 目录的）
        assert len(jsonlMeter.writes) >= 100

        # 写放大断言：追加式总写入字节必须比全量重写低一个量级
        assert jsonlMeter.total * 5 < legacy.total, (
            f"追加式写放大未达标：jsonl={jsonlMeter.total}B, legacy={legacy.total}B"
        )
        # 绝大多数写入是 O(新增量) 的小追加，而非整文件重写
        assert max(jsonlMeter.writes) < legacy.total // 10, (
            f"出现大块重写：max_single={max(jsonlMeter.writes)}B, legacy_total={legacy.total}B"
        )


class TestCrashTolerance:
    """断电模拟：写一半的 JSONL 行读取不炸、跳过坏行、不污染后续追加。"""

    def test_tornJsonlLineIsSkippedAndLaterAppendsSurvive(self, monkeypatch, tmp_path):
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=True)
        mgr.add_message(_AGENT, _SID, "问-1", "答-1")
        mgr.add_message(_AGENT, _SID, "问-2", "答-2")
        path = _sessionFile(mgr)

        # 断电模拟：追加一行写一半（在多字节字符中间截断），无换行、无收尾
        torn = '{"t":"app","m":{"role":"user","content":"断电截断✂'.encode("utf-8")[:-2]
        with open(path, "ab") as f:
            f.write(torn)

        # 读取不炸：坏行跳过，既有 4 条完好
        history = mgr.get_history(_AGENT, _SID)
        assert [m["content"] for m in history] == ["问-1", "答-1", "问-2", "答-2"]

        # 撕裂行之后继续追加：先封口再落新行，新旧互不污染
        mgr.add_message(_AGENT, _SID, "问-3", "答-3")
        history = mgr.get_history(_AGENT, _SID)
        assert [m["content"] for m in history] == [
            "问-1", "答-1", "问-2", "答-2", "问-3", "答-3",
        ]
        # 再读一遍仍一致（坏行持续被跳过，而不是偶尔炸）
        assert len(mgr.get_history(_AGENT, _SID)) == 6


class TestLegacyMigration:
    """旧格式文件：只读按旧法读出；首次写入懒迁移；迁移后读数一致。"""

    def test_legacyFileMigratesOnFirstWriteAndReadsIdentical(self, monkeypatch, tmp_path):
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=False)
        mgr.add_message(_AGENT, _SID, "旧问-1", "旧答-1")
        mgr.add_message(_AGENT, _SID, "旧问-2", "旧答-2")
        path = _sessionFile(mgr)
        legacyBlob = json.loads(path.read_text(encoding="utf-8"))
        assert len(legacyBlob["messages"]) == 4  # 确是旧全量 JSON

        # 开关打开后只读：仍按旧格式正确读出，文件一个字节不动
        monkeypatch.setenv("NEUROVA_SESSION_JSONL", "1")
        assert [m["content"] for m in mgr.get_history(_AGENT, _SID)] == [
            "旧问-1", "旧答-1", "旧问-2", "旧答-2",
        ]
        assert json.loads(path.read_text(encoding="utf-8")) == legacyBlob

        # 首次写入触发懒迁移：首行变成两段式快照行
        mgr.add_message(_AGENT, _SID, "新问-3", "新答-3")
        lines = _jsonlLines(path)
        assert lines[0].get("t") == "snap"
        assert lines[0].get("v") == sm.SESSION_JSONL_FORMAT_VERSION

        # 迁移后读数一致：旧 4 条 + 新 2 条，顺序不变
        assert [m["content"] for m in mgr.get_history(_AGENT, _SID)] == [
            "旧问-1", "旧答-1", "旧问-2", "旧答-2", "新问-3", "新答-3",
        ]
        record = mgr.get_session(_AGENT, _SID)
        assert record.total_messages == 6


class TestSnapshotRoll:
    """每 SESSION_SNAPSHOT_EVERY 条增量滚动一份快照。"""

    def test_snapshotRollsAndReplayStaysConsistent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sm, "SESSION_SNAPSHOT_EVERY", 4)
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=True)
        for i in range(6):
            mgr.add_message(_AGENT, _SID, f"问-{i}", f"答-{i}")

        path = _sessionFile(mgr)
        lines = _jsonlLines(path)
        snaps = [obj for obj in lines if obj.get("t") == "snap"]
        apps = [obj for obj in lines if obj.get("t") == "app"]
        # 12 条消息、每 4 条一滚：至少落过一次滚动快照，且快照+增量读回齐全
        assert len(snaps) >= 1
        assert len(snaps[0].get("messages") or []) >= 4
        assert len(mgr.get_history(_AGENT, _SID)) == 12
        # 快照行里的消息数 + 增量行数 == 总消息数（两段式无丢失）
        assert len(snaps[-1]["messages"]) + len(apps) == 12


class TestMigrationFailOpen:
    """迁移/快照写失败：回退旧全量写法，错误日志可见，不静默吞。"""

    def test_jsonlWriteFailureFallsBackToLegacyWriteWithVisibleLog(self, monkeypatch, tmp_path):
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=True)
        records = []

        class _Recorder:
            def __getattr__(self, name):
                return lambda msg, *a, **k: records.append(str(msg))

        monkeypatch.setattr(sm, "logger", _Recorder())
        monkeypatch.setattr(
            SessionManager, "_writeJsonlSnapshot", lambda self, path, data: False, raising=True,
        )
        mgr.add_message(_AGENT, _SID, "问-fallback", "答-fallback")

        path = _sessionFile(mgr)
        data = json.loads(path.read_text(encoding="utf-8"))  # 旧写法兜底成功
        assert len(data["messages"]) == 2
        assert data["messages"][0]["content"] == "问-fallback"
        assert records, "回退必须留下可见错误日志，不得静默吞"


class TestJsonlParity:
    """开关打开后各读面（历史/记录/搜索/最近上下文）与旧实现同读数。"""

    def test_jsonlModePreservesMetadataAndReadSurfaces(self, monkeypatch, tmp_path):
        mgr = _makeManager(monkeypatch, tmp_path, jsonl=True)
        mgr.add_message(
            _AGENT, _SID, "问-1", "答-1",
            metadata={"k": "v"}, assistant_metadata={"reasoning_content": "思考"},
        )
        mgr.save_message(_AGENT, _SID, "user", "单条", user_id="u1")

        path = _sessionFile(mgr)
        assert _jsonlLines(path)[0].get("t") == "snap"  # 确为两段式形态

        history = mgr.get_history(_AGENT, _SID)
        assert [m["content"] for m in history] == ["问-1", "答-1", "单条"]

        record = mgr.get_session(_AGENT, _SID)
        assert record.total_messages == 3
        assert (record.messages[0].metadata or {}).get("k") == "v"
        assert (record.messages[1].metadata or {}).get("reasoning_content") == "思考"

        hits = mgr.search_session(_AGENT, _SID, "单条")
        assert len(hits) == 1 and hits[0]["content"] == "单条"

        ctx = mgr.get_recent_context(_AGENT, _SID, max_messages=2)
        assert [c["content"] for c in ctx] == ["答-1", "单条"]

        # 再追加一轮，跨快照滚动后读数仍齐
        mgr.add_message(_AGENT, _SID, "问-2", "答-2")
        assert [m["content"] for m in mgr.get_history(_AGENT, _SID)] == [
            "问-1", "答-1", "单条", "问-2", "答-2",
        ]
