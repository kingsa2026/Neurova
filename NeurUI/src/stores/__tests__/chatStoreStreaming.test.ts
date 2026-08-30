/**
 * chat store — 流式消息响应式契约测试
 *
 * 背景根因（R-1）: ChatPage 创建 assistantMsg 普通对象 → store.addMessage(msg)
 * 后，模板从 storeToRefs(chatStore).messages 遍历读取 proxy 版本；但
 * processSSEEvent 仍持有 push 前的原始对象引用直接写属性，绕过 Vue proxy
 * setter → SSE 事件全部到达后仅在下次组件重渲染时一次性渲染全量，
 * 思考过程不逐字显示。
 *
 * 修复契约：
 *   addMessage 返回 store 中持有的 proxy 引用，调用方（ChatPage）必须用
 *   返回值继续更新消息，保证流式写入命中响应式代理。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effect, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'

describe('useChatStore 流式消息响应式契约', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('addMessage 返回的元素是 store 中可写且响应式的 proxy 引用', async () => {
    const store = useChatStore()
    const msg = { role: 'assistant', content: '', reasoning: '', streaming: true } as any
    const proxyMsg = store.addMessage(msg)

    // 必须返回 proxy（与 store 内存的同一引用）
    expect(proxyMsg).not.toBe(msg)
    expect(proxyMsg).toBe(store.messages[store.messages.length - 1])

    // 通过返回的 proxy 写属性：effect 必须触发（逐字渲染的响应性基础）
    let renders = 0
    effect(() => {
      void proxyMsg.reasoning
      renders++
    })
    expect(renders).toBe(1)

    proxyMsg.reasoning = 'chunk-1'
    await nextTick()
    expect(renders, 'proxy 写入必须触发依赖（逐字更新前提）').toBe(2)

    proxyMsg.reasoning = 'chunk-1chunk-2'
    await nextTick()
    expect(renders).toBe(3)
    expect(store.messages[0].reasoning).toBe('chunk-1chunk-2')
  })

  it('setMessages 后通过返回引用继续更新不影响后续消息', () => {
    const store = useChatStore()
    const a = store.addMessage({ role: 'user', content: 'hello', timestamp: 't1' } as any)
    const b = store.addMessage({ role: 'assistant', content: '', reasoning: '', streaming: true } as any)

    a.content = 'edited-user' // 用户消息不可变契约不强制，仅验证引用独立
    b.reasoning = 'think1'
    b.reasoning = 'think1think2'

    expect(store.messages[0].content).toBe('edited-user')
    expect(store.messages[1].reasoning).toBe('think1think2')
    expect(a).toBe(store.messages[0])
    expect(b).toBe(store.messages[1])
  })
})
