"""家目录那族落点必须归数据根管（§6-203 登记「剩下六处不修」的那张表，本批收掉五处）。

为什么这批值得动手：`~/.neurova/` 下的东西**不受数据根注入管辖**。实测过一条真事故链——
`security/rbac.py:177` 在 `db_path` 缺省时落 `~/.neurova/rbac.db`，而测试里有 7 处 bare 构造
（`e2e/conftest.py:63`、`test_security_integration.py:33`、`test_rbac_comprehensive.py` 那几格），
`tests/conftest.py:57-58` 只注入了临时**数据根**、没管主目录 ⇒ 跑一次测试就在操作者主目录里
建出一个真库（本机那份 45056 字节的 `~/.neurova/rbac.db` 就是这么来的，`roles` 恰 5 行全
`is_system=1`、其余表 0 行，即只跑过 `_init_system_roles`）。**修在产生该状态的这一侧**
（落点自己），不去给 conftest 加"把 home 也隔掉"的第二道兜底——落点收进数据根后，
既有的临时数据根注入自动覆盖它，那道补丁根本不需要存在。

另两处（`benchmark/__init__.py`、`image_pipeline/__init__.py` 的 `_storage_dir`）形状不同：它们不是 home，
是**裸相对** `".neurova/<包名>"`，即随 CWD 散落——同一件事在本仓已量过五处的代价（§6-202 那条
"裸文件名默认值让持久化文件随 cwd 散落"）。本批把落点正确性收掉；这两个字段本身**零消费点**
（`_storage_dir` 全文件仅此一处赋值），属票④那 6 个门面包实现的退役候选，登记在那张票里，不在本批顺手删。
**两处后来的收场记在这里**：`benchmark` 那半随票④第一包的门面实装退役一起消失（该包现在只剩
`rag_eval`／`rag_dataset_gen` 两个子模块）；`image_pipeline._storage_dir` 随票④第三包按 §2 断点条款
删除——"写出无人读的字段"该接线或删除，而它连一个读方都没有，本档那格也就成了
**替一次从未发生过的持久化钉落点**。两格都改成了全仓形状哨兵（见 `test_noBareRelativeLandingSurvivesAnywhere`），
以后再冒出第六、七处，同一格拦得住。

判据两轨：行为格从生产入口取数，钉"注入数据根后落点在那一根下、且不在主目录下"；
收养接线格钉 `dataLanding`/`adoptHomeLanding` 真的被调——只把字面量删掉而没接上单点，
是"看起来修好了"的另一种形态。反向钉由既有常驻守卫承担：`TestNoNewHomeLandingIsAllowed`
的豁免表本批从 6 条收到 1 条（只剩 `core/data_root.py` 那个收养端本身）。

第五处是 CLI 的 REPL history，与前四处不同族也不同形：旧落点挂在**主目录根**上
（`~/.neurova_repl_history`，不在 `~/.neurova/` 下），家目录那张表一直看不见它；且它是
**模块级常量**，import 即定值，注入数据根对一个已固化的常量无能为力。收它时踩到自家家规：
第一版直接调无闸的 `adoptLandingFrom` 搬主目录文件——那正是 §6-203/204 实测事故的形状
（跑测把操作者的凭据搬进临时根）。故收养端补一个同闸的入口 `adoptHomeRootLanding`，
取法不同而权利判定同一份；本档那三格收养行为钉的就是这道闸。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan

import neurova
from neurova.core import data_root
from tests.ast_scan import parseSource

NEUROVA_DIR = Path(neurova.__file__).resolve().parent
#: 主目录族落点（§6-203 那张表里的真 home 两处 + rbac）
FAMILIES = {
    "security/rbac.py": ("dataLanding", "adoptHomeLanding"),
    "channels/wecom_aibot.py": ("dataLanding", "adoptHomeLanding"),
    "knowledge/config.py": ("dataLanding", "adoptHomeLanding"),
}


def _calledNames(relPath: str) -> set:
    tree = parseSource((NEUROVA_DIR / relPath).read_text(encoding="utf-8"))
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
        tree = parseSource(path.read_text(encoding="utf-8"))
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


def _relativeHomeLandingConstants(relPath: str) -> list:
    """该文件里**以代码身份**出现的裸相对落点字符串（`".neurova/xxx"` 这种以它开头的字面量）。

    为什么不能按文本判：`security/rbac.py` 等处的说明里写着"旧 `~/.neurova/rbac.db`"，
    那是**交代来历**、不是落点。按词判会让哨兵被自家文档撞红（本仓这一形已栽过两次），
    所以取 AST 的 `Constant` 且只认"字符串本身以 `.neurova/` 开头"——真·裸相对默认值正是这个形状。
    """
    tree = parseSource((NEUROVA_DIR / relPath).read_text(encoding="utf-8", errors="replace"))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value.startswith(".neurova/"):
            hits.append((node.lineno, node.value))
    return hits


def test_noBareRelativeLandingSurvivesAnywhere():
    """主格（第三、四处收完后改成哨兵）：全仓不许再有"裸相对 `.neurova/...`"落点。

    原本这格是**逐个构造对象**验落点在数据根下。两处 subject 各自收场了：
    `benchmark` 那半随门面实装退役（票④第一包），`image_pipeline._storage_dir` 那半是
    §2 断点条款里的"写出无人读的字段"——它连一个读方都没有，那格其实是
    **替一次从未发生过的持久化钉落点**（票④第三包删除）。
    所以判据换成全仓形状哨兵：以后再来第五、六处，同一格就拦得住。
    """
    candidates = {ref.path.relative_to(NEUROVA_DIR).as_posix()
                  for ref in ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", (".neurova/",))}
    offenders = {rel: _relativeHomeLandingConstants(rel) for rel in candidates
                 if _relativeHomeLandingConstants(rel)}
    assert not offenders, (
        "这些文件里还留着裸相对落点字面量（随 CWD 散落，注入数据根管不到它）：%s" % offenders
    )
    landingRefs = [ref.path.name for ref in
                   ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", ('dataLanding("image_pipeline"',))
                   if ref.path.name != "data_root.py"]
    assert not landingRefs, f"image_pipeline 的落点解析没随断点一起收掉：{landingRefs}"


def test_imagePipelineManagerStillWorksWithoutTheRetiredField():
    """交付锁：删字段与参数删的是**死面**，管理器这条活路必须照常（端点三处在调它）。

    失效方向＝删过头：模板或构建记录面一旦被带走，这一格当场红。
    """
    from neurova.image_pipeline import ImagePipelineManager, get_image_pipeline_manager

    manager = ImagePipelineManager()
    assert not hasattr(manager, "_storage_dir"), "只写不读的字段还在 ⇒ 断点没收口"
    assert get_image_pipeline_manager() is get_image_pipeline_manager(), "单例语义被改动"
    templates = manager.list_templates()
    assert len(templates) > 0, f"默认模板没了（现读 {len(templates)}）⇒ 管理器被删过头"
    assert manager.get_builds(limit=10) == [], "新建管理器不该带历史构建记录"


@pytest.fixture()
def fakeHome(tmp_path: Path, monkeypatch) -> Path:
    """把 `Path.home()` 指到临时目录——真主目录本轮一个字都不碰。"""
    home = tmp_path / "fakeHome"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return home


def _loadCliFace():
    """按**仓根那份文件的绝对路径**加载 CLI 门面，不用 `import_module("cli") + reload`。

    `reload` 重跑的是 `sys.modules["cli"]` **当前指向的那份文件**——整目录跑时"谁先导入"
    决定了那份是谁。实测踩坑：A/B 的基线树里 `cli.py` 是未修的旧形态，这一格却绿了，
    因为同进程先导入的是主树那份已修的 `cli.py`；判据换了采集顺序就失去咬合力。
    路径按 `__file__` 反推仓根，不写死机器路径。
    """
    from importlib.util import module_from_spec, spec_from_file_location

    cliPath = Path(__file__).resolve().parents[3] / "cli.py"
    spec = spec_from_file_location("cliFaceUnderTest", cliPath)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seedHomeHistory(home: Path, payload: str = "SENTINEL-HISTORY") -> Path:
    legacy = home / ".neurova_repl_history"
    legacy.write_text(payload, encoding="utf-8")
    return legacy


def _foreignRoot(monkeypatch, tmp_path: Path) -> Path:
    """数据根显式指到**不等于默认推导**的一址（跑测临时根、取证探针根都是这形状）。"""
    monkeypatch.setattr(data_root, "_REPO_ROOT", tmp_path / "theOperatorsRepo")
    injected = tmp_path / "elsewhereRoot"
    monkeypatch.setenv(data_root.DATA_ROOT_ENV, str(injected))
    return injected


def testReplHistoryLandsInTheDataRootAndIsNotFrozenAtImport(tmp_path: Path, monkeypatch):
    """行为钉（第五处）：CLI 的 REPL history 从 `~/.neurova_repl_history` 收进数据根。

    这条与其余四处不同形，两件事都得钉：
    ① 旧落点在**主目录根**上（不在 `~/.neurova/` 下），所以守卫那张表看不见它——
       不收就会一直漏；② 它原先是**模块级常量**，import 那一刻就把路径定死了，
       注入数据根对一个已 import 的常量毫无办法（本仓 conftest 那段"构造期定死"的老账同形）。
       ② 的判据形状是"换了根，同一次 exec 出来的模块也要跟着换落点"——常量形态下
       第二次设 env 后调用仍读到老值。
    """
    first = _foreignRoot(monkeypatch, tmp_path)
    cli = _loadCliFace()
    second = tmp_path / "secondRoot"
    monkeypatch.setenv(data_root.DATA_ROOT_ENV, str(second))

    path = cli.replHistoryPath()
    assert str(Path(path).resolve()).startswith(str(second.resolve())), (
        "换根后仍指着上一次解析的落点（实得 %s，本轮根 %s）⇒ 常量形态，注入无效"
        % (path, second)
    )
    assert str(first) not in str(path), "同一模块实例把第一次的根记成了默认值"
    assert not str(path).endswith(".neurova_repl_history"), (
        "还指着主目录根那份（实得 %s）⇒ 收了函数没收落点" % path
    )


def testForeignRootDoesNotStealTheOperatorsHistory(fakeHome: Path, tmp_path: Path, monkeypatch):
    """收养那一族的家规同样管主目录根那份：数据根指到别处时一个字都不动。

    本批判据自身就是这一格的受害面——先前写的是无闸的 `adoptLandingFrom`，跑测注入临时根
    时会把操作者自己的历史搬进 `Temp/neurovaDataRoot-<随机>/`（§6-203 那次实测事故的形状）。
    """
    injected = _foreignRoot(monkeypatch, tmp_path)
    legacy = _seedHomeHistory(fakeHome)
    cli = _loadCliFace()

    path = cli.replHistoryPath()
    pathParent = Path(path).parent

    assert legacy.read_text(encoding="utf-8") == "SENTINEL-HISTORY", "操作者的历史被搬进了临时根"
    assert not (pathParent / "repl_history").exists(), (
        "别处根下凭空长出一份历史＝同一份东西两个落点（未收养时新落点必须不存在）"
    )
    assert str(injected) in str(path), "落点本身没在注入的根下，后面两条断言就是空转"


def testOperatorsOwnRootStillAdoptsTheHistory(fakeHome: Path, tmp_path: Path, monkeypatch):
    """闸不是总开关：操作者自己的默认根下照常收养，换根不让他丢掉历史。"""
    repo = tmp_path / "repo"
    monkeypatch.setattr(data_root, "_REPO_ROOT", repo)
    monkeypatch.delenv(data_root.DATA_ROOT_ENV, raising=False)
    legacy = _seedHomeHistory(fakeHome)
    cli = _loadCliFace()

    path = cli.replHistoryPath()

    assert Path(path).read_text(encoding="utf-8") == "SENTINEL-HISTORY", "升级路径没收进旧历史"
    assert not legacy.exists(), "旧那份留在原地＝同一份历史两个落点"


def testHistoryParentDirExistsBeforeWrite(tmp_path: Path, monkeypatch):
    """落点自己备齐父目录：写侧是 `except OSError: pass`，缺目录会静默变成"历史没存"。"""
    _foreignRoot(monkeypatch, tmp_path)
    cli = _loadCliFace()

    path = cli.replHistoryPath()

    assert Path(path).parent.is_dir(), (
        "父目录没建 ⇒ `_save_history` 的 FileNotFoundError 被 `except OSError: pass` 吞掉，"
        "界面上看着一切正常、历史一条不存"
    )


def testScannerFaceSeesTheseFiles():
    """扫描面自证：这几处确实在共享枚举的覆盖里（掉出扫描面＝"全仓干净"是假的）。"""
    seen = {ref.path.relative_to(NEUROVA_DIR.parent).as_posix()
            for ref in ast_scan.sourceRefsUnder(NEUROVA_DIR, ".py", ("dataLanding",))}
    for rel in FAMILIES:
        assert f"neurova/{rel}" in seen, f"{rel} 不在 dataLanding 的取数面上 ⇒ 接线格会空转"
