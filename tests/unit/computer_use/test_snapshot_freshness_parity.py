# -*- coding: utf-8 -*-
"""T-03 · 快照新鲜度两后端语义对齐（工单集 T-03）。

## 根因（亲验）

`generation` 是"这份快照事实还新不新"的唯一凭据。两个浏览器后端**都校验它**，
但只有 camofox 会在交互后让它失效：

| 动作 | CamofoxServerBackend | PlaywrightBackend |
|------|---------------------|-------------------|
| `navigate` | 推进 | 推进（`browser_manager.py:546`） |
| `click` / `type_text` | **推进** | 不推进 |
| `click_role` / `fill_role` | 经 `_click_ref`/`_type_ref` **推进** | **校验 generation 却不推进** |

最后一行是真缺陷：Playwright 的 role 层动作"查了新事实、放旧事实出去"——
模型 `dom_snapshot` 拿到 g、点一个会改写列表的按钮、再拿同一个 g 去点下一个
role 目标，**照样通过**。camofox 侧同一条序列会被拒（`:396` 注释："交互使快照事实失效"）。

同一工具在两个后端下新鲜度语义不同，不是风格差而是判据差。

## 处置边界（显式声明，不静默放宽）

`SNAPSHOT_MUTATING_ACTIONS` = {navigate, click, type_text, click_role, fill_role}
—— 判据取"**会让 DOM 变的动作必须使快照失效**"，与 camofox 现行为一致。

`execute_js` **不在集合内**：它两边都不推进、也都不校验，属两个后端**共同的限制**，
不是本单要修的分叉。把它记进 `KNOWN_CONTRACT_EXCEPTIONS` 并配一条"例外不得变僵尸"
的反向控制——将来谁实现了它而不处理新鲜度，这里会红。

`dom_read`（游标分片续读）**故意不校验新鲜度**：它的语义是"接着读同一份已取回的事实"，
推进或校验都会让分片续读自我失效。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from neurova.computer_use import browser_manager as bm

MODULE_DIR = pathlib.Path(bm.__file__).parent

# 会让 DOM 变的动作：实现它们的后端必须使该 tab 的快照事实失效
SNAPSHOT_MUTATING_ACTIONS = frozenset(
    {"navigate", "click", "type_text", "click_role", "fill_role"}
)

# 已知且已记录的合同例外：名字 -> 理由。**加例外必须带理由，销例外必须同步改代码。**
KNOWN_CONTRACT_EXCEPTIONS = {
    "PlaywrightBackend.execute_js": (
        "camofox 同样不推进也不校验 ⇒ 两后端共同限制而非分叉；修它要同时改两个后端"
        "且 JS 可静默改 DOM 的边界需单独裁量。登记待办，不静默放过。"
    ),
    "CamofoxServerBackend.execute_js": "同上，与 PlaywrightBackend.execute_js 成对。",
}

# 参与快照新鲜度契约的后端。ScraplingBackend 不实现 dom_snapshot/click_role/fill_role
# （无快照契约可言）⇒ 合法不在本集合内；若它将来实现了快照面，下面的成员资格判据会红。
CONTRACT_BACKENDS = ("PlaywrightBackend", "CamofoxServerBackend")


def _backendClasses(rootDir: pathlib.Path) -> dict:
    tree = ast.parse((rootDir / "browser_manager.py").read_text(encoding="utf-8"))
    camo = ast.parse((rootDir / "camofox_server_backend.py").read_text(encoding="utf-8"))
    found = {}
    for module in (tree, camo):
        for cls in (n for n in ast.walk(module) if isinstance(n, ast.ClassDef)):
            found[cls.name] = cls
    return found


def _methodBodies(cls: ast.ClassDef) -> dict:
    return {
        f.name: (ast.unparse(f), f)
        for f in cls.body
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _bumpsHere(bodyAst: ast.AST) -> bool:
    for node in ast.walk(bodyAst):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Subscript):
            sl = node.target.slice
            key = sl.value if isinstance(sl, ast.Constant) else getattr(sl, "value", None)
            if key == "generation":
                return True
    return False


def _advancesGeneration(cls: ast.ClassDef, methodName: str, _seen=None) -> bool:
    """该方法**自身或其类内委托**是否使 tab["generation"] 失效（最多追 3 跳）。

    必须有这一层：camofox 的 `click_role` 自己不含自增，它委托给 `_click_ref` 才推进。
    只看方法体会把"已推进"误判成"没推进"，于是"两后端一致"这条判据会
    在两边都被误判为 False 时**假通过**——本判据初版正是踩在这个上面。
    """
    seen = _seen or set()
    if methodName in seen:
        return False
    seen = seen | {methodName}
    entry = _methodBodies(cls).get(methodName)
    if entry is None:
        return False
    _src, fn = entry
    if _bumpsHere(fn):
        return True
    callees = {
        n.func.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
    }
    for name in callees:
        if _advancesGeneration(cls, name, seen):
            return True
    return False


def _isAbstractMethod(fn: ast.AST) -> bool:
    """协议基类里的 dom_snapshot 只声明不实现——不能把它当"参与了快照契约"。

    判据取体形状（docstring + pass/.../raise NotImplementedError），
    不按类名猜：协议类改名或将来给基类加默认实现，这里都会自动跟。
    """
    stmts = getattr(fn, "body", [])
    real = [
        s for s in stmts
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str))
    ]
    if not real:
        return True
    if len(real) == 1:
        only = real[0]
        if isinstance(only, ast.Pass):
            return True
        if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis:
            return True
        if isinstance(only, ast.Raise):
            exc = only.exc
            name = getattr(getattr(exc, "func", None), "id", None) or getattr(exc, "id", None) or ""
            return name in {"NotImplementedError"}
    return False


def _concreteMethodNames(cls: ast.ClassDef) -> set:
    return {
        f.name
        for f in cls.body
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and not _isAbstractMethod(f)
    }


class TestGenerationParityContract:
    """静态契约判据：两后端在同一批动作上必须同进同退。"""

    def test_contractBackendsArePresent(self):
        classes = _backendClasses(MODULE_DIR)
        missing = [n for n in CONTRACT_BACKENDS if n not in classes]
        assert not missing, f"后端类改名或移动，本判据已失去靶子: {missing}"

    def test_snapshotContractBackendMustExistForEverySnapshotSurface(self):
        """实现 dom_snapshot 的**具体后端**必须在契约集合内——防止第三个后端悄悄加入而不受判据。

        基类识别按"是否被同类里另一个类继承"来判，不按类名后缀、也不按方法体形状：
        `BrowserBackend.dom_snapshot` 是**默认拒绝**（`return BrowserResult(success=False,
        error="... does not support aria snapshot")`），它是协议给出的能力兜底，
        不是"实现了快照契约"。用名字或"函数体是否只声明"都判不准这种形态。
        `BrowserManager` 是门面而非后端，同理不算。
        """
        classes = _backendClasses(MODULE_DIR)
        bases = {
            ast.unparse(cls.bases[0]) for cls in classes.values() if cls.bases
        } | {
            name for cls in classes.values() for b in cls.bases
            for name in [ast.unparse(b)]
        }
        concreteBackends = {
            name for name, cls in classes.items()
            if name.endswith("Backend") and name not in bases
        }
        snapshotBackends = {
            name for name in concreteBackends
            if "dom_snapshot" in _concreteMethodNames(classes[name])
            and not self._isCapabilityDenial(classes[name], "dom_snapshot")
        }
        assert snapshotBackends <= set(CONTRACT_BACKENDS), (
            f"实现了 dom_snapshot 却不受新鲜度判据约束的后端: "
            f"{sorted(snapshotBackends - set(CONTRACT_BACKENDS))}"
        )

    @staticmethod
    def _isCapabilityDenial(cls: ast.ClassDef, methodName: str) -> bool:
        """方法体是否只是"本后端不支持该能力"的无条件拒绝。"""
        for fn in cls.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name != methodName:
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
                    src = ast.unparse(node.value)
                    if "success=False" in src and "support" in src:
                        return True
            return False
        return False
        assert snapshotBackends <= set(CONTRACT_BACKENDS), (
            f"实现了 dom_snapshot 却不受新鲜度判据约束的后端: "
            f"{sorted(snapshotBackends - set(CONTRACT_BACKENDS))}"
        )

    @pytest.mark.parametrize("action", sorted(SNAPSHOT_MUTATING_ACTIONS))
    def test_actionAdvancesGenerationIdenticallyAcrossBackends(self, action: str):
        """同一个使 DOM 变化的动作，两个后端要么都使快照失效，要么都不——不许一单一双。"""
        classes = _backendClasses(MODULE_DIR)
        observed = {}
        for backend in CONTRACT_BACKENDS:
            bodies = _methodBodies(classes[backend])
            if action not in bodies:
                observed[backend] = None  # 该后端未实现此动作
                continue
            observed[backend] = _advancesGeneration(classes[backend], action)
        implemented = {k: v for k, v in observed.items() if v is not None}
        assert len(set(implemented.values())) <= 1, (
            f"动作 {action} 的新鲜度语义在两后端分叉: {observed}"
        )

    @pytest.mark.parametrize("action", sorted(SNAPSHOT_MUTATING_ACTIONS))
    def test_everyMutatingActionActuallyAdvances(self, action: str):
        """不只是"两边一致"，还要"一致地对"：凡实现该动作，必须推进 generation。"""
        classes = _backendClasses(MODULE_DIR)
        offenders = []
        for backend in CONTRACT_BACKENDS:
            bodies = _methodBodies(classes[backend])
            key = f"{backend}.{action}"
            if action not in bodies:
                continue
            if not _advancesGeneration(classes[backend], action) and key not in KNOWN_CONTRACT_EXCEPTIONS:
                offenders.append(key)
        assert not offenders, (
            f"这些动作会使 DOM 变化却不使快照事实失效（旧 generation 会被继续接受）: {offenders}"
        )

    def test_exceptionListIsNotZombie(self):
        """反向控制：登记的理由若已不再成立（代码已推进），必须从例外名单删掉。"""
        classes = _backendClasses(MODULE_DIR)
        for key, _reason in KNOWN_CONTRACT_EXCEPTIONS.items():
            backend, _, action = key.partition(".")
            bodies = _methodBodies(classes[backend])
            assert action in bodies and not _advancesGeneration(classes[backend], action), (
                f"{key} 已不再是例外（已推进或方法不存在）——请同步销掉登记"
            )

    def test_detectorFollowsDelegation(self):
        """正对照：探测必须认得出"自身不推进、委托后才推进"的那一处。

        没有这条，探测函数会在 camofox.click_role 上漏判，进而让
        test_actionAdvancesGenerationIdenticallyAcrossBackends 两边都算 False 而假通过。
        """
        classes = _backendClasses(MODULE_DIR)
        camo = classes["CamofoxServerBackend"]
        assert _advancesGeneration(camo, "click_role"), (
            "追溯失效：camofox.click_role 经 _click_ref 推进，探测却没看出来"
        )
        assert _advancesGeneration(camo, "navigate"), "探测连自增都在自身方法体的用例都认不出"
        pw = classes["PlaywrightBackend"]
        assert _advancesGeneration(pw, "navigate"), "Playwright.navigate 已知推进，认不出即探测坏"
        # 并且必须能认出"确实没推进"——否则探测等价于恒真，
        # "两后端一致"会在两边都漏判时假通过。用 execute_js 做这个负对照：
        # 它在两个后端上都仍不推进（已登记为共同限制），修复其它点后依然成立。
        assert not _advancesGeneration(pw, "execute_js"), (
            "探测恒真：Playwright.execute_js 当前确实不推进，必须算成 False"
        )
        assert not _advancesGeneration(classes["CamofoxServerBackend"], "execute_js"), (
            "探测恒真：camofox.execute_js 同样不推进，负对照须在两侧都判 False"
        )
