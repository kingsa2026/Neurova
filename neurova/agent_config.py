"""
Agent Config Manager - Agent 配置管理器
管理多个 Agent 的配置信息，包括列表、单个 Agent 配置等
"""

import datetime
import json
import logging
from pathlib import Path
import threading
import typing
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

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
        self._config_dir = config_dir or Path("data/agents")
        self._config_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置文件路径
        self._agents_file = self._config_dir / "agents.json"
        self._souls_dir = self._config_dir / "souls"
        self._models_file = self._config_dir / "models.json"
        
        # 确保目录存在
        self._souls_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化文件
        self._init_files()
        
        # 加载数据
        self._agents: Dict[str, Dict[str, Any]] = self._load_agents()
        self._models: List[Dict[str, Any]] = self._load_models()
        
        logger.info(f"AgentConfigManager 初始化完成，配置目录: {self._config_dir}")
    
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
                {"id": "claude", "name": "Claude", "provider": "anthropic", "model": "claude-3-sonnet"}
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
                with open(self._agents_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载 Agent 配置失败: {e}")
        
        return {}
    
    def _load_models(self) -> List[Dict[str, Any]]:
        """
        加载模型配置
        
        Returns:
            模型配置列表
        """
        try:
            if self._models_file.exists():
                with open(self._models_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载模型配置失败: {e}")
        
        return []
    
    def _save_agents_list(self, agents: Dict[str, Dict[str, Any]]) -> None:
        """
        保存 Agent 配置
        
        Args:
            agents: Agent 配置字典
        """
        try:
            with open(self._agents_file, 'w', encoding='utf-8') as f:
                json.dump(agents, f, ensure_ascii=False, indent=2)
            logger.debug("Agent 配置已保存")
        except Exception as e:
            logger.error(f"保存 Agent 配置失败: {e}")
    
    def _save_models(self, models: List[Dict[str, Any]]) -> None:
        """
        保存模型配置
        
        Args:
            models: 模型配置列表
        """
        try:
            with open(self._models_file, 'w', encoding='utf-8') as f:
                json.dump(models, f, ensure_ascii=False, indent=2)
            logger.debug("模型配置已保存")
        except Exception as e:
            logger.error(f"保存模型配置失败: {e}")
    
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
                    "last_active": config.get("last_active", "")
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
    
    def create_agent(self, agent_id: str, name: str, description: str = "",
                    config: Dict[str, Any] = None) -> bool:
        """
        创建 Agent
        
        Args:
            agent_id: Agent ID
            name: Agent 名称
            description: 描述
            config: 配置
            
        Returns:
            是否创建成功
        """
        with self._lock:
            if agent_id in self._agents:
                logger.warning(f"Agent 已存在: {agent_id}")
                return False
            
            # 创建 Agent 配置
            agent_config = {
                "id": agent_id,
                "name": name,
                "description": description,
                "created_at": datetime.datetime.now().isoformat(),
                "last_active": datetime.datetime.now().isoformat(),
                "config": config or {}
            }
            
            self._agents[agent_id] = agent_config
            self._save_agents_list(self._agents)
            
            # 创建灵魂文件目录
            soul_dir = self._souls_dir / agent_id
            soul_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"创建 Agent: {agent_id} - {name}")
            return True
    
    def update_agent(self, agent_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新 Agent
        
        Args:
            agent_id: Agent ID
            updates: 更新内容
            
        Returns:
            是否更新成功
        """
        with self._lock:
            if agent_id not in self._agents:
                logger.warning(f"Agent 不存在: {agent_id}")
                return False
            
            # 更新配置
            agent_config = self._agents[agent_id]
            agent_config.update(updates)
            agent_config["last_active"] = datetime.datetime.now().isoformat()
            
            self._save_agents_list(self._agents)
            
            logger.info(f"更新 Agent: {agent_id}")
            return True
    
    def delete_agent(self, agent_id: str) -> bool:
        """
        删除 Agent
        
        Args:
            agent_id: Agent ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if agent_id not in self._agents:
                logger.warning(f"Agent 不存在: {agent_id}")
                return False
            
            # 删除配置
            del self._agents[agent_id]
            self._save_agents_list(self._agents)
            
            # 删除灵魂文件目录
            soul_dir = self._souls_dir / agent_id
            if soul_dir.exists():
                import shutil
                shutil.rmtree(soul_dir)
            
            logger.info(f"删除 Agent: {agent_id}")
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
            soul_file = self._souls_dir / agent_id / "soul.json"
            
            if not soul_file.exists():
                return None
            
            try:
                with open(soul_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载 Agent 灵魂配置失败: {e}")
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
            soul_file = self._souls_dir / agent_id / "soul.json"
            
            try:
                # 确保目录存在
                soul_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(soul_file, 'w', encoding='utf-8') as f:
                    json.dump(soul, f, ensure_ascii=False, indent=2)
                
                logger.info(f"保存 Agent 灵魂配置: {agent_id}")
                return True
            except Exception as e:
                logger.error(f"保存 Agent 灵魂配置失败: {e}")
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
            是否添加成功
        """
        with self._lock:
            # 检查是否已存在
            existing = self.get_model(model.get("id"))
            if existing:
                logger.warning(f"模型已存在: {model.get('id')}")
                return False
            
            self._models.append(model)
            self._save_models(self._models)
            
            logger.info(f"添加模型: {model.get('id')}")
            return True
    
    def update_model(self, model_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新模型
        
        Args:
            model_id: 模型 ID
            updates: 更新内容
            
        Returns:
            是否更新成功
        """
        with self._lock:
            for i, model in enumerate(self._models):
                if model.get("id") == model_id:
                    self._models[i].update(updates)
                    self._save_models(self._models)
                    
                    logger.info(f"更新模型: {model_id}")
                    return True
            
            logger.warning(f"模型不存在: {model_id}")
            return False
    
    def delete_model(self, model_id: str) -> bool:
        """
        删除模型
        
        Args:
            model_id: 模型 ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            for i, model in enumerate(self._models):
                if model.get("id") == model_id:
                    del self._models[i]
                    self._save_models(self._models)
                    
                    logger.info(f"删除模型: {model_id}")
                    return True
            
            logger.warning(f"模型不存在: {model_id}")
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