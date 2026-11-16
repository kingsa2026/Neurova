/**
 * CollaborationHistoryPage - 协作历史页（P1-34 切真实 API）
 *
 * 职责：展示协作历史（GET /v1/collaboration/history 的真实协作快照），
 *   按 status 筛选，时间倒序显示，点击项查看详情
 * 设计：
 *   - CollaborationHistoryViewHelper（导出）：纯视图模型，封装状态颜色/图标/文案、
 *     时间戳格式化、备注截断；无 UI 运行时依赖，可独立单元测试；
 *   - CollaborationHistoryPage（@Component）：Column [TopNavMenu(标题"协作历史"+返回)] +
 *     [status 筛选 Tab（全部/active/archived/suspended）] + [加载态/空态/列表]；
 *     列表项 GlassCard：status 徽章、名称、属主、成员数、更新时间、详情按钮；
 *   - 数据源：api.collaboration.listHistory()（真实端点，无 mock）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面
 *   - ../libs/api/modules/CollaborationApi：CollaborationHistoryDto
 *   - ../routing/Router、../libs/style/StyleManager、../libs/logger/Logger、
 *     ../libs/message/MessageManager
 *
 * TDD：CollaborationHistoryViewHelper 各方法详见 CollaborationHistoryPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { CollaborationHistoryDto } from '../libs/api/modules/CollaborationApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'CollaborationHistoryPage';

/** 备注截断默认最大长度 */
const DEFAULT_NOTE_MAX_LEN = 50;

// ===========================================================================
// CollaborationHistoryViewHelper - 协作历史视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class CollaborationHistoryViewHelper {
  /**
   * 获取协作状态对应的颜色 token 名
   * 映射：active→success，archived→warning，suspended→error，其他→info
   * @param status 协作状态字符串（后端 project status）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: string): string {
    if (status === 'active') return 'success';
    if (status === 'archived') return 'warning';
    if (status === 'suspended') return 'error';
    return 'info';
  }

  /**
   * 获取协作状态对应的图标 emoji
   * 映射：active→✅，archived→📦，suspended→⏸️，其他→🔄
   * @param status 协作状态字符串
   * @return emoji 字符串
   */
  static getStatusIcon(status: string): string {
    if (status === 'active') return '✅';
    if (status === 'archived') return '📦';
    if (status === 'suspended') return '⏸️';
    return '🔄';
  }

  /**
   * 获取协作状态对应的中文标签
   * 映射：active→进行中，archived→已归档，suspended→已暂停，其他→未知
   * @param status 协作状态字符串
   * @return 中文文案
   */
  static getStatusLabel(status: string): string {
    if (status === 'active') return '进行中';
    if (status === 'archived') return '已归档';
    if (status === 'suspended') return '已暂停';
    return '未知';
  }

  /**
   * 格式化时间戳为 "YYYY-MM-DD HH:mm" 展示字符串
   * 规则：无效时间 → "未知"；有效 → 本地时间 YYYY-MM-DD HH:mm
   * @param timestamp ISO 时间字符串
   * @return 格式化后的时间字符串
   */
  static formatTimestamp(timestamp: string): string {
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  /**
   * 截断文本，超长时截取 maxLen 字符并追加省略号
   * @param note 原始文本
   * @param maxLen 最大字符数
   * @return 截断后的文本；未超长则原样返回
   */
  static truncateNote(note: string, maxLen: number): string {
    if (note.length <= maxLen) return note;
    return note.substring(0, maxLen) + '...';
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;     // 'all' 或具体状态
  label: string;
}

/** 状态筛选 Tab 列表（后端 project status 真实词汇） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '进行中' },
  { value: 'archived', label: '已归档' },
  { value: 'suspended', label: '已暂停' },
];

// ===========================================================================
// CollaborationHistoryViewHelper - 协作历史视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

@Component
export struct CollaborationHistoryPage {
  // 历史记录列表（真实 DTO：GET /v1/collaboration/history）
  @State history: CollaborationHistoryDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选值
  @State activeStatus: string = 'all';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadHistory();
  }

  /**
   * 加载协作历史（真实 API：GET /v1/collaboration/history，P1-34）
   * 后端返回 data={history,total}，按更新时间倒序排序
   */
  private async loadHistory(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listHistory(100, 0);
      if (res.code === 0 && res.data) {
        this.history = res.data.items.slice().sort((a: CollaborationHistoryDto, b: CollaborationHistoryDto) => {
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        });
      } else {
        this.msg.error(res.message || '加载协作历史失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载历史失败', e as Error);
      this.msg.error('加载协作历史失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredHistory(): CollaborationHistoryDto[] {
    if (this.activeStatus === 'all') {
      return this.history;
    }
    return this.history.filter((h: CollaborationHistoryDto) => h.status === this.activeStatus);
  }

  /**
   * 查看历史详情（AlertDialog 展示协作快照真实字段）
   */
  private showDetail(h: CollaborationHistoryDto): void {
    const membersText = h.members.length === 0 ? '无' : h.members.join('、');
    AlertDialog.show({
      title: h.name,
      message:
        `状态：${CollaborationHistoryViewHelper.getStatusLabel(h.status)}\n\n` +
        `描述：${h.description || '无'}\n\n` +
        `属主：${h.owner_id}\n\n` +
        `成员：${membersText}\n\n` +
        `创建：${CollaborationHistoryViewHelper.formatTimestamp(h.created_at)}\n` +
        `更新：${CollaborationHistoryViewHelper.formatTimestamp(h.updated_at)}`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  build() {
    Column() {
      // 顶部导航栏：标题"协作历史" + 返回
      TopNavMenu({
        title: '协作历史',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

      // 状态筛选 Tab
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
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.getFilteredHistory().length === 0) {
        Column() {
          Text('暂无历史记录')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        List({ space: 12 }) {
          ForEach(this.getFilteredHistory(), (h: CollaborationHistoryDto) => {
            ListItem() {
              this.buildHistoryCard(h)
            }
          }, (h: CollaborationHistoryDto) => h.id)
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
  }

  // ===========================================================================
  // 历史卡片构建器
  // ===========================================================================

  /** 单个历史卡片：状态徽章 + 名称 + 属主 + 成员数 + 更新时间 + 操作按钮 */
  @Builder
  buildHistoryCard(h: CollaborationHistoryDto) {
    Column() {
    GlassCard() {
      Column() {
        // 顶部行：状态图标 + 状态徽章 + 名称
        Row() {
          Text(CollaborationHistoryViewHelper.getStatusIcon(h.status))
            .fontSize(20)
          Text(CollaborationHistoryViewHelper.getStatusLabel(h.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(CollaborationHistoryViewHelper.getStatusColor(h.status)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(h.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 描述摘要（默认 50 字符截断，无描述显示 "无描述"）
        Text(h.description
          ? CollaborationHistoryViewHelper.truncateNote(h.description, DEFAULT_NOTE_MAX_LEN)
          : '无描述')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 属主 + 成员数 + 更新时间
        Text(`属主：${h.owner_id} · 成员 ${h.members.length} 人`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')
        Text(CollaborationHistoryViewHelper.formatTimestamp(h.updated_at))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 操作按钮：查看详情（右对齐）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.showDetail(h); }
          })
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
}
