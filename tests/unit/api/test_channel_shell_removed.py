"""渠道死壳清理防复活钉（2026-09-13）。

背景：系统曾并存两套渠道代码——
- 真集 `channel_config.py`(/v1/channel-configs)：配置落盘 + `_create_adapter` 各平台分字段；
- 死壳 `channel.py`(/v1/channels)：依赖 ChannelManager 上不存在的方法（hasattr 恒假），
  GET 恒 []、POST 用请求体拼假成功、从不写配置；前端 channels.ts + AgentChannelPage
  焊死在这套假接口上（渠道 tab 永远空/保存必丢）。
AgentChannelPage 自 6 月起挂在死壳上，用户"渠道参数不对"实为双套并存的误导入口。
本轮三件套删除，本钉防复活并锁真集存活。
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]

REMOVED_PY = ROOT / "neurova" / "api" / "endpoints" / "channel.py"
REMOVED_FE = [
    # 死壳前端 API 模块永久删除；AgentChannelPage.vue 已按真集 agent 隔离语义重建
    ROOT / "NeurUI" / "src" / "api" / "modules" / "channels.ts",
]
REGISTRY = ROOT / "neurova" / "api" / "endpoints" / "__init__.py"
ROUTER = ROOT / "NeurUI" / "src" / "router" / "index.ts"


class TestDeadShellGone:
    def test_backend_module_unimportable(self):
        assert importlib.util.find_spec("neurova.api.endpoints.channel") is None
        assert not REMOVED_PY.exists()

    def test_registry_no_channel_shell_row(self):
        src = REGISTRY.read_text(encoding="utf-8")
        assert '"neurova.api.endpoints.channel"' not in src, "注册表不得再挂回 /v1/channels 死壳"
        # 活集仍在注册表
        assert '"neurova.api.endpoints.channel_config"' in src
        assert '"neurova.api.endpoints.channels"' in src

    def test_frontend_dead_api_removed_and_new_page_is_clean(self):
        # 死壳 API 模块永久删除；channels.ts 不得以任何形式复活
        for f in REMOVED_FE:
            assert not f.exists(), f"死壳前端文件复活: {f}"
        router_src = ROUTER.read_text(encoding="utf-8")
        assert "'@/api/modules/channels'" not in router_src
        # AgentChannelPage 允许以【真集 agent 隔离版】重建（2026-09-13 Phase C），
        # 但绝不得重新引用死壳 channels 模块
        page = ROOT / "NeurUI" / "src" / "pages" / "AgentChannelPage.vue"
        if page.exists():
            src = page.read_text(encoding="utf-8")
            assert "api/modules/channels'" not in src, "AgentChannelPage 复活挂死壳 /v1/channels"
            assert "channel-configs" in src, "AgentChannelPage 必须走真集 /v1/channel-configs"

    def test_channel_manager_helpers_untouched(self):
        """清理仅删假桥；真适配器管理器与运行时面完好。"""
        from neurova.channels.manager import ChannelManager
        from neurova.api.endpoints import channels, channel_config

        assert hasattr(ChannelManager, "get_instance")
        assert hasattr(channels, "router") and hasattr(channel_config, "router")
