# -*- coding: utf-8 -*-
"""生产镜像必须安装 MANIFEST 选中的完整依赖锁，且锁文件留在构建上下文。"""
from __future__ import annotations

import json
from pathlib import Path

from tests.unit.deploy.test_image_model_assets import ignoredByDockerignore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOCK_NAME = "requirements-full.lock"


def selectedRequirements() -> str:
    manifest = json.loads((PROJECT_ROOT / "models" / "MANIFEST.json").read_text(encoding="utf-8"))
    return manifest["runtime"]["pip"]["requirements"]


class TestProductionDependencyLock:
    def testManifestSelectsCompiledRuntimeLock(self):
        assert selectedRequirements() == LOCK_NAME, (
            "runtime.pip.requirements 必须选择完整锁，安装入口才能得到固定依赖树"
        )
        assert (PROJECT_ROOT / LOCK_NAME).is_file(), f"完整锁不存在: {LOCK_NAME}"

    def testDockerfileCopiesAndInstallsSelectedLock(self):
        selected = selectedRequirements()
        dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert f"COPY {selected} ." in dockerfile, (
            f"生产镜像构建阶段未 COPY {selected}，pip 无锁可用"
        )
        assert f"pip install --no-cache-dir --user -r {selected}" in dockerfile, (
            f"生产镜像未安装 MANIFEST 选中的 {selected}"
        )
        assert "pip install --no-cache-dir --user -r requirements.txt" not in dockerfile, (
            "生产镜像仍在安装未锁定的 requirements.txt，与桌面/安装器分叉"
        )

    def testSelectedLockSurvivesDockerignore(self):
        selected = selectedRequirements()
        assert not ignoredByDockerignore(selected), (
            f"{selected} 被 .dockerignore 挡在构建上下文外，Dockerfile COPY 会失败"
        )

    def testCurrentInstallGuidesUseSelectedLock(self):
        selected = selectedRequirements()
        guides = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "docs/06-bugfix/JWT修复指南.md"]
        guides.extend((PROJECT_ROOT / "docs/03-user-guide/i18n").glob("README.*.md"))
        assert guides, "现行安装文档入口为空，守卫失效"
        for guide in guides:
            text = guide.read_text(encoding="utf-8")
            assert f"pip install -r {selected}" in text, (
                f"{guide.relative_to(PROJECT_ROOT)} 仍引导用户安装未锁定清单"
            )
            assert "pip install -r requirements.txt" not in text, (
                f"{guide.relative_to(PROJECT_ROOT)} 仍含旧安装命令"
            )
