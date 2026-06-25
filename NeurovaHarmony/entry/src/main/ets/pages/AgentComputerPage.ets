/**
 * AgentComputerPage - 计算机任务页
 *
 * 职责：展示 Computer Use 任务列表，按 status 筛选，支持查看详情与新建/删除
 * 设计：
 *   - AgentComputerViewHelper（导出）：纯视图模型，封装 action 图标映射、action 中文标签、
 *     status 颜色映射、duration 格式化、result 截断；无 UI 运行时依赖，可独立单元测试；
 *   - AgentComputerPage（@Component）：Column [TopNavMenu(标题"计算机任务"+返回+新建)]
 *     + [status 筛选 Tab（全部/pending/running/completed/failed/cancelled）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含 action emoji/target、status 徽章、
 *     startedAt/finishedAt、durationMs、result 摘要、操作（查看详情/删除）；
 *     删除走 AlertDialog 二次确认；新建与详情查看走 Stack 条件渲染弹窗；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.runtime，
 *     状态走 AgentsStore（currentAgentId 过滤），日志走 Logger，提示走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime.listComputerTasks/getComputerTask/
 *     createComputerTask/removeComputerTask）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ComputerTask、ScheduleTaskStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.runtime.listComputerTasks 加载列表；
 *   status 筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   新建按钮 → Stack 弹窗收集 action/target → api.runtime.createComputerTask；
 *   查看详情 → Stack 弹窗展示完整任务信息；
 *   删除 → AlertDialog 二次确认 → api.runtime.removeComputerTask → 刷新列表
 *
 * TDD：AgentComputerViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 AgentComputerPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ComputerTask, ScheduleTaskStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentComputerPage';

// ===========================================================================
// AgentComputerViewHelper - 计算机任务视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentComputerViewHelper {
  /**
   * 获取 action 对应的图标 emoji
   * 映射：click→👆，type→⌨️，scroll→📜，screenshot→📷，其他→❓
   * @param action 动作类型字符串
   * @return emoji 字符串
   */
  static getActionIcon(action: string): string {
    if (action === 'click') return '👆';
    if (action === 'type') return '⌨️';
    if (action === 'scroll') return '📜';
    if (action === 'screenshot') return '📷';
    return '❓';
  }

  /**
   * 获取 action 的中文标签
   * 映射：click→点击，type→输入，scroll→滚动，screenshot→截图，其他→未知
   * @param action 动作类型字符串
   * @return 中文标签字符串
   */
  static getActionLabel(action: string): string {
    if (action === 'click') return '点击';
    if (action === 'type') return '输入';
    if (action === 'scroll') return '滚动';
    if (action === 'screenshot') return '截图';
    return '未知';
  }

  /**
   * 获取计算机任务 status 对应的颜色 token 名
   * 映射：pending→warning，running→info，completed→success，failed→error，cancelled→text_disabled
   * @param status 任务状态（复用 ScheduleTaskStatus）
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
   * 格式化任务执行时长
   * 规则：
   *   - undefined → "—"
   *   - <1000ms  → "n ms"（整数毫秒）
   *   - <60000ms → "n.nn s"（秒，保留 2 位小数）
   *   - >=60000ms → "M:SS"（分:秒，秒补零至 2 位）
   * @param durationMs 毫秒数，可选
   * @return 格式化后的字符串
   */
  static formatDuration(durationMs?: number): string {
    if (durationMs === undefined || durationMs === null) return '—';
    if (durationMs < 1000) return `${durationMs} ms`;
    if (durationMs < 60000) return `${(durationMs / 1000).toFixed(2)} s`;
    const totalSec = Math.floor(durationMs / 1000);
    const minutes = Math.floor(totalSec / 60);
    const seconds = totalSec % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }

  /**
   * 截断 result 文本，超长追加省略号
   * @param result 原始文本，可选
   * @param maxLen 最大保留长度，默认 100
   * @return 无值→"—"；超长→前 maxLen 字符 + "..."；未超→原样返回
   */
  static truncateResult(result?: string, maxLen: number = 100): string {
    if (result === undefined || result === null) return '—';
    if (result.length <= maxLen) return result;
    return result.substring(0, maxLen) + '...';
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

/** 可选 action 列表（用于新建弹窗选择） */
const ACTION_OPTIONS: string[] = ['click', 'type', 'scroll', 'screenshot'];

/** 新建表单数据 */
interface ComputerFormData {
  action: string;
  target: string;
}

@Component
export struct AgentComputerPage {
  // 计算机任务列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State tasks: ComputerTask[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的 status 筛选值：'all' 或具体 status
  @State activeStatus: string = 'all';

  // 新建弹窗控制
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更必须整体重新赋值）
  @State formData: ComputerFormData = { action: 'click', target: '' };

  // 详情弹窗控制
  @State showDetailDialog: boolean = false;
  @State detailTask: ComputerTask | null = null;

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
   * 加载计算机任务列表
   * 流程：取 currentAgentId → 调用 api.runtime.listComputerTasks → 写入 tasks
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
      const res = await this.api.runtime.listComputerTasks(agentId);
      if (res.code === 0 && res.data) {
        this.tasks = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载计算机任务失败', e as Error);
      this.msg.error('加载计算机任务失败');
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
  private getFilteredTasks(): ComputerTask[] {
    if (this.activeStatus === 'all') {
      return this.tasks;
    }
    return this.tasks.filter((t: ComputerTask) => t.status === this.activeStatus);
  }

  /**
   * 打开新建弹窗：重置表单数据为默认值
   */
  private openCreateDialog(): void {
    this.formData = { action: 'click', target: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：校验 → 调用 api.runtime.createComputerTask → 关闭弹窗并刷新列表
   * 异常：API 异常均提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.action) {
      this.msg.warning('请选择动作类型');
      return;
    }
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }

    try {
      const data: Partial<ComputerTask> = {
        agentId,
        action: this.formData.action,
        target: this.formData.target,
        status: 'pending',
        startedAt: new Date().toISOString(),
      };
      const res = await this.api.runtime.createComputerTask(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadTasks();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建计算机任务失败', e as Error);
      this.msg.error('创建计算机任务失败');
    }
  }

  /**
   * 打开详情弹窗：暂存当前任务
   */
  private openDetailDialog(task: ComputerTask): void {
    this.detailTask = task;
    this.showDetailDialog = true;
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(task: ComputerTask): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除计算机任务（${AgentComputerViewHelper.getActionLabel(task.action)}）吗？此操作不可撤销。`,
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
   * 流程：调用 api.runtime.removeComputerTask → 成功后重新加载列表
   */
  private async deleteTask(taskId: string): Promise<void> {
    try {
      const res = await this.api.runtime.removeComputerTask(taskId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadTasks();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除计算机任务失败', e as Error);
      this.msg.error('删除失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"计算机任务" + 返回 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '计算机任务',
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
            Text('暂无计算机任务')
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
            ForEach(this.getFilteredTasks(), (task: ComputerTask) => {
              ListItem() {
                this.buildTaskCard(task)
              }
            }, (task: ComputerTask) => task.id)
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
      // 详情弹窗：showDetailDialog 为 true 且 detailTask 存在时覆盖
      if (this.showDetailDialog && this.detailTask) {
        this.buildDetailDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 计算机任务卡片构建器
  // ===========================================================================

  /** 单条计算机任务卡片：action emoji/target + status 徽章 + 时间 + result 摘要 + 操作 */
  @Builder
  buildTaskCard(task: ComputerTask) {
    GlassCard() {
      Column() {
        // 上部：action emoji + target + status 徽章
        Row() {
          Text(AgentComputerViewHelper.getActionIcon(task.action))
            .fontSize(18)
          Text(AgentComputerViewHelper.getActionLabel(task.action))
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ left: 6 })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .layoutWeight(1)

          // status 徽章：颜色块 + 文本
          Text(task.status)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 8, right: 8, top: 2, bottom: 2 })
            .borderRadius(10)
            .backgroundColor(this.sm.getColor(AgentComputerViewHelper.getStatusColor(task.status)))
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // target（如有）
        if (task.target) {
          Text(`目标：${task.target}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ top: this.sm.getSpacing('sm') })
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .width('100%')
        }

        // 时间行：startedAt / finishedAt
        Text(`开始：${this.formatDateTime(task.startedAt)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')
        if (task.finishedAt) {
          Text(`结束：${this.formatDateTime(task.finishedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ top: 2 })
            .width('100%')
        }

        // 耗时
        Text(`耗时：${AgentComputerViewHelper.formatDuration(this.computeDuration(task))}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 2 })
          .width('100%')

        // result 摘要
        Text(`结果：${AgentComputerViewHelper.truncateResult(task.result)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .margin({ top: 4 })
          .maxLines(3)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .width('100%')

        // 操作按钮：查看详情 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '查看详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.openDetailDialog(task); }
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
  // 新建弹窗构建器（Stack 覆盖层）
  // ===========================================================================

  /** 新建计算机任务弹窗：action 选择 + target 输入 */
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
          Text('新建计算机任务')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('md') })

          // 动作类型（横向胶囊选择）
          Text('动作类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Row({ space: 8 }) {
            ForEach(ACTION_OPTIONS, (act: string) => {
              Row() {
                Text(AgentComputerViewHelper.getActionIcon(act))
                  .fontSize(14)
                  .margin({ right: 4 })
                Text(AgentComputerViewHelper.getActionLabel(act))
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.formData.action === act
                    ? this.sm.getColor('text_on_primary')
                    : this.sm.getColor('text_secondary'))
              }
              .padding({ left: 10, right: 10, top: 6, bottom: 6 })
              .borderRadius(16)
              .backgroundColor(this.formData.action === act
                ? this.sm.getColor('primary')
                : this.sm.getColor('surface'))
              .onClick(() => {
                this.formData = { ...this.formData, action: act };
              })
            }, (act: string) => act)
          }
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 目标（可选）
          Text('目标 (可选)')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '如 button#submit',
            value: this.formData.target,
            type: 'text',
            onChange: (v: string) => {
              this.formData = { ...this.formData, target: v };
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
  // 详情弹窗构建器（Stack 覆盖层）
  // ===========================================================================

  /** 详情弹窗：展示完整任务字段 */
  @Builder
  buildDetailDialog() {
    Stack({ alignContent: Alignment.Center }) {
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showDetailDialog = false; })

      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题行：动作 emoji + 标签
          Row() {
            Text(AgentComputerViewHelper.getActionIcon(this.detailTask!.action))
              .fontSize(20)
            Text(AgentComputerViewHelper.getActionLabel(this.detailTask!.action))
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ left: 6 })
          }
          .width('100%')
          .alignItems(VerticalAlign.Center)
          .margin({ bottom: this.sm.getSpacing('md') })

          // 字段列表
          this.buildDetailRow('任务 ID', this.detailTask!.id)
          this.buildDetailRow('动作', this.detailTask!.action)
          this.buildDetailRow('目标', this.detailTask!.target || '—')
          this.buildDetailRow('状态', this.detailTask!.status)
          this.buildDetailRow('开始时间', this.formatDateTime(this.detailTask!.startedAt))
          this.buildDetailRow('结束时间',
            this.detailTask!.finishedAt ? this.formatDateTime(this.detailTask!.finishedAt) : '—')
          this.buildDetailRow('耗时',
            AgentComputerViewHelper.formatDuration(this.computeDuration(this.detailTask!)))

          // result 完整内容（不截断）
          Text('结果')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          Text(this.detailTask!.result || '—')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_primary'))
            .fontFamily('monospace')
            .width('100%')
            .margin({ top: 4 })
            .padding(8)
            .backgroundColor(this.sm.getColor('surface'))
            .borderRadius(8)

          // 关闭按钮
          Row() {
            GlassButton({
              text: '关闭',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.showDetailDialog = false; }
            })
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

  /** 详情行构建器：左标签 + 右值 */
  @Builder
  buildDetailRow(label: string, value: string) {
    Row() {
      Text(label)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_secondary'))
        .width(80)
      Text(value)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_primary'))
        .layoutWeight(1)
        .maxLines(2)
        .textOverflow({ overflow: TextOverflow.Ellipsis })
    }
    .width('100%')
    .margin({ top: 4 })
  }

  // ===========================================================================
  // 内部辅助方法
  // ===========================================================================

  /** 格式化时间为 YYYY-MM-DD HH:mm */
  private formatDateTime(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  /** 计算任务耗时（finishedAt - startedAt），未完成返回 undefined */
  private computeDuration(task: ComputerTask): number | undefined {
    if (!task.finishedAt) return undefined;
    const start = new Date(task.startedAt).getTime();
    const end = new Date(task.finishedAt).getTime();
    if (isNaN(start) || isNaN(end)) return undefined;
    return end - start;
  }
}
