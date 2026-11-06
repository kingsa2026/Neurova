"""四动词访问门面的对外契约档（升级计划 §10 B3 行与 §13.2 K-08 欠的那件事）。

票面原话：门面「仓内零消费者，按对外契约管理；补 OpenAPI/SDK 契约测试；
不宣称已闭环」。此前只有功能测试（转发对不对、状态码对不对），
**没有任何一格把 OpenAPI 形状钉住**——也就是说"对外承诺"这件事只写在文档里，
机器上不成立。本档补的就是这一段，并顺手改掉两处让契约无法成立的形状：

  use     请求体原先是 `Dict[str, Any]` 再 `model_validate`——OpenAPI 只能广告成
          自由对象，等于对外承诺"什么都能发"，而实际闭集是 outcome 三态；
  analyze 请求体同样是裸 dict——广告不出它唯一消费的 `query`。

两处都改成**在被转交方声明模型**，门面只 import（门面自己的"零 schema"承诺不破）。
另一面也钉住：`/openapi.json` 与 `/docs` 在本仓是公开面缺席（既有 e2e 钉 404），
所以对外契约的可得方式是"进程内 spec ＋ SDK 侧手写类型"，这格把该决定写成判据，
而不是留给下一个人重新发现。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FACADE = REPO_ROOT / "neurova" / "api" / "endpoints" / "knowledge_access_facade.py"
TS_CLIENT = REPO_ROOT / "NeurUI" / "src" / "api" / "modules" / "ontology.ts"
TS_TYPES = REPO_ROOT / "NeurUI" / "src" / "types" / "ontology.ts"

PREFIX = "/api/v1/knowledge"
VERB_PATHS = {
    "query": f"{PREFIX}/access/query",
    "analyze": f"{PREFIX}/access/analyze",
    "validate": f"{PREFIX}/access/validate",
    "use": f"{PREFIX}/access/use/{{fact_id}}",
}


@pytest.fixture(scope="module")
def spec():
    """真装配：create_app() 起完整路由表，取**进程内** openapi。"""
    from neurova.api.app import create_app

    return create_app().openapi()


def _resolve(spec_dict: dict, ref: str) -> dict:
    name = ref.rsplit("/", 1)[-1]
    return spec_dict.get("components", {}).get("schemas", {}).get(name, {})


def _operation(spec_dict: dict, path: str, method: str = "post") -> dict:
    return spec_dict["paths"][path][method]


def _bodyProperties(spec_dict: dict, path: str):
    op = _operation(spec_dict, path)
    content = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    if "$ref" in schema:
        schema = _resolve(spec_dict, schema["$ref"])
    return set(schema.get("properties", {}).keys()), schema


@pytest.mark.parametrize("verb,path", sorted(VERB_PATHS.items()))
def test_eachVerbIsAdvertisedWithItsMethod(spec, verb, path):
    """① 四个动词都在册，且只有 POST（GET 一律 404——门面不另开读面）。"""
    assert path in spec["paths"], f"{verb} 动词的路由没进对外 spec：{path}"
    assert set(spec["paths"][path]) == {"post"}, (
        f"{verb} 广告了 POST 之外的方法：{sorted(spec['paths'][path])}"
    )


def testQueryBodyAdvertisesEverythingTheFrontendSends(spec):
    """② query 的 body 形状必须覆盖前端真发的那些字段——少一个就是跨语言契约断点。

    取的是 `NeurUI/src/types/ontology.ts` 的 FactQueryBody（真发出去的那份形状），
    不是文档里描述的形状；`asOf`/`knownAt` 是双时态那两个轴，缺了它们这一格就会红
    （B11 接线时正是靠这格提醒"页面发了但契约里没有"）。
    """
    ts = TS_TYPES.read_text(encoding="utf-8")
    block = re.search(r"export interface FactQueryBody \{([\s\S]*?)\n\}", ts)
    assert block, "FactQueryBody 在 types/ontology.ts 里找不到（形状被改名或删除？）"
    sent = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??:", block.group(1), re.M))
    advertised, _ = _bodyProperties(spec, VERB_PATHS["query"])
    missing = sorted(sent - advertised)
    assert not missing, f"query 的 spec 没广告前端真发的这些字段：{missing}"

    params = {p["name"] for p in _operation(spec, VERB_PATHS["query"]).get("parameters", [])}
    assert {"agent_id", "scope"} <= params, f"query 的门面参数没进 spec：{sorted(params)}"


def testValidateTriplesAreNamedIdenticallyOnBothSides(spec):
    """③ validate 的三元组条目字段必须与前端逐字同名（后端 camelCase 是刻意选的对外形状）。

    这条钉的是"同名字不能各写一半"：后端 `OntologyValidateCandidate` 用
    subjectLabel/subjectKey/predicateTermId/objectTerm/qualifier，前端 ValidateTriple 同形。
    任何一侧改名而另一侧没跟上，这一格当场红——dry-run 静默拿到空三元组比报错更糟。
    """
    ts = TS_TYPES.read_text(encoding="utf-8")
    block = re.search(r"export interface ValidateTriple \{([\s\S]*?)\n\}", ts)
    assert block, "ValidateTriple 在 types/ontology.ts 里找不到"
    frontend = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??:", block.group(1), re.M))

    advertised, schema = _bodyProperties(spec, VERB_PATHS["validate"])
    assert {"tenantId", "agentId", "triples"} <= advertised, f"validate 请求体形状变了：{sorted(advertised)}"
    itemRef = schema["properties"]["triples"]["items"]["$ref"]
    itemProps = set(_resolve(spec, itemRef).get("properties", {}).keys())
    assert itemProps == frontend, (
        f"三元组字段两侧不同名：只有后端有 {sorted(itemProps - frontend)}，"
        f"只有前端有 {sorted(frontend - itemProps)}"
    )


def testAnalyzeAdvertisesTheKeyItActuallyConsumes(spec):
    """④ analyze 不许再对外广告"什么都能发"：它只消费 `query`，spec 就得只说 `query`。

    原形态 `body: Dict[str, Any]` 在 spec 里是一个没有 properties 的自由对象——
    对外承诺等于"参数随便发"，而实际只有一个键起作用（教义第 2 条的反面：
    契约上说说、body 里不做）。
    """
    advertised, _ = _bodyProperties(spec, VERB_PATHS["analyze"])
    assert "query" in advertised, (
        f"analyze 的请求体没广告任何字段形状（实读 {sorted(advertised)}）——"
        "对外契约退化成自由对象"
    )


def testUseVerbAdvertisesTheClosedOutcomeSet(spec):
    """⑤ use 的 outcome 必须是闭集三态，且前端只发这一个键。"""
    advertised, schema = _bodyProperties(spec, VERB_PATHS["use"])
    assert advertised == {"outcome"}, f"use 的请求体形状不止 outcome：{sorted(advertised)}"
    enum = set(schema["properties"]["outcome"].get("enum", []))
    assert enum == {"success", "failure", "unevidenced"}, f"outcome 闭集漂移：{sorted(enum)}"

    client = TS_CLIENT.read_text(encoding="utf-8")
    start = client.index("export function accessUse")
    block = client[start:start + 600]
    assert re.search(r"body:\s*\{\s*outcome:\s*string\s*\}", block), (
        "前端 accessUse 发的 body 形状不再是单一 outcome——后端闭集与前端发法"
        "必须是同一件事，改一侧就改两侧"
    )
    assert f"`{PREFIX[6:]}/access/use/" in block or "/access/use/" in block, (
        "前端 use 的路径模板与 spec 里的 `/access/use/{fact_id}` 不再是同一条"
    )


def testFacadeStaysSchemaFreeAndNeverTakesRawDictBodies():
    """⑥ 结构闸：门面零 schema，且不得再用裸 dict 收请求体。

    两句话是同一件事的两面：转交方要么声明模型（则门面 import），要么没有契约。
    一旦出现 `body: Dict[str, Any]`，第 ④⑤ 格会红，而这一格先红——红在形状上，
    不让人等到 spec 检查才发现契约又空了一轮。
    """
    source = FACADE.read_text(encoding="utf-8")
    code = re.sub(r"/\*[\s\S]*?\*/", "", re.sub(r"(^|[^:'\"])//[^\n]*", r"\1", source))
    assert "class " not in code, "门面里出现了 schema 定义——声明应在被转交方，门面只 import"
    assert "body: Dict[str, Any]" not in code, (
        "门面请求体又退回裸 dict（对外契约将再次广告不出字段）"
    )


def testPublicSpecSurfaceStaysClosed():
    """⑦ 反向钉既有决定：`/openapi.json`、`/docs` 不对外（本档用的是进程内 spec）。

    写成一格而不是靠记忆里那句"e2e 钉过"：如果哪天有人为了 SDK 放开公开 spec，
    这里是第一个要重新拍板的地方（放开＝新增一条未鉴权的信息面）。
    """
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    client = TestClient(create_app())
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404, f"{path} 现在对外可取了——本档的前提变了，先改这格再说"
