/**
 * ChatPage 流生命周期契约测试（F-07 / F-08 / F-10 回归）。
 *
 * ChatPage 体量太大不便整体挂载（同 ChatPage.planCommand.test.ts 的取舍），
 * 这里以源码契约锁定三处缺陷的修复形态：
 * - F-07：renderedMessages computed getter 内不得写 renderStart（写后又读
 *   同一 ref → computed 自依赖，可能递归更新）；短列表归零由
 *   messages.length watch 负责。
 * - F-08：重连重试被中止（AbortError）同样置 _sendOk = false——否则
 *   utils/queueDrain 会把只播一半内容的排队项 markSent 出队。
 * - F-10：sendMessage 不得在 readStream 之外预建 AbortController
 *   （预建控制器会被 readStream 内的创建覆盖成孤儿，外层 signal 语义丢失）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// vitest 固定从 NeurUI 根目录启动（package.json "test": "vitest"）
const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')

/** 抽取 anchor 之后第一个平衡大括号块的内容。 */
function blockAfter(anchor: string): string {
  const idx = source.indexOf(anchor)
  if (idx === -1) return ''
  const braceStart = source.indexOf('{', idx)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(braceStart + 1, i)
    }
  }
  return ''
}

describe('F-07 renderedMessages getter 纯函数化', () => {
  const getter = blockAfter('const renderedMessages = computed(')

  it('getter 内不再写 renderStart（自依赖根因移除）', () => {
    expect(getter).not.toBe('')
    expect(getter).not.toContain('renderStart.value =')
  })

  it('短列表归零由 messages.length watch 负责（reset 路径仍在）', () => {
    const watch = blockAfter('() => messages.value.length,')
    expect(watch).toContain('renderStart.value = 0')
  })
})

describe('F-08 重试中止同样视为发送失败', () => {
  it('重试 catch 块：守卫块闭合后无条件置 _sendOk = false', () => {
    const retryCatch = blockAfter('catch (retryErr: any)')
    expect(retryCatch).not.toBe('')
    // 摘除模板字面量插值（${...} 内含花括号会干扰括号匹配），再压缩空白
    const clean = retryCatch.replace(/\$\{[^}]*\}/g, 'X').replace(/\s+/g, ' ')
    // 修复形态：if 守卫块闭合后紧跟 _sendOk = false（中止也置失败）
    expect(clean).toMatch(/if \(retryErr\.name !== 'AbortError'\) \{[^}]*\} _sendOk = false/)
    // 旧缺陷形态：_sendOk = false 位于守卫块内部（中止时不置失败）
    expect(clean).not.toMatch(/if \(retryErr\.name !== 'AbortError'\) \{[^}_]*_sendOk = false/)
  })
})

describe('F-10 AbortController 唯一归属 readStream', () => {
  it('sendMessage 不再预建 AbortController（防孤儿控制器）', () => {
    const occurrences = source.match(/new AbortController\(\)/g) ?? []
    expect(occurrences).toHaveLength(1)
  })

  it('fetch 仍消费 abortController.signal（stop/切会话 abort 语义保留）', () => {
    expect(source).toContain('signal: abortController.signal')
  })
})
