# -*- coding: utf-8 -*-
"""NeuacpPluginExecutor：无 ACP 但有 headless CLI 的外部代理插件执行体。

首个落地对象 = ZCode（设计文档 §4.10 专项）：以受控子进程驱动
``zcode --prompt <任务> --output-format stream-json ...``，消费 NDJSON
事件流（type=assistant→content/thinking→reasoning、type=result→结果文本），
``type:"result"`` 为正常终行；事件 schema 无公开文档，解析对未知字段/行
宽容（不认识的行忽略）。单向管道：无运行中审批交互——权限在派活前收口
（命令行 --disallowed-tools 收权 + 本仓审批链对任务书把关）。
"""
import json
import shutil
import subprocess
import threading
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpSessionContext
from neurova.agent.neuacp.process_governance import TIMEOUT_MATRIX
from neurova.agent.neuacp.redaction import redactFrame
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_FRAME_LIMIT = 1_000_000


class NeuacpPluginExecutor:
    """每次 prompt 拉起一个 CLI 子进程（无会话复用；--resume 续跑后续卡）。"""

    def __init__(
        self,
        command: List[str],
        *,
        cwd: Optional[str] = None,
        env_extra: Optional[dict] = None,
        prompt_arg: str = "--prompt",
        frame_limit: int = _DEFAULT_FRAME_LIMIT,
        transport: str = "stdio",
        remote: Optional[dict] = None,
        run_tenant_id: str = "",
    ) -> None:
        self._command = [str(part) for part in command]
        self._cwd = cwd or ""
        self._env_extra = dict(env_extra or {})
        self._prompt_arg = prompt_arg
        self._frame_limit = frame_limit
        # 传输形态（§4.8）：stdio 本机直拉；ssh 经 SSH 隧道在远端拉起同一命令。
        self._transport = str(transport or "stdio")
        self._remote = remote if isinstance(remote, dict) else None
        # C4：run 级凭据的租户段（swarm 装配期传入；run id 在 start(ctx) 时从
        # metadata 取）——每次 prompt 一进程，凭据随进程环境逐 run 注入。
        self._run_tenant_id = str(run_tenant_id or "")
        self._run_credential_context: Optional[dict] = None
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        # F2 帧留痕键（§3.2）：start(ctx) 时从 metadata["subagent_id"] 取；
        # 未绑定（空）一律不落盘——无主会话（如管理面 /test）不留痕。
        self._frame_key: Optional[str] = None

    async def start(self, ctx: NeuacpSessionContext) -> None:
        if ctx.cwd:
            self._cwd = ctx.cwd
        self._frame_key = str((ctx.metadata or {}).get("subagent_id") or "").strip() or None
        subagent_id = self._frame_key
        self._run_credential_context = (
            {"run_id": subagent_id, "tenant_id": self._run_tenant_id}
            if subagent_id and self._run_tenant_id else None)

    async def prompt(self, task_text: str, emitter: Callable[[str, Any], None], on_permission: Callable[[str, str, str], dict]) -> NeuacpExecResult:
        command = self._command + [self._prompt_arg, task_text]
        # 命令行守卫（与 /test 面同一判据）：shell 解释器头在拉起前拒绝。
        from neurova.agent.neuacp.command_guard import refuseCommandArgv

        violations = refuseCommandArgv(command)
        if violations:
            raise NeuacpError("外部代理启动命令被守卫拒绝: " + "；".join(violations))
        child_env = buildChildEnvironment(
            self._env_extra, run_credential_context=self._run_credential_context)
        # Windows：PATH 里的 CLI 可能是 .cmd/.bat，Popen 不做 PATHEXT 解析。
        # transport=ssh：先包装成 ssh 前缀命令（§4.8，缺 remote/凭据 fail-closed），
        # ssh.exe 本身在 PATH，同样走 which 解析。
        if self._transport != "stdio":
            from neurova.agent.neuacp.ssh_transport import resolveSpawnCommand

            # D2/D3 远程身份路由：OpenSSH 不转发任意本地 env，C4 的 run 凭据
            # 必须显式走远端命令面才能到达远程成员进程（缺省无凭据零前缀）。
            remote_env = {}
            run_credential = child_env.get("NEUROVA_RUN_CREDENTIAL")
            if run_credential:
                remote_env["NEUROVA_RUN_CREDENTIAL"] = run_credential
            command = resolveSpawnCommand(command, self._transport, self._remote,
                                          remote_env=remote_env)
        resolved_head = shutil.which(command[0]) if command else None
        if resolved_head:
            command[0] = resolved_head
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                cwd=self._cwd or None,
            )
        except OSError as exc:
            raise NeuacpError(f"无法启动插件 CLI 进程: {exc}") from exc
        with self._lock:
            self._process = proc
        # spawn 成功后留痕（§3.2）：命令不含凭据（凭据走 env 白名单 child_env.py）。
        self._recordFrame("out", {"type": "argv", "command": list(command)})

        result_text = ""
        result_frame: Optional[dict] = None
        saw_result = False
        exit_code: Optional[int] = None
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                if len(line) > self._frame_limit:
                    raise NeuacpError(f"plugin frame limit exceeded: {len(line)}")
                try:
                    message = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue  # 事件 schema 无公开文档：无法解析的行忽略（宽容容错）
                if not isinstance(message, dict):
                    continue
                # 入站帧留痕（§3.2）：解析成功的 NDJSON 行，fail-open 不阻断消费。
                self._recordFrame("in", message)
                event_type = str(message.get("type") or "")
                if event_type == "assistant":
                    for chunk, kind in self._contentBlocks(message):
                        if emitter is not None:
                            try:
                                emitter(kind, chunk)
                            except Exception:
                                pass
                elif event_type == "result":
                    saw_result = True
                    result_frame = message
                    result_text = str(message.get("result") or message.get("text") or "")
            exit_code = proc.wait()
            # 退出观测点（§3.2）：退出码先进 frames 流，再走非零退出报错；不猜不补。
            self._recordFrame("observed", {"type": "exited", "exit_code": exit_code})
        finally:
            self._terminateProcess(proc)

        if exit_code not in (0, None):
            raise NeuacpError(f"plugin CLI exited with code {exit_code}")
        if not saw_result:
            # F3 拍板 D-B：无 result 帧 = runtime 未报告结果 = 诚实失败。
            # 禁止用累积 chunk 拼接冒充结果（chunk 已实时经 emitter 进 contentBuffer，
            # 失败交接链路自会取尾部作部分报告）。
            raise NeuacpError("plugin CLI ended without result frame")
        if not result_text.strip():
            raise NeuacpError("plugin CLI produced no result")
        # raw 回填 result 帧原文（写盘/出口同口径脱敏，拍板 D-A）。
        return NeuacpExecResult(
            text=result_text,
            stop_reason="end_of_turn",
            raw=redactFrame(result_frame) if result_frame is not None else None,
        )

    async def cancel(self) -> None:
        with self._lock:
            proc = self._process
        if proc is not None and proc.poll() is None:
            self._terminateProcess(proc)

    async def close(self) -> None:
        with self._lock:
            proc = self._process
            self._process = None
        if proc is not None:
            self._terminateProcess(proc)

    # ---------- 内部 ----------

    def _recordFrame(self, direction: str, frame: dict) -> None:
        """帧留痕钩子（§3.2）：fail-open，绝不阻断 prompt 主流程；未绑定不落盘。"""
        key = self._frame_key
        if not key:
            return
        try:
            from neurova.agent.neuacp.frame_log import appendFrame

            appendFrame(key, direction, frame)
        except Exception as exc:  # noqa: BLE001 - 留痕故障只记日志，不上抛
            logger.debug("帧留痕失败（fail-open）: %s", exc)

    @staticmethod
    def _contentBlocks(message: dict):
        """assistant 事件的 content 块展平为 (text, kind)；text→content、thinking→reasoning。"""
        message_body = message.get("message") or {}
        for block in (message_body.get("content") or []):
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            text = str(block.get("text") or block.get("thinking") or "")
            if not text:
                continue
            yield text, ("reasoning" if block_type == "thinking" else "content")

    def _terminateProcess(self, proc: subprocess.Popen) -> None:
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
