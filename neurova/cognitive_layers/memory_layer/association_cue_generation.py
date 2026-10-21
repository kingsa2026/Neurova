"""模型联想线索的**生成器**（TM-2b，批 C-2）

上游两块地基：批 A 的存储与作用域门（§6-382）、批 C-1 的向量通道（§6-384）。
本模块只补内容——批 A 的规则线索实测信息量近零（26 条只含 2 个不同归一键），
向量通道在生产上是暗的。用户裁丙：空闲窗口、段落级批量、**不设调用上限**。

提示词与规则是本仓按自己的实测拟的，不引外部项目的措辞（`AGENTS.md` §2）。
两条硬规则直接来自 C-1 的标定读数，落成代码里的过滤与计数，不留在注释里当愿望：
- **不复述原文**：与正文词面同集的线索零增益（词法刀切不出跨句重合，向量也一样）⇒ 挡掉；
- **泛词即串味**：误注入的主因是「别的记忆的线索更像」（目标线索余弦 0.465–0.612，
  其它记忆线索可达 0.687）⇒ 同一次生成里跨条目重复的线索只留第一份。

失败形态一律**留队**（不写库、不认领、下一轮重来）并在读数里可见——
「跑过了但什么都没发生」是本仓反复点名的静默形态。
"""

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

from neurova.cognitive_layers.memory_layer import association_cues

logger = get_logger(__name__)

#: 单次批量提示覆盖多少条记忆（段落级批量＝丙档的省法：一次调用干一批）。
BATCH_ROWS = 15

#: 每条记忆最多留几条线索。上限是**形态**约束（防一条记忆刷出一片泛词毒化倒排），
#: 不是调用预算——丙档放开的是预算。
CUES_PER_MEMORY = 3

#: 单批模型调用的墙钟上界。超时不写库、留队下一轮。
TIMEOUT_SECONDS = 25.0

#: 过短线索（<4 字）几乎必然是泛词或截断残片。
MIN_CUE_CHARS = 4

#: 生成侧总闸。形态沿用仓内 env 开关先例（`NEUROVA_AUTO_EFFORT` 等），
#: 与检索侧的 `NEUROVA_MEMORY_CUE_CHANNEL` 分两把——
#: 可以停生成而继续用已有线索，也可以两者都停。
ENV_MODEL_SWITCH = "NEUROVA_MEMORY_CUE_MODEL"

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def modelGenerationEnabled() -> bool:
    """生成侧开关，默认开（丙档＝全量生成）；显式 `off`/`0`/`false` 才关。"""
    value = (os.environ.get(ENV_MODEL_SWITCH) or "").strip().lower()
    return value not in ("off", "0", "false", "disabled")


def buildCueGenerationPrompt(rows: List[Dict[str, Any]]) -> str:
    """批量提示：一次给多行，要求逐行给「以后什么时候用得上」的检索线索。

    行序 `index` 是**批内序号**，模型按序号回指——比让模型复述原句更不容易串味，
    也比按内容匹配更省（不必把长原文再回抄一遍）。
    """
    listing = "\n".join(f"[{row['index']}] {row['content']}" for row in rows)
    return (
        "你是检索线索撰写员。下面每一行是用户过去说过的一句话（编号在方括号里）。\n"
        "请为每一行写至多 3 条**检索线索**：未来什么样的问法/场合会让这一行变得有用。\n"
        "线索只用来在将来检索时命中这一行，不会展示给用户，也不作为回答的内容依据。\n"
        "\n"
        "必须遵守：\n"
        "1. 线索要具体到只有这一行才成立。换个话题也说得通的泛词（如「饮食」「安排」「事情」）不要写。\n"
        "2. 不要把该行原文里的词原样搬进线索——那些词本来就检索得到，加了等于没有。\n"
        "3. 不同行之间不要使用同一条线索。\n"
        "4. 每条线索不超过 12 个字，写成名词短语，不要整句，不要加标点。\n"
        "5. 某一行确实写不出可信线索时就不要为它输出任何项，不要凑数——编造的线索比缺线索更坏。\n"
        "\n"
        "条目：\n"
        f"{listing}\n"
        "\n"
        '只输出 JSON，不要任何解释文字：{"cues": [{"key": <方括号里的编号>, "text": "<线索>"}]}\n'
    )


def parseCueResponse(text: str) -> Optional[List[Dict[str, Any]]]:
    """从模型输出取线索列表。取不到合法 JSON 结构即返回 None（调用方计一次失败）。

    只做**形状**校验，不做语义兜底——坏输出必须留在待处理面里重来，
    而不是被就地降级成半个答案。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    candidate = text.strip()
    if not candidate.startswith("{"):
        matched = _JSON_BLOCK.search(candidate)
        if not matched:
            return None
        candidate = matched.group(0)
    try:
        payload = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    cues = payload.get("cues")
    if not isinstance(cues, list):
        return None
    normalized: List[Dict[str, Any]] = []
    for entry in cues:
        if not isinstance(entry, dict):
            continue
        textCue = str(entry.get("text") or "").strip()
        try:
            index = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        if not textCue:
            continue
        normalized.append({"index": index, "text": textCue})
    return normalized


def filterModelCues(
    parsed: List[Dict[str, Any]],
    rows: List[Dict[str, Any]],
) -> Tuple[Dict[int, List[Dict[str, Any]]], int]:
    """按 C-1 的两条实测规则过滤，返回 `{批内序号: [线索]}` 与被挡计数。"""
    contentTokens: Dict[int, set] = {
        row["index"]: set(association_cues.cueTokens(row["content"])) for row in rows
    }
    contentNormalized: Dict[int, str] = {
        row["index"]: association_cues.normalizeCueText(row["content"]) for row in rows
    }

    keptByIndex: Dict[int, List[Dict[str, Any]]] = {}
    usedNormKeys: set = set()
    dropped = 0
    for item in parsed:
        index = item["index"]
        cueText = item["text"]
        if index not in contentTokens:
            dropped += 1
            continue
        if len(cueText) < MIN_CUE_CHARS:
            dropped += 1
            continue
        normKey = association_cues.cueNormKey(cueText)
        if normKey in usedNormKeys:
            # 规则 3：跨条目复用同词——留第一份，其余挡掉
            dropped += 1
            continue
        cueTokenSet = set(association_cues.cueTokens(cueText))
        if cueTokenSet and cueTokenSet <= contentTokens[index]:
            # 规则 1：词面全在原文里，检索上零增益
            dropped += 1
            continue
        if association_cues.normalizeCueText(cueText) in contentNormalized[index]:
            dropped += 1
            continue
        usedNormKeys.add(normKey)
        bucket = keptByIndex.setdefault(index, [])
        if len(bucket) >= CUES_PER_MEMORY:
            continue
        bucket.append(
            {
                "cue_text": cueText,
                "cue_kind": "situation",
                "cue_source": "model",
                "confidence": 0.7,
                "norm_key": normKey,
            }
        )
    return keptByIndex, dropped


async def runGeneration(
    pendingRows: List[Dict[str, Any]],
    client: Any,
    writeCues,
    recordAttempt,
    batchRows: int = BATCH_ROWS,
    timeoutSeconds: float = TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """整轮生成。

    - `writeCues(memoryId, cues)`：落库并返回实际写入条数。
    - `recordAttempt(memoryId, cuesWritten)`：**调用成功**就要记，包括模型一条线索
      都没给的情况。这是丙档的护栏——不设每轮上限，就必须保证「一轮真的做完」，
      否则被模型正当拒答的行会在每个空闲窗口被重问一遍，把「无上限」变成无界烧钱。
      失败/超时/坏 JSON 一律不记，那些行自然留在下一轮。
    """
    readout: Dict[str, Any] = {
        "scanned": len(pendingRows),
        "calls": 0,
        "written": 0,
        "droppedGeneric": 0,
        "failed": 0,
        "timedOut": 0,
        "errors": [],
    }

    for start in range(0, len(pendingRows), batchRows):
        batch = pendingRows[start : start + batchRows]
        prompt = buildCueGenerationPrompt(batch)
        readout["calls"] += 1
        try:
            response = await asyncio.wait_for(client.generate(prompt), timeout=timeoutSeconds)
        except asyncio.TimeoutError:
            readout["timedOut"] += 1
            readout["errors"].append(f"batch@{start}: timeout>{timeoutSeconds}s")
            logger.warning("联想线索生成超时（批 %d 行，留队下轮）", len(batch))
            continue
        except Exception as exc:  # noqa: BLE001 - 网络/服务侧失败：留队，不吞
            readout["failed"] += 1
            readout["errors"].append(f"batch@{start}: {type(exc).__name__}: {exc}")
            logger.warning("联想线索生成调用失败（批 %d 行，留队下轮）: %s", len(batch), exc)
            continue

        parsed = parseCueResponse(response if isinstance(response, str) else str(response))
        if parsed is None:
            readout["failed"] += 1
            readout["errors"].append(f"batch@{start}: 输出非合法 JSON 结构")
            logger.warning("联想线索生成输出不可解析（批 %d 行，留队下轮）", len(batch))
            continue

        kept, dropped = filterModelCues(parsed, batch)
        readout["droppedGeneric"] += dropped
        for row in batch:
            cues = kept.get(row["index"], [])
            if cues:
                readout["written"] += writeCues(row["memory_id"], cues)
            recordAttempt(row["memory_id"], len(cues))

    return readout
