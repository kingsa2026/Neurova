/**
 * AgentSchedulerPage - 调度任务页
 *
 * 职责：展示调度任务列表，按 status 筛选，支持新建/删除/手动触发/编辑 cron
 * 设计：
 *   - AgentSchedulerViewHelper（导出）：纯视图模型，封装 status 颜色映射、status 图标映射、
 *     status 中文标签、cron 简化、nextRun/lastRun 格式化；无 UI 运行时依赖，可独立单元测试；
 *   - AgentSchedulerPage（@Component）：Column [TopNavMenu(标题"调度任务"+返回+新建)]
 *     + [status 筛选 Tab（全部/pending/running/completed/failed/cancelled）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含 name、cron 表达式、status 徽章、
 *     lastRunAt、nextRunAt、操作（手动触发/编辑 cron/删除）；
 *     删除走 AlertDialog 二次确认；新建与编辑 cron 走 Stack 条件渲染弹窗；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.runtime，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime.listScheduleTasks/getScheduleTask/
 *     createScheduleTask/updateScheduleTask/removeScheduleTask）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ScheduleTask、ScheduleTaskStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.runtime.listScheduleTasks 加载列表；
 *   status 筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   新建按钮 → Stack 弹窗收集 name/cron/payload → api.runtime.createScheduleTask；
 *   手动触发 → api.runtime.updateScheduleTask(id, { status: 'running' })；
 *   编辑 cron → Stack 弹窗收集新 cron → api.runtime.updateScheduleTask(id, { cron })；
 *   删除 → AlertDialog 二次确认 → api.runtime.removeScheduleTask → 刷新列表
 *
 * TDD：AgentSchedulerViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 AgentSchedulerPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ScheduleTask, ScheduleTaskStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentSchedulerPage';

// ===========================================================================
// AgentSchedulerViewHelper - 调度任务视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentSchedulerViewHelper {
  /**
   * 获取调度任务 status 对应的颜色 token 名
   * 映射：pending→warning，running→info，completed→success，failed→error，cancelled→text_disabled
   * @param status 调度任务状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: ScheduleTaskStatus): string {
    if (status === 'pending') return 'warning';
    if (status === 'running') return 'info';
    if (status === 'completed') return 'success';
    if (status === 'failed') return 'error';
    return 'text_disabled';
  }

  /**
   * 获取调度任务 status 对应的图标 emoji
   * 映射：pending→⏳，running→⚡，completed→✅，failed→❌，cancelled→🚫
   * @param status 调度任务状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: ScheduleTaskStatus): string {
    if (status === 'pending') return '⏳';
    if (status === 'running') return '⚡';
    if (status === 'completed') return '✅';
    if (status === 'failed') return '❌';
    return '🚫';
  }

  /**
   * 获取调度任务 status 的中文标签
   * 映射：pending→待执行，running→运行中，completed→已完成，failed→失败，cancelled→已取消
   * @param status 调度任务状态
   * @return 中文标签字符串
   */
  static getStatusLabel(status: ScheduleTaskStatus): string {
    if (status === 'pending') return '待执行';
    if (status === 'running') return '运行中';
    if (status === 'completed') return '已完成';
    if (status === 'failed') return '失败';
    return '已取消';
  }

  /**
   * 简化 cron 表达式显示：去掉所有空格，超 20 字符截断并追加省略号
   * @param cron 原始 cron 表达式，如 "0 * * * *"
   * @return 简化后的字符串，如 "0****"
   */
  static formatCron(cron: string): string {
    const compact = cron.replace(/\s+/g, '');
    if (compact.length <= 20) return compact;
    return compact.substring(0, 20) + '...';
  }

  /**
   * 格式化 nextRunAt 字符串为带"下次："前缀的展示文本
   * @param nextRunAt ISO 时间字符串，可选
   * @return 无值→"未安排"；有值→"下次：YYYY-MM-DD HH:mm"
   */
  static formatNextRun(nextRunAt?: string): string {
    if (!nextRunAt) return '未安排';
    return `下次：${AgentSchedulerViewHelper.formatDateTime(nextRunAt)}`;
  }

  /**
   * 格式化 lastRunAt 字符串为带"上次："前缀的展示文本
   * @param lastRunAt ISO 时间字符串，可选
   * @return 无值→"未运行"；有值→"上次：YYYY-MM-DD HH:mm"
   */
  static formatLastRun(lastRunAt?: string): string {
    if (!lastRunAt) return '未运行';
    return `上次：${AgentSchedulerViewHelper.formatDateTime(lastRunAt)}`;
  }

  /**
   * 内部时间格式化：YYYY-MM-DD HH:mm
   * 解析失败回退 '未知'
   */
  private static formatDateTime(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }
}

// ===========================================================================
// status 筛选 Tab 配置
// ===========================================================================

interface StatusFilterOption {
  value: string;             // 'all' 或具体 ScheduleTaskStatus
  label: string;
}

/** status 筛选 Tab 列表（顺序即展示顺序） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: '待执行' },
  { value: 'running', label: '运行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
];

/** 新建表单数据 */
interface SchedulerFormData {
  name: string;
  cron: string;
  payload: string;           // JSON 字符串文本
}

@Component
export struct AgentSchedulerPage {
  // 调度任务列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State tasks: ScheduleTask[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的 status 筛选值：'all' 或具体 status
  @State activeStatus: string = 'all';

  // 新建弹窗控制
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更必须整体重新赋值）
  @State formData: SchedulerFormData = { name: '', cron: '', payload: '' };

  // 编辑 cron 弹窗控制
  @State showEditCronDialog: boolean = false;
  @State editCronTask: ScheduleTask | null = null;
  @State editCronValue: string = '';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadTasks();
  }

  /**
   * 加载调度任务列表
   * 流程：取 currentAgentId → 调用 api.runtime.listScheduleTasks → 写入 tasks
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadTasks(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.runtime.listScheduleTasks(agentId);
      if (res.code === 0 && res.data) {
        this.tasks = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载调度任务失败', e as Error);
      this.msg.error('加载调度任务失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 切换 status 筛选 Tab（本地过滤）
   */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经当前 status 筛选后的列表
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredTasks(): ScheduleTask[] {
    if (this.activeStatus === 'all') {
      return this.tasks;
    }
    return this.tasks.filter((t: ScheduleTask) => t.status === this.activeStatus);
  }

  /**
   * 打开新建弹窗：重置表单数据为默认空值
   */
  private openCreateDialog(): void {
    this.formData = { name: '', cron: '', payload: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：校验 → 解析 payload JSON → 调用 api.runtime.createScheduleTask → 关闭弹窗并刷新列表
   * 异常：JSON 解析失败、API 异常均提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写任务名称');
      return;
    }
    if (!this.formData.cron) {
      this.msg.warning('请填写 cron 表达式');
      return;
    }
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }

    let payload: Object | undefined = undefined;
    if (this.formData.payload) {
      try {
        payload = JSON.parse(this.formData.payload);
      } catch (e) {
        this.msg.error('payload 不是合法 JSON');
        return;
      }
    }

    try {
      const data: Partial<ScheduleTask> = {
        agentId,
        name: this.formData.name,
        cron: this.formData.cron,
        status: 'pending',
        payload: payload as Record<string, Object>,
      };
      const res = await this.api.runtime.createScheduleTask(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadTasks();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建调度任务失败', e as Error);
      this.msg.error('创建调度任务失败');
    }
  }

  /**
   * 手动触发任务
   * 设计：RuntimeApi 未提供 trigger 接口，复用 updateScheduleTask 设置 status='running'
   *      以模拟触发语义；后端可在收到 status 变更时执行实际触发逻辑
   */
  private async triggerTask(task: ScheduleTask): Promise<void> {
    try {
      const res = await this.api.runtime.updateScheduleTask(task.id, { status: 'running' });
      if (res.code === 0) {
        this.msg.success('已触发');
        this.loadTasks();
      } else {
        this.msg.error(res.message || '触发失败');
      }
    } catch (e) {
      this.logger.error(TAG, '触发调度任务失败', e as Error);
      this.msg.error('触发失败');
    }
  }

  /**
   * 打开编辑 cron 弹窗：暂存当前任务，初始化 cron 输入框为当前值
   */
  private openEditCronDialog(task: ScheduleTask): void {
    this.editCronTask = task;
    this.editCronValue = task.cron;
    this.showEditCronDialog = true;
  }

  /**
   * 提交 cron 更新
   * 流程：调用 api.runtime.updateScheduleTask(id, { cron }) → 关闭弹窗并刷新列表
   */
  private async submitEditCron(): Promise<void> {
    if (!this.editCronTask) return;
    if (!this.editCronValue) {
      this.msg.warning('请填写 cron 表达式');
      return;
    }
    try {
      const res = await this.api.runtime.updateScheduleTask(this.editCronTask.id, { cron: this.editCronValue });
      if (res.code === 0) {
        this.msg.success('更新成功');
        this.showEditCronDialog = false;
        this.editCronTask = null;
        this.loadTasks();
      } else {
        this.msg.error(res.message || '更新失败');
      }
    } catch (e) {
      this.logger.error(TAG, '更新 cron 失败', e as Error);
      this.msg.error('更新失败');
    }
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(task: ScheduleTask): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除调度任务"${task.name}"吗？此操作不可撤销。`,
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
   * 流程：调用 api.runtime.removeScheduleTask → 成功后重新加载列表
   */
  private async deleteTask(taskId: string): Promise<void> {
    try {
      const res = await this.api.runtime.removeScheduleTask(taskId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadTasks();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除调度任务失败', e as Error);
      this.msg.error('删除失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"调度任务" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '调度任务',
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

        // status 筛选 Tab：横向滚动胶囊
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
        } else if (this.getFilteredTasks().length === 0) {
          Column() {
            Text('暂无调度任务')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '新建任务',
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
            ForEach(this.getFilteredTasks(), (task: ScheduleTask) => {
              ListItem() {
                this.buildTaskCard(task)
              }
            }, (task: ScheduleTask) => task.id)
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

      // 新建弹窗：showCreateDialog 为 true 时覆盖在主体之上
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
      // 编辑 cron 弹窗
      if (this.showEditCronDialog && this.editCronTask) {
        this.buildEditCronDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 调度任务卡片构建器
  // ===========================================================================

  /** 单条调度任务卡片：status 徽章 / name / cron / 时间 / 操作按钮 */
  @Builder
  buildTaskCard(task: ScheduleTask) {
    GlassCard() {
      Column() {
        // 上部：name + status 徽章
        Row() {
          Text(task.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })

          // status 徽章：图标 + 标签
          Row() {
            Text(AgentSchedulerViewHelper.getStatusIcon(task.status))
              .fontSize(14)
            Text(AgentSchedulerViewHelper.getStatusLabel(task.status))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(AgentSchedulerViewHelper.getStatusColor(task.status)))
          .alignItems(VerticalAlign.Center)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // cron 表达式（简化显示）
        Text(`cron: ${AgentSchedulerViewHelper.formatCron(task.cron)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .fontFamily('monospace')
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 时间行：lastRunAt + nextRunAt
        Text(AgentSchedulerViewHelper.formatLastRun(task.lastRunAt))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')
        Text(AgentSchedulerViewHelper.formatNextRun(task.nextRunAt))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 2 })
          .width('100%')

        // 操作按钮：触发 / 编辑 cron / 删除（右对齐）
        Row() {
          GlassButton({
            text: '触发',
            type: 'default',
            size: 'small',
            onClick: () => { this.triggerTask(task); }
          })
          GlassButton({
            text: '编辑 cron',
            type: 'default',
            size: 'small',
            onClick: () => { this.openEditCronDialog(task); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
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
  // 新建弹窗构建器（Stack 覆盖层）
  // ===========================================================================

  /** 新建调度任务弹窗：name + cron + payload(JSON) */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建调度任务')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('md') })

          // 任务名称
          Text('任务名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入任务名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => {
              this.formData = { ...this.formData, name: v };
            }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // cron 表达式
          Text('cron 表达式')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '如 0 * * * *',
            value: this.formData.cron,
            type: 'text',
            onChange: (v: string) => {
              this.formData = { ...this.formData, cron: v };
            }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // payload（JSON 文本）
          Text('payload (JSON, 可选)')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '{"key":"value"}',
            value: this.formData.payload,
            type: 'text',
            maxLength: 500,
            onChange: (v: string) => {
              this.formData = { ...this.formData, payload: v };
            }
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

  // ===========================================================================
  // 编辑 cron 弹窗构建器
  // ===========================================================================

  /** 编辑 cron 弹窗：单输入框 + 取消/确认 */
  @Builder
  buildEditCronDialog() {
    Stack({ alignContent: Alignment.Center }) {
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showEditCronDialog = false; })

      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('编辑 cron 表达式')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('sm') })

          Text(`任务：${this.editCronTask!.name}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('sm') })

          Text('cron 表达式')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '如 0 * * * *',
            value: this.editCronValue,
            type: 'text',
            onChange: (v: string) => { this.editCronValue = v; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showEditCronDialog = false; }
            })
            GlassButton({
              text: '保存',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitEditCron(); }
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
