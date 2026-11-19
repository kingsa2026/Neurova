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
import subprocess
import threading
from typing import Any, Callable, List, Optional

from neurova.agent.neuacp.child_env import buildChildEnvironment
from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.executor import NeuacpExecResult, NeuacpSessionContext

_DEFAULT_FRAME_LIMIT = 1_000_000
_TERMINATE_WAIT_S = 5.0


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
    ) -> None:
        self._command = [str(part) for part in command]
        self._cwd = cwd or ""
        self._env_extra = dict(env_extra or {})
        self._prompt_arg = prompt_arg
        self._frame_limit = frame_limit
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()

    async def start(self, ctx: NeuacpSessionContext) -> None:
        if ctx.cwd:
            self._cwd = ctx.cwd

    async def prompt(self, task_text: str, emitter: Callable[[str, Any], None], on_permission: Callable[[str, str, str], dict]) -> NeuacpExecResult:
        command = self._command + [self._prompt_arg, task_text]
        try:
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=buildChildEnvironment(self._env_extra),
                cwd=self._cwd or None,
            )
        except OSError as exc:
            raise NeuacpError(f"无法启动插件 CLI 进程: {exc}") from exc
        with self._lock:
            self._process = proc

        accumulated: List[str] = []
        result_text = ""
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
                event_type = str(message.get("type") or "")
                if event_type == "assistant":
                    for chunk, kind in self._contentBlocks(message):
                        accumulated.append(chunk)
                        if emitter is not None:
                            try:
                                emitter(kind, chunk)
                            except Exception:
                                pass
                elif event_type == "result":
                    result_text = str(message.get("result") or message.get("text") or "")
            exit_code = proc.wait()
        finally:
            self._terminateProcess(proc)

        if exit_code not in (0, None):
            raise NeuacpError(f"plugin CLI exited with code {exit_code}")
        text = result_text or "".join(accumulated)
        if not text.strip():
            raise NeuacpError("plugin CLI produced no result")
        return NeuacpExecResult(text=text, stop_reason="end_of_turn", raw=None)

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
                    proc.wait(timeout=_TERMINATE_WAIT_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:
            pass
