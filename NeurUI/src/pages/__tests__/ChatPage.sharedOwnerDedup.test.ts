/**
 * 组件抽取后的单一事实源契约（2026-09-24）。
 *
 * 事故：4669df81「协作群聊房间页与消息渲染统一为共享组件」把 ChatPage 的
 * 模板段与逻辑整体搬进共享组件，但只清掉了重复的 CSS，`<script setup>` 里
 * 已被搬走的函数实现原样留了下来 —— 同一份逻辑出现两个定义：
 *   - formatJSON / stepDurationText / onReasoningScroll → MessageSteps.vue（共享渲染单元）
 *   - handleFileSelect / removePendingFile / handlePaste / addFiles → composables/usePendingFiles.ts
 *   - scrollToMessage → 被 jumpToMatch 取代后无人引用
 * 平行定义会各自漂移（实测 removePendingFile 已从 `pf?.preview` 漂成 `pf.preview`，
 * 少了可选链，无 preview 的附件会抛 TypeError）。故按 AGENTS.md 修复教义第 6 条
 * 收口到共享属主，用本守卫钉住。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')
const PAGE = readFileSync(resolve(SRC, 'pages/ChatPage.vue'), 'utf-8')

/** 已有共享属主的名字：不得在 ChatPage 里出现第二份定义。 */
const SHARED_OWNERS: Array<[string, string]> = [
  ['getFileCategory', 'utils/fileKind.ts'],
  ['getFileIcon', 'utils/fileKind.ts'],
  ['formatFileSize', 'utils/fileKind.ts'],
  ['formatJSON', 'components/chat/MessageSteps.vue'],
  ['stepDurationText', 'components/chat/MessageSteps.vue'],
  ['onReasoningScroll', 'components/chat/MessageSteps.vue'],
  ['handleFileSelect', 'composables/usePendingFiles.ts'],
  ['removePendingFile', 'composables/usePendingFiles.ts'],
  ['handlePaste', 'composables/usePendingFiles.ts'],
  ['addFiles', 'composables/usePendingFiles.ts'],
]

/** 抽取后已退役的旧实现名（被 jumpToMatch 取代）。 */
const RETIRED = ['scrollToMessage']

describe('ChatPage 抽取后不留平行定义', () => {
  it('已搬进共享模块的函数不得在页面里留第二份定义', () => {
    const duplicated = SHARED_OWNERS.filter(([name]) =>
      new RegExp(`^function ${name}\\s*\\(`, 'm').test(PAGE),
    ).map(([name, owner]) => `${name}（共享属主 ${owner}）`)
    expect(duplicated, `平行定义会各自漂移，须收口到共享属主:\n${duplicated.join('\n')}`).toEqual([])
  })

  it('退役的旧实现名不回流', () => {
    const back = RETIRED.filter((name) => new RegExp(`^function ${name}\\s*\\(`, 'm').test(PAGE))
    expect(back).toEqual([])
  })

  it('共享属主确实定义了这些函数（否则上一条断言会空转）', () => {
    const owners = new Map(SHARED_OWNERS)
    const missing = [...owners].filter(([name, owner]) => {
      const src = readFileSync(resolve(SRC, owner), 'utf-8')
      // 属主可能是 .vue（顶层 function）或共享模块（export function）
      return !(new RegExp(`^function ${name}\\s*\\(`, 'm').test(src) ||
        new RegExp(`^export function ${name}\\s*\\(`, 'm').test(src) ||
        new RegExp(`^\\s*${name},\\s*$`, 'm').test(src))
    }).map(([name, owner]) => `${name} @ ${owner}`)
    expect(missing, `共享属主未定义，守卫失去意义:\n${missing.join('\n')}`).toEqual([])
  })

  it('<script setup> 顶层不留无人引用的函数（死码）', () => {
    const script = PAGE.slice(PAGE.indexOf('<script setup'))
    const defined = [...script.matchAll(/^function (\w+)\s*\(/gm)].map((m) => m[1])
    const orphans = defined.filter(
      (name) => PAGE.match(new RegExp(`\\b${name}\\b`, 'g'))!.length <= 1,
    )
    expect(orphans, `以下函数在页面内无任何引用（模板/脚本均无消费者）:\n${orphans.join('\n')}`).toEqual([])
  })

  it('待发送附件的容量上限只有一处定义（usePendingFiles）', () => {
    const local = /^const MAX_FILE_SIZE\s*=/m.test(PAGE)
    expect(local).toBe(false)
    const owner = readFileSync(resolve(SRC, 'composables/usePendingFiles.ts'), 'utf-8')
    expect(/^const MAX_FILE_SIZE\s*=/m.test(owner)).toBe(true)
  })

  it('附件类型分类/图标/体积文案只有一份定义（ChatPage 与 composer 同源）', () => {
    // 同一个 xlsx/docx 在「待发送」与「已发送气泡」里必须显示同一图标。
    // 抽取提交只搬走子集，两份各自漂移：ChatPage 版认 spreadsheet/presentation/document，
    // composer 版不认 → 同一文件两处图标不一致。
    const composer = readFileSync(resolve(SRC, 'components/chat/ChatComposerArea.vue'), 'utf-8')
    for (const name of ['getFileCategory', 'getFileIcon', 'formatFileSize']) {
      const re = new RegExp(`^function ${name}\\s*\\(`, 'm')
      expect(re.test(PAGE), `${name} 在 ChatPage 仍有定义`).toBe(false)
      expect(re.test(composer), `${name} 在 ChatComposerArea 仍有定义`).toBe(false)
    }
    const owner = readFileSync(resolve(SRC, 'utils/fileKind.ts'), 'utf-8')
    for (const name of ['getFileCategory', 'getFileIcon', 'formatFileSize']) {
      expect(new RegExp(`^export function ${name}\\s*\\(`, 'm').test(owner), `${name} 未在共享属主导出`).toBe(true)
    }
  })
})
