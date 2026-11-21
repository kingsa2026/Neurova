"""G0 存活探针 —— "跑不跑得起来"的唯一判据源（计划书 §3.3 / §6 P0 批 P0-2）。

设计出处：docs/04-plans/2026-11-21-recursive-self-evolution-plan.md
§2.1 三原则（内核先于演化）、§3.3 survival_probe 完整设计、§5 安全红线 L2 层。

定位：演化世代的第 0 道门禁。现有判据全是"参数/文本效果级"，没有
"改完之后系统还能不能起来"的硬闸——本探针补上这一层：任一项 failed，
该世代没资格参评任何业务判据（短路语义在调用方 gate_chain，本探针
本身逐项执行、逐项返回三态结论，绝不因一项挂掉而静默跳过其余项）。

六项判据（§3.3，任一 failed 即 G0 不过）：

1. **构建**：``create_app()`` 可构建，openapi 关键路由齐全（抽查
   /health、/v1/providers、/v1/chat 三类——进程内单例，探针在独立
   子进程中运行故单例无碍）；
2. **健康**：``/health`` 返回 ok（TestClient 本地调用，不外发）；
3. **启动**：启动日志 ``[ERROR]`` 计数为 0 且出现
   "Neurova API Server started successfully"（AGENTS.md §0 同款判据）；
4. **最小对话**：桩模型下走通一个对话回合返回非空回复。
   **判据强度如实说明**：本项走真 Agent（生产构造点）+ 真 chat 管线 +
   真后处理管线，只在模型边界用脚本化替身（与 tests/unit/agent 探针基座
   同款）——即"agent 全链可装配且能产出非空回复"，未覆盖真实 LLM 出网
   与模型质量；模型质量属 G2 业务判据面，不属于 G0 存活判据；
5. **工具执行**：ToolExecutor 成功执行至少一个内建只读工具
   （get_datetime，无副作用）；
6. **守卫子集**：以编程方式跑指定架构守卫测试文件（身份单通道 / 迁移表 /
   尺寸棘轮 / targetRegistry 守卫），独立子进程 pytest 全绿 → passed。

设计约束（§3.3）：

- 探针**不读任何被演化对象的内容**，只测行为——防止判据被改动内容绕过；
- 探针自身与判据阈值 ``forbidden``（target_registry 的
  kernel.rsi.survivalProbe，守卫测试逐条钉死）；
- 判据失败必须逐项点名（unevidenced 与 failed 分开报，沿用 GateVerdict
  语义：取不到证据报 unevidenced，绝不冒充 failed/passed）。

独立子进程语义：``runIsolated(dataRoot)`` 以子进程方式跑本文件
（``--child`` 入口），把隔离数据根经 ``NEUROVA_DATA_DIR`` 注入
（core/data_root 是数据根唯一注入口），供影子验证（P1-2 ShadowVerify）
复用；子进程以 JSON 回传逐项结论。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 本文件既作为 ``neurova.evolution.rsi.survival_probe`` 被导入，也作为
# ``runIsolated`` 的子进程脚本被直接运行；后者 sys.path 上没有仓库根，
# 必须在首次 import neurova 之前补上（与 scripts/diagnostics 探针同款引导）。
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from neurova.evolution.rsi.gate_verdict import GateVerdict

__all__ = [
    "SurvivalProbe",
    "runIsolated",
    "CRITERION_ORDER",
    "CRITERION_BUILD",
    "CRITERION_HEALTH",
    "CRITERION_STARTUP",
    "CRITERION_CHAT",
    "CRITERION_TOOL",
    "CRITERION_GUARD",
    "GUARD_SUBSET_FILES",
]

# ---------------------------------------------------------------------------
# 判据清单（§3.3 六项；顺序即返回顺序）
# ---------------------------------------------------------------------------

CRITERION_BUILD = "build"
CRITERION_HEALTH = "health"
CRITERION_STARTUP = "startup"
CRITERION_CHAT = "minimalChat"
CRITERION_TOOL = "toolExecution"
CRITERION_GUARD = "guardSubset"

CRITERION_ORDER = (
    CRITERION_BUILD,
    CRITERION_HEALTH,
    CRITERION_STARTUP,
    CRITERION_CHAT,
    CRITERION_TOOL,
    CRITERION_GUARD,
)

#: 构建判据抽查的关键路由（openapi paths 子串匹配；/api 为挂载前缀约定，
#: 计划书 §3.3 所指的 /v1/providers 即 /api/v1/providers）。
KEY_ROUTE_SUBSTRINGS = ("/health", "/v1/providers", "/v1/chat")

#: 启动判据的完成标记（neurova/api/app.py 启动日志最后一行）。
STARTUP_SUCCESS_MARKER = "Neurova API Server started successfully"

#: 工具执行判据用的内建只读工具（无副作用）。
PROBE_TOOL_NAME = "get_datetime"

#: 守卫子集白名单（§3.3 判据 6：身份单通道 / 迁移表 / 尺寸棘轮 /
#: targetRegistry 守卫）。仓库相对路径，逐文件跑、全绿才 passed。
GUARD_SUBSET_FILES = (
    "tests/unit/core/test_identityChannelMergedToOneSource.py",
    "tests/unit/core/test_db_migration.py",
    "tests/unit/agent/test_agent_core_size_ratchet.py",
    "tests/unit/guards/test_evolution_target_registry_guard.py",
)

#: 守卫子集子进程墙钟（实测 ~8s；CI 慢机留足余量）。
GUARD_SUBSET_TIMEOUT_S = 600

#: 子进程结论行的哨兵前缀（防 stdout 里混入其它打印干扰解析）。
_JSON_SENTINEL = "SURVIVAL_PROBE_JSON:"


class _LogCollector(logging.Handler):
    """启动窗口的日志收集器（挂在 root logger 上，靠传播收全 neurova 记录）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _StubChatModel:
    """模型边界替身：只回一条非空文本（与 tests/unit/agent 探针基座同款）。

    替身只放在模型边界——chat 管线、后处理、工具执行链全部走真代码。
    """

    def __init__(self, config: Any, replyText: str = "存活探针：链路正常") -> None:
        self.config = config
        self._replyText = replyText

    async def chat_stream(self, messages, **kwargs):
        from neurova.llm_client import LLMResponse

        yield LLMResponse(content=self._replyText, finish_reason="stop")

    async def chat(self, messages, **kwargs):
        from neurova.llm_client import LLMResponse

        return LLMResponse(content=self._replyText, finish_reason="stop")


class SurvivalProbe:
    """G0 存活探针：在给定工作区 + 隔离数据根上逐项执行六项存活判据。

    用法（影子验证 / 部署前自检）::

        verdicts = SurvivalProbe().probe(repoRoot, isolatedDataRoot)
        if not all(verdicts):
            ...  # G0 不过，短路后续门禁

    参数约定：
    - ``workspace``：被检代码工作区根（正常探针 = 仓库根；L2 影子验证时
      为隔离 checkout）。守卫子集以它为 cwd 与测试文件定位根。
    - ``dataRoot``：隔离数据根。探针把它注入 ``NEUROVA_DATA_DIR``（唯一
      注入口），agent 私有面、会话、经验库等运行期落盘全部收在这里，
      与生产数据根物理隔离；用毕恢复原值。
    """

    def probe(self, workspace: Path, dataRoot: Path) -> List[GateVerdict]:
        """逐项执行六项判据，按 §3.3 顺序返回三态结论（绝不短路）。"""
        workspace = Path(workspace)
        dataRoot = Path(dataRoot)
        dataRoot.mkdir(parents=True, exist_ok=True)

        previousDataRoot = os.environ.get("NEUROVA_DATA_DIR")
        os.environ["NEUROVA_DATA_DIR"] = str(dataRoot)
        try:
            buildVerdict, app = self._probeBuild(workspace, dataRoot)
            startupVerdict, healthVerdict = self._probeRuntime(app)
            chatVerdict = self._probeMinimalChat(workspace, dataRoot)
            toolVerdict = self._probeToolExecution(workspace, dataRoot)
            guardVerdict = self._probeGuardSubset(workspace, dataRoot)
        finally:
            if previousDataRoot is None:
                os.environ.pop("NEUROVA_DATA_DIR", None)
            else:
                os.environ["NEUROVA_DATA_DIR"] = previousDataRoot

        return [
            buildVerdict,
            healthVerdict,
            startupVerdict,
            chatVerdict,
            toolVerdict,
            guardVerdict,
        ]

    # ------------------------------------------------------------------
    # 判据 1：构建
    # ------------------------------------------------------------------

    def _probeBuild(
        self, workspace: Path, dataRoot: Path
    ) -> Tuple[GateVerdict, Optional[Any]]:
        """create_app 可构建 + openapi 关键路由齐全；返回 (结论, app 或 None)。"""
        try:
            from neurova.api.app import create_app

            app = create_app()
        except Exception as exc:  # noqa: BLE001 - 构建失败本身就是判据结果
            return (
                GateVerdict.failed(
                    f"构建判据失败: create_app() 不可构建: {exc}",
                    evidence={"criterion": CRITERION_BUILD},
                ),
                None,
            )

        try:
            paths = list(app.openapi().get("paths", {}).keys())
        except Exception as exc:  # noqa: BLE001 - openapi 生成失败同样是构建失败
            return (
                GateVerdict.failed(
                    f"构建判据失败: openapi 生成失败: {exc}",
                    evidence={"criterion": CRITERION_BUILD},
                ),
                None,
            )

        missing = [
            key for key in KEY_ROUTE_SUBSTRINGS
            if not any(key in path for path in paths)
        ]
        if missing:
            return (
                GateVerdict.failed(
                    f"构建判据失败: 关键路由未注册 {missing}"
                    f"（openapi 共 {len(paths)} 条路径）",
                    evidence={"criterion": CRITERION_BUILD, "missing": missing},
                ),
                None,
            )
        return (
            GateVerdict.passed(
                f"构建判据通过: create_app 可构建，关键路由齐全"
                f"（openapi 共 {len(paths)} 条路径）",
                evidence={"criterion": CRITERION_BUILD, "pathCount": len(paths)},
            ),
            app,
        )

    # ------------------------------------------------------------------
    # 判据 2/3：健康 + 启动（共用一次 TestClient lifespan，逐项独立裁决）
    # ------------------------------------------------------------------

    def _probeRuntime(self, app: Optional[Any]) -> Tuple[GateVerdict, GateVerdict]:
        startupUnevidenced = GateVerdict.unevidenced(
            "启动判据无法取证: 构建判据未通过，无应用可启动",
            evidence={"criterion": CRITERION_STARTUP},
        )
        healthUnevidenced = GateVerdict.unevidenced(
            "健康判据无法取证: 构建判据未通过，无应用可探测",
            evidence={"criterion": CRITERION_HEALTH},
        )
        if app is None:
            return startupUnevidenced, healthUnevidenced

        from fastapi.testclient import TestClient

        collector = _LogCollector()
        rootLogger = logging.getLogger()
        previousLevel = rootLogger.level
        # root 提到 DEBUG：保证"若某模块未设级别则继承 root"时 INFO 级
        # 启动完成标记也会真实产出并被收集（neurova logger 自身多为 DEBUG 级）。
        rootLogger.setLevel(logging.DEBUG)
        rootLogger.addHandler(collector)
        startupVerdict: Optional[GateVerdict] = None
        healthVerdict: Optional[GateVerdict] = None
        try:
            try:
                with TestClient(app) as client:
                    # 进入 with 即 lifespan 启动完成，启动窗口日志已收齐。
                    startupVerdict = self._startupVerdictFrom(collector.records)
                    # 健康请求前摘掉收集器：健康请求自身的日志不算进启动窗。
                    rootLogger.removeHandler(collector)
                    healthVerdict = self._healthVerdictFrom(client)
            except Exception as exc:  # noqa: BLE001 - lifespan 启动崩溃是启动判据的 failed
                if startupVerdict is None:
                    startupVerdict = GateVerdict.failed(
                        f"启动判据失败: lifespan 启动异常: {exc}",
                        evidence={"criterion": CRITERION_STARTUP},
                    )
                if healthVerdict is None:
                    healthVerdict = GateVerdict.unevidenced(
                        f"健康判据无法取证: 启动未完成（{exc}）",
                        evidence={"criterion": CRITERION_HEALTH},
                    )
        finally:
            if collector in rootLogger.handlers:
                rootLogger.removeHandler(collector)
            rootLogger.setLevel(previousLevel)
        return startupVerdict, healthVerdict

    @staticmethod
    def _startupVerdictFrom(records: List[logging.LogRecord]) -> GateVerdict:
        errors = [r for r in records if r.levelno >= logging.ERROR]
        started = any(
            STARTUP_SUCCESS_MARKER in r.getMessage() for r in records
        )
        if errors:
            headlines = "; ".join(
                f"{r.name}: {r.getMessage()[:120]}" for r in errors[:3]
            )
            return GateVerdict.failed(
                f"启动判据失败: 启动日志 [ERROR] 计数 {len(errors)}（判据要求 0）"
                f"，首条: {headlines}",
                evidence={"criterion": CRITERION_STARTUP, "errorCount": len(errors)},
            )
        if not started:
            return GateVerdict.failed(
                f"启动判据失败: 未出现启动完成标记 {STARTUP_SUCCESS_MARKER!r}",
                evidence={"criterion": CRITERION_STARTUP},
            )
        return GateVerdict.passed(
            "启动判据通过: 启动日志 [ERROR] 计数 0 且出现启动完成标记",
            evidence={"criterion": CRITERION_STARTUP},
        )

    @staticmethod
    def _healthVerdictFrom(client: Any) -> GateVerdict:
        try:
            response = client.get("/health")
        except Exception as exc:  # noqa: BLE001 - 端点异常即健康失败
            return GateVerdict.failed(
                f"健康判据失败: /health 请求异常: {exc}",
                evidence={"criterion": CRITERION_HEALTH},
            )
        if response.status_code != 200:
            return GateVerdict.failed(
                f"健康判据失败: /health 返回 {response.status_code}（判据要求 200）",
                evidence={"criterion": CRITERION_HEALTH},
            )
        try:
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            return GateVerdict.failed(
                f"健康判据失败: /health 响应非 JSON: {exc}",
                evidence={"criterion": CRITERION_HEALTH},
            )
        if body.get("status") != "ok":
            return GateVerdict.failed(
                f"健康判据失败: /health status={body.get('status')!r}（判据要求 ok）",
                evidence={"criterion": CRITERION_HEALTH},
            )
        return GateVerdict.passed(
            "健康判据通过: /health 返回 ok",
            evidence={"criterion": CRITERION_HEALTH},
        )

    # ------------------------------------------------------------------
    # 判据 4：最小对话（判据强度说明见 _StubChatModel 与模块 docstring）
    # ------------------------------------------------------------------

    def _probeMinimalChat(self, workspace: Path, dataRoot: Path) -> GateVerdict:
        try:
            from neurova.agent_core import Agent

            agentWorkspace = dataRoot / "agentWorkspaces" / "survivalProbeChat"
            agentWorkspace.mkdir(parents=True, exist_ok=True)
            agent = Agent(
                name="SurvivalProbeChat",
                agent_id="survival-probe-chat",
                workspace_path=str(agentWorkspace),
                enable_memory=False,
            )
            model = _StubChatModel(agent.llm_client.config)
            agent.llm_client = model
            agent.loop.llm_client = model

            async def _turn() -> Any:
                result = await agent.chat(
                    "存活探针最小对话", session_id="survival-probe-chat", stream=True
                )
                await agent.post_chat_pipeline.drain_background(timeout=60)
                return result

            result = asyncio.run(_turn())
            text = result.get("text") if isinstance(result, dict) else str(result)
            if not str(text or "").strip():
                return GateVerdict.failed(
                    "最小对话判据失败: 对话回合返回空回复",
                    evidence={"criterion": CRITERION_CHAT},
                )
            return GateVerdict.passed(
                f"最小对话判据通过: agent 全链（真 chat 管线，桩模型）返回非空回复"
                f"（{len(str(text))} 字符）",
                evidence={"criterion": CRITERION_CHAT, "replyLength": len(str(text))},
            )
        except Exception as exc:  # noqa: BLE001 - 对话链任何崩塌都是本判据的 failed
            return GateVerdict.failed(
                f"最小对话判据失败: {type(exc).__name__}: {exc}",
                evidence={"criterion": CRITERION_CHAT},
            )

    # ------------------------------------------------------------------
    # 判据 5：工具执行
    # ------------------------------------------------------------------

    def _probeToolExecution(self, workspace: Path, dataRoot: Path) -> GateVerdict:
        try:
            from neurova.agent_core import Agent
            from neurova.tool_executor import ToolExecutor

            agentWorkspace = dataRoot / "agentWorkspaces" / "survivalProbeTool"
            agentWorkspace.mkdir(parents=True, exist_ok=True)
            agent = Agent(
                name="SurvivalProbeTool",
                agent_id="survival-probe-tool",
                workspace_path=str(agentWorkspace),
                enable_memory=False,
            )
            executor = ToolExecutor(agent)
            result = asyncio.run(executor.execute(PROBE_TOOL_NAME, {}))
            if isinstance(result, dict) and (
                result.get("error") or result.get("success") is False
            ):
                return GateVerdict.failed(
                    f"工具执行判据失败: {PROBE_TOOL_NAME} 返回失败: "
                    f"{result.get('error') or result.get('success')}",
                    evidence={"criterion": CRITERION_TOOL, "tool": PROBE_TOOL_NAME},
                )
            keys = sorted(result) if isinstance(result, dict) else []
            return GateVerdict.passed(
                f"工具执行判据通过: 内建只读工具 {PROBE_TOOL_NAME} 执行成功",
                evidence={
                    "criterion": CRITERION_TOOL,
                    "tool": PROBE_TOOL_NAME,
                    "resultKeys": keys,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 执行链任何崩塌都是本判据的 failed
            return GateVerdict.failed(
                f"工具执行判据失败: {type(exc).__name__}: {exc}",
                evidence={"criterion": CRITERION_TOOL},
            )

    # ------------------------------------------------------------------
    # 判据 6：守卫子集
    # ------------------------------------------------------------------

    def _probeGuardSubset(self, workspace: Path, dataRoot: Path) -> GateVerdict:
        """以编程方式跑架构守卫子集（独立子进程 pytest，白名单文件集）。

        文件缺失 = 判据所需数据取不到 → unevidenced（不冒充 failed）；
        跑了但没全绿 = failed（逐条点名）。
        """
        files: List[str] = []
        for relative in GUARD_SUBSET_FILES:
            candidate = Path(relative)
            if not candidate.is_absolute():
                candidate = Path(workspace) / relative
            files.append(str(candidate))

        missing = [f for f in files if not Path(f).exists()]
        if missing:
            return GateVerdict.unevidenced(
                f"守卫子集判据无法取证: 守卫文件缺失 {missing}",
                evidence={"criterion": CRITERION_GUARD, "missing": missing},
            )

        command = [
            sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=line",
            "-p", "no:cacheprovider", *files,
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=str(workspace),
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=GUARD_SUBSET_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return GateVerdict.failed(
                f"守卫子集判据失败: 守卫测试 {GUARD_SUBSET_TIMEOUT_S}s 内未跑完"
                f"（文件: {GUARD_SUBSET_FILES}）",
                evidence={"criterion": CRITERION_GUARD},
            )

        if proc.returncode == 0:
            return GateVerdict.passed(
                f"守卫子集判据通过: {len(files)} 个架构守卫文件全绿",
                evidence={
                    "criterion": CRITERION_GUARD,
                    "files": list(GUARD_SUBSET_FILES),
                },
            )
        tailLines = [
            line for line in (proc.stdout or "").strip().splitlines() if line.strip()
        ][-4:]
        return GateVerdict.failed(
            f"守卫子集判据失败: 守卫测试未全绿（exit={proc.returncode}）"
            f" 尾部输出: {' | '.join(tailLines)}",
            evidence={"criterion": CRITERION_GUARD, "exitCode": proc.returncode},
        )


# ---------------------------------------------------------------------------
# 独立子进程语义（供 P1-2 ShadowVerify 复用）
# ---------------------------------------------------------------------------

def runIsolated(
    dataRoot: Path,
    workspace: Optional[Path] = None,
    timeoutSeconds: int = 900,
) -> Dict[str, Any]:
    """在独立子进程中运行全探针，返回 JSON 结论（逐项三态 + 生效数据根）。

    隔离机制与计划书 §3.5 ShadowVerify 同款：子进程注入
    ``NEUROVA_DATA_DIR=<dataRoot>``（core/data_root 是唯一注入口），
    子进程内所有模块在**导入期**冻结的就是隔离根——与生产数据根物理隔离。
    子进程崩溃/未产出结论时抛 RuntimeError（stderr 尾部随行），绝不把
    "没跑成"包装成任何一种判据结论。
    """
    dataRoot = Path(dataRoot)
    workspace = Path(workspace) if workspace is not None else _REPO_ROOT
    payload = json.dumps(
        {"workspace": str(workspace), "dataRoot": str(dataRoot)},
        ensure_ascii=False,
    )
    childEnv = dict(os.environ)
    childEnv["NEUROVA_DATA_DIR"] = str(dataRoot)
    childEnv["PYTHONIOENCODING"] = "utf-8"
    # 子进程是**生产形态**的探针，不是 pytest 会话：剥掉父进程（跑测进程）
    # 带进来的 pytest 会话标记，否则 storage_fence 这类 pytest-only 围栏会在
    # 子进程里把"隔离数据根"误当生产目录拦截，启动日志凭空多出 ERROR——
    # 那是测试围栏的误伤，不是被测系统跑不起来。
    for pytestMarker in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION"):
        childEnv.pop(pytestMarker, None)

    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", payload],
        cwd=str(workspace),
        env=childEnv,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeoutSeconds,
    )
    for line in (proc.stdout or "").splitlines():
        if line.startswith(_JSON_SENTINEL):
            result = json.loads(line[len(_JSON_SENTINEL):])
            result["childReturnCode"] = proc.returncode
            return result
    raise RuntimeError(
        f"存活探针子进程未返回 JSON 结论（exit={proc.returncode}）"
        f" stderr 尾部: {(proc.stderr or '')[-800:]}"
    )


def _childMain(payloadJson: str) -> int:
    """``--child`` 入口：跑全探针并回传 JSON（父进程经 runIsolated 调用）。"""
    payload = json.loads(payloadJson)
    workspace = Path(payload.get("workspace") or _REPO_ROOT)
    dataRoot = Path(payload["dataRoot"])
    verdicts = SurvivalProbe().probe(workspace, dataRoot)

    from neurova.core.data_root import get_data_root

    result = {
        "verdicts": [verdict.to_dict() for verdict in verdicts],
        "workspace": str(workspace),
        # 回读生效数据根：证明注入真实生效（而非仍落在默认 data/）。
        "dataRoot": str(get_data_root()),
    }
    sys.stdout.write(
        _JSON_SENTINEL + json.dumps(result, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(_childMain(sys.argv[2] if len(sys.argv) > 2 else "{}"))
    raise SystemExit(
        "用法: python neurova/evolution/rsi/survival_probe.py --child <json>"
        "（正常调用走 runIsolated()）"
    )
