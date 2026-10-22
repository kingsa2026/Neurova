# -*- coding: utf-8 -*-
"""`tests/unit/memory/test_storage_comprehensive.py` 的退役守卫（§6-394）。

那份 1 080 行的档自 2026-07-03 起整档 `pytest.mark.skip`（L-3 obsolete）：实测
`--collect-only` 收 46 格、跑起来 46 skipped——**收了却不跑，等于零覆盖**，
而它自己那份"全覆盖"的标题一直在给一份不存在的覆盖背书（与 §6-393 那枚
「放在 performance/ 里不等于会被跑」同族，只是这一枚连文件名都匹配收集规则，
更看不出是空的）。

它测的是一份**从未落地**的设计：给 `memory_layer.storage.MemoryStorage` 配
`VectorSearch` / `MemorySecurityGuard` / `MemoryCache` / `BatchWriter` 四件协作者，
外加 `db_path=` / `neuser_id=` / `enable_cache=` / `enable_batch_write=` 构造参数，
以及 `close()` / `update_memory_lifecycle()` / `update_metadata()` 方法。
今天的实装是 `MemoryStorage(storage_dir)` 的 JSON 版，四件里没有一件接到这只存储上——
`BatchWriter` 与 `VectorSearch` 在 `neurova/` 里**零出现**（不是"零调用"，是整仓没有这两个名字），
`MemoryCache` 活在 `core/cache.py`、`MemorySecurityGuard` 活在 `security/cognitive_security.py`，
都不被本存储 import。逐类修它等于给一条不存在的链路补形状。

分流结论（逐类给存活档指针；本批**不取长补短**，因为无可取）：

| 旧档里的类 | 它想证的性质 | 今天由谁在守 |
|------------|--------------|--------------|
| `TestMemoryStorageInit`／`TestSave`／`TestGet`／`TestIncrementAccess`／`TestDelete`／`TestCount`／`TestGetStats`／`TestUpdateMetadata` | 真 JSON 存储的 CRUD 契约 | `tests/cognitive_layers/memory_layer/test_storage.py`（18 passed：save 回 id、get 缺失返回 None、update 合并字段、count、query 按类型/属主/时间窗、list_by_tags、batch_save/batch_delete、跨实例持久化、工厂单例） |
| `TestUserIsolation`／`test_count_with_agent_id_filter` | `_passesIsolation` 三层门与共享组 | `tests/unit/memory/test_isolation_unified.py`（多处 `storage.query(isolation_context=…)`）＋ `tests/unit/cognitive/test_share_group_memory.py` |
| `TestClose`／`TestUpdateMemoryLifecycle`／`test_save_security_block/high_risk/sanitize`／`test_delete_cascade_relations` | 从未存在的门面与方法 | **无人守，也不该有**——把它们加回去就是复活第四条并行存储形态（教义第 6 条） |

本档钉四件**不许复活**，不止"文件没了"：

1. 旧档文件与模块路径都不存在（有人改成以包路径 import 也当场找不到）；
2. `tests/`＋`scripts/`＋`neurova/` 不得再有指向旧档的**裸引用行**——带「退役」二字的
   指针行除外（本仓惯例是原地留路标），本守卫档自身除外（它必须点名退役对象）；
3. `MemoryStorage.__init__` 的参数面仍**只有 `storage_dir`**，且类上不得重新出现
   `close` / `update_memory_lifecycle` / `update_metadata` / `wait_for_index_completion`
   这些旧档调过的死方法——为"让旧档跑起来"把它们加回去，本档当场红；
4. 反向控制：合成样本必须被 2 与 3 的扫描器点名，指针行与正常档不得误报。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLD_FILE = REPO_ROOT / "tests" / "unit" / "memory" / "test_storage_comprehensive.py"
STORAGE_PY = (
    REPO_ROOT / "neurova" / "cognitive_layers" / "memory_layer" / "storage.py"
)
OLD_NAME = "test_storage_comprehensive"
DEAD_METHODS = {
    "close",
    "update_memory_lifecycle",
    "update_metadata",
    "wait_for_index_completion",
}
SCAN_ROOTS = ("neurova", "tests", "scripts")

pytestmark = pytest.mark.timeout(60)


def _referenceLines(source: str) -> list:
    """指向旧档的行；带「退役」的指针行与本守卫档自身不算（本档由调用方排除）。"""
    bad = []
    for number, line in enumerate(source.splitlines(), start=1):
        if OLD_NAME in line and "退役" not in line:
            bad.append(number)
    return bad


def _liveStorageMethods() -> tuple:
    tree = ast.parse(STORAGE_PY.read_text(encoding="utf-8"))
    cls = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "MemoryStorage"
    )
    methods = {
        n.name for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    return methods, [a.arg for a in init.args.args]


def test_旧档文件与模块路径都不存在():
    assert not OLD_FILE.exists(), (
        f"旧档被复活：{OLD_FILE.relative_to(REPO_ROOT).as_posix()} —— "
        "它测的是从未落地的 SQLite 增强版设计，跑起来只会把死方法重新要一遍"
    )
    try:
        spec = importlib.util.find_spec("tests.unit.memory.test_storage_comprehensive")
    except ModuleNotFoundError:
        spec = None   # 父包在但模块不在——正是要的形态
    assert spec is None, f"旧档仍可按包路径 import：{spec}"


def test_引用面只剩指针():
    offenders = []
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts or path == Path(__file__):
                continue
            lines = _referenceLines(path.read_text(encoding="utf-8", errors="ignore"))
            if lines:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{lines}"
                )
    assert not offenders, (
        "这些行还按路径指向已退役的旧档（要留说明请带上「退役」二字）：" + "; ".join(offenders)
    )


def test_存储构造口与死方法面不得回退():
    methods, initArgs = _liveStorageMethods()
    assert initArgs == ["self", "storage_dir"], (
        f"`MemoryStorage.__init__` 的参数面变了：{initArgs} —— 旧档正是靠给它编造 "
        "db_path=/neuser_id=/enable_cache=/enable_batch_write= 才成立的；"
        "多出来的每一个参数都是第二条并行存储形态的入口（教义第 6 条）"
    )
    revived = sorted(DEAD_METHODS & methods)
    assert not revived, (
        f"旧档调过的死方法重新出现在 `MemoryStorage` 上：{revived} —— "
        "`close()`/`update_memory_lifecycle()`/`update_metadata()` 在全仓没有存储实现，"
        "加回来只为让旧档跑起来即是复活"
    )


def test_真JSON存储与隔离面确有活档在守():
    """退役的前提是"性质仍有人守"，本格把前提钉住：替代档在场且可被收集。

    否则将来任一档被删，旧档就会被当作"恢复覆盖"的理由捞回来。
    """
    live = REPO_ROOT / "tests" / "cognitive_layers" / "memory_layer" / "test_storage.py"
    iso = REPO_ROOT / "tests" / "unit" / "memory" / "test_isolation_unified.py"
    for path in (live, iso):
        assert path.exists(), f"替代覆盖档不见了：{path.relative_to(REPO_ROOT).as_posix()}"
    tree = ast.parse(live.read_text(encoding="utf-8"))
    cases = [
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test")
    ]
    assert len(cases) >= 18, f"真 JSON 存储契约的存活用例数掉到 {len(cases)}（原 18）"
    assert "storage.query(isolation_context=" in iso.read_text(encoding="utf-8").replace(" ", ""), (
        "存储级隔离断言不再经 `query(isolation_context=…)` —— `_passesIsolation` 失去守者"
    )


def test_扫描器真会咬():
    """反向控制：指针行不误报、裸引用必点名、死方法复活必点名。"""
    sample = "\n".join([
        f"from tests.unit.memory import {OLD_NAME} as m",              # 裸引用 → 该咬
        f"# 见 {OLD_NAME}.py 的退役说明",                                # 指针行 → 不该咬
    ])
    hits = _referenceLines(sample)
    assert hits == [1], f"引用扫描器分类错了：{hits}（应只点名第 1 行）"

    fake = (
        "class MemoryStorage:\n"
        "    def __init__(self, storage_dir):\n"
        "        self._dir = storage_dir\n"
        "    def close(self):\n"
        "        pass\n"
    )
    tree = ast.parse(fake)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    found = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert DEAD_METHODS & found == {"close"}, (
        f"死方法名集在合成样本上没咬住：{sorted(found)}"
    )
