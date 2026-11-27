import ast

from tests.ast_scan import REPO_ROOT, parseSource, sourceRefsUnder


def testNoAssertionIsTautologicalOrTrue():
    offenders = []
    for ref in sourceRefsUnder(REPO_ROOT / "tests", ".py"):
        tree = parseSource(ref.code)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert):
                continue
            for expression in ast.walk(node.test):
                if not isinstance(expression, ast.BoolOp):
                    continue
                if not isinstance(expression.op, ast.Or):
                    continue
                if any(isinstance(value, ast.Constant) and value.value is True
                       for value in expression.values):
                    offenders.append(f"{ref.path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
                    break
    assert offenders == [], f"恒真断言失去判别力：{offenders}"
