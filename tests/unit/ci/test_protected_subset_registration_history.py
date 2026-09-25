# -*- coding: utf-8 -*-
"""受保护子集的条目**一旦登记过，就不得被静默消失**（Issue #197 批同根第三向）。

## 根因（与"漏登记"是两个方向，此前无人守）

`scripts/ci/protected_tests.txt` 是 CI 实际跑的清单。本仓已有两条守卫守着
"清单与文件对不上"的两个方向：

- **指向不存在的文件** → `tests/unit/test_dev_path_and_runtime_dep_guards.py`
  的 `TestProtectedSubsetEntriesAreTracked`（跑不起来，CI 退 4）；
- **文件在仓而漏登记** → `tests/unit/context/test_b5_scale_batch_registration.py`
  等按批次的登记守卫（CI 跑不到，绿得毫无意义）。

**第三向是"登记过、随后被静默删掉"**：删一行即可让整票判据从 CI 上消失，
且没有任何红。Issue #197 批的 T-06 就是这样丢的（登记被同批后一票
`df0f1f15` 编辑清单时带走），本轮的 `test_issue197_judgement_registration.py`
只钉住了**本批**那几条，不足以拦住其它批次的同类删除。

## 实测（本仓历史的真实读数，不是推测）

按 `git log` 取出清单曾经登记过的**全部**条目，与 `origin/main` 现值比对：

```
曾登记过 250 条，现值 243 条 —— 差集 7 条
```

其中 2 条对应的文件已被有意退役（`test_endpoint_mount_wiring_guard.py`
并入 `test_route_mount_contract_guard.py`；`test_devRulesConfigGuard.py`
随 dev 规则配置退役），另 5 条的文件**都还在仓里且逐文件单跑全绿**，
却已不在 CI 清单上：

```
tests/unit/agent/test_tool_call_record_identity.py        5 passed
tests/unit/security/test_tool_event_export_redaction.py   5 passed
tests/unit/api/test_memory_enhancement_real_manager.py    7 passed
tests/unit/neurflow/test_storage.py                      32 passed
tests/unit/cognitive/test_cognitive_storage_engine.py    17 passed
```

最典型的一例是 `88901c00`（"清掉清单里的重复登记行"）：它要删的是
`test_tool_event_export_redaction.py` 的**重复**条目，实际把**两份都删了**，
顺带带走只登记过一次的 `test_tool_call_record_identity.py`。该提交的正文
写着"保留 e3f15895 收口后的 704 段"，而 704 段也在同一次编辑里消失——
**"删重复"与"删光"在清单这种纯文本上没有区别，删除动作本身不产生任何红。**

## 判据

1. 历史曾登记过、文件现在仍在仓里的条目，必须仍在清单里（否则本文件红）；
2. 上一条的每一处**例外**都必须在台账里显式署名并给出依据，
   台账里多出的行（已复原或无对应）同样红——两个方向都可证伪。

台账与判据同源：台账是本守卫读的唯一事实源，不存在第二份例外清单。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
#: 例外台账：曾登记过、现已按依据退役的条目。行格式 `路径 | 依据`。
LEDGER = PROJECT_ROOT / "tests" / "unit" / "ci" / "protectedSubsetRetired.txt"


def _listedNow() -> set:
    raw = PROTECTED.read_text(encoding="utf-8")
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


def _listedEver() -> set:
    """清单**历史上**出现过的全部条目（按提交逐个读清单全文，不解析 patch）。

    为何不解析 `git log -p` 的增行：删除动作**只出现在冲突合并**里也照样成立。
    实测两处此类形态（`7d672487` 的合并正文写着"两侧纯追加、无删除"，实际删掉
    4 条 Issue #56 登记；`4eaa5055` 同形）。逐提交读全文则两种形态一视同仁，
    也不依赖 patch 形态（重命名、空白、CRLF 都不影响）。

    为何用 `--full-history`：合并提交若只在一侧带上清单变更，默认简化会跳过它，
    于是"只在合并里发生"的那次删除看不见。
    """
    shas = subprocess.run(
        ["git", "log", "--full-history", "--format=%H", "--",
         "scripts/ci/protected_tests.txt"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180,
    ).stdout.split()
    if not shas:
        raise AssertionError(
            "取不到清单的历史提交——本地不是 git 工作树，或历史被浅克隆截断。"
            "本守卫按历史判「曾经登记过」，历史不可用即无法作答，"
            "故响亮失败而不是静默放行（教义第 2 条）。"
        )
    # 一次进程批量取回各提交的清单全文（逐提交起进程会拖慢同一 CI 会话）。
    batch = subprocess.run(
        ["git", "cat-file", "--batch"],
        input="\n".join(f"{sha}:scripts/ci/protected_tests.txt" for sha in shas),
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180,
    ).stdout
    found = set()
    for line in batch.splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry.startswith(("tests/", "scripts/")):
            found.add(entry)
    return found


def _retiredLedger() -> dict:
    if not LEDGER.exists():
        return {}
    rows = {}
    for raw in LEDGER.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip() if raw.strip().startswith("#") else raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[1]:
            raise AssertionError(
                f"台账行缺少依据（格式 `路径 | 依据`）：{raw!r}"
            )
        rows[parts[0]] = parts[1]
    return rows


def test_ever_registered_entry_still_in_repo_stays_registered():
    """反向自证：从清单里摘掉任一条仍留在仓里的历史条目 → 本用例转红。"""
    listed = _listedNow()
    retired = _retiredLedger()
    offenders = _offendersAmong(_listedEver() - listed, retired)
    assert not offenders, (
        "以下条目曾登记进受保护子集、其文件现在也还在仓里，却已不在清单上——\n"
        "CI 不会再跑它们，而清单与文件都对得上，不会有任何红：\n  "
        + "\n  ".join(offenders)
        + f"\n修复：逐文件单跑确认全绿后重新登记；确需退役则在 {LEDGER.name} "
        "里署名退役依据。"
    )


def _offendersAmong(gap, retired) -> list:
    """从"曾登记、现已不在清单"的差集里挑出真正的缺陷项。

    抽成纯函数是为了让**台账豁免分支**也有真消费者：文件仍在仓里却退役（判据被撤）
    是允许的，但必须署名，故 `retired` 在这里生效。本函数由下面的反向自证直接调用。
    """
    return [
        path for path in sorted(gap)
        if (PROJECT_ROOT / path).exists() and path not in retired
    ]


def test_retired_ledger_exemption_is_honored():
    """反向自证：文件仍在仓里时，豁免只认台账署名——不署名即红、署名即放行。

    非恒真壳的证据：同一输入（文件存在、不在清单）在两个方向上给出相反读数。
    """
    sample = "tests/unit/ci/test_protected_subset_registration_history.py"
    assert (PROJECT_ROOT / sample).exists(), "样本文件不在仓里，本用例失效"
    assert _offendersAmong([sample], {}) == [sample], "未署名却未被点名——豁免成了免检通道"
    assert _offendersAmong([sample], {sample: "示例依据"}) == [], "台账署名后仍被点名"
    # 已不在仓里的文件不是缺陷项（无从登记），也不要求台账署名
    ghost = "tests/unit/ci/__no_such_guard__.py"
    assert _offendersAmong([ghost], {}) == []


def test_every_vanished_entry_is_signed_off():
    """曾登记过、文件现已不在仓里的条目，**必须**在台账里署名。

    这是台账的另一半（上面的用例查"多出的行"，本条查"缺的行"）：少了这一向，
    删掉台账行 = 让一次退役从记录里消失，而文件本身已不在仓里，没人会再看见它。
    两向合起来，「登记过的条目消失」这件事要么被复原、要么留一条署名记录。
    """
    listed = _listedNow()
    retired = _retiredLedger()
    vanished = [
        path for path in sorted(_listedEver() - listed)
        if not (PROJECT_ROOT / path).exists()
    ]
    unsigned = [path for path in vanished if path not in retired]
    assert not unsigned, (
        "以下条目曾登记进受保护子集、其文件现已不在仓里，却没有退役署名——\n"
        "一次退役会就此从记录里消失（文件已不在，不会再有第二处看见它）：\n  "
        + "\n  ".join(unsigned)
        + f"\n修复：在 {LEDGER.name} 里写一行 `路径 | 退役依据`。"
    )


def test_retired_ledger_has_no_stale_rows():
    """台账不得留无效行：已复原、或从未登记过的路径都算台账失真。"""
    listed = _listedNow()
    ever = _listedEver()
    stale = []
    for path, reason in _retiredLedger().items():
        if path in listed:
            stale.append(f"{path}（已重新登记，台账该行应删；依据：{reason}）")
        elif path not in ever:
            stale.append(f"{path}（历史上从未登记过，台账该行无对应）")
    assert not stale, "退役台账里有无效应行：\n  " + "\n  ".join(stale)


def test_guard_itself_is_registered():
    rel = "tests/unit/ci/test_protected_subset_registration_history.py"
    assert rel in _listedNow(), (
        f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
    )
