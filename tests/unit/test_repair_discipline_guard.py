# -*- coding: utf-8 -*-
"""项目修复纪律守卫 —— TDD 红绿灯 + 修复教义必须落在"项目配置"里。

Issue #68 追加要求：项目配置中必须写明
1. 代码编写与 bug 修复严格走 TDD 红绿灯（先红 → 再绿 → 重构）；
2. 修 bug 要放大视角；
3. 修根因（禁止 consumer-only guard）；
4. 不得抹除或规避表面报错（禁止吞异常、加兜底默认来消错）。

为什么要有本守卫（根因，不是形状）：
要求此前只散落在 docs/ 的计划与 spec 里，或有引用无落点——
`AGENTS.md` 被全仓 90+ 处引作"修复教义"的权威文件，却被 `.gitignore`
的 `/*.md` + 三条白名单（README/CONTRIBUTING/SECURITY）吞掉，从未入库；
`.cnb/settings.yml` 的 NPC 角色 prompt 是 NPC 每次被 @ 时真正加载的
系统提示（平台配置期唯一必达通道），此前只写"读懂需求再动手"，
对 TDD / 根因 / 放大视角 / 禁抹除一字未提。
于是"要求"只存在于人的记忆里，换一次会话即失效。

守卫锁三处机器可读落点：
- `.cnb/settings.yml` 每个 NPC 角色 prompt（被 @ 即加载）
- `/AGENTS.md`（引用方认定的权威文件，必须真实存在且可入库）
- `CONTRIBUTING.md` 测试纪律节（人类贡献者入口）
"""
import io
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS = PROJECT_ROOT / "AGENTS.md"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
CONTRIBUTING = PROJECT_ROOT / "CONTRIBUTING.md"
GITIGNORE = PROJECT_ROOT / ".gitignore"

# 纪律四要点 → 判定关键词（任一缺失即判要求没写全）
REQUIRED_POINTS = {
    "TDD 红绿灯": ("红绿灯",),
    "放大视角": ("放大视角",),
    "修根因": ("根因",),
    "禁止抹除/规避表面报错": ("抹除",),
}


def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _missing_points(text: str) -> list:
    return [
        point for point, keys in REQUIRED_POINTS.items()
        if not any(k in text for k in keys)
    ]


@pytest.fixture(scope="module")
def roles():
    doc = yaml.safe_load(_read(SETTINGS)) or {}
    return (doc.get("npc") or {}).get("roles") or []


class TestNpcConfigCarriesDiscipline:
    """NPC 角色 prompt 是平台配置期唯一必达的指令通道。"""

    def test_roles_declared(self, roles):
        assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"

    def test_every_role_prompt_states_discipline(self, roles):
        bad = []
        for role in roles:
            name = (role or {}).get("name")
            prompt = (role or {}).get("prompt") or ""
            missing = _missing_points(prompt)
            if missing:
                bad.append(f"{name}: 缺 {missing}")
        assert not bad, (
            "NPC 角色 prompt 未写明修复纪律（被 @ 时该角色不会知道这条要求）:\n  "
            + "\n  ".join(bad)
            + "\n四要点：TDD 红绿灯 / 放大视角 / 修根因 / 禁止抹除或规避表面报错。"
        )


class TestDisciplineBlockHasSingleSource:
    """档位角色各带一份纪律块 —— 抄两份就有漂移；此处锁"逐字一致"。"""

    @staticmethod
    def _discipline_block(prompt: str) -> str:
        start = prompt.find("修复纪律")
        assert start != -1, "prompt 无「修复纪律」块"
        end = prompt.find("工作方式：", start)
        return prompt[start:end if end != -1 else len(prompt)].strip()

    def test_discipline_block_identical_across_roles(self, roles):
        blocks = {
            (r or {}).get("name"): self._discipline_block((r or {}).get("prompt") or "")
            for r in roles if (r or {}).get("prompt")
        }
        distinct = set(blocks.values())
        assert len(distinct) == 1, (
            "档位角色的修复纪律块出现漂移（同一纪律抄成多份就会各写各的）: "
            f"{ {k: len(v) for k, v in blocks.items()} }\n"
            "改纪律时两侧必须逐字同步。"
        )


class TestAgentsDocIsAuthoritative:
    """引用方认定的权威文件必须真实存在，且不得被 .gitignore 吞掉。"""

    def test_agents_md_exists(self):
        assert AGENTS.is_file(), (
            "/AGENTS.md 不存在——全仓 90+ 处以它为「修复教义」权威出处，"
            "缺文件等于纪律没有事实源。"
        )

    def test_agents_md_not_gitignored(self):
        """被 .gitignore 吞掉 = 只在本机存在，克隆/CI 上必然消失（历史事故形态）。"""
        if not (PROJECT_ROOT / ".git").exists() or not shutil.which("git"):
            pytest.skip("非 git 工作区 / 无 git")
        proc = subprocess.run(
            ["git", "check-ignore", "-q", "AGENTS.md"],
            cwd=str(PROJECT_ROOT), capture_output=True,
        )
        assert proc.returncode != 0, (
            "AGENTS.md 仍被 .gitignore 忽略（/*.md 白名单缺 !AGENTS.md）——"
            "文件写在本机也进不了仓库。"
        )

    def test_agents_md_states_discipline(self):
        text = _read(AGENTS)
        missing = _missing_points(text)
        assert not missing, f"/AGENTS.md 未写明: {missing}"

    def test_agents_md_has_numbered_repair_doctrine(self):
        """引用方按"修复教义第 N 条"编号引用，编号缺位则引用继续悬空。"""
        text = _read(AGENTS)
        assert "修复教义" in text, "/AGENTS.md 缺「修复教义」章（90+ 处引用它的编号）"
        # 1 / 2 / 5 三条的编号已在 docs/ 中被逐字引用（根因修复 / 净 LOC / 放大视角），
        # 编号缺位 → 这些引用继续悬空。其余条目编号可演进，故只锁被引用过的三处。
        for n in ("1", "2", "5"):
            assert f"第 {n} 条" in text, f"/AGENTS.md 缺「修复教义第 {n} 条」（仓库内被逐字引用中）"

    def test_gitignore_keeps_agents_md(self):
        lines = [ln.strip() for ln in _read(GITIGNORE).splitlines()]
        assert "!AGENTS.md" in lines, (
            ".gitignore 的 /*.md 白名单未放行 AGENTS.md："
            "根目录 AI 指令文件必须在白名单内（与 README/CONTRIBUTING/SECURITY 同列）。"
        )


class TestContributingCarriesDiscipline:
    def test_testing_section_states_red_green(self):
        text = _read(CONTRIBUTING)
        assert "红绿灯" in text, (
            "CONTRIBUTING.md 测试纪律节未写 TDD 红绿灯——贡献者入口看不到这条要求。"
        )
