"""工具参数守卫（OpenOcta 启发 P1-5：toolArgumentsGuard）。

把生产踩过的 LLM 参数坑做成执行前守卫（参考 openocta tool_arguments_guard.go）：

1. **参数别名归一**：LLM 手滑写错参数名（path/file/filename/filepath/filePath
   → file_path 一类）时自动重映射，不再让工具以空参数/错参数白跑一轮。
   别名分两档防误伤：
   - 无歧义档：filename/filepath/filePath/file_name/fileName —— 没有工具以
     它们为规范参数名，无需 schema 即可归一；
   - schema 感知档：path/file/link/cmd —— 可能是某些工具的真实参数名，
     仅当调用方提供了工具 schema（声明了目标规范名、且别名本身不是 schema
     参数）时才重映射。
2. **截断 JSON 检测与配平**：流式输出被掐断时参数值可能是半截 JSON——
   手写括号/引号配平计数，能修则修（含尾逗号清理）；修不了则拒绝执行并
   返回带修复建议的错误文案回灌模型，而不是让工具报错消耗迭代次数
   （对齐 P2-#12 教训：破坏性工具不得以残缺参数执行）。

装配语义对齐 security/tool_circuit_breaker：**默认不安装**——
install_tool_param_guard() 显式装配（幂等）；未安装时 get_param_guard()
返回 None，接入点行为与未装配完全等价（零回归面）。

拒绝结果的归类：param_guard 拒绝是"决策"而非"后端故障"——
security/governance.is_policy_denial 识别 param_guard 键，熔断器观察者
与失败统计不计数（与治理 DENY 同源口径）。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 无歧义别名：无需 schema（目标名不会是任何工具的规范参数名）
UNAMBIGUOUS_ALIASES: Dict[str, str] = {
    "filename": "file_path",
    "filepath": "file_path",
    "filePath": "file_path",
    "file_name": "file_path",
    "fileName": "file_path",
}

# 歧义别名：可能与真实参数名撞车，仅在 schema 证明目标存在且别名不存在时归一
SCHEMA_REQUIRED_ALIASES: Dict[str, str] = {
    "path": "file_path",
    "file": "file_path",
    "link": "url",
    "cmd": "command",
}

_JSON_PREFIXES = ("{", "[")
_TRAILING_COMMA = re.compile(r",\s*(?=[}\]])")
# 配平扫描上限（防御超长输入拖垮主链）
_MAX_REPAIR_LEN = 1_000_000

_SUGGESTIONS = [
    "重新生成完整、合法的 JSON 参数（注意闭合括号与引号）",
    "若参数过长导致截断，请拆分为多次调用或缩短参数值",
]


def balance_json_text(text: str) -> Optional[str]:
    """尝试配平半截 JSON 文本。

    手写括号/引号栈计数（参考 openocta tool_arguments_guard 的配平思想）：
    - 追踪字符串内/外与转义状态，统计未闭合的 { [ 与未闭合字符串
    - 补齐闭合符后再 json.loads 验证；失败再清理尾逗号重验
    - 无法配平返回 None（调用方据此拒绝执行）
    """
    if not text or len(text) > _MAX_REPAIR_LEN:
        return None
    stack: List[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return None  # 多出的闭合符：结构错乱，不可配平
            opener = stack.pop()
            if (opener, ch) not in (("{", "}"), ("[", "]")):
                return None
    if not stack and not in_string:
        return None  # 本就闭合（调用方只在 loads 失败时进来）：不处理

    suffix = '"' if in_string else ""
    closer = "".join("}" if c == "{" else "]" for c in reversed(stack))
    candidate = text + suffix + closer
    try:
        json.loads(candidate)
        return candidate
    except (json.JSONDecodeError, ValueError):
        pass
    fixed = _TRAILING_COMMA.sub("", candidate)
    try:
        json.loads(fixed)
        return fixed
    except (json.JSONDecodeError, ValueError):
        return None


class ParamGuard:
    """参数守卫（纯函数式，无全局态——装配语义见模块级 install 函数）。"""

    def __init__(
        self,
        alias_table: Optional[Dict[str, str]] = None,
        schema_provider: Optional[Any] = None,
        repair_truncated_json: bool = True,
    ) -> None:
        self._unambiguous = dict(UNAMBIGUOUS_ALIASES)
        self._schema_required = dict(SCHEMA_REQUIRED_ALIASES)
        if alias_table:
            for alias, target in alias_table.items():
                self._schema_required[alias] = target
        self._schema_provider = schema_provider
        self._repair_truncated_json = repair_truncated_json

    def guard(
        self,
        tool_name: str,
        params: Any,
        schema: Optional[Set[str]] = None,
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """守卫入口。

        Args:
            tool_name: 工具名（日志与 schema 查询用）
            params: 原始参数（dict 之外原样透传）
            schema: 工具规范参数名集合（调用方提供；None = 降级只用无歧义档）

        Returns:
            (guarded_params, rejection)
            rejection 为 None 表示放行；否则是带修复建议的拒绝结果 dict，
            调用方应直接作为工具结果返回（is_policy_denial 识别，不计故障）。
        """
        if not isinstance(params, dict):
            return params, None

        if schema is None and self._schema_provider is not None:
            try:
                schema = self._schema_provider(tool_name)
            except Exception:  # noqa: BLE001 - schema 提供方故障降级为无 schema
                schema = None

        guarded = dict(params)  # 浅拷贝：绝不修改调用方的 dict
        remapped: List[str] = []

        for alias, target in self._unambiguous.items():
            if alias in guarded and target not in guarded and not (schema and alias in schema):
                guarded[target] = guarded.pop(alias)
                remapped.append(f"{alias} → {target}")
        if schema:
            for alias, target in self._schema_required.items():
                if (
                    alias in guarded
                    and target in schema
                    and alias not in schema
                    and target not in guarded
                ):
                    guarded[target] = guarded.pop(alias)
                    remapped.append(f"{alias} → {target}")

        issues: List[str] = []
        if self._repair_truncated_json:
            for key, value in list(guarded.items()):
                if not isinstance(value, str):
                    continue
                stripped = value.lstrip()
                if not stripped.startswith(_JSON_PREFIXES):
                    continue  # 非 JSON 形态（代码/正文）不碰
                try:
                    json.loads(value)
                    continue  # 本就合法
                except (json.JSONDecodeError, ValueError):
                    pass
                fixed = balance_json_text(value)
                if fixed is not None:
                    guarded[key] = fixed
                    logger.info("参数守卫配平 %s.%s 的截断 JSON", tool_name, key)
                else:
                    issues.append(key)

        if issues:
            logger.warning(
                "参数守卫拒绝 %s：截断 JSON 无法配平 %s（别名归一: %s）",
                tool_name, issues, remapped or "无",
            )
            return guarded, {
                "success": False,
                "error": (
                    f"工具 {tool_name} 的参数 {issues} 是截断的 JSON（括号/引号无法配平），"
                    "已拒绝执行以免以残缺参数产生破坏性副作用。"
                ),
                "param_guard": {
                    "tool": tool_name,
                    "issues": issues,
                    "remapped": remapped,
                    "suggestions": list(_SUGGESTIONS),
                },
            }

        if remapped:
            logger.info("参数守卫归一 %s 别名: %s", tool_name, remapped)
        return guarded, None


# ── 装配（对齐 tool_circuit_breaker：默认不装，显式 install，幂等，可逆） ──

_global_guard: Optional[ParamGuard] = None
_install_lock = threading.RLock()


def install_tool_param_guard(
    alias_table: Optional[Dict[str, str]] = None,
    schema_provider: Optional[Any] = None,
    repair_truncated_json: bool = True,
) -> ParamGuard:
    """装配参数守卫（幂等：已安装返回同一实例）。"""
    global _global_guard
    with _install_lock:
        if _global_guard is not None:
            return _global_guard
        _global_guard = ParamGuard(
            alias_table=alias_table,
            schema_provider=schema_provider,
            repair_truncated_json=repair_truncated_json,
        )
        logger.info("工具参数守卫已装配（别名 %d+%d 档, 截断 JSON 配平=%s）",
                    len(UNAMBIGUOUS_ALIASES), len(SCHEMA_REQUIRED_ALIASES),
                    repair_truncated_json)
        return _global_guard


def uninstall_tool_param_guard(force: bool = False) -> None:
    """卸载参数守卫（可逆；幂等）。force=True 时强制清空全局实例。"""
    global _global_guard
    with _install_lock:
        _global_guard = None


def get_param_guard() -> Optional[ParamGuard]:
    with _install_lock:
        return _global_guard


__all__ = [
    "ParamGuard",
    "UNAMBIGUOUS_ALIASES",
    "SCHEMA_REQUIRED_ALIASES",
    "balance_json_text",
    "get_param_guard",
    "install_tool_param_guard",
    "uninstall_tool_param_guard",
]
