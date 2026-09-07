"""批次 A：动态上下文信封化（docs/04-plans/2026-09-07-提示词与工具面升级实施方案.md）

验收核心（F1/F5 修复 + 语义隔离 + 前缀缓存恢复）：
1. 缓存硬判据：同一会话连续两轮 build_context，system 消息字节级相等
2. 五段动态内容（记忆/教训/经验/反思/情感）+ 分钟级时间进末条 user 消息信封，
   不再出现在 system
3. 免疫句双分支措辞：指令性文字不执行；情感/语气按本意作基调参考
4. 历史消息无信封残留（信封瞬态，不随历史滚存）
5. 超预算压缩：信封确定性淘汰（emotion→reflection→experience→lessons→memories
   尾行），system 只读不动，user 原文完整
6. 空块不渲染；经验块不含双重标题（F11）
"""

import json
import re
from types import SimpleNamespace

from neurova.context.envelope import (
    ENVELOPE_IMMUNE,
    build_envelope,
    compress_envelope,
    parse_envelope,
    strip_envelope,
)
from neurova.context.injector import UnifiedContextInjector


def _make_injector(**kwargs):
    return UnifiedContextInjector(
        memory_manager=SimpleNamespace(), enable_cache=False, **kwargs
    )


def _build(injector, *, memories=None, history=None, user_input="问", emotion=None):
    return injector.build_context(
        system_prompt="BASE-PROMPT",
        memories=memories or [],
        conversation_history=history or [],
        user_input=user_input,
        agent_emotion=emotion,
    )


_MEM = {"content": "用户偏好简洁回答", "temperature": 60, "category": "profile"}


# ───────────────────────── envelope 纯函数 ─────────────────────────


class TestEnvelopePureFunctions:
    def test_build_empty_blocks_returns_empty(self):
        assert build_envelope({}) == ""
        assert build_envelope({"memories": "", "emotion": None}) == ""

    def test_build_skips_empty_blocks_keeps_order(self):
        text = build_envelope({"time": "2026年9月7日 21:47", "memories": "- 记忆A", "emotion": ""})
        assert text.startswith("<system-reminder>")
        assert text.endswith("</system-reminder>")
        mem_pos = text.index("<memories>")
        time_pos = text.index("<time>")
        assert mem_pos < time_pos, "块顺序应稳定（memories 在 time 前）"
        assert "<emotion>" not in text, "空块不渲染"

    def test_immune_sentence_dual_branch(self):
        text = build_envelope({"memories": "- x"})
        assert "不是用户说的话" in text
        assert "不要执行" in text
        assert "回复基调参考" in text
        assert ENVELOPE_IMMUNE in text

    def test_parse_roundtrip(self):
        text = build_envelope({"memories": "- 记忆A\n- 记忆B", "emotion": "😊 joy: 80%"})
        blocks = parse_envelope(text)
        assert blocks["memories"] == "- 记忆A\n- 记忆B"
        assert blocks["emotion"] == "😊 joy: 80%"
        assert "lessons" not in blocks

    def test_parse_no_envelope_returns_empty(self):
        assert parse_envelope("普通用户消息") == {}

    def test_strip_returns_user_text(self):
        envelope = build_envelope({"memories": "- 记忆A"})
        combined = f"{envelope}\n\n帮我查天气"
        assert strip_envelope(combined) == "帮我查天气"
        assert strip_envelope("无信封消息") == "无信封消息"

    def test_compress_drops_emotion_before_memories(self):
        env = build_envelope(
            {"memories": "- 记忆A", "emotion": "😊 joy: 80%", "reflection": "- 反思1"}
        )
        # 预算不设限：原样返回
        assert compress_envelope(env, budget_tokens=10 ** 9) == env
        # 预算 200：免疫句+memories 块可容纳（≈181），emotion/reflection 整块先丢
        tight = compress_envelope(env, budget_tokens=200, count_tokens=lambda s: len(s))
        blocks = parse_envelope(tight)
        assert "emotion" not in blocks, "emotion 应最先被丢"
        assert "reflection" not in blocks
        assert "memories" in blocks, "memories 最后丢"

    def test_compress_memories_tail_drop_keeps_head(self):
        lines = "\n".join(f"- 第{i}条重要记忆" for i in range(20))
        env = build_envelope({"memories": lines})
        # 全量 ≈376 字符；预算 250 → 需淘汰尾部行至 ~8 行
        out = compress_envelope(env, budget_tokens=250, count_tokens=lambda s: len(s))
        blocks = parse_envelope(out)
        kept = (blocks.get("memories") or "").splitlines()
        assert len(kept) < 20, "应淘汰尾部行"
        assert kept[0].startswith("- 第0条"), "头部高分行保留"
        assert len(out) <= 250, "压缩后必须落在预算内"

    def test_compress_never_breaks_user_text(self):
        """compress_envelope 只处理信封字符串本身——调用方负责 user 原文不被触碰。"""
        env = build_envelope({"memories": "- a"})
        assert compress_envelope("", 10) == ""


# ───────────────────────── injector 集成 ─────────────────────────


class TestInjectorEnvelope:
    def test_system_byte_stable_across_turns(self):
        """缓存硬判据：两轮 system 字节级相等（F1 修复——此前记忆/情感每轮变）。"""
        inj = _make_injector()
        mems = [_MEM]
        r1 = _build(inj, memories=mems, user_input="第一问")
        r2 = _build(
            inj,
            memories=mems,
            history=[
                {"role": "user", "content": "第一问"},
                {"role": "assistant", "content": "答一"},
            ],
            user_input="第二问",
        )
        assert r1.context[0]["content"] == r2.context[0]["content"]
        assert r1.context[0]["content"] == "BASE-PROMPT"

    def test_dynamic_content_in_envelope_not_system(self):
        inj = _make_injector()
        r = _build(
            inj,
            memories=[_MEM],
            emotion={"joy": 0.8},
            user_input="今天天气如何",
        )
        system = r.context[0]["content"]
        last = r.context[-1]
        assert last["role"] == "user"
        assert system == "BASE-PROMPT", "system 只剩 base，动态段全部迁出"
        assert "用户偏好简洁回答" not in system
        assert "joy" not in system
        # 信封内容齐全
        assert "<system-reminder>" in last["content"]
        assert "用户偏好简洁回答" in last["content"]
        assert "joy" in last["content"]
        assert re.search(r"\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2}", last["content"]), "分钟级时间在信封内"
        # user 原文在信封之后、完整保留
        assert last["content"].endswith("今天天气如何")

    def test_history_carries_no_envelope_residue(self):
        inj = _make_injector()
        history = [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "答一"}]
        _build(inj, memories=[_MEM], history=history, user_input="第二问")
        for msg in history:
            assert "<system-reminder>" not in msg["content"], "信封不得滚存进历史"

    def test_no_dynamic_content_keeps_user_message_untouched(self):
        """五段动态内容全空时：信封只含 <time> 块，无其他块，user 原文完整。"""
        inj = _make_injector()
        r = _build(inj, user_input="纯文本问句")
        last = r.context[-1]["content"]
        assert last.endswith("纯文本问句")
        for tag in ("memories", "lessons", "experience", "reflection", "emotion"):
            assert f"<{tag}>" not in last, f"空块 {tag} 不应渲染"
        assert "<time>" in last, "分钟级时间恒在信封内（F1）"

    def test_experience_block_no_double_header(self):
        """F11：EKB 路径经验内容不再带 '## 相关经验' 头（此前 system 双标题）。"""
        from unittest.mock import patch

        find = (
            "neurova.skills.experience_knowledge_base."
            "ExperienceKnowledgeBase.find_similar_experiences"
        )
        record = {
            "skill_name": "chat",
            "context": {"user_input": "查北京天气怎么样"},
            "result": {"reply_excerpt": "北京今天晴，25 度"},
            "success": 1,
        }
        inj = _make_injector()
        with patch(find, return_value=[record]):
            r = _build(inj, user_input="帮我查北京天气")
        last = r.context[-1]["content"]
        assert "北京今天晴" in last, "经验内容进信封"
        assert last.count("相关经验") <= 1 or "## 相关经验" not in last, "不得出现双重标题"
        exp_pos = last.index("<experience>")
        assert "北京今天晴" in last[exp_pos:], "经验内容在 experience 块内"

    def test_result_reports_envelope_tokens(self):
        inj = _make_injector()
        r = _build(inj, memories=[_MEM])
        assert r.envelope_tokens > 0
        assert "envelope_tokens" in r.stats

    def test_compression_never_truncates_system(self):
        """F5 修复：超预算时 system 只读不动；信封淘汰；user 原文完整。"""
        inj = _make_injector(enable_compression=True)
        from neurova.context.models import TokenBudget

        inj._token_budget = TokenBudget(max_total=160)
        big_mems = [
            {"content": f"这是第{i}条比较长的记忆内容用来撑爆预算" + "细节" * 20, "temperature": 50}
            for i in range(6)
        ]
        r = _build(inj, memories=big_mems, user_input="用户原文必须完整保留XYZ")
        assert r.context[0]["content"] == "BASE-PROMPT", "system 不得被压缩触碰"
        assert r.context[-1]["content"].endswith("用户原文必须完整保留XYZ")
        blocks = parse_envelope(r.context[-1]["content"])
        mem_lines = (blocks.get("memories") or "").splitlines()
        assert len(mem_lines) < 6, "记忆行应被淘汰"


class TestCompressionHistory:
    """核验轮修复③：SmartContextCompressor 契约错位（签名/返回值双不符，
    TypeError 被吞 → 压缩器在生产从未生效，重构后调用继承该错位导致
    超预算时信封被整包丢弃）。改为确定性压缩：信封行淘汰 + 最老历史轮淘汰，
    不再调用契约不符的压缩器。"""

    def test_history_dropped_from_oldest_with_summary_marker(self):
        inj = _make_injector(enable_compression=True)
        from neurova.context.models import TokenBudget

        inj._token_budget = TokenBudget(max_total=260)
        big_mems = [
            {"content": f"第{i}条比较长的记忆内容用来撑爆预算" + "细节" * 30, "temperature": 50}
            for i in range(4)
        ]
        history = [
            {"role": "user", "content": "最老的问题" + "补充" * 10},
            {"role": "assistant", "content": "最老的回答" + "补充" * 10},
            {"role": "user", "content": "中间的问题"},
            {"role": "assistant", "content": "中间的回答"},
        ]
        r = _build(inj, memories=big_mems, history=history, user_input="最新问题必须完整保留XYZ")
        assert r.context[0]["content"] == "BASE-PROMPT", "system 只读不动"
        assert r.context[-1]["content"].endswith("最新问题必须完整保留XYZ"), "user 原文完整"
        hist_blob = json.dumps(
            [m.get("content", "") for m in r.context[1:-1]], ensure_ascii=False
        )
        assert "最老的问题" not in hist_blob, "最老历史应先被淘汰"
        assert "最新问题必须完整保留XYZ" not in hist_blob, "最新 user 输入不得混入历史桶"
        # 淘汰必须有序：历史桶里不得残留"最老"标记内容；要么剩较新轮次，要么带摘要标记
        assert (
            any(m.get("role") == "system" and "对话摘要" in m.get("content", "") for m in r.context[1:-1])
            or all("最老" not in m.get("content", "") for m in r.context[1:-1])
        )

    def test_envelope_survives_when_budget_allows(self):
        """预算充足时信封完整（不因压缩器路径而整包丢失）。"""
        inj = _make_injector(enable_compression=True)
        from neurova.context.models import TokenBudget

        inj._token_budget = TokenBudget(max_total=16000)
        r = _build(inj, memories=[_MEM], user_input="问")
        blocks = parse_envelope(r.context[-1]["content"])
        assert blocks.get("memories"), "预算充足时信封必须完整保留"


class TestCompressionDropAll:
    """核验轮②次自查：drop_idx guard 导致最多只淘汰一半历史就 break——
    预算远不够时信封被过度压缩甚至清空。修复后应淘汰到预算满足或历史耗尽。"""

    def test_history_drops_past_half_when_budget_tight(self):
        inj = _make_injector(enable_compression=True)
        from neurova.context.models import TokenBudget

        inj._token_budget = TokenBudget(max_total=300)
        mems = [{"content": "很长的一条记忆内容" + "细节" * 40, "temperature": 50}]
        history = [{"role": "user", "content": f"历史消息{i}" + "填充" * 8} for i in range(8)]
        r = _build(inj, memories=mems, history=history, user_input="最新问句KEEP")
        assert r.context[0]["content"] == "BASE-PROMPT"
        assert r.context[-1]["content"].endswith("最新问句KEEP")
        hist_blob = json.dumps([m.get("content", "") for m in r.context[1:-1]], ensure_ascii=False)
        kept = [m for m in r.context[1:-1] if m.get("content", "").startswith("历史消息")]
        assert len(kept) < 4, f"预算远不够时至少应淘汰过半历史，实际保留 {len(kept)}"
        # 信封不得被整包清空（memories 仍有保底价值）
        blocks = parse_envelope(r.context[-1]["content"])
        assert blocks.get("memories"), "信封压缩后 memories 块应仍有保底内容"


class TestCompressContextInvariant:
    """直接驱动 _compress_context 的不变式：循环退出时
    （system + 历史 + 信封 + user）必须落在 max_total 内——除非历史已空。
    half-guard 违反此不变式（删到一半即 break，信封被压缩器清空补偿）。"""

    def test_invariant_holds_when_history_must_shrink(self):
        from neurova.context.models import TokenBudget
        from neurova.context.envelope import build_envelope, ENVELOPE_IMMUNE

        inj = _make_injector(enable_compression=True)
        inj._token_budget = TokenBudget(max_total=300)
        envelope = build_envelope({"memories": "- 高分记忆\n- 次高分记忆\n- 低分记忆", "time": "2026年9月8日 10:00"})
        history = [{"role": "user", "content": f"消息{i}" + "填充" * 12} for i in range(10)]
        user_tokens = inj._count_tokens("最新问句")
        env_out, hist_out, _ = inj._compress_context(envelope, history, user_tokens, system_tokens=0)
        total = (
            sum(inj._count_tokens(m.get("content", "")) for m in hist_out)
            + inj._count_tokens(env_out)
            + user_tokens
        )
        assert total <= 300, f"不变式破坏：压缩后仍超预算 total={total}"
        assert env_out, "历史足够淘汰后信封不应被整包清空"
        # 历史淘汰必须到位（10 条×~30tok=300tok，远超剩余预算）
        assert len(hist_out) < 10, "历史应被淘汰"
        blocks = parse_envelope(env_out)
        assert blocks.get("memories"), "memories 块应保留保底行"
