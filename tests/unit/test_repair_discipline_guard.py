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
import re
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


# ============================================================================
# 并发收口（Issue #68 双 PR 冲突）—— 纪律只允许一个事实源，且该源必须可达
# ============================================================================
# 背景：另一会话的 PR #70 另造了 docs/0-index/DEVELOPMENT_RULES.md 作为"唯一"
# 事实源，并把被 97 处引用的 /AGENTS.md 判为"已移除"、只清掉入口 2 处引用。
# 结果是第二套纪律体系与 95 处悬空引用共存——正是本次要收口的东西。
# 本节锁：单一事实源 + 被引用文件可达 + 索引入口可解析。
DR_FULES = PROJECT_ROOT / "docs" / "0-index" / "DEVELOPMENT_RULES.md"
INDEX = PROJECT_ROOT / "docs" / "INDEX.md"

# Issue #68 明列的八项要求 → 判定关键词（每个事实源必须全覆盖）
ISSUE_68_REQUIREMENTS = {
    "中文交流": ("中文交流", "一律使用中文", "使用中文"),
    "TDD 红绿灯": ("红绿灯",),
    "修根因/放大视角": ("放大视角",),
    "禁抹除表面报错": ("抹除",),
    "闭环": ("闭环",),
    "禁引用第三方/原创": ("第三方", "原创"),
    "camelCase 命名": ("camelCase",),
    "PascalCase 命名": ("PascalCase",),
    "规则文档归 docs": ("docs/",),
    "测试归唯一测试根": ("tests/",),
}


class TestDisciplineHasExactlyOneSource:
    """两套纪律事实源必须收口为一份——这也是 Issue #68 要收的口。"""

    def test_no_parallel_rules_document(self):
        assert not DR_FULES.exists(), (
            "docs/0-index/DEVELOPMENT_RULES.md 与 /AGENTS.md 构成第二套纪律事实源。\n"
            "纪律只允许一处定义（修复教义第 6 条·单一事实源）：保留被全仓 97 处引用、\n"
            "且被工作区文档收集器读取的 /AGENTS.md，把其独有条款并入该文件。"
        )

    def test_agents_md_covers_all_issue_68_requirements(self):
        """唯一事实源必须覆盖 Issue #68 的全部要求，否则并入即丢条款。"""
        text = _read(AGENTS)
        missing = [
            name for name, keys in ISSUE_68_REQUIREMENTS.items()
            if not any(k in text for k in keys)
        ]
        assert not missing, (
            f"/AGENTS.md 未覆盖 Issue #68 要求: {missing}\n"
            "收口为单一事实源后，条款一处不能少。"
        )


class TestIndexEntryIsResolvable:
    """docs/INDEX.md 自称"唯一权威入口"，其阅读顺序指向的文件必须真实可达。"""

    @staticmethod
    def _reading_order_paths() -> list:
        """抓取阅读顺序里以 `/` 引用的根级文档相对路径。"""
        text = _read(INDEX)
        section = text.split("## 0. 阅读顺序", 1)[1].split("## 1.", 1)[0]
        return re.findall(r"`/([^`]+\.md)`", section)

    def test_reading_order_root_docs_exist(self):
        paths = self._reading_order_paths()
        assert paths, "阅读顺序未解析出任何根级文档引用（索引结构已变，请同步本守卫）"
        missing = [
            p for p in paths
            if not (PROJECT_ROOT / p).is_file()
            and not (PROJECT_ROOT / "docs" / p).is_file()
        ]
        assert not missing, (
            f"docs/INDEX.md 阅读顺序指向的文件不可达: {missing}\n"
            "索引自称文档体系唯一导航事实源，入口不可解析即纪律没有事实源。"
        )

    def test_index_has_no_empty_links(self):
        text = _read(INDEX)
        problems = []
        # 空标签 `` 或空目标 []() / []( ) 都是悬空形态
        for m in re.finditer(r"`{2}|\[[^\]]*\]\(\s*\)", text):
            line = text[: m.start()].count("\n") + 1
            problems.append(f"L{line}: {m.group(0)!r}")
        assert not problems, (
            "docs/INDEX.md 存在悬空链接（空标签/空目标）:\n  " + "\n  ".join(problems)
            + "\n请指向实际路径，不要用清空目标代替修复。"
        )


class TestEntryDocsHaveNoEmptyLinks:
    """入口文档不得用"清空链接目标"代替修复——与修复教义第 2 条同型（禁表面抹除）。"""

    ENTRY_DOCS = ("README.md", "CONTRIBUTING.md", "docs/INDEX.md")

    def test_no_empty_link_targets(self):
        problems = []
        for rel in self.ENTRY_DOCS:
            path = PROJECT_ROOT / rel
            if not path.is_file():
                continue
            text = _read(path)
            for m in re.finditer(r"\[[^\]]*\]\(\s*\)", text):
                line = text[: m.start()].count("\n") + 1
                problems.append(f"{rel}:L{line} {m.group(0)!r}")
        assert not problems, (
            "入口文档存在空目标链接 `[文字]()`（抹除目标而非修复）:\n  "
            + "\n  ".join(problems)
            + "\n请指向实际可达路径。"
        )
