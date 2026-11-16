/**
 * KnowledgePage - 知识库页（对照原型 F9 + 三库分类需求）
 *
 * 职责：知识条目的三库分类展示（私有库/公共库/共享库）、搜索、
 *       私有条目「提交公共库」「共享给他人（按用户名）」、删除、查看详情
 * 数据：GET /knowledge?scope=...（三库分类，同源 PC）、
 *       POST /knowledge/search、POST /{id}/submit-public、POST /{id}/share
 * 设计：Column [内联头(标题+图谱/数据源/导入)] + [搜索栏] + [库分类筛选] +
 *       [加载态/空态/列表]；条目卡为玻璃卡（可见性徽章 + 属主 + 共享对象）。
 *
 * 门控：私有条目的共享/提交公共库操作仅条目属主可执行（后端 403 兜底）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router, RouteNames } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { KnowledgeItem, KnowledgeStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'KnowledgePage';

/** 库分类筛选：value 为后端 scope 参数 */
interface ScopeFilterOption {
  value: string;
  label: string;
}

/** 库分类筛选列表（顺序即展示顺序：私有 / 公共 / 共享） */
const SCOPE_FILTERS: ScopeFilterOption[] = [
  { value: 'private', label: '私有库' },
  { value: 'public', label: '公共库' },
  { value: 'shared', label: '共享库' },
];

/**
 * KnowledgeViewHelper - 展示纯函数集合（状态色映射 / 文件大小格式化）
 */
export class KnowledgeViewHelper {
  static getStatusColor(status: KnowledgeStatus): string {
    if (status === 'ready') {
      return 'success';
    }
    if (status === 'indexing') {
      return 'info';
    }
    if (status === 'error') {
      return 'error';
    }
    if (status === 'pending') {
      return 'warning';
    }
    return 'text_disabled';
  }

  static formatFileSize(bytes?: number): string {
    if (bytes === undefined || bytes === 0) {
      return '—';
    }
    const KB = 1024;
    const MB = KB * 1024;
    if (bytes >= MB) {
      return (bytes / MB).toFixed(1) + ' MB';
    }
    if (bytes >= KB) {
      return (bytes / KB).toFixed(1) + ' KB';
    }
    return bytes + ' B';
  }
}

@Component
export struct KnowledgePage {
  // 知识列表（由 API 加载，驱动列表渲染；scope 由后端过滤）
  @State knowledgeList: KnowledgeItem[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键词（绑定 GlassInput，受控）
  @State keyword: string = '';
  // 当前库分类：private / public / shared
  @State scope: string = 'private';
  // 详情弹窗
  @State showDetail: boolean = false;
  @State detailItem: KnowledgeItem | null = null;
  // 共享弹层：目标条目 + 用户名输入（逗号分隔多个）
  @State shareTarget: KnowledgeItem | null = null;
  @State shareUsernames: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadKnowledge();
  }

  /** 加载当前库分类的知识列表 */
  private async loadKnowledge(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.knowledge.listScoped({
        scope: this.scope,
        page: 1,
        pageSize: 50,
      });
      if (res.code === 0 && res.data) {
        this.knowledgeList = res.data.items;
      } else {
        this.msg.error(res.message || '知识列表获取失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载失败', e as Error);
      this.msg.error('加载知识列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 搜索（同源 PC：POST /knowledge/search） */
  private async handleSearch(): Promise<void> {
    const kw = this.keyword.trim();
    if (kw.length === 0) {
      await this.loadKnowledge();
      return;
    }
    this.loading = true;
    try {
      this.knowledgeList = await this.api.knowledge.search(kw, 20);
    } catch (e) {
      this.logger.error(TAG, '搜索失败', e as Error);
      this.msg.error('搜索失败');
    } finally {
      this.loading = false;
    }
  }

  /** 导入/创建知识（进导入页） */
  private handleImport(): void {
    this.router.push(RouteNames.KNOWLEDGE_IMPORT);
  }

  /** 图谱速览 */
  private openGraph(): void {
    this.router.push(RouteNames.GRAPH_PREVIEW);
  }

  /** 企业数据源 */
  private openSources(): void {
    this.router.push(RouteNames.ENTERPRISE_SOURCES);
  }

  /** 切换库分类 */
  private switchScope(value: string): void {
    if (this.scope !== value) {
      this.scope = value;
      this.loadKnowledge();
    }
  }

  /** 当前登录用户名（共享操作输入校验提示用） */
  private currentUsername(): string {
    return '';
  }

  /** 提交公共库 */
  private async submitToPublic(item: KnowledgeItem): Promise<void> {
    try {
      await this.api.knowledge.submitPublic(item.id);
      this.msg.success('已提交公共库');
      this.loadKnowledge();
    } catch (e) {
      this.msg.error('提交失败：' + (e as Error).message);
    }
  }

  /** 共享给他人（按用户名，逗号分隔多个） */
  private async shareTo(item: KnowledgeItem, usernames: string[]): Promise<void> {
    if (usernames.length === 0) {
      this.msg.warning('请填写对方用户名');
      return;
    }
    try {
      await this.api.knowledge.share(item.id, usernames);
      this.msg.success('已共享给 ' + usernames.join('、'));
      this.shareTarget = null;
      this.loadKnowledge();
    } catch (e) {
      this.msg.error('共享失败：' + (e as Error).message);
    }
  }

  private async removeItem(item: KnowledgeItem): Promise<void> {
    try {
      await this.api.knowledge.remove(item.id);
      this.msg.success('已删除');
      this.loadKnowledge();
    } catch (e) {
      this.msg.error('删除失败：' + (e as Error).message);
    }
  }

  private confirmDelete(item: KnowledgeItem): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除"${item.title}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      buttons: [
        { value: '取消', action: () => {} },
        {
          value: '删除',
          fontColor: this.sm.getColor('error'),
          action: () => {
            this.removeItem(item);
          }
        }
      ]
    });
  }

  /** 可见性徽章文案 */
  private visibilityLabel(item: KnowledgeItem): string {
    if (item.visibility === 'public') {
      return '公共';
    }
    if (item.visibility === 'shared') {
      return '共享';
    }
    return '私有';
  }

  build() {
    Column() {
      // 内联头（原型 F9：21/700 标题 + 图谱/数据源/导入）
      Row() {
        Text('知识')
          .fontSize(21)
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
        Text('图谱')
          .fontSize(12)
          .fontColor(this.sm.getColor('primary'))
          .padding(8)
          .onClick(() => {
            this.router.push(RouteNames.GRAPH_PREVIEW);
          })
        Text('数据源')
          .fontSize(12)
          .fontColor(this.sm.getColor('primary'))
          .padding(8)
          .onClick(() => {
            this.router.push(RouteNames.ENTERPRISE_SOURCES);
          })
        Button() {
          Text('＋ 导入')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_on_primary'))
        }
        .height(34)
        .linearGradient({ angle: 135, colors: [[this.sm.getColor('secondary'), 0], [this.sm.getColor('primary'), 1]] })
        .margin({ left: 4 })
        .onClick(() => {
          this.handleImport();
        })
      }
      .width('100%')
      .padding({ left: 20, right: 20, top: 8, bottom: 10 })

      // 搜索栏
      Row() {
        TextInput({ placeholder: '搜索知识…', text: this.keyword })
          .onChange((v: string) => {
            this.keyword = v;
          })
          .height(42)
          .layoutWeight(1)
          .borderRadius(12)
          .backgroundColor(this.sm.getColor('surface_strong'))
        Button('搜索')
          .height(42)
          .fontSize(13)
          .backgroundColor(this.sm.getColor('primary'))
          .fontColor(this.sm.getColor('text_on_primary'))
          .margin({ left: 8 })
          .onClick(() => {
            this.handleSearch();
          })
      }
      .width('100%')
      .padding({ left: 20, right: 20, bottom: 10 })

      // 库分类筛选：私有库 / 公共库 / 共享库
      Row() {
        ForEach(SCOPE_FILTERS, (opt: ScopeFilterOption) => {
          Text(opt.label)
            .fontSize(13)
            .fontColor(this.scope === opt.value
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_secondary'))
            .backgroundColor(this.scope === opt.value
              ? this.sm.getColor('primary_soft')
              : this.sm.getColor('surface'))
            .border({
              width: 1,
              color: this.scope === opt.value ? this.sm.getColor('primary') : this.sm.getColor('border')
            })
            .padding({ left: 14, right: 14, top: 6, bottom: 6 })
            .borderRadius(999)
            .margin({ right: 8 })
            .onClick(() => {
              this.switchScope(opt.value);
            })
        }, (opt: ScopeFilterOption) => opt.value)
        Blank()
      }
      .width('100%')
      .padding({ left: 20, right: 20, bottom: 10 })

      // 主体：加载态 / 空态 / 列表
      if (this.loading) {
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.knowledgeList.length === 0) {
        Column() {
          Text('暂无知识')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text(this.scope === 'shared' ? '他人共享的知识会出现在这里' : '点右上角「＋ 导入」添加')
            .fontSize(12)
            .fontColor(this.sm.getColor('text_tertiary'))
            .margin({ top: 6 })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.knowledgeList, (item: KnowledgeItem) => {
            ListItem() {
              this.buildKnowledgeCard(item)
            }
          }, (item: KnowledgeItem) => item.id + item.updatedAt)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
      }

      // 详情弹窗
      if (this.showDetail && this.detailItem) {
        this.buildDetailDialog(this.detailItem)
      }

      // 共享弹层
      if (this.shareTarget) {
        this.buildShareDialog(this.shareTarget)
      }
    }
    .width('100%')
    .height('100%')
  }

  /** 单个知识卡片：可见性徽章 + 属主 + 标题 + 摘要 + 来源/时间 + 操作 */
  @Builder
  buildKnowledgeCard(item: KnowledgeItem) {
    Column() {
      GlassCard() {
        Column() {
          // 首行：可见性徽章 + 属主
          Row() {
            Text(this.visibilityLabel(item))
              .fontSize(9)
              .fontColor(this.sm.getColor('primary'))
              .padding({ left: 6, right: 6, top: 1, bottom: 1 })
              .borderRadius(5)
              .border({ width: 1, color: this.sm.getColor('primary') })
            if (item.ownerUserId !== undefined && item.ownerUserId.length > 0) {
              Text('属主 ' + item.ownerUserId)
                .fontSize(9)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ left: 6 })
            }
            Blank()
            if (item.sharedWith !== undefined && item.sharedWith.length > 0) {
              Text('已共享给 ' + item.sharedWith.join('、'))
                .fontSize(9)
                .fontColor(this.sm.getColor('text_tertiary'))
                .maxLines(1)
            }
          }
          .width('100%')

          // 标题
          Text(item.title)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 8 })

          // 摘要
          Text(item.summary !== undefined && item.summary.length > 0 ? item.summary : '暂无摘要')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })

          // 底部行：来源 · 分类 · 时间
          Row() {
            Text(item.source.length > 0 ? item.source : 'manual')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text('·')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ left: 6, right: 6 })
            Text(item.category !== undefined && item.category.length > 0 ? item.category : '未分类')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Blank()
            Text(item.updatedAt.length >= 10 ? item.updatedAt.slice(0, 10) : item.updatedAt)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
          }
          .width('100%')
          .margin({ top: 8 })

          // 操作行：详情 + 删除；私有条目追加 提交公共库 / 共享
          Row() {
            if (item.visibility === 'private') {
              GlassButton({
                text: '提交公共库',
                type: 'default',
                btnSize: 'small',
                onTap: () => {
                  this.submitToPublic(item);
                }
              })
              GlassButton({
                text: '共享',
                type: 'default',
                btnSize: 'small',
                onTap: () => {
                  this.shareTarget = item;
                  this.shareUsernames = '';
                }
              })
                .margin({ left: this.sm.getSpacing('sm') })
            }
            Blank()
            GlassButton({
              text: '详情',
              type: 'default',
              btnSize: 'small',
              onTap: () => { this.openDetail(item); }
            })
            GlassButton({
              text: '删除',
              type: 'danger',
              btnSize: 'small',
              onTap: () => { this.confirmDelete(item); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
    }
    .width('100%')
  }

  /** 共享弹层：输入对方用户名（多个用逗号分隔） */
  @Builder
  buildShareDialog(item: KnowledgeItem) {
    Stack({ alignContent: Alignment.Center }) {
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => {
          this.shareTarget = null;
        })

      Column() {
        Text('共享「' + item.title + '」')
          .fontSize(16)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
        Text('对方凭用户名获得该条目的访问权；多个用户名用逗号分隔')
          .fontSize(11.5)
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 8 })
        TextInput({ placeholder: '对方用户名（逗号分隔）', text: this.shareUsernames })
          .onChange((v: string) => {
            this.shareUsernames = v;
          })
          .height(44)
          .borderRadius(12)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .margin({ top: 14 })
        Row() {
          Button('取消')
            .layoutWeight(1)
            .height(40)
            .backgroundColor(this.sm.getColor('surface_strong'))
            .fontColor(this.sm.getColor('text_secondary'))
            .onClick(() => {
              this.shareTarget = null;
            })
          Button('确认共享')
            .layoutWeight(1)
            .height(40)
            .backgroundColor(this.sm.getColor('primary'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .margin({ left: 10 })
            .onClick(() => {
              const names = this.shareUsernames
                .split(/[,，]/)
                .map((s: string) => s.trim())
                .filter((s: string) => s.length > 0);
              this.shareTo(item, names);
            })
        }
        .width('100%')
        .margin({ top: 16 })
      }
      .width('84%')
      .padding(20)
      .borderRadius(18)
      .backgroundColor(this.sm.getColor('surface'))
      .border({ width: 1, color: this.sm.getColor('border') })
    }
    .width('100%')
    .height('100%')
  }

  /** 打开详情弹窗 */
  private openDetail(item: KnowledgeItem): void {
    this.detailItem = item;
    this.showDetail = true;
  }

  private closeDetail(): void {
    this.showDetail = false;
  }

  private formatTime(ts: number): string {
    if (ts <= 0) {
      return '—';
    }
    const d = new Date(ts);
    return d.toISOString().slice(0, 10);
  }

  // ===========================================================================
  // 详情弹窗构建器
  // ===========================================================================

  /** 详情弹窗：完整 content + 元数据 */
  @Builder
  buildDetailDialog(item: KnowledgeItem) {
    Stack({ alignContent: Alignment.Center }) {
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      Column() {
        GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
          Column() {
            Text(item.title)
              .fontSize(this.sm.getFontSize('title'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')

            Row() {
              Text(this.visibilityLabel(item))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor(KnowledgeViewHelper.getStatusColor(item.status)))
              Text(`${KnowledgeViewHelper.formatFileSize(item.fileSize)}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 12 })
            }
            .width('100%')
            .margin({ top: 8 })

            Column() {
              Text(`分类: ${item.category ?? '未分类'}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
              Text(`标签: ${item.tags && item.tags.length > 0 ? item.tags.join(', ') : '无'}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 4 })
              Text(`字数: ${item.wordCount ?? 0}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 4 })
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .margin({ top: 8 })

            Scroll() {
              Text(item.content)
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_primary'))
            }
            .layoutWeight(1)
            .width('100%')
            .margin({ top: 12 })
            .scrollBar(BarState.Off)

            GlassButton({
              text: '关闭',
              type: 'primary',
              btnSize: 'medium',
              block: true,
              onTap: () => { this.closeDetail(); }
            })
              .margin({ top: 12 })
          }
          .width('100%')
          .height('100%')
          .alignItems(HorizontalAlign.Start)
        }
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }
}
