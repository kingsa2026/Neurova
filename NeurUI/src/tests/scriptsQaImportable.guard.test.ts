/**
 * 被判据 import 的本地脚本必须能被 vitest 载入（台账 §6-112 形态一的防再生网）。
 *
 * 事故形态不是"测试失败"，而是**测试从未执行**：
 * `src/tests/duplicate-function-inventory.guard.test.ts` import
 * `scripts-qa/duplicate-function-audit.mjs`，而那文件首行是 `#!/usr/bin/env node`。
 * Vite 的转换管线把 shebang 留在包装后模块的中间，运行时即
 * `SyntaxError: Invalid or unexpected token` ⇒ 整档 **0 条用例**失败，在汇总里以
 * `Test Files 1 failed / Tests no tests` 的形态混进通过数。实测（2026-10-10 复现）：
 * 同一文件把首行 shebang 去掉后 import 成功，20 个导出全可见；`node --check` 与
 * `node --input-type=module` 直接 import 也都正常 ⇒ 坏的是"shebang × 打包器"这一组合，
 * 不是脚本代码。结果就是「同名函数 A 类清零」这道门从登记那天起一次都没咬过。
 *
 * 为什么这里守的是**行首 shebang** 而不是"别 import .mjs"：
 *  1. 这些脚本的唯一调用形态是 `node <文件>`（见脚本自身「用法」段与台账），
 *     shebang 没有任何消费者 ⇒ 它是一个从未被兑现的"我可直接执行"的宣称；
 *  2. 改走子进程调用会把判据从"读同一份口径实现"降级成"解析 stdout"，
 *     口径就有了第二份解释（教义第 6 条）；把口径函数搬进 `.ts` 则多一份平行实现。
 *     摘掉那行 22 字节的东西，是把非法状态在它产生的地方消掉（教义第 1 条）。
 *
 * 一条如实边界：本文件只能保证 **shebang** 这一类不再复现。"0 用例的套件级失败"
 * 本身还有别的成因（模块不存在、顶层抛错、转换链上任何其他形态），vitest 会把它们
 * 一律报成 0 test 混进通过数——那需要在跑测器层面比对"声明的用例数 vs 实际执行数"，
 * 本层做不到，已登记台账（§6-112）不当作已解决。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

const PROJECT_ROOT = resolve(process.cwd())
const SCRIPTS_QA_DIR = join(PROJECT_ROOT, 'scripts-qa')

/** 行首 shebang：只有第 1 个字符起的 `#!` 才是 shebang。 */
function hasLeadingShebang(text: string): boolean {
  return text.startsWith('#!')
}

/** 从测试文件里收集"被 import 的本地脚本"说明符（相对路径 + .mjs/.js 后缀）。 */
function locallyImportedScripts(testFile: string, text: string): string[] {
  const found: string[] = []
  for (const match of text.matchAll(/from\s+['"](\.[^'"]+\.(?:mjs|js))['"]/g)) {
    found.push(resolve(dirname(testFile), match[1]))
  }
  return found
}

function testFilesUnder(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const entry = join(dir, name)
    if (name === 'node_modules' || name === 'dist' || name === '.git') continue
    if (statSync(entry).isDirectory()) out.push(...testFilesUnder(entry))
    else if (/\.test\.[cm]?[jt]sx?$/.test(name)) out.push(entry)
  }
  return out
}

describe('被判据 import 的本地脚本可被 vitest 载入', () => {
  it('scripts-qa 下没有脚本带行首 shebang', () => {
    const offenders = readdirSync(SCRIPTS_QA_DIR)
      .filter((name) => name.endsWith('.mjs') || name.endsWith('.js'))
      .map((name) => join(SCRIPTS_QA_DIR, name))
      .filter((path) => hasLeadingShebang(readFileSync(path, 'utf-8')))
    expect(
      offenders,
      `以下脚本带行首 shebang，被 vitest 守卫 import 时会整档 0 条用例失败`
      + `（Vite 转换后 shebang 落在模块中间 ⇒ SyntaxError）：\n${offenders.join('\n')}`,
    ).toEqual([])
  })

  it('测试文件 import 的每一个本地脚本都不带行首 shebang', () => {
    const checked: string[] = []
    const offenders: string[] = []
    for (const file of testFilesUnder(join(PROJECT_ROOT, 'src'))) {
      for (const target of locallyImportedScripts(file, readFileSync(file, 'utf-8'))) {
        checked.push(`${file} → ${target}`)
        if (!hasLeadingShebang(readFileSync(target, 'utf-8'))) continue
        offenders.push(`${file} import 了带 shebang 的 ${target}`)
      }
    }
    expect(
      checked.length,
      '一条本地脚本 import 都没扫到 ⇒ 本格空转：扫描面（src 下的 *.test.*、'
      + '相对路径 + .mjs/.js 后缀）与实际写法不符，须先修检出器再谈结论',
    ).toBeGreaterThan(0)
    expect(offenders, `以下 import 面会让守卫以 0 条用例的形态失效:\n${offenders.join('\n')}`)
      .toEqual([])
  })

  it('shebang 检出器只对行首生效，且真的抓得到（不空转）', () => {
    expect(hasLeadingShebang('#!/usr/bin/env node\nexport const a = 1\n')).toBe(true)
    expect(hasLeadingShebang('/** 用法见下 */\nexport const a = 1\n')).toBe(false)
    // 正文里出现 `#!` 不是 shebang（否则任何含注释图的脚本都会被打红）
    expect(hasLeadingShebang('const banner = "#!/usr/bin/env node"\n')).toBe(false)
  })
})
