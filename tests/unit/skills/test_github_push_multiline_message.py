"""github_push 技能多行 commit message 的红灯测试（Windows git 坑 2）。

'-m' 参数内嵌换行在 Windows 命令行传参时被空格化——多行 message 必须
走 'git commit -F -' + stdin。
"""

import subprocess

import pytest

from neurova.skills.builtin.github_push.skill import GitHubPushSkill

#: 临时仓里 git 调用的预算唯一出处（毫秒级；此前本档三枚落点全无 `timeout=`＝无界等待）。
#: 取**低于全局 30s** 的 20s——fixture 体里的等待同样算在消费它的用例头上（常驻闸
#: `test_nestedPytestBudgetWallsAreOrdered.py` 按参数名把它归账过去），先到点的应当是子进程
#: 那条诚实的 TimeoutExpired，而不是 thread 法的全局墙（§6-402 批 K 口径）。
GIT_WALL_S = 20


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, encoding="utf-8",
                       timeout=GIT_WALL_S)
    git("init", "--quiet")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    (repo / "f.txt").write_text("hello", encoding="utf-8")
    return repo


@pytest.mark.asyncio
async def test_multiline_commit_message_preserved(repo):
    skill = GitHubPushSkill()
    skill.repo_path = repo
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True,
                   timeout=GIT_WALL_S)

    result = await skill._commit_changes("标题行\n\n正文第一段")

    assert result.success, result.error
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s%n%b", "-n1"],
        capture_output=True, encoding="utf-8", check=True,
        timeout=GIT_WALL_S)
    assert log.stdout.startswith("标题行\n")  # subject 独立成行
    assert "正文第一段" in log.stdout
    assert "标题行 正文第一段" not in log.stdout  # 未被空格化合并
