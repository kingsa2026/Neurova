"""T4a NeuHebb/Evocate 全链退役守卫

拍板（2026-11-18，DCPM 启发 T4）：NeuHebb/Evocate 全链自装配起就是断链空转——
生产装配缺 llm_fn 注入（agent_core 旧 766-775 段）→ forge 恒回 "I don't know"
→ 被无效答案拦截 → 每轮 0 产物；检索侧嵌入恒零向量。功能与既有记忆召回+
结晶经验重叠，按教义第 7 条（同功能先比后合，其余退役）退役删净。

本守卫钉住"退役不可复活"：
- 四个模块文件不再存在；
- 三条管线面（agent_core / chat_pipeline / post_chat_pipeline）不再有
  evocate/hebb 装配点、注入步与生成步。
"""

import importlib.util
from pathlib import Path

import pytest

RETIRED_MODULES = (
    "neurova.cognitive_layers.memory_layer.neuHebb_manager",
    "neurova.cognitive_layers.memory_layer.neuHebb_forge",
    "neurova.cognitive_layers.memory_layer.neuHebb_curator",
    "neurova.cognitive_layers.memory_layer.neurova_hebb",
)

FACE_SOURCES = (
    "neurova/agent_core.py",
    "neurova/agent/chat_pipeline.py",
    "neurova/post_chat_pipeline.py",
)


@pytest.mark.parametrize("module", RETIRED_MODULES)
def test_retired_module_no_longer_exists(module):
    assert importlib.util.find_spec(module) is None, (
        "%s 应已退役删净—— revival 须先改本守卫并重走拍板" % module
    )


@pytest.mark.parametrize("relpath", FACE_SOURCES)
def test_pipeline_faces_carry_no_evocode_remains(relpath):
    """三条管线面不得残留**复活码痕**（导入/类名/装配属性/步骤名/API 名）。

    不查裸词 "hebb"——退役说明注释里提到被退役对象名是正当的；
    守卫钉的是"能跑起来的复活"。
    """
    repo_root = Path(__file__).resolve().parents[3]
    source = (repo_root / relpath).read_text(encoding="utf-8").lower()
    revival_tokens = (
        "neuhebbmanager",
        "neuhebbconfig",
        "neuhebb_manager",
        "neurova_hebb",
        "neuhebb_available",
        "_step_evocate",
        "evocate_generation",
        "evocate_injection",
        "add_neurova_hebb",
        "search_neurova_hebbs",
    )
    for token in revival_tokens:
        assert token not in source, (
            "%s 仍残留复活码痕 %r——NeuHebb 已整体退役，不得复活" % (relpath, token)
        )


def test_vector_store_has_no_hebb_index():
    repo_root = Path(__file__).resolve().parents[3]
    source = (
        repo_root / "neurova/cognitive_layers/memory_layer/unified_vector_store.py"
    ).read_text(encoding="utf-8").lower()
    assert "neurova_hebb" not in source, "unified_vector_store 仍残留 Hebb 向量索引死面"
