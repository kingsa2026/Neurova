/**
 * 画布全屏纯函数测试 — TDD 红灯先行。
 *
 * 范围（§6.4）：document 依赖注入，jsdom 无原生 Fullscreen API 亦可测：
 * 1. isFullscreen / canFullscreen；
 * 2. requestFullscreenCompat：标准 API + webkit 前缀回退；
 * 3. exitFullscreenCompat：标准 + 前缀。
 */
import { describe, expect, it } from 'vitest'
import {
  canFullscreen,
  exitFullscreenCompat,
  isFullscreen,
  requestFullscreenCompat,
  type FullscreenDoc,
  type FullscreenEl,
} from '../canvasFullscreen'

function makeDoc(overrides: Partial<FullscreenDoc> = {}): FullscreenDoc {
  return {
    fullscreenElement: null,
    exitFullscreen: () => Promise.resolve(),
    ...overrides,
  }
}

function makeEl(overrides: Partial<FullscreenEl> = {}): FullscreenEl {
  return { requestFullscreen: () => Promise.resolve(), ...overrides }
}

describe('isFullscreen', () => {
  it('fullscreenElement 非空即全屏', () => {
    expect(isFullscreen(makeDoc())).toBe(false)
    expect(isFullscreen(makeDoc({ fullscreenElement: {} as Element }))).toBe(true)
  })
})

describe('canFullscreen', () => {
  it('标准或 webkit 前缀任一存在即可', () => {
    expect(canFullscreen(makeDoc(), makeEl())).toBe(true)
    expect(canFullscreen(makeDoc(), makeEl({ requestFullscreen: undefined, webkitRequestFullscreen: () => {} }))).toBe(true)
    expect(canFullscreen(makeDoc(), makeEl({ requestFullscreen: undefined }))).toBe(false)
  })
})

describe('requestFullscreenCompat', () => {
  it('优先使用标准 requestFullscreen', () => {
    let called = false
    const doc = makeDoc()
    const el = makeEl({
      requestFullscreen: async () => {
        called = true
        doc.fullscreenElement = el as Element
      },
    })
    requestFullscreenCompat(el, doc)
    expect(called).toBe(true)
  })

  it('标准不可用时使用 webkit 前缀', () => {
    let called = false
    const el = makeEl({
      requestFullscreen: undefined,
      webkitRequestFullscreen: () => {
        called = true
      },
    })
    requestFullscreenCompat(el, makeDoc())
    expect(called).toBe(true)
  })
})

describe('exitFullscreenCompat', () => {
  it('标准退出', () => {
    let called = false
    const doc = makeDoc({ exitFullscreen: () => { called = true; return Promise.resolve() } })
    exitFullscreenCompat(doc)
    expect(called).toBe(true)
  })
})
