"""
测试：知识库节点 schema 条件联动（R-9 不同知识库显示不同参数）

契约:
  1. sub_blocks 各参数带 condition（按 kb_type 分组：iflow/feishu/ima/custom 各自字段）
  2. kb_type options 含 local/iflow/feishu/ima/custom
  3. api_url/api_key/dataset_id 仅 custom；app_id/app_secret/space_id 仅 feishu；
     base_url 仅 iflow/ima（与 custom 联动）; allow_local 仅 ima
  4. query/limit/kb_config_id 无 condition（通用）
"""

from neurova.collaboration.neurflow.builtin import BUILTIN_NODES


def _kb_node():
    for n in BUILTIN_NODES:
        if n.get("type") == "builtin:knowledge_base":
            return n
    raise AssertionError("knowledge_base 节点未定义")


class TestKbSchemaConditions:
    def test_options_include_all_types(self):
        kb = _kb_node()
        kb_type = [b for b in kb["sub_blocks"] if b["id"] == "kb_type"][0]
        values = [o["value"] for o in kb_type["options"]]
        assert values == ["local", "iflow", "feishu", "ima", "custom"]

    def test_common_fields_no_condition(self):
        kb = _kb_node()
        # query/limit 始终可见；kb_config_id 本地不可见（无远程配置）
        for fid in ("query", "limit"):
            b = [x for x in kb["sub_blocks"] if x["id"] == fid][0]
            assert b.get("condition") is None, f"{fid} 应始终可见"
        cfg = [x for x in kb["sub_blocks"] if x["id"] == "kb_config_id"][0]
        assert cfg.get("condition", {}).get("value") == "local"

    def test_custom_fields_condition(self):
        kb = _kb_node()
        cond = {b["id"]: b.get("condition") for b in kb["sub_blocks"]}
        # custom 专属: api_url/api_key/dataset_id
        assert cond["api_url"]["field"] == "kb_type" and cond["api_url"]["value"] == "custom"
        assert cond["api_key"]["value"] == "custom"
        assert cond["dataset_id"]["value"] == "custom"

    def test_feishu_fields_condition(self):
        kb = _kb_node()
        cond = {b["id"]: b.get("condition") for b in kb["sub_blocks"]}
        for fid in ("app_id", "app_secret", "space_id"):
            assert cond[fid]["field"] == "kb_type"
            assert cond[fid]["value"] == "feishu"

    def test_iflow_base_url_condition(self):
        kb = _kb_node()
        cond = {b["id"]: b.get("condition") for b in kb["sub_blocks"]}
        bc = cond["base_url"]
        assert bc["field"] == "kb_type"
        assert bc["operator"] == "in"
        assert set(bc["value"]) == {"iflow", "ima"}

    def test_ima_allow_local_condition(self):
        kb = _kb_node()
        cond = {b["id"]: b.get("condition") for b in kb["sub_blocks"]}
        assert cond["allow_local"]["field"] == "kb_type"
        assert cond["allow_local"]["value"] == "ima"
