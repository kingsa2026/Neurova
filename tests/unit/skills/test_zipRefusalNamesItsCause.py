# -*- coding: utf-8 -*-
r"""解包失败必须点名原因（§6-276 立项落地：zip 成员名撞 Windows MAX_PATH 那一格）。

起点是 §6-259 照出来的一条读数：内置资产包 `adaptive-presentation-studio.zip` 在安装面上被拒，
`market_sources.py` 把 `(UnsafeArchiveError, BadZipFile, OSError)` 三类失败折成同一句
`"zip refused"`，`market_importer.py` 再把它折成 `"extract builtin bundle … failed"`——
读的人拿到的是"包被拒了"，而真因是**落点根 + 成员名 = 273 字符 > 260**（该机 `LongPathsEnabled=0`）。
三类失败的处置方向完全不同：安全拒＝该拒；包坏了＝退回上游；根太长＝改部署。折成一句就是
把人支去改一个没坏的包（与 §6-259 那条"拒因文本只准念参与裁决的条目"同族）。

判据分四组，缺一组就还能把失败折回去：
① 真包在长根下失败 ⇒ 原因必须点名"路径过长"并给出**成员长／根长／合计**三个数；
② 三条失败族两两可区分（安全拒／坏包／长路径），且都不许退化成裸 "refused"；
③ 同包在短根下必须成功 ⇒ 钉"点名"不是"新增一道拒绝"；
④ `import_skill` 的 `task.error_message` 也要带上原因（回执面才是人看到的那一行），
   以及 bool 老调用面与新的原因面**同一处判定**（不许长第二套口径）。
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from neurova.security import safe_archive
from neurova.skills import market_sources
from neurova.skills.market_importer import MarketImporter, read_builtin_bundle

BUNDLE = "adaptive-presentation-studio.zip"
REFUSAL_API = "extractRemoteSkillZipRefusal"


def refusalOf(payload: bytes, dest: Path) -> str:
    """取原因面；没落地就先红在"契约没建"，不要让整档吃 ImportError。"""
    fn = getattr(market_sources, REFUSAL_API, None)
    assert callable(fn), (
        f"market_sources 里没有 {REFUSAL_API} ⇒ 原因面尚未落地，本批没做完")
    return fn("probe", payload, dest)


def buildZip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buf.getvalue()


def deepRoot(tmp: Path, skill_id: str, payload: bytes = None) -> Path:
    """复刻 pytest 那种"用例名即目录名"的深根，**逐档现算**而不是抄一个总数。

    `payload` 缺省取仓内资产包：撑根要按"最长成员"算，而不同调用点量的包可能不同
    （合成样本比真包短），故允许显式传；传空则按真资产包量。

    可复算的判据只有一条：`落点根 + 1 + 最长成员名 >= WINDOWS_MAX_PATH`。
    写死"合计 273 字符"是拿旧资产包的长成员当事实源——包里的长成员从 141 字符
    回到 125 之后（终点投影 247），同一个根就装得成了，而**长路径这一族从未消失**，
    红的是那条被抄死的读数。故这里按生产自己那份量法（`_longestProjectedPath`）
    逐档把根撑到超限为止：资产包再变，判据跟着它变，不再跟着某个数字。
    """
    if payload is None:
        payload = read_builtin_bundle(BUNDLE)
        assert payload, f"仓内资产包缺失：{BUNDLE} ⇒ 本档失去根据"
    base = (tmp / "pytest-of-operator" / "pytest-9999"
            / "test_import_builtin_offline[presentation-studio]0" / "skills" / skill_id)
    # 撑到「根 + 1 + 最长成员」超限为止：`_longestProjectedPath` 才是这条链的量法，
    # 拿根长自己跟 260 比会差一个成员名。
    while True:
        projected = market_sources._longestProjectedPath(payload, base)
        if projected is None:
            base = base / ("deep-root-segment-" + "x" * 24)
            continue
        if projected[1] >= market_sources.WINDOWS_MAX_PATH:
            return base
        base = base / ("deep-root-segment-" + "x" * 24)


def _pads(base: Path, skill_id: str, payload: bytes) -> list:
    """从"刚够超限"往上排几档候选根长。

    为什么要试：投影长度与"真会抛 OSError"不是同一个数——本机 ext4 的单段上限 255
    （`PC_NAME_MAX`）先拦下的那一档，报的是"父目录建不出来"，不是本条要的那族失败。
    """
    member = market_sources._longestProjectedPath(payload, Path("x"))
    assert member, "读不出成员清单 ⇒ 本档失去根据，去查资产包"
    overshoot = market_sources.WINDOWS_MAX_PATH - len(str(base / skill_id)) - member[1] + 20
    return [max(overshoot, 0) + step for step in (0, 150, 300, 450)]


def longRoot(tmp: Path, skill_id: str) -> Path:
    """够到预算**之上**的落点根：超限由本函数抬上去，不由机器决定。

    为什么不能只靠 `deepRoot` 那一段：包被瘦身过（当前最长成员 125 字符），
    `deepRoot` 只把投影顶到 247，落在开了长路径的机器上照样装成——那时这一族
    "没被拒"是**机器配置**的读数，不是实现的读数。
    """
    payload = read_builtin_bundle(BUNDLE)
    assert payload, f"仓内资产包缺失：{BUNDLE} ⇒ 本档失去根据"
    base = deepRoot(tmp, "")
    for pad in _pads(base, skill_id, payload):
        dest = base / ("d" * pad) / skill_id
        try:
            market_sources.safe_archive.safe_extract_zip(
                payload, dest,
                maxPayloadBytes=market_sources.MAX_SKILL_ZIP_BYTES,
                maxEntries=market_sources.MAX_ZIP_ENTRIES)
        except OSError:
            return dest
    raise AssertionError(
        "这台机器上抬到 %d 字符仍能装成 ⇒ 本档失去根据（资产包被改瘦、或路径上限放开），"
        "去复测而不是删格" % (market_sources.WINDOWS_MAX_PATH + 450))


def longLibraryRoot(tmp: Path) -> Path:
    """同上，但抬的是**技能库根**，给 `MarketImporter` 用。

    这格要的形状比 `longRoot` 挑剔两条：库根自己建得出来（否则死在本条之外），
    而库根下面再压 `<skill_id>/<成员>` 会抛 OSError。两个鼓包（库根名、技能名前后缀）
    分开调，因为 ext4 的单段上限 255 先咬住的是长的那一段，合并成一个只会两头不落。
    """
    payload = read_builtin_bundle(BUNDLE)
    base = deepRoot(tmp, "")
    for ctorPad in (0, 100, 200, 240, 254):
        libRoot = base / ("c" * ctorPad) / "lib"
        try:
            MarketImporter(skills_dir=libRoot)
        except OSError:
            continue
        for suffix in range(0, 320, 10):
            dest = libRoot / ("s" * (suffix + 1)) / "adaptive-presentation-studio"
            try:
                market_sources.safe_archive.safe_extract_zip(
                    payload, dest,
                    maxPayloadBytes=market_sources.MAX_SKILL_ZIP_BYTES,
                    maxEntries=market_sources.MAX_ZIP_ENTRIES)
            except OSError:
                return libRoot
    raise AssertionError(
        "这台机器上没有「库根能建、但装到最终位置会抛 OSError」的那一档 ⇒ 本档失去根据")


@pytest.fixture()
def builtinPayload() -> bytes:
    payload = read_builtin_bundle(BUNDLE)
    assert payload, f"仓内资产包缺失：{BUNDLE} ⇒ 本档失去根据，去补资产而不是关判据"
    return payload


def test_longRootFailureNamesPathTooLong(builtinPayload, tmp_path):
    """① 主红：长根下的失败必须点名"路径过长"，并给可行动的三个数字。"""
    dest = longRoot(tmp_path, "adaptive-presentation-studio")

    reason = refusalOf(builtinPayload, dest)
    if not reason:
        pytest.skip(
            "本机没因路径长度拒绝这个包（长路径开关/文件系统不同）——"
            "原因文案的**形状**由 `test_reasonIsDerivedFromTheConstantNotASecondCopy` 在本机钉住，"
            "这一格钉的是真链路；不要为此删格，也不要假装它被拒了")
    assert "路径过长" in reason, f"失败又被折成模糊一句话：{reason[:120]}"
    projected = market_sources._longestProjectedPath(builtinPayload, dest)
    assert projected and all(str(n) in reason for n in
                             (len(projected[0]), len(str(dest)), projected[1])), (
        f"原因里没有成员长／根长／合计三个数，读的人仍无从判断该改哪一头：{reason[:160]}")
    assert "zip refused" not in reason.lower(), f"退化回那句折衷文案：{reason[:120]}"


def test_threeFailureFamiliesStayDistinguishable(tmp_path):
    """② 三条失败族两两不同：谁都不许被写成同一句"refused"。"""
    # 第四族是"另一个 IO 故障但**长度没问题**"——它是"落点根太长"这一支的反面对照：
    # 少了这一族，把判定写成"只要是 OSError 就报路径过长"也能全绿（本档变异 M3 第一次就打空）。
    blocker = tmp_path / "blocker"
    blocker.write_text("我不是目录", encoding="utf-8")
    ioFault = refusalOf(buildZip({"short.txt": "x"}), blocker / "sub")
    unsafe = refusalOf(buildZip({"../escape.txt": "x"}), tmp_path / "a")
    broken = refusalOf(b"definitely-not-a-zip", tmp_path / "b")
    longPath = refusalOf(
        buildZip({"a" * 120 + "/" + "b" * 120 + "/deep.txt": "x"}),
        longRoot(tmp_path, "c"))

    reasons = {"安全拒": unsafe, "包坏了": broken, "路径过长": longPath, "IO故障(长度没问题)": ioFault}
    for label, reason in reasons.items():
        assert reason, f"{label} 这一族没被拒——原因面返回空串，判定漏了"
        assert reason.strip(), f"{label} 的原因为空"
    assert len({r.split(":")[0][:24] for r in reasons.values()}) == 4, (
        f"三族原因文案撞成一句，读的人仍分不出该改哪一头：{reasons}")
    # 逐族**只许**出现自己的关键字。写成 `A in r or B in r` 那种"或"式断言，
    # 会被"所有失败都报同一句"的实现蒙过去（本档第一版就栽在这上面，变异 M3 打空）。
    assert "路径过长" not in unsafe, f"安全拒被报成路径过长＝两族又混了：{unsafe[:120]}"
    assert "路径过长" not in broken, f"坏包被报成路径过长＝两族又混了：{broken[:120]}"
    assert "路径过长" not in ioFault, (
        f"长度没问题的 IO 故障也被报成路径过长 ⇒ 判定其实只看'是不是 OSError'，不是看长度：{ioFault[:130]}")
    assert ioFault.strip(), "IO 故障那一族原因面返回空串＝被当成功放过了"
    assert "路径过长" in longPath, f"长路径这一族没点名到落点：{longPath[:140]}"
    assert ("UnsafeArchiveError" in unsafe or "越出" in unsafe or "成员" in unsafe),         f"安全拒没点名是谁拒的：{unsafe[:120]}"
    assert "BadZipFile" in broken or "zip" in broken.lower(), f"坏包没点名：{broken[:120]}"


def test_shortRootStillInstallsTheSameBundle(builtinPayload, tmp_path):
    """③ 同包换短根必须装成：钉"点名原因"不是"顺手多加一道拒绝"。"""
    dest = tmp_path / "skills" / "adaptive-presentation-studio"

    assert refusalOf(builtinPayload, dest) == "", (
        "短根下这个包也装不上了——本批把可安装性改坏了")
    assert (dest / "SKILL.md").is_file(), "解包成功但成员没落盘，去查咽喉而不是改本格"


def test_importerCarriesTheReasonIntoTheReceipt(builtinPayload, tmp_path):
    """④ 回执面（人真正读到的那一行）也必须带原因；成功侧不许出现"假失败"。

    跨机器安全写法：长根那台机器若开了长路径会真装成，那种情况下本格改判"装成即可"，
    但**只要 FAILED，error_message 就必须点名**——这条不依赖本机 OS 设置。
    """
    # 长根抬在**技能库之上一级**：再往下压一层，"最终位置"就会撞上本机单段/单路径上限，
    # 用例会死在 `Path.exists()` 的 ENAMETOOLONG 上，测的就不是回执了。
    importer = MarketImporter(skills_dir=longLibraryRoot(tmp_path))
    task = importer.import_skill("builtin--adaptive-presentation-studio")

    if task.status.value == "failed":
        assert "路径过长" in (task.error_message or ""), (
            f"回执又只剩一句话：{(task.error_message or '')[:160]}")
    else:
        assert task.status.value == "completed", f"状态读数不自洽：{task.status}"


def test_boolFaceAndReasonFaceAreOneImplementation(builtinPayload, tmp_path):
    """④' bool 老调用面与原因面必须同判：薄包装不是第二套口径（教义第 6 条）。"""
    short = tmp_path / "s" / "adaptive-presentation-studio"
    long = longRoot(tmp_path, "l") / "adaptive-presentation-studio"

    assert market_sources.extract_remote_skill_zip("p", builtinPayload, short) is True
    assert refusalOf(builtinPayload, short) == ""
    # 因果按「面上说什么」对账，不假设宿主会拒：装上则两面都必须说装上了，
    # 拒了则两面都必须说拒了——分叉才是缺陷。
    refused = market_sources.extract_remote_skill_zip("p", builtinPayload, long)
    reason = refusalOf(builtinPayload, long)
    assert refused is (reason == ""), (
        f"bool 面与原因面分叉：bool={refused}，原因={reason[:120]!r}——两处判定必须同一份实现")


def test_reasonIsDerivedFromTheConstantNotASecondCopy(builtinPayload, monkeypatch, tmp_path):
    """上限数字必须由那个常量算出来，而且**它真的在闸门上**——不是文案里的装饰。

    反两件事：① 文案里再抄一遍 260（改常量不动文案＝两处各持一份口径，教义第 6 条）；
    ② 常量只是摆设、判定另用一个数。这里直接量格式化函数本身，不依赖本机的操作系统设置：
    同一个成员集合，把上限从 260 调到 40，同一份 OSError 的文案就要从"原始异常"变成"路径过长…40"。
    monkeypatch 的是**生产自己那份常量**，pytest 在用例后自动还原（形态集 233：不许把脏值留给同进程其它格）。
    """
    assert market_sources.WINDOWS_MAX_PATH == 260, "上限本身变了，本格的两侧断言要跟着重写"
    dest = tmp_path / "skills" / "adaptive-presentation-studio"
    err = OSError(2, "No such file or directory")

    plain = market_sources._describeExtractionFailure(err, builtinPayload, dest)
    assert "路径过长" not in plain, f"没超限也被报成路径过长：{plain[:120]}"

    monkeypatch.setattr(market_sources, "WINDOWS_MAX_PATH", 40)
    named = market_sources._describeExtractionFailure(err, builtinPayload, dest)
    assert "路径过长" in named and "40" in named and "260" not in named, (
        f"文案里的上限不跟着常量走（多半是又抄了一份 260）：{named[:160]}")

def test_receiptCarriesWhateverTheSeamSays(monkeypatch, tmp_path):
    """闭环：原因面说啥，回执就写啥——顺手钉住"生产调用的是哪一面"。

    本批把 `market_importer` 的取法从 bool 面挪到原因面（不然原因进不了回执）。这类挪法有个
    必须当场留档的副作用：**任何还桩在旧面上的替身都会静默失效**——本仓那格
    `test_market_sources.py::TestImporterIntegration::test_import_skill_uses_download_url`
    第一次就是这样从"桩住了"变成"去连真网络"（A/B 里报成仅本树红）。所以这里正面钉一次：
    桩在原因面上 ⇒ 它给的原因必须原样出现在 `task.error_message` 里，且**不许真去联网**。
    """
    from neurova.skills import market_sources as ms
    from neurova.skills.market_importer import MarketImporter
    from neurova.skills import market_store

    seen = []

    def fakeRefusal(skill_id, url, dest):
        seen.append(skill_id)
        return "路径过长：测试造的原因"

    monkeypatch.setattr(ms, "downloadAndExtractRefusal", fakeRefusal)
    monkeypatch.setattr(market_store, "get_market_store", lambda: _OneEntryStore())
    task = MarketImporter(skills_dir=tmp_path / "skills").import_skill("t--demo")

    assert seen == ["t--demo"], "importer 没走原因面 ⇒ 替身打在了没人调的那一面（就是本批自己犯过的形）"
    assert task.status.value == "failed" and "路径过长：测试造的原因" in (task.error_message or ""), (
        f"原因没原样进回执：{task.error_message!r}")


class _OneEntryStore:
    """最小市场账本：只给一条带 download_url 的条目（接口与 `MarketStore` 一致，不联网）。"""

    def list_all(self):
        return [self.entry()]

    def get(self, skill_id):
        entry = self.entry()
        return dict(entry) if entry.get("skill_id") == skill_id else None

    def entry(self):
        return {
            "skill_id": "t--demo", "name": "Demo", "version": "1.0.0", "description": "d",
            "author": "a", "download_url": "https://skills.aliyun.com/api/public/skills/demo/download",  # 白名单市场域名，否则这条分支自己不进下载
            "category": "utility", "tags": [], "rating": 0.0, "downloads": 0, "updated_at": 0,
        }
