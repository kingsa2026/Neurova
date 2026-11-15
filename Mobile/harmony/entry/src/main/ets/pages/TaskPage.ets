/**
 * TaskPage - 任务页
 *
 * 职责：展示任务列表，按 status 和 priority 双重筛选，支持新建/编辑/删除
 * 设计：
 *   - TaskViewHelper（导出）：纯视图模型，封装任务状态颜色/图标/标签映射、
 *     优先级颜色/图标/标签映射、标签格式化、日期格式化，无 UI 运行时依赖，可独立单元测试；
 *   - TaskPage（@Component）：Stack[Column[TopNavMenu(标题"任务"+返回+新建)]
 *     + [status 筛选 Tab（全部/todo/in_progress/review/done/blocked）]
 *     + [priority 筛选 Tab（全部/low/medium/high/urgent）]
 *     + [加载态/空态/列表] + [新建弹窗]]；
 *     列表项 GlassCard 含 title、description 摘要、status 徽章、priority 徽章、
 *     assignee、dueDate、tags、操作按钮（编辑/删除）；
 *     删除走 AlertDialog 二次确认；新建走 CustomDialog
 *     （title 输入 + projectId 选择 + description 文本域 + priority 选择 +
 *     assignee 输入 + dueDate 日期 + tags 多行）；
 *     弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.collaboration，消息走 MessageManager
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（collaboration.listTasks/getTask/
 *     createTask/updateTask/removeTask）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Task、TaskStatus、TaskPriority
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.collaboration.listTasks 加载列表；
 *   status/priority 双重筛选 Tab 切换 → 本地 filterTasks 过滤；
 *   新建按钮 → 打开 CustomDialog → 调用 api.collaboration.createTask → 刷新列表；
 *   编辑按钮 → 提示"功能开发中"（占位）；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.collaboration.removeTask → 刷新列表
 *
 * TDD：TaskViewHelper 各方法按红绿灯垂直切片逐步实现，详见 TaskPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Task, TaskStatus, TaskPriority } from '../libs/types';

/** 日志标签 */
const TAG = 'TaskPage';

// ===========================================================================
// TaskViewHelper - 任务视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class TaskViewHelper {
  /**
   * 获取任务状态对应的颜色 token 名
   * 映射：todo→text_secondary, in_progress→info, review→warning,
   *       done→success, blocked→error
   * @param status 任务状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: TaskStatus): string {
    if (status === 'todo') return 'text_secondary';
    if (status === 'in_progress') return 'info';
    if (status === 'review') return 'warning';
    if (status === 'done') return 'success';
    return 'error';
  }

  /**
   * 获取任务状态对应的图标 emoji
   * 映射：todo→📋, in_progress→⚡, review→🔍, done→✅, blocked→🚫
   * @param status 任务状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: TaskStatus): string {
    if (status === 'todo') return '📋';
    if (status === 'in_progress') return '⚡';
    if (status === 'review') return '🔍';
    if (status === 'done') return '✅';
    return '🚫';
  }

  /**
   * 获取任务状态对应的中文标签
   * 映射：todo→待办, in_progress→进行中, review→审核中,
   *       done→已完成, blocked→已阻塞
   * @param status 任务状态
   * @return 中文标签
   */
  static getStatusLabel(status: TaskStatus): string {
    if (status === 'todo') return '待办';
    if (status === 'in_progress') return '进行中';
    if (status === 'review') return '审核中';
    if (status === 'done') return '已完成';
    return '已阻塞';
  }

  /**
   * 获取任务优先级对应的颜色 token 名
   * 映射：low→text_secondary, medium→info, high→warning, urgent→error
   * @param priority 任务优先级
   * @return StyleManager 颜色 token 名
   */
  static getPriorityColor(priority: TaskPriority): string {
    if (priority === 'low') return 'text_secondary';
    if (priority === 'medium') return 'info';
    if (priority === 'high') return 'warning';
    return 'error';
  }

  /**
   * 获取任务优先级对应的图标 emoji
   * 映射：low→⬇️, medium→➡️, high→⬆️, urgent→🚨
   * @param priority 任务优先级
   * @return emoji 字符串
   */
  static getPriorityIcon(priority: TaskPriority): string {
    if (priority === 'low') return '⬇️';
    if (priority === 'medium') return '➡️';
    if (priority === 'high') return '⬆️';
    return '🚨';
  }

  /**
   * 获取任务优先级对应的中文标签
   * 映射：low→低, medium→中, high→高, urgent→紧急
   * @param priority 任务优先级
   * @return 中文标签
   */
  static getPriorityLabel(priority: TaskPriority): string {
    if (priority === 'low') return '低';
    if (priority === 'medium') return '中';
    if (priority === 'high') return '高';
    return '紧急';
  }

  /**
   * 格式化标签数组为文案
   * 规则：空数组 → "无标签"，非空 → 以 " · " 连接
   * @param tags 标签数组
   * @return 标签文案
   */
  static formatTags(tags: string[]): string {
    if (!tags || tags.length === 0) return '无标签';
    return tags.join(' · ');
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
}

/** 筛选 Tab 配置 */
interface FilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表（全部/todo/in_progress/review/done/blocked） */
const STATUS_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'todo', label: '待办' },
  { value: 'in_progress', label: '进行中' },
  { value: 'review', label: '审核中' },
  { value: 'done', label: '已完成' },
  { value: 'blocked', label: '已阻塞' },
];

/** 优先级筛选 Tab 列表（全部/low/medium/high/urgent） */
const PRIORITY_FILTERS: FilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'urgent', label: '紧急' },
];

/** 全部优先级选项（用于新建弹窗选择） */
const PRIORITY_OPTIONS: TaskPriority[] = ['low', 'medium', 'high', 'urgent'];

/** 新建任务表单数据 */
interface TaskFormData {
  title: string;
  projectId: string;
  description: string;
  priority: TaskPriority;
  assignee: string;
  dueDate: string;
  tagsText: string;
}

@Component
export struct TaskPage {
  // 任务列表
  @State tasks: Task[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选值
  @State activeStatus: string = 'all';
  // 当前激活的优先级筛选值
  @State activePriority: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: TaskFormData = {
    title: '',
    projectId: '',
    description: '',
    priority: 'medium' as TaskPriority,
    assignee: '',
    dueDate: '',
    tagsText: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTasks();
  }

  /**
   * 加载任务列表
   * 流程：调用 api.collaboration.listTasks → 写入 tasks
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadTasks(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listTasks();
      if (res.code === 0 && res.data) {
        this.tasks = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载任务失败', e as Error);
      this.msg.error('加载任务列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 Tab */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /** 切换优先级筛选 Tab */
  private switchPriority(value: string): void {
    this.activePriority = value;
  }

  /**
   * 获取经状态+优先级双重筛选后的列表
   */
  private getFilteredList(): Task[] {
    let result = this.tasks;
    if (this.activeStatus !== 'all') {
      result = result.filter((t: Task) => t.status === this.activeStatus);
    }
    if (this.activePriority !== 'all') {
      result = result.filter((t: Task) => t.priority === this.activePriority);
    }
    return result;
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.formData = {
      title: '',
      projectId: '',
      description: '',
      priority: 'medium' as TaskPriority,
      assignee: '',
      dueDate: '',
      tagsText: '',
    };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 api.collaboration.createTask → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.title) {
      this.msg.warning('请填写任务标题');
      return;
    }
    if (!this.formData.projectId) {
      this.msg.warning('请选择所属项目');
      return;
    }
    try {
      // tags 多行文本按换行拆分为数组
      const tags = this.formData.tagsText
        .split('\n')
        .map((s: string) => s.trim())
        .filter((s: string) => s.length > 0);
      const data: Partial<Task> = {
        projectId: this.formData.projectId,
        title: this.formData.title,
        description: this.formData.description,
        status: 'todo' as TaskStatus,
        priority: this.formData.priority,
        assignee: this.formData.assignee || undefined,
        dueDate: this.formData.dueDate || undefined,
        tags,
      };
      const res = await this.api.collaboration.createTask(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadTasks();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建任务失败', e as Error);
      this.msg.error('创建任务失败');
    }
  }

  /** 编辑任务（占位，提示开发中） */
  private handleEdit(task: Task): void {
    this.msg.info('功能开发中');
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(task: Task): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除任务"${task.title}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteTask(task.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.collaboration.removeTask → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteTask(taskId: string): Promise<void> {
    try {
      const res = await this.api.collaboration.removeTask(taskId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadTasks();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除任务失败', e as Error);
      this.msg.error('删除任务失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"任务" + 返回按钮 + 新建按钮
        TopNavMenu({
          title: '任务',
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
            ForEach(STATUS_FILTERS, (opt: FilterOption) => {
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
            }, (opt: FilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 优先级筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(PRIORITY_FILTERS, (opt: FilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activePriority === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activePriority === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchPriority(opt.value); })
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
            Text('暂无任务')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (task: Task) => {
              ListItem() {
                this.buildTaskCard(task)
              }
            }, (task: Task) => task.id)
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
  // 任务卡片构建器
  // ===========================================================================

  /** 单个任务卡片：状态/优先级徽章 + 标题 + 描述摘要 + assignee/dueDate/tags + 操作按钮 */
  @Builder
  buildTaskCard(task: Task) {
    GlassCard() {
      Column() {
        // 上部：状态徽章 + 优先级徽章
        Row() {
          // 状态徽章
          Row() {
            Text(TaskViewHelper.getStatusIcon(task.status))
              .fontSize(14)
            Text(TaskViewHelper.getStatusLabel(task.status))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(TaskViewHelper.getStatusColor(task.status)))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor('surface'))

          // 优先级徽章
          Row() {
            Text(TaskViewHelper.getPriorityIcon(task.priority))
              .fontSize(14)
            Text(TaskViewHelper.getPriorityLabel(task.priority))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(TaskViewHelper.getPriorityColor(task.priority)))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor('surface'))
          .margin({ left: 8 })
        }
        .alignItems(VerticalAlign.Center)

        // 标题
        Text(task.title)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 描述摘要（截断 80 字符）
        Text(task.description ? (task.description.length > 80
          ? task.description.substring(0, 80) + '...'
          : task.description) : '—')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 底部行：assignee · dueDate · tags
        Row() {
          Text(`负责人：${task.assignee || '—'}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(`截止：${TaskViewHelper.formatDate(task.dueDate)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(TaskViewHelper.formatTags(task.tags))
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
            onClick: () => { this.handleEdit(task); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(task); }
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

  /** 新建任务弹窗：title + projectId + description + priority + assignee + dueDate + tags */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层（可滚动）
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Scroll() {
          Column() {
            Text('新建任务')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')

            // 标题
            Text('标题')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '请输入任务标题',
              value: this.formData.title,
              type: 'text',
              onChange: (v: string) => { this.formData = { ...this.formData, title: v }; }
            })
              .margin({ top: 4 })

            // 所属项目
            Text('所属项目 ID')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '请输入 projectId',
              value: this.formData.projectId,
              type: 'text',
              onChange: (v: string) => { this.formData = { ...this.formData, projectId: v }; }
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

            // 优先级选择
            Text('优先级')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            Row({ space: 4 }) {
              ForEach(PRIORITY_OPTIONS, (p: TaskPriority) => {
                GlassButton({
                  text: `${TaskViewHelper.getPriorityIcon(p)} ${TaskViewHelper.getPriorityLabel(p)}`,
                  type: this.formData.priority === p ? 'primary' : 'default',
                  size: 'small',
                  onClick: () => { this.formData = { ...this.formData, priority: p }; }
                })
              }, (p: TaskPriority) => p)
            }
            .width('100%')
            .margin({ top: 4 })

            // 负责人
            Text('负责人')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '请输入 assignee',
              value: this.formData.assignee,
              type: 'text',
              onChange: (v: string) => { this.formData = { ...this.formData, assignee: v }; }
            })
              .margin({ top: 4 })

            // 截止日期
            Text('截止日期（YYYY-MM-DD）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '2024-12-31',
              value: this.formData.dueDate,
              type: 'text',
              onChange: (v: string) => { this.formData = { ...this.formData, dueDate: v }; }
            })
              .margin({ top: 4 })

            // 标签（多行，每行一个）
            Text('标签（每行一个）')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: 'bug\nfeature\nurgent',
              value: this.formData.tagsText,
              type: 'text',
              onChange: (v: string) => { this.formData = { ...this.formData, tagsText: v }; }
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
        .width('100%')
        .scrollBar(BarState.Off)
      }
      .width('90%')
      .height('85%')
    }
    .width('100%')
    .height('100%')
  }
}
