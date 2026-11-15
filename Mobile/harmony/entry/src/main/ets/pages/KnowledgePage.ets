/**
 * KnowledgePage - 知识库页
 *
 * 职责：展示知识条目列表，支持搜索、按状态筛选、删除、查看详情
 * 设计：
 *   - Column [TopNavMenu(标题+返回+新建)] + [搜索栏] + [状态筛选 Tab] + [加载态/空态/列表]；
 *   - 列表项为 GlassCard，包含状态徽章、标题、摘要、来源、字数、创建时间、操作按钮；
 *   - 删除操作需二次确认（AlertDialog）；新建 M4 实现，当前提示"功能开发中"；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.knowledge，消息走 MessageManager。
 *
 * 视图模型层（KnowledgeViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getStatusColor 返回颜色 token 名（'success'/'info'/'error'/'warning'/'text_disabled'），
 *     由调用方通过 StyleManager.getColor(token) 解析为实际颜色，便于主题切换；
 *   - getSourceIcon 返回 emoji 字符串；
 *   - formatFileSize 将字节数格式化为人类可读字符串。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（knowledge 模块：list/remove/search）
 *   - ../routing/Router：统一路由跳转 + RouteNames（含 KNOWLEDGE）
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：KnowledgeItem、KnowledgeQuery、KnowledgeStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.KNOWLEDGE) 跳转进入；
 *   aboutToAppear 调用 api.knowledge.list({}) 加载列表；
 *   搜索调用 api.knowledge.search(keyword, undefined, 20)；
 *   删除经 AlertDialog 二次确认后调用 api.knowledge.remove(id) 并刷新列表；
 *   详情弹出 Dialog 展示完整 content 与元数据；
 *   新建提示"功能开发中"（M4 实现上传）。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { KnowledgeItem, KnowledgeStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'KnowledgePage';

/**
 * KnowledgeViewHelper - 知识库页视图模型纯函数集合
 *
 * 职责：封装状态颜色映射、来源图标映射、文件大小格式化等纯展示逻辑
 * 设计：全部为静态方法、无副作用、无 UI 依赖，可直接单元测试
 *
 * 用法：
 *   const colorToken = KnowledgeViewHelper.getStatusColor(item.status);
 *   const color = sm.getColor(colorToken);
 *   const icon = KnowledgeViewHelper.getSourceIcon(item.source);
 *   const sizeText = KnowledgeViewHelper.formatFileSize(item.fileSize);
 */
export class KnowledgeViewHelper {
  /**
   * 获取状态对应的颜色 token 名
   * 映射：ready→success / indexing→info / error→error / pending→warning / 未知→text_disabled
   * 返回 token 名（非颜色值），由调用方通过 StyleManager.getColor(token) 解析
   */
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

  /**
   * 获取来源对应的图标 emoji
   * 映射：upload→📷 / url→🔗 / manual→✍️ / 未知→📄
   */
  static getSourceIcon(source: string): string {
    if (source === 'upload') {
      return '📷';
    }
    if (source === 'url') {
      return '🔗';
    }
    if (source === 'manual') {
      return '✍️';
    }
    return '📄';
  }

  /**
   * 将字节数格式化为人类可读字符串
   * 规则：1024 → "1.0 KB"，1048576 → "1.0 MB"；0 或 undefined → "—"
   * 单位阶梯：B / KB / MB（按 1024 进制，保留 1 位小数）
   */
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

/** 状态筛选 Tab 配置：value 为 'all' 或 KnowledgeStatus，label 为展示文案 */
interface StatusFilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表（顺序即展示顺序） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'ready', label: '就绪' },
  { value: 'indexing', label: '索引中' },
  { value: 'error', label: '错误' },
  { value: 'pending', label: '待处理' },
];

@Component
export struct KnowledgePage {
  // 知识列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State knowledgeList: KnowledgeItem[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 搜索关键词（绑定 GlassInput，受控）
  @State keyword: string = '';
  // 当前激活的状态筛选值：'all' 或具体 KnowledgeStatus
  @State activeStatus: string = 'all';
  // 详情弹窗控制：showDetail 控制显隐，detailItem 持有当前查看的条目
  @State showDetail: boolean = false;
  @State detailItem: KnowledgeItem | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadKnowledge();
  }

  /**
   * 加载知识列表
   * 流程：调用 api.knowledge.list({}) → 写入 knowledgeList
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadKnowledge(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.knowledge.list({});
      if (res.code === 0 && res.data) {
        this.knowledgeList = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载失败', e as Error);
      this.msg.error('加载知识列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 执行搜索
   * 流程：关键词为空 → 重新加载全量列表；非空 → 调用 api.knowledge.search(keyword, undefined, 20)
   * 异常：记录日志并提示用户；搜索期间复用 loading 占位
   */
  private async handleSearch(): Promise<void> {
    this.loading = true;
    try {
      if (!this.keyword || this.keyword.trim().length === 0) {
        await this.loadKnowledge();
        return;
      }
      const res = await this.api.knowledge.search(this.keyword.trim(), undefined, 20);
      if (res.code === 0 && res.data) {
        // search 返回 KnowledgeItem[]（非分页），直接赋值
        this.knowledgeList = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '搜索失败', e as Error);
      this.msg.error('搜索失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 Tab（本地过滤，无需重新请求后端） */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredList(): KnowledgeItem[] {
    if (this.activeStatus === 'all') {
      return this.knowledgeList;
    }
    return this.knowledgeList.filter((item: KnowledgeItem) => item.status === this.activeStatus);
  }

  /**
   * 新建知识（M4 实现上传，当前提示"功能开发中"）
   */
  private handleCreate(): void {
    this.msg.info('功能开发中');
  }

  /**
   * 打开详情弹窗
   */
  private openDetail(item: KnowledgeItem): void {
    this.detailItem = item;
    this.showDetail = true;
  }

  /**
   * 关闭详情弹窗
   */
  private closeDetail(): void {
    this.showDetail = false;
    this.detailItem = null;
  }

  /**
   * 删除前二次确认
   * 使用 AlertDialog 弹窗，避免误删；确认后调用 deleteKnowledge
   */
  private confirmDelete(item: KnowledgeItem): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除知识"${item.title}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteKnowledge(item.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.knowledge.remove(id) → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteKnowledge(knowledgeId: string): Promise<void> {
    try {
      const res = await this.api.knowledge.remove(knowledgeId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadKnowledge();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除失败', e as Error);
      this.msg.error('删除知识失败');
    }
  }

  /** 格式化创建时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(timeStr?: string): string {
    if (!timeStr) return '未知';
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"知识库" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '知识库',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.handleCreate(); }
          })
        }

        // 搜索栏：GlassInput 关键词 + 搜索按钮
        Row() {
          GlassInput({
            placeholder: '搜索知识...',
            value: this.keyword,
            type: 'text',
            onChange: (v: string) => { this.keyword = v; },
            onSubmit: () => { this.handleSearch(); }
          })
          GlassButton({
            text: '搜索',
            type: 'primary',
            size: 'small',
            onClick: () => { this.handleSearch(); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .padding({
          left: this.sm.getSpacing('md'),
          right: this.sm.getSpacing('md'),
          top: this.sm.getSpacing('sm'),
          bottom: this.sm.getSpacing('sm'),
        })
        .alignItems(VerticalAlign.Center)

        // 状态筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(STATUS_FILTERS, (opt: StatusFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeStatus === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeStatus === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchStatus(opt.value); })
            }, (opt: StatusFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 主体内容：加载态 / 空态 / 列表 三选一
        if (this.loading) {
          // 加载态：居中显示"加载中..."
          Column() {
            Text('加载中...')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.getFilteredList().length === 0) {
          // 空态：居中显示"暂无知识"
          Column() {
            Text('暂无知识')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 知识列表：纵向滚动，卡片间距 12，关闭滚动条
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (item: KnowledgeItem) => {
              ListItem() {
                this.buildKnowledgeCard(item)
              }
            }, (item: KnowledgeItem) => item.id)
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
      }
      .width('100%')
      .height('100%')
      .backgroundColor(this.sm.getColor('background'))

      // 详情弹窗：showDetail 为 true 时覆盖在主体之上
      if (this.showDetail && this.detailItem) {
        this.buildDetailDialog(this.detailItem)
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 知识卡片构建器
  // ===========================================================================

  /** 单个知识卡片：状态徽章 + 标题 + 摘要 + 底部行（来源/字数/时间）+ 操作按钮 */
  @Builder
  buildKnowledgeCard(item: KnowledgeItem) {
    GlassCard() {
      Column() {
        // 状态徽章：圆点 + 状态文案（颜色经视图模型映射）
        Row() {
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(KnowledgeViewHelper.getStatusColor(item.status)))
          Text(item.status)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(KnowledgeViewHelper.getStatusColor(item.status)))
            .margin({ left: 4 })
        }
        .alignItems(VerticalAlign.Center)

        // 标题（最多 2 行）
        Text(item.title)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 摘要（最多 2 行，空值回退"暂无摘要"）
        Text(item.summary ?? '暂无摘要')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 底部行：来源图标+文案 · 字数 · 创建时间
        Row() {
          Text(`${KnowledgeViewHelper.getSourceIcon(item.source)} ${item.source}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`${item.wordCount ?? 0} 字`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(this.formatTime(item.createdAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：详情、删除（右对齐）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetail(item); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(item); }
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
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器
  // ===========================================================================

  /** 详情弹窗：完整 content + 元数据（category、tags、fileSize、wordCount） */
  @Builder
  buildDetailDialog(item: KnowledgeItem) {
    // Stack 分层：背景层（半透明遮罩，点击关闭）+ 面板层（居中，不触发关闭）
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层：居中展示，覆盖在背景层之上（点击面板内部不关闭）
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题行
          Text(item.title)
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 状态 + 来源
          Row() {
            Text(`状态: ${item.status}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(KnowledgeViewHelper.getStatusColor(item.status)))
            Text(`${KnowledgeViewHelper.getSourceIcon(item.source)} ${item.source}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ left: 12 })
          }
          .width('100%')
          .margin({ top: 8 })
          .alignItems(VerticalAlign.Center)

          // 元数据：分类、标签、文件大小、字数
          Column() {
            Text(`分类: ${item.category ?? '未分类'}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(`标签: ${item.tags && item.tags.length > 0 ? item.tags.join(', ') : '无'}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 4 })
            Text(`文件大小: ${KnowledgeViewHelper.formatFileSize(item.fileSize)}`)
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

          // 完整内容（可滚动）
          Scroll() {
            Text(item.content)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
          }
          .layoutWeight(1)
          .width('100%')
          .margin({ top: 12 })
          .scrollBar(BarState.Off)

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            size: 'medium',
            block: true,
            onClick: () => { this.closeDetail(); }
          })
            .margin({ top: 12 })
        }
        .width('100%')
        .height('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
      .height('80%')
    }
    .width('100%')
    .height('100%')
  }
}
