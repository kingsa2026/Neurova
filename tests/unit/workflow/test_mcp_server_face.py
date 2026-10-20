"""P1-5 MCP server 面。

契约（§3.4/§4 P1-5）：
Neurova 平台自身可作为 MCP server 对外暴露能力面：
- NeurovaMCPServer：协议无关的核心（清单/调用），传输层（stdio/SSE）
  由 SDK 适配器另行包壳——核心先落，传输后接
- list_tools()：已发布工作流（workflow_as_tool schema 复用）+ 技能
  （**执行池那一份注册表**，§6-352 的乙）聚合为 MCP tools 形态
  （name/description/inputSchema，schema 由 OpenAISchemaAdapter 单源给出）
- call_tool(name, arguments)：按前缀分派 workflow:/skill:*；
  工作流经 workflow_as_tool（DAG 输入校验 + 发布态检查），技能经
  `ToolExecutor.execute_skill_tool` 咽喉（轮级可见门/权限作用域/沙箱根注入/
  漏斗记账都在那道上）——无 agent 时 fail-closed，不回退成直调 skill.execute
- 未知工具 → MCP 语义错误信封（不崩）；技能工具名不带前缀的注册面
  归一为 skill:{name}
- **失败只有一种形状**（§6-334 的 B 票裁甲）：三条腿的业务失败（工作流不存在/
  必填校验拦下、技能跑砸、治理拦截、agent 回合失败）一律收成 isError 信封；
  成功侧逐字段透传，不加工
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest


class _Pool:
    """执行池替身：只暴露咽喉与本面用到的那两个口（`skills` 只读视图／`get_skill` 取键口）。"""

    def __init__(self, skills):
        self._skills = dict(skills)

    @property
    def skills(self):
        return dict(self._skills)

    def get_skill(self, name):
        return self._skills.get(name)


def _agentWith(skills, agentId="b62agent"):
    agent = MagicMock(name="agent")
    agent._skill_registry = _Pool(skills)
    agent.config.agent_id = agentId   # 可见集装配要按身份取视图，替身得给个稳的串
    return agent


class TestListTools:
    def test_aggregates_workflows_and_skills(self, tmp_path):
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        storage = NeurflowStorage(str(tmp_path / "nf.db"))
        storage.save_workflow(WorkflowDefinition(
            id="wf_mcp", name="MCP 样例流", description="demo", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": [{"name": "city", "type": "string", "label": "城市", "required": True}]}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 99, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="g", author="t",
            created_at=time.time(), updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
        ))

        skill = MagicMock()
        skill.name = "translate"
        skill.description = "翻译技能"
        skill._get_parameters.return_value = {
            "text": {"type": "string", "required": True, "description": "待译文本"}
        }

        # §6-352 裁乙：清单源改读**执行池**（agent 的那一份），构造期注入的第二份池子已删。
        server = NeurovaMCPServer(storage=storage, agent_ref=_agentWith({"translate": skill}))
        tools = server.list_tools()

        names = [t["name"] for t in tools]
        assert "workflow:wf_mcp" in names
        assert "skill:translate" in names
        wf_tool = next(t for t in tools if t["name"] == "workflow:wf_mcp")
        assert wf_tool["inputSchema"]["properties"]["city"]["type"] == "string"
        skill_tool = next(t for t in tools if t["name"] == "skill:translate")
        assert "翻译" in skill_tool["description"]


class TestCallTool:
    @pytest.fixture
    def server(self, tmp_path):
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        storage = NeurflowStorage(str(tmp_path / "nf.db"))
        storage.save_workflow(WorkflowDefinition(
            id="wf_call", name="调用流", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": [{"name": "q", "type": "string", "required": True}]}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 99, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="g", author="t",
            created_at=time.time(), updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
        ))

        skill = MagicMock()
        skill.name = "oracle"
        skill.description = "x"

        async def _trapExec(params, context=None):  # pragma: no cover
            raise AssertionError(
                "MCP 面又直调 `skill.execute` 了——技能腿必须走 "
                "`ToolExecutor.execute_skill_tool` 那道咽喉（§6-334 的 C 票裁甲）"
            )

        skill.execute = _trapExec
        # 清单源与执行源同那一份：技能只放在 agent 的执行池里（§6-352 裁乙）。
        return NeurovaMCPServer(storage=storage, agent_ref=_agentWith({"oracle": skill}))

    @pytest.fixture
    def throat(self, monkeypatch):
        """把咽喉换成"记参数、回规范 dict"的替身——本格审的是**走没走这条路**。"""
        seen: dict = {}

        async def _fake(self_, skill_name, params, context=None):
            seen["skill_name"] = skill_name
            seen["params"] = dict(params or {})
            return {"success": True, "output": {"answer": "42"}}

        monkeypatch.setattr(
            "neurova.tool_executor.ToolExecutor.execute_skill_tool", _fake
        )
        return seen

    @pytest.mark.asyncio
    async def test_call_workflow_tool(self, server):
        out = await server.call_tool("workflow:wf_call", {"q": "hi"})
        assert out["success"] is True, out
        assert "result" in out

    @pytest.mark.asyncio
    async def test_call_skill_tool(self, server, throat):
        out = await server.call_tool("skill:oracle", {"task": "?"})
        assert throat == {"skill_name": "oracle", "params": {"task": "?"}}, (
            f"咽喉读到的分派={throat}——名字或参数被面改写过"
        )
        assert out["success"] is True, out
        assert out["result"]["answer"] == "42"

    @pytest.mark.asyncio
    async def test_skillLegRefusesWithoutAgent(self, monkeypatch):
        """无 agent 时必须 fail-closed，**不许回退成直调 `skill.execute`**。

        咽喉上的四件事（轮级可见门 H-W2／声明式权限作用域／沙箱根注入／正典 seam 记账）
        都不是这一面能自己补出来的；宁可拒，不可绕过。
        """
        from neurova.tool_layers.mcp_server import NeurovaMCPServer as Core

        skill = MagicMock()
        skill.name = "oracle"
        skill.description = "x"

        async def _trap(params, context=None):  # pragma: no cover
            # 文案里刻意不出现 "agent"：否则这条被 call_tool 外层 except 收进错误信封后，
            # 下面那句"拒因提到 agent"会被 trap 自己的文字撞绿——假阳性。
            raise AssertionError("技能腿又直调 skill.execute 了＝绕过治理咽喉")

        skill.execute = _trap
        core = Core(storage=None, agent_provider=lambda: None)
        out = await core.call_tool("skill:oracle", {})
        assert out.get("isError") is True, out
        assert "agent" in out.get("error", "").lower(), out
        assert "skill.execute" not in out["error"], (
            f"拒因里出现的是 trap 的文案＝它被调起了，fail-closed 没在 agent 缺失处生效：{out}"
        )

    @pytest.mark.asyncio
    async def test_skillLegCarriesTheThroatsOwnRefusal(self, server, monkeypatch):
        """可见门/查无此技能这类拒绝由咽喉给，面原样转成 MCP 错误信封，不重述文案。"""
        async def _refuse(self_, skill_name, params, context=None):
            return {"error": f"Skill {skill_name} 在当前会话不可用"}

        monkeypatch.setattr(
            "neurova.tool_executor.ToolExecutor.execute_skill_tool", _refuse
        )
        out = await server.call_tool("skill:oracle", {})
        assert out.get("isError") is True, out
        assert "当前会话不可用" in out["error"], out


    @pytest.mark.asyncio
    async def test_call_unknown_tool_mcp_error(self, server):
        """MCP 语义错误信封（isError 形态，不抛异常）"""
        out = await server.call_tool("tool:nope", {})
        assert out.get("isError") is True
        assert "nope" in out.get("error", "")

    @pytest.mark.asyncio
    async def test_workflow_required_validation_still_applies(self, server):
        """MCP 面不绕过 DAG 输入校验（必填缺失拒执行）——且拒的形式只有一种。

        §6-334 的 B 票裁甲：这一格原断 `out["success"] is False`，与同档那条
        「未知工具 → isError」并存在同一张面上，等于对外部客户端承认两种失败信封。
        现在校验照旧要拦（`"q" in error` 这条**没有放宽**），信封统一成 isError。
        """
        out = await server.call_tool("workflow:wf_call", {})
        assert out.get("isError") is True, out
        assert "q" in (out.get("error") or "")

    @pytest.mark.asyncio
    async def test_workflowMissingUsesTheSameEnvelopeAsUnknownTool(self, server):
        """工作流不存在与未知工具名，客户端读到的必须是同一种形状。"""
        unknown = await server.call_tool("tool:nope", {})
        missing = await server.call_tool("workflow:没有这条流", {})
        assert unknown.get("isError") is True and missing.get("isError") is True, (unknown, missing)
        assert "没有这条流" in missing["error"], missing

    @pytest.mark.asyncio
    async def test_skillBusinessFailureAlsoUsesTheSameEnvelope(self, server, monkeypatch):
        """咽喉回 `success=False`（技能自己跑砸）也必须收成 isError，而不是留第二种体。"""
        async def _fail(self_, skill_name, params, context=None):
            return {"success": False, "output": None, "error": "技能内部失败"}

        monkeypatch.setattr(
            "neurova.tool_executor.ToolExecutor.execute_skill_tool", _fail
        )
        out = await server.call_tool("skill:oracle", {})
        assert out.get("isError") is True, out
        assert "技能内部失败" in out["error"], out


class _Skill:
    """技能替身：`params=None` 时**不实现** `_get_parameters`——内置三技能的参数面落在
    `builtin.schemas` 那张表上，替身要复现的就是这个形状（声明只许从单源读出来）。"""

    def __init__(self, name, description="技能", params=None):
        self.name = name
        self.description = description
        self.config = {}
        if params is not None:
            self._get_parameters = lambda: dict(params)


@pytest.mark.asyncio
class TestSkillFaceSingleSourceAndParameterGate:
    """§6-352 裁乙＋附问裁加：清单与执行同那一份池，参数面同那一份声明，未声明的键当场拒。

    为什么这八格一起写：乙（归一取数口）与那道闸（按声明校参数）读的是**同一件事**——
    本面向外承诺的参数面。拆成两批做，第二批就会去抄第一批刚改过的那份 schema。
    """

    def _core(self, skills):
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        return NeurovaMCPServer(agent_ref=_agentWith(skills))

    @pytest.fixture
    def throat(self, monkeypatch):
        seen = []

        async def _fake(self_, skill_name, params, context=None):
            seen.append((skill_name, dict(params or {})))
            return {"success": True, "output": {"ran": skill_name}}

        monkeypatch.setattr("neurova.tool_executor.ToolExecutor.execute_skill_tool", _fake)
        return seen

    async def testAdvertisedSkillsComeFromTheExecPoolOnly(self):
        """②那一半的正解：清单只能报执行池里有的名字。"""
        names = [tool["name"] for tool in self._core({"onlyExec": _Skill("onlyExec")}).list_tools()]
        assert "skill:onlyExec" in names, names

    async def testNoSecondPoolParameterIsLeftOnTheConstructor(self):
        """第二份池子的**入口**必须一起没了——留着参数不读＝只写不读的断点（§2 断点条款）。"""
        import inspect

        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        assert "skill_registry" not in inspect.signature(NeurovaMCPServer.__init__).parameters, (
            "构造期还留着 `skill_registry`：那就有两条清单来源，乙只做了半条"
        )

    async def testNoAgentMeansNoSkillFace(self):
        """无 agent ⇒ 既不执行也不 advertise（与 C 票那条 fail-closed 同形，不留半边）。"""
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        core = NeurovaMCPServer(storage=None, agent_provider=lambda: None)
        names = [tool["name"] for tool in core.list_tools()]
        assert not any(n.startswith("skill:") for n in names), names

    async def testAdvertisedSkillIsAlsoExecutable(self, throat):
        """同一名字两个方向都要通：清单报得出的，咽喉必须收得到（③那条反方向）。"""
        core = self._core({"bothWays": _Skill("bothWays")})
        assert "skill:bothWays" in [t["name"] for t in core.list_tools()]
        out = await core.call_tool("skill:bothWays", {})
        assert throat == [("bothWays", {})], throat
        assert out.get("isError") is not True, out

    async def testSchemaComesFromTheSameDeclaration(self):
        """advertise 的 inputSchema 必须逐字段等于 `OpenAISchemaAdapter` 那份声明，
        且**不再含手抄的通用 `task`**——外部客户端据此才可能把参数写对。"""
        from neurova.skill_system.compat import OpenAISchemaAdapter

        skill = _Skill("file_operation", "文件操作")
        declared = OpenAISchemaAdapter.skill_to_tool_schema(skill)["function"]["parameters"]
        tool = next(t for t in self._core({"file_operation": skill}).list_tools()
                    if t["name"] == "skill:file_operation")
        assert tool["inputSchema"] == declared, (tool["inputSchema"], declared)
        assert {"operation", "file_path", "content"} <= set(declared["properties"]), declared
        assert "task" not in declared["properties"], "还含通用 task＝那份手抄没退干净"

    async def testUnknownParameterKeyIsRefusedBeforeTheThroat(self, throat):
        """实测到的那条：键名写错时本面不拒，而是静默落到技能的缺省分支。现在必须当场拒。"""
        skill = _Skill("file_operation", "文件操作")
        out = await self._core({"file_operation": skill}).call_tool(
            "skill:file_operation", {"action": "write", "file_path": "p.txt", "content": "x"}
        )
        assert out.get("isError") is True, out
        assert "action" in out["error"], out
        assert "operation" in out["error"], out
        assert throat == [], f"闸没拦在前面，咽喉已经收到这一发：{throat}"

    async def testMissingRequiredKeyIsRefused(self, throat):
        """必填缺失属同一根因（声明不被执行）：`operation` 是必填，缺了就不许落到缺省的 read。"""
        skill = _Skill("file_operation", "文件操作")
        out = await self._core({"file_operation": skill}).call_tool(
            "skill:file_operation", {"file_path": "p.txt"}
        )
        assert out.get("isError") is True, out
        assert "operation" in out["error"], out
        assert throat == [], throat

    async def testDeclaredKeysReachTheThroatUnchanged(self, throat):
        """控制格：全键都在声明内 ⇒ 过闸，且参数一个字段都不改。"""
        skill = _Skill("file_operation", "文件操作")
        out = await self._core({"file_operation": skill}).call_tool(
            "skill:file_operation", {"operation": "read", "file_path": "p.txt"}
        )
        assert throat == [("file_operation", {"operation": "read", "file_path": "p.txt"})], throat
        assert out.get("isError") is not True, out

    async def testSkillWithNoDeclarationIsNotGated(self, throat):
        """没有声明面就不拒——在本面另列一张「哪些键算合法」的表＝第二个事实源（教义 第 6 条）。"""
        core = self._core({"custom": _Skill("custom", "自述技能")})
        await core.call_tool("skill:custom", {"whatever": 1, "args": [2]})
        assert throat == [("custom", {"whatever": 1, "args": [2]})], throat


@pytest.mark.asyncio
class TestTurnViewAssembledBeforeTheThroat:
    """§6-352 裁甲：进咽喉之前必须挂上轮级可见集，且必须用 chat 主链那同一个构造口。

    这四格审的是**接线**（有没有装、按什么入参装、出去有没有复位、装不上时拒不拒），
    `build_turn_view` 自己那套三库合并语义由 `tests/unit/skills/` 那批判据钉，本档不重述。
    """

    def _wire(self, monkeypatch, skills, boom=False):
        import neurova.core.turn_context as tc
        import neurova.skills.skill_visibility as sv

        seen = {"viewInThroat": [], "throatCalls": []}
        built = object()

        def _build(agent_id, user_key, registry_skills=None):
            seen["buildArgs"] = (agent_id, user_key, registry_skills)
            if boom:
                raise RuntimeError("库目录读不动")
            return built

        def _resolve(user_id=None, **kw):
            seen["uid"] = user_id
            return None if user_id is None else f"u:{user_id}"

        async def _fakeThroat(self_, skill_name, params, context=None):
            seen["viewInThroat"].append(tc.get_turn_skill_view())
            seen["throatCalls"].append((skill_name, dict(params or {})))
            return {"success": True, "output": {"ran": skill_name}}

        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        monkeypatch.setattr(sv, "build_turn_view", _build)
        monkeypatch.setattr(sv, "resolve_user_key", _resolve)
        monkeypatch.setattr("neurova.tool_executor.ToolExecutor.execute_skill_tool", _fakeThroat)
        return NeurovaMCPServer(agent_ref=_agentWith(skills)), seen, built

    async def testThroatSeesTheAssembledView(self, monkeypatch):
        """咽喉读到的必须正是本面刚装上去的那个视图——不是 None，也不是上一发的残留。"""
        from neurova.core.identity_context import set_request_user_id

        core, seen, built = self._wire(monkeypatch, {"greet": _Skill("greet")})
        set_request_user_id("alice")
        out = await core.call_tool("skill:greet", {})
        assert seen["viewInThroat"] == [built], seen["viewInThroat"]
        assert out.get("isError") is not True, out

    async def testBuilderGetsTheExecPoolAndRequestIdentity(self, monkeypatch):
        """入参三件都要来自现役单点：agent 身份、请求身份、执行池那一份 skills 快照。"""
        from neurova.core.identity_context import set_request_user_id

        skills = {"greet": _Skill("greet")}
        core, seen, _built = self._wire(monkeypatch, skills)
        set_request_user_id("alice")
        await core.call_tool("skill:greet", {})
        agentId, userKey, registrySkills = seen["buildArgs"]
        assert agentId == "b62agent", agentId
        assert seen["uid"] == "alice" and userKey == "u:alice", (seen.get("uid"), userKey)
        assert set(registrySkills) == set(skills), registrySkills

    async def testViewIsResetAfterTheCall(self, monkeypatch):
        """出去必须复位——视图是 ContextVar，漏复位就是把这一发的授权留给下一发。

        这格同时断"里面看得见"：只断外面是 None 的写法在**根本没装视图**的实现上也是绿的
        （本批红自证时它就这样绿过一回，被当场补牙），所以把"装上了"与"复位了"钉在同一条里。
        """
        import neurova.core.turn_context as tc
        from neurova.core.identity_context import set_request_user_id

        core, seen, built = self._wire(monkeypatch, {"greet": _Skill("greet")})
        set_request_user_id("alice")
        assert tc.get_turn_skill_view() is None
        await core.call_tool("skill:greet", {})
        assert seen["viewInThroat"] == [built], f"咽喉没读到视图，后面那句 None 就白断：{seen['viewInThroat']}"
        assert tc.get_turn_skill_view() is None, "视图跨发残留＝第二个请求会读到第一个请求的授权"

    async def testUnknownSkillRefusalComesFromTheThroatNotTheFace(self, monkeypatch):
        """视图在位时，查无此技能名的拒因**必须来自咽喉**——这条区分是有内容的：
        装配之后咽喉先按视图判`invocable`，回的是「在当前会话不可用」（活体实测同值），
        没装配才会走到后面的「不存在」。本面不得重述出第三种说法。

        这一格刻意**不 stub 咽喉**：它审的正是"视图交到咽喉手上之后发生什么"，
        stub 掉就等于把被测的那一段换成了自己的替身。
        """
        import neurova.skills.skill_visibility as sv

        from neurova.core.identity_context import set_request_user_id
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        class _View:
            agent_id = "b62agent"

            def invocable(self, name):
                return False

            def provenance_for(self, name):
                return ("agent", "")

        monkeypatch.setattr(sv, "build_turn_view", lambda *a, **k: _View())
        monkeypatch.setattr(sv, "resolve_user_key", lambda *a, **k: "u:alice")
        set_request_user_id("alice")

        core = NeurovaMCPServer(agent_ref=_agentWith({}))
        out = await core.call_tool("skill:nope", {})
        assert out.get("isError") is True, out
        assert "当前会话不可用" in out["error"], out
        assert "可见集" not in out["error"], f"本面重述了一份自己的拒因：{out['error']}"

    async def testAssemblyFailureRefusesInsteadOfRunningBlind(self, monkeypatch):
        """装配失败 fail-closed（与 chat 主链的 fail-open 有意相反）：这道视图就是授权本身。"""
        from neurova.core.identity_context import set_request_user_id

        core, seen, _built = self._wire(monkeypatch, {"greet": _Skill("greet")}, boom=True)
        set_request_user_id("alice")
        out = await core.call_tool("skill:greet", {})
        assert out.get("isError") is True, out
        assert "可见" in out["error"] or "fail-closed" in out["error"], out
        assert seen["throatCalls"] == [], f"装配没成都把调用放进了咽喉：{seen['throatCalls']}"


@pytest.mark.asyncio
class TestOneFailureEnvelopeAcrossThreeLegs:
    """三条腿（工作流／技能／CUA）的失败必须同形；成功侧一律不加工。

    这三格审的是 B 票裁的那句话本身——**同类错误只允许一种形状**。控制格
    （成功透传）与另外两格同样重要：把成功也裹进错误信封就是自伤。
    """

    def _server(self, monkeypatch, executorResult, chatReply=None):
        from neurova.tool_layers.mcp_server import NeurovaMCPServer
        from neurova.tool_executor import ToolExecutor

        monkeypatch.setenv("NEUROVA_CUA_MCP_EXPORT", "1")

        async def _fakeExec(self, tool_name, params, skip_governance=False):
            return dict(executorResult)

        class _Agent:
            def __init__(self):
                self.calls = []

            async def chat(self, user_input, **kw):
                self.calls.append(user_input)
                return chatReply if chatReply is not None else {"success": True, "reply": "ok"}

        monkeypatch.setattr(ToolExecutor, "_execute_single_tool", _fakeExec)
        return NeurovaMCPServer(agent_ref=_Agent()), _fakeExec

    async def testGovernanceRefusalIsNotASpecialShape(self, monkeypatch):
        """安全钩子拦截＝业务失败，走同一个 isError 信封（此前它是 `success=False` 的第三种体）。"""
        server, _ = self._server(
            monkeypatch,
            {"success": False, "error": "操作被安全钩子拦截: 写动词 HIGH", "hook_blocked": True},
        )
        out = await server.call_tool("computer_shell", {"cmd": "rm -rf /"})
        assert out.get("isError") is True, out
        assert "安全钩子拦截" in out["error"], out

    async def testFailedAgentTurnCarriesItsOwnTextIntoTheEnvelope(self, monkeypatch):
        """agent 面那一轮跑砸时，拒绝文案不许被丢掉，也不许留成 `{"success": false, "result": …}`。"""
        server, _ = self._server(
            monkeypatch, {"success": True}, chatReply={"success": False, "reply": "桌面回合失败"}
        )
        out = await server.call_tool("run_computer_task", {"goal": "打开记事本"})
        assert out.get("isError") is True, out
        assert "桌面回合失败" in out["error"], out

    async def testSuccessIsPassedThroughUnchanged(self, monkeypatch):
        """控制格：成功侧逐字段透传（工具面那条"不加工"的承诺不能被 B 顺带削掉）。"""
        sentinel = {"success": True, "screen": {"width": 1920}, "action_result": {"effect": "confirmed"}}
        server, _ = self._server(monkeypatch, sentinel)
        out = await server.call_tool("computer_screenshot", {"region": "x"})
        assert out == sentinel, out
        assert "isError" not in out, out
