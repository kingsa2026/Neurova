#!/usr/bin/env node
/**
 * 2026-09-07 聊天页三需求 i18n 补键（16 键 × 11 语言）。
 * 锚点：每个 locale 的 chat 段 toolBackgroundHint 行后插入。
 * 幂等：已存在 phaseUnderstanding 键则跳过该文件。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'NeurUI', 'src', 'i18n', 'locales')

const KEYS = {
  phaseUnderstanding: {
    'zh-CN': '收到信息，正在理解', 'en-US': 'Message received — understanding',
    'ja-JP': 'メッセージを受信、解析中', 'ko-KR': '메시지 수신, 이해하는 중',
    'de-DE': 'Nachricht erhalten – wird verstanden', 'fr-FR': 'Message reçu — compréhension',
    'it-IT': 'Messaggio ricevuto — comprensione', 'es-ES': 'Mensaje recibido — entendiendo',
    'ru-RU': 'Сообщение получено, анализирую', 'hi-IN': 'संदेश मिला — समझ रहे हैं',
    'ar-SA': 'تم استلام الرسالة — جارٍ الفهم',
  },
  phaseThinking: {
    'zh-CN': '正在思考', 'en-US': 'Thinking', 'ja-JP': '思考中', 'ko-KR': '생각 중',
    'de-DE': 'Denkt nach', 'fr-FR': 'Réflexion en cours', 'it-IT': 'Sto ragionando',
    'es-ES': 'Pensando', 'ru-RU': 'Размышляю', 'hi-IN': 'सोच रहे हैं', 'ar-SA': 'جارٍ التفكير',
  },
  phaseTool: {
    'zh-CN': '工具调用中', 'en-US': 'Running tool', 'ja-JP': 'ツール実行中', 'ko-KR': '도구 실행 중',
    'de-DE': 'Tool läuft', 'fr-FR': 'Outil en cours', 'it-IT': 'Strumento in uso',
    'es-ES': 'Ejecutando herramienta', 'ru-RU': 'Инструмент выполняется', 'hi-IN': 'टूल चल रहा है', 'ar-SA': 'جارٍ تنفيذ الأداة',
  },
  phaseOutput: {
    'zh-CN': '正在输出', 'en-US': 'Writing response', 'ja-JP': '出力中', 'ko-KR': '출력 중',
    'de-DE': 'Antwort wird erstellt', 'fr-FR': 'Génération de la réponse', 'it-IT': 'Risposta in scrittura',
    'es-ES': 'Escribiendo respuesta', 'ru-RU': 'Формирую ответ', 'hi-IN': 'उत्तर लिख रहे हैं', 'ar-SA': 'جارٍ كتابة الرد',
  },
  stepThinking: {
    'zh-CN': '思考', 'en-US': 'Thinking', 'ja-JP': '思考', 'ko-KR': '생각',
    'de-DE': 'Denken', 'fr-FR': 'Réflexion', 'it-IT': 'Ragionamento',
    'es-ES': 'Razonamiento', 'ru-RU': 'Размышление', 'hi-IN': 'विचार', 'ar-SA': 'تفكير',
  },
  stepRunning: {
    'zh-CN': '进行中', 'en-US': 'Running', 'ja-JP': '実行中', 'ko-KR': '실행 중',
    'de-DE': 'Läuft', 'fr-FR': 'En cours', 'it-IT': 'In corso',
    'es-ES': 'En curso', 'ru-RU': 'Выполняется', 'hi-IN': 'चल रहा है', 'ar-SA': 'قيد التنفيذ',
  },
  stepNoResult: {
    'zh-CN': '无结果', 'en-US': 'No result', 'ja-JP': '結果なし', 'ko-KR': '결과 없음',
    'de-DE': 'Kein Ergebnis', 'fr-FR': 'Aucun résultat', 'it-IT': 'Nessun risultato',
    'es-ES': 'Sin resultado', 'ru-RU': 'Нет результата', 'hi-IN': 'कोई परिणाम नहीं', 'ar-SA': 'لا توجد نتيجة',
  },
  stepDuration: {
    'zh-CN': '持续 {n} 秒', 'en-US': 'lasted {n}s', 'ja-JP': '{n}秒継続', 'ko-KR': '{n}초 지속',
    'de-DE': 'dauerte {n}s', 'fr-FR': 'durée {n}s', 'it-IT': 'durata {n}s',
    'es-ES': 'duró {n}s', 'ru-RU': 'длилось {n} с', 'hi-IN': '{n}s तक', 'ar-SA': 'استمر {n} ث',
  },
  ctxPanelTitle: {
    'zh-CN': '上下文容量', 'en-US': 'Context usage', 'ja-JP': 'コンテキスト容量', 'ko-KR': '컨텍스트 용량',
    'de-DE': 'Kontextkapazität', 'fr-FR': 'Capacité du contexte', 'it-IT': 'Capacità contesto',
    'es-ES': 'Capacidad de contexto', 'ru-RU': 'Ёмкость контекста', 'hi-IN': 'संदर्भ क्षमता', 'ar-SA': 'سعة السياق',
  },
  ctxCacheHitRate: {
    'zh-CN': '平均缓存命中率', 'en-US': 'Avg cache hit rate', 'ja-JP': '平均キャッシュ命中率', 'ko-KR': '평균 캐시 적중률',
    'de-DE': 'Ø Cache-Trefferquote', 'fr-FR': 'Taux de cache moyen', 'it-IT': 'Tasso medio cache',
    'es-ES': 'Tasa media de caché', 'ru-RU': 'Средний процент попаданий кэша', 'hi-IN': 'औसत कैश हिट दर', 'ar-SA': 'متوسط معدل إصابة ذاكرة التخزين المؤقت',
  },
  ctxSection_messages: {
    'zh-CN': '消息', 'en-US': 'Messages', 'ja-JP': 'メッセージ', 'ko-KR': '메시지',
    'de-DE': 'Nachrichten', 'fr-FR': 'Messages', 'it-IT': 'Messaggi',
    'es-ES': 'Mensajes', 'ru-RU': 'Сообщения', 'hi-IN': 'संदेश', 'ar-SA': 'الرسائل',
  },
  ctxSection_system_tools: {
    'zh-CN': '系统工具', 'en-US': 'System tools', 'ja-JP': 'システムツール', 'ko-KR': '시스템 도구',
    'de-DE': 'System-Tools', 'fr-FR': 'Outils système', 'it-IT': 'Strumenti di sistema',
    'es-ES': 'Herramientas del sistema', 'ru-RU': 'Системные инструменты', 'hi-IN': 'सिस्टम टूल', 'ar-SA': 'أدوات النظام',
  },
  ctxSection_mcp_tools: {
    'zh-CN': 'MCP 工具', 'en-US': 'MCP tools', 'ja-JP': 'MCPツール', 'ko-KR': 'MCP 도구',
    'de-DE': 'MCP-Tools', 'fr-FR': 'Outils MCP', 'it-IT': 'Strumenti MCP',
    'es-ES': 'Herramientas MCP', 'ru-RU': 'Инструменты MCP', 'hi-IN': 'MCP टूल', 'ar-SA': 'أدوات MCP',
  },
  ctxSection_other: {
    'zh-CN': '其他', 'en-US': 'Other', 'ja-JP': 'その他', 'ko-KR': '기타',
    'de-DE': 'Sonstiges', 'fr-FR': 'Autres', 'it-IT': 'Altro',
    'es-ES': 'Otros', 'ru-RU': 'Прочее', 'hi-IN': 'अन्य', 'ar-SA': 'أخرى',
  },
  ctxSection_skills: {
    'zh-CN': '技能', 'en-US': 'Skills', 'ja-JP': 'スキル', 'ko-KR': '스킬',
    'de-DE': 'Skills', 'fr-FR': 'Compétences', 'it-IT': 'Competenze',
    'es-ES': 'Habilidades', 'ru-RU': 'Навыки', 'hi-IN': 'कौशल', 'ar-SA': 'المهارات',
  },
  ctxSection_system_prompt: {
    'zh-CN': '系统提示词', 'en-US': 'System prompt', 'ja-JP': 'システムプロンプト', 'ko-KR': '시스템 프롬프트',
    'de-DE': 'Systemprompt', 'fr-FR': 'Prompt système', 'it-IT': 'Prompt di sistema',
    'es-ES': 'Prompt del sistema', 'ru-RU': 'Системный промпт', 'hi-IN': 'सिस्टम प्रॉम्प्ट', 'ar-SA': 'موجه النظام',
  },
}

const LOCALES = Object.keys(KEYS.phaseUnderstanding)
let touched = 0

for (const locale of LOCALES) {
  const file = join(root, `${locale}.ts`)
  let src = readFileSync(file, 'utf8')
  if (src.includes('phaseUnderstanding:')) {
    console.log(`skip ${locale} (already has keys)`)
    continue
  }
  // 锚点：chat 段内 toolBackgroundHint 行（每文件唯一）
  const lines = src.split('\n')
  const anchorIdx = lines.findIndex((l) => /^\s*toolBackgroundHint:/.test(l))
  if (anchorIdx < 0) {
    console.error(`FAIL ${locale}: anchor toolBackgroundHint not found`)
    process.exitCode = 1
    continue
  }
  const indent = (lines[anchorIdx].match(/^(\s*)/) || [])[1] || '    '
  const block = Object.entries(KEYS)
    .map(([key, table]) => `${indent}${key}: '${table[locale]}',`)
    .join('\n')
  lines.splice(anchorIdx + 1, 0, block)
  writeFileSync(file, lines.join('\n'), 'utf8')
  touched += 1
  console.log(`ok ${locale} (+${Object.keys(KEYS).length} keys)`)
}
console.log(`done: ${touched}/${LOCALES.length} locales updated`)
