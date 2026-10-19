"""P1-5 MCP server 面。

契约（§3.4/§4 P1-5）：
Neurova 平台自身可作为 MCP server 对外暴露能力面：
- NeurovaMCPServer：协议无关的核心（清单/调用），传输层（stdio/SSE）
  由 SDK 适配器另行包壳——核心先落，传输后接
- list_tools()：已发布工作流（workflow_as_tool schema 复用）+ 技能
  （skill_registry 清单）聚合为 MCP tools 形态（name/description/
  inputSchema）
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
        registry = MagicMock()
        registry._skills = {"translate": skill}

        server = NeurovaMCPServer(storage=storage, skill_registry=registry)
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
        registry = MagicMock()
        registry._skills = {"oracle": skill}

        # 技能腿现在需要 agent（咽喉挂在 ToolExecutor 上）；这里给的是"接线"用的壳，
        # 业务能力由 `tests/unit/execution/` 与咽喉自己的判据档钉，本档不重述。
        return NeurovaMCPServer(
            storage=storage, skill_registry=registry, agent_ref=MagicMock(name="agent")
        )

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
        registry = MagicMock()
        registry._skills = {"oracle": skill}
        core = Core(storage=None, skill_registry=registry, agent_provider=lambda: None)
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
