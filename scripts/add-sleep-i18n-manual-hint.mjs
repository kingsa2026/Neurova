// 睡眠设置页 i18n 增键脚本（第二轮）：manualOnlyHint
// 手动参数（休眠时长/启用梦境）在开启自动休眠时隐藏，显示时附生效范围提示。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCALES_DIR = path.resolve(__dirname, '../NeurUI/src/i18n/locales')

const HINTS = {
  'zh-CN': '仅手动"进入睡眠"时生效，自动休眠不使用',
  'en-US': 'Only applies to manual "Sleep now"; auto sleep does not use this',
  'ja-JP': '手動の「睡眠開始」時にのみ有効。自動睡眠では使用しません',
  'ko-KR': '수동 "수면 시작" 시에만 적용되며 자동 수면에는 사용되지 않습니다',
  'fr-FR': "S'applique uniquement au sommeil manuel ; le sommeil automatique ne l'utilise pas",
  'de-DE': 'Gilt nur für manuelles "Einschlafen"; der automatische Schlaf verwendet dies nicht',
  'es-ES': 'Solo se aplica al sueño manual; el sueño automático no lo utiliza',
  'it-IT': "Si applica solo al sonno manuale; il sonno automatico non lo utilizza",
  'ru-RU': 'Действует только при ручном переходе в сон; автоматический сон это не использует',
  'ar-SA': 'ينطبق فقط على النوم اليدوي؛ النوم التلقائي لا يستخدمه',
  'hi-IN': 'केवल मैन्युअल "नींद शुरू करें" पर लागू; स्वचालित नींद इसका उपयोग नहीं करती',
}

const results = []
for (const [locale, hint] of Object.entries(HINTS)) {
  const file = path.join(LOCALES_DIR, `${locale}.ts`)
  let content = fs.readFileSync(file, 'utf8')

  if (content.includes('manualOnlyHint')) {
    results.push(`${locale}: SKIP (已存在)`)
    continue
  }

  // 锚点: sleep 块内的 minutes 键（第一轮新增，顺序稳定）
  const anchorRe = /^([ \t]*minutes: '.*',)(\r?\n)/m
  const m = content.match(anchorRe)
  if (!m) {
    results.push(`${locale}: FAIL (未找到 minutes 锚点)`)
    continue
  }
  const eol = m[2]
  const indent = m[1].match(/^[ \t]*/)[0]
  const line = `${indent}manualOnlyHint: '${hint.replace(/'/g, "\\'")}',`
  content = content.replace(anchorRe, `$1${eol}${line}${eol}`)
  fs.writeFileSync(file, content, 'utf8')
  results.push(`${locale}: OK (${eol === '\r\n' ? 'CRLF' : 'LF'})`)
}
console.log(results.join('\n'))
