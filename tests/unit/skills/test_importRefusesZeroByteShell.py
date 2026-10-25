# -*- coding: utf-8 -*-
r"""零字节安装不得被报成成功——市场条目的取件来源必须在安装时被问一次（丁批，用户裁乙＋丙）。

背景（本机实测链）：一条只有占位下载地址、既无内置包也不属已注册远端源的条目，`import_skill`
会**跳过下载、照样 COMPLETED**，落盘只有 skill.json；端点回 200，用户以为装上了，技能页却
只能把它标灰。批 956f18f7 把 code-analysis 挪进了内置包那条腿，但**造空壳的引擎还在**：
管理端任何人上架一条不填可取件地址的技能，就会重演同一条链。

本档钉四件事，方向各不相同：

1. **新闸**（今天红）：三条腿（内置包／已注册远端源／代码侧执行体映射）全不成立的条目，
   安装必须 FAILED 并点名「无可取件地址」，且**不许留下空壳目录**——只 FAIL 不落干净，
   等于换个方式继续产陈态。
2. **三条现役腿各一根反向控制格**（今天绿）：收紧不许把内置包、真远端下载、映射族一起误杀。
   少了这三格，第 1 格可以靠"把所有安装都判失败"蒙绿。
3. **丙**（今天红）：目录里没有地址的条目，读面不得凭空拼一个出来——合成一个不存在的 URL
   既骗人又让第 1 条闸的输入变成"看起来永远有来源"。
4. **退役**（今天红）：那个占位域名字符串与 `market_url` 构造参数在两份生产码里都不得再出现
   （退役键要连写口一起拒，形态集 362 同族）。
"""

import json
from pathlib import Path

import pytest

from neurova.skills.market_importer import MarketImporter
from neurova.skills.market_store import MarketStore

REPO_ROOT = Path(__file__).resolve().parents[3]

GHOST_ID = "ghost-no-source"
#: 一个明显不属于已注册远端源的地址：闸要拒的就是这种"看着像地址"的值。
PLACEHOLDER_URL = "https://market.invalid-placeholder.example/g.zip"


@pytest.fixture
def store(tmp_path, monkeypatch):
    """隔离 catalog；importer 经 market_store.get_market_store 取数，替换这一处即可。"""
    st = MarketStore(catalog_path=tmp_path / "catalog.json")
    import neurova.skills.market_store as ms

    monkeypatch.setattr(ms, "get_market_store", lambda: st)
    return st


def _importer(tmp_path) -> MarketImporter:
    return MarketImporter(skills_dir=tmp_path / "skills")


# ── 1. 新闸 ──


def test_noArtifactSource_failsAndLeavesNoShell(tmp_path, store):
    store.create({
        "skill_id": GHOST_ID, "name": "Ghost", "version": "1.0.0",
        "description": "只有占位地址的一条", "download_url": PLACEHOLDER_URL,
    })
    task = _importer(tmp_path).import_skill(GHOST_ID)

    assert task.status.value == "failed", (
        f"三条腿全不成立却回 {task.status.value}——装成功后落盘的就是一具空壳")
    assert "无可取件地址" in (task.error_message or ""), task.error_message
    assert not (tmp_path / "skills" / GHOST_ID / "skill.json").exists(), (
        "拒装之后不该再有 skill.json：FAIL 了还落账，等于换个方式继续产陈态")


def test_entryAbsentFromCatalog_failsToo(tmp_path, store):
    """catalog 里查无此条时同样不许"模拟成功"——那条尾巴曾经是默认出路。"""
    task = _importer(tmp_path).import_skill("never-listed")
    assert task.status.value == "failed", task.status.value
    assert not (tmp_path / "skills" / "never-listed").exists()


# ── 2. 三条现役腿的反向控制 ──


def test_mappedExecutorSeed_stillInstalls(tmp_path, store):
    """代码侧执行体那一族（web-search）本来就零字节，收紧不许把它一起掐死。

    用 catalog 自带的那条种子（`create` 撞重复 id 会 ValueError，也不该在判据里造第二条）。
    """
    assert store.get("web-search") is not None, "种子面变了，本格的取样点得跟着换"
    task = _importer(tmp_path).import_skill("web-search")

    assert task.status.value == "completed", task.error_message
    assert (tmp_path / "skills" / "web-search" / "skill.json").is_file()


def test_builtinBundle_stillInstalls(tmp_path, store):
    """内置包那条腿：真字节随包解压，与闸无关。"""
    task = _importer(tmp_path).import_skill("code-analysis")

    assert task.status.value == "completed", task.error_message
    assert (tmp_path / "skills" / "code-analysis" / "SKILL.md").is_file()


def test_registeredRemoteSource_stillDownloads(tmp_path, store, monkeypatch):
    """已注册远端源那条腿：必须真的被走到一次，不能被闸当成无来源拒掉。"""
    store.create({"skill_id": "remote--x", "name": "Remote X", "version": "1.0.0",
                  "description": "d", "download_url": PLACEHOLDER_URL})

    import neurova.skills.market_sources as msrc

    monkeypatch.setattr(msrc, "_remote_hosts", lambda: {"market.invalid-placeholder.example"})
    seen: list = []

    def fakeDownload(skill_id, url, dest):
        seen.append(url)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SKILL.md").write_text("---\nname: Remote X\ndescription: d\n---\n\n正文\n",
                                       encoding="utf-8")
        return None

    monkeypatch.setattr(msrc, "downloadAndExtractRefusal", fakeDownload)

    task = _importer(tmp_path).import_skill("remote--x")

    assert task.status.value == "completed", task.error_message
    assert seen == [PLACEHOLDER_URL], f"远端那一腿没被走到：{seen}"


# ── 3. 丙：读面不再凭空造地址 ──


def test_searchSkills_stopsFabricatingDownloadUrl(tmp_path, store):
    store.create({"skill_id": "no-url", "name": "No Url", "version": "1.0.0", "description": "d"})
    rows = {s.skill_id: s for s in _importer(tmp_path).search_skills()}

    assert "no-url" in rows
    assert rows["no-url"].download_url == "", (
        f"目录里没有地址却被拼出一个来（实得 {rows['no-url'].download_url!r}）："
        "读数造假，且让安装闸的输入永远看着「有来源」")


# ── 4. 退役：占位域名与构造参数都不许留在生产码 ──


def test_placeholderMarketUrlAndCtorArgRetired():
    """退役判据只量**代码行**：`#` 起的注释是路标，写明"过去这里挂着什么"正是它的职责。

    （按行剔注释而不是整文件子串扫——否则上一批留在 market_store 里那句历史说明会把本格
    永久钉死在红上，后来者为了灭红只能去删证据，形态集 374/414 同族。）
    """
    import re

    for rel in ("neurova/skills/market_importer.py", "neurova/skills/market_store.py"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert len(text) > 500, f"{rel} 读到的面小到不可能是在验东西"
        code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))
        assert "api.neurova.dev" not in code, f"{rel} 的代码行里仍挂着那个从不存在的市场域名"

    ctor = re.search(r"def __init__\(self, skills_dir: Path([^)]*)\)",
                     (REPO_ROOT / "neurova/skills/market_importer.py").read_text(encoding="utf-8"))
    assert ctor is not None, "导入器构造签名找不到了——本格的锚点得跟着改，不是把判据放宽"
    assert "market_url" not in ctor.group(1), (
        f"读点退役了，构造参数却还留着（实得 {ctor.group(1)!r}）——写口无人读就是断点")


def test_staleDeadUrlOnOwnSeedIsCleared(tmp_path, monkeypatch):
    """丙 的第二个命中点：存量部署里那些旧行不会自己变干净。

    本批把「凭空拼一个地址」那句拆了、种子里那条死地址也没再写，但**已经躺在 catalog 文件里**
    的死值还在，读面照样显示一个能骗人的来源。所以收口必须同时管存量：本仓自带条目（种子＋内置表）
    里不属任何注册源的 `download_url`，载入时清成空串。
    """
    import neurova.skills.market_sources as msrc

    monkeypatch.setattr(msrc, "is_remote_market_url", lambda url: "skills.aliyun.com" in url)
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([
        {"skill_id": "web-search", "name": "Web Search", "version": "1.2.0", "description": "d",
         "download_url": "https://dead-market.example.invalid/web-search/download"},
        {"skill_id": "code-analysis", "name": "Code Analysis", "version": "2.0.1", "description": "d",
         "download_url": "https://skills.aliyun.com/ca/download"},
        {"skill_id": "aliyun--keep", "name": "Keep", "version": "1.0.0", "description": "d",
         "download_url": "https://other.example.invalid/keep.zip"},
    ]), encoding="utf-8")

    store = MarketStore(catalog_path=catalog)

    assert store.get("web-search")["download_url"] == "", "自带条目上的死地址没被清"
    # 反向控制一：自带条目挂的是**已注册源**，不许被一起清掉
    assert store.get("code-analysis")["download_url"] == "https://skills.aliyun.com/ca/download"
    # 反向控制二：不是本仓自带的条目（admin/远端同步来的）一个字都不碰
    assert store.get("aliyun--keep")["download_url"] == "https://other.example.invalid/keep.zip"
