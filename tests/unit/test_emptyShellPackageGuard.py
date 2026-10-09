# -*- coding: utf-8 -*-
"""包树里不得留「零模块空壳包」（§9 序 2 的收口面，防再生）。

来历（两处残留，形态不同但同一类）：

1. `neurova/utils`、`neurova/capabilities`、`neurova/builder` —— 三个**只有一个 docstring**
   的 `__init__.py`，由 `98b5422a`（2026-06-09「清理临时文件，升级版本号，完善模块结构」）
   引入。同一笔还留下了 `neurova/expected`（0 字节重定向残留，§6-92 已收）。
   全仓实测：三者的 import 引用面为 **0**（`neurova/`、`tests/`、`scripts/`、`NeurUI/src/`
   四处扫净），也没有任何 `importlib`/`pkgutil` 按名字枚举到它们——纯占位壳。
2. `neurova/storage` —— 包内**已无一个模块**：它唯一的实现
   `zero_downtime_migration.py` 早在 `migration_api` 那批就被退役（记录在
   `tests/unit/endpointWiringBaseline.txt:58-64`：7 阶段实现"全是 pass"、
   `rollback_migration` 恒 False、`verify_migration` 恒 True，属"以假形态冒充能力"，
   故端点与桩实现同批删）。留下的目录里只剩 `covers/` 20 张图（1.3MB，内容互不重复），
   而 `git log -S "storage/covers"` 全历史**零命中**——这堆素材从入库起就没有读者。
   真实的 schema 演进唯一入口是 `neurova/core/db_migration.py`（PRAGMA user_version 注册表），
   Studio 侧封面读数是 `projects.thumbnail` 列，产物落点是 `GENERATION_OUTPUT_DIR`——
   都不依赖这几张随包图片。

只删一次不算闭环：同一形态再来一次没人会红。所以按**类**判——
"`__init__.py` 所在目录的子树里找不到任何其它 `.py`"即为空壳，一律不许存在。
本文件自带两档反向对照：造一枚空壳必须被抓到（防"扫空即绿"），
有真实模块的包（`neurova/knowledge` 那一类）不得误伤（防谓词过宽）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO / "neurova"
pytestmark = pytest.mark.timeout(60)


def _isDocstringOnlyInit(path: Path) -> bool:
    """`__init__.py` 里除一个裸字符串外什么都没有 ⇒ 这个包门面是空壳。

    本谓词必须**两**个条件同时成立才判空壳。只看"子树里没有别的 .py"会误伤
    `neurova/execution_layers` 与 `neurova/skill`——那两个包把实现写在 `__init__.py` 里
    （首跑就被这么误伤过，实状见下面 `test_packagesWithRealModulesAreNotFlagged`）。
    """
    import ast

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return False
    return all(isinstance(n, ast.Expr) for n in tree.body) and (
        len(tree.body) == 0 or (len(tree.body) == 1 and isinstance(tree.body[0].value, ast.Constant)
                                and isinstance(tree.body[0].value.value, str)))


def _shellPackages(root: Path) -> list[str]:
    """`root` 树里的"零模块空壳包"（返回相对 `root` 的目录名，排序稳定）。

    空壳 ＝ 本目录的 `__init__.py` 只有一个 docstring，**且**整个子树里再没有别的模块。
    纯数据子目录（如当年的 `covers/`）不改变判定——那正是本类要抓的形态。
    """
    shells: list[str] = []
    for init in sorted(root.rglob("__init__.py")):
        pkgDir = init.parent
        if "__pycache__" in pkgDir.parts or not _isDocstringOnlyInit(init):
            continue
        hasOtherModule = any(p.name != "__init__.py" and "__pycache__" not in p.parts
                             for p in pkgDir.rglob("*.py"))
        if not hasOtherModule:
            shells.append(pkgDir.relative_to(root).as_posix())
    return shells


def test_neurovaTreeHasNoShellPackage():
    found = _shellPackages(PKG_ROOT)
    assert not found, (
        f"neurova/ 里还有零模块空壳包：{found}\n"
        "它们让 `import neurova.xxx` 这种名字看起来「存在一个子系统」，而实际什么都不会发生；"
        "要留就把它接上真模块，要留档就写进退役记录，别留结构壳。")


def test_scannerReallyCatchesAShell(tmp_path):
    """反向对照①：造一枚空壳必须被抓到——不然上面那条断言是"扫空即绿"。"""
    (tmp_path / "brandnew").mkdir()
    (tmp_path / "brandnew" / "__init__.py").write_text('"""占位。"""\n', encoding="utf-8")
    assert _shellPackages(tmp_path) == ["brandnew"]

    # 再补一个纯数据子目录：加了数据文件仍属空壳，判定不该被它洗白
    (tmp_path / "brandnew" / "assets").mkdir()
    (tmp_path / "brandnew" / "assets" / "a.png").write_bytes(b"PNG")
    assert _shellPackages(tmp_path) == ["brandnew"], "纯数据子目录把空壳洗成了「非空壳」"


def test_packagesWithRealModulesAreNotFlagged(tmp_path):
    """反向对照②：有真模块的包、以及真模块在子包里的那一层，都不该被误伤。"""
    (tmp_path / "withmod").mkdir()
    (tmp_path / "withmod" / "__init__.py").write_text('"""门面。"""\n', encoding="utf-8")
    (tmp_path / "withmod" / "impl.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "__init__.py").write_text('"""只有 docstring。"""\n', encoding="utf-8")
    sub = tmp_path / "nested" / "deep"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "work.py").write_text("Y = 2\n", encoding="utf-8")
    assert _shellPackages(tmp_path) == [], (
        f"误伤了有代码的包：{_shellPackages(tmp_path)}")

    # 现网实据：`neurova/knowledge`（16 个模块 + 5 个子包）绝不在射程内
    found = _shellPackages(PKG_ROOT)
    assert "knowledge" not in found
    # 这一格是首跑误伤之后补的：`execution_layers`(706 行) 与 `skill`(45 行) 都把实现
    # 写在 `__init__.py` 里、子树内没有别的 .py ——形态与空壳相同而实质完全不同
    for real in ("execution_layers", "skill"):
        assert real not in found, f"把代码写在 `__init__.py` 里的真包 {real} 误判成空壳"

    # 同形态的替身对照：实现写在 `__init__.py` 里 → 不判空壳
    (tmp_path / "inline").mkdir()
    (tmp_path / "inline" / "__init__.py").write_text("Z = 3\n", encoding="utf-8")
    assert "inline" not in _shellPackages(tmp_path)


def test_scanRootActuallyCoversTheTree():
    """防"扫描根写错→无事发生却报绿"：覆盖性当场数一遍。"""
    inits = [p for p in PKG_ROOT.rglob("__init__.py") if "__pycache__" not in p.parts]
    assert len(inits) > 50, f"扫描根 {PKG_ROOT} 只找到 {len(inits)} 个包，路径层级写错了"
