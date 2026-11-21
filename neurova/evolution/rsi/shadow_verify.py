"""影子验证执行器（P1-2）—— 候选变更在隔离环境的完整判据预演。

设计出处：``docs/04-plans/2026-11-21-recursive-self-evolution-plan.md``
§2.0 总纲（候选永不直改基线）、§2.2 架构总图、§3.5 shadow_verify 完整设计、
§5 安全红线 L1/L2 层、§6 P1 批 P1-2。

定位：世代编排器（P1-3 接线）与门禁链之间的执行件。对单个候选变更在
**隔离环境**（独立子进程 + ``NEUROVA_DATA_DIR`` 注入临时数据根）应用并跑
判据面：SurvivalProbe 六判据（G0 存活）+ 可注入业务判据回调（G2 业务）。
候选永不触碰生产数据根。

隔离机制（复用 ``survival_probe.runIsolated`` 既有模式，勿复制其实现）：

- **恒等候选**（无变化）：直接调用 ``runIsolated``——探针自有子进程入口，
  隔离数据根注入与 JSON 结论回传全部复用既有实现；
- **参数/补丁候选**：本模块自有 ``--child`` 子进程入口——子进程内先应用
  候选，再复用 ``SurvivalProbe`` 本体跑六判据（判据实现全仓只有
  survival_probe 一份，本模块不重写任何判据）。子进程以 JSON 哨兵行回传
  逐项结论，契约与 ``runIsolated`` 一致（含剥离 pytest 会话标记）。

L1 参数候选：影子子进程内以「宿主类构造后覆盖」应用参数——与
``integration_manager.apply_optimization`` 的 setattr 语义一致（探针在
影子进程里按需自建 agent/宿主实例，覆盖必须落在类级构造路径上才能被
探针感知）。参数合法性以 ``RSIIntegrationManager.OPTIMIZABLE_PARAMETERS``
为唯一词表源校验，词表外的参数逐条点名报 failed，不静默丢弃。

L2 代码候选：先在 workspace 上 ``git apply --check``（只读预检，不过即
failed 点名目标文件，不起子进程）；通过后把 workspace 复制为隔离工作区、
在其中应用补丁，再以该副本为 workspace 跑探针——被验证的代码与生产代码
物理隔离，补丁永不落到真工作树。

可注入依赖（§3.5 测试同构约束）：

- ``businessCriteria``：业务判据回调 ``(change, probeVerdicts) -> GateVerdict
  | Mapping[str, GateVerdict] | Sequence[GateVerdict]``（eval_harness 决策档
  等在 P1-3 接线时注入）。默认 None 时 G2 落 unevidenced——无证据不冒充通过。
- 变更执行器：跨进程注入走 ``ShadowChange.executorRef``（"module:attr" 点
  分路径），影子子进程按引用导入并调用——离线测试由此在不真改仓库文件的
  前提下注入任意桩执行器（如让 create_app 抛错）。
- 本模块**不 import gate_chain**（并行在途件）：门禁链编排是 P1-3 的接线点，
  本件只产出逐项三态结论（``ShadowRunResult.verdicts``），供其消费。
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# 本文件既作为 ``neurova.evolution.rsi.shadow_verify`` 被导入，也作为
# ``--child`` 子进程脚本被直接运行；后者 sys.path 上没有仓库根，必须在
# 首次 import neurova 之前补上（与 survival_probe 同款引导）。
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from neurova.core.logger import get_logger
from neurova.core.data_root import repoRoot
from neurova.evolution.rsi.gate_verdict import (
    STATE_FAILED,
    STATE_PASSED,
    STATE_UNEVIDENCED,
    GateVerdict,
)
from neurova.evolution.rsi.survival_probe import SurvivalProbe, runIsolated

logger = get_logger(__name__)

__all__ = [
    "SHADOW_CHANGE_KINDS",
    "ShadowChange",
    "ShadowRunResult",
    "ShadowVerify",
    "aggregateOverall",
]

#: 候选变更类型（§3.5：L1 参数 / L2 代码 / 恒等对照）。
KIND_IDENTITY = "identity"
KIND_PARAMETER = "parameter"
KIND_PATCH = "patch"
SHADOW_CHANGE_KINDS = (KIND_IDENTITY, KIND_PARAMETER, KIND_PATCH)

#: 子进程结论行的哨兵前缀（与 survival_probe 同款机制、不同哨兵，防串行解析）。
_JSON_SENTINEL = "SHADOW_VERIFY_JSON:"

#: L2 隔离工作区复制时的剔除清单（重目录 / 运行期产物 / 仓库管理面）。
_COPY_IGNORE = (
    ".git", ".venv", "venv", "node_modules", "__pycache__", "data",
    "models", "NeurUI", ".pytest_cache", "audit-reports", ".cnb", ".github",
    "docs", "scripts",
)

#: 补丁预检与隔离应用的单次 git 调用墙钟。
_GIT_TIMEOUT_S = 120

#: L1 参数族 → 宿主类（integration_manager 参数宿主的生产类）。
#: 词表校验用 OPTIMIZABLE_PARAMETERS（唯一事实源）；这里只回答
#: 「该族参数落在哪个类的实例上」。惰性导入，避免拖重父进程导入面。
_HOST_CLASSES: Dict[str, Tuple[str, str]] = {
    "tool_memory": ("neurova.evolution.closed_loop", "AdaptiveToolWeights"),
    "sleep": ("neurova.cognitive_layers.memory_layer.sleep", "SleepConsolidation"),
    "emotion": ("neurova.cognitive_layers.memory_layer.temperature", "TemperatureEngine"),
    "experience": ("neurova.evolution.experience_feedback", "ExperienceFeedback"),
    "context": ("neurova.context.models", "TokenBudget"),
}


@dataclass(frozen=True)
class ShadowChange:
    """一个待影子验证的候选变更（§3.5 的验证对象，最小描述）。

    - ``kind="identity"``：恒等候选（无变化对照），六判据全绿即影子通过；
    - ``kind="parameter"``：L1 参数候选，``parameterOverrides`` 形如
      ``{"tool_memory": {"success_bonus": 0.2}}``（词表见
      integration_manager.OPTIMIZABLE_PARAMETERS）；
    - ``kind="patch"``：L2 代码候选，``targetFile`` 为仓库相对路径，
      ``patch`` 为 unified diff 全文。
    - ``executorRef``：可注入变更执行器的 "module:attr" 引用——影子子进程
      导入后以 ``executor(change)`` 调用，替换默认应用行为（测试注桩用，
      不真改仓库文件）。
    """

    changeId: str
    kind: str = KIND_IDENTITY
    targetId: str = ""
    parameterOverrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    targetFile: str = ""
    patch: str = ""
    executorRef: str = ""

    def __post_init__(self) -> None:
        if self.kind not in SHADOW_CHANGE_KINDS:
            raise ValueError(
                f"非法候选变更类型 {self.kind!r}，只接受 {SHADOW_CHANGE_KINDS}"
            )
        if not str(self.changeId or "").strip():
            raise ValueError("候选变更必须携带非空 changeId（证据归档的主键）")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changeId": self.changeId,
            "kind": self.kind,
            "targetId": self.targetId,
            "parameterOverrides": self.parameterOverrides,
            "targetFile": self.targetFile,
            "patch": self.patch,
            "executorRef": self.executorRef,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ShadowChange":
        return cls(
            changeId=str(raw.get("changeId", "")),
            kind=str(raw.get("kind", KIND_IDENTITY)),
            targetId=str(raw.get("targetId", "")),
            parameterOverrides=dict(raw.get("parameterOverrides") or {}),
            targetFile=str(raw.get("targetFile", "")),
            patch=str(raw.get("patch", "")),
            executorRef=str(raw.get("executorRef", "")),
        )


@dataclass(frozen=True)
class ShadowRunResult:
    """一次影子验证的产物（§3.5：随世代归档的证据包）。

    - ``verdicts``：逐项三态结论。存活判据以 criterion id 为键
      （build/health/startup/minimalChat/toolExecution/guardSubset），
      补丁预检为 ``patchApply``，参数应用为 ``parameterApply``，
      业务判据为 ``g2Business``（或回调给出的多个键）；
    - ``overall``：三态聚合（任一 failed 即 failed；否则任一 unevidenced
      即 unevidenced；否则 passed）；
    - ``dataRoot`` / ``workspace``：本次影子实际使用的隔离数据根与工作区
      （L2 时 workspace 为应用了补丁的隔离副本）——证明与生产物理隔离；
    - ``evidencePath``：判据读数 JSON 的归档落点（隔离根内，由调用方随
      世代归档后负责清理隔离根）。
    """

    changeId: str
    kind: str
    verdicts: Dict[str, GateVerdict]
    overall: str
    durationMs: int
    dataRoot: str
    workspace: str
    evidencePath: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "changeId": self.changeId,
            "kind": self.kind,
            "verdicts": {k: v.to_dict() for k, v in self.verdicts.items()},
            "overall": self.overall,
            "durationMs": self.durationMs,
            "dataRoot": self.dataRoot,
            "workspace": self.workspace,
            "evidencePath": self.evidencePath,
        }


def aggregateOverall(verdicts: Mapping[str, GateVerdict]) -> str:
    """三态聚合：failed 压倒一切；无 failed 才看 unevidenced；全绿才 passed。

    与 GateVerdict 的 ``__bool__`` 纪律同源：unevidenced 永不冒充 passed。
    """
    states = [v.state for v in verdicts.values()]
    if STATE_FAILED in states:
        return STATE_FAILED
    if STATE_UNEVIDENCED in states:
        return STATE_UNEVIDENCED
    return STATE_PASSED


class ShadowVerify:
    """影子验证执行器：对单个候选变更在隔离环境跑完整判据面。

    用法（世代编排器 / 门禁链）::

        verify = ShadowVerify(businessCriteria=evalHarnessDecisionGate)
        result = verify.verify(change)
        if result.overall != "passed":
            ...  # 影子失败 → 候选自动淘汰（总纲：跑不通不落基线）

    线程安全性：本类无可变共享状态，多候选可并发 verify（各自独立隔离根）。
    """

    def __init__(
        self,
        businessCriteria: Optional[Any] = None,
        workspace: Optional[Path] = None,
        extraSysPath: Sequence[str] = (),
        timeoutSeconds: int = 900,
    ):
        """
        Args:
            businessCriteria: G2 业务判据回调
                ``(change, probeVerdicts) -> GateVerdict | Mapping | Sequence``。
                None 时 G2 落 unevidenced（无证据不冒充通过）。
            workspace: 被检代码工作区根（默认仓库根）。L2 补丁的
                ``git apply --check`` 在此执行；隔离副本亦由此复制。
            extraSysPath: 追加进影子子进程 sys.path 的目录（供 executorRef
                指向的注入执行器被导入；测试注桩用）。
            timeoutSeconds: 影子子进程墙钟上限（超时抛 TimeoutExpired，
                不包装成判据结论）。
        """
        self._businessCriteria = businessCriteria
        self._workspace = (
            Path(workspace) if workspace is not None else repoRoot()
        )
        self._extraSysPath = tuple(str(p) for p in extraSysPath)
        self._timeoutSeconds = int(timeoutSeconds)

    # ── 主入口 ────────────────────────────────────────────────

    def verify(self, change: Any) -> ShadowRunResult:
        """对单个候选变更在隔离环境执行验证，返回逐项三态结论。

        隔离保证：候选的应用与判据执行只发生在独立子进程 + 临时数据根
        （及 L2 的隔离工作区副本）里，生产数据根与真工作树零写入。
        """
        started = time.monotonic()
        if isinstance(change, ShadowChange):
            candidate = change
        elif isinstance(change, Mapping):
            candidate = ShadowChange.from_dict(change)
        else:
            raise ValueError(
                f"verify 只接受 ShadowChange 或其 dict 载荷，收到 {type(change).__name__}"
            )

        dataRoot = Path(tempfile.mkdtemp(prefix="neurovaShadow-"))
        verdicts: Dict[str, GateVerdict] = {}
        workspaceForProbe = self._workspace

        if candidate.kind == KIND_PATCH:
            patchVerdict, workspaceForProbe = self._preparePatchWorkspace(
                candidate, dataRoot
            )
            verdicts["patchApply"] = patchVerdict
            if not patchVerdict:
                # 短路：补丁进不了隔离工作区，没资格参评任何判据（不起子进程）
                return self._assemble(
                    candidate, verdicts, dataRoot, workspaceForProbe, started
                )

        probeVerdicts, childInfo = self._runProbe(candidate, dataRoot, workspaceForProbe)
        verdicts.update(probeVerdicts)

        if candidate.kind == KIND_PARAMETER:
            verdicts["parameterApply"] = self._parameterApplyVerdict(childInfo)

        for key, verdict in self._businessVerdicts(candidate, probeVerdicts).items():
            verdicts[key] = verdict

        return self._assemble(
            candidate, verdicts, dataRoot, workspaceForProbe, started,
            childInfo=childInfo,
        )

    # ── 探针执行（隔离子进程） ────────────────────────────────

    def _runProbe(
        self, change: ShadowChange, dataRoot: Path, workspace: Path
    ) -> Tuple[Dict[str, GateVerdict], Dict[str, Any]]:
        """在隔离子进程跑六判据；返回（逐项结论, 子进程附加信息）。

        恒等候选（无注入执行器）直接复用 ``runIsolated`` 既有入口；
        其余（参数覆盖 / 补丁 / 注入执行器）走本模块 ``--child`` 入口——
        子进程内先应用候选再复用 ``SurvivalProbe`` 本体。
        """
        if change.kind == KIND_IDENTITY and not change.executorRef:
            result = runIsolated(
                dataRoot, workspace=workspace, timeoutSeconds=self._timeoutSeconds
            )
            result.setdefault("appliedPaths", [])
            result.setdefault("unappliedPaths", [])
        else:
            payload = {
                "workspace": str(workspace),
                "dataRoot": str(dataRoot),
                "change": change.to_dict(),
                "sysPath": [str(workspace), *self._extraSysPath],
            }
            result = self._spawnChild(payload, workspace)

        verdicts: Dict[str, GateVerdict] = {}
        for index, item in enumerate(result.get("verdicts") or []):
            verdict = GateVerdict.of(
                state=str(item.get("state", STATE_PASSED)),
                reason=str(item.get("reason", "")),
                evidence=item.get("evidence"),
            )
            evidence = item.get("evidence") or {}
            key = evidence.get("criterion") if isinstance(evidence, Mapping) else None
            verdicts[str(key or f"criterion[{index}]")] = verdict
        return verdicts, {
            "appliedPaths": list(result.get("appliedPaths") or []),
            "unappliedPaths": list(result.get("unappliedPaths") or []),
            "dataRoot": str(result.get("dataRoot", "")),
        }

    def _spawnChild(
        self, payload: Dict[str, Any], workspace: Path
    ) -> Dict[str, Any]:
        """起影子子进程（apply-then-probe），回传 JSON 结论。

        子进程脚本取**被检工作区**里的本文件（L2 时即隔离副本）——保证
        子进程导入的 neurova 代码就是被验证的那一份。崩溃/未产出结论时
        抛 RuntimeError（stderr 尾部随行），绝不把"没跑成"包装成判据结论。
        """
        childScript = Path(workspace) / "neurova" / "evolution" / "rsi" / "shadow_verify.py"
        if not childScript.exists():
            childScript = Path(__file__).resolve()
        payloadJson = json.dumps(payload, ensure_ascii=False)

        childEnv = dict(os.environ)
        childEnv["NEUROVA_DATA_DIR"] = str(payload["dataRoot"])
        childEnv["PYTHONIOENCODING"] = "utf-8"
        previousPythonPath = childEnv.get("PYTHONPATH")
        childEnv["PYTHONPATH"] = (
            str(workspace)
            + (os.pathsep + previousPythonPath if previousPythonPath else "")
        )
        # 子进程是生产形态的影子验证，不是 pytest 会话：剥离跑测进程带来的
        # pytest 会话标记（与 runIsolated 同款，防 pytest-only 围栏误伤）。
        for pytestMarker in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION"):
            childEnv.pop(pytestMarker, None)

        try:
            proc = subprocess.run(
                [sys.executable, str(childScript), "--child", payloadJson],
                cwd=str(workspace),
                env=childEnv,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeoutSeconds,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"影子验证子进程 {self._timeoutSeconds}s 内未完成"
                f"（changeId={payload['change']['changeId']}）"
            )
        for line in (proc.stdout or "").splitlines():
            if line.startswith(_JSON_SENTINEL):
                result = json.loads(line[len(_JSON_SENTINEL):])
                result["childReturnCode"] = proc.returncode
                return result
        raise RuntimeError(
            f"影子验证子进程未返回 JSON 结论（exit={proc.returncode}）"
            f" stderr 尾部: {(proc.stderr or '')[-800:]}"
        )

    # ── L2 补丁：预检 + 隔离工作区应用 ────────────────────────

    def _preparePatchWorkspace(
        self, change: ShadowChange, dataRoot: Path
    ) -> Tuple[GateVerdict, Path]:
        """git apply --check 预检 → 隔离副本上应用补丁。

        预检在 workspace 上只读执行（不改工作树/索引）；通过后复制出
        隔离工作区并在其中应用补丁——补丁永不落到真工作树。
        返回（patchApply 判据, 探针应使用的工作区）。
        """
        targetFile = str(change.targetFile or "").strip()
        patch = str(change.patch or "")
        evidenceBase: Dict[str, Any] = {"gate": "patchApply", "targetFile": targetFile}

        if not targetFile or not patch.strip():
            return (
                GateVerdict.failed(
                    "补丁判据失败: 缺少目标文件或补丁内容", evidence=evidenceBase
                ),
                self._workspace,
            )
        target = Path(targetFile)
        if target.is_absolute() or ".." in target.parts:
            return (
                GateVerdict.failed(
                    f"补丁判据失败: 非法目标路径 {targetFile}（须为仓库内相对路径）",
                    evidence=evidenceBase,
                ),
                self._workspace,
            )
        if not (self._workspace / target).exists():
            return (
                GateVerdict.failed(
                    f"补丁判据失败: 目标文件在工作区不存在 {targetFile}",
                    evidence=evidenceBase,
                ),
                self._workspace,
            )

        check = self._gitApply(change.patch, self._workspace, checkOnly=True)
        if check.returncode != 0:
            detail = self._gitErrorHeadline(check)
            return (
                GateVerdict.failed(
                    f"补丁判据失败: git apply --check 未通过（目标 {targetFile}）: {detail}",
                    evidence={**evidenceBase, "gitExit": check.returncode},
                ),
                self._workspace,
            )

        workspaceCopy = dataRoot / "workspace"
        shutil.copytree(
            self._workspace,
            workspaceCopy,
            ignore=shutil.ignore_patterns(*_COPY_IGNORE),
            ignore_dangling_symlinks=True,
        )
        applyOut = self._gitApply(change.patch, workspaceCopy, checkOnly=False)
        if applyOut.returncode != 0:
            detail = self._gitErrorHeadline(applyOut)
            return (
                GateVerdict.failed(
                    f"补丁判据失败: 隔离工作区应用补丁未通过（目标 {targetFile}）: {detail}",
                    evidence={**evidenceBase, "gitExit": applyOut.returncode},
                ),
                self._workspace,
            )
        return (
            GateVerdict.passed(
                f"补丁判据通过: git apply --check 通过，补丁已应用在隔离工作区"
                f"（目标 {targetFile}）",
                evidence=evidenceBase,
            ),
            workspaceCopy,
        )

    @staticmethod
    def _gitApply(patch: str, cwd: Path, *, checkOnly: bool) -> subprocess.CompletedProcess:
        # 传输委托 neurova.core.git_runner（二进制 transport）：文本模式会把补丁
        # 里的 \n 翻译成 \r\n 再进管道，--check 对 LF 工作区文件必假失败
        # （Windows 三坑同款；P2-1 生效通道依赖本预检，按教义第 5 条一并收口）。
        from neurova.core.git_runner import run_git

        command = ["apply"]
        if checkOnly:
            command.append("--check")
        command.append("-")
        return run_git(*command, cwd=str(cwd), stdin=patch, timeout=_GIT_TIMEOUT_S)

    @staticmethod
    def _gitErrorHeadline(proc: subprocess.CompletedProcess) -> str:
        raw = (proc.stderr or b"") + (proc.stdout or b"")
        text = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[0] if lines else f"exit={proc.returncode}"

    # ── L1 参数：词表核验与结论 ───────────────────────────────

    @staticmethod
    def _parameterApplyVerdict(childInfo: Mapping[str, Any]) -> GateVerdict:
        unapplied = list(childInfo.get("unappliedPaths") or [])
        applied = list(childInfo.get("appliedPaths") or [])
        if unapplied:
            return GateVerdict.failed(
                f"参数应用判据失败: 以下参数不在可优化词表或族未知，未应用: "
                f"{', '.join(unapplied)}",
                evidence={
                    "gate": "parameterApply",
                    "unapplied": unapplied,
                    "applied": applied,
                },
            )
        return GateVerdict.passed(
            f"参数应用判据通过: 影子进程内已应用 {len(applied)} 项参数覆盖",
            evidence={"gate": "parameterApply", "applied": applied},
        )

    # ── G2 业务判据（可注入回调） ─────────────────────────────

    def _businessVerdicts(
        self, change: ShadowChange, probeVerdicts: Mapping[str, GateVerdict]
    ) -> Dict[str, GateVerdict]:
        """业务判据回调归一化为 dict；回调异常 = failed（诚实点名）。"""
        if self._businessCriteria is None:
            return {
                "g2Business": GateVerdict.unevidenced(
                    "G2 业务判据无法取证: 未注入业务判据回调"
                    "（eval_harness 决策档等）——无证据不冒充通过",
                    evidence={"gate": "g2Business"},
                )
            }
        try:
            outcome = self._businessCriteria(change, dict(probeVerdicts))
        except Exception as exc:  # noqa: BLE001 - 判据回调崩塌 = 该判据 failed
            return {
                "g2Business": GateVerdict.failed(
                    f"G2 业务判据失败: 回调异常 {type(exc).__name__}: {exc}",
                    evidence={"gate": "g2Business"},
                )
            }
        if isinstance(outcome, GateVerdict):
            return {"g2Business": outcome}
        if isinstance(outcome, Mapping):
            normalized = {str(k): _coerceVerdict(v, k) for k, v in outcome.items()}
            if not normalized:
                raise ValueError("业务判据回调返回了空映射（至少给一条结论）")
            return normalized
        if isinstance(outcome, Sequence) and not isinstance(outcome, (str, bytes)):
            items = list(outcome)
            if not items:
                raise ValueError("业务判据回调返回了空序列（至少给一条结论）")
            return {
                f"g2Business[{index}]": _coerceVerdict(item, index)
                for index, item in enumerate(items)
            }
        raise ValueError(
            f"业务判据回调返回类型不支持: {type(outcome).__name__}"
            "（只接受 GateVerdict / Mapping[str, GateVerdict] / Sequence[GateVerdict]）"
        )

    # ── 产物装配 ──────────────────────────────────────────────

    def _assemble(
        self,
        change: ShadowChange,
        verdicts: Dict[str, GateVerdict],
        dataRoot: Path,
        workspace: Path,
        started: float,
        childInfo: Optional[Mapping[str, Any]] = None,
    ) -> ShadowRunResult:
        overall = aggregateOverall(verdicts)
        durationMs = int((time.monotonic() - started) * 1000)
        evidencePath = self._archiveEvidence(
            dataRoot, change, verdicts, overall, workspace, childInfo
        )
        return ShadowRunResult(
            changeId=change.changeId,
            kind=change.kind,
            verdicts=verdicts,
            overall=overall,
            durationMs=durationMs,
            dataRoot=str(dataRoot),
            workspace=str(workspace),
            evidencePath=str(evidencePath),
        )

    @staticmethod
    def _archiveEvidence(
        dataRoot: Path,
        change: ShadowChange,
        verdicts: Dict[str, GateVerdict],
        overall: str,
        workspace: Path,
        childInfo: Optional[Mapping[str, Any]],
    ) -> Path:
        """判据读数 JSON 落隔离根（§3.5：验证产物随世代归档）。失败告警不抛。"""
        target = dataRoot / "shadowEvidence" / f"{_safeFileName(change.changeId)}.json"
        payload = {
            "change": change.to_dict(),
            "overall": overall,
            "verdicts": {k: v.to_dict() for k, v in verdicts.items()},
            "workspace": str(workspace),
            "dataRoot": str(dataRoot),
            "appliedPaths": list((childInfo or {}).get("appliedPaths") or []),
            "unappliedPaths": list((childInfo or {}).get("unappliedPaths") or []),
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("影子验证证据归档失败(%s): %s", target, exc)
            return Path("")
        return target


def _coerceVerdict(value: Any, key: Any) -> GateVerdict:
    if isinstance(value, GateVerdict):
        return value
    if isinstance(value, Mapping):
        return GateVerdict.of(
            state=str(value.get("state", STATE_PASSED)),
            reason=str(value.get("reason", "")),
            evidence=value.get("evidence"),
        )
    raise ValueError(
        f"业务判据回调的第 {key!r} 项不是 GateVerdict: {type(value).__name__}"
    )


def _safeFileName(name: str) -> str:
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "-_.") else "_" for ch in str(name)
    )
    return cleaned or "change"


# ---------------------------------------------------------------------------
# 影子子进程入口（apply-then-probe）
# ---------------------------------------------------------------------------

def _applyChangeInChild(change: ShadowChange) -> Tuple[List[str], List[str]]:
    """在影子子进程内应用候选变更，返回（已应用路径, 未应用路径）。

    - 注入执行器（executorRef）：按 "module:attr" 导入后以 executor(change)
      调用——测试由此在不真改仓库文件的前提下注入任意桩（如让 create_app
      抛错），桩只存在于影子子进程内；
    - 参数候选：宿主类构造后覆盖（语义对齐 apply_optimization 的 setattr）；
    - 补丁候选：父进程已把补丁应用在隔离工作区副本上，子进程无需再动。
    """
    if change.executorRef:
        modulePath, _, attr = change.executorRef.partition(":")
        if not modulePath or not attr:
            raise ValueError(
                f"executorRef 须为 'module:attr' 形态，收到 {change.executorRef!r}"
            )
        executor = getattr(importlib.import_module(modulePath), attr)
        executor(change)
        return [change.executorRef], []
    if change.kind == KIND_PARAMETER:
        return _applyParameterOverrides(change.parameterOverrides)
    return [], []


def _applyParameterOverrides(
    overrides: Mapping[str, Mapping[str, Any]]
) -> Tuple[List[str], List[str]]:
    """把候选参数覆盖钉到宿主类的构造路径上（影子进程内生效）。

    词表唯一源 = ``RSIIntegrationManager.OPTIMIZABLE_PARAMETERS``；族→宿主类
    映射见 ``_HOST_CLASSES``。词表外参数逐条记入未应用名单（调用方落 failed
    点名），不静默丢弃。
    """
    from neurova.evolution.rsi.integration_manager import RSIIntegrationManager

    vocabulary = RSIIntegrationManager.OPTIMIZABLE_PARAMETERS
    applied: List[str] = []
    unapplied: List[str] = []
    patched: Dict[type, Dict[str, Any]] = {}

    for system, params in (overrides or {}).items():
        familySpec = vocabulary.get(system)
        hostRef = _HOST_CLASSES.get(system)
        if familySpec is None or hostRef is None:
            for name in (params or {}):
                unapplied.append(f"{system}.{name}（未知参数族）")
            continue
        knownNames = {p["name"] for p in familySpec}
        hostClass = getattr(importlib.import_module(hostRef[0]), hostRef[1])
        bucket = patched.setdefault(hostClass, {})
        for name, value in (params or {}).items():
            if name not in knownNames:
                unapplied.append(f"{system}.{name}（不在可优化词表）")
                continue
            bucket[name] = value
            applied.append(f"{system}.{name}")

    for hostClass, classOverrides in patched.items():
        _patchHostClassDefaults(hostClass, classOverrides)
    return applied, unapplied


def _patchHostClassDefaults(hostClass: type, overrides: Mapping[str, Any]) -> None:
    """包一层 __init__：原构造完成后以 setattr 钉上候选值。

    与 integration_manager.apply_optimization 的实例级 setattr 语义一致，
    只是挪到影子进程的构造路径上——探针随后自建的每个宿主实例都携带
    候选参数。同一类重复打补丁时合并覆盖表（影子进程生命周期内单调追加）。
    """
    appliedTable = getattr(hostClass, "_shadowOverridesApplied", None)
    if appliedTable is None:
        appliedTable = {}
        try:
            hostClass._shadowOverridesApplied = appliedTable
        except (AttributeError, TypeError):  # 个别类拒设类属性时退回逐次包裹
            appliedTable = dict(overrides)
            _wrapHostInit(hostClass, appliedTable)
            return
    appliedTable.update(overrides)
    originalInit = hostClass.__init__
    if getattr(originalInit, "_shadowPatchedFor", None) is id(appliedTable):
        return
    _wrapHostInit(hostClass, appliedTable)


def _wrapHostInit(hostClass: type, appliedTable: Dict[str, Any]) -> None:
    originalInit = hostClass.__init__

    def patchedInit(self, *args, **kwargs):
        originalInit(self, *args, **kwargs)
        for name, value in appliedTable.items():
            setattr(self, name, value)

    patchedInit._shadowPatchedFor = id(appliedTable)
    hostClass.__init__ = patchedInit


def _childMain(payloadJson: str) -> int:
    """``--child`` 入口：应用候选 → 跑全探针 → JSON 回传（父进程经 _spawnChild 调用）。"""
    payload = json.loads(payloadJson)
    workspace = Path(payload["workspace"])
    dataRoot = Path(payload["dataRoot"])
    # 注入隔离数据根（唯一注入口）。子进程内所有模块导入期冻结的就是它。
    os.environ["NEUROVA_DATA_DIR"] = str(dataRoot)
    for entry in payload.get("sysPath") or []:
        if entry and entry not in sys.path:
            sys.path.insert(0, str(entry))

    change = ShadowChange.from_dict(payload["change"])
    appliedPaths, unappliedPaths = _applyChangeInChild(change)
    verdicts = SurvivalProbe().probe(workspace, dataRoot)

    from neurova.core.data_root import get_data_root

    result = {
        "verdicts": [verdict.to_dict() for verdict in verdicts],
        "workspace": str(workspace),
        # 回读生效数据根：证明注入真实生效（而非仍落在默认 data/）。
        "dataRoot": str(get_data_root()),
        "appliedPaths": appliedPaths,
        "unappliedPaths": unappliedPaths,
    }
    sys.stdout.write(_JSON_SENTINEL + json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        raise SystemExit(_childMain(sys.argv[2] if len(sys.argv) > 2 else "{}"))
    raise SystemExit(
        "用法: python neurova/evolution/rsi/shadow_verify.py --child <json>"
        "（正常调用走 ShadowVerify.verify()）"
    )
