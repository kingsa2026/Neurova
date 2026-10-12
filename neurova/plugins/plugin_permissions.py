from __future__ import annotations

"""插件的授权面：能力键**取用技能那份单点**，插件独有面只有事件总线两档（台账 §6-157，用户 2026-10-12 裁「甲 · 彻底合一」）。

## 为什么这一份被重写了一遍

§6-155 给插件立了八项 `PluginPermission`，其中四项（文件读／文件写／网络／命令执行）与
`neurova/skills/permissions.py` 的七类能力键是**同一件事的两份定义**——而那一份才是真在执行的：
`tool_executor.py:1033` 把声明装进作用域、`:1540` 处按声明拒。更糟的是我自己把插件那四项写成
`disclosed_only`（"拦不住，只是披露"）。根因不是判断错，是**比对象比窄了**：判"有没有第二份定义"时
只按包名扫了 `neurova/plugins/`，没按能力面关键词扫到 `neurova/skills/`（失效形态第 69 条）。

按教义第 6 条收口到一份：**能力面词汇、安装校验、调用面仲裁全部单点在 skills**，本模块只**取用**。
`capabilityKeys()` 每次调用现取 `KNOWN_CAPABILITY_KEYS`（判据里另有一格改那份集合、断这里跟着变——
存一份副本就能骗过"集合相等"那一格）。

## 两类面，各自的强制点

| 面 | 取值来自 | 强制点 |
|---|---|---|
| 能力键（capability） | `neurova.skills.permissions.KNOWN_CAPABILITY_KEYS` | 工具执行咽喉：`skill_permission_scope()` ＋ `check_tool_permission()`（多归属取 AND） |
| 框架中介面（surface） | 本模块 `PluginFrameworkSurface`，恰两项 `read:events`/`emit:events` | `BasePlugin.subscribe/unsubscribe/publish_event` 当场拒 |

`http:request` 与 `admin` **不再是权限项**：前者就是 `network`（能力键那份已覆盖），
后者的角色门单点在 `neurova.api.deps.require_role`——留在权限面里就是第三、第四份口径。

## 档位取消了，不是放宽了

`framework_enforced / disclosed_only / never_grantable` 三档随本模块一起退役。原来把
`execute:commands`/`admin` 定成"不许授予"，实质是**"我拦不住所以禁止"**；现在命令与系统面归到
`system` 能力键：可授予，且授予后由调用面真拦（未声明的工具在 `tool_executor` 里被拒成 DENY 形态）。
这不是把口子开大，是把"靠档位声明的假强度"换成"靠仲裁点的真强度"。

## 授予存储的三条不变纪律（沿用 §6-155）

1. **落盘**（`dataPath("plugins/permissions.json")`）：装载记录本就只在内存里（重启由插件根重新发现），
   而**授予不是可以重新发现的东西**——它是人的决定；内存字典意味着每次重启都要人重点一遍，人于是闭眼点。
2. **审计写不进即回滚**（既有 `log_audit` / `PERMISSION_CHANGE`），不留"改了却没记"的半态。
3. **坏文件与历史形态都不静默**：读侧一律朝安全侧失败（＝未授予），写侧点名成因、且不覆写文件
   （`execute:commands → system` 是**变宽**，那种映射只能由人做一次显式动作，故 `STORE_VERSION`
   升到 2 后旧文件走 `grants_store_legacy_format` 响亮拒绝）。

## 仍然不构成沙箱

动态装载本身就是进程内任意代码执行（`exec_module` 里它可以自己 `import pathlib/socket/subprocess`
而绕开工具面）。本模块给的是**框架面的准入控制与留痕**：能力键管"经框架调用工具时拦得住"，
命名空间与身份门管"对外开的那一面"。两份架构文档里「路径沙箱/沙箱执行」的表述已按此改名实。
"""

import json
import os
import threading
import time
import typing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from neurova.core.data_root import dataPath
from neurova.core.lazy_singleton import lazySingleton
from neurova.core.logger import get_logger
from neurova.plugins.plugin_errors import PluginError
from neurova.plugins.plugin_manifest import PluginFrameworkSurface
from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

logger = get_logger(__name__)

#: 存储格式版本。2 ＝ 收口后的词汇表；读到 1（八项 `PluginPermission` 那一版）
#: 既不当成"空授权表"，也不就地改写——那是人的决定，只能人重新确认一遍。
STORE_VERSION = 2

#: §6-155 那八项里被收口掉的六个值。留着只为了把历史文件**点名**拒掉，
#: 不参与任何判定路径（判据：`tests/unit/plugins/test_pluginPermissionSingleSource.py`）。
RETIRED_PERMISSION_VALUES = ("http:request", "read:files", "write:files",
                             "network:access", "execute:commands", "admin")


# ── 词汇单点：能力键取用 skills，框架中介面在本模块 ──────────────

def capabilityKeys() -> typing.List[str]:
    """能力键候选，**每次调用现取** skills 那份 `KNOWN_CAPABILITY_KEYS`。"""
    from neurova.skills import permissions as skillPermissions

    return sorted(getattr(skillPermissions, "KNOWN_CAPABILITY_KEYS"))


def frameworkSurfaces() -> typing.List[str]:
    """插件独有面（事件总线两档）。"""
    return [surface.value for surface in PluginFrameworkSurface]


def grantCandidates() -> typing.List[str]:
    """管理面可以列出供逐项确认的全部取值（单一并集，两处 UI 不再各抄一份）。"""
    return sorted(set(capabilityKeys()) | set(frameworkSurfaces()))


def surfaceKind(value: typing.Any) -> str:
    """`"capability"` / `"surface"`——两类面的差别决定"授予之后由谁去拦"。"""
    return "surface" if str(value) in set(frameworkSurfaces()) else "capability"


def permissionValue(value: typing.Any) -> str:
    """把声明/授予的取值收成字符串；认不出即点名成因（封闭集合外没有默认值）。"""
    if isinstance(value, Enum):
        value = value.value
    text = str(value or "")
    if text in set(frameworkSurfaces()) or text in set(capabilityKeys()):
        return text
    if text in set(RETIRED_PERMISSION_VALUES):
        raise PluginError(
            "grants_store_legacy_format",
            "%r 是 §6-155 那一版的历史值，已被收口（能力面用 skills 那七类键，框架面只剩 %s）"
            "——请重新逐项确认，本模块不自动映射" % (text, "/".join(frameworkSurfaces())))
    raise PluginError("unknown_permission",
                      "不是已登记的授权项：%r（可用项：%s）" % (value, ", ".join(grantCandidates())))


@dataclass(frozen=True)
class FrameworkSurfaceSpec:
    """框架中介面的口径：授予后放行什么、强制点在哪。"""

    surface: PluginFrameworkSurface
    unlocks: str
    enforcedAt: str


#: 只覆盖两项面。能力键的口径在 `skills/permissions.py`（那份是唯一出处，此处不重述）。
FRAMEWORK_SURFACE_MODEL: typing.Dict[PluginFrameworkSurface, FrameworkSurfaceSpec] = {
    PluginFrameworkSurface.READ_EVENTS: FrameworkSurfaceSpec(
        PluginFrameworkSurface.READ_EVENTS, "经事件总线订阅/退订他方事件",
        enforcedAt="neurova.plugins.base_plugin:BasePlugin.subscribe"),
    PluginFrameworkSurface.EMIT_EVENTS: FrameworkSurfaceSpec(
        PluginFrameworkSurface.EMIT_EVENTS, "经事件总线向他方投递事件",
        enforcedAt="neurova.plugins.base_plugin:BasePlugin.publish_event"),
}


def _declaredFromPluginManager(pluginId: str) -> typing.List[str]:
    """默认声明面：经 `PluginManager` 的清单读面取，本模块不自己解析 manifest。"""
    from neurova.plugins.plugin_manager import get_plugin_manager

    return get_plugin_manager().declaredPermissionsOf(pluginId)


def _normalizedValue(permission: typing.Any) -> str:
    return permission if isinstance(permission, str) else str(permission.value)


class PluginPermissionStore:
    """「哪个插件的哪一项授权经人确认过」的存储（键可以是能力键，也可以是框架中介面）。

    两类值同库同审计同纪律——差别只在授予之后由谁去拦（`surfaceKind()` 就是这个区分）。
    """

    def __init__(self, path: typing.Optional[str] = None,
                 declaredProvider: typing.Optional[typing.Callable[[str], typing.Sequence[str]]] = None):
        self._path = str(path or dataPath("plugins", "permissions.json"))
        self._declared = declaredProvider or _declaredFromPluginManager
        self._lock = threading.RLock()
        self._grants: typing.Dict[str, typing.Dict[str, dict]] = {}
        self._mounts: typing.Dict[str, dict] = {}
        self._corrupt: typing.Optional[str] = None
        self._legacy: typing.Optional[str] = None
        self._loaded = False

    @property
    def path(self) -> str:
        return self._path

    # ── 读写 ───────────────────────────────────────────

    def _load(self) -> None:
        """惰性读；坏文件与历史形态各记各的，都不当成"空"。"""
        if self._loaded:
            return
        self._loaded = True
        if not Path(self._path).exists():
            self._grants = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            self._corrupt = str(exc)
            logger.error("插件授权文件读不出（%s）：%s——拒绝把它当「谁都没授予过」", self._path, exc)
            return
        version = data.get("version") if isinstance(data, dict) else None
        if isinstance(data, dict) and version == 1:
            self._legacy = "§6-155 那一版（八项 PluginPermission 词汇）的授予文件"
            logger.error("%s：%s——词汇已收口，须由人重新逐项确认；本模块不自动映射也不覆写",
                         self._legacy, self._path)
            return
        if not isinstance(data, dict) or version != STORE_VERSION:
            self._corrupt = "无法识别的授权文件格式/版本：%r" % (
                version if isinstance(data, dict) else type(data).__name__)
            logger.error("%s（%s）", self._corrupt, self._path)
            return
        grants = data.get("grants")
        if not isinstance(grants, dict):
            self._corrupt = "授权文件里的 grants 不是对象"
            return
        self._grants = {str(pid): {str(perm): dict(rec or {})
                                   for perm, rec in (per or {}).items()}
                        for pid, per in grants.items()}
        # 挂载授权与逐项确认是同一类东西：都是人的决定，都得跨重启成立。
        mounts = data.get("mounts")
        self._mounts = {str(pid): dict(rec or {}) for pid, rec in mounts.items()} \
            if isinstance(mounts, dict) else {}

    def _requireWritable(self) -> None:
        self._load()
        if self._legacy:
            raise PluginError("grants_store_legacy_format",
                              "%s（%s）不可再改：先把这份历史文件人工处置掉（改名留档或删掉），"
                              "再对新词汇逐项确认" % (self._legacy, self._path))
        if self._corrupt:
            raise PluginError("grants_store_corrupt",
                              "%s 读不出来（%s）——修好它再改授予，本模块不覆写它"
                              % (self._path, self._corrupt))

    def _save(self) -> None:
        payload = {"version": STORE_VERSION, "grants": self._grants, "mounts": self._mounts}
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        tmp = "%s.tmp" % self._path
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # ── 读数（一律朝安全侧失败：读不出＝没有授权）─────────────

    def isGranted(self, pluginId: str, permission: typing.Any) -> bool:
        self._load()
        if self._corrupt or self._legacy:
            return False
        return _normalizedValue(permission) in self._grants.get(pluginId, {})

    def grantedFor(self, pluginId: str) -> typing.List[str]:
        self._load()
        if self._corrupt or self._legacy:
            return []
        return sorted(self._grants.get(pluginId, {}))

    def declaredFor(self, pluginId: str) -> typing.List[str]:
        """清单声明了什么就是什么，**原样收成字符串**：认不出的项留在 pending 里，
        于是没人能确认它、聚合门也过不去——那才是安全侧。"""
        return sorted({_normalizedValue(p) for p in (self._declared(pluginId) or [])})

    def pendingFor(self, pluginId: str) -> typing.List[str]:
        return sorted(set(self.declaredFor(pluginId)) - set(self.grantedFor(pluginId)))

    def orphanedFor(self, pluginId: str) -> typing.List[str]:
        """已授予但清单不再声明的（聚合门不看它，面板要能看见——清单改过而授权没跟）。"""
        return sorted(set(self.grantedFor(pluginId)) - set(self.declaredFor(pluginId)))

    def snapshot(self) -> typing.Dict[str, Any]:
        self._load()
        return {
            "path": self._path,
            "corrupt": bool(self._corrupt),
            "corrupt_reason": self._corrupt or "",
            "legacy": bool(self._legacy),
            "legacy_reason": self._legacy or "",
            "grants": {pid: dict(per) for pid, per in self._grants.items()},
            "mounts": {pid: dict(rec) for pid, rec in self._mounts.items()},
        }

    # ── 挂载授权（第二次授权；与逐项确认同属「人的决定」，同库同审计）──

    def mountAuthorized(self, pluginId: str) -> bool:
        self._load()
        if self._corrupt or self._legacy:
            return False
        return pluginId in self._mounts

    def authorizeMount(self, pluginId: str, grantedBy: str = "",
                       routes: typing.Sequence[str] = ()) -> dict:
        """记录「这个插件的 HTTP 面经人放行」。**只在路由真的挂上之后调用**——
        授权了却没挂成，读数就谎报了一次能力放行。"""
        self._requireWritable()
        with self._lock:
            before = dict(self._mounts)
            record = {"authorized_by": grantedBy, "authorized_at": _now(), "routes": sorted(routes)}
            self._mounts[pluginId] = record
            self._save()
            if not self._audit(grantedBy, "plugin_routes_authorized", pluginId,
                               {"routes": sorted(routes)}):
                self._mounts = before
                self._save()
                raise PluginError("audit_write_failed", "挂载授权审计写失败，授权已回滚")
            return dict(record, changed=True)

    def revokeMount(self, pluginId: str, grantedBy: str = "") -> dict:
        """撤销授权（幂等：没授权过就是没授权，卸载路径要能无条件调它）。"""
        self._requireWritable()
        with self._lock:
            if pluginId not in self._mounts:
                return {"changed": False}
            before = dict(self._mounts)
            removed = self._mounts.pop(pluginId)
            self._save()
            if not self._audit(grantedBy, "plugin_routes_unauthorized", pluginId,
                               {"routes": removed.get("routes", [])}):
                self._mounts = before
                self._save()
                raise PluginError("audit_write_failed", "撤销挂载授权的审计写失败，授权已还原")
            return dict(removed, changed=True)

    def grantedMountActor(self, pluginId: str) -> str:
        self._load()
        return (self._mounts.get(pluginId) or {}).get("authorized_by", "")

    # ── 变更 ───────────────────────────────────────────

    def grant(self, pluginId: str, permission: typing.Any, grantedBy: str = "") -> dict:
        # 可写性先判：文件或词汇形态不可信时，任何「这条没声明/那条已授予」的结论都不可信。
        self._requireWritable()
        value = permissionValue(permission)
        declared = set(self.declaredFor(pluginId))
        if value not in declared:
            raise PluginError(
                "permission_not_declared",
                "插件 %s 的清单没声明 %s，不能授予——声明与授予只能同向（否则「先授予后声明」即越权入口）"
                % (pluginId, value))

        with self._lock:
            before = dict(self._grants.get(pluginId, {}))
            if value in before:
                return dict(before[value], changed=False)
            record = {"granted_by": grantedBy, "granted_at": _now(), "kind": surfaceKind(value)}
            after = dict(before)
            after[value] = record
            self._write(pluginId, after, record_action="plugin_permission_grant",
                        grantedBy=grantedBy, value=value)
            return dict(record, changed=True)

    def revoke(self, pluginId: str, permission: typing.Any, grantedBy: str = "") -> dict:
        value = permissionValue(permission)
        self._requireWritable()
        with self._lock:
            before = dict(self._grants.get(pluginId, {}))
            if value not in before:
                raise PluginError("not_granted",
                                  "插件 %s 并没有被授予 %s——撤销一条不存在的授予不该被记成一笔"
                                  % (pluginId, value))
            removed = before.pop(value)
            self._write(pluginId, before, record_action="plugin_permission_revoke",
                        grantedBy=grantedBy, value=value)
            return dict(removed, changed=True)

    def dropPlugin(self, pluginId: str, grantedBy: str = "") -> int:
        """卸载插件时连授予与挂载授权一起摘掉：留下的孤儿记录会让同名插件重装时
        「白捡」上次的能力与上次放开的 HTTP 面。"""
        self._requireWritable()
        with self._lock:
            existing = self._grants.pop(pluginId, None)
            hadMount = self._mounts.pop(pluginId, None) is not None
            if not existing and not hadMount:
                return 0
            self._save()
        for value in sorted(existing or {}):
            self._audit(grantedBy, "plugin_permission_dropped", pluginId,
                        {"dropped": value, "kind": surfaceKind(value)})
        if hadMount:
            self._audit(grantedBy, "plugin_routes_unauthorized", pluginId,
                        {"routes": [], "why": "插件已卸载"})
        return len(existing or {})

    def _write(self, pluginId, perPlugin, *, record_action, grantedBy, value) -> None:
        """先落盘、再审计；审计写不进去就回滚——「改了却没记」比「没改」更危险。"""
        previous = self._grants.get(pluginId)
        if perPlugin:
            self._grants[pluginId] = perPlugin
        else:
            self._grants.pop(pluginId, None)
        try:
            self._save()
        except OSError as exc:
            self._restore(pluginId, previous)
            raise PluginError("grants_store_unwritable", "%s: %s" % (self._path, exc))
        if not self._audit(grantedBy, record_action, pluginId,
                           {"permission": value, "kind": surfaceKind(value)}):
            self._restore(pluginId, previous)
            self._save()
            raise PluginError("audit_write_failed",
                              "审计写失败，授予/撤销已回滚（权限变更必须可追溯到人）")

    def _restore(self, pluginId, previous) -> None:
        if previous is None:
            self._grants.pop(pluginId, None)
        else:
            self._grants[pluginId] = previous

    @staticmethod
    def _audit(grantedBy, action, pluginId, details) -> bool:
        try:
            return bool(log_audit(AuditEventType.PERMISSION_CHANGE, AuditSeverity.HIGH,
                                  user_id=grantedBy or "", action=action, details=details,
                                  resource_type="plugin", resource_id=pluginId))
        except Exception as exc:  # noqa: BLE001 - 审计面异常＝写不进去，交给调用方按失败处理
            logger.error("插件权限审计写入异常（%s）：%s", action, exc)
            return False


def _now() -> float:
    return time.time()


# ── 单例（AGENTS.md §3：DCL + RLock 由 lazySingleton 提供）──

_permissionStore: typing.Optional[PluginPermissionStore] = None


@lazySingleton("_permissionStore")
def getPermissionStore(path: typing.Optional[str] = None) -> PluginPermissionStore:
    """全局授权存储；测试与隔离环境可显式传 path。"""
    return PluginPermissionStore(path=path)


def resetPermissionStore() -> None:
    """丢掉缓存，让下一个调用方按当前数据根重建（跨用例不串授予）。"""
    global _permissionStore
    _permissionStore = None


def permissionIsGranted(pluginId: str, permission: typing.Any) -> bool:
    """框架中介点用的判定（`BasePlugin` 走这一扇，不各自摸文件）。"""
    return getPermissionStore().isGranted(pluginId, permission)


__all__ = [
    "STORE_VERSION",
    "RETIRED_PERMISSION_VALUES",
    "PluginPermissionStore",
    "FrameworkSurfaceSpec",
    "FRAMEWORK_SURFACE_MODEL",
    "capabilityKeys",
    "frameworkSurfaces",
    "grantCandidates",
    "surfaceKind",
    "permissionValue",
    "getPermissionStore",
    "resetPermissionStore",
    "permissionIsGranted",
]
