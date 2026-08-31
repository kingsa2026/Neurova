// 睡眠设置页 i18n 增键脚本（additions+merge 工作流）
// 在每个语言的 sleep 块 enableMemoryMerge 行后插入 4 个新键，
// 保留各文件原有换行风格（CRLF/LF 混合仓库，勿统一改写）。
// 幂等：已存在 enableConflictResolution 键的文件跳过。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCALES_DIR = path.resolve(__dirname, '../NeurUI/src/i18n/locales')

const KEYS = {
  'zh-CN': {
    enableConflictResolution: '启用冲突解决',
    sleepThresholdMinutes: '休眠触发阈值 (分钟)',
    sleepDurationMinutes: '休眠时长 (分钟)',
    minutes: '分钟',
  },
  'en-US': {
    enableConflictResolution: 'Enable Conflict Resolution',
    sleepThresholdMinutes: 'Sleep Trigger Threshold (minutes)',
    sleepDurationMinutes: 'Sleep Duration (minutes)',
    minutes: 'minutes',
  },
  'ja-JP': {
    enableConflictResolution: '衝突解決を有効にする',
    sleepThresholdMinutes: '睡眠トリガーしきい値 (分)',
    sleepDurationMinutes: '睡眠時間 (分)',
    minutes: '分',
  },
  'ko-KR': {
    enableConflictResolution: '충돌 해결 활성화',
    sleepThresholdMinutes: '수면 트리거 임계값 (분)',
    sleepDurationMinutes: '수면 시간 (분)',
    minutes: '분',
  },
  'fr-FR': {
    enableConflictResolution: "Activer la résolution de conflits",
    sleepThresholdMinutes: 'Seuil de déclenchement du sommeil (minutes)',
    sleepDurationMinutes: 'Durée de sommeil (minutes)',
    minutes: 'minutes',
  },
  'de-DE': {
    enableConflictResolution: 'Konfliktlösung aktivieren',
    sleepThresholdMinutes: 'Schlaf-Auslöseschwelle (Minuten)',
    sleepDurationMinutes: 'Schlafdauer (Minuten)',
    minutes: 'Minuten',
  },
  'es-ES': {
    enableConflictResolution: 'Activar resolución de conflictos',
    sleepThresholdMinutes: 'Umbral de activación del sueño (minutos)',
    sleepDurationMinutes: 'Duración del sueño (minutos)',
    minutes: 'minutos',
  },
  'it-IT': {
    enableConflictResolution: 'Attiva risoluzione dei conflitti',
    sleepThresholdMinutes: 'Soglia di attivazione del sonno (minuti)',
    sleepDurationMinutes: 'Durata del sonno (minuti)',
    minutes: 'minuti',
  },
  'ru-RU': {
    enableConflictResolution: 'Включить разрешение конфликтов',
    sleepThresholdMinutes: 'Порог перехода в сон (минуты)',
    sleepDurationMinutes: 'Длительность сна (минуты)',
    minutes: 'мин',
  },
  'ar-SA': {
    enableConflictResolution: 'تفعيل حل النزاعات',
    sleepThresholdMinutes: 'عتبة تفعيل السكون (دقائق)',
    sleepDurationMinutes: 'مدة السكون (دقائق)',
    minutes: 'دقيقة',
  },
  'hi-IN': {
    enableConflictResolution: 'संघर्ष समाधान सक्षम करें',
    sleepThresholdMinutes: 'नींद ट्रिगर सीमा (मिनट)',
    sleepDurationMinutes: 'नींद की अवधि (मिनट)',
    minutes: 'मिनट',
  },
}

const results = []
for (const [locale, keys] of Object.entries(KEYS)) {
  const file = path.join(LOCALES_DIR, `${locale}.ts`)
  let content = fs.readFileSync(file, 'utf8')

  if (content.includes('enableConflictResolution')) {
    results.push(`${locale}: SKIP (已存在)`)
    continue
  }

  // 定位 sleep 块内的 enableMemoryMerge 锚点行（含其换行符以保留原 EOL 风格）
  const anchorRe = /^([ \t]*enableMemoryMerge: '.*',)(\r?\n)/m
  const m = content.match(anchorRe)
  if (!m) {
    results.push(`${locale}: FAIL (未找到 enableMemoryMerge 锚点)`)
    continue
  }
  const eol = m[2]
  const indent = m[1].match(/^[ \t]*/)[0]
  const insertion = Object.entries(keys)
    .map(([k, v]) => `${indent}${k}: '${v}',`)
    .join(eol)
  content = content.replace(anchorRe, `$1${eol}${insertion}${eol}`)

  fs.writeFileSync(file, content, 'utf8')
  const eolTag = eol === '\r\n' ? 'CRLF' : 'LF'
  results.push(`${locale}: OK (+4 keys, ${eolTag})`)
}
console.log(results.join('\n'))
