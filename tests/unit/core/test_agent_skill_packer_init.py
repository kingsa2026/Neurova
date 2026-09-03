"""
test_agent_skill_packer_init.py — P0-8 (H1): AutoSkillBuilder 静默禁用补全

验证 agent_core.py 中 AutoSkillBuilder 初始化代码的三处修复：
1. 参数名：min_occurrences → min_pattern_occurrences（对齐 skill_encapsulation.py 签名）
2. 异常类型：except ImportError → except Exception（覆盖 TypeError 等构造异常）
3. None 兜底：异常分支显式 self.skill_packer = None

采用静态分析（ast）验证源码，避免实例化 Agent 的重量级依赖。
"""

from __future__ import annotations

import ast
import pathlib

import pytest


def _get_agent_core_source() -> str:
    """读取 agent_core.py 源码"""
    import neurova.agent_core as agent_core_mod
    return pathlib.Path(agent_core_mod.__file__).read_text(encoding="utf-8")


def _find_skill_packer_init_node(tree: ast.AST) -> ast.Try | None:
    """定位包含 AutoSkillBuilder 的 try 块"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "AutoSkillBuilder"):
                    return node
                # 也可能是直接 Name 调用（from neurova.evolution import AutoSkillBuilder）
                if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "AutoSkillBuilder"):
                    return node
    return None


class TestSkillPackerParamName:
    """测试 1: 参数名应为 min_pattern_occurrences（对齐 skill_encapsulation.py 签名）"""

    def test_no_min_occurrences_typo(self):
        """验证源码中不再有错误的 min_occurrences 参数名

        修复前：AutoSkillBuilder(min_occurrences=3, ...) — 参数名错误，抛 TypeError
        修复后：AutoSkillBuilder(min_pattern_occurrences=3, ...)
        """
        source = _get_agent_core_source()
        # 不应出现 min_occurrences=（错误参数名）
        assert "min_occurrences=" not in source, \
            "agent_core.py 仍有错误的参数名 min_occurrences=，应为 min_pattern_occurrences="

    def test_has_correct_param_name(self):
        """验证源码中有正确的 min_pattern_occurrences 参数名"""
        source = _get_agent_core_source()
        assert "min_pattern_occurrences=" in source, \
            "agent_core.py 缺少正确的参数名 min_pattern_occurrences="


class TestSkillPackerExceptionType:
    """测试 2: 异常类型应为 except Exception（覆盖 TypeError 等构造异常）"""

    def test_no_importerror_only_for_skill_packer(self):
        """验证 AutoSkillBuilder try 块的 except 不是 ImportError

        修复前：except ImportError as e — 无法捕获 TypeError，导致 Agent 初始化崩溃
        修复后：except Exception as e — 覆盖所有常规异常
        """
        source = _get_agent_core_source()
        tree = ast.parse(source)

        skill_packer_try = _find_skill_packer_init_node(tree)
        assert skill_packer_try is not None, \
            "未找到包含 AutoSkillBuilder 的 try 块"

        # 检查该 try 块的所有 except handler
        for handler in skill_packer_try.handlers:
            if handler.type is None:
                # 裸 except: — 也不允许
                pytest.fail(
                    f"line {handler.lineno}: AutoSkillBuilder try 块有裸 except:，"
                    f"应使用 except Exception"
                )
            elif isinstance(handler.type, ast.Name) and handler.type.id == "ImportError":
                pytest.fail(
                    f"line {handler.lineno}: AutoSkillBuilder try 块使用 except ImportError，"
                    f"无法捕获 TypeError，应改为 except Exception"
                )
            # 允许: except Exception, except (ImportError, TypeError) 等

    def test_exception_caught_is_broad_enough(self):
        """验证 except 子句能捕获 Exception（覆盖 TypeError）"""
        source = _get_agent_core_source()
        tree = ast.parse(source)

        skill_packer_try = _find_skill_packer_init_node(tree)
        assert skill_packer_try is not None

        # 至少有一个 handler 能捕获 Exception
        catches_exception = False
        for handler in skill_packer_try.handlers:
            if handler.type is None:
                catches_exception = True
                break
            # except Exception
            if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                catches_exception = True
                break
            # except (..., Exception, ...) 或 except (..., BaseException, ...)
            if isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name) and elt.id in ("Exception", "BaseException"):
                        catches_exception = True
                        break

        assert catches_exception, \
            "AutoSkillBuilder try 块的 except 子句无法捕获 Exception（无法覆盖 TypeError）"


class TestSkillPackerNoneFallback:
    """测试 3: 异常分支应显式置 self.skill_packer = None"""

    def test_skill_packer_set_to_none_in_except(self):
        """验证 except 分支有 self.skill_packer = None

        修复前：except 分支只记录日志，未置 self.skill_packer = None
        → 后续引用 self.skill_packer 会抛 AttributeError
        修复后：except 分支显式 self.skill_packer = None
        """
        source = _get_agent_core_source()
        tree = ast.parse(source)

        skill_packer_try = _find_skill_packer_init_node(tree)
        assert skill_packer_try is not None

        # 在 except handler 中查找 self.skill_packer = None 赋值
        found_none_assignment = False
        for handler in skill_packer_try.handlers:
            for stmt in ast.walk(handler):
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                            and target.attr == "skill_packer"):
                            # 检查赋值是否为 None
                            if (isinstance(stmt.value, ast.Constant)
                                and stmt.value.value is None):
                                found_none_assignment = True
                                break

        assert found_none_assignment, \
            "AutoSkillBuilder 的 except 分支缺少 self.skill_packer = None 兜底"


class TestSkillPackerDisabledWhenFlagFalse:
    """测试 4: enable_skill_packer=False 时应跳过初始化"""

    def test_skill_packer_guarded_by_enable_flag(self):
        """验证 AutoSkillBuilder 初始化受 enable_skill_packer 配置守卫"""
        source = _get_agent_core_source()
        tree = ast.parse(source)

        # 找到包含 AutoSkillBuilder 的 try 块
        skill_packer_try = _find_skill_packer_init_node(tree)
        assert skill_packer_try is not None

        # 验证 try 块之前有 if self.config.enable_skill_packer 守卫
        # 通过检查源码中 try 块上方是否有该条件
        lines = source.splitlines()
        # 找到 try 块的起始行（ast lineno 是 1-indexed，lines 是 0-indexed）
        try_line = skill_packer_try.lineno
        # 向上查找 if 条件（允许几行空白和注释）
        found_guard = False
        # i 是 1-indexed 行号，lines[i-1] 是对应的 0-indexed 行
        for i in range(try_line - 1, max(try_line - 10, 0), -1):
            line = lines[i - 1].strip() if 0 < i <= len(lines) else ""
            if "enable_skill_packer" in line and "if " in line:
                found_guard = True
                break
            if line and not line.startswith("#") and not line.startswith('"""'):
                # 遇到非注释非空行，停止向上搜索
                break

        assert found_guard, \
            "AutoSkillBuilder 初始化未受 if self.config.enable_skill_packer 守卫"
