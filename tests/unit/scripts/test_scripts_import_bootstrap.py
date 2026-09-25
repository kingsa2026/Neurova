"""脚本以文件路径直接执行时，`neurova` 必须在导入期就可见。

病灶（PR #105 引入，CI 两条流水线同时红）：

`scripts/ci/experience_quality_gate.py` 为把落点收进数据根，在文件顶部加了
`from neurova.core.data_root import get_data_root`，**但那一行在把仓库根放进
`sys.path` 之前**。于是 `python scripts/ci/experience_quality_gate.py` 在 CI
（`pip install` 依赖、未 `pip install -e .`）下必然
`ModuleNotFoundError: No module named 'neurova'`——门禁脚本根本跑不起来。

同一批把 `resolveDataPath` / `get_data_root` 前置引入的另外几个脚本同形：
`demo_closed_loop.py`、`demo_optimization.py`、`diagnostics/check_databases.py`、
`diagnostics/check_users_db.py`、`diagnostics/skill_name_collisions.py`、
`diagnostics/_live_verify_growth_split.py`。它们"以前能跑"只是因为不导入
项目包：一旦落点改经数据根推导，导入顺序就成了能否启动的前置条件。

判据：脚本内任何 `import neurova...` 语句之前，必须已经有一个把**仓库根**
放进 `sys.path` 的调用。不是"文件里有 sys.path.insert"就算——顺序错了
等于没有（这正是本批的形态）。

为什么不用 `pip install -e .` 兜底：`.cnb.yml` 的 experience-quality 流水线装的是
`requirements-ci.txt`（运行依赖），scripts 靠"从仓库根执行"拿到包；把顺序纪律
交给安装方式，换台机器/换个命令就复发。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

# 把仓库根放进 sys.path 的形态：层数反推（parents[N] / ".."*N）或根常量。
_ROOT_TEXT_MARKERS = ("parents[", "REPO_ROOT", "PROJECT_ROOT", "dirname(__file__)")
_ROOT_NAMES = {"ROOT", "PROJECT_ROOT", "REPO_ROOT", "_REPO_ROOT", "PROJECT_ROOT_PATH"}


def _isRepoRootBootstrap(node: ast.AST) -> bool:
    """该语句是否把仓库根放进 sys.path（只认 insert/append 到 sys.path 的调用）。"""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    call = node.value
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr not in ("insert", "append"):
        return False
    if not isinstance(func.value, ast.Attribute) or func.value.attr != "path":
        return False
    if not isinstance(func.value.value, ast.Name) or func.value.value.id != "sys":
        return False
    if not call.args:
        return False
    target = ast.unparse(call.args[-1]).strip()
    if any(marker in target for marker in _ROOT_TEXT_MARKERS):
        return True
    # `str(ROOT)` / `ROOT` 这类具名常量：名字须落在根常量的命名集合里。只认这些
    # 名字是因为它们在本仓已被大量用作"仓库根"——脚本自己的目录另有
    # `os.path.dirname(os.path.abspath(__file__))` 形态，它拿不到 neurova 包，
    # 故不在此集合内（见反向控制那条）。
    if target in _ROOT_NAMES or target in {"str(%s)" % n for n in _ROOT_NAMES}:
        return True
    return False


def _bootstrapLine(tree: ast.AST) -> int | None:
    """首次把仓库根放进 sys.path 的行号（取最小行——`ast.walk` 非源序）。"""
    lines = [node.lineno for node in ast.walk(tree) if _isRepoRootBootstrap(node)]
    return min(lines) if lines else None


def _firstNeurovaImportLine(tree: ast.AST) -> int | None:
    """首次导入 `neurova` 的行号（取最小行，理由同上）。"""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("neurova"):
            lines.append(node.lineno)
        elif isinstance(node, ast.Import) and any(
            alias.name.startswith("neurova") for alias in node.names
        ):
            lines.append(node.lineno)
    return min(lines) if lines else None


def _scannedScripts() -> list[Path]:
    """`scripts/` 下的源码清单（走共享入口，解析量不随代码总量涨）。

    Issue #148 / #197：本判据原先自己 `SCRIPTS_ROOT.rglob("*.py")` + 逐文件
    `ast.parse`。`scripts/` 如今只有 61 个文件、成本尚小，但**形态**与
    Issue #148 的根因同款——判据只谈「导入顺序对不对」，与脚本总数无关。
    枚举与解析各收口一处：`ast_scan.filesUnder` + `_cachedParse`，
    与其余跨文件判据复用同一份缓存。
    """
    return ast_scan.filesUnder(SCRIPTS_ROOT, ".py")


def _offenders() -> list[str]:
    found = []
    for path in _scannedScripts():
        try:
            tree = ast_scan._cachedParse(ast_scan._cacheKey(path), ast_scan.sourceCode(path))
        except SyntaxError:
            continue
        first_import = _firstNeurovaImportLine(tree)
        if first_import is None:
            continue
        bootstrap = _bootstrapLine(tree)
        if bootstrap is None:
            found.append(
                "%s:%d: 导入 neurova 但从未把仓库根放进 sys.path"
                % (path.relative_to(PROJECT_ROOT), first_import)
            )
        elif bootstrap > first_import:
            found.append(
                "%s: 第 %d 行导入 neurova，仓库根却在第 %d 行才进 sys.path"
                % (path.relative_to(PROJECT_ROOT), first_import, bootstrap)
            )
    return found


class TestScriptsCanBeRunByPath:
    """`python scripts/<x>.py` 是 CI 与运维的真实调用方式，必须能启动。"""

    def test_repoRootEntersSysPathBeforeNeurovaImport(self):
        offenders = _offenders()
        assert offenders == [], (
            "以下脚本以文件路径执行时必然 ModuleNotFoundError: No module named 'neurova'：\n  %s\n"
            "修复：把仓库根进 sys.path 的语句移到所有 `from neurova...` 之前。"
            % "\n  ".join(offenders)
        )

    def test_scannerHasTeethOnKnownShapes(self, tmp_path):
        """反向控制：扫描器必须真认得出"顺序错"与"顺序对"两种形态。"""
        bad = tmp_path / "bad.py"
        bad.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "from neurova.core.data_root import get_data_root\n"
            "ROOT = Path(__file__).resolve().parents[2]\n"
            "sys.path.insert(0, str(ROOT))\n",
            encoding="utf-8",
        )
        good = tmp_path / "good.py"
        good.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "ROOT = Path(__file__).resolve().parents[2]\n"
            "sys.path.insert(0, str(ROOT))\n"
            "from neurova.core.data_root import get_data_root\n",
            encoding="utf-8",
        )
        missing = tmp_path / "missing.py"
        missing.write_text(
            "from neurova.core.data_root import get_data_root\n",
            encoding="utf-8",
        )
        syspath_other = tmp_path / "other.py"
        syspath_other.write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            "from neurova.core.data_root import get_data_root\n",
            encoding="utf-8",
        )

        assert _bootstrapLine_obj(bad) is not None and _bootstrapLine_obj(good) is not None
        assert _bootstrapLine_obj(missing) is None
        # 只改脚本自己所在目录（不是仓库根）不算数——它拿不到 neurova 包
        assert _bootstrapLine_obj(syspath_other) is None

    def test_guardIsListedInProtectedSubset(self):
        listed = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt").read_text(
            encoding="utf-8"
        )
        assert "tests/unit/scripts/test_scripts_import_bootstrap.py" in listed, (
            "本守卫不在受保护子集里，CI 不会跑它"
        )


def _bootstrapLine_obj(path: Path) -> int | None:
    """测试用：直接对临时文件断言扫描器判定。"""
    return _bootstrapLine(ast.parse(path.read_text(encoding="utf-8")))
