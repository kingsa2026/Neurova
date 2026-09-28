"""数据根的唯一装配点：`data/` 是谁、在哪儿。

为什么要收这一处：`data/` 这个落点此前被**每个模块自己拼**——`Path("data")`（相对
CWD）、`Path(__file__).resolve().parents[N] / "data"`（反推层数）、
`getattr(config, "DATA_DIR", "data")`（读一个可能不存在的配置常量）三种口径并存。
口径一多，"换个工作目录就换个库"就没人拦得住：审计 2026-09-21 §7 里那份 71,831 行的
仓库根 `neurova_memories_persist.db`，正是 CWD 相对默认值留下的物证。

纪律：

- **根必须绝对**。相对路径的默认值等于把落点交给进程的启动目录。
- **可注入**。`NEUROVA_DATA_DIR` 是唯一注入口（测试隔离与桌面部署各指向自己的目录）；
  注入非法值（相对路径 / 空串）当场失败，不静默回落——回落到仓库 `data/` 就是
  测试污染生产的经典路径。
- **按层数推导只准出现在本模块**。别处要这个根一律 `get_data_root()`；
  `parents[3]` 这类写法的层数随文件移动而变，是下一轮漂移的来源。
"""

from __future__ import annotations

import functools
import os
import shutil
from pathlib import Path

from neurova.core.logger import get_logger

DATA_ROOT_ENV = "NEUROVA_DATA_DIR"

# 本文件在 `neurova/core/` 下：parents[0]=core, [1]=neurova, [2]=仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = "data"

logger = get_logger(__name__)


def get_data_root() -> Path:
    """数据根（调用时解析——注入才对延迟装配与子线程生效）。"""
    injected = (os.environ.get(DATA_ROOT_ENV) or "").strip()
    if not injected:
        return _REPO_ROOT / _DEFAULT_DATA_DIR
    target = Path(injected).expanduser()
    if not target.is_absolute():
        raise ValueError(
            "%s 必须是绝对路径，收到 %r——相对路径会让数据落点随进程 CWD 漂移，"
            "这正是散落污染的成因。" % (DATA_ROOT_ENV, injected)
        )
    return target


def get_agent_data_dir(agent_id: str = "") -> Path:
    """单个 agent 的数据目录（agent_id 空值回落 default）。

    认知图谱等**按 agent 分目录**的数据面走这里，与 `agent_workspaces` 的
    `<root>/<agent>/` 形状对齐；写它的地方与删它的地方必须都取这个函数，
    否则 CWD 一变删除端就删不掉。
    """
    from neurova.core.agent_workspaces import _DEFAULT_AGENT_ID

    return get_data_root() / (agent_id or _DEFAULT_AGENT_ID)


def ensure_agent_data_dir(agent_id: str = "") -> Path:
    """取 agent 数据目录并保证它存在（写入端与删除端共用同一处推导）。

    与 `get_agent_data_dir` 分开是因为用途不同：读路径问"在哪儿"，
    写路径问"在哪儿、建好它"。两个问题合一个函数，读路径就会顺手建目录。
    """
    target = get_agent_data_dir(agent_id)
    target.mkdir(parents=True, exist_ok=True)
    return target


def dataPath(*parts: str) -> str:
    """数据根下的路径（字符串形态，供仍是字符串契约的调用方用）。"""
    return str(get_data_root().joinpath(*parts))


def callerPath(value: "str | os.PathLike[str] | None", *defaultParts: str) -> Path:
    """调用方显式指定的落点原样承载；未指定时落数据根下的 `defaultParts`。

    与 `resolveDataPath` 的分工：后者是**默认值**口径（相对名一律落数据根），
    本函数管"调用方给了就用它的"——显式值（相对、绝对、注入的临时目录）
    一字不改。把两者混成一个表达式（`resolveDataPath(x or "y")`）会让显式
    入参被当成默认名改写，测试隔离目录与部署指定的落点都会当场漂移。
    """
    if value:
        return Path(value).expanduser()
    return get_data_root().joinpath(*defaultParts)


def resolveDataPath(value: str | os.PathLike[str]) -> Path:
    """把落点归一到数据根。

    - **绝对路径原样放行**：调用方注入与测试隔离的显式落点不受影响。
    - **相对名按数据根解析**：`"webhooks.json"` / `"storage/runs.db"` 都落数据根内。

    各模块的默认值一律走这里，不要在本地再拼 `data/`——那正是"换个工作目录就换个库"的入口。
    """
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    return get_data_root() / candidate


def repoRoot() -> Path:
    """仓库根：随代码走的资产（配置、模型、agents.json）的锚点。

    与 `get_data_root()` 的分工：

    - 数据根管**运行期产物**（库、日志、上传件、轨迹）——部署时挂卷、可注入；
    - 仓库根管**随代码走的资产**——镜像里就带、不随 CWD 变，也不受数据根注入影响。

    两者不能混：把 `models/` 或 `config/` 归到数据根，容器里就找不到模型；
    把运行期产物按仓库根拼，换部署目录就丢数据。
    """
    return _REPO_ROOT


def repoAsset(*parts: str) -> Path:
    """仓库根下的资产路径（配置 / 模型 / 前端清单）。"""
    return _REPO_ROOT.joinpath(*parts)


def dataLanding(*parts: str, legacy: "tuple | None" = None) -> Path:
    """运行期产物的落点：数据根下的 `parts`，并在空缺时收养仓库根旧物。

    这是"运行期产物"的统一入口（库、日志、上传件、轨迹、密钥）。旧落点默认与
    新落点同名同层（`"storage"` → 仓库根 `storage/`）；形状不同的面用 `legacy=`
    显式给出旧相对路径（如 `infrastructure.json` 的旧落点是 `config/` 下的同名文件）。
    没有旧物可收养的新面传 `legacy=()`——省一次查盘。
    """
    target = get_data_root().joinpath(*parts)
    legacyParts = parts if legacy is None else legacy
    if legacyParts:
        adoptLegacyLanding(target, *legacyParts)
    return target


@functools.lru_cache(maxsize=256)
def nameConflictOnce(legacy: str, target: str) -> None:
    """两侧同时在场时点名一次（同一对落点不重复刷屏）。

    落点解析在每次读写路径上都会被调用，逐次告警会把同一条冲突打成每请求一行；
    但**不点名**又等于让旧物里的内容无声失效 —— 故按落点对去重后告警。
    """
    logger.warning(
        "旧落点仍在场且新落点已有同名物，旧物不覆盖：%s（新落点 %s 为事实源；"
        "旧物需人工核对后处置，例如确认无差异再删除）", legacy, target,
    )


def adoptLegacyLanding(target: Path, *legacyParts: str) -> bool:
    """旧落点（CWD 相对时代的产物）搬进新落点，只为**空缺时救济**。

    旧落点按**仓库根**的相对路径给出（`"config"` / `("neurova", "data", "x.json")`）。
    形状不在仓库根下的面（例如"与主库同目录的配对文件"，其旧落点在旧主库旁边）
    用 `adoptLandingFrom()` 直接给出绝对旧落点——两者的收养语义逐字相同，
    实现也只此一份。

    - 新落点已在 ⇒ 原样返回 False（旧物不覆盖新物，避免把已生效的配置盖回旧版），
      但**两侧同时在场必须点名**：那是"同一份东西有两个落点"的实况，
      不点名就等于让旧物里的内容（可能是用户以为在生效的配置）无声失效；
    - 旧落点不存在 ⇒ 返回 False（无旧物可收）；
    - 搬迁失败 ⇒ 返回 False 并留下告警，**不抛**：收养是救济，不该阻断启动。

    调用点一律写在"落点解析"处，不写在业务路径里——收养只发生一次，
    之后事实源仍是新落点。
    """
    return adoptLandingFrom(target, legacyLanding(*legacyParts))


def legacyLanding(*legacyParts: str) -> Path:
    """旧落点的**绝对路径**（仓库根 + 相对段）——唯一推导，供收养端与排查端共用。

    为什么要有它：调用方若 `from ... import repoRoot` 再自己拼，就是拿了一份
    **绑定在导入时刻**的函数引用 —— 仓库根被替换（测试隔离、打包态排查）时
    它照样指向老地方，收养静默搬错对象。经本函数取，仓库根的解析点始终只有一处。
    """
    return repoRoot().joinpath(*legacyParts)


def adoptLandingFrom(target: Path, legacy: Path) -> bool:
    """收养的**唯一实现**：把 `legacy` 处的东西搬到 `target`（空缺时才动）。

    与 `adoptLegacyLanding` 的分工只在"旧落点怎么算出来"：那个按仓库根推，
    本函数由调用方给绝对路径。收养规则（不覆盖、冲突点名、失败不抛）逐字同一份，
    两处各写一遍就是两条可独立漂移的救济语义。
    """
    if not legacy.exists():
        return False
    if target.exists():
        nameConflictOnce(str(legacy), str(target))
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    except OSError as exc:
        logger.warning("旧落点 %s 收养失败（保留原位，新落点照常使用）: %s", legacy, exc)
        return False
    logger.info("旧落点已收养：%s → %s", legacy, target)
    return True


def nameConflictOnceFor(target: Path, legacy: Path) -> None:
    """按落点对点名两侧冲突（供成对落点的第二半复用同一去重口径）。"""
    nameConflictOnce(str(legacy), str(target))
