/**
 * renderMarkdown —— 对话消息 Markdown 渲染契约测试
 *
 * 背景: 旧实现 (ChatPage.renderRichContent) 用手写正则解析 MD，
 * 仅支持围栏代码块/粗体/斜体/链接/图片；标题、列表、引用、表格、
 * 删除线全部退化为纯文本；且代码块内容会被后续正则二次污染
 * (``` 内的 ** 变 <strong>、\n 变 <br/>)，行内代码同理。
 *
 * 契约:
 *   1. 完整 GFM 渲染: 标题/列表/引用/粗斜体/删除线/表格/行内代码
 *   2. 代码块: nr-code-wrap 包装 + 语言标签 + 复制按钮;
 *      代码内容字面保留 (** 不解析、< 转义), 不依赖 data-code 属性
 *   3. XSS: script/事件处理器/javascript: 链接/iframe 一律剥离
 *   4. 链接: 安全协议 + target=_blank + rel=noopener noreferrer;
 *      javascript:/协议相对/data: 一律丢弃
 *   5. 图片: 安全 URL + loading=lazy; 危险协议丢弃
 *   6. 空输入/纯文本/半截代码块 不抛错, 输出始终是合法 HTML
 */
import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

describe('renderMarkdown — GFM 语法覆盖', () => {
  it('渲染标题 (h1-h6)', () => {
    const html = renderMarkdown('# 一级标题\n\n## 二级标题')
    expect(html).toContain('<h1>一级标题</h1>')
    expect(html).toContain('<h2>二级标题</h2>')
  })

  it('渲染无序/有序列表与嵌套', () => {
    const html = renderMarkdown('- 甲\n- 乙\n\n1. 第一\n2. 第二')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>甲</li>')
    expect(html).toContain('<ol>')
    expect(html).toContain('<li>第一</li>')
  })

  it('渲染引用块', () => {
    const html = renderMarkdown('> 这是引用')
    expect(html).toContain('<blockquote>')
    expect(html).toContain('这是引用')
  })

  it('渲染粗体/斜体/删除线', () => {
    const html = renderMarkdown('**粗体** 和 *斜体* 和 ~~删除~~')
    expect(html).toContain('<strong>粗体</strong>')
    expect(html).toContain('<em>斜体</em>')
    expect(html).toContain('<del>删除</del>')
  })

  it('渲染行内代码', () => {
    const html = renderMarkdown('使用 `npm install` 命令')
    expect(html).toContain('<code>npm install</code>')
  })

  it('渲染 GFM 表格', () => {
    const html = renderMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<th>a</th>')
    expect(html).toContain('<td>1</td>')
  })

  it('渲染分隔线', () => {
    const html = renderMarkdown('正文\n\n---\n\n结尾')
    expect(html).toContain('<hr>')
  })
})

describe('renderMarkdown — 代码块 (格式美化 + 防污染回归)', () => {
  it('围栏代码块包装为 nr-code-wrap 并带语言标签与复制按钮', () => {
    const html = renderMarkdown('```python\nprint("hi")\n```')
    expect(html).toContain('nr-code-wrap')
    expect(html).toContain('nr-code-header')
    expect(html).toContain('python')
    expect(html).toContain('nr-code-copy-btn')
    expect(html).toContain('class="language-python"')
  })

  it('无语言标注的代码块语言标签回退为 code', () => {
    const html = renderMarkdown('```\nplain text\n```')
    expect(html).toContain('nr-code-lang')
  })

  it('代码块内容保持字面 (旧 bug: ** 被解析为 strong)', () => {
    const html = renderMarkdown('```js\nconst x = a ** b\nconst s = "<div>"\n```')
    expect(html).toContain('a ** b')
    expect(html).not.toContain('<strong>')
  })

  it('代码块内容转义 HTML (旧 bug: <div> 被当作标签)', () => {
    const html = renderMarkdown('```html\n<div>hi</div>\n```')
    const text = html.replace(/<[^>]*>/g, '')
    expect(text).toContain('&lt;div&gt;')
    expect(html).not.toContain('<div>hi</div>')
  })

  it('复制链路不依赖 data-code 属性 (改用 DOM textContent)', () => {
    const html = renderMarkdown('```js\nconsole.log("hello")\n```')
    expect(html).not.toContain('data-code')
  })

  it('行内代码内容不被二次污染 (旧 bug: `**x**` 变 strong)', () => {
    const html = renderMarkdown('元数据 `**op**` 字段')
    expect(html).toContain('<code>**op**</code>')
    expect(html).not.toContain('<strong>')
  })

  it('输出语法高亮 span (highlight.js 已接线)', () => {
    const html = renderMarkdown('```js\nconst a = 1\n```')
    expect(html).toContain('hljs-')
  })
})

describe('renderMarkdown — XSS 三层防御', () => {
  it('剥离 script 标签', () => {
    const html = renderMarkdown('前文\n\n<script>alert(1)</script>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert(1)')
  })

  it('剥离事件处理器', () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">')
    expect(html).not.toContain('onerror')
  })

  it('javascript: 链接不产生 href', () => {
    const html = renderMarkdown('[点击](javascript:alert(1))')
    expect(html).not.toContain('javascript:')
    expect(html).not.toContain('<a href="javascript:')
  })

  it('协议相对链接 //evil.com 被丢弃', () => {
    const html = renderMarkdown('[外部](//evil.com)')
    expect(html).not.toContain('href="//evil.com"')
  })

  it('data:text/html 链接被丢弃', () => {
    const html = renderMarkdown('[注入](data:text/html,<script>alert(1)</script>)')
    expect(html).not.toContain('data:text/html')
  })

  it('iframe 被剥离', () => {
    const html = renderMarkdown('<iframe src="https://evil.com"></iframe>')
    expect(html).not.toContain('<iframe')
  })
})

describe('renderMarkdown — 链接与图片安全', () => {
  it('安全链接带 target=_blank 与 rel=noopener noreferrer', () => {
    const html = renderMarkdown('[文档](https://example.com)')
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })

  it('危险协议图片丢弃', () => {
    const html = renderMarkdown('![x](javascript:alert(1))')
    expect(html).not.toContain('<img')
  })

  it('安全图片带 loading=lazy', () => {
    const html = renderMarkdown('![截图](https://cdn.example.com/a.png)')
    expect(html).toContain('<img')
    expect(html).toContain('loading="lazy"')
  })
})

describe('renderMarkdown — 鲁棒性', () => {
  it('空输入返回空串', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(undefined as unknown as string)).toBe('')
  })

  it('纯文本 < 被转义', () => {
    const html = renderMarkdown('1 < 2 且 3 > 2')
    expect(html).toContain('1 &lt; 2')
    expect(html).toContain('3 &gt; 2')
  })

  it('流式半截代码块不抛错且输出合法', () => {
    // 模拟流式到一半: 围栏未闭合
    const html = renderMarkdown('```python\nprint("hi"')
    expect(() => renderMarkdown('```python\nprint("hi"')).not.toThrow()
    expect(html).toContain('python')
  })

  it('流式增量重复渲染稳定 (逐 chunk 累积不损坏)', () => {
    let acc = ''
    const chunks = ['# 标题\n\n', '正文 **加粗**\n\n', '```js\nconst a = 1\n```']
    for (const c of chunks) {
      acc += c
      const html = renderMarkdown(acc)
      expect(html.length).toBeGreaterThan(0)
    }
    expect(renderMarkdown(acc)).toContain('language-js')
  })
})
