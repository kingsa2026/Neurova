# -*- coding: utf-8 -*-
"""calculator + get_datetime 工具族。

calculator：安全数学计算，AST 白名单求值，绝不执行任意代码。
get_datetime：当前时间/时间戳 + IANA 时区/±HH:MM 偏移。
从 neurova.tool_executor 拆出。`_builtin_dispatch` 目标名不变；
`_CALC_MAX_EXPONENT`、`_ZERO_OFFSET_TIMEZONE_NAMES` 单源于本 mixin；
`parseSource` 单一 AST 解析入口。不顶层 import `neurova.tool_executor`。
"""
import ast
from datetime import datetime
from typing import Dict

from neurova.core.ast_scan import parseSource

__all__ = ["CalculatorToolsMixin"]


class CalculatorToolsMixin:
    """calculator built-in; no eval/exec."""

    # calculator 指数上限 — 防止 9**999999999 这类表达式撑爆内存
    _CALC_MAX_EXPONENT = 10000

    async def _execute_calculator(self, params: Dict) -> Dict:
        """安全数学计算：AST 白名单求值，绝不执行任意代码（无 eval/exec）"""
        import math
        import operator

        expression = (params.get("expression") or "").strip()
        if not expression:
            return {"error": "缺少 expression 参数"}

        binops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        unaryops = {ast.UAdd: operator.pos, ast.USub: operator.neg}
        functions = {
            "sqrt": math.sqrt, "abs": abs, "round": round,
            "min": min, "max": max,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log2": math.log2, "log10": math.log10,
            "floor": math.floor, "ceil": math.ceil,
        }
        constants = {"pi": math.pi, "e": math.e}

        def eval_node(node):
            if isinstance(node, ast.Expression):
                return eval_node(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in binops:
                left = eval_node(node.left)
                right = eval_node(node.right)
                if type(node.op) is ast.Pow and abs(right) > self._CALC_MAX_EXPONENT:
                    raise ValueError(f"指数过大（超过 {self._CALC_MAX_EXPONENT}）")
                return binops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in unaryops:
                return unaryops[type(node.op)](eval_node(node.operand))
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                    raise ValueError("仅允许调用白名单函数")
                if node.keywords:
                    raise ValueError("不支持关键字参数")
                return functions[node.func.id](*[eval_node(a) for a in node.args])
            if isinstance(node, ast.Name) and node.id in constants:
                return constants[node.id]
            raise ValueError(f"不支持的语法: {type(node).__name__}")

        try:
            value = eval_node(parseSource(expression, mode="eval"))
        except ZeroDivisionError:
            return {"expression": expression, "error": "除零错误"}
        except OverflowError:
            return {"expression": expression, "error": "数值溢出"}
        except Exception as e:
            return {"expression": expression, "error": f"表达式无法计算: {e}"}

        if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
            value = int(value)  # 4.0 → 4，便于阅读
        return {"expression": expression, "result": value}

    # 零偏移时区名（UTC 等义名）——按定义恒 +00:00，不查系统 tzdata。
    # 容器/宿主 tzdata 包损坏时，ZoneInfo("UTC") 会安静返回 +08:00；
    # 契约层面 "UTC" 不需要查 tzdata——它是规范定义的零偏移。Issue #62。
    _ZERO_OFFSET_TIMEZONE_NAMES = frozenset({
        "utc", "gmt", "z", "zulu", "universal", "etc/utc", "etc/gmt", "etc/zulu",
        "etc/universal", "gmt0", "etc/gmt0", "utc0", "etc/utc0",
    })

    def _resolve_timezone(self, tz_param: str):
        """解析时区参数 → tzinfo；无法解析返回 None。

        优先级：零偏移等义名（内置 timezone.utc）→ IANA 名称（ZoneInfo）
        → ±HH:MM / GMT+H 偏移字面量。
        """
        import re
        from datetime import timedelta, timezone as dt_timezone

        if tz_param.strip().casefold() in self._ZERO_OFFSET_TIMEZONE_NAMES:
            return dt_timezone.utc
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(tz_param)
        except Exception:
            # IANA 名称解析失败时，尝试 ±HH:MM / GMT+H 风格的偏移
            m = re.fullmatch(r"(?:GMT|UTC)?\s*([+-])(\d{1,2})(?::?(\d{2}))?", tz_param)
            if m:
                sign = 1 if m.group(1) == "+" else -1
                hours, minutes = int(m.group(2)), int(m.group(3) or 0)
                if hours <= 23 and minutes <= 59:
                    return dt_timezone(sign * timedelta(hours=hours, minutes=minutes))
        return None

    async def _execute_get_datetime(self, params: Dict) -> Dict:
        """获取当前日期时间或换算时间戳（支持 IANA 时区名与 ±HH:MM 偏移）"""
        from datetime import timezone as dt_timezone

        tz_param = (params.get("timezone") or params.get("tz") or "").strip()
        ts_param = params.get("timestamp")

        try:
            if ts_param is not None and str(ts_param).strip() != "":
                base_dt = datetime.fromtimestamp(float(ts_param), tz=dt_timezone.utc)
            else:
                base_dt = datetime.now(dt_timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError) as e:
            return {"error": f"无效的时间戳: {ts_param}（{e}）"}

        if tz_param:
            tz = self._resolve_timezone(tz_param)
            if tz is None:
                return {
                    "error": f"无法解析时区: {tz_param}（支持 Asia/Shanghai 等 IANA 名称或 +08:00 偏移）"
                }
            dt = base_dt.astimezone(tz)
        else:
            dt = base_dt.astimezone()  # 系统本地时区

        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return {
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M:%S"),
            "iso": dt.isoformat(),
            "weekday": weekdays[dt.weekday()],
            "timezone": str(dt.tzinfo),
            "timestamp": int(base_dt.timestamp()),
        }
