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
import { ChannelType } from '../libs/types';
import { ChannelConfigDto, ChannelConfigUpsertBody, emptyExtra } from '../libs/api/modules/AgentChannelsApi';

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
  static getTypeIcon(type: string): string {
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
  static getTypeLabel(type: string): string {
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
  static getStatusColor(status: string): string {
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
  appId: string;
  appSecret: string;
  webhookUrl: string;
}

/** 渠道类型选项（新建弹窗类型选择条目） */
interface ChannelTypeOption {
  type: ChannelType;
  label: string;
  icon: string;
}

@Component
export struct AgentChannelPage {
  // 渠道配置列表（/v1/channel-configs?agent_id= 真实数据）
  @State channels: ChannelConfigDto[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前 Agent 名称（用于头部展示，空值回退"未选择智能体"）
  @State currentAgentName: string = '';

  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据
  @State formData: ChannelFormData = {
    type: 'feishu' as ChannelType,
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
   * 测试渠道连接（POST /v1/channel-configs/{type}/test?agent_id=）
   * 流程：调用 API testConnection → 根据结果显示成功/失败消息
   * 异常：记录日志并把后端原因透出
   */
  private async testConnection(channel: ChannelConfigDto): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) return;
    try {
      const res = await this.api.agentChannels.testConnection(agentId, channel.channel_type);
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
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '测试连接失败');
    }
  }

  /**
   * 删除前二次确认
   * 使用 AlertDialog 弹窗，避免误删；确认后调用 removeChannel
   */
  private confirmDelete(channel: ChannelConfigDto): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除渠道"${channel.channel_type}"的配置吗？此操作不可撤销。`,
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
   * 执行删除（DELETE /v1/channel-configs/{type}?agent_id=）
   * 流程：调用 API remove → 成功后重新加载列表
   * 异常：记录日志并把后端原因透出
   */
  private async removeChannel(channel: ChannelConfigDto): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) return;
    try {
      await this.api.agentChannels.remove(agentId, channel.channel_type);
      this.msg.success('删除成功');
      this.loadChannels();
    } catch (e) {
      this.logger.error(TAG, '删除渠道失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '删除渠道失败');
    }
  }

  /**
   * 打开新建弹窗
   * 重置表单数据为默认值（feishu + 空字符串）
   */
  private openCreateDialog(): void {
    this.formData = {
      type: 'feishu' as ChannelType,
      appId: '',
      appSecret: '',
      webhookUrl: '',
    };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建（POST /v1/channel-configs?agent_id=，ChannelConfigRequest 契约）
   * 流程：组装 body → 调用 API create → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并把后端原因透出（含平台身份冲突 409）
   */
  private async submitCreate(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }
    try {
      const body: ChannelConfigUpsertBody = {
        channel_type: this.formData.type,
        enabled: true,
        app_id: this.formData.appId,
        app_secret: this.formData.appSecret,
        use_stream: true,
        webhook_url: this.formData.webhookUrl,
        webhook_token: '',
        encrypt_key: '',
        verification_token: '',
        extra: emptyExtra(),
      };
      await this.api.agentChannels.create(agentId, body);
      this.msg.success('创建成功');
      this.showCreateDialog = false;
      this.loadChannels();
    } catch (e) {
      this.logger.error(TAG, '创建渠道失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '创建渠道失败');
    }
  }

  /** 获取配置摘要（凭据掩码 + 传输模式） */
  private getConfigSummary(channel: ChannelConfigDto): string {
    const parts: string[] = [];
    if (channel.app_id_masked && channel.app_id_masked.length > 0) {
      parts.push(`appId: ${channel.app_id_masked}`);
    }
    parts.push(channel.use_stream ? 'Stream 模式' : 'Webhook 模式');
    return parts.join(' · ');
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
          btnSize: 'small',
          onTap: () => { this.openCreateDialog(); }
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
            btnSize: 'medium',
            onTap: () => { this.openCreateDialog(); }
          })
        }
        .width('100%')
        .layoutWeight(1)
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      } else {
        // 渠道列表：纵向滚动，卡片间距 12，关闭滚动条
        List({ space: 12 }) {
          ForEach(this.channels, (channel: ChannelConfigDto) => {
            ListItem() {
              this.buildChannelCard(channel)
            }
          }, (channel: ChannelConfigDto) => channel.channel_type)
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

  /**
   * 单个渠道卡片：图标+类型+状态 / 配置摘要 / 操作按钮
   * 状态由后端 connected/enabled 两布尔推导（真实契约无独立 status 字段）
   */
  @Builder
  buildChannelCard(channel: ChannelConfigDto) {
    // ArkTS 解析器不允许尾随闭包组件调用后再链属性修饰，外包 Column 承接 .width
    Column() {
    GlassCard() {
      Column() {
        // 上部：图标 + 类型/状态徽章
        Row() {
          // 渠道类型图标
          Text(ChannelViewHelper.getTypeIcon(channel.channel_type))
            .fontSize(24)
            .width(40)
            .height(40)
            .textAlign(TextAlign.Center)

          // 信息列：类型显示名 + 状态徽章
          Column() {
            // 类型显示名
            Text(ChannelViewHelper.getTypeLabel(channel.channel_type))
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .maxLines(1)
              .textOverflow({ overflow: TextOverflow.Ellipsis })

            // 原始渠道类型
            Text(channel.channel_type)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 2 })

            // 状态徽章：圆点 + 状态文案
            Row() {
              Row()
                .width(8)
                .height(8)
                .borderRadius(4)
                .backgroundColor(this.sm.getColor(ChannelViewHelper.getStatusColor(this.displayStatus(channel))))
              Text(this.getStatusLabel(this.displayStatus(channel)))
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

        // 下部：操作按钮（右对齐；后端无 toggle 端点，启停由配置 enabled 在保存时生效）
        Row() {
          GlassButton({
            text: '测试',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.testConnection(channel); }
          })
          GlassButton({
            text: '删除',
            type: 'danger',
            btnSize: 'small',
            onTap: () => { this.confirmDelete(channel); }
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
    }
    .width('100%')
  }

  /** 由 connected/enabled 推导展示状态（真实契约字段） */
  private displayStatus(channel: ChannelConfigDto): string {
    if (channel.connected) return 'connected';
    if (!channel.enabled) return 'disabled';
    return 'disconnected';
  }

  // ===========================================================================
  // 新建弹窗构建器
  // ===========================================================================

  /** 新建渠道弹窗：选择类型 + 填写配置 */
  @Builder
  buildCreateDialog() {
    // ArkTS 解析器不允许尾随闭包组件调用后再链属性修饰，外包 Column 承接尺寸与内边距
    Column() {
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
          ForEach(this.getChannelTypeOptions(), (opt: ChannelTypeOption) => {
            GlassButton({
              text: `${opt.icon} ${opt.label}`,
              type: this.formData.type === opt.type ? 'primary' : 'default',
              btnSize: 'small',
              onTap: () => {
                // ArkTS 禁止对象展开，逐键拷贝生成新对象以触发 @State 渲染
                const next: ChannelFormData = {
                  type: opt.type,
                  appId: this.formData.appId,
                  appSecret: this.formData.appSecret,
                  webhookUrl: this.formData.webhookUrl,
                };
                this.formData = next;
              }
            })
            .margin({ right: this.sm.getSpacing('xs') })
          }, (opt: ChannelTypeOption) => opt.type)
        }
        .width('100%')
        .margin({ top: this.sm.getSpacing('xs'), bottom: this.sm.getSpacing('sm') })

        // AppId
        Text('AppId')
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .width('100%')
        GlassInput({
          placeholder: '请输入 AppId',
          value: this.formData.appId,
          type: 'text',
          onChange: (v: string) => {
            // ArkTS 禁止对象展开，逐键拷贝生成新对象以触发 @State 渲染
            const next: ChannelFormData = {
              type: this.formData.type,
              appId: v,
              appSecret: this.formData.appSecret,
              webhookUrl: this.formData.webhookUrl,
            };
            this.formData = next;
          }
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
          onChange: (v: string) => {
            // ArkTS 禁止对象展开，逐键拷贝生成新对象以触发 @State 渲染
            const next: ChannelFormData = {
              type: this.formData.type,
              appId: this.formData.appId,
              appSecret: v,
              webhookUrl: this.formData.webhookUrl,
            };
            this.formData = next;
          }
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
          onChange: (v: string) => {
            // ArkTS 禁止对象展开，逐键拷贝生成新对象以触发 @State 渲染
            const next: ChannelFormData = {
              type: this.formData.type,
              appId: this.formData.appId,
              appSecret: this.formData.appSecret,
              webhookUrl: v,
            };
            this.formData = next;
          }
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
    .padding(this.sm.getSpacing('md'))
  }

  /** 获取渠道类型选项列表（用于新建弹窗选择） */
  private getChannelTypeOptions(): ChannelTypeOption[] {
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
    return types.map((t: ChannelType): ChannelTypeOption => {
      const opt: ChannelTypeOption = {
        type: t,
        label: ChannelViewHelper.getTypeLabel(t),
        icon: ChannelViewHelper.getTypeIcon(t),
      };
      return opt;
    });
  }

  /** 获取状态文案：connected→已连接，disconnected→未连接，error→异常，disabled→已禁用 */
  private getStatusLabel(status: string): string {
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
