#!/usr/bin/env node
/** 补 ctxPanelNoData 键 × 11 语言（锚点：ctxCacheHitRate 行后）。幂等。 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'NeurUI', 'src', 'i18n', 'locales')

const TEXT = {
  'zh-CN': '暂无数据，发送一条消息后生成',
  'en-US': 'No data yet — send a message to generate',
  'ja-JP': 'データなし — メッセージ送信後に生成されます',
  'ko-KR': '데이터 없음 — 메시지 전송 후 생성됩니다',
  'de-DE': 'Noch keine Daten — Nachricht senden',
  'fr-FR': 'Aucune donnée — envoyez un message',
  'it-IT': 'Nessun dato — invia un messaggio',
  'es-ES': 'Sin datos — envía un mensaje',
  'ru-RU': 'Нет данных — отправьте сообщение',
  'hi-IN': 'कोई डेटा नहीं — संदेश भेजें',
  'ar-SA': 'لا توجد بيانات — أرسل رسالة',
}

let touched = 0
for (const [locale, text] of Object.entries(TEXT)) {
  const file = join(root, `${locale}.ts`)
  let src = readFileSync(file, 'utf8')
  if (src.includes('ctxPanelNoData:')) {
    console.log(`skip ${locale}`)
    continue
  }
  const lines = src.split('\n')
  const idx = lines.findIndex((l) => /^\s*ctxCacheHitRate:/.test(l))
  if (idx < 0) {
    console.error(`FAIL ${locale}: anchor missing`)
    process.exitCode = 1
    continue
  }
  const indent = (lines[idx].match(/^(\s*)/) || [])[1] || '    '
  lines.splice(idx + 1, 0, `${indent}ctxPanelNoData: '${text}',`)
  writeFileSync(file, lines.join('\n'), 'utf8')
  touched += 1
}
console.log(`done: ${touched} locales`)
