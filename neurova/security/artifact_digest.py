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
import os
from pathlib import Path
from typing import Iterator, Tuple

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


def checkArtifact(root, pinnedValue) -> Tuple[str, str]:
    """构件现状与账本钉值的一致性读数：返回 (状态, 本次摘要)。

    状态四值里 `unpinned`（没钉过）与 `mismatch`（钉过却不符）**必须分开**：
    前者走 TOFU 首钉，后者是拒绝。把它们混成一格，要么存量全被挡在门外，
    要么换包永远看不见。
    """
    if not Path(root).exists():
        return STATUS_MISSING, ""
    actual = digestDir(root)
    if not isPinned(pinnedValue):
        return STATUS_UNPINNED, actual
    return (STATUS_MATCH if digestMatches(pinnedValue, actual) else STATUS_MISMATCH), actual


def refusalReason(status: str) -> str:
    """状态 → 结构化拒因标识（两条通道用同一套词，调用方按它分支而非按文案）。"""
    if status == STATUS_MISSING:
        return REASON_MISSING
    return REASON_MISMATCH
