"""
test_evolution_init_exports.py — P0-9 (H2): evolution/__init__.py 导出修复

验证 AutoSkillBuilder 已正确导出，且 None 兜底使用 Exception 而非 ImportError。
"""

from __future__ import annotations

import inspect

import pytest


# ============================================================================
# 测试：AutoSkillBuilder 导出（P0-8/P0-9 依赖项）
# ============================================================================

class TestAutoSkillBuilderExport:
    """验证 AutoSkillBuilder 在 evolution 包级别可用"""

    def test_auto_skill_builder_importable(self):
        """测试 1: from neurova.evolution import AutoSkillBuilder 不抛异常

        修复前：evolution/__init__.py 完全没有 import AutoSkillBuilder，
        导致 agent_core.py 的 `from neurova.evolution import AutoSkillBuilder` 抛 ImportError。
        """
        # 这个 import 语句本身即是断言 — 若导出缺失会抛 ImportError
        from neurova.evolution import AutoSkillBuilder
        # AutoSkillBuilder 应为 class 或 None（模块加载失败时兜底）
        assert AutoSkillBuilder is None or inspect.isclass(AutoSkillBuilder)

    def test_auto_skill_builder_is_class_when_skill_encapsulation_available(self):
        """测试 2: 当 skill_encapsulation 模块可用时，AutoSkillBuilder 应为 class

        修复前：导出缺失，即使 skill_encapsulation.py 中定义了 AutoSkillBuilder 也无法访问。
        """
        from neurova.evolution import AutoSkillBuilder
        # 若 skill_encapsulation 模块加载成功，AutoSkillBuilder 应为 class
        # 若模块加载失败（依赖缺失），应为 None
        if AutoSkillBuilder is not None:
            assert inspect.isclass(AutoSkillBuilder), \
                f"AutoSkillBuilder 应为 class 或 None，实际为 {type(AutoSkillBuilder)}"

    def test_all_list_includes_auto_skill_builder(self):
        """测试 3: AutoSkillBuilder 应在 evolution.__all__ 中

        修复前：__all__ 未包含 AutoSkillBuilder。
        """
        from neurova import evolution
        assert "AutoSkillBuilder" in evolution.__all__, \
            f"AutoSkillBuilder 未在 evolution.__all__ 中，当前 __all__: {evolution.__all__}"


# ============================================================================
# 测试：None 兜底使用 Exception 而非 ImportError（P0-9 核心）
# ============================================================================

class TestNoneFallbackExceptionType:
    """验证 except 子句使用 Exception 而非 ImportError（覆盖运行时错误）"""

    def test_no_importerror_only_except_clauses(self):
        """测试 4: evolution/__init__.py 不应有裸 `except ImportError`

        修复前：三个 try 块都用 `except ImportError`，无法捕获运行时错误（如 AttributeError）。
        修复后：应使用 `except Exception` 覆盖所有常规异常。
        """
        import neurova.evolution as evolution_mod
        import ast
        import pathlib

        init_path = pathlib.Path(evolution_mod.__file__)
        source = init_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        import_error_only_handlers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # 获取 except 子句的类型
                if node.type is None:
                    # 裸 except: — 不应在 __init__.py 中出现
                    import_error_only_handlers.append(
                        f"line {node.lineno}: 裸 except: (应使用 except Exception)"
                    )
                elif isinstance(node.type, ast.Name) and node.type.id == "ImportError":
                    # except ImportError — 应改为 except Exception
                    import_error_only_handlers.append(
                        f"line {node.lineno}: except ImportError (应改为 except Exception)"
                    )

        assert not import_error_only_handlers, \
            f"evolution/__init__.py 仍有 {len(import_error_only_handlers)} 处不正确的 except 子句: {import_error_only_handlers}"

    def test_skill_encapsulation_import_block_exists(self):
        """测试 5: 应有独立的 skill_encapsulation 导入块

        修复前：evolution/__init__.py 没有 import AutoSkillBuilder 的 try 块。
        """
        import neurova.evolution as evolution_mod
        import pathlib

        init_path = pathlib.Path(evolution_mod.__file__)
        source = init_path.read_text(encoding="utf-8")

        # 检查源码中是否有 from .skill_encapsulation import AutoSkillBuilder
        assert "from .skill_encapsulation import" in source, \
            "evolution/__init__.py 缺少 from .skill_encapsulation import 语句"
        assert "AutoSkillBuilder" in source, \
            "evolution/__init__.py 缺少 AutoSkillBuilder 引用"
