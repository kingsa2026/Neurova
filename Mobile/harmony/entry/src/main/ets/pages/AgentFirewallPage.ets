/**
 * AgentFirewallPage - 防火墙规则管理页
 *
 * 职责：展示当前 Agent 的防火墙规则列表，支持按 action 筛选、新建/编辑/删除/启用-禁用
 * 设计：
 *   - FirewallViewHelper（导出）：纯视图模型，封装动作颜色映射、动作图标映射、动作标签映射、
 *     范围颜色映射、范围标签映射、资源路径截断；无 UI 运行时依赖，可独立单元测试；
 *   - AgentFirewallPage（@Component）：Column [TopNavMenu(标题"防火墙规则"+返回+新建)]
 *     + [action 筛选 Tab（全部/allow/deny/ask）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含资源路径、action 徽章、scope 徽章、enabled 徽章、
 *     创建时间、操作（编辑/启用-禁用/删除）；
 *     删除走 AlertDialog 二次确认；新建/编辑走内嵌 Stack 条件渲染的弹窗；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，API 走 ApiFacade.runtime，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（FirewallViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getActionColor / getScopeColor 返回颜色 token 名（如 'warning'），由调用方通过
 *     StyleManager.getColor(token) 解析为实际颜色，便于主题切换；
 *   - getActionIcon / getActionLabel / getScopeLabel 返回 emoji 与中文短名；
 *   - truncateResource 按最大字符数截断并追加省略号（默认 60）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（runtime 模块：listFirewallRules/getFirewallRule/createFirewallRule/updateFirewallRule/removeFirewallRule）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：FirewallRule、FirewallAction
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.runtime.listFirewallRules(agentId) 加载列表；
 *   action 筛选 Tab 切换 → 本地过滤；
 *   新建按钮 → 打开弹窗 → 填写表单 → api.runtime.createFirewallRule → 刷新列表；
 *   编辑按钮 → 打开弹窗（预填） → 修改 → api.runtime.updateFirewallRule → 刷新列表；
 *   启用/禁用 → api.runtime.updateFirewallRule(id, { enabled: !enabled }) → 刷新列表；
 *   删除按钮 → AlertDialog 二次确认 → api.runtime.removeFirewallRule → 刷新列表。
 *
 * TDD：FirewallViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentFirewallPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { FirewallRule, FirewallAction } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentFirewallPage';

/** 防火墙规则范围类型 */
type FirewallScope = 'inbound' | 'outbound' | 'both';

// ===========================================================================
// FirewallViewHelper - 防火墙视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class FirewallViewHelper {
  /**
   * 获取动作对应的颜色 token 名
   * 映射：allow→success，deny→error，ask→warning
   * @param action 防火墙动作
   * @return StyleManager 颜色 token 名
   */
  static getActionColor(action: FirewallAction): string {
    if (action === 'allow') return 'success';
    if (action === 'deny') return 'error';
    if (action === 'ask') return 'warning';
    return 'text_secondary';
  }

  /**
   * 获取动作对应的图标 emoji
   * 映射：allow→✅，deny→⛔，ask→❓
   * @param action 防火墙动作
   * @return emoji 字符串
   */
  static getActionIcon(action: FirewallAction): string {
    if (action === 'allow') return '✅';
    if (action === 'deny') return '⛔';
    if (action === 'ask') return '❓';
    return '❓';
  }

  /**
   * 获取动作对应的中文显示名
   * 映射：allow→允许，deny→拒绝，ask→询问
   * @param action 防火墙动作
   * @return 中文短名
   */
  static getActionLabel(action: FirewallAction): string {
    if (action === 'allow') return '允许';
    if (action === 'deny') return '拒绝';
    if (action === 'ask') return '询问';
    return '未知';
  }

  /**
   * 获取范围对应的颜色 token 名
   * 映射：inbound→info，outbound→warning，both→error
   * @param scope 防火墙规则范围
   * @return StyleManager 颜色 token 名
   */
  static getScopeColor(scope: FirewallScope): string {
    if (scope === 'inbound') return 'info';
    if (scope === 'outbound') return 'warning';
    if (scope === 'both') return 'error';
    return 'text_secondary';
  }

  /**
   * 获取范围对应的中文显示名
   * 映射：inbound→入站，outbound→出站，both→双向
   * @param scope 防火墙规则范围
   * @return 中文短名
   */
  static getScopeLabel(scope: FirewallScope): string {
    if (scope === 'inbound') return '入站';
    if (scope === 'outbound') return '出站';
    if (scope === 'both') return '双向';
    return '未知';
  }

  /**
   * 截断资源路径，超长时截取 maxLen 字符并追加省略号
   * @param resource 原始资源路径（URL/IP/路径）
   * @param maxLen 最大字符数，默认 60
   * @return 截断后的文本；未超长则原样返回
   */
  static truncateResource(resource: string, maxLen?: number): string {
    const limit = maxLen === undefined ? 60 : maxLen;
    if (resource.length <= limit) return resource;
    return resource.substring(0, limit) + '...';
  }
}

// ===========================================================================
// 筛选 Tab 配置
// ===========================================================================

/** 动作筛选 Tab 选项 */
interface ActionFilterOption {
  value: string;  // 'all' 或具体 FirewallAction
  label: string;
}

/** 动作筛选 Tab 列表（顺序即展示顺序） */
const ACTION_FILTERS: ActionFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'allow', label: '允许' },
  { value: 'deny', label: '拒绝' },
  { value: 'ask', label: '询问' },
];

/** 全部动作（用于表单选择） */
const ALL_ACTIONS: FirewallAction[] = ['allow', 'deny', 'ask'];

/** 全部范围（用于表单选择） */
const ALL_SCOPES: FirewallScope[] = ['inbound', 'outbound', 'both'];

// ===========================================================================
// 表单数据
// ===========================================================================

/** 新建/编辑表单数据 */
interface FirewallFormData {
  id?: string;            // 编辑时携带 id；新建时为 undefined
  resource: string;
  action: FirewallAction;
  scope: FirewallScope;
  enabled: boolean;
}

/** 表单默认值（新建时使用） */
function createEmptyForm(): FirewallFormData {
  return {
    id: undefined,
    resource: '',
    action: 'allow' as FirewallAction,
    scope: 'both' as FirewallScope,
    enabled: true,
  };
}

@Component
export struct AgentFirewallPage {
  // 规则列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State rules: FirewallRule[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的动作筛选值：'all' 或具体 FirewallAction
  @State activeAction: string = 'all';

  // 弹窗显示状态
  @State showDialog: boolean = false;
  // 表单数据（嵌套对象，变更必须整体重新赋值）
  @State formData: FirewallFormData = createEmptyForm();

  // 统一库单例
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadRules();
  }

  /**
   * 加载防火墙规则列表
   * 流程：取 currentAgentId → 调用 api.runtime.listFirewallRules → 写入 rules
   * 异常：记录日志并提示用户；finally 关闭 loading
   */
  private async loadRules(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.loading = false;
      this.msg.warning('请先选择智能体');
      return;
    }
    this.loading = true;
    try {
      const res = await this.api.runtime.listFirewallRules(agentId);
      if (res.code === 0 && res.data) {
        this.rules = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载防火墙规则失败', e as Error);
      this.msg.error('加载防火墙规则失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换动作筛选 Tab */
  private switchAction(value: string): void {
    this.activeAction = value;
  }

  /**
   * 获取经筛选后的列表
   * 规则：activeAction === 'all' 不按动作过滤；否则按 action 精确匹配
   */
  private getFilteredRules(): FirewallRule[] {
    if (this.activeAction === 'all') {
      return this.rules;
    }
    return this.rules.filter((r: FirewallRule) => r.action === this.activeAction);
  }

  /**
   * 打开新建弹窗
   * 重置表单为默认值
   */
  private openCreateDialog(): void {
    this.formData = createEmptyForm();
    this.showDialog = true;
  }

  /**
   * 打开编辑弹窗
   * 预填当前规则数据
   */
  private openEditDialog(rule: FirewallRule): void {
    this.formData = {
      id: rule.id,
      resource: rule.resource,
      action: rule.action,
      scope: rule.scope as FirewallScope,
      enabled: rule.enabled,
    };
    this.showDialog = true;
  }

  /** 关闭弹窗 */
  private closeDialog(): void {
    this.showDialog = false;
  }

  /**
   * 提交表单（新建或编辑）
   * 流程：表单校验 → 根据 formData.id 判断新建/编辑 → 调用对应 API → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitForm(): Promise<void> {
    const agentId = this.agentsStore.currentAgentId;
    if (!agentId) {
      this.msg.warning('请先选择智能体');
      return;
    }
    if (!this.formData.resource) {
      this.msg.warning('请填写资源路径');
      return;
    }
    try {
      const data: Partial<FirewallRule> = {
        agentId,
        resource: this.formData.resource,
        action: this.formData.action,
        scope: this.formData.scope,
        enabled: this.formData.enabled,
      };
      const isEdit = this.formData.id !== undefined && this.formData.id !== '';
      const res = isEdit
        ? await this.api.runtime.updateFirewallRule(this.formData.id as string, data)
        : await this.api.runtime.createFirewallRule(data);
      if (res.code === 0) {
        this.msg.success(isEdit ? '更新成功' : '创建成功');
        this.showDialog = false;
        this.loadRules();
      } else {
        this.msg.error(res.message || (isEdit ? '更新失败' : '创建失败'));
      }
    } catch (e) {
      this.logger.error(TAG, '提交防火墙规则失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /**
   * 切换规则启用/禁用
   * 流程：调用 api.runtime.updateFirewallRule(id, { enabled: !enabled }) → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async toggleEnabled(rule: FirewallRule): Promise<void> {
    try {
      const res = await this.api.runtime.updateFirewallRule(rule.id, { enabled: !rule.enabled });
      if (res.code === 0) {
        this.msg.success(!rule.enabled ? '已启用' : '已禁用');
        this.loadRules();
      } else {
        this.msg.error(res.message || '操作失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换规则状态失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(rule: FirewallRule): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除规则"${FirewallViewHelper.truncateResource(rule.resource, 30)}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteRule(rule.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.runtime.removeFirewallRule → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteRule(ruleId: string): Promise<void> {
    try {
      const res = await this.api.runtime.removeFirewallRule(ruleId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadRules();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除防火墙规则失败', e as Error);
      this.msg.error('删除防火墙规则失败');
    }
  }

  /** 格式化时间（YYYY-MM-DD HH:mm），无值回退 '未知' */
  private formatTime(timeStr?: string): string {
    if (!timeStr) return '未知';
    const d = new Date(timeStr);
    if (isNaN(d.getTime())) return '未知';
    const yyyy = d.getFullYear();
    const MM = (d.getMonth() + 1).toString().padStart(2, '0');
    const dd = d.getDate().toString().padStart(2, '0');
    const hh = d.getHours().toString().padStart(2, '0');
    const mm = d.getMinutes().toString().padStart(2, '0');
    return `${yyyy}-${MM}-${dd} ${hh}:${mm}`;
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"防火墙规则" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '防火墙规则',
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

        // 动作筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(ACTION_FILTERS, (opt: ActionFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeAction === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeAction === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchAction(opt.value); })
            }, (opt: ActionFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 主体内容：加载态 / 空态 / 列表 三选一
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
        } else if (this.getFilteredRules().length === 0) {
          // 空态：居中显示"暂无防火墙规则" + 新建按钮
          Column() {
            Text('暂无防火墙规则')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
              .margin({ bottom: this.sm.getSpacing('md') })
            GlassButton({
              text: '新建规则',
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
          // 规则列表：纵向滚动，卡片间距 12，关闭滚动条
          List({ space: 12 }) {
            ForEach(this.getFilteredRules(), (rule: FirewallRule) => {
              ListItem() {
                this.buildRuleCard(rule)
              }
            }, (rule: FirewallRule) => rule.id)
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

      // 新建/编辑弹窗：内嵌 Stack 条件渲染
      if (this.showDialog) {
        this.buildFormDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 规则卡片构建器
  // ===========================================================================

  /** 单条规则卡片：徽章行 + 资源 + 时间 + 操作按钮 */
  @Builder
  buildRuleCard(rule: FirewallRule) {
    GlassCard() {
      Column() {
        // 徽章行：action 徽章 + scope 徽章 + enabled 徽章
        Row() {
          // 动作徽章：图标 + 中文
          Row() {
            Text(FirewallViewHelper.getActionIcon(rule.action))
              .fontSize(this.sm.getFontSize('caption'))
            Text(FirewallViewHelper.getActionLabel(rule.action))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(FirewallViewHelper.getActionColor(rule.action)))

          // 范围徽章
          Row() {
            Text(FirewallViewHelper.getScopeLabel(rule.scope as FirewallScope))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(FirewallViewHelper.getScopeColor(rule.scope as FirewallScope)))
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(FirewallViewHelper.getScopeColor(rule.scope as FirewallScope)))
          .opacity(0.2)
          .margin({ left: this.sm.getSpacing('sm') })

          // 启用状态徽章（右对齐）
          Row() {
            Row()
              .width(8)
              .height(8)
              .borderRadius(4)
              .backgroundColor(this.sm.getColor(rule.enabled ? 'success' : 'text_disabled'))
            Text(rule.enabled ? '启用' : '禁用')
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(rule.enabled ? 'success' : 'text_disabled'))
              .margin({ left: 4 })
          }
          .layoutWeight(1)
          .justifyContent(FlexAlign.End)
          .alignItems(VerticalAlign.Center)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 资源路径（截断到 60 字符）
        Text(`资源：${FirewallViewHelper.truncateResource(rule.resource)}`)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })
          .width('100%')

        // 时间行
        Text(`创建：${this.formatTime(rule.createdAt)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_disabled'))
          .margin({ top: 4 })

        // 操作按钮：编辑 / 启用-禁用 / 删除（右对齐）
        Row() {
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.openEditDialog(rule); }
          })
          GlassButton({
            text: rule.enabled ? '禁用' : '启用',
            type: rule.enabled ? 'default' : 'primary',
            size: 'small',
            onClick: () => { this.toggleEnabled(rule); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(rule); }
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
  // 新建/编辑弹窗构建器（内嵌 Stack 条件渲染）
  // ===========================================================================

  /** 表单弹窗：背景遮罩 + GlassPanel 表单 */
  @Builder
  buildFormDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.closeDialog(); })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          // 标题（新建/编辑）
          Text(this.formData.id !== undefined ? '编辑规则' : '新建规则')
            .fontSize(this.sm.getFontSize('subtitle'))
            .fontWeight(FontWeight.Bold)
            .fontColor(this.sm.getColor('text_primary'))
            .margin({ bottom: this.sm.getSpacing('md') })
            .width('100%')

          // 资源路径
          Text('资源路径（URL/IP/路径）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入资源路径',
            value: this.formData.resource,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, resource: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 动作选择（横向滚动）
          Text('动作')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              ForEach(ALL_ACTIONS, (a: FirewallAction) => {
                GlassButton({
                  text: `${FirewallViewHelper.getActionIcon(a)} ${FirewallViewHelper.getActionLabel(a)}`,
                  type: this.formData.action === a ? 'primary' : 'default',
                  size: 'small',
                  onClick: () => {
                    this.formData = { ...this.formData, action: a };
                  }
                })
              }, (a: FirewallAction) => a)
            }
            .padding({ top: 4, bottom: 4 })
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 范围选择（横向滚动）
          Text('范围')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              ForEach(ALL_SCOPES, (s: FirewallScope) => {
                GlassButton({
                  text: FirewallViewHelper.getScopeLabel(s),
                  type: this.formData.scope === s ? 'primary' : 'default',
                  size: 'small',
                  onClick: () => {
                    this.formData = { ...this.formData, scope: s };
                  }
                })
              }, (s: FirewallScope) => s)
            }
            .padding({ top: 4, bottom: 4 })
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 启用状态切换
          Row() {
            Text('启用规则')
              .fontSize(this.sm.getFontSize('body'))
              .fontColor(this.sm.getColor('text_primary'))
              .layoutWeight(1)
            Toggle({ type: ToggleType.Switch, isOn: this.formData.enabled })
              .onChange((on: boolean) => {
                this.formData = { ...this.formData, enabled: on };
              })
          }
          .width('100%')
          .justifyContent(FlexAlign.SpaceBetween)
          .alignItems(VerticalAlign.Center)
          .margin({ top: this.sm.getSpacing('sm'), bottom: this.sm.getSpacing('md') })

          // 操作按钮
          Row() {
            GlassButton({
              text: '取消',
              type: 'default',
              size: 'medium',
              onClick: () => { this.closeDialog(); }
            })
            GlassButton({
              text: this.formData.id !== undefined ? '保存' : '创建',
              type: 'primary',
              size: 'medium',
              onClick: () => { this.submitForm(); }
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
