/**
 * AIGCPage - AIGC 任务页
 *
 * 职责：展示 AIGC 任务列表，按 status 筛选，新建任务，查看结果
 * 设计：
 *   - AIGCViewHelper（导出）：纯视图模型，封装任务类型颜色/图标/文案、状态颜色/图标/文案、
 *     prompt 截断（默认 100）、时长格式化（秒/分秒），无 UI 依赖，可独立单元测试；
 *   - AIGCPage（@Component）：Stack [主内容列] + [新建任务 CustomDialog]
 *     主内容列：TopNavMenu(标题"AIGC 任务"+返回+新建) + [status 筛选 Tab（全部/queued/processing/
 *     succeeded/failed）] + [加载态/空态/列表]；
 *     列表项 GlassCard：type 徽章、prompt 摘要、status 徽章、resultUrl 链接（succeeded 时）、
 *     errorMessage（failed 时）、createdAt、finishedAt、操作（查看详情/取消/重试）；
 *   - 新建 CustomDialog：type 选择（text/image/audio/video）、prompt 文本域；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 AIGC 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M5 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：AIGCTask、AIGCTaskStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.AIGC) 跳转进入；
 *   aboutToAppear 加载 mock 任务列表（TODO M5 接入真实 API）；
 *   status 筛选 Tab 切换 → 本地按 status 过滤；
 *   新建 → 弹窗选择 type + 填 prompt → 提交 → TODO M5 接入 API；
 *   查看详情 → AlertDialog 展示完整 prompt + 元数据；
 *   取消（queued/processing）→ AlertDialog 二次确认 → TODO M5 接入 API；
 *   重试（failed）→ TODO M5 接入 API。
 *
 * TDD：AIGCViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AIGCPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { AIGCTask, AIGCTaskStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AIGCPage';

/** prompt 截断默认最大长度 */
const DEFAULT_PROMPT_MAX_LEN = 100;

/** 秒级阈值：超过 60 秒切换为 M:SS 格式 */
const SECONDS_THRESHOLD = 60;

// ===========================================================================
// AIGCViewHelper - AIGC 任务视图模型（纯函数，无 UI 依赖，可独立单元测试）
// ===========================================================================

export class AIGCViewHelper {
  /**
   * 获取任务类型对应的颜色 token 名
   * 映射：text→info，image→primary，audio→warning，video→error
   */
  static getTypeColor(type: AIGCTask['type']): string {
    if (type === 'text') return 'info';
    if (type === 'image') return 'primary';
    if (type === 'audio') return 'warning';
    if (type === 'video') return 'error';
    throw new Error(`getTypeColor 未实现: ${type}`);
  }

  /**
   * 获取任务类型对应的图标 emoji
   * 映射：text→📝，image→🖼️，audio→🎵，video→🎬
   */
  static getTypeIcon(type: AIGCTask['type']): string {
    if (type === 'text') return '📝';
    if (type === 'image') return '🖼️';
    if (type === 'audio') return '🎵';
    if (type === 'video') return '🎬';
    throw new Error(`getTypeIcon 未实现: ${type}`);
  }

  /**
   * 获取任务类型对应的中文标签
   * 映射：text→文本，image→图像，audio→音频，video→视频
   */
  static getTypeLabel(type: AIGCTask['type']): string {
    if (type === 'text') return '文本';
    if (type === 'image') return '图像';
    if (type === 'audio') return '音频';
    if (type === 'video') return '视频';
    throw new Error(`getTypeLabel 未实现: ${type}`);
  }

  /**
   * 获取任务状态对应的颜色 token 名
   * 映射：queued→warning，processing→info，succeeded→success，failed→error
   */
  static getStatusColor(status: AIGCTaskStatus): string {
    if (status === 'queued') return 'warning';
    if (status === 'processing') return 'info';
    if (status === 'succeeded') return 'success';
    if (status === 'failed') return 'error';
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取任务状态对应的图标 emoji
   * 映射：queued→⏳，processing→⚡，succeeded→✅，failed→❌
   */
  static getStatusIcon(status: AIGCTaskStatus): string {
    if (status === 'queued') return '⏳';
    if (status === 'processing') return '⚡';
    if (status === 'succeeded') return '✅';
    if (status === 'failed') return '❌';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 获取任务状态对应的中文标签
   * 映射：queued→排队中，processing→处理中，succeeded→已完成，failed→失败
   */
  static getStatusLabel(status: AIGCTaskStatus): string {
    if (status === 'queued') return '排队中';
    if (status === 'processing') return '处理中';
    if (status === 'succeeded') return '已完成';
    if (status === 'failed') return '失败';
    throw new Error(`getStatusLabel 未实现: ${status}`);
  }

  /**
   * 截断 prompt，超长时截取 maxLen 字符并追加省略号
   * @param prompt 原始 prompt
   * @param maxLen 最大字符数，默认 100
   * @return 截断后的 prompt；未超长则原样返回
   */
  static truncatePrompt(prompt: string, maxLen: number = DEFAULT_PROMPT_MAX_LEN): string {
    if (prompt.length <= maxLen) return prompt;
    return prompt.substring(0, maxLen) + '...';
  }

  /**
   * 格式化任务耗时
   * 规则：
   *   - 无 finishedAt → "—"
   *   - 差值 < 60 秒 → "n.nn s"（保留 2 位小数）
   *   - 差值 ≥ 60 秒 → "M:SS"（分:秒，秒数补 0）
   * @param startedAt 开始时间 ISO 字符串
   * @param finishedAt 结束时间 ISO 字符串（可选）
   * @return 耗时展示字符串
   */
  static formatDuration(startedAt: string, finishedAt?: string): string {
    if (!finishedAt) return '—';
    const start = new Date(startedAt).getTime();
    const end = new Date(finishedAt).getTime();
    if (isNaN(start) || isNaN(end)) return '—';
    const diffMs = end - start;
    if (diffMs < 0) return '—';
    const diffSec = diffMs / 1000;
    if (diffSec < SECONDS_THRESHOLD) {
      return `${diffSec.toFixed(2)} s`;
    }
    const minutes = Math.floor(diffSec / 60);
    const seconds = Math.floor(diffSec % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;     // 'all' 或 AIGCTaskStatus
  label: string;
}

/** 状态筛选 Tab 列表 */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'queued', label: '排队中' },
  { value: 'processing', label: '处理中' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
];

/** 新建任务表单数据 */
interface AIGCTaskFormData {
  type: AIGCTask['type'];
  prompt: string;
}

/** 默认表单数据 */
const DEFAULT_FORM: AIGCTaskFormData = {
  type: 'text',
  prompt: '',
};

/**
 * Mock AIGC 任务数据
 * TODO M5 阶段：替换为 api.aigc.list() 真实 API
 */
const MOCK_TASKS: AIGCTask[] = [
  {
    id: 'task_1',
    agentId: 'agent_1',
    type: 'image',
    prompt: '生成一只可爱的猫咪',
    status: 'succeeded',
    resultUrl: 'https://example.com/image1.png',
    createdAt: '2025-03-01T10:00:00Z',
    finishedAt: '2025-03-01T10:00:05.500Z',
  },
  {
    id: 'task_2',
    agentId: 'agent_1',
    type: 'text',
    prompt: '写一首关于秋天的诗',
    status: 'processing',
    createdAt: '2025-03-01T11:00:00Z',
  },
  {
    id: 'task_3',
    agentId: 'agent_1',
    type: 'audio',
    prompt: '生成一段欢快的背景音乐',
    status: 'queued',
    createdAt: '2025-03-01T12:00:00Z',
  },
  {
    id: 'task_4',
    agentId: 'agent_1',
    type: 'video',
    prompt: '生成一段 30 秒的产品介绍视频',
    status: 'failed',
    errorMessage: '生成超时，请重试',
    createdAt: '2025-03-01T09:00:00Z',
    finishedAt: '2025-03-01T09:00:30.000Z',
  },
];

@Component
export struct AIGCPage {
  // AIGC 任务列表
  @State tasks: AIGCTask[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选
  @State activeStatus: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: AIGCTaskFormData = { ...DEFAULT_FORM };

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
   * TODO M5 阶段：替换为真实 API（api.aigc.list）
   */
  private async loadTasks(): Promise<void> {
    this.loading = true;
    try {
      // TODO M5 阶段补充真实 API
      // const res = await this.api.aigc.list();
      // if (res.code === 0 && res.data) { this.tasks = res.data.items; }
      this.tasks = MOCK_TASKS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载任务失败', e as Error);
      this.msg.error('加载 AIGC 任务失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   */
  private getFilteredTasks(): AIGCTask[] {
    if (this.activeStatus === 'all') {
      return this.tasks;
    }
    return this.tasks.filter((t: AIGCTask) => t.status === this.activeStatus);
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { ...DEFAULT_FORM };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建任务
   * TODO M5 阶段：调用真实 API（api.aigc.create）
   * 当前为本地追加 + TODO 提示
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.prompt.trim()) {
      this.msg.warning('请填写 prompt');
      return;
    }
    try {
      // TODO M5 阶段：const res = await this.api.aigc.create({ type, prompt });
      // 临时：本地追加一个 queued 任务
      const newTask: AIGCTask = {
        id: `task_${Date.now()}`,
        agentId: 'agent_1',
        type: this.formData.type,
        prompt: this.formData.prompt.trim(),
        status: 'queued',
        createdAt: new Date().toISOString(),
      };
      this.tasks = [newTask, ...this.tasks];
      this.msg.success('已提交');
      this.showCreateDialog = false;
    } catch (e) {
      this.logger.error(TAG, '创建任务失败', e as Error);
      this.msg.error('创建任务失败');
    }
  }

  /** 选择 type（嵌套属性变更：整体重新赋值） */
  private selectType(type: AIGCTask['type']): void {
    this.formData = { ...this.formData, type };
  }

  /** 输入 prompt（嵌套属性变更：整体重新赋值） */
  private inputPrompt(v: string): void {
    this.formData = { ...this.formData, prompt: v };
  }

  /**
   * 查看详情
   * AlertDialog 展示完整 prompt + 元数据
   */
  private showDetail(task: AIGCTask): void {
    const message =
      `类型：${AIGCViewHelper.getTypeLabel(task.type)}\n\n` +
      `状态：${AIGCViewHelper.getStatusLabel(task.status)}\n\n` +
      `Prompt：\n${task.prompt}\n\n` +
      `创建时间：${this.formatTime(task.createdAt)}\n` +
      `完成时间：${this.formatTime(task.finishedAt)}`;
    AlertDialog.show({
      title: '任务详情',
      message,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '关闭',
        action: () => {}
      }
    });
  }

  /**
   * 取消任务前二次确认（仅 queued/processing 状态可取消）
   */
  private confirmCancel(task: AIGCTask): void {
    AlertDialog.show({
      title: '确认取消',
      message: `确定要取消任务吗？`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '确认',
        fontColor: this.sm.getColor('error'),
        action: () => { this.cancelTask(task.id); }
      }
    });
  }

  /**
   * 执行取消任务
   * TODO M5 阶段：调用真实 API（api.aigc.cancel）
   */
  private async cancelTask(taskId: string): Promise<void> {
    try {
      // TODO M5 阶段：const res = await this.api.aigc.cancel(taskId);
      this.tasks = this.tasks.filter((t: AIGCTask) => t.id !== taskId);
      this.msg.success('已取消');
    } catch (e) {
      this.logger.error(TAG, '取消任务失败', e as Error);
      this.msg.error('取消任务失败');
    }
  }

  /**
   * 重试失败任务
   * TODO M5 阶段：调用真实 API（api.aigc.retry）
   */
  private async retryTask(task: AIGCTask): Promise<void> {
    try {
      // TODO M5 阶段：const res = await this.api.aigc.retry(task.id);
      // 临时：本地将状态改回 queued
      this.tasks = this.tasks.map((t: AIGCTask) => {
        if (t.id === task.id) {
          return { ...t, status: 'queued' as AIGCTaskStatus, errorMessage: undefined };
        }
        return t;
      });
      this.msg.success('已重新提交');
    } catch (e) {
      this.logger.error(TAG, '重试任务失败', e as Error);
      this.msg.error('重试任务失败');
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(time?: string): string {
    if (!time) return '未知';
    const d = new Date(time);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack() {
      Column() {
        // 顶部导航栏：标题"AIGC 任务" + 返回 + 新建
        TopNavMenu({
          title: 'AIGC 任务',
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

        // 状态筛选 Tab
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
        } else if (this.getFilteredTasks().length === 0) {
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
            ForEach(this.getFilteredTasks(), (task: AIGCTask) => {
              ListItem() {
                this.buildTaskCard(task)
              }
            }, (task: AIGCTask) => task.id)
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

      // 新建任务弹窗
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

  /** 单个任务卡片：类型徽章 + prompt 摘要 + 状态徽章 + resultUrl/errorMessage + 操作按钮 */
  @Builder
  buildTaskCard(task: AIGCTask) {
    GlassCard() {
      Column() {
        // 顶部行：类型图标 + 类型徽章 + 状态徽章
        Row() {
          Text(AIGCViewHelper.getTypeIcon(task.type))
            .fontSize(20)
          Text(AIGCViewHelper.getTypeLabel(task.type))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(AIGCViewHelper.getTypeColor(task.type)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(AIGCViewHelper.getStatusIcon(task.status))
            .fontSize(16)
            .margin({ left: this.sm.getSpacing('sm') })
          Text(AIGCViewHelper.getStatusLabel(task.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(AIGCViewHelper.getStatusColor(task.status)))
            .margin({ left: 4 })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // prompt 摘要（默认 100 字符截断）
        Text(AIGCViewHelper.truncatePrompt(task.prompt))
          .fontSize(this.sm.getFontSize('body'))
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // resultUrl（succeeded 时显示）
        if (task.status === 'succeeded' && task.resultUrl) {
          Text(`结果: ${task.resultUrl}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('primary'))
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // errorMessage（failed 时显示）
        if (task.status === 'failed' && task.errorMessage) {
          Text(`错误: ${task.errorMessage}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('error'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // 时间行：创建 + 完成 + 耗时
        Row() {
          Text(`创建: ${this.formatTime(task.createdAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .layoutWeight(1)
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
          Text(`耗时: ${AIGCViewHelper.formatDuration(task.createdAt, task.finishedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：查看详情 + 取消（queued/processing）+ 重试（failed）
        Row() {
          GlassButton({
            text: '详情',
            type: 'default',
            size: 'small',
            onClick: () => { this.showDetail(task); }
          })
          if (task.status === 'queued' || task.status === 'processing') {
            GlassButton({
              text: '取消',
              type: 'danger',
              size: 'small',
              onClick: () => { this.confirmCancel(task); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
          if (task.status === 'failed') {
            GlassButton({
              text: '重试',
              type: 'primary',
              size: 'small',
              onClick: () => { this.retryTask(task); }
            })
              .margin({ left: this.sm.getSpacing('sm') })
          }
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
  // 新建任务弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建任务弹窗：type 选择 + prompt 文本域 */
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
          Text('新建 AIGC 任务')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 类型选择
          Text('任务类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          Row() {
            ForEach(this.getTypeOptions(), (opt: { type: AIGCTask['type']; label: string; icon: string }) => {
              GlassButton({
                text: `${opt.icon} ${opt.label}`,
                type: this.formData.type === opt.type ? 'primary' : 'default',
                size: 'small',
                onClick: () => { this.selectType(opt.type); }
              })
                .margin({ right: this.sm.getSpacing('xs') })
            }, (opt: { type: AIGCTask['type']; label: string; icon: string }) => opt.type)
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })

          // prompt 文本域（用 GlassInput 模拟多行输入）
          Text('Prompt')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入 prompt...',
            value: this.formData.prompt,
            type: 'text',
            onChange: (v: string) => { this.inputPrompt(v); },
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
              text: '提交',
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

  /** 获取任务类型选项列表 */
  private getTypeOptions(): { type: AIGCTask['type']; label: string; icon: string }[] {
    const types: AIGCTask['type'][] = ['text', 'image', 'audio', 'video'];
    return types.map((t: AIGCTask['type']) => ({
      type: t,
      label: AIGCViewHelper.getTypeLabel(t),
      icon: AIGCViewHelper.getTypeIcon(t),
    }));
  }
}
