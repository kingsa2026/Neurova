"""
Browser Manager 集成测试

测试 browser-skill 整合到 computer_use 能力后的新功能
"""
import pytest
import asyncio
import os
import tempfile
import yaml
from pathlib import Path

# 添加项目根目录到 Python 路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.computer_use.browser_manager import BrowserManager, get_browser_manager


class TestBrowserManagerConfig:
    """测试 BrowserManager 配置加载"""
    
    def test_load_config_from_yaml(self, tmp_path):
        """测试从 YAML 文件加载配置"""
        # 准备配置文件
        config_content = {
            "routing": {
                "timeout": 30,
                "rules": [
                    {
                        "pattern": "localhost|127\\.0\\.0\\.1",
                        "backend": "agent-browser",
                        "reason": "loopback address"
                    }
                ]
            },
            "backends": {
                "playwright": {
                    "type": "local",
                    "headless": True
                },
                "scrapling-stealthy": {
                    "type": "local",
                    "mode": "stealth",
                    "adaptive": True
                }
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        # 测试加载配置
        manager = BrowserManager(config_path=str(config_file))
        
        # 验证配置加载成功
        assert manager._config is not None
        assert "routing" in manager._config
        assert "backends" in manager._config
        assert len(manager._config["routing"]["rules"]) == 1
    
    def test_default_config_if_no_file(self):
        """测试如果没有配置文件，使用默认配置"""
        manager = BrowserManager()
        
        # 应该有默认配置
        assert manager._config is not None
        assert "backends" in manager._config
        assert "playwright" in manager._config["backends"]


class TestBrowserManagerRouting:
    """测试 BrowserManager 路由功能"""
    
    def test_resolve_backend_with_config_rules(self, tmp_path):
        """测试根据配置规则解析后端"""
        config_content = {
            "routing": {
                "rules": [
                    {
                        "pattern": "localhost|127\\.0\\.0\\.1",
                        "backend": "agent-browser",
                        "reason": "loopback"
                    },
                    {
                        "pattern": ".*\\.cloudflare\\.com",
                        "backend": "scrapling-stealthy",
                        "reason": "Cloudflare"
                    }
                ]
            },
            "backends": {
                "agent-browser": {"type": "local"},
                "scrapling-stealthy": {"type": "local"}
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        manager = BrowserManager(config_path=str(config_file))
        
        # 测试路由规则
        assert manager._resolve_backend("http://localhost:3000") == "agent-browser"
        assert manager._resolve_backend("https://example.cloudflare.com") == "scrapling-stealthy"
        assert manager._resolve_backend("https://example.com") == "playwright"  # 默认


class TestBrowserManagerBackends:
    """测试 BrowserManager 后端支持"""
    
    def test_available_backends_from_config(self, tmp_path):
        """测试从配置中获取可用后端"""
        config_content = {
            "backends": {
                "playwright": {"type": "local"},
                "scrapling-stealthy": {"type": "local"},
                "browserbase": {"type": "cloud"}
            }
        }
        
        config_file = tmp_path / "backends.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)
        
        manager = BrowserManager(config_path=str(config_file))
        
        # 验证后端配置
        assert "playwright" in manager._backend_configs
        assert "scrapling-stealthy" in manager._backend_configs
        assert "browserbase" in manager._backend_configs


class TestBrowserManagerDialogHandling:
    """测试对话框自动处理"""
    
    def test_dialog_handler_initialization(self):
        """测试对话框处理器初始化"""
        manager = BrowserManager()
        
        # 应该有对话框处理器
        assert hasattr(manager, '_dialog_handler')
        assert manager._dialog_handler is not None


class TestBrowserManagerSnapshotCompression:
    """快照压缩面：按 19 拍板（D-7 ②）改判到 fold 契约。

    原例子喂一棵 dict 树、要求 `BrowserManager._compress_snapshot` 返回按 role 过滤后的
    列表——那个方法从未存在于 `BrowserManager`（它只在 CDP 桥里以 `(str)->str` 截断的
    形态存在，语义不同）。今天真在跑的折叠面是 `foldSnapshotTree` 单源（工单集 T-06），
    它对"超预算时留哪些行、藏了多少"已有常驻判据
    （`tests/unit/computer_use/test_snapshot_fold_replaces_chop.py`）。

    所以这里不重复那条覆盖，改钉**唯一没被守住的那件事**：压缩口径不得再长第二份。
    """

    def test_compressionHasExactlyOneOwner(self):
        from neurova.computer_use import browser_manager as bm

        assert not hasattr(bm.BrowserManager, "_compress_snapshot"), (
            "BrowserManager 上又长出第二个压缩实现——折叠口径已单源在 foldSnapshotTree，"
            "两处并存会让同一份快照在不同调用路径下给出不同形状"
        )
        assert callable(bm.foldSnapshotTree), "折叠单源不在了，上面的反证就成了空断言"

    def test_cdpBridgeTruncationIsNotTheSnapshotPath(self):
        """CDP 桥里那个 `_compress_snapshot` 是**字符串截断**，与快照折叠无关。

        留这条是把"名字像但不是同一件事"写死：下一个看到它的人可能误当压缩入口接上，
        那时快照会退回已被否证的头部硬切。
        """
        import inspect

        from neurova.computer_use.browser_manager import BrowserSupervisor

        signature = inspect.signature(BrowserSupervisor._compress_snapshot)
        params = list(signature.parameters)
        assert "max_length" in params, params
        annotations = {p.name: p.annotation for p in signature.parameters.values()}
        assert annotations.get("snapshot") is str, (
            f"它一旦被改成吃 dict 树，就成了第二份压缩口径：{annotations}")


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v"])