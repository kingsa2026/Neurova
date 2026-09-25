#!/usr/bin/env node
/**
 * 跨文件同名函数定义盘点（可复跑口径，Issue #192 待办项收口）。
 *
 * 单一事实源：本脚本是「同名函数」口径的唯一出处；`docs/05-reports/`
 * 的登记台账由 `--write-ledger` 生成机器段，守卫测试
 * `src/tests/duplicate-function-inventory.guard.test.ts` 读回并逐组比对，
 * 台账与代码不一致即判红（禁止手抄第二份清单）。
 *
 * 来由：Issue #192 收口评论登记过一条「全仓另有 91 组同名函数」的待办，
 * 但那个数字没有随产物落盘，也没写出口径 —— 后人无法复跑核对，属事实源缺失。
 * 本脚本把口径钉成可执行形态，并给出分档结论：
 *
 *   A 类「同名同体 · 无局部耦合」—— 体逐字相同、不读页面局部状态与 i18n 文案，
 *      属真重复，必须收口到单一属主（否则两侧各自漂移）；
 *   B 类「同名同体 · 耦合局部状态」—— 体相同但读写本页 ref / 调本页编排函数
 *      （如 openCreate → resetForm + showModal），属页面编排胶水，强行合并只会
 *      造出无谓间接层，登记不收口；
 *   C 类「同名异体」—— 契约或语义不同（入参单位、空值占位、格式化档位差异），
 *      逐组暴露，保留并登记，禁止按名字强行合并。
 *
 * 口径（`--help` 亦输出同一份，机器可读见 `--json`）：
 *   1. 扫描范围：`NeurUI/src`；
 *   2. 文件：`.vue` / `.ts`，排除 `__tests__` 与 `*.test.ts` / `*.spec.ts`；
 *   3. 定义形态：`function name(...)`、`const name = (...) =>`、
 *      `const name = async (...) =>`；参数表允许跨行，但形参表内不得出现
 *      `{` `}` `;`（避免把 `const data = (res as any)?.data ?? res` 这类
 *      局部取值语句误判为函数定义）；
 *   4. 同名判定：按函数名聚合，且定义所在**文件数 ≥ 2**（同文件内重名不算
 *      跨文件平行定义）；
 *   5. 同体判定：体文本去注释、去空白后逐字相等；体为花括号配平块，
 *      表达式体取该语句行；
 *   6. 局部耦合判据：体内出现页面 ref 解引用 `.value`、`props.`、`ref(`、
 *      `computed(`、i18n `t(`、`message.`、`route.`/`router.` 任一（均带词界，
 *      `split(` 不算），即判为耦合页面局部状态 —— 闭包捕获本组件作用域符号的
 *      同名函数不是可复用纯函数，收口前必须先把它参数化。
 *
 * 用法：
 *   node scripts-qa/duplicate-function-audit.mjs                     # 人读分档清单
 *   node scripts-qa/duplicate-function-audit.mjs --json              # 机器可读计数
 *   node scripts-qa/duplicate-function-audit.mjs --write-ledger <f>  # 生成台账机器段
 *   node scripts-qa/duplicate-function-audit.mjs --help              # 口径说明
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const SCAN_SUFFIXES = ['.vue', '.ts']
export const SCAN_ROOT_LABEL = 'NeurUI/src'
const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', '__tests__'])
const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SCAN_ROOT = join(PROJECT_ROOT, 'src')

/**
 * 局部耦合判据：函数体出现任一即说明它依赖所在页面的状态或 i18n 上下文，
 * 属页面编排胶水而非可复用纯函数。用带词界的正则而不是裸子串，
 * 否则 `p.split(` 的 `t(`、`paint.value(` 的 `t(` 都会被误判。
 */
export const LOCAL_COUPLING_PATTERNS = [
  { name: '页面 ref / computed 解引用', pattern: /\.value\b/ },
  { name: '组件 props', pattern: /\bprops\./ },
  { name: '组合式 API ref(', pattern: /(?:^|[^\w$.])ref\s*\(/ },
  { name: 'computed(', pattern: /(?:^|[^\w$.])computed\s*\(/ },
  { name: 'i18n t(', pattern: /(?:^|[^\w$.])t\s*\(/ },
  { name: '统一提示 message.', pattern: /\bmessage\./ },
  { name: '本组件的路由实例', pattern: /(?:^|[^\w$.])(?:route|router)\s*\./ },
]

/**
 * 声明式定义匹配。参数表用 `[^;{}]*` 而非 `[^)]*`：前者跨行安全且拒绝
 * 含块起始的伪匹配；再要求参数表后必须是 `{`（声明）或 `=>`（箭头），
 * 于是 `const data = (res as any)?.data ?? res` 一律不入选。
 */
const DECLARATION = /(?:^|\n)[ \t]*(?:export[ \t]+)?(?:default[ \t]+)?function[ \t]+([A-Za-z_$][\w$]*)[ \t]*\(([^;{}]*)\)[ \t]*(?::[^\n{;]*)?\{/g
const ARROW_FUNCTION = /(?:^|\n)[ \t]*(?:export[ \t]+)?const[ \t]+([A-Za-z_$][\w$]*)[ \t]*=[ \t]*(?:async[ \t]*)?\(([^;{}]*?)\)[ \t]*(?::[^\n={;]*)?=>/g

/** 花括号配平截块；表达式体（`=> 值`）读到语句末（含跨行三元）。 */
function sliceBlock(source, braceAt) {
  let depth = 0
  for (let i = braceAt; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(braceAt, i + 1)
    }
  }
  return source.slice(braceAt)
}

function sliceExpressionBody(source, fromIndex) {
  let depth = 0
  for (let i = fromIndex; i < source.length; i++) {
    const ch = source[i]
    if (ch === '(' || ch === '[') depth++
    else if (ch === ')' || ch === ']') depth--
    else if ((ch === '\n' || ch === ';') && depth <= 0) return source.slice(fromIndex, i)
  }
  return source.slice(fromIndex)
}

/**
 * 取函数体。箭头函数的体可能起在匹配行的**下一行**（
 * `const f = (v) =>\n  v ? ... : '-'`），故先跳过 `=>` 之后的所有空白，
 * 再看首个非空白字符是不是 `{`：是则按块体配平截取，否则按表达式体读到语句末。
 * 声明式函数必为块体，`{` 由正则保证出现在参数表与返回类型之后。
 */
function readFunctionBody(source, match, isDeclaration) {
  const afterMatch = match.index + match[0].length
  if (isDeclaration) {
    const braceAt = source.lastIndexOf('{', afterMatch)
    return braceAt === -1 ? '' : sliceBlock(source, braceAt)
  }
  let cursor = afterMatch
  while (cursor < source.length && /\s/.test(source[cursor])) cursor++
  if (source[cursor] === '{') return sliceBlock(source, cursor)
  return sliceExpressionBody(source, cursor)
}

export function collectSourceFiles(dir = SCAN_ROOT, out = []) {
  for (const name of readdirSync(dir)) {
    const entry = join(dir, name)
    if (statSync(entry).isDirectory()) {
      if (!SKIP_DIRS.has(name)) collectSourceFiles(entry, out)
    } else if (isCandidateFile(name)) {
      out.push(entry)
    }
  }
  return out
}

function isCandidateFile(name) {
  if (/\.(test|spec)\.tsx?$/.test(name)) return false
  return SCAN_SUFFIXES.some((suffix) => name.endsWith(suffix))
}

function stripNoise(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function collectDefinitions(files) {
  const byName = new Map()
  for (const file of files) {
    const source = readFileSync(file, 'utf-8')
    const relPath = relative(PROJECT_ROOT, file).replace(/\\/g, '/')
    for (const [pattern, isDeclaration] of [[DECLARATION, true], [ARROW_FUNCTION, false]]) {
      pattern.lastIndex = 0
      let match
      while ((match = pattern.exec(source)) !== null) {
        const name = match[1]
        const body = stripNoise(readFunctionBody(source, match, isDeclaration))
        if (body.length < 8) continue
        const line = source.slice(0, match.index).split('\n').length
        if (!byName.has(name)) byName.set(name, [])
        byName.get(name).push({ relPath, line, body })
      }
    }
  }
  return byName
}

/**
 * 逐组归类。
 *
 * 注意：**同一个函数名可以同时落在 A/B 与 C**。前例 `formatTime` 在全仓有
 * 22 处定义、14 种写法：其中 9 处逐字相同（应收口），另有 13 处各自不同
 * （属同名异体，必须保留差异）。若按"整个名字只能归一类"处理，后者会被
 * 前者的同体组掩盖而整体消失 —— 那正是本次要消除的台账盲区。
 *
 * 故：同体组按耦合与否进 A/B；**未进入任何跨文件同体组**的定义进 C。
 */
export function auditDuplicateFunctions() {
  const files = collectSourceFiles()
  const byName = collectDefinitions(files)
  const tiers = { A: [], B: [], C: [] }
  for (const [name, definitions] of byName) {
    if (new Set(definitions.map((d) => d.relPath)).size < 2) continue
    const byBody = new Map()
    for (const definition of definitions) {
      if (!byBody.has(definition.body)) byBody.set(definition.body, [])
      byBody.get(definition.body).push(definition)
    }

    const variantDefinitions = []
    for (const group of byBody.values()) {
      const isCrossFileIdentical = group.length > 1 && new Set(group.map((d) => d.relPath)).size > 1
      if (!isCrossFileIdentical) {
        variantDefinitions.push(...group)
        continue
      }
      const hits = LOCAL_COUPLING_PATTERNS.filter((p) => p.pattern.test(group[0].body)).map((p) => p.name)
      tiers[hits.length > 0 ? 'B' : 'A'].push({
        coupling: hits,
        name,
        sites: [...new Set(group.map((d) => `${d.relPath}:${d.line}`))],
        body: group[0].body,
      })
    }

    if (variantDefinitions.length === 0) continue
    const variantBodies = [...new Set(variantDefinitions.map((d) => d.body))]
    // 只有一种体且只有一处定义 → 不是同名组；但若同名组另有同体组，它仍是
    // 一份"与属主不同体的定义"，必须登记（否则收口时会被静默删掉）。
    tiers.C.push({
      name,
      sites: [...new Set(variantDefinitions.map((d) => `${d.relPath}:${d.line}`))],
      variants: variantBodies.length,
      coupled: variantDefinitions.some((d) => LOCAL_COUPLING_PATTERNS.some((p) => p.pattern.test(d.body))),
      calibers: variantCalibers(variantBodies),
    })
  }
  for (const tier of Object.values(tiers)) {
    tier.sort((a, b) => b.sites.length - a.sites.length || a.name.localeCompare(b.name))
  }
  return { scannedFiles: files.length, tiers }
}

export function caliberSummary() {
  return {
    root: SCAN_ROOT_LABEL,
    suffixes: SCAN_SUFFIXES,
    crossFileOnly: true,
    definitionForms: ['function name(...)', 'const name = (...) =>', 'const name = async (...) =>'],
    sameBodyRule: '去注释去空白后逐字相等',
    localCoupling: LOCAL_COUPLING_PATTERNS.map((p) => `${p.name} → ${p.pattern}`),
  }
}

/** 台账机器段的分隔标记（人类可读正文与机器段的边界）。 */
export const LEDGER_BEGIN = '<!-- duplicate-function-inventory:begin -->'
export const LEDGER_END = '<!-- duplicate-function-inventory:end -->'

/**
 * 逐组机械判据：从各变体体的文本里抽出**可核实的差异事实**，
 * 不做语义judgement（"该不该合并"由人按模块定，见台账正文处置原则）。
 * 抽不出差异标记时退化为「实现细节不同」，不臆造理由。
 */
export function variantCalibers(bodies) {
  const flags = []
  const all = bodies.join(' ')
  if (bodies.some((b) => b.includes('* 1000')) && bodies.some((b) => !b.includes('* 1000'))) {
    flags.push('入参量纲不同（epoch 秒 ×1000 vs 原始值）')
  }
  const placeholders = new Set()
  for (const body of bodies) {
    for (const match of body.matchAll(/(?:return|:)\s*'([^']*)'/g)) {
      const value = match[1]
      if (value === '' || /^(-|—|N\/A)$/.test(value)) placeholders.add(value === '' ? "(空串)" : value)
    }
  }
  if (placeholders.size > 1) flags.push(`空值占位不同（${[...placeholders].join(' / ')}）`)
  if (bodies.some((b) => /(?:^|[^\w$.])t\s*\(/.test(b)) && bodies.some((b) => !/(?:^|[^\w$.])t\s*\(/.test(b))) {
    flags.push('部分变体依赖 i18n 文案、部分不依赖')
  }
  if (bodies.some((b) => /API|api\.|\.then\(|await /.test(b)) && bodies.some((b) => !/API|api\.|\.then\(|await /.test(b))) {
    flags.push('部分变体走网络/异步、部分为纯计算')
  }
  return flags.length > 0 ? flags : ['实现细节不同']
}

/** 台账机器段负载：B/C 两组逐组登记（A 类收口后应为空，非空即红灯）。 */
export function inventoryPayload(report = auditDuplicateFunctions()) {
  const flatten = (tier) => ({
    name: tier.name,
    files: [...new Set(tier.sites.map((site) => site.split(':')[0]))].sort(),
  })
  return {
    caliber: caliberSummary(),
    scannedFiles: report.scannedFiles,
    tierA: report.tiers.A.map(flatten),
    tierB: report.tiers.B.map(flatten),
    tierC: report.tiers.C.map(flatten),
  }
}

/** 生成台账里的机器段（表格 + JSON），供 `--write-ledger` 写盘与守卫读回。 */
export function renderLedgerBlock(report = auditDuplicateFunctions()) {
  const lines = [LEDGER_BEGIN, '', '### 逐组登记（本段由脚本生成，勿手改）', '']
  lines.push('| 函数名 | 档 | 定义处数 | 机械判据 | 处置 |')
  lines.push('| --- | --- | --- | --- | --- |')
  for (const group of report.tiers.A) {
    lines.push(`| ${group.name} | A | ${group.sites.length} | 体逐字相同、无局部耦合 | **未收口（红灯）**：须指向单一属主 |`)
  }
  for (const group of report.tiers.B) {
    lines.push(`| ${group.name} | B | ${group.sites.length} | ${group.coupling.join('、')} | 登记不收口：页面编排胶水 |`)
  }
  for (const group of report.tiers.C) {
    lines.push(`| ${group.name} | C | ${group.sites.length} | ${(group.calibers ?? []).join('；') || '实现细节不同'} | 登记保留：同名异体 |`)
  }
  lines.push('', '```json', JSON.stringify(inventoryPayload(report), null, 2), '```', '', LEDGER_END)
  return lines.join('\n')
}

function main() {
  const args = process.argv.slice(2)
  if (args.includes('--help')) {
    console.log(JSON.stringify(caliberSummary(), null, 2))
    console.log('分档：A=同名同体无局部耦合（应收口） B=同名同体耦合局部状态（编排胶水） C=同名异体（契约不同）')
    console.log('--write-ledger <file>：把机器段替换进台账文件（标记之间），正文其余部分不动。')
    return
  }
  const report = auditDuplicateFunctions()
  const writeIndex = args.indexOf('--write-ledger')
  if (writeIndex !== -1) {
    const target = args[writeIndex + 1]
    if (!target) throw new Error('--write-ledger 需要台账文件路径')
    const current = readFileSync(target, 'utf-8')
    const begin = current.indexOf(LEDGER_BEGIN)
    const end = current.indexOf(LEDGER_END)
    if (begin === -1 || end === -1) throw new Error(`台账缺少机器段标记：${target}`)
    writeFileSync(target, current.slice(0, begin) + renderLedgerBlock(report) + current.slice(end + LEDGER_END.length), 'utf-8')
    console.log(`已写入台账机器段：${target}`)
    return
  }
  const total = report.tiers.A.length + report.tiers.B.length + report.tiers.C.length
  if (args.includes('--json')) {
    console.log(JSON.stringify({
      scannedFiles: report.scannedFiles,
      caliber: caliberSummary(),
      counts: { A: report.tiers.A.length, B: report.tiers.B.length, C: report.tiers.C.length, crossFileSameNameTotal: total },
      tierA: report.tiers.A.map((g) => ({ name: g.name, sites: g.sites })),
    }, null, 2))
    return
  }
  console.log(`扫描文件 ${report.scannedFiles} 个；跨文件同名组 ${total} 组`)
  const labels = {
    A: 'A 类 · 同名同体无局部耦合（应收口到单一属主）',
    B: 'B 类 · 同名同体耦合局部状态（编排胶水，登记不收口）',
    C: 'C 类 · 同名异体（契约不同，禁止按名强行合并）',
  }
  for (const tier of ['A', 'B', 'C']) {
    console.log(`\n=== ${labels[tier]}：${report.tiers[tier].length} 组 ===`)
    for (const group of report.tiers[tier]) {
      const variantNote = group.variants ? ` (${group.variants} 种体)` : ''
      console.log(`[${group.sites.length}] ${group.name}${variantNote}`)
      for (const site of group.sites) console.log(`    ${site}`)
    }
  }
}

if (process.argv[1] && process.argv[1].endsWith('duplicate-function-audit.mjs')) main()
