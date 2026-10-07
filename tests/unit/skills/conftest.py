"""`tests/unit/skills/` 子包 conftest：`start.py` 的导入面收口。

`start.py` 是**仓库根**的顶层脚本（不是包内模块），测试要 `import start`
就得把仓库根塞进 `sys.path`——那样 Python 会把 `start.py` 编译出的
`__pycache__/` 写在**仓库根**，由 `tests/conftest.py` 的
`_guardRepoRootAgainstPollution` 逐条点名（受保护子集实跑
`tests/unit/skills/test_scripts_start.py` 即此形态）。

收口办法：用 `importlib.util` 从文件路径**一次性**加载并登记进
`sys.modules["start"]`。这样：
  * 不需要把仓库根加进 `sys.path`（少一条可在别处漂移的入口）；
  * 编译产物走 importlib 自己的 cache 语义，不落仓库根；
  * 各用例原有的 `from start import ...` / `import start` 无需改写——
    `sys.modules` 命中即直接返回。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_START_PY = _PROJECT_ROOT / "start.py"

if "start" not in sys.modules and _START_PY.is_file():
    _spec = importlib.util.spec_from_file_location("start", _START_PY)
    if _spec is not None and _spec.loader is not None:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["start"] = _module
        # `spec_from_file_location` 的 loader 默认会把 `.pyc` 写在**源文件旁**
        # 即仓库根的 `__pycache__/`。本次加载是唯一入口，故在此局部关掉字节码
        # 写盘——判据（工具函数行为）与 `.pyc` 缓存无关，关掉不影响断言，
        # 也不再往仓库根写盘。生产跑 `python start.py` 不受影响（那是另一进程）。
        _prev = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            _spec.loader.exec_module(_module)
        finally:
            sys.dont_write_bytecode = _prev
