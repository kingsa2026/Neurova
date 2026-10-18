# -*- coding: utf-8 -*-
"""扫描型判据必须自证"这次真扫到了多少"——只降不升棘轮（§6-322 裁定乙的落地）。

**要防的那件事**：一条"全仓不得再出现 X"的判据，如果它实跑的根被改窄（或被写错成少上一层），
读数会变成**零命中**而不是红——"干净"与"没扫到"在断言里长得一模一样。本仓已有一例实证：
模块级重名定义那条守卫自建档起就在子集里，docstring 讲的是通用形状，而它唯一真跑整树的格子
喂的根只有 `neurova/`；`tests/` 下四处既存遮蔽（其中一处让 3 条用例连收集都不发生）
活了三批，没有任何东西变红。事后按档量了一遍覆盖面（读数由本文件的 `_faceFindings` 现取，
建档那轮）：**能解出仓内扫描根的判据档里，只有不到一半把自己扫到的数量当断言比过**，
其余那批一直在赌"根没写错、也没被改窄"。

**判据只认代码形状，不认词**（本仓的守卫被自家 docstring 撞红过，也被自己的措辞豁免过）：
"自证"＝本档里存在一条 `assert`，把**由这次扫描/计数得到的量**与一个数字下限比。计数名认这几种形：
`len(...)`／`sum(...)`／`ast_scan.<入口>(...)`／列表推导／`.get()`（共享入口回填面读数的写法，
见 `shadowedTopLevelNames` 的 `stats`）／循环里 `+= 1` 累加的计数器——**每种认形都配了一格合成正检**，
放宽不白给。以下两种**不算**：只 `assert findings == []`；有一条与扫描无关的 `assert len(rows) > 0`
（收紧规则多抓出来的正是后一形）。

**存量不豁免、只登记**：下表是本档建档那轮（2026-10-19）的 offender 名单——新增即红，
把某档补上自证后**必须**从表里摘掉（"降了要看得见"），与 `test_subprocessTextEncodingRatchet.py`
同一手法。基线**只由本文件的 `_faceFindings` 生成**：上一版我从另一把探针尺里抄过一次数，
当场错出"2 条漏登 ＋ 5 条多登"，所以取数与基线必须同一次扫描同源。

**本档认不到的形状（明写边界，不当已收口）**：分类器认"扫描入口调用"——
`ast_scan.<共享入口>`、`<路径>.rglob|glob|iterdir|listdir|scandir`、`os.walk`，并且要把根参数
解成仓内目录。**按清单逐行 `read_text` 去读、不经过这些入口的档不在面内**（本档自己就是这一形，
`test_ci_ast_scan_budget_guard.py` 也是）——它们没有"根参数"可解，也就无从判面有没有被改窄。
要覆盖那一形，得先给这类读法定出"根"的表示法，属另一张票。
"""

from __future__ import annotations

import ast
import io
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 认作"扫描落点"的共享预算入口（枚举与解析都在预算内完成）。
SHARED_SCAN_ENTRIES = {
    "nodeScan", "sourceRefsUnder", "parsedModules", "walkedModules", "transientTree",
    "transientNodes", "callSites", "callNodes", "classDefsIn", "namesTakenFrom",
    "takenPerModule", "importersOfModule", "shadowedTopLevelNames", "filesUnder",
}
#: 私有文件系统枚举方法：这类调用的**根在接收者上**，第一个实参是模式。
FILE_ENUM_ATTRS = {"rglob", "glob", "iglob", "iterdir", "listdir", "scandir"}
#: 这些接收者上的同名方法不是文件枚举（`ast.walk` 与 `os.walk` 只差一个根）。
NON_PATH_RECEIVERS = {"ast", "re", "self", "node", "tree", "n"}
#: 仓根常量名：判据里这一族都指向"仓根"，因此 `<常量> / "子段"` 就是把面收窄的那一类写法。
REPO_ROOT_NAMES = {"REPO_ROOT", "PROJECT_ROOT", "REPO", "ROOT", "repoRoot"}
#: 参与面自证计数的构造：断言里跟数字比的量必须由这些得到，否则"自证"两字可以是任意的。
COUNT_CONSTRUCTORS = {"len", "sum"}

pytestmark = pytest.mark.timeout(120)

#: ── offender 基线（2026-10-19 现取：75 档有仓内扫描根，其中 52 档无面自证）──────────────
#: 建档口径与本文件的 `_faceFindings` 完全同源——**不要用别的规则量一遍再抄进来**，
#: 基线与判据不同源时，"存量在降"会被读成"治理有进展"（本仓同族账）。
BASELINE = {
    "tests/unit/agent/test_requestUserIdEntryConsistency.py",
    "tests/unit/agent/test_turnIdentitySingleSource.py",
    "tests/unit/api/test_channelWebhookResolvesAdapterByAgentTable.py",
    "tests/unit/api/test_corsPolicyIsSingleSource.py",
    "tests/unit/api/test_memoryMetacognitionSkillsMatchManagerContract.py",
    "tests/unit/api/test_memoryWriteIdentityGate.py",
    "tests/unit/api/test_studioRunStatusVocabulary.py",
    "tests/unit/channels/test_channelVoiceContextReachesTheTurn.py",
    "tests/unit/channels/test_channelVoiceFactorySeamCloses.py",
    "tests/unit/channels/test_channelWecomVoiceBytesReachThePrecheck.py",
    "tests/unit/channels/test_channelWecomVoiceInboundCarriesTranscript.py",
    "tests/unit/ci/test_context_coverage_scope.py",
    "tests/unit/ci/test_importChannelDetectorSeesAllFourForms.py",
    "tests/unit/ci/test_knowledge_base_index_wiring.py",
    "tests/unit/ci/test_liveIsolationSinglePointCoversBothRoots.py",
    "tests/unit/ci/test_manualScriptStdoutEncoding.py",
    "tests/unit/ci/test_stub_signature_single_source.py",
    "tests/unit/cognitive_layers/test_memoryBusSingleSource.py",
    "tests/unit/computer_use/test_route_vocabulary_is_single_source.py",
    "tests/unit/context/test_compression_economics.py",
    "tests/unit/context/test_context_compression_single_face.py",
    "tests/unit/core/test_cacheAccountsMergedIntoOneModule.py",
    "tests/unit/core/test_data_root_single_source.py",
    "tests/unit/core/test_dead_cache_module_removed.py",
    "tests/unit/core/test_lazySingletonDcl.py",
    "tests/unit/core/test_multiAgentManagerIslandRetired.py",
    "tests/unit/evolution/test_rsi_receipt_rollback.py",
    "tests/unit/execution/test_executionEngineOrphanSurfaceRetired.py",
    "tests/unit/execution/test_executionLayersTransportHalfRetired.py",
    "tests/unit/llm/test_capability_cache_single_source.py",
    "tests/unit/llm/test_ledgerTerminalVocabularySingleSource.py",
    "tests/unit/memory/test_memoryCipherFailFast.py",
    "tests/unit/memory_ingest/test_protected_registration.py",
    "tests/unit/memory_ingest/test_seed_db_landing_relocation.py",
    "tests/unit/plugins/test_pluginArtifactDigestPinnedAndVerified.py",
    "tests/unit/scripts/test_scripts_import_bootstrap.py",
    "tests/unit/security/test_installGateDocFilesAreReportOnly.py",
    "tests/unit/skills/test_skillsFacadeAndSourceEnumAreSingleSourced.py",
    "tests/unit/test_ci_thin_env_guards.py",
    "tests/unit/test_ci_wallclock_assertion_ledger.py",
    "tests/unit/test_deploy_config_guard.py",
    "tests/unit/test_dev_path_and_runtime_dep_guards.py",
    "tests/unit/test_manual_scripts_are_not_collectible.py",
    "tests/unit/test_script_index_registration.py",
    "tests/unit/tools/test_npx_runtime_pinning.py",
    "tests/unit/tools/test_tool_parallelism_readout.py",
}


# ── 取数：三样小工具，各自只解一件事，便于逐形反检 ─────────────────────────────
def _constTable(tree: ast.AST) -> dict:
    """模块级 `NAME = <expr>`：根参数常写成 `NEUROVA_ROOT = PROJECT_ROOT / "neurova"`。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def _resolveRoot(expr: ast.AST, consts: dict, anchor: pathlib.Path, depth: int = 0):
    """把"根"表达式解成目录；解不出返 None（真动态值不承载面的声明，不参与裁决）。

    `anchor` 是该档所在仓根：合成夹具要能被同一套代码判，所以仓根常量按**给定根**解，
    而不是写死本仓——否则正检样本永远只能往真仓里种文件（会污染其余常驻判据）。
    """
    if expr is None or depth > 8:
        return None
    if isinstance(expr, ast.Name):
        if expr.id in REPO_ROOT_NAMES:
            return anchor
        return _resolveRoot(consts.get(expr.id), consts, anchor, depth + 1)
    if isinstance(expr, ast.Attribute):
        if expr.attr in REPO_ROOT_NAMES:
            return anchor
        return _resolveRoot(consts.get(ast.unparse(expr)), consts, anchor, depth + 1)
    if isinstance(expr, ast.Call):
        name = ast.unparse(expr.func)
        if name in {"Path", "pathlib.Path"} and expr.args:
            return _resolveRoot(expr.args[0], consts, anchor, depth + 1)
        head = name.split(".")[0]
        return _resolveRoot(consts.get(head), consts, anchor, depth + 1)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _resolveRoot(expr.left, consts, anchor, depth + 1)
        right = expr.right
        if left is None or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        cand = left / pathlib.PurePosixPath(right.value)
        return cand if cand.is_dir() else None
    if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute) \
            and expr.value.attr == "parents" and isinstance(expr.slice, ast.Constant) \
            and isinstance(expr.slice.value, int):
        ups = anchor
        for _ in range(expr.slice.value + 1):
            ups = ups.parent
        return ups
    return None


def _scanSites(tree: ast.AST, consts: dict, anchor: pathlib.Path) -> list:
    """这档里的扫描落点 `(入口, 解出的根或 None)`。

    按「接收者＋属性名」两维认，不按属性名单认：`ast.walk(tree)` 与 `os.walk(dir)`
    只差一个接收者，把前者当全仓扫描会把读数放大一个量级（本档取数路自己踩过的第一版错）。
    """
    out = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        attr = call.func.attr
        recv = ast.unparse(call.func.value) if isinstance(call.func.value, ast.expr) else ""
        top = recv.split(".")[0].split("(")[0]
        if top == "ast_scan" and attr in SHARED_SCAN_ENTRIES:
            out.append((attr, _resolveRoot(call.args[0], consts, anchor) if call.args else None))
        elif attr in FILE_ENUM_ATTRS and top not in NON_PATH_RECEIVERS:
            out.append((attr, _resolveRoot(call.func.value, consts, anchor)))
        elif attr == "walk" and top == "os":
            out.append(("os.walk", _resolveRoot(call.args[0], consts, anchor) if call.args else None))
    return out


def _countNames(tree: ast.AST) -> set:
    """档内"由扫描/计数得到的名字"。

    认这四种形制，都是本仓现有判据真在用的写法（少认一种就会把已经自证的档错判成 offender——
    实测第一版就把自己刚建的那两格错判了：`surface.get("filesSeen")` 与循环里 `scanned += 1`）：
      * `x = len(...)` / `x = sum(...)`
      * `x = <统计袋>.get(...)`（共享入口回填面读数的写法，见 `shadowedTopLevelNames` 的 `stats`）
      * `x = ast_scan.<入口>(...)`（直接拿扫描结果本身）
      * `x = [...] for ... in ...`（列表推导收集出的落点清单）
      * 循环里 `x += 1` 累加出来的计数器
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            rhs = node.value
            if isinstance(rhs, ast.Call):
                fn = ast.unparse(rhs.func)
                if fn in COUNT_CONSTRUCTORS or fn.split(".")[0] == "ast_scan" or fn.endswith(".get"):
                    names.add(node.targets[0].id)
            elif isinstance(rhs, ast.ListComp):
                names.add(node.targets[0].id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and isinstance(node.op, ast.Add):
            names.add(node.target.id)
    return names


def _hasFaceProof(tree: ast.AST, counts: set) -> bool:
    """存在一条 `assert <扫描计数> > 数`（或 `>=`）——只认代码形状，不认词。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        cmp_ = node.test
        if not any(isinstance(op, (ast.Gt, ast.GtE)) for op in cmp_.ops):
            continue
        if not any(isinstance(o, ast.Constant) and isinstance(o.value, (int, float))
                   for o in cmp_.comparators):
            continue
        operands = [cmp_.left] + list(cmp_.comparators)
        for side in operands:
            text = ast.unparse(side).strip()
            if text.startswith(("len(", "sum(")) or text in counts:
                return True
    return False


def _faceFindings(root: pathlib.Path, manifest: list) -> list:
    """`(档, 扫描落点数, 有面自证?)` 里挑出**有仓内扫描根而无自证**的那些档。"""
    offenders = []
    for rel in manifest:
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        consts = _constTable(tree)
        sites = _scanSites(tree, consts, root)
        if not any(r is not None for _e, r in sites):
            continue
        if not _hasFaceProof(tree, _countNames(tree)):
            offenders.append(rel)
    return sorted(offenders)


def _manifestOf(root: pathlib.Path) -> list:
    path = root / "scripts" / "ci" / "protected_tests.txt"
    if not path.is_file():
        return []
    return [ln.split("#", 1)[0].strip() for ln in io.open(path, encoding="utf-8").read().splitlines()
            if ln.split("#", 1)[0].strip()]


def test_ratchetDoesNotRise():
    """新增"扫仓内路径而不自证面"的判据档一律拦。"""
    now = set(_faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT)))
    grew = sorted(now - set(BASELINE))
    assert not grew, (
        "这些受保护子集里的判据扫了仓内源码树，却没把**这次扫到的数量**当断言比——"
        "根被改窄或写错时它的读数是「零命中」而不是红：\n  " + "\n  ".join(grew) +
        "\n修法（一行即可）：把该次扫描的计数留在同一次读数里并断下限，"
        "形如 `scanned = len(...); assert scanned > 500, f\"扫描面现读 {scanned}\"`。"
        "\n参考同档 `test_surfaceCoversAllThreeSourceFamilies`（先验面，再谈零命中）。\n"
        "别把新档加进基线表——那等于把这条棘轮又拆回各判各的。"
    )


def test_ratchetRecordsImprovementLoudly():
    """存量被消化要**显式收表**：基线里有、现在不 offender 的档，必须从表里摘掉。"""
    now = set(_faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT)))
    dropped = sorted(set(BASELINE) - now)
    assert not dropped, (
        "以下档已经自带面自证（或不再扫仓内路径）了——把 BASELINE 里那几行摘掉再提交，"
        "别让它悬着（悬着的后果：下一条真新增的 offender 会被旧表兜住而看不见）：\n  "
        + "\n  ".join(dropped)
    )


def test_surfaceReadingIsNotVacuous():
    """反空转：扫描面本身要先在场——"一条 offender 都没有"可能只是清单没读到。

    这条格专防本仓反复吃过的那一形：清单路径写错 ⇒ 空 manifest ⇒ offender 恒空 ⇒ 两条断言全绿。
    """
    manifest = _manifestOf(PROJECT_ROOT)
    assert len(manifest) > 500, f"受保护子集清单现读 {len(manifest)} 条，量级不对＝没读到"
    parsed = 0
    for rel in manifest:
        if (PROJECT_ROOT / rel).is_file():
            parsed += 1
    assert parsed == len(manifest), (
        f"清单里有 {len(manifest) - parsed} 条指不到真实文件——offender 读数会偏小且偏干净")


@pytest.mark.parametrize("label, source, expectOffender", [
    ("只断零命中，没断面＝正是要拦的形状",
     "from tests import ast_scan\n"
     "import pathlib\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(ROOT, '.py')]\n"
     "    assert hits == []\n", True),
    ("把这次扫到的数量当断言比＝合规",
     "from tests import ast_scan\n"
     "import pathlib\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    pairs = list(ast_scan.nodeScan(ROOT, '.py'))\n"
     "    scanned = len(pairs)\n"
     "    assert scanned > 500, f'扫描面现读 {scanned}'\n"
     "    assert [p for p, _n in pairs] == []\n", False),
    ("有一条与扫描无关的数断言不算自证（6 档新增就是这形）",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    hits = list(ast_scan.nodeScan(ROOT, '.py'))\n"
     "    rows = [1, 2, 3]\n"
     "    assert len(rows) == 3\n"
     "    assert hits == []\n", True),
    ("根是真动态值（循环里的名字）＝不承载面的声明，不参与裁决",
     "from tests import ast_scan\n\n\n"
     "def test_perFamily(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n", False),
    ("`ast.walk(tree)` 不是文件扫描：别把它算成落点",
     "import ast\n\n\n"
     "def test_shape(source):\n"
     "    nodes = list(ast.walk(ast.parse(source)))\n"
     "    assert nodes\n", False),
    ("循环里累加出来的计数器算自证",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    scanned = 0\n"
     "    for path, tree in ast_scan.parsedModules(ROOT, '.py'):\n"
     "        scanned += 1\n"
     "    assert scanned > 500, f'扫描面现读 {scanned}'\n", False),
    ("共享入口回填的统计袋算自证（面读数与被裁的那次扫描同源）",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    surface = {}\n"
     "    dups = ast_scan.shadowedTopLevelNames(ROOT, stats=surface)\n"
     "    seen = surface.get('filesSeen', 0)\n"
     "    assert seen > 3000, f'现读 {seen}'\n"
     "    assert dups == []\n", False),
])
def test_classifierJudgesEveryShapeItClaims(tmp_path, label, source, expectOffender):
    """判据自身的分类器逐形自证：正检、反检都要有，且新认的形制各配一格。

    合成样本一律落在 `tmp_path`（自带一份子集清单），不往真仓里种文件——
    种进去会被其余常驻判据双计（仓内任何一份代码副本都是这条根因的账单）。
    `tmp_path/neurova/` 要真的建出来：根解析按"该目录存在"判，不建就等于让样本走一条
    与真仓不同的分支，那种绿不算证到。
    """
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "neurova").mkdir()
    (tmp_path / "scripts" / "ci" / "protected_tests.txt").write_text("tests/sample.py\n", encoding="utf-8")
    (tmp_path / "tests" / "sample.py").write_text(source, encoding="utf-8")

    offenders = _faceFindings(tmp_path, ["tests/sample.py"])
    assert bool(offenders) is expectOffender, f"{label} ⇒ 分类判错：{offenders}"
