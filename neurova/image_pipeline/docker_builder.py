"""
Docker Builder 深度模块

小接口、深实现：
- build(): 执行 Docker 构建
- check_docker_available(): 检查 Docker 是否可用
- list_images(): 列出本地镜像
- remove_image(): 删除本地镜像

支持平台、构建参数、错误处理。
"""

import subprocess
import shutil
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import os

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Docker 构建结果"""
    success: bool
    image_id: Optional[str] = None
    image_tag: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "image_id": self.image_id,
            "image_tag": self.image_tag,
            "logs": self.logs,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class DockerImage:
    """Docker 镜像信息"""
    id: str
    tags: List[str]
    size: str
    created: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tags": self.tags,
            "size": self.size,
            "created": self.created,
        }


class DockerBuilder:
    """
    Docker 构建器深度模块
    
    提供完整的 Docker 构建、查询、删除能力。
    使用 subprocess 调用 Docker CLI，支持跨平台。
    """
    
    def __init__(self, docker_cmd: Optional[str] = None):
        """
        初始化 Docker 构建器
        
        Args:
            docker_cmd: Docker 命令路径，默认使用 "docker"
        """
        self._docker_cmd = docker_cmd or "docker"
        self._lock = threading.RLock()
        self._docker_available: Optional[bool] = None
        
        logger.info("DockerBuilder initialized with cmd: %s", self._docker_cmd)
    
    def check_docker_available(self) -> bool:
        """
        检查 Docker 是否可用
        
        Returns:
            True if Docker is available, False otherwise
        """
        with self._lock:
            # 使用缓存结果
            if self._docker_available is not None:
                return self._docker_available
            
            try:
                result = subprocess.run(
                    [self._docker_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self._docker_available = result.returncode == 0
                if self._docker_available:
                    logger.info("Docker available: %s", result.stdout.strip())
                else:
                    logger.warning("Docker not available: %s", result.stderr.strip())
                    
            except FileNotFoundError:
                # Docker 命令不存在
                logger.warning("Docker command not found: %s", self._docker_cmd)
                self._docker_available = False
                
            except subprocess.TimeoutExpired:
                # Docker 命令超时
                logger.warning("Docker version check timed out")
                self._docker_available = False
                
            except Exception as e:
                logger.error("Error checking Docker availability: %s", str(e))
                self._docker_available = False
            
            return self._docker_available
    
    def build(
        self,
        dockerfile_path: str,
        tag: str,
        context_path: Optional[str] = None,
        build_args: Optional[Dict[str, str]] = None,
        platform: Optional[str] = None,
        no_cache: bool = False,
        pull: bool = False,
        rm: bool = True,
    ) -> BuildResult:
        """
        执行 Docker 构建
        
        Args:
            dockerfile_path: Dockerfile 路径
            tag: 镜像标签 (name:version)
            context_path: 构建上下文路径，默认为 Dockerfile 所在目录
            build_args: 构建参数
            platform: 目标平台 (如 linux/amd64, linux/arm64)
            no_cache: 是否禁用缓存
            pull: 是否总是拉取最新基础镜像
            rm: 是否删除中间容器
            
        Returns:
            BuildResult 对象
        """
        import time
        start_time = time.time()
        
        with self._lock:
            logs = []
            
            # 检查 Docker 是否可用
            if not self.check_docker_available():
                return BuildResult(
                    success=False,
                    error="Docker is not available",
                    logs=["Docker command not found or not responding"],
                    duration_seconds=time.time() - start_time,
                )
            
            # 检查 Dockerfile 是否存在
            dockerfile = Path(dockerfile_path)
            if not dockerfile.exists():
                return BuildResult(
                    success=False,
                    error=f"Dockerfile not found: {dockerfile_path}",
                    logs=[f"Error: Dockerfile not found at {dockerfile_path}"],
                    duration_seconds=time.time() - start_time,
                )
            
            # 确定构建上下文
            if context_path is None:
                context_path = str(dockerfile.parent)
            
            # 构建 Docker 命令
            cmd = [self._docker_cmd, "build"]
            
            # 添加标签
            cmd.extend(["--tag", tag])
            
            # 添加 Dockerfile 路径
            cmd.extend(["--file", str(dockerfile)])
            
            # 添加构建参数
            if build_args:
                for key, value in build_args.items():
                    cmd.extend(["--build-arg", f"{key}={value}"])
            
            # 添加平台
            if platform:
                cmd.extend(["--platform", platform])
            
            # 添加其他选项
            if no_cache:
                cmd.append("--no-cache")
            
            if pull:
                cmd.append("--pull")
            
            if rm:
                cmd.append("--rm")
            
            # 添加构建上下文路径
            cmd.append(context_path)
            
            logs.append(f"Running: {' '.join(cmd)}")
            logger.debug("Docker build command: %s", ' '.join(cmd))
            
            try:
                # 执行构建
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 1小时超时
                    check=False,
                )
                
                # 解析输出
                stdout_lines = result.stdout.strip().split('\n') if result.stdout else []
                stderr_lines = result.stderr.strip().split('\n') if result.stderr else []
                
                logs.extend(stdout_lines)
                if stderr_lines:
                    logs.extend([f"[stderr] {line}" for line in stderr_lines])
                
                if result.returncode == 0:
                    # 构建成功
                    image_id = self._extract_image_id(result.stdout)
                    
                    # 清理镜像 ID 中的前缀
                    if image_id and image_id.startswith("sha256:"):
                        image_id = image_id[7:]  # 移除 "sha256:" 前缀
                    
                    logs.append("Build completed successfully")
                    
                    return BuildResult(
                        success=True,
                        image_id=image_id,
                        image_tag=tag,
                        logs=logs,
                        duration_seconds=time.time() - start_time,
                    )
                else:
                    # 构建失败
                    error_msg = f"Docker build failed with return code {result.returncode}"
                    if result.stderr:
                        # 提取最后一行错误信息
                        error_lines = result.stderr.strip().split('\n')
                        if error_lines:
                            error_msg = error_lines[-1]
                    
                    return BuildResult(
                        success=False,
                        error=error_msg,
                        logs=logs,
                        duration_seconds=time.time() - start_time,
                    )
                    
            except subprocess.TimeoutExpired:
                return BuildResult(
                    success=False,
                    error="Docker build timed out",
                    logs=logs + ["Build timed out after 1 hour"],
                    duration_seconds=time.time() - start_time,
                )
                
            except subprocess.CalledProcessError as e:
                return BuildResult(
                    success=False,
                    error=f"Subprocess error: {str(e)}",
                    logs=logs + [f"Error: {str(e)}"],
                    duration_seconds=time.time() - start_time,
                )
                
            except Exception as e:
                logger.error("Docker build failed: %s", str(e))
                return BuildResult(
                    success=False,
                    error=f"Unexpected error: {str(e)}",
                    logs=logs + [f"Error: {str(e)}"],
                    duration_seconds=time.time() - start_time,
                )
    
    def _extract_image_id(self, output: str) -> Optional[str]:
        """从构建输出中提取镜像 ID"""
        for line in reversed(output.split('\n')):
            if "Successfully built" in line:
                # 格式: "Successfully built abc123"
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2]
        return None
    
    def list_images(
        self,
        name_filter: Optional[str] = None,
        dangling_only: bool = False,
    ) -> List[DockerImage]:
        """
        列出本地 Docker 镜像
        
        Args:
            name_filter: 按名称过滤
            dangling_only: 只显示悬挂镜像
            
        Returns:
            镜像列表
        """
        with self._lock:
            if not self.check_docker_available():
                return []
            
            cmd = [self._docker_cmd, "images", "--format", "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"]
            
            if dangling_only:
                cmd.append("--filter")
                cmd.append("dangling=true")
            
            if name_filter:
                cmd.append(name_filter)
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                
                if result.returncode != 0:
                    logger.error("Failed to list images: %s", result.stderr)
                    return []
                
                images = []
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    
                    parts = line.split('\t')
                    if len(parts) >= 5:
                        image_id = parts[0]
                        repository = parts[1]
                        tag = parts[2]
                        size = parts[3]
                        created = parts[4]
                        
                        # 构建完整标签
                        if tag and tag != '<none>':
                            full_tag = f"{repository}:{tag}"
                        else:
                            full_tag = repository
                        
                        images.append(DockerImage(
                            id=image_id,
                            tags=[full_tag],
                            size=size,
                            created=created,
                        ))
                
                return images
                
            except Exception as e:
                logger.error("Error listing Docker images: %s", str(e))
                return []
    
    def remove_image(
        self,
        image_id: str,
        force: bool = False,
        no_prune: bool = False,
    ) -> bool:
        """
        删除 Docker 镜像
        
        Args:
            image_id: 镜像 ID 或标签
            force: 强制删除
            no_prune: 不删除未被引用的父镜像
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if not self.check_docker_available():
                return False
            
            cmd = [self._docker_cmd, "rmi"]
            
            if force:
                cmd.append("--force")
            
            if no_prune:
                cmd.append("--no-prune")
            
            cmd.append(image_id)
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                
                if result.returncode == 0:
                    logger.info("Image removed: %s", image_id)
                    return True
                else:
                    logger.error("Failed to remove image %s: %s", image_id, result.stderr)
                    return False
                    
            except Exception as e:
                logger.error("Error removing Docker image: %s", str(e))
                return False
    
    def pull_image(
        self,
        image: str,
        tag: str = "latest",
    ) -> bool:
        """
        拉取 Docker 镜像
        
        Args:
            image: 镜像名称
            tag: 标签
            
        Returns:
            True if successful, False otherwise
        """
        with self._lock:
            if not self.check_docker_available():
                return False
            
            cmd = [self._docker_cmd, "pull", f"{image}:{tag}"]
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5分钟超时
                    check=False,
                )
                
                if result.returncode == 0:
                    logger.info("Image pulled: %s:%s", image, tag)
                    return True
                else:
                    logger.error("Failed to pull image %s:%s: %s", image, tag, result.stderr)
                    return False
                    
            except Exception as e:
                logger.error("Error pulling Docker image: %s", str(e))
                return False
    
    def get_image_info(self, image_id: str) -> Optional[DockerImage]:
        """
        获取镜像详细信息
        
        Args:
            image_id: 镜像 ID 或标签
            
        Returns:
            镜像信息或 None
        """
        with self._lock:
            if not self.check_docker_available():
                return None
            
            cmd = [
                self._docker_cmd, "inspect",
                "--format", "{{.Id}}\t{{.RepoTags}}\t{{.Size}}\t{{.Created}}",
                image_id,
            ]
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                
                if result.returncode != 0:
                    return None
                
                parts = result.stdout.strip().split('\t')
                if len(parts) >= 4:
                    return DockerImage(
                        id=parts[0],
                        tags=[parts[1].strip('[]"') if parts[1] != '[]' else '<none>'],
                        size=parts[2],
                        created=parts[3],
                    )
                
                return None
                
            except Exception as e:
                logger.error("Error getting image info: %s", str(e))
                return None
    
    def generate_dockerfile(
        self,
        template_id: str,
        base_image: str,
        layers: List[Dict[str, Any]],
        build_args: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        根据模板生成 Dockerfile 内容
        
        Args:
            template_id: 模板 ID
            base_image: 基础镜像
            layers: 构建层列表
            build_args: 构建参数
            
        Returns:
            Dockerfile 内容
        """
        lines = []
        
        # 添加构建参数
        if build_args:
            for key, value in build_args.items():
                lines.append(f"ARG {key}={value}")
            lines.append("")
        
        # 基础镜像
        lines.append(f"FROM {base_image}")
        lines.append("")
        
        # 添加工作目录
        lines.append("WORKDIR /app")
        lines.append("")
        
        # 处理构建层
        for layer in layers:
            layer_type = layer.get("type", "")
            
            if layer_type == "apt":
                packages = layer.get("packages", [])
                if packages:
                    lines.append("# Install apt packages")
                    lines.append(f"RUN apt-get update && apt-get install -y \\")
                    for i, pkg in enumerate(packages):
                        if i == len(packages) - 1:
                            lines.append(f"    {pkg} && \\")
                        else:
                            lines.append(f"    {pkg} \\")
                    lines.append("    && rm -rf /var/lib/apt/lists/*")
                    lines.append("")
            
            elif layer_type == "pip":
                packages = layer.get("packages", [])
                if packages:
                    lines.append("# Install pip packages")
                    lines.append(f"RUN pip install --no-cache-dir {' '.join(packages)}")
                    lines.append("")
            
            elif layer_type == "npm":
                global_pkgs = layer.get("global", [])
                if global_pkgs:
                    lines.append("# Install npm packages")
                    lines.append(f"RUN npm install -g {' '.join(global_pkgs)}")
                    lines.append("")
            
            elif layer_type == "run":
                command = layer.get("command", "")
                if command:
                    lines.append(f"# Custom command")
                    lines.append(f"RUN {command}")
                    lines.append("")
        
        # 添加默认端口暴露（如果模板需要）
        if template_id in ["nodejs18", "web_dev"]:
            lines.append("EXPOSE 3000")
            lines.append("")
        
        return "\n".join(lines)


# 全局单例
_builder_instance: Optional[DockerBuilder] = None
_builder_lock = threading.Lock()


def get_docker_builder(docker_cmd: Optional[str] = None) -> DockerBuilder:
    """获取全局 DockerBuilder 实例"""
    global _builder_instance
    if _builder_instance is None:
        with _builder_lock:
            if _builder_instance is None:
                _builder_instance = DockerBuilder(docker_cmd=docker_cmd)
    return _builder_instance


def reset_docker_builder() -> None:
    """重置全局 DockerBuilder 实例（用于测试）"""
    global _builder_instance
    with _builder_lock:
        _builder_instance = None