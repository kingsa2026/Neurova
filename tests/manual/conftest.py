"""tests/manual/ 是活体验证脚本目录，不是 pytest 用例集。

这些脚本在**模块顶层**改写进程环境（实测 21 个文件 27 处，如
`os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp())`），必须先于 `import neurova`
执行——作为脚本直跑是正确形态，被 pytest 导入就是事故：变量带进**整个跑测进程**，
此后任何依赖数据根/落点的判据都被无声掩盖（本仓实测掩盖过一次会话落点守卫）。

两道拦截，各管一条路径：
- 默认收集：文件名不匹配 `pyproject.toml` 的 `python_files = ["test_*.py"]`，进不来；
  `pytest_ignore_collect` 再兜一层（目录遍历路径生效）。
- 显式点名：`pytest_ignore_collect` 在 pytest 9 **对命令行直接给出的路径不生效**（实测
  仍被收集），而收集即导入、导入即改 env，钩子回来已经太晚。故在 `pytest_configure`
  （收集之前）就点名拒绝，给 out-of-band 的调用方式，而不是让它静默污染。

比较一律用 `Path`：Windows 下 `str(path)` 带反斜杠，字符串 "tests/manual" 永不匹配（实测踩过）。
"""
from pathlib import Path

import pytest

MANUAL_DIR = Path(__file__).resolve().parent


def _underManual(path) -> bool:
    try:
        Path(str(path)).resolve().relative_to(MANUAL_DIR)
    except ValueError:
        return False
    return True


def pytest_configure(config):
    offenders = [arg for arg in list(config.args or []) if _underManual(arg)]
    if offenders:
        raise pytest.UsageError(
            "tests/manual/ 下的脚本不得交给 pytest 跑：%s\n"
            "它们在模块顶层改写进程 env，被收集即导入，会把变量带进整个跑测进程、"
            "掩盖所有依赖数据根的判据。请直接运行：python tests/manual/<name>.py"
            % ", ".join(offenders)
        )


def pytest_ignore_collect(collection_path, config):
    return True if _underManual(collection_path) else None
