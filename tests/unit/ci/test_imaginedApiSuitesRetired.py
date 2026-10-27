# -*- coding: utf-8 -*-
"""「按想象的 API」测试档与「整档静默 skip」退役后不许复活（§6-404 批 M）。

## 这批清的不是一族红，是一种"看起来有覆盖"的假读数

预存红分组里那族「构造签名漂移 15 格」，逐格读实装后的实况是：**被测的那个形状在生产侧从未存在过**——
不是"参数被摘掉了"，而是"参数／属性／返回值是写测试的人想象出来的"。同一次扫荡还捞出同一病灶的另一支：
`try: import X / except ImportError: 整档 skip`——模块消失时判据不说话，只留一排绿不拉几的 skip。

### 想象面（逐条对过实装）

- `tests/auth/test_security_cognitive_security.py`（14 格／9 红 5 绿）
  · `SafetyLevel.SAFE / LOW_RISK / MEDIUM_RISK / HIGH_RISK`——真枚举是 `LOW/MEDIUM/HIGH/CRITICAL`
    （`neurova/security/cognitive_security.py:57-62`）；
  · `CognitiveSecuritySystem(cognitive_orchestrator=...)`——该类签名只有 `safety_level`（`:566`），
    `cognitive_orchestrator` 七个字全仓只出现在这一档；
  · `await system.check_input_safety(...)`——实装是**同步**返回 `SafetyCheckResult`（`:578`）；
  · `is_safe, filtered, findings = filter.filter(output)`——`OutputFilter.filter` 返回**2 元组**
    `(text, findings)`（`:325`）⇒ 当场 `ValueError: not enough values to unpack`。
  同一能力的真实档 `tests/unit/security/test_cognitive_security.py` 现跑 37 passed，覆盖面是它的超集；
  唯一缺口"门面的 `check_memory_safety:649` 到底转发给谁"已补进真实档
  （`TestCognitiveSecuritySystem::test_checkMemorySafetyDelegatesToGuard`），不留"退役即失守"。
- `tests/integration/test_browser_supervisor.py`（6 格／6 红）
  · `BrowserSupervisor()` 无参构造——实装必填 `ws_url`（`browser_manager.py:131`）；
  · `supervisor.dialog_handler / event_queue / page_snapshots`——三个属性都不存在（生产侧只有
    `BrowserManager._dialog_handler:1596`，而那条还是**只写不读**的断点）；
  · `_compress_snapshot` 被想象成"按角色过滤节点、返回节点列表"，实装是字符串头截断
    （`[:10000] + "truncated"`）；真正的结构化裁剪在 `applySnapshotBudget`，其签名已由
    `tests/integration/test_browser_manager_integration.py:191-195` 钉住。
  它还跟一条**常驻反挂接守卫正面冲突**：`test_computer_use_browser_integration.py:124` 钉的是
  「`BrowserSupervisor` 是需要 CDP ws_url 的零实例化死类，不许挂到 manager 上」——一边立"别接通"，
  一边假装它早已接通还带着三个属性。
- `tests/integration/test_project_management.py`（3 格）＋ `tests/unit/projects/test_project_manager.py`（9 格）
  **一格都没跑过**：`from neurova.projects.project_manager import ProjectManager` 落空（`neurova.projects`
  包不存在、`class ProjectManager` 全仓零命中），文件用 `try/except ImportError → @skipIf(not HAS_*)`
  把整档降级成 12 条永久 skip；而 `setUp` 里还写着 `StateManager(event_bus=...)`（该类 `__init__` 不收参数），
  即便跑起来也是 TypeError。生产侧口径早已裁定：`neurova/api/endpoints/projects_api.py:19-21`
  明写"历史上曾用内存 dict / **不存在的 ProjectManager** 做兜底……该路径已删除"。

### 不退役的一档：`tests/integration/test_event_workflow.py`

4 格里 3 格其实只测 `EventBus`（多订阅者／日志回调／优先级）——`EventBus` 是生产在用的**选定单实现**
（`cognitive_layers/memory_layer/bus_event.py:6-8` 记着逐项比对后退役的另一份），只是被 `setUp` 里那次
无关的 `StateManager(event_bus=...)` 连坐；第 4 格改成真实接缝判据：`on_change` 与 `on_any_change`
必须收到 `set` 的 key/old/new（`on_any_change` 此前全仓无人钉，而 `set:104` 走的正是它），
并明写"`StateManager` 不经 EventBus 发事件"——`_emit_state_event:220` 这个名字承诺发事件、
实为遍历本地监听器，名字与实装不符已另立档案，本批不改生产语义。

## 为什么是退役而不是"把测试改成能过"

把想象的枚举／属性改成生产实装，等于**照着实装再抄一遍契约测试**——那活儿真实档已经做了。
留下想象档只会继续供一枚假读数："这个模块有 14 格守着"。教义第 7 条在此的次序是：先比（逐格对照见上）
→ 取长补短（补 1 格真缺口）→ 整档退役 ＋ 本守卫不许复活。

## 三张需人裁票（本档不做裁决）

退役的是**测试**，不是被判死的模块。`BrowserSupervisor`／`cognitive_security.py` 整文件／
`core/state_manager.py` 三个符号在生产侧**零消费者**（影响面与"删即失去什么"见
`audit-reports/zero-consumer-module-dossier-2026-10-23.md`）：接线还是删除，需人拍板。
本档只保证"想象出来的契约"和"模块消失即静默"这两种形态不再以测试的形态回来。

## 判据自己的四条对照

- 根自证：锚按本档深度（`tests/unit/ci/` ⇒ `parents[3]`）解出且必须指得到 `pyproject.toml`
  ——锚指错时下面几条会一起假绿（形态 373）。
- 正检：每种被禁形状都要在**合成样本**上被探测到（探测恒假＝断言永远不会红）。
- 负对照：真实写法（`StateManager()`／`._dialog_handler`／给别的类传 `event_bus=`／历史 prose
  里写"不存在的 ProjectManager"）不得被抓；路标行口径沿用老规矩——注释行一律算路标，
  docstring／代码行要出现「退役」或 `§6-` 才免检（形态 374）。
- 承接面自证：退役不是失守——真实档必须还在、还在跑、用例数不低于下限（读 AST 数 `def test*`，
  不读"文件在不在"，空壳档不算覆盖）。
"""

from __future__ import annotations

import ast
import pathlib
import re

from tests import ast_scan
from tests.ast_scan import parseSource

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"

#: 已退役的想象档：路径存在即红。
RETIRED_FILES = (
    "tests/auth/test_security_cognitive_security.py",
    "tests/integration/test_browser_supervisor.py",
    "tests/integration/test_project_management.py",
    "tests/unit/projects/test_project_manager.py",
)

#: 想象的形状 → 为什么它是想象。命中被收集测试的代码／docstring 即红。
BANNED_SHAPES = (
    (r"cognitive_orchestrator", "CognitiveSecuritySystem 从未收过这个构造参"),
    (r"SafetyLevel\.(SAFE|LOW_RISK|MEDIUM_RISK|HIGH_RISK)", "真枚举成员是 LOW/MEDIUM/HIGH/CRITICAL"),
    (r"\bBrowserSupervisor\(\s*\)", "BrowserSupervisor.__init__ 的 ws_url 是必填位"),
    (r"\.dialog_handler\b", "生产侧只有 BrowserManager._dialog_handler"),
    (r"\.event_queue\b|\.page_snapshots\b", "这两个属性在 BrowserSupervisor 上从未存在"),
    (r"StateManager\(\s*event_bus", "StateManager.__init__ 不接受任何参数"),
    (r"from neurova\.projects\b", "neurova.projects 包不存在（projects_api.py:19-21 已裁定该兜底路径删除）"),
    (r"\bProjectManager\(", "全仓没有 class ProjectManager"),
)

#: 合成样本用的一行真实写法（负对照：探测不得抓它们）。
LEGIT_SHAPES = (
    "        manager = StateManager()",
    "        assert manager._dialog_handler is not None",
    "        injector = UnifiedContextInjector(memory_manager=object(), event_bus=bus)",
    "    # 历史上曾用不存在的 ProjectManager 做兜底，该路径已删除",
)

_BANNED_COMPILED = [(re.compile(pat), why) for pat, why in BANNED_SHAPES]


def _isPointerLine(line: str) -> bool:
    """路标行豁免：注释行一律算路标；docstring／代码行要出现「退役」或 `§6-`。

    与 `tests/unit/core/test_closedLoopChainRetired.py` 同一口径。本档自身在对照样本里
    大量出现被禁形状，靠的是下面 `_scanCollectedTests` 里按**本档路径**排除，不是靠这句豁免。
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    return "退役" in stripped or "§6-" in stripped


#: 文本预筛词：两类判据所需名字的**并集**，且各自都是充分条件——
#: 被禁形状要用名字／包名；静默 skip 形状必然出现 `ImportError`/`ModuleNotFoundError` 与 `skipIf`。
_SCAN_HINTS = ("cognitive_orchestrator", "SafetyLevel", "BrowserSupervisor", "dialog_handler",
               "event_queue", "page_snapshots", "StateManager", "neurova.projects", "ProjectManager",
               "ImportError", "ModuleNotFoundError", "skipIf", "skipif")


def _scanCollectedTests():
    """被收集测试档的 `(路径, 文本)`：枚举走共享预算，文本预筛是被禁形状的充分条件。"""
    here = pathlib.Path(__file__).resolve()
    for ref in ast_scan.sourceRefsUnder(TESTS_ROOT, ".py", hints=_SCAN_HINTS):
        path = ref.path
        if not path.name.startswith("test_") or "manual" in path.parts:
            continue
        if path.resolve() == here:
            continue
        yield path, ref.code


def _imaginedShapeHits() -> list:
    """被禁形状在被收集测试里的落点：[(档, 行号, 说明)]。"""
    hits = []
    for path, code in _scanCollectedTests():
        for lineno, line in enumerate(code.splitlines(), start=1):
            if _isPointerLine(line):
                continue
            for pattern, why in _BANNED_COMPILED:
                if pattern.search(line):
                    hits.append((path.relative_to(REPO_ROOT).as_posix(), lineno, why))
    return sorted(set(hits))


def _wholeFileImportProbe(tree: ast.AST) -> list:
    """`try: import X / except ImportError: FLAG=False` ＋ 档位级 `skipIf(not FLAG)` 的形状。

    只认**模块级** try（类内 try 是局部容错，不在面内），且要求同一个 FLAG 名字真的被某个
    `skipIf/skipif` 装饰器读走——没被读的 FLAG 不制造静默，不算命中。
    """
    flags = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Try):
            continue
        importsInside = any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in stmt.body)
        if not importsInside:
            continue
        for handler in stmt.handlers:
            if not _handlerCatchesImportError(handler):
                continue
            for node in ast.walk(handler):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id.startswith("HAS_"):
                            flags.add(target.id)
    if not flags:
        return []
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Module)):
            continue
        for deco in getattr(node, "decorator_list", []):
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ("skipIf", "skipif")):
                continue
            names = {n.id for n in ast.walk(deco) if isinstance(n, ast.Name)}
            if names & flags:
                holder = getattr(node, "name", "<模块级>")
                hits.append((holder, sorted(names & flags)))
    return hits


def _handlerCatchesImportError(handler) -> bool:
    if handler.type is None:
        return False
    names = set()
    if isinstance(handler.type, ast.Name):
        names.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        names.update(elt.id for elt in handler.type.elts if isinstance(elt, ast.Name))
    return "ImportError" in names or "ModuleNotFoundError" in names


class TestImaginedApiSuitesRetired:

    def test_repoRootAnchorResolvesToThisRepo(self):
        """根自证：锚指错时下面几条会一起假绿，所以先让这条说话。"""
        assert (REPO_ROOT / "pyproject.toml").is_file(), (
            "REPO_ROOT=%s 指不到 pyproject.toml——退役判据与形状扫描都会落在不存在的路径上" % REPO_ROOT
        )
        assert TESTS_ROOT.is_dir(), "测试根 %s 不存在" % TESTS_ROOT

    def test_retiredImaginedSuitesStayDeleted(self):
        """四档想象／空壳测试不许复活（连文件名带路径一起钉）。"""
        back = [rel for rel in RETIRED_FILES if (REPO_ROOT / rel).is_file()]
        assert not back, "这些按想象的 API／永久 skip 的测试档又回到仓里了：%s" % back

    def test_imaginedApiShapesAreGoneFromCollectedTests(self):
        """被禁形状不得再出现在被收集测试的代码或正文里。"""
        scannedFiles = len(ast_scan.sourceRefsUnder(TESTS_ROOT, ".py"))
        assert scannedFiles >= 1000, (
            "被收集测试语料现读 %d 个 .py——TESTS_ROOT 指错时『零命中』与『没扫到』长得一样"
            % scannedFiles)
        hits = _imaginedShapeHits()
        assert not hits, (
            "这些形状在实装里从未存在过，写进测试只会供一个假读数：\n"
            + "\n".join("%s:%d ⇒ %s" % h for h in hits)
        )

    def test_noWholeFileSkipOnMissingFirstPartyModule(self):
        """`import 失败 ⇒ 整档 skip` 一律禁：模块被删时判据必须响亮地红，而不是静默地绿。

        这一支的实际账单：`neurova.projects` 从来不存在，而两档测试用这个形状把它变成了
        12 条永久 skip——收集正常、跑测全绿、覆盖为零。同族另外五档今天导入都成功（守卫是
        休眠的），但一旦对应模块被摘，它们会立刻复现同一形态，故同批拆掉，改成裸 import。
        """
        offenders = []
        for path, code in _scanCollectedTests():
            try:
                tree = parseSource(code)
            except SyntaxError:
                continue
            for holder, flags in _wholeFileImportProbe(tree):
                offenders.append("%s :: %s 读 FLAG %s"
                                 % (path.relative_to(REPO_ROOT).as_posix(), holder, flags))
        assert not offenders, (
            "这些档把『模块 import 不进来』降级成整档 skip——模块消失时没人会红：\n"
            + "\n".join(sorted(set(offenders)))
            + "\n改法：删掉 try/except 与档位级 skipIf，直接 import（真缺件就该在收集期响亮地失败）。"
        )

    def test_detectorBitesEveryBannedShapeAndSparesTheRealOnes(self):
        """正检＋负对照：探测恒假时上面几条永远绿，所以逐形现场验一遍。"""
        samples = {
            r"cognitive_orchestrator": "system = CognitiveSecuritySystem(cognitive_orchestrator=mock)",
            r"SafetyLevel\.(SAFE|LOW_RISK|MEDIUM_RISK|HIGH_RISK)": "assert SafetyLevel.SAFE.value == 'safe'",
            r"\bBrowserSupervisor\(\s*\)": "supervisor = BrowserSupervisor()",
            r"\.dialog_handler\b": "assert supervisor.dialog_handler is not None",
            r"\.event_queue\b|\.page_snapshots\b": "assert supervisor.event_queue is not None",
            r"StateManager\(\s*event_bus": "self.state_manager = StateManager(event_bus=self.event_bus)",
            r"from neurova\.projects\b": "from neurova.projects.project_manager import ProjectManager",
            r"\bProjectManager\(": "manager = ProjectManager(temp_dir)",
        }
        for pat, line in samples.items():
            assert re.compile(pat).search(line), "合成正检样本自己没命中 %s（规则写坏了）" % pat
            assert any(p.search(line) for p, _w in _BANNED_COMPILED), "%r 应被抓却没抓" % line

        for line in LEGIT_SHAPES:
            caught = [why for p, why in _BANNED_COMPILED if p.search(line)]
            assert not caught, "真实写法被误判 %r ⇒ %s" % (line, caught)

    def test_probeDetectorBitesTheSilentSkipShape(self):
        """静默 skip 探测自己的对照：违规样本被抓、裸 import 与单格 importorskip 不被抓。"""
        bad = parseSource(
            "import unittest\n"
            "try:\n"
            "    from neurova.projects.project_manager import ProjectManager\n"
            "    HAS_PROJECT_MANAGER = True\n"
            "except ImportError:\n"
            "    HAS_PROJECT_MANAGER = False\n"
            "\n"
            "@unittest.skipIf(not HAS_PROJECT_MANAGER, 'not available')\n"
            "class TestThing(unittest.TestCase):\n"
            "    def test_one(self):\n"
            "        pass\n"
        )
        assert _wholeFileImportProbe(bad), "整档静默 skip 的形状认不出 ⇒ 上一条判据恒真"

        good = parseSource(
            "import pytest\n"
            "from neurova.security.rbac import RBACManager\n"
            "\n"
            "def test_plain_import_works():\n"
            "    assert RBACManager is not None\n"
            "\n"
            "@pytest.mark.skipif(True, reason='单格级可选依赖')\n"
            "def test_one_cell_skip():\n"
            "    pass\n"
        )
        assert not _wholeFileImportProbe(good), "合规写法被判违规（负对照失效）"

    def test_retirementIsNotSilenceTheCapabilityKeptHonestCoverage(self):
        """承接面自证：真实档必须还在、还在跑，否则本守卫守的是空气。"""
        honest = {
            "tests/unit/security/test_cognitive_security.py": 20,
            "tests/unit/core/test_state_manager.py": 6,
            "tests/integration/test_event_workflow.py": 4,
            "tests/integration/test_browser_manager_integration.py": 5,
        }
        for rel, floor in honest.items():
            path = REPO_ROOT / rel
            assert path.is_file(), "承接真实契约的档不见了：%s" % rel
            tree = parseSource(path.read_text(encoding="utf-8", errors="replace"))
            names = [n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and (n.name.startswith("test_") or (n.name.startswith("test") and len(n.name) > 4
                                                         and n.name[4].isupper()))]
            assert len(names) >= floor, (
                "%s 只剩 %d 格（下限 %d）——退役之后没有任何东西在守这条能力" % (rel, len(names), floor)
            )
