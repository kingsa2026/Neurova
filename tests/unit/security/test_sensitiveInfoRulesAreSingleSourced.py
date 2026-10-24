# -*- coding: utf-8 -*-
r"""内容级敏感信息识别与脱敏：规则表与脱敏引擎都只许有一份（§6-411 批 O-5）。

用户裁「先收口单源，暂不进回合链」——本档只收口，不往 chat 回合里新加检测。

## 比：收口前四份并存，且**没有一份能单独满足现有契约**

| 出处 | 形状 | 独有价值（取长补短时取走的那块） | 缺陷（一并随批修掉） |
|---|---|---|---|
| `security/cognitive_security.py:206` `SENSITIVE_PATTERNS` | 8 条，`key [=:] value` 宽松式＋`SafetyLevel` 分级 | **键值式识别**：`API_KEY=sk_test_1234567890` 要能被认出来（现有格子钉着） | `sanitize()` 用 `split("=")[0]+"=***"` ⇒ 冒号形 `password: abc` 输出 `password: abc=***`，**值没脱敏还添垃圾** |
| `memory_layer/security.py:160` `_BUILTIN_PATTERNS` | 8 条，`SensitivePattern`（名字＋描述＋分级＋replacement 模板） | **中文键名**（`密码/口令`）＋**校验型身份证**（年月日都验）＋**带分隔符的卡号**＋分级尺度 | `bank_card` 与 `credit_card` 是**同一条正则登记两次**；`1**********` 这种死模板会抹掉首尾（现有格子要求手机号脱敏后仍留 `138`/`5678`） |
| `core/firewall.py:61` `sensitive_output_patterns` | 6 条裸词/值形状串 | **值形状识别**：`sk-\w+`、`Bearer\s+\S+`——没有键名也能认出密钥形态，另外两份都缺 | ①`password`/`token` 是**裸词** ⇒ `sub("[REDACTED]")` 打码的是词本身，含 "token" 的正常文本被打码而真密钥原样出去；②`:147` 编译发生在 `:150 _load()` **之前** ⇒ 配置里改 `sensitive_output_patterns` 永不生效（只写不读） |
| `security/privacy_gate.py:18` `_SENSITIVE_KEY` | 一条键名正则 | —— | **不同功能**：对工具事件载荷按**键名**递归脱敏（在役，`chat_pipeline.py:2522/2712` 两条出口）。不并、不动 |

⇒ 单源取：cognitive 的键值式识别 ＋ memory 的中文键名/校验型证件/带分隔卡号与分级尺度 ＋ firewall 的值形状规则。
脱敏引擎同时只留一份（原先 `SensitiveInfoDetector.sanitize`、`MemorySecurity._mask_content`、
`anonymize_content`、`AgentFirewall.sanitize_output` 各写一遍循环，就是四份实现读一张都不完整的表）。

## 分级怎么定（这是产品语义，明写不藏）

同一规则两份分级不一致时**取较高的一档**（隐私保守方向；往下调等于把既有保护改弱，
教义第 2 条禁的就是这种降级）：身份证 `HIGH→CRITICAL`、手机号 `MEDIUM→HIGH`、
邮箱 `LOW→MEDIUM`。后果如实写：`MemorySecurityGuard.should_remember()` 从此也会拦手机号，
`ThreatFinding.severity` 对这几类的读数随之变高。**这三条链今天都没有生产消费者**
（`CognitiveSecuritySystem` 在 `neurova/` 内零引用，见 §6-404 档案 M2），所以变更当前是惰性的；
"要不要按新分级进回合链"就是"暂不进回合链"那句留给后续的那一半。

## 判据的对照

- **同表同引擎**：同一串文本从三扇 door（detector / MemorySecurity / firewall）读回的**命中集合必须一致**——
  漂移（有人另起一张表或再写一遍循环）当场红，这比数定义行难绕。
- **现有契约不动**：手机号脱敏仍留首 3 末 4、`API_KEY=…` 仍认得且保留键名只打码值、
  正常中文文本原样返回、`sk-…` 必被抹掉。
- **两处缺陷有正检**：冒号形必须真脱敏；配置文件里改规则表必须生效（这条**今天就是红的**）。
- **裸词反例**：默认表里不得存在"匹配串本身只有关键词、不含值"的规则。
- **面自证**：扫到的规则条数与门数都当断言比，不靠"零命中"充绿。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 三份旧表退役后，仓内只剩这一处规则表。
_SHARED_SOURCE = "neurova/security/sensitive_info.py"
#: 三份旧表的名字——任何一个回来即红。
_RETIRED_TABLES = ("SENSITIVE_PATTERNS", "_BUILTIN_PATTERNS")
#: 三扇 door（都在生产池里，只是目前没有生产消费者）。
_DOORS = ("cognitive", "memory")

#: 一条正常文本与一条含多种敏感信息的文本，用来比对 doors 的一致性。
_PROBE_TEXTS = (
    "这是一段正常的文本，没有任何敏感内容。",
    "手机号 13812345678，邮箱 user@example.com，身份证 110101199001011234，"
    "api_key=sk-1234567890abcdef",
    "password: hunter2 与 token: ee1f2a3b4c",
)



def _shared():
    try:
        from neurova.security import sensitive_info
    except ImportError as exc:
        pytest.fail(
            "单源模块 `neurova/security/sensitive_info.py` 还没落地（%r）——这是本批规格，"
            "不是环境缺件：规则表与脱敏引擎此刻仍散在三处" % (exc,)
        )
    return sensitive_info


def _doorReadings(door: str, text: str):
    """把同一串文本喂给一扇 door，返回**命中规则名集合**（顺序无关，便于跨 door 比）。"""
    if door == "cognitive":
        from neurova.security.cognitive_security import SensitiveInfoDetector

        return {f.description.split(": ")[-1] for f in SensitiveInfoDetector().detect(text)}
    if door == "memory":
        from neurova.cognitive_layers.memory_layer.security import MemorySecurity

        return {d["pattern_name"] for d in MemorySecurity().detect_sensitive_info(text)}
    raise AssertionError("未知 door：%s" % door)


class TestRuleTableAndEngineAreSingleSourced:

    def testSharedTableExistsAndCarriesTheMergedRules(self):
        module = _shared()
        rules = module.SENSITIVE_RULES
        assert len(rules) >= 9, (
            "合并表只有 %d 条——三份旧表里独有的形状（中文键名／校验型身份证／带分隔卡号／"
            "sk- 与 Bearer 值形状）没被全部取进来，这就不叫取长补短" % len(rules)
        )
        names = {rule.name for rule in rules}
        for expected in ("phone", "email", "id_card", "bank_card", "password",
                         "api_key", "token", "ip_address", "secret_literal"):
            assert expected in names, "合并表缺规则 %s（现名：%s）" % (expected, sorted(names))
        # memory 那份把同一条正则登记成 bank_card／credit_card 两个名字——收口后不得再有重复
        patterns = [rule.pattern.pattern for rule in rules]
        duplicated = {p for p in patterns if patterns.count(p) > 1}
        assert not duplicated, "表里有重复正则：%s" % duplicated

    def testRetiredTablesAreGoneAndNotReimportable(self):
        import ast

        from tests import ast_scan

        candidates = list(ast_scan.sourceRefsUnder(REPO_ROOT / "neurova", ".py",
                                                   hints=_RETIRED_TABLES))
        assert len(candidates) >= 2, (
            "带旧表名字的档只剩 %d 个——扫描根或预筛词写窄了，此时下面的『零违规』与『没扫到』同形"
            % len(candidates)
        )
        offenders = []
        for ref in candidates:
            path = Path(ref.path)
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    for target in getattr(node, "targets", [getattr(node, "target", None)]):
                        name = getattr(target, "id", None) or getattr(target, "attr", None)
                        if name in _RETIRED_TABLES:
                            offenders.append("%s:%d %s" % (
                                path.relative_to(REPO_ROOT).as_posix(), node.lineno, name))
        assert not offenders, (
            "旧表回来了：%s——规则表只许有 %s 一处" % (offenders, _SHARED_SOURCE)
        )

    def testAllThreeDoorsAgreeOnWhatTheyMatch(self):
        """同表同引擎：三扇 door 对同一文本的命中集合必须一致（漂移＝又长出第二份判定）。"""
        from neurova.security.sensitive_info import detectSensitive

        for text in _PROBE_TEXTS:
            shared = {d.rule.name for d in detectSensitive(text)}
            for door in _DOORS:
                assert _doorReadings(door, text) == shared, (
                    "door「%s」与单源引擎读数不一致：%s vs %s（文本：%r）"
                    % (door, _doorReadings(door, text), shared, text[:28])
                )

    def testSanitizeEngineHasOneImplementation(self):
        """脱敏也只一份：三扇 door 的脱敏结果与单源函数逐字相等（不是各自再写一遍循环）。"""
        shared = _shared()
        from neurova.cognitive_layers.memory_layer.security import MemorySecurity
        from neurova.security.cognitive_security import SensitiveInfoDetector
        from neurova.core.firewall import AgentFirewall

        detector, memory, firewall = (SensitiveInfoDetector(), MemorySecurity(), AgentFirewall())
        for text in _PROBE_TEXTS[1:]:
            expected = shared.sanitizeSensitive(text)
            assert detector.sanitize(text) == expected, "detector.sanitize 没走单源引擎"
            assert memory.anonymize_content(text, preserve_format=False) == expected, (
                "MemorySecurity 的掩码没走单源引擎（它自己那两套循环还在）")
            assert firewall.sanitize_output(text) == expected, "firewall.sanitize_output 没走单源引擎"


class TestLiveContractsSurviveTheMerge:
    """现有格子钉住的读数一条不许变（变了就必须在本档留下理由）。"""

    @pytest.mark.parametrize("text,absent,keep", [
        ("我的手机号是13812345678", "13812345678", ("138", "5678")),
        ("邮箱: user@example.com", "user@example.com", ()),
    ])
    def testMaskingKeepsTheDocumentedShape(self, text, absent, keep):
        out = _shared().sanitizeSensitive(text)
        assert absent not in out, out
        for fragment in keep:
            assert fragment in out, "脱敏把 %s 也抹了（现有契约要求保留）：%s" % (fragment, out)

    def testColonFormIsActuallyRedacted(self):
        """被修掉的第一处缺陷：`key: value` 形态过去输出 `key: value=***`，值原样留着。"""
        out = _shared().sanitizeSensitive("password: hunter2")
        assert "hunter2" not in out, "冒号形的值没脱敏（原缺陷：%s）" % out
        assert out.startswith("password"), "键名应保留，只打码值：%s" % out

    def testCleanTextIsReturnedUnchanged(self):
        assert _shared().sanitizeSensitive(_PROBE_TEXTS[0]) == _PROBE_TEXTS[0]

    def testLiteralSecretShapesWithoutAKeyAreCaught(self):
        """firewall 唯一的贡献：没有键名的密钥形态（`sk-…`／`Bearer …`）也认得。"""
        for text in ("我的API密钥是sk-1234567890abcdef", "Authorization: Bearer abcd.efgh.ijkl"):
            out = _shared().sanitizeSensitive(text)
            assert re.search(r"sk-\w+", out) is None and "Bearer abcd" not in out, out

    def testNoBareKeywordRulesRemainInTheDefaultTable(self):
        """裸词（只匹配关键词本身、不含值）会把正常文本打码而放过真密钥——原缺陷的第一半。"""
        for rule in _shared().SENSITIVE_RULES:
            if rule.matchesValueShapeOnly:
                continue
            assert rule.pattern.search("这里有一个 token 字段说明文档") is None, (
                "规则 %s 是裸词形：正常文本 %r 被打码了" % (rule.name, "这里有一个 token 字段说明文档")
            )


class TestFirewallConfigNowTakesEffect:
    """被修掉的第二处缺陷：规则表编译发生在 `_load()` 之前 ⇒ 配置改了永不生效（只写不读）。"""

    def testConfiguredPatternsAreHonoured(self, tmp_path):
        from neurova.core.firewall import AgentFirewall

        cfg = tmp_path / "firewall.json"
        cfg.write_text(json.dumps({"global": {
            "sensitive_output_patterns": [r"secretMarker-\w+"]}}), encoding="utf-8")

        firewall = AgentFirewall(config_path=str(cfg))
        out = firewall.sanitize_output("请带上 secretMarker-9ff31a 继续")
        assert "secretMarker-9ff31a" not in out, (
            "配置里的规则没生效——改回 `:147 编译 / :150 _load()` 那个顺序就会这样"
        )


class TestSeverityScaleHasOneVocabulary:
    """分级尺度单源：memory 的 `SensitivityLevel` 是别名而不是第二份枚举。"""

    def testSensitivityLevelIsTheSharedOne(self):
        from neurova.cognitive_layers.memory_layer import security as mem_security
        from neurova.security.sensitive_info import SensitivityLevel

        assert mem_security.SensitivityLevel is SensitivityLevel, (
            "记忆侧又长出第二份敏感度枚举 ⇒ 同一条规则可以有两个分级读数"
        )

    def testCognitiveMapsRatherThanRedefines(self):
        """cognitive 的 `SafetyLevel` 是它自己的报告词汇（含 SAFE），合法；
        但每条规则的分级必须来自共享表——把表里最保守的一档取进来。"""
        module = _shared()
        from neurova.security.cognitive_security import SafetyLevel, SensitiveInfoDetector

        findings = SensitiveInfoDetector().detect("身份证号: 110101199001011234")
        assert any(f.severity is SafetyLevel.CRITICAL for f in findings), (
            "身份证按合并尺度应为 CRITICAL（原 cognitive 记 HIGH；往高调是保守方向，"
            "往低调等于把既有保护改弱）"
        )
        assert module.severityOf("id_card").value == "critical"
