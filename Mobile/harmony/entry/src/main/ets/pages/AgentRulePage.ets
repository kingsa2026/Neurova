/**
 * AgentRulePage - 智能体规则管理页
 *
 * 职责：展示当前 Agent 的规则列表，支持按 type 筛选、按 status 筛选、按 priority 排序，
 *       新建/编辑/删除/启用-禁用规则
 * 设计：
 *   - AgentRuleViewHelper（导出）：纯视图模型，封装类型颜色映射、类型图标映射、类型标签映射、
 *     状态颜色映射、状态标签映射、优先级格式化、文本截断；无 UI 运行时依赖，可独立单元测试；
 *   - AgentRulePage（@Component）：Column [TopNavMenu(标题"规则管理"+返回+新建)]
 *     + [type 筛选 Tab（全部/permission/restriction/behavior/workflow）]
 *     + [status 筛选 Tab（全部/active/inactive/archived）]
 *     + [加载态/空态/列表]；列表项 GlassCard 含名称、type 徽章、status 徽章、priority、
 *     condition 摘要、action 摘要、操作（编辑/启用-禁用/删除）；
 *     删除走 AlertDialog 二次确认；新建/编辑走内嵌 Stack 条件渲染的弹窗；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，API 走 ApiFacade.capability，
 *     状态走 AgentsStore，消息走 MessageManager。
 *
 * 视图模型层（AgentRuleViewHelper）：
 *   - 刻意设计为无 UI 依赖的纯函数集合，便于单元测试；
 *   - getTypeColor / getStatusColor 返回颜色 token 名（如 'warning'），由调用方通过
 *     StyleManager.getColor(token) 解析为实际颜色，便于主题切换；
 *   - getTypeIcon / getTypeLabel / getStatusLabel 返回 emoji 与中文短名；
 *   - formatPriority 将数字优先级格式化为 "P{n}" 字符串；
 *   - truncateText 按最大字符数截断并追加省略号（默认 80）。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（capability 模块：listRules/getRule/createRule/updateRule/removeRule）
 *   - ../libs/state/stores/AgentsStore：Agent 状态（currentAgentId 过滤）
 *   - ../routing/Router：统一路由跳转
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Rule、RuleType、RuleStatus
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.capability.listRules(agentId) 加载列表；
 *   type/status 筛选 Tab 切换 → 本地过滤；
 *   新建按钮 → 打开弹窗 → 填写表单 → api.capability.createRule → 刷新列表；
 *   编辑按钮 → 打开弹窗（预填） → 修改 → api.capability.updateRule → 刷新列表；
 *   启用/禁用 → api.capability.updateRule(id, { status: 'active' | 'inactive' }) → 刷新列表；
 *   删除按钮 → AlertDialog 二次确认 → api.capability.removeRule → 刷新列表。
 *
 * TDD：AgentRuleViewHelper 各方法按红绿灯垂直切片逐步实现，详见 AgentRulePage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Rule, RuleType, RuleStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'AgentRulePage';

// ===========================================================================
// AgentRuleViewHelper - 规则视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class AgentRuleViewHelper {
  /**
   * 获取规则类型对应的颜色 token 名
   * 映射：permission→warning，restriction→error，behavior→info，workflow→primary
   * @param type 规则类型
   * @return StyleManager 颜色 token 名
   */
  static getTypeColor(type: RuleType): string {
    if (type === 'permission') return 'warning';
    if (type === 'restriction') return 'error';
    if (type === 'behavior') return 'info';
    if (type === 'workflow') return 'primary';
    return 'text_secondary';
  }

  /**
   * 获取规则类型对应的图标 emoji
   * 映射：permission→🛡️，restriction→🚫，behavior→⚙️，workflow→🔄
   * @param type 规则类型
   * @return emoji 字符串
   */
  static getTypeIcon(type: RuleType): string {
    if (type === 'permission') return '🛡️';
    if (type === 'restriction') return '🚫';
    if (type === 'behavior') return '⚙️';
    if (type === 'workflow') return '🔄';
    return '❓';
  }

  /**
   * 获取规则类型对应的中文显示名
   * 映射：permission→权限，restriction→限制，behavior→行为，workflow→工作流
   * @param type 规则类型
   * @return 中文短名
   */
  static getTypeLabel(type: RuleType): string {
    if (type === 'permission') return '权限';
    if (type === 'restriction') return '限制';
    if (type === 'behavior') return '行为';
    if (type === 'workflow') return '工作流';
    return '未知';
  }

  /**
   * 获取规则状态对应的颜色 token 名
   * 映射：active→success，inactive→text_disabled，archived→text_secondary
   * @param status 规则状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: RuleStatus): string {
    if (status === 'active') return 'success';
    if (status === 'inactive') return 'text_disabled';
    if (status === 'archived') return 'text_secondary';
    return 'text_disabled';
  }

  /**
   * 获取规则状态对应的中文显示名
   * 映射：active→启用，inactive→禁用，archived→归档
   * @param status 规则状态
   * @return 中文短名
   */
  static getStatusLabel(status: RuleStatus): string {
    if (status === 'active') return '启用';
    if (status === 'inactive') return '禁用';
    if (status === 'archived') return '归档';
    return '未知';
  }

  /**
   * 格式化优先级为 P{n} 字符串
   * @param priority 优先级数字（越小优先级越高）
   * @return "P1" / "P5" / "P10" 等格式
   */
  static formatPriority(priority: number): string {
    return `P${priority}`;
  }

  /**
   * 截断文本，超长时截取 maxLen 字符并追加省略号
   * @param text 原始文本
   * @param maxLen 最大字符数，默认 80
   * @return 截断后的文本；未超长则原样返回
   */
  static truncateText(text: string, maxLen?: number): string {
    const limit = maxLen === undefined ? 80 : maxLen;
    if (text.length <= limit) return text;
    return text.substring(0, limit) + '...';
  }
}

// ===========================================================================
// 筛选 Tab 配置
// ===========================================================================

/** 类型筛选 Tab 选项 */
interface TypeFilterOption {
  value: string;  // 'all' 或具体 RuleType
  label: string;
}

/** 类型筛选 Tab 列表（顺序即展示顺序） */
const TYPE_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'permission', label: '权限' },
  { value: 'restriction', label: '限制' },
  { value: 'behavior', label: '行为' },
  { value: 'workflow', label: '工作流' },
];

/** 状态筛选 Tab 列表（顺序即展示顺序） */
const STATUS_FILTERS: TypeFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'active', label: '启用' },
  { value: 'inactive', label: '禁用' },
  { value: 'archived', label: '归档' },
];

/** 全部规则类型（用于表单类型选择） */
const ALL_RULE_TYPES: RuleType[] = ['permission', 'restriction', 'behavior', 'workflow'];

// ===========================================================================
// 表单数据
// ===========================================================================

/** 新建/编辑表单数据 */
interface RuleFormData {
  id?: string;            // 编辑时携带 id；新建时为 undefined
  name: string;
  type: RuleType;
  priority: number;
  condition: string;
  action: string;
  description: string;
}

/** 表单默认值（新建时使用） */
function createEmptyForm(): RuleFormData {
  return {
    id: undefined,
    name: '',
    type: 'permission' as RuleType,
    priority: 3,
    condition: '',
    action: '',
    description: '',
  };
}

@Component
export struct AgentRulePage {
  // 规则列表（由 API 加载，驱动列表渲染；筛选在本地进行）
  @State rules: Rule[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的类型筛选值：'all' 或具体 RuleType
  @State activeType: string = 'all';
  // 当前激活的状态筛选值：'all' 或具体 RuleStatus
  @State activeStatus: string = 'all';

  // 弹窗显示状态
  @State showDialog: boolean = false;
  // 表单数据（嵌套对象，变更必须整体重新赋值）
  @State formData: RuleFormData = createEmptyForm();

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
   * 加载规则列表
   * 流程：取 currentAgentId → 调用 api.capability.listRules → 写入 rules
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
      const res = await this.api.capability.listRules(agentId);
      if (res.code === 0 && res.data) {
        this.rules = res.data.items;
      } else {
        this.msg.error(res.message || '加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载规则失败', e as Error);
      this.msg.error('加载规则失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换类型筛选 Tab */
  private switchType(value: string): void {
    this.activeType = value;
  }

  /** 切换状态筛选 Tab */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经筛选+排序后的列表
   * 规则：activeType === 'all' 不按类型过滤；activeStatus === 'all' 不按状态过滤；
   *       排序按 priority 升序（数字越小优先级越高）
   */
  private getFilteredRules(): Rule[] {
    let list = this.rules;
    if (this.activeType !== 'all') {
      list = list.filter((r: Rule) => r.type === this.activeType);
    }
    if (this.activeStatus !== 'all') {
      list = list.filter((r: Rule) => r.status === this.activeStatus);
    }
    return list.slice().sort((a: Rule, b: Rule) => a.priority - b.priority);
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
  private openEditDialog(rule: Rule): void {
    this.formData = {
      id: rule.id,
      name: rule.name,
      type: rule.type,
      priority: rule.priority,
      condition: rule.condition,
      action: rule.action,
      description: rule.description ?? '',
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
    if (!this.formData.name) {
      this.msg.warning('请填写规则名称');
      return;
    }
    if (!this.formData.condition) {
      this.msg.warning('请填写规则条件');
      return;
    }
    if (!this.formData.action) {
      this.msg.warning('请填写规则动作');
      return;
    }
    try {
      const data: Partial<Rule> = {
        agentId,
        name: this.formData.name,
        type: this.formData.type,
        priority: this.formData.priority,
        condition: this.formData.condition,
        action: this.formData.action,
        description: this.formData.description || undefined,
      };
      const isEdit = this.formData.id !== undefined && this.formData.id !== '';
      const res = isEdit
        ? await this.api.capability.updateRule(this.formData.id as string, data)
        : await this.api.capability.createRule(data);
      if (res.code === 0) {
        this.msg.success(isEdit ? '更新成功' : '创建成功');
        this.showDialog = false;
        this.loadRules();
      } else {
        this.msg.error(res.message || (isEdit ? '更新失败' : '创建失败'));
      }
    } catch (e) {
      this.logger.error(TAG, '提交规则失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /**
   * 切换规则启用/禁用
   * 规则：active → inactive；inactive → active；archived 不切换
   * 流程：调用 api.capability.updateRule(id, { status }) → 刷新列表
   * 异常：记录日志并提示用户
   */
  private async toggleStatus(rule: Rule): Promise<void> {
    if (rule.status === 'archived') {
      this.msg.info('归档状态不可直接切换');
      return;
    }
    const next: RuleStatus = rule.status === 'active' ? 'inactive' : 'active';
    try {
      const res = await this.api.capability.updateRule(rule.id, { status: next });
      if (res.code === 0) {
        this.msg.success(next === 'active' ? '已启用' : '已禁用');
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
  private confirmDelete(rule: Rule): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除规则"${rule.name}"吗？此操作不可撤销。`,
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
   * 流程：调用 api.capability.removeRule → 成功后重新加载列表
   * 异常：记录日志并提示用户
   */
  private async deleteRule(ruleId: string): Promise<void> {
    try {
      const res = await this.api.capability.removeRule(ruleId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadRules();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除规则失败', e as Error);
      this.msg.error('删除规则失败');
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
        // 顶部导航栏：标题"规则管理" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '规则管理',
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

        // 类型筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(TYPE_FILTERS, (opt: TypeFilterOption) => {
              Text(opt.label)
                .fontSize(this.sm.getFontSize('caption'))
                .fontColor(this.activeType === opt.value
                  ? this.sm.getColor('text_on_primary')
                  : this.sm.getColor('text_secondary'))
                .backgroundColor(this.activeType === opt.value
                  ? this.sm.getColor('primary')
                  : this.sm.getColor('surface'))
                .padding({ left: 12, right: 12, top: 6, bottom: 6 })
                .borderRadius(16)
                .onClick(() => { this.switchType(opt.value); })
            }, (opt: TypeFilterOption) => opt.value)
          }
          .padding({ left: this.sm.getSpacing('md'), right: this.sm.getSpacing('md') })
        }
        .scrollable(ScrollDirection.Horizontal)
        .scrollBar(BarState.Off)
        .width('100%')
        .padding({ top: 4, bottom: 4 })

        // 状态筛选 Tab：横向滚动胶囊
        Scroll() {
          Row({ space: 8 }) {
            ForEach(STATUS_FILTERS, (opt: TypeFilterOption) => {
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
            }, (opt: TypeFilterOption) => opt.value)
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
          // 空态：居中显示"暂无规则" + 新建按钮
          Column() {
            Text('暂无规则')
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
            ForEach(this.getFilteredRules(), (rule: Rule) => {
              ListItem() {
                this.buildRuleCard(rule)
              }
            }, (rule: Rule) => rule.id)
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

  /** 单条规则卡片：徽章行 + 名称 + 摘要 + 时间 + 操作按钮 */
  @Builder
  buildRuleCard(rule: Rule) {
    GlassCard() {
      Column() {
        // 徽章行：type 徽章 + status 徽章 + priority
        Row() {
          // 类型徽章：图标 + 中文
          Row() {
            Text(AgentRuleViewHelper.getTypeIcon(rule.type))
              .fontSize(this.sm.getFontSize('caption'))
            Text(AgentRuleViewHelper.getTypeLabel(rule.type))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor('text_on_primary'))
              .margin({ left: 4 })
          }
          .padding({ left: 8, right: 8, top: 2, bottom: 2 })
          .borderRadius(10)
          .backgroundColor(this.sm.getColor(AgentRuleViewHelper.getTypeColor(rule.type)))

          // 状态徽章：圆点 + 中文
          Row() {
            Row()
              .width(8)
              .height(8)
              .borderRadius(4)
              .backgroundColor(this.sm.getColor(AgentRuleViewHelper.getStatusColor(rule.status)))
            Text(AgentRuleViewHelper.getStatusLabel(rule.status))
              .fontSize(this.sm.getFontSize('caption'))
              .fontColor(this.sm.getColor(AgentRuleViewHelper.getStatusColor(rule.status)))
              .margin({ left: 4 })
          }
          .margin({ left: this.sm.getSpacing('sm') })
          .alignItems(VerticalAlign.Center)

          // 优先级（右对齐）
          Text(AgentRuleViewHelper.formatPriority(rule.priority))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .layoutWeight(1)
            .textAlign(TextAlign.End)
        }
        .width('100%')
        .alignItems(VerticalAlign.Center)

        // 名称
        Text(rule.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })
          .width('100%')

        // condition 摘要（截断到 80 字符）
        Text(`条件：${AgentRuleViewHelper.truncateText(rule.condition)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // action 摘要
        Text(`动作：${AgentRuleViewHelper.truncateText(rule.action)}`)
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })
          .width('100%')

        // 时间行
        Text(`更新：${this.formatTime(rule.updatedAt)}`)
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
            text: rule.status === 'active' ? '禁用' : '启用',
            type: rule.status === 'active' ? 'default' : 'primary',
            size: 'small',
            onClick: () => { this.toggleStatus(rule); }
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

          // 规则类型选择（横向滚动）
          Text('规则类型')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          Scroll() {
            Row({ space: 8 }) {
              ForEach(ALL_RULE_TYPES, (t: RuleType) => {
                GlassButton({
                  text: `${AgentRuleViewHelper.getTypeIcon(t)} ${AgentRuleViewHelper.getTypeLabel(t)}`,
                  type: this.formData.type === t ? 'primary' : 'default',
                  size: 'small',
                  onClick: () => {
                    this.formData = { ...this.formData, type: t };
                  }
                })
              }, (t: RuleType) => t)
            }
            .padding({ top: 4, bottom: 4 })
          }
          .scrollable(ScrollDirection.Horizontal)
          .scrollBar(BarState.Off)
          .width('100%')
          .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 规则名称
          Text('规则名称')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入规则名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 优先级（数字）
          Text('优先级（数字越小越高）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入优先级（1-10）',
            value: this.formData.priority.toString(),
            type: 'number',
            onChange: (v: string) => {
              const n = parseInt(v, 10);
              this.formData = { ...this.formData, priority: isNaN(n) ? 1 : n };
            }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 条件
          Text('条件')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入触发条件',
            value: this.formData.condition,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, condition: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 动作
          Text('动作')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入执行动作',
            value: this.formData.action,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, action: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('sm') })

          // 描述（可选）
          Text('描述（可选）')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
          GlassInput({
            placeholder: '请输入描述（可选）',
            value: this.formData.description,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, description: v }; }
          })
            .margin({ top: 4, bottom: this.sm.getSpacing('md') })

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
