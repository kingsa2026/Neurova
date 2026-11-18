/**
 * KnowledgeImportPage - 知识导入页（严格按设计稿 F12 还原）
 *
 * 两种来源（与 PC KnowledgePage 同源端点）：
 *   本地文档  POST /knowledge/import（multipart file + query：agent_id/sync/ocr/engine/category）
 *            —— 文件经 DocumentViewPicker 选取，HttpClient.postMultipart 直传；
 *   网页链接  POST /knowledge/import-url?url=&agent_id=&sync=true&category=（SSRF 防护在服务端）
 * 选项行：归属分类（category）/ 分块策略（engine：structured=语义分块、legacy=单段抽取）/
 *         OCR 识别扫描件（ocr：关=auto 仅无文字层页、开=on 强制）——均为后端真实参数。
 * 导入完成后返回知识列表（分块预览留在条目详情/PC）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';
import { GlassInput } from '../components/glass';
import picker from '@ohos.file.picker';
import fs from '@ohos.file.fs';

@Component
export struct KnowledgeImportPage {
  /** 来源分段：0=本地文档 / 1=网页链接（设计 F12 .seg） */
  @State private mode: number = 0;
  // 已选文件（本地文档）
  @State private hasFile: boolean = false;
  @State private fileName: string = '';
  @State private fileSizeLabel: string = '';
  private fileBytes: ArrayBuffer = new ArrayBuffer(0);
  // 表单
  @State private url: string = '';
  @State private category: string = '';
  /** 分块策略：0=语义分块（engine=structured）/ 1=单段抽取（engine=legacy） */
  @State private engineMode: number = 0;
  /** OCR 识别扫描件：关=auto（仅无文字层页）/ 开=on（强制） */
  @State private ocrOn: boolean = false;
  @State private busy: boolean = false;
  // 分类选择弹层
  @State private categoryEditing: boolean = false;
  @State private categoryDraft: string = '';
  // 分块策略弹层
  @State private enginePicking: boolean = false;
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  /** 选取本地文档（DocumentViewPicker，单选） */
  private async pickFile(): Promise<void> {
    try {
      const docPicker = new picker.DocumentViewPicker();
      const opts = new picker.DocumentSelectOptions();
      opts.maxSelectNumber = 1;
      const uris: string[] = await docPicker.select(opts);
      if (!uris || uris.length === 0) {
        return;
      }
      const uri = uris[0];
      const file = fs.openSync(uri, fs.OpenMode.READ_ONLY);
      const stat = fs.statSync(file.fd);
      const buf = new ArrayBuffer(stat.size);
      fs.readSync(file.fd, buf);
      fs.closeSync(file);
      const segs = uri.split('/');
      const rawName = decodeURIComponent(segs[segs.length - 1] || 'imported');
      this.fileName = rawName;
      this.fileSizeLabel = this.formatSize(stat.size);
      this.fileBytes = buf;
      this.hasFile = true;
    } catch (e) {
      this.msg.error('读取文件失败：' + (e as Error).message);
    }
  }

  private formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) {
      return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }
    if (bytes >= 1024) {
      return (bytes / 1024).toFixed(0) + ' KB';
    }
    return bytes.toString() + ' B';
  }

  private mimeOf(name: string): string {
    const lower = name.toLowerCase();
    if (lower.endsWith('.pdf')) {
      return 'application/pdf';
    }
    if (lower.endsWith('.docx')) {
      return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    }
    if (lower.endsWith('.md') || lower.endsWith('.txt') || lower.endsWith('.csv')) {
      return 'text/plain';
    }
    return 'application/octet-stream';
  }

  private engineLabel(): string {
    return this.engineMode === 0 ? '语义分块' : '单段抽取';
  }

  private engineParam(): string {
    return this.engineMode === 0 ? 'structured' : 'legacy';
  }

  private ocrParam(): string {
    return this.ocrOn ? 'on' : 'auto';
  }

  /** 本地文档导入（multipart → /knowledge/import） */
  private async submitLocal(): Promise<void> {
    if (!this.hasFile) {
      this.msg.warning('请先选择要导入的文档');
      return;
    }
    this.busy = true;
    try {
      const res = await this.api.knowledge.importFile(
        this.fileName, this.fileBytes, this.mimeOf(this.fileName),
        this.agentsStore.currentAgentId || undefined,
        this.category.trim().length > 0 ? this.category.trim() : undefined,
        this.ocrParam(), this.engineParam(),
      );
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

  /** 网页链接导入（/knowledge/import-url） */
  private async submitUrl(): Promise<void> {
    if (this.url.trim().length === 0) {
      this.msg.warning('请输入网页链接');
      return;
    }
    this.busy = true;
    try {
      const res = await this.api.knowledge.importUrl(
        this.url.trim(),
        this.agentsStore.currentAgentId || undefined,
        this.category.trim().length > 0 ? this.category.trim() : undefined,
      );
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

  build() {
    Column() {
      // 头部（设计 .phead：返回 + 导入知识）
      Row() {
        IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
        Text('导入知识')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Blank()
          .width(36)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          // 来源分段（设计 .seg：本地文档 / 网页链接）
          Row() {
            Text('本地文档')
              .fontSize(12)
              .padding({ left: 14, right: 14, top: 6, bottom: 6 })
              .borderRadius(999)
              .fontColor(this.mode === 0 ? '#FFFFFF' : this.sm.getColor('text_secondary'))
              .backgroundColor(this.mode === 0 ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.mode === 0 ? 'rgba(99,102,241,0.50)' : this.sm.getColor('border') })
              .onClick(() => { this.mode = 0; })
            Text('网页链接')
              .fontSize(12)
              .padding({ left: 14, right: 14, top: 6, bottom: 6 })
              .borderRadius(999)
              .fontColor(this.mode === 1 ? '#FFFFFF' : this.sm.getColor('text_secondary'))
              .backgroundColor(this.mode === 1 ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.mode === 1 ? 'rgba(99,102,241,0.50)' : this.sm.getColor('border') })
              .margin({ left: 6 })
              .onClick(() => { this.mode = 1; })
            Blank()
          }
          .width('100%')
          .padding({ left: 20, right: 20, bottom: 12 })

          if (this.mode === 0) {
            // 拖放选文区（设计 .drop：虚线框 + 图标 + 说明）
            Column() {
              AppIcon({ name: 'folder', iconSize: 28, color: this.sm.getColor('secondary') })
              Text('选择要导入的文档')
                .fontSize(13.5)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ top: 8 })
              Text('支持 PDF / DOCX / Markdown / TXT\n自动分块、OCR 扫描件识别')
                .fontSize(11)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 6 })
                .textAlign(TextAlign.Center)
            }
            .width('calc(100% - 40vp)')
            .padding({ top: 24, bottom: 24, left: 16, right: 16 })
            .borderRadius(16)
            .border({ width: 1.5, color: 'rgba(139,92,246,0.45)', style: BorderStyle.Dashed })
            .backgroundColor('rgba(139,92,246,0.05)')
            .margin({ left: 20, right: 20, bottom: 12 })
            .onClick(() => { this.pickFile(); })

            // 已选文件chip（设计 .filechip：图标 + 文件名/大小 + 进度）
            if (this.hasFile) {
              Row() {
                Column() {
                  AppIcon({ name: 'folder', iconSize: 16, color: this.sm.getColor('accent') })
                }
                .width(34)
                .height(34)
                .borderRadius(10)
                .backgroundColor('rgba(34,211,238,0.12)')
                .border({ width: 1, color: 'rgba(34,211,238,0.30)' })
                .justifyContent(FlexAlign.Center)
                .alignItems(HorizontalAlign.Center)

                Column() {
                  Text(this.fileName)
                    .fontSize(12.5)
                    .fontWeight(FontWeight.Medium)
                    .fontColor(this.sm.getColor('text_primary'))
                    .maxLines(1)
                    .textOverflow({ overflow: TextOverflow.Ellipsis })
                  Row() {
                    Text(this.fileSizeLabel + (this.busy ? ' · 解析中…' : ''))
                      .fontSize(10.5)
                      .fontColor(this.sm.getColor('text_tertiary'))
                    if (this.busy) {
                      LoadingProgress()
                        .width(12)
                        .height(12)
                        .color(this.sm.getColor('primary'))
                        .margin({ left: 6 })
                    }
                  }
                  .margin({ top: 3 })
                  .alignItems(VerticalAlign.Center)
                }
                .alignItems(HorizontalAlign.Start)
                .layoutWeight(1)
                .margin({ left: 10 })
              }
              .width('calc(100% - 40vp)')
              .padding({ left: 14, right: 14, top: 11, bottom: 11 })
              .borderRadius(13)
              .backgroundColor(this.sm.getColor('surface_strong'))
              .border({ width: 1, color: this.sm.getColor('border') })
              .margin({ left: 20, right: 20, bottom: 12 })
              .alignItems(VerticalAlign.Center)
            }
          } else {
            // 网页链接（设计 F12 第二来源）
            Column() {
              GlassInput({
                placeholder: 'https://example.com/article',
                value: this.url,
                onChange: (v: string) => { this.url = v; }
              })
            }
            .width('100%')
            .padding({ left: 20, right: 20, bottom: 12 })
          }

          // 选项行：归属分类（设计 .kopt）
          Row() {
            AppIcon({ name: 'book', iconSize: 14, color: this.sm.getColor('secondary') })
            Text('归属分类')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 12 })
            Blank()
            Text(this.category.trim().length > 0 ? this.category : '默认')
              .fontSize(12.5)
              .fontColor(this.sm.getColor('text_secondary'))
            AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
              .margin({ left: 4 })
          }
          .width('calc(100% - 40vp)')
          .padding({ left: 15, right: 15, top: 12, bottom: 12 })
          .borderRadius(13)
          .backgroundColor(this.sm.getColor('glass'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20, bottom: 9 })
          .alignItems(VerticalAlign.Center)
          .onClick(() => {
            this.categoryDraft = this.category;
            this.categoryEditing = true;
          })

          // 选项行：分块策略（engine：语义分块/单段抽取，真实传参）
          if (this.mode === 0) {
            Row() {
              AppIcon({ name: 'task', iconSize: 14, color: this.sm.getColor('secondary') })
              Text('分块策略')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 12 })
              Blank()
              Text(this.engineLabel())
                .fontSize(12.5)
                .fontColor(this.sm.getColor('text_secondary'))
              AppIcon({ name: 'chev', iconSize: 12, color: this.sm.getColor('text_tertiary') })
                .margin({ left: 4 })
            }
            .width('calc(100% - 40vp)')
            .padding({ left: 15, right: 15, top: 12, bottom: 12 })
            .borderRadius(13)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ left: 20, right: 20, bottom: 9 })
            .alignItems(VerticalAlign.Center)
            .onClick(() => { this.enginePicking = true; })

            // 选项行：OCR 识别扫描件（ocr 参数：关=auto / 开=on）
            Row() {
              AppIcon({ name: 'scan', iconSize: 14, color: this.sm.getColor('secondary') })
              Text('OCR 识别扫描件')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_primary'))
                .margin({ left: 12 })
                .layoutWeight(1)
              Toggle({ type: ToggleType.Switch, isOn: this.ocrOn })
                .selectedColor(this.sm.getColor('primary'))
                .onChange((on: boolean) => { this.ocrOn = on; })
            }
            .width('calc(100% - 40vp)')
            .padding({ left: 15, right: 15, top: 12, bottom: 12 })
            .borderRadius(13)
            .backgroundColor(this.sm.getColor('glass'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .margin({ left: 20, right: 20, bottom: 9 })
            .alignItems(VerticalAlign.Center)
          }

          // 主按钮（设计 .btn-pri：品牌渐变 + 加号 + 导入并解析）
          Column() {
            AppIcon({ name: 'plus', iconSize: 15, color: '#FFFFFF' })
            Text(this.busy ? '解析中…' : '导入并解析')
              .fontSize(15.5)
              .fontWeight(FontWeight.Medium)
              .fontColor('#FFFFFF')
              .margin({ left: 8 })
          }
          .width('calc(100% - 40vp)')
          .height(48)
          .borderRadius(14)
          .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
          .shadow({ radius: 24, color: 'rgba(99,102,241,0.40)', offsetY: 8 })
          .margin({ top: 16, left: 20, right: 20 })
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
          .opacity(this.busy ? 0.6 : 1)
          .onClick(() => {
            if (this.busy) {
              return;
            }
            if (this.mode === 0) {
              this.submitLocal();
            } else {
              this.submitUrl();
            }
          })
        }
        .width('100%')
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      .width('100%')

      // 归属分类编辑弹层
      if (this.categoryEditing) {
        Column() {
          Column() {
            Text('归属分类')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
            GlassInput({
              placeholder: '分类（留空=默认）',
              value: this.categoryDraft,
              onChange: (v: string) => { this.categoryDraft = v; }
            })
              .margin({ top: 12 })
            Row() {
              Text('取消')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_secondary'))
                .padding({ left: 14, right: 14, top: 8, bottom: 8 })
                .onClick(() => { this.categoryEditing = false; })
              Text('确定')
                .fontSize(13)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_on_primary'))
                .padding({ left: 16, right: 16, top: 8, bottom: 8 })
                .borderRadius(10)
                .linearGradient({ angle: 135, colors: this.sm.getBrandGradient() })
                .margin({ left: 8 })
                .onClick(() => {
                  this.category = this.categoryDraft;
                  this.categoryEditing = false;
                })
            }
            .width('100%')
            .justifyContent(FlexAlign.End)
            .margin({ top: 14 })
          }
          .width('82%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }

      // 分块策略选择弹层
      if (this.enginePicking) {
        Column() {
          Column() {
            Text('分块策略')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ bottom: 10 })
            Text('语义分块')
              .fontSize(13.5)
              .fontColor(this.engineMode === 0 ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .padding({ left: 14, right: 14, top: 9, bottom: 9 })
              .borderRadius(11)
              .backgroundColor(this.engineMode === 0 ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.engineMode === 0 ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ top: 4 })
              .onClick(() => {
                this.engineMode = 0;
                this.enginePicking = false;
              })
            Text('单段抽取')
              .fontSize(13.5)
              .fontColor(this.engineMode === 1 ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .padding({ left: 14, right: 14, top: 9, bottom: 9 })
              .borderRadius(11)
              .backgroundColor(this.engineMode === 1 ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.engineMode === 1 ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ top: 8 })
              .onClick(() => {
                this.engineMode = 1;
                this.enginePicking = false;
              })
          }
          .width('70%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Center)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
