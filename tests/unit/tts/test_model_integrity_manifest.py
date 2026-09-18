# -*- coding: utf-8 -*-
"""模型产物完整性守卫（Issue #56 残留边界：运行时拉取的二进制）。

背景：pip-audit / npm audit / OSV 覆盖的都是"包管理器的依赖树"。模型权重
不在其中——它们是经 snapshot_download / 镜像直链拉到本地后**直接喂给
onnxruntime 反序列化**的二进制。此前零校验：

- 镜像站投毒 → 加载攻击者权重（反序列化面 + 推理结果被操控）
- 传输截断 / 磁盘静默损坏 → 推理结果错但"无报错"
- LFS 未拉（CI 常态）→ 拿到的是 130 字节指针文件，却"存在且非空"

本守卫锁定三件事：
1. MANIFEST 覆盖每个模型的全部 `required_files`（下载器保证存在的那些）；
2. MANIFEST 里的哈希与**上游发布值**一致（ModelScope API 的 Sha256 / HF 的
   LFS oid——两者对同一文件一致，都是 sha256）；本仓在库文件（非 LFS 指针）
   也逐一对齐，锚定两侧，任一侧漂移即红；
3. 校验逻辑本身可用：好文件通过、改一个字节即被抓出、LFS 指针被正确跳过。
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from neurova.tts.model_downloader import MODEL_REGISTRY
from neurova.tts.model_integrity import (
    MANIFEST,
    find_altered_files,
    is_lfs_pointer,
    manifest_covers_required_files,
    manifest_for,
    sha256_file,
    verify_model,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TestManifestCoverage:
    """每个模型的 required_files 必须全部进清单（否则该文件裸奔）。"""

    @pytest.mark.parametrize("model_name", sorted(MODEL_REGISTRY))
    def test_all_required_files_covered(self, model_name):
        required = MODEL_REGISTRY[model_name]["required_files"]
        uncovered = manifest_covers_required_files(model_name, required)
        assert not uncovered, (
            f"{model_name} 的 required_files 未进完整性清单: {uncovered}\n"
            "这些文件下载后不做哈希校验——镜像投毒/截断不会被发现。\n"
            "补 MANIFEST（sha256 取上游发布值）。"
        )

    @pytest.mark.parametrize("model_name", sorted(MODEL_REGISTRY))
    def test_manifest_has_no_extra_entries_outside_known_files(self, model_name):
        """清单条目必须是该模型真实存在的文件（防手误写错文件名 → 校验静默失效）。"""
        entry = MODEL_REGISTRY[model_name]
        known = set(entry["required_files"]) | set(entry.get("files") or []) | {
            # 随 required_files 一起下发的说明/清单文件
            "model.onnx", "config.json", "vocab.txt", "README.md",
            "tts_browser_onnx_meta.json", "browser_poc_manifest.json",
            "codec_browser_onnx_meta.json",
        }
        unknown = set(manifest_for(model_name)) - known
        assert not unknown, (
            f"{model_name} 清单含未知文件 {unknown}——文件名写错会让校验查一个"
            "永远不存在的路径（要么误报 missing，要么被跳过）。"
        )

    def test_every_hash_is_sha256_hex(self):
        for model, files in MANIFEST.items():
            for fname, digest in files.items():
                assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), (
                    f"{model}/{fname} 的哈希不是 64 位十六进制（sha256）: {digest!r}"
                )


class TestCommittedWeightsMatchManifest:
    """本仓在库的大文件必须与清单一致（两侧锚定，防清单被"顺手改绿"）。"""

    # 只校验非 LFS 指针的在库文件；LFS 大文件由 CI 按需 smudge，
    # 指针态下无法校验内容（见 is_lfs_pointer 的用途）。
    @pytest.mark.parametrize(
        "model_name,fname",
        [
            ("moss-tts-nano", "moss_tts_prefill.onnx"),
            ("moss-tts-nano", "moss_tts_local_decoder.onnx"),
            ("moss-tts-nano", "tokenizer.model"),
            ("moss-audio-tokenizer", "moss_audio_tokenizer_encode.onnx"),
            ("bge-small-zh-v1.5", "model.safetensors"),
        ],
    )
    def test_in_repo_file_matches_manifest(self, model_name, fname):
        rel = MODEL_REGISTRY[model_name]["local_dir"]
        candidates = [PROJECT_ROOT / rel / fname, PROJECT_ROOT / "embedding" / "bge-small-zh-v1.5" / fname]
        found = None
        for c in candidates:
            if c.is_file() and not is_lfs_pointer(c):
                found = c
                break
        if found is None:
            pytest.skip(f"{rel}/{fname} 不在库或为 LFS 指针（本地未拉取）")

        expected = manifest_for(model_name)[fname]
        assert sha256_file(found) == expected, (
            f"在库文件与清单不一致: {found.relative_to(PROJECT_ROOT)}\n"
            f"  清单期望 {expected}\n"
            f"  实得     {sha256_file(found)}\n"
            "若确为上游改版，需同步更新 MANIFEST 并说明来源。"
        )


class TestVerificationLogic:
    """校验逻辑自身的双向验证（好文件过 / 坏文件红 / 指针跳过）。"""

    def _model_dir(self, tmp_path: Path, model_name: str, payload: bytes = b"good"):
        d = tmp_path / MODEL_REGISTRY[model_name]["local_dir"]
        d.mkdir(parents=True, exist_ok=True)
        for f in MODEL_REGISTRY[model_name]["required_files"]:
            (d / f).write_bytes(payload)
        return d

    def test_good_files_pass_when_manifest_matches(self, tmp_path, monkeypatch):
        """构造一份"与清单一致"的产物 → 校验应通过。"""
        model = "moss-tts-nano"
        d = self._model_dir(tmp_path, model)
        # 把清单改成当前实际哈希（模拟"下载到的就是期望内容"，必然全绿）
        fake_manifest = {f: sha256_file(d / f) for f in MODEL_REGISTRY[model]["required_files"]}
        monkeypatch.setitem(MANIFEST, model, fake_manifest)
        assert find_altered_files(model, d) == []
        verify_model(model, d)  # 不抛即通过

    def test_single_byte_flip_is_caught(self, tmp_path):
        """改一个字节必须被抓出——这是"静默损坏"的最小可复现形态。"""
        model = "bge-small-zh-v1.5"
        d = self._model_dir(tmp_path, model)
        target = d / "model.safetensors"
        target.write_bytes(b"tampered")
        altered = find_altered_files(model, d)
        flagged = [n for n, _, _ in altered]
        assert "model.safetensors" in flagged, "被篡改的文件必须被抓出"
        _, expected, actual = next(a for a in altered if a[0] == "model.safetensors")
        assert expected == manifest_for(model)["model.safetensors"]
        assert actual != expected
        with pytest.raises(RuntimeError) as ei:
            verify_model(model, d)
        assert "完整性校验失败" in str(ei.value)
        # 报错信息必须带双方哈希（可诊断），且不泄露模型内容
        assert expected[:16] in str(ei.value)

    def test_missing_file_reported(self, tmp_path):
        model = "bge-small-zh-v1.5"
        d = self._model_dir(tmp_path, model)
        (d / "tokenizer.json").unlink()
        altered = find_altered_files(model, d)
        assert ("tokenizer.json", manifest_for(model)["tokenizer.json"], "(missing)") in altered

    def test_lfs_pointer_is_skipped_not_flagged(self, tmp_path, monkeypatch):
        """LFS 指针不是"损坏"——未 smudge 的大文件必须跳过，否则 CI 恒红。"""
        model = "moss-tts-nano"
        d = self._model_dir(tmp_path, model)
        # 把其余文件对齐清单，隔离出"指针是否被跳过"这一条判据
        monkeypatch.setitem(
            MANIFEST, model,
            {f: sha256_file(d / f) for f in MODEL_REGISTRY[model]["required_files"]},
        )
        ptr = d / "moss_tts_prefill.onnx"
        ptr.write_bytes(
            b"version https://git-lfs.github.com/spec/v1\n"
            b"oid sha256:" + (b"a" * 64) + b"\nsize 283305\n"
        )
        assert is_lfs_pointer(ptr)
        assert find_altered_files(model, d) == []

    def test_lfs_pointer_detection_rejects_real_content(self, tmp_path):
        """普通内容不得被误判为指针（否则真损坏会被跳过 = 校验形同虚设）。"""
        real = tmp_path / "real.onnx"
        real.write_bytes(b"\x08\x07\x12\x07pytorch")
        assert not is_lfs_pointer(real)

    def test_unknown_model_skips_verification(self, tmp_path):
        """无清单的模型不校验（清单是增量落地的，缺席不该拦住下载）。"""
        assert manifest_for("no-such-model") == {}
        assert find_altered_files("no-such-model", tmp_path) == []


class TestDownloaderWiresVerification:
    """ensure_model 确实接上了校验（含"清理坏文件让重下自愈"）。"""

    def test_bad_hash_cleans_files_and_raises(self, tmp_path, monkeypatch):
        from neurova.tts import model_downloader as md

        model = "bge-small-zh-v1.5"

        def engine(registry, model_dir, cb=None):
            for f in registry["required_files"]:
                p = model_dir / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"poisoned")  # 哈希必然不符

        monkeypatch.setattr(md, "_download_via_modelscope", engine)
        dl = md.ModelDownloader(base_dir=str(tmp_path))  # 校验默认开启
        with pytest.raises(RuntimeError) as ei:
            dl.ensure_model(model, source="modelscope")
        assert "完整性校验失败" in str(ei.value)

        # 坏文件已清理 → is_model_available False → 下次调用会重下（自愈）
        d = tmp_path / MODEL_REGISTRY[model]["local_dir"]
        assert not (d / "model.safetensors").exists()
        assert dl.is_model_available(model) is False

    def test_verification_can_be_disabled_for_stub_envs(self, tmp_path, monkeypatch):
        from neurova.tts import model_downloader as md

        model = "bge-small-zh-v1.5"

        def engine(registry, model_dir, cb=None):
            for f in registry["required_files"]:
                p = model_dir / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"stub")

        monkeypatch.setattr(md, "_download_via_modelscope", engine)
        dl = md.ModelDownloader(base_dir=str(tmp_path), verify_integrity=False)
        assert dl.ensure_model(model, source="modelscope")  # 不抛

    def test_env_var_can_disable_verification(self, tmp_path, monkeypatch):
        from neurova.tts import model_downloader as md

        monkeypatch.setenv("NEUROVA_MODEL_INTEGRITY", "off")
        dl = md.ModelDownloader(base_dir=str(tmp_path))
        assert dl._verify_integrity is False
        model = "bge-small-zh-v1.5"

        def engine(registry, model_dir, cb=None):
            for f in registry["required_files"]:
                p = model_dir / f
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"stub")

        monkeypatch.setattr(md, "_download_via_modelscope", engine)
        assert dl.ensure_model(model, source="modelscope")
