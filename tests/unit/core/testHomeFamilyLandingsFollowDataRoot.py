"""家目录那族落点必须归数据根管（§6-203 登记「剩下六处不修」的那张表，本批收掉五处）。

为什么这批值得动手：`~/.neurova/` 下的东西**不受数据根注入管辖**。实测过一条真事故链——
`security/rbac.py:177` 在 `db_path` 缺省时落 `~/.neurova/rbac.db`，而测试里有 7 处 bare 构造
（`e2e/conftest.py:63`、`test_security_integration.py:33`、`test_rbac_comprehensive.py` 那几格），
`tests/conftest.py:57-58` 只注入了临时**数据根**、没管主目录 ⇒ 跑一次测试就在操作者主目录里
建出一个真库（本机那份 45056 字节的 `~/.neurova/rbac.db` 就是这么来的，`roles` 恰 5 行全
`is_system=1`、其余表 0 行，即只跑过 `_init_system_roles`）。**修在产生该状态的这一侧**
（落点自己），不去给 conftest 加"把 home 也隔掉"的第二道兜底——落点收进数据根后，
既有的临时数据根注入自动覆盖它，那道补丁根本不需要存在。

另两处（`benchmark/__init__.py:282`、`image_pipeline/__init__.py:180`）形状不同：它们不是 home，
是**裸相对** `".neurova/benchmark"`，即随 CWD 散落——同一件事在本仓已量过五处的代价（§6-202 那条
"裸文件名默认值让持久化文件随 cwd 散落"）。本批把落点正确性收掉；这两个字段本身**零消费点**
（`_storage_dir` 全文件仅此一处赋值），属"档案票二"那 5 个门面包实现的退役候选，登记在那张票里，
不在本批顺手删。

判据两轨：行为格从生产入口取数，钉"注入数据根后落点在那一根下、且不在主目录下"；
收养接线格钉 `dataLanding`/`adoptHomeLanding` 真的被调——只把字面量删掉而没接上单点，
是"看起来修好了"的另一种形态。反向钉由既有常驻守卫承担：`TestNoNewHomeLandingIsAllowed`
的豁免表本批从 6 条收到 1 条（只剩 `core/data_root.py` 那个收养端本身）。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import neurova

NEUROVA_DIR = Path(neurova.__file__).resolve().parent
#: 主目录族落点（§6-203 那张表里的真 home 两处 + rbac）
FAMILIES = {
    "security/rbac.py": ("dataLanding", "adoptHomeLanding"),
    "channels/wecom_aibot.py": ("dataLanding", "adoptHomeLanding"),
    "knowledge/config.py": ("dataLanding", "adoptHomeLanding"),
}


def _calledNames(relPath: str) -> set:
    tree = ast.parse((NEUROVA_DIR / relPath).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def testNoFamilyStillSpellsTheHomeLanding():
    """主红：五处里数到任何一处仍自己拼 `~/.neurova`，本批就没收干净。

    谓词与常驻守卫同形（值等于 `".neurova"` 或以 `".neurova/"` 开头的字符串常量），
    但扫的是**本批点名的这几个文件**——守卫那张表是全仓口径，本格钉的是这五处的归属。
    """
    offenders = []
    for rel in list(FAMILIES) + ["benchmark/__init__.py", "image_pipeline/__init__.py"]:
        path = NEUROVA_DIR / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hit = any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                  and (n.value == ".neurova" or n.value.startswith(".neurova/"))
                  for n in ast.walk(tree))
        if hit:
            offenders.append(rel)
    assert offenders == [], "仍自拼主目录/裸相对落点：%s" % offenders


def testEachFamilyIsActuallyWiredToTheSinglePoint():
    """接线锁：落点必须真的走 `dataLanding`（主目录旧物还得起 `adoptHomeLanding`）。"""
    notWired = []
    for rel, needed in FAMILIES.items():
        called = _calledNames(rel)
        missing = [n for n in needed if n not in called]
        if missing:
            notWired.append(f"{rel} 缺 {missing}")
    assert notWired == [], "只删字面量没接单点 ⇒ 旧物再也搬不过来：%s" % notWired


def testRbacLandsUnderTheInjectedDataRoot(tmp_path: Path, monkeypatch):
    """行为格：注入数据根后，bare 构造的 RBAC 库必须落在那一根下——而不是操作者主目录。

    这一格就是那台事故的复现：本机 `~/.neurova/rbac.db` 正是测试期 bare 构造写出来的。
    """
    from neurova.core import data_root
    from neurova.security.rbac import RBACManager

    monkeypatch.setenv(data_root.DATA_ROOT_ENV, str(tmp_path))
    manager = RBACManager()

    landed = Path(manager._db_path).resolve()
    assert str(landed).startswith(str(tmp_path.resolve())), (
        "rbac 库落在数据根之外（实得 %s）⇒ 主目录污染没修掉" % landed
    )
    assert landed != (Path.home() / ".neurova" / "rbac.db"), "还在写操作者主目录"


def testKnowledgeConfigPathFollowsTheDataRoot(tmp_path: Path, monkeypatch):
    """行为格（第二处）：知识库默认配置路径同上，且旧主目录那份在空缺时被收养而不是被忽略。"""
    from neurova.core import data_root
    from neurova.knowledge import config as kb_config

    monkeypatch.setenv(data_root.DATA_ROOT_ENV, str(tmp_path))
    landed = kb_config._get_default_config_path().resolve()
    assert str(landed).startswith(str(tmp_path.resolve())), (
        "知识配置默认路径不在数据根下（实得 %s）" % landed
    )


def testBareRelativeLandingsFollowTheDataRoot(tmp_path: Path, monkeypatch):
    """行为格（第三、四处）：裸相对 `".neurova/<包名>"` 随 CWD 走＝换目录就换一个库。

    只验落点归属，不验消费——这两个字段现读零消费点（档头写明），退役归属在档案票二。
    """
    from neurova.core import data_root

    monkeypatch.setenv(data_root.DATA_ROOT_ENV, str(tmp_path))
    monkeypatch.chdir(tmp_path)          # 旧形态在这里会算出 tmp_path/.neurova/... 之类的随 CWD 落点

    from neurova.benchmark import BenchmarkFramework
    from neurova.image_pipeline import ImagePipelineManager

    # 直接构造而不是走 `get_benchmark_framework()`：那是**进程级单例**（`_framework_instance`），
    # 一格把它指向临时根，同进程后续拿到的就是这一份——判据不该改进程级状态。
    bench = BenchmarkFramework()
    pipe = ImagePipelineManager()
    for label, value in (("benchmark", getattr(bench, "_storage_dir", None)),
                         ("image_pipeline", getattr(pipe, "_storage_dir", None))):
        assert value is not None, f"{label} 的 storage_dir 字段没了 ⇒ 本批动了形状"
        assert str(Path(value).resolve()).startswith(str(tmp_path.resolve())), (
            "%s 的 storage_dir 仍随 CWD 或仍指主目录（实得 %s）" % (label, value)
        )


def testScannerFaceSeesTheseFiles():
    """扫描面自证：这几处确实在共享枚举的覆盖里（掉出扫描面＝"全仓干净"是假的）。"""
    seen = {ref.path.relative_to(NEUROVA_DIR.parent).as_posix()
            for ref in ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", ("dataLanding",))}
    for rel in FAMILIES:
        assert f"neurova/{rel}" in seen, f"{rel} 不在 dataLanding 的取数面上 ⇒ 接线格会空转"
