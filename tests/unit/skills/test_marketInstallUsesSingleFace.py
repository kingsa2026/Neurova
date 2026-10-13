# -*- coding: utf-8 -*-
"""§6-177 批 32：市场安装那条活路的解压判定收进咽喉（同根因扫荡 + 单源）。

现役路径是 `marketplace.install_skill → market_importer.import_skill →
market_sources.extract_remote_skill_zip`（**不是** `market_adapters` 那张没人调的 install 面）。
这条路上原本自己写着第二份解压判定：自己数条目、自己判 `..`、逐条 `write_bytes`，而仓内咽喉
`security/safe_archive.py` 已被 6 处生产点消费。两份并存时咽喉修了这里不跟着修——教义第 6/7 条
的反面。按比-取-接-退：机制进咽喉，**上限作调用方递进来的参数**（上限数值属于市场安装这条路，
不属于解包器；缺省就设限会把另外 6 个调用点的形状被本批莫名挪动），判定只留一处。

同一批挖出来、刻意**不写成判据**的一条：市场安装只往 `skills/{id}/skill.json` 写元数据，而
`skill.json` 在全仓**零读者**（两处写者 `hub_client.py:531`、`market_importer.py:314`），
`call_skill` 取摘要的是 `<skills_dir>/manifest.json` 里那条账（`skill_service.py:171-173、1695`）。
⇒ 给这一侧钉摘要就是"写进没人读的文件"，而写一格"今天确实没人读"的断言等于给坏状态焊死修复路。
这条按 AGENTS §7 带影响面进台账 §6-177 待裁，不在这里留判据。

上限用 monkeypatch 改模块常量来验，不把 10MB/500 写死进判据——写死了就只证明判据自己。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) .venv/Scripts/python.exe -m pytest \
tests/unit/skills/test_marketInstallUsesSingleFaceAndPins.py -q`
"""

from __future__ import annotations

import inspect
import io
import warnings
import zipfile
from pathlib import Path

import pytest

from neurova.security import safe_archive
from neurova.skills import market_sources

from tests import ast_scan

REAL_BUNDLE_DIR = Path(market_sources.__file__).resolve().parent
NEUROVA_ROOT = REAL_BUNDLE_DIR.parent


def _zipBytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _extractallFiles() -> list:
    """真调了解包器的文件清单：按 AST 取调用节点，不按文本。

    文本守卫既会把注释里那句「原 extractall 无成员校验」算成命中（假红），
    又会放过真调用旁的任何写法；只有调用节点才是事实。

    取数走共享解析预算 `tests/ast_scan`（Issue #148）：`extractall` 是判据的
    **充分条件**——连这个符号都没出现的文件不可能命中，故带文本预筛。
    私有 `rglob + ast.parse` 把「解析量」绑成「代码总量」，与其余受保护文件
    共享机器时撞 30s 墙钟。
    """
    return sorted({
        path.relative_to(NEUROVA_ROOT).as_posix()
        for path, _line in ast_scan.callSites(NEUROVA_ROOT, "extractall")
    })


# ── 落盘解包只剩一处 ──


def testExtractallSurvivesOnlyInsideTheSingleFace():
    """往目录里写压缩包成员的落点只允许咽喉那一个文件；市场侧那份已随本批退役，别让它长回来。
    口径按**文件**取不按调用次数取（咽喉内部为 tar 的 filter 回退留了两次调用，那是实现细节
    不是纪律）；`backup/`、`skill_packager` 里的 `namelist()` 只把成员读进内存、不落盘，不算命中。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        assert _extractallFiles() == ["security/safe_archive.py"], (
            f"落盘解包必须只发生在咽喉一个文件里，实得 {_extractallFiles()}"
        )


def testExtractallProbeHasTeeth(tmp_path):
    """排除型断言在功能缺失时会自动成立——先证探针抓得到真调用、也不被注释骗。

    探针现走共享入口 `ast_scan.callSites`（原私有 `_extractallCalls` 已退役）：
    反向对照仍按同一判据取数，在临时树里放三种写法逐条反证。
    """
    tree = tmp_path / "probe"
    tree.mkdir()
    (tree / "real.py").write_text("def f(zf, d):\n    zf.extractall(d)\n", encoding="utf-8")
    (tree / "commented.py").write_text("# 原 extractall 无成员校验\nPASS\n", encoding="utf-8")
    (tree / "defined.py").write_text("class A:\n    def extractall(self, d): pass\n",
                                    encoding="utf-8")

    hits = {path.name for path, _line in ast_scan.callSites(tree, "extractall")}

    assert hits == {"real.py"}, f"探针抓不到真调用或被注释/定义骗：{hits}"


# ── 市场侧只递策略，不重写判定 ──


def testExtractionGoesThroughTheSingleFaceWithCallerCaps(monkeypatch, tmp_path):
    """市场侧不许自己判条目/判路径：必须把活儿交给咽喉，并把自己那两条上限现取常量递进去。"""
    seen = []

    def spy(source, target_dir, *, maxPayloadBytes=None, maxEntries=None):
        seen.append({"maxPayloadBytes": maxPayloadBytes, "maxEntries": maxEntries})
        return Path(target_dir)

    monkeypatch.setattr(safe_archive, "safe_extract_zip", spy)
    ok = market_sources.extract_remote_skill_zip(
        "s1", _zipBytes({"SKILL.md": "hi"}), tmp_path / "dest"
    )

    assert ok is True, "咽喉正常返回时市场侧必须报成功"
    assert len(seen) == 1, f"解压必须只走咽喉一次，实得 {len(seen)} 次"
    assert seen[0] == {
        "maxPayloadBytes": market_sources.MAX_SKILL_ZIP_BYTES,
        "maxEntries": market_sources.MAX_ZIP_ENTRIES,
    }, f"上限必须由调用方现取模块常量递进咽喉，实得 {seen[0]}"


def testEntryCapIsEnforcedBeforeAnythingIsWritten(monkeypatch, tmp_path):
    """条目数超上限 ⇒ False 且一个文件都不落（判完再写，不是写一半才发现越限）。"""
    monkeypatch.setattr(market_sources, "MAX_ZIP_ENTRIES", 2)
    dest = tmp_path / "dest"
    payload = _zipBytes({"a.txt": "1", "b.txt": "2", "c.txt": "3"})

    assert market_sources.extract_remote_skill_zip("s2", payload, dest) is False
    written = [p.name for p in dest.rglob("*") if p.is_file()] if dest.exists() else []
    assert written == [], "拒绝必须发生在写盘之前"


def testOversizedPayloadIsRefusedAsTooLargeNotAsBadZip(monkeypatch, tmp_path):
    """两种拒因不许互相盖：过大与"根本不是 zip"是两条不同的路，日志得能分辨。"""
    monkeypatch.setattr(market_sources, "MAX_SKILL_ZIP_BYTES", 16)
    garbage = b"x" * 17  # 既超限又根本不是 zip

    assert market_sources.extract_remote_skill_zip("s3", garbage, tmp_path / "dest") is False
    with pytest.raises(safe_archive.UnsafeArchiveError) as oversized:
        safe_archive.safe_extract_zip(garbage, tmp_path / "direct", maxPayloadBytes=16)
    assert "字节" in str(oversized.value), f"拒因必须点名字节数，实得 {oversized.value}"
    with pytest.raises(zipfile.BadZipFile):
        safe_archive.safe_extract_zip(b"definitely not a zip", tmp_path / "direct2")


def testPathEscapeStillRefusesAndCreatesNothingOutsideDest(tmp_path):
    """收敛之后 zip-slip 那一牙必须在（两份实现合一后最容易被悄悄削掉的就是它）。"""
    dest = tmp_path / "skills" / "s4"
    escaped = tmp_path / "escaped.txt"
    payload = _zipBytes({"../escaped.txt": "pwned", "SKILL.md": "hi"})

    assert market_sources.extract_remote_skill_zip("s4", payload, dest) is False
    assert not escaped.exists(), "越界成员必须整体拒绝，而不是丢掉那一条继续解"
    assert not (dest / "SKILL.md").exists(), "任一成员越界即 fail-closed"


def testFaceCapsAreOptInSoOtherSixCallSitesDoNotMove(tmp_path):
    """上限是调用方策略：不递参数时咽喉不得自己设限（hub_client／skill_packager 等 6 处
    今天就没有这两条上限，凭空加上去会让大一点的本地包在别的批里莫名炸掉）。"""
    payload = _zipBytes({f"f{i}.txt": "x" for i in range(501)})

    base = safe_archive.safe_extract_zip(payload, tmp_path / "noCaps")
    assert len([p for p in base.rglob("*") if p.is_file()]) == 501
    with pytest.raises(safe_archive.UnsafeArchiveError) as capped:
        safe_archive.safe_extract_zip(payload, tmp_path / "capped", maxEntries=2)
    assert "成员" in str(capped.value)
    # 缺省位也钉住：只看行为的话"默认 500 条"这种暗设的上限要在 501 条样本上才露头，
    # 而签名才是那句"默认不设限"的出处。
    params = inspect.signature(safe_archive.safe_extract_zip).parameters
    assert params["maxPayloadBytes"].default is None, "字节上限不得在咽喉里缺省设值"
    assert params["maxEntries"].default is None, "成员数上限不得在咽喉里缺省设值"
