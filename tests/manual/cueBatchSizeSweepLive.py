"""活体：联想线索生成的批量 N 该怎么定（TM-2b 后续，工单 §4.2）

跑法（仓库根）：
    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe \\
        tests/manual/cueBatchSizeSweepLive.py

问三件事，逐件给读数，并**先说清哪半件今天量不了**：

  ① 成本与爆炸半径——精确、无需模型。按生产模板 `buildCueGenerationPrompt` 与生产
     token 估算器算：调用次数、单次/整轮提示 token、一次失败要重问多少行。
  ② 去重窗口的**结构性事实**——`filterModelCues` 的 `usedNormKeys` 只在一次调用内有效，
     所以「同一条泛词被不同记忆复用」的挡与放**取决于 N**。这是读代码就能定的事，
     不依赖任何模型；本脚本另配一格**标注为设定分布**的漏网曲线（不是模型质量测量）。
  ③ 真模型侧——泛词率、key 错位率、超时率、以及端到端 hit@5/MRR 随 N 的变化。
     **本机没配任何模型端点时这一半直接跳过并点名缺什么**，不拿设定分布冒充测量。

判绿口径：① ② 是应当一直成立的事实读数；③ 只有在真端点在时才产读数。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
# 本档字面里有本机编码编不出的字符：不钉住，`print` 抛 UnicodeEncodeError 会让退出码变 1，
# 而活体档的证据就是「退出码 + 读数」——那会读成「有一条腿 FAIL」，查的是坏掉的对象。
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot()

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 本机编码编不出的字符不许把退出码变成 1

sys.stderr.reconfigure(encoding="utf-8", errors="replace")


from neurova.context.token_estimator import estimate_tokens as estimate_text_tokens  # noqa: E402
from neurova.cognitive_layers.memory_layer import association_cue_generation as gen  # noqa: E402

CANDIDATE_NS = (5, 10, 15, 25, 40)

DOMAINS = ["项目排期", "家庭事务", "代码评审", "差旅安排", "健康与用药", "孩子教育",
           "设备与预算", "客户关系", "饮食偏好", "学习与读书", "健身与体检", "保险与账单"]
FREQUENCIES = ["每周", "每月末", "下周三", "这个季度", "每次出差", "每两周"]
TICKERS = ["已经确认过", "还没定", "上次出过问题", "需要提醒我", "我比较在意"]


def buildCorpus(rows: int = 200) -> list:
    """长度分布贴近真实会话记忆的一行式条目（合成语料，用途是量 token 与调用数）。"""
    corpus = []
    for i in range(rows):
        domain = DOMAINS[i % len(DOMAINS)]
        freq = FREQUENCIES[i % len(FREQUENCIES)]
        who = ["张三", "李四", "市场部", "家里", "设备组", "学校"][i % 6]
        ticker = TICKERS[i % len(TICKERS)]
        corpus.append({
            "index": i,
            "memory_id": f"m{i}",
            "content": (
                f"用户: 关于{domain}，我{freq}会按{['A','B','C'][i % 3]}方案处理，"
                f"涉及到{who}，另外{ticker}（编号{i}）"
            ),
        })
    return corpus


def partOneCost(corpus: list) -> None:
    print("== ① 成本与爆炸半径（精确；整轮＝全量清扫 200 行）==")
    print(f"{'N':>4} {'调用次数':>8} {'单次提示token':>13} {'整轮提示token':>12} "
          f"{'输出上界token':>12} {'一次失败重问行数':>16}")
    for N in CANDIDATE_NS:
        batches = [corpus[i:i + N] for i in range(0, len(corpus), N)]
        perCall = [estimate_text_tokens(gen.buildCueGenerationPrompt(b)) for b in batches]
        # 输出上界按契约算：每行≤3 条、每条≤12 字 + JSON 骨架
        outUpper = sum(
            estimate_text_tokens(json.dumps(
                {"cues": [{"key": idx, "text": f"线索十二字上限ABCDEFGH{idx}"}] * 3},
                ensure_ascii=False,
            ))
            for batch in batches for idx in range(len(batch))
        )
        print(f"{N:>4} {len(batches):>8} {sum(perCall) / len(perCall):>13.0f} "
              f"{sum(perCall):>12} {outUpper:>12} {N:>16}")


def cuePoolWithGenericRate(batch: list, genericRate: float = 0.35) -> list:
    """**设定分布**的线索池：泛词按给定比率跨行重复。只用于量窗口漏网的形状，
    不是模型输出——真模型侧要 ③ 才有数。"""
    generic = ["时间安排", "需要注意的事项", "工作相关", "日常事务", "与他人的约定", "后续跟进"]
    pool = []
    for pos, row in enumerate(batch):
        for c in range(3):
            if (pos * 3 + c) % 100 < genericRate * 100:
                text = generic[(pos + c) % len(generic)]
            else:
                text = f"{row['content'][3:11]}的处理场合{pos}{c}"
            pool.append({"index": pos, "text": text})
    return pool


def partTwoWindowLeak(corpus: list) -> None:
    print()
    print("== ② 去重窗口＝批大小（结构事实；漏网曲线为**设定分布**，非模型测量）==")
    import inspect

    src = inspect.getsource(gen.filterModelCues)
    print(f"  代码事实：usedNormKeys 在函数体内新建 ⇒ 去重只在一次调用内有效 → "
          f"{'成立' if 'usedNormKeys: set = set()' in src.replace('    ', '') else '不成立'}")
    print(f"{'N':>4} {'放行条数':>9} {'其中泛词':>8} {'泛词占放行比':>12}")
    generic = {"时间安排", "需要注意的事项", "工作相关", "日常事务", "与他人的约定", "后续跟进"}
    for N in CANDIDATE_NS:
        passed = leaked = 0
        for i in range(0, len(corpus), N):
            batch = corpus[i:i + N]
            kept, _dropped = gen.filterModelCues(cuePoolWithGenericRate(batch), batch)
            for cues in kept.values():
                for cue in cues:
                    passed += 1
                    leaked += cue["cue_text"] in generic
        print(f"{N:>4} {passed:>9} {leaked:>8} {leaked / max(1, passed) * 100:>11.1f}%")


def _tryRealClient():
    """只有配上真端点才返回客户端；否则点名缺什么。"""
    if os.environ.get("NEUROVA_CUE_SWEEP_BASE_URL") and os.environ.get("NEUROVA_CUE_SWEEP_API_KEY"):
        from neurova.llm_client import LLMClient  # 生产客户端装配点

        return LLMClient()
    return None


def partThreeModelSide(corpus: list) -> None:
    print()
    print("== ③ 真模型侧（泛词率/key 错位/超时率/端到端 hit@5-MRR 随 N 的变化）==")
    client = _tryRealClient()
    if client is None:
        print("  跳过：本机未配模型端点。要补这一半，设 "
              "NEUROVA_CUE_SWEEP_BASE_URL + NEUROVA_CUE_SWEEP_API_KEY 后重跑本脚本；"
              "**不许**用 ② 的设定分布冒充这一半的读数。")
        return

    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    for N in CANDIDATE_NS:
        sweepDir = os.path.join(tempfile.mkdtemp(), f"sweep_{N}.db")
        manager = MemoryManager(db_path=sweepDir,
                                agent_id=f"sweep_{N}", enable_buffer=False)
        try:
            for row in corpus:
                manager.remember(content=row["content"], memory_type="episodic",
                                 metadata={"chat_scope": "direct"})
            started = time.perf_counter()
            readout = _run(manager, client, N)
            print(f"  N={N:>3} 用时={time.perf_counter() - started:6.1f}s "
                  f"written={readout['written']:>4} 泛词挡下={readout['droppedGeneric']:>4} "
                  f"失败={readout['failed']} 超时={readout['timedOut']}")
        finally:
            manager.close()
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(sweepDir + suffix):
                    os.remove(sweepDir + suffix)


def _run(manager, client, N):
    import asyncio

    return asyncio.run(manager.generateModelAssociationCues(client=client, batchRows=N))


def main() -> int:
    corpus = buildCorpus()
    partOneCost(corpus)
    partTwoWindowLeak(corpus)
    partThreeModelSide(corpus)
    print()
    print("结论口径：① 精确、② 是代码事实＋设定分布曲线、③ 缺端点即未测。"
          "N 的最终值须等 ③——在此之前它是**成本参数**，不是质量参数（去重窗口那条应先改成与 N 解耦）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
