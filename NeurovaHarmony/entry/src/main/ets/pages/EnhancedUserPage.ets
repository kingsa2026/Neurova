/**
 * EnhancedUserPage - 增强用户管理页
 *
 * 职责：列出增强用户（按 status/role/department 筛选），在线状态指示灯，
 *       部门展示，2FA 标识，点击项查看详情
 * 设计：
 *   - EnhancedUserViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标、状态标签、
 *     角色颜色映射、角色标签、最后活动时间格式化（X 分钟前/小时前/天前）、双因素认证颜色，
 *     无 UI 依赖，可独立单元测试；
 *   - EnhancedUserPage（@Component）：Stack [主内容列] + [详情弹窗]
 *     主内容列：TopNavMenu(标题"用户管理"+返回) + [状态筛选 Tab] + [加载态/空态/列表]；
 *     列表项 GlassCard：状态指示灯、displayName、username、role 徽章、department、
 *     2FA 标识、lastActiveAt；
 *     详情弹窗：Stack 内嵌条件渲染，展示用户完整信息；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无增强用户专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 接入真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：EnhancedUser、EnhancedUserStatus、EnhancedUserRole
 *
 * 用法：
 *   由 Router.push(RouteNames.ENHANCED_USER) 跳转进入；
 *   aboutToAppear 加载 mock 用户列表（TODO M6 接入真实 API api.enhancedUsers.*）；
 *   状态筛选 Tab 切换 → 本地 filterStatus 过滤；
 *   点击列表项 → 弹出详情弹窗。
 *
 * TDD：EnhancedUserViewHelper 各方法按红绿灯垂直切片逐步实现，详见 EnhancedUserPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { EnhancedUser, EnhancedUserStatus, EnhancedUserRole } from '../libs/types';

/** 日志标签 */
const TAG = 'EnhancedUserPage';

/** 全部状态（用于筛选 Tab 顺序） */
const ALL_STATUSES: EnhancedUserStatus[] = ['online', 'idle', 'dnd', 'offline'];

// ===========================================================================
// EnhancedUserViewHelper - 增强用户视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class EnhancedUserViewHelper {
  /**
   * 获取用户状态对应的颜色 token 名
   * 映射：online→success, idle→warning, dnd→error, offline→text_secondary
   * @param status 用户在线状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: EnhancedUserStatus): string {
    if (status === 'online') return 'success';
    if (status === 'idle') return 'warning';
    if (status === 'dnd') return 'error';
    return 'text_secondary';
  }

  /**
   * 获取用户状态对应的图标 emoji
   * 映射：online→🟢, idle→🟡, dnd→🔴, offline→⚪
   * @param status 用户在线状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: EnhancedUserStatus): string {
    if (status === 'online') return '🟢';
    if (status === 'idle') return '🟡';
    if (status === 'dnd') return '🔴';
    return '⚪';
  }

  /**
   * 获取用户状态对应的中文标签
   * 映射：online→在线, idle→空闲, dnd→勿扰, offline→离线
   * @param status 用户在线状态
   * @return 中文标签
   */
  static getStatusLabel(status: EnhancedUserStatus): string {
    if (status === 'online') return '在线';
    if (status === 'idle') return '空闲';
    if (status === 'dnd') return '勿扰';
    return '离线';
  }

  /**
   * 获取用户角色对应的颜色 token 名
   * 映射：admin→error, developer→primary, operator→info, viewer→text_secondary, guest→warning
   * @param role 用户角色
   * @return StyleManager 颜色 token 名
   */
  static getRoleColor(role: EnhancedUserRole): string {
    if (role === 'admin') return 'error';
    if (role === 'developer') return 'primary';
    if (role === 'operator') return 'info';
    if (role === 'viewer') return 'text_secondary';
    return 'warning';
  }

  /**
   * 获取用户角色对应的中文标签
   * 映射：admin→管理员, developer→开发者, operator→运营者, viewer→查看者, guest→访客
   * @param role 用户角色
   * @return 中文标签
   */
  static getRoleLabel(role: EnhancedUserRole): string {
    if (role === 'admin') return '管理员';
    if (role === 'developer') return '开发者';
    if (role === 'operator') return '运营者';
    if (role === 'viewer') return '查看者';
    return '访客';
  }

  /**
   * 格式化最后活动时间
   * 规则：undefined/无效 → "从未活动"；
   *       < 1 分钟 → "刚刚"；
   *       < 1 小时 → "X 分钟前"；
   *       < 1 天 → "X 小时前"；
   *       否则 → "X 天前"
   * @param timestamp ISO 时间字符串或 undefined
   * @return 格式化后的相对时间文案
   */
  static formatLastActive(timestamp?: string): string {
    if (!timestamp) return '从未活动';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '从未活动';
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 0) return '从未活动';
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${diffMin} 分钟前`;
    const diffHour = Math.floor(diffMs / 3600000);
    if (diffHour < 24) return `${diffHour} 小时前`;
    const diffDay = Math.floor(diffMs / 86400000);
    return `${diffDay} 天前`;
  }

  /**
   * 获取双因素认证状态对应的颜色 token 名
   * 映射：true→success, false→text_secondary
   * @param enabled 是否启用 2FA
   * @return StyleManager 颜色 token 名
   */
  static getTwoFactorColor(enabled: boolean): string {
    if (enabled) return 'success';
    return 'text_secondary';
  }
}

/**
 * Mock 增强用户数据
 * TODO M6 阶段：替换为 api.enhancedUsers.list() 真实 API
 */
const MOCK_USERS: EnhancedUser[] = [
  {
    id: 'user_1',
    username: 'alice',
    email: 'alice@neurova.ai',
    displayName: 'Alice 管理员',
    avatar: undefined,
    status: 'online',
    role: 'admin',
    department: '运营部',
    title: '系统管理员',
    lastActiveAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    loginCount: 320,
    twoFactorEnabled: true,
    createdAt: '2024-01-01T00:00:00Z',
  },
  {
    id: 'user_2',
    username: 'bob',
    email: 'bob@neurova.ai',
    displayName: 'Bob 开发者',
    avatar: undefined,
    status: 'idle',
    role: 'developer',
    department: '研发部',
    title: '高级工程师',
    lastActiveAt: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    loginCount: 158,
    twoFactorEnabled: true,
    createdAt: '2024-02-15T00:00:00Z',
  },
  {
    id: 'user_3',
    username: 'carol',
    email: 'carol@neurova.ai',
    displayName: 'Carol 运营者',
    avatar: undefined,
    status: 'dnd',
    role: 'operator',
    department: '运营部',
    title: '运营专员',
    lastActiveAt: new Date(Date.now() - 5 * 24 * 60 * 60 * 1000).toISOString(),
    loginCount: 42,
    twoFactorEnabled: false,
    createdAt: '2024-05-01T00:00:00Z',
  },
  {
    id: 'user_4',
    username: 'dave',
    email: 'dave@neurova.ai',
    displayName: 'Dave 访客',
    avatar: undefined,
    status: 'offline',
    role: 'guest',
    department: undefined,
    title: undefined,
    lastActiveAt: undefined,
    loginCount: 2,
    twoFactorEnabled: false,
    createdAt: '2025-06-01T00:00:00Z',
  },
];

@Component
export struct EnhancedUserPage {
  // 用户列表
  @State users: EnhancedUser[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前筛选状态（空串表示全部）
  @State filterStatus: string = '';
  // 详情弹窗显示状态
  @State showDetailDialog: boolean = false;
  // 当前选中的用户（详情弹窗使用）
  @State selectedUser: EnhancedUser | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadUsers();
  }

  /**
   * 加载增强用户列表
   * TODO M6 阶段：替换为真实 API（api.enhancedUsers.list）
   */
  private async loadUsers(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.enhancedUsers.list();
      // if (res.code === 0 && res.data) { this.users = res.data; }
      this.users = MOCK_USERS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载用户失败', e as Error);
      this.msg.error('加载用户列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换状态筛选
   * 规则：再次点击同一状态取消筛选；点击不同状态切换筛选
   */
  private handleStatusFilter(status: EnhancedUserStatus): void {
    this.filterStatus = this.filterStatus === status ? '' : status;
  }

  /**
   * 获取经筛选后的列表
   * 规则：filterStatus 为空 → 全部；否则筛选 status 等于筛选值的用户
   */
  private getFilteredUsers(): EnhancedUser[] {
    if (!this.filterStatus) return this.users;
    return this.users.filter((u: EnhancedUser) => u.status === this.filterStatus);
  }

  /**
   * 点击列表项 → 打开详情弹窗
   */
  private handleItemClick(user: EnhancedUser): void {
    this.selectedUser = user;
    this.showDetailDialog = true;
  }

  /** 关闭详情弹窗 */
  private closeDetailDialog(): void {
    this.showDetailDialog = false;
    this.selectedUser = null;
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"用户管理" + 返回
        TopNavMenu({
          title: '用户管理',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        })

        // 状态筛选 Tab（横向滚动胶囊：全部 + 4 状态）
        this.buildStatusFilter()

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
        } else if (this.getFilteredUsers().length === 0) {
          Column() {
            Text('暂无用户')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredUsers(), (user: EnhancedUser) => {
              ListItem() {
                this.buildUserCard(user)
              }
            }, (user: EnhancedUser) => user.id)
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

      // 详情弹窗
      if (this.showDetailDialog && this.selectedUser !== null) {
        this.buildDetailDialog(this.selectedUser)
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 状态筛选 Tab 构建器
  // ===========================================================================

  /** 状态筛选 Tab：横向滚动胶囊（全部 + 4 状态） */
  @Builder
  buildStatusFilter() {
    Scroll() {
      Row({ space: 8 }) {
        // 全部
        Text('全部')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.filterStatus === ''
            ? this.sm.getColor('text_on_primary')
            : this.sm.getColor('text_primary'))
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .borderRadius(16)
          .backgroundColor(this.filterStatus === ''
            ? this.sm.getColor('primary')
            : Color.Transparent)
          .onClick(() => { this.filterStatus = ''; })

        // 4 状态
        ForEach(ALL_STATUSES, (status: EnhancedUserStatus) => {
          Text(EnhancedUserViewHelper.getStatusLabel(status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.filterStatus === status
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.filterStatus === status
              ? this.sm.getColor(EnhancedUserViewHelper.getStatusColor(status))
              : Color.Transparent)
            .onClick(() => { this.handleStatusFilter(status); })
        }, (status: EnhancedUserStatus) => status)
      }
      .padding({
        left: this.sm.getSpacing('md'),
        right: this.sm.getSpacing('md'),
        top: this.sm.getSpacing('sm'),
        bottom: this.sm.getSpacing('sm'),
      })
    }
    .scrollable(ScrollDirection.Horizontal)
    .scrollBar(BarState.Off)
    .width('100%')
  }

  // ===========================================================================
  // 用户卡片构建器
  // ===========================================================================

  /** 单个用户卡片：状态指示灯 + displayName + username + role + department + 2FA + lastActiveAt */
  @Builder
  buildUserCard(user: EnhancedUser) {
    GlassCard() {
      Column() {
        // 顶部行：状态指示灯 + displayName + username + role 徽章
        Row() {
          // 状态指示灯
          Text(EnhancedUserViewHelper.getStatusIcon(user.status))
            .fontSize(14)
            .margin({ right: 6 })

          Column() {
            Text(user.displayName)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(`@${user.username}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          .margin({ right: this.sm.getSpacing('sm') })

          // 角色徽章
          Text(EnhancedUserViewHelper.getRoleLabel(user.role))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(EnhancedUserViewHelper.getRoleColor(user.role)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .onClick(() => { this.handleItemClick(user); })

        // 底部行：部门 + 2FA 标识 + 最后活动
        Row() {
          // 部门
          if (user.department) {
            Text(`🏢 ${user.department}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ right: this.sm.getSpacing('sm') })
          }

          // 2FA 标识
          Text(user.twoFactorEnabled ? '🔒 2FA' : '🔓 无 2FA')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(EnhancedUserViewHelper.getTwoFactorColor(user.twoFactorEnabled)))
            .margin({ right: this.sm.getSpacing('sm') })

          // 最后活动
          Text(EnhancedUserViewHelper.formatLastActive(user.lastActiveAt))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
    .width('100%')
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 内嵌条件渲染，不单独建文件）
  // ===========================================================================

  /** 用户详情弹窗：完整字段展示 */
  @Builder
  buildDetailDialog(user: EnhancedUser) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetailDialog(); })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Scroll() {
          Column() {
            Text('用户详情')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ bottom: this.sm.getSpacing('sm') })

            // 状态 + displayName
            Text('状态')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`${EnhancedUserViewHelper.getStatusIcon(user.status)} ${EnhancedUserViewHelper.getStatusLabel(user.status)}`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor(EnhancedUserViewHelper.getStatusColor(user.status)))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 显示名 + 用户名
            Text('用户名')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`${user.displayName} (@${user.username})`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 邮箱
            Text('邮箱')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(user.email)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 角色
            Text('角色')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(EnhancedUserViewHelper.getRoleLabel(user.role))
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor(EnhancedUserViewHelper.getRoleColor(user.role)))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 部门 + 职位
            if (user.department) {
              Text('部门')
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .width('100%')
              Text(`${user.department}${user.title ? ' · ' + user.title : ''}`)
                .fontSize(this.sm.getFontSize('body'))
                .fontColor(this.sm.getColor('text_primary'))
                .width('100%')
                .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
            }

            // 2FA
            Text('双因素认证')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(user.twoFactorEnabled ? '已启用 🔒' : '未启用 🔓')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor(EnhancedUserViewHelper.getTwoFactorColor(user.twoFactorEnabled)))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 登录次数 + 最后活动
            Text(`登录次数：${user.loginCount}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`最后活动：${EnhancedUserViewHelper.formatLastActive(user.lastActiveAt)}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .layoutWeight(1)
        .scrollBar(BarState.Off)

        // 底部按钮
        Row() {
          GlassButton({
            text: '关闭',
            type: 'default',
            size: 'medium',
            onClick: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      .width('90%')
      .height('70%')
    }
    .width('100%')
    .height('100%')
  }
}
