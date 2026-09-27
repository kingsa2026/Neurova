# -*- coding: utf-8 -*-
"""种子记忆库落点：换锚后的存量必须被收养（Issue #290 同一根因的第二批命中点）。

## 根因（与渠道配置同源，取证报告 §2.8）

`721ef038` 把八个种子脚本的落点从 `neurova/memory/data/yi_ling_memory.db`
（`Path(__file__).parent.parent / "data"` 反推）换到数据根，**存量没跟着搬**。
换锚后 `init_db.py` / `init_memories.py` 一跑就在新落点建一个空库，
旧锚点那份种子记忆（mtime 08-28）从此无人读也不被清 —— "种子记忆不可见"。

## 判据

1. 八个脚本的落点必须**同源**（`seedDbPath()` 单点），不得各推一份旧锚点；
2. 旧锚点有存量、新落点空缺 → 取落点即收养，读到原库且旧物不再存在；
3. 幂等 / 不覆盖：新落点已在时旧物不动（旧物只作空缺时的救济）；
4. 反向控制：伪仓库根下无旧物时不得凭空造出文件。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan

from neurova.core import data_root
from neurova.memory.scripts import seed_db_landing

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = PROJECT_ROOT / "neurova" / "memory" / "scripts"

SEED_SCRIPTS = (
    "init_db",
    "init_memories",
    "save_guardian_story",
    "save_kai_letter",
    "save_kai_letter_3",
    "save_precious_memories",
    "save_tonight_story",
    "save_vue_frontend_memories",
)


def _filenameLiterals(path: Path) -> list:
    """脚本正文里把库名当字面量用的位置（文档串不算：那是说明，不是落点）。

    按 AST 取，不按文本子串 —— 文本判据会把 docstring 里的文件名一起判红，
    而"提到过这个名字"与"拿它拼落点"是两件事。
    """
    tree = ast_scan.transientTree(path)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "yi_ling_memory.db" in node.value and id(node) not in docstrings
    ]


class TestSeedScriptsShareOneLanding:
    """判据 1：落点单点 —— 八个脚本不得各写一份旧锚点定义。"""

    @pytest.mark.parametrize("name", SEED_SCRIPTS)
    def test_scriptGoesThroughTheSingleLanding(self, name):
        path = SCRIPTS_ROOT / ("%s.py" % name)
        source = path.read_text(encoding="utf-8")

        assert "seedDbPath()" in source, "落点未走单点 seedDbPath()"
        assert _filenameLiterals(path) == [], (
            "脚本正文里又出现了库名 —— 落点（含文件名）只准在单点里定义，"
            "各写一份就是把同一个落点定义散成第二份源"
        )

    def test_legacyAnchorIsDeclaredOnce(self):
        """全仓只准一处声明旧锚点（AGENTS.md 第 6 条）。"""
        offenders = []
        for path in (PROJECT_ROOT / "neurova").rglob("*.py"):
            if path == Path(seed_db_landing.__file__):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if '"memory", "data"' in text:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

        assert offenders == [], "旧锚点被抄到别处：%s" % offenders


@pytest.fixture()
def landing(tmp_path, monkeypatch):
    """双锚点：旧锚点在伪仓库根下，新落点在临时数据根下（都不碰真实目录）。"""
    legacy_root = tmp_path / "repo"
    legacy = legacy_root.joinpath(*seed_db_landing.LEGACY_SEED_PARTS)
    legacy.parent.mkdir(parents=True)
    target_root = tmp_path / "dataRoot"

    monkeypatch.setattr(data_root, "repoRoot", lambda: legacy_root)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(target_root))
    return legacy, target_root


class TestLegacySeedDbIsRelocated:
    def test_legacySeedDbIsAdopted(self, landing):
        legacy, target_root = landing
        legacy.write_bytes(b"seed-bytes")

        resolved = seed_db_landing.seedDbPath()

        assert resolved == target_root / "yi_ling_memory.db"
        assert resolved.read_bytes() == b"seed-bytes", "旧锚点的种子库没被收养"
        assert not legacy.exists(), "旧物应已搬走，不该留两份"

    def test_existingTargetWins(self, landing):
        legacy, target_root = landing
        target = target_root / "yi_ling_memory.db"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"new")
        legacy.write_bytes(b"old")

        assert seed_db_landing.seedDbPath().read_bytes() == b"new", "新落点被旧物覆盖了"

    def test_noLegacyMeansNoFile(self, landing):
        """反向控制：无旧物时取落点不得凭空造文件（它只解析，不建库）。"""
        legacy, target_root = landing

        resolved = seed_db_landing.seedDbPath()

        assert not resolved.exists(), "落点解析凭空造了文件"
        assert not legacy.exists()
