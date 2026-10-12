# -*- coding: utf-8 -*-
"""退役 `neurova/skill/` 兼容 shim（用户 2026-10-12 裁「退役 shim，旧集成档另批分流」，台账 §6-165）。

## 为什么它该走

这个包只剩一个 `__init__.py`，自己的 docstring 写着它存在的理由是
"为了兼容现有测试代码中的导入语句"，并且逐条列明了它以前还挂过的 `skill_packer`
子模块如何随 Issue #46 退役。它暴露两个懒别名（`Skill`、`ExperienceRecord`）。

现场复算（本批落笔前重取，不抄旧台账）：

- **生产消费者 0 处**：`grep -rn "neurova\\.skill\\b"` 在 `neurova/` 里只命中它自己
  （口径同时收 `from neurova.skill import …` 与 `import neurova.skill`，
  并剔掉 `neurova.skills` / `neurova.skill_system` 两个真包——这三兄弟并存本身就是
  ADR 0011 记过的"同名包遮蔽同名文件"病灶的余波）；
- **测试消费者 1 处**：`tests/integration/test_full_chain.py:227` 要的是
  `create_default_skills`，而 shim 的懒映射表里**根本没有这个符号** ⇒
  实测 `ImportError: cannot import name 'create_default_skills' from 'neurova.skill'`。
  也就是说：它不是"还在替谁兼容"，它是**在给一条必失败的路径背书**；
- 两个别名本身也早已无人取用（上一批清掉 26 档 0 用例壳之后，最后的壳也没了）。

留着的代价不止是一层灰：它把"技能符号有几条取用路径"这个问题从两条变三条，
而每多一条，`import` 侧的遮蔽/降级故事就多一种长法。按教义第 7 条的固定顺序处理：
唯一实现在 `neurova.skills`（生产用的就是这条，`agent_core.py:862/1258/1517`）⇒
把那条测试 import 改指它（接线）⇒ 整包删净（退役清理，同批）。

**旧集成档不在本批**：`test_full_chain.py` 在 HEAD 侧就是 14 failed / 2 passed / 3 errors
（仓外 worktree 复算同读数），病根是 `router.route()` 早改成异步而那批用例还同步调——
与本 shim 无关，已另批分流登记。本批只负责"不再多给它一条死路"。
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHIM_DIR = PROJECT_ROOT / "neurova" / "skill"
SCAN_ROOTS = (PROJECT_ROOT / "neurova", PROJECT_ROOT / "tests", PROJECT_ROOT / "scripts")

#: shim 暴露的那两个名字（判据用得到，也用来证明"能力没被一起删掉"）。
SHIM_ALIAS_NAMES = ("Skill", "ExperienceRecord")


def _shimImportsInTree(tree: ast.AST) -> list:
    """从一棵 AST 里挑出「取用 `neurova.skill` 这个命名空间」的 import 节点，返回行号。

    按 **AST 形态**判而不是按正则扫文本：本档自己的 docstring 与反向对照样本里都要写一遍
    旧形态的字面量，文本包含检查会把这些也算成"还有人在用"（本仓记过的两头失真形态：
    同一份守卫既可能假红也可能放过违规，钉词的那头永远先失真）。
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == "neurova.skill":
            hits.append(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "neurova.skill":
                    hits.append(node.lineno)
    return hits


def _shimImportRows() -> list:
    hits = []
    for root in SCAN_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as e:  # 语法坏掉的档本身就该被别的守卫点名，这里不吞也不判
                raise AssertionError(f"{path} 解析失败，本判据无法判定：{e}") from e
            hits.extend("%s:%s" % (path.relative_to(PROJECT_ROOT), line)
                        for line in _shimImportsInTree(tree))
    return hits


class TestTheShimIsGone:
    def test_compatNamespaceIsNotImportable(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("neurova.skill")

    def test_packageDirectoryIsDeletedNotEmptied(self):
        """空目录也会让 `import neurova.skill` 在某些装配下成功（namespace package）——所以要查目录。"""
        assert not SHIM_DIR.exists(), (
            "`neurova/skill/` 还在（哪怕只剩 __init__.py 或空目录）：兼容面没退干净")

    def testNoSourceStillReachesTheShimNamespace(self):
        assert _shimImportRows() == [], (
            "这些行还在从 `neurova.skill` 取符号，退役就没完成：%s" % _shimImportRows())

    def testTheDetectorCatchesTheShapeItClaimsToCatch(self):
        """反向控制（守卫不许只会被动绿）：同一份 AST 检测在合成样本上一抓一放。

        只证"能抓"会放过误报，只证"不误报"会放过恒绿——两侧一起给。
        """
        caught = _shimImportsInTree(ast.parse(
            "from neurova.skill import create_default_skills\nimport neurova.skill\n"))
        assert sorted(caught) == [1, 2], caught

        for real in ("from neurova.skills import create_default_skills",
                     "from neurova.skill_system import get_skill_registry",
                     "from neurova.skills.models import Skill"):
            assert _shimImportsInTree(ast.parse(real)) == [], real


class TestTheCapabilityStillHasItsHome:
    """退役不等于删能力：两个别名与那条 import 要的工厂，选定单点都还在。"""

    def testSkillAndExperienceRecordRemainReachableAtTheSingleSource(self):
        models = importlib.import_module("neurova.skills.models")

        missing = [n for n in SHIM_ALIAS_NAMES if not hasattr(models, n)]
        assert not missing, "shim 那两个别名在选定单点里取不到：%s" % missing

    def testCreateDefaultSkillsIsReachableFromThePathProductionUses(self):
        """生产就是走这条（`agent_core.py:862/1258/1517`），改指它而不是另起一条。"""
        skills = importlib.import_module("neurova.skills")

        assert callable(skills.create_default_skills)

    def testTheRepointedConsumerImportsWhatItActuallyNeeds(self):
        """把 `test_full_chain.py` 那行按新契约写一遍，必须拿得到东西。

        它今天仍因异步契约而红（另批），所以这里**只验取用面**，不假装那格绿了。
        """
        from neurova.skills import create_default_skills

        assert create_default_skills.__name__ == "create_default_skills"


def test_shimIsNotStillRegisteredAsAFacadeSomewhere():
    """`sys.modules` 里也不该留着它——否则同一批符号在进程内还有第三条路径。"""
    importlib.invalidate_caches()

    assert "neurova.skill" not in sys.modules, (
        "进程里仍有 `neurova.skill` 这条模块路径（谁在导入它？）")
