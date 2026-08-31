// 睡眠设置页 i18n 增键脚本（第三轮）：阶段推进参数（睡眠节奏卡）
// phaseParams/sleepMode/modeTemperature/modeTime/modeEither/threshold/
// monitorIntervalSeconds/seconds/hibernatePhase
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCALES_DIR = path.resolve(__dirname, '../NeurUI/src/i18n/locales')

const KEYS = {
  'zh-CN': {
    phaseParams: '睡眠节奏（阶段推进）',
    sleepMode: '判定模式',
    modeTemperature: '按记忆温度',
    modeTime: '按空闲时长',
    modeEither: '温度或空闲任一满足',
    threshold: '阈值',
    monitorIntervalSeconds: '阶段监控间隔',
    seconds: '秒',
    hibernatePhase: '休眠阶段',
  },
  'en-US': {
    phaseParams: 'Sleep Rhythm (Phase Progression)',
    sleepMode: 'Decision Mode',
    modeTemperature: 'By memory temperature',
    modeTime: 'By idle duration',
    modeEither: 'Temperature or idle, whichever first',
    threshold: 'Threshold',
    monitorIntervalSeconds: 'Phase Monitor Interval',
    seconds: 'sec',
    hibernatePhase: 'Hibernate Phase',
  },
  'ja-JP': {
    phaseParams: '睡眠リズム（フェーズ遷移）',
    sleepMode: '判定モード',
    modeTemperature: '記憶温度で判定',
    modeTime: 'アイドル時間で判定',
    modeEither: '温度またはアイドルのいずれか',
    threshold: 'しきい値',
    monitorIntervalSeconds: 'フェーズ監視間隔',
    seconds: '秒',
    hibernatePhase: '休眠フェーズ',
  },
  'ko-KR': {
    phaseParams: '수면 리듬(단계 진행)',
    sleepMode: '판정 모드',
    modeTemperature: '기억 온도 기준',
    modeTime: '유휴 시간 기준',
    modeEither: '온도 또는 유휴 충족 시',
    threshold: '임계값',
    monitorIntervalSeconds: '단계 모니터 간격',
    seconds: '초',
    hibernatePhase: '최면 단계',
  },
  'fr-FR': {
    phaseParams: 'Rythme de sommeil (progression des phases)',
    sleepMode: 'Mode de décision',
    modeTemperature: "Selon la température mémoire",
    modeTime: "Selon la durée d'inactivité",
    modeEither: 'Température ou inactivité, la première',
    threshold: 'Seuil',
    monitorIntervalSeconds: 'Intervalle de surveillance',
    seconds: 's',
    hibernatePhase: 'Phase hibernation',
  },
  'de-DE': {
    phaseParams: 'Schlaf-Rhythmus (Phasenübergang)',
    sleepMode: 'Entscheidungsmodus',
    modeTemperature: 'Nach Speichertemperatur',
    modeTime: 'Nach Leerlaufdauer',
    modeEither: 'Temperatur oder Leerlauf, was zuerst',
    threshold: 'Schwelle',
    monitorIntervalSeconds: 'Überwachungsintervall',
    seconds: 'Sek.',
    hibernatePhase: 'Ruhephase',
  },
  'es-ES': {
    phaseParams: 'Ritmo de sueño (progresión de fases)',
    sleepMode: 'Modo de decisión',
    modeTemperature: 'Por temperatura de memoria',
    modeTime: 'Por tiempo de inactividad',
    modeEither: 'Temperatura o inactividad, lo primero',
    threshold: 'Umbral',
    monitorIntervalSeconds: 'Intervalo de monitoreo',
    seconds: 's',
    hibernatePhase: 'Fase de hibernación',
  },
  'it-IT': {
    phaseParams: 'Ritmo del sonno (progressione fasi)',
    sleepMode: 'Modalità di decisione',
    modeTemperature: 'In base alla temperatura memoria',
    modeTime: "In base al tempo di inattività",
    modeEither: 'Temperatura o inattività, la prima',
    threshold: 'Soglia',
    monitorIntervalSeconds: 'Intervallo di monitoraggio',
    seconds: 's',
    hibernatePhase: 'Fase di ibernazione',
  },
  'ru-RU': {
    phaseParams: 'Ритм сна (переход фаз)',
    sleepMode: 'Режим решения',
    modeTemperature: 'По температуре памяти',
    modeTime: 'По времени простоя',
    modeEither: 'Температура или простой, что раньше',
    threshold: 'Порог',
    monitorIntervalSeconds: 'Интервал мониторинга',
    seconds: 'с',
    hibernatePhase: 'Фаза гибернации',
  },
  'ar-SA': {
    phaseParams: 'إيقاع النوم (تقدم المراحل)',
    sleepMode: 'وضع القرار',
    modeTemperature: 'حسب حرارة الذاكرة',
    modeTime: 'حسب مدة الخمول',
    modeEither: 'الحرارة أو الخمول، أيهما أولاً',
    threshold: 'العتبة',
    monitorIntervalSeconds: 'فاصل مراقبة المراحل',
    seconds: 'ث',
    hibernatePhase: 'مرحلة السبات',
  },
  'hi-IN': {
    phaseParams: 'नींद की लय (चरण प्रगति)',
    sleepMode: 'निर्णय मोड',
    modeTemperature: 'स्मृति तापमान से',
    modeTime: 'निष्क्रिय अवधि से',
    modeEither: 'तापमान या निष्क्रियता, जो पहले',
    threshold: 'सीमा',
    monitorIntervalSeconds: 'चरण मॉनिटर अंतराल',
    seconds: 'सेकंड',
    hibernatePhase: 'हाइबरनेट चरण',
  },
}

const results = []
for (const [locale, keys] of Object.entries(KEYS)) {
  const file = path.join(LOCALES_DIR, `${locale}.ts`)
  let content = fs.readFileSync(file, 'utf8')

  if (content.includes('phaseParams')) {
    results.push(`${locale}: SKIP (已存在)`)
    continue
  }

  const anchorRe = /^([ \t]*manualOnlyHint: '.*',)(\r?\n)/m
  const m = content.match(anchorRe)
  if (!m) {
    results.push(`${locale}: FAIL (未找到 manualOnlyHint 锚点)`)
    continue
  }
  const eol = m[2]
  const indent = m[1].match(/^[ \t]*/)[0]
  const insertion = Object.entries(keys)
    .map(([k, v]) => `${indent}${k}: '${v.replace(/'/g, "\\'")}',`)
    .join(eol)
  content = content.replace(anchorRe, `$1${eol}${insertion}${eol}`)
  fs.writeFileSync(file, content, 'utf8')
  results.push(`${locale}: OK (+9 keys, ${eol === '\r\n' ? 'CRLF' : 'LF'})`)
}
console.log(results.join('\n'))
