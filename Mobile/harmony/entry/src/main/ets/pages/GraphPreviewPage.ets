/**
 * GraphPreviewPage - 图谱速览（严格按设计稿 F18：2D/3D + 连线 + 节点卡 + 搜索/过滤/重置）
 *
 * 数据（同源 PC GraphWorkbenchPage 端点）：
 *   GET /knowledge-graph/{agent}/subgraph          首屏全量子集（节点+关系边）
 *   GET /knowledge-graph/{agent}/subgraph?focus=   选中节点邻域（探索=换焦点再请求，不养大图）
 *   GET /knowledge-graph/{agent}/knowledge-graph/search?q=  实体搜索
 *   GET /knowledge-graph/{agent}/knowledge-graph/nodes/{id} 节点详情（关系计数）
 * 3D：角度制环形布局 + 拖动旋转（PanGesture 调 rotation，前后景深按 sin 分层）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { GraphNodeFullDto, GraphEdgeDto } from '../libs/api/modules/KnowledgeGraphApi';
import { IconBtn } from '../components/common/IconBtn';
import { AppIcon } from '../components/common/AppIcon';
import { GlassInput } from '../components/glass';

@Component
export struct GraphPreviewPage {
  @State private nodes: GraphNodeFullDto[] = [];
  @State private edges: GraphEdgeDto[] = [];
  @State private relations: string[] = [];
  @State private relationFilter: string = '';
  /** 2D/3D（设计 .ghead .seg；默认 3D 空间） */
  @State private is3D: boolean = true;
  /** 3D 拖动旋转角（PanGesture 累加） */
  @State private rotation: number = 0;
  @State private selected: GraphNodeFullDto | null = null;
  /** 选中节点关系数（node detail 真实计数） */
  @State private selectedDegree: number = -1;
  @State private loading: boolean = false;
  // 搜索弹层
  @State private searchOpen: boolean = false;
  @State private searchQuery: string = '';
  @State private searchResults: GraphNodeFullDto[] = [];
  // 关系过滤弹层
  @State private filterOpen: boolean = false;
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadGraph();
  }

  /** 首屏子图（focus 空=全图子集） */
  private async loadGraph(focus?: string): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || 'default';
      const res = await this.api.graph.subgraph(agentId, focus, focus ? 2 : undefined, 200);
      if (res.code === 0 && res.data) {
        this.nodes = res.data.nodes;
        this.edges = res.data.edges;
        this.rebuildRelations();
        if (this.nodes.length > 0 && !this.selected) {
          this.selectNode(this.nodes[0]);
        }
      } else {
        this.msg.error(res.message || '图谱获取失败');
      }
    } catch (e) {
      this.msg.error('图谱获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  /** 关系类型名册（过滤弹层选项，来自当前子图真实边） */
  private rebuildRelations(): void {
    const seen: string[] = [];
    for (const e of this.edges) {
      if (seen.indexOf(e.relation) === -1) {
        seen.push(e.relation);
      }
    }
    this.relations = seen;
  }

  /** 选中节点：拉详情（关系计数）+ 以其为焦点拉邻域子图 */
  private selectNode(n: GraphNodeFullDto): void {
    this.selected = n;
    this.selectedDegree = -1;
    const agentId = this.agentsStore.currentAgentId || 'default';
    this.api.graph.nodeDetail(agentId, n.id).then((res) => {
      if (res.code === 0 && res.data) {
        this.selectedDegree = res.data.edges.length;
      }
    }).catch(() => {
      this.selectedDegree = -1;
    });
    this.loadGraph(n.id);
  }

  /** 实体搜索 */
  private async doSearch(): Promise<void> {
    const q = this.searchQuery.trim();
    if (q.length === 0) {
      return;
    }
    try {
      const agentId = this.agentsStore.currentAgentId || 'default';
      const res = await this.api.graph.searchNodes(agentId, q, 20);
      if (res.code === 0 && res.data) {
        this.searchResults = res.data.nodes;
      }
    } catch (e) {
      this.msg.error('搜索失败：' + (e as Error).message);
    }
  }

  /**
   * 节点坐标（vp，画布固定 320×400；3D=角度加旋转、按 sin 分前后景深）。
   * 固定画布让边线端点可用数值坐标（Line 的 Point 为 vp 数值），消除百分比歧义。
   */
  private pos(idx: number): number[] {
    const total = Math.max(this.nodes.length, 1);
    const base = (idx / total) * 2 * Math.PI - Math.PI / 2;
    if (!this.is3D) {
      return [160 + 118 * Math.cos(base), 190 + 92 * Math.sin(base)];
    }
    const a = base + this.rotation;
    return [160 + 118 * Math.cos(a), 190 + 92 * Math.sin(a) * 0.9];
  }

  /** 3D 前后景深系数 0~1（2D 恒 1） */
  private depth(idx: number): number {
    if (!this.is3D) {
      return 1;
    }
    const total = Math.max(this.nodes.length, 1);
    const a = (idx / total) * 2 * Math.PI - Math.PI / 2 + this.rotation;
    return (Math.sin(a) + 1) / 2;
  }

  private nodeById(id: string): GraphNodeFullDto | null {
    for (const n of this.nodes) {
      if (n.id === id) {
        return n;
      }
    }
    return null;
  }

  private idxById(id: string): number {
    for (let i = 0; i < this.nodes.length; i++) {
      if (this.nodes[i].id === id) {
        return i;
      }
    }
    return -1;
  }

  /** 边显隐：关系过滤（选中关系=只看该类边；空=全部） */
  private edgeVisible(e: GraphEdgeDto): boolean {
    return this.relationFilter.length === 0 || e.relation === this.relationFilter;
  }

  /** 边强调：与选中节点相连的边用青色（设计两段边色） */
  private edgeColor(e: GraphEdgeDto): string {
    if (this.selected && (e.source === this.selected.id || e.target === this.selected.id)) {
      return 'rgba(34,211,238,0.55)';
    }
    return 'rgba(139,92,246,0.35)';
  }

  /** 类型 → 色相（按字符散列进主题四色） */
  private nodeColor(type: string): string {
    const palette: string[] = [
      this.sm.getColor('primary'),
      this.sm.getColor('secondary'),
      this.sm.getColor('info'),
      this.sm.getColor('warning'),
    ];
    let h = 0;
    for (let i = 0; i < type.length; i++) {
      h = (h + type.charCodeAt(i)) % palette.length;
    }
    return palette[h];
  }

  /** 画布手势：3D 拖动旋转（2D 不响应） */
  private panRotate(x: number): void {
    if (this.is3D) {
      this.rotation += x * 0.01;
    }
  }

  build() {
    Column() {
      // 头部（设计 .phead：返回 + 知识图谱 + 刷新）
      Row() {
        IconBtn({ name: 'back', onTap: () => { this.router.back(); } })
        Text('知识图谱')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        IconBtn({ name: 'history', onTap: () => { this.selected = null; this.loadGraph(); } })
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      // ghead：agent 名 + 2D/3D 分段
      Row() {
        Text((this.agentsStore.currentAgentId || 'default') + ' 的图谱')
          .fontSize(12)
          .fontColor(this.sm.getColor('text_secondary'))
          .layoutWeight(1)
        Text('2D 平面')
          .fontSize(12)
          .padding({ left: 13, right: 13, top: 6, bottom: 6 })
          .borderRadius(999)
          .fontColor(!this.is3D ? '#FFFFFF' : this.sm.getColor('text_secondary'))
          .backgroundColor(!this.is3D ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
          .border({ width: 1, color: !this.is3D ? 'rgba(99,102,241,0.50)' : this.sm.getColor('border') })
          .onClick(() => { this.is3D = false; })
        Text('3D 空间')
          .fontSize(12)
          .padding({ left: 13, right: 13, top: 6, bottom: 6 })
          .borderRadius(999)
          .fontColor(this.is3D ? '#FFFFFF' : this.sm.getColor('text_secondary'))
          .backgroundColor(this.is3D ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
          .border({ width: 1, color: this.is3D ? 'rgba(99,102,241,0.50)' : this.sm.getColor('border') })
          .margin({ left: 6 })
          .onClick(() => { this.is3D = true; })
      }
      .width('100%')
      .padding({ left: 20, right: 20, bottom: 8 })
      .alignItems(VerticalAlign.Center)

      // 画布容器（居中承载固定 320×400 画布）
      Column() {
        // 画布（设计 .gwrap：边线 + 节点 + 选中环 + 3D 角标；PanGesture 拖动旋转）
        Stack() {
          if (this.nodes.length === 0 && !this.loading) {
            Text(this.loading ? '加载中…' : '暂无可见图节点')
              .fontSize(13)
              .fontColor(this.sm.getColor('text_tertiary'))
          }

          // 关系边（子图真实边；选中节点邻接边青色强调；Path 命令用 vp 数值坐标）
          ForEach(this.edges, (e: GraphEdgeDto) => {
            if (this.edgeVisible(e) && this.idxById(e.source) >= 0 && this.idxById(e.target) >= 0) {
              Path({
                width: 320,
                height: 400,
                commands: `M ${this.pos(this.idxById(e.source))[0]} ${this.pos(this.idxById(e.source))[1]} L ${this.pos(this.idxById(e.target))[0]} ${this.pos(this.idxById(e.target))[1]}`
              })
                .stroke(this.edgeColor(e))
                .strokeWidth(this.selected !== null && (e.source === this.selected.id || e.target === this.selected.id) ? 1.6 : 1)
                .fillOpacity(0)
                .position({ x: 0, y: 0 })
            }
          }, (e: GraphEdgeDto) => e.source + '-' + e.target + '-' + this.relationFilter)

          // 节点（3D 按景深缩放降透明；选中=高亮环）
          ForEach(this.nodes, (n: GraphNodeFullDto, idx: number) => {
            Column() {
              Stack() {
                if (this.selected && this.selected.id === n.id) {
                  Circle()
                    .width(34)
                    .height(34)
                    .fill('rgba(0,0,0,0)')
                    .stroke('rgba(34,211,238,0.65)')
                    .strokeWidth(1.3)
                }
                Circle()
                  .width(12 + 10 * this.depth(idx))
                  .height(12 + 10 * this.depth(idx))
                  .fill(this.selected && this.selected.id === n.id ? this.sm.getColor('primary') : this.nodeColor(n.type))
                  .opacity(0.35 + 0.65 * this.depth(idx))
              }
              Text(n.label)
                .fontSize(8.5 + 2 * this.depth(idx))
                .fontColor(this.sm.getColor(this.depth(idx) > 0.5 ? 'text_primary' : 'text_tertiary'))
                .margin({ top: 2 })
                .opacity(0.4 + 0.6 * this.depth(idx))
                .maxLines(1)
            }
            .position({ x: this.pos(idx)[0] - 18, y: this.pos(idx)[1] - 18 })
            .onClick(() => { this.selectNode(n); })
          }, (n: GraphNodeFullDto) => n.id + '#' + (this.is3D ? '3d' : '2d') + this.rotation.toFixed(2))

          // 3D 角标（设计 .g3d）
          if (this.is3D) {
            Row() {
              AppIcon({ name: 'fork', iconSize: 10, color: this.sm.getColor('text_secondary') })
              Text('3D · 拖动旋转')
                .fontSize(9.5)
                .fontColor(this.sm.getColor('text_secondary'))
                .margin({ left: 4 })
            }
            .padding({ left: 9, right: 9, top: 5, bottom: 5 })
            .borderRadius(999)
            .backgroundColor(this.sm.getColor('surface_strong'))
            .border({ width: 1, color: this.sm.getColor('border') })
            .position({ x: 14, y: 352 })
          }
        }
        .width(320)
        .height(400)
        .borderRadius(16)
        .backgroundColor(this.sm.getColor('surface'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .gesture(
          PanGesture()
            .onActionUpdate((event: PanGestureEvent) => { this.panRotate(event.offsetX); })
        )
      }
      .width('100%')
      .alignItems(HorizontalAlign.Center)

      // 节点信息卡（设计 .gcard：标题+类型徽标+关系计数+查看事实）
      if (this.selected) {
        Row() {
          Column() {
            Row() {
              Text(this.selected.label)
                .fontSize(13.5)
                .fontWeight(FontWeight.Medium)
                .fontColor(this.sm.getColor('text_primary'))
              Text(this.selected.type.length > 0 ? this.selected.type : '实体')
                .fontSize(9)
                .fontColor(this.sm.getColor('primary'))
                .padding({ left: 6, right: 6, top: 1, bottom: 1 })
                .borderRadius(5)
                .border({ width: 1, color: this.sm.getColor('primary') })
                .margin({ left: 8 })
            }
            .alignItems(VerticalAlign.Center)
            Text((this.selectedDegree >= 0 ? '关系 ' + this.selectedDegree.toString() + ' 条' : '统计中…') +
              (this.selected.description.length > 0 ? ' · ' + this.selected.description : '') +
              (this.selected.created_at && this.selected.created_at.length >= 10
                ? ' · 建于 ' + this.selected.created_at.slice(0, 10) : ''))
              .fontSize(10.5)
              .fontColor(this.sm.getColor('text_tertiary'))
              .margin({ top: 3 })
              .maxLines(2)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)

          Row() {
            Text('查看事实')
              .fontSize(11.5)
              .fontColor(this.sm.getColor('primary'))
            AppIcon({ name: 'chev', iconSize: 11, color: this.sm.getColor('primary') })
          }
          .alignItems(VerticalAlign.Center)
          .onClick(() => { this.loadGraph(this.selected ? this.selected.id : undefined); })
        }
        .width('calc(100% - 40vp)')
        .margin({ left: 20, right: 20, top: 10, bottom: 8 })
        .padding(13)
        .borderRadius(14)
        .backgroundColor(this.sm.getColor('surface_strong'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .alignItems(VerticalAlign.Center)
      }

      // 控制排（设计 .gctl：搜索实体 / 关系过滤 / 重置视角）
      Row() {
        Row() {
          AppIcon({ name: 'search', iconSize: 11, color: this.sm.getColor('text_secondary') })
          Text('搜索实体')
            .fontSize(10.5)
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })
        }
        .padding({ left: 10, right: 10, top: 7, bottom: 7 })
        .borderRadius(999)
        .backgroundColor(this.sm.getColor('glass'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .onClick(() => { this.searchOpen = true; })

        Row() {
          AppIcon({ name: 'task', iconSize: 11, color: this.sm.getColor('text_secondary') })
          Text(this.relationFilter.length > 0 ? '关系：' + this.relationFilter : '关系过滤')
            .fontSize(10.5)
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })
        }
        .padding({ left: 10, right: 10, top: 7, bottom: 7 })
        .borderRadius(999)
        .backgroundColor(this.sm.getColor('glass'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .margin({ left: 8 })
        .onClick(() => { this.filterOpen = true; })

        Row() {
          AppIcon({ name: 'history', iconSize: 11, color: this.sm.getColor('text_secondary') })
          Text('重置视角')
            .fontSize(10.5)
            .fontColor(this.sm.getColor('text_secondary'))
            .margin({ left: 4 })
        }
        .padding({ left: 10, right: 10, top: 7, bottom: 7 })
        .borderRadius(999)
        .backgroundColor(this.sm.getColor('glass'))
        .border({ width: 1, color: this.sm.getColor('border') })
        .margin({ left: 8 })
        .onClick(() => {
          this.rotation = 0;
          this.relationFilter = '';
          this.selected = null;
          this.loadGraph();
        })
        Blank()
      }
      .width('100%')
      .padding({ left: 20, right: 20, bottom: 14 })

      // 搜索弹层
      if (this.searchOpen) {
        Column() {
          Column() {
            Text('搜索实体')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
            GlassInput({
              placeholder: '输入实体关键词',
              value: this.searchQuery,
              onChange: (v: string) => { this.searchQuery = v; },
              onSubmit: () => { this.doSearch(); }
            })
              .margin({ top: 12 })
            Scroll() {
              Column() {
                if (this.searchResults.length === 0) {
                  Text('输入关键词后搜索（回车）')
                    .fontSize(11.5)
                    .fontColor(this.sm.getColor('text_tertiary'))
                    .margin({ top: 10 })
                }
                ForEach(this.searchResults, (n: GraphNodeFullDto) => {
                  Row() {
                    Text(n.label)
                      .fontSize(12.5)
                      .fontColor(this.sm.getColor('text_primary'))
                      .layoutWeight(1)
                    Text(n.type)
                      .fontSize(9.5)
                      .fontColor(this.sm.getColor('primary'))
                  }
                  .width('100%')
                  .padding({ top: 8, bottom: 8 })
                  .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
                  .onClick(() => {
                    this.searchOpen = false;
                    this.selectNode(n);
                  })
                }, (n: GraphNodeFullDto) => n.id)
              }
              .width('100%')
              .alignItems(HorizontalAlign.Start)
            }
            .height(200)
            .margin({ top: 8 })
            .scrollBar(BarState.Off)
            Text('收起')
              .fontSize(12.5)
              .fontColor(this.sm.getColor('primary'))
              .padding({ top: 10 })
              .onClick(() => { this.searchOpen = false; })
          }
          .width('76%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }

      // 关系过滤弹层
      if (this.filterOpen) {
        Column() {
          Column() {
            Text('关系过滤')
              .fontSize(15)
              .fontWeight(FontWeight.Bold)
              .fontColor(this.sm.getColor('text_primary'))
              .margin({ bottom: 8 })
            Text('全部关系')
              .fontSize(13)
              .fontColor(this.relationFilter.length === 0 ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
              .padding({ left: 14, right: 14, top: 9, bottom: 9 })
              .borderRadius(11)
              .backgroundColor(this.relationFilter.length === 0 ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
              .border({ width: 1, color: this.relationFilter.length === 0 ? this.sm.getColor('primary') : this.sm.getColor('border') })
              .margin({ top: 4 })
              .onClick(() => {
                this.relationFilter = '';
                this.filterOpen = false;
              })
            ForEach(this.relations, (r: string) => {
              Text(r)
                .fontSize(13)
                .fontColor(this.relationFilter === r ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
                .padding({ left: 14, right: 14, top: 9, bottom: 9 })
                .borderRadius(11)
                .backgroundColor(this.relationFilter === r ? 'rgba(99,102,241,0.28)' : this.sm.getColor('glass'))
                .border({ width: 1, color: this.relationFilter === r ? this.sm.getColor('primary') : this.sm.getColor('border') })
                .margin({ top: 8 })
                .onClick(() => {
                  this.relationFilter = r;
                  this.filterOpen = false;
                })
            }, (r: string) => r)
          }
          .width('70%')
          .padding(16)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface_strong'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .alignItems(HorizontalAlign.Start)
        }
        .width('100%')
        .height('100%')
        .backgroundColor('rgba(4,6,14,0.60)')
        .justifyContent(FlexAlign.Center)
        .alignItems(HorizontalAlign.Center)
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
