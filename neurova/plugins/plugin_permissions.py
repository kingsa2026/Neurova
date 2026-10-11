from __future__ import annotations

"""插件权限的逐项确认：模型单点 + 授予存储 + 审计（用户 2026-10-11 裁「做插件体系并接线」，台账 §6-155）。

## 为什么是「逐项」而不是「整体信任」

`PluginPermission` 八项是作者 originally 设计的封闭词表，P1 之前**全仓没有任何一处消费它**——
声明了也不等于有，没声明也不等于没有，它只是清单里的一段装饰。P2 把它变成有效力的东西，
效力来自三条都能被读出来的规则：

1. **授予只允许授予清单里声明过的权限**（防「先授予、后声明」这条越权路径）；
2. **声明 ⊆ 已确认**才允许把路由挂进运行中的 app（聚合门，见 `plugin_route_mount.py`）；
3. **`execute:commands` / `admin` 本批不开放授予**——声明了这两项的插件永远挂不上路由。

## 三档，按「框架有没有真实中介点」分，不按「听起来危不危险」分

这点必须写明白，否则本模块会被读成沙箱：**动态装载本身就是把整个进程的权限交给插件**
（`exec_module` 里它可以自己 `import pathlib` / `socket` / `subprocess`）。所以：

- `framework_enforced`——框架确实拦得住：事件总线只经 `BasePlugin.subscribe/unsubscribe/publish_event`
  走，未授予即当场拒。
- `disclosed_only`——框架拦不住，授予动作的真实含义是「这份声明经人看过并签了字」，
  外加它会触发聚合挂载门（声明未确认 ⇒ 不开 HTTP 面）与审计留痕。**不是隔离**。
- `never_grantable`——本批不给授予入口；它的作用是让「要命令执行 / 要管理员」这类插件
  停在外露 HTTP 面之外，而不是一句空警告。

任何把 `disclosed_only` 写成"已限制"、把本模块写成"沙箱"的表述都是假的，
`docs/01-architecture/plugin-architecture-design.md` 里那句「路径沙箱」的同批改名实见台账。
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
from neurova.plugins.plugin_manifest import PluginPermission
from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

logger = get_logger(__name__)

#: 存储格式版本——读到不认识的版本不当成「空」（那会把已确认的记录无声抹掉）。
STORE_VERSION = 1


class PermissionTier(str, Enum):
    """权限档位：框架对它有多大的真实控制力。"""

    FRAMEWORK_ENFORCED = "framework_enforced"
    DISCLOSED_ONLY = "disclosed_only"
    NEVER_GRANTABLE = "never_grantable"


@dataclass(frozen=True)
class PermissionSpec:
    """一项权限的口径：授予后放行什么、由谁强制、强制点在哪。"""

    permission: PluginPermission
    tier: PermissionTier
    unlocks: str
    enforcedAt: typing.Optional[str] = None


def _spec(permission, tier, unlocks, enforcedAt=None) -> PermissionSpec:
    return PermissionSpec(permission=permission, tier=tier, unlocks=unlocks, enforcedAt=enforcedAt)


#: 八项权限的唯一口径表。新增枚举成员却不加表项 ⇒ 闭集判据当场红
#: （`tests/unit/plugins/test_pluginPermissionGate.py`）。
PERMISSION_MODEL: typing.Dict[PluginPermission, PermissionSpec] = {
    PluginPermission.READ_EVENTS: _spec(
        PluginPermission.READ_EVENTS, PermissionTier.FRAMEWORK_ENFORCED,
        "经事件总线订阅/退订他方事件",
        enforcedAt="neurova.plugins.base_plugin:BasePlugin.subscribe"),
    PluginPermission.EMIT_EVENTS: _spec(
        PluginPermission.EMIT_EVENTS, PermissionTier.FRAMEWORK_ENFORCED,
        "经事件总线向他方投递事件",
        enforcedAt="neurova.plugins.base_plugin:BasePlugin.publish_event"),
    PluginPermission.HTTP_REQUEST: _spec(
        PluginPermission.HTTP_REQUEST, PermissionTier.DISCLOSED_ONLY,
        "披露「会发起 HTTP 请求」；拦不住（装载即进程内任意代码），但会挡住未确认的插件挂路由"),
    PluginPermission.READ_FILES: _spec(
        PluginPermission.READ_FILES, PermissionTier.DISCLOSED_ONLY,
        "披露「会读数据根之外的文件」；同上，是披露与聚合门，不是隔离"),
    PluginPermission.WRITE_FILES: _spec(
        PluginPermission.WRITE_FILES, PermissionTier.DISCLOSED_ONLY,
        "披露「会写文件」；同上"),
    PluginPermission.NETWORK_ACCESS: _spec(
        PluginPermission.NETWORK_ACCESS, PermissionTier.DISCLOSED_ONLY,
        "披露「有出站网络访问」；同上"),
    PluginPermission.EXECUTE_COMMANDS: _spec(
        PluginPermission.EXECUTE_COMMANDS, PermissionTier.NEVER_GRANTABLE,
        "本批不开放授予：要命令执行的插件只能装载，不能对外挂 HTTP 面"),
    PluginPermission.ADMIN: _spec(
        PluginPermission.ADMIN, PermissionTier.NEVER_GRANTABLE,
        "本批不开放授予：要管理员面的插件同样被聚合门挡在路由之外"),
}


def permissionSpec(permission: typing.Any) -> PermissionSpec:
    """把字符串或枚举收成表项；收不成即 `unknown_permission`（封闭集合外没有默认值）。"""
    resolved = permissionValue(permission)
    return PERMISSION_MODEL[resolved]


def permissionValue(permission: typing.Any) -> PluginPermission:
    if isinstance(permission, PluginPermission):
        return permission
    try:
        return PluginPermission(str(permission))
    except ValueError:
        raise PluginError("unknown_permission",
                          "不是已登记的权限项：%r（可用项：%s）"
                          % (permission, ", ".join(p.value for p in PluginPermission)))


def grantablePermissions() -> typing.List[str]:
    """本批可授予的权限值（供管理面列候选，不让 UI 自己抄一份枚举）。"""
    return [p.value for p, s in PERMISSION_MODEL.items()
            if s.tier is not PermissionTier.NEVER_GRANTABLE]


def _declaredFromPluginManager(pluginId: str) -> typing.List[str]:
    """默认声明面：清单里写了什么就是什么（经 `PluginManager` 的 manifest 读面，不另开解析）。"""
    from neurova.plugins.plugin_manager import get_plugin_manager

    raw = get_plugin_manager().manifestDict(pluginId) or {}
    return [_normalizedValue(x) for x in (raw.get("required_permissions") or [])]


def _normalizedValue(permission: typing.Any) -> str:
    return permission if isinstance(permission, str) else str(permission.value)


class PluginPermissionStore:
    """「哪个插件的哪一项权限经人确认过」的存储。

    落盘是必须的：P1 之后的装载记录本就只在内存里（重启由插件根重新发现），
    而**授予不是可以重新发现的东西**——它是人的决定。内存字典意味着每次重启
    管理面都要重新点一遍，人于是会闭眼点，那正是要防的失效形态。
    """

    def __init__(self, path: typing.Optional[str] = None,
                 declaredProvider: typing.Optional[typing.Callable[[str], typing.Sequence[str]]] = None):
        self._path = str(path or dataPath("plugins", "permissions.json"))
        self._declared = declaredProvider or _declaredFromPluginManager
        self._lock = threading.RLock()
        self._grants: typing.Dict[str, typing.Dict[str, dict]] = {}
        self._mounts: typing.Dict[str, dict] = {}
        self._corrupt: typing.Optional[str] = None
        self._loaded = False

    @property
    def path(self) -> str:
        return self._path

    # ── 读写 ───────────────────────────────────────────

    def _load(self) -> None:
        """惰性读；坏文件记成「坏」而不是当成空。"""
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
            logger.error("插件权限授予文件读不出（%s）：%s——拒绝把它当「谁都没授予过」",
                         self._path, exc)
            return
        if not isinstance(data, dict) or data.get("version") != STORE_VERSION:
            self._corrupt = "无法识别的授予文件格式/版本：%r" % (
                data.get("version") if isinstance(data, dict) else type(data).__name__)
            logger.error("%s（%s）", self._corrupt, self._path)
            return
        grants = data.get("grants")
        if not isinstance(grants, dict):
            self._corrupt = "授予文件里的 grants 不是对象"
            return
        self._grants = {str(pid): {str(perm): dict(rec or {})
                                   for perm, rec in (per or {}).items()}
                        for pid, per in grants.items()}
        # 挂载授权与权限授予是同一类东西：都是**人的决定**，都得跨重启成立。
        # 缺省空表（旧文件没这一段＝没人授权过），不是损坏。
        mounts = data.get("mounts")
        self._mounts = {str(pid): dict(rec or {}) for pid, rec in mounts.items()} \
            if isinstance(mounts, dict) else {}

    def _requireReadable(self) -> None:
        self._load()
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

    # ── 读数 ───────────────────────────────────────────

    def isGranted(self, pluginId: str, permission: typing.Any) -> bool:
        """未授予即 False；坏文件也返回 False（**朝安全侧失败**：读不出＝没有能力，
        而改动类入口会因 `_requireReadable` 响亮地拒）。"""
        self._load()
        if self._corrupt:
            return False
        return _normalizedValue(permission) in self._grants.get(pluginId, {})

    def grantedFor(self, pluginId: str) -> typing.List[str]:
        self._load()
        if self._corrupt:
            return []
        return sorted(self._grants.get(pluginId, {}))

    def declaredFor(self, pluginId: str) -> typing.List[str]:
        return sorted({_normalizedValue(p) for p in (self._declared(pluginId) or [])})

    def pendingFor(self, pluginId: str) -> typing.List[str]:
        """声明了却还没确认的——管理面要逐插件显示的就是这一列。"""
        return sorted(set(self.declaredFor(pluginId)) - set(self.grantedFor(pluginId)))

    def orphanedFor(self, pluginId: str) -> typing.List[str]:
        """已授予但清单不再声明的（聚合门不看它，但面板要能看见——它意味着清单改过而授权没跟）。"""
        return sorted(set(self.grantedFor(pluginId)) - set(self.declaredFor(pluginId)))

    def snapshot(self) -> typing.Dict[str, Any]:
        self._load()
        return {
            "path": self._path,
            "corrupt": bool(self._corrupt),
            "corrupt_reason": self._corrupt or "",
            "grants": {pid: dict(per) for pid, per in self._grants.items()},
            "mounts": {pid: dict(rec) for pid, rec in self._mounts.items()},
        }

    # ── 挂载授权（第二次授权；与逐项权限同属「人的决定」，同库同审计）──

    def mountAuthorized(self, pluginId: str) -> bool:
        self._load()
        if self._corrupt:
            return False
        return pluginId in self._mounts

    def authorizeMount(self, pluginId: str, grantedBy: str = "",
                       routes: typing.Sequence[str] = ()) -> dict:
        """记录「这个插件的 HTTP 面经人放行」。**只在路由真的挂上之后调用**——
        授权了却没挂成，读数就谎报了一次能力放行。"""
        self._requireReadable()
        with self._lock:
            before = dict(self._mounts)
            record = {"authorized_by": grantedBy, "authorized_at": _now(),
                      "routes": sorted(routes)}
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
        self._requireReadable()
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
                raise PluginError("audit_write_failed",
                                  "撤销挂载授权的审计写失败，授权已还原")
            return dict(removed, changed=True)

    def grantedMountActor(self, pluginId: str) -> str:
        self._load()
        return (self._mounts.get(pluginId) or {}).get("authorized_by", "")


    # ── 变更 ───────────────────────────────────────────

    def grant(self, pluginId: str, permission: typing.Any, grantedBy: str = "") -> dict:
        # 可度性先判：文件读不出时，任何「这条没声明/那条已授予」的结论都不可信，
        # 必须先把坏文件顶到 caller 面前，而不是让它看起来像「谁都没声明过」。
        self._requireReadable()
        spec = permissionSpec(permission)
        if spec.tier is PermissionTier.NEVER_GRANTABLE:
            raise PluginError(
                "permission_not_grantable",
                "%s 本批不开放授予（档位 %s）：%s" % (spec.permission.value, spec.tier.value, spec.unlocks))

        declared = set(self.declaredFor(pluginId))
        if spec.permission.value not in declared:
            raise PluginError(
                "permission_not_declared",
                "插件 %s 的清单没声明 %s，不能授予——声明与授予只能同向（否则「先授予后声明」即越权入口）"
                % (pluginId, spec.permission.value))

        with self._lock:
            before = dict(self._grants.get(pluginId, {}))
            if spec.permission.value in before:
                return dict(before[spec.permission.value], changed=False)

            record = {
                "granted_by": grantedBy,
                "granted_at": _now(),
                "tier": spec.tier.value,
            }
            after = dict(before)
            after[spec.permission.value] = record
            self._write(pluginId, after, record_action="plugin_permission_grant",
                        grantedBy=grantedBy, spec=spec)
            return dict(record, changed=True)

    def revoke(self, pluginId: str, permission: typing.Any, grantedBy: str = "") -> dict:
        spec = permissionSpec(permission)
        self._requireReadable()
        with self._lock:
            before = dict(self._grants.get(pluginId, {}))
            if spec.permission.value not in before:
                raise PluginError("not_granted",
                                  "插件 %s 并没有被授予 %s——撤销一条不存在的授予不该被记成一笔"
                                  % (pluginId, spec.permission.value))
            removed = before.pop(spec.permission.value)
            self._write(pluginId, before, record_action="plugin_permission_revoke",
                        grantedBy=grantedBy, spec=spec)
            return dict(removed, changed=True)

    def dropPlugin(self, pluginId: str, grantedBy: str = "") -> int:
        """卸载插件时连授予与挂载授权一起摘掉：留下的孤儿记录会在同名插件重装时
        「白捡」上次的能力与上次放开的 HTTP 面。"""
        self._requireReadable()
        with self._lock:
            existing = self._grants.pop(pluginId, None)
            hadMount = self._mounts.pop(pluginId, None) is not None
            if not existing and not hadMount:
                return 0
            self._save()
        for value in sorted(existing or {}):
            tier = ""
            try:
                tier = PERMISSION_MODEL[PluginPermission(value)].tier.value
            except ValueError:
                tier = "stale"
            self._audit(grantedBy, "plugin_permission_dropped",
                        pluginId, {"dropped": value, "tier": tier})
        if hadMount:
            self._audit(grantedBy, "plugin_routes_unauthorized",
                        pluginId, {"routes": [], "why": "插件已卸载"})
        return len(existing or {})

    def _write(self, pluginId, perPlugin, *, record_action, grantedBy, spec) -> None:
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
                           {"permission": spec.permission.value, "tier": spec.tier.value}):
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
            return bool(log_audit(
                AuditEventType.PERMISSION_CHANGE,
                AuditSeverity.HIGH,
                user_id=grantedBy or "",
                action=action,
                details=details,
                resource_type="plugin",
                resource_id=pluginId,
            ))
        except Exception as exc:  # noqa: BLE001 - 审计面异常＝写不进去，交给调用方按失败处理
            logger.error("插件权限审计写入异常（%s）：%s", action, exc)
            return False


def _now() -> float:
    return time.time()


# ── 单例（AGENTS.md §3：DCL + RLock 由 lazySingleton 提供）──

_permissionStore: typing.Optional[PluginPermissionStore] = None


@lazySingleton("_permissionStore")
def getPermissionStore(path: typing.Optional[str] = None) -> PluginPermissionStore:
    """全局授予存储；测试与隔离环境可显式传 path。"""
    return PluginPermissionStore(path=path)


def resetPermissionStore() -> None:
    """丢掉缓存，让下一个调用方按当前数据根重建（跨用例不串授予）。"""
    global _permissionStore
    _permissionStore = None


def permissionIsGranted(pluginId: str, permission: typing.Any) -> bool:
    """框架中介点用的判定（`BasePlugin` 走这一扇，不各自摸文件）。"""
    return getPermissionStore().isGranted(pluginId, permission)


__all__ = [
    "PermissionTier",
    "PermissionSpec",
    "PERMISSION_MODEL",
    "PluginPermissionStore",
    "getPermissionStore",
    "resetPermissionStore",
    "permissionIsGranted",
    "permissionSpec",
    "permissionValue",
    "grantablePermissions",
]
