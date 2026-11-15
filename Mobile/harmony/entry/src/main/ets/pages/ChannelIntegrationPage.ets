/**
 * ChannelIntegrationPage - 渠道集成页
 *
 * 职责：展示渠道集成列表，按 agentId 筛选，支持搜索、新建、编辑、测试连接、删除
 * 设计：
 *   - ChannelIntegrationViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标映射、
 *     状态标签映射、能力文案格式化、名称截断，无 UI 运行时依赖，可独立单元测试；
 *   - ChannelIntegrationPage（@Component）：Stack[Column[TopNavMenu(标题"渠道集成"+返回+新建)]
 *     + [搜索框（按 name 过滤）] + [加载态/空态/列表] + [新建/编辑弹窗]]；
 *     列表项 GlassCard 含状态徽章、名称、能力摘要、操作按钮（编辑/测试连接/删除）；
 *     编辑弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.channelIntegration，消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（channelIntegration 模块）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：ChannelIntegration、IntegrationStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.channelIntegration.list 加载列表；
 *   搜索框输入 → 本地 filterByKeyword 过滤；
 *   新建按钮 → 打开弹窗 → 调用 api.channelIntegration.create → 刷新列表；
 *   编辑按钮 → 打开编辑弹窗（预填数据）→ 调用 api.channelIntegration.update → 刷新列表；
 *   测试连接按钮 → 调用 api.channelIntegration.testConnection → 提示结果；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.channelIntegration.remove → 刷新列表
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
import { ChannelIntegration, IntegrationStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'ChannelIntegrationPage';

/** 默认截断长度（与样板页保持一致，便于测试断言） */
const DEFAULT_TRUNCATE_LEN = 16;

/** 默认 agentId（M4.6 占位，后续由路由参数注入） */
const DEFAULT_AGENT_ID = 'default-agent';

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
   *       error→status_error, syncing→status_warning
   * @param status 集成状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: IntegrationStatus): string {
    if (status === 'connected') return 'status_success';
    if (status === 'disconnected') return 'text_secondary';
    if (status === 'error') return 'status_error';
    return 'status_warning';
  }

  /**
   * 获取渠道集成状态对应的图标 emoji
   * 映射：connected→✅, disconnected→⚪, error→❌, syncing→🔄
   * @param status 集成状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: IntegrationStatus): string {
    if (status === 'connected') return '✅';
    if (status === 'disconnected') return '⚪';
    if (status === 'error') return '❌';
    return '🔄';
  }

  /**
   * 获取渠道集成状态对应的中文标签
   * 映射：connected→已连接, disconnected→未连接, error→错误, syncing→同步中
   * @param status 集成状态
   * @return 中文标签
   */
  static getStatusLabel(status: IntegrationStatus): string {
    if (status === 'connected') return '已连接';
    if (status === 'disconnected') return '未连接';
    if (status === 'error') return '错误';
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

/** 渠道集成表单数据（新建/编辑共用） */
interface ChannelIntegrationFormData {
  name: string;
  type: string;
  channelId: string;
  capabilities: string;
}

/** 弹窗模式 */
type DialogMode = 'create' | 'edit';

@Component
export struct ChannelIntegrationPage {
  // 渠道集成列表（由 API 加载，驱动列表渲染）
  @State integrations: ChannelIntegration[] = [];
  // 加载态
  @State loading: boolean = true;
  // 搜索关键字（按 name 本地过滤）
  @State keyword: string = '';
  // 弹窗显示状态
  @State showDialog: boolean = false;
  // 弹窗模式（create/edit）
  @State dialogMode: DialogMode = 'create';
  // 当前编辑的渠道集成 id（编辑模式用）
  @State editingId: string = '';
  // 表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: ChannelIntegrationFormData = {
    name: '',
    type: '',
    channelId: '',
    capabilities: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadIntegrations();
  }

  /**
   * 加载渠道集成列表
   * 流程：调用 api.channelIntegration.list → 写入 integrations
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadIntegrations(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.channelIntegration.list(DEFAULT_AGENT_ID, { page: 1, size: 100 });
      if (res.code === 0 && res.data) {
        this.integrations = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载渠道集成失败', e as Error);
      this.msg.error('加载渠道集成列表失败');
    } finally {
      this.loading = false;
    }
  }

  /**
   * 获取经关键字筛选后的列表
   * 规则：keyword 为空返回全量；否则按 name 包含关键字过滤
   */
  private getFilteredList(): ChannelIntegration[] {
    if (!this.keyword || this.keyword.length === 0) {
      return this.integrations;
    }
    const kw = this.keyword.toLowerCase();
    return this.integrations.filter((ci: ChannelIntegration) =>
      ci.name.toLowerCase().includes(kw));
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.dialogMode = 'create';
    this.editingId = '';
    this.formData = { name: '', type: '', channelId: '', capabilities: '' };
    this.showDialog = true;
  }

  /** 打开编辑弹窗，预填当前渠道集成数据 */
  private openEditDialog(item: ChannelIntegration): void {
    this.dialogMode = 'edit';
    this.editingId = item.id;
    this.formData = {
      name: item.name,
      type: item.type,
      channelId: item.channelId,
      capabilities: item.capabilities ? item.capabilities.join('、') : '',
    };
    this.showDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 api.channelIntegration.create → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写渠道名称');
      return;
    }
    try {
      const data: Partial<ChannelIntegration> = {
        name: this.formData.name,
        type: this.formData.type as ChannelIntegration['type'],
        channelId: this.formData.channelId,
        capabilities: this.formData.capabilities
          ? this.formData.capabilities.split('、').map((s: string) => s.trim()).filter((s: string) => s.length > 0)
          : [],
        status: 'disconnected' as IntegrationStatus,
      };
      const res = await this.api.channelIntegration.create(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showDialog = false;
        this.loadIntegrations();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建渠道集成失败', e as Error);
      this.msg.error('创建渠道集成失败');
    }
  }

  /**
   * 提交编辑
   * 流程：组装 data → 调用 api.channelIntegration.update → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitEdit(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写渠道名称');
      return;
    }
    try {
      const data: Partial<ChannelIntegration> = {
        name: this.formData.name,
        type: this.formData.type as ChannelIntegration['type'],
        channelId: this.formData.channelId,
        capabilities: this.formData.capabilities
          ? this.formData.capabilities.split('、').map((s: string) => s.trim()).filter((s: string) => s.length > 0)
          : [],
      };
      const res = await this.api.channelIntegration.update(this.editingId, data);
      if (res.code === 0) {
        this.msg.success('更新成功');
        this.showDialog = false;
        this.loadIntegrations();
      } else {
        this.msg.error(res.message || '更新失败');
      }
    } catch (e) {
      this.logger.error(TAG, '更新渠道集成失败', e as Error);
      this.msg.error('更新渠道集成失败');
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
   * 测试渠道连接
   * 流程：调用 api.channelIntegration.testConnection → 提示结果
   * 异常：记录日志并提示用户
   */
  private async testConnection(item: ChannelIntegration): Promise<void> {
    try {
      const res = await this.api.channelIntegration.testConnection(item.id);
      if (res.code === 0 && res.data) {
        if (res.data.ok) {
          this.msg.success(`连接正常${res.data.latencyMs !== undefined ? `（${res.data.latencyMs}ms）` : ''}`);
        } else {
          this.msg.warning('连接失败');
        }
      } else {
        this.msg.error(res.message || '测试失败');
      }
    } catch (e) {
      this.logger.error(TAG, '测试渠道连接失败', e as Error);
      this.msg.error('测试渠道连接失败');
    }
  }

  /** 删除前二次确认（AlertDialog） */
  private confirmDelete(item: ChannelIntegration): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除渠道"${item.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteIntegration(item.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.channelIntegration.remove → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteIntegration(integrationId: string): Promise<void> {
    try {
      const res = await this.api.channelIntegration.remove(integrationId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadIntegrations();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除渠道集成失败', e as Error);
      this.msg.error('删除渠道集成失败');
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
            size: 'small',
            onClick: () => { this.openCreateDialog(); }
          })
        }

        // 搜索框：按 name 过滤
        GlassInput({
          placeholder: '搜索渠道名称',
          value: this.keyword,
          type: 'text',
          onChange: (v: string) => { this.keyword = v; }
        })
          .width('90%')
          .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('sm') })

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
            ForEach(this.getFilteredList(), (item: ChannelIntegration) => {
              ListItem() {
                this.buildIntegrationCard(item)
              }
            }, (item: ChannelIntegration) => item.id)
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

  /** 单个渠道集成卡片：状态徽章 + 名称 + 能力摘要 + 操作按钮 */
  @Builder
  buildIntegrationCard(item: ChannelIntegration) {
    GlassCard() {
      Column() {
        // 上部：状态徽章（图标 + 文案 + 圆点）
        Row() {
          Text(ChannelIntegrationViewHelper.getStatusIcon(item.status))
            .fontSize(16)
          Text(ChannelIntegrationViewHelper.getStatusLabel(item.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(ChannelIntegrationViewHelper.getStatusColor(item.status)))
            .margin({ left: 4 })
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(ChannelIntegrationViewHelper.getStatusColor(item.status)))
            .margin({ left: 6 })
        }
        .alignItems(VerticalAlign.Center)

        // 名称（截断 16 字符）
        Text(ChannelIntegrationViewHelper.truncateName(item.name, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 能力摘要
        Text(`能力：${ChannelIntegrationViewHelper.getCapabilitiesText(item.capabilities)}`)
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
            size: 'small',
            onClick: () => { this.openEditDialog(item); }
          })
          GlassButton({
            text: '测试连接',
            type: 'default',
            size: 'small',
            onClick: () => { this.testConnection(item); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(item); }
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
  // 新建/编辑弹窗构建器
  // ===========================================================================

  /** 弹窗：name + type + channelId + capabilities（顿号分隔） */
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
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text(this.dialogMode === 'create' ? '新建渠道集成' : '编辑渠道集成')
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
            placeholder: '请输入渠道名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4 })

          // 类型
          Text('类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '如 feishu / dingtalk / telegram',
            value: this.formData.type,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, type: v }; }
          })
            .margin({ top: 4 })

          // 渠道 ID
          Text('渠道 ID')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入关联渠道 ID',
            value: this.formData.channelId,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, channelId: v }; }
          })
            .margin({ top: 4 })

          // 能力（顿号分隔）
          Text('能力（用顿号分隔）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '如 messaging、file、audit',
            value: this.formData.capabilities,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, capabilities: v }; }
          })
            .margin({ top: 4 })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.showDialog = false; }
            })
            GlassButton({
              text: this.dialogMode === 'create' ? '创建' : '保存',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitDialog(); }
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
