"""模型联想线索生成器（TM-2b 批 C-2）的行为判据 —— 先红

上游：批 A 落了线索的存储与作用域门（§6-382）、批 C-1 落了向量通道（§6-384）。
本批补**内容**——规则线索实测信息量近零（26 条只含 2 个不同归一键），
向量通道在生产线上是暗的；用户裁丙（空闲窗口段落级、不设调用上限）要的就是这一格。

三条从上一批实测里长出来的硬规则，本批全部做成判据而不是注释：
1. **不复述原文**：与正文词面同集的线索对召回零增益（词法刀切不出跨句重合，向量也一样），
   必须挡掉并计数。
2. **泛词即串味**：C-1 标定发现误注入的主因是「别的记忆的线索更像」（目标线索 0.465–0.612，
   其它记忆线索可达 0.687），所以提示词要线索**具体到只对该条成立**，
   生成侧要按记忆分组写、不得跨记忆复用同词。
3. **失败必须留队**：模型坏了/超时/坏 JSON 一律不写库、不认领，下一轮重来，
   且读数里能看见——不许出现「跑过了但什么都没发生」的静默形态。

测试**不打真模型**：用一个实现同一 `generate(prompt)` 协议的确定性假客户端，
从**生产装配点**（`manager.generateModelAssociationCues(client=...)`）递进去。
判据同时反证生产接线（`test_生产装配点把模型依赖递进来`），
免得长成「测试里自洽、生产上没人递客户端」的孤岛——本仓该形态有先例（§6-381 的
`proactive_question_manager` 恒 None 那条）。
"""

import asyncio
import io
import json
import os
import re

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

pytestmark = [pytest.mark.timeout(120)]

ROWS = [
    "用户: 我在吃虾之后起了荨麻疹，医生确认是对虾过敏",
    "用户: 我们组每个月末做代码评审，轮流主持",
    "用户: 我的孩子叫小豆，今年四岁，最近喜欢挖沙",
]


class FakeCueClient:
    """实现生产同款协议（`await client.generate(prompt) -> str`）的确定性假件。"""

    def __init__(self, responder=None, delay=None, raises=None):
        self.calls = 0
        self.prompts = []
        self._responder = responder
        self._delay = delay
        self._raises = raises

    async def generate(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self._raises is not None:
            raise self._raises
        if self._delay is not None:
            await asyncio.sleep(self._delay)
        if self._responder is not None:
            return self._responder(prompt)
        return json.dumps(
            {
                "cues": [
                    {"key": index, "text": text}
                    for index, text in enumerate(
                        ["海鲜类食材与点菜场合", "组内例行的时间安排", "学龄前孩子的周末去处"]
                    )
                ]
            },
            ensure_ascii=False,
        )


@pytest.fixture
def manager(tmp_path):
    from neurova.cognitive_layers.memory_layer.semantic_search import reset_semantic_search

    reset_semantic_search()
    mgr = MemoryManager(
        db_path=os.path.join(str(tmp_path), "mem.db"), agent_id="cue_gen_c2", enable_buffer=False
    )
    for content in ROWS:
        mgr.remember(content=content, memory_type="episodic", metadata={"chat_scope": "direct"})
    yield mgr
    mgr.close()
    reset_semantic_search()


class TestGenerationIsBatchedAndSweeping:
    def test_整批待处理行一次调用覆盖(self, manager):
        client = FakeCueClient()
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))

        assert readout["scanned"] == len(ROWS), f"扫描面不等于待处理面：{readout}"
        assert readout["calls"] == 1, (
            f"{len(ROWS)} 行应一次批量调用（丙档＝段落级批量），实为 {readout['calls']}"
        )
        assert readout["written"] > 0, f"没写进任何线索：{readout}"

    def test_不设每轮调用上限_丙档语义(self, manager):
        """用户裁的是「不设调用上限」——那就一轮必须把欠的行做完，
        不许偷偷留半截（留半截等于用一个隐式上限假装无上限）。"""
        many = [f"用户: 第 {i} 条要生成线索的往事，涉及不同的场所与物件编号{i}" for i in range(45)]
        for content in many:
            manager.remember(content=content, memory_type="episodic", metadata={"chat_scope": "direct"})

        client = FakeCueClient()
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))

        assert readout["scanned"] == len(many) + len(ROWS), (
            f"欠处理的行没被整轮覆盖：{readout}"
        )
        after = asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient()))
        assert after["scanned"] == 0, f"上一轮没做完，仍有 {after['scanned']} 行待处理"

    def test_二轮生成不重复写(self, manager):
        asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient()))
        first = manager.associationCueStats()
        asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient()))
        second = manager.associationCueStats()
        assert second["cues"] == first["cues"], f"重放使线索由 {first} 涨到 {second}"


class TestGeneratedCuesAreUsable:
    def test_生成的线索能被向量通道召回(self, manager):
        """端到端：生成 → 入库 → 通道点火 → 无词面重合的提问能捞出对应记忆。"""
        target = ROWS[0]
        query = "团队聚餐选餐厅时要注意什么"
        # 查询与目标零中文字面重合（前提自证，否则用例白给）
        chars = lambda t: {c for c in t if "一" <= c <= "鿿"}
        assert not (chars(target) & chars(query)), "用例前提失效"

        client = FakeCueClient(
            responder=lambda _p: json.dumps(
                {"cues": [{"key": 0, "text": "海鲜类食材的聚餐点菜场合"}]}, ensure_ascii=False
            )
        )
        asyncio.run(manager.generateModelAssociationCues(client=client))
        manager.invalidateAssociationCueIndex()

        stats = manager.associationCueChannelStats()
        assert stats.get("injected", 0) > 0 or manager.associationCueChannelCandidates(), (
            f"线索没进通道索引：{stats}"
        )
        hits = manager.recall(query=query, limit=5)
        assert any((h.get("content") or "") == target for h in hits), (
            f"「{query}」召回不到目标记忆；返回 {[(h.get('content') or '')[:18] for h in hits]}"
        )

    def test_复述原文的线索被挡并计数(self, manager):
        """与正文词面同集的线索零增益（C-1 实测），必须挡下来且**读数可见**。"""
        restatement = ROWS[0][3:]  # 直接抄正文
        client = FakeCueClient(
            responder=lambda _p: json.dumps({"cues": [{"key": 0, "text": restatement}]}, ensure_ascii=False)
        )
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert readout["droppedGeneric"] >= 1, f"复述型线索没被挡：{readout}"
        cues = manager.get_associationCues(
            next(m.id for m in manager._memories.values() if m.content == ROWS[0])
        )
        assert all(c["cue_text"] != restatement for c in cues), "复述线索仍写进了库"


class TestFailureModesAreHonest:
    def test_坏JSON不写库且下一轮重来(self, manager):
        before = manager.associationCueStats()
        client = FakeCueClient(responder=lambda _p: "这不是 JSON，模型今天心情不好")
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert readout["written"] == 0, f"坏 JSON 却写库了：{readout}"
        assert readout["failed"] >= 1, f"坏 JSON 没被计数：{readout}"
        assert manager.associationCueStats() == before, "线索表被坏输出污染"

        retry = asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient()))
        assert retry["scanned"] == len(ROWS), f"失败批次没留队重来：{retry}"

    def test_客户端抛错时留队(self, manager):
        client = FakeCueClient(raises=RuntimeError("连接被重置"))
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert readout["written"] == 0 and readout["failed"] >= 1, f"异常被吞：{readout}"
        assert readout["errors"], f"异常原因没进读数：{readout}"

    def test_超时留队不阻塞(self, manager):
        client = FakeCueClient(delay=5.0, responder=lambda _p: "{}")
        readout = asyncio.run(
            manager.generateModelAssociationCues(client=client, timeoutSeconds=0.2)
        )
        assert readout["timedOut"] >= 1, f"超时没被计数：{readout}"
        assert readout["written"] == 0, f"超时却写了库：{readout}"

    def test_关断后零调用(self, manager, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_CUE_MODEL", "off")
        client = FakeCueClient()
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert client.calls == 0, f"关断后仍调了模型 {client.calls} 次"
        assert readout["scanned"] == 0 and readout.get("skippedOff"), f"关断读数缺失：{readout}"

    def test_没有客户端时不报错(self, manager):
        readout = asyncio.run(manager.generateModelAssociationCues(client=None))
        assert readout["written"] == 0, f"无客户端却写了库：{readout}"


class TestCostGuardrailUnderOpenBudget:
    """用户裁的是丙＝**不设每轮调用上限**。无上限能成立的前提是「问过就封账」——
    提示词第 5 条明令不要凑数，所以「合法返回但一条线索都不给」是正当输出；
    这种行若不记账，就会被每个空闲窗口重新捞出来重问，把「无上限」变成无界烧钱。
    """

    def test_模型正当拒答的行不会被每轮重问(self, manager):
        client = FakeCueClient(responder=lambda _p: json.dumps({"cues": []}, ensure_ascii=False))
        first = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert first["scanned"] == len(ROWS) and first["written"] == 0, f"首轮读数异常：{first}"

        second = asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient()))
        assert second["scanned"] == 0, f"拒答的行被重问了：{second}"
        assert client.calls == 1, f"拒答后仍重复调用：{client.calls}"

    def test_尝试账走迁移注册表(self, manager):
        """`memory_cue_attempts` 必须经 `register_migration` 长出（AGENTS.md §3 SQLite 条），
        并且长在 `memories` 同一只 persist 伴生库里。"""
        import sqlite3

        from neurova.cognitive_layers.memory_layer.persist_landing import persistCompanionPath

        with sqlite3.connect(str(persistCompanionPath(manager._db_path))) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            names = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert version >= 5, f"memory 域版本 {version}，v5 迁移没跑"
        assert "memory_cue_attempts" in names, f"尝试账表缺失：{sorted(names)}"


class TestProductionWiringIsOnThePath:
    def test_生产装配点把模型依赖递进来(self):
        """判据形态：post_chat 的固化窗口必须经 `_get_dependency("llm_client")`
        取依赖、调 `generateModelAssociationCues`，且经 `_spawn_background` 派发
        （一个 25s 级模型调用不许坐在用户关键路径上）。
        形状守卫按调用形态匹配，不匹配注释文字。"""
        import ast

        # 仓库根按 __file__ 反推四层（tests/unit/cognitive_layers/memory_layer/），
        # 不写死盘符+项目名（TestNoHardcodedDevMachinePaths 逐行扫 tests/**/*.py）
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))))
        path = os.path.join(_root, "neurova", "post_chat_pipeline.py")
        with io.open(path, encoding="utf-8") as fh:
            src = fh.read()
        tree = ast.parse(src)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "generateModelAssociationCues" in calls, (
            "固化窗口没调用线索生成——生成器只在测试里被调用，生产上是孤岛"
        )
        assert "_spawn_background" in calls, (
            "线索生成没走后台派发——模型调用会压在用户关键路径上"
        )
        assert "_get_dependency" in calls and re.search(
            r'_get_dependency\(\s*"llm_client"\s*\)', src
        ), "生成器没经依赖单点取模型客户端（自己 new 一条就是第二份口径）"
