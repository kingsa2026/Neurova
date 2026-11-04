"""trace 落盘出口脱敏 + data_masking 退役判据（候选 C2，对比报告 2026-11-05 N2）

教义第 7 条对比裁定（2026-11-05 实测）：
- ``sensitive_info`` 是唯一在役文本卫生单源（规则表 + keyValue 打码 + PII 规则），
  已接线多处；data_masking 的 4 条 PII 正则（手机/邮箱/身份证/IP）与单源规则表
  **同契约重复**（教义第 6 条第二份定义），结构化脱敏与已接线的 privacy_gate
  职能重叠，且生产侧零消费——退役，不接线；
- 真实缺口在 trace 落盘出口：tool_trace buffer（经 skill POST_EXECUTE 事件流向
  进化侧证据落点）与 trace_recorder 落盘文件均无文本卫生，敏感值随参数与错误
  信息进审计工件。接线两处，均走单源 sanitizeSensitive：
  1. tool_trace.recordToolTrace 入口（params 摘要与 error 脱敏）；
  2. trace_recorder.save_trace（payload **逐字符串值**脱敏后再序列化——
     不能整体序列化后替换：单源打码会吃掉 JSON 值的引号，产出非法 JSON）。
"""

import importlib
import json

import pytest

SECRET = "SuperSecret99"
TOKEN = "abc123secret"


# ── tool_trace 入口咽喉（buffer → POST_EXECUTE → 进化证据落点） ──────


def test_tool_trace_params_and_error_masked_at_entry():
    from neurova.core.tool_trace import (
        beginToolTrace,
        currentToolTrace,
        endToolTrace,
        recordToolTrace,
    )

    token, _ = beginToolTrace()
    try:
        recordToolTrace(
            tool="db_query",
            params={"password": SECRET, "email": "admin@example.com"},
            success=False,
            error="connect failed with token=" + TOKEN,
        )
        entries = currentToolTrace()
        assert entries, "trace 条目必须生成"
        entry = entries[-1]
        assert SECRET not in entry["params"], "参数摘要必须脱敏（单源打码）"
        assert "admin@example.com" not in entry["params"]
        assert TOKEN not in entry["error"], "错误信息必须脱敏"
    finally:
        endToolTrace(token)


def test_tool_trace_clean_params_untouched():
    """无规则命中的参数不得被改写（卫生面零误伤）。"""
    from neurova.core.tool_trace import (
        beginToolTrace,
        currentToolTrace,
        endToolTrace,
        recordToolTrace,
    )

    params = {"cmd": "ls -la", "count": 3}
    token, _ = beginToolTrace()
    try:
        recordToolTrace(tool="shell", params=params, success=True)
        entry = currentToolTrace()[-1]
        assert entry["params"] == json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    finally:
        endToolTrace(token)


# ── save_trace 磁盘咽喉（trajectory 审计工件） ─────────────────────


def test_save_trace_masks_sensitive_values_and_stays_valid_json(tmp_path):
    from neurova.core.trace_recorder import TrajectoryRecorder

    recorder = TrajectoryRecorder()
    recorder.set_storage_dir(str(tmp_path / "trajectories"))
    trace_id = recorder.start_trace("sec_session", "sec_agent", "sec_user")
    assert trace_id, "轨迹必须启动"
    try:
        recorder.record_tool_call(
            trace_id,
            "db_query",
            "builtin",
            parameters={"password": SECRET, "note": "reach me at admin@example.com"},
            success=False,
            error_message="token=" + TOKEN + " rejected",
        )
        saved = recorder.save_trace(trace_id, file_path=str(tmp_path / "t.json"))
        assert saved, "轨迹必须落盘"

        raw = (tmp_path / "t.json").read_text(encoding="utf-8")
        assert SECRET not in raw, "轨迹工件不得含敏感原文"
        assert TOKEN not in raw
        assert "admin@example.com" not in raw
        parsed = json.loads(raw), "打码不得破坏 JSON 结构（逐值脱敏而非整串替换）"
        assert parsed[0] is not None
    finally:
        recorder.end_trace(trace_id)


def test_save_trace_clean_content_untouched(tmp_path):
    """无敏感内容的轨迹逐字节原样（卫生面零误伤）。"""
    from neurova.core.trace_recorder import TrajectoryRecorder

    recorder = TrajectoryRecorder()
    recorder.set_storage_dir(str(tmp_path / "trajectories"))
    trace_id = recorder.start_trace("clean_session", "clean_agent", "clean_user")
    try:
        recorder.record_tool_call(
            trace_id, "shell", "builtin", parameters={"cmd": "ls -la"}, success=True
        )
        saved = recorder.save_trace(trace_id, file_path=str(tmp_path / "clean.json"))
        raw = (tmp_path / "clean.json").read_text(encoding="utf-8")
        assert '"cmd": "ls -la"' in raw
        assert saved
    finally:
        recorder.end_trace(trace_id)


# ── 退役判据（教义第 7 条：接通与退役同批，防复活守卫） ─────────────


def test_data_masking_module_retired():
    """data_masking 已退役：模块必须不可导入（判据沿 imaginedApiSuitesRetired 先例）。"""
    with pytest.raises(ImportError):
        importlib.import_module("neurova.security.data_masking")
