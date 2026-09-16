/**
 * P0 硬编码 UI 文案防回归守卫（2026-09-16 全局扫描定级后的修复锁定）。
 *
 * 根因：ModelPage / VoiceTranscriptionSettingsPage 部分标签硬编码英文字面量
 * （Base URL / API Key / Model ID / Clear），语言包 model.baseUrl / model.apiKey /
 * model.modelId / common.clear 11 语言全备，纯页面漏绑 → 中文界面露英文。
 * 与 ExperienceKnowledgePage tab 漏绑同类（P0 级：key 现成，一行改绑）。
 *
 * 锁定行为：
 * 1. 这些位置不得再出现硬编码字面量
 * 2. 必须绑定对应 i18n key
 * 3. 依赖的 key 在 zh-CN / en-US 语言包中存在（防 key 漂移）
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest root = NeurUI/，测试内相对路径从 src/ 起算
const file = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf-8')

import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'

describe('P0 硬编码文案守卫 — ModelPage', () => {
  it('预览卡/表单标签/清除按钮全部走 i18n', () => {
    const src = file('pages/ModelPage.vue')
    // 硬编码字面量不得回归
    expect(src).not.toContain('<span class="nr-pv-label">Base URL</span>')
    expect(src).not.toContain('<span class="nr-pv-label">API Key</span>')
    expect(src).not.toContain('<label>Base URL <span class="req">*</span></label>')
    expect(src).not.toContain('<label>Model ID <span class="req">*</span></label>')
    expect(src).not.toContain('title="Clear"')
    // 必须绑定对应 key
    expect(src).toContain(`{{ t('model.baseUrl') }}`)
    expect(src).toContain(`{{ t('model.apiKey') }}`)
    expect(src).toContain(`{{ t('model.modelId') }}`)
    expect(src).toContain(`:title="t('common.clear')"`)
  })
})

describe('P0 硬编码文案守卫 — VoiceTranscriptionSettingsPage', () => {
  it('远程 Whisper 表单字段标签走 i18n', () => {
    const src = file('pages/VoiceTranscriptionSettingsPage.vue')
    expect(src).not.toContain('<span class="field-label">Base URL</span>')
    expect(src).not.toContain('<span class="field-label">API Key</span>')
    expect(src).toContain(`{{ t('model.baseUrl') }}`)
    expect(src).toContain(`{{ t('model.apiKey') }}`)
  })
})

describe('P0 守卫依赖的 i18n key 存在性', () => {
  it('model.baseUrl/apiKey/modelId 与 common.clear 双语言包齐备', () => {
    for (const [name, pack] of [['zh-CN', zhCN], ['en-US', enUS]] as const) {
      expect((pack.model as Record<string, string>).baseUrl, `${name}.model.baseUrl`).toBeTruthy()
      expect((pack.model as Record<string, string>).apiKey, `${name}.model.apiKey`).toBeTruthy()
      expect((pack.model as Record<string, string>).modelId, `${name}.model.modelId`).toBeTruthy()
      expect((pack.common as Record<string, string>).clear, `${name}.common.clear`).toBeTruthy()
    }
  })
})
