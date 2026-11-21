# -*- coding: utf-8 -*-
"""外部编码代理管理面（设计文档 §4.7，B4 卡）。

- GET  /v1/external-agents/catalog  工具目录：内置预设 + 本机安装探测。
  CLI 安装检查在用户启用连接时实时进行（shutil.which）；未装返回
  ``installed=false`` + ``install_hint``，部署期不预装不强校验。
- POST /v1/external-agents/test     握手级连通测试（前端「测试连接」按钮）：
  ACP 做 initialize 往返（版本协商 fail-closed）；plugin 起进程收到首个
  合法 JSON 行即视为可达。超时 30s，进程必须清理。
  返回 ``{ok, protocolVersion?, serverCapabilities?, error?}``。
- GET  /v1/external-agents/status   进程池状态（B3 落地前为占位，落地后如实读）。
- GET  /v1/external-agents/runs/{subagent_id}/frames
                                      帧账本读面（F2，设计文档 §3.2，拍板 D-C）：
                                      按 seq 游标回放一次 run 的原生帧（脱敏后
                                      留痕，永不合成/推断）。admin 门 + 同租户
                                      校验（§6.4 红线）：跨租户 404 不泄露存在性
                                      （与 teams 口径一致）。

鉴权：整路由挂 ``get_current_user``，逐端点要求 ``role==admin``——外部编码
代理是本机进程派生面（对齐 webhook 管理面教训：外部执行面必须有属主/角色门），
非 admin 403。

握手探测为什么直驱 ``NeuacpClient``/子进程而不走会话执行体：
``NeuacpStdioExecutor``/``NeuacpPluginExecutor`` 面向完整 session/prompt
生命周期（会真派任务、消费事件流）；连通探测只验「进程起得来、协议说得通」，
取到 initialize 结果/首个合法 JSON 行即收，不派任务、不留进程。
"""
import asyncio
import json
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.agent.neuacp.acp_client import NeuacpClient
from neurova.agent.neuacp.catalog import EXECUTOR_KINDS, listCatalog
from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.agent.neuacp.process_governance import TIMEOUT_MATRIX
from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 路由级鉴权：外部代理管理面整体先过身份门，admin 门在逐端点收紧
router = APIRouter(dependencies=[Depends(get_current_user)])

#: 连通测试超时（设计文档 §4.7：30s）
TEST_TIMEOUT_S = 30.0

#: 执行体类型分派：kind 取值收口到 catalog.EXECUTOR_KINDS 单源
#: （与名册 NeuacpExecutorSpec、能力校验 refuseExecutorSpec 同一口径，教义第 6 条）
VALID_KINDS = EXECUTOR_KINDS


async def requireAdmin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """admin 门：外部编码代理管理面仅限管理员，非 admin 403。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="外部编码代理管理面仅限管理员（admin）")
    return current_user


class ExternalAgentTestRequest(BaseModel):
    """连通测试请求：与名册 ``NeuacpExecutorSpec`` 同一配置形状。

    ``env_keys`` 只录凭据键名不录值（凭据值运行时从凭据面按租户+agent 作用域
    取，不经管理面请求体）；握手级探测不依赖凭据，CLI 缺凭据时的失败会以
    错误原文如实返回。
    """

    kind: str = Field(default="acp", description="执行体类型：acp | plugin")
    tool: str = Field(default="", description="工具目录标识（catalog）")
    command: List[str] = Field(default_factory=list, description="启动命令 argv")
    cwd: str = Field(default="", description="外部代理工作目录")
    env_keys: List[str] = Field(default_factory=list, description="凭据键名清单（只录键名不录值）")
    permission_mode: str = Field(default="chain", description="chain（审批链）| auto（仅 L0，admin 专属）")


@router.get("/catalog")
async def getExternalAgentCatalog(current_user: Dict[str, Any] = Depends(requireAdmin)):
    """工具目录：内置预设 + 本机命令探测（installed/install_hint 供安装指引）。"""
    return listCatalog()


@router.post("/test")
async def testExternalAgent(
    body: ExternalAgentTestRequest,
    current_user: Dict[str, Any] = Depends(requireAdmin),
):
    """握手级连通测试：按 kind 探测，返回 {ok, protocolVersion?, serverCapabilities?, error?}。

    配置校验失败 → 400；连通性结果（含失败）一律 200 + ok/error 诚实回填
    （测试连接是探测动作，失败是结果不是 HTTP 错误）。
    """
    kind = str(body.kind or "").strip().lower()
    command = [str(part) for part in (body.command or []) if str(part).strip()]
    if kind not in VALID_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"未知执行体类型: {kind or '(空)'}（支持 {' | '.join(VALID_KINDS)}）",
        )
    if not command:
        raise HTTPException(status_code=400, detail="executor.command 不能为空")

    try:
        if kind == "plugin":
            return await _probePlugin(command, body.cwd, TEST_TIMEOUT_S)
        return await _probeAcp(command, body.cwd, TEST_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - 连通失败是结果不是 HTTP 错误，错误原文回填
        logger.warning("外部代理连通测试失败 kind=%s command=%s: %s", kind, command[0], exc)
        return {"ok": False, "error": str(exc)}


@router.get("/status")
async def externalAgentsStatus(current_user: Dict[str, Any] = Depends(requireAdmin)):
    """进程池状态：B3（process_pool）落地前为占位；落地后如实读池快照。"""
    try:
        from neurova.agent.neuacp import process_pool
    except ImportError:
        return {"processes": [], "note": "process pool lands with B3"}
    snapshot = getattr(process_pool, "poolStatus", None)
    if callable(snapshot):
        return snapshot()
    return {"processes": [], "note": "process pool lands with B3"}


# ---------- F2：帧账本读面（设计文档 §3.2，拍板 D-C） ----------

#: frames 读面分页边界：默认一页 200 条，上限 1000（limit 夹取 [1, 1000]）
FRAMES_LIMIT_DEFAULT = 200
FRAMES_LIMIT_MAX = 1000


def _clampFrameWindow(afterSeq: int, limit: int) -> Tuple[int, int]:
    """游标参数夹取：after_seq 负数按 0；limit 夹取 [1, 1000]，非法回落默认页宽。"""
    try:
        afterSeq = int(afterSeq)
    except (TypeError, ValueError):
        afterSeq = 0
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = FRAMES_LIMIT_DEFAULT
    return max(0, afterSeq), max(1, min(FRAMES_LIMIT_MAX, limit))


def _resolveRunTenantId(subagentId: str) -> str:
    """run 租户线索解析（§6.4 红线，双源按序，解析不到返回空串）。

    ① swarm 管理器内存 run 的 ``tenant_id``（getattr 容错——F5 字段落地前
    读取为空，不致命）；② H-4 事件账本 lineage：``readRunEvents`` 里第一条
    带 ``lineage.tenant_id`` 的事件。两处都无线索返回 ""，由调用方按
    「帧非空放行（历史存量）/ 帧也为空 404」裁决。
    """
    sid = str(subagentId or "").strip()
    if not sid:
        return ""
    # ① 内存 run：getattr 容错，管理器异常不致命（租户线索还有事件账本兜底）
    try:
        from neurova.agent.swarm import get_swarm_manager

        run = get_swarm_manager()._runs.get(sid)
        if run is not None:
            tenant = str(getattr(run, "tenant_id", "") or "")
            if tenant:
                return tenant
    except Exception:  # noqa: BLE001 - 线索解析 fail-soft，缺线索交由调用方裁决
        pass
    # ② H-4 事件账本 lineage（F5：事件统一携带谱系）
    try:
        from neurova.agent.swarm_event_log import readRunEvents

        for event in readRunEvents(sid):
            if not isinstance(event, dict):
                continue
            lineage = event.get("lineage")
            tenant = str((lineage or {}).get("tenant_id") or "")
            if tenant:
                return tenant
    except Exception:  # noqa: BLE001 - 同上，fail-soft
        pass
    return ""


@router.get("/runs/{subagent_id}/frames")
async def getSubagentRunFrames(
    subagent_id: str,
    after_seq: int = 0,
    limit: int = FRAMES_LIMIT_DEFAULT,
    current_user: Dict[str, Any] = Depends(requireAdmin),
):
    """帧账本读面：按 seq 游标回放一次 run 的原生帧（设计文档 §3.2，拍板 D-C）。

    - 数据源直连 ``frame_log.readFrames``（帧账本与 H-4 治理账本分工见设计
      文档 §4，本端点只读帧流）。
    - 同租户校验（§6.4 红线）：解析到的 run 租户非空且 != 请求者租户 → 404
      （不泄露存在性，与 teams 跨租户口径一致）；run 无任何租户线索且无帧
      记录 → 404（run 不存在或无帧记录）；帧非空但租户线索缺失（历史存量）
      → 放行（admin 门已过）。
    - 返回 ``{"subagent_id", "count", "frames"}``，frames 按 seq 升序。
    """
    sid = str(subagent_id or "").strip()
    # 请求边界写一次身份通道（AGENTS.md §3），请求者租户判定转调单源
    from neurova.core.identity_context import set_request_user_id

    set_request_user_id(str(current_user.get("user_id") or ""))
    afterSeq, effectiveLimit = _clampFrameWindow(after_seq, limit)
    from neurova.agent.neuacp.frame_log import readFrames

    frames = readFrames(sid, afterSeq=afterSeq, limit=effectiveLimit) if sid else []
    from neurova.auth.user_group_model import currentUserTenantId

    requesterTenant = currentUserTenantId()
    runTenant = _resolveRunTenantId(sid)
    if runTenant and requesterTenant and runTenant != requesterTenant:
        # 404 而非 403：不向其他租户泄露 run 存在性（teams 同口径）
        raise HTTPException(status_code=404, detail=f"Run '{sid}' not found")
    if not runTenant and not frames:
        raise HTTPException(status_code=404, detail=f"Run '{sid}' not found")
    return {"subagent_id": sid, "count": len(frames), "frames": frames}


# ---------- 握手级探测（按 kind 分派） ----------


async def _probeAcp(command: List[str], cwd: str, timeout_s: float) -> Dict[str, Any]:
    """ACP 握手：initialize 往返 + v1 版本协商（不兼容 fail-closed）。

    复用 ``NeuacpClient``（``NeuacpStdioExecutor`` 的握手层），拿到
    protocolVersion / serverCapabilities 即收；terminate 幂等，异常路径
    （含 start 内部自清理）后再兜一道，保证进程必被清理。
    """
    client = NeuacpClient(command, cwd=cwd or None, request_timeout=timeout_s)
    try:
        result = await asyncio.to_thread(client.start)
    finally:
        await asyncio.to_thread(client.terminate)
    result = result or {}
    return {
        "ok": True,
        "protocolVersion": str(result.get("protocolVersion", "")),
        "serverCapabilities": dict(result.get("serverCapabilities") or {}),
    }


async def _probePlugin(command: List[str], cwd: str, timeout_s: float) -> Dict[str, Any]:
    """插件形态握手：起进程，收到首个合法 JSON 行即视为可达（不派任务）。

    与 ``NeuacpPluginExecutor`` 同一 spawn 口径（Windows PATH 首词
    shutil.which 解析、环境白名单、OSError 显式报错）；stderr 单独排空
    防管道塞死。超时/退出/坏行都如实报错，进程必须清理。
    """
    command = list(command)
    resolved_head = shutil.which(command[0])
    if resolved_head:
        command[0] = resolved_head
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=buildChildEnvironment({}),
            cwd=cwd or None,
        )
    except OSError as exc:
        return {"ok": False, "error": f"无法启动插件 CLI 进程: {exc}"}

    first_line: Dict[str, Any] = {"raw": None}

    def _readFirstLine() -> None:
        try:
            first_line["raw"] = proc.stdout.readline()
        except Exception:
            first_line["raw"] = None

    def _drainStderr() -> None:
        try:
            for _ in proc.stderr:
                pass
        except Exception:
            pass

    threading.Thread(target=_drainStderr, daemon=True).start()
    reader = threading.Thread(target=_readFirstLine, daemon=True)
    reader.start()
    reader.join(timeout_s)
    try:
        raw = first_line["raw"]
        if raw is None:
            return {"ok": False, "error": f"插件 CLI 在 {timeout_s:g}s 内未输出任何行"}
        line = raw.strip()
        if not line:
            return {"ok": False, "error": "插件 CLI 首行为空（进程可能已退出）"}
        try:
            message = json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"ok": False, "error": "插件 CLI 首行不是合法 JSON（stream-json 契约不符）"}
        if not isinstance(message, dict):
            return {"ok": False, "error": "插件 CLI 首行 JSON 不是对象"}
        return {"ok": True}
    finally:
        _terminateProcess(proc)


def _terminateProcess(proc: subprocess.Popen) -> None:
    """进程必须清理：关 stdin → terminate → 超时 kill（与插件执行体同口径）。"""
    try:
        if proc.stdin is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=TIMEOUT_MATRIX["terminate_grace"])
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
    except Exception:
        pass
