/**
 * TeamPage - 团队页
 *
 * 职责：展示团队列表，支持新建/编辑/删除/查看成员
 * 设计：
 *   - TeamViewHelper（导出）：纯视图模型，封装角色颜色映射、角色图标映射、角色标签映射、
 *     成员数格式化、角色分布格式化、描述截断，无 UI 运行时依赖，可独立单元测试；
 *   - TeamPage（@Component）：Stack[Column[TopNavMenu(标题"团队"+返回+新建)]
 *     + [加载态/空态/列表] + [详情弹窗] + [新建弹窗]]；
 *     列表项 GlassCard 含 name、description 摘要、成员数（按角色分组）、
 *     操作按钮（查看成员/编辑/删除）；
 *     详情 CustomDialog 展示成员列表（userId + role 徽章）；
 *     新建 CustomDialog 含 name 输入 + description 输入；
 *     弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.collaboration，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（collaboration.listTeams/getTeam/
 *     createTeam/updateTeam/removeTeam）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Team、TeamRole
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.collaboration.listTeams 加载列表；
 *   查看成员按钮 → 弹出详情 CustomDialog 展示成员列表；
 *   新建按钮 → 打开 CustomDialog → 调用 api.collaboration.createTeam → 刷新列表；
 *   编辑按钮 → 提示"功能开发中"（占位）；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.collaboration.removeTeam → 刷新列表
 *
 * TDD：TeamViewHelper 各方法按红绿灯垂直切片逐步实现，详见 TeamPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Team, TeamRole } from '../libs/types';

/** 日志标签 */
const TAG = 'TeamPage';

/** 默认截断长度 */
const DEFAULT_TRUNCATE_LEN = 80;

// ===========================================================================
// TeamViewHelper - 团队视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'primary'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class TeamViewHelper {
  /**
   * 获取团队角色对应的颜色 token 名
   * 映射：owner→primary, admin→info, member→success, viewer→text_secondary
   * @param role 团队角色
   * @return StyleManager 颜色 token 名
   */
  static getRoleColor(role: TeamRole): string {
    if (role === 'owner') return 'primary';
    if (role === 'admin') return 'info';
    if (role === 'member') return 'success';
    return 'text_secondary';
  }

  /**
   * 获取团队角色对应的图标 emoji
   * 映射：owner→👑, admin→🛡️, member→👤, viewer→👀
   * @param role 团队角色
   * @return emoji 字符串
   */
  static getRoleIcon(role: TeamRole): string {
    if (role === 'owner') return '👑';
    if (role === 'admin') return '🛡️';
    if (role === 'member') return '👤';
    return '👀';
  }

  /**
   * 获取团队角色对应的中文标签
   * 映射：owner→所有者, admin→管理员, member→成员, viewer→观察者
   * @param role 团队角色
   * @return 中文标签
   */
  static getRoleLabel(role: TeamRole): string {
    if (role === 'owner') return '所有者';
    if (role === 'admin') return '管理员';
    if (role === 'member') return '成员';
    return '观察者';
  }

  /**
   * 格式化成员数为文案
   * 规则：0 → "无成员"，正数 → "成员 n 人"
   * @param count 成员数
   * @return 成员数文案
   */
  static formatMemberCount(count: number): string {
    if (count <= 0) return '无成员';
    return `成员 ${count} 人`;
  }

  /**
   * 格式化成员角色分布
   * 规则：按 owner/admin/member/viewer 顺序统计，无成员的角色不显示
   * 格式："owner:1 · admin:2 · member:5 · viewer:1"
   * @param members 成员列表
   * @return 角色分布字符串，空列表返回空字符串
   */
  static formatRoleDistribution(members: Array<{ userId: string; role: TeamRole }>): string {
    if (!members || members.length === 0) return '';
    const order: TeamRole[] = ['owner', 'admin', 'member', 'viewer'];
    const counts: Record<string, number> = { owner: 0, admin: 0, member: 0, viewer: 0 };
    for (const m of members) {
      counts[m.role] = (counts[m.role] || 0) + 1;
    }
    const parts: string[] = [];
    for (const role of order) {
      if (counts[role] > 0) {
        parts.push(`${role}:${counts[role]}`);
      }
    }
    return parts.join(' · ');
  }

  /**
   * 截断描述文本
   * 规则：
   *   - desc 为 undefined 或空字符串 → 返回 "—"
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param desc 描述文本
   * @param maxLen 最大长度，默认 80
   * @return 截断后的描述
   */
  static truncateDescription(desc?: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!desc || desc.length === 0) return '—';
    if (desc.length <= len) return desc;
    return desc.substring(0, len) + '...';
  }
}

/** 新建团队表单数据 */
interface TeamFormData {
  name: string;
  description: string;
}

@Component
export struct TeamPage {
  // 团队列表
  @State teams: Team[] = [];
  // 加载态
  @State loading: boolean = true;
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: TeamFormData = {
    name: '',
    description: '',
  };
  // 详情弹窗显示状态（查看成员）
  @State showDetailDialog: boolean = false;
  // 详情弹窗当前选中的团队
  @State selectedTeam: Team | null = null;

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTeams();
  }

  /**
   * 加载团队列表
   * 流程：调用 api.collaboration.listTeams → 写入 teams
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadTeams(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listTeams();
      if (res.code === 0 && res.data) {
        this.teams = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载团队失败', e as Error);
      this.msg.error('加载团队列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.formData = { name: '', description: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 api.collaboration.createTeam → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写团队名称');
      return;
    }
    try {
      const data: Partial<Team> = {
        name: this.formData.name,
        description: this.formData.description,
        members: [],
      };
      const res = await this.api.collaboration.createTeam(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadTeams();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建团队失败', e as Error);
      this.msg.error('创建团队失败');
    }
  }

  /** 打开详情弹窗（查看成员） */
  private openDetail(team: Team): void {
    this.selectedTeam = team;
    this.showDetailDialog = true;
  }

  /** 关闭详情弹窗 */
  private closeDetail(): void {
    this.showDetailDialog = false;
    this.selectedTeam = null;
  }

  /** 编辑团队（占位，提示开发中） */
  private handleEdit(team: Team): void {
    this.msg.info('功能开发中');
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(team: Team): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除团队"${team.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteTeam(team.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.collaboration.removeTeam → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteTeam(teamId: string): Promise<void> {
    try {
      const res = await this.api.collaboration.removeTeam(teamId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadTeams();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除团队失败', e as Error);
      this.msg.error('删除团队失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"团队" + 返回按钮 + 新建按钮
        TopNavMenu({
          title: '团队',
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
        } else if (this.teams.length === 0) {
          Column() {
            Text('暂无团队')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.teams, (team: Team) => {
              ListItem() {
                this.buildTeamCard(team)
              }
            }, (team: Team) => team.id)
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

      // 详情弹窗（查看成员）：内嵌 Stack 条件渲染
      if (this.showDetailDialog && this.selectedTeam) {
        this.buildDetailDialog(this.selectedTeam)
      }

      // 新建弹窗：内嵌 Stack 条件渲染
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 团队卡片构建器
  // ===========================================================================

  /** 单个团队卡片：名称 + 描述摘要 + 成员数（按角色分组）+ 操作按钮 */
  @Builder
  buildTeamCard(team: Team) {
    GlassCard() {
      Column() {
        // 名称
        Text(team.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })

        // 描述摘要（截断 80 字符）
        Text(TeamViewHelper.truncateDescription(team.description, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 成员数 + 角色分布
        Row() {
          Text(TeamViewHelper.formatMemberCount(team.members ? team.members.length : 0))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          if (team.members && team.members.length > 0) {
            Text('·')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .margin({ left: 6, right: 6 })
            Text(TeamViewHelper.formatRoleDistribution(team.members))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_disabled'))
              .layoutWeight(1)
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })
          }
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看成员/编辑/删除（右对齐）
        Row() {
          GlassButton({
            text: '查看成员',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetail(team); }
          })
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.handleEdit(team); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(team); }
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
  // 详情弹窗构建器（查看成员）
  // ===========================================================================

  /** 成员详情弹窗：成员列表（userId + role 徽章） */
  @Builder
  buildDetailDialog(team: Team) {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDetail(); })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题
          Text(team.name)
            .fontSize(this.sm.getFontSize('title'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          Text('成员列表')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: 4 })

          // 成员列表（可滚动）
          Scroll() {
            Column({ space: 8 }) {
              if (team.members && team.members.length > 0) {
                ForEach(team.members, (m: { userId: string; role: TeamRole }) => {
                  Row() {
                    Text(TeamViewHelper.getRoleIcon(m.role))
                      .fontSize(16)
                      .width(24)
                    Text(m.userId)
                      .fontSize(this.sm.getFontSize('body'))
                      .fontColor(this.sm.getColor('text_primary'))
                      .layoutWeight(1)
                      .maxLines(1)
                      .textOverflow({ overflow: TextOverflow.Ellipsis })
                      .margin({ left: 4 })
                    Text(TeamViewHelper.getRoleLabel(m.role))
                      .fontSize(this.sm.getFontSize('caption'))
                      .fontColor(this.sm.getColor('text_on_primary'))
                      .padding({ left: 8, right: 8, top: 2, bottom: 2 })
                      .borderRadius(10)
                      .backgroundColor(this.sm.getColor(TeamViewHelper.getRoleColor(m.role)))
                  }
                  .width('100%')
                  .alignItems(VerticalAlign.Center)
                }, (m: { userId: string; role: TeamRole }) => `${m.userId}_${m.role}`)
              } else {
                Text('暂无成员')
                  .fontSize(this.sm.getFontSize('body'))
                  .fontColor(this.sm.getColor('text_secondary'))
              }
            }
            .width('100%')
            .alignItems(HorizontalAlign.Start)
            .padding({ top: 8 })
          }
          .layoutWeight(1)
          .width('100%')
          .margin({ top: 8 })

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

  // ===========================================================================
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建团队弹窗：name 输入 + description 输入 */
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
          Text('新建团队')
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
            placeholder: '请输入团队名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4 })

          // 描述
          Text('描述')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入描述',
            value: this.formData.description,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, description: v }; }
          })
            .margin({ top: 4 })

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
