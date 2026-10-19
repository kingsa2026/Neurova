# -*- coding: utf-8 -*-
"""企业微信入站语音：平台已转写的文本要进得来，没有的不得被编出来（§6-184 批 25 · 缺口①）。

复核实状（逐处自己命中）：
- **活路只有一条**：`channels/wecom.py:handle_callback`（由 `api/endpoints/channels.py` 的 wecom 支
  委托进来，验签在 `:182-188` 已 fail-closed）。它此前只读 `MsgType` 与 `Content` ⇒ 语音消息的
  正文恒为空串（企业微信把语音的转写文本放在 `<Recognition>`、素材引用放在 `<MediaId>`），
  用户发一条语音进回合等于什么都没说。
- **另一份同族解析在死路上**：`channels/wechat_message.py` 早就写了 voice 的映射
  （`content = data.get("Recognition")`），但它经 `wechat_parsing.py`/`wechat_message.py` 出的是
  `UnifiedMessage`/裸 dict 那一族——§6-170 与本档第三格现量：`parse_raw_message` 在全仓
  **只有定义没有调用**（除 telegram 自己文件内那一处）。**在死路上补另一半会把"形状没接"
  洗成"看着已修"**，所以本批不动它，只把活那条补上；两份并存按 §6-170 同一口径登记为退役候选。
- **协议事实不需要往外找**：`Recognition`/`MediaId` 两个字段名在仓内那份映射里就是这么写的，
  本批按它取，不另猜第三种形状。

刻意没做的一件事（写了就有人当已做）：**`MediaId` → 音频字节这条仍没接**。按"断链结论不能在链路
第一个文件收尾"复算过两跳：`WeComAdapter(ChannelAdapter)`（`wecom.py:49`）不带媒体 mixin，
`download_media`/`_download_wecom_media` 在 `WeChatMediaMixin` 上、且它要
`self.adapter._ensure_wecom_token()`——那个 token 方法只属于 `WeChatAdapter`（`wechat.py:38`），
`wecom.py` 里没有。要接就得先把下载器抽成两处共用的单源、再把阻塞取回挪出事件循环
（`handle_callback` 是同步的且在循环线程上投事件）。那是另一次改动，本批不做，也**不因此往
metadata 里塞一个没人读的 `wecom_media_id`**（§2「只写不读即断点」）。
"""

import ast
import asyncio
import pathlib
import re
import threading
import time

REPO = pathlib.Path(__file__).resolve().parents[3]
NEUROVA = REPO / "neurova"

from tests import ast_scan  # noqa: E402  (仓根在 sys.path 上，见 tests/conftest.py)

from neurova.channels.voice_ingress import (  # noqa: E402
    AUDIO_BYTES_KEY,
    INBOUND_VOICE_PLACEHOLDER,
)
from neurova.channels.wecom import WeComAdapter, _wecom_callback_signature  # noqa: E402

CALLBACK_TOKEN = "wecom-callback-token-for-tests"

#: 本批动过的入站活路——它们只许从 `voice_ingress` 取占位串，绝不许进下面的豁免清单。
_LIVE_INBOUND_FILES = {
    "neurova/channels/wecom.py",
    "neurova/channels/wechat_ilink.py",
    "neurova/channels/wecom_aibot.py",
}

#: 仍带第二份占位串的字面路径，逐条给"为什么可以留着"：它们都够不到生产（本档第三格自己数）。
#: 值是**入口符号名**清单（判定单位是符号不是文件——同一文件半区死半区活），`"__module__"` 表示
#: 整档无人 import。豁免清单一旦过期（死路被接活），第三格立刻红。
_DEAD_ROAD_EXEMPT: dict = {
    "neurova/channels/feishu_message.py": ("__module__",),
    "neurova/channels/telegram_parser.py": ("parse_raw_message", "receive_message"),
    "neurova/channels/wechat_parsing.py": ("parse_raw_message", "receive_message"),
}


def _importersOf(ownerPath: pathlib.Path) -> list:
    """`neurova/` 内**文本里出现 import 那档模块**的文件（排除自身）。

    取数（枚举 + 不剪枝的文本面）走唯一 AST 入口 `tests/ast_scan`：受保护子集里的
    跨文件判据不得各写一套 `rglob`（Issue #148 / #197，本仓 `test_ci_ast_scan_budget_guard`
    逐条咬合）。判定仍是"某三行里出现 `from/import <模块名>`"这一**行级证据**
    （报错要能点名那一行，故不换成 AST 命中点）；`hints` 用模块名本身——
    判据只可能命中文本里出现过该词的文件，是充分条件，不放松覆盖面。
    读的仍是**未剪枝**的全量文本清单（`sourceRefsUnder` 只剪第三方/产物目录）。
    """
    return [
        ref.path for ref in ast_scan.sourceRefsUnder(NEUROVA, hints=(ownerPath.stem,))
        if ref.path != ownerPath
        and re.search(rf"^\s*(from|import)\s.*\b{re.escape(ownerPath.stem)}\b",
                      ref.code, re.M)
    ]


def _callSitesIn(candidatePaths: list, name: str) -> list:
    """候选文件里对该符号的**调用形状**读数；`def NAME(` 是定义不是消费，不计。"""
    shape = re.compile(rf"(?:self|adapter)\.{re.escape(name)}\(")
    hits = []
    for path in candidatePaths:
        for line in ast_scan.sourceCode(path).splitlines():
            if shape.search(line) and not line.strip().startswith("def "):
                hits.append(f"{path.name}: {line.strip()[:80]}")
    return hits


def _adapter() -> WeComAdapter:
    from neurova.channels.base import ChannelConfig

    adapter = WeComAdapter(ChannelConfig(channel_type="wecom", app_id="ww_corp", app_secret="sec"))
    adapter._callback_token = CALLBACK_TOKEN
    return adapter


def _signed(xml: str, timestamp: str = "1700000000", nonce: str = "n1") -> str:
    """明文模式（无 `<Encrypt>`）下的签名，直接用仓内那份公式——不重写第二份。"""
    return _wecom_callback_signature(CALLBACK_TOKEN, timestamp, nonce, "")


def _deliver(adapter: WeComAdapter, xml: str, sink: list) -> None:
    """喂一条真回调进 `handle_callback`，捕获它投出来的消息。

    `handle_callback` 是同步的、靠 `run_coroutine_threadsafe` 把 `_emit_event` 投到主 loop，
    所以要一个真在跑的后台循环——否则走的是"主循环未运行，丢弃消息"那条 warn 分支，
    读到的 0 条是夹具没驱动，不是链路坏了（§6-168 记过那一形）。
    """
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    while not loop.is_running():
        time.sleep(0.01)

    async def _record(_eventType, message):
        sink.append(message)

    adapter._main_loop = loop
    adapter._event_callback = _record
    adapter.handle_callback(_signed(xml), "1700000000", "n1", xml)
    for _ in range(120):
        if sink:
            break
        time.sleep(0.02)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)


def _xml(msgType: str, extra: str) -> str:
    return ("<xml><ToUserName><![CDATA[ww_corp]]></ToUserName>"
            "<FromUserName><![CDATA[manager_user_1]]></FromUserName>"
            "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[%s]]></MsgType>%s"
            "<MsgId>42</MsgId><AgentID>100</AgentID></xml>" % (msgType, extra))


class TestVoiceCarriesThePlatformsTranscript:
    def testVoiceWithRecognitionBecomesTheTurnText(self):
        sink: list = []
        _deliver(_adapter(), _xml("voice", "<Recognition><![CDATA[明天天气怎么样]]></Recognition>"
                                   "<MediaId><![CDATA[MEDIAVOICE_1]]></MediaId>"), sink)

        assert sink, "语音回调根本没投出消息"
        msg = sink[0]
        assert msg.content == "明天天气怎么样", f"平台已转写的文本没进正文：{msg.content!r}"
        assert msg.message_type == "voice", f"类型被改写：{msg.message_type!r}"

    def testVoiceWithoutRecognitionFallsBackToTheSharedPlaceholder(self):
        """没带 Recognition 时不得交空串——空正文进回合等于用户说了句不存在的话。"""
        sink: list = []
        _deliver(_adapter(), _xml("voice", "<MediaId><![CDATA[MEDIAVOICE_2]]></MediaId>"), sink)

        assert sink, "语音回调没投出消息"
        assert sink[0].content == INBOUND_VOICE_PLACEHOLDER, (
            f"空转写时没退回共享占位（实得 {sink[0].content!r}）")

    def testNoAudioBytesAreFabricated(self):
        """仓内没这条素材下载路 ⇒ 绝不在 metadata 里凭空写一个 audio_bytes，
        也不塞一个没人读的 media_id（那只写不读正是本仓一路在登记的断点）。"""
        sink: list = []
        _deliver(_adapter(), _xml("voice", "<Recognition><![CDATA[你好]]></Recognition>"
                                   "<MediaId><![CDATA[M3]]></MediaId>"), sink)

        assert sink
        meta = sink[0].metadata or {}
        assert AUDIO_BYTES_KEY not in meta, "凭空写了音频字节键——预检会拿它去转写不存在的数据"
        assert not [k for k in meta if "media" in k.lower()], (
            f"塞了没人读的媒体引用字段：{sorted(k for k in meta if 'media' in k.lower())}")

    def testTextTurnIsUntouched(self):
        sink: list = []
        _deliver(_adapter(), _xml("text", "<Content><![CDATA[普通文字]]></Content>"), sink)

        assert sink and sink[0].content == "普通文字" and sink[0].message_type == "text"


class TestThePlaceholderVocabularyStaysSingleSource:
    """占位串此前全仓有 8 处第二定义；本批把活路那 3 处收进 `voice_ingress`，死路那 5 档留名待退役。"""

    @staticmethod
    def _literalLines(src: str, needle: str) -> list:
        """只数**值恰为该占位串的字符串字面量**所在行（注释与长 docstring 里的提及不算第二份定义）。"""
        hits = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value == needle and node.lineno:
                hits.append(node.lineno)
        return hits

    def _scan(self) -> dict:
        """全仓只枚举一次、逐文件解析一次（取数收口到唯一 AST 入口）。

        口径与原来逐字相同：数的是**值恰为该占位串的字符串字面量**所在行号。
        改的只是取数：`rglob + ast.parse` 私有扫描正是 `test_ci_ast_scan_budget_guard`
        点名要红的形态（判据成本随代码总量涨），本判据只扫一次，故走一次性入口
        `transientNodes`（不留常驻语法树）。`hints` 是占位串本身——连它都没出现的
        文件不可能承载这份字面量，是充分条件。
        """
        found = {}
        # 预筛命中数不随根的大小变 ⇒ 证不了面；面另由共享枚举入口量一次（根＝生产源码）。
        surface = len(ast_scan.filesUnder(NEUROVA))
        assert surface > 500, (
            f"扫描面现读 {surface} 档 .py（根＝{NEUROVA}）——根被改窄时「占位串零命中」不代表干净")
        for path, node in ast_scan.transientNodes(
                NEUROVA, hints=(INBOUND_VOICE_PLACEHOLDER,)):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value == INBOUND_VOICE_PLACEHOLDER and node.lineno):
                continue
            found.setdefault(path.relative_to(REPO).as_posix(), []).append(node.lineno)
        return found

    def testOnlyTheSingleSourceAndRegisteredDeadRoadsCarryIt(self):
        found = self._scan()
        allowed = {"neurova/channels/voice_ingress.py"} | set(_DEAD_ROAD_EXEMPT)
        assert set(found) == allowed, (
            f"占位串的落点集合变了：多出的={sorted(set(found) - allowed)}，消失的={sorted(allowed - set(found))}"
            "（消失＝那一档已退役，同批把豁免删掉）")

    def testLiveInboundFilesAreNotInTheExemptionList(self):
        """豁免清单不许顺手把活路也包进去——否则上一格会因'把它当死路'而假绿。"""
        assert not (_LIVE_INBOUND_FILES & set(_DEAD_ROAD_EXEMPT)), (
            f"入站活路被登记成死路豁免：{sorted(_LIVE_INBOUND_FILES & set(_DEAD_ROAD_EXEMPT))}")
        found = self._scan()
        assert not [f for f in _LIVE_INBOUND_FILES if f in found], "活路自己写起了第二份占位串"

    def testEveryExemptionIsStillADeadRoad(self):
        """豁免的凭据是"这条路今天到不了生产"——按调用节点自己数，不采信任何注释或本档的措辞。

        三条口径都是本仓撞过的伪命中：① `def NAME(` 是定义不是消费；② 只按裸名扫会把**同名
        词不同物**算成消费者（第一版就在这里把 telegram 自己文件内的 `self.parse_raw_message()`
        记成了 `wechat_parsing` 那条路的消费者）——所以先把候选文件收在**真 import 了那档模块的
        文件**里，再在候选里数调用形状；③ 判定单位是符号不是文件，同一模块半区死半区活。
        """
        stillReferenced = []
        for relPath, entries in _DEAD_ROAD_EXEMPT.items():
            importers = _importersOf(REPO / relPath)
            if "__module__" in entries:
                if importers:
                    stillReferenced.append(
                        f"{relPath} 已被 {[p.name for p in importers]} import")
                continue
            for name in entries:
                for hit in _callSitesIn(importers, name):
                    stillReferenced.append(f"{relPath}::{name} — {hit}")
        assert stillReferenced == [], f"豁免过期——这些死路已被接活，占位串必须改取单源：{stillReferenced}"

    def testDeadRoadDetectorHasTeeth(self, tmp_path):
        """自证：死路真被接活时上面那格会红；定义形与中间对象同名都不算消费者。

        反空转的三形都取真形状：`self.NAME(` 是接活后的生产写法（必须抓到）；
        `def NAME(` 是定义（不该抓）；`self.other.NAME(` 是**同名词不同物**（第一版就在这上面假红过）。
        """
        def _probe(body):
            f = tmp_path / "importer_sim.py"
            f.write_text(body, encoding="utf-8")
            return _callSitesIn([f], "parse_raw_message")

        assert len(_probe("class C:\n    def go(self, upd):\n"
                          "        return self.parse_raw_message(upd)\n")) == 1, "接活形态没被抓到"
        assert _probe("class C:\n    def parse_raw_message(self, upd):\n        return 1\n") == []
        assert _probe("class C:\n    def go(self):\n"
                      "        return self.other.parse_raw_message(1)\n") == []

    def testDetectorHasTeeth(self):
        """自证：三种真形态都抓得到，注释与 docstring 里的提及抓不到（排除型断言在功能缺失时会自动成立）。"""
        needle = INBOUND_VOICE_PLACEHOLDER
        cases = {
            "赋值形": (f'content = "{needle}"\n', [1]),
            "函数内 return 形": (f'def _f():\n    return "{needle}"\n', [2]),
            "dict 字面量值形": (f'content = {{"voice": "{needle}"}}.get(t, "")\n', [1]),
            "注释形": (f"x = 1  # {needle}\n", []),
            "docstring 提及形": (f'"""说明里写了 {needle} 两个字。"""\n', []),
        }
        for label, (sample, expected) in cases.items():
            assert self._literalLines(sample, needle) == expected, f"{label} 的读数不是 {expected}"
