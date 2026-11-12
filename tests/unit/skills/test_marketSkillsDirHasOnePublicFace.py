"""市场安装根目录只有一个公开读口（欠账队列第 4 条）。

现量根据（动手前实测）：跨模块直取私有 `_skills_dir` 的落点恰三处——
`api/endpoints/marketplace.py:413`／`:471`（把安装根递给注册层）与
`skills/market_registry.py:130`（缺省取法）。而 `:131` 那条 except 还**另抄了一遍**
`get_data_root()/"skills"`：单例可以被显式传目录构造，抄的那份与它不同源，
于是"取到一个看着像、其实不是"的目录比取不到更坏。
"""

import ast
from pathlib import Path

import pytest

from neurova.skills.market_importer import MarketImporter
from neurova.skills.market_registry import _default_market_skills_dir, _marketSourceDir
from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
#: 扫描根提到模块级（`test_scanCriterionMustProveItsOwnSurfaceRatchet` 只认模块级常量解根）
NEUROVA_ROOT = REPO_ROOT / "neurova"
# 私有字段的合法读者：定义它自己的类所在文件。
# （P1-13 退役：skill_packager.py 连同其 7 处直取已随本批删除，条目摘除。
#   这个数是本轮 AST 现量的，不是抄来的——只降不升，扩散即红。）
ALLOWED_OWNERS = {
    "neurova/skills/market_importer.py": 8,
}


def _attrReadSites():
    """现算全仓 `X._skills_dir` 属性读的文件→次数表（AST，不按字面子串猜）。

    枚举与解析都走共享预算（`tests/ast_scan` 的 `nodeScan`）：判据谓词是
    `<属性>.attr == "_skills_dir"`，连这串字都没出现的文件不可能命中，故 `hints`
    是**充分条件**而不是放宽——它把解析量从「代码总量」降到「命中面」。
    私有 `rglob + parseSource` 会把代码总量编码成墙钟上界
    （`tests/unit/test_ci_ast_scan_budget_guard.py` 的根因）。
    """
    hits: dict = {}
    for path, node in ast_scan.nodeScan(NEUROVA_ROOT, ".py", hints=("_skills_dir",)):
        if isinstance(node, ast.Attribute) and node.attr == "_skills_dir":
            rel = path.relative_to(REPO_ROOT).as_posix()
            hits[rel] = hits.get(rel, 0) + 1
    return hits


def test_公开读口交出的就是实例真正的安装根(tmp_path):
    importer = MarketImporter(skills_dir=tmp_path / "market-root")
    assert importer.marketSkillsDir() == tmp_path / "market-root"


def test_缺省取法与单例同一个目录而不是另推一份(tmp_path, monkeypatch):
    """跨模块一致性：注册层的缺省取法必须问公开口，不许自己算路径。"""
    from neurova.skills import market_importer as MI

    importer = MarketImporter(skills_dir=tmp_path / "explicit-root")
    monkeypatch.setattr(MI, "_market_importer", importer)
    assert _default_market_skills_dir() == tmp_path / "explicit-root"
    assert _marketSourceDir("whatever", None) in (None, tmp_path / "whatever")


def test_取不到来源时如实抛出而不是交出借路目录(monkeypatch):
    """撤掉抄来的兜底之后，这条必须真成立：异常不吞成「看着像的目录」。

    旧形态在 except 里回 `get_data_root()/\"skills\"`——那目录若恰好存在又碰上有同名子目录，
    就会把一个**与单例无关**的树当成安装来源交给 staging；本格按「如实抛出」判，旧形态当场红。
    """
    from neurova.skills import market_importer as MI

    def boom(*args, **kwargs):
        raise RuntimeError("importer 不可用")

    monkeypatch.setattr(MI, "get_market_importer", boom)
    with pytest.raises(RuntimeError):
        _default_market_skills_dir()
    assert _marketSourceDir("anything", None) is None   # 调用侧退化成「无真字节」


def test_私有字段只剩定义方自己读():
    scanned = len(ast_scan.filesUnder(NEUROVA_ROOT, ".py"))
    assert scanned > 500, "扫描面现算 %d 档——面缩了，零 offender 就是假绿" % scanned
    hits = _attrReadSites()
    strangers = {rel: n for rel, n in hits.items() if rel not in ALLOWED_OWNERS}
    assert strangers == {}, "又出现跨模块直取私有安装根：{}".format(strangers)
    grew = {rel: (n, ALLOWED_OWNERS[rel]) for rel, n in hits.items()
            if rel in ALLOWED_OWNERS and n > ALLOWED_OWNERS[rel]}
    assert not grew, "定义方内部也在扩散私有字段读取，收口未成立：%s" % grew


def test_端点两处都经公开口():
    src = (REPO_ROOT / "neurova" / "api" / "endpoints" / "marketplace.py").read_text(
        encoding="utf-8")
    assert src.count("importer.marketSkillsDir()") == 2, "安装根递下来的两处必须都在"
    assert "importer._skills_dir" not in src, "端点还在直取私有成员"
