/**
 * 死码退役守卫（审计 2026-11-04 P1-7/P1-8/P2-11）。
 *
 * 这三件在退役前都是「零引用但可被误接」的形态：
 * - `stores/chat.optimized.ts` / `stores/collaboration.optimized.ts` 与活实现
 *   同名导出、同 Pinia id，IDE 自动补全一建议就会接错；
 * - `stores/utils.ts` 唯一消费方就是上面两份死 store；
 * - `getConsoleChatSSEUrl` 拼的是后端并不存在的 `/console/chat/stream`
 *   （真实流式入口是 `POST /api/v1/chat/stream`），自身也零调用。
 *
 * 判据只钉「退役后的状态」，不钉词：文件不再存在、console 客户端不再声明
 * 该出口。将来有人把任何一件搬回来，这里当场红。
 */
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')

const RETIRED_STORES = [
  'stores/chat.optimized.ts',
  'stores/collaboration.optimized.ts',
]

describe('死码退役守卫', () => {
  it('optimized 双 store 已退役，不得以同名导出复活', () => {
    expect(RETIRED_STORES.filter((path) => existsSync(resolve(SRC, path)))).toEqual([])
  })

  it('stores/utils.ts 随唯二消费方一同退役', () => {
    expect(existsSync(resolve(SRC, 'stores/utils.ts'))).toBe(false)
  })

  it('console 客户端不得再声明后端不存在的 SSE 出口', () => {
    const consoleClient = readFileSync(resolve(SRC, 'api/modules/console.ts'), 'utf-8')
    // 只判代码形态：退役说明会写出旧名字，注释不该被自己的文档措辞撞红
    const code = consoleClient
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
    expect(code).not.toContain('getConsoleChatSSEUrl')
    expect(code).not.toContain('/chat/stream')
  })
})
