/**
 * i18n fallback resolver — 统一的 i18n 翻译 + fallback 工具
 *
 * #2 / ADR 0008: 配合 "建立统一的UI提示库" 用户规则, 提供统一的 i18n
 * 翻译解析入口, 替代散落在各组件中的 `t(key) || fallback` antipattern.
 *
 * 根因 (chat.loadHistoryFailed toast 异常显示 bug):
 *   旧契约 `t(key) || fallback` 在 vue-i18n 缺失 key 时不工作:
 *   vue-i18n Composition API 模式 (legacy: false) 下 t(missingKey) 返回
 *   key 字符串本身 (truthy), `|| fallback` 短路求值不触发, 导致 toast
 *   显示 raw key (例如 "chat.loadHistoryFailed" 而非 "加载历史对话失败").
 *
 * 契约:
 *   resolveI18nMessage(t, key, fallback):
 *     - 若 t(key) === key (vue-i18n 缺失翻译信号) → 返回 fallback
 *     - 若 t(key) 为空字符串/undefined/null → 返回 fallback (防御)
 *     - 否则返回 t(key) (命中翻译)
 *
 * 用法:
 *   import { resolveI18nMessage } from '@/utils/i18n'
 *   import { useI18n } from 'vue-i18n'
 *   const { t } = useI18n()
 *   const msg = resolveI18nMessage(t, 'chat.loadHistoryFailed', '加载历史对话失败')
 *
 * 详见 docs/bugfix-delete-session-userid-mismatch.md
 *   "前端错误反馈策略深化" → "i18n fallback resolver" 小节.
 */

/**
 * vue-i18n 翻译函数的契约接口 (兼容 Composition API 的 t).
 * 接受 key 字符串, 返回翻译后的字符串.
 */
export type TranslationFn = (key: string) => string

/**
 * 解析 i18n key + fallback, 在缺失翻译时返回 fallback.
 *
 * @param t vue-i18n 翻译函数 (来自 useI18n().t)
 * @param key i18n key, 例如 'chat.loadHistoryFailed'
 * @param fallback 缺失翻译时的兜底文案
 * @returns 翻译字符串或 fallback
 */
export function resolveI18nMessage(
  t: TranslationFn,
  key: string,
  fallback: string,
): string {
  const translated = t(key)
  // 防御 1: t(key) 返回 undefined/null (类型不严的 mock 或异常场景)
  if (translated == null) return fallback
  // 防御 2: t(key) 返回空字符串
  if (translated === '') return fallback
  // 核心: vue-i18n Composition API 在缺失 key 时返回 key 字符串本身
  // (truthy), 导致 `|| fallback` 短路. 用 === 严格判断检测缺失翻译.
  if (translated === key) return fallback
  return translated
}

export default resolveI18nMessage
