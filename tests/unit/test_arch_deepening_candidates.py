"""
TDD 测试:架构深化候选实现验证

垂直切片顺序(风险递增):
- 候选 3: 静默 except → logger.exception(3 处)
- 候选 2: _unpack_skill helper 提取
- 候选 1: SkillRegistryProtocol 统一双实现
- 候选 4: 流式/非流式分支统一(暂不实现,需先补齐流式测试覆盖)

TDD 原则: 一次一个测试 → 一次一个实现 → 重复。
源码扫描测试用 re.sub 去除注释避免假阳性。
"""
import re
import importlib.util
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────
# 候选 3: 静默 except → logger.exception
# ──────────────────────────────────────────────────────────────────

class TestSilentExceptReplacedWithLoggerException:
    """候选 3: 关键路径 except 应使用 logger.exception 输出完整 traceback。

    根因(V2-1 教训): orchestrator.py:760 用 `logger.warning("...: %s", e)`
    只记录异常消息字符串,不记录 traceback。当 SkillRegistry.skills
    抛 AttributeError 时,日志只显示 'SkillRegistry' object has no
    attribute 'skills',无法定位具体调用栈。

    修复: 替换为 logger.exception("..."),自动输出 traceback。
    等价于 logger.error(..., exc_info=True)。

    范围:
    - orchestrator.py:725 (ToolRouter 工具加载)
    - orchestrator.py:760 (SkillRegistry 工具加载)
    - chat_pipeline.py:571 (NL 工具合成)
    - base.py:199 已使用 exc_info=True,无需改
    """

    def test_orchestrator_toolrouter_except_uses_logger_exception(self):
        """orchestrator.py 的 ToolRouter 工具加载 except 应使用 logger.exception。"""
        src = open(
            "e:/项目/Neurova/neurova/context/orchestrator.py",
            encoding="utf-8",
        ).read()
        # 去除注释避免假阳性
        src_no_comments = re.sub(r'#.*', '', src)
        # 查找 'logger.warning' + '从 ToolRouter 获取工具列表失败' 的组合
        # 修复后应改为 logger.exception
        assert not re.search(
            r'logger\.warning\s*\(\s*["\']从 ToolRouter 获取工具列表失败',
            src_no_comments
        ), (
            "orchestrator.py 的 ToolRouter except 仍用 logger.warning,"
            "应改为 logger.exception 以输出完整 traceback。"
            "logger.warning('...: %s', e) 只记录消息字符串,"
            "logger.exception('...') 自动输出 traceback。"
        )
        # 应存在 logger.exception 调用
        assert re.search(
            r'logger\.exception\s*\(\s*["\']从 ToolRouter 获取工具列表失败',
            src_no_comments
        ), "修复后应存在 logger.exception('从 ToolRouter 获取工具列表失败...') 调用"

    def test_orchestrator_skillregistry_except_uses_logger_exception(self):
        """orchestrator.py 的 SkillRegistry 工具加载 except 应使用 logger.exception。"""
        src = open(
            "e:/项目/Neurova/neurova/context/orchestrator.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        assert not re.search(
            r'logger\.warning\s*\(\s*["\']从 SkillRegistry 获取工具失败',
            src_no_comments
        ), (
            "orchestrator.py 的 SkillRegistry except 仍用 logger.warning,"
            "应改为 logger.exception。这是 V2-1 静默失败的直接根因——"
            "AttributeError 的 traceback 被丢失,导致调试困难。"
        )
        assert re.search(
            r'logger\.exception\s*\(\s*["\']从 SkillRegistry 获取工具失败',
            src_no_comments
        )

    def test_chat_pipeline_nl_synthesis_except_uses_logger_exception(self):
        """chat_pipeline.py 的 NL 工具合成 except 应使用 logger.exception。"""
        src = open(
            "e:/项目/Neurova/neurova/agent/chat_pipeline.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        assert not re.search(
            r'logger\.warning\s*\(\s*["\']NL工具合成检查失败',
            src_no_comments
        ), (
            "chat_pipeline.py 的 NL 工具合成 except 仍用 logger.warning,"
            "应改为 logger.exception 以输出完整 traceback。"
        )
        assert re.search(
            r'logger\.exception\s*\(\s*["\']NL工具合成检查失败',
            src_no_comments
        )


# ──────────────────────────────────────────────────────────────────
# 候选 2: _unpack_skill helper 提取
# ──────────────────────────────────────────────────────────────────

# 加载被 neurova.skill_system 包遮蔽的 neurova/skill_system.py 单文件
_SPEC = importlib.util.spec_from_file_location(
    "neurova_skill_system_standalone_for_arch_test",
    "e:/项目/Neurova/neurova/skill_system.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
Skill = _MOD.Skill


class TestUnpackSkillHelper:
    """候选 2: ToolRouter 提取 _unpack_skill(value) -> Skill 私有 helper。

    根因: V2-2 和 V2-7 都在 tool_router.py 内重复实现
    "如果是元组/列表则取 [0]" 的解包逻辑,分散在两个方法中。

    修复: 提取 _unpack_skill 私有方法,两处调用点共用。
    收益: Locality↑(单点维护)、Testability↑(helper 可独立单测)。
    """

    def test_unpack_skill_method_exists(self):
        """ToolRouter 应有 _unpack_skill 私有方法。"""
        from neurova.tool_layers.tool_router import ToolRouter
        assert hasattr(ToolRouter, "_unpack_skill"), (
            "ToolRouter 应提取 _unpack_skill(value) -> Skill 私有 helper,"
            "收敛 V2-2 和 V2-7 的元组解包重复逻辑。"
        )

    def test_unpack_skill_returns_skill_from_tuple(self):
        """_unpack_skill 对 (Skill, Path) 元组返回 Skill。"""
        from neurova.tool_layers.tool_router import ToolRouter
        test_skill = Skill(name="weather", description="天气")
        test_path = "/fake/path.py"
        tr = ToolRouter.__new__(ToolRouter)
        result = tr._unpack_skill((test_skill, test_path))
        assert result is test_skill, (
            f"元组 (Skill, Path) 应解包返回 Skill,实际:{type(result)}"
        )

    def test_unpack_skill_returns_skill_from_list(self):
        """_unpack_skill 对 [Skill, Path] 列表返回 Skill。"""
        from neurova.tool_layers.tool_router import ToolRouter
        test_skill = Skill(name="search", description="搜索")
        tr = ToolRouter.__new__(ToolRouter)
        result = tr._unpack_skill([test_skill, "/path"])
        assert result is test_skill

    def test_unpack_skill_passes_through_plain_skill(self):
        """_unpack_skill 对裸 Skill 对象直接返回。"""
        from neurova.tool_layers.tool_router import ToolRouter
        test_skill = Skill(name="plain", description="裸 Skill")
        tr = ToolRouter.__new__(ToolRouter)
        result = tr._unpack_skill(test_skill)
        assert result is test_skill, (
            "裸 Skill 对象应直接返回,不应包装或复制。"
        )

    def test_unpack_skill_used_in_discover_skill_tools(self):
        """_discover_skill_tools 应调用 _unpack_skill(消除重复逻辑)。"""
        src = open(
            "e:/项目/Neurova/neurova/tool_layers/tool_router.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        # 查找 _discover_skill_tools 内是否调用 self._unpack_skill
        # 提取 _discover_skill_tools 方法体
        match = re.search(
            r'def\s+_discover_skill_tools\s*\([^)]*\)[^:]*:.*?(?=\n    def\s|\n    async def\s|\nclass\s|\Z)',
            src_no_comments,
            re.DOTALL
        )
        assert match, "未找到 _discover_skill_tools 方法"
        method_body = match.group(0)
        assert "self._unpack_skill" in method_body, (
            "_discover_skill_tools 应调用 self._unpack_skill,"
            "而非内联 isinstance(skill, (tuple, list)) + skill[0] 逻辑。"
        )

    def test_unpack_skill_used_in_resolve_skill_tool(self):
        """_resolve_skill_tool 应调用 _unpack_skill(消除重复逻辑)。"""
        src = open(
            "e:/项目/Neurova/neurova/tool_layers/tool_router.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        match = re.search(
            r'(?:async\s+)?def\s+_resolve_skill_tool\s*\([^)]*\)[^:]*:.*?(?=\n    def\s|\n    async def\s|\nclass\s|\Z)',
            src_no_comments,
            re.DOTALL
        )
        assert match, "未找到 _resolve_skill_tool 方法"
        method_body = match.group(0)
        assert "self._unpack_skill" in method_body, (
            "_resolve_skill_tool 应调用 self._unpack_skill,"
            "而非内联 isinstance(skill, (tuple, list)) + skill[0] 逻辑。"
        )


# ──────────────────────────────────────────────────────────────────
# 候选 1: SkillRegistryProtocol 统一双实现
# ──────────────────────────────────────────────────────────────────

class TestSkillRegistryProtocol:
    """候选 1: 定义 SkillRegistryProtocol 统一两类 SkillRegistry 实现。

    根因(V2-1/V2-2/V2-5/V2-7 同根): 类 A (neurova/skill_system.py)
    和类 B (neurova/skills/registry.py) API 完全不兼容,但调用方混用。

    修复: 定义 typing.Protocol,显式声明统一接口。两个实现都满足 Protocol。
    调用方依赖 Protocol 而非具体类,编译期可检查 API 一致性。

    接口(seam):
        - skills: Dict[str, Skill]  (类 A 已有 property,类 B 需解包)
        - register(skill: Skill) -> bool  (类 A 已有,类 B 需兼容)
        - register_skill(manifest, path=None) -> bool  (类 B 已有,类 A 已加兼容)
        - list_skills() -> List[Any]  (类 A 已有,类 B 需兼容)
        - execute_skill(name, args) -> Any  (两者都有)
    """

    def test_protocol_defined_in_skill_system(self):
        """neurova/skill_system.py 应定义 SkillRegistryProtocol。"""
        src = open(
            "e:/项目/Neurova/neurova/skill_system.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        assert "SkillRegistryProtocol" in src_no_comments, (
            "skill_system.py 应定义 SkillRegistryProtocol (typing.Protocol),"
            "显式声明统一接口,作为类 A 和类 B 的 seam。"
        )
        # 应使用 typing.Protocol 或 runtime_checkable
        assert "Protocol" in src_no_comments, (
            "SkillRegistryProtocol 应基于 typing.Protocol。"
        )

    def test_protocol_declares_skills_attribute(self):
        """Protocol 应声明 skills: Dict[str, Skill] 接口。"""
        src = open(
            "e:/项目/Neurova/neurova/skill_system.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        # 提取 Protocol 类定义
        match = re.search(
            r'class\s+SkillRegistryProtocol[^:]*:.*?(?=\nclass\s|\ndef\s|\Z)',
            src_no_comments,
            re.DOTALL
        )
        assert match, "未找到 SkillRegistryProtocol 类定义"
        protocol_body = match.group(0)
        assert "skills" in protocol_body, (
            "SkillRegistryProtocol 应声明 skills 接口(Dict[str, Skill])。"
        )

    def test_protocol_declares_register_and_register_skill(self):
        """Protocol 应声明 register 和 register_skill 两个方法接口。"""
        src = open(
            "e:/项目/Neurova/neurova/skill_system.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        match = re.search(
            r'class\s+SkillRegistryProtocol[^:]*:.*?(?=\nclass\s|\ndef\s|\Z)',
            src_no_comments,
            re.DOTALL
        )
        assert match, "未找到 SkillRegistryProtocol 类定义"
        protocol_body = match.group(0)
        assert "register" in protocol_body, (
            "Protocol 应声明 register(skill: Skill) -> bool 接口。"
        )
        assert "register_skill" in protocol_body, (
            "Protocol 应声明 register_skill(manifest, path=None) -> bool 接口。"
        )

    def test_protocol_declares_list_skills_and_execute_skill(self):
        """Protocol 应声明 list_skills 和 execute_skill 接口。"""
        src = open(
            "e:/项目/Neurova/neurova/skill_system.py",
            encoding="utf-8",
        ).read()
        src_no_comments = re.sub(r'#.*', '', src)
        match = re.search(
            r'class\s+SkillRegistryProtocol[^:]*:.*?(?=\nclass\s|\ndef\s|\Z)',
            src_no_comments,
            re.DOTALL
        )
        assert match, "未找到 SkillRegistryProtocol 类定义"
        protocol_body = match.group(0)
        assert "list_skills" in protocol_body, (
            "Protocol 应声明 list_skills() -> List 接口。"
        )
        assert "execute_skill" in protocol_body, (
            "Protocol 应声明 execute_skill(name, args) 接口。"
        )

    def test_class_a_satisfies_protocol(self):
        """类 A SkillRegistry 应满足 SkillRegistryProtocol 接口。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "neurova_skill_system_for_protocol_test",
            "e:/项目/Neurova/neurova/skill_system.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        SkillRegistryClassA = mod.SkillRegistry
        Protocol = mod.SkillRegistryProtocol
        instance = SkillRegistryClassA.__new__(SkillRegistryClassA)
        instance._skills = {}
        # 验证所有 Protocol 方法都存在
        for method in ["skills", "register", "register_skill", "list_skills", "execute_skill"]:
            assert hasattr(instance, method) or hasattr(SkillRegistryClassA, method), (
                f"类 A SkillRegistry 应实现 Protocol 的 '{method}' 接口"
            )

    def test_protocol_exported_from_skill_system_package(self):
        """SkillRegistryProtocol 应从 neurova.skill_system 包可导入。"""
        # 由于 neurova/skill_system.py 被 neurova/skill_system/ 包遮蔽,
        # 需确认 Protocol 通过 __init__.py 或 __getattr__ 导出
        src = open(
            "e:/项目/Neurova/neurova/skill_system/__init__.py",
            encoding="utf-8",
        ).read()
        assert "SkillRegistryProtocol" in src, (
            "SkillRegistryProtocol 应从 neurova.skill_system 包导出,"
            "使调用方可用 'from neurova.skill_system import SkillRegistryProtocol'。"
        )


# ──────────────────────────────────────────────────────────────────
# 候选 4: 流式/非流式分支统一 — 补齐流式测试覆盖(defer 完整统一)
# ──────────────────────────────────────────────────────────────────

class TestStreamBranchCoverage:
    """候选 4 前置: 补齐流式分支测试覆盖,为未来统一铺路。

    评估结论: 完整统一 stream/non-stream 分支被标记 Speculative,因为:
    1. 改变 predict_step 接口影响所有调用方(高风险)
    2. non-stream 分支有 reasoning 捕获 + auto-continue,stream 分支没有
    3. 强制统一可能引入新 latent bug

    决策: 先补齐流式分支行为测试,验证当前 V2-6 修复(await)确实工作。
    完整统一待流式测试覆盖完善后再执行。
    """

    @pytest.mark.asyncio
    async def test_stream_branch_extracts_content_events(self):
        """流式分支应只提取 content 事件的 data,跳过元数据事件。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        # 构造 mock loop 返回 async iterator
        async def mock_predict_step(**kwargs):
            async def event_gen():
                yield {"type": "reasoning", "data": "思考中..."}
                yield {"type": "content", "data": "你好"}
                yield {"type": "tool_call", "data": {"name": "weather"}}
                yield {"type": "content", "data": "世界"}
                yield {"type": "tool_result", "data": {"result": "..."}}
                yield {"type": "done", "reply": "你好世界"}
            return event_gen()

        # 构造最小 ChatPipeline 实例(loop 是 property 来自 _agent.loop)
        pipeline = ChatPipeline.__new__(ChatPipeline)
        agent = MagicMock()
        agent.loop = MagicMock()
        agent.loop.predict_step = mock_predict_step
        pipeline._agent = agent

        # 构造 ChatContext
        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(context=[], user_input="test")

        reply = await pipeline._call_loop_stream(ctx, None)

        # 验证: 只有 content 事件的 data 进入回复
        # reasoning/tool_call/tool_result 元数据应被跳过
        assert reply == "你好世界", (
            f"流式分支应只提取 content 事件,实际:{reply!r}。"
            "reasoning/tool_call/tool_result 元数据不应进入回复。"
        )

    @pytest.mark.asyncio
    async def test_stream_branch_done_event_fallback(self):
        """流式分支: 无 content 事件时,done 事件的 reply 作为兜底。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        async def mock_predict_step(**kwargs):
            async def event_gen():
                yield {"type": "reasoning", "data": "思考中..."}
                yield {"type": "done", "reply": "兜底回复"}
            return event_gen()

        pipeline = ChatPipeline.__new__(ChatPipeline)
        agent = MagicMock()
        agent.loop = MagicMock()
        agent.loop.predict_step = mock_predict_step
        pipeline._agent = agent

        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(context=[], user_input="test")

        reply = await pipeline._call_loop_stream(ctx, None)
        assert reply == "兜底回复", (
            f"无 content 事件时,done.reply 应作为兜底,实际:{reply!r}"
        )

    @pytest.mark.asyncio
    async def test_stream_branch_empty_when_no_content_no_done_reply(self):
        """流式分支: 无 content 且 done 无 reply 时,返回空字符串。"""
        from neurova.agent.chat_pipeline import ChatPipeline

        async def mock_predict_step(**kwargs):
            async def event_gen():
                yield {"type": "reasoning", "data": "思考中..."}
                yield {"type": "done"}
            return event_gen()

        pipeline = ChatPipeline.__new__(ChatPipeline)
        agent = MagicMock()
        agent.loop = MagicMock()
        agent.loop.predict_step = mock_predict_step
        pipeline._agent = agent

        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(context=[], user_input="test")

        reply = await pipeline._call_loop_stream(ctx, None)
        assert reply == "", (
            f"无 content 且 done 无 reply 时应返回空字符串,实际:{reply!r}"
        )


class TestCandidate4DeferralDecision:
    """候选 4 推迟决策记录。

    完整统一 stream/non-stream 分支被评估为 Speculative,推迟执行。
    理由(基于架构审查):
    1. predict_step 接口变更影响所有调用方(高风险)
    2. non-stream 分支有 reasoning 捕获 + auto-continue,stream 分支缺失
    3. 强制统一可能引入新 latent bug
    4. V2-6(await)已修复最紧迫的 bug,统一是 nice-to-have

    决策: 补齐流式测试覆盖(上面 3 个测试),为未来统一铺路。
    """

    def test_stream_branch_has_test_coverage(self):
        """流式分支应有测试覆盖(为未来统一铺路)。"""
        src = open(
            "e:/项目/Neurova/tests/unit/test_arch_deepening_candidates.py",
            encoding="utf-8",
        ).read()
        assert "test_stream_branch_extracts_content_events" in src
        assert "test_stream_branch_done_event_fallback" in src
        assert "test_stream_branch_empty_when_no_content_no_done_reply" in src

