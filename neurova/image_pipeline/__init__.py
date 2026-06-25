"""
Image 定义管道 v1.0.0 (技能/环境预配)

隔离层级: 全局

能力:
1. 列出可用的镜像模板
2. 查看镜像模板详情
3. 构建自定义镜像
4. 查看构建历史
"""

from neurova.core.logger import get_logger
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .docker_builder import get_docker_builder

logger = get_logger(__name__)


class BuildStatus(Enum):
    """构建状态"""

    PENDING = "pending"
    BUILDING = "building"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ImageTemplate:
    """镜像模板"""

    template_id: str
    name: str
    description: str
    base_image: str
    tags: List[str] = field(default_factory=list)
    layers: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "base_image": self.base_image,
            "tags": self.tags,
            "layers": self.layers,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageTemplate":
        return cls(
            template_id=data.get("template_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            base_image=data.get("base_image", ""),
            tags=data.get("tags", []),
            layers=data.get("layers", []),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class BuildRecord:
    """构建记录"""

    build_id: str
    template_id: str
    status: BuildStatus
    started_at: float
    completed_at: Optional[float] = None
    image_tag: Optional[str] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_id": self.build_id,
            "template_id": self.template_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "image_tag": self.image_tag,
            "error": self.error,
            "logs": self.logs[-50:],  # 只返回最后50条日志
            "metadata": self.metadata,
        }


# 默认镜像模板
_DEFAULT_TEMPLATES = [
    {
        "template_id": "python311",
        "name": "Python 3.11",
        "description": "Python 3.11 开发环境",
        "base_image": "python:3.11-slim",
        "tags": ["python", "development"],
        "layers": [
            {"type": "apt", "packages": ["git", "curl", "wget"]},
            {"type": "pip", "packages": ["pip", "setuptools", "wheel"]},
        ],
    },
    {
        "template_id": "nodejs18",
        "name": "Node.js 18",
        "description": "Node.js 18 LTS 开发环境",
        "base_image": "node:18-slim",
        "tags": ["nodejs", "javascript", "development"],
        "layers": [
            {"type": "apt", "packages": ["git", "curl"]},
            {"type": "npm", "global": ["npm", "yarn", "typescript"]},
        ],
    },
    {
        "template_id": "ubuntu2204",
        "name": "Ubuntu 22.04",
        "description": "Ubuntu 22.04 基础环境",
        "base_image": "ubuntu:22.04",
        "tags": ["ubuntu", "linux", "base"],
        "layers": [
            {"type": "apt", "packages": ["git", "curl", "wget", "vim", "nano"]},
        ],
    },
    {
        "template_id": "pytorch_ml",
        "name": "PyTorch ML",
        "description": "PyTorch 机器学习环境",
        "base_image": "pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime",
        "tags": ["pytorch", "ml", "gpu"],
        "layers": [
            {"type": "apt", "packages": ["git", "curl"]},
            {"type": "pip", "packages": ["torchvision", "torchaudio", "jupyter", "tensorboard"]},
        ],
    },
    {
        "template_id": "web_dev",
        "name": "Web Development",
        "description": "全栈 Web 开发环境",
        "base_image": "node:18-slim",
        "tags": ["web", "fullstack", "development"],
        "layers": [
            {"type": "apt", "packages": ["git", "curl", "python3", "python3-pip"]},
            {"type": "npm", "global": ["npm", "yarn", "typescript", "vite"]},
        ],
    },
]


class ImagePipelineManager:
    """镜像管道管理器"""

    def __init__(self, storage_dir: Optional[str] = None):
        self._storage_dir = storage_dir or ".neurova/image_pipeline"
        self._templates: Dict[str, ImageTemplate] = {}
        self._builds: List[BuildRecord] = []
        self._lock = threading.RLock()
        self._init_default_templates()

        # 初始化 Docker 构建器
        self._docker_builder = get_docker_builder()

        logger.info("ImagePipelineManager initialized with %d templates", len(self._templates))

    def _init_default_templates(self) -> None:
        """初始化默认模板"""
        for tmpl_data in _DEFAULT_TEMPLATES:
            template = ImageTemplate.from_dict(tmpl_data)
            self._templates[template.template_id] = template

    def list_templates(self, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        列出可用的镜像模板

        Args:
            tag: 可选的标签过滤

        Returns:
            模板列表
        """
        with self._lock:
            templates = list(self._templates.values())

            if tag:
                templates = [t for t in templates if tag in t.tags]

            return [t.to_dict() for t in templates]

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        获取模板详情

        Args:
            template_id: 模板 ID

        Returns:
            模板详情或 None
        """
        with self._lock:
            template = self._templates.get(template_id)
            return template.to_dict() if template else None

    def build_image(
        self,
        template_id: str,
        custom_tags: Optional[List[str]] = None,
        build_args: Optional[Dict[str, str]] = None,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        构建镜像

        Args:
            template_id: 模板 ID
            custom_tags: 自定义标签
            build_args: 构建参数

        Returns:
            构建记录
        """
        start_time = time.time()

        with self._lock:
            template = self._templates.get(template_id)
            if not template:
                return {"success": False, "error": f"Template not found: {template_id}"}

            build_id = f"build_{uuid.uuid4().hex[:12]}"

            record = BuildRecord(
                build_id=build_id,
                template_id=template_id,
                status=BuildStatus.BUILDING,
                started_at=start_time,
                metadata={
                    "custom_tags": custom_tags or [],
                    "build_args": build_args or {},
                },
            )

            self._builds.append(record)

            # 使用 DockerBuilder 构建镜像
            try:
                # 生成 Dockerfile
                dockerfile_content = self._docker_builder.generate_dockerfile(
                    template_id=template_id,
                    base_image=template.base_image,
                    layers=template.layers,
                    build_args=build_args,
                )

                # 创建临时 Dockerfile
                import os
                import tempfile

                with tempfile.NamedTemporaryFile(mode="w", suffix=".dockerfile", delete=False) as f:
                    f.write(dockerfile_content)
                    dockerfile_path = f.name

                try:
                    # 确定镜像标签
                    if custom_tags:
                        image_tag = f"{template.name.lower().replace(' ', '-')}:{custom_tags[0]}"
                    else:
                        image_tag = f"{template.name.lower().replace(' ', '-')}:{uuid.uuid4().hex[:8]}"

                    record.logs.append(f"Build started for template: {template.name}")
                    record.logs.append(f"Base image: {template.base_image}")

                    # 调用 Docker 构建
                    build_result = self._docker_builder.build(
                        dockerfile_path=dockerfile_path,
                        tag=image_tag,
                        build_args=build_args,
                        platform=platform,
                        rm=True,
                    )

                    # 更新构建记录
                    record.completed_at = time.time()
                    record.logs.extend(build_result.logs)

                    if build_result.success:
                        record.status = BuildStatus.SUCCESS
                        record.image_tag = build_result.image_tag
                        record.metadata["image_id"] = build_result.image_id

                        logger.info("Image built: %s", build_result.image_tag)
                        return {"success": True, "build": record.to_dict()}
                    else:
                        record.status = BuildStatus.FAILED
                        record.error = build_result.error

                        logger.error("Image build failed: %s", build_result.error)
                        return {"success": False, "error": build_result.error, "build": record.to_dict()}

                finally:
                    # 清理临时文件
                    if os.path.exists(dockerfile_path):
                        os.unlink(dockerfile_path)

            except Exception as e:
                record.status = BuildStatus.FAILED
                record.completed_at = time.time()
                record.error = str(e)
                record.logs.append(f"Build failed: {str(e)}")

                logger.error("Image build failed: %s", str(e))
                return {"success": False, "error": str(e), "build": record.to_dict()}

    def get_builds(
        self,
        template_id: Optional[str] = None,
        status: Optional[BuildStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        获取构建历史

        Args:
            template_id: 可选的模板过滤
            status: 可选的状态过滤
            limit: 返回数量限制

        Returns:
            构建记录列表
        """
        with self._lock:
            builds = self._builds.copy()

            if template_id:
                builds = [b for b in builds if b.template_id == template_id]

            if status:
                builds = [b for b in builds if b.status == status]

            # 按时间倒序
            builds.sort(key=lambda b: b.started_at, reverse=True)

            return [b.to_dict() for b in builds[:limit]]


# 全局单例
_manager_instance: Optional[ImagePipelineManager] = None
_manager_lock = threading.Lock()


def get_image_pipeline_manager(storage_dir: Optional[str] = None) -> ImagePipelineManager:
    """获取全局 ImagePipelineManager 实例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = ImagePipelineManager(storage_dir=storage_dir)
    return _manager_instance


def reset_image_pipeline_manager() -> None:
    """重置全局 ImagePipelineManager 实例（用于测试）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
