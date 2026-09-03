/**
 * 会话自动标题 — 默认标题判定纯函数（2026-09-03）。
 *
 * 需求：不要默认对话名（新对话/新建对话/新会话），首轮完成后用语义
 * 概括自动填充。前端仅在标题命中默认清单时调用 auto-title 端点。
 */
import { describe, expect, it } from 'vitest'
import { isDefaultChatTitle } from '@/utils/sessionTitle'

describe('isDefaultChatTitle', () => {
  it('空/null 标题视为默认', () => {
    expect(isDefaultChatTitle('')).toBe(true)
    expect(isDefaultChatTitle(null)).toBe(true)
    expect(isDefaultChatTitle(undefined)).toBe(true)
    expect(isDefaultChatTitle('   ')).toBe(true)
  })

  it('命中内置默认名清单（后端/前端双重口径）', () => {
    expect(isDefaultChatTitle('新对话')).toBe(true)
    expect(isDefaultChatTitle('新建对话')).toBe(true)
    expect(isDefaultChatTitle('新会话')).toBe(true)
    expect(isDefaultChatTitle('New conversation')).toBe(true)
  })

  it('命中调用方传入的默认文案（i18n 当前语言值）', () => {
    expect(isDefaultChatTitle('Neue Unterhaltung', ['Neue Unterhaltung'])).toBe(true)
  })

  it('语义标题不误判', () => {
    expect(isDefaultChatTitle('汽车是什么')).toBe(false)
    expect(isDefaultChatTitle('关于火箭发射的讨论')).toBe(false)
  })
})
