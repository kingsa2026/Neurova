"""
Neurova Provider Registry
提供商注册表 - 统一管理所有 LLM 适配器
"""

from typing import Dict, Optional, List, Type
from neurova.core.logger import get_logger
from neurova.llm.interfaces.provider_interface import (
    LLMAbstractProvider,
    ProviderConfig,
    ProviderType,
)
from neurova.llm.adapters.openai_adapter import OpenAIAdapter

logger = get_logger(__name__)


class ProviderRegistry:
    """
    Registry for LLM providers
    
    Manages provider registration, discovery, and instantiation
    """
    
    _instance = None
    _lock = __import__('threading').RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Registered providers
        self._providers: Dict[str, Type[LLMAbstractProvider]] = {
            ProviderType.OPENAI: OpenAIAdapter,
        }
        
        # Active instances
        self._instances: Dict[str, LLMAbstractProvider] = {}
        
        logger.info("ProviderRegistry initialized")
        self._initialized = True
    
    def register_provider(
        self,
        provider_type: ProviderType,
        provider_class: Type[LLMAbstractProvider],
    ) -> None:
        """Register a new provider type"""
        with self._lock:
            self._providers[provider_type] = provider_class
            logger.info(f"Registered provider: {provider_type.value}")
    
    def create_instance(
        self,
        provider_id: str,
        provider_type: ProviderType,
        config: ProviderConfig,
    ) -> LLMAbstractProvider:
        """Create provider instance"""
        with self._lock:
            if provider_type not in self._providers:
                raise ValueError(f"Provider type '{provider_type.value}' not registered")
            
            provider_class = self._providers[provider_type]
            instance = provider_class(config)
            
            key = f"{provider_id}:{config.model_name}"
            self._instances[key] = instance
            
            logger.info(
                f"Created {provider_type.value} instance: "
                f"{key} (model={config.model_name})"
            )
            
            return instance
    
    def get_instance(self, provider_id: str, model_name: str) -> LLMAbstractProvider:
        """Get existing provider instance"""
        key = f"{provider_id}:{model_name}"
        
        with self._lock:
            if key not in self._instances:
                raise KeyError(f"Provider instance not found: {key}")
            
            return self._instances[key]
    
    def list_available_providers(self) -> List[Dict]:
        """List all available provider types"""
        with self._lock:
            return [
                {
                    "type": pt.value,
                    "registered": True,
                    "class": self._providers[pt].__name__,
                }
                for pt in ProviderType
            ]
    
    def list_active_instances(self) -> List[Dict]:
        """List all active provider instances"""
        with self._lock:
            return [
                {
                    "key": key,
                    "provider": instance.provider_type.value,
                    "model": instance.config.model_name,
                    "stats": instance.get_stats(),
                }
                for key, instance in self._instances.items()
            ]
    
    def remove_instance(self, provider_id: str, model_name: str) -> None:
        """Remove provider instance"""
        key = f"{provider_id}:{model_name}"
        
        with self._lock:
            if key in self._instances:
                del self._instances[key]
                logger.info(f"Removed provider instance: {key}")


# Global instance management
_registry_instance: Optional[ProviderRegistry] = None
_registry_lock = __import__('threading').Lock()


def get_provider_registry() -> ProviderRegistry:
    """Get global ProviderRegistry instance"""
    global _registry_instance
    
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = ProviderRegistry()
    
    return _registry_instance


def reset_provider_registry() -> None:
    """Reset ProviderRegistry instance (for testing)"""
    global _registry_instance
    _registry_instance = None
