# -*- coding: utf-8 -*-
"""只降不升棘轮：生产侧不得新增「同一逻辑被复制第二份」的跨文件重复实现（台账 D21）。

**来历**：批 84 取证 `neurova/collaborate/` 时发现，`agent/templates/collaboration_template.py`
与 `collaborate/template.py`＋`collaborate/models.py` 是同一套实现的两份拷贝——350 行里 346 行相同，
且两份都被 import（门面把死的那半也挂在每次进程启动路径上）。真正的问题不是那三档文件，
而是：仓内**没有任何判据**拦"复制一份再改两行"。见
`audit-reports/collaborate-island-archive-2026-10-18.md` 的 D21，台账 §6-312。

**与既有守卫的分工**（不是第二套平行体系）：
- `tests/unit/ci/test_moduleTopLevelShadowing.py` 管**同一文件内**两个同名顶层 def/class——后定义的
  静默遮蔽前定义的，形态是"以为改过了"。
- 本档管**跨文件**的同名同体实现——两份都在、各被不同调用方用着，形态是"双源分叉"。
  两者判定单位都是符号，取数都走 `tests/ast_scan` 的共享解析预算，面不重叠。

**口径（每个数都有来历，要改数就连同这段一起改）**：
- 扫描面＝模块顶层的 `def`/`async def`/`class` ＋ 顶层 `class` 的直接方法。再深的嵌套
  （函数体内的闭包、内嵌类的内嵌方法）**不在面内**——这是**划定**而非疏漏：D21 要拦的是
  "两份承担同一职责的实现"，它们挂在模块或类这一层；局部闭包的复制是各自的语言结构。
- 体长下限＝归一后 800 字符。实测全仓 ratio≥0.99 的 684 对里 636 对在此线以下——那些是
  getter／`__init__` 样板这类"结构相同而职责本就相同"的形状，放进命中面只会训练人去忽略门禁。
- 相似度下限＝0.90（`difflib.SequenceMatcher.ratio()`，比对**去 docstring、天然不含装饰器、压平空白**
  后的源码段）。0.85 那档开始混进"按平台各写一份"的并行适配器
  （`neurflow/external_clients/{taobao,jd,pdd,douyin}.py` 的 `call`/`fetch_orders` 实测落在 0.83–0.89），
  那是合理分化，不该由判据替人拍板。
- 配对预筛①＝按 `(kind, name)` 分桶：拷贝实现的人通常连名字一起抄，只在桶内两两比。
- 配对预筛②＝长度带 `len(b) - len(a) <= 0.35 * len(a)`。它是 ratio≥0.90 的**必要条件**不是猜测：
  匹配块数 M ≤ min(len) = L，故 ratio = 2M/(2L+d) ≤ 2L/(2L+d)，要 ratio≥0.90 必须 d ≤ (2/9)L ≈ 0.222L；
  0.35L 留了余量。
- 配对预筛③＝昂贵的切片之前先算一个**长度上界**（该符号行范围内的原始字符数）。归一只删空白与
  docstring，故上界 ≥ 归一后长度恒成立，是充分条件。**不得**换成"行数 ≥ N"：一行 900 字符的体
  会在行数上漏掉——这一条由 `test_spanBoundNeverSkipsALongBody` 咬住。

**为什么用工作树面而不是已跟踪面**：本判据的主职是"不许新增"，要当场咬住还没提交的那一份。
存量比对型判据才该走已跟踪面（并发会话半写的在途档不该算成存量红）；这里两类都要，取严的那一面。
"""

from __future__ import annotations

import ast
import collections
import difflib
import functools
import pathlib
import re
from typing import NamedTuple

from tests import ast_scan

REPO_ROOT = ast_scan.REPO_ROOT
PRODUCTION_ROOT = ast_scan.PRODUCTION_ROOT

MIN_BODY_CHARS = 800
RATIO_FLOOR = 0.90
LENGTH_SLACK = 0.35

_WS = re.compile(r"\s+")


class Symbol(NamedTuple):
    name: str
    kind: str
    path: pathlib.Path
    lineno: int
    body: str


class Duplicate(NamedTuple):
    ratio: float
    kind: str
    name: str
    fileA: str
    lineA: int
    fileB: str
    lineB: int
    lenA: int
    lenB: int

    @property
    def key(self) -> str:
        a, b = sorted((self.fileA, self.fileB))
        return f"{self.kind}|{self.name}|{a}|{b}"


class Scan(NamedTuple):
    pairs: tuple[Duplicate, ...]
    symbols: int
    files: int
    missingEnd: int


#: 冻结基线＝本轮按上述口径实测的 7 对（值恒为 1，条目数即对数）。只准降不准升，新 key 即红。
#: 取数分两族，逐对读过去确认过形状：
#: - 6 对＝`channels/{telegram,wechat}_ai_generation.py` 的六个 `generate_*`（0.90–0.97，按渠道复制的
#:   AI 生成逻辑，两份都在活路上）；
#: - 1 对＝`llm/providers/{openai,openrouter}_provider.py` 的 `_detect_capabilities`（0.9035）。
#: 原第 3 族那 5 对（`agent/templates/collaboration_template.py` ↔ `collaborate/{models,template}.py`）
#: 已随 §6-312 裁乙的退役批（批 109）消失——降基线是**本档自己红过之后**才收的（形态集 300：
#: 摘行必须配"单独退回 offender"的形状红＋行为红双格），不是顺手调小。
#: 本字典由 `scanProduction()` 现场导出后原样贴入，不手抄（抄错的方向永远是放行）。
BASELINE: dict[str, int] = {
    "method|_detect_capabilities|neurova/llm/providers/openai_provider.py|neurova/llm/providers/openrouter_provider.py": 1,
    "method|generate_image_to_image|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
    "method|generate_image_to_video|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
    "method|generate_keyframe_to_video|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
    "method|generate_text_to_image|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
    "method|generate_text_to_video|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
    "method|generate_video_to_video|neurova/channels/telegram_ai_generation.py|neurova/channels/wechat_ai_generation.py": 1,
}


def _spanUpperBound(lines: list[str], node) -> int:
    """该符号行范围内的原始字符数＝归一后体长的上界，用于昂贵切片之前的预筛。"""
    start = node.lineno - 1
    end = node.end_lineno
    if end is None or end > len(lines) or end <= start:
        return 0
    return sum(map(len, lines[start:end]))


def _normalizedBody(lines: list[str], node) -> str:
    """取源码段（从 `def`/`class` 那行起，天然不含装饰器），剥 docstring，压平空白。"""
    start = node.lineno - 1
    end = node.end_lineno
    if end is None or end > len(lines) or end <= start:
        return ""
    body = list(node.body)
    first = body[0] if body else None
    isDoc = (isinstance(first, ast.Expr)
             and isinstance(getattr(first, "value", None), ast.Constant)
             and isinstance(first.value.value, str))
    if isDoc:
        seg = "".join(lines[start: first.lineno - 1]) + "".join(lines[first.end_lineno: end])
    else:
        seg = "".join(lines[start:end])
    return _WS.sub(" ", seg).strip()


def _rel(path: pathlib.Path) -> str:
    """仓内路径给相对名；对照用的仓外 tmp 树给绝对名（两形的比对键都稳定）。"""
    try:
        text = str(path.relative_to(REPO_ROOT))
    except ValueError:
        text = str(path)
    return text.replace("\\", "/")


def symbolsUnder(root: pathlib.Path) -> tuple[tuple[Symbol, ...], int]:
    """列出扫描面上的符号（口径见模块 docstring），并报告因缺 `end_lineno` 被跳过的个数。

    枚举与解析都走 `tests/ast_scan` 的共享预算，不私有 `rglob + ast.parse`
    （`tests/unit/test_ci_ast_scan_budget_guard.py` 判红的正是那处）。
    """
    found: list[Symbol] = []
    missingEnd = 0
    for path, tree in ast_scan.parsedModules(root, ".py"):
        lines = ast_scan.sourceCode(path).splitlines(keepends=True)
        targets: list[tuple[str, ast.AST]] = []
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                targets.append(("func", stmt))
            elif isinstance(stmt, ast.ClassDef):
                targets.append(("class", stmt))
                for inner in stmt.body:
                    if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        targets.append(("method", inner))
        for kind, node in targets:
            if node.end_lineno is None:
                missingEnd += 1
                continue
            if _spanUpperBound(lines, node) < MIN_BODY_CHARS:
                continue
            text = _normalizedBody(lines, node)
            if len(text) >= MIN_BODY_CHARS:
                found.append(Symbol(node.name, kind, path, node.lineno, text))
    return tuple(found), missingEnd


def similarPairs(symbols: tuple[Symbol, ...]) -> list[Duplicate]:
    """同名同类的符号跨文件两两比相似度，返回达到下限的对。"""
    buckets: dict[tuple[str, str], list[Symbol]] = collections.defaultdict(list)
    for sym in symbols:
        buckets[(sym.kind, sym.name)].append(sym)

    hits: list[Duplicate] = []
    for (kind, name), members in buckets.items():
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda m: len(m.body))
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                a, b = ordered[i], ordered[j]
                if a.path == b.path:
                    continue
                if len(b.body) - len(a.body) > LENGTH_SLACK * len(a.body):
                    break
                matcher = difflib.SequenceMatcher(None, a.body, b.body, autojunk=False)
                if matcher.real_quick_ratio() < RATIO_FLOOR or matcher.quick_ratio() < RATIO_FLOOR:
                    continue
                ratio = matcher.ratio()
                if ratio < RATIO_FLOOR:
                    continue
                relA, relB = _rel(a.path), _rel(b.path)
                if relA <= relB:
                    f1, n1, f2, n2 = relA, a, relB, b
                else:
                    f1, n1, f2, n2 = relB, b, relA, a
                hits.append(Duplicate(round(ratio, 4), kind, name, f1, n1.lineno, f2, n2.lineno,
                                      len(a.body), len(b.body)))
    return hits


def scanRoot(root: pathlib.Path) -> Scan:
    symbols, missingEnd = symbolsUnder(root)
    return Scan(tuple(similarPairs(symbols)), len(symbols),
                len(ast_scan.filesUnder(root, ".py")), missingEnd)


@functools.lru_cache(maxsize=1)
def scanProduction() -> Scan:
    """整进程只扫一次；各格共用同一份读数，别让判据成本按格乘上全仓解析量。"""
    return scanRoot(PRODUCTION_ROOT)


def test_scanFaceIsNonEmpty():
    """覆盖性前置：扫描面塌了的话，"零新增"是假的绿。

    本仓同族判据（`test_manualScriptsEnvMutationRatchet.py`）踩过一次"仓库根写成
    `parents[2]` ⇒ 扫描面为空集"——没有这条断言，那把棘轮会永远绿着。
    """
    assert PRODUCTION_ROOT.is_dir(), f"扫描根不存在：{PRODUCTION_ROOT}"
    result = scanProduction()
    assert result.files > 500, (
        f"生产根 `.py` 文件数异常低（{result.files}），扫描根或目录结构被动过")
    assert result.symbols > 1000, (
        f"达到体长下限的符号数异常低（{result.symbols}），取数口径被动过")
    assert result.missingEnd == 0, (
        f"{result.missingEnd} 个符号没有 `end_lineno`，被静默跳过——取数面缩水，"
        "「零新增」不再是结论")


def test_knownRealPairIsDetected():
    """正控：命中面里必须仍有**真**双源，且拿的是读数不是"跑完没报错"。

    原起因那对（`agent/templates/collaboration_template.py` ↔ `collaborate/template.py`）已随
    §6-312 裁乙的退役批消失，所以正检改钉仍在活路上的渠道 `generate_*` 双源；同时**反向**钉住
    "退役那对确实不再被检出"——两个方向各钉一次，才分得开"真删干净"与"探测器坏了"（283/310 那一族）。
    """
    keys = {d.key for d in scanProduction().pairs}
    needle = ("method|generate_text_to_image|neurova/channels/telegram_ai_generation.py"
              "|neurova/channels/wechat_ai_generation.py")
    assert needle in keys, (
        "两份都在活路上的渠道生成逻辑没被检出——是探测器失效，不是仓库变干净了。\n"
        f"现存 {len(keys)} 对：\n" + "\n".join(sorted(keys)))
    leftover = [k for k in keys if "neurova/collaborate/template.py" in k or "neurova/collaborate/models.py" in k]
    assert not leftover, (
        "那座岛已按 §6-312 退役，命中面里却还留着它的双源对——说明实现没删净：\n  "
        + "\n  ".join(sorted(leftover)))


def test_noNewDuplicateImplementation():
    """棘轮本体：基线之外的新重复对一律拦。"""
    now = {d.key: d for d in scanProduction().pairs}
    fresh = [k for k in now if k not in BASELINE]
    assert not fresh, (
        "生产侧出现了新的「同一逻辑被复制第二份」——两处同功能实现不许并存各调各的"
        "（`AGENTS.md` 修复教义 第 6 条／第 7 条）。修法不是加同步脚本，是先比后合："
        "比正确性／覆盖面／可测性／调用方数量 → 把不可替代的部分并入选定那份 → "
        "全部消费方改指它 → 退役另一份连同其测试。\n"
        + "\n".join(f"  {k}（ratio={now[k].ratio}，{now[k].lenA}/{now[k].lenB} 字符）"
                    for k in sorted(fresh)))


def test_ratchetRecordsImprovementLoudly():
    """降了要**红着**提醒收基线——只降不升要真降，就得让降可见。"""
    now = {d.key for d in scanProduction().pairs}
    dropped = [k for k in BASELINE if k not in now]
    assert not dropped, (
        "以下重复对已不存在——把基线收下去再提交，别让它悬着："
        "悬着的基线会让下一次真新增被当成早就有。\n"
        + "\n".join(f"  {k}" for k in sorted(dropped)))


def test_baselineMatchesMeasuredCount():
    """基线自身可核：条目数必须等于本轮实测对数，且每条计 1。

    钉这一条而不是只信那张字典，是因为基线一旦被手抄或被顺手调一下，棘轮从第一天起
    就对不上账——而对不上账的方向永远是放行。
    """
    measured = scanProduction().pairs
    assert len(BASELINE) == 7 and all(v == 1 for v in BASELINE.values()), (
        f"基线常量自身与本轮记录不符：{len(BASELINE)} 条 / 值 {sorted(set(BASELINE.values()))}")
    assert len(measured) == 7, (
        f"现测 {len(measured)} 对，与记录的 7 不符——要么真有人动了实现，"
        "要么扫描根／取数口径／阈值被改坏，两种都要当场看见")


def test_spanBoundNeverSkipsALongBody(tmp_path):
    """预筛③必须打在**字符上界**上——两条腿都在真扫描上取读数，不在本档里 `ast.parse`。

    第一版这格直接 `ast.parse(字面量)` 来单测 `_spanUpperBound()`，被本仓的解析预算门禁
    报成"枚举＋解析"的落点（`tests/unit/test_ci_ast_scan_budget_guard.py`）——那是对的：
    要证的本来就是**扫描行为**，而扫描行为的读数只能从真扫描里取。改后的两条腿各自钉一个方向：

    - `giant`：两行、单行 900 字符 ⇒ 行数 2 会漏、字符上界不漏 ⇒ 必须被检出；
    - `spaced`：41 行、每行十几个字符 ⇒ 行数够了但字符不到 800 ⇒ 必须不被检出。
      两格合起来才说明这条线是**按字符**画的，而不是"随便一个形状筛掉了短的"。
    """
    giant = "def giant():\n    return '" + "x" * 900 + "'\n"
    spaced = "def spaced():\n" + "".join(f"    v{i} = {i}\n" for i in range(40)) + "    return v39\n"
    for pkg, text in (("giantA", giant), ("giantB", giant), ("wideA", spaced), ("wideB", spaced)):
        d = tmp_path / pkg
        d.mkdir()
        (d / "m.py").write_text(text, encoding="utf-8")

    result = scanRoot(tmp_path)
    assert result.symbols == 2 and result.missingEnd == 0, (
        f"tmp 面读数异常（符号 {result.symbols} / 缺 end_lineno {result.missingEnd}）——"
        "两行的长体被漏掉了，八成是按行数筛")
    assert len(result.pairs) == 1, f"重复对读数不是 1：{result.pairs}"
    assert result.pairs[0].name == "giant" and result.pairs[0].ratio == 1.0, (
        f"检出的不是那对长体：{result.pairs[0]}")


def test_detectorSeparatesExactFromForked(tmp_path):
    """探测器必须能报（逐字相同），也必须不报（同名但只是相像／太短）——矩阵不是单点。

    三格各自钉一条口径：ratio=1.0 的整份拷贝进面；同名差 27% 的不进面；
    同名字节相同但体长不到 800 字符的不进面。第二格的期望差值同时被现算出来，
    免得"构造得不够像"或"构造得太像"都让这格静默失去分辨力。
    """
    dirs = [tmp_path / n for n in ("pkgA", "pkgB", "pkgC", "pkgD")]
    for d in dirs:
        d.mkdir()

    core = ("def compute(a, b):\n"
            + "".join(f"    step_{i} = a * {i} + b\n" for i in range(45))
            + "    return step_44\n")
    (dirs[0] / "one.py").write_text(core, encoding="utf-8")
    (dirs[1] / "two.py").write_text(core, encoding="utf-8")
    # 同名同签名，但 45 行里有 11 行**整行不同**（不是改一个字符）——
    # 第一版写成 `+ b` → `- b`，实测 ratio=0.9875 被当成双源：那正是"控制格取值没落在分歧点上"，
    # 由本格自己的 `0.6 <= nearRatio < RATIO_FLOOR` 抓回来，不是靠肉眼。
    forked = ("def compute(a, b):\n"
              + "".join((f"    step_{i} = (a + {i}) // 3 if {i} else b // 2\n" if i % 4 == 0
                         else f"    step_{i} = a * {i} + b\n") for i in range(45))
              + "    return step_44\n")
    (dirs[2] / "near.py").write_text(forked, encoding="utf-8")
    tiny = ("def f(x):\n" + "".join(f"    y{i} = x + {i}\n" for i in range(8)) + "    return y7\n")
    (dirs[3] / "tiny_a.py").write_text(tiny, encoding="utf-8")
    (dirs[3] / "tiny_b.py").write_text(tiny, encoding="utf-8")

    symbols, missingEnd = symbolsUnder(tmp_path)
    assert symbols and missingEnd == 0, f"tmp 扫描面异常（{len(symbols)} 符号 / 缺 end_lineno {missingEnd}）"
    pairs = similarPairs(symbols)

    def pairOf(x: str, y: str) -> list[Duplicate]:
        return [d for d in pairs if {d.fileA.rsplit("/", 1)[-1], d.fileB.rsplit("/", 1)[-1]} == {x, y}]

    exact = pairOf("one.py", "two.py")
    assert len(exact) == 1, f"逐字相同的两份实现没被检出（{exact}）⇒ 棘轮空转"
    assert exact[0].ratio == 1.0, f"完全相同的两份被算成 {exact[0].ratio}"
    assert not pairOf("one.py", "near.py"), "只差两成的同名实现被算成双源，阈值失去分辨力"
    assert not pairOf("tiny_a.py", "tiny_b.py"), (
        f"短体（<{MIN_BODY_CHARS} 字符）进了命中面，样板噪音会淹没门禁")

    bodies = {s.path.name: s.body for s in symbols}
    nearRatio = difflib.SequenceMatcher(None, bodies["one.py"], bodies["near.py"],
                                        autojunk=False).ratio()
    assert 0.6 <= nearRatio < RATIO_FLOOR, (
        f"对照组落在了不该去的地方（ratio={nearRatio}）——这格什么都没分辨，先把取值改对")
