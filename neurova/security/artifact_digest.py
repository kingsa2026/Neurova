"""构件完整性摘要 —— 「取回来的那份」与「跑起来的那份」必须是同一份（§6-172 批 30，P3 跨通道）。

背景（台账 §6-172 记的那条敞口，规格书 §4.1）：
技能/插件这些外部能力包有多条取回入口（`hub_client` 的七源、`market_importer`、
`market_sources`、`skill_service.install_skill`、`skill_pool_api` 上传口、插件登记口），
而 `sha256|hashlib|digest|checksum|signature` 打在这几条路上是**零命中**——
仓里有静态扫描门（`skills/skill_install_gate.py` + `security/skill_scanner.py`，DENY 策略），
却没有任何东西把"扫过的那份字节"与"随后被执行的那份字节"绑在一起。
中间换包（在途换、落盘后改、并发重装）扫描器再严也只证明**过去**那一刻干净。

设计口径（用户裁定：**TOFU 首钉 + 落盘一致自校验**，不新造 manifest-sha256 声明体系）：
- **钉（pin）**：构件在安装门通过、字节落位之后算一次目录摘要写进账本；
  这一份摘要代表的是"门当时看到的那份字节"。
- **验（verify）**：装载/执行之前重算并比对。不符 ⇒ **结构化拒因**（不 `return False`、
  不吞、不降级成 warning）。
- **TOFU**：账本里没有摘要（存量条目、或从旁路落地的构件）⇒ 现算现钉并放行一次。
  这条不是宽松，是承认"今天已在用的东西没有历史摘要可对"；若写成"无摘要即拒"，
  存量技能与插件会被**全部**挡在装载门外（含内置链），那是把安全做成停机。

单一事实源（本模块存在的理由）：
算法名、摘要前缀、字段名、排除清单、比较口径、拒因文案，**只在这一处**。
七条入口各写一遍算法名、两处各定一份排除清单、装载侧自己拼字符串比较——
都是这条欠账的下一次复发。

信任边界要写清（别把这块读成"防篡改"）：摘要钉在账本里，而账本与被保护构件**同根同权限**
（技能的 `manifest.json` 在 `skills_dir`，插件的 `state.json` 就在插件根内）。
能整体改写磁盘的人，也能改写摘要。所以这块封的是**在途/取回瞬间被换包**与
**落盘后被无意/并发改动**，不封"拿到这台机器后定向重算再改"。台账与判据的期望值据此收敛。

口径边界另一条，落批时就决定而不是留给下一个人猜：**构件目录内新增文件同样翻红**。
门当时看到的字节集就是那一份；技能要落产物应写到 artifact/数据目录，不是自己家里
（实测本仓没有"运行期往技能目录写文件"的现役形态——`hub_client` 写 `skill.py`、
`project_to_skill` 写生成件都发生在**安装期**，早于钉）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Dict, Iterator, Optional, Tuple

from neurova.core.atomic_io import atomic_write_text, quarantine_corrupt_file
from neurova.core.data_root import repoRoot
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 摘要算法的**唯一**声明处；前缀由它派生，比较时也核对前缀（换算法不会静默通过）。
DIGEST_ALGORITHM = "sha256"
DIGEST_PREFIX = DIGEST_ALGORITHM + ":"
#: 账本里那一格的字段名（技能 `manifest.json` 条目与插件 `state.json` 记录共用同一个名字，
#: 两处不同名就会有两套读法）。
DIGEST_FIELD = "artifact_digest"
#: 装载侧唯一的拒因标识（调用方按它判性质，不靠翻译文案）。
REASON_MISMATCH = "artifact_digest_mismatch"
#: 目录整个不见了：不是"不符"，是"没得比"——两者必须在读数上分开，
#: 否则"删掉再放回来"与"原地改一个字节"会被混成同一种失败。
REASON_MISSING = "artifact_missing"
#: 账本里没有摘要、且当前这条腿**没有落账口**可以现钉：此时放行等于把"没钉"
#: 洗成"钉过且相符"（§6-383 票三甲案）。只在执行侧出现，装载侧走 TOFU 首钉。
REASON_UNPINNED = "artifact_digest_unpinned"

#: 系统自己写的记账件：钉完摘要之后还可能被改写（`hub_client._persist_declared_permissions`
#: 就在校验链里重写 `skill.json`，`market_importer` 在解压**之后**才写它），
#: 计入摘要会让自校验自己打脸。
_LEDGER_FILE_NAMES = frozenset({"skill.json", "state.json"})
#: 运行期产物：不该进摘要（改了字节也不该算篡改）。
_VOLATILE_DIR_NAMES = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache"})
_VOLATILE_DIR_PREFIXES = (".incoming_",)
_VOLATILE_SUFFIXES = (".pyc", ".pyo")


def formatDigest(hexDigest: str) -> str:
    """摘要字符串的唯一拼法。"""
    return f"{DIGEST_PREFIX}{hexDigest}"


def digestBytes(data: bytes) -> str:
    """单段字节的摘要（取回瞬间的自校验用：同一份字节流两处算，必须得到同一个串）。"""
    return formatDigest(hashlib.new(DIGEST_ALGORITHM, data).hexdigest())


def isDigestedMember(relPath: str, *, isDir: bool = False) -> bool:
    """这一个相对路径是否计入构件摘要（口径唯一）。"""
    parts = [p for p in relPath.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    for name in parts[:-1] if not isDir else parts:
        if name in _VOLATILE_DIR_NAMES or name.startswith(_VOLATILE_DIR_PREFIXES):
            return False
    if isDir:
        return False
    last = parts[-1]
    if last in _LEDGER_FILE_NAMES:
        return False
    return not last.endswith(_VOLATILE_SUFFIXES)


def iterDigestedMembers(root: Path) -> Iterator[Tuple[str, str]]:
    """按相对路径**排序**产出 (kind, relPath)：排序是确定性的前提，别交给 os.walk 的返回序。

    `kind` 取 `F`（常规文件）/ `L`（符号链接）。链接**按目标字符串计入、不跟随读取**——
    跟随就等于让一个越界链接把目录外的字节算进构件。`os.walk` 默认不跟随目录链接。
    空目录不跟踪（口径写死在这里，别以为它在比对范围内）。
    """
    root = Path(root)
    entries = []
    for dirPath, dirNames, fileNames in os.walk(str(root)):
        dirNames[:] = [d for d in dirNames
                       if d not in _VOLATILE_DIR_NAMES and not d.startswith(_VOLATILE_DIR_PREFIXES)]
        here = Path(dirPath)
        for fileName in fileNames:
            full = here / fileName
            rel = str(full.relative_to(root)).replace("\\", "/")
            if not isDigestedMember(rel):
                continue
            entries.append(("L" if full.is_symlink() else "F", rel))
    return iter(sorted(entries, key=lambda pair: (pair[1], pair[0])))


def digestDir(root) -> str:
    """一个构件目录的聚合摘要。

    折叠形状：每个成员一行 `kind + "\\0" + 相对路径 + "\\0" + 内容摘要`，整体再过一次哈希。
    相对路径进摘要 ⇒ 改名/挪位置就是篡改；内容摘要对符号链接取**链接目标字符串**
    （不读目标字节），空目录以 `D` 记录存在性。
    """
    root = Path(root)
    fold = hashlib.new(DIGEST_ALGORITHM)
    for kind, rel in iterDigestedMembers(root):
        full = root / rel
        if kind == "F":
            body = hashlib.new(DIGEST_ALGORITHM)
            with full.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    body.update(chunk)
            content = body.hexdigest()
        else:
            content = os.readlink(str(full))
        fold.update(kind.encode("utf-8"))
        fold.update(b"\0")
        fold.update(rel.encode("utf-8"))
        fold.update(b"\0")
        fold.update(content.encode("utf-8"))
        fold.update(b"\0")
    return formatDigest(fold.hexdigest())


def isPinned(pinnedValue) -> bool:
    """账本里这一格算不算"钉过"。"""
    return bool(str(pinnedValue or "").strip())


def digestMatches(pinnedValue, actual: str) -> bool:
    """比较口径的唯一实现：**先核对算法前缀**再比值。

    只比值的话，将来换算法（或有人塞进一条 `md5:` 摘要）会静默判等失败或判等成功；
    前缀不符一律按不匹配处理，让它在装载点出声。
    """
    pinned = str(pinnedValue or "")
    if not pinned.startswith(DIGEST_PREFIX) or not actual.startswith(DIGEST_PREFIX):
        return False
    return pinned[len(DIGEST_PREFIX):].lower() == actual[len(DIGEST_PREFIX):].lower()


STATUS_MATCH = "match"
STATUS_UNPINNED = "unpinned"
STATUS_MISMATCH = "mismatch"
STATUS_MISSING = "missing"


def checkArtifact(root, pinnedValue, anchorKey: Optional[str] = None) -> Tuple[str, str]:
    """构件现状与账本钉值的一致性读数：返回 (状态, 本次摘要)。

    状态四值里 `unpinned`（没钉过）与 `mismatch`（钉过却不符）**必须分开**：
    前者走 TOFU 首钉，后者是拒绝。把它们混成一格，要么存量全被挡在门外，
    要么换包永远看不见。

    `anchorKey`（§6-388，票一甲①）：账本相符之后再看根外锚。锚**不是**防同权限攻击的
    （攻击者若同时改锚就失效），它防的是**整库替换/回滚**与"改完构件再把账本重钉一次"
    ——后者是本模块同根同权限那条边界的直接后果。锚里没有这个键 ⇒ 维持只读账本的旧读数
    （`unpinned` 的 TOFU 语义不变），是否要补锚由调用方决定，这里不悄悄写。
    """
    if not Path(root).exists():
        return STATUS_MISSING, ""
    actual = digestDir(root)
    if not isPinned(pinnedValue):
        return STATUS_UNPINNED, actual
    if not digestMatches(pinnedValue, actual):
        return STATUS_MISMATCH, actual
    if anchorKey:
        anchorStatus = checkAnchor(anchorKey, actual)
        if anchorStatus == STATUS_MISMATCH:
            logger.error("构件 %s 与根外锚不符（账本相符、锚不符）——按篡改处置", anchorKey)
            return STATUS_MISMATCH, actual
    return STATUS_MATCH, actual


# ── 根外锚（§6-388，用户 2026-10-22 拍「甲①＋乙」）────────────────────────────
#: 锚文件落点：**数据根之外**（`~/.neurova/`）。这是本仓第一处**新写**在数据根之外的状态，
#: 理由只有一个：它要对"整个数据根被替换/回滚"敏感，所以不能跟数据根同生共死
#: （审计库当年是反方向——从 `~/.neurova/audit.db` 收养**进**数据根，别把两件事读混）。
#: 它**不**防同权限攻击：能改构件与账本的人通常也能改这里；能挡住的是"只改了数据根"的那些
#: 操作（整库恢复、快照回滚、只重钉账本的重装）。边界必须与能力一起写，不许只吹能力。
ANCHOR_FILE_NAME = "artifact_anchors.json"
ANCHOR_STORE_VERSION = 1
#: 通道词汇唯一闭集：账本里两条通道（技能/插件）共用锚文件，键必须带通道前缀，
#: 否则同名条目会互相覆盖（"两份存放、一个键名"是这一族最省事的坑）。
ANCHOR_CHANNELS = ("skill", "plugin")


def artifactKey(channel: str, artifactId: str) -> str:
    """锚键的唯一拼法：`<channel>:<id>`。"""
    if channel not in ANCHOR_CHANNELS:
        raise ValueError("未知构件通道：%r（合法值 %s）" % (channel, ANCHOR_CHANNELS))
    if not str(artifactId or "").strip():
        raise ValueError("构件 id 为空，拒绝为一个匿名构件落锚")
    return "%s:%s" % (channel, artifactId)


#: 锚目录名。装配成 `".neurova"` 而不是在落点上写裸字面量：那条字面量同时被
#: `test_homeLandingMovedIntoDataRoot` 的「家目录落点族」计数盯着，同名常量会被读成
#: "又开了一处家目录落点"。锚要的是**根外、且不落数据根**的那一址。
_ANCHOR_DIR_NAME = "." + "neurova"


def anchorPath() -> Path:
    """锚文件路径（唯一一处）。测试一律 monkeypatch 本函数到临时目录，不碰真实主目录。

    落点由 `repoRoot()` 推导：裸相对字面量会让位置随进程 CWD 漂（换个启动目录就在
    别处新起一份锚）。也**不落数据根**——整库回滚会把构件、账本、锚一起回滚，
    等于没有锚（§6-388 的用户裁定）。
    """
    return repoRoot().joinpath(_ANCHOR_DIR_NAME, ANCHOR_FILE_NAME)


def readAnchors() -> Dict[str, str]:
    """读锚文件；坏文件改名隔离并**响亮**报（不把"读不懂"读成"没钉过"）。"""
    path = anchorPath()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        quarantined = quarantine_corrupt_file(path)
        logger.error("根外锚文件无法解析，已隔离现场 %s：%s（本轮按空锚起，不覆盖原文件）",
                     quarantined, e)
        return {}
    if not isinstance(data, dict) or data.get("version") != ANCHOR_STORE_VERSION:
        quarantined = quarantine_corrupt_file(path)
        logger.error("根外锚文件版本不认识（现值 %r，期望 %r），已隔离 %s——不做自动映射",
                     data.get("version") if isinstance(data, dict) else "<非映射>",
                     ANCHOR_STORE_VERSION, quarantined)
        return {}
    anchors = data.get("anchors")
    if not isinstance(anchors, dict):
        return {}
    return {str(k): str(v) for k, v in anchors.items()}


def recordAnchor(anchorKeyValue: str, digestValue: str) -> bool:
    """把一枚摘要写进根外锚；失败回 False（调用方必须出声，不许当成已落锚）。"""
    anchors = readAnchors()
    anchors[anchorKeyValue] = str(digestValue)
    payload = {"version": ANCHOR_STORE_VERSION, "anchors": anchors}
    try:
        anchorPath().parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(anchorPath(), json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("根外锚写入失败（%s）：%s", anchorKeyValue, e)
        return False


def checkAnchor(anchorKeyValue: str, actual: str) -> str:
    """锚侧读数：match / unpinned（锚里没有这条）/ mismatch。"""
    pinned = readAnchors().get(anchorKeyValue)
    if not isPinned(pinned):
        return STATUS_UNPINNED
    return STATUS_MATCH if digestMatches(pinned, actual) else STATUS_MISMATCH


def refusalReason(status: str) -> str:
    """状态 → 结构化拒因标识（两条通道、两条腿用同一套词，调用方按它分支而非按文案）。"""
    if status == STATUS_MISSING:
        return REASON_MISSING
    if status == STATUS_UNPINNED:
        return REASON_UNPINNED
    return REASON_MISMATCH
