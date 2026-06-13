"""
统一错误日志模块
处理前端错误日志，并写入统一日志文件
"""

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 错误日志目录
_error_log_dir = Path("data/error_logs")
_error_log_dir.mkdir(parents=True, exist_ok=True)

# 错误日志文件
_error_log_file = _error_log_dir / "frontend_errors.json"

# 锁
_lock = threading.Lock()


def write_frontend_errors(
    errors: List[Dict[str, Any]], user_id: str = None, session_id: str = None, metadata: Dict[str, Any] = None
) -> bool:
    """
    写入前端错误日志到统一日志文件

    Args:
        errors: 错误列表，每个错误包含 type, message, stack, url, line, column 等字段
        user_id: 用户ID
        session_id: 会话ID
        metadata: 附加元数据

    Returns:
        是否写入成功
    """
    with _lock:
        try:
            # 加载现有日志
            existing_logs = _load_logs()

            # 构建日志条目
            timestamp = datetime.datetime.now().isoformat()

            for error in errors:
                log_entry = {
                    "timestamp": timestamp,
                    "user_id": user_id,
                    "session_id": session_id,
                    "type": error.get("type", "unknown"),
                    "message": error.get("message", ""),
                    "stack": error.get("stack", ""),
                    "url": error.get("url", ""),
                    "line": error.get("line"),
                    "column": error.get("column"),
                    "user_agent": error.get("userAgent", ""),
                    "metadata": metadata or {},
                }

                existing_logs.append(log_entry)

            # 限制日志数量（最多1000条）
            if len(existing_logs) > 1000:
                existing_logs = existing_logs[-1000:]

            # 保存日志
            _save_logs(existing_logs)

            logger.info("记录了 %s 条前端错误日志", len(errors))
            return True

        except Exception as e:
            logger.error("写入前端错误日志失败: %s", e)
            return False


def read_all_errors(
    limit: int = 100, error_type: str = None, user_id: str = None, start_time: str = None, end_time: str = None
) -> List[Dict[str, Any]]:
    """
    读取所有错误日志

    Args:
        limit: 返回数量限制
        error_type: 错误类型过滤
        user_id: 用户ID过滤
        start_time: 开始时间过滤（ISO格式）
        end_time: 结束时间过滤（ISO格式）

    Returns:
        错误日志列表
    """
    with _lock:
        try:
            logs = _load_logs()

            # 应用过滤器
            filtered_logs = []
            for log in logs:
                # 类型过滤
                if error_type and log.get("type") != error_type:
                    continue

                # 用户过滤
                if user_id and log.get("user_id") != user_id:
                    continue

                # 时间过滤
                log_time = log.get("timestamp", "")
                if start_time and log_time < start_time:
                    continue
                if end_time and log_time > end_time:
                    continue

                filtered_logs.append(log)

            # 按时间倒序排序
            filtered_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

            # 限制数量
            return filtered_logs[:limit]

        except Exception as e:
            logger.error("读取错误日志失败: %s", e)
            return []


def clear_errors(before_time: str = None, error_type: str = None) -> bool:
    """
    清空错误日志

    Args:
        before_time: 清除此时间之前的日志（ISO格式）
        error_type: 清除指定类型的日志

    Returns:
        是否清除成功
    """
    with _lock:
        try:
            if before_time is None and error_type is None:
                # 清空所有日志
                _save_logs([])
                logger.info("已清空所有错误日志")
                return True

            # 加载现有日志
            logs = _load_logs()

            # 过滤要保留的日志
            remaining_logs = []
            for log in logs:
                keep = True

                # 时间过滤
                if before_time and log.get("timestamp", "") < before_time:
                    keep = False

                # 类型过滤
                if error_type and log.get("type") == error_type:
                    keep = False

                if keep:
                    remaining_logs.append(log)

            # 保存过滤后的日志
            _save_logs(remaining_logs)

            removed_count = len(logs) - len(remaining_logs)
            logger.info("清除了 %s 条错误日志", removed_count)
            return True

        except Exception as e:
            logger.error("清除错误日志失败: %s", e)
            return False


def get_error_stats() -> Dict[str, Any]:
    """
    获取错误统计信息

    Returns:
        统计信息字典
    """
    with _lock:
        try:
            logs = _load_logs()

            if not logs:
                return {"total_errors": 0, "by_type": {}, "by_user": {}, "latest_error": None}

            # 按类型统计
            by_type = {}
            for log in logs:
                error_type = log.get("type", "unknown")
                by_type[error_type] = by_type.get(error_type, 0) + 1

            # 按用户统计
            by_user = {}
            for log in logs:
                user_id = log.get("user_id", "anonymous")
                by_user[user_id] = by_user.get(user_id, 0) + 1

            # 最新错误
            latest_error = logs[-1] if logs else None

            return {
                "total_errors": len(logs),
                "by_type": by_type,
                "by_user": by_user,
                "latest_error": latest_error,
                "log_file": str(_error_log_file),
            }

        except Exception as e:
            logger.error("获取错误统计失败: %s", e)
            return {"error": str(e)}


def _load_logs() -> List[Dict[str, Any]]:
    """
    加载错误日志

    Returns:
        日志列表
    """
    if not _error_log_file.exists():
        return []

    try:
        with open(_error_log_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("加载错误日志文件失败: %s", e)
        return []


def _save_logs(logs: List[Dict[str, Any]]) -> None:
    """
    保存错误日志

    Args:
        logs: 日志列表
    """
    try:
        with open(_error_log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("保存错误日志文件失败: %s", e)


def delete_log_file() -> bool:
    """
    删除错误日志文件

    Returns:
        是否删除成功
    """
    with _lock:
        try:
            if _error_log_file.exists():
                _error_log_file.unlink()
                logger.info("错误日志文件已删除")
            return True
        except Exception as e:
            logger.error("删除错误日志文件失败: %s", e)
            return False
