"""AgentRun 状态词汇与读面字段的跨语言对齐守卫（§6-72 第五格）。

`NeurUI/src/pages/ChatPage.vue` 的挂起续跑入口按 `status === 'parked'` 挑行、
按 `run_id` / `park_reason` 取凭据。这三处都是**字符串字面量**：后端改了常量名
或读面少投一个字段，前端不会报错，只会让"续跑"按钮静默不再出现——
本仓反复登记的正是这类假绿失效形态。这里把两侧钉在一起：

1. 前端比较用的状态字面量，必须是 `agent_run_store` 那份词汇表的成员（反向不要求，
   前端本就不需要展示全部状态）；
2. 读面 `/console/chat/runs` 必须把前端读的这三个字段都投出来。

口径单源在 `neurova/core/agent_run_store.py`（教义第 6 条），本判据不新建第二份枚举。
"""

import re
from pathlib import Path

from neurova.core import agent_run_store as ars

_REPO = Path(__file__).resolve().parents[3]
_CHAT_PAGE = _REPO / "NeurUI" / "src" / "pages" / "ChatPage.vue"
_CONSOLE = _REPO / "neurova" / "api" / "endpoints" / "console.py"

# 前端在 run 读面上读的三个键（改这里要同时改消费方，不是改后端就行）
_FRONTEND_KEYS = ("run_id", "status", "park_reason")


def _runVocabulary() -> set:
    return set(ars.TERMINAL_STATUSES) | set(ars.NON_TERMINAL_STATUSES)


def _statusLiteralsUsedByFrontend() -> set:
    source = _CHAT_PAGE.read_text(encoding="utf-8")
    # 只收 run 状态那一族的比较式（`?.status === 'x'`）；HTTP 状态码、设备状态等
    # 不带 `?.` 前缀，不会误收进来
    return set(re.findall(r"\?\.status\s*[=!]==?\s*'([a-z_]+)'", source))


def testFrontendStatusLiteralsAreInsideStoreVocabulary():
    used = _statusLiteralsUsedByFrontend()
    assert used, "前端一处 run 状态比较都没有——读面消费者大概已经没了，这条守卫会假绿"
    unknown = used - _runVocabulary()
    assert not unknown, (
        f"ChatPage 用了不在 AgentRun 词汇表里的状态 {sorted(unknown)}；"
        f"单源是 agent_run_store（现有词汇 {sorted(_runVocabulary())}），"
        "改名后前端按钮会静默不出现而不是报错"
    )


def testParkedReaderUsesTheParkedStatusConstant():
    """前端认挂起态用的字面量，必须等于后端 `PARKED_STATUS` 的现值。"""
    used = _statusLiteralsUsedByFrontend()
    assert ars.PARKED_STATUS in used, (
        f"ChatPage 不再比较 {ars.PARKED_STATUS!r}（现收 {sorted(used)}），"
        "挂起回合的读侧消费者等于被摘掉了"
    )


def testRunReadFaceProjectsEveryKeyTheFrontendReads():
    body = _runReadFaceSource()
    missing = [k for k in _FRONTEND_KEYS if f'"{k}"' not in body]
    assert not missing, (
        f"/console/chat/runs 的投影里少了 {missing}——前端按这些键取凭据，"
        "少一个就是'有挂起但拿不到 run_id'的静默缺席"
    )


def _runReadFaceSource() -> str:
    """取 `@router.get("/chat/runs")` 那一个处理函数的源码文本。"""
    source = _CONSOLE.read_text(encoding="utf-8")
    marker = '@router.get("/chat/runs")'
    start = source.index(marker)
    rest = source[start + len(marker):]
    nxt = re.search(r'^@router\.', rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest
