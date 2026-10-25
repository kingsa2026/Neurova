"""模型联想线索生成器（TM-2b 批 C-2）的行为判据 —— 先红

上游：批 A 落了线索的存储与作用域门（§6-382）、批 C-1 落了向量通道（§6-384）。
本批补**内容**——规则线索实测信息量近零（26 条只含 2 个不同归一键），
向量通道在生产线上是暗的；用户裁丙（空闲窗口段落级、不设调用上限）要的就是这一格。

三条从上一批实测里长出来的硬规则，本批全部做成判据而不是注释：
1. **不复述原文**：与正文词面同集的线索对召回零增益（词法刀切不出跨句重合，向量也一样），
   必须挡掉并计数。
2. **泛词即串味**：C-1 标定发现误注入的主因是「别的记忆的线索更像」（目标线索 0.465–0.612，
   其它记忆线索可达 0.687），所以提示词要线索**具体到只对该条成立**，
   生成侧要按记忆分组写；跨记忆复用同词**不在生成侧挡**（C-3 勘正：那是正当共享，
   按批去重等于让 N 兼任质量参数），改由检索侧的全局扇出门裁。
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
        from neurova.embedding import get_embedding_engine

        engine = get_embedding_engine()
        probe = [float(x) for x in engine.encode("前提自证")] if engine is not None else []
        if not probe or not any(abs(x) > 0.0 for x in probe):
            # 通道的每条线索都要先编码成向量；引擎缺档（`requirements-ci.txt` 刻意不含
            # onnxruntime/tokenizers/sentencepiece）时索引必空——那是**前置不成立**，
            # 不是判据失败。如实说明并跳过，别把「这台机器上根本没编码器」读成缺陷。
            pytest.skip("嵌入引擎不可用或回零向量：本档的向量通道前提不成立")
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
        """与正文词面同集的线索零增益（C-1 实测），必须挡下来且**读数可见**。

        写法刻意**与 pending 顺序无关**：从提示里把 `[序号] 正文` 解析出来，逐序号回抄该正文。
        早期版本硬写 `{"key": 0, ...}`，而冷启动预算上线后 pending 改成按温度排序，
        序号 0 不再对应那一条记忆——用例就从"测过滤"悄悄变成"测运气"。
        """
        import re

        def _restateEveryRow(prompt: str) -> str:
            rows = dict(
                (int(idx), body) for idx, body in re.findall(r"^\[(\d+)\] (.+)$", prompt, re.M)
            )
            assert rows, "提示里没有 `[序号] 正文` 行——解析口径与本用例的假设不符"
            return json.dumps(
                {"cues": [{"key": int(idx), "text": body[3:]} for idx, body in rows.items()]},
                ensure_ascii=False,
            )

        client = FakeCueClient(responder=_restateEveryRow)
        readout = asyncio.run(manager.generateModelAssociationCues(client=client))
        assert readout["droppedGeneric"] >= 1, f"复述型线索没被挡：{readout}"
        assert readout["written"] == 0, f"复述线索仍写进了库：{readout}"
        for mem in list(manager._memories.values()):
            assert all("起了荨麻疹" not in c["cue_text"] for c in manager.get_associationCues(mem.id)), (
                "复述原文的线索落库了"
            )


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


class TestColdStartWindowBudgetUnderOpenBudget:
    """用户裁：**只给冷启动加每窗口行数预算，稳态仍无上限**（票一·乙＋温度优先）。

    关键是别把它做成一个隐式上限——那等于把丙档收回去了。三条界线都钉住：
    ① 超预算才截断，且**截断了要看得见**（`deferred` 读数，不许静默丢）；
    ② 截断时按 `temperature DESC`（次键 `created_at DESC`）取舍，不是按插入序；
    ③ 稳态（待处理面远小于预算）**必须全处理**，预算不得伸进稳态。
    """

    def test_稳态不受预算影响(self, manager):
        """每轮落 2 行、10 轮一触发 ⇒ 稳态待处理面约 20 行，远小于预算，必须一次做完。"""
        for i in range(18):
            manager.remember(content=f"用户: 稳态新增第{i}条安排，涉及不同的场所与人员{i}",
                             memory_type="episodic", metadata={"chat_scope": "direct"})
        client = FakeCueClient()
        readout = asyncio.run(manager.generateModelAssociationCues(client=client, windowRows=500))
        assert readout["scanned"] == 18 + len(ROWS), f"稳态被预算截了：{readout}"
        assert readout["deferred"] == 0, f"稳态不该有顺延：{readout}"

    def test_超预算只截冷启动且顺延可见(self, manager):
        for i in range(9):
            manager.remember(content=f"用户: 冷启动历史第{i}条，各涉不同事项编号{i}",
                             memory_type="episodic", metadata={"chat_scope": "direct"})
        client = FakeCueClient()
        first = asyncio.run(manager.generateModelAssociationCues(client=client, windowRows=4))
        assert first["scanned"] == 4, f"窗口没生效：{first}"
        assert first["deferred"] == 9 + len(ROWS) - 4, f"顺延数没记账：{first}"

        # 顺延不能丢也不能重：逐轮跑到清空，累计处理数必须正好等于总行数
        total = first["scanned"]
        deferred = first["deferred"]
        rounds = 1
        while deferred:
            nxt = asyncio.run(
                manager.generateModelAssociationCues(client=FakeCueClient(), windowRows=4)
            )
            assert nxt["scanned"] == min(deferred, 4), f"这轮没接住顺延：{nxt}"
            assert nxt["deferred"] == deferred - nxt["scanned"], f"顺延记账不连续：{nxt}"
            total += nxt["scanned"]
            deferred = nxt["deferred"]
            rounds += 1
        assert total == 9 + len(ROWS), f"跨轮累计处理 {total}，应等于总行数"
        assert rounds == 3, f"轮数异常（每窗口 4 行、12 行应 3 轮）：{rounds}"
        tail = asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient(), windowRows=4))
        assert tail["scanned"] == 0 and tail["deferred"] == 0, f"清空后仍有活：{tail}"

    def test_截断时按温度优先不是插入序(self, manager):
        """温度低的行被留下、高的先做——否则冷启动预算会把最不该忘的先推走。"""
        ids = {}
        for i in range(6):
            content = f"用户: 温度试验第{i}条往事，涉及不同场所与人员{i}"
            memId = manager.remember(content=content, memory_type="episodic",
                                     metadata={"chat_scope": "direct"}, importance=0.5)
            ids[i] = (memId, content)
        # 人为造温度差：后三条高、前三条低
        for rank, i in enumerate((3, 4, 5)):
            manager._memories[ids[i][0]].temperature = 90.0 + rank
        for i in (0, 1, 2):
            manager._memories[ids[i][0]].temperature = 10.0 + i

        asyncio.run(manager.generateModelAssociationCues(client=FakeCueClient(), windowRows=3))

        processed = {memId for memId, _ in ids.values()
                     if manager.associationCueAttemptedFor(memId)}
        highOnly = {ids[i][0] for i in (3, 4, 5)}
        assert processed and processed <= highOnly, (
            f"窗口取了低温度行：处理={processed}，高温度集={highOnly}"
        )


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
