"""AIGC 生成器 facade（批次0：渠道/画布/REST 统一入口）。

真实协议实现单源 = ``protocols.py``；本包 re-export：
- ``base``：GeneratorType / GenerationConfig / GenerationResult / BaseGenerator
- ``manager``：GeneratorManager / GeneratorResult / get_generator_manager
- ``runtime``：ProtocolGenerator / 凭据与落盘（单源搬移）。

历史背景：包级零导出曾使全部渠道 ``from neurova.llm.generators import ...``
恒 ImportError（IM 渠道 AIGC 命令全灭）；六个虚构端点的 BaseGenerator 实现
（text_to_image 等，文档判定假 API 路径、从未真实产出）已于批次0删除。
旧 bytes 工厂（``LegacyBytesAdapter``/``get_image_generator``/``get_video_generator``，
只服务 wechat_ai/feishu_ai 旧契约）已随那两个死码文件于 2026-11-14 退役。
"""

from neurova.llm.generators.base import (
    BaseGenerator,
    GenerationConfig,
    GenerationResult,
    GeneratorType,
)
from neurova.llm.generators.manager import (
    GeneratorManager,
    GeneratorResult,
    get_generator_manager,
    reset_generator_manager,
)
from neurova.llm.generators.runtime import (
    GENERATION_OUTPUT_DIR,
    GenerationCredsError,
    ProtocolGenerator,
    persist_media,
    resolve_generation_creds,
    safe_task_name,
)

__all__ = [
    "BaseGenerator",
    "GenerationConfig",
    "GenerationResult",
    "GeneratorType",
    "GeneratorManager",
    "GeneratorResult",
    "GenerationCredsError",
    "ProtocolGenerator",
    "get_generator_manager",
    "reset_generator_manager",
    "resolve_generation_creds",
    "persist_media",
    "safe_task_name",
    "GENERATION_OUTPUT_DIR",
]
