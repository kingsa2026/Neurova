# -*- coding: utf-8 -*-
"""受保护子集里**进程内计时的口径**必须逐条登记结论。

根因（不是形状）：本仓已两次因「判据绑了墙钟」把同一份代码判成一红一绿——
`perf_gate.py` 的两处微基准（2026-09-24，构建 cnb-6t7-1k3964vd2）与
`test_perf_gate_contract.py` 的等待注入（2026-09-25，py3.11 绿 / py3.12 红）。
两处都改对了，但**每一次都是 CI 先红、人再回头找**：受保护子集里没有一处
判据回答"这份文件为什么可以用这个时钟口径"。同一契约的命中点也不止这两处
（`tests/unit/` 下另有数处进程内 CPU 计时用例），谁下次顺手多引一处，
仍然要靠 CI 红来发现。

本守卫不改任何判据的对错，只要求**逐条有结论**：受保护子集里每个进程内计时
文件都必须在 `CLOCK_LEDGER` 里写明它量什么、为什么用这个口径。新增一处未登记
的计时口径即判红——不许整体放行（`AGENTS.md` 修复教义第 2 条）。

为什么守卫放在 `tests/unit/`：受保护子集里 `unit-tests` 是**唯一**跑
`tests/unit/` 的 job。把守卫放进 `tests/performance/` 等于它永不执行
（该目录不在任何子集里；这条纪律同 `tests/unit/test_ci_wallclock_assertion_ledger.py`
的落点理由）。受保护子集取自唯一事实源 `scripts/ci/protected_tests.txt`，
不另建第二套文件清单。

为什么"计数"不够、要按文件给结论：口径是**按文件**定的——同一文件里既有判分面的
CPU 计时、也可能有超时面的墙钟计时，按命中数登记会随无关改动漂红。
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = REPO_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 进程内计时口径的两种时钟。**刻意不含** `time.time`：它是"当前时刻"
#: （时间戳/过期时间），本仓已有守卫按 `perf_counter` 一类函数名取证。
CLOCK_PATTERNS = {
    "threadCpu": re.compile(r"\bthread_time\b"),
    "wallClock": re.compile(r"\b(perf_counter|monotonic|time_ns)\b"),
}

#: 逐条结论台账：键 = 受保护子集相对路径，值 = (用到的时钟, 结论)。
#: 结论文本必须点名"这份文件量什么、为什么这个口径"。
CLOCK_LEDGER: Dict[str, tuple] = {
    "tests/performance/test_perf_gate_contract.py": (
        ("threadCpu", "wallClock"),
        "门禁自检套件：判分面的取数口（measureThreadCpu）必须走本线程 CPU 时钟，"
        "「等待不进判分」正是这套件在守的契约；墙钟只出现在两处——冷 import 探针"
        "（量「用户为首轮对话实际等了多久」，属可留墙钟的命中点，由 "
        "TestImportBudgetKeepsWallClock 单独钉住），以及 threadTimeQuantumMs 里给"
        "「实测时钟推进粒度」封顶（§6-96）：那一处读的正是墙上过了多久，"
        "不进任何判值。判分时钟被换回墙钟时，本套件实测 7 条转红（2026-09-25 变异自证）。",
    ),
    "tests/unit/ci/test_subQuantumSpinClockGate.py": (
        ("threadCpu",),
        "本守卫自身：thread_time 字样全在**被检对象**里——AST 检出器认的就是这个符号，"
        "加上跳过理由文本要复述实测粒度。它自己不测时钟：粒度取自契约模块的 "
        "CPU_QUANTUM_MS 现值（import 那一侧才量一次），本文件无任何计时读数。",
    ),
    "tests/unit/agent/test_post_chat_p0_latency_observability.py": (
        ("wallClock",),
        "对照组的**下界**：关掉后台化后必须串行付 11 步 × STEP_DELAY 的等待，"
        "断言 `elapsed >= 11 * self.STEP_DELAY`。延迟在被测生产代码里真睡了，"
        "墙钟是唯一能读到它的口径；且是下界——负载只会让它更成立，不会把 CI 判红。"
        "该文件曾经的墙钟**上界**（响应路径不付旁路代价）已改为结构不变量，"
        "见 test_ci_wallclock_assertion_ledger.CONVERTED_TO_INVARIANT。",
    ),
    "tests/unit/tools/test_tool_elapsed_clock_is_monotonic.py": (
        ("wallClock",),
        "这份文件**自己不计时**：perf_counter / monotonic 两个词只出现在两处——"
        "被 AST 扫描的生产源码里的时钟名单常量，以及它断言的判据文本里。"
        "它守的是反向口径：咽喉喂给轮级耗时聚合的时长绑定**必须**是单调系，"
        "出现 time.time() 差值即判红（Windows 墙钟 15.6ms 粒度会把快工具量成假的 0.0，"
        "见工单集 §34）。台账口径按扫描结果记 wallClock，是因为扫描只认单调系符号名。",
    ),
    "tests/unit/security/test_tool_circuit_breaker.py": (
        ("wallClock",),
        "唯一一处单调钟是**轮询换状态**，不是量时长：半开恢复的 `recovery_timeout=0.05` "
        "在 Windows 上 `time.sleep` 粒度会短于请求值，故用 "
        "`deadline = time.monotonic() + 1.0` 轮 `get_state().value == \"half_open\"`，"
        "断言的是**状态迁移**（closed→open→half_open→closed）而非任何耗时上下界。"
        "1.0s 是轮询的上限护栏（到点就断言失败），负载再高也只会让它如实红，"
        "不会把结构契约编码成墙钟阈值——与本台账 WALLCLOCK 上界那一族不同形态。",
    ),
    "tests/unit/context/test_context_pool_retention_contract.py": (
        ("wallClock",),
        "同机 A/B **比值**：同一进程内先量池规模小的尾段 1000 条 add，再量池规模"
        "大的同一段，断言 `late < early * 8`。契约是「回收成本不随常驻规模劣化」，"
        "两侧共享同一份同机负载，比值比绝对值稳；结构面另由候选/索引规模断言"
        "（resident_count / archived_by_reason）钉住，退化为整表重建时它先咬合。",
    ),
    "tests/unit/context/test_ledger_write_batching.py": (
        ("wallClock",),
        "唯一在册的墙钟上界命中点（WALLCLOCK_LEDGER 同一份结论）：A2 的倍数本身是"
        "机时契约（同机同存量的一轮批量写 vs 逐行写的比值，阈值 3×），两侧已预热、"
        "取 3 轮中位，实测 135–427× 有 45× 以上裕量；结构面由"
        "test_round_uses_one_connection_and_one_transaction 钉住（0 次新建连接 + "
        "1 次 BEGIN + 1 次 COMMIT）。",
    ),
    "tests/unit/cognitive/test_workingMemoryAugmenterBehaviour.py": (
        ("wallClock",),
        "单调钟在这里是**轮询的护栏**，不是量时长：`_pastTick()` 等的是 `time.time()` "
        "自己前进一格——本机那个读数的粒度不是 1µs，同一 tick 内写两条会让 "
        "`last_accessed` 并列，于是淘汰序与 `get_recent` 的排序断言退化成按插入序断"
        "（§6-162 记过的那枚形态）。`time.monotonic() + 1.0` 只是「到点就如实红」的上限，"
        "断言的是访问顺序与容量行为，不编码任何耗时上下界；负载再高只会让它自己报"
        "「本机读数一秒内没前进」，不会假绿。",
    ),
    "tests/unit/ci/test_clock_caliber_ledger.py": (
        ("threadCpu", "wallClock"),
        "本守卫自身：CLOCK_PATTERNS 的正则字样（thread_time / perf_counter）与被检样例"
        "都出现在源码文本里，用于检出器反向控制，不参与任何计时读数。",
    ),
    "tests/unit/test_ci_wallclock_assertion_ledger.py": (
        ("wallClock",),
        "本守卫自身：它按语法树**检出**墙钟上界并比对台账，脚本里出现的 perf_counter "
        "字样是被检对象（用于构造检出器反向控制的样例），不参与任何计时读数。",
    ),
    "tests/unit/skills/test_marketFetchBudgetIsSingleSource.py": (
        ("wallClock",),
        "本文件**不读真实墙钟**——`monotonic` 字样只出现在两处：本格自造的虚拟钟 "
        "`VirtualTime.monotonic()`（被测代码经 `H.time.monotonic()` 取的就是它），以及这条结论本身。"
        "量的是「重试被总预算掐停在第几次」与虚拟钟推进量，都是精确值，与机器负载无关。"
        "§6-198 建档时这格读的是真实 `time.monotonic()` 差值并断上界 `elapsed < 1.5`——"
        "注入的 0.2s 延迟在加压机器上会漂，那正是本门要逐条给结论的形态；"
        "§6-230 改判为虚拟钟驱动（同 §6-96/§6-216 那一族的处理方向）。",
    ),
}


def protectedFiles() -> List[str]:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    return [
        line.split("#", 1)[0].strip()
        for line in io.open(PROTECTED, encoding="utf-8").read().splitlines()
        if line.split("#", 1)[0].strip()
    ]


def test_listFaceIsNotEmptyAndResolvable():
    """反空转：本档以那份清单为扫描面，先证清单本身在场——两条都要，缺一条就是半张嘴。

    清单被截短 ⇒ `_scan()` 少跑几圈 ⇒ `hits` 变小 ⇒「超出白名单的落点」读数照样空；
    而只比条目数量级又挡不住**路径写错**那一形——那种情况下每条都走 `continue`，
    数量级却仍然好看。与面自证棘轮 `test_surfaceReadingIsNotVacuous` 同形（那边是本闸自己的清单）。
    """
    files = protectedFiles()
    assert len(files) > 500, f"受保护子集清单现读 {len(files)} 条，量级不对＝没读到／路径写错"
    resolved = sum(1 for rel in files if (REPO_ROOT / rel).is_file())
    assert resolved == len(files), (
        f"清单里有 {len(files) - resolved} 条指不到真实文件——本档的逐条扫描会一起缩水而判据照样绿")


def clockCalibersOf(source: str) -> frozenset:
    return frozenset(
        name for name, pattern in CLOCK_PATTERNS.items() if pattern.search(source)
    )


def _scan() -> Dict[str, frozenset]:
    hits: Dict[str, frozenset] = {}
    for rel in protectedFiles():
        path = REPO_ROOT / rel
        if not path.is_file() or not rel.endswith(".py"):
            continue
        source = io.open(path, encoding="utf-8", errors="ignore").read()
        calibers = clockCalibersOf(source)
        if calibers:
            hits[rel] = calibers
    return hits


class TestProcessClockCalibersAreLedgered:
    """受保护子集里的进程内计时口径逐条有结论。"""

    def test_no_unledgered_process_clock(self):
        hits = _scan()
        unregistered = sorted(set(hits) - set(CLOCK_LEDGER))
        assert unregistered == [], (
            "受保护子集里出现未登记的进程内计时口径（必须逐条给结论："
            "量的是 CPU 还是墙钟、为什么）:\n  "
            + "\n  ".join(f"{key} → {sorted(hits[key])}" for key in unregistered)
        )

    def test_ledger_calibers_match_live_usage(self):
        """登记的时钟必须与实测一致——口径换了就得重新给结论。"""
        hits = _scan()
        drifted = []
        for key, (calibers, _reason) in CLOCK_LEDGER.items():
            live = hits.get(key, frozenset())
            if set(calibers) != set(live):
                drifted.append(f"{key}: 登记 {sorted(calibers)}，实测 {sorted(live)}")
        assert drifted == [], "计时口径台账与实测不一致:\n  " + "\n  ".join(drifted)

    def test_ledger_has_no_stale_entries(self):
        """台账里不得有已离开受保护子集的文件（搬走了要同步销账）。"""
        hits = _scan()
        stale = [key for key in CLOCK_LEDGER if key not in hits]
        assert stale == [], f"台账登记了不再计时的文件：{stale}"


class TestCaliberShiftIsCaught:
    """反向控制：把一批判据从"本线程 CPU"改回"墙钟"，本守卫必须转红。

    这就是本仓两次 CI 红各自的形态（判分时钟被换回墙钟、等待注入经内核态
    换算成 CPU 读数）。测试里只做**判据口径**的文本改写，不跑真实计时，
    故与机器负载无关。
    """

    def test_caliber_shift_makes_the_guard_red(self):
        source = (
            "import time\n"
            "def test_x():\n"
            "    start = time.thread_time()\n"
            "    return time.thread_time() - start\n"
        )
        assert clockCalibersOf(source) == frozenset({"threadCpu"}), (
            "检出器对本线程 CPU 计时零命中——本守卫会空转"
        )
        shifted = source.replace("thread_time", "perf_counter")
        assert clockCalibersOf(shifted) == frozenset({"wallClock"}), (
            "把口径换回墙钟后检出器读数不变——改一处写法即可绕过本守卫"
        )
