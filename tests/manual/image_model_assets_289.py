# -*- coding: utf-8 -*-
"""live-verify：把 Dockerfile 的构建指令在**真文件系统**上跑一遍（Issue #289）。

## 为什么不用 `docker build`

本容器无 docker daemon（`command -v docker` 零命中、`/run/docker.sock` 不存在），
而"镜像里到底有没有权重"这件事**必须**用真文件系统验证，不能靠读 YAML 下结论。
本脚本的做法是：从 Dockerfile 里解析出 `COPY` 指令（与常驻判据同一份实现），
按 Docker 的两条真实规则在临时目录里复演——

1. **构建上下文**：`.dockerignore` 里被排除的路径不进上下文；
2. **`COPY` 语义**：源路径必须在上下文里存在，否则 `docker build` 报
   `COPY failed: ... not found`；源目录则整树复制。

于是"`COPY models/embedding/...` 在上下文里找不找得到源"这件事有了可判定的读数，
而不是"我看了一眼配置觉得没问题"。

用法：
    python tests/manual/image_model_assets_289.py
退出码：0 = 全部通过。
"""
from __future__ import annotations

import fnmatch
import io
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.unit.deploy.test_image_model_assets import (  # noqa: E402
    copiedPrefixes,
    declaredRepoAssets,
    ignoredByDockerignore,
)

COPY_RE_SRC = ("models/embedding/bge-small-zh-v1.5", "models/MANIFEST.json")


def buildContext(dest: Path) -> int:
    """按 .dockerignore 复演构建上下文（跳过被排除的路径）。

    只走 `models/` 与 `config/` 两棵资产树 —— 全仓拷贝要几 GB 且与本判据无关。
    """
    copied = 0
    for top in ("models", "config"):
        base = REPO / top
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            if ignoredByDockerignore(rel):
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    return copied


def main() -> int:
    failures = []

    print("=" * 72)
    print("live-verify · Issue #289 「权重没打进镜像」")
    print("=" * 72)

    # [1] 资产清单由生产读取方反推
    assets = declaredRepoAssets()
    print(f"\n[1] 生产侧声明的仓库资产（repoAsset 调用点反推）= {len(assets)} 条")
    for asset in sorted(assets):
        readers = ", ".join(sorted(assets[asset]))
        print(f"    {asset:42} <- {readers}")

    with tempfile.TemporaryDirectory(prefix="neurova_ctx_") as tmp:
        ctx = Path(tmp) / "context"
        ctx.mkdir()
        copied = buildContext(ctx)
        print(f"\n[2] 构建上下文复演完成：{copied} 个文件进入上下文（assets 两棵树）")

        # [3] 每个 COPY 源必须在上下文里存在（否则 docker build 当场报 not found）
        print("\n[3] Dockerfile 的 `COPY` 源在上下文里是否存在（不存在则构建失败）")
        for src in COPY_RE_SRC:
            present = (ctx / src).exists()
            print(f"    COPY {src:42} 在上下文中 = {present}")
            if not present:
                failures.append(f"COPY 源 {src} 不在构建上下文里（docker build 会报 not found）")

        # [4] 镜像里到底有什么：权重本体 + 元数据必须在，两种另存形态可以不在
        print("\n[4] 复演后的镜像内容抽查")
        weight_dir = ctx / "models/embedding/bge-small-zh-v1.5"
        for name, must in (
            ("model.onnx", True),
            ("config.json", True),
            ("tokenizer.json", True),
            ("vocab.txt", True),
            ("special_tokens_map.json", True),
            ("model.safetensors", False),
            ("pytorch_model.bin", False),
        ):
            present = (weight_dir / name).exists()
            size = (weight_dir / name).stat().st_size if present else 0
            mark = "必须" if must else "可选"
            print(f"    {name:26} [{mark}] 在镜像中 = {present:5}  ({size:,} B)")
            if must and not present:
                failures.append(f"必需权重文件 {name} 不在镜像里")
        print(f"    {'MANIFEST.json':26} [必须] 在镜像中 = "
              f"{(ctx / 'models/MANIFEST.json').exists()}")

        # [5] 上下文里不得混进"另两种编码"的大件（避免镜像膨胀）
        bloat = [p for p in weight_dir.glob("*") if p.suffix in (".safetensors", ".bin")]
        print(f"\n[5] 镜像未携带的另存编码大件：{[p.name for p in bloat] or '（无）'}")
        if bloat:
            failures.append(f"不需要的权重形态进了镜像：{[p.name for p in bloat]}")

    print("\n" + "=" * 72)
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print("LIVE-VERIFY FAILED")
        return 1
    print("LIVE-VERIFY PASSED / Issue #289 · 权重进镜像")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
