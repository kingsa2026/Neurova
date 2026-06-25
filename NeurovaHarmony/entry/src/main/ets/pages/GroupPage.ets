/**
 * GroupPage - 用户组管理页
 *
 * 职责：展示用户组列表（按权限筛选），成员数显示，组长展示，新建按钮，点击项进入编辑
 * 设计：
 *   - GroupViewHelper（导出）：纯视图模型，封装角色颜色映射、角色图标、角色中文标签、
 *     成员数格式化、权限列表格式化（最多显示 2 个 + 总数）、描述截断（默认 80），
 *     无 UI 依赖，可独立单元测试；
 *   - GroupPage（@Component）：Stack [主内容列] + [新建弹窗]
 *     主内容列：TopNavMenu(标题"用户组"+返回+新建) + [权限筛选 Tab] + [加载态/空态/列表]；
 *     列表项 GlassCard：name、description、memberCount、permissions、leader；
 *     新建弹窗：Stack 内嵌条件渲染（不单独建 CustomDialog 文件），
 *     含 name 输入、description 输入；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 暂无用户组专用模块 → aboutToAppear 加载 mock 静态数据 + TODO M6 接入真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：UserGroup
 *
 * 用法：
 *   由 Router.push(RouteNames.GROUP) 跳转进入；
 *   aboutToAppear 加载 mock 用户组列表（TODO M6 接入真实 API api.userGroups.*）；
 *   权限筛选 Tab 切换 → 本地 filterPermission 过滤；
 *   点击列表项 → 进入编辑（TODO M6 接入编辑流程）；
 *   新建按钮 → 弹窗填写 name/description → 提交 → TODO M6 接入 API。
 *
 * TDD：GroupViewHelper 各方法按红绿灯垂直切片逐步实现，详见 GroupPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { UserGroup } from '../libs/types';

/** 日志标签 */
const TAG = 'GroupPage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 80;

/** 全部角色（用于筛选 Tab 顺序） */
const ALL_ROLES: string[] = ['admin', 'developer', 'operator', 'viewer', 'guest'];

// ===========================================================================
// GroupViewHelper - 用户组视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'error'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class GroupViewHelper {
  /**
   * 获取角色对应的颜色 token 名
   * 映射：admin→error, developer→primary, operator→info, viewer→text_secondary, guest→warning
   * 未知角色 → text_secondary（默认）
   * @param role 角色标识
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
   * 获取角色对应的图标 emoji
   * 映射：admin→👑, developer→💻, operator→⚙️, viewer→👁️, guest→👤
   * 未知角色 → 👤（默认）
   * @param role 角色标识
   * @return emoji 字符串
   */
  static getRoleIcon(role: string): string {
    if (role === 'admin') return '👑';
    if (role === 'developer') return '💻';
    if (role === 'operator') return '⚙️';
    if (role === 'viewer') return '👁️';
    if (role === 'guest') return '👤';
    return '👤';
  }

  /**
   * 获取角色对应的中文标签
   * 映射：admin→管理员, developer→开发者, operator→运营者, viewer→查看者, guest→访客
   * 未知角色 → '未知'（默认）
   * @param role 角色标识
   * @return 中文标签
   */
  static getRoleLabel(role: string): string {
    if (role === 'admin') return '管理员';
    if (role === 'developer') return '开发者';
    if (role === 'operator') return '运营者';
    if (role === 'viewer') return '查看者';
    if (role === 'guest') return '访客';
    return '未知';
  }

  /**
   * 格式化成员数量
   * 规则：0 → "空组"；非零 → "N 人"
   * @param count 成员数量
   * @return 格式化后的成员数文案
   */
  static formatMemberCount(count: number): string {
    if (count === 0) return '空组';
    return `${count} 人`;
  }

  /**
   * 格式化权限列表
   * 规则：空数组 → "无权限"；1 个 → 权限名；多个 → "p1, p2 等 N 项"（最多显示 2 个，N 为总数）
   * @param perms 权限标识数组
   * @return 格式化后的权限文案
   */
  static formatPermissions(perms: string[]): string {
    if (perms.length === 0) return '无权限';
    if (perms.length === 1) return perms[0];
    // 多个：显示前 2 个 + 总数
    const first2 = perms.slice(0, 2).join(', ');
    return `${first2} 等 ${perms.length} 项`;
  }

  /**
   * 截断描述，超长时截取 maxLen 字符并追加省略号
   * @param desc 原始描述
   * @param maxLen 最大字符数，默认 80
   * @return 截断后的描述；未超长则原样返回
   */
  static truncateDescription(desc: string, maxLen: number = DEFAULT_DESC_MAX_LEN): string {
    if (desc.length <= maxLen) return desc;
    return desc.substring(0, maxLen) + '...';
  }
}

/** 新建用户组表单数据 */
interface GroupFormData {
  name: string;
  description: string;
}

/** 默认表单数据 */
const DEFAULT_FORM: GroupFormData = {
  name: '',
  description: '',
};

/**
 * Mock 用户组数据
 * TODO M6 阶段：替换为 api.userGroups.list() 真实 API
 */
const MOCK_GROUPS: UserGroup[] = [
  {
    id: 'group_1',
    name: '管理员组',
    description: '拥有系统全部权限，可管理用户、配置、数据',
    memberCount: 3,
    permissions: ['admin:all', 'user:manage', 'system:config', 'data:export'],
    leader: 'user_1',
    createdAt: '2025-01-01T00:00:00Z',
    updatedAt: '2025-06-01T00:00:00Z',
  },
  {
    id: 'group_2',
    name: '开发者组',
    description: '可访问 API、调试工具、查看日志',
    memberCount: 8,
    permissions: ['api:debug', 'log:read', 'tool:use'],
    leader: 'user_2',
    createdAt: '2025-02-01T00:00:00Z',
    updatedAt: '2025-06-10T00:00:00Z',
  },
  {
    id: 'group_3',
    name: '访客组',
    description: '只读权限，仅可查看公开内容',
    memberCount: 0,
    permissions: [],
    leader: undefined,
    createdAt: '2025-03-01T00:00:00Z',
    updatedAt: '2025-06-15T00:00:00Z',
  },
];

@Component
export struct GroupPage {
  // 用户组列表
  @State groups: UserGroup[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前筛选权限（空串表示全部）
  @State filterPermission: string = '';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: GroupFormData = { ...DEFAULT_FORM };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadGroups();
  }

  /**
   * 加载用户组列表
   * TODO M6 阶段：替换为真实 API（api.userGroups.list）
   */
  private async loadGroups(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.userGroups.list();
      // if (res.code === 0 && res.data) { this.groups = res.data; }
      this.groups = MOCK_GROUPS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载用户组失败', e as Error);
      this.msg.error('加载用户组列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换权限筛选
   * 规则：再次点击同一权限取消筛选；点击不同权限切换筛选
   */
  private handlePermissionFilter(permission: string): void {
    this.filterPermission = this.filterPermission === permission ? '' : permission;
  }

  /**
   * 获取经筛选后的列表
   * 规则：filterPermission 为空 → 全部；否则筛选 permissions 包含该权限的组
   */
  private getFilteredGroups(): UserGroup[] {
    if (!this.filterPermission) return this.groups;
    return this.groups.filter((g: UserGroup) => g.permissions.indexOf(this.filterPermission) >= 0);
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { ...DEFAULT_FORM };
    this.showCreateDialog = true;
  }

  /** 输入 name（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { ...this.formData, name: v };
  }

  /** 输入 description（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { ...this.formData, description: v };
  }

  /**
   * 提交新建
   * TODO M6 阶段：调用真实 API（api.userGroups.create）
   * 当前为本地追加 + TODO 提示
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写名称');
      return;
    }
    try {
      // TODO M6 阶段：const res = await this.api.userGroups.create({...});
      const newGroup: UserGroup = {
        id: `group_${Date.now()}`,
        name: this.formData.name.trim(),
        description: this.formData.description.trim(),
        memberCount: 0,
        permissions: [],
        leader: undefined,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      this.groups = [...this.groups, newGroup];
      this.msg.success('已创建');
      this.showCreateDialog = false;
    } catch (e) {
      this.logger.error(TAG, '创建用户组失败', e as Error);
      this.msg.error('创建用户组失败');
    }
  }

  /**
   * 点击列表项进入编辑
   * TODO M6 阶段：接入真实编辑流程
   */
  private handleItemClick(group: UserGroup): void {
    // TODO M6 阶段：this.router.push(RouteNames.GROUP_EDIT, { id: group.id });
    this.msg.info(`点击了用户组：${group.name}（TODO M6 接入编辑流程）`);
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"用户组" + 返回 + 新建
        TopNavMenu({
          title: '用户组',
          showBack: true,
          showMenu: false,
          onBack: () => { this.router.back(); }
        }) {
          GlassButton({
            text: '新建',
            type: 'primary',
            size: 'small',
            onClick: () => { this.openCreateDialog(); }
          })
        }

        // 权限筛选 Tab（横向滚动胶囊：全部 + 5 角色）
        this.buildPermissionFilter()

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
        } else if (this.getFilteredGroups().length === 0) {
          Column() {
            Text('暂无用户组')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '新建用户组',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.openCreateDialog(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredGroups(), (group: UserGroup) => {
              ListItem() {
                this.buildGroupCard(group)
              }
            }, (group: UserGroup) => group.id)
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

      // 新建用户组弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 权限筛选 Tab 构建器
  // ===========================================================================

  /** 权限筛选 Tab：横向滚动胶囊（全部 + 5 角色） */
  @Builder
  buildPermissionFilter() {
    Scroll() {
      Row({ space: 8 }) {
        // 全部
        Text('全部')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.filterPermission === ''
            ? this.sm.getColor('text_on_primary')
            : this.sm.getColor('text_primary'))
          .padding({ left: 12, right: 12, top: 6, bottom: 6 })
          .borderRadius(16)
          .backgroundColor(this.filterPermission === ''
            ? this.sm.getColor('primary')
            : Color.Transparent)
          .onClick(() => { this.filterPermission = ''; })

        // 5 角色
        ForEach(ALL_ROLES, (role: string) => {
          Text(GroupViewHelper.getRoleLabel(role))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.filterPermission === role
              ? this.sm.getColor('text_on_primary')
              : this.sm.getColor('text_primary'))
            .padding({ left: 12, right: 12, top: 6, bottom: 6 })
            .borderRadius(16)
            .backgroundColor(this.filterPermission === role
              ? this.sm.getColor(GroupViewHelper.getRoleColor(role))
              : Color.Transparent)
            .onClick(() => { this.handlePermissionFilter(role); })
        }, (role: string) => role)
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
  // 用户组卡片构建器
  // ===========================================================================

  /** 单个用户组卡片：name + description + memberCount + permissions + leader */
  @Builder
  buildGroupCard(group: UserGroup) {
    GlassCard() {
      Column() {
        // 顶部行：名称 + 成员数徽章
        Row() {
          Text(group.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          // 成员数徽章
          Row() {
            Text('👥')
              .fontSize(this.sm.getFontSize('caption'))
              .margin({ right: 4 })
            Text(GroupViewHelper.formatMemberCount(group.memberCount))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .alignItems(VerticalAlign.Center)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)
        .onClick(() => { this.handleItemClick(group); })

        // 描述（默认 80 字符截断）
        if (group.description) {
          Text(GroupViewHelper.truncateDescription(group.description))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: this.sm.getSpacing('xs') })
            .width('100%')
        }

        // 底部行：权限 + 组长
        Row() {
          // 权限文案
          Text(GroupViewHelper.formatPermissions(group.permissions))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          // 组长
          if (group.leader) {
            Text(`组长：${group.leader}`)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ left: this.sm.getSpacing('sm') })
          }
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
  // 新建用户组弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建用户组弹窗：name 输入 + description 输入 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建用户组')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 名称
          Text('名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入用户组名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.inputName(v); },
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 描述
          Text('描述')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入描述',
            value: this.formData.description,
            type: 'text',
            onChange: (v: string) => { this.inputDescription(v); },
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '创建',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
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
