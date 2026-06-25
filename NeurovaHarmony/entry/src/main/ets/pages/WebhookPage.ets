/**
 * WebhookPage - Webhook 管理页
 *
 * 职责：展示 Webhook 配置列表，按 status 筛选（active/paused/error），
 *   事件徽章、触发统计（成功/失败次数）、新建按钮、测试触发按钮
 * 设计：
 *   - WebhookViewHelper（导出）：纯视图模型，封装状态颜色/图标/文案、事件文案、
 *     成功率格式化、URL 截断；无 UI 运行时依赖，可独立单元测试；
 *   - WebhookPage（@Component）：Stack [主内容列] + [新建弹窗]
 *     主内容列：TopNavMenu(标题"Webhook 管理"+返回+新建) + [status 筛选 Tab] +
 *     [加载态/空态/列表]；
 *     列表项 GlassCard：name、url（截断）、status 徽章、events 徽章、
 *     success/failure 统计、成功率、最后触发时间、操作按钮（测试触发）；
 *     新建 → Stack 内嵌条件渲染弹窗；
 *   - 颜色统一走 StyleManager，路由走 Router，API 暂无 webhook 专用模块 →
 *     aboutToAppear 加载 mock 静态数据 + TODO 注释 M6 阶段补充真实 API。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（仅作为占位，未实际调用）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Webhook、WebhookStatus、WebhookEvent
 *
 * 用法：
 *   由 Router.push(RouteNames.WEBHOOK) 跳转进入；
 *   aboutToAppear 加载 mock Webhook 列表（TODO M6 接入 api.webhook.list）；
 *   status 筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   测试触发 → AlertDialog 二次确认 → TODO M6 接入 API；
 *   新建 → 弹窗输入名称/URL/事件 → 提交 → TODO M6 接入 API。
 *
 * TDD：WebhookViewHelper 各方法按红绿灯垂直切片逐步实现，详见 WebhookPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Webhook, WebhookStatus, WebhookEvent } from '../libs/types';

/** 日志标签 */
const TAG = 'WebhookPage';

/** URL 截断默认最大长度 */
const DEFAULT_URL_MAX_LEN = 40;

// ===========================================================================
// WebhookViewHelper - Webhook 视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'success'），由页面解析为实际颜色值；
//       图标方法返回 emoji 字符串直接渲染；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class WebhookViewHelper {
  /**
   * 获取 Webhook 状态对应的颜色 token 名
   * 映射：active→success，paused→warning，error→error
   * @param status Webhook 状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: WebhookStatus): string {
    if (status === 'active') return 'success';
    if (status === 'paused') return 'warning';
    if (status === 'error') return 'error';
    // 未覆盖的状态抛错，强制 TDD 红灯逐项补齐
    throw new Error(`getStatusColor 未实现: ${status}`);
  }

  /**
   * 获取 Webhook 状态对应的图标 emoji
   * 映射：active→✅，paused→⏸️，error→❌
   * @param status Webhook 状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: WebhookStatus): string {
    if (status === 'active') return '✅';
    if (status === 'paused') return '⏸️';
    if (status === 'error') return '❌';
    throw new Error(`getStatusIcon 未实现: ${status}`);
  }

  /**
   * 获取 Webhook 状态对应的中文标签
   * 映射：active→活跃，paused→暂停，error→错误
   * @param status Webhook 状态
   * @return 中文文案
   */
  static getStatusLabel(status: WebhookStatus): string {
    if (status === 'active') return '活跃';
    if (status === 'paused') return '暂停';
    if (status === 'error') return '错误';
    throw new Error(`getStatusLabel 未实现: ${status}`);
  }

  /**
   * 获取 Webhook 事件对应的中文标签
   * 映射：message.received→消息接收，agent.created→智能体创建，
   *       task.completed→任务完成，memory.created→记忆创建
   * @param event Webhook 事件
   * @return 中文文案
   */
  static getEventLabel(event: WebhookEvent): string {
    if (event === 'message.received') return '消息接收';
    if (event === 'agent.created') return '智能体创建';
    if (event === 'task.completed') return '任务完成';
    if (event === 'memory.created') return '记忆创建';
    throw new Error(`getEventLabel 未实现: ${event}`);
  }

  /**
   * 格式化成功率为百分比字符串
   * 规则：成功 + 失败 = 0 → "—"（无触发记录）；
   *       否则 → "XX.X%"（成功数 / (成功+失败) * 100，保留 1 位小数）
   * @param success 成功次数
   * @param failure 失败次数
   * @return 成功率展示字符串
   */
  static formatSuccessRate(success: number, failure: number): string {
    const total = success + failure;
    if (total === 0) return '—';
    const rate = (success / total) * 100;
    return `${rate.toFixed(1)}%`;
  }

  /**
   * 截断 URL，超长时截取 maxLen 字符并追加省略号
   * @param url 原始 URL
   * @param maxLen 最大字符数
   * @return 截断后的 URL；未超长则原样返回
   */
  static truncateUrl(url: string, maxLen: number): string {
    if (url.length <= maxLen) return url;
    return url.substring(0, maxLen) + '...';
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;     // 'all' 或具体状态
  label: string;
}

/** 状态筛选 Tab 列表 */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '活跃' },
  { value: 'paused', label: '暂停' },
  { value: 'error', label: '错误' },
];

/** 事件选项配置 */
interface EventOption {
  value: WebhookEvent;
  label: string;
}

/** 事件选项列表 */
const EVENT_OPTIONS: EventOption[] = [
  { value: 'message.received', label: '消息接收' },
  { value: 'agent.created', label: '智能体创建' },
  { value: 'task.completed', label: '任务完成' },
  { value: 'memory.created', label: '记忆创建' },
];

/** 新建 Webhook 表单数据 */
interface WebhookFormData {
  name: string;
  url: string;
  events: WebhookEvent[];
  secret: string;
}

/** 默认表单数据 */
const DEFAULT_FORM: WebhookFormData = {
  name: '',
  url: '',
  events: [],
  secret: '',
};

/**
 * Mock Webhook 数据
 * TODO M6 阶段：替换为 api.webhook.list() 真实 API
 */
const MOCK_WEBHOOKS: Webhook[] = [
  {
    id: 'wh_1',
    name: '消息推送 Webhook',
    url: 'https://api.example.com/webhooks/receive/very-long-path/with-many-segments',
    events: ['message.received', 'agent.created'],
    status: 'active',
    lastTriggeredAt: '2025-03-01T10:00:00Z',
    successCount: 90,
    failureCount: 10,
    createdAt: '2025-01-10T08:00:00Z',
    updatedAt: '2025-02-01T10:00:00Z',
  },
  {
    id: 'wh_2',
    name: '任务完成通知',
    url: 'https://hooks.example.com/task-done',
    events: ['task.completed'],
    status: 'paused',
    successCount: 50,
    failureCount: 0,
    createdAt: '2025-01-15T08:00:00Z',
    updatedAt: '2025-01-20T10:00:00Z',
  },
  {
    id: 'wh_3',
    name: '记忆创建同步',
    url: 'https://api.example.com/memory/sync',
    events: ['memory.created'],
    status: 'error',
    lastTriggeredAt: '2025-03-02T14:00:00Z',
    successCount: 0,
    failureCount: 5,
    createdAt: '2025-02-01T08:00:00Z',
    updatedAt: '2025-03-02T14:00:00Z',
  },
];

@Component
export struct WebhookPage {
  // Webhook 列表
  @State webhooks: Webhook[] = [];
  // 加载态
  @State loading: boolean = true;
  // 当前激活的状态筛选值
  @State activeStatus: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（嵌套属性变更需整体重新赋值）
  @State formData: WebhookFormData = { ...DEFAULT_FORM };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadWebhooks();
  }

  /**
   * 加载 Webhook 列表
   * TODO M6 阶段：替换为真实 API（api.webhook.list）
   */
  private async loadWebhooks(): Promise<void> {
    this.loading = true;
    try {
      // TODO M6 阶段补充真实 API
      // const res = await this.api.webhook.list();
      // if (res.code === 0 && res.data) { this.webhooks = res.data.items; }
      this.webhooks = MOCK_WEBHOOKS.slice();
    } catch (e) {
      this.logger.error(TAG, '加载 Webhook 失败', e as Error);
      this.msg.error('加载 Webhook 列表失败');
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
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredWebhooks(): Webhook[] {
    if (this.activeStatus === 'all') {
      return this.webhooks;
    }
    return this.webhooks.filter((w: Webhook) => w.status === this.activeStatus);
  }

  /** 打开新建弹窗，重置表单 */
  private openCreateDialog(): void {
    this.formData = { ...DEFAULT_FORM };
    this.showCreateDialog = true;
  }

  /** 输入名称（嵌套属性变更：整体重新赋值） */
  private inputName(v: string): void {
    this.formData = { ...this.formData, name: v };
  }

  /** 输入 URL（嵌套属性变更：整体重新赋值） */
  private inputUrl(v: string): void {
    this.formData = { ...this.formData, url: v };
  }

  /** 输入密钥（嵌套属性变更：整体重新赋值） */
  private inputSecret(v: string): void {
    this.formData = { ...this.formData, secret: v };
  }

  /** 切换事件选中状态（嵌套属性变更：整体重新赋值） */
  private toggleEvent(event: WebhookEvent): void {
    const events = this.formData.events.includes(event)
      ? this.formData.events.filter((e: WebhookEvent) => e !== event)
      : [...this.formData.events, event];
    this.formData = { ...this.formData, events };
  }

  /**
   * 提交新建 Webhook
   * TODO M6 阶段：调用真实 API（api.webhook.create）
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name.trim()) {
      this.msg.warning('请填写 Webhook 名称');
      return;
    }
    if (!this.formData.url.trim()) {
      this.msg.warning('请填写 URL');
      return;
    }
    if (this.formData.events.length === 0) {
      this.msg.warning('请至少选择一个事件');
      return;
    }
    try {
      // TODO M6 阶段：const res = await this.api.webhook.create(form);
      const now = new Date().toISOString();
      const newWh: Webhook = {
        id: `wh_${Date.now()}`,
        name: this.formData.name.trim(),
        url: this.formData.url.trim(),
        events: this.formData.events.slice(),
        status: 'active',
        secret: this.formData.secret.trim() || undefined,
        successCount: 0,
        failureCount: 0,
        createdAt: now,
        updatedAt: now,
      };
      this.webhooks = [newWh, ...this.webhooks];
      this.msg.success('已创建');
      this.showCreateDialog = false;
    } catch (e) {
      this.logger.error(TAG, '创建 Webhook 失败', e as Error);
      this.msg.error('创建 Webhook 失败');
    }
  }

  /**
   * 测试触发 Webhook 前二次确认
   */
  private confirmTestTrigger(wh: Webhook): void {
    AlertDialog.show({
      title: '确认测试触发',
      message: `确定要测试触发 Webhook"${wh.name}"吗？将向 ${wh.url} 发送测试请求。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '触发',
        fontColor: this.sm.getColor('primary'),
        action: () => { this.testTrigger(wh.id); }
      }
    });
  }

  /**
   * 执行测试触发
   * TODO M6 阶段：调用真实 API（api.webhook.testTrigger）
   */
  private async testTrigger(webhookId: string): Promise<void> {
    try {
      // TODO M6 阶段：const res = await this.api.webhook.testTrigger(webhookId);
      // 临时：本地增加成功计数 + 更新最后触发时间
      const now = new Date().toISOString();
      this.webhooks = this.webhooks.map((w: Webhook) => {
        if (w.id === webhookId) {
          return {
            ...w,
            successCount: w.successCount + 1,
            lastTriggeredAt: now,
            updatedAt: now,
          };
        }
        return w;
      });
      this.msg.success('测试触发已发送');
    } catch (e) {
      this.logger.error(TAG, '测试触发失败', e as Error);
      this.msg.error('测试触发失败');
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '从未触发' */
  private formatTime(time?: string): string {
    if (!time) return '从未触发';
    const d = new Date(time);
    if (isNaN(d.getTime())) return '从未触发';
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
        // 顶部导航栏：标题"Webhook 管理" + 返回 + 新建
        TopNavMenu({
          title: 'Webhook 管理',
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
        } else if (this.getFilteredWebhooks().length === 0) {
          Column() {
            Text('暂无 Webhook')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredWebhooks(), (wh: Webhook) => {
              ListItem() {
                this.buildWebhookCard(wh)
              }
            }, (wh: Webhook) => wh.id)
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

      // 新建 Webhook 弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // Webhook 卡片构建器
  // ===========================================================================

  /** 单个 Webhook 卡片：状态徽章 + 名称 + URL + 事件徽章 + 统计 + 操作按钮 */
  @Builder
  buildWebhookCard(wh: Webhook) {
    GlassCard() {
      Column() {
        // 顶部行：状态图标 + 状态徽章 + 名称
        Row() {
          Text(WebhookViewHelper.getStatusIcon(wh.status))
            .fontSize(20)
          Text(WebhookViewHelper.getStatusLabel(wh.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_on_primary'))
            .padding({ left: 6, right: 6, top: 2, bottom: 2 })
            .borderRadius(this.sm.getRadius('sm'))
            .backgroundColor(this.sm.getColor(WebhookViewHelper.getStatusColor(wh.status)))
            .margin({ left: this.sm.getSpacing('xs') })
          Text(wh.name)
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .layoutWeight(1)
            .margin({ left: this.sm.getSpacing('sm') })
            .maxLines(1)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // URL（截断显示）
        Text(WebhookViewHelper.truncateUrl(wh.url, DEFAULT_URL_MAX_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('xs') })
          .width('100%')

        // 事件徽章
        Flex({ wrap: FlexWrap.Wrap }) {
          ForEach(wh.events, (event: WebhookEvent) => {
            Text(WebhookViewHelper.getEventLabel(event))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .padding({ left: 6, right: 6, top: 2, bottom: 2 })
              .borderRadius(this.sm.getRadius('sm'))
              .backgroundColor(this.sm.getColor('surface'))
              .margin({ right: this.sm.getSpacing('xs'), top: 4 })
          }, (event: WebhookEvent) => event)
        }
        .width('100%')
        .margin({ top: 4 })

        // 统计行：成功/失败次数 + 成功率
        Row() {
          Text(`成功: ${wh.successCount}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('success'))
            .layoutWeight(1)
          Text(`失败: ${wh.failureCount}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('error'))
            .layoutWeight(1)
          Text(`成功率: ${WebhookViewHelper.formatSuccessRate(wh.successCount, wh.failureCount)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs') })
        .alignItems(VerticalAlign.Center)

        // 最后触发时间
        Text(`最后触发: ${this.formatTime(wh.lastTriggeredAt)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })
          .width('100%')

        // 操作按钮：测试触发（右对齐）
        Row() {
          GlassButton({
            text: '测试触发',
            type: 'primary',
            size: 'small',
            onClick: () => { this.confirmTestTrigger(wh); }
          })
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
  // 新建 Webhook 弹窗构建器（Stack 内嵌条件渲染）
  // ===========================================================================

  /** 新建 Webhook 弹窗：名称 + URL + 事件选择 + 密钥 */
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
          Text('新建 Webhook')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .width('100%')

          // 名称输入
          Text('名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入 Webhook 名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.inputName(v); },
          })
            .margin({ top: 4 })

          // URL 输入
          Text('URL')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: 'https://example.com/webhook',
            value: this.formData.url,
            type: 'text',
            onChange: (v: string) => { this.inputUrl(v); },
          })
            .margin({ top: 4 })

          // 事件选择
          Text('事件')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          Flex({ wrap: FlexWrap.Wrap }) {
            ForEach(EVENT_OPTIONS, (opt: EventOption) => {
              Text(`${this.formData.events.includes(opt.value) ? '✓ ' : ''}${opt.label}`)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.formData.events.includes(opt.value)
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.formData.events.includes(opt.value)
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 8, right: 8, top: 4, bottom: 4 })
                .borderRadius(this.sm.getRadius('sm'))
                .margin({ right: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('xs') })
                .onClick(() => { this.toggleEvent(opt.value); })
            }, (opt: EventOption) => opt.value)
          }
          .width('100%')
          .margin({ top: this.sm.getSpacing('xs') })

          // 密钥输入
          Text('密钥（可选）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '签名密钥',
            value: this.formData.secret,
            type: 'text',
            onChange: (v: string) => { this.inputSecret(v); },
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
}
