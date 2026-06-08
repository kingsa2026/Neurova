"""
RSI 集成管理器

协调 RSI 与四大闭环系统的交互
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParameterInfo:
    """参数信息"""
    name: str
    current_value: Any
    description: str
    system: str


class RSIIntegrationManager:
    """RSI 集成管理器 - 协调 RSI 与四大闭环的交互"""
    
    # 四大闭环系统的可优化参数定义
    OPTIMIZABLE_PARAMETERS = {
        'sleep': [
            {'name': 'base_decay_rate', 'description': '基础衰减率'},
            {'name': 'similarity_threshold', 'description': '相似度阈值'},
            {'name': 'merge_threshold', 'description': '合并阈值'},
        ],
        'emotion': [
            {'name': 'emotional_protection_threshold', 'description': '情感保护阈值'},
            {'name': 'emotional_protection_factor', 'description': '情感保护因子'},
        ],
        'experience': [
            {'name': 'crystallize_min_observations', 'description': '最小观察次数'},
            {'name': 'crystallize_min_success_rate', 'description': '最小成功率'},
            {'name': 'pattern_min_support', 'description': '模式最小支持度'},
        ],
        'tool_memory': [
            {'name': 'success_bonus', 'description': '成功奖励'},
            {'name': 'failure_penalty', 'description': '失败惩罚'},
            {'name': 'decay_rate', 'description': '衰减率'},
            {'name': 'muscle_memory_threshold', 'description': '肌肉记忆阈值'},
        ],
    }
    
    def __init__(self, 
                 sleep_system: Any,
                 emotion_system: Any,
                 experience_system: Any,
                 tool_memory_system: Any):
        """
        初始化 RSI 集成管理器
        
        Args:
            sleep_system: 睡眠闭环系统
            emotion_system: 情感闭环系统
            experience_system: 经验闭环系统
            tool_memory_system: 工具记忆闭环系统
        """
        self.sleep_system = sleep_system
        self.emotion_system = emotion_system
        self.experience_system = experience_system
        self.tool_memory_system = tool_memory_system
        
        # 系统名称到系统对象的映射
        self._systems = {
            'sleep': sleep_system,
            'emotion': emotion_system,
            'experience': experience_system,
            'tool_memory': tool_memory_system,
        }
        
        logger.info("RSIIntegrationManager initialized")
    
    def get_optimizable_parameters(self) -> Dict[str, List[ParameterInfo]]:
        """
        获取四大闭环系统中可被 RSI 优化的参数
        
        Returns:
            Dict[str, List[ParameterInfo]]: 各系统的可优化参数列表
        """
        result = {}
        
        for system_name, params_def in self.OPTIMIZABLE_PARAMETERS.items():
            system = self._systems[system_name]
            params = []
            
            for param_def in params_def:
                param_name = param_def['name']
                current_value = getattr(system, param_name, None)
                
                params.append(ParameterInfo(
                    name=param_name,
                    current_value=current_value,
                    description=param_def['description'],
                    system=system_name,
                ))
            
            result[system_name] = params
        
        return result
    
    def collect_feedback_signals(self) -> Dict[str, Any]:
        """
        从四大闭环系统收集反馈信号
        
        Returns:
            Dict[str, Any]: 各系统的反馈信号
        """
        signals = {}
        
        for system_name, system in self._systems.items():
            try:
                if hasattr(system, 'get_feedback'):
                    signals[system_name] = system.get_feedback()
                else:
                    signals[system_name] = {}
            except Exception as e:
                logger.error(f"Failed to collect feedback from {system_name}: {e}")
                signals[system_name] = {'error': str(e)}
        
        return signals
    
    def apply_optimization(self, parameter_path: str, new_value: Any) -> bool:
        """
        应用优化到指定参数
        
        Args:
            parameter_path: 参数路径，格式为 "system.parameter_name"
            new_value: 新的参数值
            
        Returns:
            bool: 是否成功应用
        """
        try:
            # 解析参数路径
            parts = parameter_path.split('.')
            if len(parts) != 2:
                logger.warning(f"Invalid parameter path: {parameter_path}")
                return False
            
            system_name, param_name = parts
            
            # 检查系统是否存在
            if system_name not in self._systems:
                logger.warning(f"Unknown system: {system_name}")
                return False
            
            # 检查参数是否可优化
            system_params = self.OPTIMIZABLE_PARAMETERS.get(system_name, [])
            param_names = [p['name'] for p in system_params]
            
            if param_name not in param_names:
                logger.warning(f"Parameter {param_name} not optimizable in {system_name}")
                return False
            
            # 应用优化
            system = self._systems[system_name]
            if hasattr(system, param_name):
                setattr(system, param_name, new_value)
                logger.info(f"Applied optimization: {parameter_path} = {new_value}")
                return True
            else:
                logger.warning(f"System {system_name} does not have parameter {param_name}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to apply optimization: {e}")
            return False
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        获取四大闭环系统的状态
        
        Returns:
            Dict[str, Any]: 各系统的运行状态
        """
        status = {}
        
        for system_name, system in self._systems.items():
            try:
                system_status = {'status': 'active'}
                
                if hasattr(system, 'get_status'):
                    system_status.update(system.get_status())
                
                status[system_name] = system_status
                
            except Exception as e:
                logger.error(f"Failed to get status from {system_name}: {e}")
                status[system_name] = {'status': 'error', 'error': str(e)}
        
        return status


def create_rsi_integration_manager(
    sleep_system: Any,
    emotion_system: Any,
    experience_system: Any,
    tool_memory_system: Any
) -> RSIIntegrationManager:
    """
    创建 RSI 集成管理器实例
    
    Args:
        sleep_system: 睡眠闭环系统
        emotion_system: 情感闭环系统
        experience_system: 经验闭环系统
        tool_memory_system: 工具记忆闭环系统
        
    Returns:
        RSIIntegrationManager: RSI 集成管理器实例
    """
    return RSIIntegrationManager(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
    )