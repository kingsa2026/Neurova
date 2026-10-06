"""wait_for_server 日志辅助信号判据：致命标记只认本次启动新增的字节。

缺陷（2026-10-06 重启实测）：wait_for_server 对共享 logs/server.log 全文检索
'Traceback (most recent call last)' 等致命标记，mtime 判据只证明"文件更新过"，
挡不住历史错误（当天 17:51 WinError 64 的 traceback 就躺在历史里）——每次
重启都在数秒内被误判"服务器启动失败"，启动器 rc=1 退出，而服务实际数十秒后
健康。判据：判死只看本次启动之后追加的字节（日志为 append 模式，历史轮次
必须保留作取证，见 start.start_backend）。
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.health_check import wait_for_server  # noqa: E402


@pytest.fixture
def logFile(tmp_path, monkeypatch):
    log = tmp_path / "server.log"
    log.write_text("更早轮次：正常收尾\n", encoding="utf-8")
    monkeypatch.setattr("scripts.health_check.LOG_FILE", log)
    return log


@pytest.fixture
def neverReady(monkeypatch):
    monkeypatch.setattr(
        "scripts.health_check.health_check", lambda port=None, timeout=3: False)


def _appendOnFirstTick(log, text):
    """首轮回调时追加内容，模拟正在启动的后端持续写日志。"""
    def onProgress(elapsed, timeout):
        if elapsed == 0:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(text)
    return onProgress


def testStaleTracebackInHistoryDoesNotAbortStartup(logFile, neverReady, capsys):
    """历史 traceback 不是本次启动的失败证据：只能走超时，不得提前判死。"""
    logFile.write_text(
        "2026-10-06 17:51 历史轮次：Traceback (most recent call last)\n"
        "OSError: [WinError 64] 历史现场\n",
        encoding="utf-8",
    )
    result = wait_for_server(
        port=59999, timeout=3, interval=1,
        on_progress=_appendOnFirstTick(
            logFile, "2026-10-06 18:30 本轮：Registered router\n"),
        check_log=True,
    )
    out = capsys.readouterr().out
    assert result is False
    assert "服务器启动失败" not in out
    assert "启动超时" in out


def testFreshTracebackAfterLaunchStillAborts(logFile, neverReady, capsys):
    """本次启动新写入的 traceback 仍须立即判死（保留原有快速失败）。"""
    result = wait_for_server(
        port=59999, timeout=10, interval=1,
        on_progress=_appendOnFirstTick(
            logFile, "Traceback (most recent call last)\n  本轮致命错误\n"),
        check_log=True,
    )
    out = capsys.readouterr().out
    assert result is False
    assert "服务器启动失败" in out
