/**
 * Markdown 渲染 —— 对话消息富文本内容 (ChatPage 消息气泡)
 *
 * 背景: 旧 renderRichContent 用手写正则解析 MD，仅支持围栏代码块/粗体/
 * 斜体/链接/图片; 标题、列表、引用、表格、删除线全部退化为纯文本;
 * 且代码块内容被后续正则二次污染 (``` 内的 ** 变 <strong>、\n 变 <br/>)，
 * 行内代码同理。
 *
 * 设计:
 *   - marked (GFM + breaks) 完整语法，每次调用实例化避免全局配置污染
 *   - 自定义 code/link/image renderer: 代码块卡片 (highlight.js 语法高亮
 *     + 语言标签 + 复制按钮), 链接/图片经 sanitizeUrl 协议校验
 *   - copyLabel 由调用方传入 (纯函数无 i18n 上下文)
 *   - 输出最后过 sanitizeHtmlStrict (DOMPurify 白名单) 兜底
 */
import { Marked, type Tokens } from 'marked'
import katex from 'katex'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import python from 'highlight.js/lib/languages/python'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import sql from 'highlight.js/lib/languages/sql'
import markdown from 'highlight.js/lib/languages/markdown'
import java from 'highlight.js/lib/languages/java'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import yaml from 'highlight.js/lib/languages/yaml'
import { escapeHtml, sanitizeUrl, sanitizeHtmlStrict } from './security'

// 只注册需要用到的语言 (core 包 + 单语言注册，避免全量包)
const HLJS_LANGUAGES: Array<[string, typeof javascript]> = [
  ['javascript', javascript],
  ['typescript', typescript],
  ['json', json],
  ['bash', bash],
  ['python', python],
  ['css', css],
  ['xml', xml],
  ['sql', sql],
  ['markdown', markdown],
  ['java', java],
  ['go', go],
  ['rust', rust],
  ['c', c],
  ['cpp', cpp],
  ['yaml', yaml],
]
for (const [name, language] of HLJS_LANGUAGES) {
  hljs.registerLanguage(name, language)
}

function createRenderer(copyLabel: string) {
  return {
    /** 围栏代码块: 语法高亮 + 语言标签 + 复制按钮 (升级后的代码块卡片) */
    code(token: Tokens.Code): string {
      const rawLang = (token.lang || '').trim().toLowerCase()
      const lang = rawLang.split(/\s+/)[0]
      // mermaid 占位（补课 E）：不产 pre/code 卡片，输出带 data-mermaid-code
      // 的占位 div，ChatPage 在 DOM 插入后动态 import mermaid 渲染 SVG
      if (lang === 'mermaid') {
        const encoded = encodeURIComponent(token.text)
        return `<div class="nr-mermaid" data-mermaid-code="${encoded}"><pre class="nr-mermaid-src">${escapeHtml(token.text)}</pre></div>`
      }
      // hljs 高亮输出本身已转义 HTML 特殊字符; 语言未知时退回纯转义
      const highlighted =
        lang && hljs.getLanguage(lang) ? hljs.highlight(token.text, { language: lang }).value : escapeHtml(token.text)
      const langLabel = lang ? escapeHtml(lang) : 'code'
      const codeClass = `language-${escapeHtml(lang || 'code')}`
      return (
        `<div class="nr-code-wrap">` +
        `<div class="nr-code-header">` +
        `<span class="nr-code-lang">${langLabel}</span>` +
        `<button class="nr-code-copy-btn" aria-label="copy">${escapeHtml(copyLabel)}</button>` +
        `</div>` +
        `<pre class="nr-code-block"><code class="${codeClass}">${highlighted}</code></pre>` +
        `</div>`
      )
    },

    /** 链接: 协议白名单校验, 危险协议退化为纯文本 (不产生 <a>) */
    link(token: Tokens.Link): string {
      const safeUrl = sanitizeUrl(token.href)
      const text = escapeHtml(token.text)
      if (!safeUrl) return text
      const title = token.title ? ` title="${escapeHtml(token.title)}"` : ''
      return `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" class="nr-msg-link"${title}>${text}</a>`
    },

    /** 图片: 协议白名单校验 + 懒加载; 危险协议直接丢弃 */
    image(token: Tokens.Image): string {
      const safeUrl = sanitizeUrl(token.href)
      if (!safeUrl) return ''
      const alt = escapeHtml(token.text || '')
      const title = token.title ? ` title="${escapeHtml(token.title)}"` : ''
      return `<div class="nr-inline-image"><img src="${escapeHtml(safeUrl)}" alt="${alt}" loading="lazy"${title} /><span class="nr-img-caption">${alt}</span></div>`
    },
  }
}

/**
 * 将 Markdown 文本渲染为安全的 HTML 字符串 (已过 DOMPurify 清洗)。
 *
 * 数学公式（KaTeX，QwenPaw 对齐）：
 *   1. 渲染前提取 $$...$$ / $...$ / \(..\) / \[..\] 为占位符（跳过代码段），
 *      避免 marked 把数学语法当普通文本破坏；
 *   2. marked + DOMPurify 正常渲染（占位符是纯文本，原样通过白名单）；
 *   3. 渲染后把占位符替换为 katex.renderToString 输出（本地生成、可信，
 *      不再过 sanitize——katex 输出的 MathML/svg 会被白名单剥离）。
 *
 * @param text 用户消息内容 (可为流式累加的半截文本, 未闭合围栏不会抛错)
 * @param copyLabel 代码块复制按钮文案 (由调用方提供 i18n 文本)
 */
export function renderMarkdown(text: string, copyLabel = '⧉'): string {
  if (!text || typeof text !== 'string') return ''

  const { prepared, restore } = extractMath(text)

  const marked = new Marked({
    gfm: true,
    breaks: true,
    renderer: createRenderer(copyLabel),
  })

  let html: string
  try {
    html = marked.parse(prepared, { async: false }) as string
  } catch {
    // 极端 malformed 输入也不抛错: 退化为纯文本
    html = escapeHtml(text)
  }

  // P0-7 层 3: DOMPurify 白名单兜底 (del/hr 已显式加入)
  const safe = sanitizeHtmlStrict(html)
  return restore(safe)
}

// ---------------------------------------------------------------------------
// KaTeX 数学公式（QwenPaw KaTeX 对齐）
// ---------------------------------------------------------------------------

interface MathExtractResult {
  /** 数学片段替换为占位符后的 markdown 源 */
  prepared: string
  /** 渲染+清洗后回填 katex HTML 的函数 */
  restore: (html: string) => string
}

/** 按 markdown 代码段切分文本：fenced ```、tilde ~~~、inline ` 内不提取数学。 */
function splitByCodeSegments(text: string): Array<{ isCode: boolean; content: string }> {
  const segments: Array<{ isCode: boolean; content: string }> = []
  const pattern = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]+`)/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) segments.push({ isCode: false, content: text.slice(last, m.index) })
    segments.push({ isCode: true, content: m[0] })
    last = m.index + m[0].length
  }
  if (last < text.length) segments.push({ isCode: false, content: text.slice(last) })
  return segments
}

/**
 * 提取数学片段为占位符。
 * 支持：$$..$$（display）、$..$（inline）、\(..\)（inline）、\[..\]（display）。
 * 未闭合的（流式半截）不提取，按普通文本渲染。
 */
function extractMath(text: string): MathExtractResult {
  const stash: Array<{ display: boolean; latex: string }> = []
  const mathPattern = /(\$\$[\s\S]+?\$\$)|(\$\$(?![\s\S]*?\$\$))|(\$[^$\n]+?\$)|\\\(([^)]+?)\\\)|\\\[([\s\S]+?)\\\]/g

  const replaceInSegment = (segment: string): string =>
    segment.replace(mathPattern, (match, ddBlock, ddOpen, inlineDollar, paren, bracket) => {
      if (ddOpen) return match // 未闭合 $$（流式半截）保持原样
      let display = false
      let latex = ''
      if (ddBlock) {
        display = true
        latex = ddBlock.slice(2, -2)
      } else if (inlineDollar) {
        latex = inlineDollar.slice(1, -1)
      } else if (paren !== undefined) {
        latex = paren
      } else if (bracket !== undefined) {
        display = true
        latex = bracket
      } else {
        return match
      }
      if (!latex.trim()) return match
      const idx = stash.length
      stash.push({ display, latex })
      return `⟦NR_MATH_${idx}⟧`
    })

  const segments = splitByCodeSegments(text)
  const prepared = segments
    .map((s) => (s.isCode ? s.content : replaceInSegment(s.content)))
    .join('')

  const restore = (html: string): string => {
    if (stash.length === 0) return html
    let out = html
    for (let i = 0; i < stash.length; i++) {
      const token = `⟦NR_MATH_${i}⟧`
      if (!out.includes(token)) continue
      const item = stash[i]
      let katexHtml: string
      try {
        katexHtml = katex.renderToString(item.latex, {
          displayMode: item.display,
          throwOnError: false,
          output: 'html',
        })
      } catch {
        katexHtml = escapeHtml(`$${item.latex}$`)
      }
      // 占位符可能被 marked 包进 <p>/<strong> 等，直接全局替换文本
      out = out.split(token).join(katexHtml)
    }
    return out
  }

  return { prepared, restore }
}
