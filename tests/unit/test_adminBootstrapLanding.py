"""§6-33：admin 引导脚本必须走数据根锚点，口令必须注入且不回显（红→绿）

修复前实测缺陷（本会话活体取证时踩到）：
- `create_admin_user.py:17` 写死 `UserModel(db_path="data/users.db")`——**CWD 相对字面量**，
  `NEUROVA_DATA_DIR` 完全不生效；我按"数据根已隔离"的假设跑它，结果把 admin 写进了仓内
  真库（临时数据根里反而没有），事后按四条件精确删行；
- 口令 `"Admin23@"` 硬编码并 `print` 到 stdout：任何人拿到脚本即可登录；
- 失败分支 `except Exception → print + traceback` **仍以 0 退出**：CI 里"创建失败"被读成成功。

服务端读的是 `UserModel()`（`user_model.py:73` 经 `callerPath(db_path, "users.db")` 落数据根），
所以脚本的正确形态是**同一解析口径**，不是另抄一条锚点调用。
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "create_admin_user.py"
STRONG_PASSWORD = "Adm1n-Str0ng#2026"

#: 本档两枚子进程落点的预算唯一出处（§6-402 批 K 口径）。跑的是 `create_admin_user.py`
#: 与一条 `python -c` 探径，实测 546ms / 449ms——取**低于全局 30s** 的 20s：先到点的应当是
#: 子进程那条诚实的 TimeoutExpired，而不是 thread 法的全局墙（那会把整场跑测一起打死）。
#: 此前两枚根本没有 `timeout=`，等待是无界的。
PROBE_WALL_S = 20


def _run(root: Path, cwd: Path, envExtra: dict) -> subprocess.CompletedProcess:
    """cwd 与数据根**故意不同**：这样"CWD 相对落点"与"锚点落点"一眼可分。

    stdin 关到 DEVNULL：脚本在 tty 上会交互索要口令，而无人值守（CI/管道）必须走
    "没给口令就非零退出"那条路——留着继承的 tty 会让探针卡在提示符上。
    """
    env = dict(os.environ)
    env["NEUROVA_DATA_DIR"] = str(root)
    env.pop("NEUROVA_ADMIN_PASSWORD", None)
    env.update(envExtra)
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        timeout=PROBE_WALL_S,
    )


def _adminRow(dbFile: Path):
    if not dbFile.exists():
        return None
    con = sqlite3.connect(dbFile)
    try:
        return con.execute("select username, role from users where username='admin'").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def testLandsOnDataRootNotCwd(tmp_path):
    """admin 必须落进 `NEUROVA_DATA_DIR`，而不是进程 CWD 的 `data/`。"""
    dataRoot = tmp_path / "data_root"
    dataRoot.mkdir()

    result = _run(dataRoot, tmp_path, {"NEUROVA_ADMIN_PASSWORD": STRONG_PASSWORD})

    assert result.returncode == 0, result.stdout + result.stderr
    assert _adminRow(dataRoot / "users.db") is not None, (
        f"数据根里没有 admin——落点没走锚点：{result.stdout}"
    )
    assert _adminRow(tmp_path / "data" / "users.db") is None, (
        "CWD 相对的 data/users.db 里出现了 admin——正是把账号写进别人库的那条形变"
    )


def testPasswordNeverPrintedAndNotHardcoded(tmp_path):
    """口令来自注入：stdout 不得回显，源里也不得留着那个默认值。"""
    dataRoot = tmp_path / "data_root"
    dataRoot.mkdir()

    result = _run(dataRoot, tmp_path, {"NEUROVA_ADMIN_PASSWORD": STRONG_PASSWORD})

    assert STRONG_PASSWORD not in result.stdout, "stdout 回显了口令"
    assert "Admin23@" not in SCRIPT.read_text(encoding="utf-8"), (
        "默认弱口令还硬编码在脚本里——改锚只是把它搬进更多人的数据根"
    )


def testMissingPasswordFailsLoudly(tmp_path):
    """没给口令又不肯用默认值：必须失败且退出码非 0。"""
    dataRoot = tmp_path / "data_root"
    dataRoot.mkdir()

    result = _run(dataRoot, tmp_path, {})

    assert result.returncode != 0, (
        f"无口令却静默成功（退出码 0）——stdout: {result.stdout!r}"
    )
    assert "NEUROVA_ADMIN_PASSWORD" in (result.stdout + result.stderr), (
        "报错必须点名该注入哪个环境变量"
    )


def testWeakPasswordRejected(tmp_path):
    """弱口令必须被拒，且用的是仓内既有强度口径（不另造一份策略）。"""
    dataRoot = tmp_path / "data_root"
    dataRoot.mkdir()

    result = _run(dataRoot, tmp_path, {"NEUROVA_ADMIN_PASSWORD": "abc"})

    assert result.returncode != 0, f"弱口令被接受：{result.stdout!r}"
    assert _adminRow(dataRoot / "users.db") is None


def testFailureExitsNonZero(tmp_path):
    """失败不得以 0 退出：安装脚本"打印失败却成功"会被 CI 读成通过。"""
    dataRoot = tmp_path / "data_root"
    dataRoot.mkdir()
    # 让数据根路径不可用：指向一个已存在的普通文件，目录创建必然失败
    blocker = dataRoot / "users.db"
    blocker.write_text("not a database", encoding="utf-8")

    result = _run(dataRoot, tmp_path, {"NEUROVA_ADMIN_PASSWORD": STRONG_PASSWORD})

    assert result.returncode != 0, f"坏库却退出 0：{result.stdout!r}"


def testServerResolvesTheSamePath(tmp_path):
    """脚本与登录服务端必须指向同一个库——否则建了账号也登不上。"""
    env = dict(os.environ)
    env["NEUROVA_DATA_DIR"] = str(tmp_path)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from neurova.auth.user_model import UserModel;"
            "print(UserModel().db_path)",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=PROBE_WALL_S,
    )
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve() == (tmp_path / "users.db").resolve(), (
        f"服务端解析口径变了，脚本的'同一份库'假设需要重新核对：{probe.stdout}"
    )
