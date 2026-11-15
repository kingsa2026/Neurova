/**
 * AgentMediaPage - 媒体资产管理页
 *
 * 职责：展示当前 Agent 的媒体资产列表，支持按 type 筛选、网格预览（图片缩略图）、删除
 * 设计：
 *   - AgentMediaViewHelper（导出）：纯视图模型，封装类型颜色映射、类型图标映射、类型标签映射、
 *     文件大小格式化、时长格式化；无 UI 运行时依赖，可独立单元测试；
 *   - AgentMediaPage（@Component）：Column [TopNavMenu(标题"媒体资产"+返回+上传)]
 *     + [type 筛选 Tab（全部/图片/音频/视频/文档）]
 *     + [加载态/空态/网格列表]；列表采用 Grid 布局（每行 2 项），
 *     每项含缩略图（图片显示 thumbnailUrl，其他显示 type 图标）、名称、type 徽章、大小、
 *     时长（音视频适用）、操作（预览/删除）；
 *     删除走 AlertDialog 二次确认；预览走内嵌 Stack 条件渲染弹窗（图片显示大图，其他显示信息）；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.capability，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（AgentMediaViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getTypeColor / getTypeIcon / getTypeLabel 按 MediaAssetType 四元映射；
 *   - formatFileSize 按 1024 进制格式化为 B/KB/MB，0 → "—"；
 *   - formatDuration 按秒数格式化为 "M:SS" 或 "H:MM:SS"，undefined → "—"。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（capability 模块：listMedia/getMedia/createMedia/updateMedia/removeMedia）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：MediaAsset、MediaAssetType
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.capability.listMedia(agentId) 加载列表；
 *   type 筛选 Tab 切换 → 本地过滤；
 *   预览按钮 → 打开弹窗（图片显示大图，其他显示元信息）；
 *   删除按钮 → AlertDialog 二次确认 → api.capability.removeMedia → 刷新列表。
 *
 * TDD：AgentMediaViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentMediaPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { MediaAsset, MediaAssetType } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentMediaPage';

// ===========================================================================
// AgentMediaViewHelper - 媒体资产视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class AgentMediaViewHelper {
  /**
   * 获取媒体类型对应的颜色 token 名
   * 映射：image→primary，audio→info，video→warning，document→success
   * @param type 媒体类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: MediaAssetType): string {
    if (type === 'image') return 'primary';
    if (type === 'audio') return 'info';
    if (type === 'video') return 'warning';
    if (type === 'document') return 'success';
    return 'text_secondary';
  }

  /**
   * 获取媒体类型对应的图标 emoji
   * 映射：image→🖼️，audio→🎵，video→🎬，document→📄
   * @param type 媒体类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: MediaAssetType): string {
    if (type === 'image') return '🖼️';
    if (type === 'audio') return '🎵';
    if (type === 'video') return '🎬';
    if (type === 'document') return '📄';
    return '❓';
  }

  /**
   * 获取媒体类型对应的中文显示名
   * 映射：image→图片，audio→音频，video→视频，document→文档
   * @param type 媒体类型
   * @return 中文短名
   */
  static getTypeLabel(type: MediaAssetType): string {
    if (type === 'image') return '图片';
    if (type === 'audio') return '音频';
    if (type === 'video') return '视频';
    if (type === 'document') return '文档';
    return '未知';
  }

  /**
   * 将字节数格式化为人类可读字符串
   * 规则：1024 → "1.0 KB"，1048576 → "1.0 MB"，0 → "—"
   * 单位阶梯：B / KB / MB（按 1024 进制，保留 1 位小数）
   * @param bytes 字节数
   * @return 已格式化的字符串
   */
  static formatFileSize(bytes: number): string {
    if (bytes === 0) return '—';
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

  /**
   * 格式化时长（秒）为可读字符串
   * 规则：< 1 小时 → "M:SS"（如 60 → "1:00"）；≥ 1 小时 → "H:MM:SS"（如 3600 → "1:00:00"）；
   *       undefined → "—"
   * @param seconds 秒数
   * @return 已格式化的时长字符串
   */
  static formatDuration(seconds?: number): string {
    if (seconds === undefined) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    const pad = (n: number) => n.toString().padStart(2, '0');
    if (h > 0) {
      return `${h}:${pad(m)}:${pad(s)}`;
    }
    return `${m}:${pad(s)}`;
  }
}

// ===========================================================================
// 筛选 Tab 配置
// ===========================================================================

/** type 筛选 Tab 选项 */
interface TypeFilterOption {
  value: string;  // 'all' 或具体 MediaAssetType
  label: string;
}

/** type 筛选 Tab 列表（顺序即展示顺序） */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'image', label: '图片' },
  { value: 'audio', label: '音频' },
  { value: 'video', label: '视频' },
  { value: 'document', label: '文档' },
];

@Component
export struct AgentMediaPage {
  // 媒体资产列表（由 API 加载，驱动列表渲染）
  @State mediaList: MediaAsset[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的类型筛选值：'all' 或具体 MediaAssetType
  @State activeType: string = 'all';

  // 预览弹窗显示状态
  @State showPreview: boolean = false;
  // 当前预览的媒体资产
  @State previewItem: MediaAsset | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadMedia();
  }

  /**
   * 加载媒体资产列表
   * 流程：取 currentAgentId → 调用 api.capability.listMedia → 写入 mediaList
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadMedia(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.capability.listMedia(agentId);
      if (res.code === 0 && res.data) {
        this.mediaList = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载媒体资产失败', e as Error);
      this.msg.error('加载媒体资产失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换类型筛选 Tab */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /**
   * 获取经类型筛选后的列表
   */
  private getFilteredMedia(): MediaAsset[] {
    if (this.activeType === 'all') {
      return this.mediaList;
    }
    return this.mediaList.filter((m: MediaAsset) => m.type === this.activeType);
  }

  /**
   * 打开预览弹窗
   */
  private openPreview(item: MediaAsset): void {
    this.previewItem = item;
    this.showPreview = true;
  }

  /**
   * 关闭预览弹窗
   */
  private closePreview(): void {
    this.showPreview = false;
    this.previewItem = null;
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(item: MediaAsset): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除媒体"${item.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteMedia(item.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.capability.removeMedia → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteMedia(mediaId: string): Promise<void> {
    try {
      const res = await this.api.capability.removeMedia(mediaId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadMedia();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除媒体资产失败', e as Error);
      this.msg.error('删除媒体资产失败');
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
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
        // 顶部导航栏：标题"媒体资产" + 返回 + 上传按钮
        TopNavMenu({
          title: '媒体资产',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '上传',
            type: 'primary',
            size: 'small',
            onClick: () => { this.msg.info('上传功能开发中'); }
          })
        }

        // type 筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(TYPE_FILTERS, (opt: TypeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeType === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeType === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchType(opt.value); })
            }, (opt: TypeFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 主体内容：加载态 / 空态 / 网格列表
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
        } else if (this.getFilteredMedia().length === 0) {
          Column() {
            Text('暂无媒体资产')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          // 网格列表：每行 2 项
          Grid() {
            ForEach(this.getFilteredMedia(), (item: MediaAsset) => {
              GridItem() {
                this.buildMediaCard(item)
              }
            }, (item: MediaAsset) => item.id)
          }
          .columnsTemplate('1fr 1fr')
          .columnsGap(this.sm.getSpacing('sm'))
          .rowsGap(this.sm.getSpacing('sm'))
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

      // 预览弹窗：内嵌 Stack 条件渲染
      if (this.showPreview && this.previewItem) {
        this.buildPreviewDialog(this.previewItem)
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 媒体资产卡片构建器
  // ===========================================================================

  /** 单个媒体卡片：缩略图 + 名称 + type 徽章 + 大小/时长 + 操作按钮 */
  @Builder
  buildMediaCard(item: MediaAsset) {
    GlassCard() {
      Column() {
        // 缩略图区域：图片显示 thumbnailUrl，其他显示 type 图标
        Stack({ alignContent: Alignment.Center }) {
          if (item.type === 'image' && item.thumbnailUrl) {
            Image(item.thumbnailUrl)
              .width('100%')
              .height(100)
              .objectFit(ImageFit.Cover)
              .borderRadius(8)
          } else {
            Text(AgentMediaViewHelper.getTypeIcon(item.type))
              .fontSize(40)
              .textAlign(TextAlign.Center)
          }
        }
        .width('100%')
        .height(100)
        .backgroundColor(this.sm.getColor('surface'))
        .borderRadius(8)

        // 名称
        Text(item.name)
          .fontSize(this.sm.getFontSize('caption'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 6 })
          .width('100%')

        // type 徽章
        Row() {
          Text(AgentMediaViewHelper.getTypeLabel(item.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 1, bottom: 1 })
            .borderRadius(8)
            .backgroundColor(this.sm.getColor(AgentMediaViewHelper.getTypeColor(item.type)))
        }
        .width('100%')
        .margin({ top: 4 })

        // 大小 + 时长（音视频显示时长）
        Row() {
          Text(AgentMediaViewHelper.formatFileSize(item.size))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          if (item.duration !== undefined) {
            Text('·')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ left: 4, right: 4 })
            Text(AgentMediaViewHelper.formatDuration(item.duration))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
        }
        .width('100%')
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：预览 / 删除
        Row() {
          GlassButton({
            text: '预览',
            type: 'default',
            size: 'small',
            onClick: () => { this.openPreview(item); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(item); }
          })
            .margin({ left: this.sm.getSpacing('xs') })
        }
        .width('100%')
        .justifyContent(FlexAlign.SpaceBetween)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 预览弹窗构建器（内嵌 Stack 条件渲染）
  // ===========================================================================

  /** 预览弹窗：图片显示大图，其他显示元信息 */
  @Builder
  buildPreviewDialog(item: MediaAsset) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closePreview(); })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题：类型标签 + 名称
          Row() {
            Text(AgentMediaViewHelper.getTypeIcon(item.type))
              .fontSize(this.sm.getFontSize('subtitle'))
            Text(item.name)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)

          // 预览内容：图片显示大图，其他显示类型图标占位
          if (item.type === 'image' && item.url) {
            Image(item.url)
              .width('100%')
              .height(300)
              .objectFit(ImageFit.Contain)
              .borderRadius(8)
              .margin({ top: this.sm.getSpacing('md') })
          } else {
            Column() {
              Text(AgentMediaViewHelper.getTypeIcon(item.type))
                .fontSize(72)
                .textAlign(TextAlign.Center)
              Text(AgentMediaViewHelper.getTypeLabel(item.type))
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: this.sm.getSpacing('sm') })
            }
            .width('100%')
            .height(200)
            .justifyContent(FlexAlign.Center)
            .alignItems(HorizontalAlign.Center)
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(8)
            .margin({ top: this.sm.getSpacing('md') })
          }

          // 元信息：类型 / 大小 / 时长 / 创建时间 / URL
          Column() {
            Text(`类型：${AgentMediaViewHelper.getTypeLabel(item.type)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
            Text(`大小：${AgentMediaViewHelper.formatFileSize(item.size)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 4 })
            if (item.duration !== undefined) {
              Text(`时长：${AgentMediaViewHelper.formatDuration(item.duration)}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ top: 4 })
            }
            Text(`创建：${this.formatTime(item.createdAt)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 4 })
            Text(`URL：${item.url}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .margin({ top: 4 })
              .width('100%')
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
          .margin({ top: this.sm.getSpacing('md') })

          // 关闭按钮
          GlassButton({
            text: '关闭',
            type: 'primary',
            size: 'medium',
            block: true,
            onClick: () => { this.closePreview(); }
          })
            .margin({ top: this.sm.getSpacing('md') })
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
