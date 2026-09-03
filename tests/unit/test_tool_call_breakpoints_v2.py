"""
TDD 测试:工具调用链路遗漏断点修复(第二批)

调查发现 5 个 HIGH 断点 + 1 MID 断点:
- 断点 V2-1 (HIGH): SkillRegistry 类 A 无 skills property,orchestrator.py:731
  `skill_registry.skills.items()` 抛 AttributeError,Skill 工具永远不暴露给 LLM。
- 断点 V2-2 (HIGH): tool_router.py:200 `isinstance(skills, dict)` 不匹配
  list_skills() 返回的 list,Skill 工具第二条发现路径也断。
- 断点 V2-3 (HIGH): chat.py:133, 225 强制 `{"history": []}`(与已修 console.py
  POST /chat 同根,但 chat.py 两处未修)。
- 断点 V2-4 (HIGH): console.py:445 WebSocket 强制 `metadata={"history": []}`
  (与已修 POST /chat 同根,但 ws 路径未修)。
- 断点 V2-5 (HIGH): chat_pipeline.py:647 调用 `register_skill(manifest, path)`
  但类 A SkillRegistry 只有 `register(skill)`,合成工具永远无法注册。
- 断点 V2-6 (MID): chat_pipeline.py:890 流式分支 `gen = self.loop.predict_step(...)`
  缺 await,对 coroutine 迭代会抛 TypeError。
"""
import importlib.util
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# 加载被 neurova.skill_system 包遮蔽的 neurova/skill_system.py 单文件
# (与 skill_system/__init__.py 的 _get_skill_module 加载方式一致)
_SPEC = importlib.util.spec_from_file_location(
    "neurova_skill_system_standalone_for_test",
    "e:/项目/Neurova/neurova/skill_system.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
SkillRegistry = _MOD.SkillRegistry
Skill = _MOD.Skill


# ──────────────────────────────────────────────────────────────────
# 断点 V2-1: SkillRegistry 必须有 skills property
# ──────────────────────────────────────────────────────────────────

class TestSkillRegistrySkillsProperty:
    """V2-1: SkillRegistry 必须暴露 skills property。

    orchestrator.py:731 和 base.py:241 都用 `skill_registry.skills.items()`,
    但类 A SkillRegistry 只有私有 _skills 字段。访问 .skills 抛 AttributeError,
    被 except Exception 静默吞掉,Skill 工具(MemorySkill/WebSearchSkill/等)
    永远不进入 LLM tools 列表,这是"聊天对话触发工具"失败的核心根因。
    """

    def test_skills_property_returns_dict(self):
        """SkillRegistry.skills 必须返回 _skills 字典。"""
        sr = SkillRegistry()
        # 没有 .skills 时抛 AttributeError
        assert hasattr(sr, "skills"), (
            "SkillRegistry 必须暴露 skills property,否则 orchestrator.py:731 "
            "`self.skill_registry.skills.items()` 会抛 AttributeError。"
        )
        # 应该返回字典类型(可能空)
        assert isinstance(sr.skills, dict), (
            "SkillRegistry.skills 必须返回 dict,实际:" + type(sr.skills).__name__
        )

    def test_skills_property_reflects_registered_skills(self):
        """注册后 skills 字典应包含已注册的 Skill。"""
        sr = SkillRegistry()
        # 创建一个简单的 Skill
        s = Skill(name="test_v2_skill", description="测试 skill")
        sr.register(s)

        assert "test_v2_skill" in sr.skills, (
            "注册后 SkillRegistry.skills 应包含该 skill,实际:" + str(list(sr.skills.keys()))
        )
        assert sr.skills["test_v2_skill"] is s


# ──────────────────────────────────────────────────────────────────
# 断点 V2-2: ToolRouter._discover_skill_tools 必须支持 list_skills() 返回 list
# ──────────────────────────────────────────────────────────────────

class TestToolRouterListSkillsSupport:
    """V2-2: ToolRouter._discover_skill_tools 必须支持 list 类型。

    类 A SkillRegistry.list_skills() 返回 List[SkillInfo](列表),
    但 tool_router.py:200 `isinstance(skills, dict)` 检查为 False,
    整个 for 循环跳过,返回空 dict。Skill 工具第二条发现路径也断。
    """

    def test_discover_skill_tools_handles_list(self):
        """_discover_skill_tools 在 list_skills() 返回 list 时也能发现工具。"""
        from neurova.tool_layers.tool_router import ToolRouter

        # 构造 mock skill_manager,list_skills 返回 list
        sm = MagicMock()
        # 不暴露 .skills 属性,强制走 list_skills() 路径
        # 删除 .skills 属性让 getattr 返回 None
        sm.skills = None
        # list_skills() 返回 list,每个元素有 name/description/parameters 属性
        skill1 = MagicMock()
        skill1.name = "weather_skill"
        skill1.description = "查询天气"
        skill1.parameters = {"type": "object"}
        sm.list_skills = MagicMock(return_value=[skill1])

        tr = ToolRouter.__new__(ToolRouter)
        tr._skill_manager = sm
        tr._builtin_tools = set()

        tools = tr._discover_skill_tools()

        assert "weather_skill" in tools, (
            "_discover_skill_tools 在 list_skills() 返回 list 时也应发现工具,实际:"
            + str(list(tools.keys()))
        )


# ──────────────────────────────────────────────────────────────────
# 断点 V2-3: chat.py 不应强制传空历史(POST /chat 和 /chat/stream)
# ──────────────────────────────────────────────────────────────────

class TestChatEndpointNotForceEmptyHistory:
    """V2-3: chat.py 两处不应强制 `{"history": []}`。

    与已修的 console.py POST /chat(断点 B-2)同根,但 chat.py 的 POST /api/v1/chat
    和 /api/v1/chat/stream 两处都未修。

    修复:删除强制注入,改为 `body.metadata or {}`,让 chat_pipeline 自行从 session
    恢复历史。
    """

    def test_chat_endpoint_no_force_empty_history(self):
        """chat.py 不应出现 `{"history": []}` 强制注入(非注释代码)。"""
        import re
        src = open(
            "e:/项目/Neurova/neurova/api/endpoints/chat.py",
            encoding="utf-8",
        ).read()
        # 去除注释后再检查,避免修复说明注释中的字符串触发假阳性
        src_no_comments = re.sub(r'#.*', '', src)
        # 修复后非注释代码不应再出现强制空历史注入
        assert '"history": []' not in src_no_comments, (
            "chat.py 非注释代码仍存在 `{'history': []}` 强制注入,"
            "LLM 缺对话上下文,工具参数指代不清。"
            "应改为 call_metadata = body.metadata or {}。"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 V2-4: console.py WebSocket 不应强制传空历史
# ──────────────────────────────────────────────────────────────────

class TestConsoleWebSocketNotForceEmptyHistory:
    """V2-4: console.py WebSocket 路径不应强制 `metadata={"history": []}`。

    POST /chat 已修(断点 B-2),但 WebSocket handler(line 445)未修。
    """

    def test_console_ws_no_force_empty_history(self):
        """console.py WebSocket 不应传 metadata={"history": []}(非注释代码)。"""
        import re
        src = open(
            "e:/项目/Neurova/neurova/api/endpoints/console.py",
            encoding="utf-8",
        ).read()
        # 去除注释后再检查,避免修复说明注释中的字符串触发假阳性
        src_no_comments = re.sub(r'#.*', '', src)
        # 修复后非注释代码不应再出现 WebSocket 强制空历史
        assert 'metadata={"history": []}' not in src_no_comments, (
            "console.py WebSocket 路径非注释代码仍强制传 metadata={'history': []},"
            "LLM 缺对话上下文。应删除此 metadata 注入。"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 V2-5: SkillRegistry 必须支持 register_skill(manifest, path) 兼容 API
# ──────────────────────────────────────────────────────────────────

class TestSkillRegistryRegisterSkillCompat:
    """V2-5: SkillRegistry 必须支持 register_skill(manifest, path)。

    chat_pipeline.py:647 调用 `skill_registry.register_skill(manifest, sentinel_path)`,
    但类 A SkillRegistry 只有 `register(skill)`(单参数),调用抛 AttributeError,
    被 _check_nl_synthesis 的 except 吞掉,合成工具永远无法注册。
    """

    def test_register_skill_method_exists(self):
        """SkillRegistry 必须有 register_skill 方法。"""
        sr = SkillRegistry()
        assert hasattr(sr, "register_skill"), (
            "SkillRegistry 必须暴露 register_skill(manifest, path) 方法,"
            "否则 chat_pipeline.py:647 调用会抛 AttributeError。"
        )
        assert callable(sr.register_skill), "register_skill 必须可调用"

    def test_register_skill_does_not_raise_on_manifest(self):
        """register_skill 接受 manifest 参数不抛异常。"""
        sr = SkillRegistry()
        # manifest 是任意对象,只要 register_skill 不抛 AttributeError 即可
        # 这里用 MagicMock 模拟 manifest,内部应委托到 register(skill)
        try:
            sr.register_skill(MagicMock(), Path("<synthesized>"))
        except AttributeError as ae:
            pytest.fail(f"register_skill 抛 AttributeError: {ae}")
        except Exception:
            # 其他异常(如 manifest 类型不匹配)可接受,只要不是 AttributeError
            pass


# ──────────────────────────────────────────────────────────────────
# 断点 V2-6: chat_pipeline.py 流式分支 predict_step 必须加 await
# ──────────────────────────────────────────────────────────────────

class TestChatPipelineStreamAwait:
    """V2-6: chat_pipeline.py:890 流式分支 predict_step 必须加 await。

    `gen = self.loop.predict_step(...)` 返回 coroutine(因为 predict_step 是 async),
    `async for event in gen:` 对 coroutine 迭代会抛
    `TypeError: 'coroutine' object is not async iterable`。
    """

    def test_stream_branch_has_await(self):
        """chat_pipeline.py 流式分支 predict_step 调用必须有 await。

        精确匹配 `gen = await self.loop.predict_step(...stream=True)`,
        排除非流式分支 `response = await self.loop.predict_step(...stream=False)` 的假阳性。
        """
        import re
        src = open(
            "e:/项目/Neurova/neurova/agent/chat_pipeline.py",
            encoding="utf-8",
        ).read()
        # 流式分支必须是 `gen = await ...predict_step(...stream=True)`
        pattern = r"gen\s*=\s*await\s+self\.loop\.predict_step\s*\([^)]*stream\s*=\s*True"
        assert re.search(pattern, src), (
            "chat_pipeline.py 流式分支 `gen = self.loop.predict_step(...stream=True)` "
            "必须加 await,否则对 coroutine 迭代会抛 TypeError: "
            "'coroutine' object is not async iterable"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 V2-7: chat_pipeline.py:647 调用 register_skill 不应抛 AttributeError
# ──────────────────────────────────────────────────────────────────

class TestChatPipelineRegisterSkillNoAttributeError:
    """V2-7: chat_pipeline.py:647 调用 register_skill 不应抛 AttributeError。

    这是 V2-5 的运行时验证:即使源码扫描通过,也要验证 chat_pipeline.py 调用
    register_skill 时不会因 SkillRegistry API 不匹配而失败。
    """

    def test_chat_pipeline_calls_register_skill_compatible(self):
        """chat_pipeline.py 调用 register_skill 与 SkillRegistry API 兼容。"""
        sr = SkillRegistry()
        # 模拟 chat_pipeline.py:647 的调用
        manifest = MagicMock()
        manifest.id = "test_manifest_id"
        sentinel_path = Path("<synthesized>") / "test_manifest_id"

        # 不应抛 AttributeError(API 不匹配)
        try:
            sr.register_skill(manifest, sentinel_path)
        except AttributeError as ae:
            pytest.fail(
                f"chat_pipeline.py:647 调用 register_skill(manifest, path) 抛 "
                f"AttributeError: {ae}"
            )
        except Exception:
            # 其他异常(如 manifest 不是 Skill)可接受
            pass
