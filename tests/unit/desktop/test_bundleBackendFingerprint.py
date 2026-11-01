# -*- coding: utf-8 -*-
"""打包增量指纹必须是**内容函数**，不许是「文件数＋字节数」的形状指纹（§6-459 仍开②）。

实测踩到（2026-11-01，1.0.0-beta6 打包现场）：`bundle_backend.dir_fingerprint()` 只算
`{files, bytes}`，把 `neurova/__init__.py` 里的 `1.0.0-beta1` 改成 `1.0.0-beta6` 之后
——同长度、同文件数——`copy_tree_light` 记「neurova 未变，跳过」，暂存区仍是 beta1，
而产出的安装包文件名写着 beta6。当场用 `--force` 绕开了，但**绕开不是根修**：留着这条
路，任何一次「改完版本号直接重打包」都会静默产出装着旧后端的安装包，而文件名与 release
正文都会替它撒谎。

判据口径：
- 红必须落在行为上（同尺寸改内容 ⇒ 指纹必须变、暂存树必须重拷），不是落在「某个新键存在」；
- 反向格钉住「未变仍跳过」——把指纹改成每次都重拷是另一种坏（打包机全量重拷 1GB models）。
"""
import importlib.util
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BUNDLE = _REPO / "scripts" / "desktop" / "bundle_backend.py"
# 阈值缺省值与实现无关：测试今天就要能跑起来并把红落在断言上，而不是撞 AttributeError
_DEFAULT_HASH_CAP = 32 * 1024 * 1024


def _load():
    spec = importlib.util.spec_from_file_location("bundle_backend_fingerprint_probe", _BUNDLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFingerprintIsContentFunction:
    def test_sameSizeDifferentContentIsNotReadAsUnchanged(self, tmp_path):
        """同文件数、同总字节、不同内容 ⇒ 指纹必须不同（今天相同＝这条红）。"""
        mod = _load()
        src = tmp_path / "neurova"
        src.mkdir()
        (src / "__init__.py").write_bytes(b'__version__ = "1.0.0-beta1"\n')
        before = mod.dir_fingerprint(src)

        (src / "__init__.py").write_bytes(b'__version__ = "1.0.0-beta6"\n')
        after = mod.dir_fingerprint(src)

        assert (before["files"], before["bytes"]) == (after["files"], after["bytes"]), (
            "样本没造出「同尺寸」这一形，本条就没在测缺陷："
            f"{before['files']}/{before['bytes']} vs {after['files']}/{after['bytes']}")
        assert before != after, (
            "内容变了而指纹不变——这正是不带内容项的 `{files, bytes}` 会静默跳过重拷的形状："
            f"{before!r}")

    def test_stagedTreeIsRecopiedWhenOnlyContentChanged(self, tmp_path):
        """全链路：首轮同步后只改内容（长度不变），第二轮必须把新内容铺到暂存树。

        这是安装包真正的坏形态：暂存区留着旧代码，NSIS 照旧打包，红nothing。
        """
        mod = _load()
        src = tmp_path / "pkg"
        src.mkdir()
        dst = tmp_path / "staged" / "pkg"
        (src / "init.py").write_bytes(b"VERSION = 'beta1'\n")

        manifest = {}
        mod.copy_tree_light(src, dst, manifest, "pkg")
        assert (dst / "init.py").read_bytes() == b"VERSION = 'beta1'\n"

        (src / "init.py").write_bytes(b"VERSION = 'beta6'\n")
        mod.copy_tree_light(src, dst, manifest, "pkg")

        assert (dst / "init.py").read_bytes() == b"VERSION = 'beta6'\n", (
            "内容改动没被搬进暂存树——`--force` 之外的默认路径仍会产出装旧代码的包")

    def test_unchangedTreeStillSkipsTheCopy(self, tmp_path):
        """反向控制：什么都没改时**必须仍跳过**（不许把根修做成每次全量重拷）。"""
        mod = _load()
        src = tmp_path / "pkg"
        src.mkdir()
        (src / "init.py").write_bytes(b"VERSION = 'beta6'\n")

        manifest = {}
        mod.copy_tree_light(src, tmp_path / "staged" / "pkg", manifest, "pkg")
        staged = tmp_path / "staged" / "pkg" / "init.py"
        staged.write_bytes(b"SENTINEL-KEEP-ME\n")

        manifest_before = dict(manifest)
        mod.copy_tree_light(src, tmp_path / "staged" / "pkg", manifest, "pkg")

        assert staged.read_bytes() == b"SENTINEL-KEEP-ME\n", (
            "未变的树被重拷了——打包机上 1GB 级的 models 会被反复全量复制")
        assert manifest == manifest_before

    def test_replacingLargeFileIsDetectedEvenWithoutSizeChange(self, tmp_path):
        """超过内容哈希上限的大文件（models 那种 GB 级）换掉同尺寸一份，也必须被发现。

        这一形不走内容哈希（成本），走**每文件尺寸＋修改时刻**的组合项：换文件必然动 mtime。
        """
        mod = _load()
        cap = getattr(mod, "MAX_HASH_BYTES", _DEFAULT_HASH_CAP)
        src = tmp_path / "models"
        src.mkdir()
        big = src / "weight.bin"
        with open(big, "wb") as f:
            f.seek(cap)
            f.write(b"HEAD-A")
        os.utime(big, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        before = mod.dir_fingerprint(src)

        with open(big, "r+b") as f:
            f.seek(cap)
            f.write(b"HEAD-B")
        os.utime(big, ns=(1_700_000_001_000_000_000, 1_700_000_001_000_000_000))
        after = mod.dir_fingerprint(src)

        assert before["bytes"] == after["bytes"], "样本没造出「同尺寸」这一形"
        assert before != after, "大文件被替换而指纹不变——超阈值那部分只剩字节数，看不见换过文件"

    def test_fingerprintIsDeterministicForTheSameTree(self, tmp_path):
        """同一棵树连算两次必须等值（否则增量缓存永远判「变了」，等于没有缓存）。"""
        mod = _load()
        src = tmp_path / "config"
        (src / "sub").mkdir(parents=True)
        (src / "a.json").write_text('{"k": 1}', encoding="utf-8")
        (src / "sub" / "b.py").write_text("x = 2\n", encoding="utf-8")
        assert mod.dir_fingerprint(src) == mod.dir_fingerprint(src)


@pytest.mark.parametrize("suffix", [".py", ".json", ".toml", ".txt"])
def test_textSourcesAreHashedNotJustCounted(tmp_path, suffix):
    """参数化钉住「文本源走内容项」：逐个后缀各造一份同尺寸改内容的样本。

    只测 .py 会留下「改的是配置 JSON 照样静默跳过」这条路。
    """
    mod = _load()
    src = tmp_path / f"t{suffix.strip('.')}"
    src.mkdir()
    f = src / f"m{suffix}"
    f.write_bytes(b"AAAA")
    before = mod.dir_fingerprint(src)
    f.write_bytes(b"BBBB")
    assert mod.dir_fingerprint(src) != before, f"{suffix} 的内容改动没进指纹"
