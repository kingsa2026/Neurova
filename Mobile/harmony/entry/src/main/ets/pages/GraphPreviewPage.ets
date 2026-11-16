/**
 * GraphPreviewPage - 图谱速览（对照原型 F18：2D/3D 切换）
 *
 * 数据：GET /knowledge-graph/{agent_id}/spatial-nodes（节点落图；
 *       连线子图 /subgraph 下一批接入——本页先呈现节点散布 + 类型着色）。
 * 布局：按序环形散布（2D）；3D 档以奇偶深度分层（远层缩小降透明）模拟前后景。
 * 点选节点 → 底部信息卡（label / type）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { AgentsStore } from '../libs/state/stores/AgentsStore';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';
import { GraphNodeDto } from '../libs/api/modules/KnowledgeGraphApi';

@Component
export struct GraphPreviewPage {
  @State private nodes: GraphNodeDto[] = [];
  @State private is3D: boolean = true;
  @State private selected: GraphNodeDto | null = null;
  @State private loading: boolean = false;
  private api = ApiFacade.getInstance();
  private agentsStore = new AgentsStore();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadGraph();
  }

  private async loadGraph(): Promise<void> {
    this.loading = true;
    try {
      const agentId = this.agentsStore.currentAgentId || 'default';
      const res = await this.api.graph.spatialNodes(agentId);
      if (res.code === 0 && res.data) {
        this.nodes = res.data;
        if (this.nodes.length > 0) {
          this.selected = this.nodes[0];
        }
      } else {
        this.msg.error(res.message || '图谱节点获取失败');
      }
    } catch (e) {
      this.msg.error('图谱节点获取失败：' + (e as Error).message);
    }
    this.loading = false;
  }

  /** 节点按序环形散布；返回百分比坐标（环形重排是确定性布局，非设备精确规格） */
  private deep(idx: number): boolean {
    return this.is3D && idx % 2 === 1;
  }

  private posX(idx: number): number {
    return this.pos(idx)[0];
  }

  private posY(idx: number): number {
    return this.pos(idx)[1];
  }

  private pos(idx: number): number[] {
    const total = this.nodes.length;
    const angle = (idx / Math.max(total, 1)) * 2 * Math.PI - Math.PI / 2;
    const radius = 34;
    const cx = 50;
    const cy = 46;
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * 0.78 * Math.sin(angle);
    return [x, y];
  }

  /** 类型 → 色相（按字符散列；色值经 StyleManager 令牌解析，深浅主题各自成立） */
  private nodeColor(type: string): string {
    // 四相异色相取自主题表（primary/secondary/info/warning），不硬编码——
    // 主题切换时节点色跟随主题，不再固定为暗色表四个值
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

  build() {
    Column() {
      Row() {
        Text('‹')
          .fontSize(22)
          .fontColor(this.sm.getColor('text_secondary'))
          .padding(8)
          .onClick(() => {
            this.router.back();
          })
        Text('知识图谱')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Text(this.nodes.length.toString() + ' 节点')
          .fontSize(12)
          .fontColor(this.sm.getColor('text_tertiary'))
          .padding(8)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      // 2D / 3D 切换
      Row() {
        Text('2D 平面')
          .fontSize(12)
          .padding({ left: 14, right: 14, top: 6, bottom: 6 })
          .borderRadius(999)
          .fontColor(!this.is3D ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
          .backgroundColor(!this.is3D ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
          .border({ width: 1, color: !this.is3D ? this.sm.getColor('primary') : this.sm.getColor('border') })
          .onClick(() => {
            this.is3D = false;
          })
        Text('3D 空间')
          .fontSize(12)
          .padding({ left: 14, right: 14, top: 6, bottom: 6 })
          .borderRadius(999)
          .fontColor(this.is3D ? this.sm.getColor('text_on_primary') : this.sm.getColor('text_secondary'))
          .backgroundColor(this.is3D ? this.sm.getColor('primary_soft') : this.sm.getColor('surface'))
          .border({ width: 1, color: this.is3D ? this.sm.getColor('primary') : this.sm.getColor('border') })
          .margin({ left: 8 })
          .onClick(() => {
            this.is3D = true;
          })
        Blank()
        Text(this.agentsStore.currentAgentId || 'default')
          .fontSize(11)
          .fontColor(this.sm.getColor('text_tertiary'))
      }
      .width('100%')
      .padding({ left: 20, right: 20, bottom: 8 })

      // 画布
      Stack() {
        if (this.nodes.length === 0 && !this.loading) {
          Text(this.loading ? '加载中…' : '暂无可见图节点')
            .fontSize(13)
            .fontColor(this.sm.getColor('text_tertiary'))
        }
        ForEach(this.nodes, (n: GraphNodeDto, idx: number) => {
          // 前后景深：3D 档奇数序号视作远层（缩小+降透明）
          Column() {
            Circle()
              .width(this.deep(idx) ? 12 : 18)
              .height(this.deep(idx) ? 12 : 18)
              .fill(this.nodeColor(n.type))
              .opacity(this.deep(idx) ? 0.45 : 1)
            Text(n.label)
              .fontSize(this.deep(idx) ? 8.5 : 10)
              .fontColor(this.sm.getColor(this.deep(idx) ? 'text_tertiary' : 'text_primary'))
              .margin({ top: 2 })
              .opacity(this.deep(idx) ? 0.5 : 1)
          }
          .position({ x: `${this.posX(idx)}%`, y: `${this.posY(idx)}%` })
          .onClick(() => {
            this.selected = n;
          })
        }, (n: GraphNodeDto) => n.node_id)
      }
      .layoutWeight(1)
      .width('calc(100% - 28vp)')
      .margin({ left: 14, right: 14 })
      .borderRadius(16)
      .backgroundColor(this.sm.getColor('surface'))
      .border({ width: 1, color: this.sm.getColor('border') })

      // 信息卡
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
            Text('node_id ' + this.selected.node_id)
              .fontSize(10)
              .fontColor(this.sm.getColor('text_tertiary'))
              .margin({ top: 3 })
              .maxLines(1)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
        }
        .width('calc(100% - 40vp)')
        .margin({ left: 20, right: 20, top: 10, bottom: 10 })
        .padding(13)
        .borderRadius(14)
        .backgroundColor(this.sm.getColor('surface_strong'))
        .border({ width: 1, color: this.sm.getColor('border') })
      }
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
