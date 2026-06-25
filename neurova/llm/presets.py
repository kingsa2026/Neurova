"""
LLM 预设配置 - 热插拔机制
预设从 JSON 文件加载，支持运行时热重载，不再硬编码在代码中。
"""

import json
from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class ModelPreset:
    """模型预设配置"""

    name: str
    provider: str  # openai, anthropic, ollama, etc.
    model_id: str
    display_name: str = ""
    category: str = "general"  # general, code, chat, vision, etc.
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 4096
    system_prompt: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "model_id": self.model_id,
            "display_name": self.display_name or self.name,
            "category": self.category,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "extra_params": self.extra_params,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelPreset":
        return cls(
            name=data["name"],
            provider=data["provider"],
            model_id=data["model_id"],
            display_name=data.get("display_name", ""),
            category=data.get("category", "general"),
            temperature=data.get("temperature", 0.7),
            top_p=data.get("top_p", 0.9),
            max_tokens=data.get("max_tokens", 4096),
            system_prompt=data.get("system_prompt", ""),
            extra_params=data.get("extra_params", {}),
            description=data.get("description", ""),
        )


class LLMPresetRegistry:
    """
    LLM 预设注册表

    管理模型预设配置，支持从 JSON 文件加载和热重载。
    """

    def __init__(self, presets_dir: Optional[str] = None):
        """
        初始化预设注册表

        Args:
            presets_dir: 预设配置文件目录
        """
        self._presets_dir = presets_dir or self._get_presets_path()
        self._lock = threading.RLock()
        self._presets: Dict[str, ModelPreset] = {}

        # 加载预设
        self._load_presets()

    def _get_presets_path(self) -> str:
        """获取默认预设目录"""
        # 项目根目录下的 config/llm_presets
        project_root = Path(__file__).parent.parent.parent
        return str(project_root / "config" / "llm_presets")

    def _load_presets(self) -> None:
        """从目录加载所有预设文件"""
        presets_dir = Path(self._presets_dir)
        if not presets_dir.exists():
            logger.info("Presets directory not found: %s", presets_dir)
            self._export_legacy()
            return

        for f in presets_dir.glob("*.json"):
            self._load_from_file(f)

        logger.info("Loaded %s model presets", len(self._presets))

    def _load_from_file(self, filepath: Path) -> None:
        """从单个 JSON 文件加载预设"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                for item in data:
                    preset = ModelPreset.from_dict(item)
                    self._presets[preset.name] = preset
            elif isinstance(data, dict):
                if "presets" in data:
                    for item in data["presets"]:
                        preset = ModelPreset.from_dict(item)
                        self._presets[preset.name] = preset
                else:
                    preset = ModelPreset.from_dict(data)
                    self._presets[preset.name] = preset
        except Exception as e:
            logger.warning("Failed to load presets from %s: %s", filepath, e)

    def _export_legacy(self) -> None:
        """导出内置默认预设到文件"""
        defaults = [
            ModelPreset(
                name="gpt-4o",
                provider="openai",
                model_id="gpt-4o",
                category="general",
                description="OpenAI GPT-4o 多模态模型",
            ),
            ModelPreset(
                name="gpt-4o-mini",
                provider="openai",
                model_id="gpt-4o-mini",
                category="general",
                description="OpenAI GPT-4o Mini 轻量模型",
            ),
            ModelPreset(
                name="claude-3.5-sonnet",
                provider="anthropic",
                model_id="claude-3-5-sonnet-20241022",
                category="general",
                description="Anthropic Claude 3.5 Sonnet",
            ),
            ModelPreset(
                name="deepseek-v3",
                provider="openai",
                model_id="deepseek-chat",
                category="code",
                description="DeepSeek V3 代码模型",
                extra_params={"api_base": "https://api.deepseek.com/v1"},
            ),
            ModelPreset(
                name="qwen-max",
                provider="openai",
                model_id="qwen-max",
                category="general",
                description="通义千问 Max",
                extra_params={"api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
            ),
        ]

        for preset in defaults:
            self._presets[preset.name] = preset

        # 尝试保存到文件
        try:
            presets_dir = Path(self._presets_dir)
            presets_dir.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in defaults]
            with open(presets_dir / "defaults.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def save_to_file(self, filepath: Optional[str] = None) -> None:
        """保存所有预设到文件"""
        save_path = filepath or str(Path(self._presets_dir) / "presets.json")
        try:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in self._presets.values()]
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Saved %s presets to %s", len(data), save_path)
        except Exception as e:
            logger.error("Failed to save presets: %s", e)

    def reload(self) -> None:
        """热重载预设"""
        with self._lock:
            self._presets.clear()
            self._load_presets()

    def add_preset(self, preset: ModelPreset) -> None:
        """添加预设"""
        with self._lock:
            self._presets[preset.name] = preset

    def remove_preset(self, name: str) -> bool:
        """移除预设"""
        with self._lock:
            if name in self._presets:
                del self._presets[name]
                return True
            return False

    def get_preset(self, name: str) -> Optional[ModelPreset]:
        """获取预设"""
        return self._presets.get(name)

    def list_presets(self) -> List[ModelPreset]:
        """列出所有预设"""
        return list(self._presets.values())

    def list_by_category(self, category: str) -> List[ModelPreset]:
        """按分类列出预设"""
        return [p for p in self._presets.values() if p.category == category]

    def search_presets(self, query: str) -> List[ModelPreset]:
        """搜索预设"""
        query_lower = query.lower()
        return [
            p
            for p in self._presets.values()
            if query_lower in p.name.lower()
            or query_lower in p.model_id.lower()
            or query_lower in p.description.lower()
            or query_lower in p.provider.lower()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        categories = {}
        providers = {}
        for p in self._presets.values():
            categories[p.category] = categories.get(p.category, 0) + 1
            providers[p.provider] = providers.get(p.provider, 0) + 1

        return {
            "total": len(self._presets),
            "by_category": categories,
            "by_provider": providers,
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_preset_registry: Optional[LLMPresetRegistry] = None
_registry_lock = threading.Lock()


def get_preset_registry(presets_dir: Optional[str] = None) -> LLMPresetRegistry:
    """获取全局预设注册表"""
    global _preset_registry
    if _preset_registry is None:
        with _registry_lock:
            if _preset_registry is None:
                _preset_registry = LLMPresetRegistry(presets_dir=presets_dir)
    return _preset_registry


def reset_preset_registry() -> None:
    """重置全局预设注册表（用于测试）"""
    global _preset_registry
    with _registry_lock:
        _preset_registry = None
