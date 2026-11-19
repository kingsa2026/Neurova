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
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.agent.neuacp.acp_client import NeuacpClient
from neurova.agent.neuacp.catalog import listCatalog
from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 路由级鉴权：外部代理管理面整体先过身份门，admin 门在逐端点收紧
router = APIRouter(dependencies=[Depends(get_current_user)])

#: 连通测试超时（设计文档 §4.7：30s）
TEST_TIMEOUT_S = 30.0
_PLUGIN_TERMINATE_WAIT_S = 5.0

#: 执行体类型分派（kind 取值唯一事实源，与名册 NeuacpExecutorSpec 同口径）
VALID_KINDS = ("acp", "plugin")


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
                proc.wait(timeout=_PLUGIN_TERMINATE_WAIT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
    except Exception:
        pass
