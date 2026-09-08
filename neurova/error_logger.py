"""
统一错误日志模块
处理前端错误日志，以 JSONL 行式写入统一日志文件（坏行不丢全量）。
"""

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 默认错误日志目录（可被各函数 log_dir 参数覆盖）
_DEFAULT_LOG_DIR = Path("data/error_logs")

# 锁
_lock = threading.Lock()


def _resolve_log_file(log_dir: Optional[str] = None) -> Path:
    """解析日志文件路径（log_dir 注入优先，默认 data/error_logs/all_errors.log）"""
    directory = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
    return directory / "all_errors.log"


def _append_entries(log_file: Path, entries: List[Dict[str, Any]]) -> None:
    """追加条目到 JSONL 文件（自动建目录）"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_entries(log_file: Path) -> List[Dict[str, Any]]:
    """读取 JSONL 全部条目（跳过坏行与空行）"""
    if not log_file.exists():
        return []

    entries = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("跳过损坏的错误日志行")
    return entries


def write_frontend_errors(
    errors: List[Dict[str, Any]],
    user_id: str = None,
    session_id: str = None,
    metadata: Dict[str, Any] = None,
    log_dir: str = None,
) -> int:
    """
    写入前端错误日志（JSONL 追加）

    Args:
        errors: 错误列表，每个错误包含 type, message, stack, url, componentName 等字段
        user_id: 用户ID
        session_id: 会话ID
        metadata: 附加元数据
        log_dir: 日志目录（默认 data/error_logs）

    Returns:
        写入的条目数
    """
    if not errors:
        return 0

    with _lock:
        try:
            log_file = _resolve_log_file(log_dir)
            timestamp = datetime.datetime.now().isoformat()

            entries = []
            for error in errors:
                entries.append(
                    {
                        "source": "frontend",
                        "level": "ERROR",
                        "timestamp": error.get("timestamp", timestamp),
                        "type": error.get("type", "unknown"),
                        "message": error.get("message", ""),
                        "stack": error.get("stack", ""),
                        "url": error.get("url", ""),
                        "line": error.get("line"),
                        "column": error.get("column"),
                        "component": error.get("componentName", ""),
                        "user_agent": error.get("userAgent", ""),
                        "user_id": user_id,
                        "session_id": session_id,
                        "metadata": metadata or {},
                    }
                )

            _append_entries(log_file, entries)
            return len(entries)

        except Exception as e:
            logger.error("写入前端错误日志失败: %s", e)
            return 0


def read_all_errors(
    limit: int = 100,
    error_type: str = None,
    user_id: str = None,
    start_time: str = None,
    end_time: str = None,
    log_dir: str = None,
) -> List[Dict[str, Any]]:
    """
    读取所有错误日志

    Args:
        limit: 返回数量限制
        error_type: 错误类型过滤
        user_id: 用户ID过滤
        start_time: 开始时间过滤（ISO格式）
        end_time: 结束时间过滤（ISO格式）
        log_dir: 日志目录

    Returns:
        错误日志列表
    """
    with _lock:
        try:
            entries = _read_entries(_resolve_log_file(log_dir))

            filtered = []
            for log in entries:
                if error_type and log.get("type") != error_type:
                    continue
                if user_id and log.get("user_id") != user_id:
                    continue
                log_time = log.get("timestamp", "")
                if start_time and log_time < start_time:
                    continue
                if end_time and log_time > end_time:
                    continue
                filtered.append(log)

            return filtered[-limit:] if limit else filtered

        except Exception as e:
            logger.error("读取错误日志失败: %s", e)
            return []


def clear_errors(before_time: str = None, error_type: str = None, log_dir: str = None) -> bool:
    """
    清空错误日志

    Args:
        before_time: 清除此时间之前的日志（ISO格式）
        error_type: 清除指定类型的日志
        log_dir: 日志目录

    Returns:
        是否清除成功
    """
    with _lock:
        try:
            log_file = _resolve_log_file(log_dir)

            if not log_file.exists():
                return True

            if before_time is None and error_type is None:
                # 全清：截断文件内容
                log_file.write_text("", encoding="utf-8")
                logger.info("已清空所有错误日志")
                return True

            entries = _read_entries(log_file)
            remaining = []
            for log in entries:
                keep = True
                if before_time and log.get("timestamp", "") < before_time:
                    keep = False
                if error_type and log.get("type") == error_type:
                    keep = False
                if keep:
                    remaining.append(log)

            with open(log_file, "w", encoding="utf-8") as f:
                for entry in remaining:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            logger.info("清除了 %s 条错误日志", len(entries) - len(remaining))
            return True

        except Exception as e:
            logger.error("清除错误日志失败: %s", e)
            return False


def get_error_stats(log_dir: str = None) -> Dict[str, Any]:
    """
    获取错误统计信息

    Returns:
        统计信息字典
    """
    with _lock:
        try:
            entries = _read_entries(_resolve_log_file(log_dir))

            if not entries:
                return {"total_errors": 0, "by_type": {}, "by_user": {}, "latest_error": None}

            by_type: Dict[str, int] = {}
            by_user: Dict[str, int] = {}
            for log in entries:
                error_type = log.get("type", "unknown")
                by_type[error_type] = by_type.get(error_type, 0) + 1
                uid = log.get("user_id") or "anonymous"
                by_user[uid] = by_user.get(uid, 0) + 1

            return {
                "total_errors": len(entries),
                "by_type": by_type,
                "by_user": by_user,
                "latest_error": entries[-1],
                "log_file": str(_resolve_log_file(log_dir)),
            }

        except Exception as e:
            logger.error("获取错误统计失败: %s", e)
            return {"error": str(e)}


def delete_log_file(log_dir: str = None) -> bool:
    """
    删除错误日志文件

    Returns:
        是否删除成功
    """
    with _lock:
        try:
            log_file = _resolve_log_file(log_dir)
            if log_file.exists():
                log_file.unlink()
                logger.info("错误日志文件已删除")
            return True
        except Exception as e:
            logger.error("删除错误日志文件失败: %s", e)
            return False
