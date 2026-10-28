# -*- coding: utf-8 -*-
r"""挖掘侧密钥剔除与内容级单源合表判据（§6-416 批 P-5 第三格）。

工单来自 §6-415 仍开①：`neurova/evolution/eval/miner.py` 里的 `SECRET_PATTERNS` 是内容级
敏感信息的**第八张表**，且它自带的同名 `contains_secret` 与 §6-415 接进单源的那个是
**同一功能的第二份实装**（教义第 7 条：该功能在仓内只剩一处实装被消费，留下第二份即未闭环）。

按第 7 条先比后合。逐形实测（读数抄在本格正文，不引用叙述）：

| miner 表里的形状 | 单源现状 | 本格怎么断 |
|---|---|---|
| `sk-ant-api…`／`sk-or-v1…`／`ghp_…`／`Bearer \S{20,}` | **已被泛化档覆盖**（`secret_literal`／`github_token`／`bearer_literal`） | 冗余不并表，反向钉住"泛化档覆盖得动"，谁再往表里加窄档即红 |
| `ghu_`／`xoxb-`／`xapp-`／`ntn_`／`AKIA[0-9A-Z]{16}`／PEM 私钥头 | **一条都没有**，原样进评测集与证据 | 六形必须被两扇在役门脱掉 |
| `ANTHROPIC_API_KEY` 等七个环境变量**名** | 不属脱敏形状（提到变量名不等于泄露凭据） | 作为**剔除策略**单源一处具名，仍由挖掘门消费；脱敏门**不得**因此把散文打花 |
| `\bpassword/secret/token\s*[=:]\s*…` | 单源键值档本就覆盖，且尺度只有一条 `MIN_SECRET_VALUE_LEN` | 值长尺度收成一处，挖掘侧不得再写自己的 `{10,}` |

判据全部走**在役入口**（`miner.sanitize_messages`、`summarizing_compressor._redact`、
`evolution_inputs_guard.redact_secrets`），新符号一律经模块属性或 `hasattr` 取——把生产改动
整体回退复跑时，这些档照样收集得起，红的才会是行为断言而不是 import 失败。
"""

from __future__ import annotations

import ast
from pathlib import Path

from neurova.context.summarizing_compressor import _redact
from neurova.evolution.eval import miner as _miner
from neurova.evolution.eval.miner import sanitize_messages
from neurova.security import sensitive_info as _shared
from neurova.skills.evolution_inputs_guard import redact_secrets
from tests.ast_scan import parseSource

# 挖掘门的剔除判定**经真入口问**（`sanitize_messages`）：本档原先直接 import
# `miner.contains_secret`，而那一格断言的正是"这个名字不再作为第二段实装存在"——
# 按名字 import 会让回退态与终态里有一边收集不起，红就不落在行为上了。
_BENIGN_TASK = "请把上个月的季度报表导出成 PDF 并归档到共享目录"


def _miningDoorDrops(text: str) -> bool:
    """真 `sanitize_messages`：这条文本进了评测集没有（`task_input` 用无凭据的长文本，
    免得被 `MIN_TEXT_LEN` 那道长度闸先剔掉，把长度判定冒充成密钥判定）。"""
    return not sanitize_messages([{"task_input": _BENIGN_TASK, "assistant_response": text}])

# 单源今天**一条都没有**的六形（§6-415 实测：sanitizeSensitive 原样返回、detect 零命中）。
# 片段挑"最难与键名／出口词汇重叠"的那一段（形态 413：拿片段先 in 一遍键名与词汇本身）。
_MISSING_SHAPES = (
    ("GitHub user token", "ghu_9f8e7d6c5b4a39281706f5e4d3c2b1a0f", "5b4a39281706"),
    ("Slack bot token", "xoxb-123456789012-1234567890123-AbCdEfGhIjKl", "AbCdEfGhIjKl"),
    ("Slack app token", "xapp-1-A012B012C0D-9f8e7d6c5b4a-0123456789abcdef01234567", "abcdef01234567"),
    ("Notion token", "ntn_0123456789AbCdEfGhIjKlMn", "AbCdEfGhIjKlMn"),
    ("AWS access key id", "AKIA0123456789ABCDEF", "0123456789ABCDEF"),
    ("私钥头", "-----BEGIN RSA PRIVATE KEY-----", "PRIVATE KEY"),
)

# miner 那四条**冗余窄档**：泛化档本就覆盖，并表等于给同一件事写第二条尺度。
_ALREADY_COVERED = (
    ("Anthropic 键", "sk-ant-api03-AbCdEf1234567890GhIjKlMn", "GhIjKlMn"),
    ("OpenRouter 键", "sk-or-v1-9f8e7d6c5b4a39281706f5e4d3c2b1a0", "39281706f5e4"),
    ("GitHub PAT", "ghp_AbCdEf1234567890AbCdEf1234567890AbCd", "1234567890AbCd"),
    ("Bearer 头", "Bearer abcdefghijklmnopqrstuvwxyz", "hijklmnopqrstuvw"),
)

# 环境变量**名**：只作"命中即整条剔除"的筛除词汇，不作打码形状。
_ENV_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN",
              "AWS_SECRET_ACCESS_KEY", "DATABASE_URL")

_PROSE_WITH_ENV_NAME = "部署前请先设置 GITHUB_TOKEN 与 DATABASE_URL 两个环境变量，再跑迁移。"


def _minerTree() -> ast.Module:
    return parseSource(Path(_miner.__file__).read_text(encoding="utf-8"))


def _topLevelDefNames(tree: ast.Module) -> set:
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class TestMiningDoorLeaksAreClosed:
    def testSixMissingCredentialShapesAreNowMaskedByBothLiveDoors(self):
        """六形在两扇在役门上都不得留原值片段（今天单源一条都没有 ⇒ 当场红）。"""
        for why, text, fragment in _MISSING_SHAPES:
            assert fragment not in _redact(text), "%s｜摘要出口 %r" % (why, _redact(text))
            assert fragment not in redact_secrets(text), "%s｜护栏出口 %r" % (why, redact_secrets(text))

    def testGenericShapesStillCoverTheRedundantNarrowOnes(self):
        """反向控制：miner 那四条窄档并**不**需要进表——泛化档本就脱得掉。

        这一格今天就该绿，改完必须还绿；它钉的是"别给同一件事写第二条尺度"。
        """
        for why, text, fragment in _ALREADY_COVERED:
            assert fragment not in _redact(text), "%s｜%r" % (why, _redact(text))
            assert fragment not in redact_secrets(text), "%s｜%r" % (why, redact_secrets(text))


class TestDropPolicyIsSingleSourced:
    def testEnvVarNamesStillDropTheWholeMessage(self):
        """剔除策略照旧生效：文本里出现凭据环境变量名，整条消息不得进评测集。"""
        for name in _ENV_NAMES:
            assert _miningDoorDrops("请在配置里填 %s 的值" % name) is True, name
        kept = sanitize_messages([
            {"task_input": _BENIGN_TASK, "assistant_response": "已导出 %s" % _ENV_NAMES[0]},
        ])
        assert kept == [], kept

    def testEnvVarNamesAreDeclaredOnceAndNotUsedForMasking(self):
        """词汇表只在单源一处具名；**脱敏门不得**因它把正常散文打花。

        提到变量名不等于泄露凭据——把 `GITHUB_TOKEN` 这种词在摘要里糊成 `[REDACTED]`，
        代价是运维文本没法读（与 `_kv` 拒绝"空白也算分隔符"同一类理由）。
        """
        assert hasattr(_shared, "CREDENTIAL_ENV_NAMES"), "剔除词汇没有单源落点"
        assert hasattr(_shared, "mentionsCredentialEnvVar"), "剔除口没有单源落点"
        names = set(_shared.CREDENTIAL_ENV_NAMES)
        for name in _ENV_NAMES:
            assert name in names, name
        assert _PROSE_WITH_ENV_NAME == _redact(_PROSE_WITH_ENV_NAME)
        assert _PROSE_WITH_ENV_NAME == redact_secrets(_PROSE_WITH_ENV_NAME)

    def testValueLengthScaleIsOneNamedNumber(self):
        """值长尺度全仓一处：挖掘侧不得再写自己的 `{10,}`／`{6,}`。"""
        tree = _minerTree()
        stringConsts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
                        and isinstance(n.value, str)]
        assert not [s for s in stringConsts if "{10,}" in s or "{6,}" in s], \
            "挖掘侧还自带一份值长下限"
        assert _shared.MIN_SECRET_VALUE_LEN == 6

    def testMinerCarriesNoSecondSecretTableOrDetector(self):
        """退役判据：`SECRET_PATTERNS` 与 miner 自写的 `contains_secret` 都得没。

        走 AST 不走向子串——miner 的 docstring 里谈得成"过去这张表"，那是路标句。
        今天红：`contains_secret` 仍是本文件定义的函数，`SECRET_PATTERNS` 仍在模块顶层。
        """
        tree = _minerTree()
        assert "contains_secret" not in _topLevelDefNames(tree), "挖掘侧仍是第二份实装"
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        assert "SECRET_PATTERNS" not in assigned, "第八张表还在"
        imported = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and "sensitive_info" in n.module:
                imported.extend(a.name for a in n.names)
        assert "containsSensitive" in imported, "挖掘门没接单源判据口"

    def testBothDoorsAgreeOnTheSameShape(self):
        """同表同引擎：挖掘门的"拦"与两扇脱敏门的"脱"对同一形状给同一个方向的答案。"""
        for why, text, fragment in _MISSING_SHAPES + _ALREADY_COVERED:
            assert _miningDoorDrops(text) is True, why
            assert fragment not in redact_secrets(text), (why, redact_secrets(text))
            assert fragment not in _redact(text), (why, _redact(text))
