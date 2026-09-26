# -*- coding: utf-8 -*-
"""知识库索引接线守卫（Issue #242：把仓库文档接进 CNB 知识库）。

## 为什么需要这一支

Issue #242 要求「搭建 neurova 知识库」：把 `docs/**/*.md` 切片、向量化写入 CNB
知识库，供页面问答与 Open API 检索取用。这件事由平台内置任务 `knowledge:update`
承担，但它有三处**静默失效面**，平台一处都不会报错：

1. **`options` 的未知键被静默忽略** —— `options` 不受平台 `additionalProperties:false`
   约束。本仓已踩过一次同型事故：把行为约束写进 `npc:go.options.prompt`，
   整条从未生效（Issue #158）。故键集与配置同住一份允许集
   （`.cnb/knowledge_options_keys.txt`），逐键校验。
2. **`include` 的 glob 命中为空** —— 一条"看着配了、其实一个文件都没索引"的
   流水线，跑完照样 success。故判据不止看写法，还要用真仓库实测 glob 命中数。
3. **写进去的东西没人读** —— 建了库却没有任何入口（页面按钮/角色纪律/使用文档），
   就是 AGENTS.md 协作红线点名的断点：必须形成「写入 → 读取 → 反馈」闭环。

## 本文件钉五件事（全部可证伪）

- **A 建库流水线存在且只挂推送类事件**：`main` 分支的推送事件（`push` / `commit.add`）
  上必须有一条 `type: knowledge:update` 的流水线；`pull_request` 侧必须没有它 ——
  门禁流水线以锚点别名与 PR 共用同一份定义，把非门禁的建库流水线塞进 `main.push`
  会让"提 PR 就重建整个知识库"，既烧嵌入模型调用又与门禁语义混同。
- **B options 键在平台允许集内**：事实源是 `.cnb/knowledge_options_keys.txt`
  （抓自 https://docs.cnb.cool/conf-schema-zh.json 的 knowledge:update 定义）。
- **C 索引面不空转**：`include` 覆盖 `docs/**/*.md` 且实测有命中文件；
  `exclude` 排掉的文件真实存在（写了却不存在的排除项是"只写不读的配置"）。
- **D 读取面接线**：每个在册 NPC 角色的 prompt 都载明知识库作答纪律
  （优先依据知识库 / 注明文档路径 / 无命中时明确说明），且该段逐字一致 ——
  角色 prompt 是评论触发时唯一必达的指令通道（`.cnb.yml` 的 `npc:go.options`
  没有 `prompt` 键，Issue #242 里给的写法正是那条永不生效的通路）。
- **E 指南可达**：`docs/10-configuration/KNOWLEDGE_BASE.md` 存在，且在
  `docs/0-index/README.md` 的导航里登记（新增文档不登记＝读者找不到入口）。
- **G 读数不手抄**：索引面的篇数只在正文里以**复算命令**的形式存在，不写死数字。
  读数的事实源是文件系统本身，写下的每一个数字都是第二份定义，且它会在**同批合并的
  另一条 PR** 动到 `docs/` 时当场过期——平台与 CI 都不报错（同型收口见
  `tests/unit/test_docs_index_hand_copied_counts.py` 与 Issue #231）。

反向锁：注入一个平台未声明的 option 键、或摘掉建库流水线、或往正文塞一个手抄读数，
本文件必须判红。
"""

from __future__ import annotations

import fnmatch
import glob
import io
import re
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CNB = PROJECT_ROOT / ".cnb.yml"
SETTINGS = PROJECT_ROOT / ".cnb" / "settings.yml"
OPTION_ALLOWLIST = PROJECT_ROOT / ".cnb" / "knowledge_options_keys.txt"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
INDEX_DOC = PROJECT_ROOT / "docs" / "0-index" / "README.md"
GUIDE_DOC = PROJECT_ROOT / "docs" / "10-configuration" / "KNOWLEDGE_BASE.md"

#: 建库流水线的名字（`.cnb.yml` 里唯一一处，判据按名定位）。
KB_PIPELINE_NAME = "knowledge-base"

#: 平台内置任务的类型名。
KB_STEP_TYPE = "knowledge:update"

#: 被索引的文档面（Issue #242 的原始要求：`docs/**/*.md`）。
DOC_GLOB = "docs/**/*.md"

#: 必须排除的目录：`docs/11-legacy/` 正文自述「历史/过时文档……不再维护」。
#: 把它喂给 RAG，等于让"已被取代的旧方案"与现行文档同权回答用户。
EXCLUDED_ARCHIVE = "docs/11-legacy"

#: 平台当前唯一支持的嵌入模型（`knowledge:update` 文档 + 平台 embedding 模型列表）。
SUPPORTED_EMBEDDING = {"hunyuan"}

#: 允许集文件的来源标记（缺它即无从回答"这份清单凭什么为准"）。
ALLOWLIST_SENTINEL = "# 平台 Schema：knowledge:update.options 允许的键"

#: 知识库作答纪律：三个要点逐字出现在**每个**在册角色的 prompt 里。
#: 一段话同时是"给 Agent 的约束"与"守卫的判据"，改任一侧都会让另一侧变红。
KB_ANSWER_CLAUSE = (
    "6. 知识库作答：优先依据本仓知识库（docs/ 文档与 Issue 索引）作答，"
    "并注明参考的文档路径；知识库中没有相关内容时明确说明，不得凭想象补全。"
)

#: 推送类事件：`commit.add` 与 `push` 同为「main 分支被推送新提交」的入口。
#: 本仓用 `commit.add` 而非 `push` 的理由在 `.cnb.yml` 的注释里逐字写明，
#: 判据只要求"落在推送类事件上"，不绑死具体那一个（避免把实现细节当契约）。
PUSH_LIKE_EVENTS = ("push", "commit.add")

#: 手抄「可漂移读数」的句式：`<数字> 篇`。索引面篇数的事实源是文件系统本身
#: （`glob.glob('docs/**/*.md')`），写进正文的每个数字都是第二份定义；
#: 它的漂移不需要任何人改错——同批合并的另一条 PR 往 `docs/` 加一篇文档，
#: 本文件里的读数当场过期，而平台与 CI 都不报错。
HAND_COPIED_READING = re.compile(r"\d+\s*篇")


def _load(path: Path) -> dict:
    return yaml.safe_load(io.open(path, encoding="utf-8").read())


@pytest.fixture(scope="module")
def cnb_doc():
    assert CNB.exists(), ".cnb.yml 丢失"
    return _load(CNB)


@pytest.fixture(scope="module")
def settings_doc():
    assert SETTINGS.exists(), ".cnb/settings.yml 丢失"
    return _load(SETTINGS)


def _iter_internal_steps(node, path=""):
    """递归产出 (路径, 任务体) —— 所有声明了 `type` 的内置任务。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_internal_steps(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            yield path, node
        for key, value in node.items():
            yield from _iter_internal_steps(value, f"{path}.{key}" if path else str(key))


def _iter_pipelines(node, path=""):
    """递归产出 (路径, 流水线体) —— 含 `stages` 的映射即一条流水线。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_pipelines(item, f"{path}[{i}]")
        return
    if isinstance(node, dict):
        if isinstance(node.get("stages"), list):
            yield path, node
        for key, value in node.items():
            yield from _iter_pipelines(value, f"{path}.{key}" if path else str(key))


def _knowledgeSteps(node):
    """递归产出 (路径, 内置任务体) —— 只取 knowledge:update。"""
    for where, step in _iter_internal_steps(node):
        if step.get("type") == KB_STEP_TYPE:
            yield where, step


def _main_event(cnb_doc, event: str):
    return ((cnb_doc.get("main") or {}).get(event))


class TestPipelineIsWiredOnPushLikeEventsOnly:
    """A：建库流水线必须挂在 main 的推送类事件上，且不得挂到 PR 上。"""

    def test_pipeline_exists_on_main_push_like_event(self, cnb_doc):
        main = cnb_doc.get("main") or {}
        found = []
        for event in PUSH_LIKE_EVENTS:
            body = main.get(event)
            if not isinstance(body, list):
                continue
            for pipeline in body:
                if isinstance(pipeline, dict) and pipeline.get("name") == KB_PIPELINE_NAME:
                    found.append(event)
            for _, step in _knowledgeSteps(body):
                found.append(event)
        assert found, (
            f"`main` 的推送类事件（{' / '.join(PUSH_LIKE_EVENTS)}）上找不到 {KB_PIPELINE_NAME} "
            f"建库流水线 —— 文档改动不会被索引，知识库停在首次建库那一刻的快照。\n"
            f"修法：在 `main` 下声明事件并在其流水线里放 `type: {KB_STEP_TYPE}` 的 stage。"
        )

    def test_pull_request_side_does_not_rebuild_the_index(self, cnb_doc):
        """PR 侧不得建库：门禁与 PR 共用锚点别名，塞进去就是"提 PR 重建整库"。"""
        pr_body = _main_event(cnb_doc, "pull_request") or []
        offenders = [where for where, _ in _knowledgeSteps(pr_body)]
        assert not offenders, (
            "`main.pull_request` 上出现了建库任务: "
            + ", ".join(offenders)
            + "\n每条 PR 提交都会全量重算嵌入，而 PR 的内容尚未定稿——"
            "索引的应当是已进入 main 的文档（推送类事件）。"
        )

    def test_step_declares_no_shell_script(self, cnb_doc):
        """`knowledge:update` 是平台内置任务：不得同时写 `script`（Schema 拒收）。"""
        offenders = [
            where for where, step in _knowledgeSteps(cnb_doc) if "script" in step
        ]
        assert not offenders, (
            "建库任务同时声明了 script: " + ", ".join(offenders) +
            "\n平台 Schema 的内置任务分支与自定义脚本分支互斥（`script: {not: true}`）。"
        )


class TestOptionsStayInsideThePlatformAllowlist:
    """B：`options` 的键必须在平台声明的允许集内（未知键被静默忽略）。"""

    def test_allowlist_file_lives_with_the_config(self):
        assert OPTION_ALLOWLIST.exists(), (
            f"{OPTION_ALLOWLIST.relative_to(PROJECT_ROOT)} 丢失 —— "
            "建库参数允许集没了事实源，写错键不会被任何东西拦下"
        )
        text = io.open(OPTION_ALLOWLIST, encoding="utf-8").read()
        assert ALLOWLIST_SENTINEL in text, (
            f"{OPTION_ALLOWLIST.relative_to(PROJECT_ROOT)} 缺来源标记「{ALLOWLIST_SENTINEL}」——"
            "读者无从回答「这份清单凭什么为准」"
        )

    def test_unknown_option_keys_are_rejected(self, cnb_doc):
        allowed = {
            line.split("#", 1)[0].strip()
            for line in io.open(OPTION_ALLOWLIST, encoding="utf-8").read().splitlines()
            if line.split("#", 1)[0].strip()
        }
        unknown = []
        for where, step in _knowledgeSteps(cnb_doc):
            for key in (step.get("options") or {}):
                if key not in allowed:
                    unknown.append(f"{where}.options.{key}")
        assert not unknown, (
            "knowledge:update 出现平台 Schema 未声明的键（静默忽略，等于没配）:\n  "
            + "\n  ".join(unknown)
            + f"\n允许集见 {OPTION_ALLOWLIST.relative_to(PROJECT_ROOT)}。"
        )

    def test_embedding_model_is_a_supported_one(self, cnb_doc):
        """嵌入模型目前只有 `hunyuan`（平台 embedding 模型列表实测）——写别的必失败。"""
        values = {
            (step.get("options") or {}).get("embeddingModel")
            for _, step in _knowledgeSteps(cnb_doc)
        }
        bad = sorted(v for v in values if v is not None and v not in SUPPORTED_EMBEDDING)
        assert not bad, (
            f"建库用的嵌入模型不在平台支持集内: {bad}（现支持 {sorted(SUPPORTED_EMBEDDING)}）"
        )


class TestIndexSurfaceDoesNotSpindle:
    """C：索引面既不能空转（一个文件都没命中），也不能留下无人命中的排除项。"""

    @staticmethod
    def _optionsOf(cnb_doc) -> list:
        return [step.get("options") or {} for _, step in _knowledgeSteps(cnb_doc)]

    def test_include_glob_really_matches_the_docs_tree(self, cnb_doc):
        includes = self._optionsOf(cnb_doc)
        assert includes, "配置里没有任何建库任务 —— 本判据无从生效"
        assert any(DOC_GLOB in _asList(opts.get("include")) for opts in includes), (
            f"建库任务未覆盖 {DOC_GLOB} —— docs/ 下的文档改动不会进索引"
        )
        hits = [p for p in PROJECT_ROOT.glob(DOC_GLOB) if p.is_file()]
        assert hits, (
            f"{DOC_GLOB} 在真仓库里一个文件都没命中 —— "
            "这条 include 是空转的（流水线跑完照样 success，索引里什么都没有）"
        )

    def test_excluded_archive_is_real_and_excluded(self, cnb_doc):
        archive = PROJECT_ROOT / EXCLUDED_ARCHIVE
        md_files = [p for p in archive.glob("**/*.md") if p.is_file()] if archive.is_dir() else []
        assert md_files, (
            f"{EXCLUDED_ARCHIVE}/ 下没有 Markdown 文件 —— 排除项已失效，"
            "要么目录被搬走（同步本判据），要么本来就不该写这条 exclude"
        )
        patterns = [
            pattern
            for opts in self._optionsOf(cnb_doc)
            for pattern in _asList(opts.get("exclude"))
        ]
        assert f"{EXCLUDED_ARCHIVE}/**" in patterns, (
            f"建库任务未排除 {EXCLUDED_ARCHIVE}/** —— 该目录正文自述"
            "「历史/过时文档……不再维护」，喂给 RAG 会让已被取代的旧方案"
            f"与现行文档同权回答用户（当前 {len(md_files)} 篇）"
        )

    def test_every_include_glob_surfaces_at_least_one_file(self, cnb_doc):
        """include 逐条不得空转：命中面为空 = 「配了却一个文件都不索引」。"""
        includes = [pat for opts in self._optionsOf(cnb_doc) for pat in _asList(opts.get("include"))]
        assert includes, "建库任务未写 include —— 平台默认 `**/**.md` 会把全仓 md 都吞进来"
        empty = [pat for pat in includes if not _globFiles(pat)]
        assert not empty, (
            f"include 命中面为空（该条配置不改动任何东西）: {empty}"
        )

    def test_every_exclude_changes_the_index_surface(self, cnb_doc):
        """exclude 逐条必须真的改变索引面 —— 空转的排除项就是「只写不读的配置」。

        本轮实测就是这条判据抓到的：`docs/**/*.md` 本就不匹配前导点文件，
        给 `docs/.cf_doc.md` 之类各写一条 exclude 看着很尽责，
        实则一个文件都没排掉 —— 而平台不报任何错，
        下一个人照着它以为"点文件已被排除"。
        """
        for opts in self._optionsOf(cnb_doc):
            includes = _asList(opts.get("include"))
            excludes = _asList(opts.get("exclude"))
            baseline = _surfaceUnder(includes, [])
            for pattern in excludes:
                trimmed = _surfaceUnder(includes, [pattern])
                assert len(trimmed) < len(baseline), (
                    f"exclude 项 {pattern!r} 不改变索引面（排除前后都是 {len(baseline)} 篇）——"
                    "它没排掉任何文件，是一条只写不读的配置。\n"
                    "要么删掉它，要么改成真能命中文件的写法。"
                )


def _globFiles(pattern: str) -> list:
    """按模式取仓库内的 Markdown 文件（POSIX 相对路径）。

    口径取 `glob.glob`，**不取** `pathlib.Path.glob`：两者对前导点的处理不同——
    平台的分支匹配明确采用 unix 通配（`触发规则` 一节指向 globster，
    `*` 默认不匹配前导点），`glob.glob` 与它同语义，而 `pathlib` 的 `*` 会把
    前导点也吃掉。差值恰好是 `docs/.cf_doc.md` 与 `docs/.roles.md` 两个点文件
    （篇数不在此处写死，复算命令见 `docs/10-configuration/KNOWLEDGE_BASE.md` 第 2 节）。

    这个差别不是细节：按 `pathlib` 口径，「给点文件各写一条 exclude」会显得
    非空转（判据放行），而它其实一条都没必要写 —— 本轮就是靠这一条把三处
    「只写不读的 exclude」收敛成一条的（见 `test_every_exclude_changes_the_index_surface`）。
    """
    return sorted(
        Path(rel).as_posix()
        for rel in glob.glob(pattern, recursive=True)
        if (PROJECT_ROOT / rel).is_file()
    )


def _matchesExclude(path: str, pattern: str) -> bool:
    """`path`（POSIX 相对路径）是否被 exclude 的 `pattern` 命中。

    支持两种形态：`<目录>/**`（整棵子树）与 `fnmatch` 通配（如 `**/*.tmp.md`）。
    """
    if pattern.endswith("/**"):
        return path == pattern[:-3] or path.startswith(pattern[:-2])
    return fnmatch.fnmatch(path, pattern)


def _surfaceUnder(includes: list, excludes: list) -> list:
    """给定 include/exclude 后的**有效索引面**（逐条判据的唯一口径）。"""
    files = {rel for pattern in includes for rel in _globFiles(pattern)}
    return sorted(f for f in files if not any(_matchesExclude(f, pat) for pat in excludes))


def _asList(value) -> list:
    """`include` / `exclude` 是 `String | Array<String>`，统一成列表再判。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def handCopiedReadings(text: str) -> list:
    """文本里**手抄的可漂移读数**（空列表＝读数只以复算命令的形式存在）。"""
    return HAND_COPIED_READING.findall(text)


def readingBearingFiles() -> tuple:
    """承接建库读数的三个落点：配置注释 / 使用指南 / 本守卫自身的正文。

    取模块全局而非闭包捕获，是为了让反向锁能 monkeypatch 其中一个落点。
    """
    return (CNB, GUIDE_DOC, Path(__file__))


def assertNoHandCopiedReading(path: Path) -> None:
    """`path` 的正文不得手抄可漂移读数（命中即报出落点与原文）。"""
    offenders = handCopiedReadings(io.open(path, encoding="utf-8").read())
    assert not offenders, (
        f"{Path(path).name} 手抄了可漂移的读数: {offenders}\n"
        "索引面篇数的事实源是文件系统本身；写死数字与实况之间没有任何机器判据，"
        "而同批合并的另一条 PR 动到 docs/ 就会让它过期——平台与 CI 都不报错。\n"
        "修法：删掉数字，改写成复算命令（见 docs/10-configuration/KNOWLEDGE_BASE.md 第 2 节）。"
    )


class TestIndexReadingsAreNotHandCopied:
    """G：索引面的读数以复算命令存在，不以写死的数字存在。

    这条根因不是"数字写错了"，而是"数字没人复核"：`docs/` 的篇数随任何一次文档
    增删而变，写进注释/文档的那一份没有任何判据咬合，于是从写下那一刻起就在漂移。
    修法沿用本仓既有口径（`tests/unit/test_docs_index_hand_copied_counts.py`）——
    不把数字改对，而是**不写数字**，改写成读者能当场复算的命令。
    """

    def test_no_landing_point_hand_copies_a_reading(self):
        for path in readingBearingFiles():
            assertNoHandCopiedReading(path)

    def test_the_surface_is_recomputable_from_the_repo(self):
        """不写数字的前提是**读者能复算**：命中面必须能被仓库内的命令算出。"""
        readings = _globFiles(DOC_GLOB)
        assert readings, f"{DOC_GLOB} 一个文件都没命中 —— 复算命令无从谈起"

    def test_discriminating_power(self, tmp_path, monkeypatch):
        """反向锁：往落点里塞一个手抄读数 → 必须判红。"""
        import tests.unit.ci.test_knowledge_base_index_wiring as module

        # 注入的读数是**当场复算出来的**，不在本文件里再写一个数字——
        # 否则反向锁的夹具本身就成了它要拦的那类手抄（判据会咬自己）。
        drifted = tmp_path / "KNOWLEDGE_BASE.md"
        drifted.write_text(
            f"（实测 {len(_globFiles(DOC_GLOB))} 篇）", encoding="utf-8"
        )
        monkeypatch.setattr(module, "GUIDE_DOC", drifted)
        assert module.handCopiedReadings(io.open(drifted, encoding="utf-8").read())
        with pytest.raises(AssertionError, match="手抄了可漂移的读数"):
            module.assertNoHandCopiedReading(drifted)


@pytest.fixture(scope="module")
def roles(settings_doc):
    """在册 NPC 角色（判据与 `.cnb/settings.yml` 同源，不另建一份名单）。"""
    return (settings_doc.get("npc") or {}).get("roles") or []


class TestAnswerDisciplineLivesOnTheReachableChannel:
    """D：知识库作答纪律必须写进每个在册角色的 prompt（唯一必达通道）。"""

    def test_every_role_carries_the_answer_clause(self, roles):
        assert roles, ".cnb/settings.yml 未声明任何 NPC 角色"
        missing = [
            role.get("name")
            for role in roles
            if KB_ANSWER_CLAUSE not in (role.get("prompt") or "")
        ]
        assert not missing, (
            f"角色 prompt 缺知识库作答纪律（逐字比对）: {missing}\n"
            "评论触发时提示词由角色自带（`npc:go.options` 没有 prompt 键，写在那里会被"
            "静默忽略 —— Issue #242 的示例配置正是这条永不生效的通路）。\n"
            f"应逐字包含：{KB_ANSWER_CLAUSE}"
        )

    def test_clause_is_identical_across_roles(self, roles):
        """同一句话各角色各写一份就有漂移；判据即"逐字同一句"。"""
        seen = {
            role.get("name"): [
                line for line in (role.get("prompt") or "").splitlines()
                if line.startswith("6. 知识库作答")
            ]
            for role in roles
        }
        shapes = {name: len(lines) for name, lines in seen.items()}
        assert all(count == 1 for count in shapes.values()), (
            f"各角色的知识库作答纪律条目数不一致（应各为 1 条）: {shapes}"
        )
        assert len({tuple(lines) for lines in seen.values()}) == 1, (
            "知识库作答纪律在各角色间不一致（改一处必须同步另一处）"
        )


class TestPageEntryPointsAtARealRole:
    """F：页面知识库入口的接线必须指向**真实存在**的角色，否则静默回落。

    `npc.defaultRole` 选错名字、或 `npc.button` 与知识库链路脱节（没有按钮就没有
    页面入口），平台都不会报错 —— 用户在仓库页面上看到的是"有这个功能但点了没反应"。
    """

    def test_button_declares_a_name(self, settings_doc):
        button = ((settings_doc.get("npc") or {}).get("button")) or {}
        assert str(button.get("name") or "").strip(), (
            "`.cnb/settings.yml` 的 `npc.button.name` 为空 —— "
            "仓库页面上不会出现知识库入口，建成索引后没人能点到它"
        )

    def test_default_role_names_a_registered_role(self, settings_doc, roles):
        npc = settings_doc.get("npc") or {}
        default_role = npc.get("defaultRole")
        assert default_role, (
            "缺 `npc.defaultRole` —— 知识库弹窗没有默认选中角色，"
            "用户每次都要手动挑一个"
        )
        names = {role.get("name") for role in roles}
        assert default_role in names, (
            f"`npc.defaultRole={default_role!r}` 不是 `.cnb/settings.yml` 的在册角色 "
            f"（现有 {sorted(names)}）—— 名称写错时平台静默回落，不报任何错"
        )

    def test_default_repo_is_this_repo(self, settings_doc):
        """`defaultRepo` 只在引入别的仓库知识库时才需要（`npc.imports.list`）。

        本仓没有 imports，写 defaultRepo 就是一条**只写不读的配置** ——
        指向不存在的引入项时，弹窗默认选中的仓库为空。
        """
        npc = settings_doc.get("npc") or {}
        if not (npc.get("imports") or {}).get("list"):
            assert not npc.get("defaultRepo"), (
                "未配置 `npc.imports.list` 却写了 `npc.defaultRepo` —— "
                "它指向一个没有被引入的仓库，是一条只写不读的配置"
            )


class TestGuideIsReachable:
    """E：使用指南存在且在导航里登记（不登记＝读者找不到入口）。"""

    def test_guide_exists(self):
        assert GUIDE_DOC.exists(), (
            f"{GUIDE_DOC.relative_to(PROJECT_ROOT)} 不存在 —— "
            "建库参数、Open API 检索、重建方式没有事实源文档"
        )

    def test_guide_is_registered_in_the_navigation(self):
        index = io.open(INDEX_DOC, encoding="utf-8").read()
        assert "10-configuration/KNOWLEDGE_BASE.md" in index, (
            "知识库指南未登记进 `docs/0-index/README.md` 的 10-configuration 章节 ——"
            "新增文档不登记，读者从唯一入口找不到它"
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = io.open(PROTECTED, encoding="utf-8").read()
        rel = "tests/unit/ci/test_knowledge_base_index_wiring.py"
        assert rel in listed, f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"


class TestDiscriminatingPower:
    """反向锁：三类静默失效各注入一次，判据必须报出来。"""

    @staticmethod
    def _mutated(tmp_path, cnb_doc, mutate):
        drifted = tmp_path / ".cnb.yml"
        copy = yaml.safe_load(yaml.safe_dump(cnb_doc, allow_unicode=True))
        mutate(copy)
        drifted.write_text(
            yaml.safe_dump(copy, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return drifted

    def test_unknown_option_key_is_caught(self, tmp_path, cnb_doc, monkeypatch):
        import tests.unit.ci.test_knowledge_base_index_wiring as module

        def inject(doc):
            for _, step in module._knowledgeSteps(doc):
                (step.setdefault("options", {}))["prompt"] = "这条会被静默忽略"

        drifted = self._mutated(tmp_path, cnb_doc, inject)
        monkeypatch.setattr(module, "CNB", drifted)
        with pytest.raises(AssertionError, match="未声明的键"):
            module.TestOptionsStayInsideThePlatformAllowlist() \
                .test_unknown_option_keys_are_rejected(module._load(drifted))

    def test_missing_pipeline_is_caught(self, tmp_path, cnb_doc, monkeypatch):
        import tests.unit.ci.test_knowledge_base_index_wiring as module

        def strip(doc):
            for event in module.PUSH_LIKE_EVENTS:
                body = (doc.get("main") or {}).get(event)
                if isinstance(body, list):
                    keep = [
                        p for p in body
                        if not (isinstance(p, dict) and p.get("name") == module.KB_PIPELINE_NAME)
                    ]
                    (doc["main"])[event] = [
                        p for p in keep
                        if not any(
                            step.get("type") == module.KB_STEP_TYPE
                            for _, step in module._iter_internal_steps(p)
                        )
                    ]

        drifted = self._mutated(tmp_path, cnb_doc, strip)
        monkeypatch.setattr(module, "CNB", drifted)
        with pytest.raises(AssertionError, match="找不到"):
            module.TestPipelineIsWiredOnPushLikeEventsOnly() \
                .test_pipeline_exists_on_main_push_like_event(module._load(drifted))

    def test_vacuous_exclude_is_caught(self, tmp_path, cnb_doc, monkeypatch):
        """反向锁：给配置塞一条排不掉任何文件的 exclude → 必须判红。"""
        import tests.unit.ci.test_knowledge_base_index_wiring as module

        def inject(doc):
            for _, step in module._knowledgeSteps(doc):
                opts = step.setdefault("options", {})
                opts["exclude"] = _asList(opts.get("exclude")) + ["docs/.cf_doc.md"]

        drifted = self._mutated(tmp_path, cnb_doc, inject)
        monkeypatch.setattr(module, "CNB", drifted)
        with pytest.raises(AssertionError, match="不改变索引面"):
            module.TestIndexSurfaceDoesNotSpindle() \
                .test_every_exclude_changes_the_index_surface(module._load(drifted))

    def test_dropped_answer_clause_is_caught(self, tmp_path, settings_doc, monkeypatch):
        import tests.unit.ci.test_knowledge_base_index_wiring as module

        drifted = tmp_path / "settings.yml"
        copy = yaml.safe_load(yaml.safe_dump(settings_doc, allow_unicode=True))
        for role in (copy.get("npc") or {}).get("roles") or []:
            role["prompt"] = (role.get("prompt") or "").replace(module.KB_ANSWER_CLAUSE, "")
        drifted.write_text(yaml.safe_dump(copy, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(module, "SETTINGS", drifted)
        with pytest.raises(AssertionError, match="缺知识库作答纪律"):
            module.TestAnswerDisciplineLivesOnTheReachableChannel() \
                .test_every_role_carries_the_answer_clause(
                    ((module._load(drifted).get("npc") or {}).get("roles") or [])
                )
