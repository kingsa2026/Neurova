/**
 * 工具卡分化（补课 3.1，对齐 QP 领域卡思路的轻量版）。
 *
 * 按工具名映射到五类变体（computer/file/search/shell/code/general），
 * 模板据此选图标/标题文案/tag 颜色——数据层（useChat toolCalls）不动。
 * 纯函数，供 ChatPage 与单测共用。
 */
export type ToolCardVariant = 'computer' | 'file' | 'search' | 'shell' | 'code' | 'general'

const VARIANT_RULES: Array<{ variant: ToolCardVariant; prefixes: string[] }> = [
  { variant: 'computer', prefixes: ['computer_', 'browser_', 'screen_', 'mouse_', 'keyboard_'] },
  {
    variant: 'file',
    prefixes: ['read_file', 'write_file', 'edit_file', 'append_file', 'list_dir', 'file_', 'upload', 'download'],
  },
  {
    variant: 'search',
    prefixes: ['search', 'grep', 'glob', 'recall', 'semantic', 'web_search', 'knowledge_'],
  },
  { variant: 'shell', prefixes: ['shell', 'bash', 'terminal', 'run_command', 'execute_command', 'cmd_'] },
  { variant: 'code', prefixes: ['run_code', 'execute_code', 'python', 'code_', 'create_skill', 'nl_synthesize'] },
]

/** 工具名 → 卡片变体（无匹配落 general）。 */
export function toolCardVariant(name: string | undefined | null): ToolCardVariant {
  if (!name) return 'general'
  const lower = name.toLowerCase()
  for (const { variant, prefixes } of VARIANT_RULES) {
    if (prefixes.some((p) => lower.startsWith(p))) return variant
  }
  return 'general'
}

/** 变体 → 图标。 */
export function variantIcon(variant: ToolCardVariant): string {
  switch (variant) {
    case 'computer':
      return '🖥️'
    case 'file':
      return '📁'
    case 'search':
      return '🔍'
    case 'shell':
      return '⌨️'
    case 'code':
      return '🧬'
    default:
      return '🔧'
  }
}

/** 变体 → antd tag color。 */
export function variantColor(variant: ToolCardVariant): string {
  switch (variant) {
    case 'computer':
      return 'purple'
    case 'file':
      return 'blue'
    case 'search':
      return 'cyan'
    case 'shell':
      return 'orange'
    case 'code':
      return 'geekblue'
    default:
      return 'default'
  }
}
