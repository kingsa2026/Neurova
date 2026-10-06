# -*- coding: utf-8 -*-
"""tests/manual/ 的脚本不得被 pytest 收集（审计 §6-31）。

实测成因：该目录 21 个脚本在**模块顶层**改写进程环境（`os.environ.setdefault(
"NEUROVA_DATA_DIR", tempfile.mkdtemp())` 之类，共 27 处）。作为脚本直跑这是对的
（必须先于 `import neurova` 生效），但被 pytest 导入就把变量带进**整个跑测进程**——
此后任何依赖数据根/落点的判据都被无声掩盖。本批接会话落点守卫时就实测被掩盖过一次：
同一条 41 文件的选择集，带上 manual 时守卫 0 ERROR，摘掉 manual 才露出 16 条真 ERROR。

探针实测过两条拦截的边界：
- `pytest_ignore_collect` 对**命令行直接给出的路径**在 pytest 9 不生效（照样收集），
  而收集即导入——钩子回来时 env 已经改完，太晚；
- 所以必须有 `pytest_configure`（跑在收集之前）硬拒；实测拒得干净：子进程退出码非 0，
  且探针写的环境标记始终未出现，说明脚本根本没被导入。
"""

import os
import subprocess
import sys
import textwrap
import tomllib
from fnmatch import fnmatch
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANUAL_DIR = PROJECT_ROOT / "tests" / "manual"


def _runPytest(*args: str, cwd: Path = None, timeout: int = 180):
    """子进程跑 pytest，并把输出通道钉成 UTF-8。

    Windows 上子进程的 stderr 默认走控制台编码（cp936），中文判据消息会被解成乱码，
    于是"断言消息文本"这种写法必然假失败——判据要读得懂，先固定编码。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=str(cwd or PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )


def _pythonFilesPatterns() -> list:
    """收集口径只认 pyproject 的现值（第 6 条：不在此处另抄一份 glob）。"""
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as f:
        cfg = tomllib.load(f)
    return cfg["tool"]["pytest"]["ini_options"]["python_files"]


def test_noManualFileMatchesCollectionPattern():
    """默认收集防线：`tests/manual/` 里不得出现匹配 `python_files` 的文件名。

    一旦有人把活体脚本命名成 `test_*.py`，全量跑测就会导入它、连带把它写的 env
    带给后面每一条用例——这条判据把"隐式安全"变成显式约束。
    """
    patterns = _pythonFilesPatterns()
    offenders = [p.name for p in sorted(MANUAL_DIR.glob("*.py"))
                 if any(fnmatch(p.name, pat) for pat in patterns)]
    assert not offenders, (
        "tests/manual/ 下出现了会被 pytest 收集的文件名 %s（口径 %s）——"
        "这些脚本在导入期改写进程 env，会把数据根类判据全部掩盖" % (offenders, patterns)
    )


def test_explicitManualPathIsRefusedBeforeImport(tmp_path):
    """显式点名也要拒在收集之前：探针脚本写下的环境标记绝不能出现在同进程后续用例里。"""
    probeName = "test_tmpManualProbeEnvLeak.py"
    probePath = MANUAL_DIR / probeName
    marker = "ZZ_MANUAL_LEAK_PROBE"
    os.environ.pop(marker, None)
    # 故意用匹配收集口径的文件名：证明拦截不靠"名字碰巧不被收集"
    probePath.write_text(textwrap.dedent("""
        import os

        os.environ["%s"] = "1"


        def testZzManualProbe():
            assert True
    """ % marker), encoding="utf-8")

    watcher = tmp_path / "test_tmpManualLeakWatcher.py"
    watcher.write_text("import os\n\n\ndef testZzNoLeak():\n"
                       "    print('MARKER=', os.environ.get('%s'))\n"
                       "    assert os.environ.get('%s') is None\n" % (marker, marker),
                       encoding="utf-8")
    try:
        proc = _runPytest("tests/manual/%s" % probeName, str(watcher))
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, (
            "把 tests/manual 的脚本交给 pytest 竟然跑通了——拦截失效：%s" % out[-500:]
        )
        assert "不得交给 pytest 跑" in out, out[-500:]
        assert "MARKER= 1" not in out, "拦截晚了：脚本已被导入并改写了进程环境"
    finally:
        probePath.unlink(missing_ok=True)
        os.environ.pop(marker, None)


def test_manualDirectoryInvocationIsRefused():
    """整目录交给 pytest 同样拒——否则一次 `pytest tests/manual/` 就带进 21 个脚本。"""
    proc = _runPytest("tests/manual/")
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out[-500:]
    assert "不得交给 pytest 跑" in out, out[-500:]
