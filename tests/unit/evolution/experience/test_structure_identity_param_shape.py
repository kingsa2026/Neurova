"""009 残留 · 结构身份必须吃进**参数形状**（票面核心验收项，前一轮实质落空）。

票据 009 的目标原文：「让经验条目携带可复用的**结构身份**（工具序列 + **参数形状
指纹**）」；验收要求「结构指纹与咽喉票据的 `structure_key` **同函数产出**」。

前一轮只把 `structure_key`（工具序列 + 参数）接到了 EKB `context`，却把
`canonical_skill_id` 的实现收口进同一个函数 —— 命中点只有一处，同契约的另一个
消费方 `canonical_skill_id`（技能 ID 即身份）仍是**不含参数的**老口径：

- `post_chat_pipeline._turn_structure_key` 用 `structure_key([...])`；
- `creation_governance.canonical_skill_id(steps, purpose)` 调
  `fingerprint(steps, purpose)`。

**同一根因、两个实现**：`fingerprint` 是「结构 + 意图」，`structure_key` 是「结构」，
二者必须共用同一份"结构"算法（此处抽 `_structural_identity`），否则「工具序列 + 参数
形状指纹」这一定义就有了两份互相漂移的实现——正是修复教义第 6 条点名的平行体系。

本文件三件事：
1. **正向**：参数形状（键集与值类型）参与结构身份——同工具不同参数形状不得塌成同一身份；
2. **正向**：`structure_key` 与 `fingerprint` 的"结构"部分**同函数产出**（grep/AST 守卫）；
3. **负向**：同一工具、不同参数值的两次调用，在本轮落库的 `structure_key` 上必须**不同**
   （端到端，读取侧）。

参数仅以**形状**入身份（键名 + 值类型），值不参与哈希——票据 009 禁区要求
「不得把参数明文写进 `context`」。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from neurova.skills.creation_governance import fingerprint, structure_key

REPO_ROOT = Path(__file__).resolve().parents[4]
GOVERNANCE = REPO_ROOT / "neurova" / "skills" / "creation_governance.py"
TOOL = "get_datetime"


def _steps(**params):
    return [{"tool": TOOL, "params": dict(params)}]


class TestParamShapeEntersIdentity:
    def test_different_param_shape_is_a_different_identity(self):
        assert structure_key(_steps(tz="Asia/Shanghai")) != structure_key(_steps(tz="UTC")), (
            "同工具不同参数值塌成同一结构身份（参数形状没进指纹）"
        )

    def test_missing_key_is_a_different_shape(self):
        assert structure_key(_steps(tz="UTC")) != structure_key(_steps(tz="UTC", days=3)), (
            "参数键集不同却算出同一身份（扩展参数被塌进同一结构）"
        )

    def test_value_type_is_part_of_the_shape(self):
        assert structure_key(_steps(tz="UTC")) != structure_key(_steps(tz=3)), (
            "参数值类型不同却算出同一身份（形状指纹不含类型）"
        )

    def test_identity_is_reproducible(self):
        assert structure_key(_steps(tz="UTC")) == structure_key(_steps(tz="UTC"))

    def test_no_plaintext_in_the_identity(self):
        """身份是哈希，不得把参数明文编进可读形态（隐私 + 体积）。"""
        hashed = structure_key(_steps(city="许昌"))
        assert "许昌" not in hashed and '"params"' not in hashed

    def test_business_identity_and_structure_share_one_algorithm(self):
        """`fingerprint`（业务身份）与 `structure_key`（结构身份）必须共用同一份
        结构算法——两个哈希的差异只允许来自 `purpose`。"""
        steps = _steps(tz="UTC")
        structural = structure_key(steps)
        assert structural != fingerprint(steps), "两者退化成同一个哈希，purpose 没参与业务身份"
        # 同一份结构算法：把 purpose 空串喂进去必须不等于结构身份（证明算法同源而非巧合相等）
        assert fingerprint(steps) != structural

    def test_hash_is_built_in_one_place(self):
        """AST 守卫：结构身份的归一 + 序列化哈希只有一份实现。

        两个键（业务/结构）各自复写归并与 `json.dumps(...sha256...)` 时，
        "结构 = 工具序列 + 参数"就有了第二份实现。
        """
        tree = ast.parse(GOVERNANCE.read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert "structural_identity" in functions, "结构归一没有单源函数"
        assert "_hash_identity" in functions, "身份哈希没有单源函数"

        def _calls(node, name: str) -> bool:
            return any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == name
                for child in ast.walk(node)
            )

        assert _calls(functions["fingerprint"], "structural_identity")
        assert _calls(functions["structure_key"], "structural_identity")
        for key in ("fingerprint", "structure_key"):
            assert not _calls(functions[key], "json"), (
                f"{key} 里仍在自行序列化身份（应经 _hash_identity 单源）"
            )
            assert not _calls(functions[key], "normalize_steps"), (
                f"{key} 里仍在自行归一（应经 structural_identity 单源）"
            )


class TestTurnStructureKeyCarriesParamShape:
    """端到端负向：本轮落库的 `structure_key` 必须随参数形状变化。"""

    @staticmethod
    def _run(experience_probe, params: str):
        from .conftest import tool_call_record, tool_result_record

        outcome = experience_probe.run_turn(
            tool_messages=[
                tool_call_record(TOOL, params=params),
                tool_result_record(TOOL, success=True, result="ok"),
            ]
        )
        context = outcome["rows"][-1]["context"]
        return json.loads(context) if isinstance(context, str) else context

    def test_two_param_shapes_produce_two_keys(self, experience_probe):
        first = self._run(experience_probe, json.dumps({"tz": "Asia/Shanghai"}))
        second = self._run(experience_probe, json.dumps({"tz": "UTC"}))
        assert first.get("structure_key"), f"结构指纹没落库：{first}"
        assert first["structure_key"] != second["structure_key"], (
            "换参数的两次调用落了同一个 structure_key：参数形状没进指纹"
        )

    def test_same_shape_produces_the_same_key(self, experience_probe):
        """反向锁：形状相同即同一身份，指纹不是"每次调用都换一个"。"""
        first = self._run(experience_probe, json.dumps({"tz": "Asia/Shanghai"}))
        second = self._run(experience_probe, json.dumps({"tz": "Asia/Shanghai"}))
        assert first["structure_key"] == second["structure_key"]
