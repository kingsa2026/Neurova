# -*- coding: utf-8 -*-
r"""两扇在役脱敏门的漏形状与单源接线判据（§6-415 批 P-5 第二格）。

工单是上一格（§6-413）留下的：第三处在役点 `evolution_inputs_guard` **刻意没接**单源，
理由是"差异在形状不在出口词汇"。本格把那句理由**逐形实测**，并补上单源缺的形状，
再把两扇门改接。判据全部走**在役入口**（`summarizing_compressor._redact`、
`evolution_inputs_guard.redact_secrets/contains_secret`），不走新符号——
把生产改动 stash 掉复跑时，这些符号原样在场，红的才会是行为断言而不是 import 失败。

## 今天（改接前）就漏的六形（实测读数写在本格正文，不凭叙述）

按"宁误报不漏报"的口径，一条密钥的**任何残留片段**都算漏，故判据写成
`原值 not in 出口`，而不是比较整串输出。

| 形状 | 样例 | 漏在哪一侧 |
|------|------|-----------|
| 键值档把 `Bearer` 当值吃掉 | `token: Bearer abcdef123456` | 摘要门（规则序：KV 先于 bearer_literal） |
| 引号形键值（JSON） | `{"api_key": "MyRealSecret123"}` | 摘要门（sep 不接受键名右侧的引号） |
| 键表更窄 | `authorization:`／`cookie:`／裸 `secret=` | 摘要门（表里只有 api_key/token/password 三类键） |
| 带空格的引号值 | `password="hunter2 pass"` | 进化门（值类遇空格即停） |
| 含逗号的值 | `secret=AAAaBBB,CCCcDDD` | 进化门（值类遇逗号即停） |

后两形是**进化门自己那张表的缺陷**，前三形是**单源比进化门窄的地方**——两边各缺一半，
正是"必须先比后合"的那条（教义第 7 条）。

## 反向约束（不得被"更宽"顺手放宽的两处）

- 门禁一侧的**值长下限**照旧：`token=a` 这种短值不得判成密钥。它是
  `skill_install_gate.py:211` 的 fail-closed 判据，判错一次＝正常技能被拦下；
  尺度只在单源一处具名（`MIN_SECRET_VALUE_LEN`），护栏侧不得再写 `{6,}`。
- PII 不进这两扇门（手机号／邮箱／证件／卡号／IP）：`13812345678` 在两条链上都原样保留。
- 无凭据的正常文本逐字透传。
"""

from __future__ import annotations

import ast
from pathlib import Path

from neurova.context.summarizing_compressor import _redact
from neurova.evolution.skill_evidence import summarizeSkillIO
from neurova.security import sensitive_info as _shared
from neurova.security.sensitive_info import (
    SUMMARY_RULES,
    detectSensitive,
    sanitizeSensitive,
)
from neurova.skills import evolution_inputs_guard as _guard
from neurova.skills.evolution_inputs_guard import contains_secret, redact_secrets

# 一形一条：(说明, 文本, 必须消失的片段)。片段取原值里**最难被误伤**的一段，
# 免得判据靠"整串被换掉"这种脆断言撑着。
_SUMMARY_DOOR_LEAKS = (
    ("键值档吃掉 Bearer 前缀后真令牌残留", "token: Bearer abcdef123456", "abcdef123456"),
    ("引号形键值（JSON）整条不进账", '{"api_key": "MyRealSecret123"}', "MyRealSecret123"),
    ("authorization 键不在表里", "authorization: SuperLongToken9", "SuperLongToken9"),
    ("cookie 键不在表里", "cookie: SessionCookieValue1", "SessionCookieValue1"),
    ("裸 secret 键不在表里", "secret=PlainSecretValue7", "PlainSecretValue7"),
)

_EVOLUTION_DOOR_LEAKS = (
    ("引号值里带空格，后半截留在原文", 'password="Alpha7 Bravo9"', "Bravo9"),
    ("值里带逗号，逗号之后留在原文", "secret=AAAaBBB,CCCcDDD", "CCCcDDD"),
)


def _guardTree() -> ast.Module:
    """护栏模块的 AST（退役判据只认节点，不认正文里怎么叙述）。"""
    return ast.parse(Path(_guard.__file__).read_text(encoding="utf-8"))


def _importedNames(tree: ast.Module) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def _compileCallCount(tree: ast.Module) -> int:
    """`x.compile(...)` 形状的出现次数（护栏一旦重新自编译规则必然经过它）。"""
    return sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "compile")


class TestRedactionDoorsCloseTheirOwnLeaks:
    def testSummaryDoorLeaksAreClosed(self):
        """摘要门（在役）：五条形状改接单源后不得留下任何原值片段。"""
        for why, text, fragment in _SUMMARY_DOOR_LEAKS:
            out = _redact(text)
            assert fragment not in out, "%s｜输入 %r → 出口 %r" % (why, text, out)

    def testEvolutionDoorLeaksAreClosed(self):
        """进化护栏门（在役）：自带表的两形漏点在改接后必须闭合。"""
        for why, text, fragment in _EVOLUTION_DOOR_LEAKS:
            out = redact_secrets(text)
            assert fragment not in out, "%s｜输入 %r → 出口 %r" % (why, text, out)

    def testEvidenceWriterRedactsBeforeSerializing(self):
        """证据写入口：先序列化再脱，嵌套字符串的引号变成 `\\"`，值档吃不到后半截。

        这一形是**活体自证**抓出来的（单元那几形都用的裸文本，序列化以后才是这个样子）：
        `{"note": "password=\\"Alpha7 Bravo9\\""}` 序列化后 `Bravo9` 原样留在证据文本里。
        修法不在正则里再猜一次转义引号，而在生产侧把顺序换过来（教义第 1 条）。
        """
        payload = {
            "note": 'password="Alpha7 Bravo9"',
            "config": {"api_key": "MyRealSecret123", "token": "Bearer xyz.abc.def123456"},
        }
        out = summarizeSkillIO(payload)
        for fragment in ("Bravo9", "MyRealSecret123", "xyz.abc.def123456"):
            assert fragment not in out, "%r 残留在 %r" % (fragment, out)

    def testEvidenceWriterKeepsTheStructureReadable(self):
        """脱敏不得把证据打成一片：键名与有界长度都还在（把文本糊平＝没人再读它）。"""
        out = summarizeSkillIO({
            "note": "plain text",
            "config": {"api_key": "sk-abcdefghijklmnopqrst"},
        })
        assert "note" in out and "config" in out and "api_key" in out
        assert "[REDACTED]" in out
        assert len(out) <= 2000

    def testBothDoorsStillMaskTheShapesTheyAlreadyGot(self):
        """改接不得把两扇门**今天已经脱对**的形状改坏（红→绿只能补漏，不能收窄）。"""
        already = (
            "use api_key=sk-abcd1234efgh5678ijkl to call",
            "Authorization: Bearer xyz.abc.def123456",
            "轮换仓库令牌 api_key=ghp_AAAAAAAAAAAAAAAAAAAA 完成",
            "配置密钥 token=nvk_zzzzzzzzzzzz 后重启",
        )
        for text in already:
            assert "sk-abcd1234efgh5678ijkl" not in _redact(text)
            assert "nvk_zzzzzzzzzzzz" not in _redact(text)
            assert "xyz.abc.def123456" not in _redact(text)
            assert "AAAAAAAAAAAAAAAAAAAA" not in _redact(text)
            assert "sk-abcd1234efgh5678ijkl" not in redact_secrets(text)
            assert "xyz.abc.def123456" not in redact_secrets(text)

    def testPiiStaysOutOfBothDoors(self):
        """手机号那类 PII 在两条链上都原样保留——投影多接一类就会当场红。"""
        phone_text = "告警工单已建，请联系运维 13812345678 复核节点状态。"
        assert "13812345678" in _redact(phone_text)
        assert "13812345678" in redact_secrets(phone_text)

    def testBenignTextPassesThroughVerbatim(self):
        """无凭据的正常文本：两扇门都逐字不动（把散文打花不是更安全）。"""
        for benign in (
            "把报告转成 PDF 并放到 docs/ 目录",
            "本次部署顺利完成，未触发限流，无需人工干预。",
        ):
            assert redact_secrets(benign) == benign
            assert _redact(benign) == benign


class TestGateDetectionScaleIsSingleSourced:
    def testShortValueDoesNotTripTheFailClosedGate(self):
        """门禁侧的值长下限照旧生效：`token=a` 不得判成密钥。

        这条是**反向**判据（今天绿、明天必须还绿）：`skill_install_gate.py:211` 命中即
        fail-closed 拦下整个技能安装，把短值算进去＝正常技能被误杀。
        """
        assert contains_secret("token=a") is False
        assert contains_secret("password: x") is False

    def testRealSecretStillTripsTheGate(self):
        """正向对照：真凭据形状照样命中，否则上一条的"绿"毫无意义。"""
        assert contains_secret("token=abcdef123456") is True
        assert contains_secret("api_key: sk-abcdefghijklmnopqrst") is True
        assert contains_secret('{"api_key": "MyRealSecret123"}') is True

    def testValueLengthScaleLivesInTheSingleSource(self):
        """下限尺度只在单源一处具名，护栏侧不得再写自己的值长下限。"""
        assert hasattr(_shared, "MIN_SECRET_VALUE_LEN"), "值长下限没有单源落点"
        assert _shared.MIN_SECRET_VALUE_LEN >= 6
        assert hasattr(_shared, "containsSensitive"), "命中判定没有单源落点"
        # 下限一旦回到护栏那张表，护栏必然重新 `import re` 自己编译——AST 面比子串面准：
        # 模块正文里谈"过去那份小抄"的路标句不该算命中（本仓守卫的路标行口径）。
        tree = _guardTree()
        assert "re" not in _importedNames(tree), "护栏又把自己编译规则的那条路接回来了"

    def testSharedEngineIsTheOnlyThingBehindBothDoors(self):
        """同表同引擎：护栏出口逐字等于「单源 ＋ 同一份投影 ＋ 同一个 token」。

        只看"结果里没了原值"不够——那样调用方留一份自己的小抄也能蒙过。这一格比的是
        **整串逐字相等**：护栏一旦还走自己那张表，两串必然在键表／值类／分隔符任一处分开。
        """
        corpus = tuple(t for _, t, _ in _SUMMARY_DOOR_LEAKS + _EVOLUTION_DOOR_LEAKS) + (
            "use api_key=sk-abcd1234efgh5678ijkl to call",
            "Authorization: Bearer xyz.abc.def123456",
            "把报告转成 PDF 并放到 docs/ 目录",
        )
        for text in corpus:
            assert redact_secrets(text) == sanitizeSensitive(
                text, SUMMARY_RULES, "[REDACTED]"), text

    def testSharedEngineIsTheOnlyThingBehindBothDoors(self):
        """同表同引擎：护栏出口逐字等于「单源 ＋ 同一份投影 ＋ 同一个 token」。

        只看"结果里没了原值"不够——那样调用方留一份自己的小抄也能蒙过。这一格比的是
        **整串逐字相等**：护栏一旦还走自己那张表，两串必然在键表／值类／分隔符任一处分开。
        """
        corpus = tuple(t for _, t, _ in _SUMMARY_DOOR_LEAKS + _EVOLUTION_DOOR_LEAKS) + (
            "use api_key=sk-abcd1234efgh5678ijkl to call",
            "Authorization: Bearer xyz.abc.def123456",
            "把报告转成 PDF 并放到 docs/ 目录",
        )
        for text in corpus:
            assert redact_secrets(text) == sanitizeSensitive(
                text, SUMMARY_RULES, "[REDACTED]"), text

    def testEvolutionGuardCarriesNoOwnRuleTable(self):
        """退役判据：护栏模块不得再有自编译规则（留第二份表＝未闭环）。

        判据走 AST 不走子串——模块 docstring 里必须谈得成"过去那份小抄长什么样"，那是
        路标句，不是落点。真落点是三件事：没有 `import re`、没有 `compile` 调用形状、
        旧符号名不再作为节点存在。这一格今天就该红：红的是形状（自带表还在），
        行为那几格各自点名了自己那一形，两回事分开记。
        """
        tree = _guardTree()
        assert "re" not in _importedNames(tree), "护栏仍在自己编译规则表"
        assert _compileCallCount(tree) == 0, "护栏仍有 compile 调用：%d 处" % _compileCallCount(tree)
        alive = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for banned in ("_KV_RE", "_BEARER_RE", "_OPENAI_RE"):
            assert banned not in alive, "护栏仍持有旧符号 %s" % banned

    def testRedactionDoorIsAThinWrapper(self):
        """护栏只调单源各一次：出现第二份打码／判定调用即红。"""
        calls = [n.func.id for n in ast.walk(_guardTree())
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        assert calls.count("sanitizeSensitive") == 1, calls
        assert calls.count("containsSensitive") == 1, calls

    def testDetectionDoorSharesTheSameTableAsTheRedactionDoor(self):
        """门禁判定与脱敏用同一张表：`contains_secret` 的读数必须能被 `detectSensitive` 复算。

        今天两份键表不同步（护栏多 `authorization/cookie/credential`，单源多 `口令`），
        于是"该拦的没拦、该脱的没脱"各朝一个方向漂——同一个形状在两个入口给两个答案。
        """
        for text in ("authorization: SuperLongToken9", "cookie: SessionCookieValue1",
                     "口令：MyRealPass123", "token=abcdef123456", "把报告转成 PDF"):
            expect = bool(detectSensitive(text, SUMMARY_RULES))
            assert contains_secret(text) is expect, text
