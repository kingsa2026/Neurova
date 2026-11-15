/**
 * AgentChannelPage - 智能体渠道管理页
 *
 * 职责：展示当前 Agent 已连接的所有渠道（飞书/钉钉/Telegram 等），
 *       支持连接测试、启用/禁用、删除、新建
 * 设计：
 *   - Column [TopNavMenu(标题"渠道管理"+返回+新建)] + [当前 Agent 名] +
 *            [加载态/空态/列表]；
 *   - 列表项为 GlassCard，包含渠道类型图标+名称、状态徽章、配置摘要、
 *     连接时间、最后事件时间、错误信息（error 时）、操作按钮（测试/启停/删除）；
 *   - 删除操作需二次确认（AlertDialog）；新建走 CustomDialog 选择类型+填配置；
 *   - 颜色统一走 StyleManager，路由走 Router，API 走 ApiFacade.agentChannels，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（ChannelViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getTypeIcon 返回渠道类型对应的 emoji 图标字符；
 *   - getTypeLabel 返回渠道类型对应的中文显示名；
 *   - getStatusColor 返回状态对应的颜色 token 名（'success'/'error'/'warning'/'text_disabled'），
 *     由调用方通过 StyleManager.getColor(token) 解析为实际颜色，便于主题切换。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（agentChannels 模块：list/create/remove/testConnection/toggle）
 *   - ../libs/state/stores/AgentsStore：Agent 状态管理（currentAgentId、currentAgent）
 *   - ../routing/Router：统一路由跳转 + RouteNames（含 AGENT_CHANNEL）
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ChannelInfo、ChannelType、ChannelStatus
 *
 * 用法：
 *   由 Router.push(RouteNames.AGENT_CHANNEL) 跳转进入；
 *   aboutToAppear 从 AgentsStore 取 currentAgentId，调用 api.agentChannels.list(agentId) 加载；
 *   测试连接：调用 api.agentChannels.testConnection(agentId, channelId) → 显示结果；
 *   启用/禁用：调用 api.agentChannels.toggle(agentId, channelId, enabled) → 刷新列表；
 *   删除：AlertDialog 二次确认 → api.agentChannels.remove(agentId, channelId) → 刷新；
 *   新建：CustomDialog 选择类型 + 填写配置 → api.agentChannels.create(agentId, data) → 刷新。
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ChannelInfo, ChannelType, ChannelStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentChannelPage';

/**
 * ChannelViewHelper - 渠道管理页视图模型纯函数集合
 *
 * 职责：封装渠道类型图标映射、渠道类型显示名映射、状态颜色映射等纯展示逻辑
 * 设计：全部为静态方法、无副作用、无 UI 依赖，可直接单元测试
 *
 * 用法：
 *   const icon = ChannelViewHelper.getTypeIcon(channel.type);
 *   const label = ChannelViewHelper.getTypeLabel(channel.type);
 *   const colorToken = ChannelViewHelper.getStatusColor(channel.status);
 *   const color = sm.getColor(colorToken);
 */
export class ChannelViewHelper {
  /**
   * 获取渠道类型对应的图标 emoji
   * 映射：
   *   feishu   → 🐦
   *   dingtalk → 💬
   *   telegram → ✈️
   *   discord  → 🎮
   *   wechat   → 💚
   *   webhook  → 🔗
   *   api      → ⚙️
   *   email    → 📧
   *   未知     → ❓
   */
  static getTypeIcon(type: ChannelType): string {
    if (type === 'feishu') {
      return '🐦';
    }
    if (type === 'dingtalk') {
      return '💬';
    }
    if (type === 'telegram') {
      return '✈️';
    }
    if (type === 'discord') {
      return '🎮';
    }
    if (type === 'wechat') {
      return '💚';
    }
    if (type === 'webhook') {
      return '🔗';
    }
    if (type === 'api') {
      return '⚙️';
    }
    if (type === 'email') {
      return '📧';
    }
    return '❓';
  }

  /**
   * 获取渠道类型对应的中文显示名
   * 映射：
   *   feishu   → 飞书
   *   dingtalk → 钉钉
   *   telegram → Telegram
   *   discord  → Discord
   *   wechat   → 微信
   *   webhook  → Webhook
   *   api      → API
   *   email    → 邮箱
   *   未知     → 未知
   */
  static getTypeLabel(type: ChannelType): string {
    if (type === 'feishu') {
      return '飞书';
    }
    if (type === 'dingtalk') {
      return '钉钉';
    }
    if (type === 'telegram') {
      return 'Telegram';
    }
    if (type === 'discord') {
      return 'Discord';
    }
    if (type === 'wechat') {
      return '微信';
    }
    if (type === 'webhook') {
      return 'Webhook';
    }
    if (type === 'api') {
      return 'API';
    }
    if (type === 'email') {
      return '邮箱';
    }
    return '未知';
  }

  /**
   * 获取渠道状态对应的颜色 token 名
   * 映射：connected→success / disconnected→text_disabled / error→error / disabled→warning / 未知→text_disabled
   * 返回 token 名（非颜色值），由调用方通过 StyleManager.getColor(token) 解析
   */
  static getStatusColor(status: ChannelStatus): string {
    if (status === 'connected') {
      return 'success';
    }
    if (status === 'disconnected') {
      return 'text_disabled';
    }
    if (status === 'error') {
      return 'error';
    }
    if (status === 'disabled') {
      return 'warning';
    }
    return 'text_disabled';
  }
}

/** 新建渠道表单数据 */
interface ChannelFormData {
  type: ChannelType;
  name: string;
  appId: string;
  appSecret: string;
  webhookUrl: string;
}

@Component
export struct AgentChannelPage {
  // 渠道列表（由 API 加载，驱动列表渲染）
  @State channels: ChannelInfo[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前 Agent 名称（用于头部展示，空值回退"未选择智能体"）
  @State currentAgentName: string = '';

  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据
  @State formData: ChannelFormData = {
    type: 'feishu' as ChannelType,
    name: '',
    appId: '',
    appSecret: '',
    webhookUrl: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadCurrentAgent();
    this.loadChannels();
  }

  /**
   * 加载当前 Agent 名称
   * 流程：从 AgentsStore 读取 currentAgent → 写入 currentAgentName
   */
  private loadCurrentAgent(): void {
    const agent = this.agentsStore.currentAgent;
    this.currentAgentName = agent ? agent.name : '未选择智能体';
  }

  /**
   * 加载渠道列表
   * 流程：取 currentAgentId → 调用 API 获取列表 → 写回 @State
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadChannels(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.agentChannels.list(agentId);
      if (res.code === 0 && res.data) {
        this.channels = res.data;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载渠道失败', e as Error);
      this.msg.error('加载渠道失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 测试渠道连接
   * 流程：调用 API testConnection → 根据结果显示成功/失败消息
   * 异常：记录日志并提示用户
   */
  private async testConnection(channel: ChannelInfo): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) return;
    try {
      const res = await this.api.agentChannels.testConnection(agentId, channel.id);
      if (res.code === 0 && res.data) {
        if (res.data.success) {
          this.msg.success('连接成功');
        } else {
          this.msg.error(res.data.message || '连接失败');
        }
      } else {
        this.msg.error(res.message || '测试失败');
      }
    } catch (e) {
      this.logger.error(TAG, '测试连接失败', e as Error);
      this.msg.error('测试连接失败');
    }
  }

  /**
   * 切换渠道启用/禁用
   * 流程：调用 API toggle → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async toggleChannel(channel: ChannelInfo, enabled: boolean): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) return;
    try {
      const res = await this.api.agentChannels.toggle(agentId, channel.id, enabled);
      if (res.code === 0) {
        this.msg.success(enabled ? '已启用' : '已禁用');
        this.loadChannels();
      } else {
        this.msg.error(res.message || '操作失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换渠道状态失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /**
   * 删除前二次确认
   * 使用 AlertDialog 弹窗，避免误删；确认后调用 removeChannel
   */
  private confirmDelete(channel: ChannelInfo): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除渠道"${channel.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.removeChannel(channel); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 API remove → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async removeChannel(channel: ChannelInfo): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) return;
    try {
      const res = await this.api.agentChannels.remove(agentId, channel.id);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadChannels();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除渠道失败', e as Error);
      this.msg.error('删除渠道失败');
    }
  }

  /**
   * 打开新建弹窗
   * 重置表单数据为默认值（feishu + 空字符串）
   */
  private openCreateDialog(): void {
    this.formData = {
      type: 'feishu' as ChannelType,
      name: '',
      appId: '',
      appSecret: '',
      webhookUrl: '',
    };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 API create → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }
    if (!this.formData.name) {
      this.msg.warning('请填写渠道名称');
      return;
    }
    try {
      const data: Partial<ChannelInfo> = {
        type: this.formData.type,
        name: this.formData.name,
        appId: this.formData.appId,
        webhookUrl: this.formData.webhookUrl,
        config: {
          appId: this.formData.appId,
          appSecret: this.formData.appSecret,
          webhookUrl: this.formData.webhookUrl,
        },
      };
      const res = await this.api.agentChannels.create(agentId, data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadChannels();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建渠道失败', e as Error);
      this.msg.error('创建渠道失败');
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

  /** 获取配置摘要（appId / webhookUrl 截断显示） */
  private getConfigSummary(channel: ChannelInfo): string {
    const parts: string[] = [];
    if (channel.appId) {
      const id = channel.appId;
      const short = id.length > 12 ? `${id.substring(0, 12)}...` : id;
      parts.push(`appId: ${short}`);
    }
    if (channel.webhookUrl) {
      const url = channel.webhookUrl;
      const short = url.length > 30 ? `${url.substring(0, 30)}...` : url;
      parts.push(`webhook: ${short}`);
    }
    return parts.length > 0 ? parts.join(' · ') : '无配置';
  }

  build() {
    Column() {
      // 顶部导航栏：标题"渠道管理" + 返回按钮 + 新建按钮（右侧插槽）
      TopNavMenu({
        title: '渠道管理',
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

      // 当前 Agent 名称
      Text(`当前智能体：${this.currentAgentName}`)
        .fontSize(this.sm.getFontSize('caption'))
        .fontColor(this.sm.getColor('text_secondary'))
        .width('100%')
        .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md'), top: this.sm.getSpacing('sm') })

      if (this.loading) {
        // 加载态：居中显示"加载中..."
        Column() {
          Text('加载中...')
            .fontSize(this.sm.getFontSize('body'))
            .fontColor(this.sm.getColor('text_secondary'))
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else if (this.channels.length === 0) {
        // 空列表：居中显示"暂无渠道"+ 新建按钮
        Column() {
          Text('暂无渠道')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ bottom: this.sm.getSpacing('md') })
          GlassButton({
            text: '新建渠道',
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
        // 渠道列表：纵向滚动，卡片间距 12，关闭滚动条
        List({ space: 12 }) {
          ForEach(this.channels, (channel: ChannelInfo) => {
            ListItem() {
              this.buildChannelCard(channel)
            }
          }, (channel: ChannelInfo) => channel.id)
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

      // 新建渠道弹窗
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  // ===========================================================================
  // 渠道卡片构建器
  // ===========================================================================

  /** 单个渠道卡片：图标+名称+状态 / 配置摘要 / 时间 / 错误信息 / 操作按钮 */
  @Builder
  buildChannelCard(channel: ChannelInfo) {
    GlassCard() {
      Column() {
        // 上部：图标 + 名称/状态徽章
        Row() {
          // 渠道类型图标
          Text(ChannelViewHelper.getTypeIcon(channel.type))
            .fontSize(24)
            .width(40)
            .height(40)
            .textAlign(TextAlign.Center)

          // 信息列：名称 + 类型显示名 + 状态徽章
          Column() {
            // 名称
            Text(channel.name)
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })

            // 类型显示名
            Text(ChannelViewHelper.getTypeLabel(channel.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 2 })

            // 状态徽章：圆点 + 状态文案
            Row() {
              Row()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor(this.sm.getColor(ChannelViewHelper.getStatusColor(channel.status)))
              Text(this.getStatusLabel(channel.status))
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 4 })
            }
            .margin({ top: 4 })
            .alignItems(VerticalAlign.Center)
          }
          .layoutWeight(1)
          .alignItems(HorizontalAlign.Start)
          .margin({ left: this.sm.getSpacing('sm') })
        }
        .width('100%')
        .alignItems(VerticalAlign.Top)

        // 配置摘要
        Text(this.getConfigSummary(channel))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: this.sm.getSpacing('sm') })
          .width('100%')

        // 时间行：连接时间 + 最后事件时间
        Row() {
          Text(`连接：${this.formatTime(channel.connectedAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 4, right: 4 })
          Text(`最后事件：${this.formatTime(channel.lastEventAt)}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .margin({ top: 4 })
        .alignItems(VerticalAlign.Center)

        // 错误信息（status=error 时显示）
        if (channel.status === 'error' && channel.errorMessage) {
          Text(`错误：${channel.errorMessage}`)
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('error'))
            .maxLines(2)
            .textOverflow({ overflow: TextOverflow.Ellipsis })
            .margin({ top: 4 })
            .width('100%')
        }

        // 下部：操作按钮（右对齐）
        Row() {
          GlassButton({
            text: '测试',
            type: 'default',
            size: 'small',
            onClick: () => { this.testConnection(channel); }
          })
          GlassButton({
            text: channel.enabled ? '禁用' : '启用',
            type: channel.enabled ? 'default' : 'primary',
            size: 'small',
            onClick: () => { this.toggleChannel(channel, !channel.enabled); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(channel); }
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

  /** 新建渠道弹窗：选择类型 + 填写配置 */
  @Builder
  buildCreateDialog() {
    GlassPanel() {
      Column() {
        // 标题
        Text('新建渠道')
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .margin({ bottom: this.sm.getSpacing('md') })

        // 渠道类型选择（横向滚动）
        Text('渠道类型')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        Row() {
          ForEach(this.getChannelTypeOptions(), (opt: { type: ChannelType; label: string; icon: string }) => {
            GlassButton({
              text: `${opt.icon} ${opt.label}`,
              type: this.formData.type === opt.type ? 'primary' : 'default',
              size: 'small',
              onClick: () => {
                this.formData = { ...this.formData, type: opt.type };
              }
            })
            .margin({ right: this.sm.getSpacing('xs') })
          }, (opt: { type: ChannelType; label: string; icon: string }) => opt.type)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })

        // 渠道名称
        Text('渠道名称')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入渠道名称',
          value: this.formData.name,
          type: 'text',
          onChange: (v: string) => { this.formData.name = v; }
        })
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

        // AppId
        Text('AppId')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入 AppId',
          value: this.formData.appId,
          type: 'text',
          onChange: (v: string) => { this.formData = { ...this.formData, appId: v }; }
        })
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

        // AppSecret
        Text('AppSecret')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入 AppSecret',
          value: this.formData.appSecret,
          type: 'password',
          onChange: (v: string) => { this.formData = { ...this.formData, appSecret: v }; }
        })
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

        // WebhookUrl
        Text('Webhook URL')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入 Webhook URL',
          value: this.formData.webhookUrl,
          type: 'text',
          onChange: (v: string) => { this.formData = { ...this.formData, webhookUrl: v }; }
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
    .padding(this.sm.getSpacing('md'))
  }

  /** 获取渠道类型选项列表（用于新建弹窗选择） */
  private getChannelTypeOptions(): { type: ChannelType; label: string; icon: string }[] {
    const types: ChannelType[] = [
      'feishu' as ChannelType,
      'dingtalk' as ChannelType,
      'telegram' as ChannelType,
      'discord' as ChannelType,
      'wechat' as ChannelType,
      'webhook' as ChannelType,
      'api' as ChannelType,
      'email' as ChannelType,
    ];
    return types.map((t: ChannelType) => ({
      type: t,
      label: ChannelViewHelper.getTypeLabel(t),
      icon: ChannelViewHelper.getTypeIcon(t),
    }));
  }

  /** 获取状态文案：connected→已连接，disconnected→未连接，error→异常，disabled→已禁用 */
  private getStatusLabel(status: ChannelStatus): string {
    if (status === 'connected') {
      return '已连接';
    }
    if (status === 'disconnected') {
      return '未连接';
    }
    if (status === 'error') {
      return '异常';
    }
    if (status === 'disabled') {
      return '已禁用';
    }
    return '未知';
  }
}
