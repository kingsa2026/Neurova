/**
 * EnhancedUserPage - 增强用户管理页
 *
 * 职责：列出增强用户（按启用状态筛选），启用状态指示，角色徽章，
 *       最近登录展示，点击项查看详情
 * 设计：
 *   - EnhancedUserViewHelper（导出）：纯视图模型，封装启用状态颜色/图标/标签、
 *     角色颜色映射、角色标签、最近登录时间格式化（X 分钟前/小时前/天前），
 *     无 UI 依赖，可独立单元测试；
 *   - EnhancedUserPage（@Component）：Stack [主内容列] + [详情弹窗]
 *     主内容列：TopNavMenu(标题"用户管理"+返回) + [启用状态筛选 Tab] + [加载态/空态/列表]；
 *     列表项 GlassCard：启用状态灯、username、email、role 徽章、last_login；
 *     详情弹窗：Stack 内嵌条件渲染，展示用户完整信息；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router；
 *   - P1-33 已接线 PageMap；数据走 api.admin.listUsers / removeUser
 *     （后端 /v1/enhanced-users，UserOut 投影：id/username/email/role/active/
 *     created_at/last_login）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（admin 域）
 *   - ../libs/api/modules/AdminApi：AdminUserDto 类型
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push(RouteNames.ENHANCED_USER) 跳转进入；
 *   aboutToAppear 经 api.admin.listUsers() 加载真实用户列表；
 *   启用状态筛选 Tab 切换 → 本地过滤；
 *   点击列表项 → 弹出详情弹窗。
 *
 * TDD：EnhancedUserViewHelper 各方法按红绿灯垂直切片逐步实现，详见 EnhancedUserPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AdminUserDto } from '../libs/api/modules/AdminApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'EnhancedUserPage';

/** 启用状态筛选 Tab 配置 */
interface ActiveFilterOption {
  value: string;     // '' 全部 / 'active' 启用 / 'inactive' 禁用
  label: string;
}

/** 启用状态筛选 Tab 列表（顺序即展示顺序） */
const ACTIVE_FILTERS: ActiveFilterOption[] = [
  { value: '', label: '全部' },
  { value: 'active', label: '启用' },
  { value: 'inactive', label: '禁用' },
];

// ===========================================================================
// EnhancedUserViewHelper - 增强用户视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class EnhancedUserViewHelper {
  /**
   * 获取启用状态对应的颜色 token 名
   * 映射：true→success, false→text_secondary
   * @param active 是否启用
   * @return StyleManager 颜色 token 名
   */
  static getActiveColor(active: boolean): string {
    if (active) return 'success';
    return 'text_secondary';
  }

  /**
   * 获取启用状态对应的图标 emoji
   * 映射：true→🟢, false→⚪
   * @param active 是否启用
   * @return emoji 字符串
   */
  static getActiveIcon(active: boolean): string {
    if (active) return '🟢';
    return '⚪';
  }

  /**
   * 获取启用状态对应的中文标签
   * 映射：true→启用, false→禁用
   * @param active 是否启用
   * @return 中文标签
   */
  static getActiveLabel(active: boolean): string {
    if (active) return '启用';
    return '禁用';
  }

  /**
   * 获取用户角色对应的颜色 token 名
   * 映射：admin→error, developer→primary, operator→info, viewer→text_secondary, guest→warning
   * 未知角色 → text_secondary（默认）
   * @param role 用户角色（后端为自由字符串）
   * @return StyleManager 颜色 token 名
   */
  static getRoleColor(role: string): string {
    if (role === 'admin') return 'error';
    if (role === 'developer') return 'primary';
    if (role === 'operator') return 'info';
    if (role === 'viewer') return 'text_secondary';
    if (role === 'guest') return 'warning';
    return 'text_secondary';
  }

  /**
   * 获取用户角色对应的中文标签
   * 映射：admin→管理员, developer→开发者, operator→运营者, viewer→查看者, guest→访客
   * 未知角色 → 原样展示角色标识（诚实呈现，不编造译名）
   * @param role 用户角色（后端为自由字符串）
   * @return 中文标签或角色原文
   */
  static getRoleLabel(role: string): string {
    if (role === 'admin') return '管理员';
    if (role === 'developer') return '开发者';
    if (role === 'operator') return '运营者';
    if (role === 'viewer') return '查看者';
    if (role === 'guest') return '访客';
    return role;
  }

  /**
   * 格式化最近登录时间
   * 规则：undefined/无效 → "从未登录"；
   *       < 1 分钟 → "刚刚"；
   *       < 1 小时 → "X 分钟前"；
   *       < 1 天 → "X 小时前"；
   *       否则 → "X 天前"
   * @param timestamp ISO 时间字符串或 undefined
   * @return 格式化后的相对时间文案
   */
  static formatLastActive(timestamp?: string): string {
    if (!timestamp) return '从未登录';
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) return '从未登录';
    const diffMs = Date.now() - d.getTime();
    if (diffMs < 0) return '从未登录';
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return '刚刚';
    if (diffMin < 60) return `${diffMin} 分钟前`;
    const diffHour = Math.floor(diffMs / 3600000);
    if (diffHour < 24) return `${diffHour} 小时前`;
    const diffDay = Math.floor(diffMs / 86400000);
    return `${diffDay} 天前`;
  }
}

@Component
export struct EnhancedUserPage {
  // 用户列表
  @State users: AdminUserDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前启用状态筛选（空串表示全部）
  @State filterActive: string = '';
  // 详情弹窗显示状态
  @State showDetailDialog: boolean = false;
  // 当前选中的用户（详情弹窗使用）
  @State selectedUser: AdminUserDto | null = null;

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
   * 加载增强用户列表（/v1/enhanced-users，裸 {items,total}）
   */
  private async loadUsers(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.listUsers();
      this.users = res.items;
    } catch (e) {
      this.logger.error(TAG, '加载用户失败', e as Error);
      this.msg.error('加载用户列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换启用状态筛选
   * 规则：再次点击同一状态取消筛选；点击不同状态切换筛选
   */
  private handleActiveFilter(value: string): void {
    this.filterActive = this.filterActive === value ? '' : value;
  }

  /**
   * 获取经筛选后的列表
   * 规则：filterActive 为空 → 全部；'active' → 仅启用；'inactive' → 仅禁用
   */
  private getFilteredUsers(): AdminUserDto[] {
    if (!this.filterActive) return this.users;
    if (this.filterActive === 'active') {
      return this.users.filter((u: AdminUserDto) => u.active);
    }
    return this.users.filter((u: AdminUserDto) => !u.active);
  }

  /**
   * 点击列表项 → 打开详情弹窗
   */
  private handleItemClick(user: AdminUserDto): void {
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

        // 启用状态筛选 Tab
        this.buildActiveFilter()

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
            ForEach(this.getFilteredUsers(), (user: AdminUserDto) => {
              ListItem() {
                this.buildUserCard(user)
              }
            }, (user: AdminUserDto) => user.id.toString())
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
  // 启用状态筛选 Tab 构建器
  // ===========================================================================

  /** 启用状态筛选 Tab：横向滚动胶囊（全部/启用/禁用） */
  @Builder
  buildActiveFilter() {
    Scroll() {
      Row({ space: 8 }) {
        ForEach(ACTIVE_FILTERS, (opt: ActiveFilterOption) => {
          Text(opt.label)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.filterActive === opt.value
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.filterActive === opt.value
              ? this.sm.getColor('primary')
              : Color.Transparent)
            .onClick(() => { this.handleActiveFilter(opt.value); })
        }, (opt: ActiveFilterOption) => opt.value)
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

  /** 单个用户卡片：启用状态灯 + username + email + role 徽章 + 最近登录 */
  @Builder
  buildUserCard(user: AdminUserDto) {
    GlassCard() {
      Column() {
        // 顶部行：启用状态灯 + username + email + role 徽章
        Row() {
          // 启用状态灯
          Text(EnhancedUserViewHelper.getActiveIcon(user.active))
            .fontSize(14)
            .margin({ right: 6 })

          Column() {
            Text(user.username)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
            Text(user.email)
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

        // 底部行：启用状态 + 最近登录
        Row() {
          Text(EnhancedUserViewHelper.getActiveLabel(user.active))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(EnhancedUserViewHelper.getActiveColor(user.active)))
            .margin({ right: this.sm.getSpacing('sm') })

          Text(`最近登录：${EnhancedUserViewHelper.formatLastActive(user.last_login)}`)
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
  }

  // ===========================================================================
  // 详情弹窗构建器（Stack 内嵌条件渲染，不单独建文件）
  // ===========================================================================

  /** 用户详情弹窗：完整字段展示 */
  @Builder
  buildDetailDialog(user: AdminUserDto) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetailDialog(); })

      // 面板层：居中展示（GlassPanel 为自定义组件，不能直接链 .width/.height；90%/70% 挂在外层 Column）
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Scroll() {
          Column() {
            Text('用户详情')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')
              .margin({ bottom: this.sm.getSpacing('sm') })

            // 启用状态
            Text('状态')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`${EnhancedUserViewHelper.getActiveIcon(user.active)} ${EnhancedUserViewHelper.getActiveLabel(user.active)}`)
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor(EnhancedUserViewHelper.getActiveColor(user.active)))
              .width('100%')
              .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

            // 用户名
            Text('用户名')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(user.username)
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

            // 创建时间 + 最近登录
            Text(`创建时间：${user.created_at.length > 0 ? user.created_at : '—'}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
            Text(`最近登录：${EnhancedUserViewHelper.formatLastActive(user.last_login)}`)
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
            btnSize: 'medium',
            onTap: () => { this.closeDetailDialog(); }
          })
        }
        .width('100%')
        .justifyContent(FlexAlign.End)
        .margin({ top: this.sm.getSpacing('sm') })
      }
      }
      .width('90%')
      .height('70%')
    }
    .width('100%')
    .height('100%')
  }
}
