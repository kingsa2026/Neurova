/**
 * P1 硬编码 UI 文案防回归守卫（2026-09-16 全局扫描定级后的修复锁定）。
 *
 * 根因：MemoryPage / AgentFormPage / ModelPage / StudioProjectPage 存在语言包
 * 缺 key 的硬编码文案（Tags/Add tags/Expires/Metadata/Header name/Agent ID/
 * 新镜头占位描述）→ 无法绑定，被迫字面量。本轮统一补 key（11 语言包）+ 改绑。
 *
 * 锁定行为：
 * 1. 这些位置不得再出现硬编码字面量
 * 2. 必须绑定本轮新增 key
 * 3. 新 key 必须在全部 11 个语言包中存在（防语言包漂移——过去曾出现过
 *    仅补 zh/en 双语、其余 9 语言静默回退英文的事故）
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

// vitest root = NeurUI/，测试内相对路径从 src/ 起算
const file = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf-8')

import zhCN from '@/i18n/locales/zh-CN'
import enUS from '@/i18n/locales/en-US'
import jaJP from '@/i18n/locales/ja-JP'
import koKR from '@/i18n/locales/ko-KR'
import frFR from '@/i18n/locales/fr-FR'
import deDE from '@/i18n/locales/de-DE'
import esES from '@/i18n/locales/es-ES'
import ruRU from '@/i18n/locales/ru-RU'
import itIT from '@/i18n/locales/it-IT'
import arSA from '@/i18n/locales/ar-SA'
import hiIN from '@/i18n/locales/hi-IN'

const PACKS = { zhCN, enUS, jaJP, koKR, frFR, deDE, esES, ruRU, itIT, arSA, hiIN } as const

const ns = (pack: unknown, name: string) =>
  (pack as Record<string, Record<string, string>>)[name] ?? {}

describe('P1 硬编码文案守卫 — 页面绑定', () => {
  it('MemoryPage 新建/详情弹窗字段走 i18n', () => {
    const src = file('pages/MemoryPage.vue')
    expect(src).not.toContain('label="Tags"')
    expect(src).not.toContain("placeholder=\"'Add tags'\"")
    expect(src).not.toContain('label="Metadata"')
    expect(src).not.toContain('label="Expires"')
    expect(src).toContain(`:label="t('memory.tags')"`)
    expect(src).toContain(`:placeholder="t('memory.addTags')"`)
    expect(src).toContain(`:label="t('memory.metadata')"`)
    expect(src).toContain(`:label="t('memory.expires')"`)
  })

  it('AgentFormPage Agent ID 标签走 i18n', () => {
    const src = file('pages/AgentFormPage.vue')
    expect(src).not.toContain('label="Agent ID"')
    expect(src).toContain(`:label="t('agent.agentId')"`)
  })

  it('ModelPage 自定义请求头 placeholder 走 i18n', () => {
    const src = file('pages/ModelPage.vue')
    expect(src).not.toContain('placeholder="Header name"')
    expect(src).toContain(`:placeholder="t('model.headerName')"`)
  })

  it('StudioProjectPage 手动分镜默认描述走 i18n', () => {
    const src = file('pages/aigc/StudioProjectPage.vue')
    expect(src).not.toContain('（新镜头，填写画面提示词）')
    expect(src).toContain(`t('aigc.newShotPlaceholder')`)
  })
})

describe('P1 新增 key — 11 语言包完整性', () => {
  const CASES: Array<[string, string, string]> = [
    ['memory', 'tags', 'memory.tags'],
    ['memory', 'addTags', 'memory.addTags'],
    ['memory', 'expires', 'memory.expires'],
    ['memory', 'metadata', 'memory.metadata'],
    ['model', 'headerName', 'model.headerName'],
    ['agent', 'agentId', 'agent.agentId'],
    ['aigc', 'newShotPlaceholder', 'aigc.newShotPlaceholder'],
  ]

  for (const [name, pack] of Object.entries(PACKS)) {
    it(`${name} 齐备 7 个新 key`, () => {
      for (const [namespace, key, path] of CASES) {
        expect(ns(pack, namespace)[key], `${name}.${path}`).toBeTruthy()
      }
    })
  }
})
