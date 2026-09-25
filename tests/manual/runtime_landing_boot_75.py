"""live-verify（Issue #75）：真后端启动 + 真端点，验运行期落点已锚定。

与 `tests/e2e/test_backend_boot.py` 同法（真 subprocess 拉起 `start_server.py`），
只是把数据根与 CWD 都指到临时目录，看**谁还在 CWD 造东西**——这正是本批
要灭的形态。手动运行：

    NEUROVA_DATA_DIR=$(mktemp -d) python -m pytest tests/manual/runtime_landing_boot_75.py -q -s
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _freePort() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status


def test_backendBootLeavesCwdUntouched():
    cwd = Path(tempfile.mkdtemp(prefix="landing-cwd-"))
    root = Path(tempfile.mkdtemp(prefix="landing-root-"))
    port = _freePort()
    env = dict(os.environ)
    env.update({
        "NEUROVA_DATA_DIR": str(root),
        "NEUROVA_ENV": "production",
        "NEUROVA_JWT_SECRET": "x" * 40,
        "NEUROVA_PORT": str(port),
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONUNBUFFERED": "1",
    })
    # 日志落文件而不是 PIPE：后端启动期日志量大，PIPE 缓冲写满会把服务端
    # 阻塞在 write 上（实测表现为"探活超时"而进程还活着）。
    log_path = cwd / "boot.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "start_server.py")],
        cwd=str(cwd), env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        base = "http://127.0.0.1:%d" % port
        alive = False
        for _ in range(90):
            time.sleep(1)
            try:
                if _get(base + "/health", timeout=2) == 200:
                    alive = True
                    break
            except Exception:
                if proc.poll() is not None:
                    break
        assert alive, "后端未起来:\n%s" % log_path.read_text(encoding="utf-8")[-1500:]

        assert _get(base + "/metrics", timeout=5) == 200
        assert _get(base + "/health/detailed", timeout=5) == 200

        # 排除日志文件本身（它就在 CWD 里）——判据只看"落点造出来的东西"。
        leaked = sorted(p.name for p in cwd.iterdir() if p.name != "boot.log")
        assert leaked == [], "CWD 出现新增（运行期落点仍在按 CWD 拼）：%s" % leaked
        assert (root / "evolution").exists(), "数据根下未见运行期产物，落点解析可能没生效"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
        log_file.close()
