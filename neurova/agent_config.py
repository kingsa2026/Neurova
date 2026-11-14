"""
Agent Config Manager - Agent 配置管理器
管理多个 Agent 的配置信息，包括列表、单个 Agent 配置等
"""

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import callerPath

logger = get_logger(__name__)


class AgentConfigManager:
    """
    Agent 配置管理器

    管理多个 Agent 的配置信息。
    """

    def __init__(self, config_dir: Path = None):
        """
        初始化配置管理器

        Args:
            config_dir: 配置目录路径
        """
        self._lock = threading.RLock()

        # 配置目录
        self._config_dir = callerPath(config_dir, "agents")
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # 配置文件路径
        self._agents_file = self._config_dir / "agents.json"
        self._models_file = self._config_dir / "models.json"

        # 初始化文件
        self._init_files()

        # 加载数据
        self._agents: Dict[str, Dict[str, Any]] = self._load_agents()
        self._models: List[Dict[str, Any]] = self._load_models()

        logger.info("AgentConfigManager 初始化完成，配置目录: %s", self._config_dir)

    def _init_files(self) -> None:
        """初始化配置文件"""
        # 创建 agents.json
        if not self._agents_file.exists():
            self._save_agents_list({})

        # 创建 models.json
        if not self._models_file.exists():
            default_models = [
                {"id": "default", "name": "默认模型", "provider": "openai", "model": "gpt-3.5-turbo"},
                {"id": "gpt4", "name": "GPT-4", "provider": "openai", "model": "gpt-4"},
                {"id": "claude", "name": "Claude", "provider": "anthropic", "model": "claude-3-sonnet"},
            ]
            self._save_models(default_models)

    def _load_agents(self) -> Dict[str, Dict[str, Any]]:
        """
        加载 Agent 配置

        Returns:
            Agent 配置字典
        """
        try:
            if self._agents_file.exists():
                with open(self._agents_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error("加载 Agent 配置失败: %s", e)

        return {}

    def _load_models(self) -> List[Dict[str, Any]]:
        """
        加载模型配置

        Returns:
            模型配置列表
        """
        try:
            if self._models_file.exists():
                with open(self._models_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error("加载模型配置失败: %s", e)

        return []

    def _save_agents_list(self, agents: Dict[str, Dict[str, Any]]) -> bool:
        """
        保存 Agent 配置（P2-11：tmp + os.replace 原子写）

        Args:
            agents: Agent 配置字典

        Returns:
            是否保存成功（失败记 error 日志并返回 False，不谎报成功）
        """
        tmp_file = self._agents_file.parent / (self._agents_file.name + ".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(agents, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self._agents_file)
            logger.debug("Agent 配置已保存")
            return True
        except Exception as e:
            logger.error("保存 Agent 配置失败: %s", e)
            return False
        finally:
            # 写失败/中断时清理残留 tmp，原配置文件不受影响（原子性）
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except OSError:
                pass

    def _save_models(self, models: List[Dict[str, Any]]) -> bool:
        """
        保存模型配置（P2-11：tmp + os.replace 原子写）

        Args:
            models: 模型配置列表

        Returns:
            是否保存成功（失败记 error 日志并返回 False，不谎报成功）
        """
        tmp_file = self._models_file.parent / (self._models_file.name + ".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(models, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, self._models_file)
            logger.debug("模型配置已保存")
            return True
        except Exception as e:
            logger.error("保存模型配置失败: %s", e)
            return False
        finally:
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except OSError:
                pass

    def list_agents(self) -> List[Dict[str, Any]]:
        """
        列出所有 Agent

        Returns:
            Agent 信息列表
        """
        with self._lock:
            return [
                {
                    "id": agent_id,
                    "name": config.get("name", agent_id),
                    "description": config.get("description", ""),
                    "created_at": config.get("created_at", ""),
                    "last_active": config.get("last_active", ""),
                }
                for agent_id, config in self._agents.items()
            ]

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 Agent 信息

        Args:
            agent_id: Agent ID

        Returns:
            Agent 信息，不存在返回 None
        """
        with self._lock:
            return self._agents.get(agent_id)

    def get_agent_config(self, agent_id: str, key: str = None, default: Any = None) -> Any:
        """
        获取 Agent 配置

        Args:
            agent_id: Agent ID
            key: 配置键名
            default: 默认值

        Returns:
            配置值
        """
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return default

            if key is None:
                return agent

            return agent.get(key, default)

    def create_agent(
        self,
        agent_id: str,
        name: str,
        description: str = "",
        config: Dict[str, Any] = None,
        owner_user_id: Optional[str] = None,
    ) -> bool:
        """
        创建 Agent

        Args:
            agent_id: Agent ID
            name: 名称
            description: 描述
            config: 配置
            owner_user_id: 属主用户 ID（Wave H-W0：中枢登记面带 owner，
                未启动实例的属主过滤依据）

        Returns:
            是否创建成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            if agent_id in self._agents:
                logger.warning("Agent 已存在: %s", agent_id)
                return False

            # 创建 Agent 配置
            agent_config = {
                "id": agent_id,
                "name": name,
                "description": description,
                "created_at": datetime.datetime.now().isoformat(),
                "last_active": datetime.datetime.now().isoformat(),
                "config": config or {},
            }
            if owner_user_id:
                agent_config["owner_user_id"] = str(owner_user_id)

            # P2-11：先在副本上保存，成功才应用到内存——保存失败时
            # 内存与磁盘都保持原状，不产生"内存有、盘上无"的漂移。
            trial = dict(self._agents)
            trial[agent_id] = agent_config
            if not self._save_agents_list(trial):
                return False
            self._agents = trial

            logger.info("创建 Agent: %s - %s", agent_id, name)
            return True

    def update_agent(self, agent_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新 Agent

        Args:
            agent_id: Agent ID
            updates: 更新内容

        Returns:
            是否更新成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            if agent_id not in self._agents:
                logger.warning("Agent 不存在: %s", agent_id)
                return False

            # 更新配置（P2-11：副本上保存，成功才应用内存，失败不漂移）
            agent_config = dict(self._agents[agent_id])
            agent_config.update(updates)
            agent_config["last_active"] = datetime.datetime.now().isoformat()

            trial = dict(self._agents)
            trial[agent_id] = agent_config
            if not self._save_agents_list(trial):
                return False
            self._agents = trial

            logger.info("更新 Agent: %s", agent_id)
            return True

    def delete_agent(self, agent_id: str) -> bool:
        """
        删除 Agent

        Args:
            agent_id: Agent ID

        Returns:
            是否删除成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            if agent_id not in self._agents:
                logger.warning("Agent 不存在: %s", agent_id)
                return False

            # 删除配置（P2-11：副本上保存，成功才应用内存，失败不漂移）
            trial = dict(self._agents)
            del trial[agent_id]
            if not self._save_agents_list(trial):
                return False
            self._agents = trial

            logger.info("删除 Agent: %s", agent_id)
            return True

    def get_agent_soul(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 Agent 灵魂配置

        Args:
            agent_id: Agent ID

        Returns:
            灵魂配置，不存在返回 None
        """
        with self._lock:
            from neurova.core.agent_workspaces import get_agent_soul_path

            soul_file = get_agent_soul_path(agent_id)

            if not soul_file.exists():
                return None

            try:
                with open(soul_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("加载 Agent 灵魂配置失败: %s", e)
                return None

    def save_agent_soul(self, agent_id: str, soul: Dict[str, Any]) -> bool:
        """
        保存 Agent 灵魂配置

        Args:
            agent_id: Agent ID
            soul: 灵魂配置

        Returns:
            是否保存成功
        """
        with self._lock:
            from neurova.core.agent_workspaces import get_agent_soul_path

            soul_file = get_agent_soul_path(agent_id)

            try:
                # 确保目录存在
                soul_file.parent.mkdir(parents=True, exist_ok=True)

                with open(soul_file, "w", encoding="utf-8") as f:
                    json.dump(soul, f, ensure_ascii=False, indent=2)

                logger.info("保存 Agent 灵魂配置: %s", agent_id)
                return True
            except Exception as e:
                logger.error("保存 Agent 灵魂配置失败: %s", e)
                return False

    def list_models(self) -> List[Dict[str, Any]]:
        """
        列出所有模型

        Returns:
            模型信息列表
        """
        with self._lock:
            return self._models.copy()

    def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """
        获取模型信息

        Args:
            model_id: 模型 ID

        Returns:
            模型信息，不存在返回 None
        """
        with self._lock:
            for model in self._models:
                if model.get("id") == model_id:
                    return model
            return None

    def add_model(self, model: Dict[str, Any]) -> bool:
        """
        添加模型

        Args:
            model: 模型信息

        Returns:
            是否添加成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            # 检查是否已存在
            existing = self.get_model(model.get("id"))
            if existing:
                logger.warning("模型已存在: %s", model.get('id'))
                return False

            # P2-11：副本上保存，成功才应用内存，失败不漂移
            trial = list(self._models)
            trial.append(model)
            if not self._save_models(trial):
                return False
            self._models = trial

            logger.info("添加模型: %s", model.get('id'))
            return True

    def update_model(self, model_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新模型

        Args:
            model_id: 模型 ID
            updates: 更新内容

        Returns:
            是否更新成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            for i, model in enumerate(self._models):
                if model.get("id") == model_id:
                    # P2-11：副本上保存，成功才应用内存，失败不漂移
                    updated = dict(model)
                    updated.update(updates)
                    trial = list(self._models)
                    trial[i] = updated
                    if not self._save_models(trial):
                        return False
                    self._models = trial

                    logger.info("更新模型: %s", model_id)
                    return True

            logger.warning("模型不存在: %s", model_id)
            return False

    def delete_model(self, model_id: str) -> bool:
        """
        删除模型

        Args:
            model_id: 模型 ID

        Returns:
            是否删除成功（P2-11：保存失败返回 False，不再恒 True）
        """
        with self._lock:
            for i, model in enumerate(self._models):
                if model.get("id") == model_id:
                    # P2-11：副本上保存，成功才应用内存，失败不漂移
                    trial = list(self._models)
                    del trial[i]
                    if not self._save_models(trial):
                        return False
                    self._models = trial

                    logger.info("删除模型: %s", model_id)
                    return True

            logger.warning("模型不存在: %s", model_id)
            return False


# 全局实例管理
_config_manager: Optional[AgentConfigManager] = None
_manager_lock = threading.Lock()


def get_config_manager(config_dir: Path = None) -> AgentConfigManager:
    """
    获取配置管理器单例

    Args:
        config_dir: 配置目录路径

    Returns:
        AgentConfigManager 实例
    """
    global _config_manager
    if _config_manager is None:
        with _manager_lock:
            if _config_manager is None:
                _config_manager = AgentConfigManager(config_dir)
    return _config_manager


def reset_config_manager() -> None:
    """
    重置配置管理器单例
    """
    global _config_manager
    with _manager_lock:
        _config_manager = None
