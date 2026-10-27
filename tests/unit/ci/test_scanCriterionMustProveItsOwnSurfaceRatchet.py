# -*- coding: utf-8 -*-
"""扫描型判据必须自证"这次真扫到了多少"——只降不升棘轮（§6-322 裁定乙的落地）。

**要防的那件事**：一条"全仓不得再出现 X"的判据，如果它实跑的根被改窄（或被写错成少上一层），
读数会变成**零命中**而不是红——"干净"与"没扫到"在断言里长得一模一样。本仓已有一例实证：
模块级重名定义那条守卫自建档起就在子集里，docstring 讲的是通用形状，而它唯一真跑整树的格子
喂的根只有 `neurova/`；`tests/` 下四处既存遮蔽（其中一处让 3 条用例连收集都不发生）
活了三批，没有任何东西变红。事后按档量了一遍覆盖面（取数口就是本文件的 `_faceFindings`）：
**能解出仓内扫描根的判据档里，把自己扫到的数量当断言比过的不到一半**，其余那批一直在赌
"根没写错、也没被改窄"。这里**不抄现值**——覆盖率是随批次动的量，写死一次就等着它讲假话；
要看今天的数，用本文件的取数口现跑，或查台账里那一批的落批读数。

**判据只认代码形状，不认词**（本仓的守卫被自家 docstring 撞红过，也被自己的措辞豁免过）：
"自证"＝本档里存在一条 `assert`，把**由这次扫描/计数得到的量**与一个数字下限比。计数名认这几种形：
`len(...)`／`sum(...)`／`ast_scan.<入口>(...)`／列表推导／`.get()`（共享入口回填面读数的写法，
见 `shadowedTopLevelNames` 的 `stats`）／循环里 `+= 1` 累加的计数器——**每种认形都配了一格合成正检**，
放宽不白给。以下两种**不算**：只 `assert findings == []`；有一条与扫描无关的 `assert len(rows) > 0`
（收紧规则多抓出来的正是后一形）。

**面读数怎么取（消化存量时踩出来的次序）**：优先由**被裁的那次扫描自己**给出计数——物化它的返回值
再 `len()`，或在循环里累加；这样"面"与"判据看到的量"必然同源。那次扫描带文本预筛时（预筛命中数不随
根的大小变，证不了面），另走一次共享枚举入口量根：`ast_scan.filesUnder(根)`。**但**如果本档别处还
自付 `ast.parse`，`filesUnder` 与它配成对正是 `test_ci_ast_scan_budget_guard` 报的形状（本会话三档
当场被拦：`test_manualScriptStdoutEncoding`／`test_ci_wallclock_assertion_ledger`／
`test_tool_parallelism_readout`）——那种档改用 `ast_scan.sourceRefsUnder(根, ".py")`（共享入口，
枚举与解析都在预算内），**不要**为了绕过门禁把私有解析留着、也不要退成弱读数。

**存量不豁免、只登记**：下表是本档建档那轮（2026-10-19）的 offender 名单——新增即红，
把某档补上自证后**必须**从表里摘掉（"降了要看得见"），与 `test_subprocessTextEncodingRatchet.py`
同一手法。基线**只由本文件的 `_faceFindings` 生成**：上一版我从另一把探针尺里抄过一次数，
当场错出"2 条漏登 ＋ 5 条多登"，所以取数与基线必须同一次扫描同源。名单已随四波存量收空，
本闸自此**零容忍**——这张空表本身就是裁决力，不是"治理结束"的墓碑。

**读数落在哪一格也要选**：把 `filesUnder` 塞进一条被消费的 helper，会让该 helper 的**调用闭包**
同时具备「枚举＋私有解析」两种落点——那正是 `test_ci_ast_scan_budget_guard` 点名要红的形状
（本批实测把读数放进 `declIndex()`，门禁当场报出两个落点）。门禁在这里的判断是对的：
面读数不该让判据多付一趟解析。那种档把面自证落成**独立一格**，只调枚举入口、不碰解析。

**第七类面：清单即根（§6-331 那张票的表示法，批 103 落地）**：还有一族判据不经过文件系统入口，
它的面是**一份清单文件**——按行读进来、逐条拼成路径去读／去 `is_file()`。这种档没有"根参数"可解，
清单被截短或路径写错时读数同样缩水成"零 offender"。本闸按 (a)(b)(c) 三件齐的污点链认这一形
（见下方 `_manifestFace`），并**单独要求"由这份清单得到"的自证**——文件级的 `_hasFaceProof` 在这里
不够用：档里一条与清单无关的 `assert len(nodes) > 1000` 就能把整档豁免掉，而那正是
§6-331 点名的一处真缺口。
**仍认不到的形状（明写边界，不当已收口）**：分类器认"扫描入口调用"——
`ast_scan.<共享入口>`、`<路径>.rglob|glob|iterdir|listdir|scandir`、`os.walk`，并且要把根参数
解成仓内目录。清单那一面有三条形制确实没认：**模块链两跳以上**（取数口自己再转调第三个模块，
`_moduleFacts` 只算同文件规则那一层）、**动态取数**（`importlib.import_module`／`__import__`——
认它就等于猜面，猜出来的面不算面）、以及**条目先过一道普通函数再被当路径动手**
（`d = digest(line)` 之后 `d.is_file()`——污点一旦允许顺任意 helper 蔓延，面就虚胖到不可信，
`_isPathDerivation` 那条写了理由，控制格里也钉了同一形）。另有三种**不是缺口**，理由要写清：
成员检查（只为问"这条在不在表里"）、条目只当键用（切字符串、比较、当 dict 键而从不进
`read_text`/`open`/`is_file`）在清单改窄时**当场就红**，与"仓内文件"同属坏得响那一支；
读的是**仓外**清单也照样在面内——本闸只问"条目有没有被当路径动手"，清单文件该不该在仓内是
另一回事（旧版本这里写着"仓外不在面内"，那句是假话）。

**根的形状分六态**：仓内目录／仓内文件／仓外目录／指不到东西／动态值／**函数内局部名**。只有"仓内目录"要求面自证；
"仓内文件"坏得响（入口当场抛），"动态值"不承载面的声明；**"仓外"与"指不到"一律点名，且不看它在不在下表里**
（`test_staticRootsNeverPointOutsideOrNowhere`，不留存量豁免）。为什么单独钉：`test_ratchetDoesNotRise` 只比"比基线新增了什么"，
一档本来就在表里、后来把根写错了，失败集合反而一个字节都不变——本会话把 `parents[3]` 改成 `parents[4]` 实测过这一形，两格全绿。
"根写错"比"没自证"更重（前者让判据根本不说话，后者只是没留底单），不能由存量名单兜着。
第六态"函数内局部名"由 `test_scanRootsAreNeverBoundInsideAFunction` 管：它不是写错根，而是**本闸认不出根在哪**，
性质与建档那轮的存量相同 ⇒ 带一张 `LOCAL_BASELINE`，新增即红、消化必须摘行（批 98 实测过它的坏法：
把 8 档的根收进 `faceRoot` 之后，6 档的落点态只剩 `dynamic`，offender 仍是 0——绿在这里成了假事实源）。
"""

from __future__ import annotations

import ast
import functools
import os
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan  # noqa: E402  受保护子集清单的唯一读法在 `ast_scan.protectedSubsetEntries`

#: 本闸裁决的锚（"仓内"这个词的**唯一**口径）。
#:
#: 不直接用本档的 `PROJECT_ROOT`：CI 的 `unit-tests` 腿按 `--import-mode=importlib` + 相对路径
#: 参数跑，pytest 会把一个**影子包**塞进 `sys.modules["tests"]`——它的 `__file__` 落在
#: pytest 的 basetemp 下，于是本档 `from tests import ast_scan` 取到的是临时目录里的那份，
#: `ast_scan.REPO_ROOT` 随之指向临时目录，整闸把全仓的扫描根判成"仓外"（构建
#: `cnb-eum-1k5lir51n#003` 的 2 红就是这么来的）。`ast_scan` 是**按自家 `__file__` 定位仓根**的
#: 单点，所以裁决锚只能是它的读数；`PROJECT_ROOT` 仍留给"本档自己那份清单"用（本闸自带的反证格
#: 要在 tmp 合成仓上跑）。
ANCHOR = ast_scan.REPO_ROOT

#: 认作"扫描落点"的共享预算入口（枚举与解析都在预算内完成）。
SHARED_SCAN_ENTRIES = {
    "nodeScan", "sourceRefsUnder", "parsedModules", "walkedModules", "transientTree",
    "transientNodes", "callSites", "callNodes", "classDefsIn", "namesTakenFrom",
    "takenPerModule", "importersOfModule", "shadowedTopLevelNames", "filesUnder",
    "transientTrees",
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

#: ── offender 基线：一律由本文件的 `_faceFindings` 现取生成，不在注释里抄数 ──────────
#: 建档口径与本文件的 `_faceFindings` 完全同源——**不要用别的规则量一遍再抄进来**，
#: 基线与判据不同源时，"存量在降"会被读成"治理有进展"（本仓同族账）。
#: 面读数与消化进度写在台账那一格（进账的数字背后必须有当轮跑过的命令），代码这里只留名单。
#:
#: 现值＝**空集**。四波存量（46 → 36 → 27 → 19 → 0）收干净之后，本闸是**零容忍**：
#: 新落一条「扫仓内根却不自证面」的判据即红。空表不代表这闸失去内容——它的裁决力就是"新增即红"，
#: 而 `test_ratchetRecordsImprovementLoudly` 继续留着，是为了让"名单与实际不同源"当场露形
#: （包括有人把真 offender 偷偷加回这张表来换取那一格变绿）。
BASELINE: set = set()

#: 落点**缺席**的存量表：「根推导本身无误，但那个目录此刻不在工作树里」。
#:
#: 与「根写错」必须分开：根写错是 `parents[N]` 数错层，修法是把 N 改对；本表记的是像
#: `data/sessions` 这种**运行态才被建出来**的目录——干净 checkout 上它天然缺席。
#:   （历史例：`tests/unit/test_session_landing_guard.py` 曾把落点直接锚在 `data/sessions`，
#:   而那只在跑起会话后才存在 ⇒ 干净 checkout 上解成 `missing`。该档的枚举根后来改指模块级
#:   `DATA_DIR`（`<repo>/data`，跑测时一定存在），署名因此销账——本表现值为空集。）
#: 仓外（`outside`）**不做**这类豁免：那种根指的不是本仓代码，没有任何正当理由。
#: 同一档换个写法后落点变成"解不出"（`dynamic`，如把目录名收进循环变量）时，本表同样不误报——
#: 那种形态由 `LOCAL_BASELINE` 那一格管，性质不同，不能混成"表过期"。
#: 纪律与其余表一致：新增即红、消化必须摘行；署名还在、档却已不再解到缺席时当场红
#: （表--实况咬合）——真 offender 被偷偷塞回来换绿也会露形。
MISSING_BASELINE: dict = {}


def _dropSignedOffMissing(gaps: dict) -> dict:
    """把 `MISSING_BASELINE` 里署过名的「缺席」从 offender 里摘掉；署名与实况不符当场红。

    做成函数而不是在两个格子里各写一遍：两格（棘轮／静态根）看的是同一份取数结果，
    摘法分头写就会长成两条口径（教义第 6 条）。`outside` 一律不放行。
    """
    signedOff = set(MISSING_BASELINE)
    # 「署名还在、档也不再解到缺席」＝表过期，必须同批摘行（与 `BASELINE` 的表--实况咬合同形）。
    # 档里出现 `None` 值不算过期：那是本闸对"某落点**解不出**"的记账，它出现在**别的题**上，
    # 与"这个根此刻指不到目录"是两件事——按值齐比会把它误判成实况变化。
    stale = [rel for rel in signedOff if rel in gaps and gaps[rel] != MISSING]
    assert not stale, (
        "MISSING_BASELINE 里的条目，实际落点态已不是 `missing`（表与实况不同源，必须同批改表）："
        + repr({rel: gaps[rel] for rel in stale})
    )
    return {rel: st for rel, st in gaps.items()
            if not (st in (MISSING, None) and rel in signedOff)}


#: ── LOCAL 存量表：同样只由本文件的 `_faceFindings(localGaps=...)` 现取生成 ──────────
#: 建档那轮＝批 99（2026-10-19）。「面自证」那张表已收空，这张表记下的是**本闸认不出根位置**的档：
#: 根绑在函数内的名字上，`_constTable` 解不出 ⇒ 那档连"有没有面"都不再被问。
#: 纪律与 BASELINE 一致：新增即红、消化必须摘行；下一批把某一档的根提到模块级时，
#: **同批要给它补上面自证**（提到模块级之后它才进入「仓内目录」那一支，那时才要求自证）。
#: 现值＝**空集**（批 100 收干净：9 档的根全部提到模块级，并按「仓内目录」那一支补上了面自证）。
#: 空表之后这一格也是零容忍——新把根绑进函数局部，当场点名。
LOCAL_BASELINE: set = set()

#: ── 第七类面的存量表：同样只由本文件的 `_faceFindings(manifestGaps=...)` 现取生成 ────
#: 建档那轮＝批 103（2026-10-19）。这张表记的是**以清单为扫描面、却没给这份清单留面读数**的档。
#: 纪律与前两张表一致：新增即红、消化必须摘行，数只从本文件的取数口来。
#: 现值＝**空集**。建档那轮量出 5 档（`test_ci_ast_scan_budget_guard`／`test_ci_wallclock_assertion_ledger`／
#: `ci/test_clock_caliber_ledger`／`ci/test_count_bounded_wait_ledger`／
#: `ci/test_protected_subset_registration_history`），五档同根因、同一处方（照本档
#: `test_surfaceReadingIsNotVacuous` 的形状补一条"由这份清单得到"的读数），一处方管五处 ⇒ 同批改完，
#: 不留存量表（教义 5：命中点当场处理得了，就不该登记完事）。
#: 空表之后这一格也是零容忍——新写一条"逐条读清单去动手"的判据而不留条目读数，当场点名。
#: **现值＝空表，零容忍**（批 115 收掉最后 1 档）。
#: 那一档当初"只能登记"的理由现在被实测推翻了：它说"docs/INDEX.md 的阅读顺序今天只指向
#: `AGENTS.md`（解析出 1 条），给它补 `len(paths) > N` 就是拿假数字装硬断言"——
#: **1 条不是清单的形状，是那条窄解析形的形状**。同一节里另有两条以 markdown 链接指名的入口
#: （`CONTEXT.md` 与 `INDEX.md`），旧正则一条也不认，于是它们从没进过可达性检查（302 那一形：
#: 面窄于声明时，缺的东西不红任何东西）。
#: 结法不是放宽本闸、也不是给判据塞一个漂亮数，而是把解析面扩到三种写法都认，
#: 再补两条互相咬合的读数：数量级 `len(链接目标) > 2`（退回窄形即红）＋等值对账
#: `len(目标) == len(提到 .md 的条目)`（漏一种写法即红）。可达性那条本身不许单独算收口——
#: 链接目标写错时条目数照样好看。
MANIFEST_BASELINE: set = set()


#: ── 清单取数口的单源表（§6-234 那一族的续集）：`rel -> 自己读那份清单的落点数` ──────
#: 这份清单是 CI 的唯一执行面，"哪些档在子集内"只该有一处读法（`ast_scan.protectedSubsetEntries()`）。
#: **表由本文件的 `_readerCounts` 现取生成**——我第一版手抄过一份，同一棵树就错出"28 档"（还点进了
#: 一档根本不在子集里的），正是形态集 304 那条：基线与判据不同源时，"存量在降"会被读成"治理有进展"。
#: 纪律与前三张表一致：新增落点即红、消化必须摘行。
#: 建档那轮（批 104）现值＝34 档 / 37 处，按 `_manifestReadSites` 两条支分：解析支独占 23／
#: 两支都中 13／字面量支独占 1（那 1 处是 `repo_path("scripts","ci",…)` 这种"路径由 helper 拼出来"
#: 的读法）。**现值＝空表，本闸零容忍**（批 114 收掉最后 2 档 / 5 处：夜间那 1 处改指
#: `ast_scan.rawManifestLines()`，`test_dev_path_and_runtime_dep_guards.py` 那 4 处改指
#: `ast_scan.protectedSubsetEntries()`）。
#: 夜间那一档当初"幸存"的理由是：它的职责就是拿**原始清单**去比对夜间脚本自己那份
#: `readEntries()`——用归一化那条去过归一化那条，就证不了它没吞行、没排序、没去重。
#: 结法不是豁免，是**再开一条同样只此一处的原始行读法**（`rawManifestLines`），
#: 两条刻意不同源（一条剥行内注释、一条不剥），并由合成样本格 `test_rawReaderIsNotTheNormalizedOne`
#: 当场把分歧造出来钉住——表归零不等于这条腿没牙（251 那一形）。
#: 一处不在表里也不在面内：`tests/integration/test_security_integration.py` 读这份清单，
#: 可它**不在受保护子集里**——本闸的面就是那份清单，登记在这里免得下一个人以为漏了。
READER_BASELINE: dict = {}


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


def _scopedBindings(tree: ast.AST) -> dict:
    """**任意作用域**的 `NAME = <expr>`（同名取首次绑定）——只用来认"根绑在函数里"这一形。
    合规裁决不看它：认出来之后照样要求把根提到模块级，本闸不接受"函数里也算根"。
    取首次绑定而不是最后一次：同一名字在文件里被改写过时，最后一次往往已经是运行时值，
    那种档本来就不该被认成静态根（认成 LOCAL 反而会把修法指错）。
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out.setdefault(node.target.id, node.value)
    return out


def _rootStatus(expr, consts: dict, anchor: pathlib.Path, selfPath: pathlib.Path = None,
                scoped: dict = None) -> str:
    """一个根表达式的落点态。`scoped` 给了就多认一步：模块级解不出、按作用域解得出且落在
    **仓内真实目录** ⇒ LOCAL（"根写得对、只是绑错了地方"），交给零容忍那一格点名。
    """
    status = _classifyRoot(_resolveRoot(expr, consts, anchor, selfPath=selfPath), anchor)
    if status == DYNAMIC and scoped is not None and expr is not None:
        alt = _classifyRoot(_resolveRoot(expr, scoped, anchor, selfPath=selfPath), anchor)
        if alt == DIR:
            return LOCAL
    return status


#: 静态根解出来的落点态，加上「动态值」「函数内局部名」共六态。**只有 DIR 参与面自证裁决**；
#: OUTSIDE／MISSING 都是「根写错了」的形状，一律点名；FILE 与 DYNAMIC 不承载"面会被改窄"这件事，
#: 既不点名也不免罪。把六态分开的理由：原来「解不出」与「解到别处」与「解到一个文件」都折叠成
#: 同一个 None，于是"根少写一层"的那档会安静地掉出本闸的面——正是本闸要防的事，
#: 被本闸的取数路自己放过去。
#:   FILE 为什么免裁：单文件落点坏掉时 `transientTree` 一类入口当场抛 FileNotFoundError，是**响**的；
#:   目录落点坏掉时只给出「零命中」，与干净同形，是**哑**的。本闸只管哑的那一类。
#:   LOCAL（根绑在函数里的名字上）另开一格点名（`test_scanRootsAreNeverBoundInsideAFunction`）：
#:   它不是"根写错"，而是"根本来写得对，只是绑在函数作用域里，`_constTable` 那张**模块级**表认不出"。
#:   认不出＝那档整档掉出本闸的面。批 98 实测过这一形的价钱：把 19 档的根收进 `faceRoot` 之后，
#:   offender 读数仍是 0、摘表两格全绿——绿在这里是假事实源。
#:   修法只有一条：把根提到模块级，并把同档多处根写法收成同一个名字；提上去之后这档进入 DIR 那一支，
#:   面自证的要求随即生效，所以**两处要同批改**，别只提根不补读数。
DYNAMIC, LOCAL, DIR, FILE, OUTSIDE, MISSING, NOT_CHECKED_OUT = (
    "dynamic", "local", "dir", "file", "outside", "missing", "not_checked_out"
)


def _resolveRoot(expr: ast.AST, consts: dict, anchor: pathlib.Path, depth: int = 0,
                 selfPath: pathlib.Path = None):
    """纯结构地把"根"表达式解成一个路径；解不出＝动态值，返 None。

    这里**不判存在、不判在不在仓内**——那是 `_classifyRoot` 的活。`Path(__file__)` 一形按
    **被档自己的路径**解（`selfPath`），因此 `parents[N]` 的含义随该档所在深度而定：
    `tests/unit/ci/x.py` 里的 `parents[3]` 是仓根，`tests/unit/x.py` 里的 `parents[2]` 才是仓根。
    第一版从没用过 `selfPath`，而是从仓根往上再数 N+1 层，把三档的根解成了 `E:\\`。
    深度上限也不能小：`REPO / "a" / "b" / "c" / "d"` 这一条链本身就吃掉五层，
    原来的 8 层上限会把这种**合法写法**降级成动态值，让那档安静地掉出本闸的面——
    与上一条同根因，实测由 `test_memoryWriteIdentityGate.py` 那档当场抓出。
    """
    if expr is None or depth > 64:
        return None
    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return selfPath
        if expr.id in consts:
            return _resolveRoot(consts[expr.id], consts, anchor, depth + 1, selfPath)
        return anchor if expr.id in REPO_ROOT_NAMES else None
    if isinstance(expr, ast.Attribute):
        if expr.attr in {"resolve", "absolute"}:
            return _resolveRoot(expr.value, consts, anchor, depth + 1, selfPath)
        if expr.attr == "parent":
            base = _resolveRoot(expr.value, consts, anchor, depth + 1, selfPath)
            return None if base is None else base.parent
        if ast.unparse(expr) in consts:
            return _resolveRoot(consts[ast.unparse(expr)], consts, anchor, depth + 1, selfPath)
        if expr.attr in REPO_ROOT_NAMES:
            return anchor
        return None
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr in {"resolve", "absolute"}:
            return _resolveRoot(func.value, consts, anchor, depth + 1, selfPath)
        name = ast.unparse(func)
        if name in {"Path", "pathlib.Path"} and expr.args:
            return _resolveRoot(expr.args[0], consts, anchor, depth + 1, selfPath)
        head = name.split(".")[0]
        return _resolveRoot(consts.get(head), consts, anchor, depth + 1, selfPath)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _resolveRoot(expr.left, consts, anchor, depth + 1, selfPath)
        right = expr.right
        if left is None or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        return left / pathlib.PurePosixPath(right.value)
    if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute) \
            and expr.value.attr == "parents" and isinstance(expr.slice, ast.Constant) \
            and isinstance(expr.slice.value, int):
        base = _resolveRoot(expr.value.value, consts, anchor, depth + 1, selfPath)
        if base is None:
            return None
        try:
            return base.parents[expr.slice.value]
        except IndexError:
            return pathlib.Path(base.anchor) if base.anchor else base
    return None


def _gitKnownPaths(anchor: str) -> frozenset:
    """仓内 git 认得的路径前缀（已跟踪 + 被忽略）——一次取全，判定只查集合。

    `git ls-files` 之外还要 `git check-ignore --stdin`：`data/` 这类被整目录忽略的落点
    在 `ls-files` 里永远不出现，而它恰恰是"仓内、干净检出里不存在"的正当形态。
    仓库不可用（无 git、非工作树）时给空集 ⇒ 全落 MISSING，维持原来那句更响的报错。

    **不缓存**：`anchor` 是每个 tmp 工作树一把的唯一路径，缓存只会让"本进程此前判过某个
    临时仓"与"从没判过"两种情形给出不同读数（同一台机器上本档 2 红 1 绿的那次，
    绿的成因就是 `/tmp` 路径在缓存里留过一份非空集合）。取数一次约 10ms。
    """
    def run(*args, stdin=None):
        try:
            # 两头都钉：父端按 utf-8 解、子端也按 utf-8 写（`git ls-files` 会吐出仓内
            # 中文路径；父端不钉就按本机码页解，读数被静默改写。§6-64 那条「半修计数」
            # 棘轮就是量这个的）。
            proc = subprocess.run(
                ["git", *args], cwd=anchor, input=stdin,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    known = set(run("ls-files", "--cached"))
    # `data/` 这类**整目录**规则不会被 `ls-files --ignored` 点名：它只列磁盘上真存在的
    # 忽略项，干净检出里那个目录压根没有——而这一支要判的恰恰是"该缺席、且缺席正当"。
    # 故额外问一次 `check-ignore --no-index`（`--no-index` 才问得到不存在的路径）。
    for name in sorted(_ignoredTopLevelDirs(anchor)):
        known.add(name + "/")
    known.update(run("ls-files", "--others", "--ignored", "--exclude-standard", "--directory"))
    return frozenset(known)


def _gitWorktreeRoot(anchor: str):
    """`anchor` 所在工作树的**顶层**；不是工作树时给 `None`。

    `--no-index` 只免掉"该路径在不在索引里"，不免"这是不是一个工作树"——非工作树里
    `check-ignore` 仍以 128 退出。故取证前先问一次顶层，顺带拿到本树自己的 `.gitignore`
    位置：取证只认这份树，绝不回落到宿主仓（那会让读数随宿主布局变）。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=anchor, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return pathlib.Path(top) if top else None


def _ignoredTopLevelDirs(anchor: str) -> set:
    """仓根层面被忽略的顶级目录名——名单取自本树自己的 `.gitignore` 左值，逐条问 git。"""
    root = _gitWorktreeRoot(anchor)
    if root is None:
        return set()
    ignoreFile = root / ".gitignore"
    if not ignoreFile.is_file():
        return set()
    names = set()
    for line in ignoreFile.read_text(encoding="utf-8", errors="replace").splitlines():
        rule = line.strip().lstrip("/").rstrip("/")
        if rule and not rule.startswith(("#", "!")) and "/" not in rule:
            names.add(rule)
    return {name for name in names if _gitIgnoreAnswers(str(root), name)}


def _gitIgnoreAnswers(anchor: str, name: str) -> bool:
    """`git check-ignore --no-index`：问得到**不存在**的路径，这是本支唯一能用的一问。"""
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", name + "/"], cwd=anchor,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _pathIsTrackedOrIgnored(path: pathlib.Path, anchor: pathlib.Path) -> bool:
    """该路径（或其任一祖先）是否由 git 认作本仓的一部分。"""
    try:
        rel = path.relative_to(anchor)
    except ValueError:
        return False
    known = _gitKnownPaths(str(anchor))
    if not known:
        return False
    parts = rel.parts
    for index in range(1, len(parts) + 1):
        prefix = "/".join(parts[:index])
        if index == len(parts):
            # 末级：目录规则在集合里以 `<名>/` 收录（`check-ignore` 那支给的形态就是目录），
            # 故 `data` 与 `data/` 要一起认——同一条事实的两种写法。
            return prefix in known or prefix + "/" in known
        if prefix + "/" in known:
            # 中间级被**整目录忽略**：忽略规则连内容一起盖住，末级自然也不在检出里。
            return True
    return False


def _classifyRoot(path, anchor: pathlib.Path) -> str:
    """把解出来的路径归到五态之一。大小写与分隔符按 `os.path.normcase` 归一再比。"""
    if path is None:
        return DYNAMIC
    norm = pathlib.Path(os.path.normcase(str(path)))
    home = os.path.normcase(str(anchor))
    inside = str(norm) == home or home in (os.path.normcase(str(p)) for p in norm.parents)
    if norm.is_dir():
        return DIR if inside else OUTSIDE
    if norm.is_file():
        return FILE if inside else OUTSIDE
    # 落点指到仓内的路径、但它在**这个工作树里不存在**：两件不同的事被折成了一句
    # "missing"，而本闸接着会把它读成"根写错了"。实测两例各错一半：
    #   ① `<repo>/data` —— 仓内目录且被 `.gitignore` 忽略，干净检出里本就不该有它，
    #      判据在**调用处**拼末级（`_sessionsDir()`）本身是对的；
    #   ② CI 的 `unit-tests` 腿用 `python -m pytest` 跑，**没有 `tests/__init__.py`**
    #      的空间里 `from tests import ast_scan` 取的是 pytest 装出来的**影子包**，
    #      它的 `__file__` 在 pytest 的 basetemp 下 ⇒ 同一份源码在这条腿上把仓根解到
    #      临时目录，本机也复现：临时目录被回收以后那些 `_Repo / 'neurova'` 就全成了
    #      "仓内、但不存在"。
    # 两种都**不是**根写错，也都不是"目录被改名删掉"（那一形是仓内路径解析正常、
    # 只是名字不对——它仍归 MISSING 点名）。判据只认一条可机器验的事实：
    # 解出来的**仓内相对路径能否由 git 认出它属于本仓**（`git ls-files` / `git check-ignore`）。
    if inside and _pathIsTrackedOrIgnored(norm, anchor):
        return NOT_CHECKED_OUT
    return MISSING


def _scanSites(tree: ast.AST, consts: dict, anchor: pathlib.Path,
               selfPath: pathlib.Path = None, scoped: dict = None) -> list:
    """这档里每个扫描落点的 `(入口, 根的落点态)`——落点态见上面六态的注释。

    按「接收者＋属性名」两维认，不按属性名单认：`ast.walk(tree)` 与 `os.walk(dir)`
    只差一个接收者，把前者当全仓扫描会把读数放大一个量级（本档取数路自己踩过的第一版错）。
    """
    out = []
    guarded = _existenceGuardedReceivers(tree)
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        attr = call.func.attr
        recv = ast.unparse(call.func.value) if isinstance(call.func.value, ast.expr) else ""
        top = recv.split(".")[0].split("(")[0]
        if top == "ast_scan" and attr in SHARED_SCAN_ENTRIES:
            expr = call.args[0] if call.args else None
            out.append((attr, _rootStatus(expr, consts, anchor, selfPath, scoped)))
        elif attr in FILE_ENUM_ATTRS and top not in NON_PATH_RECEIVERS:
            if recv in guarded:
                # 「先验目录在，再迭代空不空」那一形是**清理落点**，不是判据的扫描面：
                # 它指不到目录恰恰说明没东西要清，零命中是预期结果而不是假绿。
                # 只豁免"同一个接收者被同一个 if 条件用 is_dir()/exists() 守住"这一形——
                # 换个名字的守卫不认（见控制表里那条反例），否则豁免会漏成万能后门。
                continue
            out.append((attr, _rootStatus(call.func.value, consts, anchor, selfPath, scoped)))
        elif attr == "walk" and top == "os":
            expr = call.args[0] if call.args else None
            out.append(("os.walk", _rootStatus(expr, consts, anchor, selfPath, scoped)))
    return out


def _existenceGuardedReceivers(tree: ast.AST) -> set:
    """被同一条件里的 `X.is_dir()`／`X.exists()` 守住的接收者表达式集合。"""
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for sub in ast.walk(node.test):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("is_dir", "exists") and sub.args == []
                    and isinstance(sub.func.value, ast.expr)):
                guarded.add(ast.unparse(sub.func.value))
    return guarded


def _rootGap(sites: list) -> str:
    """这档有没有「静态根解到仓外／指不到目录」的落点——有就返回那一态，没有返回空串。"""
    for _entry, status in sites:
        if status in (OUTSIDE, MISSING):
            return status
    return ""


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


def _faceFindings(root: pathlib.Path, manifest: list, gaps: dict = None,
                  localGaps: dict = None, manifestGaps: dict = None) -> list:
    """挑出两类档：① 静态根解到仓外／指不到目录；② 有仓内扫描根却无面自证。

    `gaps` 传一个字典就回填 `rel -> 落点态`，供报错文案说清红的是哪一条规则——两类都算
    offender，但**修法相反**（①是把根写对，②是补断言），混成一句话人就不知道该动哪一处。
    `localGaps` 回填第三类（根绑在函数里的名字上，`rel -> 那些入口名`）。它**不计进 offender**，
    由 `test_scanRootsAreNeverBoundInsideAFunction` 单独零容忍：同一档报两处，人就分不清先动哪一步
    （正确次序＝先把根提到模块级，那档随即进入 DIR 那一支，面自证的要求才落到它头上）。
    """
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
        sites = _scanSites(tree, consts, root, selfPath=path.resolve(), scoped=_scopedBindings(tree))
        if localGaps is not None:
            localEntries = sorted({entry for entry, st in sites if st == LOCAL})
            if localEntries:
                localGaps[rel] = localEntries
        if manifestGaps is not None:
            entrySites, universe, iterReads, env = _manifestFace(
                tree, consts, root, selfPath=path.resolve(), scoped=_allBindings(tree))
            if entrySites and not _hasListProof(tree, universe, _countNames(tree),
                                                iterReads, env, root):
                manifestGaps[rel] = entrySites
        gap = _rootGap(sites)
        if gap:
            if gaps is not None:
                gaps[rel] = gap
            offenders.append(rel)
            continue

        if not any(st == DIR for _e, st in sites):
            continue
        if not _hasFaceProof(tree, _countNames(tree)):
            offenders.append(rel)
    return sorted(offenders)


def _firstSiteStatus(path: pathlib.Path, root: pathlib.Path):
    """这档第一个落点的落点态（不经过 `_faceFindings` 的点名过滤）。

    `gaps` 只回填被判为 offender 的档（那是它给报错文案用的契约）；反检格要验
    「不点名、且落点是 X」，得直接问取数口——否则它只能断言空串，
    而空串与"压根没取到数"在文本上同形。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    consts = _constTable(tree)
    scoped = _scopedBindings(tree)
    sites = _scanSites(tree, consts, root, selfPath=path.resolve(), scoped=scoped)
    return sites[0][1] if sites else None


#: ── 第七类形状：以清单为扫描面（§6-331 那张票的表示法落地）──────────────────────
#: 一条"逐条读清单、对每个条目动手"的判据，根不在文件系统里，而在那个**清单文件**上。
#: 它被截短（或路径写错）时读数一样缩水成"零 offender"，与真干净同形——所以要的正是
#: 「先证条目数对得上」这条面自证。
#:
#: 什么**不**算面：成员检查。`if rel not in listed: 红`——清单截短时它当场就红，属"坏得响"
#: 那一支（与 FILE 免裁同一条理由），本格不许把它算成落点，否则探测器会把 40 多档
#: 只读一份 `.cnb.yml` 的守卫全列成 offender（那是探测口径出错，不是存量）。
#:
#: 判定要三件同时成立（缺一不可，实施那轮被正控打回三次，每次都是少认一形）：
#:   (a) 清单源＝读到一个非 `.py` 清单文件上，含 list-comp／`splitlines()`／同文件 helper 一跳／
#:       **文件名当参数递进取数口**（`readAny('items.txt')`——helper 体内只有 `io.open(name)`，
#:       靠 `_literalListSuffix` 追那次调用的实参字面量才认得）；
#:   (b) 一次迭代（`for` 或推导式）的 iterable 污点自 (a)，**四种写法都算**：绑到清单名的名字
#:       （`for x in manifest`）、直调清单 helper（`for x in protectedFiles()`）、当场读再迭代
#:       （`for x in io.open(P).read().splitlines()`，本仓实测 9 处）、**类里的取数方法**
#:       （`for x in self._rows()`——这一形由 `_readsAList` 的**属性形方法跳**那一臂认，跳不进去就放出整族）；
#:   (c) 迭代变量**派生成路径**之后再动手：`path = 根 / 条目`、`.joinpath(条目)`、`Path(条目)`、
#:       f-string，或条目先过一道字符串处理再拼（`rel = line.split('#')[0].strip()` ⇒ `根 / rel`，
#:       台账那一族全是这个形状）；派生出的名字被 `read_text`/`open`/`is_file`/`exists`/`rglob`…
#:       动用才算，跳进同文件 helper 算一跳。
#: (c) 是这一形的要害，也是前两版漏掉的地方：第二版只认"动用在同一个 `BinOp` 子树内"，
#: 而真实代码都是先落变量再动手（`path = root / rel` 之后一句才 `path.is_file()`）——
#: 所以**污点要跨语句传递**，且条目在派生成路径之前常常先被切一遍字符串。
#: 但传递只认 `_isPathDerivation` 那几种形：上一版把"右值里提了一下条目名"的一般赋值全收，
#: 实测多出 19 档 false positive（`hits[rel] = calibers`、`len(rows) == len(declared)` 那一类）。
#: 面虚胖与面偏窄一样坏——它下次报"0 offender"就没人敢信（291 那一族的另一头）。
#: 批 104 补的那跳是**跨模块**：取数口收进 `ast_scan.protectedSubsetEntries()` 之后，"读清单"
#: 这件事根本不在本文件里，探测器若只跟同文件 helper，迁走的 6 档会在收口的**同一批**静默掉出
#: 清单面——形态集 313「判据的面由它自己的解析能力界定」那一族的新变种，且这次是治理动作自己
#: 造出来的。字典/集合中转、条目取字段（`row[0]`）再拼路径这几形也都认到（各配一格正检）。
LIST_SUFFIXES = (".txt", ".json", ".md", ".yml", ".yaml", ".ini", ".cfg", ".toml")
LIST_READS = {"read_text", "read", "readlines", "open"}
ENTRY_USES = {"read_text", "read", "open", "is_file", "is_dir", "exists", "rglob", "glob",
              "iterdir", "stat", "joinpath"}


def _helpersOf(tree: ast.AST) -> dict:
    """同文件的函数表——(a) 与 (c) 都要跳一跳，不跳就认不出 `_manifestOf(...)`／`_scanOne(rel)` 这类真形状。"""
    return {f.name: f for f in ast.walk(tree)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}


#: ── 跨模块一跳（§6-332 登记的那条形制，批 104 落地）─────────────────────────────
#: 取数口收口到 `tests/ast_scan.py::protectedSubsetEntries()` 之后，读清单这件事就**不在本文件里了**：
#: 档里只剩 `ast_scan.protectedSubsetEntries()` 或 `from tests.ast_scan import ...`。
#: 探测器要是只跟同文件 helper，那 6 档会**在收口的同一批静默掉出清单面**——正是形态集 313
#: 「判据的面由它自己的解析能力界定」那一族的新变种，而且这次是治理动作自己造出来的。
#: 所以认形必须与收口同批到位。缓存只存**算完的函数名集合**并按 (路径, mtime, 大小) 记，
#: 不存语法图——490 棵常驻树会把本闸变成 Issue #197 点过的那种 GC 账单（形态集 209）。
_MODULE_LIST_NAMES: dict = {}

#: 允许的 import 形态（各配一枚合成正检；不在列的形态不许猜——猜出来的面不算面）
def _importBase(node, anchor: pathlib.Path, selfPath: pathlib.Path = None):
    """`from a.b import c` / `from ..b import c` 里那个 `a.b`／`..b` 解成仓内目录或模块前缀。"""
    parts = tuple(node.module.split(".")) if node.module else ()
    if node.level:
        base = selfPath.parent if selfPath is not None else anchor
        for _ in range(node.level - 1):
            base = base.parent
        return base.joinpath(*parts) if parts else base
    return anchor.joinpath(*parts) if parts else anchor


def _moduleFile(base: pathlib.Path, tail: str, anchor: pathlib.Path = None):
    """把 `<base>.<tail>` 解成仓内真实文件：模块本身、子模块、或包的 `__init__.py`。

    这里**只做存在性判定**，不建全树索引：先前用 `os.walk` 建过一份 `.py` 索引来省 stat，
    那一步把「枚举入口＋私有解析」凑进了本闸自己的调用闭包，被 `TestNoUnprefilteredRepoWideScan`
    当场点名（形态集 312 那条：枚举入口一旦进了被消费的 helper 的闭包，账单记在整个取数口上）。
    """
    cands = [base.with_suffix(".py")]
    if tail:
        cands += [base / (tail + ".py"), base / tail / "__init__.py", base / "__init__.py"]
    else:
        cands.append(base / "__init__.py")
    for cand in cands:
        if cand.is_file():
            return cand
    return None


def _importEnv(tree: ast.AST, anchor: pathlib.Path, selfPath: pathlib.Path = None) -> dict:
    """`modules`：`ast_scan -> <仓内模块文件>`；`funcs`：`受入名 -> [(模块文件, 本名)]`。

    认三种真在用的写法：`from tests import ast_scan`（走属性调用那一支）、
    `from tests.ast_scan import name`（直接导入函数那一支）、测试档里的相对导入
    `from . import x`／`from ..y import z`。**不**认 `importlib.import_module`／`__import__`
    那种动态取数——那是"猜面"，登记在边界段里而不是这里。
    """
    modules, funcs = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = _importBase(node, anchor, selfPath)
            if base is None:
                continue
            own = base.with_suffix(".py")
            pkg = base / "__init__.py"
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                for holder in (own if own.is_file() else None, pkg if pkg.is_file() else None):
                    if holder is not None:
                        funcs.setdefault(local, []).append((holder, alias.name))
                sub = _moduleFile(base, alias.name, anchor)
                if sub is not None and sub != own:
                    modules[local] = sub
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                mod = _moduleFile(anchor / pathlib.Path(*alias.name.split(".")), "", anchor)
                if mod is not None:
                    modules[local] = mod
    return {"modules": modules, "funcs": funcs}


def _moduleFacts(path: pathlib.Path, anchor: pathlib.Path) -> frozenset:
    """那个模块里**自己读清单**的函数名集合——按 (路径, mtime, 大小) 记，只记这个名字集合。

    三条约束决定了这个形状：
    ① 缓存必须打洞（改文件即失效），不做"一次解析永久有效"——与本仓 `ast_scan._cacheKey` 同口径；
    ② **不保留语法图**，只保留算完的函数名集合。留着 490 棵常驻树会把本闸变成 Issue #197
       点过的那种账单（gen2 每扫一遍都走完整棵图），而判据自身的成本也是回归面（形态集 209）；
    ③ 未先过文本预筛就解析＝白付一趟。清单后缀字面量没出现在那份源码里，就不可能有函数
       把路径解析成清单（一跳之内路径总得在某处写成字面量），所以这一筛对本规则是**无损**的。
    只算**同文件规则**那一层：模块链因此一跳封顶，两跳以上登记在边界段里。
    """
    try:
        stamp = path.stat()
    except OSError:
        return frozenset()
    key = (str(path), stamp.st_mtime_ns, stamp.st_size)
    cached = _MODULE_LIST_NAMES.get(key)
    if cached is not None:
        return cached
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _MODULE_LIST_NAMES[key] = frozenset()
        return _MODULE_LIST_NAMES[key]
    if not any(suf in source for suf in LIST_SUFFIXES):
        _MODULE_LIST_NAMES[key] = frozenset()
        return _MODULE_LIST_NAMES[key]
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _MODULE_LIST_NAMES[key] = frozenset()
        return _MODULE_LIST_NAMES[key]
    consts, helpers, scoped = _constTable(tree), _helpersOf(tree), _allBindings(tree)
    names = frozenset(fn.name for fn in ast.walk(tree)
                      if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and _readsAList(fn, consts, helpers, anchor, selfPath=path,
                                      depth=1, scoped=scoped))
    _MODULE_LIST_NAMES[key] = names
    return names


def _crossModuleTargets(env: dict, call: ast.Call) -> list:
    """这次调用可能打到的 `(模块文件, 函数名)` 候选——Name 形有多个受入来源就全试，不取首个。"""
    func = call.func
    if isinstance(func, ast.Name):
        return list(env["funcs"].get(func.id, []))
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        modPath = env["modules"].get(func.value.id)
        return [(modPath, func.attr)] if modPath is not None else []
    return []


def _crossModuleReadsList(env: dict, call: ast.Call, anchor: pathlib.Path, depth: int) -> bool:
    """跟**模块一跳**：这次调用打到的函数，是不是在它自己的模块里读了一份清单。

    只在看得到具体调用时才解析那个模块（`_moduleFacts` 按轮缓存）——早先版本把每个被 import
    的模块都解析一遍再列"读清单的函数名"，实测把本闸的扫描从 4.7s 推到 14.7s（判据自身的成本
    也是回归面，形态集 209 那一族）。
    """
    if depth > 4:
        return False
    return any(name in _moduleFacts(modPath, anchor)
               for modPath, name in _crossModuleTargets(env, call))


def _operandMentionsList(side: ast.AST, universe: set, env: dict, anchor: pathlib.Path) -> bool:
    """断言的这一侧到底是不是"在量这份清单"——出现清单名，或出现一次打到跨模块清单取数口的调用。

    后一支是给 `assert len(ast_scan.protectedSubsetEntries()) > 500` 这种不落包装名的写法留的：
    它没有本地名字可匹配，但调用打过去就是那份清单的读法。
    """
    for n in ast.walk(side):
        if isinstance(n, ast.Name) and n.id in universe:
            return True
        if isinstance(n, ast.Call) and _crossModuleReadsList(env, n, anchor, 0):
            return True
    return False


def _allBindings(tree: ast.AST) -> dict:
    """`NAME -> [该文件里所有赋值右值]`。清单源的追查要用**全部**绑定：
    同名在不同函数里各拼一条路径是常态（本文件自己就有 `path = root / rel` 与
    `path = root / "scripts" / "ci" / "protected_tests.txt"` 两处），取首次会把后者判成"不是清单"。
    （LOCAL 那一侧故意用首次——那里的目的相反：最后一次常已是运行时值。）
    """
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out.setdefault(node.target.id, []).append(node.value)
    return out


def _literalListSuffix(node, scoped: dict, depth: int = 0) -> bool:
    """这个表达式（顺带它绑到的本地名字，两跳）里有没有以清单后缀结尾的**字符串字面量**。

    这一跳是第三版才补上的：真代码常常是 `path = root / "scripts" / "ci" / "protected_tests.txt"`
    里 `root` 是个**参数**（锚解不出来），随后 `io.open(path)` 只拿到那个本地名。
    按"字面量清单文件名"认不是按词判——它只看代码子树里的路径拼装，docstring 提一句不算。
    """
    if node is None or depth > 3:
        return False
    if isinstance(node, ast.Name) and node.id in scoped:
        cands = scoped[node.id]
        cands = cands if isinstance(cands, list) else [cands]
        return any(_literalListSuffix(c, scoped, depth + 1) for c in cands)
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and n.value.lower().endswith(LIST_SUFFIXES) for n in ast.walk(node))


def _readsAList(node: ast.AST, consts: dict, helpers: dict, anchor: pathlib.Path,
                selfPath: pathlib.Path = None, depth: int = 0, scoped: dict = None,
                env: dict = None, listArgAtCall: bool = False) -> bool:
    """这段子树里有没有"读一个非 .py 清单"；同文件 helper 跟一跳，**跨模块也跟一跳**（批 104）。

    跨模块那一跳是取数口收口的**前置**而不是补充：`protectedFiles()` 改成
    `ast_scan.protectedSubsetEntries()` 之后，读清单这件事在本档源码里就看不见字面量了——
    探测器要是不跟着走，那 6 档会在治理成功的同一批静默掉出清单面（形态集 313 那一族，
    而这次是治理动作自己造出来的盲区）。深度上限 4 防自旋；`env` 缺席（老调用方）就只走同文件那一支。

    `listArgAtCall` 是**调用点**那一侧的事实：`readAny("requirements-ci.txt")` 这种"文件名当参数
    递进去"的取数口，helper 体内只有 `io.open(name)`，光看 helper 认不出那是清单。
    每加一支认形就配一枚正检（310/318 那条纪律）——见 `_MANIFEST_SHAPES` 里那两枚新的。
    """
    if depth > 4:
        return False
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if isinstance(func, ast.Attribute) and func.attr in LIST_READS:
            if listArgAtCall:
                # 清单文件名是调用点递进来的（`readAny("requirements-ci.txt")`）——helper 体内
                # 只有 `io.open(name)`，光看 helper 认不出那份清单是谁；把调用点的字面量带下来。
                return True
            base = func.value if func.attr != "open" else (call.args[0] if call.args else None)
            r = _resolveRoot(base, consts, anchor, selfPath=selfPath) if base is not None else None
            if r is not None and str(r).lower().endswith(LIST_SUFFIXES):
                return True
            if base is None and isinstance(func.value, ast.Name):     # `path.read_text()` 里 path 解不出
                base = func.value
            if _literalListSuffix(base, scoped or {}, 1):
                return True
        hopName = None
        if isinstance(func, ast.Name) and func.id in helpers:
            hopName = func.id
        elif isinstance(func, ast.Attribute) and func.attr in helpers:
            # 类里的取数方法（`for row in self._rows()`）：不认这一支就把台账那一族整族放出面
            hopName = func.attr
        if hopName is not None:
            hopArg = listArgAtCall or any(
                _literalListSuffix(a, scoped or {}, 1) for a in call.args)
            if _readsAList(helpers[hopName], consts, helpers, anchor, selfPath, depth + 1,
                           scoped, env, hopArg):
                return True
        elif env is not None and _crossModuleReadsList(env, call, anchor, depth):
            return True
    return False


def _listSources(tree: ast.AST, consts: dict, helpers: dict, anchor: pathlib.Path,
                 selfPath: pathlib.Path = None, scoped: dict = None,
                 env: dict = None) -> set:
    """绑定自"读一份清单"的名字集，外加由它派生的名字（`raw = P.read_text()` → `lines = raw.splitlines()`）。

    清单源常常绑在**函数内**（`manifest = _manifestOf(ROOT)`），只看模块级常量表就会把它整个漏掉——
    这就是第二版探测器报零的真因，两档正控里的那一档正是这一形。
    """
    bindings: dict = {}
    for name, val in (scoped or consts).items():
        bindings[name] = val if isinstance(val, list) else [val]
    for name, val in consts.items():
        bindings.setdefault(name, [val])
    out = {n for n, exprs in bindings.items()
           if any(_readsAList(e, consts, helpers, anchor, selfPath, scoped=scoped, env=env)
                  for e in exprs)}
    # **当场读、不落变量**的那一形也要有名字可追：`raw = (ROOT / "x.txt").read_text()` 里
    # 清单路径是内联拼出来的，`_readsAList` 认这次读法，但读法所在的整个表达式才是要污点化的对象。
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and _readsAList(node.value, consts, helpers, anchor, selfPath,
                                scoped=scoped, env=env):
            out.add(node.targets[0].id)
    grew = True
    while grew:
        grew = False
        for name, exprs in bindings.items():
            if name in out:
                continue
            if any(isinstance(n, ast.Name) and n.id in out for e in exprs for n in ast.walk(e)):
                out.add(name)
                grew = True
    return out


def _loopsOf(tree: ast.AST):
    """`for` 与四种推导式统一成 `(迭代目标, iterable, 体片段)`。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            yield node.target, node.iter, list(node.body)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            for gen in node.generators:
                if isinstance(node, ast.DictComp):
                    parts = [node.key, node.value]
                else:
                    parts = [node.elt]
                yield gen.target, gen.iter, parts + list(gen.ifs)


#: 把条目**拼成路径**的那几种写法（污点沿这些形状前进）。
PATH_MAKERS = {"joinpath", "join", "Path", "PurePath"}


def _mentionsTainted(node, tainted: set) -> bool:
    if node is None:
        return False
    nodes = node if isinstance(node, (list, tuple)) else [node]
    return any(isinstance(n, ast.Name) and n.id in tainted
               for x in nodes for n in ast.walk(x))


def _isPathDerivation(sub: ast.AST, tainted: set) -> str:
    """这个赋值是不是"把清单条目拼成路径 / 对条目做字符串处理"？是就返回该被污染的名字。

    刻意**不收**"右值里提了一下条目名"这种一般赋值。上一版收得很宽（`NAME = 任何含条目名的式子`），
    后果是多出 19 档 false positive——`hits[rel] = calibers`、`assert len(rows) == len(declared)`
    那一类都算成了清单面。面一旦虚胖，它下次报"0 offender"就谁都不敢信（291 那一族：坏取的数
    偏小偏干净，也一样偏大偏脏）。留下的两形各有真实例子：
      * `path = 根 / 条目`、`根.joinpath(条目)`、`Path(条目)`、f-string 拼路径；
      * 条目先过一道字符串处理再拼（`rel = line.split('#')[0].strip()` ⇒ `根 / rel`），
        台账那一族全是这个形状——只认第一种就会把整族漏掉。
    函数调用一律**不**传污点（`clockCalibersOf(source)` 那种），否则污点会顺着任意 helper 蔓延。
    """
    if not (isinstance(sub, ast.Assign) and len(sub.targets) == 1
            and isinstance(sub.targets[0], ast.Name)):
        return ""
    rhs = sub.value
    if isinstance(rhs, ast.BinOp) and isinstance(rhs.op, ast.Div) and _mentionsTainted(rhs, tainted):
        return sub.targets[0].id
    if isinstance(rhs, ast.JoinedStr) and _mentionsTainted(rhs, tainted):
        return sub.targets[0].id
    if isinstance(rhs, ast.Call):
        fn = rhs.func
        if isinstance(fn, ast.Attribute) and (
                fn.attr in PATH_MAKERS or _mentionsTainted(fn.value, tainted)):
            if _mentionsTainted(rhs.args, tainted) or _mentionsTainted(fn.value, tainted):
                return sub.targets[0].id
        elif isinstance(fn, ast.Name) and fn.id in PATH_MAKERS and _mentionsTainted(rhs.args, tainted):
            return sub.targets[0].id
    return ""


def _actsOnEntry(node: ast.AST, tainted: set, helpers: dict, depth: int = 0):
    """条目（或它派生出的路径名）有没有被"动手"——命中时返回**那次动用的原文**。

    返回文本而不是布尔，是因为报错只给行号时人还得去数哪一行：`151` 既不说明是哪次读法，
    也不说明污点从哪个名字来。把动用原样带出来，红的时候直接能判断是不是真清单面。

    **污点集是传进来的同一个 set，本函数会往里加派生名**——这是第三版探测器补的洞：
    真代码的形状是两条语句，`path = REPO_ROOT / rel` 然后 `path.is_file()`，若每条语句各拿一份
    新集合，第二条就看不见 `path` 是从条目派生来的（实测本档第一版只认出 3 档，收了这个洞之后才齐）。
    派生只认 `_isPathDerivation` 那几种形；跳进 helper 那一支仍然传新集合：
    形参名不该污染调用方的名字空间。
    """
    if depth > 2:
        return None
    for sub in ast.walk(node):
        derived = _isPathDerivation(sub, tainted)
        if derived:
            tainted.add(derived)
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute) and func.attr in ENTRY_USES:
                touched = [func.value] + list(sub.args)
                hits = sorted({n.id for x in touched for n in ast.walk(x)
                               if isinstance(n, ast.Name) and n.id in tainted})
                if hits:
                    return "%s ← 污点名 %s" % (ast.unparse(sub)[:78].replace("\n", " "),
                                               ", ".join(hits))
            elif isinstance(func, ast.Name) and func.id in ENTRY_USES:
                hits = sorted({n.id for x in list(sub.args) + [k.value for k in sub.keywords]
                               for n in ast.walk(x) if isinstance(n, ast.Name) and n.id in tainted})
                if hits:
                    return "%s ← 污点名 %s" % (ast.unparse(sub)[:78].replace("\n", " "),
                                               ", ".join(hits))
            elif isinstance(func, ast.Name) and func.id in helpers:
                fn = helpers[func.id]
                params = [a.arg for a in fn.args.args]
                for i, arg in enumerate(sub.args):
                    if i < len(params) and any(isinstance(n, ast.Name) and n.id == params[i]
                                               for n in ast.walk(fn)) \
                            and any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(arg)):
                        inner = _actsOnEntry(fn, {params[i]}, helpers, depth + 1)
                        if inner:
                            return "%s(...) 内 %s" % (func.id, inner)
    return None


def _listUniverse(tree: ast.AST, consts: dict, helpers: dict, anchor: pathlib.Path,
                  selfPath: pathlib.Path = None, scoped: dict = None,
                  env: dict = None) -> set:
    """「这份清单」在档内的全部名字：绑到清单读法上的名字 ∪ 同文件读清单的 helper ∪
    **跨模块**读清单的取数口（批 104 随取数口收口一起加，少这一族就会让迁走的 6 档静默掉出面）。
    """
    sources = _listSources(tree, consts, helpers, anchor, selfPath, scoped, env)
    listHelpers = {n for n, fn in helpers.items()
                   if _readsAList(fn, consts, helpers, anchor, selfPath, 1, scoped, env)}
    return sources | listHelpers


def _iterIsListTainted(iter_: ast.AST, universe: set, readsAList=None) -> bool:
    """这次迭代的**数据到底从哪来**——三种来源一视同仁：

    绑到清单读法的名字（`for x in manifest`）、直调清单 helper（`for x in protectedFiles()`）、
    **当场读清单**（`for x in (ROOT / "protected_tests.txt").read_text().splitlines()`）。
    第三种是批 103 现扫补的：本仓有 9 处这种「不落变量直接迭代」的写法，只按名字追污点
    就等于把它们当成不存在。批 107 又**删掉一条没人独占的支路**：原先这里还有一条 `_calledNames`
    （把被调者按名字记下来，属性形也算）——它与「Name 节点集合 ∪ 方法跳」完全重叠，整条摘掉
    本闸 49 格全绿。留着它就是一条看着有牙、实际咬不到的假保险（形态集 321 的收口）。
    （`test_dev_path_and_runtime_dep_guards`／`test_experience_quality_gate`／
    `test_context_facade_retirement` 等），只按名字追污点就等于把它们当成不存在。
    """
    origins = {n.id for n in ast.walk(iter_) if isinstance(n, ast.Name)}
    if origins & universe:
        return True
    return bool(readsAList is not None and readsAList(iter_))


def _hasListProof(tree: ast.AST, universe: set, counts: set, readsAList=None,
                  env: dict = None, anchor: pathlib.Path = None) -> bool:
    """清单面的自证必须**由这份清单得到**——档里另一条无关的数值断言不算。

    为什么不能沿用文件级的 `_hasFaceProof`：那条只问"本档有没有一条 `assert <计数> > 数`"，
    而 §6-331 点名的那一档（`test_ci_ast_scan_budget_guard.py`）里绿着的两条是
    `assert len(nodes) > 1000`（夹具节点数）与 `assert len(seen) == 1`（去重），
    与它按 `protectedFiles()` 逐档扫描那条面**没有关系**。沿用文件级豁免，就是让一个
    不相干的断言替清单面背书——清单被截短时照样绿，正是本闸要防的那件事。
    认两形：`len(...)`/`sum(...)`/计数名的操作数子树里出现清单名（或直调清单 helper），
    以及**在一次清单迭代之内累加**的计数器（`parsed += 1` 那一形）。
    """
    accumulators = set()
    for _target, iter_, body in _loopsOf(tree):
        if not _iterIsListTainted(iter_, universe, readsAList):
            continue
        for stmt in body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name) \
                        and isinstance(sub.op, ast.Add):
                    accumulators.add(sub.target.id)
    tainted = universe | accumulators
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        cmp_ = node.test
        if not any(isinstance(op, (ast.Gt, ast.GtE)) for op in cmp_.ops):
            continue
        if not any(isinstance(o, ast.Constant) and isinstance(o.value, (int, float))
                   for o in cmp_.comparators):
            continue
        for side in [cmp_.left] + list(cmp_.comparators):
            text = ast.unparse(side).strip()
            if not (text.startswith(("len(", "sum(")) or text in counts
                    or text in accumulators):
                continue
            if env is not None and anchor is not None:
                if _operandMentionsList(side, tainted | universe, env, anchor):
                    return True
            elif any(isinstance(n, ast.Name) and n.id in tainted for n in ast.walk(side)):
                return True
    return False


def _manifestFace(tree: ast.AST, consts: dict, anchor: pathlib.Path,
                  selfPath: pathlib.Path = None,
                  scoped: dict = None) -> tuple:
    """`(清单落点行号, 清单名集, 「这次迭代是不是清单」的判据)`——三样同源于一次污点追查。

    那个判据要一起返回：`_hasListProof` 认累加器时问的是同一个问题（"这条循环迭代的是清单吗"），
    两处各写一遍就会分叉（本仓的"两把尺"教训，形态集 304）。
    """
    helpers = _helpersOf(tree)
    scoped = scoped or _allBindings(tree)
    env = _importEnv(tree, anchor, selfPath)
    universe = _listUniverse(tree, consts, helpers, anchor, selfPath, scoped, env)

    def iterReadsList(node: ast.AST) -> bool:
        return _readsAList(node, consts, helpers, anchor, selfPath, scoped=scoped, env=env)

    out = []
    seen = set()
    for target, iter_, body in _loopsOf(tree):
        if not isinstance(target, ast.Name):
            continue
        if not _iterIsListTainted(iter_, universe, iterReadsList):
            continue
        tainted = {target.id}
        for stmt in body:
            act = _actsOnEntry(stmt, tainted, helpers)
            if act:
                line = getattr(stmt, "lineno", 0)
                if line not in seen:
                    seen.add(line)
                    out.append((line, act))
                break
    return out, universe, iterReadsList, env


def _manifestSites(tree: ast.AST, consts: dict, anchor: pathlib.Path,
                   selfPath: pathlib.Path = None, scoped: dict = None) -> list:
    """这一档里「以清单为扫描面」的落点行号（(a)(b)(c) 三件齐了才算）。

    (b) 认四种 iterable：绑到清单源的名字（`for x in manifest`）、直接调清单 helper
    （`for x in protectedFiles()`）、当场读清单再迭代（`for x in P.read_text().splitlines()`）、
    类里的取数方法（`for x in self._rows()`）。后两种分别由批 103、批 104 的正控打出来才补上——
    少认一种，就有整档安静掉出面。
    """
    return _manifestFace(tree, consts, anchor, selfPath, scoped)[0]


def _manifestOf(root: pathlib.Path) -> list:
    """本闸取受保护子集清单——**读法不在这里**，取数口是 `ast_scan.protectedSubsetEntries(root)`。

    这层包装只为控制格能喂临时根；`PROTECTED` 那个常量以前自己 `io.open`，现在留着它就是第二份读法。
    """
    return ast_scan.protectedSubsetEntries(root)


#: ── 清单取数口的单源判据（`READER_BASELINE` 的取数口，与上面那张表同源）────────────
MANIFEST_FILE_NAME = "protected_tests.txt"
#: 唯一被允许自己开这份清单的文件——收口之后就剩这一处。
#: 它自己的三条承诺（剥注释／清单缺席即响亮失败／条目数与"指得到真实文件"的等号）由
#: `test_singleSourceReaderKeepsItsOwnContract` 钉住：把 34 档抄本收进一处，若不给那一处立契约，
#: 只是把"各抄各的、没人验"换成"一处没验"。
SINGLE_SOURCE = "tests/ast_scan.py"


def _manifestReadSites(tree: ast.AST, consts: dict, anchor: pathlib.Path,
                       selfPath: pathlib.Path = None, scoped: dict = None) -> list:
    """这一档里"自己去读那份清单"的落点行号。

    只认**代码形态**：一个读法调用（`open`/`read_text`/`read`/`readlines`），其路径要么解得到
    `.../protected_tests.txt`，要么整个子树里出现以该文件名结尾的字符串字面量。
    不认"注释或 docstring 里提到这个文件名"——本仓的守卫被自家文档撞红过（按词判的那一族）。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attr = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if attr not in LIST_READS:
            continue
        base = node.args[0] if (attr == "open" and node.args) else (
            func.value if isinstance(func, ast.Attribute) else None)
        resolved = _resolveRoot(base, consts, anchor, selfPath=selfPath) if base is not None else None
        if resolved is not None and str(resolved).endswith(MANIFEST_FILE_NAME):
            out.append(node.lineno)
            continue
        if any(isinstance(k, ast.Constant) and isinstance(k.value, str)
               and k.value.endswith(MANIFEST_FILE_NAME)
               for sub in ([base] if base is not None else []) for k in ast.walk(sub)):
            out.append(node.lineno)
    return sorted(set(out))


def _readerCounts(root: pathlib.Path, manifest: list) -> dict:
    """`rel -> 该档自己读那份清单的落点数`（单点自身不计）。**表只能由这个函数生成**。"""
    out = {}
    for rel in manifest:
        if rel == SINGLE_SOURCE:
            continue
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        sites = _manifestReadSites(tree, _constTable(tree), root, selfPath=path.resolve(),
                                   scoped=_allBindings(tree))
        if sites:
            out[rel] = len(sites)
    return out


def test_protectedSubsetReaderIsSingleSource():
    """这份清单的读法只准有一处（`tests/ast_scan.py`）——新增即红、消化必须摘行。

    为什么要有这一格：收口做到一半时，"只准一处"这件事若只写在注释里，下一档需要清单的判据
    仍会就地再抄一份 `io.open(PROTECTED)`（收口前实测 34 档 / 37 处各抄一份，抄本各自决定剥不剥注释、
    返回 list 还是 set——`_gitLsFiles` 那一族就是因为这个才收的）。教义第 6 条要的是"只有一处定义"，
    而"只剩一处"这件事必须有个会红的格子看着。
    """
    now = _readerCounts(ANCHOR, _manifestOf(ANCHOR))
    grew = {f: (now[f], READER_BASELINE.get(f, 0)) for f in now
            if now[f] > READER_BASELINE.get(f, 0)}
    assert not grew, (
        "受保护子集清单又多出了自抄的读法（这份清单是 CI 的唯一执行面，读法只准在 "
        f"`{SINGLE_SOURCE}` 一处）：\n  "
        + "\n  ".join(f"  {f} 现 {n} 处 / 基线 {b} 处" for f, (n, b) in sorted(grew.items()))
        + "\n修法：`from tests import ast_scan` 然后 `ast_scan.protectedSubsetEntries()`——"
        "\n要集合就 `set(...)`，别再去开那份文件。"
    )
    dropped = {f: (READER_BASELINE[f], now.get(f, 0)) for f in READER_BASELINE
               if now.get(f, 0) < READER_BASELINE[f]}
    assert not dropped, (
        "这些档的自抄读法已经改指单点了——把 READER_BASELINE 里那几行摘掉再提交，别让它悬着"
        "（悬着的后果：下一条真新增的抄本会被旧表兜住而看不见）：\n  "
        + "\n  ".join(f"  {f} 基线 {b} 处 / 现 {n} 处" for f, (b, n) in sorted(dropped.items()))
    )


@pytest.mark.parametrize("label, source, expectSites", [
    ("正检·`io.open(PROTECTED)` 那一形必须被数到",
     "import io\nimport pathlib\n"
     "PROTECTED = pathlib.Path(__file__).resolve().parents[2] / 'items.txt'\n\n\n"
     "def test_shape():\n"
     "    return io.open(PROTECTED, encoding='utf-8').read()\n", 1),
    ("正检·当场拼路径再 `read_text`（不落常量）也要被数到",
     "import pathlib\n_ROOT = pathlib.Path(__file__).resolve().parents[2]\n\n\n"
     "def test_shape():\n"
     "    return (_ROOT / 'sub' / 'items.txt').read_text(encoding='utf-8')\n", 1),
    ("正检·路径由 helper 拼出来（`repo_path('scripts','ci','items.txt')`）——解析支解不出，"
     "只有字面量支认得（真仓 37 处里就有 1 处靠它，见 `test_experience_quality_gate.py`）",
     "import pathlib\n_ROOT = pathlib.Path(__file__).resolve().parents[2]\n\n\n"
     "def repoPath(*parts):\n    return _ROOT.joinpath(*parts)\n\n\n"
     "def test_shape():\n"
     "    return repoPath('scripts', 'ci', 'items.txt').read_text(encoding='utf-8')\n", 1),
    ("反检·只在 docstring 里提这个文件名＝不算读法",
     "import pathlib\n\n\n"
     "def test_shape():\n"
     "    \"\"\"这条判据与 items.txt 有关，但不读它。\"\"\"\n"
     "    return 1\n", 0),
    ("反检·改指单点之后不许再被数到（这一格钉的是修法的形状）",
     "import pathlib\nimport sys\n\n"
     "_Root = pathlib.Path(__file__).resolve().parents[2]\n"
     "sys.path.insert(0, str(_Root))\n"
     "from tests import ast_scan\n\n\n"
     "def test_shape():\n"
     "    return ast_scan.protectedSubsetEntries(_Root)\n", 0),
])
def test_readerPredicateJudgesEachShape(tmp_path, label, source, expectSites):
    """单源判据的认形要有牙：三种自抄形各一枚正检，两种"不该红"各一枚反检。

    三条正检分别钉住两条认形支：常量根、当场拼路径（解析支），以及**路径由 helper 拼出来**
    （只有字面量支认得）。为什么要拆到这一层：摘掉字面量支跑同一批控制格，四格全绿——
    说明原来的取值没落在两支的分歧点上（形态集 239），而真仓 37 处里确实有 1 处只被它咬到。
    文件名在这里换成 `items.txt`（`MANIFEST_FILE_NAME` 临时改指它）——判据读的是"清单本体"这个
    形状，用真清单名做控制格会让 tmp 树里没有那个文件、正检打空（本仓 316 那一族：先证这格能红）。
    """
    global MANIFEST_FILE_NAME
    (tmp_path / "tests" / "unit" / "ci").mkdir(parents=True)
    (tmp_path / "items.txt").write_text("a.py\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "items.txt").write_text("a.py\n", encoding="utf-8")
    sample = tmp_path / "tests" / "unit" / "ci" / "sample.py"
    sample.write_text(source, encoding="utf-8")
    tree = ast.parse(source)
    saved = MANIFEST_FILE_NAME
    MANIFEST_FILE_NAME = "items.txt"
    try:
        got = _manifestReadSites(tree, _constTable(tree), tmp_path,
                                 selfPath=sample.resolve(), scoped=_allBindings(tree))
    finally:
        MANIFEST_FILE_NAME = saved
    assert len(got) == expectSites, f"{label} ⇒ 现读 {got}"


def test_singleSourceReaderKeepsItsOwnContract():
    """收口之后，单点自己的三条承诺得有格子钉——否则"只剩一处读法"＝"只剩一处没验过的读法"。

    三条各自的坏法：
    ① 不剥 `#` 注释与空行 ⇒ 清单里注释行比条目还多（现读 2607 行注释），整闸会把它们当成
       待跑节点，红指向一堆根本不存在的路径，报的是**这条读法**而不是被测对象；
    ② 清单不在时回**空列表** ⇒ "扫了个空"被读成"清单干净"（与本模块 `_gitLsFiles` 那条同形），
       所以必须响亮失败；
    ③ 面自证：真根下条目数下限＋"清单里的条目指得到真实文件"必须为 0——这正是本闸要求别的档
       给清单面留的那个等号，用在自己身上（不这样，这张表的裁决力建立在一个没人量的读法上）。
    """
    entries = ast_scan.protectedSubsetEntries(PROJECT_ROOT)
    assert len(entries) > 500, f"单点解出的条目数异常小：{len(entries)} 条"
    assert not [e for e in entries if e.startswith("#") or not e.strip()], "注释行或空行没被剥掉"
    missing = [e for e in entries if not (PROJECT_ROOT / e).is_file()]
    assert not missing, (f"清单里指不到真实文件的条目 {len(missing)} 条，前 5 条：{missing[:5]}")
    with pytest.raises(AssertionError):
        ast_scan.protectedSubsetEntries(PROJECT_ROOT / "no_such_root_for_single_source")


def test_ratchetDoesNotRise():
    """新增「扫仓内路径而不自证面」或「根写错」的判据档一律拦。

    报错文案按**全量现读**分组，不按 `now - BASELINE`：`BASELINE` 已是空表（四波存量收完），
    两者当天同值；但只要有人把 offender 加回表里换这一格变绿，按差集取数就会印出**空的**
    「根写错了」那一栏——红着，却一个字都没说清是哪一档，而同一棵树里的
    `test_staticRootsNeverPointOutsideOrNowhere` 会把那档点名（判据与文案分家，形态集 304 同族）。
    """
    gaps = {}
    now = set(_faceFindings(ANCHOR, _manifestOf(ANCHOR), gaps))
    grew = sorted(now - set(BASELINE))
    gaps = _dropSignedOffMissing(gaps)
    grew = [rel for rel in grew if rel not in set(MISSING_BASELINE) or gaps.get(rel)]
    wrongRoot = [rel for rel in grew if gaps.get(rel)]
    noProof = [rel for rel in grew if not gaps.get(rel)]
    assert not grew, (
        "**根写错了**（静态根解到仓外或指不到真实目录——它的「零命中」根本不来自代码）：\n  "
        + "\n  ".join("%s [%s]" % (rel, gaps[rel]) for rel in wrongRoot)
        + "\n**扫了仓内源码树却没把这次扫到的数量当断言比**（根被改窄时读数是「零命中」而不是红）：\n  "
        + "\n  ".join(noProof)
        + "\n修法分两条码：前者把根写对（`Path(__file__).resolve().parents[N]` 的 N 要按**本档所在深度**算）；"
        "\n后者一行即可，形如 `scanned = len(...); assert scanned > 500, f\"扫描面现读 {scanned}\"`，"
        "\n参考同档 `test_surfaceCoversAllThreeSourceFamilies`（先验面，再谈零命中）。"
        "\n别把新档加进基线表——那等于把这条棘轮又拆回各判各的。"
    )


def test_staticRootsNeverPointOutsideOrNowhere():
    """静态根必须解得到**仓内真实目录**——这一条不留存量豁免。

    为什么要单开一格：`test_ratchetDoesNotRise` 只比"比基线新增了什么"，于是**本来就在表里**的
    一档把根写错时，它照样留在 offender 里、失败集合一个字节都没变——存量名单把「根错了」这件
    更重的事兜掉了。本会话实测：把 `test_route_vocabulary_is_single_source.py` 的 `parents[3]`
    改成 `parents[4]`，棘轮两格全绿。反证在册：`test_faceRulesPinDepthAndWrongRoots` 的
    parents[3].parent／no_such_dir 两格必须交出**非空**的 gaps，否则这里的零断言只说明探测器没在跑。

    仓外（`outside`）零容忍；**缺席（`missing`）**才走 `MISSING_BASELINE` 署名——两种都叫"解不到"，
    但修法相反（前者改 N，后者是"那个目录由运行态才建出来"），混成一句会把人引去改本来对的根。
    """
    gaps = {}
    _faceFindings(ANCHOR, _manifestOf(ANCHOR), gaps)
    gaps = _dropSignedOffMissing(gaps)
    assert not gaps, (
        "这些受保护子集里的判据，静态根解到了仓外或指不到真实目录（它的「零命中」不来自代码）：\n  "
        + "\n  ".join("%s [%s]" % (rel, st) for rel, st in sorted(gaps.items()))
        + "\n`Path(__file__).resolve().parents[N]` 的 N 要按**本档所在深度**算："
        "`tests/unit/ci/x.py` 是 3，`tests/unit/x.py` 是 2。"
    )


def test_scanRootsAreNeverBoundInsideAFunction():
    """扫描根不得绑在**函数内的名字**上——新增即红，存量按表登记、消化要显式摘。

    为什么单独一格：这种档的根写得没错，错在绑的位置。`_constTable` 只收模块级绑定，于是
    `faceRoot = PROJECT_ROOT / "neurova"` 这一行让整档的落点变成"动态值"——既不要求面自证，
    也不算根写错，**安静地掉出本闸的面**。批 98 就是当场踩中的：那次为了消掉"报错里的根是把
    被检表达式再抄一遍"，把 8 档的根收进函数局部，复算发现 6 档的落点态只剩 `dynamic`，
    而 offender 仍是 0、摘表两格全绿。
    为什么这一格允许带存量表（与「根写错」那格不同）：LOCAL 是本闸的**盲区**而不是写错的根，
    建档那轮的存量与 `BASELINE` 同性质——所以纪律也同：新增即红、消化必须摘表，
    两边的表都由本文件的 `_faceFindings` 现取，不从别处抄数。
    反证在册：`test_localRootIsNamedNotIgnored` 必须交出**非空**的 localGaps，
    否则这里的"零新增"只说明探测器没在跑。
    """
    locals_ = {}
    _faceFindings(ANCHOR, _manifestOf(ANCHOR), localGaps=locals_)
    grew = sorted(set(locals_) - LOCAL_BASELINE)
    assert not grew, (
        "这些判据把扫描根绑在函数内的名字上（本闸按模块级常量解根，认不出＝那档整档不在面内）：\n  "
        + "\n  ".join("%s ← %s" % (rel, ", ".join(entries)) for rel, entries in
                      sorted((r, locals_[r]) for r in grew))
        + "\n修法：把根提到**模块级**常量，并让同档所有扫描落点与报错消息都向同一个名字要根；"
        "\n提到模块级之后这档就进入「仓内目录」那一支，面自证（`assert <扫描计数> > 数`）随即生效——"
        "两处要同批改完，别只提根不补读数。"
    )
    dropped = sorted(LOCAL_BASELINE - set(locals_))
    assert not dropped, (
        "以下档的扫描根已经提到模块级了——把 LOCAL_BASELINE 里那几行摘掉再提交，别让它悬着：\n  "
        + "\n  ".join(dropped)
    )


def test_manifestSurfaceWithoutProofIsNamed():
    """以清单为扫描面的判据，必须留一条**由这份清单得到**的面读数——新增即红、消化必须摘行。

    为什么要与「扫仓内根」那两支分开一格：那种档的根是目录，本闸能解出它有多大；这一族的根是
    **一份清单文件**（`protected_tests.txt`、台账 `.md`…）。清单被截短、改行或路径写错时，
    `for` 少跑几圈、offender 读数一起缩水，断言照绿——"干净"与"没读到"又是同形。
    为什么自证必须**由清单得到**、不能沿用文件级 `_hasFaceProof`：档里任何一条不相干的
    `assert len(x) > 数` 都能满足文件级规则，而 §6-331 点名的现场正是被
    `assert len(nodes) > 1000`（夹具节点数）兜掉的那一档——反检格
    `test_manifestDetectorJudgesEachShape` 里"无关数值断言"那一条就是钉这个的。
    反证在册：同一批控制格必须交出**非空**的 manifestGaps，否则这里的零断言只说明探测器没在跑。
    """
    mg = {}
    _faceFindings(ANCHOR, _manifestOf(ANCHOR), manifestGaps=mg)
    grew = sorted(set(mg) - MANIFEST_BASELINE)
    assert not grew, (
        "这些判据按清单逐条读文件动手，却没给这份清单留面读数"
        "（清单截短＝扫描静默少跑，读数照样绿）：\n  "
        + "\n  ".join("%s ← 落点行 %s" % (rel, mg[rel]) for rel in grew)
        + "\n修法（照本档 `test_surfaceReadingIsNotVacuous` 的形状，两条都要）：先比条目数量级 "
        "`assert len(清单) > 数`，再比「条目指得到真实文件」 `assert 命中数 == len(清单)`；"
        "\n只补第一条不算收口——路径写错那一形要让每一条都 `continue`，条目数照样好看。"
    )
    dropped = sorted(MANIFEST_BASELINE - set(mg))
    assert not dropped, (
        "以下档已经给清单面补上读数了——把 MANIFEST_BASELINE 里那几行摘掉再提交，别让它悬着：\n  "
        + "\n  ".join(dropped)
    )


_MANIFEST_HEADER = (
    "import io\nimport pathlib\n"
    "_List = pathlib.Path(__file__).resolve().parents[2] / 'items.txt'\n"
    "_Root = pathlib.Path(__file__).resolve().parents[2]\n\n\n"
    "def readList():\n"
    "    return io.open(_List, encoding='utf-8').read().splitlines()\n\n\n"
    "def readAny(name):\n"
    "    return io.open(_Root / name, encoding='utf-8').read().splitlines()\n\n\n")

#: 九条正检（真清单面）＋五条反检。正检逐条钉住一个认形：两条语句才动手、同一条语句里动手、
#: `joinpath`、当场读清单再迭代、面自证来自别处、条目先切字符串再拼路径、类里的取数方法、
#: 取数方法绑在赋值上、文件名当参数递进取数口。每条都对应批 103／批 104 实施时实际踩到或
#: 实际误伤的一形。跨模块取数口那两形另见 `_CROSS_MODULE_SHAPES`（批 104 新增认形，
#: 按 310/318 那条纪律各配一格正检＋一格反检）。
_MANIFEST_SHAPES = [
    ("正检·两条语句派生（`path = 根 / 条目` 之后才 `is_file()`）——第二版探测器漏的就是这一形",
     "def test_shape():\n"
     "    for line in readList():\n"
     "        path = _Root / line\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("正检·同一条语句里动用拼出的路径（`io.open(根 / 条目)`）",
     "def test_shape():\n"
     "    for rel in readList():\n"
     "        text = io.open(_Root / rel, encoding='utf-8').read()\n"
     "        assert text\n", True),
    ("正检·`joinpath(条目)` 派生再读——与 `/` 同一条语义，少认一种就漏一档",
     "def test_shape():\n"
     "    for rel in readList():\n"
     "        path = _Root.joinpath(rel)\n"
     "        print(path.read_text(encoding='utf-8'))\n", True),
    ("正检·当场读清单再迭代（不落变量）——批 103 现扫补的第三种 iterable 认形，本仓实测 9 处",
     "def test_shape():\n"
     "    for line in io.open(_List, encoding='utf-8').read().splitlines():\n"
     "        path = _Root / line\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("正检·面自证是**别处的**不相干数值断言 ⇒ 不许替清单面背书（§6-331 点名的现场）",
     "rows = [1, 2, 3]\n\n\n"
     "def test_shape():\n"
     "    assert len(rows) > 1\n"
     "    for line in readList():\n"
     "        path = _Root / line\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("正检·条目先过一道字符串处理再拼路径（台账那一族：`row[0].strip()` ⇒ `根 / 那` 再 stat）",
     "def test_shape():\n"
     "    for row in readList():\n"
     "        name = row.split('|')[0].strip()\n"
     "        path = _Root / name\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("反检·污点不许顺着普通函数调用蔓延（`f(x)` 不是拼路径）",
     "def digest(s):\n"
     "    return len(s)\n\n\n"
     "def test_shape():\n"
     "    for line in readList():\n"
     "        d = digest(line)\n"
     "        print(d)\n", False),
    ("正检·类里的取数方法（`for x in self._rows()`）——台账那一族的真形状，不认这支就整族掉出面",
     "class TestOne:\n"
     "    def _rows(self):\n"
     "        return readList()\n\n"
     "    def test_shape(self):\n"
     "        for line in self._rows():\n"
     "            path = _Root / line\n"
     "            if not path.is_file():\n"
     "                continue\n", True),
    ("正检·取数方法绑在**赋值**上而非迭代器（`rows = self._rows()` 之后再逐条动手）——"
     "这一形只有 `_readsAList` 的方法跳那一臂认得（批 107 起，记名那条臂已删——它不独占任何形）",
     "class TestOne:\n"
     "    def _rows(self):\n"
     "        return readList()\n\n"
     "    def test_shape(self):\n"
     "        rows = self._rows()\n"
     "        for line in rows:\n"
     "            path = _Root / line\n"
     "            if not path.is_file():\n"
     "                continue\n", True),
    ("正检·文件名当参数递进取数口（`readAny('items.txt')`）——helper 体内只有 `io.open(name)`",
     "def test_shape():\n"
     "    for line in readAny('items.txt'):\n"
     "        path = _Root / line\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("反检·条目先过一道普通函数再被当路径动手——本闸故意不认这一形，认它就等于让污点顺任意 helper 蔓延",
     "def digest(s):\n"
     "    return s\n\n\n"
     "def test_shape():\n"
     "    for line in readList():\n"
     "        d = digest(line)\n"
     "        print(d.is_file())\n", False),
    ("反检·迭代的是文件系统入口而非清单＝走「仓内目录」那一支，本格不许抢它的活",
     "def test_shape():\n"
     "    for p in _Root.rglob('*.py'):\n"
     "        print(p.read_text(encoding='utf-8'))\n", False),
    ("反检·条目只当键用（切字符串、比较），没被当路径动手 ⇒ 清单截短时坏得响，不算面",
     "def test_shape():\n"
     "    for line in readList():\n"
     "        key = line.split('#')[0].strip()\n"
     "        assert key\n", False),
    ("反检·带了**由清单得到**的读数 ⇒ 已自证，不再点名",
     "def test_shape():\n"
     "    files = readList()\n"
     "    assert len(files) > 50\n"
     "    for line in files:\n"
     "        path = _Root / line\n"
     "        if not path.is_file():\n"
     "            continue\n", False),
]


@pytest.mark.parametrize("label, body, expectNamed", _MANIFEST_SHAPES)
def test_manifestDetectorJudgesEachShape(tmp_path, label, body, expectNamed):
    """探测器要有牙：九条正检各自必须点名，五条反检各自必须闭嘴。

    这批控制格不是装饰——探测器一路补了五个洞才被正控放行：污点不跨语句
    （`path = 根 / 条目` 之后再动手）、只认名字不认当场读法、清单面能被无关数值断言兜掉、
    属性形取数方法不跳（`self._rows()`）、文件名当参数时认不出那是清单——批 107 复测又发现
    记名那条臂与「Name 集合 ∪ 方法跳」重叠、无独占形状，已删（形态集 321 的收口）。
    没有它们，"零 offender"永远分不清是干净还是没在跑（本闸自己前三版的失效形态）。
    变异侧的一条实测（239 那一族）：`self._rows()` 这一形被**两条臂**各自覆盖——
    变异侧的一条实测（239 那一族，批 107 收口）：`self._rows()` 这一形原先被**两条臂**各自覆盖，
    单摘任一条这十四格全绿；两条一起摘才红。于是给 `rows = self._rows()` 补了一格——那一形
    只有方法跳认得；再复测记名那条臂，发现它**没有任何独占形状**，遂整条删除（本闸 49 格全绿）。
    结论：一条臂是否该留，不看它「能不能红」，看它「只有它能红时是哪一格」。
    于是"这条臂有用"不能只靠"摘了它有一格红"来证。新加的 `rows = self._rows()` 那一格
    只有方法跳能红，是这两条臂各自独占性的分界。
    """
    (tmp_path / "tests" / "unit" / "ci").mkdir(parents=True)
    (tmp_path / "items.txt").write_text("a.py\nb.py\n", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "ci" / "sample.py").write_text(
        _MANIFEST_HEADER + body, encoding="utf-8")
    mg = {}
    _faceFindings(tmp_path, ["tests/unit/ci/sample.py"], manifestGaps=mg)
    assert bool(mg) is expectNamed, f"{label} ⇒ 判错：{mg}"


#: 跨模块取数口那一族（批 104 新增认形）：两格正检（直调别模块的取数口、经本地包装再转调单点）
#: ＋两格反检（被引模块不读清单、`importlib` 动态取数）。`listReader.py` 在**另一个文件**里读清单，
#: `decoyReader.py` 不读——同一条链路必须给出相反读数，否则"跟模块一跳"这句话没有证据。
_CROSS_MODULE_HEADER = (
    "import importlib\nimport io\nimport pathlib\n"
    "_Root = pathlib.Path(__file__).resolve().parents[2]\n\n\n"
    "from tests.unit.ci import listReader, decoyReader\n\n\n")

_CROSS_MODULE_SHAPES = [
    ("正检·清单读法在别的模块里（`from … import listReader` 后直调）——收口之后探测器必须还认得",
     "def test_shape():\n"
     "    for rel in listReader.readList():\n"
     "        path = _Root / rel\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("正检·经本地包装再转调单点（本仓 6 档就是这个形状）",
     "def protectedFiles():\n"
     "    return listReader.readList()\n\n\n"
     "def test_shape():\n"
     "    files = protectedFiles()\n"
     "    for rel in files:\n"
     "        path = _Root / rel\n"
     "        if not path.is_file():\n"
     "            continue\n", True),
    ("反检·同一条链路但被引模块**不读清单**＝不许凭 import 就判成清单面",
     "def test_shape():\n"
     "    for rel in decoyReader.names():\n"
     "        path = _Root / rel\n"
     "        if not path.is_file():\n"
     "            continue\n", False),
    ("反检·动态取数（importlib）不认＝登记在边界里的那一条，不许猜出来的面当已覆盖",
     "def test_shape():\n"
     "    mod = importlib.import_module('listReader')\n"
     "    for rel in mod.readList():\n"
     "        path = _Root / rel\n"
     "        if not path.is_file():\n"
     "            continue\n", False),
]


@pytest.mark.parametrize("label, body, expectNamed", _CROSS_MODULE_SHAPES)
def test_crossModuleReaderShapesAreJudgedByCodeForm(tmp_path, label, body, expectNamed):
    """跨模块一跳的两正检两反检：认形必须与取数口收口同批到位（形态集 313 的那一课）。

    这一格防的是**治理动作自己造出来的盲区**：把 6 档的读法收进单点之后，如果探测器只跟
    同文件 helper，这 6 档会一起掉出清单面——`manifestGaps` 归零看着像"存量清了"，
    实际是"没人被看着了"。没有这两枚正检，那一步是静默的。
    """
    (tmp_path / "tests" / "unit" / "ci").mkdir(parents=True)
    (tmp_path / "items.txt").write_text("a.py\nb.py\n", encoding="utf-8")
    ciDir = tmp_path / "tests" / "unit" / "ci"
    (ciDir / "__init__.py").write_text("", encoding="utf-8")
    (ciDir / "listReader.py").write_text(
        "import io\nimport pathlib\n\n"
        "_List = pathlib.Path(__file__).resolve().parents[3] / 'items.txt'\n\n\n"
        "def readList():\n"
        "    return io.open(_List, encoding='utf-8').read().splitlines()\n", encoding="utf-8")
    (ciDir / "decoyReader.py").write_text(
        "def names():\n    return ['a.py', 'b.py']\n", encoding="utf-8")
    (ciDir / "sample.py").write_text(_CROSS_MODULE_HEADER + body, encoding="utf-8")
    mg = {}
    _faceFindings(tmp_path, ["tests/unit/ci/sample.py"], manifestGaps=mg)
    assert bool(mg) is expectNamed, f"{label} ⇒ 判错：{mg}"


def test_ratchetRecordsImprovementLoudly():
    """存量被消化要**显式收表**：基线里有、现在不 offender 的档，必须从表里摘掉。"""
    now = set(_faceFindings(ANCHOR, _manifestOf(ANCHOR)))
    dropped = sorted(set(BASELINE) - now)
    assert not dropped, (
        "以下档已经自带面自证（或不再扫仓内路径）了——把 BASELINE 里那几行摘掉再提交，"
        "别让它悬着（悬着的后果：下一条真新增的 offender 会被旧表兜住而看不见）：\n  "
        + "\n  ".join(dropped)
    )


@pytest.mark.parametrize("label, source, expectNamed", [
    ("根绑在函数里的名字上（值是对的、位置不对）＝必须点名",
     "from tests import ast_scan\nimport pathlib\n\n\n"
     "def test_shape():\n"
     "    faceRoot = pathlib.Path(__file__).resolve().parents[3] / 'neurova'\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(faceRoot, '.py')]\n"
     "    assert hits == []\n", True),
    ("控制格：根是**运行时形参**＝本来就不承载面的声明，不许误报",
     "from tests import ast_scan\n\n\ndef test_shape(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n", False),
    ("控制格：函数内的名字指向**不存在的目录**＝那是「根写错」那一支，不冒充 LOCAL",
     "from tests import ast_scan\nimport pathlib\n\n\n"
     "def test_shape():\n"
     "    faceRoot = pathlib.Path(__file__).resolve().parents[3] / 'no_such_dir'\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(faceRoot, '.py')]\n"
     "    assert hits == []\n", False),
    ("控制格：根在模块级＝走正常那一支（DIR＋面自证），不该被 LOCAL 格误报",
     "from tests import ast_scan\nimport pathlib\n"
     "_Target = pathlib.Path(__file__).resolve().parents[3] / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n"
     "    assert hits == []\n", False),
])
def test_localRootIsNamedNotIgnored(tmp_path, label, source, expectNamed):
    """第五态 LOCAL 要有牙：正检（函数内静态根）与三枚控制格（形参／指不到／模块级）各配一格。

    没有这一格，`test_scanRootsAreNeverBoundInsideAFunction` 那句"零命中"就分不清是干净还是探测器
    根本没在跑——本闸自己的三版失效（`parents[N]` 按仓根数、深度上限 8、存量表兜掉根写错）都是这一形。
    """
    (tmp_path / "neurova").mkdir()
    (tmp_path / "tests" / "unit" / "ci").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "ci" / "sample.py").write_text(source, encoding="utf-8")
    locals_ = {}
    _faceFindings(tmp_path, ["tests/unit/ci/sample.py"], localGaps=locals_)
    assert bool(locals_) is expectNamed, f"{label} ⇒ 判错：{locals_}"


def test_surfaceReadingIsNotVacuous():
    """反空转：扫描面本身要先在场——"一条 offender 都没有"可能只是清单没读到。

    这条格专防本仓反复吃过的那一形：清单路径写错 ⇒ 空 manifest ⇒ offender 恒空 ⇒ 两条断言全绿。
    """
    manifest = _manifestOf(ANCHOR)
    assert len(manifest) > 500, f"受保护子集清单现读 {len(manifest)} 条，量级不对＝没读到"
    parsed = 0
    for rel in manifest:
        if (PROJECT_ROOT / rel).is_file():
            parsed += 1
    assert parsed == len(manifest), (
        f"清单里有 {len(manifest) - parsed} 条指不到真实文件——offender 读数会偏小且偏干净")


_PROOF_TAIL = (
    "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n"
    "    scanned = len(hits)\n"
    "    assert scanned > 500\n"
    "    assert hits == []\n"
)
_NO_PROOF_TAIL = "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n    assert hits == []\n"


@pytest.mark.parametrize("rel, source, label, expectOffender, expectGap", [
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'neurova'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "档在 ci/ 下（深度 3），parents[3] 就是仓根——这一档扫的是仓内路径，缺自证必须点名", True, ""),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3].parent\n_Target = _Repo\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "根上溯到仓外（`parents[3].parent`＝仓根的上一层），面根本不在代码上；带了自证也照样红", True, OUTSIDE),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo.parent\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "根解到仓外的**真实目录**（这里是仓根的上一层）：目录存在但不在仓内，带自证也照样红", True, OUTSIDE),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'neurova'\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "控制格：深度解对、自证在场＝不点名（防把规则做成『凡 parents 写法皆红』）", False, ""),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'no_such_dir'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "静态根指不到真实目录——与『目录被改名/删掉』同形，零命中是假的，必须点名", True, MISSING),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Anchor = _Repo / 'no_such_dir'\n\n\n"
     "def test_shape():\n"
     "    if _Anchor.is_dir() and not any(_Anchor.iterdir()):\n"
     "        _Anchor.rmdir()\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(_Repo / 'neurova', '.py')]\n"
     "    scanned = len(hits)\n"
     "    assert scanned > 500\n"
     "    assert hits == []\n",
     "清理落点：同一个接收者先被 is_dir() 守住再迭代——指不到目录是**预期**（没东西要清），"
     "不是扫描根写错（§6-405 批 N 的豁免；判据的扫描面走 nodeScan 那一支，照样要自证）",
     False, ""),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Other = _Repo / 'neurova'\n"
     "_Target = _Repo / 'no_such_dir'\n\n\n"
     "def test_shape():\n"
     "    hits = []\n"
     "    if _Other.is_dir():\n"
     "        hits = list(_Target.rglob('*.py'))\n"
     "    assert hits == []\n",
     "守的是**另一个名字** ⇒ 豁免不认：否则任何迭代都能被无关的 is_dir() 后门放行",
     True, MISSING),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'one.py'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "根指到仓内一个真实文件＝面很窄，但坏得**响**（入口当场抛 FileNotFoundError），本闸不管这一形", False, ""),
    ("tests/sample.py",
     "from tests import ast_scan\n\n\ndef test_shape(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n",
     "运行时才定的根不承载面的声明：既不点名也不免罪，维持原设计", False, ""),
    ("tests/unit/sample.py",
     "import pathlib\n_Repo = pathlib.Path(__file__).resolve().parents[2]\n"
     "_Data = _Repo / 'data' / 'sessions'\n\n\n"
     "def test_shape():\n"
     "    assert not list(_Data.rglob('*.json'))\n",
     "正检·接收者落在「仓根 ＋ 末级目录」，而这份 tmp 树里它既不在册也没被忽略 ⇒ 归 missing，点名。"
     "判据只认一条可机器验的事实（git 认不认得这条仓内路径），所以修法只能是把末级目录拼在调用处"
     "（`test_session_landing_guard.py` 把常量收成 `SESSIONS_PARENT` 就是为此）",
     True, MISSING),
    ("tests/unit/ci/sample.py",
     "import pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n"
     "_Data = _Repo / 'data'\n\n\n"
     "def test_shape():\n"
     "    assert not list(_Data.rglob('*.json'))\n",
     "反检·同一形状，但落点是被 `.gitignore` 整目录盖住的 `data/`：它不是「根写错」，"
     "也与「目录被改名删掉」不同读——归 `not_checked_out`，不点名。这一格与上面那格只差"
     "「git 认不认得」这一条，故它钉的正是判据本身而不是目录在不在",
     False, NOT_CHECKED_OUT),
])
def test_faceRulesPinDepthAndWrongRoots(tmp_path, rel, source, label, expectOffender, expectGap):
    """根的形状要按**被档自身深度**解，且「静态根解到仓外／指不到目录」必须点名。

    建档那轮现扫时，两档（`test_route_vocabulary_is_single_source.py`、`test_deploy_config_guard.py`）
    的根被解成了 `E:\\`——`Path(__file__).resolve().parents[N]` 这一形当时是**从仓根往上再数 N+1 层**，
    与档所在深度无关。第一版只把这当成"读数不准"，但它真正的坏法是：**把根少写一层的那档会安静地
    掉出本闸的面**（解出来的目录存在就不算动态值），于是"零命中"既可能来自干净、也可能来自
    根根本没指到代码——正是本档要防的那件事，被本档自己的取数路放过去了。
    """
    (tmp_path / "neurova").mkdir()
    (tmp_path / "one.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")

    if expectGap == NOT_CHECKED_OUT:
        # 「被整目录忽略」这一形只有 git 认得出来：钉一份本树自己的 `.gitignore` 并把它
        # 变成工作树。不这么做时两格都退回保守态，反检那格整条断言等于没跑。
        (tmp_path / ".gitignore").write_text("/data/\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=False,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)

    gaps = {}
    offenders = _faceFindings(tmp_path, [rel], gaps)
    assert bool(offenders) is expectOffender, f"{label} ⇒ 判错：{offenders}"
    # 只在该格要求验落点态时才走旁路：要求空串的那些格验的是"没有落点"
    # （运行时根／真实文件那一类），旁路会把它们读出别的值。
    # 反检格要求"不点名、且落点是 X"：`gaps` 只填 offender，故这一支直接问取数口；
    # 其余格沿用原契约（`gaps` 为空即"没有落点"），不改它们的验收口径。
    if expectGap in (NOT_CHECKED_OUT, DIR):
        actual = _firstSiteStatus(tmp_path / rel, tmp_path) or ""
    else:
        actual = gaps.get(rel, "")
    assert actual == expectGap, (
        f"{label} ⇒ 落点态判错：{actual!r} 里要的是 {expectGap!r}")


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
