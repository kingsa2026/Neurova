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

import os
from pathlib import Path

DATA_ROOT_ENV = "NEUROVA_DATA_DIR"

# 本文件在 `neurova/core/` 下：parents[0]=core, [1]=neurova, [2]=仓库根。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = "data"


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
