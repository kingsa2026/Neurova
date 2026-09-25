# -*- coding: utf-8 -*-
"""`.cnb.yml` 头部不得再手抄流水线条数（第二份定义）。

## 为什么需要这一支

`.cnb.yml` 顶部有一段写给人的「语法约定」，其中曾**逐字声明条数**：

    #     故 10 条流水线各自独立上报状态，粒度与 GitHub 的 job 对齐
    #     巡检流水线（deploy-config 的时间维度兜底），不计入上面 10 条 push 流水线。

这份手抄数字与 `main.push` 的实际条数之间**没有任何机器判据**，历史就是这样互相打架的：

- 工单 009 加 `experience-quality` 时在上面写成 11；
- 同批 Issue #223 把 `lint` 并进 `static-gate`，条数回到 10；
- 而下一段「不计入上面 10 条 push 流水线」一直是 10 —— 两份口径同文件内相反，
  全程只有「维护者记得同步」在支撑。

这正是 AGENTS.md 第 6 条点名的那类断点：**同一事实的第二份手抄定义**。
数字的第二份手抄一旦与 YAML 结构不一致，平台不报任何错、两处都不会响亮。
故修法是**收口到一份**：条数的单一事实源是 `main.push` 数组本身的长度，
头部只描述结构与口径，不再写具体数字。

## 本守卫钉两件事

- **A. 头部不再手抄条数**：`.cnb.yml` 的 `main:` 之前不得出现
  `N 条流水线` / `N 条 push 流水线` 这类**把条数写死**的表述；
- **B. 判据不空转**：头部必须显式指向条数的单一事实源（`main.push`），
  否则「不写数字」会退化成「读者无处可查」。

`.cnb.yml` 注释里写错的数字平台不会报错，故只有仓内判据能拦。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"

#: 「把条数写死」的两种句式（历史原文形态，二者属同一根因）。
HAND_COPIED_COUNT = (
    re.compile(r"故\s*\d+\s*条流水线"),
    re.compile(r"\d+\s*条 push 流水线"),
)


def readHeaderComment() -> str:
    """取 `.cnb.yml` 头部注释——`main:` 之前的全部内容。"""
    return io.open(CNB, encoding="utf-8").read().split("\nmain:")[0]


def handCopiedCounts() -> list[str]:
    """头部注释里**写死条数**的片段（空列表＝已收口到单一事实源）。"""
    head = readHeaderComment()
    found: list[str] = []
    for pattern in HAND_COPIED_COUNT:
        found.extend(m.group(0) for m in pattern.finditer(head))
    return found


class TestHeaderDoesNotHandCopyCount:
    """条数的单一事实源是 `main.push`，头部不得保留第二份手抄。"""

    def test_header_has_no_hand_copied_count(self):
        """头部不得写死流水线条数（本条是守卫的主判据）。"""
        offenders = handCopiedCounts()
        assert not offenders, (
            f".cnb.yml 头部仍在手抄流水线条数: {offenders}\n"
            "手抄的那一份与 `main.push` 之间没有任何机器判据，历史上已漂移成"
            "同文件内互相矛盾的两个数（11 与 10）。\n"
            "修法：删掉数字本身，只描述结构与口径——条数由 `main.push` 的长度给出，"
            "现读数用 `python3 -c \"import yaml;print(len(yaml.safe_load(open('.cnb.yml'))['main']['push']))\"`。"
        )

    def test_header_points_at_the_single_source_of_truth(self):
        """头部须显式指向条数的事实源，否则「不写数字」会退化成无处可查。"""
        head = readHeaderComment()
        assert "main.push" in head, (
            ".cnb.yml 头部既没写条数、也没指向 `main.push`——读者无处可查条数。\n"
            "修法：在语法约定段里写明「条数的单一事实源是 main.push 数组本身的长度」。"
        )

    def test_discriminating_power(self, tmp_path, monkeypatch):
        """反向锁：把条数手抄回去 → 必须判红。

        没有这一条，上面那条只是「当前这份文件恰好没写数字」的快照——
        本守卫的全部价值是拦住「新增/合并流水线时顺手再抄一个数」的回头路。
        """
        module = __import__(__name__, fromlist=["handCopiedCounts"])
        original = io.open(CNB, encoding="utf-8").read()
        drifted = tmp_path / ".cnb.yml"
        drifted.write_text(
            original.replace(
                "#   - 分支 → 事件(push/pull_request) → 流水线数组；",
                "#     故 10 条流水线各自独立上报状态；\n"
                "#   - 分支 → 事件(push/pull_request) → 流水线数组；",
                1,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(module, "CNB", drifted)
        assert module.handCopiedCounts() == ["故 10 条流水线"]
        with pytest.raises(AssertionError, match="手抄流水线条数"):
            module.TestHeaderDoesNotHandCopyCount() \
                .test_header_has_no_hand_copied_count()
