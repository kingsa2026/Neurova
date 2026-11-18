# -*- coding: utf-8 -*-
"""插件授权文件 grants 内层形态校验（fullrepo 审计 2026-11-18 D 组）。

红灯依据：`PluginPermissionStore._load` 只校验 grants 外层是对象，内层
（每插件一行）非 dict 时在 comprehension 里直接 AttributeError 崩——
而本模块自己的纪律是「坏文件不静默，读侧朝安全侧失败（=未授予）」，
即应记 `_corrupt` 并保持空授予，而不是让读侧炸掉。
"""
import json

from neurova.plugins.plugin_permissions import PluginPermissionStore


def _store_with(tmp_path, payload) -> PluginPermissionStore:
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return PluginPermissionStore(path=str(p))


def test_inner_non_dict_grants_marked_corrupt_not_crash(tmp_path):
    store = _store_with(tmp_path, {"version": 2, "grants": {"pid": "not-a-dict"}, "mounts": {}})
    store._load()
    assert store._corrupt, "内层非对象应记 corrupt 标（点名成因），而不是崩在读侧"
    assert store._grants == {}, "corrupt 时朝安全侧失败：不当作任何授予存在"


def test_valid_inner_shape_still_loads(tmp_path):
    """对照：合法内层形态照常装载（防修成全拒）。"""
    store = _store_with(tmp_path, {
        "version": 2,
        "grants": {"pid": {"network": {"granted": True, "by": "admin", "at": 1}}},
        "mounts": {},
    })
    store._load()
    assert store._corrupt is None
    assert store._grants.get("pid", {}).get("network", {}).get("granted") is True
