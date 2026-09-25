# -*- coding: utf-8 -*-
"""pytest 运行器守卫：收集竞争的兜底必须保持可证伪。

背景（2026-09-21）：受保护子集在 pytest 9.x 上整片
`fixture 'rsi_probe_factory' not found`（实测 65 个 error），与业务代码无关。

机制（逐层实测复现，pytest 8.4.2 / 9.0.3 / 9.1.1 同形态）：

1. `tests/unit/evolution/` 没有 `__init__.py`，由 `_pytest.main.Dir` 收集，
   `nodeid == "tests/unit/evolution"`、`name == "evolution"`。
2. 同一个目录会在收集树里出现**两个不同的 collector 对象**：
   - `Session.collect()` 逐层下钻（`_collect_path`，`path_cache` 只在单次
     `collect()` 内共享）；
   - `Dir.collect()` 扫到自己那一级时再 `pytest_collect_directory` 一次。
3. `Node.__hash__` 用 nodeid，但 `Node.__eq__` 是身份比较（cpython 默认）。
   于是 `Session._collect_one_node` 的 `node in self._collection_cache`
   （dict 查找：先按哈希落到桶，再 `__eq__` 比较）对**另一个身份**落空。
   实测打点：
     `_collect_one_node Dir id=...208 in_cache=False handle_dupes=False`
     `_collect_one_node Dir id=...504 in_cache=False handle_dupes=True cached=[...208]`
   —— 同一份收集报告被算两次，且被缓存的是"另一条"身份。
4. `FixtureManager._matchfactories` 的可见性判据是
   `fixturedef.node in parent_nodes`，`parent_nodes` 是 **list**
   （`list.__contains__` 走 `==` ⇒ 恒等身份比较），不再有哈希这一层。
   一旦父包 conftest 的 fixture 绑到了"当前 item 父链上不存在"的那个身份，
   就是成片 `fixture 'xxx' not found`。

修法（见 `tests/unit/evolution/rsi/conftest.py`）：在子包自己的 conftest 里
**按名重导出**父包 fixture（实现只有一份，不做复制），让可见性判据只在
"本包 collector"这一层求值，不再跨身份比较。

**曾经走过的弯路（留档，避免复发）**：先怀疑是"临时目录可预测"
（`_pytest/pathlib.py` 的 `exists_added_to_start` 优化）并加了 basetemp
唯一化补丁 —— 实测无效，两条 `Dir` 身份照旧。根因在 `__hash__`/`__eq__`
不对称 + `_collect_one_node` 的缓存查找，与 tmpdir 无关。

设计约束（照 AGENTS.md 的 TDD 红绿灯纪律）：

- 断言必须可证伪，且"回退修复即转红"的路径写在注释里；
- 不得只断言"清单里有某个字符串" —— 收集竞争是**行为**，用行为断言。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 最小触发集（实测穷举 7 条子集 × 全部顺序，只有这一组复现）：
# 要点是 `Session.collect()` 在处理第二条 initial path 时，必须先经过**第一条
# 路径的父链**（`tests/unit/evolution`）建出一个 Dir，再在 `Dir.collect()`
# 下钻时对同一目录建出第二个身份。三条一起给时才会走到那条复用分支。
# 实测（pytest 9.1.1）：本序 `39 passed, 10 errors`；单跑任一条、或两条按
# 其它顺序给，都不复现。
_TRIGGER_FILES = (
    "tests/unit/evolution/test_skill_consolidation_structural_and_deadcode_p1p2.py",
    "tests/unit/test_ci_npc_config_guard.py",
    "tests/unit/evolution/rsi/test_parameter_source_of_truth.py",
)

# 该 fixture 只在 `tests/unit/evolution/conftest.py` 定义，一旦跨身份比较就
# 变成 `not found` —— 它是"父包 conftest 是否绑对 collector"的探针。
_PROBE_FIXTURE = "rsi_probe_factory"

# 子包 conftest（兜底落点）。删掉它 / 删掉里面任意一个重导出，本文件转红。
_SUBPACKAGE_CONFTEST = Path("tests/unit/evolution/rsi/conftest.py")

# 必须被重导出的父包 fixture 名单（与 tests/unit/evolution/conftest.py 一一对应）。
_PARENT_FIXTURES = (
    "measured_eval_harness",
    "blind_eval_harness",
    "rsi_probe_factory",
    "probe_tool_memory_system",
    "null_systems",
    "fake_skill",
)


def _run_pytest(args):
    """在子进程里跑 pytest（不污染当前会话的 collection cache / tmpdir）。"""
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


class TestConftestFixturesResolveInMultiPathCollection:
    """最小触发集下，父包 conftest 的 fixture 必须能被解析（收集竞争回归）。"""

    def test_fixture_consumers_pass_when_given_as_multiple_paths(self):
        """三条路径按最小触发序给：必须全绿，且不得出现 `fixture ... not found`。

        可证伪路径：删掉（或清空）`tests/unit/evolution/rsi/conftest.py`，
        在 pytest>=9 上立刻转红（实测 9.1.1：`39 passed, 10 errors`）。
        """
        proc = _run_pytest(["-q", "--no-header", *_TRIGGER_FILES])
        out = proc.stdout + proc.stderr
        assert f"fixture '{_PROBE_FIXTURE}' not found" not in out, (
            "最小触发集下父包 conftest fixture 解析失败 —— 收集竞争复发。\n"
            f"根因与修法见 {_SUBPACKAGE_CONFTEST} 的模块 docstring，"
            "机制实测见本文件模块 docstring。\n"
            "--- pytest 输出 ---\n" + out[-4000:]
        )
        assert proc.returncode == 0, (
            f"最小触发集未全绿（returncode={proc.returncode}）。\n"
            "--- pytest 输出 ---\n" + out[-4000:]
        )

    def test_collection_count_equals_sum_of_single_paths(self):
        """三条路径一起收集到的用例数，必须等于各自单跑之和。

        这一条钉的是机制本身（不只是"有没有报错"）：同一份收集报告被算两次时，
        collector 树与单跑不一致，收集数会出现缺口/重复。
        """
        def collected(paths):
            proc = _run_pytest(["--co", "-q", "--no-header", *paths])
            shapes = re.findall(r"(\d+) tests? collected", proc.stdout)
            assert shapes, f"--co 未报告收集数：{proc.stdout[-2000:]}"
            return int(shapes[-1])

        total_separate = sum(collected([f]) for f in _TRIGGER_FILES)
        combined = collected(list(_TRIGGER_FILES))
        assert combined == total_separate, (
            f"三条路径一起收集到 {combined} 条，单跑之和为 {total_separate} 条 —— "
            "收集被提前中止/重复（收集竞争复发）。"
        )


class TestSubpackageConftestReexportsParentFixtures:
    """兜底落点本身的两条不变量：名单完整 + 实现仍是单份。"""

    def test_subpackage_conftest_reexports_every_parent_fixture(self):
        """父包 conftest 里的每个 fixture 都必须在子包 conftest 里按名重导出。

        可证伪路径：给 `tests/unit/evolution/conftest.py` 新增一个 fixture 而
        不同步子包 conftest，本测试转红（这正是"新增 fixture 后 RSI 子包又丢
        fixture"的预防）。fixture 集合直接取自父包源码的 `@pytest.fixture`
        装饰名单，不依赖内省。
        """
        parent = (
            PROJECT_ROOT / "tests" / "unit" / "evolution" / "conftest.py"
        ).read_text(encoding="utf-8")
        defined = set(
            re.findall(r"(?m)^@pytest\.fixture[^\n]*\ndef (\w+)\(", parent)
        )
        assert defined, "父包 conftest 里没解析到任何 @pytest.fixture —— 正则已失效"

        sub = (PROJECT_ROOT / _SUBPACKAGE_CONFTEST).read_text(encoding="utf-8")
        m = re.search(
            r"from tests\.unit\.evolution\.conftest import \(([^)]*)\)", sub, re.S
        )
        assert m, f"{_SUBPACKAGE_CONFTEST} 未按名重导出父包 fixture"
        imported = {n.strip().rstrip(",") for n in m.group(1).split() if n.strip()}

        assert imported == defined, (
            "子包 conftest 的重导出名单与父包 fixture 集合不一致 —— 缺一个就会在\n"
            "最小触发集的收集顺序下变成 `fixture not found`。\n"
            f"缺少：{sorted(defined - imported)}\n"
            f"多余（父包已无）：{sorted(imported - defined)}"
        )
        assert imported == set(_PARENT_FIXTURES), (
            "本文件的 _PARENT_FIXTURES 显式名单已过期，请同步更新：\n"
            f"实际：{sorted(defined)}"
        )

    def test_reexport_does_not_duplicate_fixture_bodies(self):
        """子包 conftest 只能是重导出，不得把 fixture 实现抄一份。

        可证伪路径：把某个 fixture 的函数体复制进子包 conftest，本测试转红
        （两份实现会各自漂移，比"丢 fixture"更难发现）。
        """
        sub = (PROJECT_ROOT / _SUBPACKAGE_CONFTEST).read_text(encoding="utf-8")
        for name in _PARENT_FIXTURES:
            assert not re.search(rf"(?m)^def {re.escape(name)}\(", sub), (
                f"{_SUBPACKAGE_CONFTEST} 里出现了 `def {name}(` —— 兜底必须是重导出，"
                "不得复制实现（两份实现会各自漂移）。"
            )


class TestGuardTargetsAreProtected:
    """本守卫的靶点必须在受保护子集里，否则回归无人看。"""

    def test_trigger_files_and_self_are_in_protected_subset(self):
        listed = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt").read_text(
            encoding="utf-8"
        )
        for rel in (*_TRIGGER_FILES, "tests/unit/test_pytest_runner_guards.py"):
            assert rel in listed, (
                f"{rel} 不在受保护子集 —— 移出后本文件守的收集竞争回归无人发现。"
            )
