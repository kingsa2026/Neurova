from __future__ import annotations

"""插件体系的失败成因单点：`PluginError`。

原先它定义在 `plugin_manager.py` 里，而 P2 之后需要点名成因的不止装载一处
（权限授予 `plugin_permissions.py`、路由挂载 `plugin_route_mount.py`）。留在 manager 里
会让后两者反向 import 装载器——一个「成因」被绑在「其中一份实现」上，正是本仓反复收口的形态
（教义第 6 条）。所以成因搬到自己一份，`plugin_manager` 仍 re-export，
既有 `from neurova.plugins.plugin_manager import PluginError` 的调用面一字不改。

`reason` 是封闭集合，端点按它映射 HTTP 语义（见 `api/endpoints/plugin.py` 的
`_REASON_TO_STATUS`）；新增成因必须同时补那一行映射，否则当场红
（漏映射比错映射更难发现）。
"""


class PluginError(Exception):
    """插件操作失败——**成因是结构化字段，不被折成一个布尔**。

    原实现每条路径都是 `except Exception: return False`：调用方拿到 False 却无从知道
    是"根外路径""缺 manifest""依赖不满足"还是"构造报 TypeError"，而端点那侧只能把
    这个 False 统一画成"失败"（§6-126 那一族：把不同的故障折成同一个结论）。
    `reason` 是封闭集合，端点按它映射 HTTP 语义（见 `api/endpoints/plugin.py`）。
    布尔门面 `install_plugin` / `load_plugin` 保留给批量入口与既有调用方，
    它们只是本异常的一层薄壳（同一实现，不是第二份口径，教义第 6 条）。
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__("[%s] %s" % (reason, detail))
