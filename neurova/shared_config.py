"""
Shared Config Manager - 共享配置管理器

管理多个 Agent 共用的配置，包括：
- LLM Providers（LLM 提供商配置）
- MCP Servers（MCP 服务器配置）
- 其他共享基础设施配置

配置结构（参考 Neurova CogArch 1.0.0 文档 2.5 节）：
```yaml
shared:
  llm_providers:
    - id: "openai"
      name: "OpenAI"
      api_key: "sk-xxx"
      base_url: "https://api.openai.com/v1"
      models: ["gpt-3.5-turbo", "gpt-4"]
  mcp_servers:
    - id: "filesystem"
      name: "文件系统"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
```
"""

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class SharedConfigManager:
    """
    共享配置管理器

    管理多个 Agent 共用的配置。
    """

    def __init__(self, config_path: Path = None):
        """
        初始化共享配置管理器

        Args:
            config_path: 配置文件路径
        """
        self._lock = threading.RLock()

        # 配置文件路径（兼容 str / Path 入参，统一归一化为 Path）
        self._config_path = Path(config_path) if config_path else Path("data/shared_config.json")
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载配置
        self._config = self._load_config()

        logger.info("SharedConfigManager 初始化完成，配置文件: %s", self._config_path)

    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置

        Returns:
            配置字典
        """
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("加载配置文件失败: %s", e)

        # 创建默认配置
        default_config = self._get_default_config()
        self._create_default_config(default_config)
        return default_config

    def _create_default_config(self, config: Dict[str, Any]) -> None:
        """
        创建默认配置文件

        Args:
            config: 配置字典
        """
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.debug("创建默认配置文件")
        except Exception as e:
            logger.error("创建默认配置文件失败: %s", e)

    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置

        Returns:
            默认配置字典
        """
        return {
            "version": "1.0.0",
            "last_updated": datetime.datetime.now().isoformat(),
            "llm_providers": [
                {
                    "id": "openai",
                    "name": "OpenAI",
                    "api_key": "",
                    "base_url": "https://api.openai.com/v1",
                    "models": ["gpt-3.5-turbo", "gpt-4"],
                    "enabled": True,
                    "priority": 1,
                },
                {
                    "id": "anthropic",
                    "name": "Anthropic",
                    "api_key": "",
                    "base_url": "https://api.anthropic.com",
                    "models": ["claude-3-sonnet", "claude-3-opus"],
                    "enabled": True,
                    "priority": 2,
                },
                {
                    "id": "local",
                    "name": "本地模型",
                    "api_key": "",
                    "base_url": "http://localhost:11434",
                    "models": ["llama2", "mistral"],
                    "enabled": False,
                    "priority": 3,
                },
            ],
            "mcp_servers": [
                {
                    "id": "filesystem",
                    "name": "文件系统",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "enabled": True,
                    "description": "文件系统访问",
                }
            ],
            "default_provider": "openai",
            "default_model": "gpt-3.5-turbo",
            "settings": {
                "max_concurrent_requests": 10,
                "request_timeout": 30,
                "retry_attempts": 3,
                "log_level": "INFO",
            },
        }

    def _save_config(self) -> None:
        """保存配置"""
        try:
            self._config["last_updated"] = datetime.datetime.now().isoformat()

            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)

            logger.debug("配置已保存")
        except Exception as e:
            logger.error("保存配置失败: %s", e)

    def list_llm_providers(self) -> List[Dict[str, Any]]:
        """
        列出所有 LLM 提供商

        Returns:
            提供商列表
        """
        with self._lock:
            return self._config.get("llm_providers", [])

    def get_llm_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 LLM 提供商

        Args:
            provider_id: 提供商ID

        Returns:
            提供商信息，不存在返回 None
        """
        with self._lock:
            providers = self._config.get("llm_providers", [])
            for provider in providers:
                if provider.get("id") == provider_id:
                    return provider
            return None

    def add_llm_provider(self, provider: Dict[str, Any]) -> bool:
        """
        添加 LLM 提供商

        Args:
            provider: 提供商信息

        Returns:
            是否添加成功
        """
        with self._lock:
            providers = self._config.get("llm_providers", [])

            # 检查是否已存在
            for existing in providers:
                if existing.get("id") == provider.get("id"):
                    logger.warning("提供商已存在: %s", provider.get('id'))
                    return False

            providers.append(provider)
            self._config["llm_providers"] = providers
            self._save_config()

            logger.info("添加 LLM 提供商: %s", provider.get('id'))
            return True

    def update_llm_provider(self, provider_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新 LLM 提供商

        Args:
            provider_id: 提供商ID
            updates: 更新内容

        Returns:
            是否更新成功
        """
        with self._lock:
            providers = self._config.get("llm_providers", [])

            for i, provider in enumerate(providers):
                if provider.get("id") == provider_id:
                    providers[i].update(updates)
                    self._config["llm_providers"] = providers
                    self._save_config()

                    logger.info("更新 LLM 提供商: %s", provider_id)
                    return True

            logger.warning("提供商不存在: %s", provider_id)
            return False

    def remove_llm_provider(self, provider_id: str) -> bool:
        """
        移除 LLM 提供商

        Args:
            provider_id: 提供商ID

        Returns:
            是否移除成功
        """
        with self._lock:
            providers = self._config.get("llm_providers", [])

            for i, provider in enumerate(providers):
                if provider.get("id") == provider_id:
                    del providers[i]
                    self._config["llm_providers"] = providers
                    self._save_config()

                    logger.info("移除 LLM 提供商: %s", provider_id)
                    return True

            logger.warning("提供商不存在: %s", provider_id)
            return False

    def list_mcp_servers(self) -> List[Dict[str, Any]]:
        """
        列出所有 MCP 服务器

        Returns:
            服务器列表
        """
        with self._lock:
            return self._config.get("mcp_servers", [])

    def get_mcp_server(self, server_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 MCP 服务器

        Args:
            server_id: 服务器ID

        Returns:
            服务器信息，不存在返回 None
        """
        with self._lock:
            servers = self._config.get("mcp_servers", [])
            for server in servers:
                if server.get("id") == server_id:
                    return server
            return None

    def add_mcp_server(self, server: Dict[str, Any]) -> bool:
        """
        添加 MCP 服务器

        Args:
            server: 服务器信息

        Returns:
            是否添加成功（配置非法时拒绝并返回 False）
        """
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        try:
            server = validate_mcp_server_config(server)
        except ValueError as e:
            logger.warning("拒绝非法 MCP 服务器配置: %s", e)
            return False

        with self._lock:
            servers = self._config.get("mcp_servers", [])

            # 检查是否已存在
            for existing in servers:
                if existing.get("id") == server.get("id"):
                    logger.warning("服务器已存在: %s", server.get('id'))
                    return False

            servers.append(server)
            self._config["mcp_servers"] = servers
            self._save_config()

            logger.info("添加 MCP 服务器: %s", server.get('id'))
            return True

    def update_mcp_server(self, server_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新 MCP 服务器

        Args:
            server_id: 服务器ID
            updates: 更新内容

        Returns:
            是否更新成功（合并后配置非法时拒绝并返回 False）
        """
        from neurova.tool_layers.mcp_config import validate_mcp_server_config

        with self._lock:
            servers = self._config.get("mcp_servers", [])

            for i, server in enumerate(servers):
                if server.get("id") == server_id:
                    merged = {**server, **updates}
                    try:
                        validated = validate_mcp_server_config(merged)
                    except ValueError as e:
                        logger.warning("拒绝非法 MCP 服务器更新: %s", e)
                        return False
                    servers[i] = validated
                    self._config["mcp_servers"] = servers
                    self._save_config()

                    logger.info("更新 MCP 服务器: %s", server_id)
                    return True

            logger.warning("服务器不存在: %s", server_id)
            return False

    def remove_mcp_server(self, server_id: str) -> bool:
        """
        移除 MCP 服务器

        Args:
            server_id: 服务器ID

        Returns:
            是否移除成功
        """
        with self._lock:
            servers = self._config.get("mcp_servers", [])

            for i, server in enumerate(servers):
                if server.get("id") == server_id:
                    del servers[i]
                    self._config["mcp_servers"] = servers
                    self._save_config()

                    logger.info("移除 MCP 服务器: %s", server_id)
                    return True

            logger.warning("服务器不存在: %s", server_id)
            return False

    def export_config(self, export_path: Path = None) -> bool:
        """
        导出配置

        Args:
            export_path: 导出路径

        Returns:
            是否导出成功
        """
        with self._lock:
            try:
                export_path = export_path or Path("data/shared_config_export.json")

                with open(export_path, "w", encoding="utf-8") as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=2)

                logger.info("配置已导出到: %s", export_path)
                return True
            except Exception as e:
                logger.error("导出配置失败: %s", e)
                return False

    def import_config(self, import_path: Path) -> bool:
        """
        导入配置

        Args:
            import_path: 导入路径

        Returns:
            是否导入成功
        """
        with self._lock:
            try:
                if not import_path.exists():
                    logger.error("导入文件不存在: %s", import_path)
                    return False

                with open(import_path, "r", encoding="utf-8") as f:
                    imported_config = json.load(f)

                # 验证配置结构
                if "llm_providers" not in imported_config or "mcp_servers" not in imported_config:
                    logger.error("导入的配置格式不正确")
                    return False

                # 更新配置
                self._config.update(imported_config)
                self._save_config()

                logger.info("配置已导入: %s", import_path)
                return True
            except Exception as e:
                logger.error("导入配置失败: %s", e)
                return False

    def get_provider_for_agent(self, agent_id: str = None) -> Dict[str, Any]:
        """
        获取 Agent 使用的提供商

        Args:
            agent_id: Agent ID

        Returns:
            提供商信息
        """
        with self._lock:
            # 获取默认提供商
            default_provider_id = self._config.get("default_provider", "openai")
            default_model = self._config.get("default_model", "gpt-3.5-turbo")

            provider = self.get_llm_provider(default_provider_id)

            if provider is None:
                # 如果默认提供商不存在，返回第一个可用的
                providers = self.list_llm_providers()
                for p in providers:
                    if p.get("enabled", False):
                        provider = p
                        break

            return {"provider": provider, "model": default_model, "agent_id": agent_id}

    def get_settings(self) -> Dict[str, Any]:
        """
        获取全局设置

        Returns:
            设置字典
        """
        with self._lock:
            return self._config.get("settings", {})

    def update_settings(self, settings: Dict[str, Any]) -> bool:
        """
        更新全局设置

        Args:
            settings: 设置字典

        Returns:
            是否更新成功
        """
        with self._lock:
            try:
                current_settings = self._config.get("settings", {})
                current_settings.update(settings)
                self._config["settings"] = current_settings
                self._save_config()

                logger.info("全局设置已更新")
                return True
            except Exception as e:
                logger.error("更新全局设置失败: %s", e)
                return False


# 全局实例管理
_shared_config_manager: Optional[SharedConfigManager] = None
_manager_lock = threading.Lock()


def get_shared_config_manager(config_path: Path = None) -> SharedConfigManager:
    """
    获取共享配置管理器单例

    Args:
        config_path: 配置文件路径

    Returns:
        SharedConfigManager 实例
    """
    global _shared_config_manager
    if _shared_config_manager is None:
        with _manager_lock:
            if _shared_config_manager is None:
                _shared_config_manager = SharedConfigManager(config_path)
    return _shared_config_manager


def reset_shared_config_manager() -> None:
    """
    重置共享配置管理器单例（主要用于测试）
    """
    global _shared_config_manager
    with _manager_lock:
        _shared_config_manager = None
