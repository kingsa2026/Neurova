/**
 * MarkdownText - 轻量 Markdown 渲染组件（会话气泡内使用，零第三方依赖）
 *
 * 支持：标题(1-6)、无序/有序列表、围栏代码块（```lang）、行内代码、
 *       粗体/斜体、链接、引用、表格、分隔线；普通文本按段落渲染。
 * 设计约束：零第三方依赖；流式场景下 content 逐帧增长，每次 build 重解析
 *       （块级切分成本低，12KB 以内回复无感知卡顿）。
 * 不支持（气泡场景低频）：图片、内联 HTML、脚注、任务列表勾选态。
 */
import { StyleManager } from '../../libs/style/StyleManager';

/** 行内片段：纯文本/粗体/斜体/行内代码/链接 */
interface MdSpan {
  text: string;
  bold: boolean;
  italic: boolean;
  code: boolean;
  link: boolean;
}

/** 块级元素 */
interface MdBlock {
  kind: string;        // para | h | code | ul | ol | quote | hr | table
  lines: string[];
  level: number;       // 标题级别(1-6) / 列表缩进级
  ordered: boolean;
  lang: string;
}

@Component
export struct MarkdownText {
  @Prop content: string = '';
  private sm: StyleManager = StyleManager.getInstance();

  /** 块级解析：按行扫描，围栏/标题/列表/引用/表格/分隔线/段落 */
  private parseBlocks(src: string): MdBlock[] {
    const blocks: MdBlock[] = [];
    const lines = src.replace(/\r\n/g, '\n').split('\n');
    let i = 0;
    let para: string[] = [];
    const flushPara = () => {
      if (para.length > 0) {
        blocks.push({ kind: 'para', lines: para, level: 0, ordered: false, lang: '' });
        para = [];
      }
    };
    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();
      if (trimmed.startsWith('```')) {
        flushPara();
        const lang = trimmed.slice(3).trim();
        const codeLines: string[] = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i += 1;
        }
        i += 1; // 跳过收尾 ```
        blocks.push({ kind: 'code', lines: codeLines, level: 0, ordered: false, lang: lang });
        continue;
      }
      const heading = trimmed.match(/^#{1,6}\s+(.*)$/);
      if (heading) {
        flushPara();
        const level = trimmed.length - trimmed.replace(/^#+/, '').length;
        blocks.push({ kind: 'h', lines: [heading[1]], level: level, ordered: false, lang: '' });
        i += 1;
        continue;
      }
      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushPara();
        blocks.push({ kind: 'hr', lines: [], level: 0, ordered: false, lang: '' });
        i += 1;
        continue;
      }
      if (trimmed.startsWith('>')) {
        flushPara();
        const quoteLines: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith('>')) {
          quoteLines.push(lines[i].trim().replace(/^>\s?/, ''));
          i += 1;
        }
        blocks.push({ kind: 'quote', lines: quoteLines, level: 0, ordered: false, lang: '' });
        continue;
      }
      if (trimmed.startsWith('|') && trimmed.endsWith('|') && trimmed.indexOf('|', 1) < trimmed.length - 1) {
        flushPara();
        const tableLines: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith('|')) {
          tableLines.push(lines[i].trim());
          i += 1;
        }
        blocks.push({ kind: 'table', lines: tableLines, level: 0, ordered: false, lang: '' });
        continue;
      }
      const ul = line.match(/^(\s*)[-*+]\s+(.*)$/);
      const ol = ul ? null : line.match(/^(\s*)\d+\.\s+(.*)$/);
      if (ul || ol) {
        flushPara();
        const kind = ul ? 'ul' : 'ol';
        const items: string[] = [];
        const indent = (ul ? ul[1] : (ol ? ol[1] : '')).length;
        if (ul) {
          items.push(ul[2]);
        } else if (ol) {
          items.push(ol[2]);
        }
        i += 1;
        while (i < lines.length) {
          const cont = kind === 'ul' ? lines[i].match(/^(\s*)[-*+]\s+(.*)$/) : null;
          const contOl = kind === 'ol' ? lines[i].match(/^(\s*)\d+\.\s+(.*)$/) : null;
          if (cont) {
            items.push(cont[2]);
            i += 1;
          } else if (contOl) {
            items.push(contOl[2]);
            i += 1;
          } else if (lines[i].trim().length > 0 && !lines[i].trim().startsWith('```') && !lines[i].trim().startsWith('#')) {
            items[items.length - 1] += ' ' + lines[i].trim();
            i += 1;
          } else {
            break;
          }
        }
        blocks.push({ kind: kind, lines: items, level: Math.floor(indent / 2), ordered: kind === 'ol', lang: '' });
        continue;
      }
      if (trimmed.length === 0) {
        flushPara();
        i += 1;
        continue;
      }
      para.push(line);
      i += 1;
    }
    flushPara();
    return blocks;
  }

  /** 行内解析：`code`、**粗体**、*斜体*、[文本](链接)，其余按纯文本 */
  private parseInline(line: string): MdSpan[] {
    const spans: MdSpan[] = [];
    const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\([^)\s]+\))/;
    let rest = line;
    let guard = 0;
    while (rest.length > 0 && guard < 200) {
      guard += 1;
      const m = rest.match(pattern);
      if (!m || m.index === undefined) {
        spans.push({ text: rest, bold: false, italic: false, code: false, link: false });
        break;
      }
      if (m.index > 0) {
        spans.push({ text: rest.slice(0, m.index), bold: false, italic: false, code: false, link: false });
      }
      const tok = m[0];
      if (tok.startsWith('`')) {
        spans.push({ text: tok.slice(1, tok.length - 1), bold: false, italic: false, code: true, link: false });
      } else if (tok.startsWith('**')) {
        spans.push({ text: tok.slice(2, tok.length - 2), bold: true, italic: false, code: false, link: false });
      } else if (tok.startsWith('*')) {
        spans.push({ text: tok.slice(1, tok.length - 1), bold: false, italic: true, code: false, link: false });
      } else {
        const link = tok.match(/\[([^\]]+)\]\(([^)\s]+)\)/);
        spans.push({ text: link ? link[1] : tok, bold: false, italic: false, code: false, link: true });
      }
      rest = rest.slice(m.index + tok.length);
    }
    return spans;
  }

  /** 标题字号（h1 最大，h6 最小） */
  private headingSize(level: number): number {
    if (level <= 1) { return 20; }
    if (level === 2) { return 18; }
    if (level === 3) { return 16.5; }
    return 15;
  }

  /** 行内片段渲染（Text 的 Span 子节点） */
  @Builder
  renderSpans(spans: MdSpan[]) {
    ForEach(spans, (s: MdSpan) => {
      Span(s.text)
        .fontWeight(s.bold ? FontWeight.Bold : FontWeight.Normal)
        .fontStyle(s.italic ? FontStyle.Italic : FontStyle.Normal)
        .fontFamily(s.code ? 'monospace' : 'HarmonyOS Sans')
        .fontColor(s.code ? this.sm.getColor('primary') : (s.link ? this.sm.getColor('primary') : this.sm.getColor('text_primary')))
        .decoration({ type: s.link ? TextDecorationType.Underline : TextDecorationType.None })
    }, (s: MdSpan, idx: number) => idx.toString() + s.text)
  }

  build() {
    Column() {
      ForEach(this.parseBlocks(this.content), (b: MdBlock) => {
        if (b.kind === 'h') {
          Text(b.lines.length > 0 ? b.lines[0] : '')
            .fontSize(this.headingSize(b.level))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ top: 8, bottom: 4 })
        } else if (b.kind === 'code') {
          Column() {
            if (b.lang.length > 0) {
              Text(b.lang)
                .fontSize(10)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ bottom: 4 })
            }
            Text(b.lines.join('\n'))
              .fontFamily('monospace')
              .fontSize(12.5)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
          }
          .alignItems(HorizontalAlign.Start)
          .width('100%')
          .padding(10)
          .borderRadius(10)
          .backgroundColor('rgba(0,0,0,0.35)')
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ top: 6, bottom: 6 })
        } else if (b.kind === 'ul' || b.kind === 'ol') {
          Column() {
            ForEach(b.lines, (item: string, idx: number) => {
              Row() {
                Text(b.ordered ? (idx + 1).toString() + '.' : '•')
                  .fontSize(this.sm.getFontSize('body_sm'))
                  .fontColor(this.sm.getColor('primary'))
                  .margin({ right: 6 })
                Text() {
                  this.renderSpans(this.parseInline(item))
                }
                .fontSize(this.sm.getFontSize('body_sm'))
                .fontColor(this.sm.getColor('text_primary'))
                .layoutWeight(1)
              }
              .width('100%')
              .alignItems(VerticalAlign.Top)
              .margin({ left: b.level * 16, bottom: 3 })
            }, (item: string, idx: number) => idx.toString() + item)
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: 4, bottom: 4 })
        } else if (b.kind === 'quote') {
          Row() {
            Column()
              .width(3)
              .height('100%')
              .borderRadius(2)
              .backgroundColor(this.sm.getColor('primary'))
            Text() {
              this.renderSpans(this.parseInline(b.lines.join('\n')))
            }
            .fontSize(this.sm.getFontSize('body_sm'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 8 })
            .layoutWeight(1)
          }
          .width('100%')
          .alignItems(VerticalAlign.Top)
          .padding({ left: 8, right: 8, top: 6, bottom: 6 })
          .margin({ top: 4, bottom: 4 })
        } else if (b.kind === 'hr') {
          Divider()
            .color(this.sm.getColor('border'))
            .margin({ top: 8, bottom: 8 })
        } else if (b.kind === 'table') {
          Column() {
            ForEach(b.lines, (row: string, idx: number) => {
              Text(row.replace(/^\|/, '').replace(/\|$/, '').split('|').join('  |  '))
                .fontFamily('monospace')
                .fontSize(12)
                .fontColor(idx === 0 ? this.sm.getColor('text_secondary') : this.sm.getColor('text_primary'))
                .width('100%')
                .padding({ top: 2, bottom: 2 })
            }, (row: string, idx: number) => idx.toString() + row)
          }
          .width('100%')
          .padding(8)
          .borderRadius(8)
          .backgroundColor('rgba(0,0,0,0.25)')
          .margin({ top: 6, bottom: 6 })
        } else {
          Text() {
            this.renderSpans(this.parseInline(b.lines.join('\n')))
          }
          .fontSize(this.sm.getFontSize('body_sm'))
          .fontColor(this.sm.getColor('text_primary'))
          .width('100%')
        }
      }, (b: MdBlock) => b.kind + b.level.toString() + b.lines.join('\u0001'))
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
  }
}
