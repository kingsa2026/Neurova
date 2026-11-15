/**
 * AdminSettingsPage - 系统设置（管理员，对照原型 F17 的治理子集）
 *
 * 数据：GET /v1/governance/agent-limits（仅管理员；响应为动态键值对象，
 *       页面按键遍历渲染）。写回（PUT）在 PC 治理页管理——移动端只读。
 * 说明：/v1/settings（扁平 kv）挂载在无 /v1 前缀的 /api/settings，App baseUrl
 *       为 /api/v1 无法直达——设置全量面留在 PC（台账记录，待后端补挂或双 baseUrl）。
 */

import { ApiFacade } from '../libs/api/ApiFacade';
import { Router } from '../routing/Router';
import { StyleManager } from '../libs/style/StyleManager';
import { MessageManager } from '../libs/message/MessageManager';

@Component
export struct AdminSettingsPage {
  @State private rows: string[][] = [];
  @State private loading: boolean = false;
  private api = ApiFacade.getInstance();
  private router = Router.getInstance();
  private sm = StyleManager.getInstance();
  private msg = MessageManager.getInstance();

  aboutToAppear(): void {
    this.loadLimits();
  }

  private async loadLimits(): Promise<void> {
    this.loading = true;
    try {
      const res = await this.api.admin.agentLimits();
      if (res.code === 0 && res.data) {
        const obj = res.data as Record<string, Object>;
        const out: string[][] = [];
        const keys = Object.keys(obj);
        for (const k of keys) {
          const v = obj[k];
          out.push([k, typeof v === 'object' ? JSON.stringify(v) : `${v}`]);
        }
        this.rows = out;
      } else {
        this.msg.error(res.message || '治理设置获取失败');
      }
    } catch (e) {
      this.msg.error('治理设置获取失败：' + (e as Error).message);
    }
    this.loading = false;
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
        Text('系统设置 · 治理')
          .fontSize(17)
          .fontWeight(FontWeight.Medium)
          .fontColor(this.sm.getColor('text_primary'))
          .layoutWeight(1)
          .textAlign(TextAlign.Center)
        Blank()
          .width(38)
      }
      .width('100%')
      .padding({ left: 12, right: 12, top: 6, bottom: 8 })

      Scroll() {
        Column() {
          Text('Agent 上限（治理，只读；写回在 PC 治理页）')
            .fontSize(12)
            .fontColor(this.sm.getColor('text_tertiary'))
            .padding({ left: 20, right: 20, bottom: 10 })

          Column() {
            if (this.rows.length === 0 && !this.loading) {
              Text(this.loading ? '加载中…' : '暂无治理键值')
                .fontSize(13)
                .fontColor(this.sm.getColor('text_tertiary'))
                .margin({ top: 30 })
            }
            ForEach(this.rows, (row: string[]) => {
              Row() {
                Text(row[0])
                  .fontSize(12.5)
                  .fontColor(this.sm.getColor('text_secondary'))
                  .layoutWeight(1)
                Text(row[1])
                  .fontSize(12.5)
                  .fontColor(this.sm.getColor('text_primary'))
                  .textAlign(TextAlign.End)
                  .constraintSize({ maxWidth: '55%' })
                  .maxLines(2)
              }
              .width('100%')
              .padding({ top: 8, bottom: 8 })
              .border({ width: { bottom: 1 }, color: this.sm.getColor('divider') })
            }, (row: string[]) => row[0])
          }
          .width('calc(100% - 40vp)')
          .padding(14)
          .borderRadius(16)
          .backgroundColor(this.sm.getColor('surface'))
          .border({ width: 1, color: this.sm.getColor('border') })
          .margin({ left: 20, right: 20 })
        }
        .width('100%')
      }
      .layoutWeight(1)
      .scrollBar(BarState.Off)
      .width('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor(this.sm.getColor('background'))
  }
}
