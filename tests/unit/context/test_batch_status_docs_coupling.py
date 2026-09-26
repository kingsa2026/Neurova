# -*- coding: utf-8 -*-
"""Issue #90 各批「是否已交付」的文档陈述必须与机器事实咬合（收尾批）。

## 根因（不是「漏改几处措辞」，是同一事实有两份定义）

`docs/` 里描述 B6 各批「有没有开工 / 还剩几组」的句子，被**手抄在十余处**
（台账 §2 / §14 / §17.3 / §18 / §22.5 / §23.2 / §24.2 / §25.8 / §26.2 / §29.5 /
§30.8、B6 立项的索引与规格、持久层工单索引）。这些句子之间没有任何机器判据，
于是同一时刻给出互相矛盾的结论：

    台账 §31（2026-09-26）：B6-10 剩余两组 + P10 交付，**T-09 / B6-10 / P10 至此无剩余项**
    台账 §17.3（更早）    ：`ContextFacade` / `ContextPoolRegistry` **待处置**
    B6 工单索引「前沿」   ：**B6-10 剩余两组待实施**（B6-11 已交付）

而判定口径早已各自落成机器事实：`scripts/ci/contextDeadlines.txt` 逐符号写了终局
（`ContextFacade | absent | 已删除`、`ContextPoolRegistry | self_loop | 已接线`），
各批的判据文件也已进 `scripts/ci/protected_tests.txt` 且退役产物已从仓库消失。
差的不是「再改一遍措辞」—— 那只是 consumer 侧修，下一批交付会再陈旧一次；
差的是把**陈述钉到那份事实源上**（`AGENTS.md` 修复教义第 6 条）。

## 本守卫锁三件事

1. **已交付的批次，文档里不得再写它「未开工 / 待实施 / 待推进」**。
   判定不读措辞自述，只读两处机器事实 —— 该批的判据文件在受保护子集里
   （清单是 CI 唯一执行面）、该批的退役产物已从仓库消失（删净了）。
2. **反向控制**：把任一判据文件从清单摘掉、或把任一退役产物放回去，
   判定必须翻转（说明它真的跟着事实源，不是恰好恒真）。
3. **不得空转**：登记批次集合非空、扫描面必须真读到文档、注入一条陈旧陈述必须判红。
"""
from __future__ import annotations

import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 交付证据（一）：这些判据文件必须都在受保护子集里 —— CI 唯一执行面，跑得到才算交付。
#: 登记形态与 `tests/unit/context/test_b5_scale_batch_registration.py` 的 `BATCH_FILES` 同族
#: （那份管 B5 批，本份管 #90 收尾各批；同一条判据不复制扫描逻辑，两份各管一段）。
DELIVERED_JUDGE_FILES = (
    # B6-3/4：池符号真面 / 池身份收口（B6-2 的端点上位面已随 T-09 下架，
    # 判据由 `test_context_budget_face_retirement.py` 的「该面确实不在」承担）
    "tests/unit/context/test_pool_identity_resolution.py",
    # B6-6…B6-9：向量批量入口 / 归档时刻单源 / 降级恢复 / 额度形态
    "tests/unit/context/test_vector_batch_encoding.py",
    "tests/unit/context/test_archive_moment_scoring.py",
    "tests/unit/context/test_context_degradation_recovery.py",
    "tests/unit/context/test_view_budget_single_form.py",
    # B6-10 批次 E/F：门面层退场 + 池注册表 session 分区读路径退场
    "tests/unit/context/test_context_facade_retirement.py",
    "tests/unit/context/test_pool_registry_session_partition_retirement.py",
    # B6-11：D5 反思记账改「进视图才记账」
    "tests/unit/context/test_reflection_view_accounting_b6_11.py",
    # T-10c/d：载荷进窗口预算 + 工具轮可观测计数与回退等式
    "tests/unit/context/test_microcompact_threshold_decoupling.py",
    "tests/unit/context/test_tool_payload_budget_accounting.py",
    "tests/unit/context/test_tool_turn_observability_t10d.py",
    # T-11 全族：代际栈 / 层索引 / 下钻 / rollup / 分辨率装配器 / 顶概览常驻
    "tests/unit/context/test_fold_generation_t11a.py",
    "tests/unit/context/test_fold_layer_index_t11b.py",
    "tests/unit/context/test_fold_span_drilldown_t11d.py",
    "tests/unit/context/test_fold_rollup_t11e.py",
    "tests/unit/context/test_fold_resolution_t11c.py",
    "tests/unit/context/test_fold_top_overview_resident_t11c.py",
    # §12.7 判据 7：真值链两处契约面收口 + 生产回填
    "tests/unit/context/test_provider_cache_truth_wiring_90.py",
    # T-09 收尾两片：假预算面 / 上下文池设置假面下架（判据锁「该面确实不在」）
    "tests/unit/api/test_context_budget_face_retirement.py",
    "tests/unit/api/test_context_pool_settings_face_retirement.py",
)

#: 交付证据（二）：这些生产文件必须已从仓库消失 —— 「退役」是删净，不是不注册。
RETIRED_PATHS = (
    "neurova/context/context_facade.py",  # B6-10 批次 E
    "neurova/api/endpoints/context_pool_settings.py",  # T-09 收尾（第 3 片）
    "neurova/context/context_pool_registry.py",  # B6-10 批次 F 仅余单池读侧，多池机制整个退场
)

#: 扫描面：陈述「某批还没做」的落点（#90 的派单源、工单、台账与两份规格索引）。
CLAIM_DOCS = (
    "docs/05-reports/上下文三链路修复台账_2026-09-21.md",
    "docs/04-plans/上下文三链路修复工单_2026-09-21.md",
    "docs/specs/2026-09-21-context-persistence/tickets/000-索引.md",
    "docs/specs/2026-09-22-b6-deadline-and-fake-surfaces/tickets/000-索引.md",
    "docs/specs/2026-09-22-b6-deadline-and-fake-surfaces-audit.md",
)

#: 陈旧陈述：同句必须**共现**全部标记才算命中（单标记会误伤「历史交代」——
#: 例如 §31.1「台账**原来**对两条的处置都是「待处置」」陈述的是改前形态，合法）。
#: 取值刻意避开 `待处置` 这个台账枚举名，只收表示**当前仍未做**的语气词。
STALE_CLAIMS = (
    (("B6 清死线与谎报面", "仍未开工"), "B6 全批「仍未开工」"),
    (("B6 仍未开工",), "B6 全批「仍未开工」（§14 收口注记）"),
    (("B6 清死线与谎报面", "仍未实施"), "B6 全批「仍未实施」"),
    (("仍未开工", "B6-10"), "B6-10「仍未开工」"),
    (("仍未开工", "B6-11"), "B6-11「仍未开工」"),
    (("仍未开工", "T-10c"), "T-10c「仍未开工」"),
    (("仍未做", "T-10d"), "T-10d「仍未做」"),
    (("B6-10 剩余两组", "仍未处置"), "B6-10 剩余两组「仍未处置」"),
    (("B6-10 剩余两组", "待实施"), "B6-10 剩余两组「待实施」"),
    (("B6-10 剩余两组", "待推进"), "B6-10 剩余两组「待推进」"),
    (("B6-10 剩余两组", "§17.3"), "B6-10 剩余两组「见台账 §17.3」"),
    (("B6-10 剩余两组", "须先裁定"), "B6-10 剩余两组「须先裁定」"),
    (("B6-11", "待你拍板"), "B6-11「待你拍板」"),
    (("B6-11", "待拍板"), "B6-11「待拍板」"),
    (("剩余五组", "§17.3"), "B6-10「剩余五组见台账 §17.3」"),
    (("批次 A / B / C / D 已交付",), "B6-10 停在批次 A/B/C/D"),
    (("T-08 规模与自适应额度", "未落地"), "T-08「未落地」"),
    (("T-07 池持久化", "读回待验"), "T-07「读回待验」"),
)


def protectedEntries() -> set:
    """受保护子集的条目（`#` 注释与空行忽略，清单是 CI 唯一执行面）。"""
    raw = io.open(PROTECTED, encoding="utf-8").read()
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


def deliveryGaps() -> dict:
    """交付证据的缺口：`{"judgeNotInProtected": [...], "judgeMissing": [...], "retiredStillPresent": [...]}`。"""
    listed = protectedEntries()
    judge_not_listed = [rel for rel in DELIVERED_JUDGE_FILES if rel not in listed]
    judge_missing = [
        rel for rel in DELIVERED_JUDGE_FILES
        if not (PROJECT_ROOT / rel).is_file()
    ]
    retired_present = [
        rel for rel in RETIRED_PATHS
        if (PROJECT_ROOT / rel).exists()
    ]
    return {
        "judgeNotInProtected": judge_not_listed,
        "judgeMissing": judge_missing,
        "retiredStillPresent": retired_present,
    }


def issueFullyDelivered() -> bool:
    """Issue #90 的交付面是否闭环 —— 只由两处机器事实推出，不读任何自述。"""
    return not any(deliveryGaps().values())


#: 历史交代标记：同句出现任一，则该句陈述的是**改前形态**（合法）。
#: 缺了它，上面第 4 条会把「原写"未落地"」这类正当的历史交代一并判红 ——
#: 那时守卫只能靠"不写历史"来转绿，正是 `AGENTS.md` 修复教义第 2 条禁的
#: 「把报错改到看不见」。反向控制在 `TestDiscriminatingPower` 里逐条钉住。
HISTORICAL_MARKERS = ("原来", "原写", "改前", "此前", "快照原")


def staleClaims(text: str) -> list:
    """文本里陈述「某批还没做」的片段（空列表＝陈述已与交付面同源）。

    判定取两件事实：同句共现全部标记（`STALE_CLAIMS`）**且**不含历史交代标记
    （`HISTORICAL_MARKERS`）。只做共现不做时序推断 —— 时序无法从文本推出。
    """
    found: list = []
    for line in text.splitlines():
        if any(marker in line for marker in HISTORICAL_MARKERS):
            continue
        for markers, label in STALE_CLAIMS:
            if all(marker in line for marker in markers):
                found.append(f"{label} :: {line.strip()[:100]}")
    return found


class TestDeliveryIsBackedByMachineFacts:
    """先决条件：交付面闭环本身要可复核，否则下面的陈述判定没有真值来源。"""

    def test_registered_judge_files_are_all_in_protected_subset(self):
        gaps = deliveryGaps()["judgeNotInProtected"]
        assert not gaps, (
            "登记为「已交付」的判据文件不在受保护子集里 —— CI 跑不到它们，"
            f"「已交付」就没有机器依据：{gaps}"
        )

    def test_registered_judge_files_exist_in_repo(self):
        gaps = deliveryGaps()["judgeMissing"]
        assert not gaps, f"登记为「已交付」的判据文件在仓库里不存在：{gaps}"

    def test_registered_retired_paths_are_gone(self):
        gaps = deliveryGaps()["retiredStillPresent"]
        assert not gaps, (
            "登记为「已退役」的生产文件仍在仓库里 —— 「退役」是删净，不是不注册："
            f"{gaps}"
        )


class TestDocsMatchDeliveryFacts:
    """主判据：交付面闭环时，派单源与台账不得再写「某批还没做」。"""

    def test_claim_docs_exist(self):
        missing = [
            rel for rel in CLAIM_DOCS
            if not (PROJECT_ROOT / rel).is_file()
        ]
        assert not missing, f"扫描面的文档不存在（守卫会空转）：{missing}"

    def test_no_stale_batch_claims_when_issue_is_delivered(self):
        if not issueFullyDelivered():
            return  # 交付面未闭环时，这些陈述合法（本判据只在闭环后生效）
        offenders: list = []
        for rel in CLAIM_DOCS:
            text = io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
            for hit in staleClaims(text):
                offenders.append(f"{rel}: {hit}")
        assert not offenders, (
            "交付面已闭环（判据进受保护子集 + 退役产物已消失），但文档仍陈述「某批还没做」。\n"
            "这些句子是同一事实的手抄第二份，已实测与 §31/§32/§33 的收口记录互相矛盾：\n  "
            + "\n  ".join(offenders)
            + "\n修法：就地改判为收口记录（见台账 §31 / §32 / §33），"
              "不改写历史（「原写 X」保留），也不删如实登记的残余。"
        )


class TestDiscriminatingPower:
    """反向控制：判据必须真的跟着事实源 —— 否则它只是「当前恰好没写」的快照。"""

    def test_injecting_a_stale_claim_turns_red(self, tmp_path, monkeypatch):
        module = __import__(__name__, fromlist=["staleClaims"])
        clean = "本批 001–008 全部交付。\n**B6-11 已交付**（2026-09-25）。"
        assert module.staleClaims(clean) == []
        assert module.staleClaims("2. **B6 清死线与谎报面**：**仍未开工**。")
        assert module.staleClaims("- **T-10c 仍未开工**，但本轮已复核前置读数。")
        assert module.staleClaims("**B6-10 剩余两组待实施**（B6-11 已交付）。")
        # 历史交代不得被误伤：`原来/改前/原写` 形态陈述的是改前状态。
        assert module.staleClaims("台账**原来**对两条的处置都是「待处置」。") == []
        assert module.staleClaims('**09-23 快照原写"未落地"**，按实测为准。') == []
        # 反方向：把历史标记摘掉，同一句必须立刻判红（豁免不得变成后门）。
        assert module.staleClaims("T-08 规模与自适应额度 | **未落地** | 探针 P9。")

        drifted = tmp_path / "台账.md"
        io.open  # noqa: B018 - 明确此处只写文件
        drifted.write_text(clean + "\n**B6-10 剩余两组待实施**。\n", encoding="utf-8")
        monkeypatch.setattr(module, "CLAIM_DOCS", (str(drifted),))
        assert module.staleClaims(drifted.read_text(encoding="utf-8"))

    def test_摘掉一条判据即让交付判定翻转(self, monkeypatch):
        module = __import__(__name__, fromlist=["issueFullyDelivered", "protectedEntries"])
        assert module.issueFullyDelivered() is True
        trimmed = module.protectedEntries() - {
            "tests/unit/context/test_context_facade_retirement.py",
        }
        monkeypatch.setattr(module, "protectedEntries", lambda: trimmed)
        assert module.issueFullyDelivered() is False, (
            "判据不跟随事实源：把该批的判据从受保护子集摘掉后，"
            "「已交付」竟仍然成立 —— 那它就不是从机器事实推出来的。"
        )

    def test_把退役产物放回去即让交付判定翻转(self, tmp_path, monkeypatch):
        module = __import__(__name__, fromlist=["issueFullyDelivered"])
        assert module.issueFullyDelivered() is True
        resurrected = tmp_path / "context_facade.py"
        resurrected.write_text("", encoding="utf-8")
        monkeypatch.setattr(module, "RETIRED_PATHS", (str(resurrected),))
        assert module.issueFullyDelivered() is False, (
            "判据不读退役产物：把已删净的文件放回去后「已交付」仍成立。"
        )
