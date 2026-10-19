# -*- coding: utf-8 -*-
"""H2-2 · E 条：任务账本的终态词汇只许一份定义（§6-78 E 条）。

缺陷形态（改前）：账本成功态由 `recovery.py:68/73/77` 写 **`succeeded`**，而产物保留
清理 `retention.py:30` 自造 `_TERMINAL = ("done", "failed")` —— `"done"` 是账本里
**不存在的值**。于是 `purge_expired_files` 对每条成功件走 `continue`：清理逻辑从未清过
一个成功产物，且 `if stats.get("deleted")` 让日志连一行都不打——用户打开
`NEUROVA_GENERATION_RETENTION_DAYS` 后只看到磁盘无界增长，没有任何故障信号
（`app.py:1153-1158` 真挂 lifespan，消费侧成立）。

四条判据，缺一条这条链就是断的：

1. **跨边界闭环**（本条真正的红灯）：**真** `settle_video_record` 收口一条视频任务
   （写侧）→ **真** `purge_expired_files` 读同一份账本 → 过期件必须被删。
   不让测试自己挑词值：只有写侧与读侧共用一份定义时才会绿。
2. **单源**：`retention` 不再有本地终态集合，判定时引用的集合与 `task_ledger` 那份
   是同一个对象（按 import 归属判，不按字面量计数——同 §6-78 A 条守卫的教训）。
3. **活跃态同源**：`unfinished()` 的 `submitted/running` 与 `TASK_ACTIVE_STATUSES` 同集合。
4. **同根因扫荡**（教义第 5 条）：账本词汇的所有命中点里，`done` 不得作为账本状态出现；
   终态/活跃集合不得在 `task_ledger` 之外再定义一份。每格都配**反向对照**，
   防本仓老根因「扫空即全绿」。
"""
from __future__ import annotations

import ast
import time
from pathlib import Path

from tests import ast_scan

import pytest

from neurova.llm.generators import retention as rt
from neurova.llm.generators import task_ledger as tl
from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord

pytestmark = pytest.mark.timeout(60)

DAY = 86400.0

#: 建档时逐处 grep 现取的已知命中点——扫描面若收缩到不含它们，判据即红
#: （防止「反扫结果空了」被读成「全仓干净」，本仓老根因）。
_KNOWN_VOCAB_FILES = [
    "neurova/llm/generators/task_ledger.py",
    "neurova/llm/generators/recovery.py",
    "neurova/llm/generators/retention.py",
    "neurova/aigc_studio/video_reconcile.py",
    "neurova/api/endpoints/generation.py",
]
#: 允许定义词汇的字面落点（唯一事实源本体）
_DEF_SITE = "neurova/llm/generators/task_ledger.py"

REPO = Path(__file__).resolve().parents[3]
#: 扫描根单点，且必须是**模块级**：收进函数局部，面自证棘轮的取数口会把它解成动态值，
#: 那档就静默掉出它的面（补了自证也是假的）。
NEUROVA = REPO / "neurova"


def _importsTaskLedger(rel: str) -> bool:
    """现场 AST 反推扫描面：谁 import 了 `task_ledger`，谁就受词汇纪律约束。
    两种写法都要认：`from a.b import task_ledger as m`（名字在 alias 里）与
    `from a.b.task_ledger import X`（名字在 module 里）。"""
    for node in ast.walk(_parseSrc(_source(rel), rel)):
        if isinstance(node, ast.Import):
            if any(a.name.endswith("task_ledger") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.endswith("task_ledger") or any(
                    a.name == "task_ledger" for a in node.names):
                return True
    return False


def _vocabFiles() -> list[str]:
    """import 了 `task_ledger` 的文件清单（受词汇纪律约束的扫描面）。

    枚举与解析走 tests/ast_scan 的共享预算（`parsedModules` 一次给出
    `(路径, 语法树)`），不私有 `rglob + ast.parse`——后者把判据成本绑在代码总量上
    （见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    """
    found = [_DEF_SITE]
    modules = list(ast_scan.parsedModules(NEUROVA, ".py"))
    assert len(modules) > 500, (
        f"扫描面现读 {len(modules)} 档（根＝{NEUROVA}，本判据的域＝生产源码）——"
        "根被改窄时「除定义处没人另立词汇」只是没在看代码")
    for path, tree in modules:
        rel = path.relative_to(REPO).as_posix()
        if rel == _DEF_SITE:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.endswith("task_ledger") for a in node.names):
                    found.append(rel)
                    break
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.endswith("task_ledger") or any(
                        a.name == "task_ledger" for a in node.names):
                    found.append(rel)
                    break
    return sorted(found)


def _source(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _parseSrc(src: str, rel: str = "<inline>") -> ast.AST:
    r"""被扫文件里的 `\w`/`\`` 之类会以 SyntaxWarning 冒到本判据名下——那些是**被扫**
    源码的事，不是本文件的事，扫的时候按名字压掉，不顺手改别人的转义。"""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(src, filename=rel)


#: 收集期现算的扫描面（import 现场反推，不手抄清单）
_VOCAB_FILES = _vocabFiles()


def _statusComparisonsMentioningDone(src: str) -> list[str]:
    """左侧是 `*status*` 名字/属性、右侧字符串集合含 `done` 的比较——即把账本
    状态拿来跟一个不存在的词值比。返回命中的行号串。"""
    hits = []
    for node in ast.walk(_parseSrc(src, "<inline>")):
        if not isinstance(node, ast.Compare):
            continue
        left = node.left
        leftName = (left.id if isinstance(left, ast.Name)
                    else left.attr if isinstance(left, ast.Attribute) else "")
        if "status" not in leftName.lower():
            continue
        operands = list(node.comparators)
        for operand in operands:
            strs = []
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                strs = [operand.value]
            elif isinstance(operand, (ast.Tuple, ast.List, ast.Set)):
                strs = [e.value for e in operand.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "done" in strs:
                hits.append(f"line {node.lineno}: {leftName} 与 'done' 比较")
    return hits


def _secondVocabularyDefinitions(src: str, selfRel: str) -> list[str]:
    """模块级把终态/活跃集合**用字符串字面量**再定义一份（唯一事实源之外）。"""
    if selfRel == _DEF_SITE:
        return []
    hits = []
    tree = _parseSrc(src, selfRel)
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        else:
            continue
        if not targets or value is None:
            continue
        name = targets[0]
        if not any(k in name.upper() for k in ("TERMINAL", "ACTIVE", "STATUS")):
            continue
        strs = [e.value for e in ast.walk(value)
                if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if strs:
            hits.append(f"line {node.lineno}: {name} 自造词值 {strs}")
    return hits


class TestWriteReadClosedLoop:
    """判据 1：写侧（真收口）与读侧（真清理）必须共用一份词值。"""

    def test_recovered_success_is_purgeable_by_retention(self, tmp_path, monkeypatch):
        import asyncio

        from neurova.llm.generators import recovery as rec_mod

        led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
        outDir = tmp_path / "generations"
        outDir.mkdir()
        rec = led.add(TaskRecord(
            kind="video", provider_id="p1", protocol="wan", model="wan3.0-t2v",
            base_url="https://dashscope/api/v1", status="submitted",
            remote_task_id="rt-1", poll_url="https://x/tasks/rt-1", prompt="p",
            owner_user_id="u1",
        ))

        async def fakePoll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "http://cdn/v.mp4", "raw": {}}

        async def fakePersist(url, kind, task_id, index, out_dir=None):
            p = outDir / f"{task_id}.mp4"
            p.write_bytes(b"MP4")
            return str(p)

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fakePoll)
        monkeypatch.setattr(rec_mod, "persist_media", fakePersist)
        monkeypatch.setattr(rec_mod, "resolve_generation_creds",
                            lambda *a, **k: object())
        monkeypatch.setattr(rec_mod, "_record_video_usage", lambda *a, **k: None)

        out = asyncio.run(rec_mod.settle_video_record(rec, ledger=led))
        assert out["status"] == "succeeded", out
        written = led.get(rec.task_id)
        assert written.local_path, "本地化成功应把产物路径写进账本"

        artifact = Path(written.local_path)
        assert artifact.is_file()
        stats = rt.purge_expired_files(led, referenced=set(), days=7, out_dir=outDir,
                                       now=time.time() + 8 * DAY)
        assert stats["scanned"] == 1, (
            f"成功件没被当成终态扫到（scanned={stats['scanned']}）——"
            f"写侧词值与读侧词值不同源，清理逻辑对成功产物整轮空转")
        assert stats["deleted"] == 1 and not artifact.exists()
        assert led.get(rec.task_id) is not None, "账本行永不删（历史面板据此显示已过期）"

    def test_localization_failure_has_no_local_path_and_is_not_purged(self, tmp_path, monkeypatch):
        """反向对照：判据 1 不是「全都删」——本地化失败的件没有 local_path，不该被计入。"""
        import asyncio

        from neurova.llm.generators import recovery as rec_mod

        led = GenerationTaskLedger(path=str(tmp_path / "tasks2.json"))
        outDir = tmp_path / "generations"
        outDir.mkdir()
        rec = led.add(TaskRecord(
            kind="video", provider_id="p1", protocol="wan", model="wan3.0-t2v",
            base_url="b", status="submitted", remote_task_id="rt-2",
            poll_url="https://x/tasks/rt-2", prompt="p", owner_user_id="u1",
        ))

        async def fakePoll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "http://cdn/v.mp4", "raw": {}}

        async def boomPersist(*a, **k):
            raise RuntimeError("下载失败")

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fakePoll)
        monkeypatch.setattr(rec_mod, "persist_media", boomPersist)
        monkeypatch.setattr(rec_mod, "resolve_generation_creds", lambda *a, **k: object())
        monkeypatch.setattr(rec_mod, "_record_video_usage", lambda *a, **k: None)

        asyncio.run(rec_mod.settle_video_record(rec, ledger=led))
        written = led.get(rec.task_id)
        assert written.status == "succeeded" and not written.local_path
        stats = rt.purge_expired_files(led, referenced=set(), days=7, out_dir=outDir,
                                       now=time.time() + 8 * DAY)
        assert stats["deleted"] == 0

    def test_writeSideValueIsInSharedTerminalSet(self, tmp_path, monkeypatch):
        """同一格的「单源」面：写侧真正落库的词值必须就在那份唯一集合里。"""
        import asyncio

        from neurova.llm.generators import recovery as rec_mod

        led = GenerationTaskLedger(path=str(tmp_path / "tasks-v.json"))
        outDir = tmp_path / "generations"
        outDir.mkdir()
        rec = led.add(TaskRecord(kind="video", provider_id="p1", protocol="wan",
                                 model="m", base_url="b", status="submitted",
                                 remote_task_id="rt-v", poll_url="u", prompt="p"))

        async def fakePoll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "http://cdn/v.mp4"}

        async def fakePersist(url, kind, task_id, index, out_dir=None):
            p = outDir / f"{task_id}.mp4"
            p.write_bytes(b"MP4")
            return str(p)

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fakePoll)
        monkeypatch.setattr(rec_mod, "persist_media", fakePersist)
        monkeypatch.setattr(rec_mod, "resolve_generation_creds", lambda *a, **k: object())
        monkeypatch.setattr(rec_mod, "_record_video_usage", lambda *a, **k: None)

        asyncio.run(rec_mod.settle_video_record(rec, ledger=led))
        written = led.get(rec.task_id)
        assert written.status in tl.TASK_TERMINAL_STATUSES, (
            f"收口写侧的 {written.status!r} 不在账本终态单源集合 "
            f"{sorted(tl.TASK_TERMINAL_STATUSES)} 里")


class TestSingleSource:
    """判据 2/3：集合只有一份，且读侧引用的就是那一份。"""

    def test_retention_has_no_local_terminal_vocabulary(self):
        assert getattr(rt, "_TERMINAL", None) is None, (
            "retention 仍在自造终态集合——§6-78 E 条的第二份定义没退役")
        bound = [v for v in vars(rt).values() if v is tl.TASK_TERMINAL_STATUSES]
        assert bound, "retention 判定终态时没有引用 task_ledger 那份单源集合"

    def test_active_statuses_drive_unfinished(self, tmp_path):
        led = GenerationTaskLedger(path=str(tmp_path / "tasks3.json"))
        for st in ("submitted", "running", "succeeded", "failed"):
            led.add(TaskRecord(kind="video", task_id=f"t-{st}", status=st,
                               remote_task_id=f"rt-{st}", prompt="p"))
        active = {r.status for r in led.unfinished()}
        assert active == set(tl.TASK_ACTIVE_STATUSES), (
            f"unfinished() 的活跃态 {sorted(active)} 与单源集合 "
            f"{sorted(tl.TASK_ACTIVE_STATUSES)} 不同源")
        # 反向对照：终态两件确实没混进来
        assert "succeeded" not in active and "failed" not in active

    def test_vocabulary_values_are_the_declared_domain(self):
        assert tl.TASK_TERMINAL_STATUSES == {tl.TASK_SUCCEEDED, tl.TASK_FAILED}
        assert "done" not in tl.TASK_TERMINAL_STATUSES, (
            '"done" 不是账本里的值（成功态由 recovery 写 succeeded）——放进终态集合'
            "等于把幻影词值写进单源")


class TestSweepScopeIsLive:
    """防「扫空即全绿」：扫描面必须真的存在且真的非空。"""

    def test_scope_is_derived_and_covers_known_hits(self):
        assert _VOCAB_FILES, "反扫结果为空——判据会退化成恒真"
        missing = [p for p in _KNOWN_VOCAB_FILES if p not in _VOCAB_FILES]
        assert not missing, (
            f"建档时已知的账本词汇命中点掉出了扫描面（有人改了 import 写法，"
            f"或扫描面自己坏了）：{missing}")
        for rel in _VOCAB_FILES:
            assert (REPO / rel).is_file(), f"扫描面里的文件不在盘：{rel}"
            _parseSrc(_source(rel), rel)

    def test_reverse_control_status_comparison(self):
        """把幻影词值塞回源码，扫描器必须报出来（否则第 4 条判据是恒绿的摆设）。"""
        src = "def f(rec):\n    if rec.status in ('done', 'failed'):\n        return 1\n"
        assert _statusComparisonsMentioningDone(src), "扫描器抓不到 `status in ('done',…)`"
        assert _statusComparisonsMentioningDone(
            "def g(t):\n    return t.status == 'done'\n")
        # 合法形态不误伤：用单源常量比较
        assert not _statusComparisonsMentioningDone(
            "def g(t):\n    return t.status == tl.TASK_SUCCEEDED\n")

    def test_reverse_control_second_vocabulary_definition(self):
        src = "_TERMINAL = ('done', 'failed')\n"
        assert _secondVocabularyDefinitions(src, "neurova/x.py"), (
            "扫描器抓不到模块级自造终态集合")
        assert _secondVocabularyDefinitions("_ACTIVE = ('submitted',)\n", "neurova/x.py")
        # 允许落点：事实源本体自己定义
        assert not _secondVocabularyDefinitions(src, _DEF_SITE)
        # 合法形态：只导入，不再抄一份
        assert not _secondVocabularyDefinitions(
            "from neurova.llm.generators.task_ledger import TASK_TERMINAL_STATUSES as T\n",
            "neurova/x.py")


class TestSweep:
    """判据 4（教义第 5 条）：同一根因在所有命中点闭环。"""

    @pytest.mark.parametrize("rel", _VOCAB_FILES)
    def test_no_phantom_done_in_status_comparisons(self, rel):
        offenders = _statusComparisonsMentioningDone(_source(rel))
        assert not offenders, f"{rel} 把账本状态跟幻影 'done' 比：{offenders}"

    @pytest.mark.parametrize("rel", _VOCAB_FILES)
    def test_no_second_vocabulary_definition(self, rel):
        offenders = _secondVocabularyDefinitions(_source(rel), rel)
        assert not offenders, f"{rel} 自造了第二份账本状态词汇：{offenders}"
