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
2. **落点由生产单点推导**：`tests/manual/` 下不得出现 `"data"` 目录字面量拼路径。
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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
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
    return sorted(
        path for path in MANUAL_ROOT.glob("*.py")
        if not path.name.startswith("_") and "__pycache__" not in path.parts
    )


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
    offenders: list[str] = []
    for path in _manualScripts():
        text = path.read_text(encoding="utf-8")
        if re.search(r'join\([^)]*[\'"]data[\'"]', text):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, (
        "以下脚本自己拼了 `data/` 落点 —— 落点推导的唯一单点是 `core/data_root.py`，"
        "脚本抄第二份就会与生产打开的库不是同一个文件：\n  " + "\n  ".join(offenders)
    )


def testDataRootLiteralIsDetected():
    """反向控制：把落点字面量塞进一份样本，判定必须翻转。"""
    sample = 'dbPath = os.path.join(cwd, "data", "context_ledger", "x.db")\n'
    assert re.search(r'join\([^)]*[\'"]data[\'"]', sample), "反向控制失效：判据抓不到该形态"


# ───────────────────────── 判据 3：注入数据根 ─────────────────────────


def testManualScriptsConstructingProductionObjectsInjectDataRoot():
    offenders: list[str] = []
    for path in _manualScripts():
        text = path.read_text(encoding="utf-8")
        if _injectsDataRoot(text):
            continue
        tree = ast.parse(text, filename=str(path))
        if _callsProductionBuilder(tree):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, (
        "以下脚本构造了生产持久对象却没注入数据根 —— 未注入时 `get_data_root()` "
        "落仓库 `data/`，而绝对锚定之后 `os.chdir()` 已经不能隔离落点：\n  "
        + "\n  ".join(offenders)
    )


def testMissingInjectionIsDetected():
    """反向控制：一份「构造生产对象 + 不注入」的样本必须被判红。"""
    sample = "from neurova.agent_core import Agent\nagent = Agent(cfg)\n"
    tree = ast.parse(sample)
    assert _callsProductionBuilder(tree), "反向控制失效：判据认不出生产构造调用"
    assert not _injectsDataRoot(sample), "反向控制失效：样本意外含隔离单点"
    assert _injectsDataRoot(
        'from tests.manual._liveVerifyIsolation import isolatedDataRoot\nisolatedDataRoot()\n'
    ), "反向控制失效：判据认不出隔离单点（只认字面量就等于把单点路径封死）"
