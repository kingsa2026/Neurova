/**
 * WorkflowEditPage - 工作流编辑器（M5）
 *
 * 职责：编辑既有工作流——基本信息（名称/描述）+ 节点列表（增/删/改/上下移）
 *   + 线性连线（按节点顺序自动成边）+ 保存（PUT /neurflow/workflows/{id}）+ 运行
 *   （POST /neurflow/workflows/{id}/execute）。
 * 设计：
 *   - 节点类型四类：start/task/decision/end（后端 WorkflowNode 契约）；
 *   - 连线不手画：按节点顺序线性成边（移动端形态，复杂分叉留待 PC 端画布）；
 *   - 工作流 id 经 StateManager('workflow:edit_id') 传入；
 *   - GlassPanel 尾闭包后不可链属性——外包内置容器承接。
 *
 * 依赖：../components/glass、../libs/api/ApiFacade、../routing/Router、
 *   ../libs/state/StateManager、../libs/style/StyleManager、../libs/logger/Logger、
 *   ../libs/message/MessageManager、../libs/types（Workflow/WorkflowNode/WorkflowEdge）
 */

import { TopNavMenu, GlassCard, GlassButton, GlassInput, GlassPanel } from '../components/glass';
import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StateManager } from '../libs/state/StateManager';
import { StyleManager } from '../libs/style/StyleManager';
import { Logger } from '../libs/logger/Logger';
import { MessageManager } from '../libs/message/MessageManager';
import { Workflow, WorkflowNode, WorkflowEdge } from '../libs/types';

/** 日志标签 */
const TAG = 'WorkflowEditPage';

/** 节点类型取值（后端 WorkflowNode.type 契约） */
const NODE_TYPE_VALUES: string[] = ['start', 'task', 'decision', 'end'];

/** 字符串 → 节点类型联合（ArkTS 不支持字符串直赋联合类型） */
function nodeTypeOf(v: string): 'start' | 'task' | 'decision' | 'end' {
  if (v === 'start') return 'start';
  if (v === 'decision') return 'decision';
  if (v === 'end') return 'end';
  return 'task';
}

@Component
export struct WorkflowEditPage {
  // 工作流本体
  @State wfId: string = '';
  @State wfName: string = '';
  @State wfDescription: string = '';
  @State nodes: WorkflowNode[] = [];
  @State loading: boolean = true;
  @State saving: boolean = false;
  @State running: boolean = false;

  // 节点编辑弹层
  @State showNodeEdit: boolean = false;
  @State nodeEditIndex: number = -1;
  @State nodeEditName: string = '';
  @State nodeEditType: string = 'task';
  // 节点新增弹层
  @State showNodeAdd: boolean = false;
  @State nodeAddName: string = '';
  @State nodeAddType: string = 'task';

  // 统一库单例
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private logger = Logger.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear() {
    this.wfId = StateManager.getInstance().get<string>('workflow:edit_id', '');
    this.loadWorkflow();
  }

  /** 加载工作流详情 */
  private async loadWorkflow(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.collaboration.getWorkflow(this.wfId);
      if (res.code === 0 && res.data) {
        this.wfName = res.data.name;
        this.wfDescription = res.data.description ?? '';
        this.nodes = res.data.nodes ?? [];
      } else {
        this.msg.error(res.message || '工作流加载失败');
      }
    } catch (e) {
      this.logger.error(TAG, '加载工作流失败', e as Error);
      this.msg.error('加载工作流失败');
    } finally {
      this.loading = false;
    }
  }

  /** 节点类型中文标签 */
  private typeLabel(t: string): string {
    if (t === 'start') return '开始';
    if (t === 'decision') return '决策';
    if (t === 'end') return '结束';
    return '任务';
  }

  /** 节点类型颜色 token */
  private typeColor(t: string): string {
    if (t === 'start') return 'success';
    if (t === 'decision') return 'warning';
    if (t === 'end') return 'error';
    return 'primary';
  }

  /** 上移节点 */
  private moveNodeUp(index: number): void {
    if (index <= 0) return;
    const next = this.nodes.slice();
    const tmp = next[index];
    next[index] = next[index - 1];
    next[index - 1] = tmp;
    this.nodes = next;
  }

  /** 下移节点 */
  private moveNodeDown(index: number): void {
    if (index >= this.nodes.length - 1) return;
    const next = this.nodes.slice();
    const tmp = next[index];
    next[index] = next[index + 1];
    next[index + 1] = tmp;
    this.nodes = next;
  }

  /** 删除节点 */
  private deleteNode(index: number): void {
    const next = this.nodes.slice();
    next.splice(index, 1);
    this.nodes = next;
  }

  /** 打开节点编辑弹层 */
  private openNodeEdit(index: number): void {
    this.nodeEditIndex = index;
    this.nodeEditName = this.nodes[index].name;
    this.nodeEditType = this.nodes[index].type;
    this.showNodeEdit = true;
  }

  /** 保存节点编辑 */
  private saveNodeEdit(): void {
    if (this.nodeEditIndex < 0 || this.nodeEditIndex >= this.nodes.length) {
      return;
    }
    if (this.nodeEditName.trim() === '') {
      this.msg.warning('请填写节点名称');
      return;
    }
    const next = this.nodes.slice();
    const src = next[this.nodeEditIndex];
    const updated: WorkflowNode = {
      id: src.id,
      type: nodeTypeOf(this.nodeEditType),
      name: this.nodeEditName.trim(),
      config: src.config,
    };
    next[this.nodeEditIndex] = updated;
    this.nodes = next;
    this.showNodeEdit = false;
  }

  /** 打开节点新增弹层 */
  private openNodeAdd(): void {
    this.nodeAddName = '';
    this.nodeAddType = 'task';
    this.showNodeAdd = true;
  }

  /** 追加新节点 */
  private saveNodeAdd(): void {
    if (this.nodeAddName.trim() === '') {
      this.msg.warning('请填写节点名称');
      return;
    }
    const node: WorkflowNode = {
      id: `node-${Date.now().toString(36)}`,
      type: nodeTypeOf(this.nodeAddType),
      name: this.nodeAddName.trim(),
    };
    const next = this.nodes.slice();
    next.push(node);
    this.nodes = next;
    this.showNodeAdd = false;
  }

  /** 线性连线：按节点顺序 source→target */
  private buildEdges(): WorkflowEdge[] {
    const edges: WorkflowEdge[] = [];
    for (let i = 0; i < this.nodes.length - 1; i++) {
      const e: WorkflowEdge = { source: this.nodes[i].id, target: this.nodes[i + 1].id };
      edges.push(e);
    }
    return edges;
  }

  /** 保存（名称/描述/节点/线性连线） */
  private async saveWorkflow(): Promise<void> {
    if (this.wfName.trim() === '') {
      this.msg.warning('请填写工作流名称');
      return;
    }
    if (this.nodes.length < 2) {
      this.msg.warning('至少需要两个节点（开始/结束）');
      return;
    }
    this.saving = true;
    try {
      const data: Partial<Workflow> = {
        name: this.wfName.trim(),
        description: this.wfDescription.trim(),
        nodes: this.nodes,
        edges: this.buildEdges(),
      };
      const res = await this.api.collaboration.updateWorkflow(this.wfId, data);
      if (res.code === 0) {
        this.msg.success('工作流已保存');
        this.router.back();
      } else {
        this.msg.error(res.message || '保存失败');
      }
    } catch (e) {
      this.logger.error(TAG, '保存工作流失败', e as Error);
      this.msg.error('保存失败：' + (e as Error).message);
    } finally {
      this.saving = false;
    }
  }

  /** 运行工作流（触发执行，结果经执行记录查看） */
  private async runWorkflow(): Promise<void> {
    this.running = true;
    try {
      const inputs: Record<string, Object> = {};
      const res = await this.api.collaboration.executeWorkflow(this.wfId, inputs);
      if (res.code === 0 || res.data !== undefined) {
        this.msg.success('已触发执行，可在执行记录中查看进度');
      } else {
        this.msg.error(res.message || '触发执行失败');
      }
    } catch (e) {
      this.logger.error(TAG, '触发执行失败', e as Error);
      this.msg.error('触发执行失败：' + (e as Error).message);
    } finally {
      this.running = false;
    }
  }

  build() {
    Column() {
      TopNavMenu({
        title: '编辑工作流',
        showBack: true,
        showMenu: false,
        onBack: () => { this.router.back(); }
      })

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
      } else {
        Scroll() {
          Column() {
            // ========== 基本信息 ==========
            Column() {
              GlassCard({ title: '基本信息' }) {
                Column() {
                  Text('名称')
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_secondary'))
                    .width('100%')
                  GlassInput({
                    placeholder: '工作流名称',
                    value: this.wfName,
                    type: 'text',
                    onChange: (v: string) => { this.wfName = v; }
                  })

                  Text('描述')
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_secondary'))
                    .width('100%')
                    .margin({ top: this.sm.getSpacing('sm') })
                  GlassInput({
                    placeholder: '工作流描述',
                    value: this.wfDescription,
                    type: 'text',
                    onChange: (v: string) => { this.wfDescription = v; }
                  })
                }
                .width('100%')
                .alignItems(HorizontalAlign.Start)
              }
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // ========== 节点列表 ==========
            Column() {
              GlassCard({ title: '节点列表（按顺序线性连线）' }) {
                Column() {
                  ForEach(this.nodes, (n: WorkflowNode, i: number) => {
                    Row() {
                      Text((i + 1).toString())
                        .fontSize(this.sm.getFontSize('caption'))
                        .fontWeight(FontWeight.Bold)
                        .fontColor(this.sm.getColor('text_on_primary'))
                        .width(24)
                        .height(24)
                        .borderRadius(12)
                        .textAlign(TextAlign.Center)
                        .backgroundColor(this.sm.getColor('primary'))
                      Text(n.name)
                        .fontSize(this.sm.getFontSize('body_sm'))
                        .fontColor(this.sm.getColor('text_primary'))
                        .maxLines(1)
                        .textOverflow({ overflow: TextOverflow.Ellipsis })
                        .margin({ left: 8 })
                      Text(this.typeLabel(n.type))
                        .fontSize(this.sm.getFontSize('badge'))
                        .fontColor(this.sm.getColor('text_on_primary'))
                        .padding({ left: 6, right: 6, top: 2, bottom: 2 })
                        .borderRadius(8)
                        .backgroundColor(this.sm.getColor(this.typeColor(n.type)))
                        .margin({ left: 8 })
                      Blank()
                      Text('↑')
                        .fontSize(this.sm.getFontSize('body_sm'))
                        .fontColor(this.sm.getColor('text_secondary'))
                        .padding(4)
                        .onClick(() => { this.moveNodeUp(i); })
                      Text('↓')
                        .fontSize(this.sm.getFontSize('body_sm'))
                        .fontColor(this.sm.getColor('text_secondary'))
                        .padding(4)
                        .margin({ left: 2 })
                        .onClick(() => { this.moveNodeDown(i); })
                      Text('编辑')
                        .fontSize(this.sm.getFontSize('badge'))
                        .fontColor(this.sm.getColor('primary'))
                        .padding(4)
                        .margin({ left: 2 })
                        .onClick(() => { this.openNodeEdit(i); })
                      Text('删除')
                        .fontSize(this.sm.getFontSize('badge'))
                        .fontColor(this.sm.getColor('error'))
                        .padding(4)
                        .margin({ left: 2 })
                        .onClick(() => { this.deleteNode(i); })
                    }
                    .width('100%')
                    .padding({ top: 6, bottom: 6 })
                    .alignItems(VerticalAlign.Center)
                  }, (n: WorkflowNode) => n.id + n.name)
                }
                .width('100%')
                .alignItems(HorizontalAlign.Start)

                GlassButton({
                  text: '＋ 添加节点',
                  type: 'default',
                  btnSize: 'small',
                  onTap: () => { this.openNodeAdd(); }
                })
                  .margin({ top: this.sm.getSpacing('sm') })
              }
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // ========== 连线预览 ==========
            Column() {
              GlassCard({ title: '连线（自动按顺序）' }) {
                Column() {
                  Text(this.nodes.map((n: WorkflowNode) => n.name).join(' → '))
                    .fontSize(this.sm.getFontSize('caption'))
                    .fontColor(this.sm.getColor('text_secondary'))
                    .width('100%')
                }
                .width('100%')
                .alignItems(HorizontalAlign.Start)
              }
            }
            .width('100%')
            .margin({ bottom: this.sm.getSpacing('md') })

            // ========== 操作 ==========
            Row() {
              GlassButton({
                text: this.saving ? '保存中...' : '保存',
                type: 'primary',
                btnSize: 'medium',
                onTap: () => { this.saveWorkflow(); }
              })
                .layoutWeight(1)
              GlassButton({
                text: this.running ? '触发中...' : '运行',
                type: 'default',
                btnSize: 'medium',
                onTap: () => { this.runWorkflow(); }
              })
                .layoutWeight(1)
                .margin({ left: this.sm.getSpacing('sm') })
            }
            .width('100%')
            .margin({ bottom: 28 })
          }
          .width('100%')
          .padding(this.sm.getSpacing('md'))
          .alignItems(HorizontalAlign.Start)
        }
        .layoutWeight(1)
        .width('100%')
        .scrollBar(BarState.Off)
        .align(Alignment.TopStart)
      }

      // 节点编辑弹层
      if (this.showNodeEdit) {
        Stack({ alignContent: Alignment.Center }) {
          Column()
            .width('100%')
            .height('100%')
            .backgroundColor(this.sm.getColor('overlay_mask'))
            .onClick(() => { this.showNodeEdit = false; })

          Column() {
            GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
              Column() {
                Text('编辑节点')
                  .fontSize(this.sm.getFontSize('subtitle'))
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.sm.getColor('text_primary'))
                  .width('100%')

                Text('节点类型')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .width('100%')
                  .margin({ top: this.sm.getSpacing('sm') })
                Select(this.typeSelectOptions())
                  .selected(this.typeSelectIndex(this.nodeEditType))
                  .value(this.typeLabel(this.nodeEditType))
                  .font({ size: this.sm.getFontSize('body_sm') })
                  .fontColor(this.sm.getColor('text_primary'))
                  .optionFont({ size: this.sm.getFontSize('body_sm') })
                  .width('100%')
                  .onSelect((index: number) => {
                    if (index >= 0 && index < NODE_TYPE_VALUES.length) {
                      this.nodeEditType = NODE_TYPE_VALUES[index];
                    }
                  })

                Text('节点名称')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .width('100%')
                  .margin({ top: this.sm.getSpacing('sm') })
                GlassInput({
                  placeholder: '节点名称',
                  value: this.nodeEditName,
                  type: 'text',
                  onChange: (v: string) => { this.nodeEditName = v; }
                })

                Row() {
                  GlassButton({
                    text: '取消',
                    type: 'default',
                    btnSize: 'medium',
                    onTap: () => { this.showNodeEdit = false; }
                  })
                  GlassButton({
                    text: '保存',
                    type: 'primary',
                    btnSize: 'medium',
                    onTap: () => { this.saveNodeEdit(); }
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
          .width('90%')
        }
        .width('100%')
        .height('100%')
      }

      // 节点新增弹层
      if (this.showNodeAdd) {
        Stack({ alignContent: Alignment.Center }) {
          Column()
            .width('100%')
            .height('100%')
            .backgroundColor(this.sm.getColor('overlay_mask'))
            .onClick(() => { this.showNodeAdd = false; })

          Column() {
            GlassPanel({ variant: 'elevated', innerPadding: 20 }) {
              Column() {
                Text('添加节点')
                  .fontSize(this.sm.getFontSize('subtitle'))
                  .fontWeight(FontWeight.Bold)
                  .fontColor(this.sm.getColor('text_primary'))
                  .width('100%')

                Text('节点类型')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .width('100%')
                  .margin({ top: this.sm.getSpacing('sm') })
                Select(this.typeSelectOptions())
                  .selected(this.typeSelectIndex(this.nodeAddType))
                  .value(this.typeLabel(this.nodeAddType))
                  .font({ size: this.sm.getFontSize('body_sm') })
                  .fontColor(this.sm.getColor('text_primary'))
                  .optionFont({ size: this.sm.getFontSize('body_sm') })
                  .width('100%')
                  .onSelect((index: number) => {
                    if (index >= 0 && index < NODE_TYPE_VALUES.length) {
                      this.nodeAddType = NODE_TYPE_VALUES[index];
                    }
                  })

                Text('节点名称')
                  .fontSize(this.sm.getFontSize('caption'))
                  .fontColor(this.sm.getColor('text_secondary'))
                  .width('100%')
                  .margin({ top: this.sm.getSpacing('sm') })
                GlassInput({
                  placeholder: '节点名称',
                  value: this.nodeAddName,
                  type: 'text',
                  onChange: (v: string) => { this.nodeAddName = v; }
                })

                Row() {
                  GlassButton({
                    text: '取消',
                    type: 'default',
                    btnSize: 'medium',
                    onTap: () => { this.showNodeAdd = false; }
                  })
                  GlassButton({
                    text: '添加',
                    type: 'primary',
                    btnSize: 'medium',
                    onTap: () => { this.saveNodeAdd(); }
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
          .width('90%')
        }
        .width('100%')
        .height('100%')
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }

  /** 节点类型下拉选项 */
  private typeSelectOptions(): SelectOption[] {
    const out: SelectOption[] = [];
    for (const t of NODE_TYPE_VALUES) {
      const so: SelectOption = { value: this.typeLabel(t) };
      out.push(so);
    }
    return out;
  }

  /** 节点类型 → 下标 */
  private typeSelectIndex(t: string): number {
    return NODE_TYPE_VALUES.indexOf(t) >= 0 ? NODE_TYPE_VALUES.indexOf(t) : 1;
  }
}
