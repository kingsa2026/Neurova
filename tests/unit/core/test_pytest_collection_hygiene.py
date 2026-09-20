"""pytest 收集卫生守卫。

`def testXxx`（漏下划线）不会被 pytest 收集，既不报错也不失败——整份测试文件
可以静默不跑。工单 003 期间真实踩到（13 个用例 collected 0 items）。
"""

from __future__ import annotations

import re
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parents[2]
_FUNCTION_PATTERN = re.compile(r"^\s*def (test[A-Z]\w*)\(", re.M)
_CLASS_PLACEHOLDER = re.compile(r"^\s*class (Test)\b", re.M)


def _offenders() -> list:
    found = []
    for path in _TESTS_DIR.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _FUNCTION_PATTERN.finditer(text):
            found.append("%s → %s（应为 test_%s）" % (path.relative_to(_TESTS_DIR), match.group(1),
                                                      match.group(1)[4].lower() + match.group(1)[5:]))
        found += ["%s → 类名 %r 不是 Test* 形态" % (path.relative_to(_TESTS_DIR), m.group(1))
                  for m in _CLASS_PLACEHOLDER.finditer(text)]
        if path.name == Path(__file__).name:
            continue
        # 本守卫自己就是"改了收集规则之后必须还守得住"的那条线：
        # 配置里的 python_functions 加了 test[A-Z]*（项目命名用驼峰，pytest 默认只认 test_*，
        # 两边一撞就是整份文件静默不跑），所以这里反过来禁止本文件用驼峰名。
        found += ["%s → 守卫自身用例不得用驼峰名 %s" % (path.relative_to(_TESTS_DIR), m.group(1))
                  for m in re.finditer(r"^\s*def test[A-Z]\w*\(", text, re.M)]
    return found


def test_noTestFunctionIsMisspelledForCollection():
    offenders = _offenders()

    assert not offenders, "以下用例名不会被 pytest 收集，会静默不跑:\n" + "\n".join(offenders)
