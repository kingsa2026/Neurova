"""三态契约在**写入面**的剩余命中点：outcome 词域必须单一事实源，未知词不许洗成成功。

## 为什么这是同一根因的命中点（不新造议题）

票 004 的禁区是一句话：**三态（成功 / 失败 / 未测量）不许在半路裂开**。已修的四面
（EKB 行 / 权重表 / 结晶器 / API 展示）与第五面（进 prompt 的那一段）都在**读**侧。

写入侧的 `POST /experience/records` 一直用一句补集表达式把客户端给的词折算成行：

```python
success=None if outcome == "unevidenced" else (outcome != "failure")
```

它认的词只有两个半：`success` / `failure` / `unevidenced`。**其余任何词都落 `True`**，
即"没听懂"被静默记成"做成了"——与"未测量被渲染成 ✗"是同一条契约上的两个方向，
教义第 1 条点名的 consumer-only 形态：症状在行上，根因在**两个词域**：

- 后端契约词域是 `skills.models` 的三值；
- 前端 `experience.ts` 的类型与新建表单的词域是 `'success' | 'failure' | 'partial'`，
  且表单把 `partial`（部分成功）作为可选项提交。

两边词域不一致 ⇒ 用户点"部分成功"提交，库里落的是 `success=1`，回读显示"成功"，
**没有任何地方出声**。第三份词表出现在端点内部的字面量里（`"unevidenced"` / `"failure"`
各写一次），所以前端改词域不会带着后端一起动。

## 锁定行为

1. 三个契约词各自归位：`success → 1` / `failure → 0` / `unevidenced → NULL`；
2. 未知词（含前端旧词 `partial`、空串、任意串）**显式 422 并点名合法词域**，
   不得折进任何一个态（诚实暴露，教义第 2 条）；
3. 词 → 态的反向映射**只有一处定义**（与 `outcomeWord` 正向映射同模块），
   端点与前端都不得再自带一份词表；
4. 前端词域与后端契约词域同一份：类型里没有 `partial`，有 `unevidenced`；
   11 个语言包的 `outcomeUnevidenced` 齐备、`outcomePartial` 死键退役。

## 反向控制

把补集表达式写回端点、或把 `partial` 写回前端词域，本文件立刻转红。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi import HTTPException

from neurova.api import endpoints as endpoints_pkg
from neurova.api.endpoints import experience_knowledge_api as exp_api
from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase
from neurova.skills.models import OUTCOME_STATES, outcomeStateFromWord

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def readText(relPath: str) -> str:
    return io.open(PROJECT_ROOT / relPath, encoding="utf-8").read()


def readCodeLines(relPath: str) -> str:
    """只取代码行：**注释引用旧写法**与"第二份定义"是两件事。

    判据要的是"还有没有把契约词写进代码"，不是"注释里有没有提这个词"——
    把注释算进去，判据就逼着人删掉说明它为什么被修的那段注释（教义第 2 条禁止抹除）。
    """
    lines = [
        line for line in readText(relPath).splitlines()
        if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


@pytest.fixture
def ekb(tmp_path, monkeypatch):
    kb = ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb-word-domain.db"))
    monkeypatch.setattr(exp_api, "get_experience_kb", lambda: kb)
    return kb


def request(outcome, task="t", context="c"):
    return exp_api.AddExperienceRecordRequest(
        agent_id="a", task_type=task, context=context, outcome=outcome
    )


def rowOf(kb, task):
    return [r for r in kb.get_experience_records(agent_id="a") if r["skill_name"] == task][0]


class TestKnownWordsLandOnTheirOwnState:
    """三态各自成值：写入面不得把任两个态撞成一个。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("word", "expectedColumn"),
        [("success", 1), ("failure", 0), ("unevidenced", None)],
    )
    async def test_eachWordLandsOnItsOwnState(self, ekb, word, expectedColumn):
        await exp_api.add_experience_record(request(word, task=f"k-{word}"))
        row = rowOf(ekb, f"k-{word}")
        assert row["success"] == expectedColumn, (
            f"契约词 {word!r} 落库应该是 {expectedColumn!r}，实际 {row['success']!r}"
        )


class TestUnknownWordsAreRejectedNotFolded:
    """未测量是"没测到"，未知词是"没听懂"——两者都不许变成"成功"。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", ["partial", "bogus", "", "SUCCESS", "success "])
    async def test_unknownWordIsNotFoldedIntoASuccess(self, ekb, word):
        with pytest.raises(HTTPException) as excinfo:
            await exp_api.add_experience_record(request(word, task=f"u-{word!r}"))
        assert excinfo.value.status_code == 422, (
            f"未知词 {word!r} 应以 422 诚实拒绝，实际 {excinfo.value.status_code}"
        )
        assert not ekb.get_experience_records(agent_id="a"), (
            f"未知词 {word!r} 被写进了库——静默折叠就是这个形态"
        )

    @pytest.mark.asyncio
    async def test_rejectionNamesTheLegalVocabulary(self, ekb):
        with pytest.raises(HTTPException) as excinfo:
            await exp_api.add_experience_record(request("partial"))
        detail = str(excinfo.value.detail)
        for word in ("success", "failure", "unevidenced"):
            assert word in detail, f"拒绝理由没点名合法词域（缺 {word!r}）：{detail!r}"


class TestWordToStateMappingHasOneDefinition:
    """词 → 态的反向映射与态 → 词的正向映射同处一份（教义第 6 条）。"""

    def test_reverseMappingCoversExactlyTheContractWords(self):
        assert OUTCOME_STATES == {"success": True, "failure": False, "unevidenced": None}, (
            f"反向映射的域与契约词不一致：{OUTCOME_STATES!r}"
        )

    def test_mappingIsNotDuplicatedInTheEndpoint(self):
        text = readCodeLines("neurova/api/endpoints/experience_knowledge_api.py")
        assert '"unevidenced"' not in text, (
            "端点又自带了一份契约词字面量——词域要取单源，不得各写一份"
        )
        assert '"failure"' not in text, "端点自带契约词字面量，词域的第二份定义"
        assert "outcomeStateFromWord" in text, "端点没有取用单源的反向映射"

    def test_criterionActuallyNoticesASecondDefinition(self):
        """反向控制：把补集表达式写回端点，上面那条判据必须转红。"""
        synthetic = 'success=None if body.outcome == "unevidenced" else (body.outcome != "failure")'
        assert '"unevidenced"' in synthetic, "反向控制的样本本身没咬合，判据成了恒真"

    def test_mappingRejectsRatherThanGuessing(self):
        with pytest.raises(ValueError):
            outcomeStateFromWord("partial")
        assert outcomeStateFromWord("unevidenced") is None, (
            "未测量必须原样还原成 None，不许与失败撞成一个值"
        )


class TestFrontendWordDomainMatchesTheBackendContract:
    """前端词域是后端契约词域的第二份定义处——两份必须逐字同一份。"""

    def test_typeDomainHasNoPartialAndHasUnevidenced(self):
        text = readText("NeurUI/src/api/modules/experience.ts")
        assert "'partial'" not in text, (
            "前端类型仍带着 partial——后端不认这个词，提交即被 422 或（改前）静默折成成功"
        )
        assert "'unevidenced'" in text, "前端类型缺 unvidenced，三态在词域里就裂了"

    def test_createFormOffersTheContractWordsOnly(self):
        text = readText("NeurUI/src/pages/ExperienceKnowledgePage.vue")
        assert 'value="partial"' not in text, "新建表单仍提供 partial 选项（后端不认的词）"
        assert 'value="unevidenced"' in text, "新建表单缺 unvidenced 选项"

    def test_localesCarryTheThirdWord(self):
        localesDir = PROJECT_ROOT / "NeurUI/src/i18n/locales"
        codes = sorted(p.stem for p in localesDir.glob("*.ts") if not p.stem.startswith("_"))
        assert len(codes) == 11, f"语言包数量变了（{len(codes)}）：{codes}"
        for code in codes:
            text = readText(f"NeurUI/src/i18n/locales/{code}.ts")
            assert "outcomeUnevidenced:" in text, f"{code} 缺 outcomeUnevidenced"
            assert "outcomePartial:" not in text, f"{code} 仍留着退役死键 outcomePartial"
