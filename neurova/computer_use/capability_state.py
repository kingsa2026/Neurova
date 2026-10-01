"""能力可用性的一等状态（T-07 · D-3）。

在此之前"能不能用"只有一堆布尔，而且来源是**看环境变量**而不是真探：
`_camofox_enabled` 只要 `NEUROVA_CAMOFOX_URL` 非空就是 True，从不问那台服务活没活；
`/status` 的 `vision_available` 干脆写成常量 `False`。两者都把"三种处置相反的故障"
压成同一个读数——没装依赖、装了但连不上、压根没配，该找的人与该做的事完全不同。

本模块是这条面的**唯一事实源**：六个读数，每个都带状态、owner（谁能修）、
具名原因与"改授权要不要重启"。它只**消费**既有探测点（`manager.input_available()`、
`desktop_uia` 的探测、`BrowserManager._backends`、provider 的模型档案），不另起一套探测，
否则就是教义第 6 条点名的第二份定义。

状态集合（字符串常量，进模型可见面，保持稳定）：

- `available`               真探通过，可以按该能力动作；
- `configured-unreachable`  配置指向的东西拿不到（服务没起、依赖装了但调用失败、权限被拒）；
- `not-configured`          根本没配/依赖不在；
- `unknown`                 配置到位但**没有任何声明或实测证据**——只有视觉这一条用得上它，
                            因为"模型支不支持图"要么靠 provider 声明、要么靠真发一张图探测，
                            把"没证据"报成"不可用"会把人导向错误的自救动作。

缓存口径（用户 2026-10-01 拍板：缓存 + TTL + 显式失效）：一次真探多次读，
TTL 内直接回缓存；后端注册、配置变更、动作失败各处调 `invalidate()` 主动作废；
`/status?refresh=true` 走强探。取数**懒执行**：没人读某个能力就不为它花钱。
"""

from __future__ import annotations

import os
import threading
import time
import typing
from dataclasses import dataclass

CAP_AVAILABLE = "available"
CAP_CONFIGURED_UNREACHABLE = "configured-unreachable"
CAP_NOT_CONFIGURED = "not-configured"
CAP_UNKNOWN = "unknown"

#: 谁能修这一项——报错 owner 就等于把人送到错误的自救动作上
OWNER_HOST = "host"          # 缺依赖/缺系统授权：装东西或开权限
OWNER_OPERATOR = "operator"  # 外部服务没起或配置不对：起进程、改配置
OWNER_AGENT = "agent"        # 重试或换一条能力路径即可

CAPABILITY_TTL_SECONDS = 5.0

#: 面板全集：截图 / 输入 / UIA / aria / camofox / 视觉
CAPABILITY_NAMES = ("screenshot", "input", "uia", "aria", "camofox", "vision")


@dataclass(frozen=True)
class CapabilityReading:
    """一项能力的一次读数。`state` 是判据，`reason` 是给模型与人看的原文。"""

    name: str
    state: str
    owner: str
    reason: str
    requiresRestart: bool = False

    def usable(self) -> bool:
        return self.state == CAP_AVAILABLE

    def refusal(self) -> str:
        """产出侧具名拒绝文案（单源）：manager 层三处抛出与 /status 都读这一句。"""
        hint = "需重启宿主进程后重探" if self.requiresRestart else "可重探或改配置后重探"
        return f"capability-{self.name}-{self.state}: {self.reason}（owner={self.owner}，{hint}）"

    def asDict(self) -> typing.Dict[str, typing.Any]:
        return {
            "state": self.state,
            "owner": self.owner,
            "reason": self.reason,
            "requiresRestart": self.requiresRestart,
        }


_lock = threading.RLock()
_cache: typing.Dict[str, typing.Tuple[float, CapabilityReading]] = {}

#: 桌面三轴走注入的装配点；其余三轴的事实源在浏览器/模型侧
_DESKTOP_AXES = frozenset({"screenshot", "input", "uia"})


def _cacheKey(name: str, manager: typing.Any) -> str:
    """按装配点分键：一份替身管理器的读数不得冒充另一份（也不得冒充真的）。"""
    return name if manager is None else f"{name}@{id(manager)}"


def _axisOf(key: str) -> str:
    return key.split("@", 1)[0]


def invalidate(*names: str) -> None:
    """显式失效：后端注册、配置变更、动作失败处调用。不传参即全清。"""
    with _lock:
        if not names:
            _cache.clear()
            return
        wanted = set(names)
        for key in [k for k in _cache if _axisOf(k) in wanted]:
            _cache.pop(key, None)


def _cached(key: str, refresh: bool) -> typing.Optional[CapabilityReading]:
    if refresh:
        return None
    hit = _cache.get(key)
    if not hit:
        return None
    stamp, reading = hit
    if time.monotonic() - stamp > CAPABILITY_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    return reading


def _read(key: str, probe: typing.Callable[[], CapabilityReading], refresh: bool) -> CapabilityReading:
    hit = _cached(key, refresh)
    if hit is not None:
        return hit
    try:
        reading = probe()
    except Exception as e:  # noqa: BLE001 - 探测自身失败必须成为读数，不能把端点打崩
        reading = CapabilityReading(
            name=_axisOf(key), state=CAP_CONFIGURED_UNREACHABLE, owner=OWNER_AGENT,
            reason=f"能力探测自身抛错：{type(e).__name__}: {e}",
        )
    with _lock:
        _cache[key] = (time.monotonic(), reading)
    return reading


def _desktopManager():
    from neurova.computer_use import get_computer_use_manager

    return get_computer_use_manager()


def _probeScreenshot(manager) -> CapabilityReading:
    try:
        backend = manager.screenshotBackend()
    except Exception as e:  # noqa: BLE001 - 管理器起不来本身就是故障现场
        return CapabilityReading("screenshot", CAP_CONFIGURED_UNREACHABLE, OWNER_HOST,
                                 f"桌面管理器不可用：{type(e).__name__}: {e}")
    if backend != "basic":
        return CapabilityReading("screenshot", CAP_AVAILABLE, OWNER_AGENT, f"截图后端={backend}")
    return CapabilityReading(
        "screenshot", CAP_NOT_CONFIGURED, OWNER_HOST,
        "截图后端停在 basic 兜底（Pillow 的 ImageGrab 未生效）——装 Pillow 后重探")


def _probeInput(manager) -> CapabilityReading:
    ok, state, reason = manager.inputProbe()
    if ok:
        return CapabilityReading("input", CAP_AVAILABLE, OWNER_AGENT, reason)
    return CapabilityReading("input", state, OWNER_HOST, reason,
                             requiresRestart=_globalInputNeedsRestart())


def _globalInputNeedsRestart() -> bool:
    """`NEUROVA_ALLOW_GLOBAL_INPUT` 每次调用现读，但部署里它由启动环境给——改了要重启进程。"""
    return bool(os.environ.get("NEUROVA_ALLOW_GLOBAL_INPUT"))


def _probeUia(manager) -> CapabilityReading:
    state, reason = manager.uiaProbe()
    owner = OWNER_AGENT if state == CAP_AVAILABLE else OWNER_HOST
    return CapabilityReading("uia", state, owner, reason)


def _browserManager():
    from neurova.computer_use.browser_manager import get_browser_manager

    return get_browser_manager()


def _probeAria(_manager=None) -> CapabilityReading:
    try:
        status = _browserManager().get_status()
    except Exception as e:  # noqa: BLE001
        return CapabilityReading("aria", CAP_CONFIGURED_UNREACHABLE, OWNER_HOST,
                                 f"浏览器管理器不可用：{type(e).__name__}: {e}")
    backends = list(status.get("available_backends") or [])
    if backends:
        return CapabilityReading("aria", CAP_AVAILABLE, OWNER_AGENT,
                                 f"可产出 aria 快照的后端：{', '.join(backends)}")
    return CapabilityReading(
        "aria", CAP_NOT_CONFIGURED, OWNER_HOST,
        "没有任何浏览器后端在册（Playwright/Scrapling 都未导入成功）——装依赖后重探")


def _probeCamofox(_manager=None) -> CapabilityReading:
    """camofox 的关键：`_camofox_enabled` 只看配置，本探针**真打一次 /health**。"""
    try:
        manager = _browserManager()
    except Exception as e:  # noqa: BLE001
        return CapabilityReading("camofox", CAP_CONFIGURED_UNREACHABLE, OWNER_HOST,
                                 f"浏览器管理器不可用：{type(e).__name__}: {e}")
    if not manager.camofoxConfigured():
        url = os.environ.get("NEUROVA_CAMOFOX_URL") or ""
        why = (f"URL 已设（{url}）但 camofox 未启用（配置里 enabled 关闭或缺 httpx）"
               if url else "NEUROVA_CAMOFOX_URL 未设且配置未启用")
        return CapabilityReading("camofox", CAP_NOT_CONFIGURED, OWNER_OPERATOR, why)
    url = manager.camofoxBaseUrl()
    reachable, why = camofoxReachable(url)
    if reachable:
        return CapabilityReading("camofox", CAP_AVAILABLE, OWNER_AGENT, f"{url} /health 通过")
    return CapabilityReading(
        "camofox", CAP_CONFIGURED_UNREACHABLE, OWNER_OPERATOR,
        f"已配置 {url} 但不可达：{why}——起 camofox-browser 服务后重探，无需重启本进程")


def camofoxReachable(url: str, timeoutSeconds: float = 1.5) -> typing.Tuple[bool, str]:
    """真打 `/health`。返回 (可达?, 原文原因)。"""
    if not url:
        return False, "URL 为空"
    try:
        import httpx

        with httpx.Client(timeout=timeoutSeconds) as client:
            r = client.get(f"{url.rstrip('/')}/health")
            if r.status_code < 300:
                return True, f"HTTP {r.status_code}"
            return False, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001 - 连不上是常态读数，不是崩溃
        return False, f"{type(e).__name__}: {e}"


def _probeVision(_manager=None) -> CapabilityReading:
    """视觉轴的证据次序：实测（学习型缓存）> provider 声明 > 没有证据=`unknown`。

    把"没证据"报成"不可用"会让 T-09 的门永久关闭，而真探一次要真发一张图，
    不该在 /status 里付费——这正是 §19 说的懒执行。
    """
    try:
        from neurova.llm.provider_manager import get_provider_manager

        active = get_provider_manager().get_active_model()
    except Exception as e:  # noqa: BLE001
        return CapabilityReading("vision", CAP_CONFIGURED_UNREACHABLE, OWNER_OPERATOR,
                                 f"活跃模型取不到：{type(e).__name__}: {e}")
    if not active:
        return CapabilityReading("vision", CAP_NOT_CONFIGURED, OWNER_OPERATOR,
                                 "没有默认服务商/模型——配好模型后重探")
    model = str(active.get("model") or "")
    key = f"{active.get('provider_id')}:{model}"
    try:
        from neurova.llm.model_capability_cache import ModelCapabilityCache

        learned = ModelCapabilityCache.get_instance().get(key, "vision")
    except Exception:  # noqa: BLE001 - 缓存读不到就退回声明
        learned = None
    if learned is not None:
        state = CAP_AVAILABLE if learned else CAP_CONFIGURED_UNREACHABLE
        return CapabilityReading("vision", state, OWNER_AGENT,
                                 f"实测（学习型缓存）{key} vision={learned}")
    declared = _declaredVision(active)
    if declared is True:
        return CapabilityReading("vision", CAP_AVAILABLE, OWNER_AGENT, f"provider 声明 {model} 支持图")
    if declared is False:
        return CapabilityReading("vision", CAP_CONFIGURED_UNREACHABLE, OWNER_HOST,
                                 f"provider 声明 {model} 不含图像输入")
    return CapabilityReading("vision", CAP_UNKNOWN, OWNER_OPERATOR,
                             f"{model} 既无实测也无声明——需要跑一次多模态探测才能定")


def _declaredVision(active: typing.Dict[str, typing.Any]) -> typing.Optional[bool]:
    """从 provider 的模型档案里取声明；取不到返回 None（绝不猜）。"""
    try:
        from neurova.llm.provider_manager import get_provider_manager

        provider = get_provider_manager().get_default_provider()
        if provider is None:
            return None
        meta = (provider.model_metadata or {}).get(str(active.get("model") or "")) or {}
        caps = meta.get("capabilities") or {}
        for key in ("vision", "image", "supports_vision"):
            if key in caps:
                return bool(caps.get(key))
            if key in meta:
                return bool(meta.get(key))
        modalities = meta.get("input_modalities") or caps.get("input_modalities") or []
        if modalities:
            return any(str(m).lower() in ("image", "vision") for m in modalities)
    except Exception:  # noqa: BLE001 - 声明面缺字段是"没有证据"，不是错误
        return None
    return None


def reading(name: str, *, refresh: bool = False, manager: typing.Any = None) -> CapabilityReading:
    """单条读数（懒执行：只探被问到的那一条）。

    `manager` 是**桌面三轴**的装配点注入位：`/status` 用它自己的 `_get_manager()`，
    这样判据替身的是"外部世界"，而不是绕过装配点手工传阈值——后者会让判据与生产分叉。
    传了 manager 时缓存按 manager 分键，避免一份替身的读数冒充另一份。
    """
    probes = {
        "screenshot": _probeScreenshot,
        "input": _probeInput,
        "uia": _probeUia,
        "aria": _probeAria,
        "camofox": _probeCamofox,
        "vision": _probeVision,
    }
    probe = probes.get(name)
    if probe is None:
        raise KeyError(f"未登记的能力轴: {name}（全集 {CAPABILITY_NAMES}）")
    if name in _DESKTOP_AXES and manager is None:
        manager = _desktopManager()
    return _read(_cacheKey(name, manager), lambda: probe(manager), refresh)


def probeAll(*, refresh: bool = False, manager: typing.Any = None) -> typing.Dict[str, typing.Dict[str, typing.Any]]:
    """整块读数，供 /status 与自检消费。"""
    return {name: reading(name, refresh=refresh, manager=manager).asDict() for name in CAPABILITY_NAMES}
