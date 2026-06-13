"""
文件操作工具函数（公共模块）

提供三层隔离存储的通用工具函数，避免在多个模块中重复定义。
"""

import datetime
import json
import logging
import mimetypes
import re
import typing
import uuid
from pathlib import Path

# 配置常量
STORAGE_ROOT = Path("storage")
DATA_DIR = Path("data")
FILES_DB = DATA_DIR / "files.json"

logger = logging.getLogger(__name__)


def sanitize_name(name: str) -> str:
    """
    清理名称，防止路径遍历攻击

    Args:
        name: 原始名称

    Returns:
        清理后的名称
    """
    if not name:
        return "unknown"

    # 先移除路径遍历序列（..）
    sanitized = name.replace("..", "")

    # 替换每个特殊字符为下划线（不合并）
    sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "_", sanitized)

    # 去除首尾下划线
    sanitized = sanitized.strip("_")

    # 如果清理后为空（如全部是特殊字符），返回替换后的结果而非 unknown
    if not sanitized:
        # 全部是特殊字符，返回全下划线
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)

    return sanitized


def get_isolated_path(
    user_id: str,
    agent_id: typing.Optional[str] = None,
    session_id: typing.Optional[str] = None,
    file_type: typing.Optional[str] = None,
) -> Path:
    """
    获取三层隔离的存储路径

    路径格式: /storage_root/users/{user_id}/agents/{agent_id}/sessions/{session_id}/{file_type}/

    Args:
        user_id: 用户 ID
        agent_id: 代理 ID（可选）
        session_id: 会话 ID（可选）
        file_type: 文件类型（可选）

    Returns:
        隔离的存储路径
    """
    # 清理各个 ID
    user_id = sanitize_name(user_id) if user_id else "default"
    agent_id = sanitize_name(agent_id) if agent_id else "default"
    session_id = sanitize_name(session_id) if session_id else "default"
    file_type = sanitize_name(file_type) if file_type else "default"

    # 构建路径
    path = STORAGE_ROOT / "users" / user_id / "agents" / agent_id / "sessions" / session_id / file_type

    # 创建目录
    path.mkdir(parents=True, exist_ok=True)

    return path


def generate_file_id() -> str:
    """
    生成唯一的文件 ID

    Returns:
        文件 ID，格式为 "file_" + 12位十六进制
    """
    # 生成 UUID 并取前 12 位十六进制
    uuid_hex = uuid.uuid4().hex[:12]
    return f"file_{uuid_hex}"


def get_file_extension(filename: str) -> str:
    """
    获取文件扩展名

    Args:
        filename: 文件名

    Returns:
        小写的文件扩展名（不包含点）
    """
    if not filename:
        return ""

    # 获取最后一个点后的扩展名
    if "." in filename:
        ext = filename.split(".")[-1].lower()
        return ext

    return ""


def detect_mime_type(filename: str, content: typing.Optional[bytes] = None) -> str:
    """
    检测文件的 MIME 类型

    Args:
        filename: 文件名
        content: 文件内容（可选）

    Returns:
        MIME 类型字符串
    """
    # 首先尝试从文件名推断
    mime_type, _ = mimetypes.guess_type(filename)

    if mime_type:
        return mime_type

    # 如果提供了内容，尝试从内容推断
    if content:
        # 简单的文件头检测
        if content.startswith(b"%PDF"):
            return "application/pdf"
        elif content.startswith(b"\x89PNG"):
            return "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        elif content.startswith(b"GIF8"):
            return "image/gif"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        elif content.startswith(b"ID3") or content.startswith(b"\xff\xfb"):
            return "audio/mpeg"
        elif content.startswith(b"\x1f\x8b"):
            return "application/gzip"
        elif content.startswith(b"PK\x03\x04"):
            return "application/zip"

    # 默认返回二进制流
    return "application/octet-stream"


def load_files_db() -> dict:
    """
    加载文件数据库（files.json）

    Returns:
        文件数据库字典
    """
    try:
        if FILES_DB.exists():
            with open(FILES_DB, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error("加载文件数据库失败: %s", e)
        return {}


def save_files_db(data: dict) -> bool:
    """
    保存文件数据库（files.json）

    Args:
        data: 要保存的数据

    Returns:
        是否保存成功
    """
    try:
        # 确保目录存在
        FILES_DB.parent.mkdir(parents=True, exist_ok=True)

        with open(FILES_DB, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error("保存文件数据库失败: %s", e)
        return False


def get_file_metadata(file_id: str) -> typing.Optional[dict]:
    """
    获取文件元数据

    Args:
        file_id: 文件 ID

    Returns:
        文件元数据字典，不存在则返回 None
    """
    db = load_files_db()
    return db.get(file_id)


def save_file_metadata(file_id: str, metadata: dict) -> bool:
    """
    保存文件元数据

    Args:
        file_id: 文件 ID
        metadata: 元数据字典

    Returns:
        是否保存成功
    """
    db = load_files_db()
    db[file_id] = metadata
    return save_files_db(db)


def delete_file_metadata(file_id: str) -> bool:
    """
    删除文件元数据

    Args:
        file_id: 文件 ID

    Returns:
        是否删除成功
    """
    db = load_files_db()
    if file_id in db:
        del db[file_id]
        return save_files_db(db)
    return False


def save_file_to_isolated_path(
    user_id: str,
    agent_id: str,
    session_id: str,
    file_type: str,
    filename: str,
    content: bytes,
    metadata: typing.Optional[dict] = None,
) -> dict:
    """
    保存文件到三层隔离路径，并记录元数据到 JSON 数据库

    Args:
        user_id: 用户 ID
        agent_id: 代理 ID
        session_id: 会话 ID
        file_type: 文件类型
        filename: 文件名
        content: 文件内容
        metadata: 额外的元数据（可选）

    Returns:
        包含 file_id, storage_path, metadata 的字典
    """
    # 生成文件 ID
    file_id = generate_file_id()

    # 获取隔离路径
    isolated_path = get_isolated_path(user_id, agent_id, session_id, file_type)

    # 清理文件名并限制长度
    sanitized_filename = sanitize_name(filename)
    # Windows MAX_PATH is 260; reserve space for directory + file_id prefix + extension
    max_name_len = 100
    if len(sanitized_filename) > max_name_len:
        ext = get_file_extension(filename)
        base = sanitized_filename[: max_name_len - len(ext) - 1] if ext else sanitized_filename[:max_name_len]
        sanitized_filename = f"{base}.{ext}" if ext else base

    # 构建存储路径
    storage_path = isolated_path / f"{file_id}_{sanitized_filename}"

    # 保存文件
    with open(storage_path, "wb") as f:
        f.write(content)

    # 构建元数据
    file_metadata = {
        "name": filename,
        "size": len(content),
        "mime_type": detect_mime_type(filename, content),
        "created_at": datetime.datetime.now().isoformat(),
        "user_id": user_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "file_type": file_type,
        "storage_path": str(storage_path),
    }

    # 合并额外的元数据
    if metadata:
        file_metadata.update(metadata)

    # 保存元数据到数据库
    save_file_metadata(file_id, file_metadata)

    return {"file_id": file_id, "storage_path": str(storage_path), "metadata": file_metadata}


def load_file_from_isolated_path(file_id: str) -> typing.Optional[dict]:
    """
    从三层隔离路径加载文件

    Args:
        file_id: 文件 ID

    Returns:
        包含 file_path 和 metadata 的字典，不存在则返回 None
    """
    # 获取元数据
    metadata = get_file_metadata(file_id)
    if not metadata:
        return None

    # 获取存储路径
    storage_path = Path(metadata.get("storage_path", ""))

    # 检查文件是否存在
    if not storage_path.exists():
        logger.warning("文件不存在: %s", storage_path)
        return None

    return {"file_path": str(storage_path), "metadata": metadata}


def delete_file_from_isolated_path(file_id: str) -> bool:
    """
    从三层隔离路径删除文件

    Args:
        file_id: 文件 ID

    Returns:
        是否删除成功
    """
    # 获取文件信息
    file_info = load_file_from_isolated_path(file_id)
    if not file_info:
        return False

    # 删除文件
    try:
        storage_path = Path(file_info["file_path"])
        if storage_path.exists():
            storage_path.unlink()

        # 删除元数据
        delete_file_metadata(file_id)
        return True
    except Exception as e:
        logger.error("删除文件失败: %s", e)
        return False


def get_generation_file_info(generation_type: str) -> dict:
    """
    根据生成类型获取文件信息

    Args:
        generation_type: 生成类型（如 text_to_image, text_to_video 等）

    Returns:
        包含 file_type, mime_type, file_ext 的字典
    """
    # 定义生成类型映射
    type_mapping = {
        "text_to_image": {"file_type": "image", "mime_type": "image/png", "file_ext": "png"},
        "image_to_image": {"file_type": "image", "mime_type": "image/png", "file_ext": "png"},
        "text_to_video": {"file_type": "video", "mime_type": "video/mp4", "file_ext": "mp4"},
        "image_to_video": {"file_type": "video", "mime_type": "video/mp4", "file_ext": "mp4"},
        "text_to_audio": {"file_type": "audio", "mime_type": "audio/mpeg", "file_ext": "mp3"},
        "text_to_speech": {"file_type": "audio", "mime_type": "audio/mpeg", "file_ext": "mp3"},
    }

    # 返回映射或默认值
    return type_mapping.get(
        generation_type, {"file_type": "file", "mime_type": "application/octet-stream", "file_ext": "bin"}
    )
