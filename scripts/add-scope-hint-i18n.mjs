// 模型页个人配置范围提示 i18n 增键脚本(additions+merge 工作流)
// 在每个语言的 model 块 discover 行后插入 personalScopeHint,
// 保留各文件原有换行风格;幂等:已存在 personalScopeHint 则跳过。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCALES_DIR = path.resolve(__dirname, '../NeurUI/src/i18n/locales')

const VALUES = {
  'zh-CN': '这里是你的个人 LLM 配置,仅你可见、仅你可编辑。',
  'en-US': 'Your personal LLM configuration — visible and editable only by you.',
  'ja-JP': 'これは個人の LLM 設定です。あなただけが閲覧・編集できます。',
  'ko-KR': '여기는 개인 LLM 설정입니다. 본인만 보고 편집할 수 있습니다.',
  'fr-FR': 'Votre configuration LLM personnelle — visible et modifiable uniquement par vous.',
  'de-DE': 'Deine persönliche LLM-Konfiguration — nur für dich sichtbar und bearbeitbar.',
  'es-ES': 'Tu configuración LLM personal: solo tú puedes verla y editarla.',
  'it-IT': 'La tua configurazione LLM personale — visibile e modificabile solo da te.',
  'ru-RU': 'Ваша персональная конфигурация LLM — видно и изменяемо только вами.',
  'ar-SA': 'إعداداتك الشخصية لنماذج الذكاء الاصطناعي — مرئية وقابلة للتعديل لك وحدك.',
  'hi-IN': 'आपका निजी LLM कॉन्फ़िगरेशन — केवल आप देख और संपादित कर सकते हैं।',
}

const results = []
for (const [locale, value] of Object.entries(VALUES)) {
  const file = path.join(LOCALES_DIR, `${locale}.ts`)
  let content = fs.readFileSync(file, 'utf8')

  if (content.includes('personalScopeHint')) {
    results.push(`${locale}: SKIP (已存在)`)
    continue
  }

  const anchorRe = /^([ \t]*discover: '[^']*',)(\r?\n)/m
  const m = content.match(anchorRe)
  if (!m) {
    results.push(`${locale}: FAIL (未找到 discover 锚点)`)
    continue
  }
  const eol = m[2]
  const indent = m[1].match(/^[ \t]*/)[0]
  content = content.replace(anchorRe, `$1${eol}${indent}personalScopeHint: '${value}',${eol}`)

  fs.writeFileSync(file, content, 'utf8')
  const eolTag = eol === '\r\n' ? 'CRLF' : 'LF'
  results.push(`${locale}: OK (+1 key, ${eolTag})`)
}
console.log(results.join('\n'))
