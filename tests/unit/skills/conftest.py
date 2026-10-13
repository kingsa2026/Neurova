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
        # 即仓库根的 `__pycache__/`。字节码写盘已由 `tests/conftest.py` 在导入期
        # 统一关掉（`sys.dont_write_bytecode`）——本处原有一份局部开关，与
        # `tests/unit/desktop/test_install_supply_contract.py`（install.py）和
        # CLI 那条（cli.py）是同一件事的三份实现，已按教义第 6/7 条收口。
        _spec.loader.exec_module(_module)
