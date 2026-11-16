"""
P0-1 出厂守卫（bundle_backend.assertStageFreeOfMasterPassword）——分发包零主恢复口令。

背景（2026-11-16 全库审计 P0-1 拍板）：主恢复口令只经环境变量在部署/运行期存在，
源码与分发包不含口令常量（源码侧 fail-closed 由 S2 落地）。本守卫钉住打包链的
最后一格：bundle_backend 打完包对产物做双查——①历史口令字样（66269ea0 引入过的
"neurovamakehappy"）零残留；②口令环境变量被赋字面常量的形态零出现
（auth.py 的 os.environ.get(ENV_NAME) 合法引用不误伤）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "desktop"))

import bundle_backend  # noqa: E402


def _make_stage(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def testHistoricalPasswordLiteralFailsStage(tmp_path):
    """产物含历史口令字样 → 守卫抛 RuntimeError（构建失败）。"""
    stage = _make_stage(tmp_path, {
        "neurova/api/legacy.py": 'MASTER = "neurovamakehappy"\n',
    })
    with pytest.raises(RuntimeError, match="拒绝出厂"):
        bundle_backend.assertStageFreeOfMasterPassword(stage)


def testEnvAssignedLiteralFailsStage(tmp_path):
    """产物把口令环境变量赋字面常量 → 守卫抛 RuntimeError。"""
    stage = _make_stage(tmp_path, {
        "neurova/api/auth.py": 'NEUROVA_MASTER_RECOVERY_PASSWORD = "s3cret"\n',
    })
    with pytest.raises(RuntimeError, match="拒绝出厂"):
        bundle_backend.assertStageFreeOfMasterPassword(stage)


def testLegitEnvReferencePassesStage(tmp_path):
    """auth.py 的 os.environ.get(ENV_NAME) 合法引用 + .env.example 空槽位 → 放行。"""
    stage = _make_stage(tmp_path, {
        "neurova/api/auth.py": (
            '_MASTER_RECOVERY_PASSWORD_ENV = "NEUROVA_MASTER_RECOVERY_PASSWORD"\n'
            'configured = (os.environ.get(_MASTER_RECOVERY_PASSWORD_ENV) or "").strip()\n'
        ),
        ".env.example": "NEUROVA_MASTER_RECOVERY_PASSWORD=\n",
    })
    bundle_backend.assertStageFreeOfMasterPassword(stage)  # 不抛即绿


def testGuardWiredIntoMainPipeline():
    """守卫接线进 main()：打包尾段必须调用出厂守卫（静态断言防接线被摘）。"""
    import inspect

    source = inspect.getsource(bundle_backend.main)
    assert "assertStageFreeOfMasterPassword" in source, (
        "main() 未调用出厂守卫——打包链的 P0-1 最后一格被摘除"
    )
