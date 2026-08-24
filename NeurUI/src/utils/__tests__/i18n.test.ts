/**
 * resolveI18nMessage — i18n fallback resolver 单元测试
 *
 * 根因 (chat.loadHistoryFailed toast 异常显示 bug):
 *   旧契约 `t(key) || fallback` 在 vue-i18n 缺失 key 时不工作:
 *   vue-i18n Composition API 模式下 t(missingKey) 返回 key 字符串本身
 *   (truthy), `|| fallback` 短路求值不触发, 导致 toast 显示 raw key
 *   (例如 "chat.loadHistoryFailed" 而非 "加载历史对话失败").
 *
 * 修复契约:
 *   resolveI18nMessage(t, key, fallback) 检测 t(key) === key (缺失翻译信号),
 *   缺失时返回 fallback; 否则返回 t(key). 同时防御空字符串/undefined/null.
 *
 * 详见 docs/bugfix-delete-session-userid-mismatch.md
 *   "前端错误反馈策略深化" → "i18n fallback resolver" 小节.
 */
import { describe, it, expect, vi } from 'vitest'
import { resolveI18nMessage } from '../i18n'

describe('resolveI18nMessage', () => {
  // ── Slice 1: 命中翻译时返回翻译字符串 ──────────────────────────────
  it('returns translated string when t(key) returns a different string', () => {
    const t = vi.fn((key: string) => (key === 'chat.loadHistoryFailed' ? '加载历史对话失败' : key))
    const result = resolveI18nMessage(t, 'chat.loadHistoryFailed', 'Fallback')
    expect(result).toBe('加载历史对话失败')
    expect(t).toHaveBeenCalledWith('chat.loadHistoryFailed')
  })

  // ── Slice 2: 缺失翻译时 (t(key) === key) 返回 fallback ──────────────
  it('returns fallback when t(key) returns the key itself (missing translation)', () => {
    // vue-i18n Composition API 在缺失 key 时返回 key 字符串本身
    const t = vi.fn((key: string) => key)
    const result = resolveI18nMessage(t, 'chat.loadHistoryFailed', '加载历史对话失败')
    expect(result).toBe('加载历史对话失败')
    expect(t).toHaveBeenCalledWith('chat.loadHistoryFailed')
  })

  // ── Slice 3: t(key) 返回空字符串时返回 fallback ───────────────────
  it('returns fallback when t(key) returns empty string', () => {
    const t = vi.fn(() => '')
    const result = resolveI18nMessage(t, 'chat.loadHistoryFailed', '加载历史对话失败')
    expect(result).toBe('加载历史对话失败')
  })

  // ── Slice 4: t(key) 返回 undefined/null 时返回 fallback (防御) ────
  it('returns fallback when t(key) returns undefined (defensive)', () => {
    const t = vi.fn(() => undefined as unknown as string)
    const result = resolveI18nMessage(t, 'chat.loadHistoryFailed', '加载历史对话失败')
    expect(result).toBe('加载历史对话失败')
  })

  it('returns fallback when t(key) returns null (defensive)', () => {
    const t = vi.fn(() => null as unknown as string)
    const result = resolveI18nMessage(t, 'chat.loadHistoryFailed', '加载历史对话失败')
    expect(result).toBe('加载历史对话失败')
  })

  // ── Slice 5: fallback 本身可能为空, 不应崩溃 ─────────────────────
  it('returns empty string when both translation and fallback are missing', () => {
    const t = vi.fn((key: string) => key)
    const result = resolveI18nMessage(t, 'some.missing.key', '')
    expect(result).toBe('')
  })

  // ── Slice 6: 命中翻译且包含参数时不破坏参数 ───────────────────────
  it('preserves parameter substitution in translated string', () => {
    const t = vi.fn((key: string) =>
      key === 'chat.welcome' ? '欢迎, {name}' : key,
    )
    const result = resolveI18nMessage(t, 'chat.welcome', 'Welcome')
    expect(result).toBe('欢迎, {name}')
  })

  // ── Slice 7: 同一 key 多次调用保持稳定 (无副作用) ─────────────────
  it('returns consistent result across multiple calls with same inputs', () => {
    const t = vi.fn((key: string) => key)
    const r1 = resolveI18nMessage(t, 'missing.key', 'Fallback')
    const r2 = resolveI18nMessage(t, 'missing.key', 'Fallback')
    expect(r1).toBe('Fallback')
    expect(r2).toBe('Fallback')
    expect(t).toHaveBeenCalledTimes(2)
  })
})
