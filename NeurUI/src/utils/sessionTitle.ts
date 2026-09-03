/**
 * 会话语义标题判定：前端与后端 session_title.is_default_title 同口径。
 *
 * 命中默认清单（含调用方 i18n 当前语言值）→ 需要语义自动填充。
 */
const BUILTIN_DEFAULT_TITLES = ['新对话', '新建对话', '新会话', 'New conversation']

export function isDefaultChatTitle(
  title: string | null | undefined,
  defaults: string[] = [],
): boolean {
  const t = (title ?? '').trim()
  if (!t) return true
  return defaults.concat(BUILTIN_DEFAULT_TITLES).includes(t)
}
