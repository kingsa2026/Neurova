# -*- coding: utf-8 -*-
"""权限词汇必须只有一处定义（用户 2026-10-12 裁「甲 · 彻底合一」，台账 §6-159，设计稿 §3/§5）。

§6-155 立了八项 `PluginPermission`，而 `neurova/skills/permissions.py` 里那套七类能力键
（`tools|network|file|model|system|node|storage`）才是**真在执行**的那份——
`tool_executor.py:1033` 把声明装进作用域、`:1540` 处按声明拒。八项里四项（文件读／文件写／
网络／命令）是同一件事的更弱写法，还被我写成 `disclosed_only`＝"拦不住"。
根因不是判断错，是**比对象比窄了**：扫重复口径时只按包名扫了 `neurova/plugins/`，
没按能力面关键词扫到 `neurova/skills/`（失效形态第 69 条）。

这一档判据钉的是收口后的四件事：

1. **能力键的词汇与校验、调用面仲裁全部单点在 skills**，插件侧只**取用**、不复制一份；
   取用必须到调用时再取（`KNOWN_CAPABILITY_KEYS` 被改，插件侧候选要跟着变——否则就是抄了一份）。
2. **插件独有的中介面只剩两档**：`read:events` / `emit:events`（事件总线，技能侧没有这个概念）。
   `http:request` 就是 `network`、`admin` 就是 `api/deps.require_role` 的角色门，两者从权限面删掉。
3. **不再有 `never_grantable` 档**：`system`/`node` 变成"可授予＋调用面真拦"。
   这不是放宽——原来是"因为我拦不住所以禁止"，现在是"拦得住所以可授"，
   而拦的那一下由 `check_tool_permission` 在工具执行咽喉处做，不是靠我写的一行注释。
4. **§6-155 聚合门的空真通过修掉**：清单**没有** `permissions` 键 ⇒ 拒挂
   （`permissions_undeclared`）；显式空 dict ⇒ 可以挂，但声明作用域里七类能力一律未开，
   调用面 fail-closed。旧语义下"没声明"＝空真过门，插件 handler 却拥有整个进程的能力。

另外钉两条纪律：安装校验**复用** `skill_install_gate.validate_permissions_for_install`
（未知能力键、白名单含未知工具、mcp.* 未声明网络 ⇒ 拒），插件侧不再自带一套校验；
旧的八项形态授予文件**不自动映射**——`execute:commands → system` 会变宽，
那是人的决定，只能响亮拒绝并要求重新逐项确认。
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from neurova.plugins.plugin_manager import PluginError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_PACKAGE = PROJECT_ROOT / "neurova" / "plugins"

#: 技能那份单点的七类能力键（本文件按"取用相等"判，不在此重述其语义）
LEGACY_EIGHT = ["read:events", "emit:events", "http:request", "read:files",
                "write:files", "execute:commands", "network:access", "admin"]


def _permissions():
    return importlib.import_module("neurova.plugins.plugin_permissions")


def _skillPermissions():
    return importlib.import_module("neurova.skills.permissions")


def _store(tmp_path, declared=None, fileName="permissions.json"):
    mod = _permissions()
    return mod.PluginPermissionStore(
        path=str(tmp_path / fileName),
        declaredProvider=lambda pid: list((declared or {}).get(pid, [])))


class TestCapabilityVocabularyIsSourcedNotCopied:
    def test_capabilityKeysEqualTheSkillSingleSource(self):
        mod, skills = _permissions(), _skillPermissions()
        assert set(mod.capabilityKeys()) == set(skills.KNOWN_CAPABILITY_KEYS), (
            "插件侧的能力键集合与 skills 那份不相等——要么抄了一份，要么漂移了")

    def test_capabilityKeysAreReadAtCallTimeNotFrozen(self):
        """变异对照：改单点那份集合，插件侧候选必须跟着变。

        没有这一格，`capabilityKeys()` 里藏一份字面量副本也一样能过上一格——
        那正是"两边都留着"最舒服的伪装形态。
        """
        mod, skills = _permissions(), _skillPermissions()
        before = set(mod.capabilityKeys())
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(skills, "KNOWN_CAPABILITY_KEYS", before | {"teleport"})
            assert "teleport" in set(mod.capabilityKeys()), (
                "单点加了键而插件侧没跟着变——它拿的是副本，不是同一份定义")

    def test_pluginPackageDoesNotDeclareItsOwnCapabilitySet(self):
        """AST 防再生：`neurova/plugins/` 里不许再出现"字面量集合的 capability 口径"。

        扫的是赋值/枚举里同时含 ≥3 个能力键字符串的字面量——那形状就是第二份定义的出生形态
        （§6-155 的八项枚举正是这么长出来的）。
        """
        skills = _skillPermissions()
        keys = set(skills.KNOWN_CAPABILITY_KEYS)
        offenders = []
        for path in sorted(PLUGIN_PACKAGE.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                literals = {n.value for n in ast.walk(node)
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
                hit = literals & keys
                if isinstance(node, (ast.Set, ast.List, ast.Tuple, ast.Dict)) and len(hit) >= 3:
                    offenders.append("%s:%s 含 %s" % (path.name, getattr(node, "lineno", "?"),
                                                      sorted(hit)))
        assert not offenders, "插件包里又长出一份能力键集合：%s" % offenders

    def test_legacyEightEnumIsGoneFromTheManifestModule(self):
        """`PluginPermission` 这个符号不得再存在（它才是"第二份定义"的载体）。"""
        manifest = importlib.import_module("neurova.plugins.plugin_manifest")
        assert not hasattr(manifest, "PluginPermission"), (
            "八项枚举还活着——收口没做完，两份词汇表仍然并存")
        with pytest.raises(ImportError):
            from neurova.plugins.plugin_manifest import PluginPermission  # noqa: F401


class TestFrameworkSurfaceIsOnlyTheEventBus:
    def test_surfacesAreExactlyReadAndEmitEvents(self):
        mod = _permissions()
        assert set(mod.frameworkSurfaces()) == {"read:events", "emit:events"}, (
            "插件独有面只该是事件总线两档")

    def test_httpRequestAndAdminAreNoLongerPermissionValues(self):
        """`http:request` 就是 `network`；`admin` 是 `api/deps.require_role` 的角色门——
        两者留在权限面里就是第三、第四份口径。"""
        mod = _permissions()
        candidates = set(mod.grantCandidates())
        assert "http:request" not in candidates
        assert "admin" not in candidates
        assert "network" in candidates

    def test_thereIsNoNeverGrantableTierAnymore(self):
        mod = _permissions()
        assert not hasattr(mod, "PermissionTier"), (
            "三档口径还留着＝`system`/`node` 仍被归到「拦不住／不许授」那一类，"
            "而收口后拦的手段是调用面仲裁，不是档位")

    def test_grantCandidatesAreTheUnionOfBothVocabularies(self):
        mod, skills = _permissions(), _skillPermissions()
        assert set(mod.grantCandidates()) == set(skills.KNOWN_CAPABILITY_KEYS) | set(mod.frameworkSurfaces())


class TestGrantFollowsDeclaration:
    def test_capabilityGrantRequiresTheManifestToDeclareIt(self, tmp_path):
        store = _store(tmp_path, {"probe": ["network"]})
        store.grant("probe", "network", grantedBy="admin-1")
        assert store.isGranted("probe", "network")

        with pytest.raises(PluginError) as caught:
            store.grant("probe", "file", grantedBy="admin-1")
        assert caught.value.reason == "permission_not_declared"

    def test_legacyValueIsNamedNotSilentlyUnknown(self, tmp_path):
        store = _store(tmp_path, {"probe": ["read:files"]})
        with pytest.raises(PluginError) as caught:
            store.grant("probe", "read:files", grantedBy="admin-1")
        assert caught.value.reason == "grants_store_legacy_format", (
            "旧八项的值必须被点名成「历史形态」，而不是混在 unknown_permission 里——"
            "运维读到 unknown 会以为是拼错，读不到「这份授权需要人重新确认」")

    def testLegacyFileIsRefusedLoudlyAndLeftIntact(self, tmp_path):
        """旧授予文件不许被读成"谁都没授予过"，也不许被就地改写。"""
        path = tmp_path / "legacy.json"
        path.write_text(json.dumps({"version": 1,
                                    "grants": {"probe": {"read:files": {"granted_by": "admin-1"}}},
                                    "mounts": {}}), encoding="utf-8")
        original = path.read_text(encoding="utf-8")
        mod = _permissions()
        reopened = mod.PluginPermissionStore(path=str(path),
                                            declaredProvider=lambda pid: ["file"])

        assert reopened.isGranted("probe", "file") is False, "读侧必须朝安全侧失败"
        with pytest.raises(PluginError) as caught:
            reopened.grant("probe", "file", grantedBy="admin-2")
        assert caught.value.reason == "grants_store_legacy_format"
        assert path.read_text(encoding="utf-8") == original, (
            "覆写旧文件＝销毁「当初确认过什么」的证据；迁移必须是人做的一次显式动作")

    def testSurfaceGrantPersistsAndIsAudited(self, tmp_path, monkeypatch):
        """事件面沿用 §6-155 的存储与审计纪律：落盘可被新实例读回；审计写不进 ⇒ 授予回滚。"""
        mod = _permissions()
        rows = []
        monkeypatch.setattr(mod, "log_audit",
                            lambda event_type, severity, **kw: rows.append((event_type.value, kw)) or True)
        store = _store(tmp_path, {"probe": ["read:events"]})

        store.grant("probe", "read:events", grantedBy="admin-1")

        assert store.isGranted("probe", "read:events")
        reopened = mod.PluginPermissionStore(path=store.path,
                                             declaredProvider=lambda pid: ["read:events"])
        assert reopened.isGranted("probe", "read:events"), "授予只在内存里＝重启即失效，面板却显示已确认"
        assert rows and rows[0][0] == "permission_change"

        monkeypatch.setattr(mod, "log_audit", lambda *a, **kw: False)
        other = _store(tmp_path, {"probe": ["emit:events"]}, fileName="probe2.json")
        with pytest.raises(PluginError) as caught:
            other.grant("probe", "emit:events", grantedBy="admin-1")

        assert caught.value.reason == "audit_write_failed"
        assert not other.isGranted("probe", "emit:events"), (
            "内存回滚了、盘上留着——重启后这条没有留痕的授予又活了")


class TestInstallUsesTheSkillGate:
    def test_unknownCapabilityKeyIsRejectedByTheSharedGate(self, tmp_path):
        """安装校验单点在 `skill_install_gate.validate_permissions_for_install`，
        插件侧不再自带一套——所以错误文案必须是那份的原文。"""
        from neurova.plugins.plugin_manager import get_plugin_manager

        root = tmp_path / "plugins"
        (root / "probe").mkdir(parents=True)
        (root / "probe" / "manifest.json").write_text(json.dumps({
            "name": "probe", "version": "1.0.0", "entry_point": "main.py",
            "permissions": {"teleport": True},
        }), encoding="utf-8")
        (root / "probe" / "main.py").write_text("MARKER = 1\n", encoding="utf-8")

        manager = get_plugin_manager(str(root))
        try:
            with pytest.raises(PluginError) as caught:
                manager.install_plugin(root / "probe")
            assert caught.value.reason == "invalid_permissions_declaration"
            assert "未知权限能力键" in caught.value.detail, (
                "错误文案不是那份单点的原文＝插件侧又写了一套校验：%s" % caught.value.detail)
        finally:
            from neurova.plugins.plugin_manager import reset_plugin_manager

            reset_plugin_manager()

    def test_managerDelegatesToTheSharedValidator(self):
        """判"复用"而不是"抄一段"：安装路径必须真的调那份函数。"""
        source = (PLUGIN_PACKAGE / "plugin_manager.py").read_text(encoding="utf-8")
        assert "validate_permissions_for_install" in source, (
            "安装路径没走 skill_install_gate 那份校验")
        permissionsSource = (PLUGIN_PACKAGE / "plugin_permissions.py").read_text(encoding="utf-8")
        assert "def _validate" not in permissionsSource and "KNOWN_CAPABILITY_KEYS" in permissionsSource
