/**
 * NotificationPage - 通知页
 *
 * 职责：展示通知列表，按 type/read 筛选，支持标记已读/全部已读/删除
 * 设计：
 *   - NotificationViewHelper（导出）：纯视图模型，封装通知类型颜色/图标/标签映射、
 *     已读状态颜色、创建时间相对格式化（X分钟前/X小时前/X天前/YYYY-MM-DD）、
 *     标题截断，无 UI 运行时依赖，可独立单元测试；
 *   - NotificationPage（@Component）：Stack[Column[TopNavMenu(标题"通知"+返回+全部已读)]
 *     + [type 筛选 Tab（全部/info/success/warning/error）]
 *     + [read 筛选 Tab（全部/未读/已读）]
 *     + [加载态/空态/列表]]；
 *     列表项 GlassCard 含 类型徽章、标题（未读加粗）、时间、左侧红点（未读）、
 *     正文摘要、操作按钮（标记已读/删除）；
 *     点击未读项 → 标记已读；全部已读按钮 → 调用 api.monitor.markAllNotificationsRead；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.monitor，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton
 *   - ../libs/api/ApiFacade：统一 API 门面（monitor.listNotifications/markNotificationRead/
 *     markAllNotificationsRead/removeNotification）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：NotificationItem、NotificationType
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.monitor.listNotifications 加载列表；
 *   type/read 筛选 Tab 切换 → 本地 filterByTypeAndRead 过滤；
 *   点击未读项 → 调用 api.monitor.markNotificationRead → 刷新列表；
 *   全部已读按钮 → 调用 api.monitor.markAllNotificationsRead → 刷新列表；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.monitor.removeNotification → 刷新列表
 *
 * TDD：NotificationViewHelper 各方法按红绿灯垂直切片逐步实现，详见 NotificationPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { NotificationItem, NotificationType } from '../libs/types';

/** 日志标签 */
const TAG = 'NotificationPage';

/** 默认标题截断长度（通知页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

/** 7 天的毫秒数（超过 7 天显示绝对日期） */
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

// ===========================================================================
// NotificationViewHelper - 通知视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'info'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
//
// 颜色 token 说明：返回 StyleManager 实际支持的 token 名（'info'/'warning'/'error'/
//   'success'/'text_secondary'），不加 'status_' 前缀。StyleManager 的 ColorToken 类型
//   仅包含未加前缀的 token，'status_info' 不在其列，调用 getColor('status_info') 会
//   回退到 '#000000'（黑色）。为避免此 bug，统一使用未加前缀的 token。
// ===========================================================================

export class NotificationViewHelper {
  /**
   * 获取通知类型对应的颜色 token 名
   * 映射：info→info, success→success, warning→warning, error→error
   * @param type 通知类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: NotificationType): string {
    if (type === 'info') return 'info';
    if (type === 'success') return 'success';
    if (type === 'warning') return 'warning';
    return 'error';
  }

  /**
   * 获取通知类型对应的图标 emoji
   * 映射：info→ℹ️, success→✅, warning→⚠️, error→❌
   * @param type 通知类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: NotificationType): string {
    if (type === 'info') return 'ℹ️';
    if (type === 'success') return '✅';
    if (type === 'warning') return '⚠️';
    return '❌';
  }

  /**
   * 获取通知类型对应的中文标签
   * 映射：info→信息, success→成功, warning→警告, error→错误
   * @param type 通知类型
   * @return 中文标签
   */
  static getTypeLabel(type: NotificationType): string {
    if (type === 'info') return '信息';
    if (type === 'success') return '成功';
    if (type === 'warning') return '警告';
    return '错误';
  }

  /**
   * 获取已读状态对应的颜色 token 名（用于左侧红点）
   * 映射：未读(false)→error（红点），已读(true)→text_secondary（无强调）
   * @param read 是否已读
   * @return StyleManager 颜色 token 名
   */
  static getReadStatusColor(read: boolean): string {
    return read ? 'text_secondary' : 'error';
  }

  /**
   * 格式化创建时间为相对时间文案
   * 规则：
   *   - 无值/无效 → "-"
   *   - <1 分钟 → "1分钟前"
   *   - <1 小时 → "X分钟前"
   *   - <1 天 → "X小时前"
   *   - <7 天 → "X天前"
   *   - >=7 天 → "YYYY-MM-DD"
   * @param timestamp ISO 时间戳字符串
   * @return 相对时间文案或绝对日期
   */
  static formatCreatedAt(timestamp?: string): string {
    if (!timestamp || timestamp.length === 0) return '-';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '-';
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 0) return '-'; // 未来时间无效
    // 小于 1 分钟
    if (diff < 60 * 1000) return '1分钟前';
    // 小于 1 小时
    if (diff < 60 * 60 * 1000) {
      const minutes = Math.floor(diff / (60 * 1000));
      return `${minutes}分钟前`;
    }
    // 小于 1 天
    if (diff < 24 * 60 * 60 * 1000) {
      const hours = Math.floor(diff / (60 * 60 * 1000));
      return `${hours}小时前`;
    }
    // 小于 7 天
    if (diff < WEEK_MS) {
      const days = Math.floor(diff / (24 * 60 * 60 * 1000));
      return `${days}天前`;
    }
    // 超过 7 天，显示绝对日期 YYYY-MM-DD
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd}`;
  }

  /**
   * 截断通知标题
   * 规则：
   *   - title 为空 → 原样返回
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param title 通知标题
   * @param maxLen 最大长度，默认 100
   * @return 截断后的标题
   */
  static truncateTitle(title: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!title || title.length === 0) return title;
    if (title.length <= len) return title;
    return title.substring(0, len) + '...';
  }
}

/** 筛选 Tab 配置 */
interface FilterOption {
  value: string;
  label: string;
}

/** 类型筛选 Tab 列表（全部/info/success/warning/error） */
const TYPE_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'info', label: '信息' },
  { value: 'success', label: '成功' },
  { value: 'warning', label: '警告' },
  { value: 'error', label: '错误' },
];

/** 已读状态筛选 Tab 列表（全部/未读/已读） */
const READ_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'unread', label: '未读' },
  { value: 'read', label: '已读' },
];

@Component
export struct NotificationPage {
  // 通知列表
  @State notifications: NotificationItem[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的类型筛选值
  @State activeType: string = 'all';
  // 当前激活的已读筛选值
  @State activeRead: string = 'all';
  // 标记全部已读中态
  @State markingAll: boolean = false;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadNotifications();
  }

  /**
   * 加载通知列表
   * 流程：调用 api.monitor.listNotifications → 写入 notifications
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadNotifications(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.monitor.listNotifications(false);
      if (res.code === 0 && res.data) {
        this.notifications = res.data;
      }
    } catch (e) {
      this.logger.error(TAG, '加载通知失败', e as Error);
      this.msg.error('加载通知列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换类型筛选 Tab */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /** 切换已读状态筛选 Tab */
  private switchRead(value: string): void {
    this.activeRead = value;
  }

  /** 获取经类型+已读双重筛选后的列表 */
  private getFilteredList(): NotificationItem[] {
    let result = this.notifications;
    if (this.activeType !== 'all') {
      result = result.filter((n: NotificationItem) => n.type === this.activeType);
    }
    if (this.activeRead === 'unread') {
      result = result.filter((n: NotificationItem) => !n.read);
    } else if (this.activeRead === 'read') {
      result = result.filter((n: NotificationItem) => n.read);
    }
    return result;
  }

  /** 获取未读数量 */
  private getUnreadCount(): number {
    return this.notifications.filter((n: NotificationItem) => !n.read).length;
  }

  /**
   * 标记单条通知为已读
   * 流程：调用 api.monitor.markNotificationRead → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async markRead(id: string): Promise<void> {
    try {
      const res = await this.api.monitor.markNotificationRead(id);
      if (res.code === 0) {
        this.msg.success('已标记为已读');
        this.loadNotifications();
      } else {
        this.msg.error(res.message || '标记失败');
      }
    } catch (e) {
      this.logger.error(TAG, '标记已读失败', e as Error);
      this.msg.error('标记已读失败');
    }
  }

  /** 点击通知项：未读则标记已读 */
  private handleClick(n: NotificationItem): void {
    if (!n.read) {
      this.markRead(n.id);
    }
  }

  /**
   * 标记全部已读
   * 流程：调用 api.monitor.markAllNotificationsRead → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async markAllRead(): Promise<void> {
    this.markingAll = true;
    try {
      const res = await this.api.monitor.markAllNotificationsRead();
      if (res.code === 0) {
        this.msg.success('全部已标记为已读');
        this.loadNotifications();
      } else {
        this.msg.error(res.message || '标记失败');
      }
    } catch (e) {
      this.logger.error(TAG, '全部标记已读失败', e as Error);
      this.msg.error('全部标记已读失败');
    } finally {
      this.markingAll = false;
    }
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(n: NotificationItem): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除通知"${n.title}"吗？`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteNotification(n.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.monitor.removeNotification → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteNotification(id: string): Promise<void> {
    try {
      const res = await this.api.monitor.removeNotification(id);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadNotifications();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除通知失败', e as Error);
      this.msg.error('删除通知失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"通知" + 返回按钮 + 全部已读按钮
        TopNavMenu({
          title: `通知${this.getUnreadCount() > 0 ? ` (${this.getUnreadCount()})` : ''}`,
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '全部已读',
            type: 'default',
            size: 'small',
            onClick: () => { this.markAllRead(); }
          })
        }

        // 类型筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(TYPE_FILTERS, (opt: FilterOption) => {
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
            }, (opt: FilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 已读状态筛选 Tab
        Scroll() {
          Row({ space: 8 }) {
            ForEach(READ_FILTERS, (opt: FilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeRead === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeRead === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchRead(opt.value); })
            }, (opt: FilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无通知')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (n: NotificationItem) => {
              ListItem() {
                this.buildNotificationCard(n)
              }
            }, (n: NotificationItem) => n.id)
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
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 通知卡片构建器
  // ===========================================================================

  /** 单条通知卡片：左侧红点 + 类型徽章 + 标题（未读加粗）+ 时间 + 正文 + 操作按钮 */
  @Builder
  buildNotificationCard(n: NotificationItem) {
    GlassCard() {
      Row() {
        // 左侧红点（未读才显示）
        if (!n.read) {
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(NotificationViewHelper.getReadStatusColor(n.read)))
            .margin({ right: this.sm.getSpacing('sm') })
        }

        // 右侧内容
        Column() {
          // 上部：类型徽章 + 时间
          Row() {
            Row() {
              Text(NotificationViewHelper.getTypeIcon(n.type))
                .fontSize(14)
              Text(NotificationViewHelper.getTypeLabel(n.type))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor(NotificationViewHelper.getTypeColor(n.type)))
                .margin({ left: 4 })
            }
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor('surface'))

            Text(NotificationViewHelper.formatCreatedAt(n.createdAt))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .layoutWeight(1)
              .margin({ left: 8 })
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
              .textAlign(TextAlign.End)
          }
          .alignItems(VerticalAlign.Center)

          // 标题（未读加粗）
          Text(NotificationViewHelper.truncateTitle(n.title, DEFAULT_TRUNCATE_LEN))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(n.read ? FontWeight.Normal : FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 8 })

          // 正文摘要
          Text(n.body)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(3)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })

          // 操作按钮：标记已读 / 删除
          Row() {
            if (!n.read) {
              GlassButton({
                text: '标记已读',
                type: 'default',
                size: 'small',
                onClick: () => { this.markRead(n.id); }
              })
            }
            GlassButton({
              text: '删除',
              type: 'danger',
              size: 'small',
              onClick: () => { this.confirmDelete(n); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
          .margin({ top: this.sm.getSpacing('md') })
        }
        .layoutWeight(1)
        .alignItems(HorizontalAlign.Start)
      }
      .width('100%')
      .alignItems(VerticalAlign.Top)
    }
    .width('100%')
    .onClick(() => { this.handleClick(n); })
  }
}
