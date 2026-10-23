# -*- coding: utf-8 -*-
"""对象内键值状态袋：全仓只许留**一处**实装，三族消费者共用它（§6-409 批 O-3）。

## 要收的那三处（本批现查，不沿用旧描述）

同一件功能——"给一个对象挂一串键值状态，写了要能读回来"——在 `neurova/` 里有三份实装：

1. `core/base_module.py:70/74` `set_state_value`/`get_state_value`，存 `self._state_values`。
   **在役**：`core/idle_tracker.py` 往它写 6 个键（`:165/:172/:355/:565/:693/:726`），
   `tests/unit/memory/test_sleep_loop_wiring.py:111` 读回 `running` —— 有写有读，是本档选定的那一份。
2. `cognitive_layers/memory_layer/sleep.py:272/276` 同名两行，存 `self._state`。
   该 dict 在全仓只被这三行用到（`:194` 建、`:274` 写、`:278` 读）⇒ 与 ① 是同一功能的第二份拷贝。
3. `plugins/base_plugin.py:293-311` 的 `get_state`/`set_state`，**坏的那一份**：它转发到
   `self._state_manager.get_state(self.plugin_id, key, default)` / `.set_state(plugin_id, key, value)`，
   而 `core/state_manager.py` 的真 API 是 `get(key, default)` / `set(key, value)`（`:74/:88`）⇒
   那两个带 `plugin_id` 的方法**从未存在**。且 `_state_manager` 只在 `:109` 被置 None，
   `state_manager` 的 setter（`:164`）全仓零调用；`BasePlugin.get_state/set_state` 本身
   在 neurova/ ＋ tests/ ＋ scripts/ 里**零调用方**。

⇒ 教义第 7 条的次序落在这里是：**比**（① 在役有读路、② 与① 逐字符同功能、③ 契约错位且无人调）
→ **取长补短**（③ 唯一"多出"的东西是跨对象共享的一个全局 dict，而那个 dict 本身
   `get_state_manager()` 零消费者——没有不可替代的部分可取）
→ **接通**（三族都指向 ①）→ **退役**（② 的两行与 ③ 的整套接缝同批删净，含 `_state_manager`
   字段与 `state_manager` 那对属性）。

## 顺带扫到的同根一处（第 5 条：同一根因全命中点）

`core/idle_tracker.py:116` 的签名广告了 `state_manager=`／`log_manager=`／`error_handler=`
三个注入位，但构造体里只把 `event_bus` 转给 `super().__init__`，另三个**收下即丢**
（`BaseModule` 连这三个形参名都没有，靠 `**kwargs` 静默吞掉）。全仓 grep 构造函数签名
只有这一处广告它们，且**没有任何调用方传过** ⇒ 撤广告，不加"顺手把它们接上"的第二体系。

## 本档不做的事（写在明处，免得被当成已收口）

- **`StateManager` 的去留不由本档裁**：用户裁的是"先修错位接缝，再定去留"。接缝已按上面
  收口；`core/state_manager.py` 三个符号在收口后仍**零生产消费者**，那张需人裁票的档案在
  `audit-reports/zero-consumer-module-dossier-2026-10-23.md`（M3）。
- **不给插件加"跨进程持久化状态"**：插件态的现役单源是 `plugin_manager.py:44`
  `STATE_FILE_NAME = "state.json"`（装过什么／启没启用，§6-164 裁定）与
  `plugin_lifecycle.py:194/205` 的运行态字符串——都不是任意键值袋，本批不动它们。

## 判据自己的四条对照

- **行为断言先跑**：第一格在三族上各写一次、读回来、比默认值与覆盖值——今天的红是
  `AttributeError`（插件那份方法名对不上）与"三个 function 对象不是同一个"，不是 import 失败。
- **唯一实装用"同一个对象"判**：`is` 比解析到的方法函数本体，比数定义行更难绕（抄一份
  一模一样的代码会同时被两条抓到，两条互为反证）。
- **反面控制**：`BaseModule.get_state()/set_state(ModuleState)` 是**状态机**，与键值袋同名不同职，
  必须仍然存在且仍不收 key——否则本批就成了"顺手抹掉一半契约"。
- **面自证**：扫描分三面分开比（枚举文件数／预筛候选数／定义点数），合成样本双向验探测器。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
NEUROVA_ROOT = REPO_ROOT / "neurova"

#: 键值袋这一功能允许的名字——与状态机的 `get_state`/`set_state` 严格分开。
_STORE_METHODS = ("set_state_value", "get_state_value")
#: 那件坏接缝的名字：收口后 `BasePlugin` 上不该再有任何一个。
_RETIRED_SEAM = ("get_state", "set_state", "state_manager", "_state_manager")


class _ProbeModule:
    pass


def _concreteModule():
    from neurova.core.base_module import BaseModule

    class Concrete(BaseModule):
        def on_initialize(self) -> None:
            pass

        def on_start(self) -> None:
            pass

        def on_stop(self) -> None:
            pass

    return Concrete()


def _probePlugin():
    from neurova.plugins.base_plugin import BasePlugin
    from neurova.plugins.plugin_manifest import PluginManifest, SemVersion

    class Probe(BasePlugin):
        async def on_initialize(self) -> None:
            pass

        async def on_start(self) -> None:
            pass

        async def on_stop(self) -> None:
            pass

        async def on_destroy(self) -> None:
            pass

    return Probe(PluginManifest(plugin_id="state-probe", name="Probe",
                                version=SemVersion("1.0.0")))


def _consolidation():
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    return SleepConsolidation()


def _storeDefinitionSites(tree: ast.AST) -> list:
    """这棵 AST 里**定义**了 `_STORE_METHODS` 的行号（调用不算，`x.set_state_value()` 不是实装）。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _STORE_METHODS:
            out.append(node.name)
    return out


def _scanDefinitionSites():
    """扫 `neurova/`，返回 [(相对路径, 方法名)]——按定义点计，不按引用点计。"""
    hits = []
    candidates = ast_scan.sourceRefsUnder(NEUROVA_ROOT, ".py", hints=_STORE_METHODS)
    for ref in candidates:
        for name in _storeDefinitionSites(ast_scan.transientTree(ref.path)):
            hits.append((ref.path.relative_to(REPO_ROOT).as_posix(), name))
    return hits, len(candidates)


class TestTheStateValueStoreIsOneImplementation:
    """三族共用同一份实装；坏的那份接缝不许复活。"""

    def test_allThreeFamiliesRoundTripThroughTheStore(self):
        """行为面：写进去要读得回来、缺失要给默认值、覆盖要可见——三族都走同样两条方法。"""
        for label, obj in (("BaseModule", _concreteModule()),
                           ("SleepConsolidation", _consolidation()),
                           ("BasePlugin", _probePlugin())):
            assert all(hasattr(obj, name) for name in _STORE_METHODS), (
                "%s 上没有 %s——键值袋的口径还没统一（插件族今天只有坏掉的 get_state/set_state）"
                % (label, "/".join(_STORE_METHODS))
            )
            assert obj.get_state_value("missing", "fallback") == "fallback", (
                "%s 的默认值路径不通：写了别的键之后，读不存在的键该回默认" % label)
            obj.set_state_value("phase", 1)
            assert obj.get_state_value("phase") == 1, "%s 写完读不回来" % label
            obj.set_state_value("phase", 2)
            assert obj.get_state_value("phase") == 2, "%s 覆盖不可见" % label

    def test_theTwoMethodsAreLiterallyTheSameObject(self):
        """唯一实装的硬判据：三族解析到的函数本体必须是**同一个**，不是"各抄一份长得像的"。"""
        from neurova.core import base_module

        store = getattr(base_module, "StateValuesStore", None)
        assert store is not None, (
            "`core/base_module.py` 里还没有 `StateValuesStore`——键值袋的实装仍散在三处"
            "（BaseModule 一份、SleepConsolidation 一份、BasePlugin 一份坏掉的转发）"
        )
        owners = {
            "BaseModule": type(_concreteModule()),
            "SleepConsolidation": type(_consolidation()),
            "BasePlugin": type(_probePlugin()),
        }
        for label, cls in owners.items():
            for name in _STORE_METHODS:
                resolved = getattr(cls, name, None)
                assert resolved is not None, "%s 缺 %s" % (label, name)
                # 类上取到的是**函数本体**（不是绑定方法），三族一致 ⇔ 真的共用同一份实装；
                # 各抄一份时这里是两个不同的函数对象，比"数定义行"更难绕。
                assert resolved is getattr(store, name), (
                    "%s.%s 不是共用那一份实装（各自实现的那份读的是不同的 dict 字段）"
                    % (label, name)
                )

    def test_pluginNoLongerClaimsAStateManagerSeam(self):
        """坏接缝退役：`BasePlugin` 上不得再有 `get_state`/`set_state`/`state_manager`/`_state_manager`，
        源码里也不得再出现 `StateManager` 这个名字——它转发的方法从未存在，留着就是**谎报的契约**。"""
        from neurova.plugins import base_plugin
        from neurova.plugins.base_plugin import BasePlugin

        plugin = _probePlugin()
        leaked = [name for name in _RETIRED_SEAM if hasattr(BasePlugin, name) or hasattr(plugin, name)]
        assert not leaked, "退役的接缝回来了：%s（`:300/:311` 那两个带 plugin_id 的方法在 StateManager 上不存在）" % leaked
        assert "_state_manager" not in plugin.__dict__, (
            "实例上又长出 `_state_manager`——一个从不被赋值、也无人注入的字段正是本批要清的那条形"
        )
        source = (NEUROVA_ROOT / "plugins" / "base_plugin.py").read_text(encoding="utf-8")
        assert "StateManager" not in source, (
            "`base_plugin.py` 又引用起 `StateManager` 了；`core/state_manager.py` 的去留是 M3 那张"
            "需人裁票，不在这里被接缝**默认接线**"
        )

    def test_lifecycleStateContractSurvivesAsItsOwnThing(self):
        """反面控制：状态机那一对**同名不同职**的方法必须还在、且仍不收 key。

        少了这一格，上一条就只是"把名字删了"——`BaseModule.get_state()` 返回 `ModuleState`、
        `set_state(ModuleState)` 发 `module.state_changed` 事件（`:78/:95`），它们是另一件功能。
        """
        from neurova.core.base_module import BaseModule, ModuleState

        module = _concreteModule()
        assert module.get_state() is ModuleState.UNINITIALIZED, "状态机读口没了"
        module.set_state(ModuleState.RUNNING)
        assert module.get_state() is ModuleState.RUNNING, "状态机写口没了"
        assert "key" not in inspect.signature(BaseModule.get_state).parameters, (
            "`BaseModule.get_state` 又长出 key 形参＝键值袋与状态机再次混进同一个名字"
        )

    def test_productionTreeKeepsExactlyOneDefinitionPair(self):
        """定义面复算：`neurova/` 里 `_STORE_METHODS` 的定义点只剩一份（两行），且在选定那份文件里。"""
        hits, _candidates = _scanDefinitionSites()
        byFile = {}
        for rel, name in hits:
            byFile.setdefault(rel, []).append(name)
        assert sorted(byFile) == ["neurova/core/base_module.py"], (
            "键值袋的实装还不止一处：%s——教义第 7 条在这里的判据是「该功能在仓内只剩一处实现被消费」" % byFile
        )
        assert sorted(byFile["neurova/core/base_module.py"]) == sorted(_STORE_METHODS), (
            "选定那份文件里的定义不是恰好一对：%s" % byFile["neurova/core/base_module.py"]
        )

    def test_scanFaceIsNotVacuous(self):
        """面自证（三面分开比）：枚举面掉穿＝扫描根指错；候选面为空＝预筛写窄；只有定义点为 0 而前两面正常才可能是真收口。"""
        enumerated = len(ast_scan.sourceRefsUnder(NEUROVA_ROOT, ".py"))
        assert enumerated >= 800, (
            "`neurova/` 现读 %d 个 .py——NEUROVA_ROOT 指错时上一条的『只剩一处』不作数" % enumerated
        )
        _hits, candidates = _scanDefinitionSites()
        assert candidates >= 3, (
            "提到 %s 的文件只剩 %d 个——预筛词或收集口径写窄了" % ("/".join(_STORE_METHODS), candidates)
        )

    def test_detectorBitesDuplicateDefinitionsAndSparesCalls(self):
        """合成样本双向对照：探测器要数得出重复实装，也不许把**调用**数成实装。"""
        duplicated = (
            "class A:\n"
            "    def set_state_value(self, key, value):\n        pass\n"
            "    def get_state_value(self, key, default=None):\n        return None\n"
            "class B:\n"
            "    def set_state_value(self, key, value):\n        pass\n"
        )
        assert sorted(_storeDefinitionSites(ast.parse(duplicated))) == [
            "get_state_value", "set_state_value", "set_state_value"], "重复实装没被数出来 ⇒ 定义面判据是恒真的"
        onlyCalls = (
            "def use(x):\n"
            "    x.set_state_value('k', 1)\n"
            "    return x.get_state_value('k')\n"
        )
        assert _storeDefinitionSites(ast.parse(onlyCalls)) == [], (
            "把调用点数成了实装——定义面判据会把每一个消费者都误报成第二份拷贝"
        )


class TestIdleTrackerDoesNotAdvertiseKnobsItCannotHonor:
    """幻影注入位的撤广告：签名上写了的参数必须真被消费。"""

    def test_ctorAcceptsOnlyTheBusItActuallyForwards(self):
        from neurova.core.idle_tracker import IdleTimeTracker

        params = list(inspect.signature(IdleTimeTracker.__init__).parameters)
        assert params == ["self", "event_bus"], (
            "`IdleTimeTracker.__init__` 又广告了转不出去的注入位：%s——构造体只把 `event_bus` 交给 "
            "`super().__init__`，另三个被 `BaseModule` 的 `**kwargs` 静默吞掉（全仓 grep 无任何调用方"
            "传它们，也从未有读者）" % params
        )

    def test_baseModuleStillHonoursItsOwnNamedKnobs(self):
        """反面控制：`BaseModule` 的具名参数面不许被一起削掉（它收 config/event_bus/… 并真存字段）。"""
        from neurova.core.base_module import BaseModule

        named = inspect.signature(BaseModule.__init__).parameters
        for knob in ("config", "event_bus", "module_id", "name", "version"):
            assert knob in named, "BaseModule 的具名注入位 %s 不见了" % knob
