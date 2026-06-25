/**
 * ProjectPage - 项目页
 *
 * 职责：展示项目列表，按 status 筛选，支持新建/编辑/删除
 * 设计：
 *   - ProjectViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标映射、状态标签映射、
 *     成员数格式化、日期格式化、描述截断，无 UI 运行时依赖，可独立单元测试；
 *   - ProjectPage（@Component）：Stack[Column[TopNavMenu(标题"项目"+返回+新建)]
 *     + [status 筛选 Tab（全部/planning/active/paused/completed/archived）]
 *     + [加载态/空态/列表] + [新建弹窗]]；
 *     列表项 GlassCard 含 name、description 摘要、status 徽章、owner、members 数、
 *     startDate、endDate、操作按钮（编辑/删除）；
 *     删除走 AlertDialog 二次确认；新建走 CustomDialog
 *     （name 输入 + description 文本域 + startDate 日期 + endDate 日期）；
 *     新建弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.collaboration，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（collaboration.listProjects/getProject/
 *     createProject/updateProject/removeProject）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Project、ProjectStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.collaboration.listProjects 加载列表；
 *   status 筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   新建按钮 → 打开 CustomDialog → 调用 api.collaboration.createProject → 刷新列表；
 *   编辑按钮 → 提示"功能开发中"（占位）；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.collaboration.removeProject → 刷新列表
 *
 * TDD：ProjectViewHelper 各方法按红绿灯垂直切片逐步实现，详见 ProjectPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Project, ProjectStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'ProjectPage';

/** 默认截断长度（项目页为 100 字符） */
const DEFAULT_TRUNCATE_LEN = 100;

// ===========================================================================
// ProjectViewHelper - 项目视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ProjectViewHelper {
  /**
   * 获取项目状态对应的颜色 token 名
   * 映射：planning→warning, active→success, paused→text_secondary,
   *       completed→info, archived→text_disabled
   * @param status 项目状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: ProjectStatus): string {
    if (status === 'planning') return 'warning';
    if (status === 'active') return 'success';
    if (status === 'paused') return 'text_secondary';
    if (status === 'completed') return 'info';
    return 'text_disabled';
  }

  /**
   * 获取项目状态对应的图标 emoji
   * 映射：planning→📝, active→▶️, paused→⏸️, completed→✅, archived→📦
   * @param status 项目状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: ProjectStatus): string {
    if (status === 'planning') return '📝';
    if (status === 'active') return '▶️';
    if (status === 'paused') return '⏸️';
    if (status === 'completed') return '✅';
    return '📦';
  }

  /**
   * 获取项目状态对应的中文标签
   * 映射：planning→规划中, active→进行中, paused→已暂停,
   *       completed→已完成, archived→已归档
   * @param status 项目状态
   * @return 中文标签
   */
  static getStatusLabel(status: ProjectStatus): string {
    if (status === 'planning') return '规划中';
    if (status === 'active') return '进行中';
    if (status === 'paused') return '已暂停';
    if (status === 'completed') return '已完成';
    return '已归档';
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
   * 格式化 ISO 日期字符串为 YYYY-MM-DD
   * 规则：无值或无效 → "—"
   * @param date ISO 日期字符串
   * @return YYYY-MM-DD 格式或 "—"
   */
  static formatDate(date?: string): string {
    if (!date || date.length === 0) return '—';
    const d = new Date(date);
    if (isNaN(d.getTime())) return '—';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd}`;
  }

  /**
   * 截断描述文本
   * 规则：
   *   - desc 为空字符串 → 返回 "—"
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param desc 描述文本
   * @param maxLen 最大长度，默认 100
   * @return 截断后的描述
   */
  static truncateDescription(desc: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!desc || desc.length === 0) return '—';
    if (desc.length <= len) return desc;
    return desc.substring(0, len) + '...';
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表（全部/planning/active/paused/completed/archived） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'planning', label: '规划中' },
  { value: 'active', label: '进行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'archived', label: '已归档' },
];

/** 新建项目表单数据 */
interface ProjectFormData {
  name: string;
  description: string;
  startDate: string;
  endDate: string;
}

@Component
export struct ProjectPage {
  // 项目列表
  @State projects: Project[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选值
  @State activeStatus: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: ProjectFormData = {
    name: '',
    description: '',
    startDate: '',
    endDate: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadProjects();
  }

  /**
   * 加载项目列表
   * 流程：调用 api.collaboration.listProjects → 写入 projects
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadProjects(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listProjects();
      if (res.code === 0 && res.data) {
        this.projects = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载项目失败', e as Error);
      this.msg.error('加载项目列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 Tab */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /** 获取经状态筛选后的列表 */
  private getFilteredList(): Project[] {
    if (this.activeStatus === 'all') {
      return this.projects;
    }
    return this.projects.filter((p: Project) => p.status === this.activeStatus);
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.formData = { name: '', description: '', startDate: '', endDate: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 api.collaboration.createProject → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写项目名称');
      return;
    }
    try {
      const data: Partial<Project> = {
        name: this.formData.name,
        description: this.formData.description,
        status: 'planning' as ProjectStatus,
        owner: '',
        members: [],
        startDate: this.formData.startDate || undefined,
        endDate: this.formData.endDate || undefined,
      };
      const res = await this.api.collaboration.createProject(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadProjects();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建项目失败', e as Error);
      this.msg.error('创建项目失败');
    }
  }

  /** 编辑项目（占位，提示开发中） */
  private handleEdit(project: Project): void {
    this.msg.info('功能开发中');
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(project: Project): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除项目"${project.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteProject(project.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.collaboration.removeProject → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteProject(projectId: string): Promise<void> {
    try {
      const res = await this.api.collaboration.removeProject(projectId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadProjects();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除项目失败', e as Error);
      this.msg.error('删除项目失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"项目" + 返回按钮 + 新建按钮
        TopNavMenu({
          title: '项目',
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
            Text('暂无项目')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (project: Project) => {
              ListItem() {
                this.buildProjectCard(project)
              }
            }, (project: Project) => project.id)
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

      // 新建弹窗：内嵌 Stack 条件渲染
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 项目卡片构建器
  // ===========================================================================

  /** 单个项目卡片：状态徽章 + 名称 + 描述摘要 + owner/members/日期 + 操作按钮 */
  @Builder
  buildProjectCard(project: Project) {
    GlassCard() {
      Column() {
        // 状态徽章：图标 + 文案 + 圆点
        Row() {
          Text(ProjectViewHelper.getStatusIcon(project.status))
            .fontSize(16)
          Text(ProjectViewHelper.getStatusLabel(project.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(ProjectViewHelper.getStatusColor(project.status)))
            .margin({ left: 4 })
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(ProjectViewHelper.getStatusColor(project.status)))
            .margin({ left: 6 })
        }
        .alignItems(VerticalAlign.Center)

        // 名称
        Text(project.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 描述摘要（截断 100 字符）
        Text(ProjectViewHelper.truncateDescription(project.description, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 底部行：owner · members · startDate · endDate
        Row() {
          Text(`负责人：${project.owner || '—'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(ProjectViewHelper.formatMemberCount(project.members ? project.members.length : 0))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`${ProjectViewHelper.formatDate(project.startDate)} → ${ProjectViewHelper.formatDate(project.endDate)}`)
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

        // 操作按钮：编辑/删除（右对齐）
        Row() {
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.handleEdit(project); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(project); }
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
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建项目弹窗：name + description + startDate + endDate */
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
          Text('新建项目')
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
            placeholder: '请输入项目名称',
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

          // 开始日期
          Text('开始日期（YYYY-MM-DD）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '2024-06-15',
            value: this.formData.startDate,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, startDate: v }; }
          })
            .margin({ top: 4 })

          // 结束日期
          Text('结束日期（YYYY-MM-DD）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '2024-12-31',
            value: this.formData.endDate,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, endDate: v }; }
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
