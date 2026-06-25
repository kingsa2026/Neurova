/**
 * WorkflowPage - 工作流页
 *
 * 职责：展示工作流列表，按 status 筛选，支持新建/编辑/删除/复制/启用-禁用
 * 设计：
 *   - WorkflowViewHelper（导出）：纯视图模型，封装状态颜色映射、状态图标映射、状态标签映射、
 *     节点数格式化、版本格式化、描述截断，无 UI 运行时依赖，可独立单元测试；
 *   - WorkflowPage（@Component）：Stack[Column[TopNavMenu(标题"工作流"+返回+新建)]
 *     + [status 筛选 Tab（全部/draft/active/paused/archived）] + [加载态/空态/列表]
 *     + [新建弹窗]]；
 *     列表项 GlassCard 含名称、描述摘要、status 徽章、节点数、版本、操作按钮
 *     （编辑/复制/启用-禁用/删除）；
 *     删除走 AlertDialog 二次确认；新建走 CustomDialog（name + description）；
 *     编辑跳转 WorkflowDetail（占位，提示"工作流编辑器 M5 实现"）；
 *     新建弹窗内嵌 Stack 条件渲染；
 *   - 颜色统一走 StyleManager（返回 token 名），路由走 Router，
 *     API 走 ApiFacade.collaboration，消息走 MessageManager。
 *
 * 依赖：
 *   - ../components/glass：TopNavMenu、GlassCard、GlassButton、GlassInput、GlassPanel
 *   - ../libs/api/ApiFacade：统一 API 门面（collaboration.listWorkflows/getWorkflow/
 *     createWorkflow/updateWorkflow/removeWorkflow）
 *   - ../routing/Router：统一路由跳转 + RouteNames
 *   - ../libs/style/StyleManager：统一样式 token
 *   - ../libs/logger/Logger：统一日志
 *   - ../libs/message/MessageManager：统一消息提示
 *   - ../libs/types：Workflow、WorkflowStatus、WorkflowNode
 *
 * 用法：
 *   由 Router.push 跳转进入；
 *   aboutToAppear 调用 api.collaboration.listWorkflows 加载列表；
 *   status 筛选 Tab 切换 → 本地 filterByStatus 过滤；
 *   新建按钮 → 打开 CustomDialog → 调用 api.collaboration.createWorkflow → 刷新列表；
 *   编辑按钮 → 提示"工作流编辑器 M5 实现"（占位）；
 *   复制按钮 → 复制工作流（含原节点与边）→ 调用 api.collaboration.createWorkflow；
 *   启用-禁用按钮 → 调用 api.collaboration.updateWorkflow 切换 status；
 *   删除按钮 → AlertDialog 二次确认 → 调用 api.collaboration.removeWorkflow → 刷新列表
 *
 * TDD：WorkflowViewHelper 各方法按红绿灯垂直切片逐步实现，详见 WorkflowPage.test.ets
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Workflow, WorkflowStatus } from '../libs/types';

/** 日志标签 */
const TAG = 'WorkflowPage';

/** 默认截断长度（与样板页保持一致，便于测试断言） */
const DEFAULT_TRUNCATE_LEN = 80;

// ===========================================================================
// WorkflowViewHelper - 工作流视图模型（纯函数，无 UI 依赖，可独立单元测试）
//
// 设计：所有方法为 static，输入 → 输出，无副作用；
//       颜色方法返回 StyleManager 的 token 名（如 'warning'），由页面解析为实际颜色值；
//       通过本文件 export，供 ohosTest 直接导入测试
// ===========================================================================

export class WorkflowViewHelper {
  /**
   * 获取工作流状态对应的颜色 token 名
   * 映射：draft→warning, active→success, paused→text_secondary, archived→text_disabled
   * @param status 工作流状态
   * @return StyleManager 颜色 token 名
   */
  static getStatusColor(status: WorkflowStatus): string {
    if (status === 'draft') return 'warning';
    if (status === 'active') return 'success';
    if (status === 'paused') return 'text_secondary';
    return 'text_disabled';
  }

  /**
   * 获取工作流状态对应的图标 emoji
   * 映射：draft→📝, active→▶️, paused→⏸️, archived→📦
   * @param status 工作流状态
   * @return emoji 字符串
   */
  static getStatusIcon(status: WorkflowStatus): string {
    if (status === 'draft') return '📝';
    if (status === 'active') return '▶️';
    if (status === 'paused') return '⏸️';
    return '📦';
  }

  /**
   * 获取工作流状态对应的中文标签
   * 映射：draft→草稿, active→运行中, paused→已暂停, archived→已归档
   * @param status 工作流状态
   * @return 中文标签
   */
  static getStatusLabel(status: WorkflowStatus): string {
    if (status === 'draft') return '草稿';
    if (status === 'active') return '运行中';
    if (status === 'paused') return '已暂停';
    return '已归档';
  }

  /**
   * 格式化节点数为文案
   * 规则：0 → "无节点"，n → "节点 n 个"
   * @param count 节点数量
   * @return 节点数文案
   */
  static formatNodeCount(count: number): string {
    if (count <= 0) return '无节点';
    return `节点 ${count} 个`;
  }

  /**
   * 格式化版本号，前缀 "v"
   * 规则：输入 "1.2.0" → 输出 "v1.2.0"
   * @param version 版本号字符串
   * @return "v" 前缀的版本字符串
   */
  static formatVersion(version: string): string {
    return `v${version}`;
  }

  /**
   * 截断描述文本
   * 规则：
   *   - desc 为 undefined 或空字符串 → 返回 "—"
   *   - 长度 ≤ maxLen → 原样返回
   *   - 长度 > maxLen → 截取前 maxLen 字符并追加省略号 "..."
   * @param desc 描述文本
   * @param maxLen 最大长度，默认 80
   * @return 截断后的描述
   */
  static truncateDescription(desc?: string, maxLen?: number): string {
    const len = maxLen !== undefined ? maxLen : DEFAULT_TRUNCATE_LEN;
    if (!desc || desc.length === 0) return '—';
    if (desc.length <= len) return desc;
    return desc.substring(0, len) + '...';
  }
}

/** 状态筛选 Tab 配置 */
interface StatusFilterOption {
  value: string;
  label: string;
}

/** 状态筛选 Tab 列表（顺序：全部/draft/active/paused/archived） */
const STATUS_FILTERS: StatusFilterOption[] = [
  { value: 'all', label: '全部' },
  { value: 'draft', label: '草稿' },
  { value: 'active', label: '运行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'archived', label: '已归档' },
];

/** 新建工作流表单数据 */
interface WorkflowFormData {
  name: string;
  description: string;
}

@Component
export struct WorkflowPage {
  // 工作流列表（由 API 加载，驱动列表渲染）
  @State workflows: Workflow[] = [];
  // 加载态（控制"加载中..."占位与列表的切换）
  @State loading: boolean = true;
  // 当前激活的状态筛选值：'all' 或具体 WorkflowStatus
  @State activeStatus: string = 'all';
  // 新建弹窗显示状态
  @State showCreateDialog: boolean = false;
  // 新建表单数据（@State 嵌套属性变更整体重新赋值）
  @State formData: WorkflowFormData = {
    name: '',
    description: '',
  };

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.loadWorkflows();
  }

  /**
   * 加载工作流列表
   * 流程：调用 api.collaboration.listWorkflows → 写入 workflows
   * 异常：记录日志并提示用户；无论成败 finally 关闭 loading
   */
  private async loadWorkflows(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.listWorkflows();
      if (res.code === 0 && res.data) {
        this.workflows = res.data.items;
      }
    } catch (e) {
      this.logger.error(TAG, '加载工作流失败', e as Error);
      this.msg.error('加载工作流列表失败');
    } finally {
      this.loading = false;
    }
  }

  /** 切换状态筛选 Tab（本地过滤，无需重新请求后端） */
  private switchStatus(value: string): void {
    this.activeStatus = value;
  }

  /**
   * 获取经状态筛选后的列表
   * 规则：activeStatus === 'all' 返回全量；否则按 status 字段过滤
   */
  private getFilteredList(): Workflow[] {
    if (this.activeStatus === 'all') {
      return this.workflows;
    }
    return this.workflows.filter((w: Workflow) => w.status === this.activeStatus);
  }

  /** 打开新建弹窗，重置表单数据 */
  private openCreateDialog(): void {
    this.formData = { name: '', description: '' };
    this.showCreateDialog = true;
  }

  /**
   * 提交新建
   * 流程：组装 data → 调用 api.collaboration.createWorkflow → 成功后关闭弹窗并刷新列表
   * 异常：记录日志并提示用户
   */
  private async submitCreate(): Promise<void> {
    if (!this.formData.name) {
      this.msg.warning('请填写工作流名称');
      return;
    }
    try {
      const data: Partial<Workflow> = {
        name: this.formData.name,
        description: this.formData.description,
        status: 'draft' as WorkflowStatus,
        nodes: [],
        edges: [],
        version: '0.1.0',
      };
      const res = await this.api.collaboration.createWorkflow(data);
      if (res.code === 0) {
        this.msg.success('创建成功');
        this.showCreateDialog = false;
        this.loadWorkflows();
      } else {
        this.msg.error(res.message || '创建失败');
      }
    } catch (e) {
      this.logger.error(TAG, '创建工作流失败', e as Error);
      this.msg.error('创建工作流失败');
    }
  }

  /** 编辑工作流（M5 实现，当前提示） */
  private handleEdit(workflow: Workflow): void {
    this.msg.info('工作流编辑器 M5 实现');
  }

  /**
   * 复制工作流
   * 流程：基于原工作流克隆数据，去除 id → 调用 createWorkflow
   * 异常：记录日志并提示用户
   */
  private async duplicateWorkflow(workflow: Workflow): Promise<void> {
    try {
      const data: Partial<Workflow> = {
        name: `${workflow.name} 副本`,
        description: workflow.description,
        status: 'draft' as WorkflowStatus,
        nodes: workflow.nodes,
        edges: workflow.edges,
        version: workflow.version,
      };
      const res = await this.api.collaboration.createWorkflow(data);
      if (res.code === 0) {
        this.msg.success('复制成功');
        this.loadWorkflows();
      } else {
        this.msg.error(res.message || '复制失败');
      }
    } catch (e) {
      this.logger.error(TAG, '复制工作流失败', e as Error);
      this.msg.error('复制工作流失败');
    }
  }

  /**
   * 切换工作流启用/禁用
   * 流程：active↔paused 切换 → 调用 api.collaboration.updateWorkflow
   * 异常：记录日志并提示用户
   */
  private async toggleStatus(workflow: Workflow): Promise<void> {
    const newStatus: WorkflowStatus = workflow.status === 'active' ? 'paused' : 'active';
    try {
      const res = await this.api.collaboration.updateWorkflow(workflow.id, { status: newStatus });
      if (res.code === 0) {
        this.msg.success(newStatus === 'active' ? '已启用' : '已暂停');
        this.loadWorkflows();
      } else {
        this.msg.error(res.message || '操作失败');
      }
    } catch (e) {
      this.logger.error(TAG, '切换工作流状态失败', e as Error);
      this.msg.error('操作失败');
    }
  }

  /**
   * 删除前二次确认（AlertDialog）
   */
  private confirmDelete(workflow: Workflow): void {
    AlertDialog.show({
      title: '确认删除',
      message: `确定要删除工作流"${workflow.name}"吗？此操作不可撤销。`,
      autoCancel: true,
      alignment: DialogAlignment.Center,
      primaryButton: {
        value: '取消',
        action: () => {}
      },
      secondaryButton: {
        value: '删除',
        fontColor: this.sm.getColor('error'),
        action: () => { this.deleteWorkflow(workflow.id); }
      }
    });
  }

  /**
   * 执行删除
   * 流程：调用 api.collaboration.removeWorkflow → 成功后刷新列表
   * 异常：记录日志并提示用户
   */
  private async deleteWorkflow(workflowId: string): Promise<void> {
    try {
      const res = await this.api.collaboration.removeWorkflow(workflowId);
      if (res.code === 0) {
        this.msg.success('删除成功');
        this.loadWorkflows();
      } else {
        this.msg.error(res.message || '删除失败');
      }
    } catch (e) {
      this.logger.error(TAG, '删除工作流失败', e as Error);
      this.msg.error('删除工作流失败');
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      Column() {
        // 顶部导航栏：标题"工作流" + 返回按钮 + 新建按钮（右侧插槽）
        TopNavMenu({
          title: '工作流',
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

        // 状态筛选 Tab：横向滚动胶囊
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
        } else if (this.getFilteredList().length === 0) {
          Column() {
            Text('暂无工作流')
              .fontSize(this.sm.getFontSize('subtitle'))
              .fontColor(this.sm.getColor('text_secondary'))
          }
          .width('100%')
          .layoutWeight(1)
          .justifyContent(FlexAlign.Center)
          .alignItems(HorizontalAlign.Center)
        } else {
          List({ space: 12 }) {
            ForEach(this.getFilteredList(), (workflow: Workflow) => {
              ListItem() {
                this.buildWorkflowCard(workflow)
              }
            }, (workflow: Workflow) => workflow.id)
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

      // 新建弹窗：内嵌 Stack 条件渲染
      if (this.showCreateDialog) {
        this.buildCreateDialog()
      }
    }
    .width('100%')
    .height('100%')
  }

  // ===========================================================================
  // 工作流卡片构建器
  // ===========================================================================

  /** 单个工作流卡片：状态徽章 + 名称 + 描述摘要 + 节点数/版本 + 操作按钮 */
  @Builder
  buildWorkflowCard(workflow: Workflow) {
    GlassCard() {
      Column() {
        // 上部：状态徽章（圆点 + 图标 + 文案）
        Row() {
          Text(WorkflowViewHelper.getStatusIcon(workflow.status))
            .fontSize(16)
          Text(WorkflowViewHelper.getStatusLabel(workflow.status))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor(WorkflowViewHelper.getStatusColor(workflow.status)))
            .margin({ left: 4 })
          Row()
            .width(8)
            .height(8)
            .borderRadius(4)
            .backgroundColor(this.sm.getColor(WorkflowViewHelper.getStatusColor(workflow.status)))
            .margin({ left: 6 })
        }
        .alignItems(VerticalAlign.Center)

        // 名称
        Text(workflow.name)
          .fontSize(this.sm.getFontSize('subtitle'))
          .fontWeight(FontWeight.Bold)
          .fontColor(this.sm.getColor('text_primary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 8 })

        // 描述摘要（截断 80 字符）
        Text(WorkflowViewHelper.truncateDescription(workflow.description, DEFAULT_TRUNCATE_LEN))
          .fontSize(this.sm.getFontSize('caption'))
          .fontColor(this.sm.getColor('text_secondary'))
          .maxLines(2)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .margin({ top: 4 })

        // 底部行：节点数 · 版本
        Row() {
          Text(WorkflowViewHelper.formatNodeCount(workflow.nodes ? workflow.nodes.length : 0))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
          Text('·')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
            .margin({ left: 6, right: 6 })
          Text(WorkflowViewHelper.formatVersion(workflow.version || '0.1.0'))
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_disabled'))
        }
        .width('100%')
        .margin({ top: 8 })
        .alignItems(VerticalAlign.Center)

        // 操作按钮：编辑/复制/启用-禁用/删除（右对齐）
        Row() {
          GlassButton({
            text: '编辑',
            type: 'default',
            size: 'small',
            onClick: () => { this.handleEdit(workflow); }
          })
          GlassButton({
            text: '复制',
            type: 'default',
            size: 'small',
            onClick: () => { this.duplicateWorkflow(workflow); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: workflow.status === 'active' ? '暂停' : '启用',
            type: workflow.status === 'active' ? 'default' : 'primary',
            size: 'small',
            onClick: () => { this.toggleStatus(workflow); }
          })
            .margin({ left: this.sm.getSpacing('sm') })
          GlassButton({
            text: '删除',
            type: 'danger',
            size: 'small',
            onClick: () => { this.confirmDelete(workflow); }
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

  /** 新建工作流弹窗：name 输入 + description 输入 */
  @Builder
  buildCreateDialog() {
    Stack({ alignContent: Alignment.Center }) {
      // 背景遮罩层：点击空白处关闭
      Column()
        .width('100%')
        .height('100%')
        .backgroundColor(this.sm.getColor('overlay_mask'))
        .onClick(() => { this.showCreateDialog = false; })

      // 面板层：居中展示
      GlassPanel({ variant: 'elevated', padding: 20 }) {
        Column() {
          Text('新建工作流')
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
            placeholder: '请输入工作流名称',
            value: this.formData.name,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, name: v }; }
          })
            .margin({ top: 4 })

          // 描述
          Text('描述')
            .fontSize(this.sm.getFontSize('caption'))
            .fontColor(this.sm.getColor('text_secondary'))
            .width('100%')
            .margin({ top: this.sm.getSpacing('sm') })
          GlassInput({
            placeholder: '请输入描述',
            value: this.formData.description,
            type: 'text',
            onChange: (v: string) => { this.formData = { ...this.formData, description: v }; }
          })
            .margin({ top: 4 })

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
