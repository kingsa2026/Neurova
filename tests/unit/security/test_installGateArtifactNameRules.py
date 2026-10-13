"""安装门的名称级缺口与代码后缀盲区（§6-194，2026-10-13 裁定甲″）。

现量根据（动手前实测）：
1. 咽喉只看**内容**，从不看**文件名**。`.env`、`id_rsa`、`server.pem`、`.aws/credentials`
   这类凭据产物，以及 `.exe`/`.dll` 这类真可执行文件，`_discover_files` 因后缀不在清单、
   或路径分段以点开头而**根本不进扫描**——门既不漏报也不报错，就是看不见。
2. `scannable_suffixes` 缺 `.mjs/.cjs/.mts/.cts`。本仓自带的 presentation-studio 资产包
   138 个文件里 **38 个从不被读**（37 个 .mjs + 1 个 .csv）；把 .mjs 改名 .js 复扫，
   参与 DENY 的命中由 31 条涨到 33 条——危险字节落在门看不见的后缀里。
3. 白名单式「只扫这些后缀」本身就是 fail-open：没被扫的文件不留任何读数。

裁定甲″的口径三条，同时成立：
- 已知凭据文件名/私钥与真可执行产物 ⇒ 参与 DENY（名称级判定不看内容，
  `.env` 哪怕一行可读内容也没有也是泄漏）；
- 未进扫描的文件 ⇒ 必须留下**报告项**并计入对账（放行≠看不见）；
- 口径单源在 `neurova/security/skill_scanner.py`，装载侧不得另立一份。
"""

import io
import zipfile
from pathlib import Path

import pytest

from neurova.security.skill_scanner import (
    Finding,
    ScanPolicy,
    ScanMode,
    SkillScanner,
    isDenyBearing,
)
from neurova.skills.market_importer import read_builtin_bundle
from neurova.skills.skill_install_gate import reset_install_gate_scanner, scan_skill_for_install

REPO_ROOT = Path(__file__).resolve().parents[3]

BENIGN_MD = """---
name: demo
description: 演示技能
---

# 演示

按说明使用本技能即可。
"""

MJS_WITH_EXEC = """export function run(userInput) {
    return eval(userInput);
}
"""

CREDENTIAL_SHAPES = [
    ".env",                    # 前导点：discovery 因分段 startswith(".") 整条跳过
    "deploy/id_rsa",           # 无后缀
    "certs/server.pem",        # 私钥后缀不在可扫清单
    "config/.ssh/config",      # 私钥目录下的任意文件
    ".aws/credentials",        # 云凭据目录
]


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _write(root: Path, rel: str, text: str) -> Path:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _ruleIds(scan: dict) -> set:
    return {f.get("rule_id") for f in scan.get("findings") or []}


class TestArtifactNameGate:
    @pytest.mark.parametrize("rel", CREDENTIAL_SHAPES)
    def testCredentialArtifactIsBlocked(self, tmp_path, rel):
        """陪衬一份无害 SKILL.md：不能让 no_files 替这条闸顶罪。"""
        _write(tmp_path, "SKILL.md", BENIGN_MD)
        _write(tmp_path, rel, "PRIVATE KEY MATERIAL\n")

        scan = scan_skill_for_install("b38-cred-" + rel.replace("/", "-"), str(tmp_path))

        assert "credential_artifact_name" in _ruleIds(scan), (
            f"{rel} 落在可扫后缀之外，门连一条读数都没留——凭据文件混进技能包是静默通过的")
        assert scan.get("blocked") is True, (
            f"名称级凭据命中却没拦住（实得 {sorted(_ruleIds(scan))}）——只报不拦等于没闸")

    def testExecutableArtifactIsBlocked(self, tmp_path):
        _write(tmp_path, "SKILL.md", BENIGN_MD)
        _write(tmp_path, "bin/updater.exe", "MZ\x90\x00binary")
        _write(tmp_path, "lib/native.dll", "MZ\x90\x00binary")

        scan = scan_skill_for_install("b38-exe", str(tmp_path))

        exeHits = [f for f in scan.get("findings") or [] if f.get("rule_id") == "executable_artifact"]
        assert len(exeHits) == 2, f"两份可执行产物只点名 {len(exeHits)} 份"
        assert scan.get("blocked") is True, "技能包里带 .exe/.dll 本该拒装"

    def testBenignNameLikeAssetsAreNotFlagged(self, tmp_path):
        """反误报格：当年那份表把 token/password 当子串扫，第一方包里 4 个文档资产名中枪。
        口径必须是**已知凭据文件名**，不是"名字里像有秘密"。"""
        for rel in ("SKILL.md", "protection/password-hash.json", "assets/design_tokens.json",
                    "references/content-tokens.json", "docs/tokens.md", ".env.example"):
            _write(tmp_path, rel, "{}\n")

        scan = scan_skill_for_install("b38-falsepositive", str(tmp_path))

        assert not _ruleIds(scan) & {"credential_artifact_name", "executable_artifact"}, (
            f"按子串冤枉了正当资产名（实得 {sorted(_ruleIds(scan))}）——误拦比漏拦更快被人关掉")

    def testScanReceiptAccountsForEveryFile(self, tmp_path):
        """未扫文件必须留可见读数，且 scanned+unscanned 必须等于目录总数（不留静默格）。"""
        _write(tmp_path, "SKILL.md", BENIGN_MD)
        _write(tmp_path, "assets/table.csv", "a,b\n1,2\n")
        _write(tmp_path, "assets/logo.png", "binary")

        scan = scan_skill_for_install("b38-unscanned", str(tmp_path))

        assert "unscanned_artifact" in _ruleIds(scan), (
            ".csv/.png 掉出可扫清单后一条读数都不留——「没有发现」和「根本没看」不可分辨")
        assert scan.get("blocked") is not True, (
            "未知后缀只该报告，不该拦——否则每个带图片的技能都被误拒")


class TestCodeSuffixBlindSpot:
    @pytest.mark.parametrize("rel", ["scripts/payload.mjs", "scripts/helper.cjs",
                                     "src/module.mts", "src/typing.cts"])
    def testModuleCodeSuffixIsScannedAndDenies(self, tmp_path, rel):
        _write(tmp_path, "SKILL.md", BENIGN_MD)
        _write(tmp_path, rel, MJS_WITH_EXEC)

        scan = scan_skill_for_install("b38-mod-" + Path(rel).suffix.strip("."), str(tmp_path))

        execHits = [f for f in scan.get("findings") or []
                    if f.get("rule_id") == "dangerous_exec"
                    and str(f.get("file_path", "")).endswith(Path(rel).suffix)]
        assert execHits, f"{rel} 里的 eval( 没被读到——这段字节从不进扫描"
        assert scan.get("blocked") is True, (
            f"同样的 exec 写在 {Path(rel).suffix} 里就放行，写在 .py 里就拦（见批 37 配对格）")


class TestCaliberIsSingleSource:
    def testUnscannedCategoryIsNeverDenyBearing(self):
        """报告项与阻断项的分界单源在 isDenyBearing：未扫读数不参与 DENY。"""
        assert isDenyBearing(Finding(rule_id="unscanned_artifact", severity="medium",
                                     category="unscanned_artifact",
                                     file_path="pkg/assets/logo.png")) is False, (
            "把「没扫到」当阻断理由 ⇒ 每个带图片的技能都被误拒，这道门会被人整个关掉")

    def testNameLevelHitsAreNotSilencedByTheDocExemption(self):
        """名称级判定不看内容：文件后缀是不是"文档类"与它泄不泄密无关。"""
        assert isDenyBearing(Finding(rule_id="credential_artifact_name", severity="high",
                                     category="artifact_name", file_path="pkg/.env")) is True

    def testCacheKeyCoversFileNames(self, tmp_path):
        """只按内容算摘要时，加一个凭据文件不改摘要 ⇒ 回缓存里的旧放行结论，门形同虚设。"""
        _write(tmp_path, "SKILL.md", BENIGN_MD)
        first = scan_skill_for_install("b38-cache", str(tmp_path))
        assert first.get("blocked") is not True, f"前置不成立：无害包首扫就被拦了（{first}）"

        _write(tmp_path, ".env", "API_KEY=leak\n")
        again = scan_skill_for_install("b38-cache", str(tmp_path))

        assert again.get("blocked") is True, (
            "同名同内容、只多出一个 .env 却被放行——摘要没算文件名，读的是缓存不是门")

    def testRealAssetBundleLeavesNoBlindSpotAndNoFalseDeny(self, tmp_path):
        """真产物对账：包内每个文件都必须被 accounted（扫过或明确报未扫），
        而第一方资产名不得被名称级规则冤枉。"""
        import neurova.security.safe_archive as SA

        payload = read_builtin_bundle("adaptive-presentation-studio.zip")
        assert payload, "包内资产缺失——本格失去根据，先去补齐资产而不是关掉判据"
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            total = sum(1 for i in z.infolist() if not i.is_dir())

        dest = tmp_path / "studio"
        dest.mkdir(parents=True)
        SA.safe_extract_zip(payload, dest)

        scanner = SkillScanner(workspace_path=str(dest))
        scanner.policy = ScanPolicy.DENY
        result = scanner.scan_skill("builtin--adaptive-presentation-studio-b38", str(dest),
                                   mode=ScanMode.QUICK)

        unscanned = result.metadata.get("unscanned_file_count")
        assert unscanned is not None, (
            f"扫描器报不出「有多少文件没被读」（metadata 键 {sorted(result.metadata)}）"
            "——盲区大小本身不可见，就没人知道漏了多少")
        assert result.file_count + unscanned == total, (
            f"已扫 {result.file_count} + 未扫 {unscanned} ≠ 包内 {total} 个文件——有文件两头都不计")
        assert not [f for f in result.findings
                    if f.rule_id in {"credential_artifact_name", "executable_artifact"}], (
            "第一方资产包被名称级规则误伤（design_tokens.json / password-hash.json 那一族）")


class TestSecondScannerIsRetired:
    def testDuplicateSkillScannerIsGone(self):
        """教义第 7 条：同一能力只许一处实现。取回形态按 find_spec 判——那份死体的来历
        正是 pyc 骨架恢复（7835c367），只查 .py 存在会放过"文件没了但 .pyc 还在能被 import"。
        """
        import importlib.util

        assert importlib.util.find_spec("neurova.skills.security_scanner") is None, (
            "仓内还并存第二套技能扫描器（908 行、零生产消费者）——安全裁决出现第二本账的入口")
