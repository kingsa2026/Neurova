/**
 * GroupPage - 用户组管理页
 *
 * 职责：展示用户组列表，成员数显示，组属主展示，新建按钮
 * 设计：
 *   - GroupViewHelper（导出）：纯视图模型，封装成员数格式化、描述截断（默认 80），
 *     无 UI 依赖，可独立单元测试；
 *   - GroupPage（@Component）：Stack [主内容列] + [新建弹窗]
 *     主内容列：TopNavMenu(标题"用户组"+返回+新建) + [加载态/空态/列表]；
 *     列表项 GlassCard：name、description、members_count、owner_id；
 *     新建弹窗：Stack 内嵌条件渲染（不单独建 CustomDialog 文件），
 *     含 name 输入、description 输入；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router；
 *   - P1-33 已接线 PageMap；数据走 api.admin.listGroups / createGroup
 *     （后端 /v1/groups，GroupInfo 投影：group_id/name/description/owner_id/
 *     members/members_count）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（admin 域）
 *   - ../libs/api/modules/AdminApi：AdminGroupDto 类型
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push(RouteNames.GROUP) 跳转进入；
 *   aboutToAppear 经 api.admin.listGroups() 加载真实用户组列表；
 *   新建按钮 → 弹窗填写 name/description → 提交 → api.admin.createGroup。
 *
 * TDD：GroupViewHelper 各方法按红绿灯垂直切片逐步实现，详见 GroupPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AdminGroupDto } from '../libs/api/modules/AdminApi';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';

/** 日志标签 */
const TAG = 'GroupPage';

/** 描述截断默认最大长度 */
const DEFAULT_DESC_MAX_LEN = 80;

// ===========================================================================
// GroupViewHelper - 用户组视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class GroupViewHelper {
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

@Component
export struct GroupPage {
  // 用户组列表
  @State groups: AdminGroupDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: GroupFormData = { name: '', description: '' };

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
   * 加载用户组列表（/v1/groups，裸数组）
   */
  private async loadGroups(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.listGroups();
      this.groups = res;
    } catch (e) {
      this.logger.error(TAG, '加载用户组失败', e as Error);
      this.msg.error('加载用户组列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { name: '', description: '' };
    this.showCreateDialog = true;
  }

  /** 输入 name（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { name: v, description: this.formData.description };
  }

  /** 输入 description（嵌套属性变更：整体重新赋值） */
  private inputDescription(v: string): void {
    this.formData = { name: this.formData.name, description: v };
  }

  /**
   * 提交新建（POST /v1/groups，GroupCreate {name, description}）
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写名称');
      return;
    }
    try {
      const res = await this.api.admin.createGroup(
        this.formData.name.trim(),
        this.formData.description.trim(),
      );
      if (res.code === 0) {
        this.msg.success('已创建');
        this.showCreateDialog = false;
        await this.loadGroups();
      } else {
        this.msg.error(res.message || '创建用户组失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建用户组失败', e as Error);
      this.msg.error('创建用户组失败');
    }
  }

  /**
   * 点击列表项（编辑流程后端未提供，诚实提示）
   */
  private handleItemClick(group: AdminGroupDto): void {
    this.msg.info(`用户组：${group.name}（成员 ${group.members_count} 人）`);
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
            btnSize: 'small',
            onTap: () => { this.openCreateDialog(); }
          })
        }

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
        } else if (this.groups.length === 0) {
          Column() {
            Text('暂无用户组')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '新建用户组',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.openCreateDialog(); }
            })
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.groups, (group: AdminGroupDto) => {
              ListItem() {
                this.buildGroupCard(group)
              }
            }, (group: AdminGroupDto) => group.group_id)
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
  // 用户组卡片构建器
  // ===========================================================================

  /** 单个用户组卡片：name + description + members_count + owner_id */
  @Builder
  buildGroupCard(group: AdminGroupDto) {
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
            Text(GroupViewHelper.formatMemberCount(group.members_count))
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

        // 底部行：属主
        if (group.owner_id) {
          Text(`属主：${group.owner_id}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: this.sm.getSpacing('xs') })
            .width('100%')
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
    }
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

      // 面板层：居中展示（GlassPanel 为自定义组件，不能直接链 .width；90% 挂在外层 Column）
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
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
              btnSize: 'medium',
              onTap: () => { this.showCreateDialog = false; }
            })
            GlassButton({
              text: '创建',
              type: 'primary',
              btnSize: 'medium',
              onTap: () => { this.submitCreate(); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          .width('100%')
          .justifyContent(FlexAlign.End)
        }
        .width('100%')
        .alignItems(HorizontalAlign.Start)
      }
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
