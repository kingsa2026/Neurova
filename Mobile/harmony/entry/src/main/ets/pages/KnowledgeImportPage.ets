/**
 * KnowledgeImportPage - 知识导入页（对照原型 F12）
 *
 * 两种来源（PC KnowledgePage 同源端点）：
 *   URL 导入  POST /knowledge/import-url?url=&agent_id=&sync=true（SSRF 防护在服务端）
 *   手动创建  POST /knowledge（KnowledgeCreate：title/content/category/tags/source）
 * 文件导入（POST /knowledge/import，multipart）待 HttpClient 上传能力后补——
 * 本页暂只提供 URL 与手动两种形态（诚实降级，不画假按钮）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';

@Component
export struct KnowledgeImportPage {
  @State private url: string = '';
  @State private title: string = '';
  @State private content: string = '';
  @State private category: string = 'general';
  @State private busy: boolean = false;
  /** 来源分段：0=URL 导入 / 1=手动创建 */
  @State private mode: number = 0;
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  private async submitUrl(): Promise<void> {
    if (this.url.trim().length === 0) {
      this.msg.warning('请输入网页链接');
      return;
    }
    this.busy = true;
    try {
      const res = await this.api.knowledge.importUrl(this.url.trim(), this.agentsStore.currentAgentId || undefined, this.category);
      if (res.code === 0) {
        this.msg.success('导入成功，已解析为知识条目');
        this.router.back();
      } else {
        this.msg.error(res.message || '导入失败');
      }
    } catch (e) {
      this.msg.error('导入失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  private async submitManual(): Promise<void> {
    if (this.title.trim().length === 0 || this.content.trim().length === 0) {
      this.msg.warning('标题与内容不能为空');
      return;
    }
    this.busy = true;
    try {
      const body: Record<string, Object> = {
        'title': this.title.trim(),
        'content': this.content.trim(),
        'category': this.category,
        'tags': [],
        'source': 'mobile-manual',
        'visibility': 'private',
      };
      const res = await this.api.knowledge.create(body);
      if (res.code === 0) {
        this.msg.success('已创建知识条目');
        this.router.back();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.msg.error('创建失败：' + (e as Error).message);
    }
    this.busy = false;
  }

  build() {
    Column() {
      Row() {
        Text('‹')
          .fontSize(22)
          .fontColor(this.sm.getColor('text_secondary'))
          .padding(8)
          .onClick(() => {
            this.router.back();
          })
        Text('导入知识')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Blank()
          .width(38)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          // 来源分段
          Row() {
            Text('网页链接')
              .fontSize(13)
              .padding({ left: 14, right: 14, top: 7, bottom: 7 })
              .borderRadius(999)
              .fontColor(this.mode === 0 ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .backgroundColor(this.mode === 0 ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
              .border({ width: 1, color: this.mode === 0 ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .onClick(() => {
                this.mode = 0;
              })
            Text('手动创建')
              .fontSize(13)
              .padding({ left: 14, right: 14, top: 7, bottom: 7 })
              .borderRadius(999)
              .fontColor(this.mode === 1 ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .backgroundColor(this.mode === 1 ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
              .border({ width: 1, color: this.mode === 1 ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ left: 8 })
              .onClick(() => {
                this.mode = 1;
              })
            Blank()
          }
          .width('100%')
          .padding({ left: 20, right: 20, bottom: 12 })

          if (this.mode === 0) {
            // URL 导入
            Column() {
              Text('把网页正文抽取为知识条目（服务端 SSRF 防护）')
                .fontSize(11.5)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ bottom: 10 })
              TextInput({ placeholder: 'https://example.com/article' })
                .onChange((v: string) => {
                  this.url = v;
                })
                .height(44)
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('surface_strong'))
              TextInput({ text: this.category, placeholder: '分类（默认 general）' })
                .onChange((v: string) => {
                  this.category = v;
                })
                .height(44)
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .margin({ top: 10 })
            }
            .width('100%')
            .padding({ left: 20, right: 20 })
          } else {
            // 手动创建
            Column() {
              TextInput({ placeholder: '标题' })
                .onChange((v: string) => {
                  this.title = v;
                })
                .height(44)
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('surface_strong'))
              TextArea({ placeholder: '正文内容…', text: this.content })
                .onChange((v: string) => {
                  this.content = v;
                })
                .height(150)
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .margin({ top: 10 })
              TextInput({ text: this.category, placeholder: '分类（默认 general）' })
                .onChange((v: string) => {
                  this.category = v;
                })
                .height(44)
                .borderRadius(12)
                .backgroundColor(this.sm.getColor('surface_strong'))
                .margin({ top: 10 })
            }
            .width('100%')
            .padding({ left: 20, right: 20 })
          }

          Button() {
            Text(this.busy ? '处理中…' : (this.mode === 0 ? '导入并解析' : '创建知识条目'))
              .fontSize(15)
              .fontColor(this.sm.getColor('text_on_primary'))
          }
          .width('calc(100% - 40vp)')
          .height(46)
          .borderRadius(14)
          .backgroundColor(this.sm.getColor('primary'))
          .enabled(!this.busy)
          .margin({ top: 22 })
          .onClick(() => {
            if (this.mode === 0) {
              this.submitUrl();
            } else {
              this.submitManual();
            }
          })

          Text('文件导入（PDF/DOCX/MD）待客户端上传能力后开放')
            .fontSize(11)
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ top: 14 })
        }
        .width('100%')
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
