"""Console debug endpoints; old console globals remain patchable."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from neurova.api.deps import require_admin

router = APIRouter()


@router.get("/debug/logs")
async def get_backend_debug_logs(
    lines: int = 100,
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """查看后端日志"""
    from . import console as api
    log_path = api.config.get("NEUROVA_LOG_FILE", "logs/neurova.log")
    if api.os.path.exists(log_path):
        content = api._tail_text_file(log_path, lines)
    else:
        content = "Log file not found. Set NEUROVA_LOG_FILE environment variable."
    return {"code": 0, "message": "success", "data": {"content": content, "lines": lines}}


@router.get("/debug/status")
async def get_system_status(
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """系统状态"""
    from . import console as api
    import psutil

    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        status = {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_mb": round(mem.used / 1048576),
            "memory_total_mb": round(mem.total / 1048576),
            "disk_percent": disk.percent,
            "uptime_seconds": int(api.time.time() - psutil.boot_time()),
        }
    except Exception:
        status = {
            "note": "psutil not available, showing basic info",
            "timestamp": api.datetime.datetime.now(api.datetime.timezone.utc).isoformat(),
        }
    return {"code": 0, "message": "success", "data": status}


def bind_command_endpoint(CommandRequest):
    """Bind the console-owned model once without a circular module import."""
    @router.post("/debug/command")
    async def post_debug_run_command(
        body: CommandRequest, current_user: Dict[str, Any] = Depends(require_admin())
    ,):
        """运行调试命令（仅限管理员，避免任意命令执行 / 密钥泄露）"""
        from . import console as api
        # 注意： deliberately 排除 `env` —— 它会泄露全部环境变量（含密钥/令牌），
        # 属安全敏感命令，绝不允许通过 HTTP 调试接口执行（P1-#7）。
        allowed = {"ls", "pwd", "whoami", "date", "python --version", "node --version"}
        cmd = body.command.strip()
        # 白名单精确匹配 + exec 数组执行（根因修复 2026-09-07：原 echo 前缀分支
        # 配 shell=True 可被 `echo hi; <任意命令>` 绕过，白名单形同虚设）
        if cmd not in allowed:
            raise HTTPException(status_code=403, detail=f"Command '{cmd}' not allowed. Allowed: {sorted(allowed)}")

        try:
            import shlex as _shlex

            proc = await api.asyncio.create_subprocess_exec(
                *_shlex.split(cmd), stdout=api.asyncio.subprocess.PIPE, stderr=api.asyncio.subprocess.PIPE
            )
            stdout, stderr = await api.asyncio.wait_for(proc.communicate(), timeout=10)
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "returncode": proc.returncode,
                },
            }
        except api.asyncio.TimeoutError:
            raise HTTPException(status_code=408, detail="Command timed out")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return post_debug_run_command
