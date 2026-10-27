"""github_push 技能多行 commit message 的红灯测试（Windows git 坑 2）。

'-m' 参数内嵌换行在 Windows 命令行传参时被空格化——多行 message 必须
走 'git commit -F -' + stdin。
"""

import os
import subprocess

import pytest

from neurova.skills.builtin.github_push.skill import GitHubPushSkill

#: 临时仓里 git 调用的预算唯一出处（毫秒级；此前本档三枚落点全无 `timeout=`＝无界等待）。
#: 取**低于全局 30s** 的 20s——fixture 体里的等待同样算在消费它的用例头上（常驻闸
#: `test_nestedPytestBudgetWallsAreOrdered.py` 按参数名把它归账过去），先到点的应当是子进程
#: 那条诚实的 TimeoutExpired，而不是 thread 法的全局墙（§6-402 批 K 口径）。
GIT_WALL_S = 20


@pytest.fixture(autouse=True)
def _hermeticGitConfig(monkeypatch):
    """宿主 git 全局/系统配置不得漏进本档（与 `tests/unit/tools/test_git_tool.py` 同一口径）。

    被测执行体刻意继承 `os.environ`（真实凭据/代理是运行时依赖），于是宿主全局
    `commit.gpgsign=true` 会在 `git commit` 处炸 `error: gpg failed to sign the data`：
    提交根本没发生，判据红在"宿主配了签名代理"，不是红在"多行提交信息被空格化合并"。
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


@pytest.fixture
def repo(tmp_path):
    """临时仓，并把宿主的 git 全局/系统配置隔开（`tests/unit/tools/test_git_tool.py` 同一口径）。

    不隔开时，宿主全局 `commit.gpgsign=true` 会漏进本档起的每一次 `git commit`：
    `error: gpg failed to sign the data` ⇒ 提交根本没发生，判据红在"宿主配了签名代理"，
    而不是红在"多行提交信息被空格化合并"。被测对象是提交信息的形状，不是宿主的签名配置。
    """
    repo = tmp_path / "work"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_TERMINAL_PROMPT": "0"}
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, encoding="utf-8",
                       timeout=GIT_WALL_S, env=env)
    git("init", "--quiet")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    # 这条判据量的是**多行 message 逐字保留**，与签名无关：跑测机若开了全局
    # `commit.gpgsign=true`（本仓开发机就是），提交会因没有可用私钥失败，
    # 红成 "gpg failed to sign the data"——像 transport 坏了，实际只是签名。
    git("config", "commit.gpgsign", "false")
    (repo / "f.txt").write_text("hello", encoding="utf-8")
    return repo


@pytest.mark.asyncio
async def test_multiline_commit_message_preserved(repo):
    skill = GitHubPushSkill()
    skill.repo_path = repo
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True,
                   timeout=GIT_WALL_S,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull})

    result = await skill._commit_changes("标题行\n\n正文第一段")

    assert result.success, result.error
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s%n%b", "-n1"],
        capture_output=True, encoding="utf-8", check=True,
        timeout=GIT_WALL_S)
    assert log.stdout.startswith("标题行\n")  # subject 独立成行
    assert "正文第一段" in log.stdout
    assert "标题行 正文第一段" not in log.stdout  # 未被空格化合并
