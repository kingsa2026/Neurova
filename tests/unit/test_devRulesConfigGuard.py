# -*- coding: utf-8 -*-
"""开发准则配置守卫（docs/0-index/DEVELOPMENT_RULES.md + .cnb/settings.yml）。

锁定五件已定稿的协作红线，防规则只写在口头、配置漂移：

1. **规则文档唯一落点** —— 准则类文档只能放 docs/ 下，仓库根目录不得再出现
   RULES / CONVENTIONS / 编码规范之类平铺文件（历史上根目录散落过同类文档，
   最后被清理）。定位基准是 docs/0-index/DEVELOPMENT_RULES.md。
2. **NPC 人设必须带上协作红线** —— .cnb/settings.yml 每个角色的 prompt 都要
   写明中文交流、TDD 红绿灯、根因修复、闭环、原创性、Neurova 命名法六项；
   角色被 @ 时若无这些约束，NPC 会按平台默认风格自由发挥。
3. **测试目录单一** —— 全仓只有一个测试根目录，且按功能模块分子目录存放；
   新增第二个测试根（如 TEST/）或把用例平铺在测试根即报错。
4. **根目录悬空引用清零** —— CONTRIBUTING 等入口文档不得指向已不存在的
   AGENTS.md（规则文档统一在 docs/ 后，该文件不再存在），也不得留空链接。
5. **命名口径与收集口径一致** —— 用例名用驼峰（test[A-Z]* 已在 pyproject 的
   python_functions 放开），本守卫自身仍走 test_* 以自证收集规则改动后守得住。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULES_DOC = PROJECT_ROOT / "docs" / "0-index" / "DEVELOPMENT_RULES.md"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"

# 协作红线：关键词 → 命中任一即可视为该条已写明
REDLINE_KEYWORDS = {
    "中文交流": ("中文",),
    "TDD 红绿灯": ("TDD", "红绿灯", "红灯"),
    "根因修复": ("根因",),
    "闭环": ("闭环",),
    "原创性": ("原创", "第三方"),
    "Neurova 命名法": ("camelCase", "PascalCase", "驼峰", "帕斯卡"),
}

# 仓库根目录不得出现的准则类文档（大小写/中英混合均拦）
FORBIDDEN_ROOT_DOCS = (
    "RULES.md",
    "CONVENTIONS.md",
    "CODING_RULES.md",
    "开发规范.md",
    "开发准则.md",
    "编码规范.md",
)


def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _settings_roles():
    doc = yaml.safe_load(_read(SETTINGS))
    roles = ((doc or {}).get("npc") or {}).get("roles") or []
    assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
    return roles


class TestRulesDocIsSingleSourceHere:
    def test_rules_doc_exists_under_docs(self):
        assert RULES_DOC.exists(), (
            f"开发准则文档缺失: {RULES_DOC.relative_to(PROJECT_ROOT)}\n"
            "规则文档统一存放于 docs/，新增准则请落在该目录并在 docs/0-index/README.md 登记。"
        )

    def test_rules_doc_covers_every_redline(self):
        text = _read(RULES_DOC)
        missing = [
            name for name, keys in REDLINE_KEYWORDS.items()
            if not any(k in text for k in keys)
        ]
        assert not missing, (
            f"开发准则文档未覆盖以下红线: {missing}\n"
            "准则一旦少一条，NPC 与人类协作者就会各自发挥。"
        )

    def test_no_rules_doc_at_repo_root(self):
        found = sorted(
            name for name in FORBIDDEN_ROOT_DOCS
            if (PROJECT_ROOT / name).exists()
        )
        assert not found, (
            f"仓库根目录出现准则类文档: {found}\n"
            "规则文档必须统一存放于 docs/（唯一入口 docs/0-index/DEVELOPMENT_RULES.md）。"
        )

    def test_entry_docs_do_not_dangle_to_removed_agents_md(self):
        """入口文档不得再引用已不存在的根级 AGENTS.md（规则统一进 docs/ 的收口）。"""
        problems = []
        for rel in ("CONTRIBUTING.md", "README.md", "docs/INDEX.md", "docs/0-index/README.md"):
            path = PROJECT_ROOT / rel
            if not path.exists():
                continue
            text = _read(path)
            if "](AGENTS.md)" in text or "](#AGENTS.md)" in text:
                problems.append(f"{rel} → 仍指向已移除的 AGENTS.md")
            # 形如 [AGENTS.md]() 的空目标：文案还在，目标已被清空，同样算悬空
            if re.search(r"\[AGENTS\.md\]\(\s*\)", text):
                problems.append(f"{rel} → AGENTS.md 链接目标为空")
        assert not problems, (
            "入口文档存在悬空引用（规则文档改挂 docs/ 后未同步）:\n  " + "\n  ".join(problems)
            + "\n请统一指向 docs/0-index/DEVELOPMENT_RULES.md。"
        )


class TestNpcPersonaCarriesRedlines:
    def test_every_role_prompt_states_redlines(self):
        problems = []
        for role in _settings_roles():
            name = (role or {}).get("name") or "<unnamed>"
            prompt = (role or {}).get("prompt") or ""
            missing = [
                label for label, keys in REDLINE_KEYWORDS.items()
                if not any(k in prompt for k in keys)
            ]
            if missing:
                problems.append(f"{name}: 缺 {missing}")
        assert not problems, (
            "NPC 角色人设未写明协作红线（角色被 @ 时会按平台默认风格自由发挥）:\n  "
            + "\n  ".join(problems)
            + "\n红线清单见 docs/0-index/DEVELOPMENT_RULES.md，两份必须同步。"
        )


class TestTestRootIsSingleAndModular:
    def test_exactly_one_test_root(self):
        roots = sorted(
            p.name for p in PROJECT_ROOT.iterdir()
            if p.is_dir() and p.name.lower() == "tests"
        )
        assert roots == ["tests"], (
            f"测试根目录必须唯一且为 tests/，实际: {roots}\n"
            "需求口径中的 TEST 目录即本仓唯一测试根；整体更名属全仓路径迁移，"
            "须单独立项并同步 pyproject/CI/守卫，不要在配置波里顺手改。"
        )

    def test_rule_doc_states_the_single_test_root(self):
        text = _read(RULES_DOC)
        assert "tests/" in text, (
            "准则文档未写明测试根目录口径（应指向本仓唯一测试根 tests/）"
        )

    def test_module_subdirs_are_the_norm_not_flat_files(self):
        """测试按功能模块分子目录：平铺在测试根的文件数不得反超子目录数。"""
        root = PROJECT_ROOT / "tests"
        flat = [p for p in root.glob("test_*.py")]
        subdirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "__"))]
        assert len(flat) <= len(subdirs), (
            f"测试根平铺用例 {len(flat)} 个已不亚于模块子目录 {len(subdirs)} 个——"
            "新用例应落入对应功能模块子目录（tests/unit/<module>/、tests/integration/ 等）。"
        )
