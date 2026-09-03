"""Test Image Pipeline Docker integration"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestImagePipelineDockerIntegration:
    """Test Docker integration for Image Pipeline"""

    def test_build_image_uses_docker_builder(self):
        """build_image should use DockerBuilder instead of simulation"""
        from neurova.image_pipeline import ImagePipelineManager, BuildStatus

        manager = ImagePipelineManager()

        # Mock Docker builder to simulate successful build
        mock_build_result = Mock(
            success=True,
            image_id="sha256:abc123",
            image_tag="python-3.11:latest",
            logs=["Step 1/5: FROM python:3.11-slim", "Successfully built abc123"],
            duration_seconds=2.5,
        )

        with patch.object(manager._docker_builder, "build", return_value=mock_build_result) as mock_build, \
             patch.object(manager._docker_builder, "generate_dockerfile", return_value="FROM python:3.11-slim"):
            result = manager.build_image("python311", custom_tags=["latest"])

            # Should call Docker builder
            mock_build.assert_called_once()

            # Should return real Docker output
            assert result["success"] is True
            assert result["build"]["image_tag"] == "python-3.11:latest"
            assert result["build"]["metadata"]["image_id"] == "sha256:abc123"

    def test_build_image_handles_docker_failure(self):
        """Test handling of Docker build failures"""
        from neurova.image_pipeline import ImagePipelineManager, BuildStatus

        manager = ImagePipelineManager()

        # Mock Docker builder to fail
        mock_build_result = Mock(
            success=False,
            image_id=None,
            image_tag=None,
            logs=["Step 1/5: FROM invalid-image", "ERROR: image not found"],
            error="Docker build failed: invalid Dockerfile",
            duration_seconds=1.0,
        )

        with patch.object(manager._docker_builder, "build", return_value=mock_build_result), \
             patch.object(manager._docker_builder, "generate_dockerfile", return_value="FROM invalid-image"):
            result = manager.build_image("python311")

            # Should handle failure
            assert result["success"] is False
            assert "error" in result
            assert "Docker build failed" in result["error"]

            # Build record should show failure
            assert result["build"]["status"] == BuildStatus.FAILED.value

    def test_build_image_with_build_args(self):
        """Test passing build arguments to Docker"""
        from neurova.image_pipeline import ImagePipelineManager

        manager = ImagePipelineManager()

        mock_build_result = Mock(
            success=True,
            image_id="sha256:def456",
            image_tag="python-3.11:custom",
            logs=[],
            duration_seconds=1.0,
        )

        build_args = {"PYTHON_VERSION": "3.11", "INSTALL_DEV": "true"}

        with patch.object(manager._docker_builder, "build", return_value=mock_build_result) as mock_build, \
             patch.object(manager._docker_builder, "generate_dockerfile", return_value="FROM python:3.11-slim"):
            result = manager.build_image(
                "python311",
                custom_tags=["custom"],
                build_args=build_args,
            )

            # Should pass args to Docker
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["build_args"] == build_args

    def test_build_image_with_platform(self):
        """Test building for specific platform"""
        from neurova.image_pipeline import ImagePipelineManager

        manager = ImagePipelineManager()

        mock_build_result = Mock(
            success=True,
            image_id="sha256:ghi789",
            image_tag="python-3.11:arm64",
            logs=[],
            duration_seconds=1.0,
        )

        with patch.object(manager._docker_builder, "build", return_value=mock_build_result) as mock_build, \
             patch.object(manager._docker_builder, "generate_dockerfile", return_value="FROM python:3.11-slim"):
            result = manager.build_image(
                "python311",
                custom_tags=["arm64"],
                platform="linux/arm64",
            )

            # Should pass platform to Docker
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["platform"] == "linux/arm64"

    def test_build_image_docker_unavailable(self):
        """Test build fails gracefully when Docker is unavailable"""
        from neurova.image_pipeline import ImagePipelineManager, BuildStatus

        manager = ImagePipelineManager()

        mock_build_result = Mock(
            success=False,
            image_id=None,
            image_tag=None,
            logs=["Docker command not found or not responding"],
            error="Docker is not available",
            duration_seconds=0.1,
        )

        with patch.object(manager._docker_builder, "build", return_value=mock_build_result), \
             patch.object(manager._docker_builder, "generate_dockerfile", return_value="FROM python:3.11-slim"):
            result = manager.build_image("python311")

            assert result["success"] is False
            assert result["build"]["status"] == BuildStatus.FAILED.value

    def test_build_image_template_not_found(self):
        """Test build fails for nonexistent template"""
        from neurova.image_pipeline import ImagePipelineManager

        manager = ImagePipelineManager()

        result = manager.build_image("nonexistent_template")

        assert result["success"] is False
        assert "not found" in result["error"].lower()


class TestDockerBuilder:
    """Test DockerBuilder deep module"""

    def test_docker_builder_interface(self):
        """Test DockerBuilder interface"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()

        # Should have build method
        assert hasattr(builder, "build")

        # Should have helper methods
        assert hasattr(builder, "check_docker_available")
        assert hasattr(builder, "list_images")
        assert hasattr(builder, "remove_image")
        assert hasattr(builder, "pull_image")
        assert hasattr(builder, "get_image_info")
        assert hasattr(builder, "generate_dockerfile")

    def test_docker_builder_build_calls_subprocess(self):
        """Test DockerBuilder.build calls subprocess with correct args"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            # Mock successful docker --version check
            mock_run.return_value = Mock(returncode=0, stdout="Docker version 24.0.0", stderr="")

            # Mock build result
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Step 1/5: FROM python:3.11-slim\nSuccessfully built abc123",
                stderr="",
            )

            result = builder.build(
                dockerfile_path="Dockerfile",
                tag="test-image:latest",
                build_args={"ARG1": "value1"},
            )

            # BuildResult should be returned (not dict)
            assert result.success is True
            assert result.image_tag == "test-image:latest"
            assert result.image_id == "abc123"

    def test_docker_builder_build_handles_error(self):
        """Test handling of subprocess errors"""
        from neurova.image_pipeline.docker_builder import DockerBuilder
        import subprocess

        builder = DockerBuilder()

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            # Mock successful docker --version check
            mock_run.return_value = Mock(returncode=0, stdout="Docker version 24.0.0", stderr="")
            # Mock build failure
            mock_run.side_effect = [
                Mock(returncode=0, stdout="Docker version 24.0.0", stderr=""),  # version check
                Mock(returncode=1, stdout="", stderr="Error: No such file or directory"),  # build
            ]

            result = builder.build(
                dockerfile_path="/nonexistent/Dockerfile",
                tag="test-image:latest",
            )

            assert result.success is False
            assert result.error is not None

    def test_docker_builder_check_docker_available(self):
        """Test Docker availability check"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        # Reset cache to test fresh check
        builder = DockerBuilder()
        builder._docker_available = None  # Reset cache

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            # Docker available
            mock_run.return_value = Mock(returncode=0, stdout="Docker version 24.0.0")
            assert builder.check_docker_available() is True

    def test_docker_builder_check_docker_unavailable(self):
        """Test Docker unavailable"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()
        builder._docker_available = None  # Reset cache

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("docker not found")
            assert builder.check_docker_available() is False

    def test_generate_dockerfile(self):
        """Test Dockerfile generation from template"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()

        dockerfile = builder.generate_dockerfile(
            template_id="python311",
            base_image="python:3.11-slim",
            layers=[
                {"type": "apt", "packages": ["git", "curl"]},
                {"type": "pip", "packages": ["pip", "setuptools"]},
            ],
            build_args={"PYTHON_VERSION": "3.11"},
        )

        assert "FROM python:3.11-slim" in dockerfile
        assert "ARG PYTHON_VERSION=3.11" in dockerfile
        assert "apt-get" in dockerfile
        assert "git" in dockerfile
        assert "pip install" in dockerfile

    def test_build_result_dataclass(self):
        """Test BuildResult dataclass serialization"""
        from neurova.image_pipeline.docker_builder import BuildResult

        result = BuildResult(
            success=True,
            image_id="abc123",
            image_tag="test:latest",
            logs=["step 1"],
            duration_seconds=5.0,
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["image_id"] == "abc123"
        assert d["image_tag"] == "test:latest"
        assert d["logs"] == ["step 1"]
        assert d["duration_seconds"] == 5.0

    def test_docker_image_dataclass(self):
        """Test DockerImage dataclass"""
        from neurova.image_pipeline.docker_builder import DockerImage

        img = DockerImage(
            id="abc123",
            tags=["test:latest"],
            size="100MB",
            created="2024-01-01",
        )

        d = img.to_dict()
        assert d["id"] == "abc123"
        assert d["tags"] == ["test:latest"]
        assert d["size"] == "100MB"

    def test_remove_image(self):
        """Test image removal"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()
        builder._docker_available = True  # Assume available

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
            assert builder.remove_image("test:latest") is True

    def test_remove_image_failure(self):
        """Test image removal failure"""
        from neurova.image_pipeline.docker_builder import DockerBuilder

        builder = DockerBuilder()
        builder._docker_available = True

        with patch("neurova.image_pipeline.docker_builder.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="Error: image not found")
            assert builder.remove_image("nonexistent:latest") is False

    def test_global_singleton(self):
        """Test global singleton pattern"""
        from neurova.image_pipeline.docker_builder import get_docker_builder, reset_docker_builder

        reset_docker_builder()
        builder1 = get_docker_builder()
        builder2 = get_docker_builder()

        assert builder1 is builder2

        reset_docker_builder()
        builder3 = get_docker_builder()
        assert builder1 is not builder3


class TestDockerfileGeneration:
    """Test Dockerfile generation for different templates"""

    def test_python_template(self):
        """Test Python template Dockerfile"""
        from neurova.image_pipeline import ImagePipelineManager

        manager = ImagePipelineManager()

        dockerfile = manager._docker_builder.generate_dockerfile(
            template_id="python311",
            base_image="python:3.11-slim",
            layers=[
                {"type": "apt", "packages": ["git", "curl"]},
                {"type": "pip", "packages": ["pip", "setuptools"]},
            ],
        )

        assert "FROM python:3.11-slim" in dockerfile
        assert "WORKDIR /app" in dockerfile
        assert "git" in dockerfile
        assert "pip install" in dockerfile

    def test_nodejs_template(self):
        """Test Node.js template Dockerfile"""
        from neurova.image_pipeline import ImagePipelineManager

        manager = ImagePipelineManager()

        dockerfile = manager._docker_builder.generate_dockerfile(
            template_id="nodejs18",
            base_image="node:18-slim",
            layers=[
                {"type": "apt", "packages": ["git"]},
                {"type": "npm", "global": ["yarn", "typescript"]},
            ],
        )

        assert "FROM node:18-slim" in dockerfile
        assert "npm install -g" in dockerfile
        assert "EXPOSE 3000" in dockerfile


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
