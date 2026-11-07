# -*- coding: utf-8 -*-
"""自动路由收口批（红灯）：能力映射单源 + 文本猜类型退役。

复核实状（本批自己命中）：

- 「RequestType → 必需能力」在 `neurova/llm/llm_router.py` 里有**两份逐字相同的定义**：
  `LLMRouter._matches_request_type` 里内联的 `capability_requirements` dict（真被消费）与
  模块级 `REQUEST_TYPE_CAPABILITIES`（第 500 行起，**全仓零消费者**——grep 只命中定义本身）。
  这是教义第 6 条的标准形态：不新造第三份、也不把有信息的那份删掉，而是**收口成一处并被读**。
- `detect_request_type`（按用户文本猜请求类型）在生产上**没有任何调用者**：
  `neurova/router.py:28` 只 import 不用，`neurova/llm/__init__.py` 只是再导出。而它猜的东西
  已有更强的事实源在位——网页/渠道附件的 `file_type`（服务端判定）与 `voice_ingress` 的
  入站语音类型；模型覆盖那一侧由 `llm_routing_overlay.resolve_vision_capable_model` 按
  **本轮真往请求里塞了什么载荷**决定（`chat_pipeline._maybe_activate_vision_routing` 读
  `ctx._pending_vision_parts`，不读用户文本）。
  ⇒ 按点单口径「不得与现有功能重复，若有重复则取长补短后退役」：本批退役它，
  连同它反解的那三条中文占位串（与 `agent_core` 写侧互抄的第二事实源）。
  取长补短的"长"留在 overlay/attachments 这两处显式来源上；文本关键词这条脆弱来源不取。
"""

from __future__ import annotations

import ast
import pathlib

from neurova.llm.llm_router import (
    LLMRouter,
    ModelCapability,
    RequestType,
)
from tests.ast_scan import parseSource

ROUTER_SRC = pathlib.Path("neurova/llm/llm_router.py")


def _assignedNames(node) -> list:
    """取赋值目标名：`Assign` 与带注解的 `AnnAssign` 两种写法都要认。

    只认 `Assign` 会把 `NAME: Dict[...] = {...}` 这种带注解的单源定义量成 0 命中，
    判据于是"红得莫名其妙"——本仓登记过的取错 AST 节点形态，正反两个方向都会咬人。
    """
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def test_capabilityMappingIsDefinedOnceAndActuallyRead():
    """映射只留一处定义，且被 `_matches_request_type` 读——补齐"只写不读"的断点。"""
    tree = parseSource(ROUTER_SRC.read_text(encoding="utf-8"), str(ROUTER_SRC))

    inlineDicts = [
        node for node in ast.walk(tree) if "capability_requirements" in _assignedNames(node)
    ]
    assert not inlineDicts, f"方法里还内联着第二份映射（{len(inlineDicts)} 处）"

    moduleConsts = [
        node for node in ast.walk(tree) if "REQUEST_TYPE_CAPABILITIES" in _assignedNames(node)
    ]
    assert len(moduleConsts) == 1, f"模块级映射定义应恰一处，实量 {len(moduleConsts)}"

    readerBody = next(
        f for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef) and f.name == "_matches_request_type"
    )
    names = {n.id for n in ast.walk(readerBody) if isinstance(n, ast.Name)}
    assert "REQUEST_TYPE_CAPABILITIES" in names, "唯一那份没被消费方读取"


def test_matchingStillFiltersByTheSingleMapping():
    """行为：收口后按能力筛的读数不变（不靠"文件里写着"当作已存在）。"""
    router = LLMRouter()
    assert router._matches_request_type(
        RequestType.TEXT_TO_IMAGE, [ModelCapability.IMAGE_GENERATION]
    )
    assert not router._matches_request_type(
        RequestType.TEXT_TO_IMAGE, [ModelCapability.TEXT]
    )
    assert router._matches_request_type(
        RequestType.IMAGE_UNDERSTANDING, [ModelCapability.VISION]
    )
    assert not router._matches_request_type(
        RequestType.VIDEO_UNDERSTANDING, [ModelCapability.VISION]
    )


def test_textBasedRequestTypeGuesserRetiredEverywhere():
    """退役要退净：函数、再导出、router 的无用 import、钉它的测试，一处不剩。"""
    assert not hasattr(
        __import__("neurova.llm.llm_router", fromlist=["x"]), "detect_request_type"
    ), "detect_request_type 还在"

    for rel in ("neurova/router.py", "neurova/llm/__init__.py", "tests/unit/llm/test_llm_router.py"):
        text = pathlib.Path(rel).read_text(encoding="utf-8", errors="replace")
        assert "detect_request_type" not in text, f"{rel} 仍引用已退役符号"


def test_mediaTurnRoutingCapabilityComesFromPayloadNotFromText():
    """反向守卫（今天就该绿）：媒体轮换模型的依据是本轮真塞进去的载荷，不是猜文本。"""
    tree = parseSource(pathlib.Path("neurova/agent/chat_pipeline.py").read_text(encoding="utf-8"),
                       "neurova/agent/chat_pipeline.py")
    body = next(
        f for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef) and f.name == "_maybe_activate_vision_routing"
    )
    consts = {
        n.value for n in ast.walk(body) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "_pending_vision_parts" in consts, "能力来源不是本轮载荷"
    haystack = ast.dump(body)
    for word in ("图片", "视频", "音频"):
        assert f"'{word}'" not in haystack, f"路由判定里混进了文本关键词 '{word}'"
