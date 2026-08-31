// 模型筛选面板 i18n 增键脚本(additions+merge 工作流)
// 在每个语言的 model 块 discover 行后插入筛选相关键,
// 保留各文件原有换行风格(CRLF/LF 混合仓库,勿统一改写)。
// 幂等:已存在 filterModels 键的文件跳过。
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const LOCALES_DIR = path.resolve(__dirname, '../NeurUI/src/i18n/locales')

const KEYS = {
  'zh-CN': {
    filterModels: '筛选模型',
    filterByProvider: '按提供商筛选',
    filterByModality: '按输入模态筛选',
    filterFreeOnly: '仅显示免费模型',
    applyFilter: '应用筛选',
    filterResults: '筛选结果',
    noFilteredModels: '没有符合筛选条件的模型',
    modalityImage: '图像',
    modalityAudio: '音频',
    modalityVideo: '视频',
    addFiltered: '添加',
  },
  'en-US': {
    filterModels: 'Filter Models',
    filterByProvider: 'Filter by Provider',
    filterByModality: 'Filter by Input Modality',
    filterFreeOnly: 'Free Models Only',
    applyFilter: 'Apply Filter',
    filterResults: 'Filter Results',
    noFilteredModels: 'No models match the filters',
    modalityImage: 'Image',
    modalityAudio: 'Audio',
    modalityVideo: 'Video',
    addFiltered: 'Add',
  },
  'ja-JP': {
    filterModels: 'モデルを絞り込む',
    filterByProvider: 'プロバイダーで絞り込む',
    filterByModality: '入力モダリティで絞り込む',
    filterFreeOnly: '無料モデルのみ',
    applyFilter: '絞り込みを適用',
    filterResults: '絞り込み結果',
    noFilteredModels: '条件に合うモデルがありません',
    modalityImage: '画像',
    modalityAudio: '音声',
    modalityVideo: '動画',
    addFiltered: '追加',
  },
  'ko-KR': {
    filterModels: '모델 필터',
    filterByProvider: '제공자별 필터',
    filterByModality: '입력 모달리티별 필터',
    filterFreeOnly: '무료 모델만',
    applyFilter: '필터 적용',
    filterResults: '필터 결과',
    noFilteredModels: '조건에 맞는 모델이 없습니다',
    modalityImage: '이미지',
    modalityAudio: '오디오',
    modalityVideo: '비디오',
    addFiltered: '추가',
  },
  'fr-FR': {
    filterModels: 'Filtrer les modèles',
    filterByProvider: "Filtrer par fournisseur",
    filterByModality: "Filtrer par modalité d'entrée",
    filterFreeOnly: 'Modèles gratuits uniquement',
    applyFilter: 'Appliquer le filtre',
    filterResults: 'Résultats du filtre',
    noFilteredModels: 'Aucun modèle ne correspond aux filtres',
    modalityImage: 'Image',
    modalityAudio: 'Audio',
    modalityVideo: 'Vidéo',
    addFiltered: 'Ajouter',
  },
  'de-DE': {
    filterModels: 'Modelle filtern',
    filterByProvider: 'Nach Anbieter filtern',
    filterByModality: 'Nach Eingabemodalität filtern',
    filterFreeOnly: 'Nur kostenlose Modelle',
    applyFilter: 'Filter anwenden',
    filterResults: 'Filterergebnisse',
    noFilteredModels: 'Keine Modelle entsprechen den Filtern',
    modalityImage: 'Bild',
    modalityAudio: 'Audio',
    modalityVideo: 'Video',
    addFiltered: 'Hinzufügen',
  },
  'es-ES': {
    filterModels: 'Filtrar modelos',
    filterByProvider: 'Filtrar por proveedor',
    filterByModality: 'Filtrar por modalidad de entrada',
    filterFreeOnly: 'Solo modelos gratuitos',
    applyFilter: 'Aplicar filtro',
    filterResults: 'Resultados del filtro',
    noFilteredModels: 'Ningún modelo coincide con los filtros',
    modalityImage: 'Imagen',
    modalityAudio: 'Audio',
    modalityVideo: 'Vídeo',
    addFiltered: 'Añadir',
  },
  'it-IT': {
    filterModels: 'Filtra modelli',
    filterByProvider: 'Filtra per provider',
    filterByModality: 'Filtra per modalità di input',
    filterFreeOnly: 'Solo modelli gratuiti',
    applyFilter: 'Applica filtro',
    filterResults: 'Risultati del filtro',
    noFilteredModels: 'Nessun modello corrisponde ai filtri',
    modalityImage: 'Immagine',
    modalityAudio: 'Audio',
    modalityVideo: 'Video',
    addFiltered: 'Aggiungi',
  },
  'ru-RU': {
    filterModels: 'Фильтр моделей',
    filterByProvider: 'Фильтр по провайдеру',
    filterByModality: 'Фильтр по входной модальности',
    filterFreeOnly: 'Только бесплатные модели',
    applyFilter: 'Применить фильтр',
    filterResults: 'Результаты фильтра',
    noFilteredModels: 'Нет моделей по заданным условиям',
    modalityImage: 'Изображение',
    modalityAudio: 'Аудио',
    modalityVideo: 'Видео',
    addFiltered: 'Добавить',
  },
  'ar-SA': {
    filterModels: 'تصفية النماذج',
    filterByProvider: 'تصفية حسب المزود',
    filterByModality: 'تصفية حسب نمط الإدخال',
    filterFreeOnly: 'النماذج المجانية فقط',
    applyFilter: 'تطبيق التصفية',
    filterResults: 'نتائج التصفية',
    noFilteredModels: 'لا توجد نماذج مطابقة',
    modalityImage: 'صورة',
    modalityAudio: 'صوت',
    modalityVideo: 'فيديو',
    addFiltered: 'إضافة',
  },
  'hi-IN': {
    filterModels: 'मॉडल फ़िल्टर',
    filterByProvider: 'प्रदाता द्वारा फ़िल्टर',
    filterByModality: 'इनपुट मॉडलिटी फ़िल्टर',
    filterFreeOnly: 'केवल मुफ़्त मॉडल',
    applyFilter: 'फ़िल्टर लागू करें',
    filterResults: 'फ़िल्टर परिणाम',
    noFilteredModels: 'कोई मिलता-जुलता मॉडल नहीं',
    modalityImage: 'छवि',
    modalityAudio: 'ऑडियो',
    modalityVideo: 'वीडियो',
    addFiltered: 'जोड़ें',
  },
}

const results = []
for (const [locale, keys] of Object.entries(KEYS)) {
  const file = path.join(LOCALES_DIR, `${locale}.ts`)
  let content = fs.readFileSync(file, 'utf8')

  if (content.includes('filterModels')) {
    results.push(`${locale}: SKIP (已存在)`)
    continue
  }

  // 定位 model 块内的 discover 锚点行(含其换行符以保留原 EOL 风格)
  const anchorRe = /^([ \t]*discover: '[^']*',)(\r?\n)/m
  const m = content.match(anchorRe)
  if (!m) {
    results.push(`${locale}: FAIL (未找到 discover 锚点)`)
    continue
  }
  const eol = m[2]
  const indent = m[1].match(/^[ \t]*/)[0]
  const insertion = Object.entries(keys)
    .map(([k, v]) => `${indent}${k}: ${v.includes("'") ? `'${v.replace(/'/g, "\\'")}'` : `'${v}'`},`)
    .join(eol)
  content = content.replace(anchorRe, `$1${eol}${insertion}${eol}`)

  fs.writeFileSync(file, content, 'utf8')
  const eolTag = eol === '\r\n' ? 'CRLF' : 'LF'
  results.push(`${locale}: OK (+${Object.keys(keys).length} keys, ${eolTag})`)
}
console.log(results.join('\n'))
