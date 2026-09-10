# -*- coding: utf-8 -*-
"""插件化自定义渠道注册表（B4-d，QwenPaw register_channel 对齐）。

外部/扩展代码可注册自定义渠道类型：
- ``register_channel(spec)``：声明 channel_type + 动态表单 schema
  （config_fields）+ 适配器工厂；
- ``/v1/channel-config/schemas`` 端点下发 schema（前端动态表单渲染）；
- ``channel_config._create_adapter`` 兜底前先查注册表——插件渠道与
  内置渠道走同一配置/启动链路。

注册表是进程级单例；schema 仅做形状校验（key/type 白名单），不持久化——
注册动作须在应用启动期完成（提供 start hooks 可用性）。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_FIELD_TYPES = ("string", "bool", "int", "secret")


@dataclass
class PluginChannelSpec:
    """插件渠道声明"""

    channel_type: str
    name: str
    config_fields: List[Dict[str, Any]] = field(default_factory=list)
    description: str = ""
    # 适配器工厂：接收 neurova.channels.base.ChannelConfig，返回适配器实例
    factory: Optional[Callable[[Any], Any]] = None

    def validate(self) -> None:
        if not self.channel_type or not self.channel_type.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"非法 channel_type: '{self.channel_type}'")
        for f in self.config_fields:
            if "key" not in f or f.get("type", "string") not in _FIELD_TYPES:
                raise ValueError(f"非法 config_field: {f}")


class PluginChannelRegistry:
    """插件渠道注册表（线程安全单例）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._specs: Dict[str, PluginChannelSpec] = {}

    def register(self, spec: PluginChannelSpec, *, replace: bool = False) -> None:
        spec.validate()
        with self._lock:
            if spec.channel_type in self._specs and not replace:
                raise ValueError(f"渠道类型已注册: {spec.channel_type}（replace=True 覆盖）")
            self._specs[spec.channel_type] = spec
        logger.info("插件渠道已注册: %s (%s)", spec.channel_type, spec.name)

    def unregister(self, channel_type: str) -> bool:
        with self._lock:
            return self._specs.pop(channel_type, None) is not None

    def get(self, channel_type: str) -> Optional[PluginChannelSpec]:
        with self._lock:
            return self._specs.get(channel_type)

    def list(self) -> List[PluginChannelSpec]:
        with self._lock:
            return list(self._specs.values())

    def schemas(self) -> List[Dict[str, Any]]:
        """动态表单 schema（/channels/schemas 下发形态）。"""
        out = []
        with self._lock:
            specs = list(self._specs.values())
        for spec in specs:
            out.append({
                "channel_type": spec.channel_type,
                "name": spec.name,
                "description": spec.description,
                "config_fields": [
                    {
                        "key": f.get("key"),
                        "label": f.get("label", f.get("key")),
                        "type": f.get("type", "string"),
                        "required": bool(f.get("required", False)),
                        "default": f.get("default"),
                        "placeholder": f.get("placeholder", ""),
                    }
                    for f in spec.config_fields
                ],
            })
        return out

    def create_adapter(self, channel_type: str, config: Any) -> Optional[Any]:
        """构造插件渠道适配器；未注册返回 None（调用方走原有兜底）。"""
        spec = self.get(channel_type)
        if spec is None or spec.factory is None:
            return None
        return spec.factory(config)


_registry: Optional[PluginChannelRegistry] = None
_registry_lock = threading.Lock()


def get_plugin_channel_registry() -> PluginChannelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = PluginChannelRegistry()
    return _registry


def reset_plugin_channel_registry() -> None:
    global _registry
    with _registry_lock:
        _registry = None
