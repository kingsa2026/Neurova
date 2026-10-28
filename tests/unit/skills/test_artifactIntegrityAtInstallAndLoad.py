"""技能通道的构件完整性：安装门通过时钉摘要，装载执行前比对（§6-172 批 30， P3 技能半区）。

敞口（规格书 §4.1 与台账 §6-172 那条零命中复算）：`sha256|hashlib|digest|checksum|signature`
打在 `hub_client / market_importer / market_sources / marketplace 端点` 上是 **0 命中**。
仓里有静态扫描门（`skill_install_gate` + `skill_scanner`，DENY、异常 fail-closed），
但**没有任何东西把「门当时看到的字节」与「随后 exec 的字节」绑在一起**——
中间换包（在途换、落盘后改、并发重装）时，扫描器再严也只证明过去那一刻干净。

做法按裁定：TOFU 首钉 + 装载前比对，摘要口径全仓一处（`neurova/security/artifact_digest.py`）。

判据分两层：
- **行为层**（本批的红就红在这里）：装完的账本条目带摘要；改一个字节 ⇒ 装载被结构化拒绝；
  没动过 ⇒ 照常跑；存量无摘要 ⇒ 首钉放行、此后才开始执法；系统自己写的记账件不触发误报。
- **形状层**：算法字符串与排除清单不得在装载侧各写一份（教义第 6 条），并配复活样本反空转。

**不夸大能力**：摘要钉在账本里，账本与构件同根同权限——能整体改写磁盘的人也能改写摘要。
这块封的是在途换包与落盘后改动，不封拿到机器后的定向重算。
"""
import asyncio
import ast
import json
import os
import tempfile
from pathlib import Path

import pytest

from neurova.security import artifact_digest as AD
from neurova.skills.skill_install_gate import reset_install_gate_scanner
from neurova.skills.skill_service import SkillService
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]


def _guardedPinKeys(tree):
    """被"落盘确有构件"那条谓词挡住的钉摘要赋值，按账本键名收（`self._skills[<key>][DIGEST_FIELD] = …`）。

    §6-289 第①条改判了本档的口径：装侧过去**无条件**钉，空壳也被钉成构件权威；现在
    `install_skill` 两个写账本口都写成 `if self._hasArtifactBytes(dir): 钉`。
    "凡落盘条目必钉"因此不再等于"字面量里必须有那个键"——认不出这一形的守卫会把正确写法报成漏钉，
    而那种误报历史上正是让人关掉守卫的起点（本档头上那段两种键写法都要认，同一族）。
    """
    keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        guarded = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "_hasArtifactBytes" for n in ast.walk(node.test))
        if not guarded:
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign) or not isinstance(stmt.targets[0], ast.Subscript):
                continue
            outer = stmt.targets[0]
            inner = outer.value
            if (isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Attribute)
                    and inner.value.attr == "_skills"
                    and isinstance(outer.slice, ast.Attribute) and outer.slice.attr == "DIGEST_FIELD"):
                keys.add(ast.unparse(inner.slice))
    return keys


def _ledgerEntryDicts(source: str):
    """枚举 `self._skills[<id>] = {…}` 这类账本条目创建点，读出它是落盘条目还是空路径条目。

    键的写法两种都要认：字面量 `"artifact_digest"` 与常量引用 `artifact_digest.DIGEST_FIELD`
    ——只认字面量的探测器会把"用了常量"这份**正确**写法报成没钉，那种误报会让人把守卫关掉。
    """
    tree = parseSource(source)
    guardedKeys = _guardedPinKeys(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        targetIsLedger = False
        entryKey = None
        for target in node.targets:
            sub = target
            if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Attribute)
                    and isinstance(sub.value.value, ast.Name)
                    and sub.value.value.id == "self" and sub.value.attr == "_skills"):
                targetIsLedger = True
                entryKey = ast.unparse(sub.slice)
        if not targetIsLedger:
            continue
        pathIsConstantBlank = False
        hasPath = False
        hasDigestKey = False
        for key, value in zip(node.value.keys, node.value.values):
            keyName = key.value if isinstance(key, ast.Constant) else None
            if keyName == "path":
                hasPath = True
                pathIsConstantBlank = (isinstance(value, ast.Constant)
                                       and str(value.value or "") == "")
            isDigestKey = (keyName == AD.DIGEST_FIELD) or (
                isinstance(key, ast.Attribute) and key.attr == "DIGEST_FIELD")
            hasDigestKey = hasDigestKey or isDigestKey
        out.append({"line": node.lineno,
                    "diskBacked": hasPath and not pathIsConstantBlank,
                    "hasDigestKey": hasDigestKey,
                    "pinnedByGuard": entryKey in guardedKeys})
    return out

CLEAN_MD = "# helper\n\n把日期格式化为 ISO 标准格式的技能说明。\n"


@pytest.fixture(autouse=True)
def _gate_isolation():
    reset_install_gate_scanner()
    yield
    reset_install_gate_scanner()


def _makeSrc(base: Path, skillId: str, body: str = "def main(**kwargs):\n    return {'ok': True}\n"):
    src = base / skillId
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(
        json.dumps({"id": skillId, "name": skillId, "version": "1.0.0"}), encoding="utf-8")
    (src / "SKILL.md").write_text(CLEAN_MD, encoding="utf-8")
    (src / "main.py").write_text(body, encoding="utf-8")
    return src


@pytest.fixture
def svc(tmp_path):
    return SkillService(agent_id="digest-b30", skills_dir=str(tmp_path / "installed"))


def _install(svc, tmp_path, skillId="plain1", sourceBase=None):
    _makeSrc(sourceBase or (tmp_path / "src"), skillId)
    result = svc.install_skill(str((sourceBase or (tmp_path / "src")) / skillId))
    assert result.get("success") is True, result
    return svc.skills_dir / skillId


class TestPinnedAtInstall:
    def test_ledger_entry_carries_the_digest_of_what_the_gate_saw(self, svc, tmp_path):
        installed = _install(svc, tmp_path)
        # 读**账本本体**而不是 `get_skill_info`：后者是一份投影白名单，
        # 摘要的读者是装载前的执法接缝（不是 UI 字段），投影里不该替它新造一格。
        pinned = str(svc._skills["plain1"].get(AD.DIGEST_FIELD) or "")
        assert pinned.startswith(AD.DIGEST_PREFIX), (
            f"安装门通过后没钉摘要（{pinned!r}）——「扫过的那份」没有留底，"
            "此后 exec 的那份字节无法与它对账")
        assert pinned == AD.digestDir(installed), (
            "钉下的摘要与落盘目录现状不符——钉的时机早于落位，或排除口径漂了")

    def test_digest_survives_a_restart(self, svc, tmp_path):
        """写→读闭环：摘要必须经 `_save_manifest`/`_load_skills` 往返还读得到。

        缺这一格，"钉在账本里"可能只是钉在内存里——重启即失忆，装载前比对
        从此永远走 TOFU 分支，看着全绿却一次也没执法（本卷记过的只写不读同族）。
        """
        installed = _install(svc, tmp_path)
        pinned = str(svc._skills["plain1"].get(AD.DIGEST_FIELD) or "")

        reloaded = SkillService(agent_id="digest-b30", skills_dir=str(tmp_path / "installed"))
        assert str(reloaded._skills["plain1"].get(AD.DIGEST_FIELD) or "") == pinned
        (installed / "main.py").write_text("def main(**kwargs):\n    return 'after-restart'\n",
                                           encoding="utf-8")
        assert asyncio.run(reloaded.call_skill("plain1")).get("error") == AD.REASON_MISMATCH, (
            "重启后摘要虽在却不再执法——执法接缝读的是内存态而非账本态")

    def test_reinstall_repins_to_the_new_bytes(self, svc, tmp_path):
        """覆盖式重装必须重钉：否则升级后的正常内容会被上一次钉判成篡改。"""
        _install(svc, tmp_path)
        first = svc._skills["plain1"][AD.DIGEST_FIELD]
        _makeSrc(tmp_path / "src2", "plain1", body="def main(**kwargs):\n    return {'ok': 2}\n")
        assert svc.install_skill(str(tmp_path / "src2" / "plain1")).get("success") is True
        second = svc._skills["plain1"][AD.DIGEST_FIELD]
        assert second != first and second == AD.digestDir(svc.skills_dir / "plain1")


class TestVerifiedBeforeExec:
    def test_tampered_bytes_are_refused_at_load(self, svc, tmp_path):
        """这一格就是 P3 那句话的正面：改一个字节，今天照样跑得动。"""
        installed = _install(svc, tmp_path)
        (installed / "main.py").write_text(
            "def main(**kwargs):\n    return {'stolen': True}\n", encoding="utf-8")

        result = asyncio.run(svc.call_skill("plain1"))
        assert result.get("success") is not True, (
            "字节被换过仍装载执行——扫描门证明的是过去，执行的是现在，中间没人对账")
        assert result.get("error") == AD.REASON_MISMATCH, (
            f"拒因不是结构化标识而是自然语言（{result.get('error')!r}），调用方无法按性质分支")

    def test_untouched_skill_still_runs(self, svc, tmp_path):
        """正向格：钉与验是为了拦换包，不是为了把功能焊死。"""
        _install(svc, tmp_path)
        assert asyncio.run(svc.call_skill("plain1")).get("success") is True

    def test_legacy_entry_without_digest_is_pinned_then_enforced(self, svc, tmp_path):
        """TOFU 两拍：存量条目没有摘要 ⇒ 首钉放行；此后才开始执法。

        缺这一格，「装载前比对」会退化成把**所有**已安装技能挡在门外（含内置链）。
        """
        installed = _install(svc, tmp_path)
        svc._skills["plain1"].pop(AD.DIGEST_FIELD, None)
        assert svc._save_manifest()

        assert asyncio.run(svc.call_skill("plain1")).get("success") is True, (
            "存量无摘要即拒＝把今天所有已安装技能一起挡掉，这不是安全是停机")
        assert str(svc._skills["plain1"].get(AD.DIGEST_FIELD) or "").startswith(
            AD.DIGEST_PREFIX), (
            "首钉没落账：下一次装载还是「没钉过」，永远走 TOFU 分支，比对一次也不会发生")

        (installed / "main.py").write_text("def main(**kwargs):\n    return 'evil'\n",
                                           encoding="utf-8")
        assert asyncio.run(svc.call_skill("plain1")).get("error") == AD.REASON_MISMATCH

    def test_bookkeeping_and_runtime_files_do_not_trip_the_pin(self, svc, tmp_path):
        """系统自己写的不算篡改：`skill.json` 在校验链里会被重写，`__pycache__` 运行时长出来。

        口径若把它们计入，每一次正常运行都会自打脸——那之后人们只会把这块关掉。
        """
        installed = _install(svc, tmp_path)
        (installed / "skill.json").write_text(json.dumps({"permissions": ["read:files"]}),
                                              encoding="utf-8")
        os.makedirs(installed / "__pycache__", exist_ok=True)
        (installed / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00stale-bytecode")

        assert asyncio.run(svc.call_skill("plain1")).get("success") is True, (
            "记账件/运行产物被计入摘要 ⇒ 正常安装也会翻红，判据就成了噪音发生器")


class TestRefusalIsAttributable:
    def test_mismatch_carries_both_digests_not_just_a_sentence(self, svc, tmp_path):
        installed = _install(svc, tmp_path)
        (installed / "main.py").write_text("def main(**kwargs):\n    return 'swapped'\n",
                                           encoding="utf-8")
        result = asyncio.run(svc.call_skill("plain1"))
        expected = str(result.get("expected_digest") or "")
        actual = str(result.get("actual_digest") or "")
        assert expected.startswith(AD.DIGEST_PREFIX) and actual.startswith(AD.DIGEST_PREFIX), (
            f"只说「不匹配」却没给出两边读数（{result}）——出事时无法判断改了哪一份字节")
        assert expected != actual


class TestDigestCaliberIsSingleSource:
    """口径单点：算法名与排除清单只能在 `artifact_digest.py` 一份（教义第 6 条）。"""

    def test_skill_channel_does_not_redeclare_the_algorithm_or_the_exclusions(self):
        src = (REPO_ROOT / "neurova/skills/skill_service.py").read_text(encoding="utf-8")
        assert '"sha256"' not in src and "hashlib" not in src, (
            "装载侧自己算摘要了——算法与排除清单从此两份，迟早说两种话")
        assert "__pycache__" not in src, "排除清单被抄进了调用方"

    def test_detector_hits_a_revived_local_digest(self):
        """反空转：探测器认不出旧形态，上一格就是恒真的空守卫。"""
        revived = "import hashlib\nd = hashlib.new('sha256', b'x').hexdigest()\n"
        assert "hashlib" in revived

    def test_comparison_checks_the_algorithm_not_just_the_value(self):
        """比较口径：算法前缀不符必须判不匹配。

        只比值的话，将来换算法或有人塞进一条 `md5:` 摘要，会静默判等失败（误拒存量）
        或在同值碰撞时静默判等成功（放过换包）——两种都听不见声音。
        """
        digest = AD.digestBytes(b"same-bytes")
        assert AD.digestMatches(digest, digest) is True
        # 样本必须取**等长的另一种算法标签**：前缀长度不同会被字符串长度差自动判负，
        # 那样这一格对"去掉前缀核对"的变异是聋的（本卷「自证样本要取真码那形」的同族）。
        sameTail = "sha512:" + digest.split(":", 1)[1]
        assert AD.digestMatches(sameTail, digest) is False, (
            "算法标签不同（sha512 vs sha256）却判等——比较口径没核算法，换算法会静默通过")
        assert AD.digestMatches("md5:" + digest.split(":", 1)[1][:8], digest) is False

    def test_empty_and_missing_are_not_the_same_answer(self):
        """`没钉过` 与 `目录不见了` 必须是两个状态：前者首钉放行，后者拒绝。

        混成一个，"删掉再放回来"与"存量首次装载"就会共用一条分支——
        要么把删除当首钉静默放过，要么把存量当篡改一律拒。
        """
        root = Path(tempfile.mkdtemp(prefix="adState."))
        (root / "main.py").write_text("x = 1\n", encoding="utf-8")
        status, actual = AD.checkArtifact(root, "")
        assert (status, actual) == (AD.STATUS_UNPINNED, AD.digestDir(root))
        assert AD.checkArtifact(root / "nope", actual)[0] == AD.STATUS_MISSING
        assert AD.checkArtifact(root, "sha256:" + "0" * 64)[0] == AD.STATUS_MISMATCH

    def test_helper_is_the_only_digest_implementation(self):
        """聚合摘要的实现全仓一处：`def digestDir` 出现两次就是下一次漂移的起点。"""
        hits = [p.relative_to(REPO_ROOT).as_posix()
                for p in (REPO_ROOT / "neurova").rglob("*.py")
                if "__pycache__" not in p.parts
                and "def digestDir" in p.read_text(encoding="utf-8")]
        assert hits == ["neurova/security/artifact_digest.py"], hits

    def test_every_disk_backed_ledger_entry_is_pinned(self):
        """「每个 X 都必须 Y」的契约要有一格自己枚举 X（本卷口径，手抄登记表只会审住已登记的）。

        机器枚举技能账本的条目创建点：凡落盘条目（`path` 不是空串字面量）都必须带摘要键。
        `register_auto_skill` 那支是 `"path": ""` 的无文件条目（配置存在 manifest 里、
        不走 `call_skill` 的 exec 分支），因此不在要求内——由判据自己读出来，不是我点名。
        """
        src = (REPO_ROOT / "neurova/skills/skill_service.py").read_text(encoding="utf-8")
        entries = _ledgerEntryDicts(src)
        assert len(entries) >= 2, f"账本条目创建点数少于已知值：{entries}"
        unpinned = [e for e in entries
                    if e["diskBacked"] and not (e["hasDigestKey"] or e["pinnedByGuard"])]
        assert not unpinned, (
            f"这些落盘条目创建时没钉摘要也没走那条守卫：{[e['line'] for e in unpinned]}——"
            "从这条旁路进来的构件从此只有 TOFU 兜底，门当时看到的字节没有留底")

    def test_guarded_pin_form_is_recognised_not_waved_through(self):
        """改判口径自己要有牙：认的是"被那条谓词挡住的钉"，不是"只要有个 if 就算钉"。

        两半必须反向：同一份带守卫的写法要被判成**已钉**（否则本批改判后一处也过不了），
        而把守卫摘掉、只留一条无条件之外的空 if，要仍然被判成**漏钉**（否则这条改判
        就是把守卫改成了橡皮章）。
        """
        guarded = (
            "class S:\n"
            "    def install(self):\n"
            "        self._skills[skill_id] = {'id': 'x', 'path': str(d)}\n"
            "        if self._hasArtifactBytes(d):\n"
            "            self._skills[skill_id][artifact_digest.DIGEST_FIELD] = artifact_digest.digestDir(d)\n")
        # 同一份代码，只把守卫摘掉（钉赋值仍在，但不再由那条谓词挡着）——这才叫落在分歧点上。
        unguarded = (
            "class S:\n"
            "    def install(self):\n"
            "        self._skills[skill_id] = {'id': 'x', 'path': str(d)}\n"
            "        if d.exists():\n"
            "            self._skills[skill_id][artifact_digest.DIGEST_FIELD] = artifact_digest.digestDir(d)\n")

        assert _ledgerEntryDicts(guarded)[0]["pinnedByGuard"] is True, (
            "带守卫的钉没被认出来——本批改判后，正确写法会被自己的守卫报成漏钉")
        found = _ledgerEntryDicts(unguarded)
        assert found[0]["pinnedByGuard"] is False and not found[0]["hasDigestKey"], (
            "摘掉守卫也算钉好了？那这条改判就成了橡皮章")

    def test_detector_hits_a_revived_unpinned_writer(self):
        """反空转：把摘除掉的写法喂给探测器，必须被认成"没钉"。"""
        revived = (
            "class S:\n"
            "    def install(self):\n"
            "        self._skills['x'] = {'id': 'x', 'path': str(some_dir)}\n")
        found = _ledgerEntryDicts(revived)
        assert len(found) == 1 and found[0]["diskBacked"] and not found[0]["hasDigestKey"], found
