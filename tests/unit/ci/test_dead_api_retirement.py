"""无人消费且与生产契约不相容的旧入口退役判据。"""

import importlib

import pytest


@pytest.mark.parametrize(
    "moduleName,attribute",
    [
        ("neurova.core.agent_layout_migration", "ensure_agent_layout_v3"),
        ("neurova.collaboration.neurflow.external_api", "get_commerce_platform_client"),
        ("neurova.collaboration.neurflow.external_api", "reset_commerce_platform_client"),
        ("neurova.core.config", "ConfigManager"),
        ("neurova.core.config", "get_config_manager"),
        ("neurova.core.config", "reset_config_manager"),
        (
            "neurova.cognitive_layers.memory_layer.bayesian_eki",
            "EnsembleKalmanInversion",
        ),
        (
            "neurova.cognitive_layers.memory_layer.conversation_buffer",
            "MemoryWriteQueue.verify_write",
        ),
    ],
)
def testRetiredEntryPointsAreAbsent(moduleName, attribute):
    module = importlib.import_module(moduleName)
    target = module
    for part in attribute.split("."):
        target = getattr(target, part, None)
        if target is None:
            break
    assert target is None, f"旧入口 {moduleName}.{attribute} 不得复活"


@pytest.mark.parametrize(
    "moduleName",
    [
        "neurova.llm.config_resolver",
        "neurova.core.error_handler",
        "neurova.analytics.collector",
    ],
)
def testRetiredModulesAreAbsent(moduleName):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(moduleName)


def testIncompatibleRatchetSinkModuleIsRetired():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("neurova.benchmark.ratchet")
