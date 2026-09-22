#!/bin/sh
# NPC 门禁脚本的 node 桥（构建 cnb-9cc-1k34ff3t1 的根因修复）。
#
# ## 为什么需要这层壳
#
# `.cnb.yml` 的解释器探测在镜像只提供 node 时给出 `NPX=node`。但把 `.py`
# 交给 node **跑不起来**：node 按扩展名解析模块，遇到 `.py` 在解析前就以
# `ERR_UNKNOWN_FILE_EXTENSION` 退出（rc=1）—— 那是 node 的模块加载阶段，
# 与脚本内容无关，脚本里任何 `if __name__` 判断都到不了。
# 实测（本仓，node v24）：
#   $ node scripts/ci/npc_turn_handoff_gate.py
#   TypeError [ERR_UNKNOWN_FILE_EXTENSION]: Unknown file extension ".py" ...
#
# 故 node 分支不能写 `$NPX <script>.py`，必须由本壳接管：
#   1. 令脚本吐出自带的 node 实现正文（取回 NODE_IMPLEMENTATION 正文）；
#   2. 写到临时 `.js`；
#   3. 交给 node 执行，把退出码原样传出去。
# 判据、读数键名、退出码三处与 python 分支**逐字等价**（由
# tests/unit/ci/test_npc_script_interpreter_reachability.py 常驻校验）。
#
# 用法：sh scripts/ci/run_gate_under_node.sh scripts/ci/npc_turn_handoff_gate.py [--json ...]
set -e

sourcescript="$1"
shift

if [ ! -f "$sourcescript" ]; then
  echo "门禁脚本不存在: $sourcescript" >&2
  exit 127
fi

# node 分支只在探测确实选中 node 时才走这里；python 可用时本壳不被引用。
if ! command -v node >/dev/null 2>&1; then
  echo "请求了 node 桥但 node 不可用 —— 解释器探测与调用形态不一致" >&2
  exit 127
fi

# 临时文件名自己拼，不依赖 mktemp（部分精简镜像里没有 mktemp，见 node-only 实测）：
# 用脚本自身 PID + 纳秒时间戳，够唯一且不引外部依赖。
nodeimpl="${TMPDIR:-/tmp}/npc_turn_handoff_gate_$$$(date +%s%N 2>/dev/null || echo 0).js"
trap 'rm -f "$nodeimpl"' EXIT INT TERM

# 取回 node 实现正文：这一步只用 node 的读文件能力，不经模块解析，故不受
# `.py` 扩展名影响（脚本自身对 node 提取段落的响应）。
node -e '
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const start = src.indexOf("NODE_IMPLEMENTATION = r\"\"\"");
if (start < 0) { console.error("脚本里取不到 node 实现正文"); process.exit(127); }
const bodyStart = src.indexOf("\n", start) + 1;
const bodyEnd = src.indexOf("\n\"\"\"", bodyStart);
if (bodyEnd < 0) { console.error("node 实现正文未闭合"); process.exit(127); }
fs.writeFileSync(process.argv[2], src.slice(bodyStart, bodyEnd) + "\n");
' "$sourcescript" "$nodeimpl"

exec node "$nodeimpl" "$@"
