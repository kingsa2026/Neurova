#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""外部 agent 数据导入 CLI：detect（只读）/ convert / apply（需 --yes）/ undo。

业务逻辑都在 neurova.memory_ingest 里，这里只做参数装配与人读的输出。写库要显式 --yes，
与既有备份/恢复的确认口径一致；未识别或指纹冲突一律不写（不猜最像的那一家）。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from neurova.memory_ingest.cli_errors import (  # noqa: E402
    EXIT_INVALID_BUNDLE, EXIT_OK, EXIT_REPORT_ONLY, EXIT_UNRECOGNIZED)
from neurova.memory_ingest.bundle.manifest import BundleError, UnrecognizedSourceError  # noqa: E402
from neurova.memory_ingest.bundle.validate import validate_bundle  # noqa: E402
from neurova.memory_ingest.converters import CONVERTERS  # noqa: E402
from neurova.memory_ingest.intake import apply_bundle, plan_bundle, undo_run  # noqa: E402
from neurova.memory_ingest.probe import probe_store  # noqa: E402

_VERDICT_LABEL = {"unique": "唯一命中", "conflict": "多指纹冲突", "unknown": "未识别"}


def main(argv: Sequence[str], *, manager=None, sessions=None) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.cmd == "detect":
            source = Path(args.source)
            if _is_bundle(source):
                return _report_bundle(source)
            return _detect(_scan(source))
        if args.cmd == "convert":
            return _convert(Path(args.source), Path(args.out), args.agent_name)
        if args.cmd == "apply":
            return _apply(args, manager=manager, sessions=sessions)
        return _undo(args, manager=manager, sessions=sessions)
    except UnrecognizedSourceError as exc:
        print(f"拒收：{exc}", file=sys.stderr)
        return EXIT_UNRECOGNIZED
    except BundleError as exc:
        print(f"拒绝：{exc}", file=sys.stderr)
        return EXIT_INVALID_BUNDLE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest_memory",
                                     description="外部 agent 会话与记忆导入")
    sub = parser.add_subparsers(dest="cmd", required=True)

    detect = sub.add_parser("detect", help="只读：逐 store 报告识别结论")
    detect.add_argument("source")

    convert = sub.add_parser("convert", help="只读源，把包写到指定目录供查看")
    convert.add_argument("source")
    convert.add_argument("--out", required=True)
    convert.add_argument("--agent-name", default="imported")

    apply_ = sub.add_parser("apply", help="写库（需 --yes 确认）")
    apply_.add_argument("source")
    apply_.add_argument("--agent-id", required=True)
    apply_.add_argument("--agent-name", default="imported")
    apply_.add_argument("--run-id", default=None, help="批次标签；缺省自动生成，撤销按它删")
    apply_.add_argument("--sessions-dir", default=None)
    apply_.add_argument("--yes", action="store_true", help="确认写库（缺省只出报告）")

    undo = sub.add_parser("undo", help="按批次标签撤销一次导入")
    undo.add_argument("--agent-id", required=True)
    undo.add_argument("--run-id", required=True)
    undo.add_argument("--sessions-dir", default=None)
    return parser


def _scan(source: Path) -> List[Any]:
    findings = probe_store(source)
    return findings if isinstance(findings, list) else [findings]


def _is_bundle(path: Path) -> bool:
    """有 manifest.json 的目录就是包，不是待识别的源：apply 两种都要收。"""
    return path.is_dir() and (path / "manifest.json").is_file()


def _detect(findings: Sequence[Any]) -> int:
    for finding in findings:
        hits = ",".join(finding.hits) or "无"
        print(f"[{_VERDICT_LABEL[finding.verdict]}] {finding.path} 指纹={hits} "
              f"结构={finding.structure}")
    if all(finding.verdict == "unique" for finding in findings) and findings:
        return EXIT_OK
    print("未识别或冲突的 store 一律不写库；把上面的结构摘要发给我方以新增指纹。")
    return EXIT_UNRECOGNIZED


def _report_bundle(bundle: Path) -> int:
    """包不是源：detect 指到包上就直接报价里有什么，不逐文件报未识别。"""
    errors = validate_bundle(bundle)
    if errors:
        print("这是一支已转好的包，但校验未通过：" + "；".join(errors))
        return EXIT_INVALID_BUNDLE
    plan = plan_bundle(bundle)
    print(f"这是一支已转好的包（{bundle}）：事件 {plan.counts['transcripts']} 条、"
          f"记忆 {plan.counts['memories']} 条、降级申报 {len(plan.dropped)} 项")
    print("导入用 apply 指到同一路径（写库仍需 --yes）。")
    return EXIT_OK


def _bundles(source: Path, staging: Path, agent_name: str
             ) -> Tuple[List[Tuple[str, Path]], List[Tuple[str, str]]]:
    """逐 store 出结论：认得出的转，认不出的照实回报。

    单源不猜——指到哪一支就该是哪一支；整目录则不因一个无关文件判死整批，
    但被跳过的每一支都要报出来，并以非零码收尾，脚本才不会当成成功。
    返回值第一元是给人读的标签（源路径 + 指纹名），第二元是包目录。
    """
    findings = _scan(source)
    if not findings:
        print(f"[跳过] {source} —— 目录里没有一个可探查的 store（既无 .db 也无 .jsonl），"
              f"一个字节都没写")
        return [], [(str(source), "无可探查的 store")]
    if _detect(findings) != EXIT_OK and not source.is_dir():
        raise UnrecognizedSourceError("源未识别或指纹冲突，拒绝猜测")
    usable, blocked = [], []
    for finding in findings:
        if finding.verdict != "unique":
            blocked.append((finding.path, _VERDICT_LABEL[finding.verdict]))
        elif finding.hits[0] not in CONVERTERS:
            blocked.append((finding.path, "有指纹无转换器"))
        else:
            usable.append(finding)
    single = len(findings) == 1
    bundles = []
    for index, finding in enumerate(usable):
        out_dir = staging if single else staging / f"{index:02d}-{Path(finding.path).name}"
        CONVERTERS[finding.hits[0]](Path(finding.path), out_dir, agent_name=agent_name)
        bundles.append((f"{finding.path}({finding.hits[0]})", out_dir))
    for path, reason in blocked:
        print(f"[跳过] {path} —— {reason}，一个字节都没写")
    return bundles, blocked


def _convert(source: Path, out: Path, agent_name: str) -> int:
    staging = Path(out)
    staging.mkdir(parents=True, exist_ok=True)
    bundles, blocked = _bundles(source, staging, agent_name)
    for label, bundle in bundles:
        errors = validate_bundle(bundle)
        print(f"{bundle} 来源={label} "
              f"{'校验通过' if not errors else '校验失败：' + '；'.join(errors)}")
        if errors:
            raise BundleError(f"{bundle} 校验未通过")
    return EXIT_UNRECOGNIZED if blocked else EXIT_OK


def _apply(args: argparse.Namespace, *, manager=None, sessions=None) -> int:
    source = Path(args.source)
    with tempfile.TemporaryDirectory(prefix="neurova-ingest-") as staging:
        if _is_bundle(source):
            # 包是 convert 的产物，拿来即用：不再经临时目录重转一遍
            bundles, blocked = [(str(source), source)], []
        else:
            bundles, blocked = _bundles(source, Path(staging), args.agent_name)
        for label, bundle in bundles:
            plan = plan_bundle(bundle)
            print(f"{label}：事件 {plan.counts['transcripts']} 条 → 装配后消息 "
                  f"{plan.turn_messages} 条，记忆 {plan.counts['memories']} 条，"
                  f"降级申报 {len(plan.dropped)} 项")
            for entry in plan.dropped:
                print(f"  申报 {entry['field']}：{entry['count']} 条 —— {entry['reason']}")
        if not args.yes:
            print("未写库（报告态）。确认请加 --yes")
            return EXIT_REPORT_ONLY

        manager = manager or _memory_manager(args.agent_id)
        sessions = sessions or _session_manager(args.sessions_dir)
        code = EXIT_OK
        for label, bundle in bundles:
            try:
                report = apply_bundle(bundle, agent_id=args.agent_id, manager=manager,
                                      sessions=sessions, run_id=args.run_id)
            except BundleError as exc:
                # 跨 store 不做分布式事务：失败者进报告，已写的靠 run_id 撤销
                print(f"拒绝 {label}：{exc}", file=sys.stderr)
                code = EXIT_INVALID_BUNDLE
                continue
            print(f"已写入 {label} run_id={report.run_id}：消息 +{report.messages_added}"
                  f"/跳过 {report.messages_skipped}，会话文件 {report.sessions_touched} 个，"
                  f"记忆 +{report.memories_added}/跳过 {report.memories_skipped}")
            print(f"  撤销：python scripts/ingest_memory.py undo --agent-id {args.agent_id} "
                  f"--run-id {report.run_id}")
        if blocked:
            code = EXIT_UNRECOGNIZED
        return code


def _undo(args: argparse.Namespace, *, manager=None, sessions=None) -> int:
    manager = manager or _memory_manager(args.agent_id)
    sessions = sessions or _session_manager(args.sessions_dir)
    memories, messages = undo_run(args.agent_id, args.run_id, manager=manager,
                                  sessions=sessions)
    print(f"已撤销 run_id={args.run_id}：记忆 {memories} 条、消息 {messages} 条"
          f"（这批引用过且已无人用的媒体文件一并清掉）")
    return EXIT_OK


def _memory_manager(agent_id: str):
    from neurova.cognitive_layers.memory_layer.manager import get_memory_manager

    return get_memory_manager(agent_id)


def _session_manager(sessions_dir: Optional[str]):
    if sessions_dir:
        # 会话根目录必须在构造 SessionManager 之前定：类级单例只认首次构造
        os.environ["NEUROVA_SESSIONS_DIR"] = str(Path(sessions_dir).resolve())
    from neurova.session_manager import SessionManager

    return SessionManager()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
