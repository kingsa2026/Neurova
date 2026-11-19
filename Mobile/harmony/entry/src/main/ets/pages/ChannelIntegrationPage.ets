/**
 * ChannelIntegrationPage - 渠道集成页（M9.2 渠道域契约迁移）
 *
 * 职责：展示渠道配置列表（GET /v1/channel-configs?agent_id=，真实端点），
 *   支持新建/编辑（POST upsert）、测试连接（POST /{type}/test）、删除（DELETE /{type}）
 * 设计：
 *   - ChannelIntegrationViewHelper（导出）：纯视图模型，封装状态颜色/图标/文案映射、
 *     名称截断，无 UI 运行时依赖，可独立单元测试；
 *   - ChannelIntegrationPage（@Component）：Stack[Column[TopNavMenu(标题"渠道集成"+返回+新建)]
 *     + [搜索框（按 channel_type 过滤）] + [加载态/错误态/空态/列表] + [新建/编辑弹窗]]；
 *     列表项 GlassCard 含连接状态徽章、渠道类型、凭据掩码、传输模式、操作按钮；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.channelIntegration（list/saveConfig/removeConfig/testConfig），
 *     消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（channelIntegration 模块）
 *   - ../libs/api/modules/ChannelIntegrationApi：渠道域真实 DTO
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.channelIntegration.list 加载列表；
 *   新建/编辑 → 弹窗填 channel_type/app_id/app_secret/webhook_url → saveConfig；
 *   测试连接 → api.channelIntegration.testConfig → 提示结果；
 *   删除 → AlertDialog 二次确认 → api.channelIntegration.removeConfig → 刷新列表
 *
 * TDD：ChannelIntegrationViewHelper 各方法按红绿灯垂直切片逐步实现，
 *      详见 ChannelIntegrationPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { ChannelConfigDto, ChannelConfigUpsertBody, emptyExtra } from '../libs/api/modules/ChannelIntegrationApi';
import { Agent } from '../libs/types';

/** 日志标签 */
const TAG = 'ChannelIntegrationPage';

/** 默认截断长度（与样板页保持一致，便于测试断言） */
const DEFAULT_TRUNCATE_LEN = 16;

/** 默认 agentId（后端渠道配置按 agent 隔离，缺省 default） */
const DEFAULT_AGENT_ID = 'default';

// ===========================================================================
// ChannelIntegrationViewHelper - 渠道集成视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'status_success'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class ChannelIntegrationViewHelper {
  /**
   * 获取渠道集成状态对应的颜色 token 名
   * 映射：connected→status_success, disconnected→text_secondary,
   *       error→status_error, syncing→status_warning, disabled→text_disabled
   * @param status 集成状态（后端 connected/enabled 推导，宽松接收）
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: string): string {
    if (status === 'connected') return 'status_success';
    if (status === 'disconnected') return 'text_secondary';
    if (status === 'error') return 'status_error';
    if (status === 'disabled') return 'text_disabled';
    return 'status_warning';
  }

  /**
   * 获取渠道集成状态对应的图标 emoji
   * 映射：connected→✅, disconnected→⚪, error→❌, syncing→🔄, disabled→⏸️
   * @param status 集成状态（宽松接收）
   * @return emoji 字符串
   */
  static getStatusIcon(status: string): string {
    if (status === 'connected') return '✅';
    if (status === 'disconnected') return '⚪';
    if (status === 'error') return '❌';
    if (status === 'disabled') return '⏸️';
    return '🔄';
  }

  /**
   * 获取渠道集成状态对应的中文标签
   * 映射：connected→已连接, disconnected→未连接, error→错误, syncing→同步中, disabled→已禁用
   * @param status 集成状态（宽松接收）
   * @return 中文标签
   */
  static getStatusLabel(status: string): string {
    if (status === 'connected') return '已连接';
    if (status === 'disconnected') return '未连接';
    if (status === 'error') return '错误';
    if (status === 'disabled') return '已禁用';
    return '同步中';
  }

  /**
   * 格式化能力列表为文案
   * 规则：空数组 → "无"；非空 → 用顿号 "、" 连接
   * @param capabilities 能力标识数组
   * @return 能力文案
   */
  static getCapabilitiesText(capabilities: string[]): string {
    if (!capabilities || capabilities.length === 0) return '无';
    return capabilities.join('、');
  }

  /**
   * 截断渠道名称
   * 规则：
   *   - name 为空 → 返回空字符串
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param name 渠道名称
   * @param maxLen 最大长度，默认 16
   * @return 截断后的名称
   */
  static truncateName(name: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!name || name.length === 0) return '';
    if (name.length <= len) return name;
    return name.substring(0, len) + '...';
  }
}

/** 渠道配置表单数据（新建/编辑共用；对应 ChannelConfigRequest 契约字段） */
interface ChannelConfigFormData {
  channelType: string;
  appId: string;
  appSecret: string;
  webhookUrl: string;
}

/** 弹窗模式 */
type DialogMode = 'create' | 'edit';

@Component
export struct ChannelIntegrationPage {
  // 渠道配置列表（/v1/channel-configs 真实数据）
  @State integrations: ChannelConfigDto[] = [];
  // 加载态
  @State loading: boolean = true;
  // 错误文案（非空时显示错误态）
  @State errorMsg: string = '';
  // 搜索关键字（按 channel_type 本地过滤）
  @State keyword: string = '';
  // 弹窗显示状态
  @State showDialog: boolean = false;
  // 弹窗模式（create/edit）
  @State dialogMode: DialogMode = 'create';
  // 当前编辑的渠道类型（编辑模式用）
  @State editingType: string = '';
  // 表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: ChannelConfigFormData = {
    channelType: '',
    appId: '',
    appSecret: '',
    webhookUrl: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();
  // Agent 切换（渠道配置按 agent 隔离；默认 default）
  @State agents: Agent[] = [];
  @State selectedAgentId: string = DEFAULT_AGENT_ID;

  aboutToAppear() {
    this.loadIntegrations();
    this.loadAgents();
  }

  /** Agent 切换源列表（admin 全量、普通用户自有） */
  private async loadAgents(): Promise<void> {
    try {
      this.agents = await this.api.agents.list();
    } catch (e) {
      this.logger.error(TAG, 'Agent 列表加载失败', e as Error);
    }
  }

  /**
   * 加载渠道配置列表（GET /v1/channel-configs?agent_id=）
   * 流程：调用 api.channelIntegration.list → 写入 integrations
   * 异常：记录日志并把后端原因透出；无论成败 finally 关闭 loading
   */
  private async loadIntegrations(): Promise<void> {
    this.loading = true;
    this.errorMsg = '';
    try {
      const res = await this.api.channelIntegration.list(this.selectedAgentId, undefined);
      if (res.code === 0 && res.data) {
        this.integrations = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载渠道集成失败', e as Error);
      this.errorMsg = (e as Error).message.length > 0 ? (e as Error).message : '加载渠道集成列表失败';
    } finally {
      this.loading = false;
    }
  }

  /**
   * 获取经关键字筛选后的列表
   * 规则：keyword 为空返回全量；否则按 channel_type 包含关键字过滤
   */
  private getFilteredList(): ChannelConfigDto[] {
    if (!this.keyword || this.keyword.length === 0) {
      return this.integrations;
    }
    const kw = this.keyword.toLowerCase();
    return this.integrations.filter((ci: ChannelConfigDto) =>
      ci.channel_type.toLowerCase().includes(kw));
  }

  /** 由配置推导展示状态（后端只给 connected/enabled 两个布尔） */
  private displayStatus(item: ChannelConfigDto): string {
    if (item.connected) return 'connected';
    if (!item.enabled) return 'disabled';
    return 'disconnected';
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.dialogMode = 'create';
    this.editingType = '';
    this.formData = { channelType: '', appId: '', appSecret: '', webhookUrl: '' };
    this.showDialog = true;
  }

  /** 打开编辑弹窗，预填当前渠道配置（凭据为掩码，原样回传即保持不变） */
  private openEditDialog(item: ChannelConfigDto): void {
    this.dialogMode = 'edit';
    this.editingType = item.channel_type;
    this.formData = {
      channelType: item.channel_type,
      appId: item.app_id_masked,
      appSecret: '',
      webhookUrl: item.extra['webhook_url'] !== undefined ? String(item.extra['webhook_url']) : '',
    };
    this.showDialog = true;
  }

  /** 组装 upsert body（ChannelConfigRequest 契约，蛇形字段） */
  private buildUpsertBody(): ChannelConfigUpsertBody {
    const body: ChannelConfigUpsertBody = {
      channel_type: this.formData.channelType,
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
    return body;
  }

  /**
   * 提交新建（POST /v1/channel-configs?agent_id=，upsert）
   * 异常：记录日志并把后端原因透出（含平台身份冲突 409 / 需扫码 needs_scan）
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.channelType) {
      this.msg.warning('请填写渠道类型');
      return;
    }
    try {
      const res = await this.api.channelIntegration.saveConfig(this.selectedAgentId, this.buildUpsertBody());
      if (res.data.success) {
        if (res.data.needs_scan) {
          this.msg.warning('配置已保存：该渠道需扫码确认后生效');
        } else {
          this.msg.success('保存成功');
        }
        this.showDialog = false;
        this.loadIntegrations();
      } else {
        this.msg.error(res.data.message || '保存失败');
      }
    } catch (e) {
      this.logger.error(TAG, '保存渠道集成失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '保存渠道集成失败');
    }
  }

  /**
   * 提交编辑（同走 saveConfig upsert）
   * 异常：记录日志并把后端原因透出
   */
  private async submitEdit(): Promise<void> {
    if (!this.formData.channelType) {
      this.msg.warning('请填写渠道类型');
      return;
    }
    try {
      const res = await this.api.channelIntegration.saveConfig(this.selectedAgentId, this.buildUpsertBody());
      if (res.data.success) {
        this.msg.success('更新成功');
        this.showDialog = false;
        this.loadIntegrations();
      } else {
        this.msg.error(res.data.message || '更新失败');
      }
    } catch (e) {
      this.logger.error(TAG, '更新渠道集成失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '更新渠道集成失败');
    }
  }

  /** 提交弹窗（按 dialogMode 路由到新建/编辑） */
  private submitDialog(): void {
    if (this.dialogMode === 'create') {
      this.submitCreate();
    } else {
      this.submitEdit();
    }
  }

  /**
   * 测试渠道连接（POST /v1/channel-configs/{type}/test?agent_id=）
   * 异常：记录日志并把后端原因透出
   */
  private async testConnection(item: ChannelConfigDto): Promise<void> {
    try {
      const body: ChannelConfigUpsertBody = {
        channel_type: item.channel_type,
        enabled: true,
        app_id: '',
        app_secret: '',
        use_stream: item.use_stream,
        webhook_url: '',
        webhook_token: '',
        encrypt_key: '',
        verification_token: '',
        extra: emptyExtra(),
      };
      const res = await this.api.channelIntegration.testConfig(this.selectedAgentId, item.channel_type, body);
      if (res.data.success) {
        this.msg.success(res.data.message.length > 0 ? res.data.message : '连接正常');
      } else {
        this.msg.warning(res.data.message.length > 0 ? res.data.message : '连接失败');
      }
    } catch (e) {
      this.logger.error(TAG, '测试渠道连接失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '测试渠道连接失败');
    }
  }

  /** 删除前二次确认（AlertDialog） */
  private confirmDelete(item: ChannelConfigDto): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除渠道"${item.channel_type}"的配置吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteIntegration(item.channel_type); }
      }
    });
  }

  /**
   * 执行删除（DELETE /v1/channel-configs/{type}?agent_id=）
   * 流程：调用 api.channelIntegration.removeConfig → 成功后刷新列表
   * 异常：记录日志并把后端原因透出
   */
  private async deleteIntegration(channelType: string): Promise<void> {
    try {
      await this.api.channelIntegration.removeConfig(DEFAULT_AGENT_ID, channelType);
      this.msg.success('删除成功');
      this.loadIntegrations();
    } catch (e) {
      this.logger.error(TAG, '删除渠道集成失败', e as Error);
      this.msg.error((e as Error).message.length > 0 ? (e as Error).message : '删除渠道集成失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"渠道集成" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '渠道集成',
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

        // Agent 切换胶囊（渠道配置按 agent 隔离）
        Scroll() {
          Row({ space: 8 }) {
            ForEach(this.agents, (a: Agent) => {
              Text(a.name)
                .fontSize(12)
                .fontColor(this.selectedAgentId === a.id
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.selectedAgentId === a.id
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(14)
                .onClick(() => {
                  this.selectedAgentId = a.id;
                  this.loadIntegrations();
                })
            }, (a: Agent) => a.id)
          }
          .padding({ left: 20, right: 20 })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .margin({ bottom: this.sm.getSpacing('sm') })

        // 搜索框：按 channel_type 过滤
        GlassInput({
          placeholder: '搜索渠道类型',
          value: this.keyword,
          type: 'text',
          onChange: (v: string) => { this.keyword = v; }
        })
          .width('90%')
          .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })

        // 主体内容：加载态 / 错误态 / 空态 / 列表 四选一
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
        } else if (this.errorMsg.length > 0) {
          Column() {
            Text('渠道配置加载失败')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('status_error'))
            Text(this.errorMsg)
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ top: 8 })
            GlassButton({
              text: '重试',
              type: 'default',
              btnSize: 'small',
              onTap: () => { this.loadIntegrations(); }
            })
              .margin({ top: 12 })
          }
          .width('90%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无渠道集成')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (item: ChannelConfigDto) => {
              ListItem() {
                this.buildIntegrationCard(item)
              }
            }, (item: ChannelConfigDto) => item.channel_type)
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

      // 弹窗：内嵌 Stack 条件渲染（新建/编辑共用）
      if (this.showDialog) {
        this.buildDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 渠道集成卡片构建器
  // ===========================================================================

  /** 单个渠道配置卡片：连接状态徽章 + 渠道类型 + 凭据掩码/传输模式 + 操作按钮 */
  @Builder
  buildIntegrationCard(item: ChannelConfigDto) {
    Column() {
    GlassCard() {
      Column() {
        // 上部：状态徽章（图标 + 文案 + 圆点）
        Row() {
          Text(ChannelIntegrationViewHelper.getStatusIcon(this.displayStatus(item)))
            .fontSize(16)
          Text(ChannelIntegrationViewHelper.getStatusLabel(this.displayStatus(item)))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(ChannelIntegrationViewHelper.getStatusColor(this.displayStatus(item))))
            .margin({ left: 4 })
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(ChannelIntegrationViewHelper.getStatusColor(this.displayStatus(item))))
            .margin({ left: 6 })
        }
        .alignItems(VerticalAlign.Center)

        // 渠道类型（截断 16 字符）
        Text(ChannelIntegrationViewHelper.truncateName(item.channel_type, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 配置摘要：凭据掩码 + 传输模式
        Text(`凭据：${item.app_id_masked.length > 0 ? item.app_id_masked : '未配置'} · ${item.use_stream ? 'Stream 模式' : 'Webhook 模式'}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 操作按钮：编辑/测试连接/删除（右对齐）
        Row() {
          GlassButton({
            text: '编辑',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.openEditDialog(item); }
          })
          GlassButton({
            text: '测试连接',
            type: 'default',
            btnSize: 'small',
            onTap: () => { this.testConnection(item); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            btnSize: 'small',
            onTap: () => { this.confirmDelete(item); }
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

  // ===========================================================================
  // 新建/编辑弹窗构建器
  // ===========================================================================

  /** 弹窗：channel_type + app_id + app_secret + webhook_url（ChannelConfigRequest 契约字段） */
  @Builder
  buildDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showDialog = false; })

      // 面板层：居中展示
      Column() {
      GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
        Scroll() {
          Column() {
            Text(this.dialogMode === 'create' ? '新建渠道配置' : '编辑渠道配置')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .width('100%')

            // 渠道类型
            Text('渠道类型')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '如 feishu / dingtalk / wecom',
              value: this.formData.channelType,
              type: 'text',
              onChange: (v: string) => { this.formData = { channelType: v, appId: this.formData.appId, appSecret: this.formData.appSecret, webhookUrl: this.formData.webhookUrl }; }
            })
              .margin({ top: 4 })

            // App ID
            Text('App ID')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: this.dialogMode === 'edit' ? '已配置凭据显示为掩码，留空保持原值' : '请输入应用 ID',
              value: this.formData.appId,
              type: 'text',
              onChange: (v: string) => { this.formData = { channelType: this.formData.channelType, appId: v, appSecret: this.formData.appSecret, webhookUrl: this.formData.webhookUrl }; }
            })
              .margin({ top: 4 })

            // App Secret
            Text('App Secret')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '请输入应用密钥',
              value: this.formData.appSecret,
              type: 'password',
              onChange: (v: string) => { this.formData = { channelType: this.formData.channelType, appId: this.formData.appId, appSecret: v, webhookUrl: this.formData.webhookUrl }; }
            })
              .margin({ top: 4 })

            // Webhook URL
            Text('Webhook URL')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_secondary'))
              .width('100%')
              .margin({ top: this.sm.getSpacing('sm') })
            GlassInput({
              placeholder: '请输入 Webhook 回调 URL',
              value: this.formData.webhookUrl,
              type: 'text',
              onChange: (v: string) => { this.formData = { channelType: this.formData.channelType, appId: this.formData.appId, appSecret: this.formData.appSecret, webhookUrl: v }; }
            })
              .margin({ top: 4 })

            // 操作按钮
            Row() {
              GlassButton({
                text: '取消',
                type: 'default',
                btnSize: 'medium',
                onTap: () => { this.showDialog = false; }
              })
              GlassButton({
                text: this.dialogMode === 'create' ? '创建' : '保存',
                type: 'primary',
                btnSize: 'medium',
                onTap: () => { this.submitDialog(); }
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
      }
      .width('90%')
    }
    .width('100%')
    .height('100%')
  }
}
