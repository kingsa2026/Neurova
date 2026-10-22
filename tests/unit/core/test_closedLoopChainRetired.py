# -*- coding: utf-8 -*-
"""闭环链两档退役的守卫（§6-395）——「同一条不存在的链上的测试与脚本」清零。

退役对象（两份都在引用一条**全仓零定义**的链）：

- `tests/integration/test_full_conflict_integration.py`（238 行）：模块级
  `pytest.skip(allow_module_level=True)`，skip 理由自己写着"引用不存在的模块
  `neurova.core.闭环_manager`（非法模块名）"。逐符号现算：`闭环_manager` 与
  `start_闭环`／`create_闭环_manager`／`stop_闭环` 在 `neurova/` 里**零出现**；
  它 import 的 `MemoryConflictDetector`／`ConflictLevel` 也零定义（今天的实现是
  `conflict.py:LegacyConflictDetector`，`ConflictType` 在 `modules/conflict_module.py`）；
  skip 理由里那句"conflict_detector_v2 已于 §6-370 退役"由**另一档**守卫
  （`tests/unit/cognitive_layers/memory_layer/test_conflictDetectorV2Retirement.py`），
  本档不重复钉它——那正是本仓要避免的双源（教义第 6 条）。
  一格一格修它＝给一条不存在的链补形状（§6-391 对旧集成档的同一口径）。
- `scripts/demo_closed_loop.py`（290 行）：整个脚本的主体就是那条链——
  `demo_closed_loop()` 与 `demo_manual_operations()` 都从 `neurova.core.闭环_manager`
  取 `start_闭环`／`create_闭环_manager`／`stop_闭环`。它不是"两处构造参数写错"，
  而是演示对象根本不存在；`db_path=` 那两枚只是同一条死链上的症状。

性质今天由谁在守（本批**不取长补短**：无可取，也没有能力被删）：
冲突检测是否阻断本步 → `tests/unit/agent/test_conflict_detection_observation_only.py`；
账上成员必须能在库里定位 → `test_conflict_ledger_member_identity.py`；
检测链接线 → `test_memory_guards_wiring.py`（三档现算 19 passed）。
`LegacyConflictDetector` 自身作为 legacy 面的判据不在本批范围，登记在 §6-395 仍开栏。

本档钉四件不许复活，外加一枚对本仓新形态的自我防御（形态 373：守卫档的仓库根
基准按本档深度算，抄别的档会让「不存在」类断言恒绿）：

1. 两个文件与其模块路径都不存在；
2. `tests/`＋`scripts/`＋`neurova/` 里 `闭环_manager`／`start_闭环`／
   `create_闭环_manager`／`MemoryConflictDetector` 四个死名字**零出现**，
   本守卫档自身除外（它必须点名退役对象）——有人为了让旧档"跑起来"把链加回去，
   当场红；
3. 替代覆盖档在场且仍可被收集（否则将来替代档被删时，旧档会以"恢复覆盖"捞回来）；
4. 反向控制：合成样本必须被扫描器点名、正常档不得误报；
5. 自证：`REPO_ROOT` 必须真的指向含 `neurova/` 的仓库根（这一格专治形态 373）。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RETIRED_TEST = REPO_ROOT / "tests" / "integration" / "test_full_conflict_integration.py"
RETIRED_SCRIPT = REPO_ROOT / "scripts" / "demo_closed_loop.py"
DEAD_NAMES = (
    "闭环_manager",
    "start_闭环",
    "create_闭环_manager",
    "MemoryConflictDetector",
)
SURVIVOR_TESTS = (
    REPO_ROOT / "tests" / "unit" / "agent" / "test_conflict_detection_observation_only.py",
    REPO_ROOT / "tests" / "unit" / "agent" / "test_conflict_ledger_member_identity.py",
    REPO_ROOT / "tests" / "unit" / "agent" / "test_memory_guards_wiring.py",
)
SCAN_ROOTS = ("neurova", "tests", "scripts")

pytestmark = pytest.mark.timeout(60)


def _isPointerLine(line: str) -> bool:
    """注释行一律算路标；docstring/代码行要带「退役」或台账号才认。

    只在注释上放宽是安全的：真把死链 import 回来的一定是代码行，注释咬不动任何东西；
    反过来，多行 bullet 里「退役」二字未必落在带路径那一行，按关键词逐行判会误报自家
    账目（本批就被 `test_dreamReportSeamIsNotFabricated.py` 的注释咬过一次）。
    docstring 仍需关键词——它是会被 `import`/复制传播的位置。
    """
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return True
    return "退役" in line or "§6-" in line


def _deadNameHits(source: str) -> list:
    """返回命中的死名字（注释里的指针行不算）。"""
    hits = []
    for line in source.splitlines():
        if _isPointerLine(line):
            continue
        for name in DEAD_NAMES:
            if name in line:
                hits.append(name)
    return hits


def test_仓库根基准真的指向本仓():
    """形态 373 的自证：路径基准一错，下面所有「不存在」类断言会无条件成立。"""
    assert (REPO_ROOT / "neurova").is_dir(), (
        f"REPO_ROOT 取错了：{REPO_ROOT} 下没有 neurova/ —— "
        "本档在 tests/unit/core/ 三层深，parents[3] 才是仓库根"
    )
    assert (REPO_ROOT / "pyproject.toml").is_file(), f"REPO_ROOT 不像仓库根：{REPO_ROOT}"


def test_两档文件与模块路径都不存在():
    for path in (RETIRED_TEST, RETIRED_SCRIPT):
        assert not path.exists(), (
            f"退役件被复活：{path.relative_to(REPO_ROOT).as_posix()} —— "
            "它引用的闭环链在 neurova/ 零定义，跑起来只会把死名字重新要一遍"
        )
    for dotted in (
        "tests.integration.test_full_conflict_integration",
        "scripts.demo_closed_loop",
    ):
        try:
            spec = importlib.util.find_spec(dotted)
        except ModuleNotFoundError:
            spec = None   # 父包在而模块不在——正是要的形态
        assert spec is None, f"{dotted} 仍可按包路径 import：{spec}"


def test_死名字在全仓代码里清零():
    offenders = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path == Path(__file__):
                continue
            hits = _deadNameHits(path.read_text(encoding="utf-8", errors="ignore"))
            if hits:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{sorted(set(hits))}"
                )
    assert not offenders, (
        "这些文件还在按名字引用已退役的闭环链（要留说明请带上「退役」二字）："
        + "; ".join(offenders)
    )


def test_替代覆盖档在场且仍含活体用例():
    for path in SURVIVOR_TESTS:
        assert path.exists(), f"替代判据档不见了：{path.relative_to(REPO_ROOT).as_posix()}"
    total = 0
    for path in SURVIVOR_TESTS:
        text = path.read_text(encoding="utf-8")
        total += sum(
            1
            for line in text.splitlines()
            if line.startswith(("def test", "    def test", "    async def test"))
        )
    assert total >= 12, f"三档活体用例数掉到 {total}（原 12 格以上）——替代覆盖名存实亡"


def test_扫描器真会咬():
    """反向控制：注释行不误报，代码行与无关键词的 docstring 行必点名。"""
    sample = "\n".join([
        "from neurova.core.闭环_manager import start_闭环",      # 裸引用 → 该咬
        "# 见 scripts/demo_closed_loop.py 的退役说明（闭环_manager 已不存在）",  # 注释 → 不该咬
        "# from neurova.core.闭环_manager import start_闭环",    # 注释里的代码形 → 仍不该咬
        '    """旧档 test_full_conflict_integration.py 引用 start_闭环"""',  # docstring 无关键词 → 该咬
        "detector = MemoryConflictDetector()",                   # 死类名 → 该咬
    ])
    hits = _deadNameHits(sample)
    assert sorted(set(hits)) == ["MemoryConflictDetector", "start_闭环", "闭环_manager"], (
        f"死名字扫描器分类错了：{sorted(set(hits))}"
    )
    # 命中的行号只应是 1 / 4 / 5——第 2、3 行是注释
    flagged = [
        number
        for number, line in enumerate(sample.splitlines(), start=1)
        if _deadNameHits(line)
    ]
    assert flagged == [1, 4, 5], f"注释放宽越界了：{flagged}"
    assert _deadNameHits("from neurova.cognitive_layers.memory_layer.conflict import (\n"
                         "    LegacyConflictDetector,\n)") == [], "正常档被误报"
