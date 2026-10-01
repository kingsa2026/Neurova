# -*- coding: utf-8 -*-
"""能力可用性必须是**带 owner 的三态读数**，不是一堆布尔（T-07 · D-3）。

## 为什么这条值得常驻

改前的事实形状：

- `BrowserManager._camofox_enabled` 只看 `NEUROVA_CAMOFOX_URL` 非不非空，**从不问那台服务
  活没活**（工单集 §13.3 现场量到：`.env` 里设了 URL ⇒ 布尔为 True，而 `:9377` 实测超时）；
- `/status` 的 `vision_available` 是常量 `False`，全仓零消费方；
- 后端起不来时抛的是三处英文裸串（`No browser backend available` /
  `Browser backend not available: x` / `Failed to initialize backend: x`）——
  与 T-13 已收口的那族同源：模型读到只知道"坏了"，不知道该找谁、该做什么。

三种**处置相反**的故障（没装 / 装了但连不上 / 压根没配）被压成同一个布尔，
就会把人导向错误的自救动作。本判据钉的是"读数能不能区分开"，不是"有没有这个键"。

反自证设计：camofox 那条用**真连不上的地址**（`127.0.0.1:1`，必然 connection refused）
走真实探测口，而不是把 `camofoxReachable` mock 成想要的结果——被 mock 掉的判据不咬人。
"""

from __future__ import annotations

import pathlib
import typing

import pytest

from neurova.computer_use import capability_state as cs


@pytest.fixture(autouse=True)
def _cleanCache():
    """缓存跨用例不串：TTL 会让上一条的读数冒充本条的探测。"""
    cs.invalidate()
    yield
    cs.invalidate()


def test_everyAxisGivesAFiniteStateWithOwnerAndReason():
    readings = cs.probeAll(refresh=True)
    assert set(readings) == set(cs.CAPABILITY_NAMES), sorted(readings)
    allowed = {cs.CAP_AVAILABLE, cs.CAP_CONFIGURED_UNREACHABLE, cs.CAP_NOT_CONFIGURED, cs.CAP_UNKNOWN}
    for name, item in readings.items():
        assert item["state"] in allowed, f"{name} 的状态不在词表里：{item}"
        assert item["owner"] in {cs.OWNER_HOST, cs.OWNER_OPERATOR, cs.OWNER_AGENT}, item
        assert item["reason"].strip(), f"{name} 有状态却没原因，读它等于没读：{item}"


def test_camofoxConfiguredButUnreachableIsNotReportedAsEnabled(monkeypatch):
    """判别前提：只看配置的旧口径会把"连不上"读成"已启用"。

    这里替身的是 `camofoxConfigured`（配置面谓词）而不是 `camofox_active`（授权门）：
    探针一旦读错谓词，替身跟着错就永远测不出来——同文件那条 integration 判据
    （playwright 在册 + 配了 camofox）才抓得住这种混用。
    """
    from neurova.computer_use.browser_manager import BrowserManager

    mgr = BrowserManager(config={})
    monkeypatch.setattr(mgr, "camofoxConfigured", lambda: True)
    monkeypatch.setattr(mgr, "camofoxBaseUrl", lambda: "http://127.0.0.1:1")
    monkeypatch.setattr(cs, "_browserManager", lambda: mgr)

    r = cs.reading("camofox", refresh=True)
    assert r.state == cs.CAP_CONFIGURED_UNREACHABLE, r.asDict()
    assert r.owner == cs.OWNER_OPERATOR, f"该找的是起服务的人：{r.asDict()}"
    assert "127.0.0.1:1" in r.reason and "不可达" in r.reason, r.reason
    assert r.requiresRestart is False, "起 camofox 服务不需要重启 Neurova——报成要重启会把人支使去干别的"
    assert f"owner={cs.OWNER_OPERATOR}" in r.refusal(), r.refusal()


def test_camofoxNotConfiguredIsADifferentAnswerThanUnreachable(monkeypatch):
    from neurova.computer_use.browser_manager import BrowserManager

    mgr = BrowserManager(config={})
    monkeypatch.setattr(mgr, "camofoxConfigured", lambda: False)
    monkeypatch.setattr(cs, "_browserManager", lambda: mgr)
    r = cs.reading("camofox", refresh=True)
    assert r.state == cs.CAP_NOT_CONFIGURED, r.asDict()
    assert r.usable() is False


def test_cacheIsBoundedAndRefreshAndInvalidateEachBreakIt(monkeypatch):
    calls: typing.List[str] = []
    monkeypatch.setattr(cs, "CAPABILITY_TTL_SECONDS", 3600.0)

    def fakeProbe(_manager=None):
        calls.append("probe")
        return cs.CapabilityReading("camofox", cs.CAP_AVAILABLE, cs.OWNER_AGENT, "假探成功")

    monkeypatch.setattr(cs, "_probeCamofox", fakeProbe)
    cs.reading("camofox")
    cs.reading("camofox")
    assert len(calls) == 1, f"TTL 内不该重复付探测的钱，实付 {len(calls)} 次"
    cs.reading("camofox", refresh=True)
    assert len(calls) == 2, "refresh=true 必须绕过缓存"
    cs.invalidate("camofox")
    cs.reading("camofox")
    assert len(calls) == 3, "显式失效后必须重探"


def test_backendRefusalsCarryTheTriStateNotAnEnglishBareString():
    """三处英文裸串必须换成带状态与 owner 的原文。"""
    import asyncio

    from neurova.computer_use.browser_manager import BrowserManager

    mgr = BrowserManager(config={})
    mgr._backends.clear()
    mgr._camofox_enabled = False
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(mgr._get_backend())
    text = str(exc.value)
    assert "capability-aria-" in text, f"没有能力 marker，模型只能瞎猜：{text}"
    assert "owner=" in text, text
    for legacy in ("No browser backend available", "Browser backend not available",
                   "Failed to initialize backend"):
        assert legacy not in text, f"旧英文裸串又漏回生产面：{legacy} in {text}"


def test_noLegacyEnglishRaiseRemainsInTheSource():
    """源码级反证（与 T-13 同法）：字符串不在产出面里，就没人能在下一轮把它悄悄加回来。"""
    src = pathlib.Path(cs.__file__).resolve().parents[0].joinpath("browser_manager.py").read_text(
        encoding="utf-8")
    for legacy in ('RuntimeError("No browser backend available")',
                   'Browser backend not available: {name}',
                   'Failed to initialize backend: {name}'):
        assert legacy not in src, f"英文裸串回潮：{legacy}"


def test_statusBooleansAreDerivedFromTheOneReading(monkeypatch):
    """旧键保留，但必须由同一份读数派生——否则第二份事实源悄悄长出来。"""
    from neurova.api.endpoints import computer as computer_ep

    fake = {
        "screenshot": {"state": cs.CAP_AVAILABLE, "owner": cs.OWNER_AGENT, "reason": "ok",
                       "requiresRestart": False},
        "input": {"state": cs.CAP_CONFIGURED_UNREACHABLE, "owner": cs.OWNER_HOST,
                  "reason": "打不开", "requiresRestart": True},
        "uia": {"state": cs.CAP_NOT_CONFIGURED, "owner": cs.OWNER_HOST, "reason": "非 Windows",
                "requiresRestart": False},
        "aria": {"state": cs.CAP_AVAILABLE, "owner": cs.OWNER_AGENT, "reason": "playwright",
                 "requiresRestart": False},
        "camofox": {"state": cs.CAP_CONFIGURED_UNREACHABLE, "owner": cs.OWNER_OPERATOR,
                    "reason": "连不上", "requiresRestart": False},
        "vision": {"state": cs.CAP_AVAILABLE, "owner": cs.OWNER_AGENT, "reason": "实测支持",
                   "requiresRestart": False},
    }
    seen: typing.List[typing.Tuple[bool, typing.Any]] = []

    def spyProbeAll(*, refresh: bool = False, manager=None):
        seen.append((refresh, manager))
        return {name: dict(item) for name, item in fake.items()}

    monkeypatch.setattr(cs, "probeAll", spyProbeAll)
    import asyncio

    sentinel = object()  # 装配点哨兵：端点必须把自己那一份 manager 交下去，而不是另起一个
    monkeypatch.setattr(computer_ep, "_get_manager", lambda *a, **k: sentinel)
    monkeypatch.setattr(cs, "probeAll", spyProbeAll)
    import asyncio

    res = asyncio.run(computer_ep.get_status())
    data = res["data"]
    assert [item[0] for item in seen] == [False], f"默认必须读缓存：{seen}"
    assert [item[1] for item in seen] == [sentinel], (
        f"/status 没把它的装配点交给探测层（桌面三轴就会去探真机器，替身失效）：{seen}")
    assert data["screenshot_available"] is True
    assert data["input_available"] is False, "读数不可用却报 True ⇒ 派生被绕过"
    assert data["desktop_available"] is False, "截图可用+输入不可用 ⇒ 桌面整体不可用"
    assert data["vision_available"] is True, "vision 还报 False 就是常量没撤干净"
    assert data["capabilities"] == fake, "三态面必须原样交给消费方，不是只留派生布尔"

    asyncio.run(computer_ep.get_status(refresh=True))
    assert [item[0] for item in seen] == [False, True], "refresh=true 没传到探测层"


def test_doctorDerivesFromTheSameReadingAsStatus(monkeypatch):
    """/doctor 与 /status 不得各判一次能力。改前 `doctor_report()` 自己比
    `_screenshot_backend == "PIL"`、自己调 `input_available()`——同一事实的第二份定义，
    探测口径一改两侧就分叉。现在两者都由 `probeAll` 派生。"""
    from neurova.computer_use import ComputerUseManager

    fake = {
        "screenshot": {"state": cs.CAP_AVAILABLE, "owner": cs.OWNER_AGENT, "reason": "PIL",
                       "requiresRestart": False},
        "input": {"state": cs.CAP_CONFIGURED_UNREACHABLE, "owner": cs.OWNER_HOST,
                  "reason": "通道打不开", "requiresRestart": True},
        "uia": {"state": cs.CAP_NOT_CONFIGURED, "owner": cs.OWNER_HOST, "reason": "非 Windows",
                 "requiresRestart": False},
        "aria": {"state": cs.CAP_AVAILABLE, "owner": cs.OWNER_AGENT, "reason": "playwright",
                 "requiresRestart": False},
        "camofox": {"state": cs.CAP_NOT_CONFIGURED, "owner": cs.OWNER_OPERATOR, "reason": "未设",
                    "requiresRestart": False},
        "vision": {"state": cs.CAP_UNKNOWN, "owner": cs.OWNER_OPERATOR, "reason": "无证据",
                   "requiresRestart": False},
    }
    got: typing.List[typing.Any] = []

    def spy(*, refresh: bool = False, manager=None):
        got.append(manager)
        return {name: dict(item) for name, item in fake.items()}

    monkeypatch.setattr(cs, "probeAll", spy)
    manager = ComputerUseManager()
    report = manager.doctor_report()
    assert report["pillow"] is True and report["pyautogui_input"] is False \
        and report["uia"] is False, report
    assert report["capabilities"] == fake, "doctor 也得把三态面交出去，否则只剩两个口径"
    assert got == [manager], f"自检必须把自己那一份管理器交给探测层：{got}"


def test_uiaDetailIsTheSingleSourceForTheBoolean():
    """`is_available()` 必须等于 `availabilityDetail()['available']`，两处不许各判一次。"""
    from neurova.computer_use import desktop_uia

    detail = desktop_uia.availabilityDetail()
    assert detail["available"] is desktop_uia.is_available()
    assert detail["state"] in {cs.CAP_AVAILABLE, cs.CAP_NOT_CONFIGURED}, detail
    assert detail["reason"].strip(), detail


def test_inputProbeDistinguishesMissingLibraryFromBlockedChannel(monkeypatch):
    """库没装 与 装了但通道打不开 是两个 owner、两种自救动作。"""
    from neurova.computer_use import get_computer_use_manager

    manager = get_computer_use_manager()
    ok, state, reason = manager.inputProbe()
    assert ok is (state == cs.CAP_AVAILABLE), (ok, state, reason)
    if not ok:
        assert state in {cs.CAP_NOT_CONFIGURED, cs.CAP_CONFIGURED_UNREACHABLE}, (state, reason)
        assert reason.strip(), reason


def test_visionReadingNeverInventsEvidence(monkeypatch):
    """没有实测也没有声明时必须是 `unknown`，不能拿"没证据"冒充"不可用"。"""
    from neurova.llm.provider_manager import LLMProviderManager
    from neurova.llm.model_capability_cache import ModelCapabilityCache

    class _NoMeta:
        model_metadata: dict = {}

    monkeypatch.setattr(LLMProviderManager, "get_active_model",
                        lambda self: {"provider_id": "probe", "model": "m-unknown",
                                      "provider_name": "p", "base_url": ""}, raising=False)
    monkeypatch.setattr(LLMProviderManager, "get_default_provider",
                        lambda self: _NoMeta(), raising=False)
    monkeypatch.setattr(ModelCapabilityCache, "get",
                        lambda self, key, cap, default=None: default, raising=False)
    r = cs.reading("vision", refresh=True)
    assert r.state == cs.CAP_UNKNOWN, r.asDict()
    assert r.owner == cs.OWNER_OPERATOR, r.asDict()


def test_visionAvailableComesFromEvidenceNotTheOldLiteral(monkeypatch):
    """`vision_available` 由读数派生：实测说支持才是 True。

    夹具形状按**事实源**（用户配置里 `model_metadata[*]["capabilities"]` 实测 866 条全是 list，
    0 条 dict —— `capability_names()` 是那条字段的单源出口）。本条初版替它造的是 dict 形状，
    等于照着一个没有生产者会写的形状自证；Q-2 落地时一并纠正。
    """
    from neurova.llm.provider_manager import LLMProviderManager
    from neurova.llm.model_capability_cache import ModelCapabilityCache

    class _Meta:
        model_metadata = {"m-vision": {"capabilities": ["vision"]}}

    monkeypatch.setattr(LLMProviderManager, "get_active_model",
                        lambda self: {"provider_id": "probe", "model": "m-vision",
                                      "provider_name": "p", "base_url": ""}, raising=False)
    monkeypatch.setattr(LLMProviderManager, "get_default_provider", lambda self: _Meta(), raising=False)
    monkeypatch.setattr(ModelCapabilityCache, "get",
                        lambda self, key, cap, default=None: default, raising=False)
    r = cs.reading("vision", refresh=True)
    assert r.state == cs.CAP_AVAILABLE and r.usable(), r.asDict()


def _learnViaProductionWriter(supported: bool, capabilityArg):
    """用**生产写侧**把探测结论落进元数据与进程级缓存，返回那个 provider 对象。

    能力名与形状都由写侧决定，本判据不挑名字——挑了就等于让替身跟着实现一起错
    （工单集 §26.4 的教训）。只把落盘 `_save_config` 摘掉，不碰用户目录。
    """
    import threading

    from neurova.llm.provider_manager import LLMProviderManager
    from neurova.llm.providers.types import ProbeResult

    class _Provider:
        def __init__(self):
            self.id = "probe"
            self.default_model = "m-learned"
            self.model_metadata: dict = {}

    class _WriterSelf:
        _config_lock = threading.RLock()

        def _save_config(self) -> None:
            return None

    provider = _Provider()
    result = ProbeResult(
        model_id="m-learned",
        supported=supported,
        capabilities=capabilityArg,
        metadata={} if supported else {"probe_detail": "media_rejected"},
    )
    LLMProviderManager._persist_probe_result(_WriterSelf(), provider, "m-learned", result)
    return provider


def _pointActiveModelAt(monkeypatch, provider) -> None:
    from neurova.llm.provider_manager import LLMProviderManager

    monkeypatch.setattr(LLMProviderManager, "get_active_model",
                        lambda self: {"provider_id": provider.id, "model": "m-learned",
                                      "provider_name": "p", "base_url": ""}, raising=False)
    monkeypatch.setattr(LLMProviderManager, "get_default_provider",
                        lambda self: provider, raising=False)


def test_probeResultFromEnumProviderBecomesReadableDeclaration(monkeypatch):
    """探测回枚举成员时，写侧存的必须仍是可读的小写名 —— 清空缓存后声明档要能开门。

    咬住的形状：`_persist_probe_result` 早先用 `[str(c) for c in capabilities]`，而
    `ProviderCapability` 是 (str, Enum) mixin，`str()` 吐的是 `ProviderCapability.VISION`
    类名形态 ⇒ `"vision" in [...]` 恒 False，探测成功却把结论写没了。
    """
    from neurova.llm.model_capability_cache import reset_capability_cache
    from neurova.llm.providers.types import ProviderCapability

    reset_capability_cache()
    provider = _learnViaProductionWriter(True, [ProviderCapability.VISION])
    reset_capability_cache()          # 只留声明档，验写侧存的形状
    _pointActiveModelAt(monkeypatch, provider)
    try:
        r = cs.reading("vision", refresh=True)
        assert r.state == cs.CAP_AVAILABLE, r.asDict()
        assert "声明" in r.reason, r.asDict()
    finally:
        reset_capability_cache()


def test_learnedYesOpensVisionAxisEvenWhenDeclarationFaceIsBlank(monkeypatch):
    """实测档必须读得到缓存里那条 True：两表面会分叉（配置裁剪/换模型时元数据重铺，缓存仍在）。

    咬住的形状：能力轴问缓存用的名字与唯一写入方学的名字不同源 ⇒ 这一档结构性不可达，
    docstring 写的"实测 > 声明"证据次序名不副实。
    """
    from neurova.llm.model_capability_cache import reset_capability_cache

    reset_capability_cache()
    provider = _learnViaProductionWriter(True, ["vision"])
    provider.model_metadata = {}      # 声明面抹平，只剩实测
    _pointActiveModelAt(monkeypatch, provider)
    try:
        r = cs.reading("vision", refresh=True)
        assert r.state == cs.CAP_AVAILABLE, r.asDict()
        assert "实测" in r.reason, r.asDict()
    finally:
        reset_capability_cache()


def test_measuredRejectionIsNotDowngradedToUnknown(monkeypatch):
    """探测实测"不支持图" ⇒ 必须报 configured-unreachable，不许退回"没证据"。

    写侧在 supported=False 时不会把 vision 写进 capabilities，声明面因此本就是空的；
    这时唯一的事实是缓存里那条 False。读不到它就等于把已证伪的结论当未知，
    下一轮还会再付一次探测，而 T-09 的门也会因"unknown 不给图"反复悬着。
    """
    from neurova.llm.model_capability_cache import reset_capability_cache

    reset_capability_cache()
    provider = _learnViaProductionWriter(False, [])
    _pointActiveModelAt(monkeypatch, provider)
    try:
        r = cs.reading("vision", refresh=True)
        assert r.state == cs.CAP_CONFIGURED_UNREACHABLE, r.asDict()
        assert "实测" in r.reason, r.asDict()
    finally:
        reset_capability_cache()
