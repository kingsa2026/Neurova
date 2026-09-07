#!/usr/bin/env node
/** 补顶入卡片 4 键 × 11 语言（锚点：queueEdit 行后）。幂等。
 *  queueSendNow=立即 / queueSendNowTitle / queueDrag / queueSending / queueFailed / queueEditInline
 *  （共 6 键；queueEdit 旧键保留供兼容引用） */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'NeurUI', 'src', 'i18n', 'locales')

const KEYS = {
  queueSendNow: {
    'zh-CN': '立即',
    'en-US': 'Now',
    'ja-JP': '今すぐ',
    'ko-KR': '지금',
    'de-DE': 'Jetzt',
    'fr-FR': 'Maintenant',
    'it-IT': 'Adesso',
    'es-ES': 'Ahora',
    'ru-RU': 'Сейчас',
    'hi-IN': 'अभी',
    'ar-SA': 'الآن',
  },
  queueSendNowTitle: {
    'zh-CN': '立即发送：插到队首，当前空闲则马上发出',
    'en-US': 'Send now: move to queue head and dispatch when idle',
    'ja-JP': '今すぐ送信：先頭に移動し、空き時に送信',
    'ko-KR': '지금 보내기: 맨 앞으로 이동 후 즉시 전송',
    'de-DE': 'Jetzt senden: an den Anfang und sofort absenden',
    'fr-FR': 'Envoyer maintenant : passer en tête et émettre',
    'it-IT': 'Invia adesso: in testa alla coda e invia',
    'es-ES': 'Enviar ahora: pasar al frente y enviar',
    'ru-RU': 'Отправить сейчас: в начало очереди и отправить',
    'hi-IN': 'अभी भेजें: कतार में सबसे आगे और भेजें',
    'ar-SA': 'إرسال الآن: إلى مقدمة القائمة ثم الإرسال',
  },
  queueTopAuto: {
    'zh-CN': '已置顶，当前回复完成后优先发送',
    'en-US': 'Moved to top — sends first when the current reply finishes',
    'ja-JP': '先頭に移動 — 現在の返信後に優先送信されます',
    'ko-KR': '맨 앞으로 이동 — 현재 응답 후 우선 전송됩니다',
    'de-DE': 'Nach oben verschoben — wird nach der aktuellen Antwort zuerst gesendet',
    'fr-FR': 'Placé en tête — envoyé en priorité après la réponse en cours',
    'it-IT': 'Spostato in testa — inviato per primo dopo la risposta corrente',
    'es-ES': 'Movido al frente — se envía primero al terminar la respuesta',
    'ru-RU': 'Перемещено в начало — отправится первым после текущего ответа',
    'hi-IN': 'सबसे ऊपर ले जाया गया — वर्तमान उत्तर के बाद पहले भेजा जाएगा',
    'ar-SA': 'نُقل إلى المقدمة — سيُرسل أولاً بعد انتهاء الرد الحالي',
  },
  queueDrag: {
    'zh-CN': '拖拽排序',
    'en-US': 'Drag to reorder',
    'ja-JP': 'ドラッグで並べ替え',
    'ko-KR': '드래그하여 정렬',
    'de-DE': 'Zum Sortieren ziehen',
    'fr-FR': 'Glisser pour réordonner',
    'it-IT': 'Trascina per riordinare',
    'es-ES': 'Arrastra para reordenar',
    'ru-RU': 'Перетащите для сортировки',
    'hi-IN': 'क्रम बदलने के लिए खींचें',
    'ar-SA': 'اسحب لإعادة الترتيب',
  },
  queueSending: {
    'zh-CN': '发送中',
    'en-US': 'Sending',
    'ja-JP': '送信中',
    'ko-KR': '전송 중',
    'de-DE': 'Wird gesendet',
    'fr-FR': 'Envoi en cours',
    'it-IT': 'Invio in corso',
    'es-ES': 'Enviando',
    'ru-RU': 'Отправляется',
    'hi-IN': 'भेजा जा रहा है',
    'ar-SA': 'جارٍ الإرسال',
  },
  queueFailed: {
    'zh-CN': '发送失败',
    'en-US': 'Send failed',
    'ja-JP': '送信失敗',
    'ko-KR': '전송 실패',
    'de-DE': 'Senden fehlgeschlagen',
    'fr-FR': 'Échec envoi',
    'it-IT': 'Invio non riuscito',
    'es-ES': 'Error al enviar',
    'ru-RU': 'Ошибка отправки',
    'hi-IN': 'भेजना विफल',
    'ar-SA': 'فشل الإرسال',
  },
  queueEditInline: {
    'zh-CN': '编辑顶入内容，回车确认 / Esc 取消',
    'en-US': 'Editing queued message — Enter to confirm, Esc to cancel',
    'ja-JP': '予約メッセージを編集 — Enterで確定 / Escでキャンセル',
    'ko-KR': '예약 메시지 편집 — Enter 확인 / Esc 취소',
    'de-DE': 'Nachricht bearbeiten — Enter bestätigen / Esc abbrechen',
    'fr-FR': 'Modification du message — Entrée pour valider / Échap pour annuler',
    'it-IT': 'Modifica messaggio in coda — Invio conferma / Esc annulla',
    'es-ES': 'Editando mensaje en cola — Enter confirma / Esc cancela',
    'ru-RU': 'Правка сообщения — Enter подтвердить / Esc отмена',
    'hi-IN': 'कतार संदेश संपादित करें — Enter पुष्टि / Esc रद्द',
    'ar-SA': 'تحرير الرسالة المدرجة — Enter للتأكيد / Esc للإلغاء',
  },
}

let touched = 0
for (const locale of Object.keys(KEYS.queueSendNow)) {
  const file = join(root, `${locale}.ts`)
  let src = readFileSync(file, 'utf8')
  const lines = src.split('\n')
  const idx = lines.findIndex((l) => /^\s*queueEdit:/.test(l))
  if (idx < 0) {
    console.error(`FAIL ${locale}: anchor queueEdit missing`)
    process.exitCode = 1
    continue
  }
  const indent = (lines[idx].match(/^(\s*)/) || [])[1] || '    '
  // 逐键幂等：缺哪个补哪个（首次 7 键全插，后续只补增量）
  const missing = Object.entries(KEYS).filter(([k]) => !src.includes(`${k}:`))
  if (missing.length === 0) {
    console.log(`skip ${locale}`)
    continue
  }
  const insert = missing.map(([k, texts]) =>
    `${indent}${k}: '${String(texts[locale]).replace(/\\/g, '\\\\').replace(/'/g, "\\'")}',`)
  lines.splice(idx + 1, 0, ...insert)
  writeFileSync(file, lines.join('\n'), 'utf8')
  touched += 1
}
console.log(`done: ${touched} locales`)
