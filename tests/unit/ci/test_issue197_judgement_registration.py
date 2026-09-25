# -*- coding: utf-8 -*-
"""Issue #197 批的判据文件必须真在 CI 受保护子集里 —— 且不得被静默删掉。

## 根因（不是形状）

本批（能力缺口自主闭环，Issue #197）六票各交付/修订了判据文件，逐票在提交时
登记进 `scripts/ci/protected_tests.txt`。但**同批的最后一票**（`df0f1f15`，
"T-03 同根第三命中点"）在编辑该文件时，把 T-06 的两行登记注释与它的判据条目
一并删掉了 —— `tests/unit/evolution/test_reward_does_not_gamble_on_retrieval.py`
的 9 条判据从此**不在 CI 上跑**。

形态与 Issue #109 / 本仓既有两例正相反：
- Issue #109：清单指向不存在的文件（跑不起来，CI 退 4）；
- B5 规模批：文件在仓而漏登记（CI 跑不到）；
- **本例：登记过、又被后一个不相关提交静默删掉**。

三种形态都让"CI 绿"与"判据真跑过"变成两件事。前两种已有常驻守卫
（`tests/unit/test_dev_path_and_runtime_dep_guards.py`、
`tests/unit/context/test_b5_scale_batch_registration.py`），
**"登记被删"这一向此前无人守** —— 于是删一行就能让一整票的判据从 CI 上消失，
且没有任何红。

判据（可证伪）：从清单里删掉本批任一条 → 本文件转红。

## 为什么不写成"整目录必须全登记"

本批跨 `agent/ evolution/ tools/ security/` 四个模块目录，这些目录里同时住着
大量**预存失败**的文件（不满足受保护子集"只进当前确定全绿"的原则）。
按目录全收会连带把预存失败拖进 CI，那是另一件事。故本守卫只钉**本批自己交付
与修订、且逐文件单跑确定全绿**的那几条，一个批次一份登记，不复制扫描逻辑。
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 本批（Issue #197）交付或修订的判据文件。逐条列明它守什么，避免变成无注释的
#: 字符串堆——下一轮读到它时要知道"删掉这条等于哪一票失去 CI 覆盖"。
BATCH_JUDGEMENTS = {
    # T-01 诊断回环：工具失败正文必须携带 stderr/exit_code
    "tests/unit/agent/test_tool_failure_diagnostics.py": "T-01 失败诊断回到模型",
    # T-01 同契约：失败结果不得被 OutputRef 折叠成无诊断信息的引用
    "tests/unit/agent/test_tool_output_ref.py": "T-01 失败结果不得被折叠",
    # T-02 句柄可见：附件抽取失败携带 file_id/status 且留痕，且不泄露绝对路径
    "tests/unit/agent/test_attachment_handle_injection.py": "T-02 附件句柄与留痕",
    # T-03 缺口驱动：自主造能力的入口改挂能力缺口
    "tests/unit/agent/test_capability_gap_trigger.py": "T-03 缺口信号取代关键词闸",
    # T-03 同根消费方：014 置信闸用例按缺口入口重钉前置条件
    "tests/unit/evolution/test_nl_confidence_gate.py": "T-03 消费方入口前置",
    # T-03 同根消费方：注入扫描守卫的探针必须真咬合
    "tests/unit/security/test_p1_6_skill_guard.py": "T-03 注入扫描探针咬合",
    # T-04 字母表去幻：合成序列 ⊆ 真实注册名，未知分类转人工复核
    "tests/unit/evolution/test_synthesis_alphabet_registered.py": "T-04 字母表去幻",
    # T-04 同契约：general 分类不再落兜底幻名
    "tests/unit/evolution/test_nl_synthesizer.py": "T-04 general 分类无幻名兜底",
    # T-05 只读数据集查询原语：句柄域 / 只读连接 / SQL 白名单 / 有界
    "tests/unit/tools/test_query_database.py": "T-05 只读查询原语四道防线",
    # T-06 强化口径：纯检索基因型不得被遗传反哺顶到权重上限
    "tests/unit/evolution/test_reward_does_not_gamble_on_retrieval.py": "T-06 强化口径",
    # T-03 同根第四条（并行会话补）：市场未命中 → 自主合成的回退不得成死路
    "tests/unit/agent/test_skill_acquisition_fallback.py": "T-03 市场未命中回退可达",
}

SELF_REL = "tests/unit/ci/test_issue197_judgement_registration.py"


def _listed() -> set:
    """CI 实际跑的清单条目（唯一事实源，不另建第二份清单）。"""
    raw = io.open(PROTECTED, encoding="utf-8").read()
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


def test_every_batch_judgement_is_registered():
    """反向自证：从清单里摘掉本批任一条 → 本用例转红。"""
    listed = _listed()
    missing = [
        rel for rel in sorted(BATCH_JUDGEMENTS)
        if rel not in listed
    ]
    assert not missing, (
        "Issue #197 批的判据文件不在受保护子集里 —— CI 不会跑它们，"
        "'全绿'与'判据真跑过'不是同一件事：\n  "
        + "\n  ".join(f"{rel}（{BATCH_JUDGEMENTS[rel]}）" for rel in missing)
        + "\n修复：逐文件单跑确认全绿后，加进 scripts/ci/protected_tests.txt。"
    )


def test_registered_batch_judgements_are_tracked_by_git():
    """清单条目必须真被 git 跟踪：未跟踪 = CI 上 `file or directory not found`。"""
    files = sorted(BATCH_JUDGEMENTS)
    result = subprocess.run(
        ["git", "ls-files", *files],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
    )
    tracked = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert tracked == set(files), (
        f"本批判据里登记了未被 git 跟踪的文件：{sorted(set(files) - tracked)}"
    )


def test_guard_itself_is_registered():
    """守卫自己也得进清单，否则本文件的判据在 CI 上根本不执行。"""
    assert SELF_REL in _listed(), (
        f"{SELF_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
    )
