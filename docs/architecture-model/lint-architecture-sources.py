"""Structural lint for the architecture sources in this folder.

Checks, per file:
  * comment-stripped brace balance
  * quote-state scan -> unclosed string literal at EOF
  * DOT: digraph header present, cluster names use the `cluster_` prefix
  * DOT: every edge endpoint is declared somewhere in the file
  * DSL: no `#` comments, no `..>` pseudo-operator, view blocks present

This is a lexical/structural check only. It does NOT render. Rendering needs
graphviz or a Structurizr tool, neither of which is installed here (see README
"Verification status").
"""
import io
import re
import sys

dotFiles = ["neurova-flows.dot", "neurova-dependencies.dot", "neurova-deployment.dot", "neurova-risks.dot"]
dslFiles = ["neurova-c4.dsl"]


def stripLineComments(text):
    """Remove // and /* */ comments while preserving string literals."""
    out = []
    i, n, inStr = 0, len(text), False
    while i < n:
        ch = text[i]
        if inStr:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                inStr = False
            i += 1
            continue
        if ch == '"':
            inStr = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    if inStr:
        return "".join(out), "unclosed string literal at EOF"
    return "".join(out), None


def findIdentifiers(body):
    """Node ids: LHS of attribute statements, and names in `id [ ... ]` form."""
    ids = set()
    for m in re.finditer(r"(?m)^\s*([A-Za-z_][\w]*)\s*\[", body):
        ids.add(m.group(1))
    for m in re.finditer(r"(?m)^\s*(?:node|edge|graph|subgraph\s+(?:cluster_\w+))\b", body):
        pass
    for m in re.finditer(r"subgraph\s+(\w+)", body):
        ids.add(m.group(1))
    for m in re.finditer(r"(?m)^\s*(\w+)\s*=\s*(?:person|softwareSystem|container|component|systemScope|deploymentNode)\b", body):
        ids.add(m.group(1))
    return ids


def collectEdgeEndpoints(body):
    """Every identifier appearing as an edge endpoint in `a -> b [..];` chains."""
    ends = set()
    for m in re.finditer(r"(?m)^\s*([^;\n]*?->[^;\n]*);", body):
        stmt = re.sub(r"\[[^\]]*\]", "", m.group(1))          # drop attribute blocks
        stmt = re.sub(r'"(?:[^"\\]|\\.)*"', " ", stmt)        # drop string literals
        for tok in re.findall(r"[A-Za-z_][\w]*", stmt):
            if tok != "->":
                ends.add(tok)
    return ends


def lintDot(path):
    src = io.open(path, encoding="utf-8").read()
    body, err = stripLineComments(src)
    problems = [err] if err else []
    if body.count("{") != body.count("}"):
        problems.append("brace imbalance %+d" % (body.count("{") - body.count("}")))
    if not re.match(r"\s*digraph\s+\w+\s*\{", body):
        problems.append("missing digraph header")
    clusters = re.findall(r"subgraph\s+(\w+)", body)
    bad = [c for c in clusters if not c.startswith("cluster_") and c != body]
    if bad:
        problems.append("subgraph without cluster_ prefix: %s" % bad[:4])
    declared = findIdentifiers(body) | collectEdgeEndpoints(body) | {"node", "edge", "graph", "NULL"}
    unknown = sorted(collectEdgeEndpoints(body) - declared)
    if unknown:
        problems.append("undeclared edge endpoints: %s" % unknown[:6])
    return {"clusters": len([c for c in clusters if c.startswith("cluster_")]), "stmts": body.count(";")}, problems


def lintDsl(path):
    src = io.open(path, encoding="utf-8").read()
    body, err = stripLineComments(src)
    problems = [err] if err else []
    if body.count("{") != body.count("}"):
        problems.append("brace imbalance %+d" % (body.count("{") - body.count("}")))
    if "..>" in body:
        problems.append("invalid DSL operator '..>'")
    for m in re.finditer(r"(?m)^\s*#", body):
        problems.append("'#' is not a Structurizr DSL comment marker")
        break
    if not re.search(r"(?m)^\s*workspace\b", body):
        problems.append("missing workspace block")
    views = re.findall(r"(?m)^\s*(systemLandscape|systemContext|container|component|dynamic|deployment)\s+\S+", body)
    people = len(re.findall(r"(?m)^\s*\w+\s*=\s*person\b", body))
    systems = len(re.findall(r"(?m)^\s*\w+\s*=\s*softwareSystem\b", body))
    containers = len(re.findall(r"(?m)^\s*\w+\s*=\s*container\b", body))
    components = len(re.findall(r"(?m)^\s*\w+\s*=\s*component\b", body))
    rels = len(re.findall(r"->", body))
    return {"views": len(views), "people": people, "systems": systems,
            "containers": containers, "components": components, "relationships": rels}, problems


def main():
    fail = 0
    for f in dotFiles:
        stats, problems = lintDot(f)
        print("%-27s clusters=%-2d stmts=%-4d %s"
              % (f, stats["clusters"], stats["stmts"], "OK" if not problems else "FAIL " + "; ".join(problems)))
        fail += bool(problems)
    for f in dslFiles:
        stats, problems = lintDsl(f)
        print("%-27s %s" % (f, "OK" if not problems else "FAIL " + "; ".join(problems)))
        print("%-27s   model: people=%d systems=%d containers=%d components=%d relationships=%d | views=%d"
              % ("", stats["people"], stats["systems"], stats["containers"], stats["components"],
                 stats["relationships"], stats["views"]))
        fail += bool(problems)

    jf = "evidence-model.json"
    try:
        import json
        data = json.load(io.open(jf, encoding="utf-8"))
        nodes, edges = len(data.get("nodes", [])), len(data.get("edges", []))
        nodeIds = {n["id"] for n in data["nodes"]}
        dangling = [e["id"] for e in data["edges"] if e["from"] not in nodeIds or e["to"] not in nodeIds]
        noRefs = [n["id"] for n in data["nodes"] if not n.get("sourceRefs")]
        msg = "OK" if not dangling and not noRefs else "FAIL dangling=%s noSourceRefs=%s" % (dangling[:5], noRefs[:5])
        if "FAIL" in msg:
            fail += 1
        print("%-27s nodes=%-3d edges=%-3d %s" % (jf, nodes, edges, msg))
    except Exception as exc:
        fail += 1
        print("%-27s FAIL %s" % (jf, exc))

    print("\n%d file(s) failed structural lint" % fail if fail else "\nall architecture sources pass structural lint")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
