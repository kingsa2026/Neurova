# -*- coding: utf-8 -*-
"""glib 0.18.5 本地补丁守卫（RUSTSEC-2024-0429 / GHSA-wrw7-89jp-8q8g）。

为什么要有本守卫：`glib` 由 Tauri 桌面栈的 gtk 层拉入（wry / tao 一律钉
`gtk ^0.18`），本仓无 registry 升级路径，故按上游 0.20.0 的修法就地打补丁：
vendor 一份 crates.io 0.18.5 源码、只改 `VariantStrIter::impl_get` 的出参
（`&p` → `&mut p`），由 `[patch.crates-io]` 顶替来源、版本号保持 0.18.5。

这套改动有一处与「普通修依赖」本质不同的地方，也是本守卫存在的唯一理由：
**OSV 按 `name + version` 查库，不解析 `[patch]` 段**，所以漏洞扫描器看到的
永远是「0.18.5 未修」。于是「源码已修」这件事没有任何外部工具替我们背书，
只能靠仓内自证。少了本守卫，删掉 `vendor/glib-0.18.5` 或退回 `[patch]` 段
仍然全绿——`scripts/ci/osv-allowlist.toml` 里那条就从「已修」退化成
「给不存在的修复背书」。

守卫锁八件事（任一松掉，「已修」就不再成立）：
1. 补丁副本在内且版本仍是 0.18.5（换版本会破 gtk 的 `^0.18` 约束）；
2. 副本里确实是修复后的源码（可变出参），且未退回不可变出参；
3. `[patch.crates-io]` 真把 glib 指向副本；
4. 锁文件里 glib 条目失去 `source`/`checksum`（= cargo 确认走本地）；
5. 允许清单条目与补丁绑定（理由点名副本路径）；
6. 门禁脚本自己会核验（`LOCAL_PATCHES` + `verify_local_patches`，空手不认账）；
7. 退役信号可见：gtk 仍在 0.18 线（一旦抬到 `^0.19` 就该升栈删补丁）；
8. 本守卫自身在受保护子集里（否则 CI 不跑它）。

可证伪性：每类断言都对应一条「回退即转红」的路径，见各用例 docstring。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

VENDOR_DIR = PROJECT_ROOT / "NeurUI" / "src-tauri" / "vendor" / "glib-0.18.5"
VENDOR_VARIANT_ITER = VENDOR_DIR / "src" / "variant_iter.rs"
PATCH_NOTES = VENDOR_DIR / "PATCH_NOTES.md"
MANIFEST = PROJECT_ROOT / "NeurUI" / "src-tauri" / "Cargo.toml"
LOCKFILE = PROJECT_ROOT / "NeurUI" / "src-tauri" / "Cargo.lock"
ALLOWLIST = PROJECT_ROOT / "scripts" / "ci" / "osv-allowlist.toml"
AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "ci" / "osv_audit.py"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

# 漏洞公告 id 与承载它的包：本守卫全部判据都挂在这两者上。
ADVISORY_ID = "RUSTSEC-2024-0429"
CRATE = "glib"
CRATE_VERSION = "0.18.5"

# 补丁生效的唯一形态：出参可变。退回 `let p` / `&p` 即未修（红）。
_PATCHED_DECL = re.compile(r"let mut p: \*mut libc::c_char = std::ptr::null_mut\(\);")
_PATCHED_ARG = re.compile(r"&mut p,")
_UNPATCHED_DECL = re.compile(r"let p: \*mut libc::c_char = std::ptr::null_mut\(\);")

_LOCK_NAME = re.compile(r'name = "([^"]+)"')
_LOCK_VERSION = re.compile(r'version = "([^"]+)"')
_SOURCE_FIELD = re.compile(r'^source = ', re.M)
_CHECKSUM_FIELD = re.compile(r'^checksum = ', re.M)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _lock_block(crate: str) -> str:
    """取 Cargo.lock 里某个 [[package]] 段落的原文（找不到返回空串）。"""
    text = _read(LOCKFILE)
    blocks = re.split(r"(?m)^\[\[package\]\]$", text)[1:]
    for block in blocks:
        name = _LOCK_NAME.search(block)
        if name and name.group(1) == crate:
            return block
    return ""


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("osv_audit_local_patch", AUDIT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPatchSourceIsInPlace:
    """补丁副本必须在内，且仍是 0.18.5 的源码（不是空目录、不是别的版本）。"""

    def test_vendor_crate_directory_exists(self):
        """回退路径：删掉 vendor 目录 → 转红（补丁没了，已修无从谈起）。"""
        assert (VENDOR_DIR / "Cargo.toml").is_file(), (
            f"补丁副本不是 crate: {VENDOR_DIR}\n"
            "该目录是 glib 0.18.5 未定义行为的唯一修复载体，"
            "删掉它 [patch.crates-io] 会指向不存在的路径（cargo 直接报错）。"
        )

    def test_vendor_crate_keeps_upstream_version(self):
        """版本号必须保持 0.18.5：抬到 0.19+ 会破 gtk 的 glib ^0.18 约束。

        回退路径：把副本 Cargo.toml 的 version 改成 0.19.0 → 转红。
        """
        text = _read(VENDOR_DIR / "Cargo.toml")
        match = re.search(
            r'(?m)^name = "' + re.escape(CRATE) + r'"\nversion = "([^"]+)"', text
        )
        assert match, f"副本 Cargo.toml 未声明 {CRATE} 的 name/version"
        assert match.group(1) == CRATE_VERSION, (
            f"补丁副本版本是 {match.group(1)}，应为 {CRATE_VERSION}——"
            "改版本号会让 gtk 的 glib ^0.18 约束失配"
            "（本仓 29be2081 曾因此打断 Windows 打包）。"
        )

    def test_patch_notes_document_retirement(self):
        """副本必须自述补丁内容与退役条件（否则接手人不知道何时该删）。"""
        assert PATCH_NOTES.is_file(), f"缺 {PATCH_NOTES.name}——补丁无自述"
        notes = _read(PATCH_NOTES)
        assert "退役条件" in notes, "PATCH_NOTES.md 未写退役条件（何时删本目录）"


class TestVendorSourceCarriesTheFix:
    """副本里那一处改动必须真在，且不得退回未修形态。"""

    def test_impl_get_takes_mutable_out_param(self):
        """上游修法：出参指针以可变引用传入（不可变时写穿会被优化丢弃）。

        回退路径：把 `let mut p` 改回 `let p`、`&mut p` 改回 `&p` → 转红。
        """
        source = _read(VENDOR_VARIANT_ITER)
        assert _PATCHED_DECL.search(source), (
            "副本的 impl_get 未声明可变出参（缺 `let mut p: *mut libc::c_char = ...`）——"
            "补丁内容丢失，编译的仍是未修源码。"
        )
        assert _PATCHED_ARG.search(source), (
            "副本的 impl_get 未把出参以 `&mut p` 传入 C 函数——"
            "不可变引用下写穿会被丢弃，随后 CStr::from_ptr(NULL) 解引用崩溃。"
        )

    def test_unpatched_form_is_gone(self):
        """未修形态必须消失：留着就等于把漏洞源码又抄了一遍。"""
        source = _read(VENDOR_VARIANT_ITER)
        assert not _UNPATCHED_DECL.search(source), (
            "副本里仍存在不可变出参形态"
            "`let p: *mut libc::c_char = std::ptr::null_mut();`——"
            "补丁被回退，段错误会复现。"
        )


class TestWiringPointsAtTheVendorCopy:
    """[patch.crates-io] 与锁文件必须真把编译来源换到副本。"""

    def test_manifest_patches_crates_io_to_vendor(self):
        """回退路径：删掉 [patch.crates-io] 段 → 转红（编译回到 registry 未修版）。"""
        text = _read(MANIFEST)
        assert "[patch.crates-io]" in text, (
            "Cargo.toml 缺 [patch.crates-io] 段——glib 会回到 registry 的未修 0.18.5。"
        )
        patch_section = text.split("[patch.crates-io]", 1)[1]
        match = re.search(
            r'(?m)^' + re.escape(CRATE) + r'\s*=\s*\{\s*path\s*=\s*"([^"]+)"\s*\}',
            patch_section,
        )
        assert match, f"[patch.crates-io] 未把 {CRATE} 指向本地路径"
        declared = (MANIFEST.parent / match.group(1)).resolve()
        assert declared == VENDOR_DIR.resolve(), (
            f"[patch.crates-io] 指向 {match.group(1)}，实际副本在 "
            f"{VENDOR_DIR.relative_to(PROJECT_ROOT)}——接线与目录不一致。"
        )

    def test_lockfile_entry_is_local_not_registry(self):
        """锁里 glib 必须失去 source/checksum（cargo 确认走本地）。

        回退路径：给锁里 glib 加回 source = registry+... → 转红。
        """
        block = _lock_block(CRATE)
        assert block, f"Cargo.lock 里找不到 {CRATE} 条目"
        assert f'version = "{CRATE_VERSION}"' in block, (
            f"锁里 {CRATE} 不是 {CRATE_VERSION}——版本漂移会让本守卫的判据错位。"
        )
        assert not _SOURCE_FIELD.search(block), (
            f"Cargo.lock 的 {CRATE} 仍带 source 字段——[patch.crates-io] 未生效，"
            "实际编译的是 registry 的未修版本。"
        )
        assert not _CHECKSUM_FIELD.search(block), (
            f"Cargo.lock 的 {CRATE} 仍带 checksum——同上，说明走的还是 registry。"
        )

    def test_gtk_still_on_018_line(self):
        """退役信号：gtk 一旦离开 0.18 线，就该升栈到 glib >= 0.20 并删本补丁。

        这条不是「必须永远为真」，而是「补丁存在的前提仍在」——
        前提失效时它会转红，提醒把 vendor 目录与 [patch] 段一起退役。
        """
        block = _lock_block("gtk")
        assert block, "Cargo.lock 里找不到 gtk（桌面栈结构已变，请复核本守卫）"
        match = _LOCK_VERSION.search(block)
        version = match.group(1) if match else "未知"
        assert version.startswith("0.18."), (
            f"gtk 已到 {version}——桌面栈可能已可升到 glib >= 0.20。\n"
            "此时应升级 Tauri 栈、删除 vendor/glib-0.18.5、[patch.crates-io] 段与 "
            f"{ALLOWLIST.relative_to(PROJECT_ROOT)} 里的 {ADVISORY_ID} 条目，"
            "而不是继续维持本地补丁。"
        )


class TestAllowlistEntryIsBoundToThePatch:
    """允许清单里那条的语义是「已修、与补丁绑定」，必须能从文本核出这层绑定。"""

    def _entry_block(self) -> str:
        text = _read(ALLOWLIST)
        blocks = re.split(r"\[\[IgnoredVulns\]\]", text)[1:]
        for block in blocks:
            if re.search(r'(?m)^id = "' + re.escape(ADVISORY_ID) + r'"', block):
                return block
        return ""

    def test_entry_exists(self):
        assert self._entry_block(), (
            f"允许清单缺 {ADVISORY_ID} 条目。注意：本条目不应删除——OSV 不解析 "
            "[patch] 段，去掉 source/checksum 后它照旧按 0.18.5 命中；"
            "删条目只会让门禁在扫描器侧报红，而修复依据随之消失。"
        )

    def test_reason_names_the_vendor_copy(self):
        """回退路径：把理由改回「等上游」→ 转红（清单又成了未修豁免）。"""
        block = self._entry_block()
        assert "vendor/glib-0.18.5" in block, (
            f"{ADVISORY_ID} 的理由未点名补丁副本路径——清单条目与补丁脱钩后，"
            "它读起来就是一条未修的豁免（这正是 Issue #109 要消除的形态）。"
        )
        assert "本地补丁" in block, (
            f"{ADVISORY_ID} 的理由未说明已由本地补丁修复——语义退回静音。"
        )


class TestGateVerifiesLocalPatchesItself:
    """门禁必须自己核验补丁仍在，不能只靠清单文字。"""

    def test_local_patches_registry_binds_lock_crate_and_path(self):
        module = _load_audit_module()
        registry = module.LOCAL_PATCHES
        assert registry, "osv_audit 未登记任何本地补丁——允许清单里的已修无人核验"
        lock_key = LOCKFILE.relative_to(PROJECT_ROOT).as_posix()
        assert lock_key in registry, f"LOCAL_PATCHES 未登记锁文件 {lock_key}"
        crates = registry[lock_key]
        assert crates.get(CRATE), f"LOCAL_PATCHES 未登记 {CRATE} 的补丁路径"
        declared = (PROJECT_ROOT / crates[CRATE]).resolve()
        assert declared == VENDOR_DIR.resolve(), (
            f"LOCAL_PATCHES 登记的路径 {crates[CRATE]} 与实际副本不一致"
        )

    def test_verify_reports_nothing_on_current_tree(self):
        """当前树必须通过核验（真调函数，不看文字）。"""
        module = _load_audit_module()
        problems = module.verify_local_patches()
        assert problems == [], (
            "本地补丁核验在当前树上就报错——门禁会直接退出 2。\n"
            f"问题: {problems}"
        )

    def test_verify_fails_when_registry_source_returns(self, tmp_path, monkeypatch):
        """可证伪性：锁里该包重新带上 source 时，核验必须报出问题。

        这条钉的是「核验判据真的咬合」，不是「库里有文件」——
        没有它，verify_local_patches 返回空列表也能让本类全绿。
        """
        module = _load_audit_module()
        crate_dir = tmp_path / "NeurUI" / "src-tauri"
        vendor_copy = crate_dir / "vendor" / "glib-0.18.5"
        vendor_copy.mkdir(parents=True)
        (vendor_copy / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
        lock_text = _read(LOCKFILE).replace(
            f'name = "{CRATE}"\nversion = "{CRATE_VERSION}"\n',
            f'name = "{CRATE}"\nversion = "{CRATE_VERSION}"\n'
            'source = "registry+https://github.com/rust-lang/crates.io-index"\n',
            1,
        )
        (crate_dir / "Cargo.lock").write_text(lock_text, encoding="utf-8")
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
        problems = module.verify_local_patches()
        assert problems, (
            "锁里 glib 带回 source 字段后核验仍报通过——判据不咬合，"
            "[patch.crates-io] 失效时门禁会静默放行。"
        )

    def test_verify_fails_when_vendor_copy_is_gone(self, tmp_path, monkeypatch):
        """可证伪性：副本目录消失时核验必须报出问题。"""
        module = _load_audit_module()
        crate_dir = tmp_path / "NeurUI" / "src-tauri"
        crate_dir.mkdir(parents=True)
        (crate_dir / "Cargo.lock").write_text(_read(LOCKFILE), encoding="utf-8")
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
        problems = module.verify_local_patches()
        assert problems, (
            "补丁副本目录不存在时核验仍报通过——允许清单会为不存在的修复背书。"
        )


class TestGuardIsWiredIntoCi:
    """本守卫必须真被 CI 跑到，否则以上断言全是摆设。"""

    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in _read(PROTECTED).splitlines()
        }
        rel = Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix()
        assert rel in listed, (
            f"{rel} 不在 scripts/ci/protected_tests.txt —— unit-tests 流水线不会跑它，"
            "补丁被回退时 CI 静默放行。"
        )
