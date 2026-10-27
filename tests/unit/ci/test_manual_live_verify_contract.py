# -*- coding: utf-8 -*-
"""手工 live-verify 脚本的常驻契约（Issue #90 收尾）。

## 为什么要有这条守卫

`tests/manual/*.py` 是 Issue #90 全部交付的**活体证据**：台账与提交说明里
「LIVE-VERIFY PASSED」那几行，正是这些脚本印出来的。它们的特性是**手工跑、
不进 CI** —— 于是它们的失效对 CI 完全不可见，只能靠人记得「改完再跑一遍」。

2026-09-26 环境实测（本 Issue 点名的那件事）把这一层翻了出来：36 份脚本里
**2 份当前根本跑不到 `LIVE-VERIFY PASSED`**，**18 份把生产数据写进了仓库根
`data/`**（而每份的 docstring 都写着「写盘全在系统临时目录（不碰 data 生产库）」）。
两者都不是"脚本写得糙"，是**同一根因的两种形态**：

- **形态一 · 读数键与生产事实源脱钩**。`get_context_health()` 的键域由编排器
  `_emptyContextHealth()` 单点定义（AGENTS.md 教义第 6 条），而
  `turn_session_identity_t03b_90.py` 读的是 `["session_identity"]` —— 那是个
  **已并入时被收口掉的旧键名**（T-03b 同单两份交付合并为单一事实源时统一成了
  `turn_identity`，见台账 §18）。生产侧改名了，脚本没跟：`KeyError`。
  这类"消费方读一个生产已经不提供的事实"在 CI 里没有落点，因为脚本不进 CI。

- **形态二 · 数据根推导被脚本抄了第二份**。生产侧的数据根自 2026-09-22 起
  由 `core/data_root.py` 单点推导、且**绝对锚定**（`NEUROVA_DATA_DIR` 为唯一
  注入口，未注入才落仓库 `data/`）。而 `context_ledger_migration_90.py` /
  `context_pool_startup_load_90.py` 仍按 `<临时目录>/data/context_ledger/` 拼路径，
  写盘却落在 `NEUROVA_DATA_DIR`（或仓库 `data/`）—— **脚本造的前像库与生产
  打开的库根本不是同一个文件**，于是断言读到 0 行、"同内容重复行未合并"。
  其余 16 份则是**没注入 `NEUROVA_DATA_DIR`**：它们靠 `os.chdir(临时目录)`
  来隔离，而绝对锚定之后 chdir 不再改变落点 —— 全部泄进仓库根 `data/`。

两种形态合成一条不变量：**脚本对生产事实的引用（读数键、落点）必须来自
生产侧的单点，不得在脚本里重写一份。**

## 判据（三条，各带反向控制）

1. **读数键必须存在于生产键域**：扫 `tests/` 与 `scripts/` 下所有
   `get_context_health()[...]` / `["<key>"]` 常量索引，键必须能在
   `_emptyContextHealth()` 的单点定义里找到。
2. **落点由生产单点推导**：`tests/manual/` 下不得出现「把 `data` 当路径段拼出来、
   并交给存储入口（开库/写）」的形态。判定按**代码形态 + 用途**两维取形（AST，
   不是文本正则）：文本正则既抓不到 pathlib 的 `X / "data"`，又会把
   `"".join(e.get("data"))` 这种**协议字段名**判成落点（2026-10-08 起的那格常驻红
   就是它）；而只读取仓内 `data/` 做**指纹对照**的锚点属第三种用途，不判红
   ——`isolatedDataRoot()` 已把 `NEUROVA_DATA_DIR` 注到临时根，生产单点表达不出
   「工作树里那个真 data 目录」，所以它不是第二份落点定义。
3. **构造生产持久对象的脚本必须注入数据根**：脚本里出现
   `Agent(` / `AgentConfig(` / `ContextOrchestrator(` / `ContextPool(` /
   `EvictionLedgerDB(` / `SessionManager(` 之一、即把持落点，则必须显式
   `NEUROVA_DATA_DIR`。

反向控制（缺一条本判据就是恒真断言，教义第 3 条明禁）：
往三条判据的输入里各塞一份**应被判红**的样本，判定必须翻转。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 跨文件 AST 判据的唯一解析入口（Issue #148）：本文件是**一次性**全仓扫描
#: （只问「仓库里有没有出现某个形状」，不存在第二次命中），故走一次性入口
#: `transientTree` —— 不留常驻语法树，判据成本不随代码总量与机器速度挂钩。
#: 自扫自解（`Path.glob` + `ast.parse`）会被
#: `tests/unit/test_ci_ast_scan_budget_guard.py` 判红：那是把代码总量编码成
#: 时间上界，单跑绿、全套撞 `pytest-timeout` 的 30s 默认墙钟。
from tests import ast_scan
from tests.ast_scan import parseSource
MANUAL_ROOT = PROJECT_ROOT / "tests" / "manual"
ORCHESTRATOR = PROJECT_ROOT / "neurova" / "context" / "orchestrator.py"

#: 把「落点」交给生产装配面的构造调用（出现其一即须注入数据根）。
_DATA_ROOT_CONSUMERS = (
    "Agent",
    "AgentConfig",
    "ContextOrchestrator",
    "ContextPool",
    "EvictionLedgerDB",
    "SessionManager",
)

#: 唯一注入口（`core/data_root.py` 的 `DATA_ROOT_ENV`）。
_DATA_ROOT_ENV = "NEUROVA_DATA_DIR"

#: 隔离动作的单点模块（`tests/manual/_liveVerifyIsolation.py`）。
#: 脚本要么直呼注入口，要么走这个单点 —— 两选一，**不许自己拼一份**。
_ISOLATION_HELPER = "_liveVerifyIsolation"


def _injectsDataRoot(text: str) -> bool:
    """脚本是否把数据根交给单点（注入口字面量 或 隔离单点模块）。"""
    return _DATA_ROOT_ENV in text or _ISOLATION_HELPER in text


#: 存储入口：路径被交给这些调用，才是「拿自己拼出来的落点开库/写」。
#: 只读取（`exists`/`rglob`/`stat`/`relative_to`）**不在内** —— 活体脚本要读仓内真
#: `data/` 做**指纹对照**以自证没写脏生产库；而 `isolatedDataRoot()` 已把
#: `NEUROVA_DATA_DIR` 注到临时根，生产单点在脚本里**表达不出**「工作树里那个真
#: data 目录」这个语义，所以那份锚点不是「第二份落点定义」。
_STORAGE_SINKS = frozenset({
    "connect", "require_data_path", "open", "write_text", "write_bytes",
    "mkdir", "makedirs", "touch", "remove", "unlink", "rename", "replace",
    "copy", "copyfile", "copytree", "move",
})

#: 路径型 join 的接收者。假红的来源正是这里要区分开的东西：`"".join(...)` 是
#: **字符串** join，它拼的是流式事件的协议字段 `data`，与磁盘落点无关。
_PATH_JOIN_RECEIVERS = frozenset({"os", "posixpath", "ntpath", "pathlib", "Path"})

#: 被抄的第二份落点里那段目录名（生产侧 `core/data_root.py` 是它的唯一出处）。
_DATA_SEGMENT = "data"


def _joinReceiverRoot(node: ast.AST) -> str | None:
    """属性链最左端的名字；字面量接收者（`""`、`f""`）返回 None —— 那不是路径拼接。"""
    cur = node
    while isinstance(cur, ast.Attribute):
        cur = cur.value
    if isinstance(cur, ast.Name):
        return cur.id
    if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Name):
        return cur.func.id
    return None


def _isDataSegment(node: ast.AST) -> bool:
    """一个字面量是不是恰好那个目录段（`"data"`）。"""
    return isinstance(node, ast.Constant) and node.value == _DATA_SEGMENT


def _buildsDataLayout(node: ast.AST) -> bool:
    """子树里是否出现「把 `data` 当路径段拼进去」的形态。

    认三种：路径型 `join(..., "data", ...)` / `joinpath("data")`、pathlib 的
    `X / "data"`、以及形如 `"data/x.db"`、`"...<sep>data<sep>..."` 的相对路径串。
    故意**不**按文本扫 `join(` —— 那会把字符串 join 与协议字段名一起卷进来。
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            args = list(sub.args) + [kw.value for kw in sub.keywords if kw.value is not None]
            if sub.func.attr == "join" and (
                    _joinReceiverRoot(sub.func.value) in _PATH_JOIN_RECEIVERS):
                if any(_isDataSegment(a) for a in args):
                    return True
            elif sub.func.attr == "joinpath" and any(_isDataSegment(a) for a in args):
                return True
        elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
            if _isDataSegment(sub.left) or _isDataSegment(sub.right):
                return True
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            norm = sub.value.replace("\\", "/")
            if (norm.startswith(f"{_DATA_SEGMENT}/")
                    or f"/{_DATA_SEGMENT}/" in norm
                    or norm.endswith(f"/{_DATA_SEGMENT}")):
                return True
    return False


def _replicatesDataRootLayout(tree: ast.AST) -> bool:
    """脚本是否**另拼了一份 `data/` 落点并把它交给了存储入口**。

    谓词只许这一处（本文件原先在整目录扫描与反向控制里各写了一遍同一正则，
    两份会漂 —— 漂的方向永远是「判据以为自己在防，实际防的是另一件事」）。

    用途这一维不可省：只看「有没有拼 `data`」会把 10 份活体脚本的只读指纹锚点
    一起误伤；只看 `join(` 文本又既抓不到 pathlib 形态、又把协议字段名判成落点。
    """
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and _buildsDataLayout(node.value) for t in node.targets):
            assigned.update(t.id for t in node.targets if isinstance(t, ast.Name))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        isSink = (isinstance(func, ast.Attribute) and func.attr in _STORAGE_SINKS) or (
            isinstance(func, ast.Name) and func.id in _STORAGE_SINKS)
        if not isSink:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in assigned:
                return True
            if _buildsDataLayout(sub):
                return True
    return False


def _treeOfSample(tmp_path: Path, source: str) -> ast.AST:
    """样本落成临时文件后走**共享的一次性解析入口**。

    本文件不许出现私有 `ast.parse`：枚举 + 私有解析是
    `tests/unit/test_ci_ast_scan_budget_guard.py` 判红的形态。
    """
    sample = tmp_path / "layoutSample.py"
    sample.write_text(source, encoding="utf-8")
    return ast_scan.transientTree(sample)


#: 已知存量：判据从「文本正则」换成「AST + 用途」后**第一次显形**的真断点
#: （2026-10-09 登记，台账 §6-87）。`seed_memory_pair_relocation_290.py:50` 手拼
#: 旧锚点前像 `legacy_root / "neurova" / "memory" / "data"` 再 `mkdir`，而生产侧
#: 有这一件事的单点 `core/data_root.py:190 legacyLanding(*legacyParts)`
#: （该脚本 `:54` 已把 `data_root.repoRoot` 打到假根，走的正是单点解析那条路）。
#: 它不是本轮的误伤对象：与只读指纹锚点不同，这里是**拼出来去 mkdir 落点**，
#: 且同一件事在仓内已有唯一出处。
#: 本表**双向咬合**（见 `testKnownLayoutOffendersAreStillReallyMatched`）：
#: 新增命中即红；把它修好了不摘表也红。
_KNOWN_LAYOUT_OFFENDERS = ("seed_memory_pair_relocation_290.py",)


def _layoutOffenders() -> list[Path]:
    return [p for p in _manualScripts()
            if _replicatesDataRootLayout(ast_scan.transientTree(p))]


def _healthKeyDomain() -> set[str]:
    """生产键域：`_emptyContextHealth()` 返回值字面量的顶层键。

    按源码解析而不是实例化编排器取键 —— 判据要的是"生产声明了哪些键"，
    实例化会把判据变成 runtime 行为测试，且 `__new__` 直构路径本身就有降级分支。
    """
    source = ORCHESTRATOR.read_text(encoding="utf-8")
    marker = 'return {\n            "ledger"'
    start = source.find(marker)
    assert start != -1, "未找到 `_emptyContextHealth()` 的返回值字面量（判据需同步）"
    block = source[start:]
    end = block.find("\n        }\n")
    assert end != -1, "未找到 `_emptyContextHealth()` 字面量结尾（判据需同步）"
    return set(re.findall(r'^\s{12}"([a-z_]+)":', block[:end], re.M))


def _constantKeyIndexes() -> list[tuple[str, int, str]]:
    """全仓（tests/ + scripts/）对 `get_context_health()[...]` 的常量键索引。"""
    pattern = re.compile(r'get_context_health\(\)\[\s*[\'"]([a-z_]+)[\'"]\s*\]')
    found: list[tuple[str, int, str]] = []
    for root in (PROJECT_ROOT / "tests", PROJECT_ROOT / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                found.append((str(path.relative_to(PROJECT_ROOT)), line, match.group(1)))
    return found


def _manualScripts() -> list[Path]:
    """本格扫描面＝**已跟踪**的 `tests/manual/*.py`（裁定乙）。

    为什么不按目录 glob：本格拿现读与 `_KNOWN_LAYOUT_OFFENDERS` 比**两侧相等**，属"存量比对"型判据。
    按工作树 glob 时，并发会话正在半写的在途档会被算成"本仓多了一条断点"——而 A/B 的基线侧是
    HEAD 的 worktree，看不见那份文件，于是别人写的东西被记成本批引入的回归（§6-225 的 A/B 第一轮
    与本批复算都撞到过）。代价说清楚：**新档要先 `git add` 才进本判据**（CI 只跑跟踪文件，
    所以漏不掉，只是当场不咬）。

    与"不许新增"型守卫（棘轮、形状扫描）刻意相反——那一类要的就是当场咬住未提交的档，
    用工作树面；两者的区别写在 `tests/ast_scan.py` 的清单入口注释里。
    """
    tracked = {rel.rsplit("/", 1)[-1] for rel in ast_scan.trackedPaths("tests/manual")
               if rel.endswith(".py")}
    return sorted(MANUAL_ROOT / name for name in tracked
                  if not name.startswith("_") and (MANUAL_ROOT / name).is_file())


def _callsProductionBuilder(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _DATA_ROOT_CONSUMERS:
                return True
    return False


# ───────────────────────── 判据 1：读数键 ─────────────────────────


def testHealthReadoutKeysExistInProductionDomain():
    domain = _healthKeyDomain()
    assert "turn_identity" in domain and "fold_index" in domain, (
        f"生产键域解析结果异常：{sorted(domain)}"
    )
    offenders = [
        f"{path}:{line} 读 `{key}`" for path, line, key in _constantKeyIndexes()
        if key not in domain
    ]
    assert not offenders, (
        "以下落点读的读数键不在 `_emptyContextHealth()` 的单点键域里 —— "
        "生产侧改名后消费方没跟，脚本会 KeyError、CI 看不见：\n  "
        + "\n  ".join(offenders)
    )


def testStaleReadoutKeyIsRejected():
    """反向控制：旧键名（`session_identity`）必须被判红。"""
    domain = _healthKeyDomain()
    assert "session_identity" not in domain, (
        "旧键名又回到了键域 —— 与判据 1 的收口结论冲突，请同步本用例"
    )


# ───────────────────────── 判据 2：落点推导 ─────────────────────────


def testManualScriptsDoNotReplicateDataRootLayout():
    unexpected = [str(p.relative_to(PROJECT_ROOT)) for p in _layoutOffenders()
                  if p.name not in _KNOWN_LAYOUT_OFFENDERS]
    assert not unexpected, (
        "以下脚本自己拼了 `data/` 落点并把它交给存储入口（开库/写）—— 落点推导的唯一"
        "单点是 `core/data_root.py`，脚本抄第二份就会与生产打开的库不是同一个文件：\n  "
        + "\n  ".join(unexpected)
        + "\n（已知存量另见 `_KNOWN_LAYOUT_OFFENDERS`，双向咬合，不静默放行）"
    )


def testScanFaceIgnoresForeignUntrackedScratchFile():
    """本格是**存量比对**型判据 ⇒ 扫描面只认已跟踪清单，外来未跟踪档不得算进来。

    为什么不是"顺手把 glob 换成 tracked 列表"这么小：本仓实测过两次同形误报——
    并发会话正在 `tests/manual/` 里半写自己的活体档时，那一档会进**本树**读数而进不了
    **基线树**（A/B 的基线是 HEAD 的 worktree），于是别人写的内容被记成"我引入了新断点"
    （§6-225 的 A/B 第一轮、以及本批现量都撞到这一形）。

    反面一并钉：**谓词本身不许跟着松**。同一份内容形状若已被跟踪，必须照样点名——
    所以本格同时断"`_replicatesDataRootLayout` 认得这份探针内容"，把"收面"与"改谓词"分开。
    """
    probe = MANUAL_ROOT / "b54_foreign_untracked_scratch_tmp.py"
    assert not probe.exists(), "上一次探针残留会污染扫描面"
    probe.write_text(
        "import sqlite3\n"
        "from pathlib import Path\n"
        "\n"
        "root = Path('here') / 'data' / 'scratch.db'\n"
        "conn = sqlite3.connect(str(root))\n",
        encoding="utf-8")
    try:
        offenders = _layoutOffenders()
        assert probe not in offenders, (
            f"未跟踪的外来档被算进本仓存量红里了（扫描面没收口）：{offenders}")
        assert _replicatesDataRootLayout(ast_scan.transientTree(probe)), (
            "谓词对同一份内容形状不再翻红——那是把『扫描面收口』做成了『判据变松』")
    finally:
        probe.unlink(missing_ok=True)
    assert not probe.exists(), "探针残留会让下一条用例把临时文件算进真实存量"


def testKnownLayoutOffendersAreStillReallyMatched():
    """例外表双向咬合：新增命中由主判据拦，**修好了不摘表也拦**。

    少了这一格，存量表就成了永久豁免 —— 那正是「豁免通道一开就有人顺同一口径进来」
    的形态。同时它反证主判据不是空转：表里那条今天必须仍被真抓到。
    """
    for name in _KNOWN_LAYOUT_OFFENDERS:
        path = MANUAL_ROOT / name
        assert path.is_file(), f"存量表指向的文件已不在：{name} —— 改判或摘表，别留悬空条目"
        assert _replicatesDataRootLayout(ast_scan.transientTree(path)), (
            f"{name} 已不再命中判据（说明它被修好了）——"
            "把名字从 `_KNOWN_LAYOUT_OFFENDERS` 摘掉再提交，别让表替不存在的事背书"
        )


def testDataRootLiteralIsDetected(tmp_path):
    """反向控制：`join` 形态拼出的库路径进了开库调用，判定必须翻转。

    样本带 sink 是必需的：本判据按**用途**取形（见 `_replicatesDataRootLayout`），
    不带存储入口的拼法（只读对照）属另一件事，有专门的负向控制钉住。
    """
    sample = ('dbPath = os.path.join(cwd, "data", "context_ledger", "x.db")\n'
              "conn = sqlite3.connect(dbPath)\n")
    assert _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), \
        "反向控制失效：判据抓不到该形态"


def testDataRootOpenedViaPathlibIsDetected(tmp_path):
    """反向控制：pathlib `/ "data"` 拼出的库路径**进了开库调用**，必须判红。

    这条抓的是本判据的**覆盖缺口**：谓词只认 `join(` 形态，于是 docstring 里
    「形态二 · 数据根推导被脚本抄了第二份」换个写法就静默放过——判据以为在防，
    实际防的是另一件事。
    """
    sample = (
        'dbPath = PROJECT_ROOT / "data" / "agent_runs.db"\n'
        "conn = sqlite3.connect(dbPath)\n"
    )
    assert _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), (
        "pathlib 形态的落点拼接没被判红（覆盖缺口）"
    )


def testProtocolFieldJoinIsNotMistakenForDataRoot(tmp_path):
    """反向控制（负向）：`"".join(...)` 取的是协议字段 `data`，不是落点，不得判红。

    本仓 2026-10-08 起这一格常驻红就是它：`anthropicLoop_realProvider.py` 拼流式
    事件文本 `e.get("data", "")` 被当成「脚本自拼 data/ 落点」。守卫钉的该是代码形态，
    不是字面量本身——`data` 在别的域里是同名词值。
    """
    sample = (
        'reply = "".join(\n'
        '    e.get("data", "") for e in events if e.get("type") == "content"\n'
        ")\n"
    )
    assert not _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), (
        "字符串 join 的协议字段名被当成 `data/` 落点（假红）"
    )


def testReadOnlyFingerprintAnchorIsNotMistakenForDataRoot(tmp_path):
    """反向控制（负向）：只读取仓内 `data/` 做**指纹对照**（证本轮没写脏生产库）不是违规。

    要说清为什么它不算「第二份落点定义」：`dataPath()` 那类单点走的是
    `NEUROVA_DATA_DIR`，而活体脚本一进来就把它注到临时根（`isolatedDataRoot()`），
    于是单点在脚本里**表达不出**「仓库工作树里那个真 data 目录」这个语义。
    判据要拦的是「拼出来去开库/写」，不是「拼出来读一下看有没有被写」。
    """
    sample = (
        'REPO_DATA_DIR = PROJECT_ROOT / "data"\n'
        'for p in REPO_DATA_DIR.rglob("*"):\n'
        "    p.stat()\n"
    )
    assert not _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), (
        "只读指纹对照锚点被判成落点拼接（会把 10 份活体脚本一并误伤）"
    )


def testInlineLayoutInSinkArgumentIsDetected(tmp_path):
    """反向控制：不赋变量、直接把落点拼进存储入口，也必须判红（数据流不止走变量名）。"""
    sample = ("import sqlite3\n"
              'conn = sqlite3.connect(os.path.join(root, "data", "agent_runs.db"))\n')
    assert _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), (
        "内联形态的落点拼接没被判红"
    )


def testStringLiteralRelativePathIsDetected(tmp_path):
    """反向控制：直接写相对路径串 `"data/x.db"` 进 `open`，也必须判红。"""
    sample = 'handle = open("data/context_ledger/x.db", "w")\n'
    assert _replicatesDataRootLayout(_treeOfSample(tmp_path, sample)), (
        '相对路径串形态没被判红'
    )


# ───────────────────────── 判据 3：注入数据根 ─────────────────────────


def testManualScriptsConstructingProductionObjectsInjectDataRoot():
    offenders: list[str] = []
    for path in _manualScripts():
        text = path.read_text(encoding="utf-8")
        if _injectsDataRoot(text):
            continue
        if _callsProductionBuilder(ast_scan.transientTree(path)):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, (
        "以下脚本构造了生产持久对象却没注入数据根 —— 未注入时 `get_data_root()` "
        "落仓库 `data/`，而绝对锚定之后 `os.chdir()` 已经不能隔离落点：\n  "
        + "\n  ".join(offenders)
    )


def testMissingInjectionIsDetected():
    """反向控制：一份「构造生产对象 + 不注入」的样本必须被判红。"""
    sample = "from neurova.agent_core import Agent\nagent = Agent(cfg)\n"
    tree = parseSource(sample)
    assert _callsProductionBuilder(tree), "反向控制失效：判据认不出生产构造调用"
    assert not _injectsDataRoot(sample), "反向控制失效：样本意外含隔离单点"
    assert _injectsDataRoot(
        'from tests.manual._liveVerifyIsolation import isolatedDataRoot\nisolatedDataRoot()\n'
    ), "反向控制失效：判据认不出隔离单点（只认字面量就等于把单点路径封死）"
