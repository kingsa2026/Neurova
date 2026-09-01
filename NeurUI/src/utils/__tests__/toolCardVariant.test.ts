/**
 * toolCardVariant 纯函数单测（补课 3.1：工具卡按类型分化）。
 */
import { describe, it, expect } from 'vitest'
import { toolCardVariant, variantIcon, variantColor } from '@/utils/toolCardVariant'

describe('toolCardVariant', () => {
  it('maps tool names to expected variants', () => {
    expect(toolCardVariant('computer_screenshot')).toBe('computer')
    expect(toolCardVariant('browser_click')).toBe('computer')
    expect(toolCardVariant('read_file')).toBe('file')
    expect(toolCardVariant('write_file')).toBe('file')
    expect(toolCardVariant('grep_search')).toBe('search')
    expect(toolCardVariant('web_search')).toBe('search')
    expect(toolCardVariant('bash')).toBe('shell')
    expect(toolCardVariant('execute_command')).toBe('shell')
    expect(toolCardVariant('run_code')).toBe('code')
    expect(toolCardVariant('create_skill')).toBe('code')
  })

  it('falls back to general for unknown/empty names', () => {
    expect(toolCardVariant('unknown_tool')).toBe('general')
    expect(toolCardVariant('')).toBe('general')
    expect(toolCardVariant(undefined)).toBe('general')
  })

  it('is case-insensitive', () => {
    expect(toolCardVariant('READ_FILE')).toBe('file')
  })
})

describe('variantIcon / variantColor', () => {
  it('every variant has an icon and color', () => {
    for (const v of ['computer', 'file', 'search', 'shell', 'code', 'general'] as const) {
      expect(variantIcon(v)).toBeTruthy()
      expect(variantColor(v)).toBeTruthy()
    }
  })
})
