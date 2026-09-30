/**
 * 工具调用卡换行契约（2026-09-24 报障：工具卡内容不折行，只能横向拖动）。
 *
 * 根因：工具卡的参数/结果块是 <pre>，样式给了 `white-space: pre` + `overflow-x: auto`
 * ——长行（JSON 里的长路径/token、单行长结果）永不折行，只能出现横向滚动条；
 * 卡头标题则是 `nowrap + ellipsis`，长任务名被裁成省略号。
 * 二者同属"卡内换行"这一条契约，故同表断言。
 *
 * 用 jsdom 真跑 CSS 层叠（selectors 匹配 + 简写展开），不是文本包含式断言：
 * 断言值直接来自 getComputedStyle，改错文件位置同样会红。
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const SRC = resolve(process.cwd(), 'src')
const CSS_PATH = resolve(SRC, 'styles/messageRender.css')

/** 工具卡 DOM 骨架：与 MessageSteps.vue 模板结构一致（steps 段 + legacy 兜底段）。 */
function mountToolCardSkeleton(): void {
  const style = document.createElement('style')
  style.textContent = readFileSync(CSS_PATH, 'utf-8')
  document.head.appendChild(style)
  document.body.innerHTML = `
    <div class="nr-tool-background" id="bg"></div>
    <div class="nr-msg-reasoning"><div class="nr-reasoning-content" id="lr"></div></div>
    <div class="nr-step-item"><div class="nr-step-body">
      <div class="nr-step-reasoning" id="sr"></div>
    </div></div>
    <div class="nr-msg-steps">
      <div class="nr-steps-timeline">
        <div class="nr-step-item nr-step--tool">
          <div class="nr-step-header">
            <span class="nr-step-icon"></span>
            <span class="nr-step-title" id="t">很长的任务名</span>
            <span class="nr-step-badge is-done"></span>
            <span class="nr-step-toggle"></span>
          </div>
          <div class="nr-step-body">
            <pre class="nr-tool-args" id="a">{}</pre>
            <div class="nr-tool-result">
              <pre class="nr-tool-result-content" id="r"></pre>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="nr-msg-tool-call">
      <div class="nr-tool-header">
        <span class="nr-tool-name" id="n">long_tool_name</span>
      </div>
      <pre class="nr-tool-args" id="la"></pre>
    </div>`
}

function computed(selector: string, prop: string): string {
  const el = document.querySelector(selector)
  if (!el) throw new Error(`骨架缺元素：${selector}`)
  return getComputedStyle(el).getPropertyValue(prop)
}

/** 递归收集 src 下的 .vue / .css 文件。 */
function collectStyleSources(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) out.push(...collectStyleSources(full))
    else if (name.endsWith('.vue') || name.endsWith('.css')) out.push(full)
  }
  return out
}

describe('工具调用卡换行契约', () => {
  beforeAll(mountToolCardSkeleton)

  it('参数块在卡内折行：pre-wrap + 长串可断，无横向滚动', () => {
    expect(computed('#a', 'white-space')).toBe('pre-wrap')
    expect(computed('#a', 'overflow-wrap')).toBe('anywhere')
    expect(['auto', 'scroll']).not.toContain(computed('#a', 'overflow-x'))
    // 纵向仍限高（过长结果不拉爆消息流），滚动条改走纵向
    expect(computed('#a', 'max-height')).toBe('120px')
    expect(computed('#a', 'overflow-y')).toBe('auto')
  })

  it('结果块与参数块同契约（同一条规则覆盖两者）', () => {
    expect(computed('#r', 'white-space')).toBe('pre-wrap')
    expect(computed('#r', 'overflow-wrap')).toBe('anywhere')
    expect(['auto', 'scroll']).not.toContain(computed('#r', 'overflow-x'))
  })

  it('legacy 兜底卡参数块同契约（旧消息同源渲染）', () => {
    expect(computed('#la', 'white-space')).toBe('pre-wrap')
    expect(computed('#la', 'overflow-wrap')).toBe('anywhere')
    expect(['auto', 'scroll']).not.toContain(computed('#la', 'overflow-x'))
  })

  it('步骤卡标题折行而非省略号截断', () => {
    expect(computed('#t', 'white-space')).not.toBe('nowrap')
    expect(computed('#t', 'text-overflow')).not.toBe('ellipsis')
    expect(computed('#t', 'overflow-wrap')).toBe('anywhere')
    // flex 子项要能收缩到内容宽以下，否则长 token 反向撑破卡片
    expect(computed('#t', 'min-width')).toBe('0px')
  })

  it('卡头在窄容器下可换行（子项不被互相挤破）', () => {
    expect(computed('.nr-step-header', 'flex-wrap')).toBe('wrap')
    expect(computed('.nr-tool-header', 'flex-wrap')).toBe('wrap')
    expect(computed('#n', 'overflow-wrap')).toBe('anywhere')
    expect(computed('#n', 'min-width')).toBe('0px')
  })

  it('同一根因的卡内旁支命中点一并收口（后台提示条 / legacy 推理段）', () => {
    expect(computed('.nr-tool-background', 'overflow-wrap')).toBe('anywhere')
    expect(computed('.nr-reasoning-content', 'overflow-wrap')).toBe('anywhere')
    // 思考段既有实现用 word-break: break-word 达到同一效果（它不外溢，见 live 实测）
    expect(computed('.nr-step-reasoning', 'word-break')).toBe('break-word')
  })

  it('该契约只有一份定义（messageRender.css），不在消费方留平行副本', () => {
    const definitions = collectStyleSources(SRC).filter((file) => {
      const src = readFileSync(file, 'utf-8').replace(/\/\*[\s\S]*?\*\//g, '')
      return /\.nr-tool-(args|result-content|background)\s*[,{]/.test(src)
    })
    // 分隔符归一必须**两侧都做**：Windows 上 resolve() 给出的 SRC 含反斜杠，
    // 只归一样本路径会让前缀替换失配、相对路径退化成绝对路径（本机实测该条恒红）。
    const srcRoot = SRC.replace(/\\/g, '/')
    const relative = definitions.map((f) => f.replace(/\\/g, '/').replace(`${srcRoot}/`, ''))
    expect(relative).toEqual(['styles/messageRender.css'])
  })
})
